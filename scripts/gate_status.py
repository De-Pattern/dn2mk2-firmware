"""The patcher's build status box (dn2mk2 patcher.html, the MOD's step 6): a gate's progress as
status.json on this repository's `gate-status` branch, which the page reads every 30 s.

    python3 scripts/gate_status.py --wt ../status-wt \
        --gate "v0.76 FLOW · full gate|/path/full.log|69" [--gate "LABEL|LOG|TOTAL" ...] \
        [--note "Plan: ..."] [--every 180] [--once]

Each --gate is a label, the ship gate's log (its stdout) and the number of checks a full run
prints (0 for a step run: the box then counts passes). It reads the log only: the gate itself is
not touched, so no step's reuse record changes. Every EVERY seconds, when status.json would
differ, it commits it on the gate-status worktree WT and pushes (never forced). It stops on its
own once every gate's log has ended (between, a heartbeat every 10 min keeps "updated" fresh
through a long step) (CLEARED TO FLASH, a partial run's end, or a failure), after
one last push.

The branch is public: labels and notes carry version names and check names only."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import time

GIT_ID = ["-c", "user.name=De-Pattern", "-c", "user.email=239624238+De-Pattern@users.noreply.github.com"]
SCRIPT = re.compile(r"scripts/(?:emu_|gate_)?([A-Za-z0-9_]+)\.py")
JSON_OUT = re.compile(r"--json \S*/([A-Za-z0-9_.-]+)\.json")      # the step's own record (names it best)


def parse(label: str, log: pathlib.Path, total: int) -> dict:
    try:
        text = log.read_text(errors="replace")
    except OSError:
        return {"label": label, "state": "d", "frac": 0, "done": 0, "total": total,
                "status": "waiting for the gate to start", "last": [], "ended": False}
    passes, fails, running = [], [], None
    for line in text.splitlines():
        if line.startswith("[PASS] "):
            passes.append(line[7:].split(":", 1)[0].strip())
            running = None
        elif line.startswith("[FAIL] "):
            fails.append(line[7:].split(":", 1)[0].strip())
        elif line.startswith("  $ "):
            m = JSON_OUT.search(line) or SCRIPT.search(line)
            running = m.group(1) if m else "a step"
    done = len(passes)
    g = {"label": label, "done": done, "total": total, "last": passes[-3:], "ended": False}
    if "CLEARED TO FLASH:" in text:
        g.update(state="ok", frac=1, status="CLEARED TO FLASH", ended=True)
        if total:
            g["done"] = total
    elif fails:
        g.update(state="bad", frac=done / total if total else 1,
                 status=f"stopped: {fails[0]} failed (fixing, then a new run)", ended=True)
    elif "A PARTIAL RUN" in text:
        g.update(state="ok", frac=1, status="finished (partial run: passes recorded)", ended=True)
    else:
        g.update(state="run", frac=min(done / total, 0.99) if total else min(done / 40, 0.99),
                 status=f"running: {running}" if running else "running")
    return g


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--wt", required=True, help="a worktree of the gate-status branch")
    p.add_argument("--gate", action="append", required=True, help="LABEL|LOG|TOTAL")
    p.add_argument("--note", default="")
    p.add_argument("--every", type=int, default=180)
    p.add_argument("--once", action="store_true")
    a = p.parse_args()
    wt = pathlib.Path(a.wt)
    gates = []
    for spec in a.gate:
        label, log, total = spec.split("|")
        gates.append((label, pathlib.Path(log), int(total)))
    last, pushed = None, 0.0
    while True:
        gs = [parse(*g) for g in gates]
        body = {"gates": [{k: v for k, v in g.items() if k != "ended"} for g in gs], "note": a.note}
        if body != last or time.time() - pushed > 600:   # a heartbeat every 10 min: the page
            last, pushed = body, time.time()            # calls 20 min old "no gate reporting"
            out = dict(body, updated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
            (wt / "status.json").write_text(json.dumps(out, indent=1) + "\n")
            subprocess.run(["git", "-C", str(wt), "add", "status.json"], check=True)
            msg = "status: " + "; ".join(f"{g['label']} {g['done']}" + (f"/{g['total']}" if g["total"] else "")
                                         + f" {g['status']}" for g in gs)
            if subprocess.run(["git", "-C", str(wt), "diff", "--cached", "--quiet"]).returncode:
                subprocess.run(["git", "-C", str(wt), *GIT_ID, "commit", "-q", "-m", msg], check=True)
                r = subprocess.run(["git", "-C", str(wt), "push", "-q", "origin", "gate-status"])
                print(time.strftime("%H:%M"), msg, "" if r.returncode == 0 else "(push failed, next time)", flush=True)
        if a.once or all(g["ended"] for g in gs):
            return 0
        time.sleep(a.every)


if __name__ == "__main__":
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
    raise SystemExit(main())
