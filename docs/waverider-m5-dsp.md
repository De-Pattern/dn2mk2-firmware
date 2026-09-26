# Waverider Milestone 5, the DSP half: the section 7 a flashable build ships

**2026-09-26, offline.** What `dnfw.waverider.dsp.section7(stock)` does to DN2 1.11's
section 7, why, and what the runner gate (`scripts/sharc_waverider_m5.py`) measured.
The ColdFire half (the machine list, the names, sending type 5, the mod) is in
`docs/waverider-feasibility.md`, Milestone 5. Four readings from Milestones 3 and 4
are corrected here, and each correction is marked where the claim was made.

```
python scripts/gen_waverider_sharc.py [--assemble]        # objects -> sharc_code.json
python scripts/sharc_waverider_m5.py \
    --digikit D:/01_Code/Z_Personal/digikit-wt-sharcemu [--blocks 8] \
    [--frame FILE | --frame-be FILE | --frames PATTERN]
python -m pytest test/test_waverider_dsp.py
```

## What the builder does

| edit | where | bytes |
|---|---|---|
| `reader_m5.asm` (`wr_render5`) | PM sw `0x180000`, byte `0x300000` | 374 |
| `machine5_live.asm` (`wr_type5v`) | PM sw `0x180200`, byte `0x300400` | 758 |
| state: save area, loop counter, 16 reader blocks (zeros) | DM `0x301000` | 1,024 |
| increment table, 129 float32 | DM `0x301400` | 516 |
| wavetable directory (`WRT1`, 2, `0x302000`, `0x306000`) | DM `0x301800` | 16 |
| table 0: a 32-harmonic saw darkening to a sine (`testtable`, frames reversed) | DM `0x302000` | 16,384 |
| table 1: the overtone series, frame k = partial k+1 (`harmonics`) | DM `0x306000` | 16,384 |
| entry: `JUMP 0x180200` + the firmware's 16-bit NOP, over `i5=dm(-0x18,i6); r10=dm(-0x22,i6)` | sw `0x1c9448` | 8 |
| machine lookup `0x25d748[5]`: 0 -> 5 | DM `0x25d75c` | 4 |

Every added span is its own boot block, inserted before the final block, and is
checked to lie outside every block of the stock stream (loaded or filled). Both
patched words are checked to be stock first. Section 7 grows from 836,956 to
872,524 bytes (sha256 `bb3ca2eb...158c3dff`).

**Not done, on purpose:** the clamp `min(R2, 4)` at `0x1c294c` stays stock, and the
per-type setup table `0x8052db90` is not touched. Both are corrections, below.

## Four corrections to Milestones 3 and 4

### 1. The tables were placed in a hole, not in memory

~~The spans M1-M4 used (DM `0x280000`, `0x284000`, `0x28c000`, `0x290000`) are
unloaded by the boot stream~~ -- true, and the reason is that **they are not
memory**. The loaded image fills L1 block 0 from `0x2403f0` exactly to
`0x26f000`, and the startup code puts the system stack right after it:
`b7=0x26f000; i7=0x26f7f0; l7=0x1fd` at sw `0x1c0eae`. That is the shape of the
standard ADSP-21569 layout, whose L1 is four blocks of 192, 192, 128 and 128 KB at
`0x240000`, `0x2c0000`, `0x300000` and `0x380000` **[D]**: `0x270000..0x2c0000` is a
gap between block 0 and block 1, which digikit's findings also call "probably not
memory at all". The runner models flat memory, so M1-M4 read their tables back; the
silicon would not have. **[D]** -- the block sizes are from the part's published
total (640 KB) and this image's own boundaries, not from a datasheet in the repo.

M5 puts everything in **L1 block 2** (`0x300000..`), which the stream loads nothing
into, and where the code already was (sw `0x180000` is byte `0x300000`). What else
the image says about block 2:

- no instruction in the L1 or L2 code loads an address in `0x300000..0x320000` (or
  its normal-word or short-word forms) as an immediate -- the two `data32` hits are
  a bit mask (`0x300000` at sw `0x1cb5d5`, ANDed) and a compare constant
  (`0x180000` at sw `0x1c5012`); no loaded data word points there either;
- the stack is in block 0 (above); FreeRTOS's heap and the task stacks are static
  arrays inside the stream's fill blocks;
- block 3's code ends at `0x39bffc`, 16 KB short of the block's end, which is where a
  16 KB cache would be carved; the startup enables caches (`SHL1C_CFG` bits 8 and
  14, `0x4100` as read statically from `sw 0xb8b93a`, written through `sw 0x1c0272`)
  and marks `0x28240000..0x2839ffff`
  (all of L1) non-cacheable. **Where the second cache is carved is not known.** If
  it is block 2's top, it is `0x31c000..0x31ffff`, which M5 leaves untouched; our
  spans end at `0x30a000`.

So block 2's lower 112 KB is **free by every static test available [D]**, and not
proven free at run time: a DMA descriptor or a pointer computed at run time could
still reach it. This is the first-flash risk that a crash at boot would point to.

### 2. The clamp at `0x1c294c` is not the machine-type clamp

~~the per-track selector clamp `min(R2, 4)` ... raised to `min(R2, 5)`~~ (M3). Run
through the unpack with a type-5 frame, the clamp sees R2 = 0; set the frame's
per-track field at offset `84 + 2t` to 3 and it sees 3. Its input is that field
(the ColdFire's per-track byte `0x80003af0 + 153t + 3470`, not identified), and the
value it clamps indexes 512-word records at `0x8045a6c8`. The machine type reaches
record `+0x1b4` through the lookup `0x25d748[nibble]` alone: with the stock clamp
and the lookup patched a type-5 frame gives 5; without the lookup patch it gives
0. M3's control fed R2 = 5 by hand, so it proved the arithmetic, not the role.
**Raising the clamp would let that other field index a sixth record past its
table**, so M5 leaves it stock.

### 3. Type 5 never reads past the per-type setup table

~~Type 5's per-type setup ... with type 5 it reads the next table's first word~~
(M4). The dispatch compares the type with 5 before it indexes `0x8052db90`:

```
1c9056  r2 = dm(-0xc, i0)          ; record +0x1b4, the machine type
1c905b  r15 = 0x5
1c905d  compu(r2, r15)
1c909f  if ge jump (pc, 0x35) (db) ; -> 0x1c90d4
1c90a6  i4 = 0x8052db90
1c90a9  i12 = dm(m4, i4)           ; m4 = the type
1c90b0  jump (m13, i12)
```

The table's five entries are code addresses: `0x1c90b2` FM Tone, `0x1c91dc`
WaveTone (calls `sw 0x1c694a`, then `sw 0x1c6757` and `sw 0x1c6c13`), `0x1c920b` FM
Drum, `0x1c922f` Swarmer, and `0x1c90d4` for MIDI, which is also where the bound
sends type 5. The next word, `0x1c927e`, is the first entry of the filter-setup
table `0x8052dba4`. **Measured:** for a type-5 track the guard sees R2 = 5 and the
next event is `0x1c90d4`, on every block; the table read at `0x1c90a9` never runs
for it. Type 5 takes MIDI's no-setup arm, which is correct for a machine that needs
no setup, so the table is not edited.

WaveTone's own arm was the planned source of pitch. It was not used: in the runner,
WaveTone's osc 1 increment (state word 4) stays 0 through its setup and render even
with a note triggered, while the note does arrive (state word 191 = 60.0 / 72.0), so
where WaveTone turns a note into an increment was not found. M5 computes the pitch
itself (below).

### 4. A type-5 track's machine parameters are not in its record

M4's field map was measured with a zeroed frame, whose machine type is 0: record
`+0x0..+0x98` is **FM Tone's** conversion of parameters 25..64. With machine type 1
or 5 the same window does not move for any value of params 26-30 (WaveTone puts its
own elsewhere; type 5 has no unpack at all). What the unpack does keep is the frame
itself: `sw 0x1c2712` copies the 2,688-byte image to `0x25c48c`, verbatim (0 words of
672 differ), and it is still there when the dispatch runs. `machine5_live.asm`
reads WAV1 and TBL1 from that copy.

## How the parameters reach the loop

| | read from | used as |
|---|---|---|
| POS = `WAV1` (param 26) | frame copy `0x25c48c + 220 + 146t`, 16-bit LE | `min(WAV1, 0x7800) << 5`, Q16 frames (0x7800 is frame 15; the fine byte counts) |
| SLOT = `TBL1` (param 27) | frame copy `+ 222 + 146t` | `TBL1 >> 8`, through the directory; >= count plays 0 |
| pitch | note cell `0x254b14 + 4t` (engine `+0x1387c`), float semitones | clamp 0..127, `inc = trunc(T[k] + fr (T[k+1] - T[k]))`, T = 440 * 2^((k-69)/12) Hz as a u32 step at 48 kHz |
| phase | the track's reader block `0x301100 + 32t` | carried from block to block |

The frame offsets of an even track put WAV1 in the low half of a word and TBL1 in
the high half; an odd track's straddle two words; the loop handles both without a
branch. Nothing about the pitch uses `TUN1`, portamento or the ColdFire's keyboard
tracking beyond what the ColdFire already folds into the trig note -- that is a
known gap, not a finding.

## Instruction forms: what the first flash may contain

The Milestone 1 reader was "only forms the firmware itself uses", checked against
digikit's decoder. Checked against **selache's own disassembler** as well, it was
not:

- `R3 = DM(I0, M0)` (reader.asm's frame-row dummy read) is the 16-bit Type 3c
  parcel `0x9013`, which selmap reads as `daddr=dm(0x3e,i0)`, and
  `R3 = DM(I1, M1)` as `i14=dm(0x3,i1)`; the inner loop's `R4 = DM(M2, I0)` reads as
  `dm(m6, i0)`. selas, digikit and selmap cannot all be right, and the firmware
  gives no tie-break: of its 1,266 Type 3c accesses, 1,250 set the parcel's bit 8
  and name M4-M7 (selmap reads the other 16 as immediate-offset forms), and, as
  selmap reads the image, no Type 3a/3c access names DAG1 M0-M3 at all.
- Outside a DO loop, selas compresses the pre-modify `R4 = DM(M4, I0)` to the same
  parcel as the post-modify `R4 = DM(I0, M4)` (`0x9114`), which updates I0 -- the
  M4 finding, now seen to apply to any pre-modify, not only through M1.

So the M5 code avoids both: no DAG1 M0-M3 in any memory access, pre-modify reads
only inside the DO loop (where selas emits the 48-bit Type 3a both decoders read
alike), addresses by byte arithmetic and `In = Rn` (the firmware's own idiom:
`r1 = r4 + r1` at `0x1c9259`, a byte offset on the engine pointer), and every add
with a low first register written with R8-R15 first so no 16-bit parcel in
`0xc000..0xc07f` appears (digikit's G5). **Step 1 of the gate checks every
instruction of both files: selmap's text, normalised, equals the source line, and
digikit's length equals selas's, on selas's own boundaries.** That is agreement of
three toolchains, not silicon.

The entry JUMP is selas's `JUMP 0x180200;` (`8a_abs`, 48-bit), the same form as the
firmware's `jump 0x1c0000` at sw `0x1c1311`; the NOP is the firmware's own parcel.

## The gate

Run of 2026-09-26: `--blocks 8 --frame-be out/waverider/m5_test_frame_be.bin`,
digikit `6f812e9`, CPython 3.13 on a shared machine, **PASS on all 26 checks**,
554 s. About 154.5 k instructions a block. Nothing is poked into a voice block and
the entry is the image's own JUMP; the only harness inputs are frame images.

| step | measured |
|---|---|
| decode | 0 disagreements over both files (selas boundaries, digikit length, selmap text vs source); entry `8a_abs` 48-bit + `21c` 16-bit NOP |
| map | WAV1/TBL1 read back verbatim from the frame copy at 5 (track, param) points; the record window unchanged; note cell 60.0 / 72.0 / 60.5; type 5 with the stock clamp; clamp R2 follows field 84 (3 in, 3 seen; init frame R2 = 0, R0 = 4); without the lookup 0; our 7 spans 0 word mismatches after init |
| voice, init sound (note 60, WAV1 0, TBL1 0) | loop entered 8/8 blocks; setup: the no-setup arm after the type-5 guard on 8/8; reader block `table 0x302000, inc 23,409,860, pos 0, count 32`; machine tap 0 float32 mismatches in 256; amp out peak 0.066, rms 0.034; fit to the ideal through the chain r = 0.934 (gain 0.072, SNR 8.3 dB) |
| POS 120 | 0 mismatches; spectral centroid 410 Hz vs 735 Hz at POS 0 |
| TBL1 1 (WAV1 0x4000) | 0 mismatches; table pointer `0x306000` |
| note 72 (POS 120) | 0 mismatches; inc 46,819,720 = 2 x 23,409,860 exactly; zero crossings 5 vs 2 in the same 256 samples |
| no trigger | amp out peak 0.0031 |
| stock | M5 image with no type-5 track vs the stock image: all 16 buffers bit-identical over 4 blocks; with track 0 type 5, tracks 1-15 bit-identical to stock |
| caller frame (BE, swapped) | tracks 0 and 5 type 5, both 0 mismatches (note 48 / WAV1 0x3000 / TBL1 1 and note 60 / WAV1 0x6000 / TBL1 0) |

**The stock-identity control is weaker than it looks.** Compared as bit patterns
(the runner's FM Tone voice on track 2 produces NaN, and NaN != NaN), and it holds;
but in this frame setup the stock voices on tracks 1-4 put out -0.0 or NaN, not
audio. So it proves our code writes nothing into other tracks' buffers and the
chain runs identically, not that a playing FM Tone is unchanged by ear. The loop
touches no stock state beyond the track buffers of type-5 tracks, the registers it
restores, and the stack slots of its own call.

**The correlation through the chain (0.93) is lower than M4's (0.987)** because the
init sound is now the bright saw, which the per-track filter and DC blocker shape
more than M4's sine-ish sweep; the machine tap itself is exact.

### The WAVs

All in `out/waverider/`, 48 kHz 16-bit mono. LOOPED ones are 256 rendered samples
(8 blocks) repeated to 2.5 s; each has a PREVIEW, the float32 reference that is
bit-exact to the runner's machine tap, rendered over the whole file.

| file | what |
|---|---|
| `m5_voice_amp_out.wav` (+ `_normalised`) | the init Waverider voice at the amp's output, LOOPED |
| `m5_voice_machine.wav` / `m5_preview_init_sound.wav` | the saw, machine tap (LOOPED) / PREVIEW |
| `m5_pos120_machine.wav` / `m5_preview_pos120.wav` | POS 120: the sine (0.555 peak: the table is normalised as a whole) |
| `m5_slot1_machine.wav` / `m5_preview_slot1.wav` | TBL1 1, WAV1 0x4000: partials 9-10 |
| `m5_note72_machine.wav` / `m5_preview_note72.wav` | the sine an octave up |
| `m5_no_trigger.wav` | control, silent (LOOPED) |
| `m5_demo_pos_sweep_preview.wav` | DEMO PREVIEW, 4 s: note 48, slot 0, POS 0 -> 120: saw darkening to sine |
| `m5_demo_harmonic_climb_preview.wav` | DEMO PREVIEW, 4 s: note 48, slot 1, POS 0 -> 120: the overtones climbing |
| `m5_frame_machine.wav`, `m5_frame_amp_out.wav`, `m5_preview_frame.wav` | the caller's frame (LOOPED / PREVIEW) |

## What is unverified, for the first flash of modified SHARC code

- **Silicon.** Nothing here has run on a DSP. The runner is a model with eleven
  documented workarounds (G1-G11).
- **Block 2 at run time** (correction 1): free by every static test, not proven.
- **Instruction encodings** agree across selas, digikit and selmap for every
  instruction shipped; none of the three is the silicon.
- **Byte addressing.** The loop and reader do byte arithmetic on byte-address
  pointers and index words through the DAG, as the firmware does; the runner's
  address model (`assume_nw32`) is what was run.
- **The frame copy** is read inside the dispatch; that it is not refilled by DMA
  while the dispatch runs is an inference from the unpack copying it first.
- **Pitch** is our own equal-tempered table, not WaveTone's: `TUN1`, fine tune and
  portamento beyond the trig note's fine byte are not applied.
- **The ColdFire's frame**: what reaches offsets 220/222 + 146t for a type-5 track
  on the instrument (WaveTone's page, per the ColdFire design) is the parent's
  emulator measurement, not this one's.
