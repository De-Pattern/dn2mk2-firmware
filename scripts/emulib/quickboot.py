"""dspboot.run without its per-instruction Python hook (v0.43: the gate's boot steps faster).

digikit's `emu.dspboot.run(fast=True)` adds one GLOBAL code hook, `cover`, that runs a Python
call on every instruction to count instructions and collect the addresses seen (`st['n']`,
`st['seen']`, `st['stall_pcs']`, `st['curve']`). The boot steps' verdicts never read those:
they come from per-address hooks (the frame, the fault reporter, the build's routines, the
start-up animation's stamp and show), and the run's length is `emu_start(count=limit)`, which
Unicorn counts natively. So the hook costs the gate time and checks nothing.

This runs the same boot with that one hook left out. Nothing else changes: the same machine,
MMIO models, scheduler tick (driven by the idle-spin addresses, not by instruction count),
flash HLE and count. Measured on this firmware (docs/emu-speed.md): the machine's whole memory
and its registers are byte-identical with and without it at 30M and at 700M instructions, and
the boot runs 1.7x faster.

What is lost: `st['n']` is not counted along the way. It is set to the limit when the run ends
on it; a run stopped early (the fault reporter) leaves it 0, so `counted` is False and callers
print no instruction number for the stop.
"""
from __future__ import annotations

import unicorn

from emu import dspboot


def run(syx_path, main_img, limit, **kw):
    """-> (m, st, stop), as dspboot.run, without the `cover` hook. st['counted'] says whether
    st['n'] is the run's real length."""
    orig = unicorn.Uc.hook_add
    left_out = []

    def hook_add(self, htype, callback, user_data=None, begin=1, end=0, *a, **k):
        if (htype == unicorn.UC_HOOK_CODE and begin == 1 and end == 0
                and getattr(callback, "__name__", "") == "cover"
                and getattr(callback, "__module__", "") == dspboot.__name__):
            left_out.append(callback)
            return 0
        return orig(self, htype, callback, user_data, begin, end, *a, **k)

    unicorn.Uc.hook_add = hook_add
    try:
        m, st, stop = dspboot.run(syx_path, main_img, limit=limit, fast=True, **kw)
    finally:
        unicorn.Uc.hook_add = orig
    if not left_out:
        # digikit changed: the hook ran as before, so the run is the old (slower) one, still correct
        print("  (quickboot: dspboot's cover hook not found; ran with it)")
        st["counted"] = True
        return m, st, stop
    st["counted"] = stop == "instruction limit"
    if st["counted"]:
        st["n"] = limit
    return m, st, stop
