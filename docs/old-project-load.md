# SKETCHPAD halts a modded build: a stock song overrun, not a mod

**2026-09-26.** The owner opened project 4, `SKETCHPAD`, on
`Digitone_II_OS1.11_fxmod_lfo4.syx` and the instrument drew `EXCEPTION DS0059`,
`V00 M0 P44630000`. The same screen appeared on 2026-09-24 with
`lfowaves-moddest-midiarp` opening a pre-existing project. New projects open.

The two builds share **no mod**. That was the first hint that no mod was the
cause.

## What was measured

`scripts/emu_project_load.py` loads a `+Drive` project (DNX's read-only capture,
`00_Resources/07_DataCapture/projects_4_12890159B.bin`) through the firmware's
own code on a restored `ui1200M`, with each build installed the way its loader
would leave it.

**1. The deserialiser alone (`0x400e1782`) is clean on every build.** Stock,
fxmod, lfo4, moddest, lfowaves, midiarp, fxmod+lfo4 and
lfowaves+moddest+midiarp all return success. They reject exactly the same records
(5 patterns, 6 kits, 144 sounds, 1 song: bad version words, the stock
tolerance). So no mod changes what the converters accept, and the garbage DNX
found in LFO lanes, machine bytes, locks and p-lock headers is either rejected by
a version check or passes through stock and every mod alike.

**2. The whole open routine (`0x40042b92`, `--full`) faults on every build,
including stock.** Same instruction, same trail:

| build | SKETCHPAD, as stored | song 0's row count repaired to 0, nothing else |
|---|---|---|
| stock 1.11 | **fault** at `0x40042cc4`, `jsr (%a0)` with `%a0 = 0` | opens clean |
| fxmod+lfo4 (the owner's file) | **fault**, identical | opens clean |
| lfowaves+moddest+midiarp | **fault**, identical | opens clean |
| project 11 (control), stock | opens clean | -- |

**3. The field.** `SKETCHPAD`'s first song record (song 0, which the
instrument shows as song 1) stores a row count of **21,503**: the 16-bit word
`0x53ff` at image `+0xc3ef4b`.

~~(image `+0xc3e400`)~~: **corrected 2026-09-27 with DNX.** That base was
back-computed from the count using the pre-1.11 field position, which is wrong.
The table did not move in the 1.11 migration. It is at **image `+0xc3ee04`**:
16 records of 3,072 bytes. Within each record, the 1.11 (storage version 4)
migration moved the meta block by `-0xa00`:
- the row count went from `+0xb47` to **`+0x147`**, a u16 big-endian word, as
  the loader reads it;
- the tempo from `+0xb4c` to `+0x14c`.

So `+0xc3ef4b` is song 0 at `+0x147`. The file offset is the image offset plus
31. DNX measured the shift on 15 undamaged records
(`dn_sysex/99_HardwareTest/dn2-sketchpad-2026-09-26/song-geometry-v4.md`), and
the firmware's loader confirms the position. **A file-level repair must use
the version-4 offsets.** The other sixteen
songs, and every song in the 26 other projects in `dn_sysex`, store 0. The older
export `01_Projects/004 SKETCHPAD.dn2prj` stores 0 too; the 2026-09-22 export in
`03_OS111/` stores 21,503, so the damage entered between the two.

**4. The mechanism.** The song `LOAD` (`0x400dea6a`) copies `count` stored
29-byte rows into 37-byte live rows and never checks `count`. Both records hold
99. With 21,503 it writes 795,611 bytes from `project + 0x11e4d1d`: the other
songs, the project settings -- a write watch shows it overwrite the current
pattern at `0x42431a81` with `0xff` from `0x400deb30`, which is why the
activation indexes app object `-1` and calls a null vtable -- then past the end
of the project object into BSS, where the first two RTOS tasks keep their TCBs
and stacks (`0x424388ac`, `0x4243c900`). On the instrument that is a stack
pointer made of song data, which is what the photographed frame looks like.

## The fix

`songguard` (`src/dnfw/mods/songguard.py`): the same 54 bytes of the song
`LOAD`, rewritten with the bound. A count above 99 (or negative) loads as an
empty song; 0..99 loads exactly as before. No cave, no hook, nothing appended,
and it shares no byte with any other mod.

## Confirmed on the instrument -- 2026-09-26

The owner flashed `Digitone_II_OS1.11_fxmod_lfo4_fixed.syx` (fxmod + lfo4 +
songguard, sha256 `120c23a5...0eef`) and opened project 4, SKETCHPAD: **it
opened, with no EXCEPTION screen** (confirmed by the owner). The same project
on the same mods without songguard had halted.

Then, same session (owner): song 1 reads empty and the other songs are intact;
SKETCHPAD re-opens after switching projects; every mod works after the load.

**Playback shows the rest of the damage.** B9 track 4 and B1 track 12 lose their
sound. Read from the capture, not measured on the device:
- B9 track 4's stored sound is shifted by a few bytes (magic `ffffff21` where
  `beefbace` belongs, version `0x00260000`, the name `WOODPECKER` starting 3
  bytes late). The sound `LOAD` rejects it and puts the default sound there. That
  is a stock converter, so every build does the same.
- B1 track 12 has a valid header (`PRESET 12`, version 3), so its silence comes
  from somewhere else -- the pattern's locks or the sound's own values. Not
  traced.

Neither is songguard's business, and neither halts: the guard only stops the one
field that overwrote memory.

## What stays unverified

- **Stock on the instrument.** The emulator says stock 1.11 takes the same
  fault. SKETCHPAD has not been opened on stock since the damage; the
  prediction is that it halts too.
- **The exact screen.** The emulator's fault is the first consequence of the
  overrun (the settings); the instrument got further before something read the
  overwritten task state. The photographed frame is consistent with that, not
  derived from it.
- **Playback.** The emulator runs neither the sequencer nor the engine, so the
  other anomalies in SKETCHPAD are cleared for *opening* only.
- **Where the 21,503 came from.** Not established. It entered after the older
  export and before 2026-09-22.
