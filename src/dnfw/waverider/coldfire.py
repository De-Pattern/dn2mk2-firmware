"""Waverider on the ColdFire: machine type 5, offered by MACHINE SEL, a WaveTone clone
everywhere else (`docs/waverider-feasibility.md`, "Milestone 5").

The DSP renders type 5 with our own code (section 7, `dnfw.waverider.dsp`). The
ColdFire's job is smaller and is only this:

1. **offer it** -- MACHINE SEL lists the machine types from a static list
   (`{0, 2, 1, 3, 4}` at `0x401ddd58`, copied into a `std::vector` by
   `0x4004d8b6`) and draws a divider wherever the group `0x40059274(type)`
   changes. The list gains a 5 before MIDI, and 5 (with 6, reserved for
   a second sample machine) is a group of its own, so it reads synths | WAVERIDER | MIDI;
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

from . import pages
from dataclasses import dataclass

BASE = 0x40000400
NEW_TYPE = 5
from ..mnm import machines as _mnm           # noqa: E402
# PERC; the Monomachine's machines (docs/mnm.md: 6, 7, then 14.. after the sample machines);
# the Digitakt II's sample machines (docs/sampler.md, 8..13): all WaveTone clones
from ..sampler import machines as _smpm         # noqa: E402
NEW_TYPES = tuple(range(5, max(13, *_mnm.TYPES, _smpm.BOUNCE_TYPE) + 1))   # v0.44: to 17, BOUNCE
CLONE = 1                               # WaveTone
LONG_NAME, SHORT_NAME = "Perc", "PRC"           # v0.11: PERC in Waverider's place
MACHINE_NAMES = {5: ("Perc", "PRC"),
                 8: ("Oneshot", "ONE"), 9: ("Werp", "WRP"), 10: ("Stretch", "STR"),
                 11: ("Repitch", "RPT"), 12: ("Grid", "GRD"), 13: ("Slice", "SLC"),
                 _smpm.BOUNCE_TYPE: ("Bounce", "BNC"),       # v0.44: a section of its own, after the sample machines
                 **{t: _mnm.LIST_NAMES[n] for t, n in zip(_mnm.TYPES, _mnm.NAMES)}}   # v0.26
if set(MACHINE_NAMES) != set(NEW_TYPES):
    raise ImportError(f"machine types {sorted(set(NEW_TYPES) - set(MACHINE_NAMES))} have no machine")
# RESONATOR (2026-10-18): the shims, the name table, the attribute rows and the list
# outgrew the three caves W5 used, so all of it is a platform CODE chunk in RAM, after
# what was PING's (0x4670F000..; v0.45: PING removed) and below the platform runtime; the caves are
# left as stock had them.
MCHUNK = 0x4670F800
PAGES_END = 0x4670F000                  # the pages assembly's room ends here (PING's chunk until v0.44)
MCHUNK_END = 0x46710000

# -- 1. the MACHINE SEL list -------------------------------------------------------------
LIST_STOCK_VA = 0x401DDD58             # {0, 2, 1, 3, 4}, five longs
LIST_STOCK = (0, 2, 1, 3, 4)
# PERC, RESONATOR, CZ after Swarmer; then the Digitakt II's sample machines in its own
# order (v0.15: all five; v0.13 offered ONESHOT and GRID); then MIDI
LIST_NEW = (0, 2, 1, 3, 5, *_mnm.TYPES, 8, 9, 10, 11, 13, 12, *((_smpm.BOUNCE_TYPE,) if _smpm.BOUNCE_LISTED else ()), 4)   # v0.19: SLICE before GRID, the DT2's order; v0.44 BOUNCE after them (group 3: its own divider)
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
# (W5 to v0.5: DATA_CAVE 0x4028e958, CODE_CAVE 0x4029037c, NAME_CAVE 0x4028db24; now unused)

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
    (0x4005B6C2, "4eb94003134e", "MACHINE SEL's current machine (view +412) is 0x4003134e"),
    # v0.35, colsw: the column switch, the row vectors and the follow it relies on
    (0x4005BA9C, "254001a8", "MACHINE SEL LEFT / RIGHT writes the column (+424)"),
    (0x4005BAB6, "256a01a001a4", "... and the cursor (+420) from the filter type (+416)"),
    (0x4005B162, "2f0a2f02206f000c202801a8", "the type under the cursor(view) saves a2, d2; reads +424"),
    (0x4005A92C, "206f0004202801a8", "rows in the column(view)"),
    (0x4005A956, "2f0a2f02246f000c", "the scroll-follow(view) saves a2 and d2"),
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


SAMPLE_GROUP = 3                        # our synth machines: PERC (5), the Monomachine's (6, 7, 14..)
SAMPLER_GROUP = 4                       # the sample machines (8..13), a section of their own
SAMPLER_FIRST, SAMPLER_LAST = 8, 13
TYPES_LAST = NEW_TYPES[-1]              # every type 5..TYPES_LAST is a WaveTone clone

# MACHINE SEL (and the second list at 0x40059cdc) inserts a divider row -- an
# unlabelled row of value -1, drawn as dots -- wherever this group changes. The
# groups are only compared for equality, so a third one is just another section.
GROUP_SOURCE = f"""
| group(type), rewritten in place at {GROUP_FN:#010x}: the synths 0..3 -> 1, MIDI (4)
| -> 2, the sample machines {SAMPLER_FIRST}..{SAMPLER_LAST} -> {SAMPLER_GROUP}, every other type from
| {NEW_TYPE} on (PERC, the Monomachine's: 5..7, 14..) -> {SAMPLE_GROUP}, a negative one 0 (stock: 0..3 ->
| 1, 4 -> 2, else 0). d0 holds the answer to each test before it is made, and every
| branch follows the instruction that set its flags: `moveq` clears C, so it never sits
| between a `subq` and its `bcs` (the first version of this did, and put the synths in
| group 0 -- the emulator caught it). Borrows are unsigned, after the sign test. Callers
| read the low byte. 34 bytes, the stock function's own size (v0.26: 5..7 and 14.. one
| group, so the Monomachine's machines after the sample machines in type order still sit
| together in the list).
    moveq   #0,%d0
    move.l  %sp@(4),%d1
    blt.s   9f
    moveq   #1,%d0
    subq.l  #4,%d1
    bcs.s   9f
    moveq   #2,%d0
    tst.l   %d1
    beq.s   9f
    moveq   #{SAMPLER_GROUP},%d0
    subq.l  #{SAMPLER_FIRST - 4},%d1
    bcs.s   8f
    subq.l  #{SAMPLER_LAST - SAMPLER_FIRST + 1},%d1
    bcs.s   9f
8:  moveq   #{SAMPLE_GROUP},%d0
9:  rts
"""


def group_function(assemble) -> bytes:
    code = assemble(GROUP_SOURCE, base=GROUP_FN)
    if len(code) > len(GROUP_STOCK):
        raise ComposeError(f"the group function grew: {len(code)} > {len(GROUP_STOCK)}")
    return code + bytes(len(GROUP_STOCK) - len(code))


TRACK_TYPE_EXIT = 0x4004B81E            # getMachineType(track): its common exit

SHIMS = f"""
| param_set_slot_to_id, entered from {SLOT_HOOK:#010x}: the two loads it displaced,
| then types {NEW_TYPE}..{TYPES_LAST} -> {CLONE} (WaveTone), then back. d2 is saved at entry and
| overwritten before it is read ({SLOT_TO_ID + 0x16:#010x}).
slot_shim:
    move.l  %sp@(12),%d0
    movea.l %sp@(16),%a1
    cmpi.l  #{NEW_TYPE},%d0
    blt.s   1f
    cmpi.l  #{TYPES_LAST},%d0
    bgt.s   1f
    moveq   #{CLONE},%d0
1:  jmp     {SLOT_RESUME:#010x}

| A one-argument per-machine UI accessor whose first two instructions were
| `moveq #4,%d1 ; move.l %sp@(4),%d0`, now `jsr` here: the same two loads, with
| types {NEW_TYPE}..{TYPES_LAST} read as {CLONE}. The jsr's return address sits on top, so the
| caller's argument is at 8. The accessor goes on to `cmp.l %d0,%d1`.
canon_arg:
    move.l  %sp@(8),%d0
    cmpi.l  #{NEW_TYPE},%d0
    blt.s   1f
    cmpi.l  #{TYPES_LAST},%d0
    bgt.s   1f
    moveq   #{CLONE},%d0
1:  moveq   #4,%d1
    rts

| The page accessor 0x400c24ee(type, page): its `move.l %sp@(8),%d1 ; move.l
| %sp@(12),%d0` (after its own push of d2), now `jsr` here, with types {NEW_TYPE}..{TYPES_LAST}
| read as {CLONE}. d2 holds its bound 4 and is left alone; it compares next.
canon_page:
    move.l  %sp@(12),%d1
    move.l  %sp@(16),%d0
    cmpi.l  #{NEW_TYPE},%d1
    blt.s   1f
    cmpi.l  #{TYPES_LAST},%d1
    bgt.s   1f
    moveq   #{CLONE},%d1
1:  rts

| getMachineType(track) 0x4004b7f2, from its read of sound+0xDE: the UI's view of
| a track's machine. Types {NEW_TYPE}..{TYPES_LAST} are reported as {CLONE}, so the ~60 places the UI
| asks behave as they do for WaveTone. Back to its common exit.
canon_track:
    mvs.b   %a0@(222),%d0
    cmpi.l  #{NEW_TYPE},%d0
    blt.s   1f
    cmpi.l  #{TYPES_LAST},%d0
    bgt.s   1f
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

| v0.35: MACHINE SEL's LEFT / RIGHT (0x4005ba9c..0x4005babc) switches the column (+424),
| sets the cursor (+420) from the current type (+412 / +416, as if types were rows) and
| redraws (jsr 0x4011c7ba) without the scroll-follow 0x4005a956 that UP / DOWN run. Stock's
| lists fit the screen, so the top row (+428) was always 0; ours scrolls, so RIGHT from a
| machine low in the SRC list kept a top row past the FLTR list's end: an empty FLTR
| column (flupperich6l, v0.33). Here, from the redraw's jsr: the cursor on the first row
| whose type (0x4005b162(view): the row under the cursor, through the row object) is the
| column's current one, over the column's rows (0x4005a92c(view)); stock's cursor kept if
| none is; the follow; then the redraw. The YES paths share the site: a no-op there.
colsw:
    lea     %sp@(-20),%sp
    movem.l %d2-%d5/%a2,%sp@
    movea.l %sp@(24),%a2
    move.l  %a2@(420),%d5
    move.l  %a2@(424),%d0
    beq.s   3f
    moveq   #1,%d1
    cmp.l   %d0,%d1
    bne.s   5f
    move.l  %a2@(416),%d2
    bra.s   4f
3:  move.l  %a2@(412),%d2
4:  move.l  %a2,%sp@-
    jsr     0x4005a92c
    addq.l  #4,%sp
    move.l  %d0,%d4
    moveq   #0,%d3
1:  cmp.l   %d4,%d3
    bge.s   7f
    move.l  %d3,%a2@(420)
    move.l  %a2,%sp@-
    jsr     0x4005b162
    addq.l  #4,%sp
    cmp.l   %d0,%d2
    beq.s   5f
    addq.l  #1,%d3
    bra.s   1b
7:  move.l  %d5,%a2@(420)
5:  move.l  %a2,%sp@-
    jsr     0x4005a956
    addq.l  #4,%sp
    movem.l %sp@,%d2-%d5/%a2
    lea     %sp@(20),%sp
    jmp     0x4011c7ba
"""
SHIM_LABELS = ("slot_shim", "canon_arg", "canon_page", "canon_track", "raw_track", "colsw")

# -- 8. the sound's "is this parameter mine?" (vtable +0x50, 0x40036bfa) --------------------
# For a machine parameter it answers `sound+0xDE == record[param].page`. WaveTone's
# records are page 1, so a Waverider sound would disown its own machine parameters
# (the p-lock, LFO-destination and CC paths ask this). The read becomes a jsr to a
# shim that reads the type as WaveTone's and replays the push it displaced.
VALID_SITE = 0x40036C24                 # mvs.b %a0@(222),%d3 ; move.l %d2,-(%sp)
VALID_STOCK = bytes.fromhex("772800de2f02")
VALID_NEXT = bytes.fromhex("4eb9400dbce8")   # jsr record page(param)
SHIMS2 = f"""
| from {VALID_SITE:#010x} by jsr: the type byte into d3, {NEW_TYPE}..{TYPES_LAST} read as {CLONE}, then
| the displaced `move.l %d2,-(%sp)` under the return address. a1 is free: the jsr
| that follows (0x400dbce8) is a scratch-register call.
canon_valid:
    mvs.b   %a0@(222),%d3
    cmpi.l  #{NEW_TYPE},%d3
    blt.s   1f
    cmpi.l  #{TYPES_LAST},%d3
    bgt.s   1f
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
    # v0.22: TRK + CLEAR (0x40071e80, "CLEAR TRK %d PRESET") re-initialises the sound as
    # the machine it reads here (0x4004d5f0 -> 0x400e7d4c: the type into +0xde, every slot's
    # record through param_set_slot_to_id, which reads ours as WaveTone's); canonical, a
    # cleared PERC, sample or RESONATOR track became WaveTone (the owner's v0.21 report)
    (0x40071EB6, "4eb9", "TRK + CLEAR: the machine the cleared preset is made for"),
)

# -- 7b. getMachineType(model, track) 0x4003134e: the real type -------------------------
# The model-level question -- "what machine does track t have?" -- is 0x4003134e,
# which finds the track and ends in a tail `jmp 0x4004b7f2`. A `jmp`, not a `jsr`,
# so the identity search above never saw it, and the answer came back canonical:
# a Waverider track read as WaveTone to every one of its twelve callers. Four of
# them are MACHINE SEL: the machine it marks and puts the cursor on (view +412,
# set at open, after every commit and on every model change). So YES on WAVERIDER
# wrote 5, and the view at once re-read 1 and marked WAVETONE; a second YES found
# 1 != 5 and committed 5 again; reopening marked WAVETONE (hardware, 2026-09-27;
# `out/fix-select/`, emulator). Three more re-commit the type they read: the track
# swap `0x40041bca`, and the two "restore the old machine" paths `0x400a7f92` /
# `0x400b15e8` -- each would turn a Waverider track into a WaveTone one for real.
# The rest ask "is it MIDI?" (compare 4), or hand the type to the SYN overview and
# page accessors (0x400c248e, 0x400c24ee), which read 5 as WaveTone's rows already.
# So the tail jump goes to raw_track, and all twelve see 5.
MODEL_TRACK_TYPE_JMP = 0x40031394      # jmp 0x4004b7f2, the tail of 0x4003134e

# -- 6. the per-machine UI tables (0x42432ad4, 0x42432b24): the SYN pages ---------------
# `pages(type)`, `page(type, n)` and `overview(type)` read five-row tables built
# at boot and fall back to an empty page above 4 -- which is what a type-5 track's
# SYN page showed in the emulator before this. Type 5 reads WaveTone's rows.
CANON_ARG_SITES = (
    (0x400C248E, "overview descriptor(type): 0x42432b24 + 44 type"),
)
# Milestone 7 (dnfw.waverider.pages): the page count and the page reader answer a
# Waverider track with its own two pages, and the SYN page's label fetch gives it
# its own labels. Everything else behaves as the M5 shims did.
COUNT_SITE = 0x400C24D2                 # SYN page count(type): 0x42432ad4[type].count
LABEL_SITE = 0x40064622                 # the SYN page's jsr getShortName(this, id)
LABEL_STOCK = bytes.fromhex("4eb9400372da")
CANON_ARG_STOCK = bytes.fromhex("7204202f0004")
PAGE_SITE = 0x400C24F2                  # 0x400c24ee: after `move.l %d2,-(%sp) ; moveq #4,%d2`
PAGE_STOCK = bytes.fromhex("222f0008202f000c")
# the SYN page draw (0x40018118), after the grid of a type-1 page: page id 7 (WaveTone's
# OSC page) goes on to draw WaveTone's two oscillator icons at B and F from WAV1/TBL1
# and WAV2/TBL2. A Waverider track is type 1 to it: wr_icons takes the page id test.
ICON_SITE = 0x4001821E                  # moveq #7,%d0 ; cmp.l %d3,%d0 ; bne.w 0x400182c6
ICON_STOCK = bytes.fromhex("7007b083660000a2")
# the same draw, a type-1 page other than page id 9: push the canvas and the view, call
# the grid 0x40017428 (a pc-relative jsr), pop them. wr_grid draws Waverider's own page.
GRID_SITE = 0x40018214
GRID_STOCK = bytes.fromhex("2f022f0a4ebaf20e508f")
# the UI task's loop asks its screen `isDirty()` (0x4011d2f4, the byte at screen +32) once
# a pass, and redraws every view on it when set (0x4011d32a). The stock UI sets it on a
# change: at rest a shown page redraws once a second, and a modulation never redraws it
# (instrument, modview1). wr_poll asks the same question, first setting the byte through
# the stock 0x4011d2fe while a modulation marker on Waverider's page would move.
# v0.14, the sample link (csrc/sampler, docs/sampler.md): the SysEx router's hook (the USB
# probe's site, docs/usbprobe.md). v0.14..v0.19 also hooked the frame builder (0x400276a2)
# to put packets in the frame's words 2650..2681; those are the DSP's per-track routing,
# so v0.20 leaves the frame builder stock (LINK_FEED_SITE is kept for the test that says so)
LINK_RX_SITE = 0x4012169A               # lea 0x40207ae6,%a3: F0 00 20 3C, before the compare
LINK_RX_STOCK = bytes.fromhex("47f940207ae6")
LINK_FEED_SITE = 0x400276A2             # lea 0x40006c4a,%a2: the frame is built
LINK_FEED_STOCK = bytes.fromhex("45f940006c4a")
KEY_SLOT = 0x401D49A8                    # the parameter page view's key handler, in its vtable (v0.15)
KEY_STOCK = 0x40016480                   # stock's: code 2 cycles the pages, the rest to its base
QUANT_SITE = 0x40037BE6                  # the setter's write: movea.l %d0,%a0 ; move.w %d3,14(%a0,%d2.l*2)
QUANT_STOCK = bytes.fromhex("204031832a14")
TDM_SITE = 0x40026098                    # the SSI ISR, its transmit fill done: move.l %fp,%d2 ; addi.l #-72,%d2 (v0.16)
TDM_STOCK = bytes.fromhex("240e0682ffffffb8")
# DIRECT JUMP (csrc/jump, docs/jump.md): the PTN view's single cue, the sequencer tick ISR's
# queue test, arming, switch and per-track positions, and the PTN view's key handler
JUMP_CUE_SITE = 0x400FA1DA               # jsr 0x400d93f0: the PTN view's one-pattern cue (0x400fa11e)
JUMP_CUE_STOCK = bytes.fromhex("4eb9400d93f0")
JUMP_ISR_SITES = (                       # (site, stock bytes, its symbol, the instruction)
    (0x400DA406, "123942c5a91e", "jmp_tick", "move.b 0x42c5a91e,%d1: the tick's queue test (tick 2)"),
    (0x400DA45A, "737942c5aab4", "jmp_arm", "mvs.w 0x42c5aab4,%d1: the change-length test before arming"),
    (0x400DA6E6, "43f942c5a9c4", "jmp_switch", "lea 0x42c5a9c4,%a1: the switch's start step"),
    (0x400DA8CC, "4879401f6b25", "jmp_tracks", "pea 0x401f6b25: the per-track positions' end"),
)
JUMP_KEY_SLOT = 0x402008CC               # the PTN view's key handler, in its vtable
JUMP_KEY_STOCK = 0x400FA6BE
JUMP_GUARDS = (                          # what the shims jump back to and rely on
    (0x400DA40C, "7c027b01bc85", "jmp_tick resumes: moveq #2,%d6 ; mvs.b %d1,%d5 ; cmp.l %d5,%d6"),
    (0x400DA416, "227942c5aac0", "the queue's path: movea.l 0x42c5aac0,%a1"),
    (0x400DA460, "7e01", "jmp_arm's stock way resumes: moveq #1,%d7"),
    (0x400DA4D2, "23c042c5a9a4", "stock's arming: move.l %d0,0x42c5a9a4 (the next pattern)"),
    (0x400DA6EC, "4df942c5a9c8", "jmp_switch resumes: lea 0x42c5a9c8,%fp"),
    (0x400DA6F8, "23d142c5a9bc", "... then 0x42c5a9bc = (a1): the start step"),
    (0x400DA7CA, "1e350800", "the per-track positions read the mode from a5"),
    (0x400DA81C, "264d", "... and the tracks from a5 (movea.l %a5,%a3)"),
    (0x400DA904, "4bf942c5a9ea", "... until a5 is set again (lea 0x42c5a9ea,%a5)"),
    (0x400DA8D2, "2f394028c1fc", "jmp_tracks resumes: move.l 0x4028c1fc,-(%sp)"),
    (0x400FA1E0, "4fef001c", "the cue's caller pops its arguments"),
    (0x400DA902, "42024bf942c5a9ea", "v0.40: jmp_arm's forced tick ends as stock's ticks past 2 (clr.b %d2 ; lea 0x42c5a9ea,%a5)"),
    (0x400DA41C, "42b942c5aaac", "v0.40: stock's tick 2 clears the arming (why jmp_tick never takes tick 1)"),
    (0x400DA52A, "4a01660003d4", "v0.40: ... and its ticks past 2 go to 0x400da902 (tst.b %d1 ; bne.w)"),
)
# v0.40, parameter slides' SLD/SLEN drawn as stock draws RTRG and LEN (csrc/slides/slide.c,
# sl_draw_sld / sl_draw_slen): the stock routines called, and the cell routine's and LEN
# widget's own calls whose arguments they copy
SLIDE_DRAW_GUARDS = (
    (0x40036560, "4fefffec48d7007c", "slides: the widget routine (id, value, ..., canvas, x, y)"),
    (0x400BC414, "4feffff4202f0014", "slides: RTRG's toggle widget (its sheet's frame value >> 8)"),
    (0x40115668, "4e56ff44", "slides: the cell's label text routine"),
    (0x40114842, "4fefffd4", "slides: the fill / invert routine (the p-lock look)"),
    (0x40115E6C, "206f0004", "slides: the box font's set-up"),
    (0x40115CE8, "206f0004", "slides: ... and its release"),
    (0x40114626, "4fefffd4", "slides: the box's rectangle"),
    (0x400CC2CE, "41f9402a0f48487940293c64", "slides: LEN's box: its table and font 0x40293c64"),
    (0x400CC2EE, "2f04487940219c2d48780002486b0006486a00092f022f034eb94011545c",
     "slides: LEN's box text: centred (2) at (x + 9, y + 6)"),
    (0x40064630, "487940219c2d4879402170b942a7487800012f0a486b00094879402917602f03",
     "slides: the cell's label: font 0x40291760 at (x + 9, y), 'XXXX' wide"),
)
# v0.22, the RECORDER as a screen of its own (csrc/sampler/rec.c): the UI loop's queue
# receive (every key and knob item passes it first), its draw of the screen (the recorder
# over it), and the main key handler's FUNC + VOICE (stock: unison on/off) opening it
UI_POP_SITE = 0x4002F17E                # jsr 0x40001928: the UI queue's receive, in the UI loop
UI_POP_STOCK = bytes.fromhex("4eb940001928")
SCREEN_SITE = 0x4002E4CA                # jsr 0x4011d32a(screen, canvas): the views drawn
SCREEN_STOCK = bytes.fromhex("4eb94011d32a")
# v0.45: the trig LEDs show recorder trigs while the BOUNCE REC panel is up (csrc/sampler/rec.c
# bn_led_walk): the LED compose's walk of the views (0x4002c854's jsr 0x4011d3b2(screen))
LED_SITE = 0x4002C880
LED_STOCK = bytes.fromhex("4eb94011d3b2")
REC_COMBO_SITE = 0x4005F008             # the VOICE case's FUNC branch: push, jsr 0x40046bfe (unison)
REC_COMBO_STOCK = bytes.fromhex("2f2a00a44eb940046bfe")
REC_COMBO_EXIT = 0x4005FC50             # the handler's common exit (the key offered to the base)
LFO_MASK_LEA = 0x40039570               # the LFO destination list's lea 0x400dc30e,%a2 (v0.22)
LFO_MASK_STOCK = 0x400DC30E
KEYNOTES_SITE = 0x40058BE8              # v0.23: KeyboardView's jsr 0x40034460(kbd, &notes, key)
KEYNOTES_STOCK = bytes.fromhex("4eb940034460")
MACHSEL_COLSW_SITE = 0x4005BABE         # v0.35: MACHINE SEL's redraw after LEFT / RIGHT (jsr 0x4011c7ba)
MACHSEL_COLSW_STOCK = bytes.fromhex("4eb94011c7ba")
MACHSEL_COMMIT_SITE = 0x4005BBA0        # v0.30: MACHINE SEL's jsr 0x40031880 (commit(model, track, type, 1, 1))
MACHSEL_COMMIT_STOCK = bytes.fromhex("4eb940031880")
MODAPPLY_SITE = 0x40027196              # v0.25: the per-frame driver's jsr 0x400db22c (apply modulation)
MODAPPLY_STOCK = bytes.fromhex("4eb9400db22c")
POLL_SITE = 0x4002E464                  # jsr 0x4011d2f4 (isDirty), its argument the screen
# v0.38: per-project pools (csrc/sampler/pools.c, hooks.S, docs/project-pools.md): the OS's
# project LOAD 0x40042E6E (its entry, its success where it sets the slot, its exit) and NEW
# 0x400428C0 (where it sets the slot), each a jmp to a cave that replays what it replaced
PJ_BEGIN_SITE = 0x40042E6E              # lea -36(%sp),%sp ; movem.l %d2-%d5/%a2,(%sp)
PJ_BEGIN_STOCK = bytes.fromhex("4fefffdc48d7043c")
PJ_LOADED_SITE = 0x40042ED2             # move.l %d5,-(%sp) ; move.l %d3,-(%sp) ; jsr 0x4003eb62
PJ_LOADED_STOCK = bytes.fromhex("2f052f034ebabc8a")
PJ_END_SITE = 0x40042EE6                # move.b %d4,%d0 ; movem.l (%sp),%d2-%d5/%a2 ; lea 36(%sp),%sp
PJ_END_STOCK = bytes.fromhex("10044cd7043c4fef0024")
PJ_NEW_SITE = 0x40042AF0                # move.l 12(%fp),(%sp) ; move.l %a2,-(%sp) ; jsr 0x4003eb62
PJ_NEW_STOCK = bytes.fromhex("2eae000c2f0a4ebac06a")
POLL_STOCK = bytes.fromhex("4eb94011d2f4")


def _cave_free(content: bytes, cave: tuple[int, int]) -> None:
    at, cap = cave
    if any(_read(content, at - 4, cap + 8)):
        raise ComposeError(f"the cave at {at:#010x} (+{cap}) is not free")


def compose(stock: bytes, assemble, compile_c) -> dict:
    """-> {"content", "edits", "layout", "chunk"}. ASSEMBLE(source, base=...) -> bytes;
    COMPILE_C(header, base=...) -> (image, symbols, bss): csrc/waverider/page.c linked at
    BASE with `header` as its generated `wr_gen.h`."""
    content = bytearray(stock)
    for va, want, why in GUARDS:
        _need(content, va, bytes.fromhex(want), why)
    edits: list[Edit] = []

    # Milestone 7: Waverider's pages, as one platform CODE chunk in RAM (pages.LOAD)
    # the C page renderer first (the assembly calls it), at C_LOAD
    from .. import slides as SL
    from .. import modversion                   # v0.39: the mod's version (VERSION), shown at the browser's top
    cimage, csyms, cbss = compile_c(pages.c_header() + SL.c_header(stock)
                                    + modversion.c_define(),
                                     base=pages.C_LOAD)
    if cbss:
        raise ComposeError(f"the page renderer has {cbss} bytes of BSS; nothing zeroes it")
    if len(cimage) > pages.C_SPAN:
        raise ComposeError(f"the page renderer ({len(cimage)} B) is larger than its {pages.C_SPAN:#x}")
    ptable = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in pages.LABELS_OUT) + "\n"
    pblob = assemble(pages.source(csyms["wr_page_draw"], csyms["wr_cell"]) + ptable, base=pages.LOAD)
    asm = pblob[:-4 * len(pages.LABELS_OUT)]
    if pages.LOAD + len(asm) > PAGES_END:
        raise ComposeError(f"the pages assembly ({len(asm)} B) runs past {PAGES_END:#010x}")
    chunk = asm
    playout = dict(zip(pages.LABELS_OUT, struct.unpack(f">{len(pages.LABELS_OUT)}I",
                                                       pblob[-4 * len(pages.LABELS_OUT):])))

    def edit(va: int, new: bytes, what: str, stock_bytes: bytes | None = None) -> None:
        old = _read(content, va, len(new)) if stock_bytes is None else stock_bytes
        _need(content, va, old, what)
        content[va - BASE:va - BASE + len(new)] = new
        edits.append(Edit(va, old, new, what))

    # the machines chunk (RAM, MCHUNK): the shims, the names, the name table, the
    # attribute rows, the list -- what W5 kept in three caves, for two machines now
    _need(content, LIST_STOCK_VA, b"".join(_long(t) for t in LIST_STOCK), "the MACHINE SEL list")
    names_rows = _read(content, NAMES_STOCK_VA, NAME_ROW * 5)
    attr_rows = _read(content, ATTR_STOCK_VA, ATTR_ROW * 5)
    strings = "\n".join(f'name_long_{t}:\n    .asciz "{MACHINE_NAMES[t][0]}"\n'
                        f'name_short_{t}:\n    .asciz "{MACHINE_NAMES[t][1]}"' for t in NEW_TYPES)
    labels = SHIM_LABELS + SHIM2_LABELS + tuple(f"name_{c}_{t}" for t in NEW_TYPES
                                                for c in ("long", "short")) + ("mdata",)
    table = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in labels) + "\n"
    src = SHIMS + SHIMS2 + "\n" + strings + "\n    .align 2\nmdata:\n" + table
    blob = assemble(src, base=MCHUNK)
    head = blob[:-4 * len(labels)]
    layout = dict(zip(labels, struct.unpack(f">{len(labels)}I", blob[-4 * len(labels):])))
    if layout["mdata"] != MCHUNK + len(head):
        raise ComposeError("the machines chunk's data does not follow its code")
    layout["long_name"], layout["short_name"] = layout["name_long_5"], layout["name_short_5"]
    rows = bytearray(names_rows)
    for t in NEW_TYPES:
        rows += _long(layout[f"name_long_{t}"]) + _long(layout[f"name_short_{t}"]) + _long(0)
    n_rows = 5 + len(NEW_TYPES)
    layout["names"] = layout["mdata"]
    layout["attributes"] = layout["names"] + NAME_ROW * n_rows
    layout["list"] = layout["attributes"] + ATTR_ROW * n_rows
    clone_attr = attr_rows[ATTR_ROW * CLONE:ATTR_ROW * (CLONE + 1)]
    mchunk = (head + bytes(rows) + attr_rows + clone_attr * len(NEW_TYPES)
              + b"".join(_long(t) for t in LIST_NEW))
    if MCHUNK + len(mchunk) > MCHUNK_END:
        raise ComposeError(f"the machines chunk ends past {MCHUNK_END:#010x}")
    layout["mchunk_code_end"] = layout["mdata"]
    top = TYPES_LAST                            # the highest type with a row
    if NEW_TYPES != tuple(range(NEW_TYPE, top + 1)):
        raise ComposeError("the new types must be one run from 5: each has a row")

    # 1. the list: its length is LIST_NEW's, so a seventh machine is one entry there
    n = len(LIST_NEW)
    edit(LIST_ALLOC, bytes.fromhex("4878") + struct.pack(">H", 4 * n),
         f"MACHINE SEL list: storage for {n} longs", bytes.fromhex("48780014"))
    edit(LIST_END, bytes.fromhex("4879") + _long(layout["list"] + 4 * n),
         "MACHINE SEL list: the copy's end", bytes.fromhex("4879") + _long(LIST_STOCK_VA + 20))
    edit(LIST_CAP, bytes.fromhex("41e8") + struct.pack(">H", 4 * n),
         f"MACHINE SEL list: the vector's capacity, {n} longs", bytes.fromhex("41e80014"))
    edit(LIST_BEGIN, bytes.fromhex("4879") + _long(layout["list"]),
         "MACHINE SEL list: the copy's start", bytes.fromhex("4879") + _long(LIST_STOCK_VA))
    edit(GROUP_FN, group_function(assemble), f"the MACHINE SEL group: our synth machines ({SAMPLE_GROUP}) "
         f"and the sample machines ({SAMPLER_GROUP}) are sections of their own, divided off like MIDI",
         GROUP_STOCK)

    # 2. the names
    for bound, base, op, col in NAME_SITES:
        edit(bound, bytes([0x72, top]), f"name column {col // 4}: bound 4 -> {top}",
             bytes.fromhex("7204"))
        edit(base + 2, _long(layout["names"] + col),
             f"name column {col // 4}: the {n_rows}-row table", _long(NAMES_STOCK_VA + col))
        _need(content, base, bytes.fromhex(op), "the name accessor's base instruction")

    # 3. the attribute rows
    for bound in ATTR_BOUNDS:
        edit(bound, bytes([0x74 if bound == 0x400DC19C else 0x72, top]),
             f"attribute rows: bound 4 -> {top}",
             bytes.fromhex("7404" if bound == 0x400DC19C else "7204"))
    for site, col in ATTR_BASES:
        _need(content, site, bytes.fromhex("41f9"), "the attribute accessor's lea")
        edit(site + 2, _long(layout["attributes"] + col), f"attribute rows: the {n_rows}-row copy",
             _long(ATTR_STOCK_VA + col))

    # 5. the stored-sound LOAD keeps type 5 (stock turns it into FM Tone)
    edit(LOAD_BOUND, bytes([0x74, top + 2]), f"stored-sound LOAD: machine types -1..{top} are "
         "kept (stock keeps -1..4; anything else loads as FM Tone)", bytes.fromhex("7406"))

    # 4. slot_to_id
    edit(SLOT_HOOK, bytes.fromhex("4ef9") + _long(layout["slot_shim"]) + bytes.fromhex("4e71"),
         "param_set_slot_to_id: detour to the shim", SLOT_HOOK_STOCK)

    # 6. the SYN page tables
    for site, what in CANON_ARG_SITES:
        edit(site, bytes.fromhex("4eb9") + _long(layout["canon_arg"]),
             f"{what}: type 5 reads WaveTone's row", CANON_ARG_STOCK)
    edit(COUNT_SITE, bytes.fromhex("4eb9") + _long(playout["wr_count"]),
         "SYN page count(type): 2 for a Waverider track (M7); otherwise type 5 reads WaveTone's",
         CANON_ARG_STOCK)
    edit(PAGE_SITE, bytes.fromhex("4eb9") + _long(playout["wr_page"]) + bytes.fromhex("4e71"),
         "SYN page(type, n): Waverider's own pages for a Waverider track (M7); otherwise "
         "type 5 reads WaveTone's", PAGE_STOCK)
    edit(LABEL_SITE, bytes.fromhex("4eb9") + _long(playout["wr_label"]),
         "the SYN page's label fetch: Waverider's labels for a Waverider track (M7)", LABEL_STOCK)
    edit(GRID_SITE, bytes.fromhex("4eb9") + _long(playout["wr_grid"]) + bytes.fromhex("4e714e71"),
         "the SYN page draw: Waverider's own page for a Waverider track (M8.1)", GRID_STOCK)
    edit(pages.CELL_EXIT, bytes.fromhex("4ef9") + _long(playout["wr_cell_tail"]) + bytes.fromhex("4e714e71"),
         "a stock page cell's widget (0x4006448a): its exit through wr_cell_tail, which draws "
         "parameter slides' marks (v0.45: no longer PING's TYPE)", bytes.fromhex(pages.CELL_EXIT_STOCK))
    edit(pages.ID9_SITE, bytes.fromhex("4eb9") + _long(playout["wr_id9"]),
         "the SYN page draw: a CZ track's third page (id 9 to the draw) to wr_grid, not "
         "WaveTone's page-3 grid", bytes.fromhex(pages.ID9_STOCK))
    edit(ICON_SITE, bytes.fromhex("4eb9") + _long(playout["wr_icons"]) + bytes.fromhex("4e71"),
         "the SYN page draw: no WaveTone oscillator icons on a Waverider track (M7)", ICON_STOCK)
    _need(content, PAGE_SITE - 4, bytes.fromhex("2f027404"), "0x400c24ee's push of d2 and its bound")
    _need(content, POLL_SITE - 2, bytes.fromhex("2f0a"), "the UI loop pushes the screen")
    _need(content, POLL_SITE + 6, bytes.fromhex("588f4a00"), "... and tests the answer's low byte")
    edit(POLL_SITE, bytes.fromhex("4eb9") + _long(csyms["wr_poll"]),
         "the UI loop's redraw test: wr_poll asks for a redraw while a modulation marker on "
         "Waverider's page would move, then answers as stock", POLL_STOCK)

    # v0.22: the RECORDER's screen -- its keys and knobs, its draw, FUNC + VOICE
    _need(content, UI_POP_SITE - 6, bytes.fromhex("48794059d214"), "the UI loop pushes its queue")
    _need(content, UI_POP_SITE + 6, bytes.fromhex("588f72292440"), "... then takes the item: moveq #41 ; movea d0,a2")
    edit(UI_POP_SITE, bytes.fromhex("4eb9") + _long(csyms["smp_ui_pop"]),
         "the UI loop's queue receive: smp_ui_pop takes the recorder's keys and knobs while "
         "it is up, and the sample list's UP/DOWN; everything else as stock", UI_POP_STOCK)
    _need(content, SCREEN_SITE - 4, bytes.fromhex("2f0b2f0a"), "the UI loop pushes canvas, screen")
    edit(SCREEN_SITE, bytes.fromhex("4eb9") + _long(csyms["wr_screen"]),
         "the UI loop's draw of its screen: stock's, then the RECORDER over it while it is up",
         SCREEN_STOCK)
    edit(LED_SITE, bytes.fromhex("4eb9") + _long(csyms["bn_led_walk"]),
         "the LED compose's walk of the views: bn_led_walk claims the 16 trig LEDs for the "
         "page's recorder trigs while the BOUNCE REC panel is up, then stock's walk", LED_STOCK)
    _need(content, REC_COMBO_SITE - 4, bytes.fromhex("60000ff4"), "the VOICE case without FUNC ends just before")
    _need(content, REC_COMBO_EXIT, bytes.fromhex("2f022f0a4eb94011c674"), "the key handler's common exit")
    disp = REC_COMBO_EXIT - (REC_COMBO_SITE + 8)
    edit(REC_COMBO_SITE, bytes.fromhex("4eb9") + _long(csyms["rec_combo"]) + bytes.fromhex("6000")
         + disp.to_bytes(2, "big"),
         "FUNC + VOICE: the RECORDER opens or closes (stock: unison on/off; VOICE alone "
         "still opens its menu)", REC_COMBO_STOCK)

    # v0.23: SLICES: in KEYBOARD mode a SLICE track (SLCE NOTE) plays slice k on trig k
    _need(content, KEYNOTES_SITE - 8, bytes.fromhex("2f04486effd42f00"), "the KeyboardView pushes key, &notes, view")
    edit(KEYNOTES_SITE, bytes.fromhex("4eb9") + _long(csyms["slc_keynotes"]),
         "a trig key's notes in KEYBOARD mode: on a SLICE track (SLCE NOTE) slice k, else stock's",
         KEYNOTES_STOCK)

    # v0.30: MACHINE SEL from one sample machine to another keeps SAMP (owner's request: the
    # commit resets the sound to the machine's defaults, SAMP to OFF; measured in the emulator)
    edit(MACHSEL_COLSW_SITE, bytes.fromhex("4eb9") + _long(layout["colsw"]),
         "MACHINE SEL LEFT / RIGHT: the cursor on the column's current machine, the scroll "
         "following it (v0.35: an empty FLTR column after RIGHT from a machine low in the list)",
         MACHSEL_COLSW_STOCK)
    edit(MACHSEL_COMMIT_SITE, bytes.fromhex("4eb9") + _long(csyms["smp_machine_commit"]),
         "MACHINE SEL's commit: between two sample machines SAMP is kept (rec.c)", MACHSEL_COMMIT_STOCK)

    # v0.25: modulation on SAMP steps through the loaded samples (link.c, smp_mod_apply)
    _need(content, MODAPPLY_SITE - 4, bytes.fromhex("2f002440"), "the driver pushes the mirror (move.l %d0,-(sp); movea.l %d0,%a2)")
    edit(MODAPPLY_SITE, bytes.fromhex("4eb9") + _long(csyms["smp_mod_apply"]),
         "the per-frame modulation apply: stock's 0x400db22c, then a sample machine's modulated SAMP "
         "moved through the loaded slots", MODAPPLY_STOCK)

    # v0.22: the LFOs' destination list leaves out the WaveTone records our machines do not use
    _need(content, LFO_MASK_LEA, bytes.fromhex("45f9400dc30e"), "the destination list: lea 0x400dc30e,%a2")
    _need(content, LFO_MASK_LEA + 0x30, bytes.fromhex("4e92"), "... called once a slot (jsr %a2@)")
    edit(LFO_MASK_LEA + 2, _long(csyms["wr_lfo_mask"]),
         "the LFO destination list's mask lookup: wr_lfo_mask answers 0 for a record our "
         "machine leaves unused (named -), stock's 0x400dc30e for everything else",
         _long(LFO_MASK_STOCK))

    # v0.38: per-project pools: the four detours, entered by jmp (the stack as stock left it)
    _need(content, PJ_BEGIN_SITE + 8, bytes.fromhex("262f0028"), "the load goes on: move.l 40(%sp),%d3")
    _need(content, PJ_LOADED_SITE - 2, bytes.fromhex("67de"), "the load's success test just before")
    _need(content, PJ_LOADED_SITE + 8, bytes.fromhex("42a72f03"), "the load goes on: clr.l -(%sp) ; move.l %d3,-(%sp)")
    _need(content, PJ_END_SITE + 10, bytes.fromhex("4e75"), "the load's rts")
    _need(content, PJ_NEW_SITE + 10, bytes.fromhex("42a72f0a"), "NEW goes on: clr.l -(%sp) ; move.l %a2,-(%sp)")
    _need(content, 0x400428C0, bytes.fromhex("4e56ffa848d71c3c"), "NEW's entry: link.w %fp,#-88 (12(%fp) its slot)")
    edit(PJ_BEGIN_SITE, bytes.fromhex("4ef9") + _long(csyms["smp_pj_begin_hook"]) + bytes.fromhex("4e71"),
         "the project LOAD's entry: counted, and the DSP's directory emptied at once (per-project pools)",
         PJ_BEGIN_STOCK)
    edit(PJ_LOADED_SITE, bytes.fromhex("4ef9") + _long(csyms["smp_pj_loaded_hook"]) + bytes.fromhex("4e71"),
         "the project LOAD's success: the slot set as stock, then noted for the pools' switch",
         PJ_LOADED_STOCK)
    edit(PJ_END_SITE, bytes.fromhex("4ef9") + _long(csyms["smp_pj_end_hook"]) + bytes.fromhex("4e714e71"),
         "the project LOAD's exit: counted (a LOAD that failed gives the pool back)", PJ_END_STOCK)
    edit(PJ_NEW_SITE, bytes.fromhex("4ef9") + _long(csyms["smp_pj_new_hook"]) + bytes.fromhex("4e714e71"),
         "NEW project: the slot set as stock, then noted (an empty pool, the owner's decision 1)",
         PJ_NEW_STOCK)

    # the sample link: SysEx in (v0.14); out over the TDM link alone (v0.20)
    edit(LINK_RX_SITE, bytes.fromhex("4eb9") + _long(csyms["smp_rx_hook"]),
         "the SysEx router: the sample link's requests (F0 00 20 3C 7D 01) to smp_rx", LINK_RX_STOCK)

    # the fast link (v0.16): the SSI ISR, its transmit fill done, through smp_tdm_hook
    _need(content, TDM_SITE + 8, bytes.fromhex("2f024eb94012a4e6"), "the ISR goes on: push d2 ; jsr 0x4012a4e6")
    edit(TDM_SITE, bytes.fromhex("4eb9") + _long(csyms["smp_tdm_hook"]) + bytes.fromhex("4e71"),
         "the SSI audio ISR after its transmit fill: smp_tdm writes the sample link's packet "
         "into TDM slots 8..15 and reads the DSP's from slots 14..15", TDM_STOCK)

    for va, want, why in SLIDE_DRAW_GUARDS:
        _need(content, va, bytes.fromhex(want), why)

    # DIRECT JUMP (csrc/jump, docs/jump.md): off unless PTN + YES turns it on
    for va, want, why in JUMP_GUARDS:
        _need(content, va, bytes.fromhex(want), why)
    edit(JUMP_CUE_SITE, bytes.fromhex("4eb9") + _long(csyms["jmp_cue"]),
         "DIRECT JUMP: the PTN view's one-pattern cue: stock's, then armed if the setting is on "
         "and the sequencer plays", JUMP_CUE_STOCK)
    for va, stock_hex, sym, what in JUMP_ISR_SITES:
        edit(va, bytes.fromhex("4ef9") + _long(csyms[sym]),
             f"DIRECT JUMP, the sequencer tick: {what} -> {sym}, which replays it", bytes.fromhex(stock_hex))
    edit(JUMP_KEY_SLOT, _long(csyms["jmp_key"]),
         "DIRECT JUMP: the PTN view's key handler (vtable): PTN held + YES / NO sets it on / off; "
         "everything else to stock's 0x400fa6be", _long(JUMP_KEY_STOCK))

    # the RECORDER page's YES (v0.15): the parameter page's key handler through smp_key,
    # which takes YES on that page and hands everything else to stock's
    edit(KEY_SLOT, _long(csyms["smp_key"]),
         "the parameter page's key handler (vtable): smp_key, YES on the sample machines' "
         "RECORDER page records; every other key and page goes on to stock's 0x40016480",
         _long(KEY_STOCK))

    # one detent a choice (v0.15): the setter's write through smp_quant_hook
    _need(content, QUANT_SITE - 4, bytes.fromhex("4e90588f"), "the setter's jsr %a0@ ; addq #4 before its write")
    _need(content, QUANT_SITE + 6, bytes.fromhex("4a07"), "... and its tst.b %d7 after")
    edit(QUANT_SITE, bytes.fromhex("4eb9") + _long(csyms["smp_quant_hook"]),
         "the parameter setter's write: smp_quant moves a sample machine's few-choice "
         "control one choice a detent, then writes as stock", QUANT_STOCK)

    # 7. getMachineType(track): WaveTone for the UI, the real type where it is identity
    _need(content, TRACK_TYPE_FN, TRACK_TYPE_FN_STOCK, "getMachineType(track), as raw_track copies it")
    edit(TRACK_TYPE_READ, bytes.fromhex("4ef9") + _long(layout["canon_track"]),
         "getMachineType(track): type 5 is reported as WaveTone", TRACK_TYPE_READ_STOCK)
    for op_va, op, what in IDENTITY_SITES:
        _need(content, op_va, bytes.fromhex(op), f"{what}: the instruction")
        edit(op_va + 2, _long(layout["raw_track"]), f"{what}: asks for the real type",
             _long(TRACK_TYPE_FN))

    # 7b. getMachineType(model, track): the real type, for MACHINE SEL and the re-commits
    _need(content, MODEL_TRACK_TYPE_JMP, bytes.fromhex("4ef9"), "0x4003134e's tail jump")
    edit(MODEL_TRACK_TYPE_JMP + 2, _long(layout["raw_track"]),
         "getMachineType(model, track) 0x4003134e: the real type (MACHINE SEL's marker and "
         "cursor, the track swap, the machine restores)", _long(TRACK_TYPE_FN))

    # 8. the sound's "is this parameter mine?"
    _need(content, VALID_SITE + len(VALID_STOCK), VALID_NEXT, "the ownership test's record-page call")
    edit(VALID_SITE, bytes.fromhex("4eb9") + _long(layout["canon_valid"]),
         "the sound's parameter-ownership test: type 5 owns WaveTone's machine parameters",
         VALID_STOCK)
    # parameter slides (csrc/slides, dnfw.slides, docs/slides.md): the per-voice note block
    # and the lock applier (the trig's slide starts), the frame's smoother (every slide one
    # frame on), the lock-list builder (the step's SLD/SLEN), the step clear, the lock table's
    # LOAD and SAVE (our records' stored ids)
    edit(SL.PRE_SITE, bytes.fromhex("4eb9") + _long(csyms["sl_pre_hook"]),
         "slides: a note's voice in the frame ISR: sl_pre keeps the track's values before the trig",
         bytes.fromhex(SL.PRE_STOCK))
    _need(content, SL.PRE_SITE + 6, bytes.fromhex("49ec05ee670e"), "... then lea 1518(%a4),%a4 ; beq.s")
    edit(SL.APPLY_SITE, bytes.fromhex("4ef9") + _long(csyms["sl_apply"]) + bytes.fromhex("4e71"),
         "slides: the lock applier 0x400db092 through sl_apply (stock's, then the trig's slide)",
         bytes.fromhex(SL.APPLY_STOCK))
    _need(content, SL.SMOOTH_SITE - 10, bytes.fromhex("487980003af02d42ff64"), "the ISR pushes the smoother's source")
    edit(SL.SMOOTH_SITE, bytes.fromhex("4eb9") + _long(csyms["sl_smooth"]),
         "slides: the frame's smoother through sl_smooth (stock's, then every slide one frame on)",
         bytes.fromhex(SL.SMOOTH_STOCK))
    edit(SL.BUILD_SITE, bytes.fromhex("4ef9") + _long(csyms["sl_build"]),
         "slides: the lock-list builder through sl_build (stock's, then the step's SLD/SLEN)",
         bytes.fromhex(SL.BUILD_STOCK))
    edit(SL.CLEAR_SITE, bytes.fromhex("4ef9") + _long(csyms["sl_clear"]) + bytes.fromhex("4e71"),
         "slides: clearing a step's locks clears its SLD/SLEN too", bytes.fromhex(SL.CLEAR_STOCK))
    edit(SL.LOAD_SITE, bytes.fromhex("4ef9") + _long(csyms["sl_load"]) + bytes.fromhex("4e71"),
         "slides: a pattern's lock table LOAD keeps SLD/SLEN records (ids 200/201)",
         bytes.fromhex(SL.LOAD_STOCK))
    edit(SL.SAVE_SITE, bytes.fromhex("4ef9") + _long(csyms["sl_save"]) + bytes.fromhex("4e71"),
         "slides: a pattern's lock table SAVE stores SLD/SLEN records as ids 200/201",
         bytes.fromhex(SL.SAVE_STOCK))
    for va, stock_hex, label in SL.PASTE_SITES:    # v0.40: copy and paste carry SLD/SLEN
        n = len(stock_hex) // 2
        edit(va, bytes.fromhex("4eb9") + _long(csyms[label]) + bytes.fromhex("4e71") * ((n - 6) // 2),
             f"slides: copy/paste carries SLD/SLEN ({label})", bytes.fromhex(stock_hex))
    for name in ("sl_ui_table", "sl_page_up", "sl_page_seen", "sl_knob", "sl_pre_hook", "sl_pre", "sl_apply", "sl_smooth", "sl_build", "sl_clear", "sl_load", "sl_save",
                 "sl_lock_get", "sl_lock_set", "sl_v", "sl_cap", "sl_started", "sl_ticks", "sl_pasted", "sl_tclip", "sl_paste",
                 "sl_draw_sld", "sl_draw_slen"):
        layout[name] = csyms[name]
    layout.update(playout)
    # W2: where the C renderer's code ends (its rodata and data follow): the ship gate
    # checks [C_LOAD, c_text_end) as code
    layout["c_load"] = pages.C_LOAD
    layout["c_text_end"] = csyms["__text_end"]
    for name in ("smp_hi", "smp_walk", "smp_booted", "smp_cmds", "smp_tdm_sent", "smp_tdm_heard",
                 "smp_retries", "smp_saved", "smp_boot", "smp_save_recording", "smp_save_mark", "smp_load", "smp_lstate",
                 "rec_overlay", "rec_src", "rec_dest", "smp_ram", "rec_phase", "trim_slot",
                 "trim_n", "trim_s", "trim_e", "nm_cur", "nm_text", "slc_state", "slc_page_seen", "slc_seen_draw", "slc_letgo", "slc_open_track",
                 "smp_analyse", "smp_analysis", "smp_onsets", "smp_slices_set", "smp_slices_get",
                 "slc_nfr", "slc_sl", "slc_ns", "slc_cur", "slc_grid_n", "smp_pos", "smp_pos_at", "smp_periods", "smp_dir_ok", "smp_meta_ok", "smp_lst_open", "smp_fb_open", "smp_fb_folder", "smp_fb_cur", "smp_fb_count", "smp_fb_mark_count", "smp_fb_mark_unused", "smp_fb_marked", "smp_fb_menu", "smp_mod_apply", "smp_quant", "smp_samp_turned", "smp_overlay_dirty", "rec_pv_on", "smp_func_held", "smp_question_up", "smp_machine_commit", "smp_rx", "smp_fb_store", "smp_lib_refresh", "smp_lib_pending", "smp_lp_queued", "smp_lib_state", "smp_lib_writes", "smp_lib_load", "smp_lib_slot_of", "smp_lib_preview", "smp_lib_preview_stop", "smp_fb_rowtext", "smp_mq_off", "smp_fb_mcur", "smp_lp_done", "smp_lp_full", "smp_l_order", "smp_walk_total", "smp_held_lo", "smp_held_hi", "smp_knob_d", "smp_knob_at", "smp_dsp_load", "smp_load_peak", "smp_load_seen", "smp_load_at", "wr_screen_obj", "rec_state", "rec_heard", "slc_kb_c", "slc_alloc_n", "smp_tables", "smp_pv_state", "trim_zoom", "trim_head_x", "rt_on", "rt_play", "rt_rplace", "rt_rbytes", "rt_pend", "rt_cur", "rt_cur_end", "rt_manual", "rt_qrec", "rt_qplay", "rt_pos", "rt_steps", "rt_nx_place", "rt_nx_room", "rt_nx_need", "rt_w", "rt_gen", "q_gen", "q_fire", "q_cancel", "rt_fired", "rt_refused", "rt_swaps", "rt_qfired", "rt_why", "rt_why_at", "rt_trig", "rt_bounce_samp", "rt_is_bounce", "rt_buf_of", "rt_trig_get", "rt_trig_toggle", "rt_rearm", "rt_count", "rt_take_handover", "rt_regions", "rt_rsteps", "rt_last_step", "rt_used", "rt_fired_at", "rt_fired_trk", "rt_why_trk", "rt_last_key", "bn_page", "bn_yes_at", "bn_active", "bn_led_walk", "bn_led_poll", "bn_led_claims", "bn_open", "bn_save", "bn_pages", "bn_said_at", "bn_said_n", "bn_nothing_at", "sl_ui_table_now", "smp_push_slot", "rt_frame", "rt_poll", "rt_cut", "smp_rt_sent", "sl_rec_knob", "sl_rec_held", "sl_rec_table", "rec_view", "rec_rt_take", "rec_rlen", "rec_src", "rec_chan", "rt_q_set", "rt_q_waiting", "sl_rec_page", "rt_knob", "rt_state", "smp_rec_place", "smp_slot_empty", "smp_pl_dirp", "rec_combo", "rec_overlay",
                 "jmp_on", "jmp_armed", "jmp_pending", "jmp_count", "jmp_last", "jmp_loaded", "jmp_dirty",
                 "jmp_reads", "jmp_writes", "jmp_to", "jmp_from", "jmp_key", "jmp_poll", "jmp_forced",
                 # v0.38: per-project pools
                 "smp_pj_begins", "smp_pj_ends", "smp_pj_loads", "smp_pj_news", "smp_pj_slot", "smp_pj_newslot", "smp_pj_last", "smp_blank_req", "smp_blank_sent", "smp_pl_on", "smp_pl_owner", "smp_pl_state", "smp_pl_writes", "smp_pl_switches", "smp_pl_lists_written", "smp_pl_events", "smp_pl_src", "smp_pl_boot_case", "smp_pl_gen", "smp_pl_skipped", "smp_pl_mismatch", "smp_discard", "smp_rename",
                 # v0.38: the count to the DSP after a live add (link.c K_HEAD)
                 "smp_heads", "smp_head_due", "smp_head_min", "smp_count_cover",
                 # v0.39: ERASE MOD DATA (erase.c; scripts/emu_erase.py)
                 "smp_er_lock", "smp_er_req", "smp_er_state", "smp_er_err", "smp_er_sector", "smp_er_value",
                 "smp_er_done", "smp_er_total", "smp_er_trims", "smp_er_reads", "smp_er_checks",
                 "smp_er_nchecks", "smp_er_job", "smp_er_start", "smp_er_poll",
                 "smp_er_retries", "smp_er_waits", "smp_er_resume",   # v0.41
                 # v0.40: the slice menus' wait, LINKED points, the playhead's redraw (gate: slice, samplist)
                 "slc_pop", "slc_poll", "slc_stock_asked", "slc_fails", "slc_linked", "smp_norm_state",
                 "smp_pl_quiesce", "smp_analysis_slot", "smp_slot_frames", "wr_draws", "smp_pos_in", "smp_playhead",
                 # v0.40: folders inside folders
                 "smp_lib_fpar", "smp_fb_titletext", "smp_fb_delete"):   # the sample link's state (v0.15)
        layout[name] = csyms[name]
    # v0.45: PING removed (owner, 2026-11-08): its chunk (the FLTR list's 'Ping', the filter
    # names, the LOAD bound, slot_to_id, the descriptor, the curve) is no longer composed, so
    # all of those stay stock and a sound saved with filter 6 loads as Multi-Mode
    return {"content": bytes(content), "edits": edits, "layout": layout,
            "chunk": {"load": pages.LOAD, "code": chunk},
            "c_chunk": {"load": pages.C_LOAD, "code": cimage},
            "machines_chunk": {"load": MCHUNK, "code": bytes(mchunk)}}
