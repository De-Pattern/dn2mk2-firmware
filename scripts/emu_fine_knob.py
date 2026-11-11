"""v0.48: STRT, LEN and LOOP's knobs against a stock fine control, on the ColdFire emulator
(emu_encoder_trace.py; category 2: the modified ColdFire alone, no DSP).

For each case: the same build, snapshot and turn (counts on one encoder, one every GAP
instructions, a key held or not, the knob's rest counter emptied at its first step), once on
FREQ (FLTR, encoder E, record 36: stock's fine unipolar control; v0.49: at 24 phases of
the turn against the timer wheel, LEADS) and once on the target on
ONESHOT's SRC page (STRT E, LEN F, LOOP G, with fmt.c smp_fine's words). Every knob step
0x4011336e is logged with its inputs (the bundle's delta, the knob's state) and its output
(d0, the change it asks for). The timer wheel cuts the counts into bundles, so the two runs
need not line up; what must hold: **every target step whose inputs a FREQ step also had
asked for the same change**, most steps had such a twin, the value stays in 0..120.00 (held
at 0.00 going down, at 120.00 going up), push + turn moves in whole steps, a plain turn by a
fraction, and the target's value type, formatter and flag are FREQ's.

Cases (CASES): strt, strt-fast, strt-rev, strt-push, strt-func, strt-low, len, len-top, loop.
The gate runs `strt`; `--cases all` the rest. PASS/FAIL on the last line.
Usage: emu_fine_knob.py --build out/v048.syx [--cases all] [--json OUT]"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
MIN_SHARED = 0.6
LEADS = tuple(52_000 * k for k in range(24))   # the FREQ references: 0 .. 23/24 of the wheel's 4-tick flush (1.25 M instructions)


# name: (target slot, encoder, plan, gap, held key or None); the reference is FREQ (FLTR,
# encoder E, slot 67, stock's fine unipolar control) with the same plan, gap and key
CASES = {
    "strt":      (26, 4, "1*24", 1_000_000, None),        # slow, from 0.00
    "strt-fast": (26, 4, "1*24", 50_000, None),           # one bundle of 24
    "strt-rev":  (26, 4, "1*12,-1*12", 200_000, None),    # a reversal mid-turn
    "strt-push": (26, 4, "1*12", 1_000_000, 45),          # the encoder's push held: whole steps
    "strt-func": (26, 4, "1*12", 1_000_000, 17),          # FUNC held through the turn
    "strt-low":  (26, 4, "-1*12", 1_000_000, None),       # down from 0.00: held at 0.00
    "len":       (45, 5, "-1*24", 1_000_000, None),       # down from 120.00
    "len-top":   (45, 5, "1*12", 1_000_000, None),        # up at 120.00: held there
    "loop":      (44, 6, "1*24", 1_000_000, None),        # slow, from 0.00
}
TOP = 0x7800


def run(build, snapshot, out, extra):
    cmd = [sys.executable, "-u", str(HERE / "emu_encoder_trace.py"), "--build", build, "--machine", "8",
           "--rest", "0", "--records", "36,239,257,258", "--regs", "0x400675c4",
           "--json", str(out)] + (["--snapshot", snapshot] if snapshot else []) + extra
    p = subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
    if p.returncode != 0 or not out.exists():
        raise SystemExit(f"FAIL: the trace did not run ({' '.join(extra)}): {(p.stdout + p.stderr)[-800:]}")
    d = json.loads(out.read_text())
    steps = [(e[3], tuple(e[4])) for e in d["log"] if e[0] == "step"]
    outs = [int(e[3][0], 16) for e in d["log"] if e[0] == "regs 0x400675c4"]   # the step's d0: its change
    outs = [o - (1 << 32) if o >> 31 else o for o in outs]
    if len(outs) != len(steps):
        raise SystemExit(f"FAIL: {len(steps)} knob steps but {len(outs)} returns logged")
    return d, steps, outs


def inputs(st):
    """A knob step's inputs, as stock's 0x4011336e reads them (disassembled, 2026-11-11): the
    bundle's delta, the state's acceleration (+8), remainder (+12) and whether its rest counter
    (+16) is above 24 (the guard's branch; below it the counter only gets 48 added). +0 is
    written from 0x40055b3a's tick and never read back here, +4 never touched, so neither is an
    input. (st: (delta, the five state words before the step); the first step's is logged before
    --rest empties it, alike in every run.) The step's other inputs, the parameter's descriptor
    and the flag byte, are the target's own: those are what is compared. Every reference input
    must decide one change (checked), or the key misses one."""
    d, w = st
    return (d, w[2], w[3], w[4] > 24)


def _unused(steps, sets, values, v0):
    """-> [(step inputs, the value change it made)], each knob step paired with its value
    after it (a step that made no change calls no setter)"""
    out, prev = [], v0
    for k, st in enumerate(steps):
        v = values[k] if k < len(values) else prev
        out.append((st, v - prev))
        prev = v
    return out


def one(a, work, name):
    slot, enc, plan, gap, hold = CASES[name]
    common = ["--detents", plan, "--gap", str(gap)] + (["--hold", str(hold if hold != 45 else 41 + 4)] if hold else [])
    # v0.49: the reference at several phases of the turn against the timer wheel's flush
    # (LEADS): which counts the wheel bundles first depends on that phase, and a build whose
    # boot runs a few instructions longer starts the turn at another one (v0.49's STRT run
    # split the first bundle 1 + 1 where FREQ's lead-0 run had 2, so its acceleration ran a
    # step behind and only 1 of 20 steps had a lead-0 twin). Every reference step is stock's
    # own; the rule is unchanged: a target step whose inputs any reference step had must ask
    # for the same change, and most target steps must have such a twin. (A step's inputs are
    # what the stock step reads, inputs(); v0.48 keyed on all five state words, two of which
    # it never reads, so twins that were twins went uncounted.)
    refs = [run(a.build, a.snapshot, work / f"{name}-freq{'' if ld == 0 else f'-{ld}'}.json",
                ["--slot", "67", "--page", "0,2", "--enc", "4", "--lead", str(ld)] + common) for ld in LEADS]
    fd = refs[0][0]
    fch = [x for _, fs_, fo_ in refs for x in zip(fs_, fo_)]
    hold_t = (["--hold", str(41 + enc)] if hold == 45 else (["--hold", str(hold)] if hold else []))
    td, ts, to = run(a.build, a.snapshot, work / f"{name}.json",
                    ["--slot", str(slot), "--page", "0,1", "--enc", str(enc), "--detents", plan, "--gap", str(gap)] + hold_t)
    tch = list(zip(ts, to))
    if a.brk == "offby1":                     # the negative control: every target change one more
        tch = [(st, dv + 1) for st, dv in tch]
    shared, bad = 0, []
    fmap = {}
    for st, dv in fch:
        fmap.setdefault(inputs(st), set()).add(dv)
    for key, outs in fmap.items():         # a twin's inputs must decide its change
        if len(outs) > 1:
            bad.append(f"FREQ's own steps with inputs {key} made {sorted(outs)}: the inputs do not decide it")
    t0, tend = td["start"]["value"], td["end"]["value"]
    for k, (st, dv) in enumerate(tch):
        if inputs(st) in fmap:
            shared += 1
            ok = dv in fmap[inputs(st)]
            if not ok:
                bad.append(f"step {k} {st}: {dv:+d}, FREQ made {sorted(fmap[inputs(st)])}")
    if not 0 <= tend <= TOP:
        bad.append(f"ended outside 0..120.00: {tend:#06x}")
    if name == "strt-low" and tend != 0:
        bad.append(f"down from 0.00 ended at {tend:#06x}, not 0")
    if name == "len-top" and tend != TOP:
        bad.append(f"up at 120.00 ended at {tend:#06x}, not 0x7800")
    if name in ("strt", "loop", "strt-fast") and not (tend > 0 and tend % 256):
        bad.append(f"ended at {tend:#06x}: not a fraction above 0")
    if name == "strt-push" and tend % 256:
        bad.append(f"push + turn ended at {tend:#06x}: not whole steps")
    rec = td.get("records_after", {})
    r, r36 = rec.get(str({26: 239, 45: 258, 44: 257}[slot]), {}), rec.get("36", {})
    if (r.get("type"), r.get("fmt"), r.get("flag")) != (r36.get("type"), r36.get("fmt"), r36.get("flag")):
        bad.append(f"its value type is not FREQ's: {r} vs {r36}")
    if tch and shared < MIN_SHARED * len(tch) and name not in ("strt-low", "len-top"):
        bad.append(f"only {shared} of {len(tch)} steps had a FREQ step's inputs")
    return {"case": name, "target_steps": len(tch), "shared": shared, "start": t0, "end": tend,
            "freq": [fd["start"]["value"], fd["end"]["value"]], "bad": bad}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--snapshot", default=None)
    p.add_argument("--json", default=None)
    p.add_argument("--break", dest="brk", default=None, choices=("offby1",),
                   help="negative control: the target's every change made one more (must FAIL)")
    p.add_argument("--cases", default="strt", help="comma list of " + ",".join(CASES) + ", or all")
    a = p.parse_args()
    names = list(CASES) if a.cases == "all" else a.cases.split(",")
    work = pathlib.Path(a.json or "out/fine_knob.json").with_suffix("")
    work.mkdir(parents=True, exist_ok=True)
    res = []
    for n in names:
        r = one(a, work, n)
        res.append(r)
        print(("  ok    " if not r["bad"] else "  FAIL  ") + f"{n}: {r['target_steps']} steps, {r['shared']} with a "
              f"FREQ step's inputs, {r['start']:#06x} -> {r['end']:#06x} ({r['end'] / 256:.2f}); FREQ "
              f"{r['freq'][0]:#06x} -> {r['freq'][1]:#06x}" + (f"; {'; '.join(r['bad'])}" if r["bad"] else ""), flush=True)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(res, indent=1))
    bad = [r for r in res if r["bad"]]
    print(("FAIL" if bad else "PASS") + f": {len(res) - len(bad)}/{len(res)} cases; every knob step whose inputs a "
          f"stock FREQ step also had made the same change (a bound's clamp aside)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
