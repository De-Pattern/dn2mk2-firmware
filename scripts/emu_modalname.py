"""What string does the destination modal hand its section headers?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_modalname.py

`fxbrowser2` works — the FX destinations are selectable and they modulate — but
the **Chorus section header draws `ERR`** while Delay and Reverb draw `DEL` and
`REV`. `docs/fx-master-modulation.md` §22 has five dead leads and one unread
piece: *what the modal calls to name a section*.

This runs it instead of reading it.

**The modal's list construction is callable.** `0x4010632c` is the constructor
(`linkw %fp,#-156`); `%fp@(16)` is the `ParameterSet` it hands to the list
builder at `0x40106502` and `%fp@(32)` is the `want` mask. It then walks the
sorted vector and, **every time `0x400dbce8` reports a different group**, builds
a section header: `0x4019d140(%d2, %d7)` to fill a string, then
`0x401170d8(obj, %d2, %d6, %d4, %d5, -1, 8)` to construct the widget.

So: replay the browser's prologue for a live `ParameterSet` (as
`emu_destlist.py` does), call `0x4010632c`, and hook the three sites. Every
header the modal builds reports the group it was building for and the bytes of
the string it was handed.

**A null is only evidence once the input is known to arrive.** If the hook
reports nothing for Chorus, that means nothing until it has reported something
for **Delay**, whose header is known to draw correctly on the instrument. The
run therefore fails loudly if no header at all is seen, rather than printing
zeros and letting them be read as a finding. `emu_mirror_base.py` read a pointer
as `0x00000000` and reported it an hour before this was written, when the value
had simply never been set.

**The prediction, stated before looking**, so this cannot be fitted afterwards:
if the cause is a per-group name lookup that has no row for group 16, then the
trace shows `0x401170d8` receiving a good string for groups 17 and 18 and either
an empty one or `ERR`'s for group 16 — **and it shows all three being called**.
If instead the header for Chorus is never constructed at all, the fault is in
the group-change test and not in the naming, which is a different fix.

**What it found, 2026-09-23.** Neither. Chorus *does* get a header, built right
beside Reverb's and Delay's -- 11 on `fxbrowser2` against stock's 8, groups
`1, 5, 13, 11, 15, 16, 17, 18, 26, 27, 28` -- and **no short name is resolved at
all during construction, on either image**. So the text is fetched when a row is
drawn, which is why every construction-side theory in §22 failed. The draw is
`scripts/emu_fxname.py`, and the answer is `0x400dc3f0` and the group-name table
at `0x401f76f4`: `docs/fx-master-modulation.md` §23.
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.image import differences                          # noqa: E402
from emulib.machine import Machine                            # noqa: E402

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
BUILD = os.environ.get("DT2_BUILD", "out/fxbrowser2")
BUILT = f"{ROOT}/{BUILD}/section_3_MAIN_OS.bin"

MODAL = 0x4010632C          # the destination modal's list constructor
HEADER = 0x401170D8         # the section-header widget constructor
FILL = 0x4019D140           # what fills the string handed to it
GROUP_OF = 0x400DBCE8       # entry -> group
SHORT_NAME = 0x400372DA     # (this, entry) -> record word 14, the short name.
                            # It clamps entry >= 321 to 0, and entry 0/1/2 are the
                            # dead `Error` records whose short name is `ERR`.

RECORDS = 0x401F7FC8
RECORD_SIZE = 60

CONTEXT = 0x4018A97A
STEP_A, STEP_B, STEP_C = 0x4003E40E, 0x40046BFE, 0x4003E41A
PARAMETER_SET = 0x400312AE

WANT = 0x0200               # the list path's mask, 0x40107ab0 -- the owner's list
FX_GROUPS = (16, 17, 18)


def parameter_set(m) -> int:
    a = m.call(CONTEXT)
    b = m.call(STEP_A, a)
    c = m.call(STEP_B, b)
    d = m.call(CONTEXT)
    e = m.call(STEP_C, d)
    return m.call(PARAMETER_SET, e, c) & 0xFFFFFFFF


def cstring(m, address: int, limit: int = 32) -> str:
    if not (0x40000000 <= address < 0x48000000):
        return ""
    out = bytearray()
    while len(out) < limit:
        try:
            b = m.read(address + len(out), 1)[0]
        except Exception:
            break
        if not b or not (0x20 <= b < 0x7F):
            break
        out.append(b)
    return out.decode("latin1")


def describe(m, slot: int) -> str:
    """A string object: show the raw head, what each of its first two longwords
    points at, and any inline bytes. Which spelling this build uses is not
    assumed -- all three are printed so the reader can see which one carries
    the text."""
    try:
        raw = bytes(m.read(slot, 24))
    except Exception:
        return "<unreadable>"
    parts = [f"raw={raw[:12].hex(' ')}"]
    pointer = struct.unpack_from(">I", raw, 0)[0]
    if 0x40000000 <= pointer < 0x48000000:
        try:
            parts.append(f"*{pointer:#010x}=" + bytes(m.read(pointer, 24)).hex(" "))
        except Exception:
            parts.append(f"*{pointer:#010x}=<unreadable>")
    inline = cstring(m, slot)
    if inline:
        parts.append(f"inline={inline!r}")
    return "  ".join(parts)


def trace(m, label: str, pset: int) -> list:
    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_A7

    seen, state, events = [], {"group": None, "entry": None, "fills": 0}, []

    def at_group(uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        entry = struct.unpack(">I", bytes(uc.mem_read(sp + 4, 4)))[0]
        state["entry"] = entry

    def at_fill(uc, address, size, user):
        state["fills"] += 1
        sp = uc.reg_read(UC_M68K_REG_A7)
        dest, src = struct.unpack(">2I", bytes(uc.mem_read(sp + 4, 8)))
        state["fill"] = (dest, describe(m, dest), src, describe(m, src))

    def at_name(uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        ret, _this, entry = struct.unpack(">3I", bytes(uc.mem_read(sp, 12)))
        events.append(("name", entry, ret))

    def at_header(uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        args = struct.unpack(">7I", bytes(uc.mem_read(sp + 4, 28)))
        if args[5] != 0xFFFFFFFF:          # an entry widget, not a section header
            return
        events.append(("header", state["entry"], 0))
        seen.append({"entry": state["entry"], "args": args,
                     "label": " | ".join(f"a{i + 2}:" + describe(m, args[i])
                                        for i in (1, 2, 3, 4)),
                     "fill": state.get("fill")})

    handles = [m.uc.hook_add(UC_HOOK_CODE, at_group, begin=GROUP_OF, end=GROUP_OF),
               m.uc.hook_add(UC_HOOK_CODE, at_fill, begin=FILL, end=FILL),
               m.uc.hook_add(UC_HOOK_CODE, at_header, begin=HEADER, end=HEADER),
               m.uc.hook_add(UC_HOOK_CODE, at_name, begin=SHORT_NAME, end=SHORT_NAME)]
    this = m.alloc(1024)
    m.write(this, bytes(1024))
    try:
        m.call(MODAL, this, 0, pset, 0, 0, 0, WANT, 0, 0, 0, 0)
        note = "returned"
    except Exception as exc:                                  # noqa: BLE001
        note = f"faulted: {exc}"
    finally:
        for h in handles:
            m.uc.hook_del(h)

    print(f"  {label}: the modal constructor {note}; "
          f"{len(seen)} header(s), {state['fills']} string fill(s)")
    names = [e for e in events if e[0] == "name"]
    print(f"    {len(names)} short-name lookup(s); "
          f"{sum(1 for _, e, _ in names if e < 3)} of them on a dead record (0/1/2)")
    for index, event in enumerate(events):
        if event[0] != "header":
            continue
        entry = event[1]
        group = m.long(RECORDS + RECORD_SIZE * (entry - 1) + 8) if entry else None
        after = [e for e in events[index + 1:index + 4] if e[0] == "name"]
        shown = ", ".join(f"entry {e}<-{r:#010x}" for _, e, r in after) or "none"
        flag = "   <<< DEAD RECORD" if any(e < 3 for _, e, _ in after) else ""
        print(f"    header group {group:>3} (before entry {entry}): "
              f"short-name lookups {shown}{flag}")
    return seen, events


# The draw side is `scripts/emu_fxname.py`, not here.
#
# A sweep of the modal's vtable slots was tried in this file first and reported
# nothing, because it was looking for the short-name accessor `0x400372da` and
# the modal does not call it: the record's short name is read **inline** at
# `0x40105b72`, and the *group's* short name comes from `0x400dc3f0` and a table
# at `0x401f76f4` that this file never looked at. `emu_fxname.py` asks each row
# widget for the string it displays, which is the measurement this file's
# construction-side result -- "0 short-name lookups on either image" -- was
# pointing at. Keeping a stub here would only invite the same wrong question
# again.


def main() -> int:
    stock_path = os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin")
    runs = differences(open(stock_path, "rb").read(), open(BUILT, "rb").read())
    print(f"  under test: {BUILD}, {len(runs)} run(s) differ from stock\n")

    m = Machine()
    stock_pset = parameter_set(m)
    print(f"  stock: ParameterSet {stock_pset:#010x}")
    stock_seen, _ = trace(m, "stock    ", stock_pset)

    print()
    b = Machine()
    b.apply(runs)
    b.flush()
    built_pset = parameter_set(b)
    print(f"  build: ParameterSet {built_pset:#010x}")
    built_seen, _ = trace(b, "fxbrowser2", built_pset)

    print()
    print("  where a header's text comes from is answered by emu_fxname.py,")
    print("  which asks each row widget for the string it displays.")

    print()
    # The input must be known to arrive before any null is read as a finding.
    if not stock_seen and not built_seen:
        print("  ** no section header was constructed on either image **")
        print("     The modal constructor did not reach its header path here, so")
        print("     nothing about Chorus is shown either way. This is a property")
        print("     of the harness, not of the build, and nothing is concluded.")
        return 2
    if not built_seen:
        print("  ** the build constructed no headers while stock did **")
        print("     That is itself the finding, but check the fault note above first.")
        return 1

    groups = {}
    for row in built_seen:
        entry = row["entry"]
        if entry:
            groups[b.long(RECORDS + RECORD_SIZE * (entry - 1) + 8)] = row["label"]
    missing = [g for g in FX_GROUPS if g not in groups]
    print(f"  groups that got a header on the build: {sorted(groups)}")
    if missing:
        print(f"  ** groups {missing} got no header at all -- the fault is the")
        print(f"     group-change test, not the naming **")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
