"""Does the bridge look up the same sound the setter writes?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_lfo4_sound.py [--build out/lfo4-value]

The extension table is keyed by **the live sound's address**, and the two ends
of the feature learn that address differently:

- the **setter** takes it from the firmware's own virtual call, so it is
  whatever the firmware thinks it is;
- the **bridge** computes it, `LFO4_KIT + 52 + track * 1163`, from a constant
  measured once out of `ui1200M`.

If those ever disagree, every turn lands in the table under one key and every
tick looks it up under another. The page works, sounds save and reload, and
**nothing modulates** -- which is what the instrument reported.

`LFO4_KIT` is not obviously a constant: the snapshot holds that address in 24
separate places, which is what a pointer the firmware keeps looks like, not an
address fixed at link time.

So this boots from reset -- not the snapshot the constant was measured from --
and hooks `lfo4_on_load`, which the firmware calls with **its own** live sound
pointer for every sound it loads. Those addresses are the ground truth. If none
of them is one of the sixteen the bridge would compute, the constant is wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emu import dspboot                                        # noqa: E402
from unicorn import UC_HOOK_CODE                               # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A7                  # noqa: E402

from emu_boot_engine import REPORTER, ROOT, SYX                # noqa: E402
from emulib.report import check, report                        # noqa: E402

KIT_BUILT = 0x4210C08C            # what the build was told
SOUND_AT, STRIDE, TRACKS = 52, 1163, 16


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-value")
    p.add_argument("--limit", type=int, default=450_000_000)
    args = p.parse_args()

    build = os.path.join(ROOT, args.build)
    sym = {k: int(v, 16) for k, v in json.load(open(f"{build}/symbols.json")).items()}
    holder, live, fault = {}, [], {}

    def pre_start(m):
        st = holder["st"]

        def at_reporter(uc, address, size, user):
            if not fault:
                fault.update(at=st["n"])
            uc.emu_stop()

        def at_load(uc, address, size, user):
            # lfo4_on_load(live, stored): the first argument, the firmware's own
            # pointer to the sound it is filling.
            sp = uc.reg_read(UC_M68K_REG_A7)
            live.append(int.from_bytes(bytes(uc.mem_read(sp + 4, 4)), "big"))

        m.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)
        m.uc.hook_add(UC_HOOK_CODE, at_load, begin=sym["lfo4_on_load"], end=sym["lfo4_on_load"])

    print(f"  booting {os.path.basename(build)} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(SYX, open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}")
    if fault:
        print(f"  FAULT at {fault['at']:,} -- this run says nothing.")
        return 1

    computed = [KIT_BUILT + SOUND_AT + t * STRIDE for t in range(TRACKS)]
    seen = sorted(set(live))
    print(f"\n  the firmware loaded {len(live):,} sound(s), {len(seen)} distinct address(es)")
    print("  the lowest few: " + " ".join(f"{a:#010x}" for a in seen[:6]))
    print("  the highest few: " + " ".join(f"{a:#010x}" for a in seen[-6:]))
    print(f"\n  the bridge would compute, from LFO4_KIT = {KIT_BUILT:#010x}:")
    print("    " + " ".join(f"{a:#010x}" for a in computed[:6]) + " ...")

    overlap = sorted(set(computed) & set(seen))
    check("the firmware loaded any sound at all", seen, "none")
    check("the addresses the bridge computes are ones the firmware uses",
          len(overlap) == TRACKS,
          f"{len(overlap)} of {TRACKS} match: " + " ".join(f"{a:#010x}" for a in overlap[:4]))
    if len(overlap) != TRACKS:
        near = [a for a in seen if abs(a - KIT_BUILT) < 0x40000]
        print("\n  The bridge is looking up a key the setter never writes, which is")
        print("  exactly 'the page works and nothing modulates'. Addresses near the")
        print("  built-in constant: " + (" ".join(f"{a:#010x}" for a in near[:8]) or "none"))
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
