"""Does an FX parameter round-trip between a `DEST` code and a list entry?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_fxbrowser.py

**What this can and cannot reach.** The emulator has no destination browser —
no panel, no page view, no encoder — so "the list shows `Feedback Gain` and
turning the knob selects it" is the instrument's question and nothing here can
answer it. Writing "n/a" against the whole gate would be
`docs/PRINCIPLES.md` §19 again, so this runs every piece the browser is built
out of, by calling it:

1. **the boot-time FX slot table** at `0x42c649a8`, read out of a booted
   machine — which of each duplicated slot's two records it kept is a
   derivation in the build script, and this is the measurement of it;
2. **`0x400dc02a`**, the slot -> entry helper behind `SoundParameterSet`'s
   vtable `+0x50`, over every slot 0..130;
3. **the entry -> code helper** in the cave, over every entry 1..330, against
   `0x400dbcc4`'s own untouched answer;
4. **the round trip** the browser's confirm path at `0x40107b0e` depends on:
   `helper(slot_to_entry(code)) == code` for every code 101..124.

Every one of them is run **against the stock image on the same snapshot**, so
"the patched build answers 111" is a statement about the patch and not about
the harness. And 2 and 3 are run over their whole domain rather than at a few
chosen points, because the risk in this build is not that the FX codes are
wrong — it is that something *below* 101 moved.

`scripts/emulib/machine.py` restores a booted snapshot instead of booting from
reset, which is what makes running four whole domains cheap. The boot itself is
`emu_boot_check.py`'s question and is gated separately.
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

SLOT_TO_ENTRY = 0x400DC02A     # the sound set's vtable +0x50, hooked by this build
ENTRY_TO_SLOT = 0x400DBCC4     # entry -> record+12, deliberately left alone
ENTRY_TO_GROUP = 0x400DBCE8    # entry -> record+8
HELPER = 0x4028EA02            # the cave: entry -> code, +76 for an FX record
FX_SLOT_TABLE = 0x42C649A8

CODE_BIAS = 76
CODE_LO, CODE_HI = 101, 124
FX_GROUPS = (16, 17, 18)
SLOTS = range(0, 131)
ENTRIES = range(1, 331)


def probe(m, label: str) -> dict:
    """Everything the browser is built out of, called rather than read."""
    table = [m.long(FX_SLOT_TABLE + 4 * slot) for slot in range(0, 101)]
    slot_to_entry = {slot: m.call(SLOT_TO_ENTRY, slot, 0, 0) & 0xFFFFFFFF
                     for slot in SLOTS}
    entry_to_slot = {e: m.call(ENTRY_TO_SLOT, e) & 0xFFFFFFFF for e in ENTRIES}
    group = {e: m.call(ENTRY_TO_GROUP, e) & 0xFFFFFFFF for e in ENTRIES}
    print(f"  {label}: FX table slots 25..48 -> entries "
          f"{[table[s] for s in range(25, 49)]}")
    return {"table": table, "s2e": slot_to_entry, "e2s": entry_to_slot,
            "group": group}


def main() -> int:
    stock_path = os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin")
    stock_image = open(stock_path, "rb").read()
    built_image = open(BUILT, "rb").read()
    runs = differences(stock_image, built_image)
    print(f"  the build differs from stock in {len(runs)} run(s), "
          f"{sum(len(r[1]) for r in runs)} bytes\n")

    print("  the control, on a stock snapshot:")
    control = probe(Machine(), "stock ")

    print("\n  the build, on the same snapshot:")
    m = Machine()
    m.apply(runs)
    m.flush()
    got = probe(m, "fxbrowser")
    helper = {e: m.call(HELPER, e) & 0xFFFFFFFF for e in ENTRIES}

    fails = []

    # 0. The instrument is validated on a known positive before any negative in
    #    it is believed. Stock must answer a plain sound slot with an entry.
    if not any(control["s2e"][s] for s in range(1, 101)):
        print("  ** stock answered 0 for every sound slot 1..100 **")
        print("     The harness cannot see a lookup it is certain stock makes;")
        print("     nothing below is concluded.")
        return 2
    live = sum(1 for s in range(0, 101) if control["s2e"][s])
    print(f"\n  control: stock resolves {live} of slots 0..100 to an entry")

    # 1. Nothing below 101 may move. This is the whole risk of the build.
    moved = [s for s in range(0, 101) if control["s2e"][s] != got["s2e"][s]]
    if moved:
        fails.append(f"slot -> entry changed for slots {moved[:12]} (and "
                     f"{max(0, len(moved) - 12)} more) at or below 100")
    unchanged = [e for e in ENTRIES if control["e2s"][e] != got["e2s"][e]]
    if unchanged:
        fails.append(f"0x400dbcc4 itself changed for entries {unchanged[:12]} -- "
                     f"it was supposed to be left alone for its other 31 callers")

    # 2. Stock must refuse every code this build claims, or the comparison is
    #    measuring the harness.
    claimed = [c for c in range(CODE_LO, CODE_HI + 1) if control["s2e"][c]]
    if claimed:
        fails.append(f"stock already resolves codes {claimed} -- this is not "
                     f"measuring the patch")

    # 3. Every code 101..124 resolves to the FX set's own entry for that slot.
    for code in range(CODE_LO, CODE_HI + 1):
        want = got["table"][code - CODE_BIAS]
        if got["s2e"][code] != want:
            fails.append(f"code {code}: slot -> entry gave {got['s2e'][code]}, "
                         f"expected the FX table's {want}")
    for code in (125, 126, 127, 128, 130):
        if got["s2e"][code]:
            fails.append(f"code {code} resolves to {got['s2e'][code]}; above "
                         f"{CODE_HI} nothing may resolve")

    # 4. The helper is 0x400dbcc4 plus 76, and only for groups 16..18.
    for e in ENTRIES:
        bias = CODE_BIAS if got["group"][e] in FX_GROUPS else 0
        want = (got["e2s"][e] + bias) & 0xFFFFFFFF
        if helper[e] != want:
            fails.append(f"entry {e} (group {got['group'][e]}): helper gave "
                         f"{helper[e]}, expected {want}")
            if len(fails) > 8:
                break

    # 5. The round trip the browser's confirm path needs.
    broken = []
    for code in range(CODE_LO, CODE_HI + 1):
        entry = got["s2e"][code]
        if not entry or helper[entry] != code:
            broken.append((code, entry, helper.get(entry)))
    if broken:
        fails.append(f"the round trip does not close for {broken[:6]}")

    biased = sorted(e for e in ENTRIES if helper[e] != got["e2s"][e])
    print(f"  the helper adds {CODE_BIAS} for {len(biased)} of 330 entries: "
          f"{biased[:6]}..{biased[-3:] if biased else ''}")
    print(f"  codes {CODE_LO}..{CODE_HI} resolve to entries "
          f"{[got['s2e'][c] for c in range(CODE_LO, CODE_HI + 1)]}")

    if fails:
        for f in fails[:12]:
            print("  FAIL  " + f)
        return 1

    print(f"\n  slots 0..100 answer exactly as stock answers them, and "
          f"0x400dbcc4 is untouched for its other callers.")
    print(f"  codes {CODE_LO}..{CODE_HI} resolve to the FX set's own entries, which "
          f"stock refuses entirely,")
    print(f"  and every one of them round-trips back to itself through the helper.")
    print("  What is left is the browser, which does not run here: the list, the")
    print("  names on the screen and the encoder are the instrument's question.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
