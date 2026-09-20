"""What the MOD pages do when nothing else touches the machine.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_mod_pages.py --keys down,down,up,up

Every reading of the pages so far came from a probe that also **turned an
encoder**, because the slot a turn writes is what named the page. That couples
two mechanisms: `emu_param_setter.py` saw one DOWN travel from LFO1 to LFO3,
and then saw neither DOWN *nor UP* move again -- and a page that stops
answering both arrows is no longer a story about paging alone.

So this one never turns anything. It taps keys and keeps the screen, and the
screen is the whole result: two pages that render the same 1024 bytes are the
same page, and the console says so without anyone eyeballing a PNG.

What it separates:

- if the keys page normally here, the coupling is the encoder's -- a held push
  leaves the UI somewhere the arrows no longer mean "page";
- if the keys behave the same with no encoder in the run at all, paging itself
  is what travels two at a time, and the turn was never involved.
"""

from __future__ import annotations

import argparse
import hashlib
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.machine import SNAP, Machine                       # noqa: E402
from emulib.panel import DOWN, MOD, UP, Panel                  # noqa: E402

KEYS = {"down": DOWN, "up": UP, "mod": MOD}


def frame_id(panel):
    """-> a short digest of the last untorn frame, or None."""
    if not panel.capture or not panel.capture.frames:
        return None
    return hashlib.sha256(bytes(panel.capture.frames[-1])).hexdigest()[:8]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=60_000_000)
    p.add_argument("--keys", default="down,down,down,up,up",
                   help="the taps to make after [MOD], from " + "/".join(KEYS))
    p.add_argument("--dwell", type=int, default=0,
                   help="how long each key is held; 0 uses emulib.panel's TAP")
    p.add_argument("--png-dir", default="out/mod-pages")
    args = p.parse_args()

    machine = Machine(args.snapshot)
    panel = Panel(machine, png_dir=args.png_dir)
    if args.dwell:
        import emulib.panel as panelmod
        panelmod.TAP = args.dwell

    panel.settle(args.warmup)
    print(f"  warmed up, {panel.frames()} frame(s) composed\n")

    steps = [("[MOD]", MOD)] + [(k, KEYS[k]) for k in args.keys.split(",") if k]
    seen, pages = {}, []
    for step, (name, key) in enumerate(steps):
        panel.tap(key)
        digest = frame_id(panel)
        if digest is None:
            print(f"  {step}: {name:>7} -- no frame composed")
            continue
        page = seen.setdefault(digest, len(seen) + 1)
        pages.append(page)
        shot = panel.screen(f"{step}-{name.strip('[]')}-page{page}")
        print(f"  {step}: {name:>7} -> page {page}  ({digest})  {shot}")

    print(f"\n  the walk visited: {pages}")
    distinct = len(set(pages))
    print(f"  {distinct} distinct page(s) for {len(steps)} tap(s)")
    if distinct == 1:
        print("  nothing paged at all: the keys arrive and the view does not move.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
