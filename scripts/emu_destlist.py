"""What is actually in the destination list, stock beside the build?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_destlist.py

From the instrument, 2026-09-23, on `fxbrowser`:

> "when browsing the destination list, once I get to OVR Routing, if I turn one
> more click the list goes to the very top again. I can see by the scroll mark
> on the right that there was still more list after OVR Routing but I can never
> reach under it."

`OVR Routing` is entry 304, group 15, **slot 99** — the highest occupied slot in
the sound set, and group 15 is rank 10, immediately before the FX groups at
ranks 11-13. So the wrap is exactly at the end of the stock entries.

`emu_fxbrowser.py` verified the `+0x50` lookup and the entry -> code conversion
over their whole domains, but **it never ran the enumeration**. That is the
untested link and this is the instrument for it: call `0x4003951e` directly and
dump the vector it returns — length, and every entry with its group and name.

It answers three questions in one run, and they need different fixes:

1. **did the list grow at all?** If the build's vector is the same length as
   stock's, nothing the browser does is the problem and the fault is upstream
   in the enumeration.
2. **does the stock list already stop at `OVR Routing`?** If stock's vector
   ends there too, then the reachable part *is* the whole stock list and we
   have appended entries the navigation cannot see. If stock's vector runs past
   it, the bound was always there and the owner has simply never had a reason
   to notice.
3. **does `want` change the answer?** The browser's list path passes `0x200`
   (`0x40107ab0`) and the other call site at `0x40106502` passes its caller's
   mask. Both are run.

The list builder takes its output pointer in `%a0`, which `Machine.call` cannot
set, so a four-instruction trampoline is assembled by hand below and called
instead. `0x4003951e` constructs the vector itself; the output is an 8-byte
`{vector*, holder*}` and the vector's first two longwords are `begin` and `end`.
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.image import differences                          # noqa: E402
from emulib.machine import Machine                            # noqa: E402

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
BUILT = f"{ROOT}/out/fxbrowser/section_3_MAIN_OS.bin"

BUILD_LIST = 0x4003951E
RECORDS = 0x401F7FC8
RECORD_SIZE = 60
NAME_WORD = 12              # the long name; the last three words are the names

# The browser's own prologue for reaching a live ParameterSet, from 0x400c28a2.
CONTEXT = 0x4018A97A
STEP_A, STEP_B = 0x4003E40E, 0x40046BFE
STEP_C = 0x4003E41A
PARAMETER_SET = 0x400312AE

# movea.l %sp@(4),%a0 ; move.l %sp@(12),%sp@- ; move.l %sp@(12),%sp@-
# jsr 0x4003951e ; addq.l #8,%sp ; rts
TRAMPOLINE = bytes.fromhex("206f00042f2f000c2f2f000c4eb94003951e508f4e75")

WANTS = (("the browser's list path, 0x200", 0x0200),
         ("LFO1's own mask, 0x1e00", 0x1E00),
         ("LFO3's own mask, 0x0600", 0x0600))

# The owner wraps after `OVR Routing`. The coordinator gave it as record
# **index** 304; entry = index + 1, so the entry is 305 and entry 304 is
# `Overdrive` at slot 98. The first run of this harness printed the marker on
# the wrong row for exactly that reason -- the distinction is one the record
# table punishes constantly (`docs/lfo-parameters.md`).
OVR_ROUTING = 305           # entry, group 15, slot 99 -- where the owner wraps


def name(m, entry: int) -> str:
    pointer = m.long(RECORDS + RECORD_SIZE * (entry - 1) + 4 * NAME_WORD)
    if not (0x40000400 <= pointer < 0x40400000):
        return "?"
    out = bytearray()
    while len(out) < 40:
        b = m.read(pointer + len(out), 1)[0]
        if not b:
            break
        out.append(b)
    return out.decode("latin1")


def group_of(m, entry: int) -> int:
    return m.long(RECORDS + RECORD_SIZE * (entry - 1) + 8)


def slot_of(m, entry: int) -> int:
    return m.long(RECORDS + RECORD_SIZE * (entry - 1) + 12)


def parameter_set(m) -> int:
    a = m.call(CONTEXT)
    b = m.call(STEP_A, a)
    c = m.call(STEP_B, b)
    d = m.call(CONTEXT)
    e = m.call(STEP_C, d)
    return m.call(PARAMETER_SET, e, c) & 0xFFFFFFFF


def build(m, tramp: int, out: int, pset: int, want: int) -> list[int]:
    m.write(out, bytes(8))
    m.call(tramp, out, pset, want)
    vector = m.long(out)
    if not vector:
        return []
    begin, end = m.long(vector), m.long(vector + 4)
    if not begin or end < begin or (end - begin) % 4:
        return []
    return [m.long(a) for a in range(begin, end, 4)]


def dump(m, label: str, entries: list[int]) -> None:
    print(f"    {label}: {len(entries)} entries")
    if not entries:
        return
    groups = []
    for e in entries:
        g = group_of(m, e)
        if not groups or groups[-1][0] != g:
            groups.append((g, []))
        groups[-1][1].append(e)
    print("      by group: " + ", ".join(f"{g}x{len(v)}" for g, v in groups))
    if OVR_ROUTING in entries:
        i = entries.index(OVR_ROUTING)
        window = entries[max(0, i - 2):i + 6]
        print(f"      around the seam (OVR Routing is #{i + 1} of {len(entries)}):")
        for e in window:
            mark = "  <-- the owner wraps after this" if e == OVR_ROUTING else ""
            print(f"        #{entries.index(e) + 1:3} entry {e:3} group "
                  f"{group_of(m, e):2} slot {slot_of(m, e):3} {name(m, e)!r}{mark}")
    else:
        print(f"      OVR Routing (entry {OVR_ROUTING}) is NOT in this list")
    print(f"      last five: " + ", ".join(
        f"{e}/{name(m, e)!r}" for e in entries[-5:]))


def main() -> int:
    stock_path = os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin")
    runs = differences(open(stock_path, "rb").read(), open(BUILT, "rb").read())
    print(f"  the build differs from stock in {len(runs)} run(s)\n")

    results = {}
    for label, apply_build in (("stock", False), ("fxbrowser", True)):
        m = Machine()
        if apply_build:
            m.apply(runs)
            m.flush()
        tramp = m.alloc(len(TRAMPOLINE))
        m.write(tramp, TRAMPOLINE)
        out = m.alloc(8)
        pset = parameter_set(m)
        print(f"  {label}: the live ParameterSet is {pset:#010x}")
        if not pset:
            print(f"  ** could not reach a ParameterSet on {label}; the prologue "
                  f"at 0x400c28a2 did not reproduce **")
            return 2
        for why, want in WANTS:
            entries = build(m, tramp, out, pset, want)
            results[(label, want)] = entries
            dump(m, f"{why}", entries)
        print()

    fails = []
    # The known positive: stock must produce a list at all.
    if not results[("stock", 0x0200)]:
        print("  ** stock produced an empty list; the harness is what is broken **")
        return 2

    for _why, want in WANTS:
        s, b = results[("stock", want)], results[("fxbrowser", want)]
        added = [e for e in b if e not in s]
        lost = [e for e in s if e not in b]
        print(f"  want {want:#06x}: stock {len(s)} -> build {len(b)}  "
              f"(+{len(added)}, -{len(lost)})")
        if lost:
            fails.append(f"want {want:#06x}: the build LOST entries {lost[:8]}")
        if want in (0x0200, 0x1E00) and len(added) != 24:
            fails.append(f"want {want:#06x}: the build added {len(added)} entries, "
                         f"not the 24 Chorus/Delay/Reverb destinations")

    s = results[("stock", 0x0200)]
    if OVR_ROUTING in s and s[-1] == OVR_ROUTING:
        print(f"\n  STOCK ALREADY ENDS AT OVR Routing -- the reachable part of the")
        print(f"  list on the instrument IS the whole stock list, so the wrap is a")
        print(f"  bound the build did not create and the appended entries expose.")
    elif OVR_ROUTING in s:
        i = s.index(OVR_ROUTING)
        print(f"\n  stock runs {len(s) - i - 1} entries PAST OVR Routing, so the")
        print(f"  wrap the owner sees is not the end of the stock list either.")

    if fails:
        for f in fails:
            print("  FAIL  " + f)
        return 1
    print("\n  The enumeration is what it was asked to be. Where the encoder stops")
    print("  is a separate question and this cannot answer it: no browser runs here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
