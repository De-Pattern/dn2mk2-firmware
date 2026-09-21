"""Does a fourth MOD page get built, and does the accessor answer for it?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_SYX=<the 1.11 .syx> \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_page.py

Step 4b's page is two stubs over structures the UI builds at startup: a page
record for an id the firmware's table has no room for, and a fourth entry in
the MOD mode's vector of three. Both are done by `lfo4_pages`, called from the
mode-header renderer the first time it draws a header holding `4 5 6`.

`ui1200M` is a machine that has already built all of it, which is exactly what
this needs: `lfo4_pages` is called with the **real** MOD mode object and reads
the **real** LFO3 page record, so the record it assembles is checked against
the one the instrument made rather than against a fabrication.

**What this does not establish.** It does not draw LFO4's page. Getting there
means paging with `[MOD]` and then resolving entries 321-330 through both
relocated tables, and the second of those is a 68-byte table the *snapshot*
filled at its old address -- see `repair` below. The page appearing correctly
is a hardware result, and this is the half that can be had before one.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.image import code_chunks, differences, load_build     # noqa: E402
from emulib.machine import SNAP, Machine                          # noqa: E402
from emulib.report import check, report                           # noqa: E402

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-page"
PAGE_TABLE, PAGE_STRIDE = 0x42432C00, 44
LFO3_PAGE, LFO4_PAGE = 6, 37
ACCESSOR = 0x400C2474
MODE_OBJECT = 0x447BF800          # scripts/emu_mod_pagelist.py read it from a live render
VEC_BEGIN, VEC_END = 124, 128
RUNTIME_OLD, RUNTIME_STRIDE, RUNTIME_ENTRIES = 0x4243325C, 68, 321
ENTRY0 = 321                      # csrc/include/dn2_111.h


def repair(machine, new_base):
    """Copy the runtime table the snapshot filled to where the build moved it.

    Not a fudge, and worth being precise about which: on a real boot the
    firmware's own registration loop fills this table **through the base
    literals the build rewrote**, so it fills the new one. A snapshot has
    already run that loop, at the old address, and cannot be asked to run it
    again -- so the harness does what the boot would have done.

    It is still only the 321 entries stock has. Entries 321-330 stay empty
    here; a real boot's loop, whose bound this build also raised, fills them.
    """
    blob = machine.read(RUNTIME_OLD, RUNTIME_STRIDE * RUNTIME_ENTRIES)
    if not any(blob):
        raise SystemExit("the snapshot's runtime table is empty -- nothing to copy, "
                         "and a copy of nothing would look exactly like a pass")
    machine.write(new_base, blob)
    return sum(1 for i in range(RUNTIME_ENTRIES)
               if any(blob[RUNTIME_STRIDE * i:RUNTIME_STRIDE * (i + 1)]))


def words(blob):
    return [int.from_bytes(blob[i:i + 4], "big") for i in range(0, len(blob), 4)]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--object", type=lambda x: int(x, 0), default=MODE_OBJECT)
    args = p.parse_args()

    machine = Machine(args.snapshot)
    image, sym = load_build(BUILD)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    runs = differences(stock, image)
    machine.apply(runs)
    for load, _n, bss, init, blob in code_chunks(image):
        machine.load_code_chunk((load, len(blob), bss, init, blob))
    machine.flush()
    print(f"  installed {len(runs)} run(s), {sum(len(b) for _, b in runs):,} B, "
          f"{len(code_chunks(image))} CODE chunk(s)")
    filled = repair(machine, sym["lfo4_prm68"])
    print(f"  runtime table: {filled} stock entries copied to {sym['lfo4_prm68']:#010x}\n")

    lfo3 = words(machine.read(PAGE_TABLE + PAGE_STRIDE * LFO3_PAGE, PAGE_STRIDE))
    before = words(machine.read(args.object + VEC_BEGIN, 8))
    begin, end = before
    ids_before = words(machine.read(begin, end - begin))
    print(f"  LFO3's page record: " + " ".join(f"{w:#010x}" for w in lfo3))
    print(f"  the mode vector before: {begin:#010x}..{end:#010x} -> {ids_before}")
    check("the object this is called with is the MOD mode", ids_before == [4, 5, 6],
          f"its pages are {ids_before}")

    machine.call(sym["lfo4_pages"], args.object)

    swapped = machine.long(sym["lfo4_pages_swapped"])
    begin, end = words(machine.read(args.object + VEC_BEGIN, 8))
    ids_after = words(machine.read(begin, end - begin))
    record = words(machine.read(sym["lfo4_page_record"], PAGE_STRIDE))
    name = bytes(machine.read(sym["lfo4_page_name"], 32))
    print(f"\n  lfo4_pages_swapped {swapped}")
    print(f"  the mode vector after:  {begin:#010x}..{end:#010x} -> {ids_after}")
    print(f"  LFO4's page record: " + " ".join(f"{w:#010x}" for w in record))
    print(f"  its name object: {name.hex()}  {name.split(bytes(1))[0]!r}")

    check("it swapped exactly once", swapped == 1, f"{swapped}")
    check("the vector now names four pages, LFO4 last",
          ids_after == [4, 5, 6, LFO4_PAGE], f"{ids_after}")
    check("it points at the array the build owns", begin == sym["lfo4_page_ids"],
          f"{begin:#010x}, not {sym['lfo4_page_ids']:#010x}")
    check("the name reads LFO4", name.split(bytes(1))[0] == b"LFO4",
          f"{name.split(bytes(1))[0]!r}")
    check("the mode name is shared with LFO3's, not copied",
          record[1] == lfo3[1], f"{record[1]:#010x} against {lfo3[1]:#010x}")
    check("the eight entries are LFO4's, skipping the two alternates",
          record[2:10] == [ENTRY0 + k for k in (0, 1, 2, 3, 4, 6, 7, 8)],
          f"{record[2:10]}")
    check("everything else is LFO3's", record[10] == lfo3[10],
          f"span {record[10]} against {lfo3[10]}")

    # Called twice, it must do nothing the second time: the renderer calls it
    # on every frame.
    machine.call(sym["lfo4_pages"], args.object)
    check("a second call changes nothing", machine.long(sym["lfo4_pages_swapped"]) == 1,
          f"{machine.long(sym['lfo4_pages_swapped'])}")

    got = machine.call(ACCESSOR, LFO4_PAGE) & 0xFFFFFFFF
    stock_id = machine.call(ACCESSOR, LFO3_PAGE) & 0xFFFFFFFF
    print(f"\n  the accessor answers {LFO4_PAGE} with {got:#010x} and "
          f"{LFO3_PAGE} with {stock_id:#010x}")
    check("the accessor returns LFO4's record", got == sym["lfo4_page_record"],
          f"{got:#010x}, not {sym['lfo4_page_record']:#010x}")
    check("every other id still gets the firmware's own arithmetic",
          stock_id == PAGE_TABLE + PAGE_STRIDE * LFO3_PAGE, f"{stock_id:#010x}")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
