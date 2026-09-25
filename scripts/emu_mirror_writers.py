"""Who writes the mirror rows, and which row does each writer touch?

    /root/dn2-emu-venv/bin/python -u scripts/emu_mirror_writers.py --build out/lfo4-tlm

**The question, and why this shape of it.** LFO4's row table is keyed by track
and the engine's index is a voice (`docs/lfo4-build-plan.md`, "the engine's
index is a VOICE"). The owner's point is that stock LFO1-3 never look anything
up: their parameters are already in the row the engine hands the evaluator,
because something put them there. Finding *that* writer is the fix.

**Why not hook a named function.** The previous attempt hooked one statically
chosen candidate, `Sound::updateMirror` at `0x4004ca80`, and reported zero calls
-- which says nothing, because it was a plain boot: no kit loads and the audio
engine never runs, so the delivery moment never arrives. A negative from a probe
that was never in the path is not evidence, and this project has twice recorded
a wrong static reading of this same area (`docs/display-path.md`, "a vtable-only
lambda nothing calls"). So this asks the machine the question directly: **watch
the memory, not a guess about who writes it.**

Every write into `0x800068E4 + 34 + 202*block` for sixteen blocks is recorded
with the PC that made it. The histogram of PCs *is* the list of writers, found
rather than assumed, and the set of blocks each PC touches says whether that
writer is per-track, per-voice or global.

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
from unicorn import UC_HOOK_MEM_WRITE, UcError                 # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_PC                  # noqa: E402

MIRROR_BASE = 0x800068E4
MIRROR_AT = 34
MIRROR_STRIDE = 202
TRACKS = 16

LO = MIRROR_BASE
HI = MIRROR_BASE + MIRROR_AT + MIRROR_STRIDE * TRACKS - 1

UPDATE_MIRROR = 0x4004CA80          # the candidate, still counted for the record


def block_of(address):
    """-> the mirror block this address falls in, or None for the lead-in."""
    off = address - MIRROR_BASE - MIRROR_AT
    if off < 0:
        return None
    b = off // MIRROR_STRIDE
    return b if 0 <= b < TRACKS else None


def report(writes, um_calls, phase):
    print(f"\n  == {phase}: {len(writes)} write(s) into the mirror ==")
    if not writes:
        print("     nothing wrote it in this phase")
        return
    by_pc = collections.defaultdict(list)
    for pc, addr, size, value in writes:
        by_pc[pc].append(addr)
    print(f"     {len(by_pc)} distinct writer PC(s); "
          f"Sound::updateMirror ran {um_calls} time(s)")
    for pc, addrs in sorted(by_pc.items(), key=lambda kv: -len(kv[1]))[:14]:
        blocks = sorted({b for b in (block_of(a) for a in addrs) if b is not None})
        slots = sorted({(a - MIRROR_BASE - MIRROR_AT) % MIRROR_STRIDE // 2
                        for a in addrs if block_of(a) is not None})
        shape = ("all 16 blocks" if len(blocks) == TRACKS else
                 f"blocks {blocks}" if blocks else "lead-in only")
        print(f"     pc {pc:#010x}  x{len(addrs):<6} {shape}")
        print(f"                     slots {slots[:14]}{' ...' if len(slots) > 14 else ''}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-tlm")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--frames", type=int, default=4)
    args = p.parse_args()

    build = os.path.join(eng.ROOT, args.build)
    holder = {}
    writes = []                      # the live bucket; swapped between phases
    um = [0]

    def pre_start(m):
        def wrote(uc, access, address, size, value, user):
            if len(writes) < 200_000:
                writes.append((uc.reg_read(UC_M68K_REG_PC), address, size, value))

        def at_um(uc, address, size, user):
            um[0] += 1

        m.uc.hook_add(UC_HOOK_MEM_WRITE, wrote, begin=LO, end=HI)
        from unicorn import UC_HOOK_CODE
        m.uc.hook_add(UC_HOOK_CODE, at_um, begin=UPDATE_MIRROR, end=UPDATE_MIRROR)

    print(f"  watching {LO:#010x}..{HI:#010x} through a boot of "
          f"{os.path.basename(build)}, {args.limit:,} instructions")
    m, st, stop = dspboot.run(eng.SYX,
                              open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}")

    boot_writes, boot_um = list(writes), um[0]
    report(boot_writes, boot_um, "boot from reset")

    # **The phase the previous probe never reached.** A boot loads no kit and
    # runs no audio, so a delivery into a row cannot happen there. This drives
    # the engine and then pushes a stored sound through the LOAD converter,
    # which is where a sound's parameters would travel into a row.
    writes.clear()
    um[0] = 0
    after = eng.After(m.uc)
    span = eng.MIRROR_AT + eng.TRACKS * eng.MIRROR_BYTES + 32
    buf = after.alloc(span)
    after.write(buf, struct.pack(">H", eng.REST) * (span // 2))
    for base in eng.STATE:
        after.write(base, bytes(eng.STATE_LEN))
    frac = after.alloc(len(eng.SET_FRAC))
    after.write(frac, eng.SET_FRAC)
    after.call(frac)
    rate = after.long(eng.RATE)
    out1, out2 = after.alloc(256), after.alloc(256)
    print(f"\n  entering evaluator A at {eng.EVAL_A:#010x}, {args.frames} frame(s)")
    try:
        for _ in range(args.frames):
            after.call(eng.EVAL_A, buf, rate, 0xFFFF, 0xFFFF, out1, out2, 0)
    except UcError as exc:
        print(f"  ** the evaluator faulted: {exc} **")
    report(list(writes), um[0], "evaluator A")

    writes.clear()
    um[0] = 0
    src = eng.stored_sound(after, eng.MARKS)
    live = after.alloc(eng.SOUND_BYTES)
    print(f"\n  pushing a stored sound through LOAD at {eng.LOAD:#010x}")
    try:
        after.call(eng.LOAD, live, src)
    except UcError as exc:
        print(f"  ** LOAD faulted: {exc} **")
    report(list(writes), um[0], "LOAD a stored sound")

    out = pathlib.Path(eng.ROOT) / "out" / "mirror-writers.json"
    out.write_text(json.dumps(
        {"boot": [[f"{pc:#x}", f"{a:#x}", s, v] for pc, a, s, v in boot_writes[:2000]]},
        indent=1))
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
