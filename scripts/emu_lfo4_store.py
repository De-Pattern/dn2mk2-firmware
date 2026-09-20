"""LFO4 step 2 under the emulator: does a sound keep its LFO4 across save and load?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_lfo4_store.py [--snapshot ...]

`docs/lfo4-build-plan.md` §4 read both converters; step 2 hooks them. The
firmware's own `0x400dd1ea` (stored -> live) and `0x400dd6a6` (live -> stored)
are called here with laid-out arguments -- their real loops, their real maps --
and the eight reserved p-lock ids are read out of the bytes afterwards.

Two questions, in this order:

1. **What does stock 1.11 do with those eight ids?** Asked *before* the build is
   installed, on the same snapshot, so the answer is the instrument's and not
   ours. It settles §8's open question -- whether a stock load and re-save keeps
   or zeroes them -- by measurement rather than by reading the maps.
2. **Does our build carry them, and change nothing else?** The live sound and
   the stored sound our hooks produce are compared byte for byte with stock's,
   so "nothing else" is checked rather than asserted.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from lfo4_harness import PARAMS, SOUND, SNAP, Harness, check, load_build, report  # noqa: E402

LOAD, SAVE = 0x400DD1EA, 0x400DD6A6     # (live, stored) and (stored, live, flag)
STORED, VALUES = 359, 28                # a stored track's stride, and its value block
LFO4_IDS = [4, 8, 12, 16, 20, 24, 28, 32]
MARKS = [0x2A01, 0x2A02, 0x2A03, 0x2A04, 0x2A05, 0x2A06, 0x2A07, 0x2A08]


def stored_sound(h, marks=None, version=3):
    """A stored track the converter will accept: magic, version, name, values."""
    at = h.alloc(STORED + 16)
    h.write(at, b"\xbe\xef\xba\xce" + version.to_bytes(4, "big"))
    h.write(at + 12, b"LFO4 TEST\0")
    for i in range(107):                       # every id a value of its own, so a
        h.write(at + VALUES + 2 * i, bytes([0x40, i]))   # misplaced word is visible
    for k, v in enumerate(marks or []):
        h.write(at + VALUES + 2 * LFO4_IDS[k], v.to_bytes(2, "big"))
    return at


def ids_of(h, at):
    """The eight reserved ids, as words, out of a stored sound."""
    return [int.from_bytes(h.read(at + VALUES + 2 * i, 2), "big") for i in LFO4_IDS]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", default=SNAP)
    args = p.parse_args()
    h = Harness(args.snapshot, *load_build())
    print(f"stock {args.snapshot}\n")

    # --- 1. what stock does, before anything of ours is installed ------------
    src = stored_sound(h, MARKS)
    live_stock = h.alloc(SOUND)
    h.call(LOAD, live_stock, src)
    slot0 = int.from_bytes(h.read(live_stock + 0x14, 2), "big")
    slots = [int.from_bytes(h.read(live_stock + 0x14 + 2 * s, 2), "big") for s in range(101)]
    check("stock loads a sound carrying the eight ids without complaint",
          h.read(live_stock + 4, 9) == b"LFO4 TEST", h.read(live_stock + 4, 9).hex())
    landed = sorted(s for s, v in enumerate(slots) if v in MARKS)
    check("stock folds the eight onto slot 0 and keeps none of them as a value",
          landed in ([], [0]), f"slot 0 holds 0x{slot0:04x}; slots {landed} hold one of ours")

    back_stock = h.alloc(STORED + 16)
    stock_save = h.cost(SAVE, back_stock, live_stock, 0)[1]
    stock_load = h.cost(LOAD, h.alloc(SOUND), src)[1]
    kept = ids_of(h, back_stock)
    check("and a stock re-save leaves every one of them zero",
          kept == [0] * PARAMS, f"{[hex(v) for v in kept]}")
    print("    -> §8's open question is answered: a stock load and re-save does NOT\n"
          "       keep the reserved ids. They survive being stored, not being reloaded.\n")

    # --- 2. the same two calls, with our build in --------------------------
    h.install()
    print(f"code at 0x{h.load:08x}, every site patched\n")

    live = h.alloc(SOUND)
    h.call(LOAD, live, src)
    check("our load puts the eight into the table", h.get(live) == MARKS, f"{[hex(v) for v in h.get(live)]}")
    check("and the live sound it produced is byte for byte stock's",
          h.read(live, SOUND) == h.read(live_stock, SOUND))
    check("the load was counted, and counted as carrying",
          (h.u32("lfo4_loads"), h.u32("lfo4_loads_carrying")) == (1, 1),
          f"{h.u32('lfo4_loads')} loads, {h.u32('lfo4_loads_carrying')} carrying")

    back = h.alloc(STORED + 16)
    h.call(SAVE, back, live, 0)
    check("our save writes the eight back", ids_of(h, back) == MARKS, f"{[hex(v) for v in ids_of(h, back)]}")
    stock_bytes, ours = bytearray(h.read(back_stock, STORED)), bytearray(h.read(back, STORED))
    for i in LFO4_IDS:                          # blank the eight and the rest must match
        stock_bytes[VALUES + 2 * i:VALUES + 2 * i + 2] = b"\0\0"
        ours[VALUES + 2 * i:VALUES + 2 * i + 2] = b"\0\0"
    check("and changes nothing else in the stored sound", bytes(stock_bytes) == bytes(ours),
          f"{sum(a != b for a, b in zip(stock_bytes, ours))} other byte(s) differ")

    # --- a round trip, which is the step's actual question ------------------
    h.reset()
    live2 = h.alloc(SOUND)
    h.set(live2, MARKS)
    out = h.alloc(STORED + 16)
    h.call(SAVE, out, live2, 0)
    h.reset()                                   # the table is gone, as after a power cycle
    live3 = h.alloc(SOUND)
    h.call(LOAD, live3, out)
    check("save, lose the table, load: the eight values come back", h.get(live3) == MARKS,
          f"{[hex(v) for v in h.get(live3)]}")

    # --- a sound with no LFO4, which is every stock sound -------------------
    h.reset()
    plain = stored_sound(h)                     # the reserved ids left at 0x4000-ish pattern
    for k in range(PARAMS):                     # ... explicitly zeroed, as a stock sound has them
        h.write(plain + VALUES + 2 * LFO4_IDS[k], b"\0\0")
    live4 = h.alloc(SOUND)
    h.call(LOAD, live4, plain)
    check("a stock sound loads to no entry at all, not an entry of zeros",
          h.u32("ext_live") == 0 and h.get(live4) == [0] * PARAMS, f"{h.u32('ext_live')} live")
    out2 = h.alloc(STORED + 16)
    h.call(SAVE, out2, live4, 0)
    check("and saving it leaves the eight ids zero, as stock leaves them",
          ids_of(h, out2) == [0] * PARAMS, f"{[hex(v) for v in ids_of(h, out2)]}")

    # --- what it costs ------------------------------------------------------
    h.reset()
    live5 = h.alloc(SOUND)
    h.set(live5, MARKS)
    _, save_cost = h.cost(SAVE, h.alloc(STORED + 16), live5, 0)
    _, load_cost = h.cost(LOAD, h.alloc(SOUND), src)
    print(f"\n  cost, instructions per call    save {stock_save:,} -> {save_cost:,} "
          f"(+{save_cost - stock_save}),  load {stock_load:,} -> {load_cost:,} (+{load_cost - stock_load})")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
