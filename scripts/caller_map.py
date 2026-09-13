"""Which of a function's callers actually fire, and from where.

## The question

`dnfw fn callers --at` lists every site that *can* call an address. It found 34
for `param_index_in_page`, and that list is right — each was re-verified as a
genuine `jsr` on a real instruction boundary. But a static list cannot say which
of the 34 run when the instrument is drawing a parameter page, and that is the
question standing between this project and the display path.

`scripts/call_map.py` answered "does it run" (yes, constantly,
`docs/trace-harness.md`). This answers **"called from where"**, which is the
walk-back: hook the entry, read the return address off the stack, and the
histogram of return addresses is the set of live call sites.

## Reading the stack at entry, and when that is wrong

ColdFire `jsr` pushes the return address, so at the **first instruction of the
callee** — before any prologue — `(sp)` holds it. That is why probes go at
function entries and nowhere else.

It is only the return address if the function was *called*. Reached by a `jmp`,
a vtable thunk, or hooked one instruction late, `(sp)` is something else
entirely and the number will be nonsense. So nonsense is expected to be
possible, and the report says how much of it there was rather than hiding it:
every value is checked against the loaded MAIN OS range, and anything outside
is counted separately as `implausible`.

## The control, and it is a real one

**The runtime sites should be a subset of the static ones.** Two instruments
with nothing in common — a linear disassembly scan in this repository, and a
stack read inside an emulator — have to agree, and if they do not, one of them
is wrong and it matters which. The script reports the runtime set; compare it
with:

    dnfw fn <image> callers --at <the same address>

A runtime site that is **not** in the static list is the interesting failure: it
means either the caller scan misses a call form, or the entry is being reached
without a call. Either is worth more than the histogram.

Needs digikit (`docs/emulator.md`) and its patched Unicorn, so run it under WSL
with digikit's interpreter. No firmware bytes are read from or written to this
repository.

    python scripts/caller_map.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap \
        --at 0x400dbcc4 --json out/caller-map-1.11.json
"""

import argparse
import collections
import json
import pathlib
import sys
import time

# MAIN OS loads at 0x40000400; the decoded 1.11 section ends at 0x4030b980
# (docs/version-anchors.md). A return address outside this is not a call site.
CODE_LO = 0x40000400
CODE_HI = 0x4030B980


def run(args) -> dict:
    root = pathlib.Path(args.digikit).resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tools"))
    from emu import longrun, symbols, config  # noqa: E402  (needs the path above)
    from emu.dtim import Dtims, Timers  # noqa: E402
    from emu.pit import Pits, intro_running  # noqa: E402
    from unicorn.m68k_const import UC_M68K_REG_A7  # noqa: E402

    main_img = open(config.main_image(), "rb").read()
    profile = symbols.resolve(main_img)

    m, ev, st, pc, inq, at = longrun.build(
        args.snapshot, syx=args.syx, unblock=True,
        softfloat=True, dsp=True, sdgate=True, esdhc=True)

    sites = {a: collections.Counter() for a in args.at}
    hits = collections.Counter()
    implausible = collections.Counter()

    def watch(target):
        def on_entry(uc, address, size, data):
            hits[target] += 1
            sp = uc.reg_read(UC_M68K_REG_A7)
            try:
                ret = int.from_bytes(bytes(uc.mem_read(sp, 4)), "big")
            except Exception:                                    # noqa: BLE001
                implausible[target] += 1
                return
            if CODE_LO <= ret <= CODE_HI:
                # The return address points *after* the call, so the call site
                # itself is earlier. Report the return address and let
                # `dnfw fn entry --at` resolve the enclosing function, which is
                # what is actually wanted -- the caller, not the byte offset.
                sites[target][ret] += 1
            else:
                implausible[target] += 1
        return on_entry

    for target in args.at:
        at(target, watch(target))

    frames = [0]
    if profile.panel_diff is not None:
        at(profile.panel_diff, lambda uc, a, s, d: frames.__setitem__(0, frames[0] + 1))

    intro = intro_running(m, profile.intro_pit3_isr)
    pits = Timers(Pits(m, hold=intro), Dtims(m, channels=(3,), hold=intro))
    if intro and profile.intro_done is not None:
        at(profile.intro_done, lambda uc, a, s, d: pits.release())

    t0 = time.time()
    executed, stop = 0, None
    for _ in range(args.slices):
        pc, ran, stop = longrun.spin(m, pc, args.slice_size, pits=pits, fast=True)
        executed += ran
        if ran == 0:
            break

    watched = [{
        "address": target,
        "hits": hits[target],
        "implausible": implausible[target],
        "distinct_sites": len(sites[target]),
        "sites": [{"return_to": r, "count": n}
                  for r, n in sites[target].most_common(args.top)],
    } for target in args.at]

    return {
        "snapshot": args.snapshot,
        "digikit": str(root),
        "instructions": executed,
        "stop": stop,
        "elapsed_s": round(time.time() - t0, 1),
        "frames_composed": frames[0],
        "watched": watched,
    }


def print_report(report) -> None:
    print(json.dumps({k: v for k, v in report.items() if k != "watched"}, indent=2))

    if not report["frames_composed"]:
        print("\n*** NO FRAMES: the UI never drew, so whatever did or did not "
              "get called here is not about drawing a parameter page. ***")

    for w in report["watched"]:
        print("\n0x%08x -- %d entries, %d distinct return addresses"
              % (w["address"], w["hits"], w["distinct_sites"]))
        if not w["hits"]:
            print("  never entered in this window. With no input modelled that "
                  "is 'not during an undriven boot', not 'never'.")
            continue
        if w["implausible"]:
            print("  %d entries had a stack top outside the MAIN OS range: "
                  "reached by something other than a jsr, or hooked late."
                  % w["implausible"])
        print("  %-12s %10s" % ("returns to", "count"))
        for s in w["sites"]:
            print("  0x%08x %10d" % (s["return_to"], s["count"]))
        print("  Resolve each with `dnfw fn <image> entry --at <addr>`, and")
        print("  check the set against `dnfw fn <image> callers --at 0x%08x`:"
              % w["address"])
        print("  a runtime site missing from the static list means one of the")
        print("  two instruments is wrong, which is worth more than the table.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--digikit", required=True, help="path to the digikit clone")
    parser.add_argument("--snapshot", required=True, help="boot snapshot to resume")
    parser.add_argument("--syx", default=None, help="firmware, for build() provenance")
    parser.add_argument("--at", type=lambda s: int(s, 0), action="append", required=True,
                        help="function entry to watch; repeatable")
    parser.add_argument("--slice-size", type=int, default=10_000_000)
    parser.add_argument("--slices", type=int, default=20)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--json", help="write the full report here")
    args = parser.parse_args(argv)

    report = run(args)
    if args.json:
        path = pathlib.Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
    print_report(report)
    return 0 if any(w["hits"] for w in report["watched"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
