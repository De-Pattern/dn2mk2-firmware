"""The PyPy cross-check (2026-11-12, owner: "Yes, with a cross-check"; docs/gate-speed.md).

The gate runs the SHARC emulator's steps (the SHARC runner's parts, the coupled THRES and FLEX)
under PyPy. This reruns each of them under CPython, on the same build, and compares what each
wrote with the gate's own reports:

- the SHARC runner: m5_report_part_*.json (every field but `wall_s`, the run's own timing) and
  every frame WAV, byte for byte;
- THRES and FLEX: their JSON reports, every field; floating-point numbers that are computed
  from the emulation afterwards (correlations, levels) equal to 1e-12 relative, everything else
  exact; the work folder's path, which they record, normalised.

It does not clear or block a build: it is the check that PyPy changes nothing. Run it in the
background after a gate (each part is resumable: a part whose comparison is already written is
skipped), e.g.

    DT2_SECTIONS=../sec111 python3 scripts/gate_crosscheck.py STOCK BUILD.syx GATE_WORK_DIR

GATE_WORK_DIR is the gate's out/ship_gate_* folder with thres.json and flex.json. Prints
`CROSS-CHECK SAME` when every report matched, `CROSS-CHECK DIFFERS` (exit 1) otherwise; the
per-part results are in out/crosscheck/SHA16/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import gate_sharc  # noqa: E402

WAV = ROOT / "out" / "waverider"
WORKPATH = re.compile(r"/[^\s\"']*/out/(ship_gate_[A-Za-z0-9_]+|crosscheck/[0-9a-f]+/[a-z]+)")


def norm(s: str) -> str:
    return WORKPATH.sub("WORK", s)


def diff(a, b, path="", tol=0.0, skip=("wall_s",)) -> list[str]:
    """Differences between two JSON values (A the gate's, B CPython's)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k in skip:
                continue
            if k not in a or k not in b:
                out.append(f"{path}/{k}: only in {'the gate' if k in a else 'CPython'}")
            else:
                out += diff(a[k], b[k], f"{path}/{k}", tol, skip)
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} items vs {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, f"{path}[{i}]", tol, skip)]
    if isinstance(a, float) and isinstance(b, float) and tol:
        same = a == b or (math.isnan(a) and math.isnan(b)) or math.isclose(a, b, rel_tol=tol, abs_tol=0)
        return [] if same else [f"{path}: {a!r} vs {b!r}"]
    if isinstance(a, str) and isinstance(b, str):
        return [] if norm(a) == norm(b) else [f"{path}: {a[:80]!r} vs {b[:80]!r}"]
    return [] if a == b and type(a) is type(b) else [f"{path}: {a!r} vs {b!r}"]


def run(cmd, log: pathlib.Path, env=None) -> int:
    with open(log, "w") as f:
        f.write("$ " + " ".join(map(str, cmd)) + "\n")
        f.flush()
        return subprocess.call([str(c) for c in cmd], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                               env={**os.environ, **(env or {})})


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("stock", type=pathlib.Path)
    p.add_argument("build", type=pathlib.Path)
    p.add_argument("work", type=pathlib.Path, help="the gate's out/ship_gate_* folder")
    p.add_argument("--venv", default=str(ROOT.parent / "digikit/.venv/bin/python"),
                   help="CPython with digikit's emulator deps (the coupled tests)")
    p.add_argument("--digikit-sharc", default=os.environ.get(
        "DNFW_DIGIKIT_SHARC", str(ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--only", help="comma-separated: sharc, thres, flex (default all)")
    a = p.parse_args()

    sha = hashlib.sha256(a.build.read_bytes()).hexdigest()
    out = ROOT / "out" / "crosscheck" / sha[:16]
    out.mkdir(parents=True, exist_ok=True)
    want = set((a.only or "sharc,thres,flex").split(","))
    results: dict[str, list[str]] = {}

    def done(name, diffs):
        (out / f"{name}.json").write_text(json.dumps({"same": not diffs, "diffs": diffs[:200]}, indent=2))
        results[name] = diffs
        print(f"  {name}: {'same' if not diffs else f'{len(diffs)} DIFFER: ' + '; '.join(diffs[:3])}", flush=True)

    def earlier(name):
        f = out / f"{name}.json"
        if f.exists():
            r = json.loads(f.read_text())
            results[name] = r["diffs"]
            print(f"  {name}: {'same' if r['same'] else 'DIFFERS'} (compared earlier)", flush=True)
            return True
        return False

    if "sharc" in want:
        for steps in gate_sharc.parts():
            name = "sharc_" + "_".join(steps)
            if earlier(name):
                continue
            gtag, ctag = "part_" + "_".join(steps), "cpy_" + "_".join(steps)
            gate_rep = WAV / f"m5_report_{gtag}.json"
            if not gate_rep.exists():
                done(name, [f"no gate report {gate_rep.name}"])
                continue
            rc = run(gate_sharc.command(a.stock, a.digikit_sharc, steps, ctag, python=sys.executable),
                     out / f"{name}.log")
            cpy_rep = WAV / f"m5_report_{ctag}.json"
            if rc != 0 or not cpy_rep.exists():
                done(name, [f"CPython's run failed (rc {rc}): {out / (name + '.log')}"])
                continue
            g, c = json.loads(gate_rep.read_text()), json.loads(cpy_rep.read_text())
            d = diff(g, c, skip=("wall_s", "wavs"))
            gw = sorted(f.name[len(f"m5_frame_{gtag}_"):] for f in WAV.glob(f"m5_frame_{gtag}_*.wav"))
            cw = sorted(f.name[len(f"m5_frame_{ctag}_"):] for f in WAV.glob(f"m5_frame_{ctag}_*.wav"))
            if gw != cw:
                d.append(f"frame WAVs: {len(gw)} vs {len(cw)} ({sorted(set(gw) ^ set(cw))[:4]})")
            for s in set(gw) & set(cw):
                if (WAV / f"m5_frame_{gtag}_{s}").read_bytes() != (WAV / f"m5_frame_{ctag}_{s}").read_bytes():
                    d.append(f"frame WAV {s} differs")
            done(name, d)

    snap = ROOT.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"
    env = {"DT2_MAIN_IMG": str(pathlib.Path(os.environ["DT2_SECTIONS"]) / "section_3_MAIN_OS.bin"),
           "DNFW_EMU_FLAGS": '{"weakptr": false}', "DNFW_LOWTRAP": "1"}     # the gate's EMU_ENV
    for name, script in (("thres", "emu_coupled_thres.py"), ("flex", "emu_coupled_flex.py")):
        if name not in want or earlier(name):
            continue
        gate_js = a.work / f"{name}.json"
        if not gate_js.exists():
            done(name, [f"no gate report {gate_js}"])
            continue
        cpy_js = out / f"{name}.cpython.json"
        rc = run([a.venv, "-u", f"scripts/{script}", "--build", a.build, "--stock", a.stock,
                  "--snapshot", snap, "--json", cpy_js], out / f"{name}.log", env)
        if rc != 0 or not cpy_js.exists():
            done(name, [f"CPython's run failed (rc {rc}): {out / (name + '.log')}"])
            continue
        done(name, diff(json.loads(gate_js.read_text()), json.loads(cpy_js.read_text()), tol=1e-12))

    bad = [k for k, v in results.items() if v]
    print(("CROSS-CHECK SAME: every report the same under CPython" if not bad else
           f"CROSS-CHECK DIFFERS: {', '.join(bad)}") + f"  ({out})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
