"""v0.42: the Machinedrum machines re-coded must sound bit for bit as before (owner,
2026-11-06: rebuild the MD engines too). Every machine in run mode over its golden cases' events
(dnfw.md.bench, the model the SHARC runner holds the DSP to bit for bit) plus two variants of
each whose knobs change mid-note at random (each case its own seed), and the PERC voice
(dnfw.perc.live: the 48 kHz reader, the voice's machine changes) over a fixed sequence; each
output's float words hashed, with the instructions a block.

    python scripts/md_identity.py record OUT.json
    python scripts/md_identity.py check REF.json [NAMES]
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import random
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dnfw.md import bench as MDB                 # noqa: E402
from dnfw.md import machines as MM               # noqa: E402
from dnfw.perc import live as PL                 # noqa: E402
from dnfw.perc import machines as PM             # noqa: E402


def _h(xs):
    return hashlib.sha256(b"".join(struct.pack("<f", x) for x in xs)).hexdigest()


def machine_runs(name):
    M = MM.MACHINES[MM.NAMES.index(name)]
    per, steps, blocks = {}, 0, 0
    for case in MDB.golden(name)["cases"]:
        rnd = random.Random(f"{name}/{case['name']}")
        variants = [case]
        for _ in range(2):
            ev = {e[0]: list(e) for e in case["events"]}
            for blk in sorted(rnd.sample(range(1, case["nblocks"]), 3)):
                ev[blk] = [blk, [rnd.randrange(128) << 7 for _ in range(8)], rnd.random() < 0.4]
            variants.append({**case, "events": [ev[k] for k in sorted(ev)]})
        for k, c in enumerate(variants):
            ev = {b: (i, t) for b, i, t in c["events"]}
            b = MDB.Bench(M)
            out = []
            for blk in range(c["nblocks"]):
                out += b.block(*ev[blk]) if blk in ev else b.block()
                steps += b.steps
                blocks += 1
            per[f"{case['name']}#{k}"] = _h(out)
    return per, steps / blocks


def voice_runs():
    """the PERC voice: each machine, notes at 0, 9, 30, a machine change to the next at 50"""
    per, steps, blocks = {}, 0, 0
    for k, name in enumerate(PM.NAMES):
        h = PL.Harness(0)
        h.set_controls(k, PL.defaults(name))
        out = []
        for b in range(80):
            if b == 50:
                nxt = PM.NAMES[(k + 1) % len(PM.NAMES)]
                h.set_controls((k + 1) % len(PM.NAMES), PL.defaults(nxt))
            s0 = h.steps
            out += h.block(48.0 + (b % 5), b in (0, 9, 30, 50, 61))
            steps += h.steps - s0
            blocks += 1
        per[name] = _h(out)
    return per, steps / blocks


def run_all(only=None):
    res = {}
    for name in MM.NAMES:
        if only and name not in only:
            continue
        per, st = machine_runs(name)
        res[name] = {"cases": per, "steps_a_block": st}
        print(f"{name}: {len(per)} runs, {st:.1f} instructions a block", flush=True)
    if not only or "VOICE" in only:
        # in a process of its own: after the machines' benches the model's state once made
        # a voice run overflow (as test_slides' MD table: a run's state reaching the next)
        import subprocess
        r = subprocess.run([sys.executable, __file__, "voice"], capture_output=True, text=True, check=True)
        per, st = json.loads(r.stdout.strip().splitlines()[-1])
        res["VOICE"] = {"cases": per, "steps_a_block": st}
        print(f"VOICE: {len(per)} runs, {st:.1f} instructions a block", flush=True)
    return res


def main() -> int:
    if sys.argv[1] == "voice":
        print(json.dumps(voice_runs()))
        return 0
    mode, path = sys.argv[1], pathlib.Path(sys.argv[2])
    only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
    res = run_all(only)
    if mode == "record":
        path.write_text(json.dumps(res, indent=1))
        return 0
    ref = json.loads(path.read_text())
    bad = []
    for name, r in res.items():
        for case, h in r["cases"].items():
            if ref[name]["cases"].get(case) != h:
                bad.append(f"{name} {case}")
        if set(r["cases"]) != set(ref[name]["cases"]):
            bad.append(f"{name}: the case lists differ")
        print(f"{name}: {ref[name]['steps_a_block']:.1f} -> {r['steps_a_block']:.1f} instructions a block")
    print(("PASS" if not bad else "FAIL") + f": {sum(len(r['cases']) for r in res.values())} runs, "
          f"{len(bad)} differ{' (a partial check: ' + ','.join(only) + ')' if only else ''} " + " ".join(bad[:10]))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
