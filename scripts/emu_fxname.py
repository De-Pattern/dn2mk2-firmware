"""What short name does the firmware give each modulation group?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_BUILD=out/fxbrowser3 \
        /root/dn2-emu-venv/bin/python -u scripts/emu_fxname.py

`fxbrowser2` works — the FX destinations are selectable and they modulate — but
the **Chorus section draws `ERR`** while Delay and Reverb draw `DEL` and `REV`.
`docs/fx-master-modulation.md` §22 lists six dead explanations, all of them on
the *construction* side of the destination modal. `emu_modalname.py` then
measured that construction resolves **no** names at all, on either image, which
is why every one of them failed: the text is resolved when a row is **drawn**.

This asks the draw side, and it asks it of one function.

**`0x400dc3f0` is the group -> short-name lookup.** Groups 0..4 return `'SYN'`,
groups above 30 return `'ERR'`, and everything between indexes a 26-longword
table at `0x401f76f4` with `group - 5`. That `lea` is the **only** reference to
the table in the whole image, so the table has exactly one reader and this
function is the whole of the naming.

Two things are measured here, on stock and on a build:

1. **the table itself, at run time** — `0x400dc3f0(g)` for every group, with the
   pointer it returns and the string that pointer holds;
2. **the draw**, for real — the destination modal is constructed for a live
   `ParameterSet`, every row widget it builds is captured, and each one's own
   label accessor `0x40116e5e` is then called, which is exactly what the list
   calls when it paints. The text that comes back is the text on the screen.

**A null is only evidence once the input is known to arrive** (`PRINCIPLES.md`
§19, and a probe broke this rule in this session by reading a pointer that had
never been set). So the run **fails loudly** unless groups 17 and 18 — Reverb and
Delay, the two the owner reports as *correct* — resolve to `'REV'` and `'DEL'`
through this same call on both images, and unless the draw produces text for a
Delay row. Chorus's answer is only read after those two controls have passed.

**The prediction, written before the run**, so it cannot be fitted afterwards.
If the cause is `0x401f76f4`'s eleventh longword, then:

- group 16 resolves to `0x40210c9e` `'ERR'` — the *same pointer* the
  out-of-range fallback returns — on stock and on `fxbrowser2`;
- group 17 resolves to `0x402107d2` and group 18 to `0x40210919`, which are
  **literally the short-name pointers of entries 129 `Reverb Mix Vol.` and 120
  `Delay Mix Vol.`**, while group 16 does *not* point at entry 111 `Chorus Mix
  Vol.`'s `'CHR'` at `0x4021077c`;
- so every Chorus row's short label reads `ERR:...` and every Reverb and Delay
  row reads `REV:...` and `DEL:...`;
- and the build that writes `0x4021077c` into that one longword changes group 16
  to `'CHR'` **and nothing else**, because no other group's slot is touched and
  the table has one reader.
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.image import differences                          # noqa: E402
from emulib.machine import STACK, Machine                     # noqa: E402

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
BUILD = os.environ.get("DT2_BUILD", "out/fxbrowser3")
BUILT = f"{ROOT}/{BUILD}/section_3_MAIN_OS.bin"

GROUP_NAME = 0x400DC3F0     # group -> short name, the only reader of the table
NAME_TABLE = 0x401F76F4     # 26 longwords, indexed by `group - 5`
TABLE_LO, TABLE_HI = NAME_TABLE, NAME_TABLE + 4 * 26 - 1

MODAL = 0x4010632C          # the destination modal's list constructor
ROW = 0x401170D8            # the list-row widget constructor
ROW_LABEL = 0x40116E5E      # row -> its displayed string; what the paint calls

RECORD_BASE = 0x401F7F94    # the pre-biased record base the accessors use
RECORD_SIZE = 60
SHORT_NAME_OFF = 0x30       # from RECORD_BASE: the record's own short name.
                            # objdump prints an indexed displacement in hex with
                            # no prefix, so `%a0@(30,%d2:l)` at 0x40105b72 is 48,
                            # not 30 -- FEATURE-PLAYBOOK.md §2.6, twice bitten.

CONTEXT = 0x4018A97A
STEP_A, STEP_B, STEP_C = 0x4003E40E, 0x40046BFE, 0x4003E41A
PARAMETER_SET = 0x400312AE

WANT = 0x0200               # the list path's mask -- the owner's list
FX = {16: "Chorus", 17: "Reverb", 18: "Delay"}
CONTROL = {17: "REV", 18: "DEL"}   # what the owner reports as already correct


# --------------------------------------------------------------------------
# reading the machine


def cstring(m, address: int, limit: int = 40) -> str:
    if not (0x40000000 <= address < 0x48000000):
        return ""
    out = bytearray()
    while len(out) < limit:
        try:
            b = m.read(address + len(out), 1)[0]
        except Exception:                                     # noqa: BLE001
            break
        if not b or not (0x20 <= b < 0x7F):
            break
        out.append(b)
    return out.decode("latin1")


def call_sret(m, fn: int, sret: int, *args) -> int:
    """`m.call`, with `%a0` set — the ABI's hidden return-value pointer.

    `emulib.machine.Machine.call` cannot do this: every routine it was written
    for returns in `%d0`. A routine that returns a `std::string` is handed the
    storage in `%a0` instead, and calling it without one writes over whatever
    `%a0` happened to hold.
    """
    from unicorn.m68k_const import (UC_M68K_REG_A0, UC_M68K_REG_A6,
                                    UC_M68K_REG_A7, UC_M68K_REG_D0)

    frame = struct.pack(">I", m.ret) + b"".join(
        struct.pack(">I", a & 0xFFFFFFFF) for a in args)
    m.write(STACK, frame)
    m.uc.reg_write(UC_M68K_REG_A7, STACK)
    m.uc.reg_write(UC_M68K_REG_A6, 0)
    m.uc.reg_write(UC_M68K_REG_A0, sret)
    m.uc.emu_start(fn, m.ret, count=20_000_000)
    return m.uc.reg_read(UC_M68K_REG_D0)


def parameter_set(m) -> int:
    a = m.call(CONTEXT)
    b = m.call(STEP_A, a)
    c = m.call(STEP_B, b)
    d = m.call(CONTEXT)
    e = m.call(STEP_C, d)
    return m.call(PARAMETER_SET, e, c) & 0xFFFFFFFF


def group_of(m, entry: int) -> int:
    return m.long(RECORD_BASE + RECORD_SIZE * entry)


def record_short(m, entry: int) -> str:
    return cstring(m, m.long(RECORD_BASE + RECORD_SIZE * entry + SHORT_NAME_OFF))


# --------------------------------------------------------------------------
# the two measurements


def table(m, label: str) -> dict:
    """`0x400dc3f0(g)` for every group, run rather than read."""
    out = {}
    for group in range(0, 35):
        pointer = m.call(GROUP_NAME, group) & 0xFFFFFFFF
        out[group] = (pointer, cstring(m, pointer))
    print(f"  {label}: group -> short name, through {GROUP_NAME:#010x}")
    for group in sorted(out):
        pointer, text = out[group]
        note = f"   <<< {FX[group]}" if group in FX else ""
        print(f"    group {group:>2} -> {pointer:#010x} {text!r}{note}")
    return out


def draw(m, label: str, pset: int) -> dict:
    """Build the modal, then ask every row widget for the string it displays.

    `0x40116e5e(row)` is the row's own label accessor: it invokes the functor
    the list builder stored in the widget, which is what the paint does. So the
    text this returns is the text drawn, resolved through whatever the firmware
    resolves it through -- nothing about the path is assumed here.
    """
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ
    from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC

    rows, reads = [], []

    def at_row(uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        args = struct.unpack(">7I", bytes(uc.mem_read(sp + 4, 28)))
        rows.append((args[0], args[5]))          # the widget, and its entry

    def at_table(uc, access, address, size, value, user):
        reads.append((uc.reg_read(UC_M68K_REG_PC),
                      (address - NAME_TABLE) // 4 + 5))

    this = m.alloc(2048)
    m.write(this, bytes(2048))
    handle = m.uc.hook_add(UC_HOOK_CODE, at_row, begin=ROW, end=ROW)
    try:
        m.call(MODAL, this, 0, pset, 0, 0, 0, WANT, 0, 0, 0, 0)
    except Exception as exc:                                  # noqa: BLE001
        print(f"  {label}: the modal would not construct: {exc}")
        return {}
    finally:
        m.uc.hook_del(handle)

    sret = m.alloc(256)
    watch = m.uc.hook_add(UC_HOOK_MEM_READ, at_table, begin=TABLE_LO, end=TABLE_HI)
    drawn = {}
    try:
        for widget, entry in rows:
            entry = entry if entry != 0xFFFFFFFF else -1
            if entry >= 0 and group_of(m, entry) not in FX:
                continue                         # only the three under question
            m.write(sret, bytes(64))
            before = len(reads)
            try:
                call_sret(m, ROW_LABEL, sret, widget)
                text = cstring(m, m.long(sret))
            except Exception as exc:             # noqa: BLE001
                text = f"<faulted: {str(exc)[:40]}>"
            drawn.setdefault(entry, (text, [g for _, g in reads[before:]]))
    finally:
        m.uc.hook_del(watch)

    print(f"  {label}: the modal built {len(rows)} row(s); "
          f"{sum(1 for _, e in rows if e == 0xFFFFFFFF)} of them section headers")
    print(f"    the group-name table was read {len(reads)} time(s) while drawing, "
          f"for groups {sorted({g for _, g in reads})}")
    for entry in sorted(drawn, key=lambda e: (e < 0, e)):
        text, groups = drawn[entry]
        if entry < 0:
            print(f"    a section header  -> {text!r}")
            continue
        group = group_of(m, entry)
        print(f"    entry {entry:>3} {FX[group]:<6} ({record_short(m, entry):>5})"
              f" -> {text!r}  table reads {groups}")
    return drawn


# --------------------------------------------------------------------------


def main() -> int:
    stock_path = os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin")
    runs = differences(open(stock_path, "rb").read(), open(BUILT, "rb").read())
    print(f"  under test: {BUILD}, {len(runs)} run(s) differ from stock\n")

    machines = {}
    for label, build in (("stock", False), (BUILD, True)):
        m = Machine()
        if build:
            m.apply(runs)
            m.flush()
        machines[label] = m

    tables, draws = {}, {}
    for label, m in machines.items():
        tables[label] = table(m, f"{label:<16}")
        print()

    # --- the control, before Chorus is read at all ------------------------
    bad = [(label, group, tables[label][group][1])
           for label in tables for group, want in CONTROL.items()
           if tables[label][group][1] != want]
    if bad:
        print("  ** the control failed: the two groups the owner reports as")
        print("     correct do not resolve to their reported names here, so this")
        print("     harness is not reading what the instrument reads and nothing")
        print("     is concluded about Chorus.")
        for label, group, got in bad:
            print(f"     {label}: group {group} -> {got!r}, expected "
                  f"{CONTROL[group]!r}")
        return 2
    print(f"  control: groups 17 and 18 resolve to 'REV' and 'DEL' on "
          f"{' and '.join(tables)} -- the lookup is the one the owner is reading\n")

    for label, m in machines.items():
        pset = parameter_set(m)
        print(f"  {label}: ParameterSet {pset:#010x}")
        draws[label] = draw(m, f"{label:<16}", pset)
        print()

    # --- the second control: the draw must have produced text for Delay ---
    delay = [t for label in draws for e, (t, _) in draws[label].items()
             if e >= 0 and group_of(machines[label], e) == 18 and t
             and not t.startswith("<")]
    if not delay:
        print("  ** the draw produced no text for any Delay row, and Delay is the")
        print("     group that is known to draw correctly on the instrument. The")
        print("     harness did not reach the text, so nothing is concluded.")
        return 2
    print(f"  control: the draw produced text for {len(delay)} Delay row(s), "
          f"e.g. {delay[0]!r} -- the draw path was reached\n")

    # --- the answer -------------------------------------------------------
    for label in tables:
        pointer, text = tables[label][16]
        fallback = tables[label][34][0]          # group 34 > 30 -> the fallback
        same = "  == the out-of-range fallback" if pointer == fallback else ""
        print(f"  {label:<16} group 16 (Chorus) -> {pointer:#010x} {text!r}{same}")
    print(f"  entry 111 'Chorus Mix Vol.' short name: "
          f"{record_short(machines['stock'], 111)!r} at "
          f"{machines['stock'].long(RECORD_BASE + RECORD_SIZE * 111 + SHORT_NAME_OFF):#010x}")
    print(f"  entry 129 'Reverb Mix Vol.' short name: "
          f"{record_short(machines['stock'], 129)!r} at "
          f"{machines['stock'].long(RECORD_BASE + RECORD_SIZE * 129 + SHORT_NAME_OFF):#010x}"
          f"   (= group 17's table entry)")
    print(f"  entry 120 'Delay Mix Vol.'  short name: "
          f"{record_short(machines['stock'], 120)!r} at "
          f"{machines['stock'].long(RECORD_BASE + RECORD_SIZE * 120 + SHORT_NAME_OFF):#010x}"
          f"   (= group 18's table entry)")

    if tables[BUILD][16][1] == "ERR":
        print("\n  the build still names group 16 'ERR' -- not fixed here")
        return 1
    print(f"\n  the build names group 16 {tables[BUILD][16][1]!r}, "
          f"and groups 17/18 are unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
