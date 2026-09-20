"""LFO4 step 3 under the emulator: does each track get its own fourth LFO?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_lfo4_tick.py [--frames 400]

`scripts/build_lfo4_tick7.py` gives every track its own row of LFO4 parameters
and makes both evaluators index it. The question it asks is whether that
actually produces *different modulation per track*, and the evaluator can be
asked directly rather than through a flash and a listen.

A snapshot is restored, the build's bytes are written in -- only where they
differ from stock, so what runs is the patched firmware and nothing else -- and
evaluator A (`0x40137726`) is entered with a laid-out parameter mirror and the
relocated state arrays zeroed. Its own code runs from there: the generator, the
MAC-unit apply, the state walk.

**The observable is the thing itself.** `DEST` is a slot index into the same
per-track mirror (`docs/lfo4-build-plan.md` §5k), so after N frames the
modulation shows up as slot 76 of each track having moved away from where it
started. The build gives track 1 a fast LFO4, track 2 the same one slowed down,
and every other track `DEST = 0` -- the no-destination sink. So:

- tracks 1 and 2 must move slot 76, **by different amounts**;
- every other track must write slot 0 instead -- the sink -- and nothing else;
- so the whole buffer must show **exactly sixteen** changed words, one per
  track, which is a stronger check than looking at three of them.

The evaluator's first argument is not the mirror itself: its prologue does
`lea %a0@(34),%a0`, so the sixteen 202-byte rows start **34 bytes in**. That
was found by letting it run and diffing the buffer, not by assuming.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from lfo4_harness import SNAP, Machine, check, report  # noqa: E402

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
BUILT = f"{ROOT}/out/lfo4-tick7/section_3_MAIN_OS.bin"
BASE = 0x40000400

EVAL_A = 0x40137726
MIRROR_SLOTS, MIRROR_BYTES = 101, 202
STATE = (0x46700000, 0x46701000, 0x46702000)   # live, second, backup (v6a's relocation)
STATE_LEN, STATE_STRIDE = 2560, 160
TRACKS = 16
DEST_SLOT = 76                                  # what the build points LFO4 at
REST = 0x4000                                   # every slot starts centred
MIRROR_AT = 34                                  # the prologue's `lea %a0@(34),%a0`

# The seven arguments, read off the firmware's own call at 0x400272a4:
#   1 the parameter mirror           5 a scratch pointer (an out-parameter)
#   2 [0x402a0dec], a global scale   6 another
#   3 a per-track enable mask        7 a flag whose low byte asks for a state
#   4 a second mask                    backup before the walk
RATE = 0x402A0DEC

# The evaluator asserts `GET_MACSR_MODE() == MACF_FRAC` (../../../lib/shared/sm/
# fade.c:16, getFadeStep) -- it expects its caller to have put the EMAC in
# fractional mode, which the audio-frame function does and a bare snapshot has
# not. Evaluator B sets it itself at 0x401373f0. Unicorn does not expose MACSR,
# so it is set the way the firmware sets it: by running the instruction.
SET_FRAC = bytes.fromhex("a93c000000204e75")      # movel #32,%macsr ; rts


def differences(stock: bytes, built: bytes):
    """-> [(virtual address, bytes)] for every run the build changed."""
    if len(stock) != len(built):
        raise SystemExit(f"section lengths differ: {len(stock):,} vs {len(built):,}")
    runs, start = [], None
    for i in range(len(stock) + 1):
        same = i == len(stock) or stock[i] == built[i]
        if not same and start is None:
            start = i
        elif same and start is not None:
            runs.append((BASE + start, built[start:i]))
            start = None
    return runs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--frames", type=int, default=40, help="calls to the evaluator")
    args = p.parse_args()

    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    runs = differences(stock, open(BUILT, "rb").read())
    m = Machine(args.snapshot)
    for va, blob in runs:
        m.write(va, blob)
    m.flush()
    print(f"{len(runs)} changed run(s), {sum(len(b) for _, b in runs)} byte(s) into the snapshot")

    span = MIRROR_AT + TRACKS * MIRROR_BYTES + 32
    buf = m.alloc(span)
    rest = struct.pack(">H", REST) * (span // 2)
    m.write(buf, rest)
    for base in STATE:
        m.write(base, bytes(STATE_LEN))

    frac = m.alloc(len(SET_FRAC))
    m.write(frac, SET_FRAC)
    m.call(frac)
    rate = m.long(RATE)
    out1, out2 = m.alloc(256), m.alloc(256)
    print(f"entering {EVAL_A:#010x} {args.frames} time(s), scale {rate:#06x}\n")
    for _ in range(args.frames):
        m.call(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, out1, out2, 0)

    after = m.read(buf, span)
    written = {}
    for off in range(0, span - 1, 2):
        if after[off:off + 2] != rest[off:off + 2]:
            track, rem = divmod(off - MIRROR_AT, MIRROR_BYTES)
            written[(track, rem // 2)] = struct.unpack(">H", after[off:off + 2])[0]

    for (track, slot), value in sorted(written.items())[:4]:
        print(f"  track {track + 1:<2} slot {slot:<3} -> {value:#06x}")
    print(f"  ... {len(written)} word(s) written in all\n")

    modulated = {track: value for (track, slot), value in written.items() if slot == DEST_SLOT}
    sunk = sorted(track for (track, slot) in written if slot == 0)

    check("exactly one word per track was written", len(written) == TRACKS, f"{len(written)}")
    check("tracks 1 and 2 wrote their own destination, slot 76",
          sorted(modulated) == [0, 1], f"{sorted(t + 1 for t in modulated)}")
    check("and to different values -- the two rows are not shared",
          len(set(modulated.values())) == 2,
          " vs ".join(f"{v:#06x}" for v in modulated.values()))
    check("every other track wrote slot 0, the no-destination sink",
          sunk == list(range(2, TRACKS)), f"{len(sunk)} track(s)")

    records = [m.read(STATE[0] + t * STATE_STRIDE + 40 * 3, 40) for t in range(3)]
    check("the three tracks' LFO4 state records differ from each other",
          len(set(records)) == 3)
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
