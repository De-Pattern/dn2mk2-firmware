"""Does the page read LFO4's value from the table instead of from the sound?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_value.py

Step 4a diverted the **write** at the firmware's `slot > 100` guard. Step 4c
diverts the **read** at the identical guard six bytes wide, `0x4003717c`, which
`scripts/emu_value_reads.py` picked out of 119 candidates by hooking all of
them and opening the MOD page: two fire, and the other clamps its index to
0..15.

There is still no page that asks for slot 101, so the id alone is faked, the
same way step 4a's harness faked it: a code hook at the bound rewrites `d2` as
the firmware arrives there, with everything else -- the object in `a2`, the
virtual call that produces the live sound -- exactly what drawing a real MOD
page set up.

**Nothing here calls into the firmware to collect a result.** The value is read
out of `d0` at the function's own epilogue, by a hook, because a call on a
machine whose timers are running comes back with whatever an interrupt handler
left in `d0` -- which is how 330 accessor calls once returned 0 apiece
(`docs/lfo4-build-plan.md`).

Three things have to hold together, and any one alone would mislead:

- the diverted read **returns the value the table holds**, not the sound's;
- it read it **for the sound the firmware itself produced**, inside the kit;
- slots the firmware owns still answer from the sound, which the control turn
  checks by leaving `d2` alone and watching `lfo4_gets_ignored` stay put.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.image import code_chunks, differences, load_build     # noqa: E402
from emulib.machine import SNAP, Machine                          # noqa: E402
from emulib.panel import MOD, Panel                               # noqa: E402
from emulib.report import check, report                           # noqa: E402

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-value"
GET_BOUND, GET_RETURN = 0x4003717C, 0x4003719C
KIT, SOUND_AT, SOUND_STRIDE, TRACKS = 0x4210C08C, 52, 1163, 16
SLOT, PARAM = 101, 0
MARK = 0x2A5C                     # distinctive, and not a plausible stray


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--slot", type=int, default=SLOT)
    p.add_argument("--delta", type=int, default=10)
    args = p.parse_args()

    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_D0, UC_M68K_REG_D2

    machine = Machine(args.snapshot)
    image, sym = load_build(BUILD)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    runs = differences(stock, image)
    machine.apply(runs)
    for load, _n, bss, init, blob in code_chunks(image):
        machine.load_code_chunk((load, len(blob), bss, init, blob))
    machine.flush()
    print(f"  installed {len(runs)} run(s), {len(code_chunks(image))} CODE chunk(s); "
          f"stub at {sym['lfo4_get_stub']:#010x}")

    # The mark goes into every track's sound, because which track the page is
    # showing is not this probe's subject. `lfo4_get_sound` says which one it
    # actually read, and that it is inside the kit is checked below.
    sounds = [KIT + SOUND_AT + t * SOUND_STRIDE for t in range(TRACKS)]
    for sound in sounds:
        machine.call(sym["ext_set"], sound, PARAM, MARK)
    print(f"  {MARK:#06x} written to all {TRACKS} tracks' sounds, "
          f"live {machine.long(sym['ext_live'])}\n")

    # `seen` records every read the bound sees, always; `armed` decides
    # whether the id is rewritten. Keeping those two apart is what lets the
    # same hook serve the control phase, the diverted phase and the turn.
    armed, seen, answers = [False], [], []

    def at_bound(uc, address, size, user):
        seen.append(uc.reg_read(UC_M68K_REG_D2))
        if armed[0]:
            uc.reg_write(UC_M68K_REG_D2, args.slot)

    def at_return(uc, address, size, user):
        if armed[0]:
            answers.append(uc.reg_read(UC_M68K_REG_D0))

    machine.uc.hook_add(UC_HOOK_CODE, at_bound, begin=GET_BOUND, end=GET_BOUND)
    machine.uc.hook_add(UC_HOOK_CODE, at_return, begin=GET_RETURN, end=GET_RETURN)

    panel = Panel(machine, png_dir="out/lfo4-value")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print(f"  {panel.screen('mod-1')}")

    # The control first: the same page drawn with nothing rewritten. Every read
    # is a slot the firmware owns, so the divert must decline all of them.
    ignored_before = machine.long(sym["lfo4_gets_ignored"])
    gets_before = machine.long(sym["lfo4_gets"])
    control_from = len(seen)
    panel.tap(MOD)
    control_gets = machine.long(sym["lfo4_gets"]) - gets_before
    control_ignored = machine.long(sym["lfo4_gets_ignored"]) - ignored_before
    control_reads = len(seen) - control_from

    rewritten_from = len(seen)
    armed[0] = True
    panel.tap(MOD)
    armed[0] = False
    rewritten = seen[rewritten_from:]

    gets = machine.long(sym["lfo4_gets"]) - gets_before
    sound = machine.long(sym["lfo4_get_sound"])
    slot = machine.long(sym["lfo4_get_slot"])
    value = machine.long(sym["lfo4_get_value"])
    print("")
    print(f"  control page: {control_reads} read(s) at the bound, "
          f"{control_gets} diverted, {control_ignored} declined")
    print(f"  rewritten page: the bound saw {len(rewritten)} read(s) for slots "
          f"{sorted(set(rewritten))[:8]}")
    print(f"  lfo4_gets {gets}, sound {sound:#010x}, slot {slot}, value {value:#06x}")
    print(f"  the function returned {sorted(set(answers))[:8]} at its epilogue")

    check("the page reads values at all", rewritten, "the bound was never reached")
    check("the control page diverted nothing", control_gets == 0,
          f"{control_gets} diverted while nothing was rewritten")
    check("every rewritten read was diverted", gets == len(rewritten),
          f"{gets} diverted, {len(rewritten)} rewritten")
    check("it read the id we asked for", slot == args.slot, f"slot {slot}")
    check("the sound is the firmware's own, inside the kit",
          KIT <= sound < KIT + SOUND_AT + TRACKS * SOUND_STRIDE, f"{sound:#010x}")
    check("the value came from the table", value == MARK, f"{value:#06x}")
    check("and that is what the function returned",
          answers and set(answers) == {MARK},
          f"{sorted(set(answers))[:8]} against {MARK:#06x}")

    # Does *turning* a knob go through this read too? The build note predicted
    # it does -- a UI that computes `new = old + delta` has to fetch `old` from
    # somewhere, and if that somewhere is this site then the divert fixes
    # turning and not only display. Nothing is rewritten here: the question is
    # whether the instruction executes at all while a value moves.
    turned_from = len(seen)
    panel.push_and_turn(0, args.delta)
    turned = seen[turned_from:]
    during_turn = len(turned)
    print("")
    print(f"  a turn on this page reached the read bound {during_turn} time(s), "
          f"for slots {sorted(set(turned))[:8]}")
    # `check` prints its detail on a pass as well as a failure, so the detail
    # is the measurement, not an explanation of what failure would mean.
    check("turning a knob reads through the same site", during_turn > 0,
          f"{during_turn} read(s) during the turn; zero would mean the turn "
          "path fetches its old value somewhere else, needing its own divert")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
