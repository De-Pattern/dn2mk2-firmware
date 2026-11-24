"""Real ColdFire metadata client exchanging packets with the Pi's compiled server.

No device I/O. Original metadata-only fixtures; no private plugin or DSP dependency.
"""
import json
from functools import lru_cache
import os
from pathlib import Path
import struct
import subprocess
import pytest

from .test_sidecar_capture import capture
from .test_sidecar_pages import compiled_runtime

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = Path(os.environ.get('SIDECAR_BRIDGE_ROOT', ROOT.parent / 'sidecar-bridge-public')).resolve()


@pytest.fixture(scope='session')
@lru_cache(maxsize=1)
def ui_server():
    import sys
    opts = dict(cwd=SIDECAR, capture_output=True, text=True, check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    subprocess.run([sys.executable, 'tools/dn2/check_dn2.py', '--ui-only'], **opts)
    subprocess.run([sys.executable, 'tools/dn2/make_metadata_fixtures.py'], **opts)
    exe = SIDECAR / 'build/dn2/dn2_native_ui.exe'
    return exe if os.name == 'nt' else exe.with_suffix(''), opts


def test_compiled_metadata_transactions(capture, compiled_runtime, tmp_path, ui_server):
    feed, *_ = capture
    cpu, call = feed.cpu, feed.call
    from dnfw.sidecar import machines as sc
    from dnfw.waverider import pages
    from unicorn import m68k_const as reg
    stock, built = compiled_runtime
    for base, size in ((0x40000000, 0x400000), (0x42430000, 0x10000),
                       (0x4058e000, 0x1000), (pages.LOAD, 0x4000)):
        cpu.mem_map(base, size)
    cpu.mem_write(0x40000400, stock)
    cpu.mem_write(pages.LOAD, built['chunk']['code'])
    sound = 0x46a09001
    cpu.mem_write(0x800052a0, struct.pack('>I', sound - 52))
    cpu.mem_write(0x42431a6c, b'\0')
    # The fixture tuple is intentionally shared with the existing capture tests.
    exe, opts = ui_server
    request_file, reply_file = tmp_path / 'ask.bin', tmp_path / 'reply.bin'
    ident, packet = 0x46a06000, 0x46a06100
    token, now = 0x1234567, 200
    originals = {record: (bytes(cpu.mem_read(0x401f7f94 + 60 * record + 8, 16)),
                          bytes(cpu.mem_read(0x401f7f94 + 60 * record + 0x34, 4)))
                 for record, _ in sc.ALL_RECORDS}

    def want(engine):
        cpu.mem_write(ident, engine.encode().ljust(32, b'\0'))
        return call('sc_ui_want', ident)

    def ask(at=None):
        n = call('sc_ui_request', token, now if at is None else at, packet)
        return bytes(cpu.mem_read(packet, n))

    def answer(request, package):
        request_file.write_bytes(request)
        subprocess.run([str(exe), '--answer', str(request_file), str(reply_file), str(package)], **opts)
        return reply_file.read_bytes()

    def receive(reply):
        cpu.mem_write(packet, reply)
        return call('sc_ui_receive', packet, len(reply), now)

    count = 0
    revision_changed = False
    cases = [(SIDECAR / f'build/dn2/fixtures/{engine}.json',
              SIDECAR / f'build/dn2/fixtures/{engine}.rmp')
             for engine in ('bell', 'tone', 'noise')]
    public_demo = os.environ.get('SIDECAR_DEMO_PACKAGE')
    if public_demo:
        cases.append((SIDECAR / 'plugins/sc_snare/manifest.json', Path(public_demo)))
    tested_ids = []
    for manifest_file, package in cases:
        manifest = json.loads(manifest_file.read_text())
        tested_ids.append(manifest['id'])
        assert want(manifest['id']) == 1
        assert call('sc_sound_store', sound, ident) == 1
        call('sc_ui_follow')
        assert call('sc_ui_view') == 0  # previous engine's labels cannot leak
        prior = None
        while True:
            request = ask()
            assert len(request) == 50
            assert request[17:49].rstrip(b'\0').decode() == manifest['id']
            reply = answer(request, package)
            if not revision_changed and request[14:17] == bytes((0, 1, 0)):
                changed = bytearray(reply); changed[21] ^= 1
                assert receive(bytes(changed)) == 1
                assert call('sc_ui_publish') == 0 and call('sc_ui_view') == 0
                again = ask()
                assert again[14:17] == bytes(3) and again[10:14] != request[10:14]
                assert receive(reply) == 0
                revision_changed = True
                request = again
                reply = answer(request, package)
            # Partial/malformed/stale replies never publish or advance this request.
            assert receive(reply[:-1]) == 0
            stale = bytearray(reply); stale[13] ^= 1
            assert receive(bytes(stale)) == 0
            malformed = bytearray(reply); malformed[22] |= 128
            assert receive(bytes(malformed)) == 0
            if prior is not None:
                assert receive(prior) == 0
            assert ask(now + 149) == b''
            assert ask(now + 150) == request  # retry, unchanged correlation/identity
            now += 151
            assert receive(reply) == 1
            assert receive(reply) == 0  # duplicate cannot advance the next part
            count += 1
            assert call('sc_ui_view') == 0
            prior = reply
            if call('sc_ui_publish'):
                break
            now += 1
        view = call('sc_ui_view')
        assert view
        raw = bytes(cpu.mem_read(view, 5096))
        assert raw[8:40].rstrip(b'\0').decode() == manifest['id']
        assert raw[40:51].rstrip(b'\0').decode() == manifest['name']
        assert raw[56:70].rstrip(b'\0').decode() == manifest['page2_title']
        assert raw[70] == 1  # READY from the fixture provider
        # Actual emitted assembly dispatch returns the same generic records as the renderer.
        for page in (0, 1):
            sp, stop = 0x46a04000, 0x46a08000
            cpu.mem_write(sp, struct.pack('>6I', stop, 0x12345678, stop, sc.TYPE, page, 0))
            cpu.reg_write(reg.UC_M68K_REG_SR, 0x2000)
            cpu.reg_write(reg.UC_M68K_REG_A7, sp)
            cpu.emu_start(built['layout']['wr_page'], stop, count=200000)
            assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop
            assert cpu.reg_read(reg.UC_M68K_REG_D2) == 0x12345678
            descriptor = cpu.reg_read(reg.UC_M68K_REG_D0)
            fields = struct.unpack('>11I', cpu.mem_read(descriptor, 44))
            present = {k['p'] for k in manifest['knobs']}
            expected = tuple(record if page * 8 + i + 1 in present else 0
                             for i, record in enumerate(sc.GENERIC_PAGES[page]))
            assert fields[2:10] == expected and fields[10] == pages.TAG
            title = bytes(cpu.mem_read(fields[0], 32)).split(b'\0')[0].decode()
            assert title == (manifest['page2_title'] if page else manifest['name'])
        call('smp_formats', sc.KIND)
        for k, knob in enumerate(manifest['knobs']):
            offset = 72 + k * 314
            actual = raw[offset:offset + 314]
            assert actual[3:6] == bytes((knob.get('min', 0), knob.get('max', 127), knob['default']))
            assert actual[8:21].rstrip(b'\0').decode() == knob['long']
            assert actual[21:26].rstrip(b'\0').decode() == knob['short']
            names = knob.get('names', [])
            assert actual[6] == len(names)
            assert [actual[26 + i * 8:34 + i * 8].rstrip(b'\0').decode() for i in range(len(names))] == names
            record = 0x401f7f94 + 60 * sc.ALL_RECORDS[k][0]
            assert struct.unpack('>3I', cpu.mem_read(record + 8, 12)) == (
                knob.get('min', 0) << 8, knob.get('max', 127) << 8, knob['default'] << 8)
            formatter, = struct.unpack('>I', cpu.mem_read(record + 0x34, 4))
            for value in (0, 0x2aaa, 0x2aab, 0x7f00):
                sp, stop = 0x46a04000, 0x46a08000
                cpu.mem_write(sp, struct.pack('>3I', stop, value, packet))
                cpu.reg_write(reg.UC_M68K_REG_SR, 0x2000)
                cpu.reg_write(reg.UC_M68K_REG_A7, sp)
                cpu.emu_start(formatter, stop, count=10000)
                assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop
                text = bytes(cpu.mem_read(packet, 16)).split(b'\0')[0].decode()
                expected = names[value * len(names) // 32768] if names else str((value >> 8) - (64 if knob.get('text') == 'bipolar' else 0))
                assert text == expected
        assert ask() == b''
        # A refresh with an unchanged revision keeps the exact published buffer.
        now += 1500
        request = ask(); assert request[14:17] == bytes(3)
        assert receive(answer(request, package)) == 1
        assert call('sc_ui_publish') == 0 and call('sc_ui_view') == view
        assert bytes(cpu.mem_read(view, 5096)) == raw
        now += 1500
        request = ask()
        # Changing sessions rejects the old pending response and invalidates the cache.
        old = answer(request, package)
        token += 1
        call('sc_ui_session', token)
        assert receive(old) == 0 and call('sc_ui_view') == 0
        call('smp_formats', 0)
        for record, (ranges, formatter) in originals.items():
            assert bytes(cpu.mem_read(0x401f7f94 + 60 * record + 8, 16)) == ranges
            assert bytes(cpu.mem_read(0x401f7f94 + 60 * record + 0x34, 4)) == formatter
    report = {'scope': 'compiled ColdFire client and Pi metadata server; cached manifest fixtures, no hardware',
              'engines': tested_ids, 'responses': count,
              'checks': ['16 labels/ranges/defaults', 'all enum names', 'atomic publication',
                         'partial/malformed/duplicate/stale rejection', 'bounded retry', 'unchanged refresh', 'session change',
                         'native assembly page dispatch', 'native formatter values and manifest ranges',
                         'restart on descriptor revision change']}
    (ROOT / 'out/sidecar-ui-client.json').write_text(json.dumps(report, indent=2) + '\n')


def test_compiled_catalog_transactions(capture, tmp_path, ui_server):
    feed, *_ = capture
    cpu, call = feed.cpu, feed.call
    packet, token, now = 0x46a06100, 0x1234567, 0xfffffff0
    exe, opts = ui_server

    def ask():
        n = call('sc_catalog_request', token, now & 0xffffffff, packet)
        return bytes(cpu.mem_read(packet, n))

    def receive(reply):
        cpu.mem_write(packet, reply)
        return call('sc_catalog_receive', packet, len(reply), now & 0xffffffff)

    def synthetic(request, count, revision=0xabcdef01, duplicate=False):
        i = request[15]
        head = bytearray(request[:17]); head[5] = 4
        head += bytes((revision >> shift) & 127 for shift in (28, 21, 14, 7, 0))
        if i >= count:
            return bytes(head) + bytes([count]) + bytes(47) + b'\xf7'
        ident = f'demo.x{0 if duplicate else i:02}'.encode().ljust(32, b'\0')
        name = f'ENGINE{i:02}'.encode().ljust(10, b'\0')
        return bytes(head) + bytes((count, i % 7)) + ident + name + b'TEST\xf7'

    assert ask() == b''
    call('sc_catalog_open', 1)
    request = ask()
    assert len(request) == 50 and request[14:17] == bytes((2, 0, 0)) and not any(request[17:49])
    # First exchange uses the real Pi server and an actual package.
    ask_file, reply_file = tmp_path / 'cat-ask.bin', tmp_path / 'cat-reply.bin'
    ask_file.write_bytes(request)
    subprocess.run([str(exe), '--answer', str(ask_file), str(reply_file),
                    str(SIDECAR / 'build/dn2/fixtures/bell.rmp')], **opts)
    assert receive(reply_file.read_bytes()) == 1
    assert call('sc_catalog_view') == 0 and call('sc_catalog_publish') == 1
    view = call('sc_catalog_view'); assert view
    assert bytes(cpu.mem_read(view + 9, 32)).rstrip(b'\0') == b'demo.bell'
    assert bytes(cpu.mem_read(view + 8, 1)) == b'\x01'
    original = bytes(cpu.mem_read(view, 1580))
    # All 32 entries, including unavailable/loading/bad states, publish together.
    call('sc_catalog_open', 1)
    for i in range(32):
        request = ask(); assert len(request) == 50 and request[15] == i
        reply = synthetic(request, 32)
        assert receive(reply[:-1]) == 0
        bad = bytearray(reply); bad[22] = 33
        assert receive(bytes(bad)) == 0
        bad = bytearray(reply); bad[13] ^= 1
        assert receive(bytes(bad)) == 0
        if i:
            assert receive(synthetic(request, 32, duplicate=True)) == 0
        assert ask() == b''
        now += 150
        assert ask() == request  # includes native frame-counter wrap
        assert receive(reply) == 1 and receive(reply) == 0
        assert bytes(cpu.mem_read(view, 1580)) == original
        assert call('sc_catalog_publish') == (1 if i == 31 else 0)
        now += 1
    view = call('sc_catalog_view')
    assert bytes(cpu.mem_read(view + 8, 1)) == b'\x20'
    for i in range(32):
        entry = bytes(cpu.mem_read(view + 9 + i * 49, 49))
        assert entry[:32].rstrip(b'\0') == f'demo.x{i:02}'.encode() and entry[48] == i % 7
    # A mid-transfer shrink and revision change restart; an empty list is valid.
    call('sc_catalog_open', 1)
    request = ask(); assert receive(synthetic(request, 4, revision=17)) == 1
    request = ask(); assert request[15] == 1
    assert receive(synthetic(request, 0, revision=18)) == 1
    request = ask(); assert request[15] == 0
    assert receive(synthetic(request, 0, revision=18)) == 1
    assert call('sc_catalog_publish') == 1
    assert bytes(cpu.mem_read(call('sc_catalog_view') + 8, 1)) == b'\0'
    call('sc_catalog_open', 1); request = ask()
    call('sc_catalog_open', 0)
    assert receive(synthetic(request, 32)) == 0 and ask() == b''
    call('sc_catalog_session', 0)
    assert call('sc_catalog_view') == 0


def test_compiled_explicit_load_transaction(capture, tmp_path, ui_server):
    feed, *_ = capture
    cpu, call = feed.cpu, feed.call
    ident, packet, token, now = 0x46a06000, 0x46a06100, 0x1234567, 200
    exe, opts = ui_server
    cpu.mem_write(ident, b'demo.bell'.ljust(32, b'\0'))

    def ask():
        n = call('sc_load_request', token, now, packet)
        return bytes(cpu.mem_read(packet, n))

    def receive(reply):
        cpu.mem_write(packet, reply)
        return call('sc_load_receive', packet, len(reply), now)

    def answer(request):
        a, r = tmp_path / 'load-ask.bin', tmp_path / 'load-reply.bin'
        a.write_bytes(request)
        subprocess.run([str(exe), '--answer', str(a), str(r),
                        str(SIDECAR / 'build/dn2/fixtures/bell.rmp')], **opts)
        return r.read_bytes()

    assert ask() == b'' and call('sc_load_state') == 0xffffffff
    assert call('sc_load_start', 16, ident) == 0
    assert call('sc_load_start', 2, ident) == 1
    request = ask()
    assert request[14:17] == bytes((3, 2, 0)) and request[17:49].rstrip(b'\0') == b'demo.bell'
    assert call('sc_load_state') == 0xfffffffe
    reply = answer(request)
    assert len(reply) == 24 and reply[22] == 1
    bad = bytearray(reply); bad[13] ^= 1
    assert receive(bytes(bad)) == 0 and receive(reply[:-1]) == 0
    bad = bytearray(reply); bad[22] = 7
    assert receive(bytes(bad)) == 0
    now += 149; assert ask() == b''
    now += 1; assert ask() == request
    loading = bytearray(reply); loading[22] = 2
    assert receive(bytes(loading)) == 1 and call('sc_load_state') == 2
    now += 149; assert ask() == b''
    now += 1; newer = ask()
    assert newer[10:14] != request[10:14] and newer[14:] == request[14:]
    assert receive(reply) == 0
    assert receive(answer(newer)) == 1 and call('sc_load_state') == 1
    now += 1500; assert ask() == b''
    call('sc_load_session', 0); assert call('sc_load_state') == 0xfffffffe
    token += 1; request = ask(); assert request
    call('sc_load_cancel')
    assert receive(answer(request)) == 0 and ask() == b'' and call('sc_load_state') == 0xffffffff
    # Failed load states are terminal, never an automatic retry/reload loop.
    for state in (0, 3, 4, 5, 6):
        assert call('sc_load_start', 2, ident) == 1
        request = ask(); reply = bytearray(answer(request)); reply[22] = state
        assert receive(bytes(reply)) == 1 and call('sc_load_state') == state
        now += 1500; assert ask() == b''
