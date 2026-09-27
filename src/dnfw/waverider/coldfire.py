"""Waverider on the ColdFire: machine type 5, offered by MACHINE SEL, a WaveTone clone
everywhere else (`docs/waverider-feasibility.md`, "Milestone 5").

The DSP renders type 5 with our own code (section 7, `dnfw.waverider.dsp`). The
ColdFire's job is smaller and is only this:

1. **offer it** -- MACHINE SEL lists the machine types from a static list
   (`{0, 2, 1, 3, 4}` at `0x401ddd58`, copied into a `std::vector` by
   `0x4004d8b6`) and draws a divider wherever the group `0x40059274(type)`
   changes. The list gains a 5 before MIDI, and 5 joins the synth group;
2. **name it** -- the three name accessors (`0x400dc332` long, `0x400dc358`
   short, `0x400dc37e` the third column) are bounded at 4 and read 12-byte rows
   at `0x401f77f4`. The 192 zero bytes after that table are a live 16-long
   array (`0x400dc1fe`, `docs/machine-list.md`), so the table moves to a cave
   with a sixth row, `Waverider` / `WVR`;
3. **permit it** -- the per-type attribute rows at `0x401f7930` (a byte, then a
   16-bit track mask) are read by the permission test `0x400dc19a(type, track)`
   that the machine setter `0x4004cc08` asks before it writes `sound+0xDE`, and
   by two neighbours. Row 5 would be the 16-long table at `0x401f7944`, so these
   move too, with WaveTone's row as the sixth;
4. **behave as WaveTone** -- the one place the sound's machine parameters are
   resolved, `param_set_slot_to_id(slot, type, filter)` (`0x400dc02a`), sends
   type 5 to WaveTone's forty machine slots. So the SYN pages are WaveTone's
   pages, WaveTone's defaults load when the machine is chosen, and the frame
   carries WaveTone's machine parameters -- `WAV1` (index 26) is Waverider's
   POS and `TBL1` (27) its SLOT on the DSP side.

What is **not** changed: the sound's machine type byte stays 5 (so it is saved
and loaded by the stock mechanism, and the frame builder `0x400274ba` sends 5
at frame offset `148 + 2t` from the per-track mirror it already keeps), and no
new storage is added anywhere.

Pure: `compose(stock, assemble)` takes the stock MAIN OS and an assembler
(`dnfw.patch.assemble.assemble`), and returns the edits. Every edit carries the
stock bytes it replaces, and every cave must be zero, with a 4-byte margin.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

BASE = 0x40000400
NEW_TYPE = 5
CLONE = 1                               # WaveTone
LONG_NAME, SHORT_NAME = "Waverider", "WVR"

# -- 1. the MACHINE SEL list -------------------------------------------------------------
LIST_STOCK_VA = 0x401DDD58             # {0, 2, 1, 3, 4}, five longs
LIST_STOCK = (0, 2, 1, 3, 4)
LIST_NEW = (0, 2, 1, 3, NEW_TYPE, 4)    # Waverider after Swarmer, before MIDI's divider
LIST_ALLOC = 0x4004D8E0                 # pea 0x14 -- the vector's storage, 5 longs
LIST_END = 0x4004D900                   # pea 0x401ddd6c -- the copy's end
LIST_CAP = 0x4004D906                   # lea %a0@(20),%a0 -- the vector's capacity
LIST_BEGIN = 0x4004D90A                 # pea 0x401ddd58 -- the copy's start

GROUP_FN = 0x40059274                   # group(type): <0 or >4 -> 0, 0..3 -> 1, 4 -> 2
GROUP_STOCK = bytes.fromhex("202f00046d147203b2806c0a123c0004b280670a600470014e7542004e7570024e75")

# -- 2. the name table -------------------------------------------------------------------
NAMES_STOCK_VA = 0x401F77F4             # 5 rows of {long, short, third}
NAME_ROW = 12
NAME_SITES = (                          # (bound site, base site, stock base, column)
    (0x400DC332, 0x400DC342, "41f9", 0),     # long:  moveq #4 / lea table,%a0
    (0x400DC358, 0x400DC36A, "0680", 4),     # short: moveq #4 / addil table+4,%d0
    (0x400DC37E, 0x400DC390, "0680", 8),     # third: moveq #4 / addil table+8,%d0
)

# -- 3. the per-type attribute rows ------------------------------------------------------
ATTR_STOCK_VA = 0x401F7930              # 5 rows of {byte, 0, u16 track mask}
ATTR_ROW = 4
ATTR_BOUNDS = (0x400DC15C, 0x400DC19C)  # moveq #4 (byte getter), moveq #4 (permission)
ATTR_BASES = ((0x400DC166, 0), (0x400DC180, 2), (0x400DC1B2, 2))   # lea site, column

# -- 4. param_set_slot_to_id: type 5 resolves as WaveTone ---------------------------------
SLOT_TO_ID = 0x400DC02A
SLOT_HOOK = 0x400DC032                  # movel %sp@(12),%d0 ; moveal %sp@(16),%a1
SLOT_HOOK_STOCK = bytes.fromhex("202f000c226f0010")
SLOT_RESUME = 0x400DC03A

# -- 5. the stored-sound LOAD (0x400dd1ea) --------------------------------------------------
# `d1 = (stored[244] + 1) & 0xff; keep the type if 6 > d1, else 0`. The bound is
# a `moveq #6,%d2` reused for nothing else before the compare (the filter type
# loads its own `moveq #7`). SAVE copies `sound+0xDE` to `stored+244` as it is.
LOAD_BOUND = 0x400DD286

# the caves: clean runs from `dnfw cave scan` that no other mod writes, entered
# 4 bytes in and left 4 bytes short, as arpmodes does (docs/memory-map.md).
DATA_CAVE = (0x4028E958, 128)           # the run 0x4028e952, 138 B; long-aligned
CODE_CAVE = (0x4029037C, 129)           # the run 0x40290378, 137 B: the shims
NAME_CAVE = (0x4028DB24, 120)           # the run 0x4028db1d, 131 B: the two names

# Read, never written: what the edits rely on.
GUARDS = (
    (0x400DC02A, "2f027264206f0008", "slot_to_id: saves d2, d1 = 100, a0 = slot"),
    (0x400DC03A, "b288", "slot_to_id resumes with cmpl %a0,%d1"),
    (0x400DC040, "7402", "... and overwrites d2 before it reads it"),
    (0x4004CC42, "4eb9400dc19a", "the machine setter asks the permission test"),
    (0x4004CC94, "114200de", "... and writes the type byte at sound+0xDE"),
    (0x4002757C, "10280d8c", "the frame builder takes each track's type from its mirror"),
    (0x40027582, "37400092", "... and writes it at frame offset 148 + 2t"),
    (0x4005B35C, "2a1b", "MACHINE SEL walks the list..."),
    (0x4005B364, "4eb940059274", "... and asks the group of each type"),
)


@dataclass(frozen=True)
class Edit:
    va: int
    stock: bytes
    new: bytes
    what: str

    def to_json(self) -> dict:
        return {"va": self.va, "stock": self.stock.hex(), "new": self.new.hex(), "what": self.what}


class ComposeError(ValueError):
    """The image is not the one these edits were read from."""


def _read(content: bytes, va: int, n: int) -> bytes:
    return bytes(content[va - BASE:va - BASE + n])


def _need(content: bytes, va: int, want: bytes, why: str) -> None:
    have = _read(content, va, len(want))
    if have != want:
        raise ComposeError(f"{va:#010x}: expected {want.hex()}, found {have.hex()} ({why})")


def _long(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


GROUP_SOURCE = f"""
| group(type), rewritten in place at {GROUP_FN:#010x}: MIDI (4) -> 2, the synths
| 0..3 and Waverider ({NEW_TYPE}) -> 1, anything else 0 (stock: 0..3 -> 1, 4 -> 2).
    move.l  %sp@(4),%d0
    blt.s   2f
    moveq   #4,%d1
    cmp.l   %d0,%d1
    beq.s   3f
    moveq   #{NEW_TYPE},%d1
    cmp.l   %d0,%d1
    bcs.s   2f
    moveq   #1,%d0
    rts
2:  clr.b   %d0
    rts
3:  moveq   #2,%d0
    rts
"""


def group_function(assemble) -> bytes:
    code = assemble(GROUP_SOURCE, base=GROUP_FN)
    if len(code) > len(GROUP_STOCK):
        raise ComposeError(f"the group function grew: {len(code)} > {len(GROUP_STOCK)}")
    return code + bytes(len(GROUP_STOCK) - len(code))


TRACK_TYPE_EXIT = 0x4004B81E            # getMachineType(track): its common exit

SHIMS = f"""
| param_set_slot_to_id, entered from {SLOT_HOOK:#010x}: the two loads it displaced,
| then type {NEW_TYPE} -> {CLONE} (WaveTone), then back. d2 is saved at entry and
| overwritten before it is read ({SLOT_TO_ID + 0x16:#010x}).
slot_shim:
    move.l  %sp@(12),%d0
    movea.l %sp@(16),%a1
    moveq   #{NEW_TYPE},%d2
    cmp.l   %d0,%d2
    bne.s   1f
    moveq   #{CLONE},%d0
1:  jmp     {SLOT_RESUME:#010x}

| A one-argument per-machine UI accessor whose first two instructions were
| `moveq #4,%d1 ; move.l %sp@(4),%d0`, now `jsr` here: the same two loads, with
| type {NEW_TYPE} read as {CLONE}. The jsr's return address sits on top, so the
| caller's argument is at 8. The accessor goes on to `cmp.l %d0,%d1`.
canon_arg:
    move.l  %sp@(8),%d0
    moveq   #{NEW_TYPE},%d1
    cmp.l   %d0,%d1
    bne.s   1f
    moveq   #{CLONE},%d0
1:  moveq   #4,%d1
    rts

| The page accessor 0x400c24ee(type, page): its `move.l %sp@(8),%d1 ; move.l
| %sp@(12),%d0` (after its own push of d2), now `jsr` here, with type {NEW_TYPE}
| read as {CLONE}. d2 holds its bound 4 and is left alone; it compares next.
canon_page:
    move.l  %sp@(12),%d1
    move.l  %sp@(16),%d0
    subq.l  #{NEW_TYPE},%d1
    bne.s   1f
    moveq   #{CLONE},%d1
    rts
1:  addq.l  #{NEW_TYPE},%d1
    rts

| getMachineType(track) 0x4004b7f2, from its read of sound+0xDE: the UI's view of
| a track's machine. Type {NEW_TYPE} is reported as {CLONE}, so the ~60 places the UI
| asks behave as they do for WaveTone. Back to its common exit.
canon_track:
    mvs.b   %a0@(222),%d0
    moveq   #{NEW_TYPE},%d1
    cmp.l   %d0,%d1
    bne.s   1f
    moveq   #{CLONE},%d0
1:  jmp     {TRACK_TYPE_EXIT:#010x}

| The same question, answered with the machine the track really has: for the
| few callers that show or keep the identity (see IDENTITY_SITES). The body of
| 0x4004b7f2 as it stands in stock: the sound through vtable +40, or -1.
raw_track:
    move.l  %a2,%sp@-
    movea.l %sp@(8),%a2
    movea.l %a2@,%a0
    move.l  %a2,%sp@-
    movea.l %a0@(40),%a0
    jsr     %a0@
    addq.l  #4,%sp
    tst.l   %d0
    beq.s   1f
    movea.l %d0,%a0
    mvs.b   %a0@(222),%d0
    bra.s   2f
1:  moveq   #-1,%d0
2:  movea.l %sp@+,%a2
    rts
"""
SHIM_LABELS = ("slot_shim", "canon_arg", "canon_page", "canon_track", "raw_track")

# -- 8. the sound's "is this parameter mine?" (vtable +0x50, 0x40036bfa) --------------------
# For a machine parameter it answers `sound+0xDE == record[param].page`. WaveTone's
# records are page 1, so a Waverider sound would disown its own machine parameters
# (the p-lock, LFO-destination and CC paths ask this). The read becomes a jsr to a
# shim that reads the type as WaveTone's and replays the push it displaced.
VALID_SITE = 0x40036C24                 # mvs.b %a0@(222),%d3 ; move.l %d2,-(%sp)
VALID_STOCK = bytes.fromhex("772800de2f02")
VALID_NEXT = bytes.fromhex("4eb9400dbce8")   # jsr record page(param)
SHIMS2 = f"""
| from {VALID_SITE:#010x} by jsr: the type byte into d3, 5 read as 1, then the
| displaced `move.l %d2,-(%sp)` under the return address. a1 is free: the jsr
| that follows (0x400dbce8) is a scratch-register call.
canon_valid:
    mvs.b   %a0@(222),%d3
    moveq   #{NEW_TYPE},%d0
    cmp.l   %d3,%d0
    bne.s   1f
    moveq   #{CLONE},%d3
1:  movea.l %sp@+,%a1
    move.l  %d2,%sp@-
    jmp     %a1@
"""
SHIM2_LABELS = ("canon_valid",)

# -- 7. getMachineType(track): WaveTone for the UI, the real type for identity ----------
TRACK_TYPE_READ = 0x4004B816            # mvs.b %a0@(222),%d0 ; bra.s exit
TRACK_TYPE_READ_STOCK = bytes.fromhex("712800de6002")
TRACK_TYPE_FN = 0x4004B7F2
TRACK_TYPE_FN_STOCK = bytes.fromhex("2f0a246f00082052" "2f0a20680028" "4e90588f4a806714"
                                    "20522f0a20680028" "4e90588f2040712800de600270ff245f4e75")
# The callers that must see the real type, each an absolute reference to 0x4004b7f2
# (the pc-relative ones in 0x4004b822..0x4004dde0 cannot reach a cave, and are all
# behavioural: the permission test, the parameter reset, the list position).
IDENTITY_SITES = (
    (0x4005A4AC, "47f9", "MACHINE SEL: the current machine's marker (lea into a3)"),
    (0x40071912, "4eb9", "the track's machine name, drawn from the long-name table"),
    (0x4002DB2C, "4eb9", "re-commit of the track's own machine type (0x40031880)"),
    (0x400D5A72, "4eb9", "the track state message: machine type byte"),
    (0x400D675E, "4eb9", "an incoming machine type, compared with the track's before commit"),
)

# -- 6. the per-machine UI tables (0x42432ad4, 0x42432b24): the SYN pages ---------------
# `pages(type)`, `page(type, n)` and `overview(type)` read five-row tables built
# at boot and fall back to an empty page above 4 -- which is what a type-5 track's
# SYN page showed in the emulator before this. Type 5 reads WaveTone's rows.
CANON_ARG_SITES = (
    (0x400C248E, "overview descriptor(type): 0x42432b24 + 44 type"),
    (0x400C24D2, "SYN page count(type): 0x42432ad4[type].count"),
)
CANON_ARG_STOCK = bytes.fromhex("7204202f0004")
PAGE_SITE = 0x400C24F2                  # 0x400c24ee: after `move.l %d2,-(%sp) ; moveq #4,%d2`
PAGE_STOCK = bytes.fromhex("222f0008202f000c")


def _cave_free(content: bytes, cave: tuple[int, int]) -> None:
    at, cap = cave
    if any(_read(content, at - 4, cap + 8)):
        raise ComposeError(f"the cave at {at:#010x} (+{cap}) is not free")


def compose(stock: bytes, assemble) -> dict:
    """-> {"content", "edits", "layout"}. ASSEMBLE(source, base=...) -> bytes."""
    content = bytearray(stock)
    for va, want, why in GUARDS:
        _need(content, va, bytes.fromhex(want), why)
    edits: list[Edit] = []

    def edit(va: int, new: bytes, what: str, stock_bytes: bytes | None = None) -> None:
        old = _read(content, va, len(new)) if stock_bytes is None else stock_bytes
        _need(content, va, old, what)
        content[va - BASE:va - BASE + len(new)] = new
        edits.append(Edit(va, old, new, what))

    # the code cave: the three shims, then the two name strings
    _cave_free(content, CODE_CAVE)
    _cave_free(content, DATA_CAVE)
    table = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in SHIM_LABELS) + "\n"
    blob = assemble(SHIMS + table, base=CODE_CAVE[0])
    shim = blob[:-4 * len(SHIM_LABELS)]
    layout = dict(zip(SHIM_LABELS, struct.unpack(f">{len(SHIM_LABELS)}I",
                                                 blob[-4 * len(SHIM_LABELS):])))
    if len(shim) > CODE_CAVE[1]:
        raise ComposeError(f"the code cave overflows: {len(shim)} > {CODE_CAVE[1]}")
    edit(CODE_CAVE[0], shim, "the shims: type 5 resolves as WaveTone in slot_to_id, the SYN "
                             "page tables and getMachineType; the real type for identity")

    # the name cave: the two strings, then the second shim block
    _cave_free(content, NAME_CAVE)
    names = LONG_NAME.encode("ascii") + b"\0" + SHORT_NAME.encode("ascii") + b"\0"
    names += bytes(-len(names) % 4)
    layout["long_name"] = NAME_CAVE[0]
    layout["short_name"] = NAME_CAVE[0] + len(LONG_NAME) + 1
    at2 = NAME_CAVE[0] + len(names)
    table2 = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in SHIM2_LABELS) + "\n"
    blob2 = assemble(SHIMS2 + table2, base=at2)
    shim2 = blob2[:-4 * len(SHIM2_LABELS)]
    layout.update(zip(SHIM2_LABELS, struct.unpack(f">{len(SHIM2_LABELS)}I",
                                                  blob2[-4 * len(SHIM2_LABELS):])))
    names += shim2
    if len(names) > NAME_CAVE[1]:
        raise ComposeError(f"the name cave overflows: {len(names)} > {NAME_CAVE[1]}")
    edit(NAME_CAVE[0], names, f"Waverider's names ({LONG_NAME!r}, {SHORT_NAME!r}) and the "
                              "parameter-ownership shim")

    # the data cave: the six-row name table, the six attribute rows, the list
    _need(content, LIST_STOCK_VA, b"".join(_long(t) for t in LIST_STOCK), "the MACHINE SEL list")
    names_rows = _read(content, NAMES_STOCK_VA, NAME_ROW * 5)
    attr_rows = _read(content, ATTR_STOCK_VA, ATTR_ROW * 5)
    layout["names"] = DATA_CAVE[0]
    layout["attributes"] = layout["names"] + NAME_ROW * 6
    layout["list"] = layout["attributes"] + ATTR_ROW * 6
    row5 = _long(layout["long_name"]) + _long(layout["short_name"]) + _long(0)
    blob = (names_rows + row5
            + attr_rows + attr_rows[ATTR_ROW * CLONE:ATTR_ROW * (CLONE + 1)]
            + b"".join(_long(t) for t in LIST_NEW))
    if len(blob) > DATA_CAVE[1]:
        raise ComposeError(f"the data cave overflows: {len(blob)} > {DATA_CAVE[1]}")
    edit(DATA_CAVE[0], blob, "Waverider's data: the six-row name table, the six attribute "
                             "rows (the sixth is WaveTone's), the six-entry MACHINE SEL list")

    # 1. the list
    edit(LIST_ALLOC, bytes.fromhex("48780018"), "MACHINE SEL list: storage for 6 longs",
         bytes.fromhex("48780014"))
    edit(LIST_END, bytes.fromhex("4879") + _long(layout["list"] + 4 * len(LIST_NEW)),
         "MACHINE SEL list: the copy's end", bytes.fromhex("4879") + _long(LIST_STOCK_VA + 20))
    edit(LIST_CAP, bytes.fromhex("41e80018"), "MACHINE SEL list: the vector's capacity, 6 longs",
         bytes.fromhex("41e80014"))
    edit(LIST_BEGIN, bytes.fromhex("4879") + _long(layout["list"]),
         "MACHINE SEL list: the copy's start", bytes.fromhex("4879") + _long(LIST_STOCK_VA))
    edit(GROUP_FN, group_function(assemble), "the MACHINE SEL group: type 5 joins the synths (1)",
         GROUP_STOCK)

    # 2. the names
    for bound, base, op, col in NAME_SITES:
        edit(bound, bytes.fromhex("7205"), f"name column {col // 4}: bound 4 -> 5",
             bytes.fromhex("7204"))
        edit(base + 2, _long(layout["names"] + col), f"name column {col // 4}: the six-row table",
             _long(NAMES_STOCK_VA + col))
        _need(content, base, bytes.fromhex(op), "the name accessor's base instruction")

    # 3. the attribute rows
    for bound in ATTR_BOUNDS:
        edit(bound, bytes.fromhex("7405" if bound == 0x400DC19C else "7205"),
             "attribute rows: bound 4 -> 5", bytes.fromhex("7404" if bound == 0x400DC19C else "7204"))
    for site, col in ATTR_BASES:
        _need(content, site, bytes.fromhex("41f9"), "the attribute accessor's lea")
        edit(site + 2, _long(layout["attributes"] + col), "attribute rows: the six-row copy",
             _long(ATTR_STOCK_VA + col))

    # 5. the stored-sound LOAD keeps type 5 (stock turns it into FM Tone)
    edit(LOAD_BOUND, bytes.fromhex("7407"), "stored-sound LOAD: machine types -1..5 are kept "
                                            "(stock keeps -1..4; anything else loads as FM Tone)",
         bytes.fromhex("7406"))

    # 4. slot_to_id
    edit(SLOT_HOOK, bytes.fromhex("4ef9") + _long(layout["slot_shim"]) + bytes.fromhex("4e71"),
         "param_set_slot_to_id: detour to the shim", SLOT_HOOK_STOCK)

    # 6. the SYN page tables
    for site, what in CANON_ARG_SITES:
        edit(site, bytes.fromhex("4eb9") + _long(layout["canon_arg"]),
             f"{what}: type 5 reads WaveTone's row", CANON_ARG_STOCK)
    edit(PAGE_SITE, bytes.fromhex("4eb9") + _long(layout["canon_page"]) + bytes.fromhex("4e71"),
         "SYN page(type, n): 0x42432ad4[type].pages[n]; type 5 reads WaveTone's", PAGE_STOCK)
    _need(content, PAGE_SITE - 4, bytes.fromhex("2f027404"), "0x400c24ee's push of d2 and its bound")

    # 7. getMachineType(track): WaveTone for the UI, the real type where it is identity
    _need(content, TRACK_TYPE_FN, TRACK_TYPE_FN_STOCK, "getMachineType(track), as raw_track copies it")
    edit(TRACK_TYPE_READ, bytes.fromhex("4ef9") + _long(layout["canon_track"]),
         "getMachineType(track): type 5 is reported as WaveTone", TRACK_TYPE_READ_STOCK)
    for op_va, op, what in IDENTITY_SITES:
        _need(content, op_va, bytes.fromhex(op), f"{what}: the instruction")
        edit(op_va + 2, _long(layout["raw_track"]), f"{what}: asks for the real type",
             _long(TRACK_TYPE_FN))

    # 8. the sound's "is this parameter mine?"
    _need(content, VALID_SITE + len(VALID_STOCK), VALID_NEXT, "the ownership test's record-page call")
    edit(VALID_SITE, bytes.fromhex("4eb9") + _long(layout["canon_valid"]),
         "the sound's parameter-ownership test: type 5 owns WaveTone's machine parameters",
         VALID_STOCK)
    return {"content": bytes(content), "edits": edits, "layout": layout}
