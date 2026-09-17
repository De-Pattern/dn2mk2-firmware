"""Check lfo-waves: the boot copy stub and the generators running from RAM, under Unicorn.

    python scripts/check_lfo_waves.py <main_os.bin> <offsets.txt>

offsets.txt: the "  label  0xaddr" lines build_lfo_waves.py prints for step, pulse,
noise, trap, wt1..wt3. Init and BSS clear are stubbed; the copy must reproduce the
appended blob byte for byte at 0x46780000.
"""
import struct, sys, random
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE
from unicorn.m68k_const import *
import wavetables as wt
img = open(sys.argv[1],'rb').read()
B = 0x40000400; AREA = 0x4030B980; RT = 0x46780000
off = dict(l.split() for l in open(sys.argv[2]))
uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN); uc.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
uc.mem_map(0x40000000, 0x400000); uc.mem_write(B, img)
uc.mem_map(0x46700000, 0x100000); uc.mem_map(0x10000000, 0x10000)
RET = 0x10008000; uc.mem_write(RET, b'\x4e\x71')
# 1. the boot stub: init and clear stubbed out by rts; the copy must reproduce the appended blob at RT
calls = []
for fn in (0x4000045C, 0x400004B2):
    uc.hook_add(UC_HOOK_CODE, lambda u, a, s, d, fn=fn: calls.append(fn), begin=fn, end=fn)
uc.mem_write(0x4000045C, b'\x4e\x75'); uc.mem_write(0x400004B2, b'\x4e\x75')
sp = 0x1000e000; uc.mem_write(sp, struct.pack('>I', RET)); uc.reg_write(UC_M68K_REG_A7, sp)
uc.emu_start(0x402CF52C, RET, count=100000)
length = struct.unpack('>I', img[AREA - B + 4:AREA - B + 8])[0]
copied = bytes(uc.mem_read(RT, length)) == img[AREA - B:AREA - B + length]
print('boot stub: init then clear called:', calls == [0x4000045C, 0x400004B2], '| blob copied intact:', copied, f'({length} B)')
# 2. generators from RAM
def call(entry, phase, d1):
    sp = 0x1000e000; uc.mem_write(sp, struct.pack('>II', RET, phase)); uc.reg_write(UC_M68K_REG_A7, sp); uc.reg_write(UC_M68K_REG_D1, d1)
    uc.reg_write(UC_M68K_REG_D2, 0x77); uc.reg_write(UC_M68K_REG_D5, 0x99)
    uc.emu_start(entry, RET, count=20000)
    assert uc.reg_read(UC_M68K_REG_D2) == 0x77 and uc.reg_read(UC_M68K_REG_D5) == 0x99 and uc.reg_read(UC_M68K_REG_A7) == sp + 4
    v = uc.reg_read(UC_M68K_REG_D0) & 0xffffffff; return v - (1 << 32) if v & 0x80000000 else v
rng = random.Random(1); bad = 0; n = 0
for (name, _, make), e in zip(wt.TABLES, ('wt1', 'wt2', 'wt3')):
    fr = make()
    for sph in (0, 33, 64, 127):
        for p in [rng.getrandbits(32) for _ in range(40)]:
            n += 1; bad += call(int(off[e], 16), p, sph) != wt.reference(fr, p, sph)
def trapref(p, sph):
    t = p if p < 0x80000000 else (~p) & 0xFFFFFFFF
    return max(-0x800000, min(0x7fffff, ((t - 0x40000000) >> 7) * (1 + (127 - sph) // 4))) << 8
for sph in (0, 64, 127):
    for p in [rng.getrandbits(32) for _ in range(40)]:
        n += 1; bad += call(int(off['trap'], 16), p, sph) != trapref(p, sph)
steps = [call(int(off['step'], 16), s << 24, 48) for s in range(256)]
pulse = [call(int(off['pulse'], 16), s << 24, 64) for s in range(256)]
noise = [call(int(off['noise'], 16), s << 26, (5 << 8) | 3) for s in range(64)]
print(f'wavetables + trap from RAM: {n} calls, {bad} mismatches | STEP levels {len(set(steps))} | PULS duty {sum(v > 0 for v in pulse)}/256 | NOIS distinct {len(set(noise))}/64')
