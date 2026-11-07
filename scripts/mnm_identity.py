"""v0.42: the Monomachine machines re-coded must sound bit for bit as before (owner, 2026-11-06:
"rewriting the MM machines while keeping them bit-exact"). This runs every machine in run mode
(dnfw.mnm.bench, the model the SHARC runner holds the DSP to, bit for bit) over the golden
cases' notes and increments, and over variants of them whose knobs change mid-note at random
(a fixed seed), and records each output's float words (sha256) and the instructions a block.

    python scripts/mnm_identity.py record OUT.json      # before the re-code
    python scripts/mnm_identity.py check REF.json       # after: every output identical
    python scripts/mnm_identity.py check REF.json VO6   # one machine, while working

The golden runs (MNM_GOLDEN) give the cases' A/F words only; nothing of the Monomachine's
output is used. Exit 0 and PASS when every output is identical, 1 and the cases otherwise.
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

from dnfw.mnm import bench, ddrw, dens, sid, vo6, wave      # noqa: E402

MACHINES = {"WAVE": wave, "SID": sid, "DENS": dens, "DDRW": ddrw, "VO6": vo6}
VARIANTS = 2                    # knob-changing variants of each golden case


def variants(case: dict, rnd: random.Random) -> list[dict]:
    out = []
    for _ in range(VARIANTS):
        c = dict(case)
        ev = {e[0]: list(e) for e in case["events"]}
        for blk in sorted(rnd.sample(range(1, case["nblocks"]), 3)):
            knobs = [rnd.randrange(128) for _ in range(8)]
            ev[blk] = [blk, knobs, None, rnd.random() < 0.3]
        c["events"] = [ev[k] for k in sorted(ev)]
        out.append(c)
    return out


def run_all() -> dict:
    res: dict = {}
    for name, M in MACHINES.items():
        cases = bench.golden(name)["cases"]
        per, steps, blocks = {}, 0, 0
        for case in cases:
            rnd = random.Random(f"{name}/{case['name']}")     # its own: a partial check is the same
            for k, c in enumerate([case] + variants(case, rnd)):
                ev = {e[0]: e for e in c["events"]}
                b = bench.Bench(M)
                words = []
                for blk in range(c["nblocks"]):
                    if blk in ev:
                        _, knobs, _n, trig = ev[blk]
                        out = b.block(c["A"][blk], c["F"][blk], knobs, trig)
                    else:
                        out = b.block(c["A"][blk], c["F"][blk])
                    words += [struct.pack("<f", x) for x in out]
                    steps += b.steps
                    blocks += 1
                per[f"{case['name']}#{k}"] = hashlib.sha256(b"".join(words)).hexdigest()
        res[name] = {"cases": per, "steps_a_block": steps / blocks}
        print(f"{name}: {len(per)} runs, {steps / blocks:.1f} instructions a block", flush=True)
    return res


def main() -> int:
    mode, path = sys.argv[1], pathlib.Path(sys.argv[2])
    if len(sys.argv) > 3:                       # check only these machines (while working)
        for n in list(MACHINES):
            if n not in sys.argv[3].split(","):
                del MACHINES[n]
    res = run_all()
    if mode == "record":
        path.write_text(json.dumps(res, indent=1))
        print(f"recorded {path}")
        return 0
    ref = json.loads(path.read_text())
    bad = []
    for name, r in res.items():
        for case, h in r["cases"].items():
            if ref[name]["cases"].get(case) != h:
                bad.append(f"{name} {case}")
        print(f"{name}: {ref[name]['steps_a_block']:.1f} -> {r['steps_a_block']:.1f} instructions a block")
    if len(sys.argv) > 3:
        ref = {n: ref[n] for n in res}
        print("ONLY " + sys.argv[3] + ": a partial check")
    if set(ref) != set(res) or any(set(ref[n]["cases"]) != set(res[n]["cases"]) for n in res):
        bad.append("the case lists differ")
    print(("PASS" if not bad else "FAIL") + f": {sum(len(r['cases']) for r in res.values())} runs, "
          f"{len(bad)} differ " + " ".join(bad[:10]))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
