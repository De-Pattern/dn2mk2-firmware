"""Run the compiled guard AND stock USB writer/allocator/submit under CFV4E.

MMIO is a memory model, not hardware timing. No stock function is replaced by a
success stub. Explicitly bound instruction counts catch accidental device waits.
"""
import struct
import json
from pathlib import Path

import pytest

from dnfw.waverider import pages
from .test_sidecar_pages import compiled_runtime


@pytest.fixture
def usb(compiled_runtime):
    uc = pytest.importorskip("unicorn")
    from unicorn import m68k_const as reg
    stock, built = compiled_runtime
    cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
    for address, size in ((0x40000000, 0x400000), (pages.C_LOAD, pages.C_SPAN),
                          (0x4058E000, 0x1000), (0x44647000, 0x1000), (0x445EF000, 0x1000),
                          (0x4664A000, 0x2000), (0x80000000, 0x10000),
                          (0x4E6C4000, 0x1000), (0xFC0B0000, 0x1000),
                          (0x46A00000, 0x10000)):
        cpu.mem_map(address, size)
    cpu.mem_write(0x40000400, built["content"])
    cpu.mem_write(pages.C_LOAD, built["c_chunk"]["code"])
    for v in range(16):
        sound = 0x46A09001 + 1163 * v
        cpu.mem_write(0x800052A8 + 4 * v, struct.pack('>I', sound))
        cpu.mem_write(sound + 0xde, bytes([21]))
    def put(address, value): cpu.mem_write(address, struct.pack(">I", value))
    def get(address): return struct.unpack(">I", cpu.mem_read(address, 4))[0]
    stop, sp, packet, descriptor = 0x46A08000, 0x46A04000, 0x46A01000, 0x46A03000
    wire = bytes([0xF0, 0x7D, 0x44, 0x32, 1, 1] + list(range(43)) + [0xF7])
    cpu.mem_write(packet, wire)
    cpu.mem_write(0x4E6C4000, b"\xA5" * 4096)
    for address, value in ((0x4664ACDC, 0x445E6764), (0x446478D0, 1),
                           (0x4058E220, 1), (0xFC0B01C4, 1),
                           (0x4058E364, descriptor), (0x4058E228, 4092)):
        put(address, value)
    visited = []
    counts = {"masked": 0, "sr": 0x2000}
    def trace(cpu, address, size, user):
        visited.append(address)
        # Infer the interrupt mask from executed SR writes. Reading SR inside
        # every Unicorn instruction hook changed the sender's control flow on
        # this runtime; don't use an intrusive tracer for admission checks.
        if counts["sr"] & 0x0700 == 0x0700: counts["masked"] += 1
        op = struct.unpack(">H", cpu.mem_read(address, 2))[0]
        if op == 0x46FC:
            counts["sr"] = struct.unpack(">H", cpu.mem_read(address + 2, 2))[0]
        elif 0x46C0 <= op <= 0x46C7:
            counts["sr"] = cpu.reg_read(reg.UC_M68K_REG_D0 + op - 0x46C0)
    cpu.hook_add(uc.UC_HOOK_CODE, trace)
    def call(name, *args, sr=0x2000):
        visited.clear()
        counts["masked"] = 0
        counts["sr"] = sr
        cpu.mem_write(sp, struct.pack(">" + "I" * (1 + len(args)), stop, *args))
        cpu.reg_write(reg.UC_M68K_REG_SR, sr)
        cpu.reg_write(reg.UC_M68K_REG_A7, sp)
        # Full sixteen-voice capture uses its capture fixture's bound; USB
        # admission/submit retain the smaller no-wait budget below.
        cpu.emu_start(built["layout"][name] if isinstance(name, str) else name, stop,
                      count=200000 if name == 'sc_capture' else 30000)
        assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop, "USB path waited or exceeded its instruction bound"
        assert cpu.reg_read(reg.UC_M68K_REG_SR) & 0x2700 == sr & 0x2700
        return cpu.reg_read(reg.UC_M68K_REG_D0)
    def send(sr=0x2000, size=50): return call("sc_usb_try", packet, size, sr=sr)
    send.counts = counts
    return cpu, put, get, send, visited, wire, descriptor, call, built["layout"]


@pytest.mark.parametrize('wire_size',[50,52])
def test_actual_stock_usb_writer_publishes_complete_packet_without_wrap(usb,wire_size):
    cpu, put, get, send, visited, wire, descriptor, _, _ = usb
    if wire_size==52:
        wire=wire[:-1]+bytes(2)+b'\xf7';cpu.mem_write(0x46A01000,wire)
    usb_size=4*((wire_size+2)//3)
    assert send(size=wire_size) == 1
    assert get(0x4058E224) == usb_size and get(0x4058E228) == usb_size
    assert get(0x4664ADE4) == 0  # mutex released
    assert get(0x4058E364) == 0  # the single prechecked descriptor was used
    assert get(descriptor + 8) == 0x4E6C4000
    assert get(descriptor + 32) == usb_size
    assert get(descriptor + 36) == get(descriptor + 40) == 0x400041A8
    assert get(0xFC0B01B0) == 0x20000  # stock endpoint-5 prime
    expected = bytearray()
    for i in range(0, len(wire), 3):
        group = wire[i:i + 3]
        expected.extend(bytes((4 if i + 3 < len(wire) else 4 + len(group),)) + group + bytes(3 - len(group)))
    assert bytes(cpu.mem_read(0x4E6C4000, usb_size)) == bytes(expected)
    assert bytes(cpu.mem_read(0x4E6C4000+usb_size,4096-usb_size)) == b"\xA5" * (4096-usb_size)
    for routine in (0x40001680, 0x40004734, 0x40005764, 0x40005A86, 0x400016D2):
        assert routine in visited  # actual stock code, not mocked success
    assert 0x4000141A not in visited  # descriptor/event wait never entered
    assert len(visited) < 5000
    Path("out/sidecar-usb-execution.json").write_text(json.dumps({
        "scope": "actual compiled guard and stock routines; modeled MMIO, not hardware timing",
        "cold_empty_endpoint_instructions": len(visited),
        "cold_empty_endpoint_interrupt_masked_instructions": send.counts["masked"],
        "wire_bytes": wire_size, "usb_midi_bytes": usb_size,
    }, indent=2) + "\n")
    # No completion yet: a second event is retried without touching in-flight DMA.
    before = bytes(cpu.mem_read(0x4E6C4000, 4096))
    assert send(size=wire_size) == 0 and 0x40004734 not in visited
    assert bytes(cpu.mem_read(0x4E6C4000, 4096)) == before


@pytest.mark.parametrize("address,value", [
    (0x4664ADE4, 0x1234), # lock belongs to another task
    (0x446478D0, 0), (0x4058E220, 0), (0xFC0B01C4, 0), # disabled/unplugged
    (0x4664AF0C, 32), # endpoint disabled
    (0x4058E224, 4), # ring not empty
    (0x4058E210, 0xF0), # another SysEx message is incomplete
    (0x4058E364, 0), # descriptor pool empty
    (0x46A03004, 0x80), # free-list head still active in hardware
    (0x4664ACDC, 0x1234), # wrong task
])
def test_busy_or_disconnected_usb_is_retry_without_wait_or_write(usb, address, value):
    cpu, put, get, send, visited, _, _, _, _ = usb
    put(address, value)
    assert send() == 0
    assert 0x40004734 not in visited and 0x4000141A not in visited
    assert get(0x4664ADE4) == (value if address == 0x4664ADE4 else 0)
    assert bytes(cpu.mem_read(0x4E6C4000, 4096)) == b"\xA5" * 4096
    assert len(visited) < 1000


def test_interrupt_context_cannot_send(usb):
    _, _, get, send, visited, _, _, _, _ = usb
    assert send(sr=0x2700) == 0
    assert 0x40001680 not in visited and 0x40004734 not in visited
    assert get(0x4058E224) == 0


def test_generic_packet_uses_one_stock_descriptor_and_retries_without_dma_changes(usb):
    cpu, put, get, send, visited, _, descriptor, _, _ = usb
    wire = bytes([0xf0, 0x7d, 0x44, 0x32, 2, 1] + list(range(91)) + [0xf7])
    cpu.mem_write(0x46A01000, wire)
    for size in (0, 49, 51, 97, 99, 0xffffffff):
        assert send(size=size) == 0 and 0x40004734 not in visited
    put(descriptor + 4, 0x80)
    assert send(size=98) == 0 and 0x40004734 not in visited
    put(descriptor + 4, 0)
    assert send(size=98) == 1
    assert get(0x4058E224) == get(0x4058E228) == get(descriptor + 32) == 132
    expected = bytearray()
    for i in range(0, 98, 3):
        group = wire[i:i + 3]
        expected.extend(bytes((4 if i + 3 < 98 else 4 + len(group),)) + group + bytes(3 - len(group)))
    assert bytes(cpu.mem_read(0x4E6C4000, 132)) == bytes(expected)
    assert bytes(cpu.mem_read(0x4E6C4084, 4096 - 132)) == b'\xa5' * (4096 - 132)
    assert 0x4000141A not in visited and len(visited) < 7000
    Path('out/sidecar-usb-generic.json').write_text(json.dumps(dict(
        scope='Compiled guard and actual stock USB routines; modeled MMIO, not hardware timing.',
        wire_bytes=98, usb_midi_bytes=132, instructions=len(visited),
        masked_instructions=send.counts['masked']), indent=2) + '\n')
    before = bytes(cpu.mem_read(0x4E6C4000, 4096))
    assert send(size=98) == 0 and 0x40004734 not in visited
    assert bytes(cpu.mem_read(0x4E6C4000, 4096)) == before


def test_stock_endpoint_tripwire_retry_is_bounded(usb):
    import unicorn as uc
    cpu, put, get, send, visited, _, _, _, _ = usb
    # A separate short-message transfer can occupy this USB endpoint without
    # using the long-message ring. Exercise stock's 1000-attempt tripwire limit.
    other = 0x46A03200
    put(0x800000C0 + 48, other); put(0x800000C0 + 52, other)
    put(other, 0xDEAD0001); put(other + 4, 0x00048080)
    attempts = []
    def miss(cpu, address, size, user):
        attempts.append(1); put(0xFC0B0140, 0)
    hook = cpu.hook_add(uc.UC_HOOK_CODE, miss, begin=0x40005B82, end=0x40005B82)
    assert send() == 1 and len(attempts) == 1000
    assert len(visited) < 30000 and get(0x4664ADE4) == 0
    cpu.hook_del(hook)
    path = Path("out/sidecar-usb-execution.json")
    report = json.loads(path.read_text()) if path.exists() else {}
    report.update(tripwire_limit_instructions=len(visited),
                  tripwire_limit_interrupt_masked_instructions=send.counts["masked"])
    path.write_text(json.dumps(report, indent=2) + "\n")


def test_midi_service_is_inactive_until_enabled_then_sends_reset(usb):
    cpu, put, get, _, visited, _, _, call, layout = usb
    call("sc_midi_poll")
    assert 0x40004734 not in visited and get(layout["sc_sent"]) == 0
    call("sc_set_link", 1)
    call("sc_midi_poll")
    assert get(layout["sc_sent"]) == 1 and get(0x4058E224) == 68
    # Unpack the stock USB MIDI event words, then the native packet.
    usb_bytes = bytes(cpu.mem_read(0x4E6C4000, 68))
    packet = b"".join(usb_bytes[i + 1:i + 1 + (3 if usb_bytes[i] == 4 else usb_bytes[i] - 4)]
                      for i in range(0, 68, 4))
    assert len(packet) == 50
    raw = bytearray(); offset = 6
    while len(raw) < 37:
        mask = packet[offset]; offset += 1
        for bit in range(min(7, 37 - len(raw))):
            raw.append(packet[offset] | ((mask >> bit & 1) << 7)); offset += 1
    assert raw[8] == 16 and raw[:2] == b"\0\0"  # initial RESET, sequence 0
    call("sc_set_link", 0)
    call("sc_midi_poll")
    assert 0x40004734 not in visited


def test_frame_wakes_ready_midi_task_without_accumulating_signals(usb):
    from .test_sidecar_capture import frame_for
    cpu, put, get, _, visited, _, _, call, _ = usb
    event, frame, tracks = 0x445EF3B8, 0x46A00000, 0x46A02000
    call("sc_set_link", 1)
    cpu.mem_write(frame, struct.pack(">1374H", *frame_for()))
    cpu.mem_write(tracks, struct.pack(">16I", *range(16)))
    call("sc_capture", frame, tracks, 1, 1)
    assert get(event) == 0 and 0x4000148C not in visited  # task not ready yet
    put(event, 1)
    call("sc_midi_wait", event) # actual stock event wait consumes existing signal
    assert get(event) == 0 and 0x4000141A in visited
    call("sc_capture", frame, tracks, 2, 1)
    assert get(event) == 1 and 0x4000148C in visited
    call("sc_capture", frame, tracks, 3, 1)
    assert get(event) == 1 and 0x4000148C not in visited


def test_queue_pass_hook_preserves_stock_live_registers(usb):
    from unicorn import m68k_const as reg
    cpu, _, _, _, _, _, _, call, _ = usb
    registers = [reg.UC_M68K_REG_D0, reg.UC_M68K_REG_D1, reg.UC_M68K_REG_D2,
                 reg.UC_M68K_REG_A0, reg.UC_M68K_REG_A1, reg.UC_M68K_REG_A2,
                 reg.UC_M68K_REG_A6]
    for i, r in enumerate(registers): cpu.reg_write(r, 0x12345000 + i)
    call("sc_midi_poll_hook")
    for i, r in enumerate(registers): assert cpu.reg_read(r) == 0x12345000 + i
    assert cpu.reg_read(reg.UC_M68K_REG_A5) == 0x40001876


def session_packet(command=0, token=0x1234567, track=2):
    return bytes([0xF0, 0x7D, 0x44, 0x32, 1, 2, command,
                  (token >> 21) & 127, (token >> 14) & 127,
                  (token >> 7) & 127, token & 127, track, 1] + [0] * 36 + [0xF7])


@pytest.fixture
def session(usb):
    cpu, put, get, _, visited, _, descriptor, call, layout = usb
    def request(packet=None, source=2, router=False):
        packet = session_packet() if packet is None else packet
        cpu.mem_write(0x46A01000, packet)
        return call(0x4012166E if router else "sc_rx", 0x46A01000, len(packet), source)
    def packet_out():
        assert get(0x4058E224) == 68
        data = bytes(cpu.mem_read(0x4E6C4000, 68))
        return b"".join(data[i + 1:i + 1 + (3 if data[i] == 4 else data[i] - 4)]
                        for i in range(0, 68, 4))
    def complete():
        # Model completion to exercise the next task pass. This does not test
        # hardware DMA/completion interrupts or replace the sender's routines.
        put(0x4058E224, 0); put(0x4058E364, descriptor); put(descriptor + 4, 0)
        put(0x800000C0 + 48, 0); put(0x800000C0 + 52, 0)
    return request, packet_out, complete


def test_router_accepts_session_before_events_and_keeps_sampler_route(usb, session):
    cpu, put, get, _, visited, _, _, call, layout = usb
    request, packet_out, complete = session
    request(router=True)
    assert layout["sc_rx"] in visited and layout["smp_rx"] in visited
    assert 0x40004734 not in visited  # parsing never sends
    call("sc_midi_poll")
    assert packet_out() == session_packet(command=1)
    assert get(layout["sc_sent"]) == 0  # ACK precedes even initial RESET
    Path("out/sidecar-native-ack.bin").write_bytes(packet_out())
    complete(); call("sc_midi_poll")
    assert packet_out()[5] == 1 and get(layout["sc_sent"]) == 1
    complete()
    # Repeated HELLO/KEEP for this live session acknowledges without restarting.
    for command in (0, 2):
        assert request(session_packet(command)) == 1
        call("sc_midi_poll"); assert packet_out() == session_packet(1)
        assert get(layout["sc_sent"]) == 1
        complete()
    assert request(session_packet(3)) == 1
    call("sc_midi_poll"); assert get(0x4058E224) == 0


@pytest.mark.parametrize("kind", ["din", "source", "short", "long", "version", "header",
                                  "opcode", "ack", "track", "engine", "nonce", "reserved",
                                  "highbit", "end", "keep_before_hello", "close_before_hello"])
def test_session_rejects_malformed_or_unestablished_request(usb, session, kind):
    _, _, get, _, visited, _, _, call, _ = usb
    request, _, _ = session
    p = bytearray(session_packet()); source = 2
    if kind == "din": source = 8
    elif kind == "source": source = 0
    elif kind == "short": p = p[:-1]
    elif kind == "long": p += b"\0"
    elif kind == "version": p[4] = 2
    elif kind == "header": p[2] = 0x52
    elif kind == "opcode": p[6] = 4
    elif kind == "ack": p[6] = 1
    elif kind == "track": p[11] = 17
    elif kind == "engine": p[12] = 2
    elif kind == "nonce": p[7:11] = bytes(4)
    elif kind == "reserved": p[40] = 1
    elif kind == "highbit": p[9] |= 0x80
    elif kind == "end": p[-1] = 0
    elif kind == "keep_before_hello": p[6] = 2
    elif kind == "close_before_hello": p[6] = 3
    assert request(bytes(p), source) == 0
    call("sc_midi_poll")
    assert 0x40004734 not in visited and get(0x4058E224) == 0


@pytest.mark.parametrize("start", [0, 0xFFFFFC00])
def test_lease_expires_across_frame_counter_wrap_and_cannot_be_revived_by_keep(usb, session, start):
    _, put, get, _, _, _, _, call, _ = usb
    request, packet_out, complete = session
    put(0x4058E8D4, start)
    assert request() == 1
    put(0x4058E8D4, (start + 2999) & 0xFFFFFFFF)
    assert request(session_packet(2)) == 1  # renew before the deadline
    put(0x4058E8D4, (start + 5999) & 0xFFFFFFFF)
    assert request(session_packet(2)) == 0
    call("sc_midi_poll"); assert get(0x4058E224) == 0
    assert request(session_packet()) == 1  # explicit HELLO starts afresh
    call("sc_midi_poll"); assert packet_out() == session_packet(1)
    complete()
    put(0x446478D0, 0)
    call("sc_midi_poll"); assert get(0x4058E224) == 0  # disconnect discards held RESET
    put(0x446478D0, 1)
    assert request(session_packet(2)) == 0


def test_new_session_discards_unsent_history_and_ignores_old_close(usb, session):
    _, put, get, _, _, _, _, call, layout = usb
    request, packet_out, complete = session
    assert request() == 1
    call("sc_midi_poll"); assert packet_out() == session_packet(1)
    # Old ACK is in flight, old RESET is held. New ACK must be next, then new RESET.
    assert request(session_packet(token=7, track=9), source=4) == 1
    assert request(session_packet(3)) == 0
    assert request(session_packet(2, token=7, track=8)) == 0
    complete(); call("sc_midi_poll")
    assert packet_out() == session_packet(1, token=7, track=9)
    assert get(layout["sc_sent"]) == 0
    complete(); call("sc_midi_poll")
    assert packet_out()[5] == 1 and get(layout["sc_sent"]) == 1


def test_session_captures_only_the_selected_track(usb, session):
    from .test_sidecar_capture import frame_for
    cpu, put, _, _, _, _, _, call, _ = usb
    request, _, complete = session
    request(session_packet(track=7))
    call("sc_midi_poll"); complete(); call("sc_midi_poll"); complete()
    frame, tracks, event = 0x46A00000, 0x46A02000, 0x46A02400
    f = frame_for(); f[17] = 1 << 2
    cpu.mem_write(frame, struct.pack(">1374H", *f))
    cpu.mem_write(tracks, struct.pack(">16I", *range(16)))
    call("sc_capture", frame, tracks, 1, 1)
    assert call("sc_pop", event) == 0
    # Same allocated voice now belongs to selected track 7.
    put(tracks + 8, 7)
    cpu.mem_write(frame, struct.pack(">1374H", *f))
    call("sc_capture", frame, tracks, 2, 1)
    assert call("sc_pop", event) == 1
    assert bytes(cpu.mem_read(event + 44, 3)) == bytes([2, 7, 3])


def test_eight_track_session_keeps_parts_and_locks_independent(usb, session):
    from .test_sidecar_capture import frame_for
    cpu, _, get, _, _, _, _, call, layout = usb
    request, packet_out, complete = session
    assert request(session_packet(track=16)) == 1
    call("sc_midi_poll"); assert packet_out() == session_packet(1, track=16)
    complete(); call("sc_midi_poll"); complete()  # initial RESET
    frame, tracks, event = 0x46A00000, 0x46A02000, 0x46A02400
    owners = list(reversed(range(16)))
    cpu.mem_write(tracks, struct.pack(">16I", *owners))

    def feed(tick, changed=None, on=False):
        f = [0] * 1374
        for v in range(16):
            source = frame_for(v)
            for offset in (1, 26, 58, 74): f[offset + v] = source[offset + v]
            for slot in range(25, 73):
                f[84 + 73 * v + slot] = source[84 + 73 * v + slot]
            f[84 + 73 * v + 48] = (owners[v] << 8) + (tick if owners[v] == changed else 0)
        f[17] = 0xFFFF if on else 0
        cpu.mem_write(frame, struct.pack(">1374H", *f))
        call("sc_capture", frame, tracks, tick, 1)
        return struct.unpack(">1374H", bytes(cpu.mem_read(frame, 2748)))

    def drain():
        rows = []
        while call("sc_pop", event):
            raw = bytes(cpu.mem_read(event, 80))
            rows.append((raw[45], raw[44], raw[46], struct.unpack_from(">H", raw, 12)[0]))
        return rows

    feed(1, on=True)
    rows = drain()
    assert sorted(rows) == [(part, 15 - part, 3, part << 8) for part in range(8)]
    # Hundreds of edits before a consumer pass coalesce independently per owner.
    for tick in range(2, 202): feed(tick, changed=4)
    assert drain() == [(4, 11, 1, (4 << 8) + 201)]
    assert get(layout["sc_overflows"]) == 0
    # Only defined return modes can be negotiated.
    bad = bytearray(session_packet(track=16)); bad[13] = 2
    assert request(bytes(bad)) == 0
    native = bytearray(session_packet(track=16)); native[13] = 1
    assert request(bytes(native)) == 1
    call("sc_midi_poll")
    ack = bytearray(native); ack[6] = 1
    assert packet_out() == bytes(ack)
    complete(); call("sc_midi_poll"); complete()
    after = feed(203, on=True)
    assert after[17] == 0xFF00  # only the eight subscribed allocated owners
    for v, part in enumerate(owners):
        assert after[74 + v] == 21
        assert after[84 + 73 * v + 25] == 0x5380 | (part if part < 8 else 15)
        assert after[58 + v] == (127 << 8 if part < 8 else 0)
    drain()
    # A producer fault silences every owner while retaining native lane mode;
    # stale dry audio must never become an unfiltered MAIN/FX bypass.
    for tick in range(204, 210): after = feed(tick, on=True)
    assert get(layout["sc_overflows"]) > 0
    assert after[17] == 0
    assert all(after[84 + 73 * v + 25] == 0x538F for v in range(16))


@pytest.mark.parametrize('generic',[False,True])
def test_live_session_drops_old_voice_smoothing_but_keeps_note_edges(usb,session,generic):
    from dnfw.sidecar import machines as sc
    cpu,put,get,_,_,_,_,call,layout=usb
    request,_,complete=session
    assert request(session_packet(track=16))==1
    call('sc_midi_poll');complete();call('sc_midi_poll');complete()
    frame,tracks,event,ident=0x46a00000,0x46a02000,0x46a02400,0x46a02500
    cpu.mem_write(tracks,bytes(64)) # sixteen allocations belonging to track 1
    if generic:
        cpu.mem_write(ident,b'mega.perkons'.ljust(32,b'\0'))
        for v in range(16):assert call('sc_sound_store',0x46a09001+1163*v,ident)==1
    f=[0]*1374
    for v in range(16):
        f[74+v],f[1+v],f[26+v],f[58+v]=sc.TYPE,60<<8,100<<8,127<<8
    def feed(tick,on=0,off=0):
        f[17],f[18]=on,off
        for v in range(16):f[84+73*v+sc.RECORDS[0][1]]=tick*17+v
        cpu.mem_write(frame,struct.pack('>1374H',*f))
        call('sc_capture',frame,tracks,tick,1)
    def drain():
        rows=[]
        while call('sc_pop',event):
            raw=bytes(cpu.mem_read(event,80))
            rows.append((raw[44],raw[46],struct.unpack_from('>H',raw,4)[0],
                         struct.unpack_from('>H',raw,12)[0]))
        return rows
    feed(1,on=1<<2);rows=drain()
    assert rows[0][:2]==(2,3)
    assert all(r[0]==2 for r in rows)
    for tick in range(2,12):
        feed(tick);updates=drain();rows+=updates
        assert len(updates)==1 and updates[0][0:2]==(2,1)
        assert updates[0][3]==tick*17+2
    # New owner, old-owner OFF, then smoothed state: keep edges in capture order.
    feed(12,on=1<<5);feed(13,off=1<<2);feed(14)
    edges=drain();rows+=edges
    assert [r[:2] for r in edges]==[(5,3),(2,5),(5,1)]
    assert edges[-1][3]==14*17+5
    assert [r[2] for r in rows]==list(range(1,len(rows)+1)) # RESET was sequence zero
    assert get(layout['sc_overflows'])==0
    if generic:
        # Identity edits to an obsolete allocation are deferred, but its next
        # ON must capture the new identity before the note can reach the Pi.
        cpu.mem_write(ident,b'demo.tone'.ljust(32,b'\0'))
        assert call('sc_sound_store',0x46a09001+1163*2,ident)==1
        feed(15);assert [r[:2] for r in drain()]==[(5,1)]
        feed(16,on=1<<2)
        assert call('sc_pop',event)==1
        assert bytes(cpu.mem_read(event+44,3))==bytes([2,0,8])
        assert call('sc_pop',event)==1
        assert bytes(cpu.mem_read(event+44,3))==bytes([2,0,3])
        assert bytes(cpu.mem_read(event+48,32)).rstrip(b'\0')==b'demo.tone'
        assert not drain()


def test_native_owner_preserves_complete_processing_frame(usb, session):
    from .test_sidecar_capture import frame_for
    cpu, _, _, _, _, _, _, call, _ = usb
    request, _, complete = session
    packet = bytearray(session_packet(track=2)); packet[13] = 1
    assert request(bytes(packet)) == 1
    call("sc_midi_poll"); complete(); call("sc_midi_poll"); complete()  # ACK and initial RESET
    frame, tracks = 0x46A00000, 0x46A02000
    cpu.mem_write(tracks, struct.pack(">16I", *range(16)))
    original = frame_for(2)
    # Distinct values throughout the record include filter, AMP, pan and sends.
    for slot in range(25, 93): original[84 + 73 * 2 + slot] = 1000 + slot * 37
    for tick, edge in enumerate((17, 18), 1):
        f = original.copy(); f[edge] = 1 << 2
        cpu.mem_write(frame, struct.pack(">1374H", *f))
        call("sc_capture", frame, tracks, tick, 1)
        expected = f.copy(); expected[84 + 73 * 2 + 25] = 0x5380
        assert struct.unpack(">1374H", bytes(cpu.mem_read(frame, 2748))) == tuple(expected)


def test_idle_frame_wakes_task_to_expire_session(usb, session):
    cpu, put, get, _, visited, _, _, call, _ = usb
    request, _, complete = session
    request(); call("sc_midi_poll"); complete(); call("sc_midi_poll"); complete()
    event = 0x445EF3B8
    put(event, 1); call("sc_midi_wait", event)
    # No pending events, ACK or held packet; only the lease deadline can wake it.
    put(0x4058E8D4, 3000)
    cpu.mem_write(0x46A00000, bytes(2748))
    cpu.mem_write(0x46A02000, struct.pack(">16I", *range(16)))
    call("sc_capture", 0x46A00000, 0x46A02000, 3000, 0)
    assert get(event) == 1 and 0x4000148C in visited
    call("sc_midi_poll"); assert get(0x4058E224) == 0
    assert request(session_packet(2)) == 0


def test_unrelated_keep_does_not_extend_lease(usb, session):
    _, put, _, _, _, _, _, _, _ = usb
    request, _, _ = session
    assert request() == 1
    put(0x4058E8D4, 2999)
    assert request(session_packet(2, token=77)) == 0
    put(0x4058E8D4, 3000)
    assert request(session_packet(2)) == 0
