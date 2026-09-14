"""Does a button message flush the encoder accumulator? Testing digikit#6's fix.

## The blocker

`m-dwyer/digikit#6`: in the emulator an encoder delta is delivered, decoded and
queued correctly -- the firmware's own `queue_send` record shows
`type=1 code=1 delta=+5` -- the UI focuses the parameter and shows its value
overlay, and **the number never moves**. Located precisely: the per-encoder
accumulator at `0x445a0dc4` is touched by exactly two pcs, both the driver's
own, and climbs `1,2,3...` never cleared.

`docs/display-path.md` proposed why: its drainer `0x4011f9ac` is reached through
a dispatch on the **wire tag**, where tag 3 accumulates and tag 2 drains. Real
hardware streams button messages continuously, so on a device the flush arrives
constantly and for free; a test that sends only encoder messages never sends
one.

**That was a reading of the code and has never been tested.** It predicts
something specific and cheap: send an encoder delta, then *any* tag-2 message,
and the accumulator should clear.

## Why it matters now

The owner's route to the FM drum transients is: set a track to FM DRUM, go to
SYN page 4, turn knob C, and the transient index cycles. Every step after the
first needs a working encoder. If this prediction holds, the emulator can drive
parameter changes at all -- which is the gate on watching what memory the
firmware touches when a transient is selected.

## The test, and its control

The accumulator's address is known, so this does not need the screen:

    baseline   -> read it
    N encoder deltas, nothing else  -> it should CLIMB      (reproduces #6)
    one button message              -> it should CLEAR      (the prediction)
    N more deltas                   -> it should climb again

The middle step is the experiment; the first and last are what make a clear
distinguishable from "it was never counting". A run where it never climbs says
the input did not arrive and the drain result means nothing.

    python scripts/encoder_drain.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap
"""

import argparse
import pathlib
import sys

ACCUM = 0x445A0DC4        # docs/display-path.md, per-encoder accumulator
PENDING = 0x445A0DEC      # pending mask, beside it


def run(args) -> int:
    root = pathlib.Path(args.digikit).resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tools"))
    from emu import longrun, symbols, config, panelin  # noqa: E402
    from emu.dtim import Dtims, Timers  # noqa: E402
    from emu.pit import Pits, intro_running  # noqa: E402

    profile = symbols.resolve(open(config.main_image(), "rb").read())
    m, ev, st, pc, inq, at = longrun.build(
        args.snapshot, syx=args.syx, unblock=True,
        softfloat=True, dsp=True, sdgate=True, esdhc=True)
    intro = intro_running(m, profile.intro_pit3_isr)
    pits = Timers(Pits(m, hold=intro), Dtims(m, channels=(3,), hold=intro))
    if intro and profile.intro_done is not None:
        at(profile.intro_done, lambda uc, a, s, d: pits.release())

    def spin(n=1):
        nonlocal pc
        for _ in range(n):
            pc, ran, _ = longrun.spin(m, pc, args.slice_size, pits=pits,
                                      fast=True)

    def peek(addr, n=4):
        return int.from_bytes(bytes(m.uc.mem_read(addr, n)), "big")

    def state():
        return peek(args.accum), peek(args.pending)

    for _ in range(args.warmup):
        spin()

    rows = []
    rows.append(("after warmup", *state()))

    # 1. encoder deltas only -- reproduces #6 if it climbs
    for _ in range(args.deltas):
        pc = panelin.encoder(m, profile, args.encoder, 1)
        spin()
    rows.append((f"{args.deltas} encoder deltas", *state()))

    # 2a. A tag-2 message carrying NO edge: mask 0 while nothing is held. The
    #     firmware XORs against the previous byte for the channel, so this is
    #     "no change" and may be discarded before any drain runs. Measured
    #     separately because the first version of this test used only this and
    #     would have reported the hypothesis dead on a message that arguably
    #     never became a button event.
    pc = panelin.buttons(m, profile, args.button_channel, 0)
    spin()
    rows.append(("tag-2, no edge (mask 0)", *state()))

    # 2b. A real edge: press, then release. This is what hardware sends.
    pc = panelin.buttons(m, profile, args.button_channel, 1 << args.button_bit)
    spin()
    rows.append(("tag-2 press (edge)", *state()))
    pc = panelin.buttons(m, profile, args.button_channel, 0)
    spin()
    rows.append(("tag-2 release (edge)", *state()))

    # 3. climb again -- shows the counter still works after the flush
    for _ in range(args.deltas):
        pc = panelin.encoder(m, profile, args.encoder, 1)
        spin()
    rows.append((f"{args.deltas} more deltas", *state()))

    pc = panelin.buttons(m, profile, args.button_channel, 1 << args.button_bit)
    spin()
    pc = panelin.buttons(m, profile, args.button_channel, 0)
    spin()
    rows.append(("second press+release", *state()))

    print(f"\naccumulator 0x{args.accum:08x}, pending 0x{args.pending:08x}\n")
    print(f"  {'step':<30}{'accum':>12}{'pending':>12}")
    for label, a, p in rows:
        print(f"  {label:<30}{a:>12}{p:>12}")

    climbed = rows[1][1] > rows[0][1]
    # any of the tag-2 steps clearing counts
    cleared = any(r[1] < rows[1][1] for r in rows[2:5])
    print()
    if not climbed:
        print("The accumulator never climbed, so the encoder input did not")
        print("arrive. Nothing below it means anything -- fix that first.")
        return 0
    print("The accumulator climbed with encoder messages alone "
          "(reproduces digikit#6).")
    if cleared:
        print("AND a single tag-2 message cleared it. The tag-dispatch reading")
        print("holds: the emulator must stream button state for encoders to")
        print("work, exactly as hardware does.")
    else:
        print("But a tag-2 message did NOT clear it. The tag-dispatch reading")
        print("is wrong, or the drain needs something this message lacks.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--digikit", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--syx", default=None)
    p.add_argument("--encoder", type=int, default=0)
    p.add_argument("--button-channel", type=int, default=0)
    p.add_argument("--button-bit", type=int, default=5)
    p.add_argument("--deltas", type=int, default=5)
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--slice-size", type=int, default=10_000_000)
    p.add_argument("--accum", type=lambda x: int(x, 0), default=ACCUM)
    p.add_argument("--pending", type=lambda x: int(x, 0), default=PENDING)
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
