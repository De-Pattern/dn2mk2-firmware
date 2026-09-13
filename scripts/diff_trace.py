"""What code runs when the user turns an encoder, and not otherwise.

## Why a diff and not a reading

`0x4002e91c` is the main task's message loop and it is large. Somewhere inside
it an encoder record becomes a parameter change, and that is the **engine-feed
path** — one of the two functions LFO4 has to hook. Reading 2 KB of dispatch by
eye to find it is exactly how this project produced two wrong identifications.

The emulator can be asked instead. Record every basic block the CPU enters
during an idle window, then during a window where an encoder is being turned,
and **subtract**. What is left ran because of the turn.

## The control, and it is the whole design

A naive before/after diff reports a great deal of noise: any code that simply
had not run yet — a timer branch, a lazily-initialised path, a once-per-N-frames
redraw — appears "new" in the second window and has nothing to do with input.

So three windows run, in this order:

    idle A   ->  drive  ->  idle B

and the answer is `drive - (A | B)`: blocks that ran while turning the encoder
and in **neither** quiet window either side of it. A path that is merely late,
periodic, or first-time is very likely to show up in B as well, and is
subtracted. Nothing is claimed about blocks that appear in all three.

Both idle windows are the same length as the driven one, for the same reason
`scripts/drive.py` measures idle churn before believing a screen changed:
"ran during input" is only evidence if the alternative was measured.

## What it costs, and the honest caveat

This installs a global `UC_HOOK_BLOCK` callback, which digikit warns changes
outcomes rather than only timing. That is tolerable **here specifically**
because the measurement is a difference between three windows that all carry
the identical hook — the perturbation is in the baseline as well as the
experiment. It would not be tolerable for a run whose absolute totals mattered.

Needs digikit (`docs/emulator.md`) and its patched Unicorn, so run it under WSL
with digikit's interpreter. No firmware bytes are read from or written to this
repository.

    python scripts/diff_trace.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap \
        --json out/diff-trace.json
"""

import argparse
import collections
import json
import pathlib
import sys
import time


def run(args) -> dict:
    root = pathlib.Path(args.digikit).resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tools"))
    from emu import longrun, symbols, config, panel, panelin  # noqa: E402
    from emu.dtim import Dtims, Timers  # noqa: E402
    from emu.pit import Pits, intro_running  # noqa: E402
    from unicorn import UC_HOOK_BLOCK  # noqa: E402

    profile = symbols.resolve(open(config.main_image(), "rb").read())
    m, ev, st, pc, inq, at = longrun.build(
        args.snapshot, syx=args.syx, unblock=True,
        softfloat=True, dsp=True, sdgate=True, esdhc=True)

    cap = panel.Capture(at, diff_addr=profile.panel_diff,
                        front_addr=profile.fb_front)

    intro = intro_running(m, profile.intro_pit3_isr)
    pits = Timers(Pits(m, hold=intro), Dtims(m, channels=(3,), hold=intro))
    if intro and profile.intro_done is not None:
        at(profile.intro_done, lambda uc, a, s, d: pits.release())

    # Counts, not a set. The first version of this recorded which blocks ran
    # and subtracted, and the answer came back as the UART driver and the RTOS
    # queue only -- no application code at all, at 6 detents and again at 20.
    # That was the instrument, not the firmware: the dispatch that handles an
    # encoder record sits in code the idle loop runs anyway, so subtracting
    # "blocks that also ran when idle" deletes the very thing being looked for.
    # A block that runs 40x more often while turning is the signal; a block
    # that is merely present is not.
    seen = collections.Counter()
    recording = [False]

    def on_block(uc, address, size, data):
        if recording[0]:
            seen[address] += 1

    m.uc.hook_add(UC_HOOK_BLOCK, on_block)

    def spin(slices):
        nonlocal pc
        for _ in range(slices):
            pc, ran, _stop = longrun.spin(m, pc, args.slice_size,
                                          pits=pits, fast=True)
            if ran == 0:
                break

    def window(label, slices, turn=False):
        """-> the set of blocks entered during this window."""
        nonlocal pc
        seen.clear()
        recording[0] = True
        if turn:
            # A plausibly-timed turn, not a burst. The firmware scales an
            # encoder by how fast it is moved, and one large message is not a
            # fast turn -- six of +10 change nothing, while single detents a
            # slice apart engage the parameter (docs/display-path.md).
            for _ in range(slices):
                pc = panelin.encoder(m, profile, args.encoder, args.delta)
                spin(1)
        else:
            spin(slices)
        recording[0] = False
        return collections.Counter(seen)

    t0 = time.time()
    spin(args.warmup)
    idle_a = window("idle A", args.slices)
    driven = window("drive", args.slices, turn=True)
    idle_b = window("idle B", args.slices)

    # A block counts as input-driven when it runs materially more often during
    # the turn than in EITHER quiet window. Comparing against the larger of the
    # two is the strict direction: a block that is merely warming up over the
    # run has a rising idle_b to defend itself with.
    quiet = {a: max(idle_a[a], idle_b[a]) for a in set(idle_a) | set(idle_b)}
    scored = []
    for addr, n in driven.items():
        base = quiet.get(addr, 0)
        if n >= args.min_hits and n >= base * args.ratio:
            scored.append({"block": addr, "driven": n, "quiet_max": base,
                           "ratio": None if base == 0 else round(n / base, 1)})
    scored.sort(key=lambda r: -r["driven"])
    only = scored[: args.top]
    return {
        "snapshot": args.snapshot,
        "digikit": str(root),
        "warmup_slices": args.warmup,
        "slices": args.slices,
        "slice_size": args.slice_size,
        "encoder": args.encoder,
        "delta": args.delta,
        "frames_composed": len(cap.frames),
        "elapsed_s": round(time.time() - t0, 1),
        "blocks_idle_a": len(idle_a),
        "blocks_driven": len(driven),
        "blocks_idle_b": len(idle_b),
        "input_driven_blocks": only,
    }


def print_report(report) -> None:
    print(json.dumps({k: v for k, v in report.items()
                      if k != "input_driven_blocks"}, indent=2))

    if not report["frames_composed"]:
        print("\n*** NO FRAMES: the UI never drew, so the driven window is not "
              "a window in which anything was driven. ***")
        return

    only = report["input_driven_blocks"]
    print("\n%d block(s) ran markedly more while the encoder was turning than "
          "in either quiet window." % len(only))
    if not only:
        print("Nothing cleared the threshold. Lower --ratio, or the turn "
              "engaged nothing.")
        return
    print("\n%-12s %10s %10s %8s" % ("block", "driven", "quiet max", "ratio"))
    for r in only:
        print("0x%08x %10d %10d %8s"
              % (r["block"], r["driven"], r["quiet_max"],
                 "new" if r["ratio"] is None else r["ratio"]))
    print("\nResolve each to its function, which is the point of the list:")
    print("    dnfw fn <image> entry --at <addr>")
    print("\nThese are candidates, not the edit path. A block that ran only "
          "here\nstill has to be shown to do something before it is believed.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--digikit", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--syx", default=None)
    parser.add_argument("--warmup", type=int, default=20, help="slices before measuring")
    parser.add_argument("--slices", type=int, default=6, help="slices per window")
    parser.add_argument("--slice-size", type=int, default=10_000_000)
    parser.add_argument("--encoder", type=int, default=0)
    parser.add_argument("--delta", type=int, default=1)
    parser.add_argument("--ratio", type=float, default=5.0,
                        help="times more often than the quietest window to count")
    parser.add_argument("--min-hits", type=int, default=20,
                        help="ignore blocks that barely ran at all")
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--json")
    args = parser.parse_args(argv)

    report = run(args)
    if args.json:
        path = pathlib.Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
