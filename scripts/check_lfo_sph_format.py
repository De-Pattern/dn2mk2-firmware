"""Run lfo-waveshapes' SPH format wrapper (fmt_v92) under Unicorn with a fake ParameterSet.

    python scripts/check_lfo_sph_format.py <main_os.bin> <fmt_v92>

The fake object's vtable slot 40 (get a record's value) returns a chosen WAVE, so
the wrapper's whole contract is exercised on the real bytes and the firmware's own
sprintf: SPH records 81/91/101 ask for WAVE 79/89/99; NOIS (9) prints
`colour.loop`; any other wave or record reaches stock 0x40036692 untouched.
Each WAVE value gets its own stub address -- Unicorn caches translated code, and
rewriting one stub in place silently kept returning the first value.
"""
import struct, sys
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
from unicorn.m68k_const import *
img = open(sys.argv[1], 'rb').read(); FMT = int(sys.argv[2], 0)
B = 0x40000400
uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
uc.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
uc.mem_map(0x40000000, 0x400000); uc.mem_write(B, img)
uc.mem_map(0x10000000, 0x10000); uc.mem_map(0x80000000, 0x20000)
RET = 0x10008000; uc.mem_write(RET, b'\x4e\x71')
# fake ParameterSet: vtable[40] -> stub `move.l #WAVE,d0 ; rts` ; stock v92 must not be reached for NOIS
THIS, VT, GET = 0x10001000, 0x10002000, 0x10003000
uc.mem_write(THIS, struct.pack('>I', VT)); uc.mem_write(VT + 40, struct.pack('>I', GET))
stock_hit = []
from unicorn import UC_HOOK_CODE
uc.hook_add(UC_HOOK_CODE, lambda u, a, s, d: (stock_hit.append(1), u.emu_stop()), begin=0x40036692, end=0x40036692)
got_rec = []
uc.hook_add(UC_HOOK_CODE, lambda u, a, s, d: got_rec.append(struct.unpack('>I', bytes(u.mem_read(u.reg_read(UC_M68K_REG_A7) + 8, 4)))[0]), begin=GET, end=GET + 0x200)
dbg=[]
uc.hook_add(UC_HOOK_CODE, lambda u,a,s_,d: dbg.append((hex(a), hex(u.reg_read(UC_M68K_REG_D0)), hex(u.reg_read(UC_M68K_REG_A1)))), begin=FMT+0x2c, end=FMT+0x3a)
SAVED = (UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4, UC_M68K_REG_A2, UC_M68K_REG_A3)
def run(rec, wave, sph):
    stub = GET + 16 * wave  # one address per value: Unicorn caches translated code
    uc.mem_write(stub, b' <' + struct.pack('>I', wave << 8) + b'Nu')
    uc.mem_write(VT + 40, struct.pack('>I', stub))
    sp = 0x1000e000; dest = 0x1000c000; uc.mem_write(dest, bytes(32))
    uc.mem_write(sp, struct.pack('>IIIII', RET, THIS, rec, sph << 8, dest))
    uc.reg_write(UC_M68K_REG_A7, sp)
    for i, r in enumerate(SAVED): uc.reg_write(r, 0x2200 + i)
    stock_hit.clear(); got_rec.clear(); dbg.clear()
    uc.emu_start(FMT, RET, count=100000)
    if stock_hit: return f'-> stock v92 (asked get for {got_rec})'
    assert uc.reg_read(UC_M68K_REG_A7) == sp + 4
    assert [uc.reg_read(r) for r in SAVED] == [0x2200 + i for i in range(len(SAVED))]
    return repr(bytes(uc.mem_read(dest, 16)).split(b'\0')[0].decode()) + f' (get record {got_rec})'
for rec, wave, sph in ((81, 9, 0), (81, 9, 3), (91, 9, 45), (101, 9, 127), (81, 9, 95), (81, 1, 64), (91, 8, 12), (79, 9, 3), (83, 9, 3)):
    print(f'record {rec:3} wave {wave} sph {sph:3}: {run(rec, wave, sph)}')
