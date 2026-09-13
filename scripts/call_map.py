"""Ask the emulator how often each candidate function runs, and when.

## The question this exists to answer

`docs/trace-harness.md` put eleven functions on the instrument at once, each
stamping its own column of a string when it ran. Two columns marked, nine
stayed blank, and the result is **ambiguous between two readings that point
opposite ways**:

* **A** — the nine never run, and `param_index_in_page` (34 real callers) is
  somehow not on the DN2's parameter path. A large finding.
* **B** — the board is frozen early, late writes are never displayed, and
  every blank column is uninterpretable.

**A stamp cannot tell those apart**, because "ran once at boot" and "runs
constantly" leave the same mark. That is the design flaw the harness was built
to avoid and reproduced anyway.

A call *count* under emulation is immune to both halves of the ambiguity: it
does not go through the display at all, and it separates the two readings by
shape rather than by presence. So this runs the same eleven addresses in
digikit and reports, per slice of the run, how many times each was entered.

| the eleven | reading |
|---|---|
| some fire | **B** — the hardware readout was broken; blanks meant nothing |
| none fire, controls do | **A** survives, bounded by the caveats below |
| controls do not fire | the run is not comparable; the table says nothing |

## The control, and why it is drawn from hardware

`R` (`reverse_copy`, `0x400dd1ea`) and `E` (`0x40037942`) **marked on the
device**. Whatever else is true, those two run on real silicon. If they do not
fire here, this emulation did not reach what the instrument reached, and every
zero below is the emulator's, not the firmware's. The harness says so and exits
non-zero rather than print a table that would be read as a result.

That is the same rule the write map arrived at, one level up: *it is not enough
for the experiment to discriminate — the control has to discriminate too.*

## What a zero here still does not mean

**digikit models no input** (`docs/emulator.md`): the front-panel receive side
is not implemented, so no button is pressed, no encoder turns, and the UI can
never be driven off whatever page it boots to. A function reached only by
opening the `[MOD]` page cannot fire in this run. So a zero means **"not
entered during an undriven boot"**, never "dead".

**`unblock=True` changes semantics.** It force-satisfies every `sem_pend` so
the draw task actually draws; nothing ever really waits. That is what makes a
UI appear at all, and it is a deviation from the hardware, recorded here rather
than buried. Run with `--no-unblock` to see which results depend on it.

## On Digitone II 1.11 the rung to resume is 400M — measured, not assumed

digikit's boot ladder has rungs at 60/120/200/280/400M, and **the rungs are
instruction counts, not phases** — two firmwares do not reach the same place at
the same count. digikit's `emu.run` picks by state and its note says that on a
Digitone only 400M is disqualified, because the intro is already parked inside
`sem_pend` on the frame semaphore there and `unblock` cannot satisfy a wait that
is already blocked. So 280M looked like the rung to use.

**On 1.11 it is the other way round, and the difference is total.** Rendering
each rung with digikit's own `emu.panel` for 60M instructions:

| rung | frames flushed | distinct |
|---|---|---|
| 120M | 0 | 0 |
| 200M | 0 | 0 |
| 280M | 0 | 0 |
| **400M** | **173** | **109** |

120M through 280M never compose a frame and leave the timers held — the intro
never hands over. 400M draws. The upstream note was measured on 1.10E; 1.11
relinked and moved the phase boundary past 280M. Resume **400M**.

This is worth stating as a rule rather than a number: a rung is a phase, the
phase moves between builds, and the cheap way to find it is to render each rung
and look. Taking the documented rung on trust cost two full runs here, both of
which reported a dead machine as nine silent functions.

Needs digikit (`docs/emulator.md`) and its patched Unicorn, so run it under WSL
with digikit's interpreter. No firmware bytes are read from or written to this
repository.

    python scripts/call_map.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap \
        --syx .../Digitone_II_OS1.11.syx --json out/call-map-1.11.json
"""

import argparse
import json
import pathlib
import sys
import time

# The eleven sites from `docs/trace-harness.md`, in its column order, so a row
# of counts can be read straight against the row of stamps the device showed.
# Addresses are **Digitone II 1.11**; nothing here transfers to 1.10E.
#
# Every one re-checked with `dnfw fn <1.11> callers --at` before this ran, which
# is the rule `docs/trace-harness.md` paid four flashes for. All eleven are
# genuine direct-call targets -- 34, 2, 0, 1, 1, 2, 1, 1, 3, 3, 2 callers in
# column order -- and the single zero is `M`, the vtable-only lambda, exactly as
# recorded. So a silent probe here is not a probe aimed at nothing.
PROBES = [
    (0, "P", 0x400DBCC4, "param_index_in_page", "34 callers -- the static control"),
    (1, "G", 0x4006408A, "parameter_value_getter", "mis-anchored; does it run at all?"),
    (2, "M", 0x4004CA80, "updateMirror lambda", "vtable-only; a hit overturns the retraction"),
    (3, "S", 0x4004C5C6, "mirror enclosing fn", "the directly-called function the sites sit in"),
    (4, "R", 0x400DD1EA, "reverse_copy", "MARKED ON HARDWARE -- positive control"),
    (5, "F", 0x40043F5E, "fill loop", "the 0..100 loop, generic by construction"),
    (6, "B", 0x4004C178, "bulk copy A", "bulk value-array copy via 0x400dbc88"),
    (7, "C", 0x4004C23A, "bulk copy B", "the second bulk copy"),
    (8, "A", 0x40036274, "pip consumer A", "indexes the value array"),
    (9, "D", 0x40036BAC, "pip consumer B", "two generic sites inside it"),
    (10, "E", 0x40037942, "pip consumer C", "MARKED ON HARDWARE -- positive control"),
]

# The two the instrument itself lit, with the phase each one runs in. A run that
# lights neither is not comparable with the run being explained, whatever the
# other nine say.
#
# **The phase matters, and getting it wrong made the control lie.** `R` was
# first required in every run, and a post-boot window then reported "control
# silent" while three probes were plainly firing thousands of times. `R` is a
# boot-phase function: measured from the 280M rung it fires 697 times between
# 5M and 21M and never again. Demanding it in a window that starts after boot
# is demanding a negative, which is the same error as a watch that cannot
# produce a different answer per outcome -- only wearing a control's clothes.
CONTROLS = {"R": "boot", "E": "post-boot"}


def probe_table(extra):
    """-> the eleven, plus any `--at` the caller added.

    Extra sites carry no column letter and are never controls: they are being
    asked about, not relied on.
    """
    table = list(PROBES)
    for i, addr in enumerate(extra):
        table.append((len(table), "+%d" % i, addr, "0x%08x" % addr, "added with --at"))
    return table


def run(args) -> dict:
    root = pathlib.Path(args.digikit).resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tools"))
    from emu import longrun, symbols, config  # noqa: E402  (needs the path above)
    from emu.dtim import Dtims, Timers  # noqa: E402
    from emu.pit import Pits, intro_running  # noqa: E402

    table = probe_table(args.at)
    counts = {mark: 0 for _, mark, _, _, _ in table}

    def counter_for(mark):
        def hit(uc, address, size, data):
            counts[mark] += 1
        return hit

    # softfloat/dsp are not optional decoration. Without `dsp=True` the
    # priority-3 job worker wedges in the ready-bit spin at 0x400cf4ec on its
    # first transfer and none of the five jobs queued at boot ever runs
    # (digikit's own GUI comment). A run missing those jobs would report
    # silence that belongs to the emulator.
    #
    # `bitmap`/`on_pixel` is deliberately NOT used as the liveness signal, and
    # this is the trap worth naming: `Bitmap::setPixel` is the intro's drawing
    # primitive, and **the main OS never calls it** -- it composes text and
    # widgets straight into a framebuffer. So setPixel counts near zero while a
    # complete UI sits in RAM, and a harness trusting it would report "nothing
    # drew" over a running interface. digikit's `emu/panel.py` records that this
    # cost its author a session. Frames are counted at `panel_diff` instead.
    m, ev, st, pc, inq, at = longrun.build(
        args.snapshot, syx=args.syx, unblock=not args.no_unblock,
        softfloat=True, dsp=True, sdgate=True, esdhc=True)

    if not args.no_hooks:
        for _, mark, addr, _, _ in table:
            at(addr, counter_for(mark))

    # The timers are not optional either, and the reason is the whole
    # experiment. PIT2 is what spawns the OS tasks, and DMA timer 3 is the
    # 30 Hz tick whose ISR is the only thing at boot that posts to the queue
    # the **main application task** blocks on. Without them that task makes
    # exactly one pass through its message loop and waits forever -- a machine
    # that is running but not doing anything, whose every zero would be the
    # harness's own fault. `hold` keeps them back while the intro still owns
    # the vector, and `intro_done` hands over.
    profile = symbols.resolve(open(config.main_image(), "rb").read())
    intro = intro_running(m, profile.intro_pit3_isr)
    pits = Timers(Pits(m, hold=intro), Dtims(m, channels=(3,), hold=intro))
    if intro and profile.intro_done is not None:
        at(profile.intro_done, lambda uc, a, s, d: pits.release())

    # The liveness control: frames. `panel_diff` is the routine that diffs the
    # two 1024-byte framebuffers and flushes the changed runs to the panel, so
    # entering it means a frame was composed. Counting it answers "is the UI
    # running at all", which is what bounds every zero in the table below.
    frames = [0]
    if profile.panel_diff is not None:
        at(profile.panel_diff, lambda uc, a, s, d: frames.__setitem__(0, frames[0] + 1))

    # Slices, not one long run. A count says whether a function ran; a
    # *timeline* of counts says whether it ran once at boot or keeps running,
    # which is the half the stamp on the instrument could never report.
    t0 = time.time()
    timeline, executed, stop = [], 0, None
    for _ in range(args.slices):
        before = dict(counts)
        pc, ran, stop = longrun.spin(m, pc, args.slice_size, pits=pits, fast=True)
        executed += ran
        timeline.append({
            "executed": executed,
            "frames": frames[0],
            "delta": {k: counts[k] - before[k] for k in counts if counts[k] != before[k]},
        })
        if ran == 0:
            break

    rows = []
    for col, mark, addr, name, note in table:
        fired = [s["executed"] for s in timeline if s["delta"].get(mark)]
        rows.append({
            "column": col, "mark": mark, "address": addr, "name": name,
            "note": note, "count": counts[mark],
            "is_control": mark in CONTROLS,
            "control_phase": CONTROLS.get(mark),
            "first_slice_end": fired[0] if fired else None,
            "last_slice_end": fired[-1] if fired else None,
            "slices_active": len(fired),
        })

    controls_fired = sum(1 for r in rows if r["is_control"] and r["count"])
    return {
        "snapshot": args.snapshot,
        "syx": args.syx,
        "digikit": str(root),
        "unblock": not args.no_unblock,
        "hooks_installed": not args.no_hooks,
        "slices": len(timeline),
        "slice_size": args.slice_size,
        "instructions": executed,
        "stop": stop,
        "frames_composed": frames[0],
        "panel_diff": profile.panel_diff,
        "timers_held": bool(pits.held),
        "elapsed_s": round(time.time() - t0, 1),
        "controls_fired": controls_fired,
        "controls_total": len(CONTROLS),
        "rows": rows,
        "timeline": timeline,
    }


def print_report(report) -> None:
    head = {k: v for k, v in report.items() if k not in ("rows", "timeline")}
    print(json.dumps(head, indent=2))

    if not report["hooks_installed"]:
        print("\n*** --no-hooks: the non-interference baseline. Compare "
              "`instructions` and `stop` against the hooked run. ***")
    elif not report["controls_fired"]:
        print("\n*** CONTROLS SILENT: neither R nor E ran, and the instrument "
              "showed both. This run did not reach what the device reached, so "
              "every zero below is the emulator's and none of it is about the "
              "firmware. Do not read the table. ***")
    else:
        print("\ncontrol OK: %d/%d hardware-marked probes fired, so the hooks "
              "fire and this run reaches the device's behaviour."
              % (report["controls_fired"], report["controls_total"]))
        for row in report["rows"]:
            if row["is_control"] and not row["count"]:
                print("  (%s is a %s probe; silence is expected in a window "
                      "that does not cover that phase.)"
                      % (row["mark"], row["control_phase"]))

    # The second control, and it is the one that bounds every zero: a UI that
    # never draws cannot fail to call a drawing function in any interesting way.
    if report["frames_composed"]:
        print("UI alive: %d frames composed, so the draw task is running."
              % report["frames_composed"])
    elif report["panel_diff"] is None:
        print("*** panel_diff did not resolve for this image, so there is no "
              "liveness signal at all. Every zero below is unbounded. ***")
    else:
        print("*** NO FRAMES: the UI never composed one. Whatever the counts "
              "below say about functions on the drawing path, they are about a "
              "UI that never ran. ***")

    print("\n%-3s %-4s %-12s %-26s %10s %8s  %s"
          % ("col", "mark", "address", "name", "calls", "slices", "first..last"))
    for row in report["rows"]:
        span = ("-" if row["first_slice_end"] is None
                else "%dM..%dM" % (row["first_slice_end"] // 1_000_000,
                                   row["last_slice_end"] // 1_000_000))
        print("%-3d %-4s 0x%08x %-26s %10d %8d  %s"
              % (row["column"], row["mark"], row["address"], row["name"],
                 row["count"], row["slices_active"], span))

    # A reading is only printed when the run earned one. Both controls must have
    # fired and the UI must have drawn -- otherwise the nine zeros are the
    # emulator's state, not the firmware's behaviour, and printing "READING A
    # survives" over them would be this project's own recurring mistake:
    # announcing a conclusion a silent instrument cannot support.
    # A run earns a reading when the UI is alive and at least one
    # hardware-marked probe fired: together those say the hooks fire and the
    # machine reached the state being asked about. Requiring *both* controls in
    # one window is wrong, because they live in different phases.
    ready = (report["hooks_installed"]
             and report["controls_fired"]
             and report["frames_composed"])
    if not ready:
        print("\nNO READING. This run does not settle A vs B:")
        if not report["controls_fired"]:
            print("  - neither hardware-marked control fired, so the hooks "
                  "cannot be shown to work at all.")
        if not report["frames_composed"]:
            print("  - no frame was composed%s."
                  % (", and the intro still holds the timers"
                     if report.get("timers_held") else ""))
        print("  The nine zeros above are this machine's state, not a finding.")
    elif report["controls_fired"] and report["hooks_installed"]:
        nine = [r for r in report["rows"] if not r["is_control"] and r["column"] < 11]
        live = [r["mark"] for r in nine if r["count"]]
        print()
        if live:
            print("READING B. %d of the nine blank columns ran here: %s."
                  % (len(live), " ".join(live)))
            print("So the instrument's blank columns did NOT mean those functions")
            print("never run, and docs/trace-harness.md's reading A is dead.")
        else:
            print("READING A survives: none of the nine ran in this window either.")
        print("\nBounded by: no input is modelled, so nothing reached only by")
        print("pressing a key or turning an encoder can appear here. A zero means")
        print("'not entered during an undriven boot', and nothing more.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--digikit", required=True, help="path to the digikit clone")
    parser.add_argument("--snapshot", required=True, help="boot snapshot to resume")
    parser.add_argument("--syx", default=None, help="firmware, for build() provenance")
    parser.add_argument("--slice-size", type=int, default=10_000_000,
                        help="instructions per slice; the timeline's resolution")
    parser.add_argument("--slices", type=int, default=12, help="how many slices to run")
    parser.add_argument("--at", type=lambda s: int(s, 0), action="append", default=[],
                        help="an extra address to count; repeatable")
    parser.add_argument("--no-unblock", action="store_true",
                        help="do not force-satisfy sem_pend: faithful, but the UI may not draw")
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
    # Non-zero unless the run earned a reading, so a caller that only checks the
    # exit status cannot mistake an unlit machine for a negative result.
    return 0 if (report["controls_fired"] == report["controls_total"]
                 and report["frames_composed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
