"""Fit `TRAN` -> transient slot from a sweep produced by `tran_sweep.py`.

Takes the CSV, finds where each probe slot is at its loudest, and fits a line.
The slope is how many `TRAN` units one slot spans; the residuals say whether a
straight line is the right shape at all.

**Weighted by confidence, not thresholded.** An earlier version kept only rows
where one slot held more than 45% of the probe energy, which silently discarded
the boundaries between slots -- exactly where the interpolation lives -- and
made every run look cleaner than it was. Each row now contributes in proportion
to that slot's share, so a blended reading pulls the centre gently rather than
vanishing.
"""

import argparse
import csv
import pathlib


def load(path):
    rows = []
    for r in csv.DictReader(path.open(encoding="utf-8")):
        slots = {int(k[4:]): float(v) for k, v in r.items()
                 if k.startswith("slot") and k != "loudest_slot"}
        rows.append((int(r["tran"]), float(r.get("peak_hz", 0) or 0), slots))
    return rows


def centres(rows, min_share=0.25):
    """-> {slot: (weighted centre TRAN, total weight, lo, hi)}."""
    acc = {}
    for tran, _peak, slots in rows:
        total = sum(slots.values()) or 1.0
        for slot, energy in slots.items():
            share = energy / total
            if share < min_share:
                continue
            w, s, lo, hi = acc.get(slot, (0.0, 0.0, tran, tran))
            acc[slot] = (w + share * tran, s + share, min(lo, tran), max(hi, tran))
    return {slot: (w / s, s, lo, hi) for slot, (w, s, lo, hi) in acc.items() if s > 0}


def fit(points):
    """Least squares TRAN = a*slot + b -> (a, b, max residual)."""
    n = len(points)
    sx = sum(s for s, _ in points)
    sy = sum(t for _, t in points)
    sxx = sum(s * s for s, _ in points)
    sxy = sum(s * t for s, t in points)
    denom = n * sxx - sx * sx
    if not denom:
        return 0.0, 0.0, 0.0
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    worst = max(abs(t - (a * s + b)) for s, t in points)
    return a, b, worst


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("csv", type=pathlib.Path)
    p.add_argument("--min-weight", type=float, default=1.0,
                   help="drop slots seen too weakly to place")
    p.add_argument("--from-slot", type=int, default=16, metavar="N",
                   help="also fit slots >= N alone. The default of 16 is where "
                        "the probe tone clears the FM DRUM body's harmonics; "
                        "below it the readings are contaminated, not wrong. "
                        "See docs/tran-mapping.md.")
    args = p.parse_args(argv)

    rows = load(args.csv)
    c = centres(rows)
    strong = {s: v for s, v in c.items() if v[1] >= args.min_weight}

    print(f"{len(rows)} sweep points, {len(strong)} slots placed\n")
    print(f"{'slot':>5} {'TRAN range':>12} {'centre':>8} {'weight':>7}")
    for slot in sorted(strong):
        centre, weight, lo, hi = strong[slot]
        print(f"{slot:>5} {f'{lo}..{hi}':>12} {centre:>8.1f} {weight:>7.1f}")

    points = [(s, v[0]) for s, v in sorted(strong.items())]
    report("all slots", points)
    clean = [(s, t) for s, t in points if s >= args.from_slot]
    if len(clean) < len(points):
        report(f"slots >= {args.from_slot}", clean)
    return 0


def report(label: str, points) -> None:
    if len(points) < 3:
        return
    a, b, worst = fit(points)
    print()
    print(f"fit over {label}:  TRAN = {a:.3f} x slot + {b:.2f}")
    print(f"      worst residual {worst:.2f} TRAN units")
    print(f"      -> {a:.2f} TRAN per slot, "
          f"{'straight' if worst < 2.5 else 'NOT straight -- the shape is wrong'}")
    print(f"      slot 0  at TRAN {b:.1f}")
    print(f"      slot 33 at TRAN {a * 33 + b:.1f}   (the knob stops at 124)")


if __name__ == "__main__":
    raise SystemExit(main())
