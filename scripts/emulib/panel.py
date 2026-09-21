"""Driving the instrument as a person would, and keeping what the screen said.

Two things here are not obvious and have each cost a run:

**A tap is not a hold.** The firmware calls a press longer than about 7.5 M
instructions a hold, and the natural pacing of a harness is longer than that.
So `tap` releases inside `TAP`, and `hold` is the one that lingers. A held
`[MOD]` does not cycle the pages.

**And a dwell is only a dwell if something reads it.** `settle` used to spin a
full `CHUNK` whatever it was asked for, so every tap ran 10 M and was a hold
after all -- while the code said `TAP = 2_000_000` and a `--dwell` argument
sat there being passed and ignored. It cost a sweep that reported the same
result at 500 K and at 2 M and a plan note blaming the instrument, so: a
constant that names a duration is a claim, and the first probe to lean on one
should check that changing it changes something.

**A plain turn does nothing in a menu.** Values move when the encoder's push is
held *while* it turns, which is what `push_and_turn` does. A probe that turned
without holding reported zero writes -- a clean-looking null that meant nothing.

The timers are claimed through digikit's `restore_timers`, never constructed:
`ui1200M` carries armed DMA timer registers, and ordinary construction
"repairs" them as stale, which is exactly the state the snapshot exists to hold.
"""

from __future__ import annotations

import pathlib

TAP = 2_000_000                     # well inside the hold threshold
SETTLE = 10_000_000                 # let the UI compose after an input
CHUNK = 10_000_000

# (channel, bit); `code_for` is channel * 8 + bit + 1, so code = these + 1.
MOD = (0, 5)
UP, DOWN = (1, 2), (1, 5)
YES, NO = (1, 1), (1, 3)            # codes 10 and 12, from the firmware's own table
LEFT, RIGHT = (1, 4), (1, 6)
ENCODER_PUSH = [(5, b) for b in range(8)]      # A..H, codes 41..48


class Panel:
    """A `Machine` driven through its front panel."""

    def __init__(self, machine, png_dir="out/screens"):
        from emu import config, panel, panelin, symbols
        from emu.dtim import restore_timers

        self.m = machine
        self.panel, self.panelin = panel, panelin
        self.profile = symbols.resolve(open(config.main_image(), "rb").read())
        # Capture at `panel_diff` entry, the only moment the front buffer holds
        # a complete, untorn frame (digikit's `emu/panel.py`). `hook_at` is the
        # registrar `longrun.build` returns -- an earlier version of this looked
        # for it in `ev`, found nothing, and quietly captured no frames at all.
        self.capture = panel.Capture(machine.hook_at, diff_addr=self.profile.panel_diff,
                                     front_addr=self.profile.fb_front)
        self.timers = restore_timers(machine.m, machine.ev["deferred_checkpoint_restore"])
        if self.timers is None:
            raise SystemExit("this snapshot carries no timer state to claim")
        self.png_dir = pathlib.Path(png_dir)

    # --- time ---------------------------------------------------------------
    def settle(self, instructions=SETTLE):
        """Run for `instructions`, in chunks. -> what it actually ran.

        The budget is `min(CHUNK, what is left)`, and the `min` is the whole
        point: an earlier version passed `CHUNK` every time, so **every window
        shorter than a chunk ran a full chunk**. `tap` asked for 2 M and got
        10 M, past the hold threshold -- so every tap this harness ever made
        was a hold, and `--dwell` changed nothing because nothing read it. The
        page probes that came out identical at 500 K and at 2 M were measuring
        the same 10 M twice.

        A window that executes nothing ends it: `spin` returns normally having
        run zero when a vector has no handler, and a caller that only watches
        the screen reads that as "the input did nothing".
        """
        from emu import longrun

        done = 0
        while done < instructions:
            budget = min(CHUNK, instructions - done)
            self.m.pc, ran, _stop = longrun.spin(self.m.m, self.m.pc, budget,
                                                 pits=self.timers, fast=True)
            done += ran
            if ran == 0:
                break
        return done

    # --- input --------------------------------------------------------------
    def tap(self, key, after=SETTLE):
        channel, bit = key
        self.m.pc = self.panelin.press(self.m.m, self.profile, channel, bit)
        self.settle(TAP)
        self.m.pc = self.panelin.release(self.m.m, self.profile, channel, bit)
        return self.settle(after)

    def hold(self, key, instructions=SETTLE):
        channel, bit = key
        self.m.pc = self.panelin.press(self.m.m, self.profile, channel, bit)
        return self.settle(instructions)

    def let_go(self, key, after=SETTLE):
        channel, bit = key
        self.m.pc = self.panelin.release(self.m.m, self.profile, channel, bit)
        return self.settle(after)

    def push_and_turn(self, encoder, delta, times=2, dwell=SETTLE // 2):
        """Hold the encoder's push and turn it -- the only thing that moves a
        value in a menu."""
        push = ENCODER_PUSH[encoder]
        self.hold(push, dwell)
        for _ in range(times):
            self.m.pc = self.panelin.encoder(self.m.m, self.profile, encoder, delta)
            self.settle(dwell)
        self.let_go(push, dwell)

    # --- what the screen said ------------------------------------------------
    def frames(self):
        return len(self.capture.frames) if self.capture else 0

    def screen(self, name):
        """Archive the last untorn frame. -> its path, or a note.

        The screens are the evidence: a slot number says which parameter moved,
        a picture says which page was open. They are a 128x64 mono panel and
        carry no firmware bytes.
        """
        if not self.capture or not self.capture.frames:
            return "(no frame composed)"
        self.png_dir.mkdir(parents=True, exist_ok=True)
        path = self.png_dir / f"{name}.png"
        self.panel.write_png(bytes(self.capture.frames[-1]), str(path))
        return str(path)
