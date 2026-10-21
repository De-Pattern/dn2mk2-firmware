# PERC: the owner's drum machines as machine type 5 (v0.11, v0.12)

PERC replaces Waverider. MACHINE SEL offers **Perc** after Swarmer (type 5, Waverider's
slot; every one of the engine's eight machine-lookup entries is in use, so a new machine
takes an old one's place). A PERC track plays one of **24 drum machines**, chosen with
TYPE:

| family | machines |
|---|---|
| TRX (analog models) | BD, B2, SD, XT, CP, RS, CB, CH, OH, CY, MA, CL, XC |
| EFM (FM) | BD, SD, XT, CP, RS, CB, HH, CY |
| GND (basics) | SN (sine), NS (noise), IM (impulse) |

The machines are the owner's own, from his Ravel firmware
([De-Pattern/Ravel_FM1](https://github.com/De-Pattern/Ravel_FM1), `firmware/app/rv_perc.c`,
GPL-3.0): designs after the Elektron Machinedrum's TRX, EFM and GND machines. The modal
P-I machines are not ported.

## The pages

| page | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| 1 | p1 | p2 | p3 | p4 | p5 | p6 | p7 | p8 |
| 2 | TYPE | AMD | AMF | EQF | EQG | FLTF | FLTW | FLTQ |

**Page 1 is the machine** (v0.12; v0.11 had TYPE on A and p8 alone on page 2): its eight
synthesis parameters, named per machine (`dnfw.perc.machines.PNAMES`: TRX-BD's are PTCH
DEC RAMP RDEC STRT NOIS HARM CLIP). A parameter a machine lacks is labelled `-` and has no
indicator. **Page 2 is TYPE and the Machinedrum's track effects**, as Ravel has them
(`rv_perc.c perc_render`), the same for every machine and all off at their defaults:

| | what | range |
|---|---|---|
| AMD | amplitude modulation depth | 0 (off) .. full |
| AMF | its rate | 0.1 Hz .. 2.3 kHz |
| EQF | the EQ band's frequency | 40 Hz .. 19 kHz |
| EQG | its gain (centre 0 dB) | -18 .. +18 dB |
| FLTF | the band filter's base: a high pass from 20 Hz up (0 = off) | 20 Hz .. 20 kHz |
| FLTW | its width: a low pass at base + width (127 = off) | |
| FLTQ | the filters' resonance | q 0.5 .. 12.5 |

The middle of the page shows the machine (`TRX-BD`), what it is (`Bass Drum`) and a dot
row with the machine's place among the 24. The names are swapped in the record table
itself (`wr_names`, `csrc/waverider/page.c`), so the header's value line and the LFO
destination lists use them too. **v0.12 fix:** the names follow TYPE as the page reads it
(`GET_VALUE`); v0.11 read the sound's target array, which on the instrument did not follow
TYPE, so every machine showed one machine's names.

Every PERC control is a WaveTone record, so every one is p-lockable and an LFO
destination like any WaveTone parameter, and SAVE/LOAD keep them:

| place | record (WaveTone) | frame slot | value read |
|---|---|---|---|
| p1 | 238 TUN1 | 25 | `(v >> 8) - 4`, over 120 |
| p2 | 242 TUN2 | 31 | as p1 |
| p3 | 254 HOLD | 41 | `v >> 8`, over 127 |
| p4 | 241 LEV1 | 30 | over 127 (ATK until v0.12) |
| p5 | 256 NLEV | 43 | over 127 |
| p6 | 257 BASE | 44 | over 127 |
| p7 | 260 CHAR | 47 | over 127 |
| p8 | 240 PD1 | 29 | over 100 |
| TYPE | 252 DRIF | 38 | `(min(v >> 8, 127) * 24) >> 7` |
| AMD | 239 WAV1 | 26 | over 120 |
| AMF | 246 OFS1 | 28 | over 100 |
| EQF | 250 OFS2 | 34 | over 100 |
| EQG | 244 PD2 | 35 | over 100 (0.5: 0 dB) |
| FLTF | 243 WAV2 | 32 | over 120 |
| FLTW | 258 WDTH | 45 | over 127 |
| FLTQ | 253 ATK | 40 | over 127 |

A note latches the machine TYPE names at that moment: turning TYPE while a hit rings
changes the labels at once and the sound at the next note. A track that stops being PERC
has its voice silenced (v0.12): coming back to PERC, it waits for a note (v0.11 resumed
whatever it had left ringing, heard once as a short ring). The parameters are read every
32-sample block. Selecting PERC gives the WaveTone records' defaults, not the per-machine
defaults the Ravel firmware had; the PERC voice reads the knobs wherever they are.

## On the DSP

One program, written once (`src/dnfw/perc/`):

- `dsl.py` -- a `Prog` that either **emits** SHARC assembly or **runs** the same
  instruction on a float32 register file and memory, with the SHARC's semantics.
- `machines.py` -- the shared primitives (tables, exp2, sine, reciprocal, noise, the
  TPT state-variable filter, envelopes) and the machines' parameters and names;
  `kit.py` -- each machine's setup and the eleven shared per-sample loops.
- `program.py` -- one slot's block (`voice`) and the 16-slot loop (`program`).
- `live.py` -- a harness that runs the model the way the DSP holds its memory.

`scripts/gen_perc_asm.py` writes `csrc/waverider/sharc/perc.asm` from it (about 4,200
instructions, 19.4 KB) and resolves its branches with selas's own layout.

**Where it runs.** PERC's code is too big for the free tail of L1 block 1, so it runs
from **L2 at `0x200c0000`** (sw `0xbe0000`), through the I-cache the startup enables.
`scripts/sharc_l2_ceiling.py` records what L2 the stock firmware touches (`docs/data/l2-ceiling-2026-10-20.json`), from a fresh
engine init (5.0 M instructions) and every stock machine on all 16 tracks: reads
`0x2002f0d0..0x20078256`, writes `0x2002f0d0..0x200779f8`, **nothing above the stock
image's end `0x2008823c`**. PERC's 64 KB span sits 230 KB above that and 200 KB below
the startup's non-cacheable window `0x200fa000..0x200fdfff`. Its voices' state (16 x 128
bytes, `0x2de180`) and scratch (`0x2dde80`) are in L1, its tables (6 KB, `0x81216000`)
in DDR beside the others, and it reads SHFT's sine table.

**Entry and exit.** The block counter (`block_count.asm`), which the entry JUMP at
`0x1c9448` reaches every block, now jumps to `0xbe0000`. PERC saves R0-R15, I0-I5, I12
and M0-M4 at `0x2dde00` exactly as Waverider's loop did, renders every type-5 track, and
jumps to RESONATOR (`0x172980`), then CZ, then PING, whose tail restores them and rejoins
the chain at `0x1c944c`. Its subroutines return with a plain `JUMP (M14, I12)` (not the
compiler's delayed return form, which the runner reserves for real calls).

**What it costs.** The model counts every instruction it executes: 30 to 280 a sample,
by machine (`EFM-RS` the most). Sixteen PERC tracks of the heaviest machine would be
about 220 M instructions a second.

## Checks

- **The DSP against the model, bit for bit** (`sharc_waverider_m5.py` step 3, in the ship
  gate): at PERC's entry each block the runner runs `dnfw.perc.program` on the DSP's own
  memory, then compares every type-5 track's buffer and voice state when PERC hands on.
  Runs: all 24 machines at the owner's defaults (eight PERC tracks at once), a note an
  octave up, a retrigger, TYPE turned mid-note, every parameter at its top and at its
  bottom, every track effect on, a track leaving PERC while it rings and coming back
  (silent), and no note (silence). Steps 4-9 (stock machines and filters unchanged, PING,
  SHFT, GRAN, RESONATOR, CZ) run with a PERC track 0 as their source.
- **The model against the owner's C** (`test/test_perc_live.py`): peak within 8 %, the
  10 ms envelope within 0.8-1.25x, the zero-crossing rate within 25 %, for every machine,
  against `test/data/perc_c_reference.json` (the C compiled at 48 kHz, each machine at
  its Ravel defaults). The track effects against Ravel's formulas in float64 with libm's
  tan and sin (within 8 % of the peak; the AM rate's table exp2 drifts its phase slowly).
- `test/test_waverider_dsp.py`: the L2 placement, the saves, the registers PERC writes.
- `test/test_waverider_pages.py`: the pages, the per-machine names, TYPE's mapping
  agreeing with the DSP's.

## Known limits

- Several machines peak above 1.0 at their defaults (TRX-CB 1.75, GND-IM 1.76, TRX-MA
  1.6), as they do in the owner's C. The DN2's chain is floating point, so this is
  headroom for the track's level and the filter, not a clip in PERC itself.
- The DSP's load in L2 has not been measured on the instrument.
- P-I machines are not ported.
