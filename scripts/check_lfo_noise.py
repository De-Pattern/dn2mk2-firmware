"""Run the NOI generator and the SPH formatter from a built MAIN OS under Unicorn.

    python scripts/check_lfo_noise.py <main_os.bin> <noise> <fmt_sph1> <fmt_sph2> <fmt_sph3>

(WSL, digikit's patched Unicorn; the addresses are what build_lfo_waveshapes.py
prints in part 1.) Checks, on the real bytes:
- the noise repeats every loop+1 cycles, and never on loop field 31, forwards and
  backwards, with callee-saved registers and the stack intact;
- the SPH formatter prints `colour.loop` through the firmware's own sprintf when
  the mirror says WAVE is NOIS, and the stock number otherwise.
"""
import struct, sys
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UcError
from unicorn.m68k_const import *
img = open(sys.argv[1], 'rb').read()
NOISE, S1, S2, S3 = (int(x, 0) for x in sys.argv[2:6])
B = 0x40000400
uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
try: uc.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
except Exception as e: print('cpu', e)
uc.mem_map(0x40000000, 0x400000); uc.mem_write(B, img)
for base, size in ((0x10000000, 0x10000), (0x42400000, 0x100000), (0x44600000, 0x100000), (0x46740000, 0x10000), (0x80000000, 0x20000)):
    uc.mem_map(base, size)
RET = 0x10008000; uc.mem_write(RET, b'\x4e\x71')
SAVED = (UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4, UC_M68K_REG_D5, UC_M68K_REG_D6, UC_M68K_REG_D7, UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4)
def call(entry, args, d1=0):
    sp = 0x1000e000
    uc.mem_write(sp, struct.pack('>I' + 'I' * len(args), RET, *args))
    uc.reg_write(UC_M68K_REG_A7, sp); uc.reg_write(UC_M68K_REG_D1, d1)
    for i, r in enumerate(SAVED): uc.reg_write(r, 0x1100 + i)
    uc.emu_start(entry, RET, count=200000)
    assert uc.reg_read(UC_M68K_REG_A7) == sp + 4
    assert [uc.reg_read(r) for r in SAVED] == [0x1100 + i for i in range(len(SAVED))], 'callee-saved clobbered'
    v = uc.reg_read(UC_M68K_REG_D0) & 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v
# ---- noise: loop semantics ----
key = 37 << 8
def run(sph, cycles):
    uc.mem_write(0x46740000 + 37 * 8, bytes(8))
    out = []
    for c in range(cycles):
        out.append(tuple(call(NOISE, [s << 26 | 0x1234], key | sph) for s in range(64)))
    return out
for sph, label in ((0, 'white loop1'), (3, 'white loop4'), (31, 'white never'), (32 + 1, 'pink loop2'), (96 + 30, 'violet loop31')):
    cyc = run(sph, 70)
    L = (sph & 31) + 1
    if sph & 31 == 31:
        print(f'{label:14} distinct cycles {len(set(cyc))} of 70')
    else:
        ok = all(cyc[i] == cyc[i + L] for i in range(70 - L)) and len(set(cyc[:L])) == L
        print(f'{label:14} repeats every {L}: {ok}  distinct {len(set(cyc))}')
# backwards wrap: phase decreasing
uc.mem_write(0x46740000 + 37 * 8, bytes(8))
back = [tuple(call(NOISE, [s << 26], key | 3) for s in reversed(range(64))) for c in range(9)]
print('backwards loop4 repeats:', all(back[i] == back[i + 4] for i in range(5)))
# ---- formatter ----
def fmt(entry, track, wave, sph):
    uc.mem_write(0x42431a6c, bytes([track]))
    lfo = {S1: 0, S2: 1, S3: 2}[entry]
    uc.mem_write(0x44616448 + 202 * track + 2 * (8 * lfo + 5), bytes([wave, 0]))
    dest = 0x1000c000; uc.mem_write(dest, bytes(32))
    call(entry, [sph << 8, dest])
    return bytes(uc.mem_read(dest, 16)).split(b'\0')[0].decode()
for e, t, w, v in ((S1, 0, 9, 0), (S1, 0, 9, 3), (S2, 5, 9, 45), (S3, 15, 9, 127), (S1, 0, 9, 95), (S1, 0, 1, 64), (S2, 2, 8, 12)):
    print(f'lfo{ {S1:1,S2:2,S3:3}[e]} track {t:2} wave {w} sph {v:3} -> {fmt(e, t, w, v)!r}')
