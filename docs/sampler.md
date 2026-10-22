# The Digitakt II's sample machines on the DN2 (v0.13)

The Digitone II and the Digitakt II are the same board and one codebase; what makes a
Digitakt a sampler is its sample machines, a sample pool in the DSP's memory, and the
ColdFire's sample manager (`docs/dt2-port-map.md`). This is the first part of putting
them beside the DN2's own machines: the machines themselves, on the DSP, playing from a
pool in the DSP's DDR.

## What v0.13 has

MACHINE SEL gains a section after PERC, RESONATOR and CZ:

| type | machine | in v0.13 |
|---|---|---|
| 8 | **ONESHOT** | plays |
| 9 | WERP | a row, not offered (needs the tempo) |
| 10 | STRETCH | a row, not offered (needs the tempo) |
| 11 | REPITCH | a row, not offered (needs the tempo) |
| 12 | **GRID** | plays |

The pool holds **four test sounds**, made by `dnfw.sampler.live.test_samples` (no one's
recordings): 1 KICK, 2 SNARE, 3 HAT, 4 BEAT (sixteen steps of the three, for GRID).
Loading your own samples is the next part.

## The pages

One page each, as the Digitakt II's SRC page (DT2 1.17's parameter descriptors,
`dnfw.sampler.machines.PAGES`):

| machine | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| ONESHOT | TUNE | PLAY | SAMP | CFAD | STRT | LEN | LOOP | LEV |
| GRID | TUNE | PLAY | SAMP | GRID | SLCE | LEN | - | LEV |

- **TUNE** ±60 semitones around the note (C4 plays the sample at its own pitch).
- **PLAY** REV, REV LOOP, FWD LOOP, FWD (the DT2's order; FWD is the default).
  FWD LOOP loops between LOOP and the end; REV LOOP starts at the end, plays back to
  LOOP, and loops between them (DT2 manual, Appendix A).
- **SAMP** 0 is OFF (no sound, as on the DT2); 1..4 the pool's sounds; a slot the pool
  does not hold is silent.
- **STRT / LEN** where the sound starts and how much of it plays; **LOOP** the loop point.
- **GRID** 4, 8, 16, 32 or 64 equal slices; **SLCE** which one; **LEN** how many
  consecutive slices.
- **LEV** the sample's level (100 = as recorded).
- **CFAD** (ONESHOT) is drawn but not yet heard.

The page shows the machine and the sound in the middle, and the sample as a bar: the
part that plays solid, LOOP's point marked in the loop modes, GRID's slices ticked.

## How it works

- **The DSP** (`dnfw.sampler.program`, written by `scripts/gen_smp_asm.py` to
  `csrc/waverider/sharc/smp.asm`): entered from PERC's tail, on to RESONATOR. Its code
  is in L2 at `0x200d0000` (sw `0xbe8000`), after PERC's 64 KB span, well below the
  non-cacheable window; its 16 voices' state (64 bytes each) and scratch in L1
  (`0x2def00`, Waverider's old loop room). Per voice: the region and loop are latched at
  the note; pitch and level follow the knobs every block; linear interpolation between
  frames, an integer position and a float fraction.
- **The machine lookup.** The engine maps the frame's machine field through a table
  (v0.13: a 16-entry copy at `0x2dee04`). Types 8..12 map to **5**, PERC's engine slot:
  the record's copy of that answer (`+0x1b4`) indexes 8-entry tables in the stock code
  (sw `0x1c299f`, the render code), so an answer of 8 or more would read past them. Slot
  5 is the one path through the stock code the runner and the instrument have already
  proven for PERC. PERC and the sample machines then tell themselves apart by the
  frame's own type word (`148 + 2t`), not the record.
- **The pool** is in the DSP's DDR at `0x84000000` (64 MB in; the stock program claims
  about 5 MB of a 512 MB part): a directory (magic `SMP1`, count, 128 entries of
  address, frames, rate, spare), then each sound's float32 frames. The test sounds are
  24 kHz (BEAT 12 kHz), each entry's rate scaling its step, to keep the upgrade file small.
- **The ColdFire** (`dnfw.waverider.coldfire`, `pages`, `csrc/waverider/page.c`): types
  5..12 are WaveTone clones (one range check in each shim); the name table, attribute
  rows and LOAD bound grow to 12; MACHINE SEL's group function puts 8..12 in a section
  of their own; the page renderer moved to a CODE chunk of its own at `0x46a00000`.
- A sample machine with no renderer yet (WERP, STRETCH, REPITCH) has its buffer
  cleared each block: silent, never a stale block.

## Checked

- `scripts/sharc_waverider_m5.py` step **3b** (in the ship gate): every sample track's
  buffer and state bit-exact to `dnfw.sampler.program` run on the DSP's memory at its
  entry, every block of nine runs; ONESHOT's KICK matches the sound itself (error
  < 1e-5); TUNE +12 is higher; reversed, looping and GRID tracks sound; PERC beside them
  stays bit-exact; WERP's buffer is 0; OFF, an empty slot and no trigger are silent; a
  second note restarts.
- Step 4: tracks 1-15 bit-identical to stock with track 0 on ONESHOT or WERP.
- The ship gate's SAVE/LOAD: types 8 and 12 round-trip; 13 loads as FM Tone.
- `test/test_waverider_dsp.py`, `test_waverider_mod.py`, `test_waverider_pages.py`.

## Next

1. **Your samples**: a way to put sounds in the pool (an upload tool and the ColdFire
   writing them through to the DSP) and to keep them (the eMMC).
2. WERP, STRETCH and REPITCH, which need the tempo on the DSP side.
3. CFAD.
