"""Does `Sound::updateMirror` actually run, and what row does it fill?

    /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_mirror.py --build out/lfo4-tlm

**The question.** LFO4's row table is keyed by track and the engine indexes it
by voice (`docs/lfo4-build-plan.md`, "the engine's index is a VOICE"). The fix
wants the moment a sound's parameters are delivered into a row, because both the
sound and the destination are known there and nothing has to be looked up at
tick time.

`0x4004ca80` is that copy: it reads parameter `d2` from the sound at
`%a0@(14,%d2:l:2)` and writes it to `%a3@(0x1c + 2*slot)`. Its RTTI says it is a
virtual method of **`Sound`** -- slot 17 of the vtable whose typeinfo names
`5Sound` -- and `%a3` is **arg2**, so the caller decides the destination.

**Why this cannot be answered by reading.** It is dispatched through a vtable at
`0x401de138`, so no static scan finds the call sites, and `docs/display-path.md`
already records a previous attempt concluding *"a vtable-only lambda nothing
calls"* -- a conclusion this project reached twice by reading and was wrong
about twice. Only running it settles whether it runs.

**What is recorded**, per call: `this` (the Sound), `%a3` (the destination row)
and `%d2` (arg3). If `%a3` takes sixteen distinct values that stride by 202, it
is the per-voice mirror and this is the delivery moment we want. If it is one
fixed buffer, it is a staging area and the fix has to look elsewhere.

**Read-only.** It hooks and observes; it changes no memory.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import emu_boot_engine as eng                                  # noqa: E402
from emu import dspboot                                        # noqa: E402
from unicorn import UC_HOOK_CODE                               # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A7                  # noqa: E402

UPDATE_MIRROR = 0x4004CA80


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-tlm")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--frames", type=int, default=8)
    args = p.parse_args()

    build = os.path.join(eng.ROOT, args.build)
    calls = []
    holder = {}

    def pre_start(m):
        def at_copy(uc, address, size, user):
            # Entry: nothing pushed yet, so %sp@(4).. are the arguments.
            sp = uc.reg_read(UC_M68K_REG_A7)
            try:
                a = struct.unpack(">3I", bytes(uc.mem_read(sp + 4, 12)))
            except Exception:                                   # noqa: BLE001
                return
            if len(calls) < 4000:
                calls.append(a)
        m.uc.hook_add(UC_HOOK_CODE, at_copy, begin=UPDATE_MIRROR, end=UPDATE_MIRROR)

    print(f"  booting {os.path.basename(build)} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(eng.SYX,
                              open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}")
    print(f"\n  Sound::updateMirror (0x4004ca80) ran {len(calls)} time(s) during boot")

    if not calls:
        print("  ** it never ran. The previous static reading stands, and the fix")
        print("     must find the delivery moment somewhere else. **")
        return 0

    dests = collections.Counter(c[1] for c in calls)
    sounds = collections.Counter(c[0] for c in calls)
    print(f"  distinct destinations (%a3): {len(dests)}   distinct sounds (this): {len(sounds)}")
    ds = sorted(dests)
    for d in ds[:12]:
        print(f"    dest {d:#010x}  x{dests[d]}")
    if len(ds) > 1:
        gaps = sorted({ds[i + 1] - ds[i] for i in range(len(ds) - 1)})
        print(f"  gaps between destinations: {[hex(g) for g in gaps[:6]]}")
        if 202 in gaps:
            print("  ** a 202-byte stride: this is the per-voice mirror, and this is")
            print("     the delivery moment the fix wants. **")
    else:
        print("  ** one fixed destination: a staging buffer, not per-voice rows. **")

    out = pathlib.Path(eng.ROOT) / "out" / "updatemirror-calls.json"
    out.write_text(json.dumps([[f"{x:#x}" for x in c] for c in calls[:400]], indent=1))
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
