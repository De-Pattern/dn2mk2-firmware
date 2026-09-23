"""Does LFO4's output actually move frame to frame, or only when something kicks it?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_BUILD=out/lfo4-browser \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_sweep.py [--frames 60]

From the instrument, 2026-09-22:

> "the frequency to when the modulation applies is directly related to how fast
> I re-press the track trigger. The faster I press it, the more frequent the
> modulation is applied."

**That is not intermittency.** Rare-and-random would be a lookup that
sometimes misses. A rate proportional to the press rate means *every* press
produces movement and then it stops until the next one -- which is what an LFO
whose phase is not advancing sounds like. A trig kicks the phase, the kick is
audible, and then it holds.

`emu_lfo4_chain.py` cannot see this. It runs forty frames and reads the mirror
**once at the end**, so it proves the slot was written and that a different
rate reaches a different endpoint. A phase that only moves when kicked would
pass both.

So this samples the modulated slot **after every frame** and prints the
trajectory. A running LFO sweeps; a frozen one sits still or takes one step and
stops. Two rates are run because a single trajectory has nothing to be wrong
against: the faster row must move faster, and if neither moves, neither rate
matters.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build
from emulib.machine import SNAP, Machine

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-browser"))

EVAL_A = 0x40137726
MIRROR_AT, MIRROR_BYTES, TRACKS = 34, 202, 16
STATE = (0x46700000, 0x46701000, 0x46702000)
STATE_LEN = 2560
REST = 0x4000
RATE = 0x402A0DEC
SET_FRAC = bytes.fromhex("a93c000000204e75")      # movel #32,%macsr ; rts
DEST_SLOT = int(os.environ.get("DT2_DEST_SLOT", 76))   # 76 is what tick7 swept audibly
TRACK = int(os.environ.get("DT2_TRACK", 0))            # 0-based; track 5 is 4
LIVE_CONTAINER, SOUND_AT, SOUND_STRIDE = 0x800052A0, 52, 1163

# **`DEP` at maximum is not a good test and that is the first finding.** The
# mirror clamps at `0x7F00`, so a full-depth LFO ramps to the ceiling in a
# frame or ten and then sits there: inaudible as modulation, and the only thing
# you hear is the ramp after whatever reset the phase. `tick7` used
# `DEP 0x7FFE` and took about fourteen bars to be heard on the instrument --
# which is that same effect, not a fast LFO.
#
#            SPD   MULT   FADE   DEST         WAVE   SPH  MODE  DEP
ROWS = (
    ("tick7's row, DEP max",
     (0x7000, 0x0800, 0x4000, DEST_SLOT << 8, 0x0100, 0, 0, 0x7FFE)),
    ("the same at a quarter depth",
     (0x7000, 0x0800, 0x4000, DEST_SLOT << 8, 0x0100, 0, 0, 0x2000)),
    ("quarter depth, a faster multiplier",
     (0x7000, 0x1700, 0x4000, DEST_SLOT << 8, 0x0100, 0, 0, 0x2000)),
    ("quarter depth, the fastest multiplier",
     (0x7F00, 0x1700, 0x4000, DEST_SLOT << 8, 0x0100, 0, 0, 0x2000)),
    # **The instrument's own configuration, 2026-09-22.** `lfo4-meter2` read
    # the row back off the glass on track 5: the exact destination slot chosen,
    # `DEP` at `0x7ffe`, and every value nobody set left at `lfo4_init`'s seed
    # from LFO3's records -- `SPD` 0x7000, `MULT` 0x0300, `FADE` 0x4000,
    # `WAVE` 0. Nothing modulated. This row is that row, so the emulator is
    # asked the same question the instrument was.
    ("the instrument's own row: defaults, DEP at maximum",
     (0x7000, 0x0300, 0x4000, DEST_SLOT << 8, 0x0000, 0, 0, 0x7FFE)),
    ("the same row at a quarter depth",
     (0x7000, 0x0300, 0x4000, DEST_SLOT << 8, 0x0000, 0, 0, 0x2000)),
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--frames", type=int, default=60)
    args = p.parse_args()

    m = Machine(SNAP)
    image, sym = load_build(BUILD)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"],
                              "section_3_MAIN_OS.bin"), "rb").read()
    m.apply(differences(stock, image))
    for load, _n, bss, init, blob in code_chunks(image):
        m.load_code_chunk((load, len(blob), bss, init, blob))
    m.flush()

    base = m.long(LIVE_CONTAINER)
    sound = base + SOUND_AT + SOUND_STRIDE * TRACK
    span = MIRROR_AT + TRACKS * MIRROR_BYTES + 32
    buf = m.alloc(span)
    rest = struct.pack(">H", REST) * (span // 2)
    frac = m.alloc(len(SET_FRAC))
    m.write(frac, SET_FRAC)
    m.call(frac)
    rate = m.long(RATE)
    out1, out2 = m.alloc(256), m.alloc(256)
    at = MIRROR_AT + TRACK * MIRROR_BYTES + DEST_SLOT * 2
    print(f"  the live sound for track {TRACK + 1} is {sound:#010x}; "
          f"watching slot {DEST_SLOT} every frame\n")

    def trajectory(values, label, backup=0):
        """`backup` is the evaluator's seventh argument: its low byte asks for
        a state backup before the walk.

        **Nothing has ever run this path with it set.** `emu_lfo4_tick.py`,
        `emu_lfo4_chain.py` and the first version of this all pass 0. The build
        widens the per-track state stride from `0x78` to `0xa0` to make room
        for a fourth LFO's phase, and if the backup and restore still move the
        old stride then LFO4's phase is restored from stale bytes every frame
        -- frozen except when something else kicks it, which is what the
        instrument reports.
        """
        for slot, value in enumerate(values):
            m.call(sym["ext_set"], sound, slot, value)
        for state in STATE:
            m.write(state, bytes(STATE_LEN))
        seen = []
        for _ in range(args.frames):
            # **Reset the mirror before every frame, not once before all of
            # them.** The evaluator writes modulation *into* the mirror, and
            # the firmware rebuilds it from the parameter base each audio
            # frame. A harness that writes the resting value once and then runs
            # four hundred frames is measuring an accumulator: every row
            # saturates at the clamp within a few frames whatever its depth,
            # which is exactly what the first version of this reported and
            # nearly had recorded as a firmware fault. `emu_lfo4_chain.py` has
            # the same shape and does not show it only because it reads the
            # endpoint once.
            m.write(buf, rest)
            m.call(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, out1, out2, backup)
            seen.append(struct.unpack(">H", m.read(buf + at, 2))[0])
        steps = sum(1 for a, b in zip(seen, seen[1:]) if a != b)
        print(f"  {label}: {seen[:16]}")
        print(f"      {len(set(seen))} distinct value(s) over {args.frames} frame(s), "
              f"{steps} change(s), span {min(seen):#06x}..{max(seen):#06x}")
        return seen, steps

    # The row that is known to be audible, run both ways. Everything else is
    # held constant, so a difference between these two is the backup and
    # nothing else.
    audible = ROWS[0][1]
    results = [("no state backup", *trajectory(audible, "no state backup", backup=0)),
               ("asking for a state backup", *trajectory(audible, "asking for a state backup",
                                                         backup=1))]
    # **The rest of `ROWS` used to be defined and never run**, which is a
    # harness that looks like it tested four configurations and tested one.
    # Found on 2026-09-23 after adding the instrument's own row to the table
    # and reading a log that did not contain it.
    for label, values in ROWS[1:]:
        results.append((label, *trajectory(values, label, backup=0)))

    print()
    # The question is not "does it move" but "does it come back": an LFO turns
    # round, a ramp that pinned at the ceiling does not.
    for label, seen, steps in results:
        rising = max(seen)
        turned = any(b < a for a, b in zip(seen, seen[1:]))
        pinned = seen.count(max(seen))
        print(f"  {label}: {steps} change(s), "
              f"{'turns round' if turned else 'never turns round'}, "
              f"{pinned} of {len(seen)} frame(s) at its maximum {rising:#06x}")
    if not any(turned for _l, seen, _s in results
               for turned in [any(b < a for a, b in zip(seen, seen[1:]))]):
        print("\n  **nothing ever comes back down.** Every row ramps and holds, so")
        print("  what reaches the destination is not an oscillation at all -- and")
        print("  a phase that only moves when something resets it is exactly the")
        print("  instrument's report: one audible ramp per press.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
