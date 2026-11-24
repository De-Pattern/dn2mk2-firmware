"""Execute the actual compiled native frame capture/queue, without device I/O."""
import struct
from pathlib import Path

import pytest

from dnfw.sidecar import machines as sc
from dnfw.waverider import pages
from .test_sidecar_pages import compiled_runtime  # shared real compiler fixture


@pytest.fixture
def capture(compiled_runtime):
    uc = pytest.importorskip("unicorn")
    from unicorn import m68k_const as reg

    _, built = compiled_runtime
    cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
    cpu.mem_map(pages.C_LOAD, pages.C_SPAN)
    cpu.mem_write(pages.C_LOAD, built["c_chunk"]["code"])
    cpu.mem_map(0x46A00000, 0x10000)
    cpu.mem_map(0x80005000, 0x1000)
    for v in range(16):
        sound = 0x46A09001 + 1163 * v
        cpu.mem_write(0x800052A8 + 4 * v, struct.pack('>I', sound))
        cpu.mem_write(sound + 0xde, bytes([sc.TYPE]))
    stop, sp, frame, owners, event = (0x46A08000, 0x46A04000, 0x46A00000, 0x46A01000, 0x46A02000)

    def call(name, *args):
        cpu.mem_write(sp, struct.pack(">" + "I" * (len(args) + 1), stop, *args))
        cpu.reg_write(reg.UC_M68K_REG_SR, 0x2000)
        cpu.reg_write(reg.UC_M68K_REG_A7, sp)
        cpu.emu_start(built["layout"][name], stop, count=200000)
        assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop
        return cpu.reg_read(reg.UC_M68K_REG_D0)

    def feed(values, tracks=None, tick=1, playing=1):
        cpu.mem_write(frame, struct.pack(">1374H", *values))
        cpu.mem_write(owners, struct.pack(">16I", *(tracks if tracks is not None else range(16))))
        call("sc_capture", frame, owners, tick, playing)
        return list(struct.unpack(">1374H", cpu.mem_read(frame, 2748)))

    def pop():
        if not call("sc_pop", event): return None
        row = struct.unpack(">I20H4B32s", cpu.mem_read(event, 80))
        result = dict(tick=row[0], sequence=row[1], note=row[2], velocity=row[3],
                      level=row[4], params=row[5:21] if row[24] else row[5:16],
                      voice=row[21], track=row[22], flags=row[23])
        if row[24]: result['engine'] = row[25].split(b'\0')[0].decode()
        return result

    def counter(name):
        return struct.unpack(">I", cpu.mem_read(built["layout"][name], 4))[0]

    def encode(row=None, capacity=50):
        if row is not None:
            cpu.mem_write(event, struct.pack(">I20H4B32s", *row[:16], *([0] * 5), *row[16:], bytes(32)))
        packet = event + 128
        cpu.mem_write(packet, b"\xA5" * 64)
        n = call("sc_encode", event, packet, capacity)
        return n, bytes(cpu.mem_read(packet, 64))

    feed.cpu, feed.call, feed.event = cpu, call, event
    return feed, pop, counter, encode


def frame_for(voice=2):
    f = [0] * 1374
    f[74 + voice] = sc.TYPE
    f[1 + voice] = 60 << 8
    f[26 + voice] = 100 << 8
    f[58 + voice] = 127 << 8
    for i, (_, slot) in enumerate(sc.RECORDS):
        f[84 + 73 * voice + slot] = (i * 10 << 8) + i  # fractional bits retained
    for slot in (86, 87, 88): f[84 + 73 * voice + slot] = 12345
    return f


def test_atomic_trigger_snapshot_and_internal_voice_suppression(capture):
    feed, pop, _, _ = capture
    f = frame_for()
    f[17] = 1 << 2
    after = feed(f, tick=123)
    e = pop()
    assert e == dict(tick=123, sequence=0, note=60 << 8, velocity=100 << 8,
                     level=127 << 8, params=tuple((i * 10 << 8) + i for i in range(11)),
                     voice=2, track=2, flags=3)
    assert pop() is None
    expected = list(f)
    expected[74 + 2], expected[58 + 2] = 21, 0
    expected[84 + 73 * 2 + 25] = 0x530F  # explicit legacy descriptor
    expected[17], expected[18] = 0, 1 << 2
    for s in (86, 87, 88): expected[84 + 73 * 2 + s] = 0
    assert after == expected  # every other frame word stays exactly unchanged


def test_params_retriggers_releases_mute_and_voice_reassignment(capture):
    feed, pop, _, _ = capture
    f = frame_for()
    feed(f); assert pop()["flags"] == 1
    feed(f, tick=2); assert pop() is None
    f[84 + 73 * 2 + sc.RECORDS[0][1]] += 1
    feed(f, tick=3); assert pop()["params"][0] == 1
    f[17] = f[18] = 1 << 2
    feed(f, tick=4); assert pop()["flags"] == 7
    feed(f, tick=5); assert pop()["flags"] == 7  # same note is still a retrigger
    f[17] = 0
    feed(f, tick=6); assert pop()["flags"] == 5
    f[18], f[60] = 0, 0
    feed(f, tick=7); assert pop()["flags"] == 9
    tracks = list(range(16)); tracks[2] = 7
    feed(f, tracks, tick=8)
    old, new = pop(), pop()
    assert (old["flags"], old["track"], new["track"]) == (8, 2, 7)
    assert pop() is None
    f[76] = 1
    feed(f, tracks, tick=9)
    assert pop()["flags"] == 8
    assert pop() is None


def test_overflow_resets_before_resynchronizing_and_keeps_internal_audio_suppressed(capture):
    feed, pop, counter, _ = capture
    f = frame_for(); f[17] = 1 << 2
    for tick in range(33): feed(f, tick=tick)
    assert counter("sc_overflows") == 1
    after = feed(f, tick=34)
    assert after[17] == 0 and after[76] == 21 and after[60] == 0
    assert counter("sc_overflows") == 1
    reset = pop()
    assert reset["flags"] == 16
    assert pop() is None
    f[17] = 0
    feed(f, tick=35)
    e = pop()
    assert e["flags"] == 1 and e["tick"] == 35
    assert e["sequence"] == (reset["sequence"] + 1) & 0xFFFF


def test_transport_stop_resets_once_but_live_notes_can_play_while_stopped(capture):
    feed, pop, _, _ = capture
    f = frame_for()
    feed(f, playing=1); assert pop()["flags"] == 1
    feed(f, tick=2, playing=0)
    assert pop()["flags"] == 16
    assert pop()["flags"] == 1
    feed(f, tick=3, playing=0); assert pop() is None
    f[17] = 1 << 2
    feed(f, tick=4, playing=0); assert pop()["flags"] == 3


def test_dense_knob_updates_coalesce_without_cutting_the_voice(capture):
    feed, pop, counter, _ = capture
    f = [0] * 1374
    for v in range(16):
        f[74 + v], f[1 + v], f[26 + v], f[58 + v] = sc.TYPE, 60 << 8, 100 << 8, 127 << 8
    tracks = [0] * 16  # the hardware's allocated/free voices can share track 1
    f[17] = 1 << 2
    feed(f, tracks)
    events = [pop()]
    assert events[0]["flags"] == 3
    f[17] = 0
    for tick in range(1, 161):
        for v in range(16):
            f[84 + 73 * v + sc.RECORDS[0][1]] = tick * 17 + v
        feed(f, tracks, tick=tick)
        if tick % 4 == 0:
            e = pop()
            if e: events.append(e)
    while (e := pop()) is not None: events.append(e)
    assert counter("sc_overflows") == 0
    assert all(e["flags"] in (1, 3) for e in events)
    assert [e["sequence"] for e in events] == list(range(len(events)))
    latest = {e["voice"]: e for e in events}
    assert len(latest) == 16
    for v, e in latest.items():
        assert e["tick"] == 160 and e["params"][0] == 160 * 17 + v


def test_note_edges_keep_their_snapshots_before_latest_knob_state(capture):
    feed, pop, counter, _ = capture
    f = frame_for()
    pitch = 84 + 73 * 2 + sc.RECORDS[0][1]
    for tick, flags, value in [(1, 0, 100), (2, 3, 200), (3, 0, 300),
                               (4, 7, 400), (5, 0, 500)]:
        f[17] = (1 << 2) if flags & 2 else 0
        f[18] = (1 << 2) if flags & 4 else 0
        f[pitch] = value
        feed(f, tick=tick)
    events = [pop(), pop(), pop()]
    assert [(e["flags"], e["params"][0], e["sequence"]) for e in events] == [
        (3, 200, 0), (7, 400, 1), (1, 500, 2)]
    assert pop() is None and counter("sc_overflows") == 0


def test_stock_frame_is_untouched_and_exports_nothing(capture):
    feed, pop, _, _ = capture
    f = [i & 0xFFFF for i in range(1374)]
    for v in range(16): f[74 + v] = v % 5
    assert feed(f) == f
    assert pop() is None


def test_native_usb_codec_preserves_all_fraction_bits_and_buffer_bounds(capture):
    _, _, _, encode = capture
    params = tuple((i * 3333 + 171) & 0xFFFF for i in range(11))
    row = (0x89ABCDEF, 0xFFFE, 0x3C80, 0x6481, 0x7F00, *params, 15, 14, 7, 0)
    n, packet = encode(row)
    assert n == 50 and packet[:6] == bytes((0xF0, 0x7D, 0x44, 0x32, 1, 1))
    assert packet[49] == 0xF7 and packet[50:] == b"\xA5" * 14
    assert all(b < 128 for b in packet[1:49])
    decoded = bytearray()
    pos = 6
    while len(decoded) < 37:
        mask = packet[pos]; pos += 1
        for bit in range(min(7, 37 - len(decoded))):
            decoded.append(packet[pos] | ((mask >> bit & 1) << 7)); pos += 1
    expected = struct.pack(">HIBBB14H", 0xFFFE, 0x89ABCDEF, 14, 15, 7,
                           0x3C80, 0x6481, 0x7F00, *params)
    assert bytes(decoded) == expected
    # Optional cross-repository interoperability input: generated by real
    # ColdFire instructions, not a second host implementation of the encoder.
    Path("out/sidecar-native-event.bin").write_bytes(packet[:n])
    n, packet = encode(row, capacity=49)
    assert n == 0 and packet == b"\xA5" * 64


def test_generic_capture_uses_allocated_sound_not_track_or_modulated_identity(capture):
    feed, pop, _, _ = capture
    cpu, call = feed.cpu, feed.call
    sound, identity = 0x46A09001 + 1163 * 2, 0x46A03000
    cpu.mem_write(identity, b'demo.bell'.ljust(32, b'\0'))
    assert call('sc_sound_store', sound, identity) == 1
    # The allocated voice belongs to a different track. The base kit sound is
    # deliberately absent; source identity must follow this sound-lock object.
    tracks = list(range(16)); tracks[2] = 7
    f = frame_for(); f[17] = 1 << 2
    slots = [s for _, s in sc.RECORDS] + list(range(25, 30))
    values = tuple(0x103 + i * 0x579 for i in range(16))
    for slot, value in zip(slots, values): f[84 + 73 * 2 + slot] = value
    # Bogus identity-like words in the rendered frame must not select an engine.
    for slot in [31, 33, 34, 37, 39, *range(50, 65)]: f[84 + 73 * 2 + slot] = 0xffff
    after = feed(f, tracks, tick=10)
    e = pop()
    assert (e['engine'], e['track'], e['params'], e['flags']) == ('demo.bell', 7, values, 3)
    assert after[84 + 73 * 2 + 25] == 0x530f  # route tag only AFTER P12 captured
    assert pop() is None
    # A switch on the same allocated voice kills the old engine before exposing
    # the next sound. Recall's STATE never fabricates an ON edge.
    cpu.mem_write(identity, b'demo.long-tone'.ljust(32, b'\0'))
    assert call('sc_sound_store', sound, identity) == 1
    f[17] = 0
    feed(f, tracks, tick=11)
    old, new = pop(), pop()
    assert (old['engine'], old['flags']) == ('demo.bell', 8)
    assert (new['engine'], new['flags']) == ('demo.long-tone', 1)
    assert pop() is None
    # Damaged metadata retires the current sound; it must not become Perkons.
    cpu.mem_write(sound + 20 + 2 * 39, b'\xff\xff')
    feed(f, tracks, tick=12)
    assert pop()['flags'] == 8
    assert pop() is None
    # Repairing the same object must invalidate the cached rejection.
    cpu.mem_write(identity, b'demo.bell'.ljust(32, b'\0'))
    assert call('sc_sound_store', sound, identity) == 1
    feed(f, tracks, tick=13)
    repaired = pop()
    assert (repaired['engine'], repaired['flags']) == ('demo.bell', 1)
    feed(f, tracks, tick=14)
    assert pop() is None


def test_tagging_existing_perkons_publishes_generic_snapshot_without_phantom_hit(capture):
    feed, pop, _, _ = capture
    f = frame_for(); feed(f)
    assert 'engine' not in pop()
    identity = 0x46A03000
    feed.cpu.mem_write(identity, b'mega.perkons'.ljust(32, b'\0'))
    assert feed.call('sc_sound_store', 0x46A09001 + 1163 * 2, identity) == 1
    feed(f, tick=2)
    e = pop()
    assert e['engine'] == 'mega.perkons' and e['flags'] == 1 and len(e['params']) == 16
    assert pop() is None


def test_compiled_generic_encoder_full_id_sixteen_words_and_no_partial_write(capture):
    feed, _, _, _ = capture
    cpu, call, event = feed.cpu, feed.call, feed.event
    packet = event + 128
    params = tuple((0x81ff * (i + 1)) & 0xffff for i in range(16))
    engine = b'demo.bell'.ljust(32, b'\0')
    row = struct.pack('>I20H4B32s', 0x89abcdef, 0xfffe, 0x3c80, 0x6481, 0x7f00,
                      *params, 15, 14, 7, 1, engine)
    cpu.mem_write(event, row)
    cpu.mem_write(packet, b'\xa5' * 112)
    assert call('sc_encode', event, packet, 98) == 98
    wire = bytes(cpu.mem_read(packet, 112))
    assert wire[:6] == bytes((0xf0, 0x7d, 0x44, 0x32, 2, 1))
    assert wire[97] == 0xf7 and wire[98:] == b'\xa5' * 14
    assert all(b < 128 for b in wire[1:97])
    raw = bytearray(); at = 6
    while len(raw) < 79:
        mask = wire[at]; at += 1
        for bit in range(min(7, 79 - len(raw))):
            raw.append(wire[at] | ((mask >> bit & 1) << 7)); at += 1
    assert bytes(raw) == struct.pack('>HIBBB19H32s', 0xfffe, 0x89abcdef, 14, 15, 7,
                                    0x3c80, 0x6481, 0x7f00, *params, engine)
    Path('out/sidecar-native-generic.bin').write_bytes(wire[:98])
    for capacity, offset, value in [(97, None, None), (98, 48, 0), (98, 46, 0),
                                    (98, 47, 2), (98, 45, 16), (98, 57, ord('/'))]:
        changed = bytearray(row)
        if offset is not None: changed[offset] = value
        cpu.mem_write(event, bytes(changed)); cpu.mem_write(packet, b'\xa5' * 112)
        assert call('sc_encode', event, packet, capacity) == 0
        assert bytes(cpu.mem_read(packet, 112)) == b'\xa5' * 112


def test_eight_generic_parts_capture_instruction_cost(capture):
    import json
    import unicorn as uc
    feed, pop, _, _ = capture
    cpu, call = feed.cpu, feed.call
    identity = 0x46A03000
    f = [0] * 1374
    for v in range(8):
        source = frame_for(v)
        for off in (1, 26, 58, 74): f[off + v] = source[off + v]
    feed(f)
    while pop() is not None: pass
    count = [0]
    def tick(*_): count[0] += 1
    hook = cpu.hook_add(uc.UC_HOOK_CODE, tick)
    cpu.ctl_flush_tb()  # previously translated blocks must also carry the new hook
    feed(f); legacy = count[0]
    cpu.hook_del(hook)
    for v in range(8):
        cpu.mem_write(identity, (b'demo.bell' if v % 2 else b'demo.long-tone').ljust(32, b'\0'))
        assert call('sc_sound_store', 0x46A09001 + 1163 * v, identity) == 1
    count[0] = 0; hook = cpu.hook_add(uc.UC_HOOK_CODE, tick)
    cpu.ctl_flush_tb()
    feed(f); cold = count[0]
    cpu.hook_del(hook)
    while pop() is not None: pass
    count[0] = 0; hook = cpu.hook_add(uc.UC_HOOK_CODE, tick)
    cpu.ctl_flush_tb()
    feed(f); warm = count[0]
    cpu.hook_del(hook)
    Path('out/sidecar-generic-capture-cost.json').write_text(json.dumps(dict(
        scope='Compiled capture instruction counts, eight parts; not measured hardware cycles or latency.',
        legacy_steady=legacy, generic_first=cold, generic_steady=warm), indent=2) + '\n')


def test_engine_edit_holds_only_its_track_until_complete(capture, compiled_runtime):
    feed, pop, _, _ = capture
    _, built = compiled_runtime
    cpu, call = feed.cpu, feed.call
    f = frame_for(2)
    other = frame_for(3)
    for offset in (1, 26, 58, 74): f[offset+3] = other[offset+3]
    f[17] = (1 << 2) | (1 << 3)
    feed(f)
    while pop() is not None: pass
    f[17] = 0
    cpu.mem_write(built['layout']['sc_edit_mask'], struct.pack('>I',1 << 2))
    f[84+73*2+48] = 0x7e00  # intermediate setter value; must never be exported
    f[84+73*3+48] = 0x4200
    feed(f)
    events=[]
    while (e:=pop()) is not None: events.append(e)
    assert len(events)==1 and events[0]['track']==3 and events[0]['params'][0]==0x4200
    ident=0x46a03000
    cpu.mem_write(ident,b'demo.bell'.ljust(32,b'\0'))
    assert call('sc_sound_store',0x46a09001+1163*2,ident)==1
    f[84+73*2+48] = 0x3300
    cpu.mem_write(built['layout']['sc_edit_mask'],bytes(4))
    feed(f)
    events=[]
    while (e:=pop()) is not None: events.append(e)
    assert len(events)==2 and events[0]['flags']==8
    assert events[1]['engine']=='demo.bell' and events[1]['params'][0]==0x3300
