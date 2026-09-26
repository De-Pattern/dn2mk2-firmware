"""The arpeggiator's SHUF and RAND modes, as real modes.

    python scripts/build_arpmodes.py

Writes `out/arpmodes/section_3_MAIN_OS.bin` (what `dnfw mods` `arpmodes` must
reproduce byte for byte). The `.syx` comes from `dnfw mods apply --mod
arpmodes`. `docs/arp-hidden-modes.md` is the evidence this builds on: stock
1.11 names eight modes, offers five, and plays CYCL for 4, 5, 6 and 7 alike.

## What it changes

| # | site | stock | new | why |
|---|---|---|---|---|
| 1 | `0x4002a13c` | `moveq #3; cmp; beq DOWN; bra CYCL` | `jmp` the cave | the step's dispatch: 3 as stock, 5 and 6 to the cave, anything else CYCL |
| 2 | `0x4004befa`, `0x4004bf00` | `moveq #4` | `moveq #6` | the menu edit (setMode) clamps to 0..6 |
| 3 | `0x4004bfb4`, `0x4004bfc6` | `moveq #4` | `moveq #6` | FUNC+ARP restores a parked MODE clamped to 1..6 |
| 4 | `0x400dd530` | `moveq #4` | `moveq #6` | the stored-sound LOAD keeps 0..6 (7 and above still load as OFF) |

MODE 7, CHRD, stays out: every bound stops at 6, and a 7 forced in some other
way still plays CYCL, as in stock.

## The modes

The **range** is what every other mode plays over: the held notes (the track's
128-bit held-note bitmap, `0x40598728 + 16 * track`) times RNG + 1 octaves. Its
N entries are numbered `j = rank + H * octave`, H the held-note count, rank the
note's place among the held notes counted from the lowest.

- **SHUF** plays every entry of the range once per cycle, in a new random order
  each cycle. Per track, a record keeps which entries this cycle has played
  (1,024 bits, enough for 128 notes x 8 octaves). A new cycle holds out the
  entry the last one ended on for its first draw, so the boundary never repeats
  a note (unless the range is one note long). A change in N (a note added or
  let go, RNG turned) starts a new cycle.
- **RAND** draws an entry of the range on every step, repeats allowed.

Both hand the stock tail (`0x4002a376`) a note index and an octave (state
`+28`), exactly as UP does, so the octave, the step's note offset and the rest
behave as in every mode. LEN, the step mask (a muted step rests and does not
advance) and the step counter all run before the dispatch; N.LEN and SPD are the
ISR's, not the step's. None of it is new code.

## Randomness

A private **xorshift32** (13, 17, 5), one generator for all tracks, in RAM
above BSS. The firmware's `rand()` (`0x40150670`, state `0x405cd95c`) is not
called or touched. The generator is **stirred with the millisecond tick**
(`0x466758b0`) each time an arp starts on SHUF or RAND (the step's arp id at
state `+24` changes when the held set is started afresh), so two boots, or two
chords, do not replay the same sequence. A zero state (xorshift's one fixed
point) is replaced by a constant before stepping. The bits drawn are the top 16,
scaled to the range by a multiply, never a modulo.

## RAM

`0x467a0000`, above BSS, which the boot clear does not reach, so it holds
whatever was there at power-up. Nothing relies on it being zero: a record is
reset whenever its arp id differs from the step's, and SHUF's search starts the
cycle over if a record's bits do not agree with its count.

| offset | size | what |
|---|---|---|
| `+0` | 4 | the generator's state |
| `+16 + 144 * track` | 4 | the arp id the record belongs to |
| | 4 | N the cycle was drawn over |
| | 4 | the last entry played (-1: none) |
| | 4 | how many this cycle has played |
| | 128 | the entries this cycle has played, one bit each |

2,320 bytes in all. No other mod uses `0x467a0000..0x467a0910`: bootscreen
`0x46710000`, lfowaves `0x46740000`-`0x46780000`, arpplocks `0x467c0000`, lfo4
`0x46800000` and up.
"""

from __future__ import annotations

import json
import pathlib
import re
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.patch.assemble import assemble, available  # noqa: E402

MAIN_OS = 3
BASE = 0x40000400
STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
OUT = ROOT / "out/arpmodes/section_3_MAIN_OS.bin"
RANGES = ROOT / "out/arpmodes/arpmodes.ranges.json"

# The arp step (0x4002a0bc) and where its cases start.
DISPATCH = 0x4002A13C                   # moveq #3,%d0; cmp.l %d4,%d0; beq.w DOWN; bra.w CYCL
DISPATCH_STOCK = bytes.fromhex("7003b0846700 00c6 6000 0144".replace(" ", ""))
DOWN, CYCL, TAIL, REST = 0x4002A208, 0x4002A28A, 0x4002A376, 0x4002A39A
TICK = 0x466758B0                       # the millisecond tick global
RAM = 0x467A0000
REC, REC_BASE = 144, 16                 # per-track record: 16 B header + 1,024 bits
RAM_BYTES = REC_BASE + 16 * REC
MODE_MAX = 6                            # SHUF 5, RAND 6; CHRD 7 stays out

# The five `moveq #4` that bound MODE, each a whole instruction.
BOUNDS = [
    (0x4004BEFA, "7404", "the menu edit (setMode): the upper test"),
    (0x4004BF00, "7204", "the menu edit (setMode): the clamp"),
    (0x4004BFB4, "7004", "FUNC+ARP restore: the upper test"),
    (0x4004BFC6, "7204", "FUNC+ARP restore: the clamp"),
    (0x400DD530, "7404", "stored-sound LOAD: the upper test (above it loads as OFF)"),
]

# Read, not written: the step's register contract at the hook, and its tail.
CONTEXT = [
    (0x4002A114, "1029015f", "the step reads MODE from its sound (a1 +351)"),
    (0x4002A11A, "7900", "... and sign-extends it into d4"),
    (0x4002A12C, "2401", "d2 = track ..."),
    (0x4002A130, "e58a", "... x 4, the track's first bitmap word"),
    (0x4002A132, "45f940598728", "a2 = the held-note bitmaps"),
    (0x4002A0F4, "22680020", "a1 = the state's sound (+32)"),
    (0x4002A10C, "2610", "d3 = the step counter, which the tail's offset reads"),
    (DOWN, "7003", "DOWN starts with moveq #3,%d0"),
    (CYCL, "2401", "CYCL starts with move.l %d1,%d2"),
    (TAIL, "4a806d22", "the tail: a negative index rests"),
    (TAIL + 4, "2228001c", "... the octave from +28"),
    (0x4002A38C, "75290166", "... the step's offset from +358"),
    (REST, "70ff", "a rest"),
    (0x40029F7C, "2010", "the note set's reset moves the arp id (+24) on"),
    (0x4011F5E4, "52b9466758b0", "the tick: addq.l #1 in its interrupt"),
]

# Two clean runs (`dnfw cave scan`: no reference, no stride), each entered 4 B
# in and left 4 B short. The first is the tail of the run midiarp and arpplocks
# already execute from on the instrument (0x402d0664, 896 B): midiarp ends at
# 0x402d0872, arpplocks at 0x402d08b8, the run at 0x402d09e4.
CAVE = (0x402D08C0, 288)
CAVE2 = (0x4028FCB4, 128)               # the run 0x4028fcb0, 136 B

SOURCE = f"""
| Entered from the step's dispatch (0x4002a13c) for MODE > 1, not 2. Live:
| a0 the arp state, a1 the sound, a2 the held-note bitmaps, d1 the track,
| d2 4 x track, d3 the step counter, d4 MODE. The stock tail wants d0 the note
| index (0..127) and +28 the octave, with a0, a1 and d3 as they came.
arpmodes:
    moveq   #3,%d0
    cmp.l   %d4,%d0
    bne.s   1f
    jmp     {DOWN:#010x}
1:  subq.l  #5,%d4
    moveq   #1,%d0
    cmp.l   %d4,%d0
    bcc.s   2f                  | 5 SHUF (d4 0), 6 RAND (d4 1)
    jmp     {CYCL:#010x}        | 4, 7, anything else: CYCL, as stock
2:  lea     %a2@(0,%d2:l:4),%a2 | the track's four bitmap words
    moveq   #0,%d5              | H, the notes held
    moveq   #12,%d6
3:  move.l  %a2@(0,%d6:l),%d0
    bra.s   5f
4:  addq.l  #1,%d5
    move.l  %d0,%d7
    subq.l  #1,%d7
    and.l   %d7,%d0             | the lowest bit cleared
5:  bne.s   4b
    subq.l  #4,%d6
    bpl.s   3b
    tst.l   %d5
    beq.s   rest
    mvs.b   %a1@(353),%d6       | RNG
    addq.l  #1,%d6
    bgt.s   6f
    moveq   #1,%d6
6:  move.l  %d5,%d7
    muls.w  %d6,%d7             | N, the range: H x (RNG + 1)
    lea     {RAM:#010x},%a3     | +0 the generator
    move.l  %d1,%d0
    muls.w  #{REC},%d0
    lea     %a3@({REC_BASE},%d0:l),%a4  | the track's record
    move.l  %a0@(24),%d0
    cmp.l   %a4@,%d0
    beq.s   7f
    move.l  %d0,%a4@            | a new arp: a new record
    moveq   #-1,%d0
    move.l  %d0,%a4@(8)         | nothing played yet
    clr.l   %a4@(4)             | N 0: SHUF starts a cycle
    move.l  {TICK:#010x},%d0
    eor.l   %d0,%a3@            | the millisecond it started stirs the generator
7:  move.l  %d7,%d6
    tst.l   %d4
    bne.s   9f
    jmp     @shuf@
9:  bsr.s   draw                | RAND: any entry, repeats allowed
    bra.s   play

rest:
    jmp     {REST:#010x}

| d6 = r (1..65535) -> d0 uniform in 0..r-1. The generator at a3 steps once.
| Clobbers d1, d2.
draw:
    move.l  %a3@,%d0
    bne.s   1f
    move.l  #0x2545f491,%d0     | xorshift's fixed point is zero: never step it
1:  move.l  %d0,%d1
    moveq   #13,%d2
    lsl.l   %d2,%d1
    eor.l   %d1,%d0
    move.l  %d0,%d1
    moveq   #17,%d2
    lsr.l   %d2,%d1
    eor.l   %d1,%d0
    move.l  %d0,%d1
    lsl.l   #5,%d1
    eor.l   %d1,%d0
    move.l  %d0,%a3@
    clr.w   %d0
    swap    %d0                 | the top 16 bits
    mulu.w  %d6,%d0
    clr.w   %d0
    swap    %d0                 | x r / 65536
    rts

| d0 = j, an entry of the range; d5 = H. -> the stock tail with the note and
| its octave, as UP leaves them.
play:
    divu.w  %d5,%d0             | low: octave, high: rank
    move.l  %d0,%d6
    swap    %d6
    mvz.w   %d6,%d6
    mvz.w   %d0,%d0
    move.l  %d0,%a0@(28)
    moveq   #-1,%d0
8:  addq.l  #1,%d0
    moveq   #127,%d1
    cmp.l   %d0,%d1
    bcs.s   rest                | past note 127: the bitmap moved under us
    move.l  %d0,%d1
    lsr.l   #5,%d1
    move.l  %a2@(0,%d1:l:4),%d1
    btst    %d0,%d1
    beq.s   8b
    subq.l  #1,%d6
    bpl.s   8b
    jmp     {TAIL:#010x}
"""

SOURCE2 = """
| SHUF, from the first cave: a4 the record, d7 = d6 = N, d5 = H, a3 the
| generator. Record: +4 N of this cycle, +8 the last entry, +12 how many this
| cycle has played, +16 one bit per entry played.
shuf:
    moveq   #-1,%d4             | the entry held out of this draw: none
    cmp.l   %a4@(4),%d7
    bne.s   1f
    sub.l   %a4@(12),%d6        | r, what this cycle has left
    bgt.s   3f
1:  move.l  %d7,%a4@(4)         | a new cycle: nothing played
    clr.l   %a4@(12)
    moveq   #31,%d1
2:  clr.l   %a4@(16,%d1:l:4)
    subq.l  #1,%d1
    bpl.s   2b
    move.l  %d7,%d6
    move.l  %a4@(8),%d0         | the entry the last cycle ended on,
    cmp.l   %d7,%d0
    bcc.s   3f                  | (none, or outside this range)
    moveq   #1,%d1
    cmp.l   %d7,%d1
    beq.s   3f                  | (a range of one plays it anyway)
    move.l  %d0,%d4             | ... is held out of the first draw
    bsr.s   mark
    subq.l  #1,%d6
3:  jsr     @draw@
    move.l  %d0,%d6             | k: the k-th entry not yet played
    moveq   #-1,%d0
4:  addq.l  #1,%d0
    cmp.l   %d7,%d0
    bcc.s   1b                  | past N: the record disagrees with itself, start over
    move.l  %d0,%d1
    lsr.l   #3,%d1
    btst    %d0,%a4@(16,%d1:l)
    bne.s   4b
    subq.l  #1,%d6
    bpl.s   4b
    move.l  %d4,%d1
    bmi.s   5f
    move.l  %d1,%d2
    lsr.l   #3,%d2
    bclr    %d1,%a4@(16,%d2:l)  | the held-out entry is this cycle's again
5:  bsr.s   mark
    addq.l  #1,%a4@(12)
    move.l  %d0,%a4@(8)
    jmp     @play@

| Entry d0 played this cycle. Clobbers d1.
mark:
    move.l  %d0,%d1
    lsr.l   #3,%d1
    bset    %d0,%a4@(16,%d1:l)
    rts
"""


def check(content: bytes, va: int, want: bytes, why: str) -> None:
    have = bytes(content[va - BASE:va - BASE + len(want)])
    if have != want:
        raise SystemExit(f"{va:#010x}: expected {want.hex()}, found {have.hex()} ({why})")


def _assemble(source: str, at: dict, cave: tuple[int, int], labels: tuple[str, ...]) -> tuple[bytes, dict]:
    """-> (payload, {label: address}); `@name@` resolves to another cave's label."""
    text = re.sub(r"@(\w+)@", lambda m: f"{at.get(m.group(1), cave[0]):#010x}", source)
    table = "\n    .align 2\n" + "\n".join(f"    .long {n}" for n in labels) + "\n"
    blob = assemble(text + table, base=cave[0])
    payload = blob[:-4 * len(labels)]
    return payload, dict(zip(labels, struct.unpack(f">{len(labels)}I", blob[-4 * len(labels):])))


def code() -> tuple[bytes, bytes, dict]:
    """-> (cave 1, cave 2, labels). Two passes: each cave names the other's labels."""
    at: dict = {}
    for _ in range(2):
        one, found1 = _assemble(SOURCE, at, CAVE, ("arpmodes", "draw", "play"))
        at.update(found1)
        two, found2 = _assemble(SOURCE2, at, CAVE2, ("shuf", "mark"))
        at.update(found2)
    return one, two, at


def compose(stock: bytes, log=print) -> dict:
    if not available():
        raise SystemExit("no m68k assembler found (m68k-linux-gnu-as; WSL is fine)")
    content = bytearray(stock)
    log("part 1 -- the code this relies on, asserted")
    for va, want, why in CONTEXT:
        check(content, va, bytes.fromhex(want), why)
        log(f"  {va:#010x}  {want:<14}  {why}")

    log("part 2 -- the caves")
    one, two, at = code()
    caves = []
    for (cave, cap), payload in ((CAVE, one), (CAVE2, two)):
        if len(payload) > cap:
            raise SystemExit(f"cave at {cave:#010x} overflows: {len(payload)} > {cap}")
        if any(content[cave - BASE - 4:cave - BASE + cap + 4]):
            raise SystemExit(f"cave at {cave:#010x} is not free")
        content[cave - BASE:cave - BASE + len(payload)] = payload
        caves.append((cave, len(payload)))
        log(f"  {len(payload)} of {cap} bytes at {cave:#010x}")

    log("part 3 -- the dispatch")
    check(content, DISPATCH, DISPATCH_STOCK, "the dispatch's tail: 3 DOWN, else CYCL")
    hook = bytes.fromhex("4ef9") + struct.pack(">I", at["arpmodes"]) + bytes.fromhex("4e71") * 3
    content[DISPATCH - BASE:DISPATCH - BASE + len(hook)] = hook
    log(f"  {DISPATCH:#010x}  {DISPATCH_STOCK.hex()} -> {hook.hex()}")

    log("part 4 -- the MODE bounds, 4 -> 6")
    for va, want, why in BOUNDS:
        check(content, va, bytes.fromhex(want), why)
        content[va - BASE + 1] = MODE_MAX
        log(f"  {va:#010x}  {want} -> {content[va - BASE:va - BASE + 2].hex()}  {why}")
    return {"content": bytes(content), "caves": caves, "at": at, "hook": (DISPATCH, len(hook))}


def main() -> int:
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    stock = load(read_image(STOCK)).container.find(MAIN_OS).unpack()
    built = compose(stock)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(built["content"])
    # The changed runs, for the emulator harnesses' --ranges (out/mkranges.py's format).
    content, ranges, i = built["content"], [], 0
    while i < len(stock):
        if stock[i] != content[i]:
            j = i
            while j < len(stock) and stock[j] != content[j]:
                j += 1
            ranges.append({"va": hex(BASE + i), "hex": content[i:j].hex()})
            i = j
        else:
            i += 1
    RANGES.write_text(json.dumps({"ranges": ranges}))
    pathlib.Path(str(RANGES) + ".at").write_text(
        json.dumps({k: hex(v) for k, v in built["at"].items()}))
    print(f"wrote {OUT.relative_to(ROOT)} and {RANGES.relative_to(ROOT)}; labels "
          + ", ".join(f"{k} {v:#010x}" for k, v in sorted(built["at"].items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
