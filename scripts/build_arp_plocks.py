"""P-locks for the arpeggiator: MODE and RNG, per trig.

    python scripts/build_arp_plocks.py

Writes `00_Resources/02_Builds/arp-plocks_DN2_1.11.syx`. `docs/ideas-backlog.md`
section 18 has the reasoning; the short version, read 2026-09-18:

## Where a lock goes

A pattern's lock record names a **lock id**. Load maps it to one of 101
per-track **mirror slots** (`0x400dccc0`, table `0x401fd0b0`, ids <= 106), save
maps a slot back to an id (`0x400dccfa`, table `0x401fcf20`, slots <= 99). Every
slot 0..99 means something on some page except **65**, and **100** is past the
save table -- the only two free. So:

| lock id | slot | arp setting | sound byte |
|---|---|---|---|
| 107 | 65 | MODE | `+0x15f` |
| 108 | 100 | RNG | `+0x161` |

Both lookups are entered through a hook that answers these two and otherwise
runs the stock code, so every other id and slot is exactly as before.

## How a lock reaches the arp

The sequencer hands the frame ISR each note with its lock list (`record+84`:
count at `+8`, 8-byte entries from `+20`, `u16 slot, u16 value`), which
`0x400db092` applies. The arp does not read the mirror: it reads MODE, RNG and
the rest from the **sound pointer the note set is given** (`0x40029cd4`, called
at `0x40026762` with the sound at `sp+32`), and keeps that pointer for every
step. Sound locks already vary the arp this way on stock firmware (owner,
2026-09-17).

So the hook at that call looks in the note's lock list for slots 65 and 100. If
either is there, it copies the sound into a per-track shadow (16 x 1,164 bytes
at `0x467c0000`, free RAM above BSS), writes the locked byte (the value's low
byte) and passes the shadow instead. No lock: the call is stock.

## Limits, by design

- MODE can only be **changed** per trig while the arp is on for the track:
  whether the arp clock runs is decided in the sequencer from the sound's own
  MODE. A lock to MODE 0 (off) makes the step silent -- the arp step returns no
  note.
- Recording: in grid recording, hold a trig and turn MODE or RANGE in the
  ARPEGGIATOR menu. The menu itself still shows the sound's value, not the lock
  (it has no parameter records to highlight); the trig blinks like any locked trig.
- The applied value also reaches the DSP's parameter mirror at slots 65/100 for
  that track (`0x8000de60`), which no parameter uses; the hardware test watches
  for any side effect.
"""

from __future__ import annotations

import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.patch.assemble import assemble, available

MAIN_OS = 3
BASE = 0x40000400
CAVES = ((0x40295698, 203), (0x40295A30, 200),   # dnfw cave scan: clean, no code reference
         (0x402CF600, 684))                        # LFO Waves' cave past its 46-byte stub: disjoint
SHADOW = 0x467C0000                     # 16 x SOUND_STRIDE, above BSS
SOUND_STRIDE = 1163
SHADOW_STRIDE = 1164                    # word-aligned per track
SOUND_MODE, SOUND_RNG = 0x15F, 0x161
SLOT_MODE, SLOT_RNG = 65, 100
ID_MODE, ID_RNG = 107, 108

ID_TO_SLOT = 0x400DCCC0                 # (table, id) -> slot
SLOT_TO_ID = 0x400DCCFA                 # (table, slot) -> id
SLOT_TABLE = 0x401FCF20                 # slot -> id, slots 0..99
SAVE_REC = 0x400DE75E                   # pattern save: the inline slot -> id, 18 bytes
SAVE_ONE = 0x400DE8B2                   # one-record save: the same, 18 bytes
LOAD_MAX = 0x400DE594                   # pattern load: `moveq #106` bounds the id
NOTE_SET = 0x40029CD4
NOTE_SET_CALL = 0x40026762

# Recording, read 2026-09-18 by recording a real p-lock under the emulator (hold
# a trig in grid recording, push encoder A and turn it) and watching the writes.
SET_LOCK = 0x4004F8FE          # (ctx, step, slot, value) -> 0x4003ceee recorder
APP = 0x4018A97A               # the app singleton
TRACK_CTX = 0x4003EFDE         # (app) -> the active track's context
PATTERN_LEN = 0x4004F896       # (ctx) -> steps
CTX_MODEL, CTX_TRACK = 44, 60  # the context's pattern model and track
HELD = 0x446478C8              # the held-trig object (0x447683f0 on the snapshot)
HELD_BITS, HELD_ANY = 600, 616 # its 128-bit held-step set, and "any held"
BIT_TEST = 0x4019C40C          # (bits, step) -> bool
GET_MODE, SET_MODE = 0x4004BE74, 0x4004BEA4
GET_RNG, SET_RNG = 0x4004C0AA, 0x4004C0DA
MAX_MODE, MAX_RNG = 4, 7       # the stock setters' clamps
MENU_MODE_CALL = 0x40018EEE    # ArpSetupMenuView: jsr setMode
MENU_RNG_CALL = 0x40018FBE     # ... jsr setRng

LABELS = (("load_hook", "save_hook", "save_rec", "save_one"), ("note_hook",), ("ui_mode", "ui_rng"))


def cave_sources() -> tuple[str, str, str]:
    lookups = f"""
| Lock id -> slot. Args (table, id); table 16 is track 16's own, left stock.
load_hook:
    move.l  %sp@(4),%d1
    moveq   #16,%d0
    cmp.l   %d1,%d0
    beq.s   2f
    move.l  %sp@(8),%d0
    cmpi.l  #{ID_MODE},%d0
    bne.s   1f
    moveq   #{SLOT_MODE},%d0
    rts
1:  cmpi.l  #{ID_RNG},%d0
    bne.s   2f
    moveq   #{SLOT_RNG},%d0
    rts
2:  move.l  %d2,%sp@-                   | the stock entry, replayed
    moveq   #16,%d2
    move.l  %sp@(8),%d1
    jmp     {ID_TO_SLOT + 8:#010x}

| Slot -> lock id, for save.
save_hook:
    move.l  %sp@(4),%d1
    moveq   #16,%d0
    cmp.l   %d1,%d0
    beq.s   2f
    move.l  %sp@(8),%d0
    cmpi.l  #{SLOT_MODE},%d0
    bne.s   1f
    moveq   #{ID_MODE},%d0
    rts
1:  cmpi.l  #{SLOT_RNG},%d0
    bne.s   2f
    moveq   #{ID_RNG},%d0
    rts
2:  move.l  %d2,%sp@-
    moveq   #16,%d2
    move.l  %sp@(8),%d1
    jmp     {SLOT_TO_ID + 8:#010x}

| The pattern save's own slot -> id, inline in its record loop (0x400de718), which
| never calls the lookup above. In: d1 slot, d3 track, a0 the stored record, a3 /
| a4 the stock tables. Out: the id byte written, as the replaced bytes did.
save_rec:
    moveq   #16,%d4
    cmp.l   %d3,%d4
    bne.s   1f
    move.l  %a4@(0,%d1:l:4),%d1
    bra.s   3f
1:  moveq   #{SLOT_MODE},%d4
    cmp.l   %d4,%d1
    bne.s   2f
    moveq   #{ID_MODE},%d1
    bra.s   3f
2:  moveq   #{SLOT_RNG},%d4
    cmp.l   %d4,%d1
    bne.s   4f
    moveq   #{ID_RNG},%d1
    bra.s   3f
4:  move.l  %a3@(0,%d1:l:4),%d1
3:  move.b  %d1,%a0@
    rts

| The same inline in the one-record save (0x400de86e). In: a1 slot, a0 the stored
| record; d2 / d3 / a3 are dead there.
save_one:
    move.l  %a1,%d2
    moveq   #{SLOT_MODE},%d3
    cmp.l   %d3,%d2
    bne.s   1f
    moveq   #{ID_MODE},%d2
    bra.s   3f
1:  moveq   #{SLOT_RNG},%d3
    cmp.l   %d3,%d2
    bne.s   2f
    moveq   #{ID_RNG},%d2
    bra.s   3f
2:  lea     {SLOT_TABLE:#010x},%a3
    move.b  %a3@(3,%a1:l:4),%d2
3:  move.b  %d2,%a0@
    rts
"""
    note = f"""
| The arp's note set, (track, ..., sound at +32, ...). A note carrying a lock on
| slot 65 or 100 gets a shadow of its sound with the locked arp byte.
note_hook:
    move.l  %fp@(-36),%a0               | the ISR's note record
    move.l  %a0@(84),%d0                | its lock list
    beq     9f
    lea     %sp@(-16),%sp
    moveml  %d2-%d4/%a2,%sp@            | args now 16 further: track +20, sound +48
    movea.l %d0,%a1
    move.l  %a1@(8),%d4                 | entries
    moveq   #-1,%d2                     | MODE lock
    moveq   #-1,%d3                     | RNG lock
    lea     %a1@(20),%a1
1:  subq.l  #1,%d4
    bmi.s   3f
    mvs.w   %a1@,%d0
    moveq   #{SLOT_MODE},%d1
    cmp.l   %d1,%d0
    bne.s   2f
    mvz.b   %a1@(3),%d2
2:  moveq   #{SLOT_RNG},%d1
    cmp.l   %d1,%d0
    bne.s   4f
    mvz.b   %a1@(3),%d3
4:  addq.l  #8,%a1
    bra.s   1b
3:  move.l  %d2,%d0
    and.l   %d3,%d0
    bmi.s   8f                          | neither: stock
    move.l  %sp@(20),%d0                | track
    move.l  #{SHADOW_STRIDE},%d1
    muls.l  %d1,%d0
    addi.l  #{SHADOW:#010x},%d0
    movea.l %d0,%a2                     | the shadow
    movea.l %sp@(48),%a0                | the sound
    movea.l %a2,%a1
    move.l  #{SOUND_STRIDE},%d1
5:  move.b  %a0@+,%a1@+
    subq.l  #1,%d1
    bne.s   5b
    tst.l   %d2
    bmi.s   6f
    move.b  %d2,%a2@({SOUND_MODE})
6:  tst.l   %d3
    bmi.s   7f
    move.b  %d3,%a2@({SOUND_RNG})
7:  move.l  %a2,%sp@(48)                | the note set arpeggiates the shadow
8:  moveml  %sp@,%d2-%d4/%a2
    lea     %sp@(16),%sp
9:  jmp     {NOTE_SET:#010x}
"""
    ui = f"""
| The ARPEGGIATOR menu's MODE / RNG edit, replacing `jsr setter(model, value)`.
| With a trig held in grid recording, lock (existing lock or sound value) + the
| knob's delta on every held step, through the firmware's own recorder, so the
| lock highlights and the trig blinks exactly as on a parameter page. Otherwise
| the stock setter.
ui_mode:
    pea     {GET_MODE:#010x}
    pea     {SET_MODE:#010x}
    move.l  #{(SLOT_MODE << 8) | MAX_MODE},%sp@-
    bra.s   ui_lock
ui_rng:
    pea     {GET_RNG:#010x}
    pea     {SET_RNG:#010x}
    move.l  #{(SLOT_RNG << 8) | MAX_RNG},%sp@-
ui_lock:                                | +0 slot<<8|max, +4 setter, +8 getter, +12 ret, +16 model, +20 value
    move.l  {HELD:#010x},%d0
    beq     90f
    movea.l %d0,%a0
    tst.b   %a0@({HELD_ANY})
    beq     90f
    lea     %sp@(-32),%sp
    moveml  %d2-%d7/%a2-%a3,%sp@        | +32 packed, +36 setter, +40 getter, +48 model, +52 value
    movea.l %d0,%a3
    move.l  %sp@(48),%sp@-
    movea.l %sp@(44),%a0
    jsr     %a0@                        | the sound's current value
    addq.l  #4,%sp
    move.l  %d0,%d7
    move.l  %sp@(52),%d6
    sub.l   %d0,%d6                     | the knob's delta
    jsr     {APP:#010x}
    move.l  %d0,%sp@-
    jsr     {TRACK_CTX:#010x}
    addq.l  #4,%sp
    movea.l %d0,%a2                     | the active track's context
    move.l  %a2,%sp@-
    jsr     {PATTERN_LEN:#010x}
    addq.l  #4,%sp
    move.l  %d0,%d5
    moveq   #0,%d2                      | step
1:  cmp.l   %d5,%d2
    bge     80f
    move.l  %d2,%sp@-
    pea     %a3@({HELD_BITS})
    jsr     {BIT_TEST:#010x}
    addq.l  #8,%sp
    tst.b   %d0
    beq.s   7f
    movea.l %a2@({CTX_MODEL}),%a0
    move.l  %a0,%sp@-
    movea.l %a0@,%a1
    movea.l %a1@(40),%a1
    jsr     %a1@                        | the pattern's lock table
    addq.l  #4,%sp
    movea.l %d0,%a0
    move.l  %sp@(32),%d4
    lsr.l   #8,%d4                      | slot
    move.l  %a2@({CTX_TRACK}),%d1
    moveq   #101,%d0
    muls.l  %d0,%d1
    add.l   %d4,%d1
    movea.l %a0,%a1
    adda.l  #20640,%a1
    mvs.b   %a1@(0,%d1:l),%d1           | the track's record for the slot
    bmi.s   4f
    move.l  #258,%d3
    muls.l  %d1,%d3
    add.l   %d2,%d3
    add.l   %d2,%d3
    mvz.w   %a0@(2,%d3:l),%d3           | this step's value
    cmpi.l  #0xffff,%d3
    bne.s   5f
4:  move.l  %d7,%d3                     | no lock yet: start from the sound
5:  add.l   %d6,%d3
    bpl.s   6f
    moveq   #0,%d3
6:  moveq   #0,%d0
    move.b  %sp@(35),%d0                | max
    cmp.l   %d0,%d3
    ble.s   3f
    move.l  %d0,%d3
3:  move.l  %d3,%sp@-
    move.l  %d4,%sp@-
    move.l  %d2,%sp@-
    move.l  %a2,%sp@-
    jsr     {SET_LOCK:#010x}
    lea     %sp@(16),%sp
7:  addq.l  #1,%d2
    bra     1b
80: moveml  %sp@,%d2-%d7/%a2-%a3
    lea     %sp@(44),%sp                | our 32, and packed / setter / getter
    rts
90: movea.l %sp@(4),%a0
    lea     %sp@(12),%sp
    jmp     %a0@
"""
    return lookups, note, ui


# (va, stock bytes, label) -- replaced by a jmp (entry) or jsr (call) to the label.
HOOKS = (
    (ID_TO_SLOT, bytes.fromhex("2f027410222f0008"), "jmp", "load_hook"),
    (SLOT_TO_ID, bytes.fromhex("2f027410222f0008"), "jmp", "save_hook"),
    (NOTE_SET_CALL, bytes.fromhex("4eb940029cd4"), "jsr", "note_hook"),
    (MENU_MODE_CALL, bytes.fromhex("4eb94004bea4"), "jsr", "ui_mode"),
    (MENU_RNG_CALL, bytes.fromhex("4eb94004c0da"), "jsr", "ui_rng"),
    (SAVE_REC, bytes.fromhex("7810 b883 6606 2234 1c00 6004 2233 1c00 1081".replace(" ", "")), "jsr", "save_rec"),
    # the first 6 bytes are the table load, dropped; the next 8 are kept ahead of the call
    (SAVE_ONE, bytes.fromhex("47f9401fcf20 2443 45f22a00 d1ca 10b39c03".replace(" ", "")), "jsr", "save_one",
     bytes.fromhex("244345f22a00d1ca")),
)

# Plain byte patches: (va, stock, new, why).
PATCHES = (
    (LOAD_MAX, bytes.fromhex("786a"), bytes.fromhex(f"78{ID_RNG:02x}"),
     "pattern load: let ids up to 108 through to the lookup"),
)

# Read, not written: what the hooks rely on.
CONTEXT = (
    (0x400DCCDA, bytes.fromhex("746a"), "load: ids <= 106 use the table"),
    (0x400DCCEC, bytes.fromhex("41f9401fd0b0"), "load: the id -> slot table"),
    (0x400DCD14, bytes.fromhex("7463"), "save: slots <= 99 use the table"),
    (0x400DCD26, bytes.fromhex("41f9401fcf20"), "save: the slot -> id table"),
    (0x400DD14A, bytes.fromhex("4ebafb74"), "a lock record's header: id -> slot on load"),
    (0x400DD17C, bytes.fromhex("4ebafb7c"), "...and slot -> id on save"),
    (0x40026C34, bytes.fromhex("4eb9400db092"), "ISR applies a note's lock list"),
    (0x40026748, bytes.fromhex("2f02"), "the note set's sound argument, pushed 8th"),
    (0x40026762 + 6, bytes.fromhex("4fef0028"), "the call pops 40 bytes"),
    (0x4002A114, bytes.fromhex("1029015f"), "the arp step reads MODE from its sound"),
    (0x4002A164, bytes.fromhex("79290161"), "...and RNG"),
    (0x4004F930, bytes.fromhex("4eb94003ceee"), "the lock wrapper calls the recorder"),
    (0x4003CF50, bytes.fromhex("752850a0"), "recorder: the track x slot record index at +20640"),
    (0x4003CFD6, bytes.fromhex("33862a02"), "recorder: the step's u16 at record +2"),
    (0x40055BBE, bytes.fromhex("10280268"), "held object: any trig held at +616"),
    (0x4005693C, bytes.fromhex("486b0258"), "held object: the held-step set at +600"),
    (0x40018EE0, bytes.fromhex("4eb94004be74"), "arp menu: MODE getter before the setter"),
    (0x40018FA4, bytes.fromhex("4eb94004c0aa"), "arp menu: RNG getter before the setter"),
    (0x4004BEFA, bytes.fromhex("7404"), "setMode clamps to 4"),
    (0x4004C10E, bytes.fromhex("7407"), "setRng clamps to 7"),
)

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
OUT = pathlib.Path("00_Resources/02_Builds/arp-plocks_DN2_1.11.syx")


def be32(v: int) -> bytes:
    return struct.pack(">I", v)


def check(content: bytes, va: int, want: bytes, why: str) -> None:
    have = bytes(content[va - BASE:va - BASE + len(want)])
    if have != want:
        raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} ({why})")


def compose(stock: bytes, log=print) -> dict:
    if not available():
        raise SystemExit("no m68k assembler found (m68k-linux-gnu-as; WSL is fine)")
    content = bytearray(stock)
    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        check(content, va, want, why)
        log(f"  {va:#010x}  {want.hex():<14}  {why}")

    log("part 2 -- the caves")
    at, caves = {}, []
    for (cave, cap), source, labels in zip(CAVES, cave_sources(), LABELS):
        if any(content[cave - BASE:cave - BASE + cap]):
            raise SystemExit(f"cave at {cave:#010x} is not free")
        table = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in labels) + "\n"
        blob = assemble(source + table, base=cave)
        payload = blob[:-4 * len(labels)]
        at.update(zip(labels, struct.unpack(f">{len(labels)}I", blob[-4 * len(labels):])))
        if len(payload) > cap:
            raise SystemExit(f"cave at {cave:#010x} overflows: {len(payload)} > {cap}")
        content[cave - BASE:cave - BASE + len(payload)] = payload
        caves.append((cave, len(payload)))
        log(f"  {len(payload)} bytes at {cave:#010x}: " + ", ".join(f"{k} {at[k]:#010x}" for k in labels))

    log("part 3 -- the hooks")
    for va, stock_bytes, kind, label, *keep in HOOKS:
        check(content, va, stock_bytes, f"{kind} -> {label}")
        new = keep[0] if keep else b""
        new += (bytes.fromhex("4ef9") if kind == "jmp" else bytes.fromhex("4eb9")) + be32(at[label])
        new += bytes.fromhex("4e71") * ((len(stock_bytes) - len(new)) // 2)
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex():<16} -> {new.hex():<16}  {kind} {label}")

    log("part 4 -- byte patches")
    for va, stock_bytes, new, why in PATCHES:
        check(content, va, stock_bytes, why)
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex()} -> {new.hex()}  {why}")
    return {"content": bytes(content), "caves": caves}


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = compose(section.unpack())["content"]
    print("part 5 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, content)}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
