"""Run the NOI generator from a built MAIN OS under Unicorn, and check it.

Usage (WSL, digikit's patched Unicorn): python scripts/check_lfo_noise.py <main_os.bin>
Checks that the output holds within each of the 64 steps per cycle, that the
callee-saved registers and stack survive, and prints each colour's peak, mean
and lag-1 correlation (white ~0, pink ~0.5, brown ~0.9).
"""
import struct
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
from unicorn.m68k_const import *
import sys
img=open(sys.argv[1],'rb').read()
B=0x40000400
NOISE=int(sys.argv[2],0) if len(sys.argv)>2 else 0x402cf6ac  # the build prints `noise` in part 1
uc=Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
try:
    from unicorn.m68k_const import UC_CPU_M68K_CFV4E
    uc.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
except Exception as e: print('cpu model',e)
uc.mem_map(0x40000000, 0x400000); uc.mem_write(B, img)
uc.mem_map(0x10000000, 0x10000)
RET=0x10008000
uc.mem_write(RET, b'\x4e\x71')
def call(phase, sph):
    sp=0x1000f000
    uc.mem_write(sp, struct.pack('>II', RET, phase))
    uc.reg_write(UC_M68K_REG_A7, sp); uc.reg_write(UC_M68K_REG_D1, sph)
    for r,v in ((UC_M68K_REG_D2,0x11),(UC_M68K_REG_D3,0x22),(UC_M68K_REG_D4,0x33),(UC_M68K_REG_D5,0x44)):
        uc.reg_write(r,v)
    uc.emu_start(NOISE, RET, count=2000)
    assert uc.reg_read(UC_M68K_REG_A7)==sp+4, hex(uc.reg_read(UC_M68K_REG_A7))
    assert [uc.reg_read(r) for r in (UC_M68K_REG_D2,UC_M68K_REG_D3,UC_M68K_REG_D4,UC_M68K_REG_D5)]==[0x11,0x22,0x33,0x44]
    v=uc.reg_read(UC_M68K_REG_D0)&0xffffffff
    return v-(1<<32) if v&0x80000000 else v
for name,sph in (('white',0),('pink',40),('brown',80),('violet',110)):
    vals=[call(s<<26 | 0x123456, sph) for s in range(64)]
    same=all(call(s<<26 | 0x3ffffff, sph)==vals[s] for s in range(64))
    mean=sum(vals)/64/2**31; peak=max(abs(v) for v in vals)/2**31
    # lag-1 correlation shows colour
    import statistics
    c=sum((vals[i]-sum(vals)/64)*(vals[i+1]-sum(vals)/64) for i in range(63))/sum((v-sum(vals)/64)**2 for v in vals)
    print(f'{name:6} hold-within-step={same} peak={peak:.2f} mean={mean:+.2f} lag1corr={c:+.2f} first={[round(v/2**31,2) for v in vals[:8]]}')
