"""Run LFO3 and LFO4 side by side through the same evaluator, same frames.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_BUILD=out/lfo4-meterkeep \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_vs_lfo3.py [--frames 240]

**Why this shape.** By 2026-09-23 everything about LFO4 that could be measured
separately has been, and none of it explains the instrument: the row the engine
holds is correct and continuously present, nothing removes it, and driving
evaluator A directly produces a clean oscillation -- 119 changes over 120
frames on the owner's own track and destination. Yet on hardware it is binary
per note while **LFO3, on the same track and the same destination, sweeps every
time**.

`emu_lfo4_sweep.py` cannot see that, because it drives LFO4 alone. Its mirror
is filled with the resting `0x4000` every frame, which leaves LFO1-3 with a
`DEST` byte of `0x40` and a `DEP` of exactly centre -- so they contribute
nothing and there is nothing to compare against. **A trajectory with nothing
beside it is the same mistake as a hardware negative with no control**
(`docs/lfo4-build-plan.md`, the three flashes that had to be re-run).

So this configures **both**: LFO3 through the mirror, where the firmware puts
its parameters, and LFO4 through `ext_set`, where ours live. Same track, same
frame, adjacent destinations, everything else identical. Then it prints the two
trajectories together.

  * **identical in character** -- the emulator cannot reproduce the fault, and
    the remaining difference really is note-on, which no harness here has ever
    run. That is a null worth having, because it is the one that justifies the
    cost of driving the sequencer.
  * **LFO4 diverges** -- stalls, or steps where LFO3 turns, or stops after N
    frames -- then the fault is offline after all and it can be bisected
    without another flash.

**Where LFO3's parameters go, and why in the buffer rather than through a
setter.** An LFO's eight parameters are mirror slots `8*lfo+1 .. 8*lfo+8`
(`docs/lfo4-build-plan.md` §5k), so LFO3 owns 17..24 -- which the record table
confirms independently: LFO3 `SPD` carries `+12 = 17` and `DEP` carries 24. The
evaluator reads them at `%a4@(68..83)` with `%a4` set to the track's block minus
34, and `base - 34 + 68 = base + 34 = 2*17`. The harness writes them straight
into the mirror it refills each frame, which is exactly where the frame builder
would have put them.
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
                     os.environ.get("DT2_BUILD", "out/lfo4-meterkeep"))

EVAL_A = 0x40137726
MIRROR_AT, MIRROR_BYTES, TRACKS = 34, 202, 16
STATE = (0x46700000, 0x46701000, 0x46702000)
STATE_LEN = 2560
REST = 0x4000
RATE = 0x402A0DEC
SET_FRAC = bytes.fromhex("a93c000000204e75")      # movel #32,%macsr ; rts
LIVE_CONTAINER, SOUND_AT, SOUND_STRIDE = 0x800052A0, 52, 1163

TRACK = int(os.environ.get("DT2_TRACK", 0))
LFO3_SLOT0 = 17                                   # 8*2 + 1
LFO3_DEST = 66                                    # adjacent cells, so neither
LFO4_DEST = 67                                    # stacks into the other

#      SPD     MULT    FADE    DEST          WAVE  SPH MODE DEP
ROW3 = (0x7000, 0x0300, 0x4000, LFO3_DEST << 8, 0x0000, 0, 0, 0x6000)
ROW4 = (0x7000, 0x0300, 0x4000, LFO4_DEST << 8, 0x0000, 0, 0, 0x6000)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--frames", type=int, default=240)
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
    frac = m.alloc(len(SET_FRAC))
    m.write(frac, SET_FRAC)
    m.call(frac)
    rate = m.long(RATE)
    out1, out2 = m.alloc(256), m.alloc(256)

    # LFO4's eight go in our table; LFO3's go in the mirror, refilled below.
    for slot, value in enumerate(ROW4):
        m.call(sym["ext_set"], sound, slot, value)
    for state in STATE:
        m.write(state, bytes(STATE_LEN))

    block = MIRROR_AT + TRACK * MIRROR_BYTES
    resting = bytearray(struct.pack(">H", REST) * (span // 2))
    for k, value in enumerate(ROW3):                     # LFO3 into the mirror
        at = block + 2 * (LFO3_SLOT0 + k)
        resting[at:at + 2] = struct.pack(">H", value)

    print(f"  track {TRACK + 1}, sound {sound:#010x}; "
          f"LFO3 -> slot {LFO3_DEST}, LFO4 -> slot {LFO4_DEST}; "
          f"{args.frames} frames\n")

    at3 = block + 2 * LFO3_DEST
    at4 = block + 2 * LFO4_DEST
    seen3: list[int] = []
    seen4: list[int] = []
    for _ in range(args.frames):
        m.write(buf, bytes(resting))          # every frame -- see emu_lfo4_sweep.py
        m.call(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, out1, out2, 0)
        seen3.append(struct.unpack(">H", m.read(buf + at3, 2))[0])
        seen4.append(struct.unpack(">H", m.read(buf + at4, 2))[0])

    def report(label: str, seen: list[int]) -> tuple[int, bool]:
        steps = sum(1 for a, b in zip(seen, seen[1:]) if a != b)
        turned = any(b < a for a, b in zip(seen, seen[1:]))
        print(f"  {label}: {seen[:12]}")
        print(f"      {len(set(seen))} distinct, {steps} change(s) over {len(seen)}, "
              f"{'turns round' if turned else 'NEVER TURNS ROUND'}, "
              f"span {min(seen):#06x}..{max(seen):#06x}")
        return steps, turned

    steps3, turn3 = report("LFO3 (firmware's own parameters)", seen3)
    steps4, turn4 = report("LFO4 (ours, through ext_set)     ", seen4)

    print()
    if steps3 == 0:
        print("  **LFO3 did not move either.** The control failed, so nothing here")
        print("  says anything about LFO4. Fix the setup before reading the rest.")
        return 2
    if steps4 == 0:
        print("  **LFO3 moves and LFO4 does not** -- the fault reproduces offline.")
        return 1
    ratio = steps4 / steps3
    same = 0.8 <= ratio <= 1.25 and turn3 == turn4
    print(f"  LFO3 {steps3} change(s), LFO4 {steps4} -- ratio {ratio:.2f}, "
          f"{'same character' if same else 'DIFFERENT character'}")
    if same:
        print()
        print("  The two are indistinguishable under this harness. Whatever gates")
        print("  LFO4 on the instrument is not in the evaluator, and the remaining")
        print("  difference is note-on -- which nothing here has ever run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
