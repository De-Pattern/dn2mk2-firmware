"""v0.43 (docs/emu-speed.md): boot N instructions with and without dspboot's global per-instruction
hook and hash the end state (all mapped memory, PC, SR, A0-A7, D0-D7). Usage: MODE IMAGE N, MODE
cover or nocover; the two lines must match."""
import sys, os, time, hashlib
sys.path.insert(0, "/home/claude/dn2/digikit")
from emu import dspboot
from unicorn.m68k_const import *
mode, img, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
SYX = "/home/claude/dn2/Digitone_II_OS1.11.syx"
holder = {}
def pre(m):
    pass
if mode == "nocover":
    import unicorn
    orig = unicorn.Uc.hook_add
    def hook_add(self, htype, cb, user_data=None, begin=1, end=0, *a, **k):
        if getattr(cb, "__name__", "") == "cover":
            return 0
        return orig(self, htype, cb, user_data, begin, end, *a, **k)
    unicorn.Uc.hook_add = hook_add
t = time.time()
m, st, stop = dspboot.run(SYX, open(img, "rb").read(), limit=n, machine_out=holder, pre_start=pre)
dt = time.time() - t
h = hashlib.sha256()
for b, e, p in sorted(m.uc.mem_regions()):
    h.update(b.to_bytes(4, "big")); h.update(bytes(m.uc.mem_read(b, e - b + 1)))
regs = [m.uc.reg_read(r) for r in (UC_M68K_REG_PC, UC_M68K_REG_SR, *range(UC_M68K_REG_A0, UC_M68K_REG_A7 + 1), *range(UC_M68K_REG_D0, UC_M68K_REG_D7 + 1))]
print(mode, "stop", stop, "time %.1fs" % dt, "pc %08x" % regs[0], "mem", h.hexdigest()[:16], "regs", hashlib.sha256(repr(regs).encode()).hexdigest()[:16], "spins", st["spin"], "tasks", len(st["task_start_hits"]))
