# W5: many wavetables, a smooth POS, and a display that follows what you hear

**Opened 2026-10-11, at the owner's request,** after Waverider played on his unit:
*"only 2 wavetables"*, *"the sound is very stepped between waves"*, and the wave
display *"very choppy … intermittent when playing back p-locked or live motion
recorded wavetable movements"*. Built: `waverider-w5_DN2_1.11.syx`. Not yet flashed.

Grades: **[D]** read statically, **[E]** measured in an emulator, **[H]** on the
instrument, **[O]** open.

## What changed, as a player meets it

| | before (M7) | W5 |
|---|---|---|
| tables | 2, in DSP L1 | **11**, in the DSP's DDR (`dnfw.waverider.factory`) |
| TBL | WaveTone's `TBL1` (0..1) | WaveTone's `DRIF` (0..127), its travel shared evenly between the tables |
| TBL's label | `TBL` | the **table's name** (`VOX`, `SYNC`, …) |
| POS | the frame's value, taken as is each block | **glides** ~21 ms per voice; a new note starts exactly on its POS |
| the wave display | knob + LFO offset; redraws only on modulation, ≤ 24 fps | the value **heard** (p-lock, recorded motion, LFO); redraws when it changes, ≤ 30 fps |

The factory set, in TBL order: `PRIM` (saw → sine, M5's table 0), `HARM` (the
overtone series, M5's table 1), `PWM`, `SYNC`, `VOX`, `FM`, `FOLD`, `ORGN`, `RESO`,
`BITS`, `PHAS`. All original, generated, band-limited to 48 partials. Slots 0 and 1
are M5's two tables, so a sound saved on M5 keeps its first table.

## Why the sound stepped [D, E]

The reader interpolates between two waves sample by sample, at full precision
(`csrc/waverider/sharc/reader_m5.asm`). What it was handed was coarse: WAV1 moves in
120 steps over 16 waves, and a p-lock or recorded motion lands once per step. Each
step was one block's jump in timbre. The stock machines smooth their parameters on
the DSP; Waverider did not.

**The glide** (`machine5_live.asm`, `dnfw.waverider.live.glide`): per voice,
`s += (target − s) >> 5` each 32-sample block, a time constant of about 21 ms. In
the block whose frame triggers the voice (TRIG_NOTE, frame offset 34, bit *t*,
read from the copy the unpack makes at `0x25c48c`), `s` is set to the target, so a
note never sweeps in from where that voice last played.

*Tried first and dropped:* track record word 113, which upstream noted as the
dispatch's note counter. In the runner it stays 0 through a trigger, so it could
not serve as a note-on.

## Where the tables live: DDR, measured [E]

- The stock boot stream loads DDR to `0x8052fbe0`. The engine's init writes past
  that, to `0x80530be8` (`scripts/sharc_ddr_ceiling.py`: init from scratch, then
  every stock machine type, with a recorder on every DM access).
- In the runner, one stock dispatch path writes 32-word bursts through a pointer
  the runner never initialises, at scattered addresses from `0x85d7…` to `0x9fc4…`.
  On the instrument that pointer is real (most likely a voice buffer inside the
  image); it cannot be resolved offline.
- **So the tables sit at `0x81000000`**: 11 MB above everything init touches, and
  below the lowest of the runner's stray addresses. `dsp.DDR_FLOOR` (`0x80600000`)
  is a hard floor in the build. The DDR part is a Kingston D2516 DDR3, which I read
  as 512 MB from the part number; that's my reading, not a measurement.
- The M5 gate's "every span we add reads back, after init" now covers the DDR
  tables.

## Budget: the DSP upload buffer

MAIN OS uploads section 7 through two 1 MiB buffers (`0x400cf34c`): it checks the
**stored** size against 1 MiB, depacks after a one-byte header, and checks
**unpacked + 1** against 1 MiB *after* depacking. So the unpacked DSP program must
be at most **1,048,575** bytes, and an overflow would overrun the heap before the
check refused it. `dnfw.safety` enforces exactly that.

| | bytes |
|---|---|
| stock section 7 | 836,956 |
| W5 section 7 | **1,025,436** |
| limit | 1,048,575 |
| margin, for W2–W4's code | 23,139 |

Each 16 × 512 int16 table is 16 KB, so 11 is the default set. A 12th (`SPEC`,
random spectra) is built but left out. More tables need either compression
(decoded by the DSP at init into DDR, where there is room) or delivery from the
+Drive (`docs/waverider-tables.md`); both are later steps.

## Waverider's own controls on WaveTone's records

Waverider has no parameter records of its own. Its controls are WaveTone's, read
by the DSP at their frame offsets (`218 + 2(p − 25) + 146t`). W5 moves TBL from
`TBL1` (param 27, range 0..1) to `DRIF` (param 38, range 0..127) rather than
widening `TBL1`, which a real WaveTone track would then index past its two tables.
Waverider's page labels it, and its value picks a table through the same 128-entry
table the DSP uses (`dsp.slot_lut`, `wr_slot` in `page.c`). WaveTone tracks are
untouched.

**Still WaveTone's names in the LFO/MOD destination list** (owner, 2026-10-11): an
LFO aimed at POS is listed as WaveTone's `WAV1`, at TBL as `DRIF`. Fixing that list
belongs to W2, which gives the remaining controls their records.

## The display [D, E]

- `wave.span_bytes()` (11 tables × 16 frames × 2 × 96 columns = 33,792 bytes)
  outgrew the page's 15 KB chunk. It is now a second platform `CODE` chunk at
  `0x46b00000` (clear of every mod's RAM and of the emulator harness's scratch at
  `0x46a00000`); `page.c` reaches it through a pointer.
- **The two arrays, measured** (emulator, 2026-10-11, `mem` before and after a TBL
  turn): the *target* array (`0x80003af0`) is the live sound. A turn writes it at once
  (`0x0000` → `0x6800`), and a p-lock reaches it while it plays. The *value* array
  (`0x800068e4`) is the audio tick's: the target smoothed, plus every modulator. The
  emulator never runs that tick, and on the instrument it does not follow a turn while
  the sequencer is stopped (upstream's modview2b).
- **So `heard()` is the target, plus the value array's offset only while that array
  is live**, meaning it has moved since the target last did (`live()` in `page.c`).
  During playback that is exactly what is heard, LFO included; stopped, a turn
  shows the knob at once, and a stale difference is never drawn as modulation (the
  markers use the same test).
- **Emulator check of the page** (`scripts/emu_waverider_menu.py` on a snapshot
  made with `scripts/emu_install_snapshot.py`; screens in `out/w5/screens/`):
  WAVERIDER in MACHINE SEL; TBL turned → `RESO`, then `PHAS` at the top, each with
  its wave; a p-lock value written to the target → `FOLD`; a heard value from the
  audio tick → `PHAS` with the modulation marker; a further turn → the knob again;
  POS at the top → FOLD's last frame.
- The redraw signature includes the lock offset, so a p-lock or recorded motion
  asks for a redraw. The cap went from 5 UI ticks (24 fps) to 4 (30 fps). Upstream
  measured a page draw at ~1.4 ms (`docs/modulation-display.md`), so about 4 % of
  the ColdFire while the wave moves, and nothing while it is still.

## Gates (all on this build)

| gate | result |
|---|---|
| `dnfw mods apply` + preflight | PASS: bootstrap, updater, metadata and Outbox untouched; DSP 1,025,436 of 1,048,575 |
| `emu_boot_check` from reset | booted and drew its UI |
| the page in the ColdFire emulator | table names, waves, knob / lock / heard paths as above |
| `sharc_waverider_m5` (SHARC runner) | **all PASS**: bit-exact to `live` in every run; TBL picks table 1 and the last table, both in DDR; the glide matches `live.glide` block by block; a triggered block starts at its POS; types 0–4 bit-identical to stock with and without a Waverider track |
| unit tests | `test_waverider_*`, `test_mods_*`, `test_grains_model`: pass |
| MAIN OS size | 3,230,988 B unpacked, under upstream's M0 build (3,233,040 B, flashed and passed on hardware) |

## On the instrument: what to check (W5 test)

1. **Low volume first.** Recovery cable connected.
2. WAVERIDER on a track, VOICE SETUP > 1 voice. TBL's label shows `PRIM`; turn it
   through all 11 names. Each sounds different, and none is silent or noise.
3. Slow POS sweeps: continuous, no stepping.
4. p-lock POS on a few steps, and record a POS motion: each step lands on its
   value; the display follows playback.
5. An LFO on POS: the wave moves with it.
6. The SAFETY.md regression check: the stock machines, FX, save/reload, a
   power-cycle.
7. If you have the load probe build: SHARC load with 8 Waverider voices held.

## Unverified [O]

- That DDR from `0x81000000` stays untouched on the instrument (emulator-measured,
  with a wide margin).
- The display on the instrument, where the audio tick runs: the arrays' behaviour
  above is measured in the emulator plus upstream's hardware note, not on your unit.
- CPU cost of DDR reads for 16 voices (the reader's table reads went from L1 to
  DDR, through the data cache).
