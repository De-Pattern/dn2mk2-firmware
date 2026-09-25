"""LFO4: the destination browser opens, because "is this a DEST?" learns a bit.

    python scripts/build_lfo4_browser.py

From the instrument, after `lfo4-ui`:

> "The modulation destination window doesn't pop up yet but now the order reads
> correct I think."

Both halves of that are explained by the same field. `lfo4-ui` taught the
**list** about LFO4 -- which is why the order came right -- and the **window**
is opened somewhere else entirely, by a test this project had not found.

`scripts/emu_lfo4_modal.py` found it by diffing what the four MOD pages
execute while `DEST` is turned. 776 firmware blocks LFO1, LFO2 and LFO3 all
reach and LFO4 never does; the largest cluster, 216 blocks at
`0x40105a6c..0x40106d08`, is the browser view. Walking that back gave its
opener (`0x401a074a`, one caller) and then a call chain; walking *forward* from
the first place the traces part gave the decision itself:

```
400679c8  cmpil #320,%d3            ; the entry bound -- already raised to 330
400679ce  bhiw  0x40067ed6            by the table relocation
400679da  lea   0x401f7f94,%a0      ; the parameter table, pre-biased
400679e2  movel %a0@(24,%d0:l),%d0  ; field +44 of the record  (0x24 = 36; 8+36 = 44)
400679e6  andil #0x70000,%d0        ; bits 18, 17, 16 -- and nothing else
400679ec  beqw  0x40067edc          ; not a DEST: no browser
400679f0  ...                       ; open it
```

`0x70000` is "is this parameter a `DEST`?", and it names LFO1's, LFO2's and
LFO3's bits. `lfo4records.DEST_FLAGS` is **bit 15**, the value the staircase
`0x40000 / 0x20000 / 0x10000` continues to, so the AND yields zero and the
window never opens. The measured trace says exactly that: at `0x400679d2` both
pages are together, LFO3 goes to `0x400679f0` and LFO4 to `0x40067edc`.

**The change is one bit in an immediate, three times, and it cannot affect a
stock parameter.** Every distinct value of `+44` across all 320 records is
`0`, `0x200`, `0x600`, `0xe00`, `0x1e00`, `0x10000`, `0x20000` or `0x40000`.
**None has bit 15 set.** So widening the test to `0x78000` admits LFO4's `DEST`
record and changes the answer for nothing else -- which the build asserts
against the image rather than taking on trust.
"""

from __future__ import annotations

import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import build_lfo4_bridge as bridge                         # noqa: E402
import build_lfo4_page as page                             # noqa: E402
import build_lfo4_pagelist as pagelist                     # noqa: E402
import build_lfo4_slots as slots                           # noqa: E402
import build_lfo4_table as table                           # noqa: E402
import build_lfo4_ui as ui                                 # noqa: E402
import build_lfo4_ui2 as ui2                               # noqa: E402
import build_lfo4_value as value                           # noqa: E402
from dnfw.patch import lfo4records, paramtable              # noqa: E402

BASE = 0x40000400
OUT = ROOT / "out/lfo4-browser"
SYX = ROOT / "00_Resources/02_Builds/lfo4-browser_DN2_1.11.syx"

# `andil #0x70000,%d0` -- "is this parameter a DEST?", asked three times.
MASK_SITES = (0x40067506, 0x400676E4, 0x400679E6)
MASK_STOCK = 0x00070000
MASK_OURS = MASK_STOCK | lfo4records.DEST_FLAGS            # 0x78000


def browser(content, code):
    """Let the three `is this a DEST?` tests see LFO4's capability bit."""
    print("part 14 -- the destination browser opens")

    # The one thing that makes this safe, checked rather than assumed: no
    # record in the stock table carries the bit being added, so widening the
    # test cannot change the answer for a parameter that already had one.
    clash = [i for i in range(paramtable.COUNT)
             if struct.unpack_from(">I", content, paramtable.TABLE - BASE
                                   + paramtable.RECORD * i + lfo4records.FLAGS)[0]
             & lfo4records.DEST_FLAGS]
    if clash:
        raise SystemExit(f"{len(clash)} stock record(s) already carry "
                         f"{lfo4records.DEST_FLAGS:#x} in +44: {clash[:8]}")

    for va in MASK_SITES:
        at = va - BASE
        word, imm = struct.unpack_from(">H", content, at)[0], \
            struct.unpack_from(">I", content, at + 2)[0]
        if word & 0xFFF8 != 0x0280 or imm != MASK_STOCK:
            raise SystemExit(f"the DEST test at {va:#010x} is "
                             f"{bytes(content[at:at + 6]).hex()}, not andil #0x70000")
        struct.pack_into(">I", content, at + 2, MASK_OURS)
        print(f"  {va:#010x}  andil #{MASK_STOCK:#07x} -> #{MASK_OURS:#07x},%d{word & 7}")
    print(f"  no stock record carries {lfo4records.DEST_FLAGS:#x} in +44, "
          f"so this admits LFO4's DEST and nothing else")


if __name__ == "__main__":
    import argparse
    # Same guard as build_lfo4_tlm.py: a build name is never silently reused,
    # because a .syx on disk that no longer matches the one on the instrument
    # has already cost this project a gate.
    ap = argparse.ArgumentParser(description="the release LFO4 build: every feature, no diagnostics")
    ap.add_argument("--name", default="lfo4-browser")
    cli = ap.parse_args()
    OUT = ROOT / f"out/{cli.name}"
    SYX = ROOT / f"00_Resources/02_Builds/{cli.name}_DN2_1.11.syx"
    if SYX.exists():
        raise SystemExit(f"  {SYX.name} already exists. Pick another --name, or "
                         f"delete it deliberately if this is a rebuild of the same thing.")
    table.describe(bridge.load(bridge.read_image(bridge.STOCK)).container.find(3).unpack())
    raise SystemExit(bridge.main(sources=ui2.SOURCES, entries=ui2.ENTRIES,
                                 out=OUT, syx=SYX,
                                 extra=[slots.divert, table.relocate, page.hooks,
                                        value.divert, value.companion, value.waveform,
                                        ui.slew, ui.dest, pagelist.pagelist, ui2.rnd,
                                        browser],
                                 chunks=table.chunks))
