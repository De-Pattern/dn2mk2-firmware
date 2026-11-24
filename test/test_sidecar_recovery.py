"""Saved eight-part sounds -> native capture -> Pi-consumable packet fixture.

Actual stock converters and compiled bridge; not project filesystem/UI evidence.
"""
import hashlib
import json
import struct

import pytest

from dnfw.sidecar import machines as sc
from .test_sidecar_pages import ROOT, compiled_runtime


def test_saved_eight_parts_feed_native_capture(compiled_runtime):
    uc = pytest.importorskip('unicorn')
    from unicorn import m68k_const as reg

    _, built = compiled_runtime
    cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
    cpu.mem_map(0x40000000, 0x08000000)
    cpu.mem_map(0x80000000, 0x10000)
    cpu.mem_write(0x40000400, built['content'])
    for key in ('chunk', 'c_chunk', 'machines_chunk'):
        cpu.mem_write(built[key]['load'], built[key]['code'])
    stop, stack = 0x46a00800, 0x46a04000
    live, stored, back = 0x46a10001, 0x46a14000, 0x46a18001
    ident, frame, tracks, event, packet = (0x46a20000, 0x46a21000, 0x46a22000,
                                          0x46a23000, 0x46a24000)

    def call(fn, *args):
        cpu.mem_write(stack, struct.pack('>' + 'I' * (1 + len(args)), stop, *args))
        cpu.reg_write(reg.UC_M68K_REG_SR, 0x2000)
        cpu.reg_write(reg.UC_M68K_REG_A7, stack)
        cpu.reg_write(reg.UC_M68K_REG_A6, 0)
        cpu.emu_start(built['layout'].get(fn, fn), stop, count=300000)
        assert cpu.reg_read(reg.UC_M68K_REG_PC) == stop
        return cpu.reg_read(reg.UC_M68K_REG_D0)

    ids = [f'recall.engine{i}'.encode() for i in range(8)]
    slots = [slot for _, slot in sc.ALL_RECORDS]
    expected, words = [], [0] * 1374
    for part, engine in enumerate(ids):
        source, saved, restored = live + 1163 * part, stored + 359 * part, back + 1163 * part
        values = [(part * 1777 + i * 1231 + 129) % 32513 for i in range(16)]
        sound = bytearray(1163)
        sound[0xde] = sc.TYPE
        for slot, value in zip(slots, values):
            struct.pack_into('>H', sound, 20 + 2 * slot, value)
        cpu.mem_write(source, bytes(sound))
        cpu.mem_write(ident, engine.ljust(32, b'\0'))
        assert call('sc_sound_store', source, ident) == 1
        call(0x400dd6a6, saved, source, 0)
        cpu.mem_write(restored, b'\xa5' * 1163)
        call(0x400dd1ea, restored, saved)
        assert call('sc_sound_identity', restored, ident) == 1
        assert bytes(cpu.mem_read(ident, 32)) == engine.ljust(32, b'\0')
        # Fill the completed control frame from LOAD's output, not the input values.
        voice = 15 - part
        cpu.mem_write(0x800052a8 + 4 * voice, struct.pack('>I', restored))
        words[74 + voice] = sc.TYPE
        words[1 + voice], words[26 + voice], words[58 + voice] = 60 << 8, 100 << 8, 127 << 8
        for slot, value in zip(slots, values):
            got = struct.unpack('>H', cpu.mem_read(restored + 20 + 2 * slot, 2))[0]
            assert got == value
            words[84 + 73 * voice + slot] = got
        expected.append(dict(track=part, voice=voice, engine=engine.decode(), params=values))

    cpu.mem_write(tracks, struct.pack('>16I', *([99] * 8 + list(reversed(range(8))))))
    packets = bytearray()
    # Restore while stopped, then trigger: identical controls still need a fresh ON.
    for trigger in (False, True):
        current = words.copy()
        current[17] = 0xff00 if trigger else 0
        cpu.mem_write(frame, struct.pack('>1374H', *current))
        call('sc_capture', frame, tracks, 100 + int(trigger), int(trigger))
        seen = set()
        while call('sc_pop', event):
            row = struct.unpack('>I20H4B32s', cpu.mem_read(event, 80))
            part = row[22]
            assert part not in seen and part < 8
            seen.add(part)
            assert row[23] == (3 if trigger else 1)
            assert row[25].rstrip(b'\0').decode() == expected[part]['engine']
            assert list(row[5:21]) == expected[part]['params']
            assert call('sc_encode', event, packet, 98) == 98
            packets.extend(cpu.mem_read(packet, 98))
        assert seen == set(range(8))
    path = ROOT / 'out/sidecar-recovery'
    path.mkdir(exist_ok=True)
    (path / 'saved-parts.bin').write_bytes(packets)
    (path / 'saved-parts.json').write_text(json.dumps(dict(
        scope='Actual SAVE/LOAD, capture and encoder; no project filesystem or hardware',
        parts=expected, packets=16, sha256=hashlib.sha256(packets).hexdigest()), indent=2) + '\n')
