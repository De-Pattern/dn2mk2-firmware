# W2: every control on page 1, Waverider's own names, and the scanner

**Opened 2026-10-11, at the owner's request:** *"i want to make sure we get all the
parameters in here properly before anything"*, and *"the lfo page for this machine
has to reflect the new params. right now, its set to the wavetone engines params"*.
Built: `waverider-w2_DN2_1.11.syx`. Not yet flashed.

Grades: **[D]** read statically, **[E]** measured in an emulator, **[H]** on the
instrument, **[O]** open.

## Page 1, as a player meets it

    TUNE   LEV    POS    TBL
    ~~~~~~~~~~~~ the wave ~~~~~~~~~~~~
    [========|=====================]
    RATE   MPOS   MLEV   MOVE

| control | what it does | range | default |
|---|---|---|---|
| TUNE | pitch, ±5 octaves | as WaveTone's | 0 |
| **LEV** | the oscillator's level; 100 is unity, 127 is +2 dB | 0..127 | 100 |
| POS | position in the table (glides ~21 ms, W5) | 0..120 | 0 |
| TBL | the table, by name (`PRIM`, `VOX`, …) | 0..127 over the tables (9 since v0.7) | `PRIM` |
| **RATE** | the scanner's speed, 0.05 Hz to 30 Hz, exponential | 0..127 | 0 |
| **MPOS** | how far the scanner sweeps POS, ± (centre: none; ±50 sweeps the whole table) | -50..+50 | 0 |
| **MLEV** | how much the scanner moves the level, ± (+: dips as the shape falls; -: as it rises) | -50..+50 | 0 |
| **MOVE** | the scanner's shape, its name on the page: `TRI SAW RAMP SQR RND S&H ONE ENV` | 8 shapes | `TRI` |

**The scanner** is a modulator inside each voice, separate from the three LFOs.
Every note restarts it. `TRI`, `SAW`, `SQR`, `RND` and `S&H` swing both ways around
POS. `RAMP` is unipolar and repeats. `ONE` and `ENV` are one-shots: `ONE` rises once
and holds at the top, `ENV` falls once and holds at the bottom. So MLEV + `ENV` is a
decay, and MPOS + `ONE` is a sweep through the table on every note. `RND` glides
between random values once a cycle, and `S&H` steps between them.

**Defaults change nothing.** With MPOS and MLEV at their centre and LEV at 100, the
DSP adds exactly 0 to POS and multiplies by exactly 1.0, so a W5 sound plays bit for
bit as it did (`test_w2_defaults_change_nothing`).

## Which records carry them, and why these [D]

Waverider still has no parameter records of its own: each control sits on a WaveTone
record (option C, `docs/waverider-m7-pages.md`), whose value the frame already
carries to the DSP. The first plan used MOD (0..3) and RSET (0..2) for MLEV and
MOVE. They cannot hold a ± depth or eight shapes, and widening them would change
WaveTone. So each control sits on a record whose range fits, and osc 2's records
(TUN2, WAV2, LEV2, PD2, OFS2) stay free for page 2:

| control | record | id | slot | frame offset | range, default |
|---|---|---|---|---|---|
| LEV | LEV1 *Osc1 Level* | 241 | 30 | 228 + 146t | 0..0x7f00, 0x6400 |
| RATE | ATK *Noise Attack* | 253 | 40 | 248 + 146t | 0..0x7f00, 0 |
| MPOS | OFS1 *Osc1 Lin Offset* | 246 | 28 | 224 + 146t | 0..0x6400, 0x3200 |
| MLEV | PD1 *Osc1 Phase Dist* | 240 | 29 | 226 + 146t | 0..0x6400, 0x3200 |
| MOVE | NLEV *Noise Level* | 256 | 43 | 254 + 146t | 0..0x7f00, 0 |

Each record's id is its index in the parameter dump plus one (`RECORD(id)` in
`page.c`), checked against the slot the dump prints.

## Waverider's names everywhere: the LFO and MOD lists [D, E]

**What draws a name [D].** The destination list's row label (`0x40105a6c`) asks the
parameter set for the **long name** (a virtual call, vtable +88 → `getLongName`
`0x400365c8`, which reads `record + 0x28`), and falls back to `GROUP:SHORT` (the
short name read straight from `record + 0x30` at `0x40105b72`) when the long one is too
wide. Eleven places read `+0x30` directly, the LFO page's DEST field
(`0x4010758a`) among them. Hooking each one would mean eleven hooks.

**What W2 does instead.** The record table is in RAM. While the active track is a
Waverider, `wr_names` (`page.c`, called from `wr_poll` once a UI pass) points the
`+0x28` and `+0x30` name pointers of WaveTone's records at Waverider's names. As soon
as the active track is anything else, it puts the stock pointers back. It writes only on
a change. So every reader, stock or not, sees TBL / *Wave Table* where it saw DRIF /
*Osc Drift*. The header line, the LFO and modulation destination lists, and the DEST
field all follow.

| record | short | long |
|---|---|---|
| TUN1 | TUNE | Tune |
| LEV1 | LEV | Wave Level |
| WAV1 | POS | Wave Position |
| DRIF | TBL | Wave Table |
| ATK | RATE | Scan Rate |
| OFS1 | MPOS | Scan Pos Depth |
| PD1 | MLEV | Scan Lev Depth |
| NLEV | MOVE | Scan Shape |
| WaveTone's other 17 | - | Unused |

**Is that table writable on the instrument? [D]** The startup writes ACR0 =
`0x4007e020` (`0x40000564`): base 0x40, mask 0x07, so 0x40000000-0x47ffffff, enabled,
with **the write-protect bit (bit 2) clear**. That range includes MAIN OS. The firmware
also writes inside it itself, e.g. `move.b %d0,0x4058aee0`. So this works on the
hardware, not only in the emulator, which models no ACRs.

**What it fixes.** The table jump the owner saw on W5 (2026-10-11) came from an
existing LFO aimed at *Osc Drift*, which W5 had turned into TBL without the list
saying so. Now that entry reads *Wave Table*.

**Dropped: a sticky TBL.** Hysteresis at the table edges was considered, so that an
LFO nudge at a boundary would not flip the table. It was dropped because the DSP's
table would then depend on its history, and the page, which reads the value, would
sometimes show a different table from the one playing. LFO on TBL is a feature
(Tonverk sweeps tables too). It only needed a name.

## The DSP side [D, E]

`machine5_live.asm`, after the W5 glide (`dnfw.waverider.live` is the contract,
operation by operation, float32):

1. read LEV1, ATK, OFS1, PD1 and NLEV from the frame copy;
2. on the voice's note (TRIG_NOTE bit t): phase 0, not done, the next random value;
3. the shape's `u` (0..1) and `s` (bipolar shapes `2u - 1`, unipolar `u`) from
   `phase >> 8` × 2^-24;
4. the phase advances by `RATE`'s step (a 128-entry u32 table, 30 Hz is 50 blocks a
   cycle); a wrap finishes a one-shot and takes the next random value;
5. POS = trunc(clamp(float(glided POS) + s × MPOS × 983040, 0, 983040));
6. after the reader has filled the track buffer, each sample is multiplied by a gain
   ramped from the last block's to this one's (no zipper at 30 Hz): `LEV ×
   (1 - MLEV (1 - u))` for MLEV ≥ 0, `LEV × (1 + MLEV u)` below.

State: 16 words a voice at `0x2df900`. Tables: RATE (`0x2dfd00`), LEV (`0x2dff00`),
256 random floats (`0x2e0100`). The loop grew to 2,258 bytes, in a span of `0xa00` at
`0x2def00`. All of it stays below `0x2e0500`, inside L1 block 1's free tail, which
held M5c's tables up to `0x2e5600` on the instrument.

Budget: section 7 is **1,029,596 of 1,048,575** bytes, so 18,979 are left.

## The sample slicer: any short WAV to a wavetable

`dnfw waverider slice voice.wav -o voice_wt.wav [--preview sweep.wav]`
(`dnfw.waverider.slicer`), after Tonverk's own:

- **window** is Tonverk's rule: fixed frames (2,048 samples, or `_wt1024` in the name).
  Here they are spread over the whole sample instead of taken from its start.
- **pitch** finds the period at each frame's position (autocorrelation, refined at full
  rate) and cuts exactly one cycle there, from a rising zero crossing. A voice or a synth
  note becomes a table of its own waveforms, playable at any pitch.
- **auto** (the default) uses pitch where the sound is periodic and window where it is
  not.
- Every frame is band-limited to 48 partials, as the factory set is, and the table is
  normalised as a whole.

It writes a standard float32 wavetable WAV, which `dnfw waverider bake` reduces to
Waverider's 16 × 512. Putting the user's tables into a flashable build is a later step:
each table is 16 KB, and only ~1 fits beside the 11 factory ones until compression
lands.

## Gates

`scripts/ship_gate.py` on the exact file (CLAUDE.md). Results are in the build's
`.gate.json` and summarised in the README.

## On the instrument: what to check (W2 test)

1. **Low volume.** The usual USB flash. Have the proven DIN recovery cable at hand.
2. A W5 sound: it sounds exactly as before (the defaults change nothing).
3. Page 1 shows all eight: LEV, then RATE, MPOS, MLEV and MOVE (with the shape's name).
4. MPOS up with RATE ~60 and MOVE `TRI`: the timbre sweeps through the table. Try
   `ONE` (a sweep per note), `RND`, `S&H`.
5. MLEV up with MOVE `ENV`: each note decays. MLEV down with `SQR`: a gate.
6. The LFO page on a Waverider track: DEST lists *Wave Table*, *Wave Position*,
   *Scan Rate*, … and the 17 *Unused*. A WaveTone track: WaveTone's names, unchanged.
7. Regression check, `docs/SAFETY.md`.

## Unverified [O]

- The scanner's CPU cost on the SHARC with 16 voices: about 150 instructions a voice a
  block more, plus the 32-sample gain pass.
- That nothing outside the UI keeps a record's name pointer across a track change
  (only draws were found reading them).
