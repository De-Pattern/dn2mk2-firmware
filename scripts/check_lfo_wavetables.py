"""Run the wavetable generators from a built MAIN OS under Unicorn, against the reference.

    python scripts/check_lfo_wavetables.py <main_os.bin> <wt1> <wt2> <wt3>

(WSL, digikit's patched Unicorn; addresses as build_lfo_wavetables.py prints.)
Every generator is called at a grid of phases and SPH values; each result must
equal `wavetables.reference` exactly, with callee-saved registers and the stack
intact.
"""
import pathlib
import random
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
from unicorn.m68k_const import *
import wavetables as wt

img = open(sys.argv[1], "rb").read()
entries = [int(a, 0) for a in sys.argv[2:5]]
B = 0x40000400
uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
uc.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
uc.mem_map(0x40000000, 0x400000); uc.mem_write(B, img)
uc.mem_map(0x10000000, 0x10000)
RET = 0x10008000; uc.mem_write(RET, b"\x4e\x71")
SAVED = (UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4, UC_M68K_REG_D5, UC_M68K_REG_D6,
         UC_M68K_REG_D7, UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4)
rng = random.Random(7)
phases = [0, 1 << 27, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF] + [rng.getrandbits(32) for _ in range(60)]
sphs = [0, 1, 20, 21, 63, 64, 104, 105, 126, 127, 0x7F | (37 << 8)]
bad = 0
for (name, _, make), entry in zip(wt.TABLES, entries):
    frames = make()
    peak = 0
    for sph in sphs:
        for ph in phases:
            sp = 0x1000E000
            uc.mem_write(sp, struct.pack(">II", RET, ph))
            uc.reg_write(UC_M68K_REG_A7, sp); uc.reg_write(UC_M68K_REG_D1, sph)
            for i, r in enumerate(SAVED): uc.reg_write(r, 0x3300 + i)
            uc.emu_start(entry, RET, count=10000)
            got = uc.reg_read(UC_M68K_REG_D0) & 0xFFFFFFFF
            got = got - (1 << 32) if got & 0x80000000 else got
            want = wt.reference(frames, ph, sph)
            ok = got == want and uc.reg_read(UC_M68K_REG_A7) == sp + 4 and \
                [uc.reg_read(r) for r in SAVED] == [0x3300 + i for i in range(len(SAVED))]
            if not ok:
                bad += 1
                if bad < 5:
                    print(f"  MISMATCH {name} sph {sph:#x} phase {ph:#010x}: got {got} want {want}")
            peak = max(peak, abs(got))
    print(f"{name}: {len(sphs) * len(phases)} calls, peak {peak / 2**31:.3f} of full scale")
print("all match" if not bad else f"{bad} mismatches")
sys.exit(1 if bad else 0)
