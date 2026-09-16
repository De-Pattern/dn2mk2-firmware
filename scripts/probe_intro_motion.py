"""What moves the intro: is the offset table rebuilt per frame, and who writes it.

Backlog §9, a custom start-up animation. The intro is a copy loop that samples a
static source bitmap at `table[i] + scroll` for each panel pixel
(`docs/display-path.md`). A new animation is therefore new data -- but which data
depends on the answers here:

- if the **table** is built once and only the **scroll** changes, the animation
  is a trajectory through one fixed warp, and a new animation is a new table;
- if the table is regenerated every frame, the generator is the animation, and a
  new animation is a new generator.

Runs from a snapshot with the intro already running (the recipe in
`trace_intro_draw.py`), samples the table pointer, a hash of the table and the
scroll value once per slice, and write-watches the table's memory and the scroll
field to name the code that writes each.

    DIGIKIT=... DT2_SECTIONS=/root/dn2-sections-111 \\
    /root/dn2-emu-venv/bin/python scripts/probe_intro_motion.py \\
        snapshots/dn2_111_ext400M.snap 20000000 \\
        --table-ptr 0x42c45698 --scroll 0x42c45678
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import os
import struct
import sys

TABLE_WORDS = 16384


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snapshot")
    ap.add_argument("instrs", type=int)
    ap.add_argument("--table-ptr", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--scroll", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--slice", type=int, default=1_000_000)
    args = ap.parse_args()

    digikit = os.environ.get("DIGIKIT")
    if not digikit:
        raise SystemExit("set DIGIKIT to the digikit checkout")
    sys.path.insert(0, digikit)
    os.chdir(digikit)

    from unicorn import UC_HOOK_MEM_WRITE
    from unicorn.m68k_const import UC_M68K_REG_PC
    from emu.longrun import build, spin

    m, ev, st, pc, inq, at = build(args.snapshot, unblock=True, softfloat=True,
                                   bitmap=True, dsp=True, on_pixel=lambda *a: None)
    uc = m.uc

    def u32(addr):
        return struct.unpack(">I", bytes(uc.mem_read(addr, 4)))[0]

    def s32(addr):
        return struct.unpack(">i", bytes(uc.mem_read(addr, 4)))[0]

    table = u32(args.table_ptr)
    print(f"table pointer {args.table_ptr:#x} -> {table:#x}; scroll at {args.scroll:#x} = {s32(args.scroll)}")
    first = [s32(table + 4 * k) for k in range(8)]
    print(f"table[0..7] = {first}")

    writers = {"table": collections.Counter(), "scroll": collections.Counter(),
               "tableptr": collections.Counter()}

    def on_write(uc_, access, addr, size, value, name):
        writers[name][uc_.reg_read(UC_M68K_REG_PC)] += 1

    uc.hook_add(UC_HOOK_MEM_WRITE, on_write, "table", begin=table, end=table + 4 * TABLE_WORDS - 1)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write, "scroll", begin=args.scroll, end=args.scroll + 3)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write, "tableptr", begin=args.table_ptr, end=args.table_ptr + 3)

    def table_hash():
        return hashlib.sha1(bytes(uc.mem_read(table, 4 * TABLE_WORDS))).hexdigest()[:12]

    done, last_hash = 0, table_hash()
    scrolls = []
    print(f"{'M':>6}  {'scroll':>12}  table-hash     changed")
    while done < args.instrs:
        pc, n, stop = spin(m, pc, min(args.slice, args.instrs - done))
        done += n
        h = table_hash()
        sc = s32(args.scroll)
        scrolls.append(sc)
        print(f"{done/1e6:6.1f}  {sc:>12}  {h}  {'YES' if h != last_hash else ''}", flush=True)
        last_hash = h
        if n == 0:
            break

    for name, c in writers.items():
        print(f"\nwriters of {name}: {sum(c.values()):,} writes")
        for addr, k in c.most_common(6):
            print(f"  pc {addr:#010x}  x{k:,}")
    if len(scrolls) > 1:
        steps = collections.Counter(b - a for a, b in zip(scrolls, scrolls[1:]))
        print(f"\nscroll steps per slice: {steps.most_common(6)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
