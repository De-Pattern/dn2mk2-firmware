"""Where does `param_5` sit, relative to the frame pointer our stub is handed?

    /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_frame.py --build out/lfo4-tlm

**Why this is the right instrument and the hardware sweep was not.** The sweep
asked 32 words "are you a pointer whose byte looks like a voice?" and could only
answer from whatever the instrument happened to be doing. Here the answer is
known before the question: this harness *calls* evaluator A itself, so it knows
exactly which addresses it passed as `param_5` and `param_6`. Finding them in
the frame is then a search for two values we chose, not an inference from what
the bytes look like -- a control on both arms, which three earlier readings of
this frame did not have.

Everything measured here costs no flash. The offset it prints is what
`bridge.c` should read instead of the pair it currently guesses at.
"""

from __future__ import annotations

import argparse
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

WINDOW = 256          # bytes above the stub's frame pointer to search


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-tlm")
    p.add_argument("--limit", type=int, default=400_000_000)
    args = p.parse_args()

    build = os.path.join(eng.ROOT, args.build)
    sym = {k: int(v, 16)
           for k, v in json.loads(pathlib.Path(f"{build}/symbols.json").read_text()).items()}
    target = sym.get("lfo4_row_for_block")
    if target is None:
        print("  this build has no lfo4_row_for_block: nothing to measure")
        return 1

    holder, seen = {}, []

    def pre_start(m):
        def at_stub(uc, address, size, user):
            # On entry the stub's callee has not pushed anything: %sp@(0) is the
            # return address, %sp@(4) `block`, %sp@(8) `frame`.
            sp = uc.reg_read(UC_M68K_REG_A7)
            try:
                frame = struct.unpack(">I", bytes(uc.mem_read(sp + 8, 4)))[0]
            except Exception:                                   # noqa: BLE001
                return
            if len(seen) < 64:
                seen.append(frame)
        m.uc.hook_add(UC_HOOK_CODE, at_stub, begin=target, end=target)

    print(f"  booting {os.path.basename(build)} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(eng.SYX,
                              open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}")

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
    print(f"\n  param_5 = {out1:#010x}   param_6 = {out2:#010x}   (chosen here, so"
          f" finding them is a control, not a guess)")

    seen.clear()
    after.call(eng.EVAL_A, buf, rate, 0xFFFF, 0xFFFF, out1, out2, 0)
    if not seen:
        print("\n  the stub never ran: nothing to report")
        return 1

    frame = seen[0]
    print(f"  the stub was handed frame = {frame:#010x} "
          f"({len(seen)} call(s), {len(set(seen))} distinct)")

    hits = {}
    for off in range(0, WINDOW, 2):
        try:
            w = struct.unpack(">I", bytes(m.uc.mem_read(frame + off, 4)))[0]
        except Exception:                                       # noqa: BLE001
            continue
        if w == out1:
            hits.setdefault("param_5", []).append(off)
        elif w == out2:
            hits.setdefault("param_6", []).append(off)
        elif w == buf:
            hits.setdefault("param_1", []).append(off)

    print()
    if not hits:
        print(f"  neither argument appears within +0..+{WINDOW} of the frame pointer.")
        print("  The stub's %sp is further from evaluator A's than the window reaches;")
        print("  widen WINDOW here -- in the emulator, where an unmapped read is a")
        print("  report and not a dead MIDI task on the owner's desk.")
        return 1
    for name in ("param_1", "param_5", "param_6"):
        if name in hits:
            print(f"  {name}: frame + {', '.join(f'{o}' for o in hits[name])}")
    if "param_5" in hits:
        print(f"\n  So bridge.c should read the voice array at frame + {hits['param_5'][0]}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
