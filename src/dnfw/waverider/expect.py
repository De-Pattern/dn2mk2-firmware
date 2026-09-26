"""What Milestone 0's telemetry must report, written down before the flash.

**A pass is a match, not a judgement.** Every value the firmware sends is
computed here first from the same generator the build baked, so reading the
instrument is a comparison with a list, and a failure is a named mismatch.

**One burst, in the order the firmware sends it** (`csrc/waverider/table.c`,
called from the LFO4 telemetry burst right after `probe_a` = 99):

    wr_frame                     the probe's frame, 0..15
    wr_idx_lo,  wr_idx_hi        the probe's sample index, 0..511, 7 + 7 bits
    wr_val_lo, wr_val_mid, wr_val_hi
                                 the int16 read there, as 16 unsigned bits:
                                 bits 0-6, 7-13, 14-15
    wr_sum_lo, wr_sum_mid, wr_sum_hi
                                 the whole table's checksum, computed on the
                                 instrument (`bake.checksum`), same split
    wr_passes                    whole-table checksum passes completed, mod 128

The probe advances by one each burst and wraps after `len(PROBES)`. The
checksum is computed `SLICE` words per burst, so the first pass completes after
`WORDS / SLICE` bursts; until then `wr_passes` is 0 and the sum reads 0.
"""

from __future__ import annotations

import re

from . import bake, reduce

# Chosen to be told apart: both signs, the table's extremes, every region.
PROBES = [
    (0, 128),     # frame 0 is a sine: its crest
    (0, 384),     # ... and its trough
    (3, 100),
    (7, 255),
    (8, 257),     # just past the saw's reset: negative
    (12, 33),
    (15, 248),    # the table's largest point, 32767 after scaling
    (15, 263),    # the table's smallest
]
SLICE = 1024      # checksum words per burst -> 8 bursts per pass
PROBE_A = 99      # the LFO4 burst's calibration constant, sent just before

SIGNALS = ("wr_frame", "wr_idx_lo", "wr_idx_hi", "wr_val_lo", "wr_val_mid",
           "wr_val_hi", "wr_sum_lo", "wr_sum_mid", "wr_sum_hi", "wr_passes")


def split16(v: int) -> tuple[int, int, int]:
    """16 bits -> (bits 0-6, 7-13, 14-15), as the firmware sends them."""
    v &= 0xFFFF
    return v & 0x7F, (v >> 7) & 0x7F, v >> 14


def join16(lo: int, mid: int, hi: int) -> int:
    return (lo & 0x7F) | ((mid & 0x7F) << 7) | ((hi & 0x03) << 14)


def signed(u: int) -> int:
    return u - 0x10000 if u & 0x8000 else u


def probes(table: list[list[int]]) -> list[dict]:
    """-> one row per probe: where, the value, and the exact CC values to see."""
    rows = []
    for f, i in PROBES:
        v = table[f][i]
        lo, mid, hi = split16(v)
        rows.append({"frame": f, "index": i, "value": v, "u16": v & 0xFFFF,
                     "cc": {"wr_frame": f, "wr_idx_lo": i & 0x7F, "wr_idx_hi": i >> 7,
                            "wr_val_lo": lo, "wr_val_mid": mid, "wr_val_hi": hi}})
    return rows


def summary(table: list[list[int]]) -> dict:
    s = bake.checksum(table)
    lo, mid, hi = split16(s)
    return {"checksum": s, "cc": {"wr_sum_lo": lo, "wr_sum_mid": mid, "wr_sum_hi": hi},
            "bursts_per_pass": (reduce.FRAMES * reduce.POINTS) // SLICE}


# A line of `scripts/midi_watch.py`: "  12.345  ch16 CC41  (wr_frame)   = 3"
LINE = re.compile(r"CC\s*(\d+)\s*\((\w+)\)\s*=\s*(\d+)")


def parse(text: str) -> list[tuple[str, int]]:
    """A `midi_watch.py` capture -> [(signal name, value)] in arrival order."""
    return [(m.group(2), int(m.group(3))) for m in map(LINE.search, text.splitlines()) if m]


def verify(pairs: list[tuple[str, int]], table: list[list[int]]) -> tuple[bool, list[str]]:
    """Check a capture against the expectation. -> (passed, report lines).

    A burst is the run of `wr_*` signals starting at `wr_frame`. A capture that
    starts mid-burst drops its first partial one rather than misreading it.
    """
    want = {(r["frame"], r["index"]): r for r in probes(table)}
    total = summary(table)
    report, fails = [], []
    bursts, cur = [], None
    for name, value in pairs:
        if name == "wr_frame":
            cur = {"wr_frame": value}
            bursts.append(cur)
        elif cur is not None and name in SIGNALS:
            cur[name] = value
    bursts = [b for b in bursts if all(s in b for s in SIGNALS)]
    probe_a = [v for n, v in pairs if n == "probe_a"]
    if not probe_a:
        fails.append("no probe_a at all: the LFO4 burst is not in this capture")
    elif any(v != PROBE_A for v in probe_a):
        fails.append(f"probe_a read {sorted(set(probe_a))}, not only {PROBE_A}: "
                     "nothing beside it can be trusted")
    if not bursts:
        fails.append("no complete wr_* burst in the capture")
    seen, sums = set(), set()
    for b in bursts:
        at = (b["wr_frame"], b["wr_idx_lo"] | (b["wr_idx_hi"] << 7))
        got = join16(b["wr_val_lo"], b["wr_val_mid"], b["wr_val_hi"])
        row = want.get(at)
        if row is None:
            fails.append(f"a burst reported frame {at[0]} index {at[1]}, which is not a probe")
        elif got != row["u16"]:
            fails.append(f"frame {at[0]} index {at[1]}: read {signed(got)}, expected {row['value']}")
        else:
            seen.add(at)
        if b["wr_passes"]:
            sums.add(join16(b["wr_sum_lo"], b["wr_sum_mid"], b["wr_sum_hi"]))
    missing = [p for p in want if p not in seen]
    if bursts and missing:
        fails.append(f"{len(missing)} probe(s) never read back correctly: {missing}")
    if bursts and not sums:
        fails.append("wr_passes stayed 0: no checksum pass completed in the capture")
    for s in sorted(sums):
        if s != total["checksum"]:
            fails.append(f"checksum read {s:#06x}, expected {total['checksum']:#06x}")
    report.append(f"{len(bursts)} complete burst(s), {len(seen)}/{len(want)} probes matched, "
                  f"checksum(s) seen {[f'{s:#06x}' for s in sorted(sums)]}, "
                  f"expected {total['checksum']:#06x}")
    return not fails, report + [f"FAIL  {f}" for f in fails]
