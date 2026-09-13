"""Does a held button lapse in the emulator if the state is not re-sent?

## The question, and why it is not obvious

`m-dwyer/digikit#9` reports that Digitakt II's MACHINE SEL menu "usually closes
within a second, **with or without the patch**". With or without is the
important half: it is not the patch.

One explanation would tie it to something this project already measured. The
panel wire tags buttons `0x2` and encoders `0x3`, and `m-dwyer/digikit#6` found
the per-encoder accumulator is drained only when a **button** message arrives --
the drainer is gated on the tag. The inference drawn there was that real
hardware **streams** button state continuously, and the firmware's input
handling rides on that stream. If so, a modifier held by one message and never
refreshed would lapse, and "within a second" is the shape of a panel-link
watchdog.

**But digikit's own docstring argues the other way**, and it is worth quoting
because it is the reason this is a real test rather than a demonstration:

    tag 0x2  1 byte  buttons -- an 8-bit STATE BITMASK for that channel's
                     eight buttons, not a press/release event. The firmware
                     XORs it against the previous byte for the channel and
                     derives the edges itself, so a caller only has to say
                     what is held right now.

If the firmware only XORs against the previous byte, state persists with no
timeout and sending once is enough. So the two readings predict opposite
results, which is exactly what a test needs.

## The design

Three windows of equal length, on one boot, in this order:

    idle -> hold (send once) -> idle -> hold (re-send every slice) -> idle

and the measurement is the **screen**, sampled at `panel_diff` entry the way
`scripts/drive.py` established is the only moment a frame is untorn. Holding
`[FUNC]` on an Elektron box changes what is drawn, so "is the modifier still
held" is visible without needing a named menu or any internal address.

The idle windows either side are the control, and they are not optional: the UI
churns on its own, so "the screen changed" is only evidence if the alternative
was measured on the same boot.

**What each outcome means**

- send-once reverts, re-send stays  -> the stream hypothesis is right, and it is
  the same root cause as digikit#6
- both stay held                    -> state persists; the menu bug is
                                       something else entirely
- both revert together              -> the modifier is not reaching the UI at
                                       all, and this test says nothing about
                                       timeouts

## THE ANSWER, measured 2026-09-14: the driver latches. The hypothesis is wrong.

Run on Digitone II 1.11 from the 400M rung. `[FUNC]` (code 17, channel 2, bit 0)
pressed once, never re-sent, then held for **600M instructions**:

```
0x445a0983  idle=0x00 -> after 1 slice 0x01, after 59 0x01, after 60 0x01
0x445a0df7  idle=0x00 -> after 1 slice 0x01, after 59 0x01, after 60 0x01
```

Two bytes take the FUNC mask and still hold it after 60 slices with nothing
refreshing them. Idle churn across the same window is **1 byte**, so the
measurement is clean.

**So digikit's docstring is right and the streaming idea is wrong.** The panel
state does not need refreshing, there is no driver-level timeout, and whatever
closes MACHINE SEL is above the driver. It is not the same root cause as
`digikit#6`.

Two instruments were discarded getting here, both recorded because the reasons
recur:

- **The screen.** Holding `[FUNC]` changes nothing drawable on this build:
  deviation `+0` against an idle spread of 2, identical whether held once or
  streamed. That is the outcome meaning *this test measured nothing*, not a
  finding.
- **A write trace.** It named `0x445a0df4`, which takes the mask and is zero
  again by the next sample -- a transient edge byte consumed within one slice.
  A write trace shows what was written, not what survived, so the persistent
  store had to be found by diffing snapshots instead.

Needs digikit and its patched Unicorn (`docs/emulator.md`), so run under WSL
with digikit's interpreter. No firmware bytes are read from or written to this
repository.

    python scripts/hold_test.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap \
        --button FUNC --diff-state --watch-lo 0x445a0000 --watch-hi 0x445a2000 \
        --slices 60
"""

import argparse
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

    # The control is found BY NAME from the firmware's own table, never by a
    # hardcoded channel/bit -- emu/serial.py hardcoded Digitakt's addresses and
    # was silently wrong on Digitone, which is the mistake this avoids.
    names = panelin.control_names(m, profile, "button")
    target = None
    for code, name in sorted(names.items()):
        if name.strip().upper() == args.button.upper():
            target = code
            break
    if target is None:
        raise SystemExit(
            f"no button named {args.button!r}. Available: "
            + ", ".join(sorted({v.strip() for v in names.values()}))[:600])

    # code_for(channel, bit) is digikit's mapping; invert it by search rather
    # than re-deriving the arithmetic.
    chan = bit = None
    for c in range(8):
        for b in range(8):
            if panelin.code_for(c, b) == target:
                chan, bit = c, b
    if chan is None:
        raise SystemExit(f"{args.button} (code {target}) has no wire position")

    lit = lambda f: sum(bin(x).count("1") for x in f) if f else 0

    def screen():
        return bytes(cap.frames[-1]) if cap.frames else None

    def spin_one():
        nonlocal pc
        pc, ran, _ = longrun.spin(m, pc, args.slice_size, pits=pits, fast=True)
        return ran

    def window(label, slices, mode):
        """-> per-slice lit-pixel counts. mode: idle | once | stream."""
        nonlocal pc
        out = []
        for i in range(slices):
            if mode == "once" and i == 0:
                pc = panelin.buttons(m, profile, chan, 1 << bit)
            elif mode == "stream":
                pc = panelin.buttons(m, profile, chan, 1 << bit)
            if spin_one() == 0:
                break
            out.append(lit(screen()))
        # release, whichever mode
        if mode in ("once", "stream"):
            pc = panelin.buttons(m, profile, chan, 0)
            spin_one()
        return out

    t0 = time.time()
    for _ in range(args.warmup):
        spin_one()

    idle_a = window("idle A", args.slices, "idle")
    once = window("hold, sent once", args.slices, "once")
    idle_b = window("idle B", args.slices, "idle")
    stream = window("hold, re-sent", args.slices, "stream")
    idle_c = window("idle C", args.slices, "idle")

    return {
        "button": args.button, "code": target, "channel": chan, "bit": bit,
        "slices": args.slices, "slice_size": args.slice_size,
        "frames_composed": len(cap.frames),
        "elapsed_s": round(time.time() - t0, 1),
        "idle_a": idle_a, "once": once, "idle_b": idle_b,
        "stream": stream, "idle_c": idle_c,
    }


def find_state(args) -> int:
    """Locate the byte the panel driver keeps a channel's button state in.

    The screen turned out to be the wrong instrument: holding `[FUNC]` on this
    build changes nothing drawable, so a lit-pixel count cannot tell a held
    modifier from a lapsed one -- it reads +0 either way, which is the outcome
    that means "this test measured nothing".

    The driver itself is a better witness. digikit's own wire note says the
    firmware "XORs it against the previous byte for the channel", so a previous
    byte is *stored*, and whatever holds it is the state this question is about.
    This finds it by watching writes in the driver's data window while a button
    message is fed, rather than by naming an address -- the same discipline
    `docs/display-path.md` used for the framebuffer, and for the same reason.
    """
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

    names = panelin.control_names(m, profile, "button")
    target = next((c for c, n in names.items()
                   if n.strip().upper() == args.button.upper()), None)
    chan = bit = None
    for c in range(8):
        for b in range(8):
            if panelin.code_for(c, b) == target:
                chan, bit = c, b

    lo, hi = args.watch_lo, args.watch_hi
    writes = {}

    class Sink:
        """install_mmio_trace wants an object with .event(), not a function.

        Passing a plain callable fails inside digikit's harness with
        `'function' object has no attribute 'event'` -- their interface, and
        scripts/paint_map.py already models it correctly.
        """

        def event(self, *, pc, address, width, direction, value,
                  register=None, instruction_count=None, read_phase=None):
            if direction != "write":
                return
            writes.setdefault(address, []).append((value, pc))

    m.install_mmio_trace(Sink(), ranges=[(lo, hi)])

    for _ in range(args.warmup):
        pc, ran, _ = longrun.spin(m, pc, args.slice_size, pits=pits, fast=True)
    writes.clear()

    mask = 1 << bit
    pc = panelin.buttons(m, profile, chan, mask)
    pc, _, _ = longrun.spin(m, pc, args.slice_size, pits=pits, fast=True)
    down = dict(writes)
    writes.clear()
    pc = panelin.buttons(m, profile, chan, 0)
    pc, _, _ = longrun.spin(m, pc, args.slice_size, pits=pits, fast=True)

    print(f"{args.button}: code={target} channel={chan} bit={bit} mask=0x{mask:02x}")
    print(f"watching 0x{lo:08x}..0x{hi:08x}\n")
    hits = [(a, v) for a, v in down.items()
            if any(val == mask for val, _ in v)]
    print(f"{len(down)} addresses written while the button was down; "
          f"{len(hits)} took the value 0x{mask:02x}:")
    for a, v in sorted(hits)[:20]:
        print(f"  0x{a:08x}  values={[hex(x) for x, _ in v][:6]}  "
              f"pc={[hex(p) for _, p in v][:3]}")
    if not hits:
        print("  none -- the state is kept outside this window, or as a "
              "different\n  encoding than the raw mask. Widen --watch-lo/"
              "--watch-hi.")
    return 0


def diff_state(args) -> int:
    """Find bytes that go set on press and STAY set while held.

    --watch-addr found 0x445a0df4 takes the mask value and is zero again by the
    next sample: a transient edge byte, consumed within one slice. The byte the
    question is about is the one that persists, so this compares snapshots of
    the whole driver window instead of tracing writes -- a write trace shows
    what was written, not what survived.
    """
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

    names = panelin.control_names(m, profile, "button")
    target = next((c for c, n in names.items()
                   if n.strip().upper() == args.button.upper()), None)
    chan = bit = None
    for c in range(8):
        for b in range(8):
            if panelin.code_for(c, b) == target:
                chan, bit = c, b
    mask = 1 << bit
    lo, hi = args.watch_lo, args.watch_hi

    def snap():
        return bytes(m.uc.mem_read(lo, hi - lo))

    def spin():
        nonlocal pc
        pc, ran, _ = longrun.spin(m, pc, args.slice_size, pits=pits, fast=True)

    for _ in range(args.warmup):
        spin()

    # Two idle snapshots first: whatever differs between THEM is churn, and
    # must not be reported as a response to the button.
    a0 = snap(); spin(); a1 = snap()
    churn = {i for i in range(len(a0)) if a0[i] != a1[i]}

    # Hold for the full --slices, not a token few. The bug being chased is
    # "closes within a second"; three slices is ~30M instructions, well under
    # that, so a short hold could show a latch that later lapses and call the
    # question closed on the strength of not having waited.
    pc = panelin.buttons(m, profile, chan, mask)
    spin(); b1 = snap()
    for _ in range(max(args.slices - 2, 1)):
        spin()
    b2 = snap()
    spin(); b3 = snap()

    changed = [i for i in range(len(a1))
               if i not in churn and (b1[i] != a1[i])]
    print(f"{args.button}: channel={chan} bit={bit} mask=0x{mask:02x}")
    print(f"window 0x{lo:08x}..0x{hi:08x}   idle churn: {len(churn)} bytes\n")
    print(f"{len(changed)} byte(s) changed on press and are not churn:")
    for i in changed[:24]:
        print(f"  0x{lo+i:08x}  idle=0x{a1[i]:02x} -> "
              f"after 1 slice 0x{b1[i]:02x}, after {args.slices - 1} "
              f"0x{b2[i]:02x}, after {args.slices} 0x{b3[i]:02x}"
              + ("   <-- holds the mask" if b3[i] == mask else ""))
    holds = [i for i in changed if b1[i] == mask and b3[i] == mask]
    total_m = args.slices * args.slice_size / 1e6
    print(f"\n{len(holds)} byte(s) took the mask and still hold it after "
          f"{args.slices} slices ({total_m:.0f}M instructions) "
          f"with nothing re-sent.")
    if holds:
        print("  -> the driver LATCHES the state; it does not need refreshing.")
    else:
        print("  -> nothing latched the mask. Either the state lives outside "
              "this\n     window, or it genuinely does not persist.")
    return 0


def watch_addr(args) -> int:
    """Read the driver's own state byte each slice: held once vs re-sent.

    This is the measurement the screen could not make. The byte comes from
    --find-state rather than from a guess, and the question is simply whether
    it stays set when nothing refreshes it.
    """
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

    names = panelin.control_names(m, profile, "button")
    target = next((c for c, n in names.items()
                   if n.strip().upper() == args.button.upper()), None)
    chan = bit = None
    for c in range(8):
        for b in range(8):
            if panelin.code_for(c, b) == target:
                chan, bit = c, b
    mask = 1 << bit
    addr = args.watch_addr

    def peek():
        return m.uc.mem_read(addr, 1)[0]

    def spin():
        nonlocal pc
        pc, ran, _ = longrun.spin(m, pc, args.slice_size, pits=pits, fast=True)
        return ran

    for _ in range(args.warmup):
        spin()

    out = {}
    for mode in ("once", "stream"):
        pc = panelin.buttons(m, profile, chan, mask)
        seq = []
        for i in range(args.slices):
            if mode == "stream" and i:
                pc = panelin.buttons(m, profile, chan, mask)
            spin()
            seq.append(peek())
        out[mode] = seq
        pc = panelin.buttons(m, profile, chan, 0)
        spin()
        out[mode + "_after_release"] = peek()

    print(f"{args.button}: channel={chan} bit={bit} mask=0x{mask:02x}  "
          f"watching 0x{addr:08x}\n")
    for mode in ("once", "stream"):
        seq = out[mode]
        held = sum(1 for x in seq if x & mask)
        print(f"  {mode:<7} {[hex(x) for x in seq]}")
        print(f"  {'':<7} bit set in {held}/{len(seq)} slices; "
              f"after release: 0x{out[mode + '_after_release']:02x}")
    print("\nIf 'once' loses the bit while 'stream' keeps it, the state needs"
          "\nrefreshing and the stream hypothesis holds. If both keep it, the"
          "\ndriver latches and the menu bug is higher up.")
    return 0


def spark(v):
    if not v:
        return "(nothing)"
    lo, hi = min(v), max(v)
    if hi == lo:
        return "=" * len(v) + f"  (flat at {lo})"
    ch = " .:-=+*#%@"
    return "".join(ch[min(9, int(9 * (x - lo) / (hi - lo)))] for x in v)


def report(r) -> None:
    print(json.dumps({k: v for k, v in r.items()
                      if not isinstance(v, list)}, indent=2))
    if not r["frames_composed"]:
        print("\n*** NO FRAMES COMPOSED: the UI never drew, so nothing here "
              "measures anything. ***")
        return

    print()
    for k in ("idle_a", "once", "idle_b", "stream", "idle_c"):
        v = r[k]
        print(f"  {k:<9} {spark(v)}")
        if v:
            print(f"  {'':<9} min={min(v)} max={max(v)} first={v[0]} last={v[-1]}")

    once, stream = r["once"], r["stream"]
    idle = r["idle_a"] + r["idle_b"] + r["idle_c"]
    if not (once and stream and idle):
        print("\nA window is empty -- the run stalled; no conclusion.")
        return

    import statistics
    base = statistics.median(idle)
    spread = max(idle) - min(idle)
    d_once = max(once) - base
    d_stream = max(stream) - base
    print(f"\n  idle median {base:.0f}, idle spread {spread}")
    print(f"  hold-once   peak deviation from idle: {d_once:+.0f}")
    print(f"  hold-stream peak deviation from idle: {d_stream:+.0f}")
    print("\nRead it against the idle spread, not against zero: a deviation "
          "smaller than\nthe spread is the UI churning, which is why three "
          "idle windows are measured.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--digikit", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--syx", default=None)
    p.add_argument("--button", default="FUNC")
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--slices", type=int, default=12)
    p.add_argument("--slice-size", type=int, default=10_000_000)
    p.add_argument("--json")
    p.add_argument("--find-state", action="store_true",
                   help="locate the driver byte holding this channel's state")
    p.add_argument("--watch-lo", type=lambda x: int(x, 0), default=0x445A0C00)
    p.add_argument("--watch-hi", type=lambda x: int(x, 0), default=0x445A1000)
    p.add_argument("--watch-addr", type=lambda x: int(x, 0), default=None,
                   help="read this driver byte each slice, held vs streamed")
    p.add_argument("--diff-state", action="store_true",
                   help="diff the driver window across press and hold")
    args = p.parse_args(argv)

    if args.find_state:
        return find_state(args)
    if args.watch_addr is not None:
        return watch_addr(args)
    if args.diff_state:
        return diff_state(args)

    r = run(args)
    if args.json:
        path = pathlib.Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(r, indent=2) + "\n")
    report(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
