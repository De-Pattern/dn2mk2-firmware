"""Which code writes a sound's parameter value when an encoder is turned?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_param_setter.py --digikit /mnt/d/01_Code/Z_Personal/digikit-up \\
        --snapshot /root/dn2-snapshots/Digitone_II_OS1.11/ui1200M.snap

LFO4's step 4 needs one address: the point where the UI's edit lands in the
live sound, so that the fourth page's ten records can be routed to the
extension table instead. The getter is known (`0x4006408a`, called with an id
and returning the value); its counterpart is not, and the static search for it
went through several plausible candidates without a decision.

So ask the machine. This drives the panel the way `scripts/drive.py` does --
the same `panelin.press` / `panelin.encoder`, the same settle loop, because
that script exists to prove input actually arrives -- with a **memory write
hook over track 1's live value array**. Whatever writes it is the setter, by
definition rather than by inference.

`sound(track) = 0x4210c08c + 52 + track * 1163` and the values start at `+0x14`
(`docs/lfo4-build-plan.md`). Track 1's array is therefore `0x4210c0d4`, 202
bytes.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

SOUND = 0x4210C08C + 52                 # track 1's live sound
VALUES, VALUES_LEN = SOUND + 0x14, 202
MOD_CHANNEL, MOD_BIT = 0, 5
ENCODER_A = 0
# Encoder A's push is control code 41, and `code_for` is channel * 8 + bit + 1,
# so it is channel 5 bit 0. Holding it while turning is what actually moves a
# value in this emulator -- a plain turn does nothing in a menu (the owner has
# had to say so twice; it is in this project's memory).
PUSH_CHANNEL, PUSH_BIT = 5, 0


def run(args) -> int:
    root = pathlib.Path(args.digikit).resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tools"))
    from emu import config, longrun, panel, panelin, symbols
    from emu.dtim import restore_timers
    from unicorn import UC_HOOK_MEM_WRITE
    from unicorn.m68k_const import UC_M68K_REG_PC

    profile = symbols.resolve(open(config.main_image(), "rb").read())
    # The flags must match the ones the snapshot was saved with, or digikit's
    # manifest guard refuses -- which it did, naming bitmap, weakptr and slc.
    # These are `scripts/lfo4_harness.py`'s, which is what ui1200M was made by.
    m, ev, st, pc, inq, at = longrun.build(
        args.snapshot, syx=args.syx, unblock=True, softfloat=True, bitmap=True,
        dsp=True, weakptr=True, slc=True, sdgate=True, esdhc=True,
        deferred_components=("timers",))
    cap = panel.Capture(at, diff_addr=profile.panel_diff, front_addr=profile.fb_front)
    # The snapshot carries armed DMA timer registers, so the timers are claimed
    # through digikit's own `restore_timers` rather than constructed: ordinary
    # construction repairs "stale" DTMR registers, which here are the state.
    pits = restore_timers(m, ev["deferred_checkpoint_restore"])
    if pits is None:
        raise SystemExit("the snapshot carries no timer state to claim")

    writes = collections.Counter()
    detail = []
    watching = {"on": False}

    def wrote(uc, access, address, size, value, user):
        if not watching["on"]:
            return
        writer = uc.reg_read(UC_M68K_REG_PC)
        writes[writer] += 1
        if len(detail) < 12:
            slot = (address - VALUES) // 2
            detail.append((writer, slot, value, size))

    m.uc.hook_add(UC_HOOK_MEM_WRITE, wrote, begin=VALUES, end=VALUES + VALUES_LEN - 1)

    def settle(instructions):
        """drive.py's loop, verbatim: a run that executes nothing is the
        interesting case, so a zero ends it rather than spinning."""
        nonlocal pc
        done = 0
        while done < instructions:
            pc, ran, stop = longrun.spin(m, pc, args.chunk, pits=pits, fast=True)
            done += ran
            if ran == 0:
                break
        return done

    print(f"watching {VALUES:#010x}..{VALUES + VALUES_LEN - 1:#010x} "
          f"(track 1's value array)\n")
    settle(args.warmup)
    print(f"  warmed up, {len(cap.frames)} frame(s) composed")

    watching["on"] = True
    settle(args.window)
    idle = sum(writes.values())
    print(f"  idle control: {idle} write(s) with no input")

    # [MOD] cycles its pages, so each one is visited and turned on: the first
    # page is not necessarily one that edits a sound value, and on a build with
    # LFO4 the fourth press is the page this whole step exists for.
    seen = idle
    for page in range(1, 5):
        pc = panelin.press(m, profile, MOD_CHANNEL, MOD_BIT)
        settle(args.window // 4)
        pc = panelin.release(m, profile, MOD_CHANNEL, MOD_BIT)
        settle(args.window // 4)
        pc = panelin.press(m, profile, PUSH_CHANNEL, PUSH_BIT)
        settle(args.window // 4)
        for _ in range(2):
            pc = panelin.encoder(m, profile, ENCODER_A, args.delta)
            settle(args.window // 4)
        pc = panelin.release(m, profile, PUSH_CHANNEL, PUSH_BIT)
        settle(args.window // 4)
        now = sum(writes.values())
        print(f"  MOD page {page}, push-and-turn {args.delta:+} x2: "
              f"{now - seen} write(s)")
        seen = now
    print("")

    if not writes:
        print("  nothing wrote the value array. Either the input never reached a\n"
              "  parameter page, or this is not the array the UI edits.")
        return 1
    print("  writers, hottest first:")
    for writer, n in writes.most_common(8):
        print(f"    {writer:#010x}  {n:,}")
    print("\n  first writes:")
    for writer, slot, value, size in detail:
        print(f"    {writer:#010x}  slot {slot:<3} <- {value:#06x} ({size} B)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--digikit", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--syx", default=None)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--window", type=int, default=40_000_000)
    p.add_argument("--chunk", type=int, default=10_000_000)
    p.add_argument("--delta", type=int, default=10)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
