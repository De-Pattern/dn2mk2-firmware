"""Drive the emulated panel, and prove the input actually did something.

## Why this exists before any probe that uses input

`docs/emulator.md` records the author's warning that **encoder deltas are
buggy**, and the standing rule here is that a trace is worth nothing until the
thing it depends on is shown to work. If a delta delivers an *event* but no
value *change*, every probe downstream lights the wrong half of the path and
looks exactly like a result.

So this runs first and answers one question: **does pressing a button and
turning an encoder change what is on the screen?**

## The outcomes it can tell apart

| screen after MOD | screen after encoder | reading |
|---|---|---|
| unchanged | unchanged | input is not reaching the firmware at all |
| **changed** | unchanged | navigation works, **deltas do not** — the flagged bug |
| changed | **changed** | the input path works end to end |

Three outcomes, three different printouts. A harness that could only say
"changed / did not change" would fold the middle row into one of the others,
which is the failure this project has now paid for four times.

## The control's own control: idle churn

"The screen changed" is only evidence if the screen would otherwise have stayed
still. A sequencer playhead, a blinking cursor or a level meter would all change
the framebuffer with no input whatever, and would make every row above read as
success.

So an **idle window of the same length runs first**, with no input, and its
churn is measured. If the screen moves on its own, the comparison is against
that motion rather than against zero, and the report says so instead of
claiming a result.

## What is compared

The 1024-byte framebuffer behind `fb_front` (dereferenced — the symbol is the
address of the *pointer*, see `docs/display-path.md`), rendered to ASCII so the
change is legible rather than a hash that says only "different". A parameter
value is text on that screen; if a number changes, it is visible here.

Needs digikit (`docs/emulator.md`) and its patched Unicorn, so run it under WSL
with digikit's interpreter. No firmware bytes are read from or written to this
repository.

    python scripts/drive.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap
"""

import argparse
import json
import pathlib
import sys

# The firmware's own panel table, read out of the running image by
# `panelin.control_names` -- not written down here. On Digitone II 1.11:
# button code 6 is MOD, and `code_for(channel, bit) = channel*8 + bit + 1`,
# so MOD is channel 0, bit 5. Encoder channel 0 is ENCODER A.
MOD_CHANNEL, MOD_BIT = 0, 5
ENCODER_A = 0


def settle(longrun, m, pc, pits, instrs, chunk):
    """Run `instrs`, in chunks. -> (pc, executed, last stop reason).

    The stop reason is carried out rather than dropped because a run that
    executes nothing is the interesting case: `spin` returns normally having
    executed zero when a vector has no handler, and a caller that only looks
    at the screen reads that as "the input did nothing".
    """
    done, stop = 0, None
    while done < instrs:
        pc, ran, stop = longrun.spin(m, pc, chunk, pits=pits, fast=True)
        done += ran
        if ran == 0:
            break
    return pc, done, stop


def run(args) -> dict:
    root = pathlib.Path(args.digikit).resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tools"))
    from emu import longrun, symbols, config, panel, panelin  # noqa: E402
    from emu.dtim import Dtims, Timers  # noqa: E402
    from emu.pit import Pits, intro_running  # noqa: E402

    profile = symbols.resolve(open(config.main_image(), "rb").read())
    # `weakptr=True` and DMA timer channel 1 are both load-bearing, and both
    # are named in digikit's own build() docstring rather than guessed:
    #
    #  - weakptr would settle the panel on the real main screen instead of a
    #    modal / `Loading...`, but it is **not available on 1.11**: its patch
    #    site is build-specific and digikit's own guard refuses, with
    #    `weakptr: 0x40188b40 holds 4878, expected 6714`. That is the guard
    #    working. It is off by default here and `--weakptr` is left available
    #    for a build where the anchor holds.
    #  - DMA timer channel 1 was added on the strength of the same docstring
    #    ("channels=(3, 1) stops faulting") and **measurably made this build
    #    worse**: with channels=(3,) the richest frame of the run is the real
    #    SYN1 parameter page at 2,183 lit pixels; with (3, 1) it is the boot
    #    animation at 411, and the page is never reached. It did not stop the
    #    input fault either. Digitakt's fix is not Digitone's -- the same
    #    lesson as the boot rung, learnt twice from the same docstring.
    m, ev, st, pc, inq, at = longrun.build(
        args.snapshot, syx=args.syx, unblock=True, weakptr=args.weakptr,
        softfloat=True, dsp=True, sdgate=True, esdhc=True)

    # Capture at `panel_diff` entry, which `emu/panel.py` names as the only
    # moment [FRONT] holds a complete, untorn frame. Reading the pointer at an
    # arbitrary stop instead catches a buffer mid-render or mid-swap: the first
    # version of this script did that and reported a blank screen and "no
    # input reaches the firmware", while 403 of 409 captured frames in the same
    # run carried up to 2,183 lit pixels. Sampling the right bytes at the wrong
    # moment is the same class of error as sampling the wrong bytes.
    cap = panel.Capture(at, diff_addr=profile.panel_diff,
                        front_addr=profile.fb_front)

    intro = intro_running(m, profile.intro_pit3_isr)
    pits = Timers(Pits(m, hold=intro), Dtims(m, channels=(3,), hold=intro))
    if intro and profile.intro_done is not None:
        at(profile.intro_done, lambda uc, a, s, d: pits.release())

    def screen():
        """-> the last untorn frame, or None if none has been composed yet."""
        return bytes(cap.frames[-1]) if cap.frames else None

    def diff(a, b):
        if a is None or b is None:
            return None
        return sum(1 for x, y in zip(a, b) if x != y)

    def write_png(step, buf):
        """Save the step's screen as a PNG. -> the path, or None.

        The screens are the evidence, so they are archived rather than
        described: a byte count says a screen changed, a picture says what it
        changed to. These are emulator output -- a 128x64 mono panel -- and
        carry no firmware bytes.
        """
        if buf is None or not args.png_dir:
            return None
        slug = "".join(c if c.isalnum() else "-" for c in step).strip("-").lower()
        out = pathlib.Path(args.png_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / ("%s.png" % slug)
        panel.write_png(buf, str(path))
        return str(path)

    def mark(step, before, after, frames_before):
        """Record a step, including whether any NEW frame was composed.

        Without this, "the screen did not change" and "nothing was drawn at
        all" both print zero: cap.frames[-1] simply stays the frame it already
        was. That is the same undiscriminating zero this project keeps
        rebuilding, so the frame delta is part of every row.
        """
        steps.append({
            "step": step,
            "changed_bytes": diff(before, after),
            "new_frames": len(cap.frames) - frames_before,
            "lit": len(panel.lit(after)) if after else None,
            "executed": _ran,
            "stop": _stop,
            "png": write_png(step, after),
        })

    names = panelin.control_names(m, profile, "button")
    mod_code = next((c for c, n in names.items() if n.strip() == "MOD"), None)

    steps = []

    # Reach a drawing state first: nothing below means anything until the UI
    # is composing frames.
    pc, _ran, _stop = settle(longrun, m, pc, pits, args.warmup, args.chunk)
    base = screen()
    n0 = len(cap.frames)

    # The control's control. No input at all, same window length as every
    # step below, so "changed" is measured against how much this screen moves
    # on its own rather than against an assumed zero.
    pc, _ran, _stop = settle(longrun, m, pc, pits, args.window, args.chunk)
    idle = screen()
    mark("idle (no input)", base, idle, n0)

    before, n0 = idle, len(cap.frames)
    panelin.press(m, profile, MOD_CHANNEL, MOD_BIT)
    pc, _ran, _stop = settle(longrun, m, pc, pits, args.window // 2, args.chunk)
    panelin.release(m, profile, MOD_CHANNEL, MOD_BIT)
    pc, _ran, _stop = settle(longrun, m, pc, pits, args.window // 2, args.chunk)
    after_mod = screen()
    mark("press+release MOD", before, after_mod, n0)

    before, n0 = after_mod, len(cap.frames)
    panelin.encoder(m, profile, ENCODER_A, args.delta)
    pc, _ran, _stop = settle(longrun, m, pc, pits, args.window, args.chunk)
    after_enc = screen()
    mark("ENCODER A %+d" % args.delta, before, after_enc, n0)

    # The step PNGs are the honest state at each step, blank frames included.
    # A blank one is a real observation, not a bad capture -- but it makes a
    # poor illustration, so the richest frame of the whole run is archived too.
    best = max(cap.frames, key=lambda f: len(panel.lit(f))) if cap.frames else None
    best_png = write_png("best frame", best) if best is not None else None

    return {
        "best_frame_png": best_png,
        "best_frame_lit": len(panel.lit(best)) if best is not None else None,
        "snapshot": args.snapshot,
        "digikit": str(root),
        "mod_button_code": mod_code,
        "buttons_named": len(names),
        "window": args.window,
        "delta": args.delta,
        "frames_composed": len(cap.frames),
        "distinct_frames": len(cap.distinct()),
        "steps": steps,
        "screens": {
            "after_idle": panel.ascii_art(idle) and list(panel.ascii_art(idle)),
            "after_mod": list(panel.ascii_art(after_mod)) if after_mod else None,
            "after_encoder": list(panel.ascii_art(after_enc)) if after_enc else None,
        },
    }


def print_report(report) -> None:
    print(json.dumps({k: v for k, v in report.items() if k != "screens"}, indent=2))

    if not report["frames_composed"]:
        print("\n*** NO FRAMES: the UI never drew, so nothing below is about "
              "input. Resume a rung whose intro hands over. ***")
        return

    by = {s["step"]: s["changed_bytes"] for s in report["steps"]}
    idle = by.get("idle (no input)") or 0
    mod = next(v for k, v in by.items() if k.startswith("press+release"))
    enc = next(v for k, v in by.items() if k.startswith("ENCODER"))

    print("\nidle churn: %d bytes changed with no input at all." % idle)
    if idle:
        print("The screen moves on its own, so a change below only counts if it")
        print("is clearly larger than this.")

    print("\nMOD      -> %d bytes changed" % mod)
    print("ENCODER  -> %d bytes changed" % enc)

    moved = lambda n: n > max(idle, 0)                       # noqa: E731
    print()
    if not moved(mod) and not moved(enc):
        print("INPUT NOT REACHING THE FIRMWARE. Neither a button nor an encoder")
        print("moved the screen more than it moves by itself. Nothing that")
        print("depends on driving the UI can be trusted yet.")
    elif moved(mod) and not moved(enc):
        print("NAVIGATION WORKS, DELTAS DO NOT -- which is exactly the bug")
        print("digikit's author flagged. Buttons may be used to drive probes;")
        print("an encoder-driven result would be measuring an event that")
        print("changes no value.")
    elif moved(enc) and not moved(mod):
        print("Encoder moved the screen but the button did not. Check the")
        print("MOD channel/bit against panelin.code_for before reading on.")
    else:
        print("INPUT WORKS END TO END. Both a button and an encoder change the")
        print("screen by more than it changes on its own, so the UI can be")
        print("driven and probe counts taken under input mean something.")

    for label in ("after_idle", "after_mod", "after_encoder"):
        rows = report["screens"].get(label)
        if not rows:
            continue
        print("\n--- %s ---" % label)
        for row in rows:
            print("  " + row)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--digikit", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--syx", default=None)
    parser.add_argument("--warmup", type=int, default=60_000_000)
    parser.add_argument("--window", type=int, default=40_000_000,
                        help="instructions per step, and of the idle control")
    parser.add_argument("--chunk", type=int, default=10_000_000)
    parser.add_argument("--delta", type=int, default=10, help="encoder detents")
    parser.add_argument("--weakptr", action="store_true",
                        help="step over the weak_ptr branches; refused on 1.11")
    parser.add_argument("--png-dir", default="docs/img",
                        help="archive each step's screen here as a PNG")
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
