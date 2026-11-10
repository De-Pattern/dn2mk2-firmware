"""v0.48: STRT's knob against a stock fine control, on the ColdFire emulator (emu_encoder_trace).

The same build, the same snapshot, the same turn (TURN counts on encoder E, one every GAP
instructions, the knob's rest counter emptied at its first step): once on FREQ (the FLTR
page, record 36, stock's fine unipolar control) and once on STRT (track 0 on ONESHOT, the
SYN page, record 239 with smp_fine's words). Each knob step 0x4011336e is logged with its
inputs (the record's delta and the knob state before it) and the value change the setter
made. The flush that cuts the counts into records follows the timer wheel, so the two runs'
records need not line up; what must hold is that **every STRT step whose inputs a FREQ step
also had made the same change**, that most did (MIN_SHARED), that no step ran without its
setter, and that STRT ended above 0 by a fraction (not whole steps).

PASS/FAIL on the last line; the exit code is 0 only on PASS.
Usage: emu_fine_knob.py --build out/v048.syx [--json OUT]"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
TURN, GAP, MIN_SHARED = "1*24", "1000000", 0.6


def run(build, snapshot, out, extra):
    cmd = [sys.executable, "-u", str(HERE / "emu_encoder_trace.py"), "--build", build, "--machine", "8",
           "--enc", "4", "--rest", "0", "--detents", TURN, "--gap", GAP, "--records", "36,239",
           "--json", str(out)] + (["--snapshot", snapshot] if snapshot else []) + extra
    p = subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
    if p.returncode != 0 or not out.exists():
        raise SystemExit(f"FAIL: the trace did not run ({' '.join(extra)}): {(p.stdout + p.stderr)[-800:]}")
    d = json.loads(out.read_text())
    steps = [(e[3], tuple(e[4])) for e in d["log"] if e[0] == "step"]
    sets = [int(e[3][2], 16) for e in d["log"] if e[0] == "setter"]
    return d, steps, sets


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--snapshot", default=None)
    p.add_argument("--json", default=None)
    a = p.parse_args()
    work = pathlib.Path(a.json or "out/fine_knob.json").with_suffix("")
    work.mkdir(parents=True, exist_ok=True)
    fd, fs, fv = run(a.build, a.snapshot, work / "freq.json", ["--slot", "67", "--page", "0,2"])
    sd, ss, sv = run(a.build, a.snapshot, work / "strt.json", ["--slot", "26", "--page", "0,1"])
    bad = []
    if len(fs) != len(fv) or len(ss) != len(sv):
        bad.append(f"a step without its setter: FREQ {len(fs)} steps {len(fv)} sets, STRT {len(ss)} steps {len(sv)} sets")
    f0, s0 = fd["start"]["value"], sd["start"]["value"]
    fmap = {}
    for k, (step, v) in enumerate(zip(fs, fv)):
        fmap.setdefault(step, set()).add(v - (fv[k - 1] if k else f0))
    shared = 0
    for k, (step, v) in enumerate(zip(ss, sv)):
        dv = v - (sv[k - 1] if k else s0)
        if step in fmap:
            shared += 1
            if dv not in fmap[step]:
                bad.append(f"STRT step {k} {step}: {dv:+d}, FREQ made {sorted(fmap[step])}")
    rec = sd.get("records_after", {})
    r239, r36 = rec.get("239", {}), rec.get("36", {})
    if not r239 or (r239.get("type"), r239.get("fmt"), r239.get("flag")) != (r36.get("type"), r36.get("fmt"), r36.get("flag")):
        bad.append(f"STRT's value type is not FREQ's: {rec}")
    end = sd["end"]["value"]
    if not (0 < end and end % 256):
        bad.append(f"STRT ended at {end:#06x}: not a fraction above 0")
    if not ss or shared < MIN_SHARED * len(ss):
        bad.append(f"only {shared} of {len(ss)} STRT steps had a FREQ step's inputs")
    out = {"freq": {"steps": fs, "values": fv, "start": f0}, "strt": {"steps": ss, "values": sv, "start": s0},
           "shared": shared, "bad": bad}
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(out, indent=1))
    if bad:
        print("FAIL: " + "; ".join(bad))
        return 1
    print(f"PASS: {len(ss)} STRT knob steps, {shared} with a FREQ step's very inputs, each the same change; "
          f"STRT {s0:#06x} -> {end:#06x} ({end / 256:.2f}), FREQ {f0:#06x} -> {fv[-1] if fv else f0:#06x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
