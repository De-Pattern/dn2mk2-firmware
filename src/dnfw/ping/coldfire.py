"""PING on the ColdFire: filter type 6, offered by the FLTR type list, Multi-Mode's
pages and parameters everywhere else (`docs/ping.md`, "P2").

The DSP renders type 6 with our own code (`csrc/waverider/sharc/ping.asm`): the stock
unpack maps any filter type above 5 to its "no filter" (measured, P0), and PING runs
in Waverider's loop tail, reading the track's Multi-Mode records. So the ColdFire's
job is this, and only this:

1. **offer it** -- the FLTR type list is a static `{0, 1, 4, 3, 5, 2}` at
   `0x401ddd40`, copied once into a vector by `0x4004dae2` (storage `pea 0x18`,
   capacity `lea %a0@(24)`, the copy's begin and end). The list gains a 6 at its end;
   the list is the four edits that W5 made to MACHINE SEL's;
2. **name it** -- the long and short name accessors (`0x400dc3a4`, `0x400dc3ca`) are
   bounded at 5 and read 12-byte rows at `0x401f77ac`; they get a seventh row,
   `Ping` / `PING`, in a copy of the table;
3. **keep it** -- the stored-sound LOAD keeps filter types -1..5 (`moveb #7,%d2` at
   `0x400dd2bc`, the bound of an unsigned `type + 1 < 7`), and anything else loads
   as Multi-Mode; it keeps -1..6;
4. **behave as Multi-Mode** -- `param_set_slot_to_id(slot, type, filter)`
   (`0x400dc02a`) resolves the three filter-type slots 66..68 through a table of six
   rows (`moveq #5,%d2 ; cmp.l %a1,%d2 ; bcs` at `0x400dc096`), and returns id 0
   above it. Filter 6 reads row 0. So the FLTR page's parameters are Multi-Mode's
   records, which is what `dnfw.ping.live` reads on the DSP side (+0x1C8 TYPE, FREQ,
   RESO); and the FLTR page's descriptor, `0x400c24b0(filter)` (six rows of 44 at
   `0x424329cc`, an empty page above 5), reads row 0 for 6.

What is **not** changed: the sound's filter byte (`sound+0xDF`) stays 6, so it is
saved and loaded by the stock mechanism and the frame builder sends it from the
per-track mirror (`+0xD8D`, frame offset 178) as it is. `getFilterType` is not
canonicalised: its fourteen callers either go through slot_to_id or the descriptor
(both answer 6 as 0 now), report identity (the list marker, the state message), or
switch on it with a bound: the FLTR page's response curve (`0x4006eca0`, six cases,
on page id 12) would draw nothing for 6, leaving FREQ and RING blank (emulator,
2026-10-13), so it draws Multi-Mode's.

The parameter-ownership test (`0x40036bfa`) owns every filter parameter whatever the
type (`0x400dbee6`), so p-locks and LFO destinations need nothing.

All new code and data are one platform `CODE` chunk in RAM at `LOAD`, below the
platform runtime and above Waverider's page chunk. Every edit carries the stock bytes
it replaces.
"""

from __future__ import annotations

import struct

BASE = 0x40000400
NEW_FILTER = 6                          # PING
NEW_FILTERS = (6, 7, 8, 9, 10)          # PING, SHFT (docs/shft.md), GRAN (docs/gran.md), COMB-, COMB+ (docs/comb.md)
CLONE = 0                               # Multi-Mode
NAMES = {6: ("Ping", "PING"), 7: ("Shift", "SHFT"), 8: ("Grains", "GRAN"),
         9: ("Comb-", "COMB-"), 10: ("Comb+", "COMB+")}
LONG_NAME, SHORT_NAME = NAMES[6]

LOAD = 0x4670F000                       # Waverider's region (pages.LOAD..C_END), its last 4 KB
END = 0x4670F800                        # the machines chunk (dnfw.waverider.coldfire.MCHUNK) starts here

LIST_STOCK_VA = 0x401DDD40              # {0, 1, 4, 3, 5, 2}, six longs
LIST_STOCK = (0, 1, 4, 3, 5, 2)
LIST_NEW = LIST_STOCK + NEW_FILTERS     # Ping, then Shift, at the end
LIST_ALLOC = 0x4004DB0C                 # pea 0x18 -- the vector's storage
LIST_END = 0x4004DB2C                   # pea 0x401ddd58 -- the copy's end
LIST_CAP = 0x4004DB32                   # lea %a0@(24),%a0 -- the capacity
LIST_BEGIN = 0x4004DB36                 # pea 0x401ddd40 -- the copy's start

NAMES_STOCK_VA = 0x401F77AC             # 6 rows of {long, short, 0}
NAME_ROW = 12
NAME_SITES = (                          # (bound site, base instruction, column)
    (0x400DC3A4, 0x400DC3B4, "41f9", 0),     # long: moveq #5 ; lea 0x401f77ac,%a0
    (0x400DC3CA, 0x400DC3DC, "0680", 4),     # short: moveq #5 ; addil #0x401f77b0,%d0
)

LOAD_BOUND = 0x400DD2BC                 # moveb #7,%d2: filter types -1..5 kept
LOAD_BOUND_STOCK = bytes.fromhex("143c0007")

SLOT_SITE = 0x400DC096                  # moveq #5,%d2 ; cmp.l %a1,%d2 ; bcs.s 0x400dc05e
SLOT_STOCK = bytes.fromhex("7405b48965c2")
SLOT_ZERO = 0x400DC05E                  # clrl %d0 ; bra exit -- "no parameter"
SLOT_ROW = 0x400DC09C                   # lea %a1@(0,%a1:l:2),%a1 -- the row's lookup

GRAPH_SITE = 0x4006ECA0                 # moveq #5,%d0 ; cmp.l %d4,%d0 ; bcs.w 0x4006ed3a
GRAPH_STOCK = bytes.fromhex("7005b08465000094")
GRAPH_CASES = 0x4006ECA8                # the six-case jump on d4, the filter type
GRAPH_NONE = 0x4006ED3A                 # past the cases: no response curve

OVER_SITE = 0x400C24B0                  # moveq #5,%d1 ; move.l %sp@(4),%d0
OVER_STOCK = bytes.fromhex("7205202f0004")

# Read, never written: what the edits rely on.
GUARDS = (
    (0x4004DAE2, "4feffff4", "the FLTR list builder 0x4004dae2"),
    (0x4004DB10, "42b9405ccfa4", "... builds its vector once, into 0x405ccfa4"),
    (0x4005B4DE, "4eb94004dae2", "the FLTR type list asks the builder"),
    (0x4005A904, "4eb9400dc3a4", "... and names each row with the long-name accessor"),
    (0x400DC3A6, "202f0004b2806514", "long names: d0 = filter; unsigned bound in d1"),
    (0x400DC3CC, "202f0004b2806514", "short names: the same"),
    (0x400DD2B8, "b48152c1", "LOAD: cmp.l %d1,%d2 ; shi %d1, the filter's bound test"),
    (0x400DD2C0, "c0811540", "... and keeps the type or makes it 0"),
    (0x400DD2DA, "154000df", "... into sound+0xDF"),
    (0x400DC08A, "41f942c64d18", "slot_to_id's machine-slot table (resolved before)"),
    (0x400DC0A4, "41f942c64cd0", "slot_to_id's filter-slot table, rows of three"),
    (0x400DC05E, "4280604a", "slot_to_id: clrl %d0 ; bra exit"),
    (0x400DC09C, "43f19a00", "slot_to_id: the row's lookup"),
    (0x400C24B6, "b2806510", "the FLTR descriptor accessor: compares, then branches"),
    (0x4004CDE6, "114200df", "the filter setter writes sound+0xDF with no bound"),
    (0x40027586, "10280d8d", "the frame builder takes each track's filter from its mirror"),
    (0x40027590, "374000b2", "... and writes it at frame offset 178 + 2t"),
    (0x400DBEDA, "5b80b280", "filter records are pages 5.. (type + 5)"),
    (0x4006EC9E, "2800", "the FLTR page's curve: d4 = getFilterType(track)"),
    (0x4006ECA8, "303b4a0848c04efb0802", "... then a six-case jump on d4"),
    (0x4006ED90, "7801", "... d4 is next written, not read, past the cases"),
)

def _is_new(reg: str, scratch: str, done: str) -> str:
    """GNU as: branch to `done` unless REG is one of NEW_FILTERS (scratch is clobbered);
    falls through to the next line when it is."""
    out = []
    for k, t in enumerate(NEW_FILTERS):
        out.append(f"    moveq   #{t},{scratch}")
        out.append(f"    cmp.l   {reg},{scratch}")
        out.append(f"    beq.s   0f" if k < len(NEW_FILTERS) - 1 else f"    bne.s   {done}")
    out.append("0:")
    return "\n".join(out)


SOURCE = f"""
| param_set_slot_to_id, from {SLOT_SITE:#010x} by jmp: a1 is the filter type, d1 and
| d2 are free (d2 was saved at entry and is restored at the exit; d1 is not read on
| the row path). Filters {NEW_FILTERS} read Multi-Mode's row ({CLONE}); then the stock
| bound, 0..5, and the stock paths.
ping_slot:
{_is_new("%a1", "%d2", "1f")}
    suba.l  %a1,%a1
1:  moveq   #5,%d2
    cmp.l   %a1,%d2
    bcs.s   2f
    jmp     {SLOT_ROW:#010x}
2:  jmp     {SLOT_ZERO:#010x}

| The FLTR page descriptor accessor {OVER_SITE:#010x}(filter): its first two
| instructions, `moveq #5,%d1 ; move.l %sp@(4),%d0`, now `jsr` here, with filters
| {NEW_FILTERS} read as {CLONE}. The jsr's return address is on top, so the argument
| is at 8. The accessor compares next.
ping_over:
    move.l  %sp@(8),%d0
{_is_new("%d0", "%d1", "1f")}
    moveq   #{CLONE},%d0
1:  moveq   #5,%d1
    rts

| The FLTR page's response curve, from {GRAPH_SITE:#010x} by jmp (both of its entries,
| the fall-through and `bcs.s` from 0x4006ec84, land on the jmp itself): d4 is the
| filter type and the cases read it only as the jump's index. Filters {NEW_FILTERS} draw
| Multi-Mode's curve, so FREQ and RESO's places show where they are; then the stock bound.
ping_graph:
{_is_new("%d4", "%d0", "1f")}
    moveq   #{CLONE},%d4
1:  moveq   #5,%d0
    cmp.l   %d4,%d0
    bcs.s   2f
    jmp     {GRAPH_CASES:#010x}
2:  jmp     {GRAPH_NONE:#010x}
ping_code_end:

    .align 2
ping_list:
{chr(10).join(f"    .long {t}" for t in LIST_NEW)}
ping_list_end:
{chr(10).join(f'name_long_{t}:{chr(10)}    .asciz  "{NAMES[t][0]}"{chr(10)}name_short_{t}:{chr(10)}    .asciz  "{NAMES[t][1]}"' for t in NEW_FILTERS)}
    .align 2
ping_names:
"""
LABELS = (("ping_slot", "ping_over", "ping_graph", "ping_code_end", "ping_list", "ping_list_end")
          + tuple(f"name_{c}_{t}" for t in NEW_FILTERS for c in ("long", "short")) + ("ping_names",))


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


def compose(content: bytearray, edit, assemble) -> dict:
    """Make PING's edits on CONTENT (the MAIN OS being composed) through
    EDIT(va, new, what, stock_bytes), ASSEMBLE(source, base=...) -> bytes.
    -> {"layout": {...}, "chunk": {"load", "code"}}."""
    for va, want, why in GUARDS:
        _need(content, va, bytes.fromhex(want), why)
    _need(content, LIST_STOCK_VA, b"".join(_long(t) for t in LIST_STOCK), "the FLTR type list")

    table = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in LABELS) + "\n"
    blob = assemble(SOURCE + table, base=LOAD)
    head = blob[:-4 * len(LABELS)]
    layout = dict(zip(LABELS, struct.unpack(f">{len(LABELS)}I", blob[-4 * len(LABELS):])))
    if layout["ping_names"] != LOAD + len(head):
        raise ComposeError("the name table is not at the end of the assembly")
    rows = bytearray(_read(content, NAMES_STOCK_VA, NAME_ROW * 6))
    for r in range(6):
        if _read(content, NAMES_STOCK_VA + NAME_ROW * r + 8, 4) != bytes(4):
            raise ComposeError(f"filter name row {r}: its third column is not 0")
    for t in NEW_FILTERS:
        rows += _long(layout[f"name_long_{t}"]) + _long(layout[f"name_short_{t}"]) + bytes(4)
    code = head + bytes(rows)
    if LOAD + len(code) > END:
        raise ComposeError(f"PING's chunk ends past {END:#010x}")
    layout["ping_end"] = LOAD + len(code)

    # 1. the list
    n = len(LIST_NEW)
    edit(LIST_ALLOC, bytes.fromhex("4878") + struct.pack(">H", 4 * n),
         f"FLTR type list: storage for {n} longs", bytes.fromhex("48780018"))
    edit(LIST_END, bytes.fromhex("4879") + _long(layout["ping_list_end"]),
         "FLTR type list: the copy's end", bytes.fromhex("4879") + _long(LIST_STOCK_VA + 24))
    edit(LIST_CAP, bytes.fromhex("41e8") + struct.pack(">H", 4 * n),
         f"FLTR type list: the vector's capacity, {n} longs", bytes.fromhex("41e80018"))
    edit(LIST_BEGIN, bytes.fromhex("4879") + _long(layout["ping_list"]),
         "FLTR type list: the copy's start, with Ping last", bytes.fromhex("4879") + _long(LIST_STOCK_VA))

    # 2. the names
    for bound, base, op, col in NAME_SITES:
        _need(content, base, bytes.fromhex(op), "the name accessor's base instruction")
        edit(bound, bytes([0x72, NEW_FILTERS[-1]]),
             f"filter name column {col // 4}: bound 5 -> {NEW_FILTERS[-1]}", bytes.fromhex("7205"))
        edit(base + 2, _long(layout["ping_names"] + col),
             f"filter name column {col // 4}: the seven-row table", _long(NAMES_STOCK_VA + col))

    # 3. the stored-sound LOAD keeps filter 6
    edit(LOAD_BOUND, bytes([0x14, 0x3C, 0, NEW_FILTERS[-1] + 2]),
         f"stored-sound LOAD: filter types -1..{NEW_FILTERS[-1]} are kept (stock keeps -1..5; "
         "anything else loads as Multi-Mode)", LOAD_BOUND_STOCK)

    # 4. slot_to_id and the FLTR page descriptor: 6 reads Multi-Mode's
    edit(SLOT_SITE, bytes.fromhex("4ef9") + _long(layout["ping_slot"]),
         "param_set_slot_to_id: filters 6 and 7 resolve as Multi-Mode", SLOT_STOCK)
    edit(OVER_SITE, bytes.fromhex("4eb9") + _long(layout["ping_over"]),
         "the FLTR page descriptor: filters 6 and 7 read Multi-Mode's", OVER_STOCK)

    edit(GRAPH_SITE, bytes.fromhex("4ef9") + _long(layout["ping_graph"]) + bytes.fromhex("4e71"),
         "the FLTR page's response curve: filters 6 and 7 draw Multi-Mode's", GRAPH_STOCK)

    return {"layout": layout, "chunk": {"load": LOAD, "code": bytes(code)}}
