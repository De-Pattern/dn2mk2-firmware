"""Find the display path by watching who writes to the framebuffer.

## Why this and not another named guess

This project has named the display path twice by reading code, and been wrong
twice. `Sound::updateMirror` was a lambda in a vtable slot that nothing calls;
`parameter_value_getter` was anchored on a real instruction but forcing its
return changed nothing on screen. The rule that came out of it
(`docs/version-anchors.md`) is that **an address confirmed by an instruction
pattern is not a confirmed role, and only the role justifies a hook.**

So do not look for a function that seems to draw. Watch the bytes that *are*
the screen, and record the `pc` of every instruction that writes one. A pc is
not a guess: whatever wrote the pixel is on the display path by definition.

The screen is a pair of 1024-byte buffers whose addresses digikit resolves per
image as `fb_front` / `fb_back` (`emu/panel.py`): the main OS composes text and
widgets straight into them, `panel_diff` diffs the two and flushes the changed
runs, then swaps the pointers. Both are watched here, because which one is
being painted alternates every frame.

## The two controls, and what each one separates

**Frames.** `panel_diff` is hooked and counted. If no frame was composed, the
UI never drew and nothing below is about drawing — the same liveness gate
`scripts/call_map.py` uses, for the same reason.

**The write hook itself.** This is the first run in this project able to check
it. `scripts/write_map.py` used `install_mmio_trace` over candidate RAM and got
`events: 0` twice, and both times the run was too short to reach the code that
writes — so *"the hooks do not fire"* and *"nothing wrote"* were never
separated. Here they are, because a composed frame **must** have been painted:

| frames | writes | verdict |
|---|---|---|
| 0 | — | the UI never drew; no reading |
| >0 | 0 | **the write hook is blind** — and `write_map.py`'s zeros mean nothing |
| >0 | >0 | the instrument works; the pc histogram is the display path |

That middle row is worth the run on its own, whichever way it falls.

## What this produces, and what resolves it

A histogram of writing `pc`s, not function names — naming is a separate job and
a separate tool. Feed the pcs back through the analyser that already exists:

    dnfw fn <image> entry   --at 0x40126xxx     # which function is this in
    dnfw fn <image> callers --at <that entry>   # and who calls it

Needs digikit (`docs/emulator.md`) and its patched Unicorn, so run it under WSL
with digikit's interpreter. No firmware bytes are read from or written to this
repository.

    python scripts/paint_map.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap \
        --json out/paint-map-1.11.json
"""

import argparse
import collections
import json
import pathlib
import sys
import time

FB_BYTES = 1024  # one 128x64 mono panel buffer, 8 pages of 128 columns


class PaintSink:
    """An `install_mmio_trace` sink that buckets framebuffer writes by pc.

    Counts in memory. A line per event would be hopeless: a single full frame
    is up to 2,048 byte writes and the run composes hundreds.
    """

    def __init__(self):
        self.writes = collections.Counter()
        self.reads = collections.Counter()
        self.widths = collections.defaultdict(collections.Counter)
        self.first_addr = {}
        self.events = 0

    def event(self, *, pc, address, width, direction, value,
              register=None, instruction_count=None, read_phase=None):
        self.events += 1
        if direction == "write":
            self.writes[pc] += 1
            self.widths[pc][width] += 1
            self.first_addr.setdefault(pc, address)
        else:
            self.reads[pc] += 1

    def close(self):
        pass


def run(args) -> dict:
    root = pathlib.Path(args.digikit).resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tools"))
    from emu import longrun, symbols, config  # noqa: E402  (needs the path above)
    from emu.dtim import Dtims, Timers  # noqa: E402
    from emu.pit import Pits, intro_running  # noqa: E402

    main_img = open(config.main_image(), "rb").read()
    profile = symbols.resolve(main_img)
    if profile.fb_front is None or profile.fb_back is None:
        raise SystemExit("fb_front/fb_back did not resolve for this image; "
                         "there is nothing to watch.\n" + profile.report())

    m, ev, st, pc, inq, at = longrun.build(
        args.snapshot, syx=args.syx, unblock=True,
        softfloat=True, dsp=True, sdgate=True, esdhc=True)

    # `fb_front` and `fb_back` are the addresses of the **pointers**, not of the
    # buffers -- they sit four bytes apart, and `emu.panel.read()` dereferences
    # them before reading 1024 bytes. Watching them directly watches the pointer
    # variables and whatever RAM follows, which is not the screen: the first run
    # of this script did exactly that and produced a confident table of six pcs
    # that paint nothing. Dereference first, then watch what they point at.
    buffers = []
    for name, ptr_addr in (("fb_front", profile.fb_front),
                           ("fb_back", profile.fb_back)):
        addr = int.from_bytes(bytes(m.uc.mem_read(ptr_addr, 4)), "big")
        if not addr:
            raise SystemExit("%s at 0x%08x holds a null pointer; the buffers "
                             "are not set up in this snapshot" % (name, ptr_addr))
        buffers.append({"name": name, "pointer_at": ptr_addr, "buffer": addr})

    sink = PaintSink()
    if not args.no_hooks:
        m.install_mmio_trace(
            sink, ranges=[(b["buffer"], b["buffer"] + FB_BYTES - 1)
                          for b in buffers])

    frames = [0]
    if profile.panel_diff is not None:
        at(profile.panel_diff, lambda uc, a, s, d: frames.__setitem__(0, frames[0] + 1))

    # Same timer wiring as scripts/call_map.py, and not optional for the same
    # reason: without PIT2 and DMA timer 3 the main application task makes one
    # pass through its message loop and waits forever, so nothing draws.
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

    rows = [{
        "pc": pc_,
        "writes": n,
        "reads": sink.reads.get(pc_, 0),
        "widths": dict(sink.widths[pc_]),
        "first_addr": sink.first_addr.get(pc_),
    } for pc_, n in sink.writes.most_common(args.top)]

    return {
        "snapshot": args.snapshot,
        "digikit": str(root),
        "hooks_installed": not args.no_hooks,
        "buffers": buffers,
        "instructions": executed,
        "stop": stop,
        "elapsed_s": round(time.time() - t0, 1),
        "frames_composed": frames[0],
        "events": sink.events,
        "total_writes": sum(sink.writes.values()),
        "distinct_write_pcs": len(sink.writes),
        "rows": rows,
    }


def print_report(report) -> None:
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))

    if not report["hooks_installed"]:
        print("\n*** --no-hooks: the non-interference baseline. Compare "
              "`instructions`, `stop` and `frames_composed` with the hooked run. ***")
        return

    if not report["frames_composed"]:
        print("\n*** NO FRAMES: the UI never composed one, so nothing was "
              "painted and this says nothing about the display path. Resume a "
              "rung whose intro hands over -- ask emu.run.usable_rung(). ***")
        return

    if not report["total_writes"]:
        print("\n*** WRITE HOOK BLIND: %d frames were composed, so the "
              "framebuffer WAS painted, and the hook saw none of it. "
              "install_mmio_trace does not fire here -- which also means every "
              "zero scripts/write_map.py has ever printed is meaningless. ***"
              % report["frames_composed"])
        return

    print("\ninstrument OK: %d frames composed and %d framebuffer writes seen "
          "from %d distinct pcs, so install_mmio_trace fires."
          % (report["frames_composed"], report["total_writes"],
             report["distinct_write_pcs"]))

    print("\n%-12s %10s %10s  %-16s %s"
          % ("pc", "writes", "reads", "widths", "first address"))
    for row in report["rows"]:
        widths = " ".join("%sb:%d" % (w, n) for w, n in sorted(row["widths"].items()))
        print("0x%08x %10d %10d  %-16s 0x%08x"
              % (row["pc"], row["writes"], row["reads"], widths, row["first_addr"]))

    print("\nEvery pc above wrote a byte of the screen, so every one is on the")
    print("display path by definition -- no pattern match, no named guess.")
    print("Resolve them to functions with the tool that already does that:")
    print("    dnfw fn <image> entry --at <pc>")
    print("and then `callers --at <entry>` to walk back toward the page view.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--digikit", required=True, help="path to the digikit clone")
    parser.add_argument("--snapshot", required=True, help="boot snapshot to resume")
    parser.add_argument("--syx", default=None, help="firmware, for build() provenance")
    parser.add_argument("--slice-size", type=int, default=10_000_000)
    parser.add_argument("--slices", type=int, default=20)
    parser.add_argument("--top", type=int, default=40, help="how many pcs to report")
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
    return 0 if (report["frames_composed"] and report["total_writes"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
