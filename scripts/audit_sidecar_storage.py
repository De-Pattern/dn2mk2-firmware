"""Exercise all forty SYN sound words in an existing image, without rebuilding.

This establishes converter capacity only: no project filesystem, sequencer,
parameter enumeration, modulation or hardware claim. Never sends to a device.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def audit(image):
    import unicorn as uc
    from unicorn import m68k_const as reg
    from dnfw.mods import platform

    cpu = uc.Uc(uc.UC_ARCH_M68K, uc.UC_MODE_BIG_ENDIAN)
    cpu.ctl_set_cpu_model(reg.UC_CPU_M68K_CFV4E)
    cpu.mem_map(0x40000000, 0x08000000)
    cpu.mem_map(0x80000000, 0x10000)
    cpu.mem_write(0x40000400, image)
    for address, data in platform.runtime(image):
        cpu.mem_write(address, data)
    # Startup's two SRAM initializer copies (not a complete boot).
    cpu.mem_write(0x80000000, image[0x402fc000-0x40000400:0x40304000-0x40000400])
    cpu.mem_write(0x80008000, image[0x40304000-0x40000400:0x4030b980-0x40000400])
    ret, stack = 0x46a00800, 0x46a00000
    live, stored, back, again = 0x46a10000, 0x46a11000, 0x46a12000, 0x46a13000
    sound_bytes, stored_bytes = 1163, 359
    slots = tuple(range(25, 65))
    lock_map = struct.unpack('>107I', image[0x401fd0b0-0x40000400:0x401fd0b0-0x40000400+428])
    ids = [[i for i, s in enumerate(lock_map) if s == slot] for slot in slots]
    assert all(len(row) == 1 for row in ids), 'SYN slots do not have distinct stored IDs'

    def call(fn, *args):
        cpu.mem_write(stack, struct.pack('>' + 'I' * (len(args) + 1), ret, *args))
        cpu.reg_write(reg.UC_M68K_REG_SR, 0x2700)
        cpu.reg_write(reg.UC_M68K_REG_A7, stack)
        cpu.reg_write(reg.UC_M68K_REG_A6, 0)
        cpu.emu_start(fn, ret, count=200000)
        assert cpu.reg_read(reg.UC_M68K_REG_PC) == ret, 'Converter did not return'

    patterns = [(0,) * 40, (0x7f00,) * 40,
                tuple((0x19d + i * 0xb13) % 0x7f01 for i in range(40)),
                tuple(1 << (i % 15) for i in range(40))]
    rows = []
    for kind in (1, 21):  # stock WaveTone and current native Sidecar machine
        for case, values in enumerate(patterns):
            sound = bytearray(sound_bytes)
            sound[0xde] = kind
            for slot, value in zip(slots, values):
                struct.pack_into('>H', sound, 20 + slot * 2, value)
            cpu.mem_write(live, bytes(sound))
            cpu.mem_write(stored, bytes(stored_bytes))
            call(0x400dd6a6, stored, live, 0)
            packed = bytes(cpu.mem_read(stored, stored_bytes))
            cpu.mem_write(back, b'\xa5' * sound_bytes)
            call(0x400dd1ea, back, stored)
            loaded = bytes(cpu.mem_read(back, sound_bytes))
            got = tuple(struct.unpack_from('>H', loaded, 20 + slot * 2)[0] for slot in slots)
            assert got == values, f'Machine {kind} case {case}: lost SYN words'
            assert loaded[0xde] == kind and packed[244] == kind, 'Machine identity lost'
            cpu.mem_write(again, bytes(stored_bytes))
            call(0x400dd6a6, again, back, 0)
            assert bytes(cpu.mem_read(again, stored_bytes)) == packed, 'Second SAVE changed bytes'
            rows.append(dict(machine=kind, case=case, words_exact=40, second_save_exact=True))
    return dict(scope='Existing compiled SAVE/LOAD converters only; no UI, locks, modulation, project filesystem or hardware proof.',
                image_sha256=hashlib.sha256(image).hexdigest(), live_synth_slots=list(slots),
                stored_ids=[row[0] for row in ids], stored_sound_bytes=stored_bytes,
                results=rows, words_exact=sum(row['words_exact'] for row in rows))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out.unlink(missing_ok=True)
    result = audit(args.image.read_bytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('image_sha256', 'live_synth_slots', 'stored_ids', 'results')}, indent=2))


if __name__ == '__main__':
    main()
