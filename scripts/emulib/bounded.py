"""A guest call's run, bounded without a per-instruction hook (2026-11-11, docs/gate-speed.md).

`uc.emu_start(begin, until, count=N)` is how the harnesses stopped a call that never returns. Unicorn
implements `count=` as a hidden code hook on every address, and while any code hook covers every
address, each instruction walks all of Unicorn's code hooks: the ~300 the ISA patches add (one per
FF1/MOVEC site). That was 89% of link16's time.

digikit's fast stepper (longrun._FastStepper) already has a block hook that stops the machine once
its budget is spent. `run` gives the call a budget of LIMIT blocks: each block is at least one
instruction, so a call stops no sooner than `count=LIMIT` stopped it. Running out raises Runaway
(`count=` stopped silently, leaving the caller to read a half-run function as a result).

With no fast stepper on the machine, `run` falls back to `count=` exactly as before.
"""

from __future__ import annotations


class Runaway(RuntimeError):
    """A guest call spent its whole budget without reaching its return."""


def run(uc, machine, begin: int, until: int, limit: int) -> int:
    """Run from BEGIN until UNTIL, at most LIMIT blocks. MACHINE is digikit's (has
    `_fast_stepper_obj` once a fast run has been made). -> blocks run (0 without a stepper)."""
    stepper = getattr(machine, "_fast_stepper_obj", None)
    if stepper is None:
        uc.emu_start(begin, until, count=limit)
        return 0
    stepper.left = limit
    try:
        uc.emu_start(begin, until)
    finally:
        left, stepper.left = stepper.left, 0
    if left <= 0:
        raise Runaway(f"the call at {begin:#010x} ran {limit:,} blocks without reaching {until:#010x}")
    return limit - left
