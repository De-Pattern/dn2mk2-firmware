"""Bound a song's row count on load, so a damaged project opens instead of halting.

## The stock bug this closes

Stock 1.11's song `LOAD` (`0x400dea6a`) reads the stored song's row count as a
signed word at stored `+2891`, writes it to the live song at `+3679`, and then
copies that many 29-byte stored rows into 37-byte live rows. It never checks the
count. Both records hold **99** rows -- `(2891 - 20) / 29` and `(3679 - 16) / 37`
are exactly 99 -- so a count above 99 copies past the song into whatever
follows it.

Project 4 on the owner's instrument, `SKETCHPAD`, carries a count of **21,503**
(`0x53ff`) in its first song record (the table is at image `+0xc3ee04`, 3,072 B per
record; in storage version 4 the count is the u16 at record `+0x147`, so image `+0xc3ef4b`).
Opening it copies 795,611 bytes from `project + 0x11e4d1d`: through the other
sixteen songs, the project settings (which is how the current pattern becomes
`-1`), past the end of the 18,977,747-byte project object, and 580 KB into the
BSS after it -- where the first two RTOS tasks keep their control blocks and
stacks (`0x424388ac`, `0x4243c900`). The exception screen that follows reads a
frame from a stack pointer that is now song data.

**This is stock behaviour, not a mod's.** `scripts/emu_project_load.py --full`
runs the firmware's own open-project routine (`0x40042b92`) on the project:
stock, `fxmod+lfo4` and `lfowaves+moddest+midiarp` take the identical fault at
the identical instruction, and all three open cleanly when that one field is
repaired to 0 and nothing else is changed (2026-09-26).

## What it changes

One in-place rewrite of 54 bytes at `0x400deac2`, the song `LOAD`'s header copy,
into the same 54 bytes with the bound added. No cave, no hook, nothing appended.

| stock | now |
|---|---|
| `count = (s16) stored[2891]` into `%d0`, stored to the live song | the same, into `%d2`, then **`count > 99` (unsigned, so negatives too) becomes 0** before it is stored |
| two byte copies, `stored[2898..2899] -> live[3692..3693]` | one word copy of the same two bytes |
| after the row clear, the loop bound reloaded from the live song into `%d1` | taken from `%d2`, which the row clear leaves alone (`%d2` is saved by `LOAD`'s own prologue and first used by the loop) |

A song with 0..99 rows loads exactly as before. A song whose count is out of
range loads as an empty song with its other fields intact, rather than being
allowed to overwrite the machine. That is the same tolerance stock shows every
other record: a converter that finds a record it cannot trust keeps the project
loading.

Because the clamped value is what is stored in the live song, playback and a
later save see 0 too -- the damage does not travel with the project.
"""

from . import Extent, ModError, Result

ID = "songguard"
NAME = "Song guard"
SUMMARY = "Bound a song's stored row count on load, so a damaged project opens instead of halting."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SITE = 0x400DEAC2
ROWS = 99                          # both the stored and the live song hold 99 rows

# Stock 1.11, 0x400deac2..0x400deaf8, as `out/main111.dis` reads it.
STOCK = bytes.fromhex(
    "716b0b4b"          # mvs.w  2891(%a3),%d0        the stored count
    "25400e5f"          # move.l %d0,3679(%a2)        -> the live song
    "156b0b4d0e67"      # move.b 2893(%a3),3687(%a2)
    "256b0b4e0e68"      # move.l 2894(%a3),3688(%a2)
    "156b0b520e6c"      # move.b 2898(%a3),3692(%a2)
    "156b0b530e6d"      # move.b 2899(%a3),3693(%a2)
    "48780e4f"          # pea    0xe4f
    "486a0010"          # pea    16(%a2)
    "4e94"              # jsr    (%a4)                 clear the 99 live rows
    "508f"              # addq.l #8,%sp
    "222a0e5f"          # move.l 3679(%a2),%d1        the loop bound
    "4280"              # clr.l  %d0
    "41eb0014"          # lea    20(%a3),%a0          the first stored row
)
NEW = bytes.fromhex(
    "756b0b4b"          # mvs.w  2891(%a3),%d2
    "7063"              # moveq  #99,%d0
    "b480"              # cmp.l  %d0,%d2
    "6302"              # bls.s  1f                   0..99 kept; above, or negative, ->
    "7400"              # moveq  #0,%d2               an empty song
    "25420e5f"          # 1: move.l %d2,3679(%a2)
    "156b0b4d0e67"      # move.b 2893(%a3),3687(%a2)
    "256b0b4e0e68"      # move.l 2894(%a3),3688(%a2)
    "356b0b520e6c"      # move.w 2898(%a3),3692(%a2)  the two byte copies, as one
    "48780e4f"          # pea    0xe4f
    "486a0010"          # pea    16(%a2)
    "4e94"              # jsr    (%a4)
    "508f"              # addq.l #8,%sp
    "2202"              # move.l %d2,%d1              the bound, clamped
    "4280"              # clr.l  %d0
    "41eb0014"          # lea    20(%a3),%a0
)
assert len(NEW) == len(STOCK) == 54


def extents(firmware=None) -> list[Extent]:
    return [Extent(SECTION, SITE - BASE, len(NEW), "song LOAD: bound the row count")]


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original = section.unpack()
    at = SITE - BASE
    # Longer is fine: data appended after the stock end moves nothing here.
    if len(original) < at + len(STOCK) or original[at:at + len(STOCK)] != STOCK:
        raise ModError(f"0x{SITE:08x} is not stock; this mod is for Digitone II 1.11, "
                       "or another mod already wrote there")
    content = bytearray(original)
    content[at:at + len(NEW)] = NEW
    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=[f"a song's stored row count above {ROWS} loads as 0 instead of "
                         "overwriting memory",
                         "1 in-place edit of 54 B in section 3, nothing appended"])
