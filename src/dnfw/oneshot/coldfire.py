"""ONESHOT on the ColdFire: a machine type the DN2 offers, with the DT2's own page.

The DSP renders the machine (`dnfw.oneshot.build`); the ColdFire's job is to
let a track *be* it, show its page, and send its parameters. The page's
content is the Digitakt II's -- its eight parameter records, their formatters
(the DN2's byte-identical twins) and its knob list -- composed from the user's
DT2 file by `dnfw.transplant.cfplan`. This module is the plumbing around it.

**The machine-type sites are Waverider Milestone 5's** (`docs/machine-list.md`,
"What a sixth machine actually cost on the ColdFire", on `feature/waverider-m5`):
MACHINE SEL's list and group, the three name accessors, the attribute rows and
their permission test, the stored-sound LOAD bound, `param_set_slot_to_id`, the
SYN page accessors and the sound's parameter-ownership test. Waverider answers
each of them with "WaveTone"; ONESHOT answers the two that decide what a track
*is* -- its parameter slots and its SYN page -- with its own. The addresses are
facts measured there; the code here is this module's own.

**Type 5, exclusive with Waverider, for now.** Both claim machine type 5 and
the same sites. When Waverider M5 lands with a seven-row machine list, ONESHOT
moves to type 6 by changing `NEW_TYPE` and the list (`docs/dt2-machine-port.md`,
"The plan to a flashable ONESHOT").

What changes, in MAIN OS:

1. **offer it**: MACHINE SEL lists `{0, 2, 1, 3, 5, 4}` (ONESHOT after Swarmer),
   and the group function puts 5 with the synths;
2. **name it**: the three name accessors read a six-row table whose sixth row is
   the DT2's own `Oneshot` / `ONE`;
3. **permit it**: the attribute rows gain a sixth, WaveTone's (all tracks);
4. **keep it**: the stored-sound LOAD keeps types -1..5;
5. **its parameters**: `param_set_slot_to_id(slot, 5, filter)` answers slots
   25..64 from ONESHOT's own map (the DT2 records' slots), so a machine change
   loads the DT2 defaults and the frame carries the DT2 values;
6. **its page**: the SYN page count, page and overview accessors give type 5
   one page, the DT2 descriptor;
7. **its records are its own**: the records carry page id 1, which the DN2
   reads as "a machine parameter" (page <= 4); the ownership test reads type 5
   as 1, so a ONESHOT sound owns them (and WaveTone's, harmlessly);
8. **room for eight records**: the eight DT2 records take the places of eight
   of the table's dead `Error` records (entries 1-5 and 11-13), in the image.
   Appending them after the stock 320, as LFO4 does, was tried first and failed
   in the emulator: the runtime companion table (68 bytes an entry, 321 entries,
   `0x4243325c`) cannot grow, so entries 321.. clamp to entry 0 there -- a machine
   change loaded 0xffff into every ONESHOT slot and drawing the page faulted
   (`docs/dt2-machine-port.md`, "The ColdFire half"). LFO4 gets away with it
   because its values have their own storage (its C). Everything else -- the
   strings, the tables, the shims -- is one CODE chunk the startup loader
   (`dnfw.patch.loader`) copies to RAM.

Pure: `compose` takes the stock MAIN OS, a checked `CfPlan` and the assembled
shims, and returns the new MAIN OS and every edit with the bytes it replaced.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..patch import area, loader, paramtable
from ..transplant import cfspec as C

BASE = 0x40000400
NEW_TYPE = 5
RECORD_PAGE = 1                         # "a machine parameter", as WaveTone's records are
OWNER_AS = RECORD_PAGE                  # the ownership test reads type 5 as this

# -- where everything lives: one CODE chunk the startup loader copies to RAM ------------
CHUNK_VA = 0x46900000                   # above BSS (0x466b74d0), as LFO4's table
# the dead `Error` records ONESHOT's eight take over (entry = index + 1). Entries
# 17 and 18 are dead too but carry a range and a default; they are left alone.
DEAD_ENTRIES = (1, 2, 3, 4, 5, 11, 12, 13)
ADDED = len(DEAD_ENTRIES)
STRINGS_OFF = 0x0000
DATA_OFF = 0x0400
SHIMS_OFF = 0x0800
CHUNK_BYTES = 0x0A00
SHIMS_VA = CHUNK_VA + SHIMS_OFF

# -- 1. MACHINE SEL -----------------------------------------------------------------------
LIST_STOCK_VA = 0x401DDD58
LIST_STOCK = (0, 2, 1, 3, 4)
LIST_NEW = (0, 2, 1, 3, NEW_TYPE, 4)
LIST_ALLOC, LIST_END, LIST_CAP, LIST_BEGIN = 0x4004D8E0, 0x4004D900, 0x4004D906, 0x4004D90A
GROUP_FN = 0x40059274
GROUP_STOCK = bytes.fromhex("202f00046d147203b2806c0a123c0004b280670a600470014e7542004e7570024e75")

# -- 2. names -------------------------------------------------------------------------------
NAMES_STOCK_VA, NAME_ROW = 0x401F77F4, 12
NAME_SITES = ((0x400DC332, 0x400DC342, "41f9", 0),
              (0x400DC358, 0x400DC36A, "0680", 4),
              (0x400DC37E, 0x400DC390, "0680", 8))

# -- 3. attributes --------------------------------------------------------------------------
ATTR_STOCK_VA, ATTR_ROW = 0x401F7930, 4
ATTR_BOUNDS = (0x400DC15C, 0x400DC19C)
ATTR_BASES = ((0x400DC166, 0), (0x400DC180, 2), (0x400DC1B2, 2))
ATTR_CLONE = 1                          # WaveTone's row: every track may hold it

# -- 4. LOAD --------------------------------------------------------------------------------
LOAD_BOUND = 0x400DD286                 # moveq #6,%d2: keep -1..4

# -- 5. param_set_slot_to_id ------------------------------------------------------------------
SLOT_HOOK = 0x400DC032                  # movel %sp@(12),%d0 ; moveal %sp@(16),%a1
SLOT_HOOK_STOCK = bytes.fromhex("202f000c226f0010")
SLOT_RESUME = 0x400DC03A
SLOT_FIRST, SLOT_LAST = 25, 64

# -- 6. SYN pages ---------------------------------------------------------------------------
OVERVIEW_FN = 0x400C248E                # overview(type): 0x42432b24 + 44 type
COUNT_FN = 0x400C24D2                   # count(type): 0x42432ad4[type].count
PAGE_FN = 0x400C24EE                    # page(type, n): 0x42432ad4[type].pages + 44 n
ONE_ARG_STOCK = bytes.fromhex("7204202f0004")        # moveq #4,%d1 ; movel %sp@(4),%d0
PAGE_STOCK = bytes.fromhex("2f027404222f0008")       # movel %d2,-(%sp); moveq #4,%d2; movel %sp@(8),%d1
PAGE_FALLBACK = 0x42432BD4              # the empty page every accessor falls back to

# -- 7. ownership -----------------------------------------------------------------------------
VALID_SITE = 0x40036C24                 # mvs.b %a0@(222),%d3 ; move.l %d2,-(%sp)
VALID_STOCK = bytes.fromhex("772800de2f02")
VALID_NEXT = bytes.fromhex("4eb9400dbce8")

GUARDS = (
    (0x400DC02A, "2f027264206f0008", "slot_to_id: saves d2, d1 = 100, a0 = slot"),
    (0x400DC03A, "b288", "slot_to_id resumes with cmpl %a0,%d1"),
    (0x4004CC42, "4eb9400dc19a", "the machine setter asks the permission test"),
    (0x4004CC94, "114200de", "... and writes the type byte at sound+0xDE"),
    (0x4002757C, "10280d8c", "the frame builder takes each track's type from its mirror"),
    (0x40027582, "37400092", "... and writes it at frame offset 148 + 2t"),
    (0x4005B35C, "2a1b", "MACHINE SEL walks the list..."),
    (0x4005B364, "4eb940059274", "... and asks the group of each type"),
    (0x400C2494, "b280", "overview: compares after the two loads"),
    (0x400C24D8, "b280", "count: compares after the two loads"),
    (0x400C24F6, "202f000c", "page: loads n after the displaced three"),
)


class ComposeError(ValueError):
    """The image is not the one these edits were read from."""


@dataclass(frozen=True)
class Edit:
    va: int
    stock: bytes
    new: bytes
    what: str

    def to_json(self) -> dict:
        return {"va": self.va, "stock": self.stock.hex(), "new": self.new.hex(), "what": self.what}


# -- the chunk's data layout ------------------------------------------------------------------
@dataclass(frozen=True)
class Layout:
    names: int              # six rows of {long, short, third}
    attributes: int         # six rows of {byte, 0, u16 mask}
    machine_list: int       # six longs
    slot_map: int           # 40 longs: slot 25..64 -> entry, 0 = none
    descriptor: int         # 44 bytes: {title, subtitle, 8 entries, tag}
    reps: int               # the two static COW string reps
    strings: int

    @classmethod
    def fixed(cls) -> "Layout":
        d = CHUNK_VA + DATA_OFF
        return cls(names=d, attributes=d + 0x48, machine_list=d + 0x60, slot_map=d + 0x80,
                   descriptor=d + 0x120, reps=d + 0x150, strings=CHUNK_VA + STRINGS_OFF)


def shim_source(layout: Layout | None = None) -> str:
    """The shims, assembled at SHIMS_VA. Our own code."""
    lay = layout or Layout.fixed()
    return f"""
| param_set_slot_to_id(slot, type, filter), from {SLOT_HOOK:#010x}: the two loads it
| displaced, then a type-{NEW_TYPE} machine slot ({SLOT_FIRST}..{SLOT_LAST}) is answered from
| ONESHOT's map (0 = none); anything else resumes the stock routine with d1 = 100, as it
| left it. d2 is on the stack, and the routine overwrites it before reading it.
slot_shim:
    move.l  %sp@(12),%d0
    movea.l %sp@(16),%a1
    moveq   #{NEW_TYPE},%d1
    cmp.l   %d0,%d1
    bne.s   1f
    move.l  %a0,%d1
    moveq   #{SLOT_FIRST},%d2
    sub.l   %d2,%d1
    moveq   #{SLOT_LAST - SLOT_FIRST},%d2
    cmp.l   %d1,%d2
    bcs.s   1f
    lea     {lay.slot_map:#x},%a1
    move.l  %a1@(0,%d1:l:4),%d0
    move.l  %sp@+,%d2
    rts
1:  moveq   #100,%d1
    jmp     {SLOT_RESUME:#x}

| overview(type) {OVERVIEW_FN:#010x}: type {NEW_TYPE} -> the ONESHOT descriptor.
overview_shim:
    move.l  %sp@(4),%d0
    moveq   #{NEW_TYPE},%d1
    cmp.l   %d0,%d1
    beq.s   1f
    moveq   #4,%d1
    jmp     {OVERVIEW_FN + 6:#x}
1:  move.l  #{lay.descriptor:#x},%d0
    rts

| count(type) {COUNT_FN:#010x}: type {NEW_TYPE} has one SYN page.
count_shim:
    move.l  %sp@(4),%d0
    moveq   #{NEW_TYPE},%d1
    cmp.l   %d0,%d1
    beq.s   1f
    moveq   #4,%d1
    jmp     {COUNT_FN + 6:#x}
1:  moveq   #1,%d0
    rts

| page(type, n) {PAGE_FN:#010x}: type {NEW_TYPE}, page 0 -> the descriptor; any other
| page -> the stock fallback. d2 was pushed by the displaced prologue.
page_shim:
    move.l  %d2,%sp@-
    moveq   #4,%d2
    move.l  %sp@(8),%d1
    moveq   #{NEW_TYPE},%d0
    cmp.l   %d1,%d0
    beq.s   1f
    jmp     {PAGE_FN + 8:#x}
1:  move.l  #{PAGE_FALLBACK:#x},%d0
    tst.l   %sp@(12)
    bne.s   2f
    move.l  #{lay.descriptor:#x},%d0
2:  move.l  %sp@+,%d2
    rts

| the sound's "is this parameter mine?" at {VALID_SITE:#010x}, by jsr: the type byte into
| d3, {NEW_TYPE} read as {OWNER_AS} (the records' page), then the displaced push of d2.
canon_valid:
    mvs.b   %a0@(222),%d3
    moveq   #{NEW_TYPE},%d0
    cmp.l   %d3,%d0
    bne.s   1f
    moveq   #{OWNER_AS},%d3
1:  movea.l %sp@+,%a1
    move.l  %d2,%sp@-
    jmp     %a1@
"""


SHIM_LABELS = ("slot_shim", "overview_shim", "count_shim", "page_shim", "canon_valid")

GROUP_SOURCE = f"""
| group(type), rewritten in place at {GROUP_FN:#010x}: MIDI (4) -> 2, the synths
| 0..3 and ONESHOT ({NEW_TYPE}) -> 1, anything else 0 (stock: 0..3 -> 1, 4 -> 2).
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


def assemble_shims(assemble) -> dict:
    """-> {"code": bytes, "labels": {name: va}, "group": bytes}. Needs the m68k assembler."""
    table = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in SHIM_LABELS) + "\n"
    blob = assemble(shim_source() + table, base=SHIMS_VA)
    code = blob[:-4 * len(SHIM_LABELS)]
    labels = dict(zip(SHIM_LABELS, struct.unpack(f">{len(SHIM_LABELS)}I",
                                                 blob[-4 * len(SHIM_LABELS):])))
    group = assemble(GROUP_SOURCE, base=GROUP_FN)
    if len(group) > len(GROUP_STOCK):
        raise ComposeError(f"the group function grew: {len(group)} > {len(GROUP_STOCK)}")
    return {"code": code, "labels": labels, "group": group + bytes(len(GROUP_STOCK) - len(group))}


# -- strings and reps ---------------------------------------------------------------------------
def _strings_blob(texts: list[tuple[str, str]], at: int) -> tuple[bytes, dict[str, int]]:
    blob, where = b"", {}
    for key, text in texts:
        where[key] = at + len(blob)
        blob += text.encode("ascii") + b"\0"
    return blob, where


def cow_rep(text: str) -> bytes:
    """A static libstdc++ COW string rep, `[length][capacity][refcount -1][chars\\0]`,
    padded to a longword. A std::string's pointer names the chars (rep + 12); refcount
    -1 is 'leaked': every copy clones, nothing frees it (digikit's `machinepatch`)."""
    raw = text.encode("ascii")
    rep = struct.pack(">IIi", len(raw), len(raw), -1) + raw + b"\0"
    return rep + bytes(-len(rep) % 4)


def compose(stock: bytes, plan, shims: dict) -> dict:
    """-> {"content": the new MAIN OS, "edits": [...], "layout": {...}, "chunk": bytes}.

    `stock` is Digitone II 1.11 MAIN OS as shipped; `plan` a checked `CfPlan`;
    `shims` the output of `assemble_shims` (or the committed JSON of it)."""
    if not plan.ok:
        raise ComposeError("the ColdFire plan refused: " + "; ".join(plan.refusals))
    content = bytearray(stock)
    for va, want, why in GUARDS:
        _need(content, va, bytes.fromhex(want), why)
    edits: list[Edit] = []

    def edit(va: int, new: bytes, what: str, old: bytes | None = None) -> None:
        cur = _read(content, va, len(new)) if old is None else old
        _need(content, va, cur, what)
        content[va - BASE:va - BASE + len(new)] = new
        edits.append(Edit(va, cur, new, what))

    lay = Layout.fixed()
    labels = shims["labels"]

    # the records, in place of the dead ones; each keeps the dead record's ordinal
    dead = [record_va(e) for e in DEAD_ENTRIES]
    for e, va in zip(DEAD_ENTRIES, dead):
        _need_dead(content, e, va)
    ordinals = [struct.unpack_from(">I", _read(content, va + C.ORDINAL, 4))[0] for va in dead]
    texts = plan.strings()
    strings, string_va = _strings_blob(texts, lay.strings)
    if len(strings) > DATA_OFF - STRINGS_OFF:
        raise ComposeError(f"the strings overflow their room: {len(strings)} B")
    donor_entry0 = plan.spec.records.donor_entry
    entry_of = {donor_entry0 + k: DEAD_ENTRIES[k] for k in range(ADDED)}
    records = plan.records(page=RECORD_PAGE, ordinals=ordinals, string_va=string_va)

    # the data: names, attributes, list, slot map, descriptor, reps
    names_rows = _read(content, NAMES_STOCK_VA, NAME_ROW * 5)
    names = names_rows + _long(string_va["machine.long"]) + _long(string_va["machine.short"]) + _long(0)
    attr_rows = _read(content, ATTR_STOCK_VA, ATTR_ROW * 5)
    attrs = attr_rows + attr_rows[ATTR_ROW * ATTR_CLONE:ATTR_ROW * (ATTR_CLONE + 1)]
    mlist = b"".join(_long(t) for t in LIST_NEW)
    slot_map = [0] * (SLOT_LAST - SLOT_FIRST + 1)
    for k in range(ADDED):
        rec = records[C.RECORD * k:C.RECORD * (k + 1)]
        slot = struct.unpack_from(">I", rec, C.SLOT)[0]
        if not SLOT_FIRST <= slot <= SLOT_LAST:
            raise ComposeError(f"record {k} has slot {slot}, outside the machine window")
        slot_map[slot - SLOT_FIRST] = DEAD_ENTRIES[k]
    title, subtitle = dict(texts)["page.title"], dict(texts)["machine.long"]
    rep_t = cow_rep(title)
    rep_s = cow_rep(subtitle)
    reps = rep_t + rep_s
    entries = plan.page_entries(entry_of)
    descriptor = (_long(lay.reps + 12) + _long(lay.reps + len(rep_t) + 12)
                  + b"".join(_long(e) for e in entries) + _long(plan.spec.page.tag))

    chunk = bytearray(CHUNK_BYTES)

    def put(va: int, blob: bytes, room: int | None = None) -> None:
        at = va - CHUNK_VA
        if room is not None and len(blob) > room:
            raise ComposeError(f"{len(blob)} B at {va:#x} overflow {room}")
        if any(chunk[at:at + len(blob)]):
            raise ComposeError(f"{va:#x}: the chunk is not blank there")
        chunk[at:at + len(blob)] = blob

    put(lay.strings, strings, DATA_OFF - STRINGS_OFF)
    put(lay.names, names, 0x48)
    put(lay.attributes, attrs, 0x18)
    put(lay.machine_list, mlist, 0x20)
    put(lay.slot_map, b"".join(_long(e) for e in slot_map), 0xA0)
    put(lay.descriptor, descriptor, 0x30)
    put(lay.reps, reps, SHIMS_OFF - (lay.reps - CHUNK_VA))
    put(SHIMS_VA, shims["code"], CHUNK_BYTES - SHIMS_OFF)

    # 8. the records
    for k, (e, va) in enumerate(zip(DEAD_ENTRIES, dead)):
        edit(va, records[C.RECORD * k:C.RECORD * (k + 1)],
             f"parameter entry {e}: the dead Error record becomes DT2 "
             f"{plan.spec.records.labels[k]}")

    # 1. MACHINE SEL
    _need(content, LIST_STOCK_VA, b"".join(_long(t) for t in LIST_STOCK), "the MACHINE SEL list")
    edit(LIST_ALLOC, bytes.fromhex("48780018"), "MACHINE SEL list: storage for 6 longs",
         bytes.fromhex("48780014"))
    edit(LIST_END, bytes.fromhex("4879") + _long(lay.machine_list + 4 * len(LIST_NEW)),
         "MACHINE SEL list: the copy's end", bytes.fromhex("4879") + _long(LIST_STOCK_VA + 20))
    edit(LIST_CAP, bytes.fromhex("41e80018"), "MACHINE SEL list: capacity 6", bytes.fromhex("41e80014"))
    edit(LIST_BEGIN, bytes.fromhex("4879") + _long(lay.machine_list), "MACHINE SEL list: the copy's start",
         bytes.fromhex("4879") + _long(LIST_STOCK_VA))
    edit(GROUP_FN, shims["group"], "MACHINE SEL group: type 5 joins the synths", GROUP_STOCK)

    # 2. names
    for bound, base, op, col in NAME_SITES:
        edit(bound, bytes.fromhex("7205"), f"name column {col // 4}: bound 4 -> 5", bytes.fromhex("7204"))
        _need(content, base, bytes.fromhex(op), "the name accessor's base instruction")
        edit(base + 2, _long(lay.names + col), f"name column {col // 4}: the six-row table",
             _long(NAMES_STOCK_VA + col))

    # 3. attributes
    for bound in ATTR_BOUNDS:
        new, old = ("7405", "7404") if bound == 0x400DC19C else ("7205", "7204")
        edit(bound, bytes.fromhex(new), "attribute rows: bound 4 -> 5", bytes.fromhex(old))
    for site, col in ATTR_BASES:
        _need(content, site, bytes.fromhex("41f9"), "the attribute accessor's lea")
        edit(site + 2, _long(lay.attributes + col), "attribute rows: the six-row copy",
             _long(ATTR_STOCK_VA + col))

    # 4. LOAD
    edit(LOAD_BOUND, bytes.fromhex("7407"), "stored-sound LOAD keeps machine types -1..5",
         bytes.fromhex("7406"))

    # 5. slot_to_id
    edit(SLOT_HOOK, b"\x4e\xf9" + _long(labels["slot_shim"]) + b"\x4e\x71",
         "param_set_slot_to_id: type 5's machine slots from ONESHOT's map", SLOT_HOOK_STOCK)

    # 6. SYN pages
    edit(OVERVIEW_FN, b"\x4e\xf9" + _long(labels["overview_shim"]), "SYN overview(type): 5 -> ONESHOT",
         ONE_ARG_STOCK)
    edit(COUNT_FN, b"\x4e\xf9" + _long(labels["count_shim"]), "SYN page count(type): 5 -> 1", ONE_ARG_STOCK)
    edit(PAGE_FN, b"\x4e\xf9" + _long(labels["page_shim"]) + b"\x4e\x71",
         "SYN page(type, n): 5 -> the ONESHOT descriptor", PAGE_STOCK)

    # 7. ownership
    _need(content, VALID_SITE + len(VALID_STOCK), VALID_NEXT, "the ownership test's record-page call")
    edit(VALID_SITE, b"\x4e\xb9" + _long(labels["canon_valid"]),
         "parameter ownership: type 5 owns page-1 records", VALID_STOCK)

    code_chunk = area.CodeChunk(load=CHUNK_VA, image=bytes(chunk)).pack()
    out = loader.install(bytes(content), [(area.CODE, code_chunk)])
    layout = {"chunk": CHUNK_VA,
              "entries": {plan.spec.records.labels[k]: DEAD_ENTRIES[k] for k in range(ADDED)},
              "page_entries": entries, "slot_map": {SLOT_FIRST + i: e for i, e in enumerate(slot_map) if e},
              "descriptor": lay.descriptor, "names": lay.names, "attributes": lay.attributes,
              "machine_list": lay.machine_list, "ordinals": ordinals, **labels}
    return {"content": bytes(out), "edits": edits, "layout": layout, "chunk": bytes(chunk)}


def record_va(entry: int) -> int:
    """Where entry ENTRY's 60-byte record starts (its page-id word)."""
    return paramtable.TABLE + paramtable.RECORD * (entry - 1) + 8


def _need_dead(content, entry: int, va: int) -> None:
    """A dead record: no page, no slot, range 0, and its names are all `Error`/`ERR`."""
    rec = _read(content, va, C.RECORD)
    page, slot, top = (struct.unpack_from(">I", rec, o)[0] for o in (C.PAGE, C.SLOT, C.MAXIMUM))
    short = _cstr(content, struct.unpack_from(">I", rec, C.SHORT_NAME)[0])
    if page != C.UNSET or slot != C.UNSET or top != 0 or short != "ERR":
        raise ComposeError(f"entry {entry} at {va:#010x} is not a dead Error record "
                           f"(page {page:#x}, slot {slot:#x}, max {top:#x}, {short!r})")


def _cstr(content, va: int) -> str:
    at = va - BASE
    return bytes(content[at:content.index(0, at)]).decode("latin1") if 0 <= at < len(content) else ""


def _read(content, va: int, n: int) -> bytes:
    return bytes(content[va - BASE:va - BASE + n])


def _need(content, va: int, want: bytes, why: str) -> None:
    have = _read(content, va, len(want))
    if have != want:
        raise ComposeError(f"{va:#010x}: expected {want.hex()}, found {have.hex()} ({why})")


def _long(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)
