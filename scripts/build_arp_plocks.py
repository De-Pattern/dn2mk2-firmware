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
- No UI yet: locks are written into a pattern by DNX for testing (ids 107/108).
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
CAVES = ((0x40295698, 203), (0x40295A30, 200))   # dnfw cave scan: clean, no code reference
SHADOW = 0x467C0000                     # 16 x SOUND_STRIDE, above BSS
SOUND_STRIDE = 1163
SHADOW_STRIDE = 1164                    # word-aligned per track
SOUND_MODE, SOUND_RNG = 0x15F, 0x161
SLOT_MODE, SLOT_RNG = 65, 100
ID_MODE, ID_RNG = 107, 108

ID_TO_SLOT = 0x400DCCC0                 # (table, id) -> slot
SLOT_TO_ID = 0x400DCCFA                 # (table, slot) -> id
NOTE_SET = 0x40029CD4
NOTE_SET_CALL = 0x40026762

LABELS = (("load_hook", "save_hook"), ("note_hook",))


def cave_sources() -> tuple[str, str]:
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
    return lookups, note


# (va, stock bytes, label) -- replaced by a jmp (entry) or jsr (call) to the label.
HOOKS = (
    (ID_TO_SLOT, bytes.fromhex("2f027410222f0008"), "jmp", "load_hook"),
    (SLOT_TO_ID, bytes.fromhex("2f027410222f0008"), "jmp", "save_hook"),
    (NOTE_SET_CALL, bytes.fromhex("4eb940029cd4"), "jsr", "note_hook"),
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
    for va, stock_bytes, kind, label in HOOKS:
        check(content, va, stock_bytes, f"{kind} -> {label}")
        new = (bytes.fromhex("4ef9") if kind == "jmp" else bytes.fromhex("4eb9")) + be32(at[label])
        new += bytes.fromhex("4e71") * ((len(stock_bytes) - len(new)) // 2)
        content[va - BASE:va - BASE + len(new)] = new
        log(f"  {va:#010x}  {stock_bytes.hex():<16} -> {new.hex():<16}  {kind} {label}")
    return {"content": bytes(content), "caves": caves}


def main() -> int:
    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    content = compose(section.unpack())["content"]
    print("part 4 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: compress(section.id, section.dest, content)}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
