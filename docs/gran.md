# GRAN: a granular effect in the filter slot

**Owner, 2026-10-19:** *"granular effect is next on the list. so you can continue with
that too without checking in with me first."* Built the SHFT way: filter type 8 on
the FLTR page, on any machine, with a float32 contract (`dnfw.grain.live`) the SHARC
code is held to bit for bit.

Grades: **[D]** designed, **[E]** measured in the emulator or the SHARC runner, **[H]** on
the instrument, **[O]** open.

## What it is

Each track set to GRAN records what its machine plays into a ring buffer of its own,
0.68 s long, and plays it back as a stream of short grains. Up to four play at once,
and each one reads a stretch of the recent past through a smooth window, at its own
speed. Short grains with no scatter give a shimmering echo of the note. Long grains
read backwards turn it inside out. With scatter and feedback it becomes a cloud that
smears and builds on itself.

    FLTR page 1   FDBK  -    MIX  -   /  SIZE DENS MODE SPRD
    FLTR page 2   DRIV  .    .    -   /  BASE WDTH BW.RT RSET

| control | record | what it does |
|---|---|---|
| SIZE | Frequency | a grain's length, 10 .. 160 ms, exponential |
| DENS | Resonance | how many grains overlap, 1 .. 4: a new one starts every SIZE / DENS |
| MODE | Filter Type | NORM (as played), UP (an octave up), DOWN (an octave down), REV (backwards); its name shows in the cell |
| SPRD | Env. Depth | how far back, at random, each grain starts: none at the centre, up to 0.34 s at either end |
| FDBK | Attack Time | 0 .. 0.9 of the grains written back into the buffer, soft-clipped |
| MIX | Sustain Level | dry .. wet |
| DRIV | Env. Delay | the level into the buffer, 0.4 .. 2.0 |

**MIX starts at the sustain's value**, which for Multi-Mode's default is 0, so a track
switched to GRAN is still dry until MIX is turned up (SHFT does the same).

BASE and WDTH (the filter page's second, fixed band filter) still apply after it.
Decay, release and key tracking do nothing on GRAN and read `-`.

## How [D]

- **The buffer.** 32,768 float32 a track, in the DSP's DDR at `0x81400000 + 128 KB t`,
  zeroed at boot (a fill block, so it costs the upload almost nothing).
- **A grain.** It starts `64 + (UP ? L : 0) + r x SPRD x 16384` samples behind the
  write head, `r` the next of Waverider's 256 random values (the same table the
  scanner's RND uses), and moves by its rate each sample (1, 2, 0.5 or -1), read with
  linear interpolation. Its window is the parabola `4x(1 - x)` over its L samples.
- **The scheduler.** A new grain every `L / DENS` samples, in the next of four slots,
  so the oldest is stolen. The sum is scaled by `1 / sqrt(DENS)`.
- **Out.** What is written back is `x DRIV + FDBK knee(wet)`. What comes out is PING's
  ceiling on the wet signal, mixed with the dry as SHFT mixes it.

**Where it lives.** GRAN's 2.2 KB of code needed L1 room, and the free tail was full
after osc 2. PING's and SHFT's tables (7.3 KB, read-only) moved to DDR, next to CZ's
and RESONATOR's. GRAN's code took PING's old table space (`0x2e2540`) and its state
took SHFT's (`0x2e4b00`, 16 × 128 bytes). PING jumps to `wr_gran` for a type-8 track,
and `wr_gran` jumps back to PING's next track; both jumps are checked against the
objects' layouts. PING and SHFT are re-held to their models with the tables in DDR:
same values, same bits.

**What it costs.** +2,848 bytes of the USB budget (16,350 left). On the SHARC, only
while a track is on GRAN: about 150 instructions a sample a track with four grains
sounding.

## Checked [E]

- SHARC runner, step 7b: three pairs of tracks over 24 blocks (768 samples), every GRAN
  track bit-exact to `dnfw.grain.live`, with the buffer carried from block to block.
  The pairs are NORM beside UP with feedback, DOWN with full scatter beside REV, and
  GRAN with full feedback beside SHFT. SHFT beside it stays bit-exact to its model,
  and every other track passes through unchanged.
- Steps 6 and 7: PING and SHFT still bit-exact, now reading their tables from DDR.
- `test_gran_live.py`:
  - MIX 0 is the dry signal bit for bit;
  - grains start at the density's rate and stay bounded at full feedback and scatter;
  - UP reads an octave up and DOWN an octave down;
  - the longest delay fits the buffer;
  - the layout fits;
  - the cross-object jumps land on their labels.
- The emulator: a track on filter 8 shows FDBK - MIX - / SIZE DENS MODE SPRD, MODE
  reads NORM / UP / DOWN / REV, and page 2 reads DRIV and `-` for KEY.T.

## Open [O]

- The sound on the instrument, and the SHARC load with several tracks on GRAN.
- A FREEZE (stop writing, keep playing the buffer), and the envelope driving SIZE or
  SPRD, are the natural next controls. Decay and release are free for them.
