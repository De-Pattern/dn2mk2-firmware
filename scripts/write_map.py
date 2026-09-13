"""Watch the firmware run and record *who writes where* — the runtime half of
`dnfw cave scan`.

## Why a write hook and not a memory watch

`docs/code-caves.md` closes with the limit of static analysis: a region reached
only through a computed pointer, with no constant anywhere and no sibling to
give it a stride, passes both checks in silence. The only thing that settles it
is watching the firmware run.

The obvious way to do that is to run the emulator and read the bytes afterwards.
**That does not work here, and the reason is the whole point of this file.** The
array that crashed the device on 2026-09-13 is cleared by a loop of `clrl` — it
is *written with zeros*. A watch that reads a value back at the end of the run
cannot tell "cleared to zero" from "never touched": both outcomes print
`0x00000000`. That was the third instrument this project built whose two
branches produce identical output (`docs/trace-harness.md`, `docs/emulator.md`),
and the rule it cost us is:

> A watch must be able to produce a different answer for each outcome.

A write **hook** can. It fires on the store itself, so a zero write is an event
like any other, and it carries the `pc` that did it — which is the address to
hand to Ghidra, and the thing a value watch could never produce at all.

## The two controls this run carries

**Positive: the known-live array.** `0x40287ef6` and its fifteen siblings are
cleared at boot by the loop at `0x4002a4d2`. If the hooks report no writes
there, the instrument is blind and *every* zero in the report is meaningless.
The run reports `control: BLIND` and exits non-zero rather than publish numbers.

That control has a failure mode of its own, and the first run hit it: **"the
hooks are broken" and "the run never reached the clearing loop" both print
zero.** A cold boot needs ~315M instructions to start the main application task,
so a 120M run cannot write that array and a blind report proves nothing about
the hooks. So the loop's own address is hooked too (`--loop`), which splits the
two: loop hits of zero means the run was too short; loop hits with no writes
means the write hooks are not firing.

**Non-interference: the digest.** digikit warns that global `UC_HOOK_CODE` and
`UC_HOOK_BLOCK` hooks change outcomes rather than merely timing. These hooks are
range-scoped and fire only on RAM inside the candidate runs, but "should not
perturb" is exactly the kind of claim this project has learned to check. Run
with `--no-hooks` and compare `digest` and `instructions`: identical means the
measurement did not create what it measured.

## What a clean result still does not mean

A cold boot with no notes played, no encoder turned and no project loaded. If a
region is written only when a voice is allocated, this run cannot see it — which
is precisely the state the device was in when it faulted. **Zero writes here
means "not written during cold boot", never "free".**

Needs digikit (`docs/emulator.md`) and its patched Unicorn, so run it under WSL
with digikit's interpreter. No firmware bytes are read from or written to this
repository.

    python scripts/write_map.py --digikit ~/digikit \
        --syx 00_Resources/00_Firmware/.../Digitone_II_OS1.11.syx \
        --runs out/runs-1.11.json --json out/write-map-1.11.json
"""

import argparse
import bisect
import collections
import hashlib
import json
import pathlib
import sys
import time

# The clearing loop at 0x4002a4d2 walks this array at boot (docs/code-caves.md).
# It is the positive control: hooks that see nothing here saw nothing anywhere.
CONTROL_NOTE = "known-live: cleared at boot by the loop at 0x4002a4d2"


def load_runs(path: pathlib.Path, min_size: int) -> tuple[list, list]:
    """-> (candidates, controls) from a `dnfw cave scan --json` report.

    Controls are drawn from the *same* report rather than hard-coded, so the
    control and the candidates are always the same build's addresses.
    """
    report = json.loads(path.read_text())
    runs = [r for r in report["runs"] if r["size"] >= min_size]
    candidates = [r for r in runs if r["passes"]]
    controls = [r for r in runs if r["strided"]]
    return candidates, controls


class WriteSink:
    """An `install_mmio_trace` sink that buckets events by watched region.

    Counts in memory; a JSONL line per event would be far too slow over a
    hundred million instructions.
    """

    def __init__(self, regions, max_pcs=12):
        # regions: [(lo, hi, label)], sorted by lo, non-overlapping.
        self.regions = sorted(regions)
        self.starts = [lo for lo, _, _ in self.regions]
        self.max_pcs = max_pcs
        self.writes = collections.Counter()
        self.reads = collections.Counter()
        self.first_pc = {}
        self.first_addr = {}
        self.pcs = collections.defaultdict(set)
        self.events = 0

    def _label(self, address):
        i = bisect.bisect_right(self.starts, address) - 1
        if i < 0:
            return None
        lo, hi, label = self.regions[i]
        return label if lo <= address <= hi else None

    def event(self, *, pc, address, width, direction, value,
              register=None, instruction_count=None, read_phase=None):
        label = self._label(address)
        if label is None:
            return
        self.events += 1
        if direction == "write":
            self.writes[label] += 1
        else:
            self.reads[label] += 1
        key = (label, direction)
        if key not in self.first_pc:
            self.first_pc[key] = pc
            self.first_addr[key] = address
        seen = self.pcs[key]
        if len(seen) < self.max_pcs:
            seen.add(pc)

    def close(self):
        pass

    def row(self, lo, size, label, kind):
        def side(direction):
            key = (label, direction)
            return {
                "count": (self.writes if direction == "write" else self.reads)[label],
                "first_pc": self.first_pc.get(key),
                "first_addr": self.first_addr.get(key),
                "pcs": sorted(self.pcs.get(key, ())),
            }
        return {
            "address": lo, "size": size, "kind": kind,
            "write": side("write"), "read": side("read"),
        }


def run(args) -> dict:
    sys.path.insert(0, str(pathlib.Path(args.digikit).resolve()))
    sys.path.insert(0, str(pathlib.Path(args.digikit).resolve() / "tools"))
    from addrtrace import load_main_image  # noqa: E402  (needs the path above)
    from emu import dspboot, snapshot  # noqa: E402
    from unicorn import UC_HOOK_CODE  # noqa: E402

    candidates, controls = load_runs(pathlib.Path(args.runs), args.min)
    if not controls:
        raise SystemExit("no strided run in the report to use as a positive control")

    regions, meta = [], []
    for kind, runs in (("control", controls[: args.controls]),
                       ("candidate", candidates)):
        for r in runs:
            label = "0x%08x" % r["address"]
            regions.append((r["address"], r["address"] + r["size"] - 1, label))
            meta.append((r["address"], r["size"], label, kind))

    main_img, sections_dir = load_main_image(args.syx, args.sections_dir)
    sink = WriteSink(regions)
    box = {}
    loop_hits = [0]

    def pre_start(m):
        if args.no_hooks:
            return
        m.install_mmio_trace(sink, ranges=[(lo, hi) for lo, hi, _ in regions])
        if args.loop:
            def on_loop(uc, address, size, data):
                loop_hits[0] += 1
            m.uc.hook_add(UC_HOOK_CODE, on_loop, begin=args.loop, end=args.loop)

    t0 = time.time()
    m, st, stop = dspboot.run(args.syx, main_img, limit=args.limit,
                              machine_out=box, pre_start=pre_start,
                              sdgate=True, esdhc=True)

    digest = hashlib.sha256()
    for name, rid in snapshot.REGS:
        digest.update(("%s=%d" % (name, m.uc.reg_read(rid))).encode())
    digest.update(("n=%d" % st["n"]).encode())

    rows = [sink.row(*entry) for entry in meta]
    touched = {"control": 0, "candidate": 0}
    for row in rows:
        if row["write"]["count"]:
            touched[row["kind"]] += 1

    return {
        "syx": args.syx,
        "sections_dir": sections_dir,
        "digikit": str(pathlib.Path(args.digikit).resolve()),
        "hooks_installed": not args.no_hooks,
        "regions": len(regions),
        "min_size": args.min,
        "limit": args.limit,
        "instructions": st["n"],
        "stop": stop,
        "digest": digest.hexdigest(),
        "elapsed_s": round(time.time() - t0, 1),
        "events": sink.events,
        "loop_address": args.loop,
        "loop_hits": loop_hits[0],
        "controls_written": touched["control"],
        "controls_total": sum(1 for r in rows if r["kind"] == "control"),
        "candidates_written": touched["candidate"],
        "candidates_total": sum(1 for r in rows if r["kind"] == "candidate"),
        "control_note": CONTROL_NOTE,
        "rows": rows,
    }


def print_report(report) -> None:
    head = {k: v for k, v in report.items() if k != "rows"}
    print(json.dumps(head, indent=2))

    blind = report["hooks_installed"] and not report["controls_written"]
    if not report["hooks_installed"]:
        print("\n*** --no-hooks: this is the non-interference baseline. Compare "
              "`digest` and `instructions` against the hooked run. ***")
    elif blind and report["loop_address"] and not report["loop_hits"]:
        print("\n*** RUN TOO SHORT: the clearing loop at 0x%08x never executed "
              "(%d instructions). The control could not be written, so this says "
              "nothing about the hooks OR the candidates. Raise --limit. ***"
              % (report["loop_address"], report["instructions"]))
    elif blind:
        print("\n*** CONTROL BLIND: the clearing loop ran (%d hits) but not one "
              "known-live region was written. The write hooks are not firing, so "
              "every zero below is meaningless. Do not read the table. ***"
              % report["loop_hits"])
    else:
        print("\ncontrol OK: %d/%d known-live regions were written, so the hooks fire."
              % (report["controls_written"], report["controls_total"]))

    print("\n%-12s %-10s %7s %9s %9s  %s"
          % ("address", "kind", "size", "writes", "reads", "first write pc"))
    for row in sorted(report["rows"], key=lambda r: (r["kind"], -r["write"]["count"])):
        pc = row["write"]["first_pc"]
        print("0x%08x %-10s %7d %9d %9d  %s"
              % (row["address"], row["kind"], row["size"], row["write"]["count"],
                 row["read"]["count"], "-" if pc is None else "0x%08x" % pc))

    if not blind and report["hooks_installed"]:
        quiet = [r for r in report["rows"]
                 if r["kind"] == "candidate" and not r["write"]["count"]]
        print("\n%d candidate run(s) took no write during this boot." % len(quiet))
        print("That is NOT a blessing: no note was played, no encoder turned and no")
        print("project loaded -- and the device faulted while the keyboard was played.")
        print("It means 'not written during cold boot', and nothing more.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--digikit", required=True, help="path to the digikit clone")
    parser.add_argument("--syx", required=True, help="firmware to boot")
    parser.add_argument("--runs", required=True, help="`dnfw cave scan --json` report")
    parser.add_argument("--sections-dir", default=None,
                        help="a sections directory to use instead of digikit's own extraction")
    parser.add_argument("--min", type=int, default=128, help="smallest run to watch")
    parser.add_argument("--controls", type=int, default=4,
                        help="how many known-live strided runs to carry as positive controls")
    parser.add_argument("--limit", type=int, default=400_000_000,
                        help="a cold boot needs ~315M to start the main application task")
    parser.add_argument("--loop", type=lambda s: int(s, 0), default=0x4002A4D2,
                        help="address of the control's clearing loop; 0 to skip")
    parser.add_argument("--no-hooks", action="store_true",
                        help="install nothing: the non-interference baseline")
    parser.add_argument("--json", help="write the full report here")
    args = parser.parse_args(argv)

    report = run(args)
    if args.json:
        path = pathlib.Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
    print_report(report)

    if args.no_hooks:
        return 0
    return 0 if report["controls_written"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
