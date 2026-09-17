"""Make the arpeggiator play on MIDI tracks: route their notes through the arp, out over MIDI.

`arp-on-midi2` opened the ARPEGGIATOR menu on a MIDI track, and DNX measured
that nothing arpeggiated: the trig went out as written. Reading the engine says
why, and this build is the answer to it.

## Where the arp lives, read 2026-09-17

A note has two roads, chosen per track by the kit's synth/MIDI mask (`+0x5cda`):

| source | synth track | MIDI track | the fork |
|---|---|---|---|
| sequencer trig | `0x400d8654` makes an engine record | `0x400d8b5a` makes a MIDI record | `0x400d9062`, `0x400d9ee0` |
| live key down | `0x40137d3c` (voice starter) | `0x4012b8b0` (MIDI sender) | `0x40121d5c` in `0x40121ad2` |
| live key up | `0x40137d3c` | `0x4012b8b0` | `0x401218ec` in `0x4012182a` |

The synth road ends in the frame ISR `0x40025e36`. That is where the arp is: the
note set `0x40029cd4`, the step `0x4002a0bc` (called at `0x400266e0` and
`0x4002686e`), the step clock (type-9 records, the second sequencer fork
schedules them), and finally the voice trigger `0x400db524`, called at
`0x400268f8` for every note, arpeggiated or not. The MIDI road goes to the MIDI
task `0x4012a9a8` and never meets the arp.

The arp's settings are the track's sound, `kit + 52 + 1163*track`: MODE `+0x15f`
(0 = off; [FUNC]+[ARP] parks it at `+0x176` and writes 0, `0x4004bea4`),
SPD `+0x160`, RNG `+0x161`, N.LEN `+0x162`, LEN `+0x163`. DNX found a MIDI
track's sound slot holds these bytes and keeps them.

## What this build does

1. **The menu opens** on a MIDI track: `arp-on-midi2`'s gate, unchanged.
2. **A MIDI track with the arp on takes the synth road** at all three forks, so
   its notes reach the ISR's arp. Arp off, or a synth track: stock.
3. **At the voice trigger, a MIDI track's note becomes a MIDI record** instead
   of a voice. Its note and velocity are the arp's step; its length is N.LEN
   while the arp runs, else the note's own. It is appended to the batch the ISR
   already hands the MIDI task once per frame (head `-180(%fp)`, tail `%a5`,
   posted at `0x40026f60`), so nothing new crosses a context boundary. The MIDI
   task then sends it on the track's channel and schedules its note-off from
   the length, exactly as for a trig.

A key-down note carries a lock list from the MIDI pool when `0x4029f524` selects
one (0..127). The engine would free it into its own pool, so on the arp road it
goes back to the MIDI pool first and the note plays without it.

A MIDI note needs a finite length to be switched off, so an INF length (127)
is sent as 126, the longest finite one.

4. **The menu's knobs stay on the menu.** `ArpSetupMenuView`'s constructor
   (`0x400191a6`) connects `0x400187b4` to the model's change signal. It reads
   the active track and, if MIDI, calls the owner's vtable `+40` and closes the
   view. A knob edit is a change, so on v2 the first detent closed the menu and
   the rest of the turn landed on the TRIG page beneath -- the owner's report.
   Its `beq.s` becomes `bra.s`: the view stays open on any track.

## What to listen and look for

| on a MIDI track, arp ON | means |
|---|---|
| MIDI out arpeggiates, at SPD, over RNG, N.LEN long | done |
| MIDI out plays the trig as written | a fork was missed; the arp never saw the note |
| nothing on MIDI out | the voice-trigger hook never fired for the track |
| audio from the MIDI track's own output | the engine voiced the record before the hook |
| stuck MIDI notes | a length arrived as INF, or a note-off path is missing |
| turning a menu knob returns to TRIG | another path closes the view; `0x400187b4` was not the only one |

Arp OFF on the MIDI track, and every synth track: must be exactly stock.
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

# One of the three clean 896-byte runs (docs/code-caves.md). lfo-waves boots
# from 0x402cf52c and lfo4-tick6a lives at 0x402dfa1c; this one is left.
CAVE = 0x402D0664
CAVE_CAP = 896

KIT = 0x800052A0            # the ISR's kit pointer, also read at task level (0x40025bda)
MIDI_MASK = 0x8000537C      # kit +0x5cda, mirrored per frame (0x40025b9a)
SOUND_BASE = 52             # kit + 52 + 1163*track: the track's sound
SOUND_STRIDE = 1163
ARP_MODE = 0x15F
ARP_NLEN = 0x162
SOUND_VELOCITY = 0x480      # a trig's velocity when its own byte is negative (0x4012a9a8)
SOUND_LENGTH = 0x481        # ...and its length (0x40026680, 0x4012a9a8)

VOICE_START = 0x40137D3C    # synth road, live
MIDI_SEND = 0x4012B8B0      # MIDI road, live
VOICE_TRIGGER = 0x400DB524  # the ISR's per-note voice trigger
MIDI_RECORD = 0x4012A408    # MIDI record pool, interrupts masked while taken
MIDI_LOCKS_FREE = 0x4012A3B4  # returns a MIDI lock list to 0x4460fcbc

LABELS = ("seq_gate", "live_send", "voice_hook")


FILTER = """  move.l  56(%a0),%d1
    btst    #1,%d1                      | a note on
    beq     9f
    and.l   #0x140000,%d1               | the stock routine voices neither
    bne     9f
"""
LEAVE = """9:  moveq   #0,%d0
    rts"""

# --diag: every MIDI-track record that reaches the hook goes out, and is voiced
# as well, at velocity 100 and length 6. A filtered one is replaced by a marker
# note on the same channel:
# C1 (24) gate off, D1 (26) legato bit 18, E1 (28) already-voiced bit 20.
DIAG_FILTER = "\n"
DIAG_MARK = """    move.l  56(%a2),%d1
    moveq   #24,%d0
    btst    #1,%d1
    beq.s   15f
    moveq   #26,%d0
    btst    #18,%d1
    bne.s   15f
    moveq   #28,%d0
    btst    #20,%d1
    beq.s   16f
15: move.b  %d0,38(%a3)
16: moveq   #100,%d0                    | every note: fixed velocity and length,
                                        | so neither can be what silences it
    move.b  %d0,39(%a3)
    moveq   #6,%d0
    move.b  %d0,40(%a3)
"""
DIAG_LEAVE = f"""    jmp     {VOICE_TRIGGER:#x}              | and voice it: the hook fired if T16 sounds"""


def cave_source(diag: bool = False) -> str:
    return f"""
| Sequencer fork. In: %a0 kit, %d2 track. Out: Z set -> synth producer,
| Z clear -> MIDI producer. Replaces `mvs.w 23770(%a0),%dN; btst %d2,%dN`;
| the stock bne that follows is kept. Preserves every register.
seq_gate:
    lea     -12(%sp),%sp
    movem.l %d0-%d1/%a1,(%sp)
    mvs.w   23770(%a0),%d1
    btst    %d2,%d1
    beq.s   1f                          | synth track: Z set, stock
    move.l  #{SOUND_STRIDE},%d1
    muls.l  %d2,%d1
    lea     0(%a0,%d1.l),%a1
    tst.b   {SOUND_BASE + ARP_MODE}(%a1)  | arp MODE
    seq     %d0                         | 0xff when the arp is off
    tst.b   %d0                         | off -> Z clear (MIDI); on -> Z set (synth)
1:  movem.l (%sp),%d0-%d1/%a1
    lea     12(%sp),%sp
    rts

| Live fork, MIDI branch. Same argument as both callees: one note event,
| whose first long is the track. Arp on -> the voice starter.
live_send:
    move.l  4(%sp),%a0
    move.l  (%a0),%d0
    moveq   #15,%d1
    cmp.l   %d0,%d1
    bcs.s   2f
    move.l  {KIT:#x},%d1
    beq.s   2f
    move.l  %d1,%a1
    move.l  #{SOUND_STRIDE},%d1
    muls.l  %d0,%d1
    add.l   %d1,%a1
    tst.b   {SOUND_BASE + ARP_MODE}(%a1)
    beq.s   2f
    move.l  52(%a0),%d0                 | a lock list from the MIDI pool (0x40121d06)
    beq.s   11f
    clr.l   52(%a0)
    move.l  %d0,-(%sp)
    jsr     {MIDI_LOCKS_FREE:#x}        | back to its own pool, not the engine's
    addq.l  #4,%sp
11: jmp     {VOICE_START:#x}
2:  jmp     {MIDI_SEND:#x}

| The ISR's voice trigger, (record, time). A MIDI track's note becomes a
| MIDI record on the ISR's outgoing batch; everything else is stock.
voice_hook:
    move.l  4(%sp),%a0
    move.l  16(%a0),%d0
    moveq   #15,%d1
    cmp.l   %d0,%d1
    bcs.s   3f
    mvs.w   {MIDI_MASK:#x},%d1
    btst    %d0,%d1
    bne.s   4f
3:  jmp     {VOICE_TRIGGER:#x}
4:{{FILTER}}    lea     -16(%sp),%sp
    movem.l %d2-%d3/%a2-%a3,(%sp)
    move.l  %a0,%a2
    jsr     {MIDI_RECORD:#x}
    move.l  %d0,%a3
    move.l  16(%a2),%d2
    move.l  %d2,8(%a3)                  | track
    moveq   #1,%d0
    move.l  %d0,12(%a3)                 | note on
    move.l  #0x80,%d0
    move.l  %d0,16(%a3)                 | play it
    clr.l   20(%a3)
    moveq   #-1,%d0
    move.l  %d0,24(%a3)                 | the note is the inline entry at +36
    clr.l   32(%a3)
    move.l  24(%sp),48(%a3)             | time, the base of its note-off
    moveq   #2,%d0
    move.l  %d0,52(%a3)                 | live-played: the engine already gated mutes
    clr.b   36(%a3)
    clr.b   37(%a3)
    move.b  38(%a2),38(%a3)             | note: the arp's step
    clr.b   41(%a3)
    move.l  64(%a2),%d0                 | the sound it plays with, as the ISR finds it (0x40026708)
    bne.s   5f
    move.l  60(%a2),%d0
    bne.s   5f
    move.l  #{SOUND_STRIDE},%d0
    muls.l  %d2,%d0
    add.l   {KIT:#x},%d0
    add.l   #{SOUND_BASE},%d0
5:  move.l  %d0,%a1
    move.l  44(%a2),%d0                 | the sound its defaults come from (0x4002672c)
    bne.s   12f
    move.l  %a1,%d0
12: move.l  %d0,44(%a3)                 | the MIDI task reads defaults through +44 too:
    move.l  %d0,%a0                     | never leave it null
    move.b  39(%a2),%d1                 | velocity; negative = the sound's
    bpl.s   13f
    move.b  {SOUND_VELOCITY}(%a0),%d1
    bpl.s   13f
    moveq   #100,%d1
13: move.b  %d1,39(%a3)
    moveq   #0,%d3
    move.b  40(%a2),%d3                 | the note's own length
    move.l  56(%a2),%d1
    btst    #19,%d1                     | the arp is running this note
    beq.s   14f
    move.b  {ARP_NLEN}(%a1),%d3         | N.LEN
14: tst.b   %d3
    bpl.s   6f
    move.b  {SOUND_LENGTH}(%a0),%d3     | negative = the sound's (0x40026680)
6:  moveq   #126,%d1
    cmp.l   %d3,%d1
    bcc.s   7f
    move.l  %d1,%d3                     | INF would never be switched off
7:  move.b  %d3,40(%a3)
{{MARK}}    tst.l   -180(%fp)
    bne.s   8f
    move.l  %a3,-180(%fp)
    bra.s   10f
8:  move.l  %a3,92(%a5)
10: move.l  %a3,%a5
    movem.l (%sp),%d2-%d3/%a2-%a3
    lea     16(%sp),%sp
{{LEAVE}}
""".replace("{FILTER}", DIAG_FILTER if diag else FILTER)      .replace("{MARK}", DIAG_MARK if diag else "")      .replace("{LEAVE}", DIAG_LEAVE if diag else LEAVE)


# (va, stock bytes, kind, label) -- each stock sequence is replaced by a call
# to `label`, padded with NOPs.
HOOKS = (
    (0x400D905E, bytes.fromhex("73685cda0501"), "jsr", "seq_gate"),   # sequencer fork 1
    (0x400D9EDC, bytes.fromhex("71685cda0500"), "jsr", "seq_gate"),   # sequencer fork 2
    (0x40121D84, bytes.fromhex("4eb94012b8b0"), "jsr", "live_send"),  # key down, MIDI branch
    (0x40121914, bytes.fromhex("4eb94012b8b0"), "jsr", "live_send"),  # key up, MIDI branch
    (0x400268F8, bytes.fromhex("4eb9400db524"), "jsr", "voice_hook"), # ISR voice trigger
)

# The menu gate from arp-on-midi2, and the view's own MIDI test.
EDITS = (
    (0x4005F9C2, bytes.fromhex("6600f58e"), bytes.fromhex("4e714e71"),
     "bne.w -> nop nop: the ARPEGGIATOR menu opens on MIDI tracks"),
    (0x400187F6, bytes.fromhex("670e"), bytes.fromhex("600e"),
     "beq.s -> bra.s: the open menu no longer closes itself on a MIDI track"),
)

# Read, not written: the code the hooks rely on.
CONTEXT = (
    (0x400D9064, bytes.fromhex("6626"), "fork 1: bne to the MIDI producer"),
    (0x400D9086, bytes.fromhex("4ebaf5cc"), "fork 1: jsr 0x400d8654, synth producer"),
    (0x400D90CE, bytes.fromhex("4ebafa8a"), "fork 1: jsr 0x400d8b5a, MIDI producer"),
    (0x400D9EE2, bytes.fromhex("6656"), "fork 2: bne to the MIDI producer"),
    (0x400D9F50, bytes.fromhex("4ebaec08"), "fork 2: jsr 0x400d8b5a, MIDI producer"),
    (0x40121D6C, bytes.fromhex("4a01"), "key down: synth test before the MIDI branch"),
    (0x40121D72, bytes.fromhex("4eb940137d3c"), "key down: jsr the voice starter"),
    (0x401218FC, bytes.fromhex("4eb940137d3c"), "key up: jsr the voice starter"),
    (0x400266E0, bytes.fromhex("4eb94002a0bc"), "ISR: arp step"),
    (0x4002686E, bytes.fromhex("4eb94002a0bc"), "ISR: arp step on start"),
    (0x4002611C, bytes.fromhex("9bcd"), "ISR: batch tail %a5 cleared"),
    (0x40026128, bytes.fromhex("42aeff4c"), "ISR: batch head -180(%fp) cleared"),
    (0x40026E4C, bytes.fromhex("2d4dff4c"), "ISR: batch head set"),
    (0x40026F5A, bytes.fromhex("4879445fe870"), "ISR: batch posted to the MIDI task's queue"),
    (0x4004BF0C, bytes.fromhex("1141015f"), "arp toggle writes MODE +0x15f"),
    (0x40025BE8, bytes.fromhex("068000000034"), "sound = kit + 52 + 1163*track"),
    (0x40121D06, bytes.fromhex("4eb94012a394"), "key down: MIDI lock list taken"),
    (0x40121D22, bytes.fromhex("2d40fff4"), "key down: ...and placed at event +52 (fp-12)"),
    (0x400192C2, bytes.fromhex("203c400187b4"), "ArpSetupMenuView ctor registers the callback"),
    (0x400192FA, bytes.fromhex("49f9400f630a"), "...connected to the model's change signal"),
    (0x400187EA, bytes.fromhex("4eb940031274"), "callback: is the active track MIDI"),
    (0x400187FE, bytes.fromhex("20690028"), "callback: yes -> owner vtable +40, close"),
    (0x4012A3B4, bytes.fromhex("206f0004"), "the MIDI lock-list free"),
    (0x4002672C, bytes.fromhex("2268002c"), "ISR: a note's default-giving sound is record +44"),
    (0x40026680, bytes.fromhex("2069002c"), "ISR: negative length -> sound +0x481 through +44"),
)

STOCK = pathlib.Path("00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
DIAG = "--diag" in sys.argv[1:]
OUT = pathlib.Path("00_Resources/02_Builds/"
                   + ("arp-midi-diag" if DIAG else "arp-midi-play2") + "_DN2_1.11.syx")


def be32(v: int) -> bytes:
    return struct.pack(">I", v)


def assemble_stubs(source: str, base: int) -> tuple[bytes, dict[str, int]]:
    """Assemble once and read each label's address off a trailing table."""
    table = "\n".join(f"    .long {name}" for name in LABELS)
    blob = assemble(source + "\n    .align 2\n" + table + "\n", base=base)
    width = 4 * len(LABELS)
    addrs = struct.unpack(">%dI" % len(LABELS), blob[-width:])
    return blob[:-width], dict(zip(LABELS, addrs))


def check(content: bytes, va: int, want: bytes, why: str) -> None:
    have = bytes(content[va - BASE:va - BASE + len(want)])
    if have != want:
        raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} "
                         f"-- not the image this patch was written against ({why})")


def poke(content: bytearray, va: int, stock: bytes, new: bytes, why: str) -> None:
    check(content, va, stock, why)
    content[va - BASE:va - BASE + len(new)] = new
    print(f"  {va:#010x}  {stock.hex():<14} -> {new.hex():<14}  {why}")


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler found (m68k-linux-gnu-as; WSL is fine)")

    firmware = load(read_image(STOCK))
    section = firmware.container.find(MAIN_OS)
    if section is None:
        raise SystemExit("image has no MAIN OS section")
    content = bytearray(section.unpack())

    print("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        check(content, va, want, why)
        print(f"  {va:#010x}  {want.hex():<14}  {why}")

    print("part 2 -- the cave")
    if any(content[CAVE - BASE:CAVE - BASE + CAVE_CAP]):
        raise SystemExit(f"cave at {CAVE:#010x} is not free")
    payload, at = assemble_stubs(cave_source(DIAG), CAVE)
    if len(payload) > CAVE_CAP:
        raise SystemExit(f"cave overflows: {len(payload)} > {CAVE_CAP}")
    content[CAVE - BASE:CAVE - BASE + len(payload)] = payload
    print(f"  {len(payload)} bytes at {CAVE:#010x}: "
          + ", ".join(f"{k} {v:#010x}" for k, v in at.items()))

    print("part 3 -- the menu gate")
    for va, stock, new, why in EDITS:
        poke(content, va, stock, new, why)

    print("part 4 -- the hooks")
    for va, stock, kind, label in HOOKS:
        new = (b"\x4e\xb9" if kind == "jsr" else b"\x4e\xf9") + be32(at[label])
        if len(new) > len(stock) or (len(stock) - len(new)) % 2:
            raise SystemExit(f"hook at {va:#010x} does not fit {len(stock)} bytes")
        new += b"\x4e\x71" * ((len(stock) - len(new)) // 2)
        poke(content, va, stock, new, f"{kind} -> {label}")

    print("part 5 -- repack")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"  wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
