"""The idle-time stub in digikit's SHARC runner: FreeRTOS's idle loop, patched, goes round.

    python scripts/sharc_idle_load_check.py [--instructions 40000]

Starts the idle task at the top of its loop (sw 0xb88aab, `dnfw.waverider.dsp`'s
IDLE_RETURN_SW) on the engine-init snapshot with the built section 7, and runs it.
Checks, each against the machine's own state:

- the loop goes round: the top is reached again and again, and nothing outside the
  idle loop, its callee and the stub runs;
- the stub counts every pass (DM 0x2de114) and, on a quiet idle task, adds each
  pass's cycles to the idle total (0x2de110);
- reply word 1 of both reply pages (0x2c49d4, 0x2c59d4) holds that total with its
  halves swapped, as the per-frame handler stores word 0;
- R8, R9 and R10, the only registers it touches, are what they were at every return
  to the loop's top.

The runner's EMUCLK does not advance, so the stub's clock is fed in: right after its
`R8 = EMUCLK` (sw 0x16f514) R8 is set to a counter that steps STEP cycles a pass, with
a GAP-cycle jump every tenth pass (a preemption). The idle total must then be exactly
the sum of the short steps: the gaps left out, the wrap of the counter handled. The
instrument is where the figure means anything.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as m5                                # noqa: E402
from dnfw.waverider import dsp                                  # noqa: E402

PASSES, TOTAL, LAST = 0x2DE114, 0x2DE110, 0x2DE10C
MARK, BEFORE, AFTER, MARK0 = 0x2DE124, 0x2DE128, 0x2DE12C, 0x2DE13C
REPLY_WORD1 = (0x2C49D4, 0x2C59D4)
REPLY_WORD3, REPLY_WORD4 = (0x2C49DC, 0x2C59DC), (0x2C49E0, 0x2C59E0)
SENTINELS = {"R8": 0x11111111, "R9": 0x22222222, "R10": 0x33333333, "R11": 0x44444444}
MARK_INTO_GAP = 3000                               # where the fed MARK (the splice) sits inside each gap
MARK0_INTO_GAP = 1000                              # where the fed MARK0 (the routine's call) sits


def after_emuclk() -> int:
    """The sw address of the instruction after the stub's `R8 = EMUCLK;`, from its object."""
    spec = json.loads((ROOT / "csrc/waverider/sharc/idle_load.json").read_text(encoding="utf-8"))
    src = [ln.split("//", 1)[0].strip() for ln in (ROOT / "csrc/waverider/sharc/idle_load.asm").read_text().splitlines()]
    src = [c for c in src if c and not c.startswith(".") and not c.endswith(":")]
    return dsp.IDLE_SW + spec["instruction_offsets"][src.index("R8 = EMUCLK;") + 1] // 2


def model(fed, marks, marks0):
    """What the stub must leave: (idle total, BEFORE, AFTER), from the fed clock and marks:
    BEFORE adds MARK0 - last, AFTER adds now - MARK, each when that mark is inside the stretch."""
    last = total = before = after = 0
    for now, mark, mark0 in zip(fed, marks, marks0):
        d = (now - last) & 0xFFFFFFFF
        if d < 4096:
            total = (total + d) & 0xFFFFFFFF
        else:
            a = (mark0 - last) & 0xFFFFFFFF
            if a < d:
                before = (before + a) & 0xFFFFFFFF
            c = (now - mark) & 0xFFFFFFFF
            if c < d:
                after = (after + c) & 0xFFFFFFFF
        last = now
    return total, before, after
STEP, GAP, START = 100, 10_000, 0xFFFFF000         # START makes the counter wrap during the run


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                       ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--instructions", type=int, default=40_000)
    a = p.parse_args(argv)
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, dsp.section7(stock))
    tops, pcs, fed, marks, marks0 = [], set(), [], [], []
    at_clock = after_emuclk()
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, image)
        i7 = m5.m2.word_reg(init, "I7")
        r = init.fresh_call(dsp.IDLE_RETURN_SW,
                            regs={"I5": 0x2D0608, "R15": 1, "I6": i7, "I7": i7 - 16, **SENTINELS},
                            return_address=dsp.IDLE_RETURN_SW)

        def at_top(runner):
            tops.append({k: m5.m2.word_reg(runner, k) for k in SENTINELS})

        def feed(runner):
            n = len(fed)
            clock = (START + STEP * n + GAP * (n // 10)) & 0xFFFFFFFF
            fed.append(clock)
            runner.state.uregs[m5.fx.UREG_CODES["R8"]] = m5.fx.Const(clock)
            if n and n % 10 == 0:                  # a gap: the call and the dispatch passed inside it
                m5.m2.poke(runner.state, MARK0, (fed[n - 1] + MARK0_INTO_GAP) & 0xFFFFFFFF)
                m5.m2.poke(runner.state, MARK, (fed[n - 1] + MARK_INTO_GAP) & 0xFFFFFFFF)
            marks.append(m5.m2.word(runner.state, MARK) or 0)
            marks0.append(m5.m2.word(runner.state, MARK0) or 0)

        f = m5.fixups({dsp.IDLE_RETURN_SW: at_top, dsp.IDLE_SW: lambda runner: pcs.add("stub"),
                       at_clock: feed})
        res = m5.fx.run(r, a.instructions, f)
        st = r.state
        passes = m5.m2.word(st, PASSES) or 0
        total = m5.m2.word(st, TOTAL) or 0
        words = [m5.m2.word(st, w) or 0 for w in REPLY_WORD1]
        before, after = m5.m2.word(st, BEFORE) or 0, m5.m2.word(st, AFTER) or 0
        w3 = [m5.m2.word(st, w) or 0 for w in REPLY_WORD3]
        w4 = [m5.m2.word(st, w) or 0 for w in REPLY_WORD4]
    swapped = ((total << 16) | (total >> 16)) & 0xFFFFFFFF
    # the first pass differences against the zeroed LAST word: a gap, left out
    want = sum(d for d in ((b - a) & 0xFFFFFFFF for a, b in zip(fed, fed[1:])) if d < 4096) & 0xFFFFFFFF
    m_total, m_before, m_after = model(fed[:passes], marks[:passes], marks0[:passes])
    sw = lambda v: ((v << 16) | (v >> 16)) & 0xFFFFFFFF
    gaps = sum(1 for n in range(1, passes) if n % 10 == 0)
    wrapped = any(b < a for a, b in zip(fed, fed[1:]))
    print(f"  run ended: {res[0]}; loop tops {len(tops)}, stub passes {passes}, idle total {total}")
    print(f"  reply word 1: {words[0]:#010x} / {words[1]:#010x}   (total swapped {swapped:#010x})")
    print(f"  BEFORE {before}  AFTER {after}  (model {m_before} / {m_after}; gaps {gaps})")
    checks = {
        "the idle loop goes round (its top reached 10+ times)": len(tops) >= 10,
        "the stub ran": "stub" in pcs,
        "the stub counts every pass (passes = loop tops - 1, within 1)": abs(passes - (len(tops) - 1)) <= 1,
        "R8-R11 unchanged at every return to the top": all(t == SENTINELS for t in tops),
        "reply word 1 of both pages holds the idle total, halves swapped":
            words[0] == words[1] == swapped and (total == 0 or words[0] != 0),
        "the idle total is exactly the sum of the short steps (gaps left out)": total == want > 0,
        "the fed clock wrapped during the run, and the total did not jump": wrapped and total == want,
        "BEFORE and AFTER are exactly what the stub's rule gives (model)": (before, after) == (m_before, m_after),
        "each gap put MARK0_INTO_GAP in BEFORE (the first pass's zeroed LAST and marks aside)":
            before == MARK0_INTO_GAP * gaps and gaps > 0,
        "each gap put its tail after MARK in AFTER": after - (m_after - (STEP + GAP - MARK_INTO_GAP) * gaps) >= 0
            and m_after >= (STEP + GAP - MARK_INTO_GAP) * gaps,
        "reply words 3 and 4 of both pages hold BEFORE and AFTER, halves swapped":
            w3[0] == w3[1] == sw(before) and w4[0] == w4[1] == sw(after),
    }
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    bad = [t for t in tops if t != SENTINELS][:3]
    if bad:
        print("  first differing registers:", bad)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
