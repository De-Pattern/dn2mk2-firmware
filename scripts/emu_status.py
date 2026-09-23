"""What the emulator is doing right now, and what is queued behind it.

    python scripts/emu_status.py                 # once
    python scripts/emu_status.py --watch 5       # refresh every 5 seconds
    python scripts/emu_status.py --lines 12      # more of each log

The emulator is **one machine, used serially**, and a gate run takes twenty to
forty-five minutes. Everything driving it queues on the same `while pgrep`
wait, which means a session can spend a long stretch with nothing to say and
the owner with nothing to look at. That is a reporting failure, not a fact of
the work: the logs exist the whole time.

So this reads them. Every run writes into `out/emu-logs/`, and this prints what
is executing in WSL, how long it has been going, and the tail of each log
newest first. Nothing here touches the emulator, so it is safe to run while a
gate is in flight -- it only reads files and asks `ps` a question.

`--watch` is a plain loop, not a daemon: stop it with Ctrl-C and nothing is
left behind.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOGS = ROOT / "out/emu-logs"
# The scratchpad a session is using, if it says so. Runs started before this
# script existed write there, and they are still worth seeing.
EXTRA = os.environ.get("DT2_LOGDIR")

# What a log line has to contain to be worth showing as progress. A gate spends
# most of its life printing nothing, and the TASK_CREATE trace is noise.
SKIP = ("TASK_CREATE",)


def running():
    """-> [(elapsed, command, state)] for the emulator and everything queued.

    **The queue matters as much as the job.** Everything here waits its turn on
    a `while pgrep ... sleep` loop, so at any moment one Python process is using
    the machine and several shell scripts are asleep waiting for it. Showing
    only the running one answers "is it busy" and not "how much is left", which
    is the question actually being asked.
    """
    try:
        out = subprocess.run(
            ["wsl", "bash", "-c",
             "ps -eo etimes,args | grep -E 'dn2-emu-venv|run_[a-z0-9_]*\\.sh' "
             "| grep -v grep"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"}).stdout
    except Exception as error:                                  # noqa: BLE001
        return [(0, f"(could not ask WSL: {error})", "?")]
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        seconds, _, command = line.partition(" ")
        try:
            elapsed = int(seconds)
        except ValueError:
            continue
        # A venv python is the machine in use; a runner script is either the
        # parent of that python or a sibling asleep on its wait loop.
        state = "RUNNING" if "dn2-emu-venv" in command else "queued "
        rows.append((elapsed, command.strip(), state))
    return sorted(rows, reverse=True)


def clock(seconds):
    return f"{seconds // 60:>3}m{seconds % 60:02d}s"


def logs(lines):
    """Every log we know about, newest written first."""
    # **By name, newest wins.** A session that copies its scratchpad into
    # `out/emu-logs` and also points `DT2_LOGDIR` at that scratchpad would
    # otherwise show every log twice, which is how the first version of this
    # read -- and a status view that double-reports is worse than none.
    places = [LOGS] + ([pathlib.Path(EXTRA)] if EXTRA else [])
    best = {}
    for place in places:
        if not place.is_dir():
            continue
        for path in place.glob("*.log"):
            if not path.stat().st_size:
                continue
            seen = best.get(path.name)
            if seen is None or path.stat().st_mtime > seen.stat().st_mtime:
                best[path.name] = path
    for path in sorted(best.values(), key=lambda p: p.stat().st_mtime, reverse=True):
        age = int(time.time() - path.stat().st_mtime)
        body = [l.rstrip() for l in path.read_text(errors="replace").splitlines()
                if l.strip() and not any(s in l for s in SKIP)]
        yield path.name, age, body[-lines:]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--watch", type=float, metavar="SECONDS",
                   help="refresh until interrupted")
    p.add_argument("--lines", type=int, default=6, help="tail per log (default 6)")
    p.add_argument("--all", action="store_true", help="every log, not just recent ones")
    args = p.parse_args(argv)

    while True:
        if args.watch:
            print("\033[2J\033[H", end="")
        print(f"  emulator status  {time.strftime('%H:%M:%S')}")
        print("  " + "-" * 68)

        live = running()
        if live:
            for seconds, command, state in live:
                short = command.split("/")[-1][:60]
                print(f"  {state}  {clock(seconds)}  {short}")
            waiting = sum(1 for _e, _c, s in live if s.strip() == "queued")
            if waiting:
                print(f"           {waiting} job(s) waiting their turn on one machine")
        else:
            print("  RUNNING  nothing -- the machine is free")

        print()
        any_log = False
        for name, age, tail in logs(args.lines):
            if not args.all and age > 3600:
                continue
            any_log = True
            fresh = "live" if age < 90 else f"{clock(age)} ago"
            print(f"  {name}  ({fresh})")
            for line in tail:
                print(f"      {line[:110]}")
            print()
        if not any_log:
            print("  no recent logs. Set DT2_LOGDIR to a session scratchpad to")
            print("  include runs started before this script existed.")

        if not args.watch:
            return 0
        try:
            time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n  stopped watching; nothing was changed")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
