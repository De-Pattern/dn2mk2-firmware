"""Does a turn on parameter id 101 land in the extension table?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_slots.py

Step 4a puts `lfo4_set_stub` in place of the setter's own `slot > 100` bound,
so ids 101-108 reach `ext_set` instead of being dropped. There is no page that
*shows* those ids yet, so the panel cannot ask for one -- and building a call
to the setter by hand would test a signature this project inferred rather than
the path the firmware takes.

So the turn is real and only the id is not: a code hook at the bound rewrites
`d2` to 101 as the firmware arrives there, with everything else -- the object
in `a2`, the virtual call that produces the live sound, the value in `d3` --
exactly what a genuine encoder turn set up. What is being tested is the divert,
and the divert's input is a slot number.

Three things have to be true together, and any one alone would mislead:

- the table gained the value, for **the sound the firmware itself produced**;
- the live sound's own slots did **not** move, since above 100 stock firmware
  writes nothing and neither may we;
- `lfo4_sets` counted exactly the turns we rewrote, against an idle control.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.image import code_chunk, differences, load_build      # noqa: E402
from emulib.machine import SNAP, Machine                          # noqa: E402
from emulib.panel import MOD, Panel                               # noqa: E402
from emulib.report import check, report                           # noqa: E402

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-slots"
SET_BOUND = 0x40037BD0
KIT = 0x4210C08C
SOUND = KIT + 52
VALUES, VALUES_LEN = SOUND + 0x14, 202
SLOT = 101
EXT_SLOTS, EXT_PARAMS = 256, 8      # csrc/lfo4/ext.h


def table_read(machine, sym, key, param):
    """-> `ext_val[key][param]` read straight out of memory, or None if absent.

    Not `machine.call(ext_get, ...)`, which is what the harnesses before this
    one used and what this one used first. Once `Panel` has claimed the
    snapshot's timers, a call into firmware-resident code does not reliably
    reach its return: an interrupt vectors away, `emu_start` stops on its
    instruction count instead of at the return address, and the d0 that comes
    back is whatever the handler left there. It comes back as a plausible
    number -- 0 -- which is the worst possible failure for a probe that is
    asking whether a value arrived.

    The table is ours and its layout is known, so read it: `ext_key` is 256
    u32 keys and `ext_val` is the matching 256 x 8 u16 values.
    """
    for i in range(EXT_SLOTS):
        if machine.long(sym["ext_key"] + 4 * i) == key:
            return machine.word(sym["ext_val"] + 2 * (i * EXT_PARAMS + param))
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--delta", type=int, default=10)
    p.add_argument("--slot", type=int, default=SLOT)
    p.add_argument("--build", default=BUILD, help="the build directory to install into the snapshot")
    p.add_argument("--after", type=int, default=40_000_000,
                   help="instructions to run after the turn, so a queued job can execute")
    args = p.parse_args()

    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_D2, UC_M68K_REG_D3

    machine = Machine(args.snapshot)
    image, sym = load_build(args.build)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    runs = differences(stock, image)
    machine.apply(runs)
    machine.load_code_chunk(code_chunk(image))
    machine.flush()
    print(f"  installed {len(runs)} run(s), {sum(len(b) for _, b in runs):,} B; "
          f"stub at {sym['lfo4_set_stub']:#010x}\n")

    # What the firmware would have written, and what we turned it into.
    arrivals = []
    armed = [False]

    def at_bound(uc, address, size, user):
        if not armed[0]:
            return
        was = uc.reg_read(UC_M68K_REG_D2)
        arrivals.append((was, uc.reg_read(UC_M68K_REG_D3)))
        uc.reg_write(UC_M68K_REG_D2, args.slot)

    machine.uc.hook_add(UC_HOOK_CODE, at_bound, begin=SET_BOUND, end=SET_BOUND)

    writes = collections.Counter()
    machine.watch_writes(VALUES, VALUES + VALUES_LEN - 1,
                         lambda pc, a, v, s: writes.update([(a - VALUES) // 2]))

    # **Who answers a change, counted, with a stock turn as the control.** A
    # null from this snapshot is only evidence if a stock edit is seen to reach
    # the same place: the emulator's boot never builds the project, so the
    # observer that hands Sound::updateMirror a stored record may not exist here
    # at all, and "LFO4's announcement was ignored" would look identical.
    UPDATE_MIRROR, WHOLE_JOB = 0x4004CA80, 0x4004AD10
    seen = collections.Counter()
    machine.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: seen.update(["updateMirror"]),
                        begin=UPDATE_MIRROR, end=UPDATE_MIRROR)
    machine.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: seen.update(["whole-sound job"]),
                        begin=WHOLE_JOB, end=WHOLE_JOB)

    panel = Panel(machine, png_dir="out/lfo4-slots")
    panel.settle(args.warmup)
    panel.tap(MOD)
    print(f"  {panel.screen('page-1')}")

    if "lfo4_announced" in sym:
        seen.clear()
        panel.push_and_turn(0, args.delta)          # a STOCK turn: nothing rewritten
        panel.settle(args.after)
        print(f"  control, a stock turn: updateMirror ran {seen['updateMirror']}, "
              f"whole-sound job {seen['whole-sound job']}")
        control_reached = seen["updateMirror"] > 0
        seen.clear()

    before = dict(writes)
    armed[0] = True
    panel.push_and_turn(0, args.delta)
    armed[0] = False

    sets = machine.long(sym["lfo4_sets"])
    ignored = machine.long(sym["lfo4_sets_ignored"])
    sound = machine.long(sym["lfo4_set_sound"])
    slot = machine.long(sym["lfo4_set_slot"])
    value = machine.long(sym["lfo4_set_value"])
    print(f"\n  the bound saw {len(arrivals)} turn(s): "
          f"{', '.join(f'slot {w} <- {v:#06x}' for w, v in arrivals) or 'none'}")
    print(f"  lfo4_sets {sets}, ignored {ignored}, "
          f"sound {sound:#010x}, slot {slot}, value {value:#06x}")

    check("the turn reached the bound at all", arrivals, "nothing arrived")
    check("every rewritten turn was recorded", sets == len(arrivals),
          f"{sets} recorded, {len(arrivals)} arrived")
    check("it recorded the id we asked for", slot == args.slot, f"slot {slot}")
    check("the sound is the firmware's own, inside the kit",
          KIT <= sound < KIT + 52 + 16 * 1163, f"{sound:#010x}")

    # The table's own report. `ext_set` refuses only three ways -- a zero key,
    # a parameter past the span, or a full table -- and each has a counter, so
    # a silent nothing is distinguishable from a refusal that said why.
    live = machine.long(sym["ext_live"])
    print(f"  table: live {live}, inserts {machine.long(sym['ext_inserts'])}, "
          f"generation {machine.long(sym['ext_generation'])}, "
          f"full {machine.long(sym['ext_full'])}, overflow {machine.long(sym['ext_overflow'])}")

    if sets:
        stored = table_read(machine, sym, sound, 0)
        print(f"  the table's entry for {sound:#010x}, param 0: "
              f"{stored if stored is None else f'{stored:#06x}'}")
        check("the turn reached the table", live >= 1, f"{live} entr(y/ies)")
        check("the table holds what the turn wrote", stored == value,
              f"{stored} in the table, {value:#06x} written")

    # The control for the *reader*: a key nothing has ever set must be absent.
    # Without it, "the value is there" and "this function returns the value
    # whatever you ask it" look identical.
    absent = table_read(machine, sym, sound + 1163, 0)
    check("a key nothing set is absent", absent is None, f"it read back {absent}")

    moved = {slot_: n for slot_, n in writes.items() if before.get(slot_, 0) != n}
    print(f"  live value slots written during the turn: {sorted(moved) or 'none'}")
    check("no slot of the live sound moved", not moved,
          f"slots {sorted(moved)} were written, and above 100 stock writes nothing")

    # **The announcement, for a build that makes one** (setter.c, `announce`).
    # An LFO4 edit sends the stock SoundConfigChangedInfo through the sound's
    # holder, and Sound::updateMirror should answer it by queueing a job that
    # re-serialises this sound through SAVE -- where lfo4_on_save writes the
    # lane. So: did we announce, and after letting the machine run, did a save
    # of this sound happen carrying an LFO4? That is the whole mechanism, and
    # the save count before the turn is the control.
    if "lfo4_announced" in sym:
        saves0 = machine.long(sym["lfo4_saves"])
        carry0 = machine.long(sym["lfo4_saves_carrying"])
        announced = machine.long(sym["lfo4_announced"])
        held = machine.long(sym["lfo4_announce_held"])
        pending = machine.long(sym["lfo4_pending_sound"])
        print(f"\n  announced {announced}, held back {held}, pending {pending:#010x}")
        check("the edit was announced", announced >= 1, "no announcement")
        panel.settle(args.after)
        print(f"  after LFO4's turn: updateMirror ran {seen['updateMirror']}, "
              f"whole-sound job {seen['whole-sound job']}")
        if not control_reached:
            print("  ** the control never reached updateMirror either: this snapshot has no "
                  "observer that writes a stored record, so nothing below is evidence either way **")
        saves = machine.long(sym["lfo4_saves"]) - saves0
        carry = machine.long(sym["lfo4_saves_carrying"]) - carry0
        pending2 = machine.long(sym["lfo4_pending_sound"])
        print(f"  after {args.after:,} more instructions: {saves} save(s), "
              f"{carry} carrying an LFO4; pending now {pending2:#010x}")
        check("the stock chain re-saved the sound", saves >= 1, "no SAVE ran after the announcement")
        check("the re-save carried LFO4", carry >= 1, "saves ran, none carried LFO4")
        check("the pending mark was cleared by that save", pending2 == 0,
              f"still pending on {pending2:#010x}")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
