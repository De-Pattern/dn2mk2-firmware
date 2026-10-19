# W3: Waverider's osc 2 (page 2)

**Opened 2026-10-19, at the owner's request:** *"osc2 on waverider would be nice, im
considering abandoning that to free up space but we should finish page two anyway for
now if it doesnt cost us a detrimental amount of space, just so we have it to go back to
later as a working option."*

Grades: **[D]** read statically, **[E]** measured in an emulator or the SHARC runner,
**[H]** on the instrument, **[O]** open.

## Page 2, as a player meets it

    DETN   LEV    POS    TBL
    ~~~~~~~~ osc 2's wave ~~~~~~~~
    [====|=========================]
    -      MPOS   MLEV   -

| control | what it does | record | default |
|---|---|---|---|
| DETN | osc 2's pitch against osc 1's, ±60 semitones (TUNE moves both) | TUN2 242 | 0 |
| **LEV** | osc 2's level; **0 is off**, 100 is unity | CHAR 260 | 0 |
| POS | osc 2's position in its table (glides as osc 1's) | WAV2 243 | 0 |
| TBL | osc 2's table, by name | BASE 257 | `PRIM` |
| MPOS | how far osc 1's scanner sweeps osc 2's POS, ± | OFS2 250 | centre |
| MLEV | how much the scanner moves osc 2's level, ± | PD2 244 | centre |

**One scanner.** RATE and MOVE are osc 1's (page 1). Osc 2 has its own depths, so the
scanner can sweep the two oscillators apart, together or against each other. E and H
are empty on page 2.

**Off by default, and free when off.** Osc 2's level sits on a WaveTone record whose
default is 0 (CHAR, *Noise Character*), so every Waverider sound saved before W3 plays
bit for bit as it did. With LEV at 0 the DSP skips osc 2 outright: no second reader,
no extra cost. Turned up with a note already sounding, it ramps in from silence over
one block.

The names follow the active track as page 1's do (`wr_names`): the LFO and modulation
lists say *Osc2 Detune*, *Osc2 Level*, *Osc2 Position*, *Osc2 Table*, *Osc2 Pos Depth*
and *Osc2 Lev Depth*.

## The DSP side [E]

`dnfw.waverider.live.render_blocks` is the contract (`Osc2`, `detuned`, `osc2_gain`):

1. after osc 1 is in the track's buffer, with its gain ramp, machine5_live.asm jumps to
   `wr_osc2` (osc2.asm) instead of going straight to the next track;
2. LEV 0: the gain rests at 0; back to the loop;
3. otherwise osc 2's POS glides like osc 1's, the shared scanner's `s` moves it by MPOS;
   TBL goes through the same TBL → slot table and directory; its pitch is osc 1's note
   (after TUNE, at most 127) plus DETN, through the same increment table;
4. `wr_render5` (the same reader) renders osc 2's 32 samples into a buffer of its own;
5. the buffer is added into the track's, ramped from the last block's gain to this one's
   (LEV × the scanner's level through MLEV, as osc 1's);
6. back to the loop's `wr_t5v_next`.

**Where it lives.** L1's free tail is nearly full, so the routine is in two pieces in
two gaps: osc2.asm (742 bytes) after reader_m5's code at `0x2dd7a0`, osc2b.asm (480
bytes) in the tail of PING's code span at `0x2e1a40`. Its per-voice state (phase, glide,
gain; 16 × 16 bytes) and its 32-sample buffer sit in the gap after the increment table
(`0x2de480`), its reader block and four scratch words in the state block's free words.
The jumps between the objects are addresses; the decode step of the SHARC gate and
`test_w3_osc2.py` check that each lands on its label.

**What it costs.** +707 bytes of the USB upgrade budget (19,178 left). On the SHARC,
nothing while LEV is 0; with osc 2 on, a second reader pass a voice (the reader is
about 38 instructions a sample).

## Checked [E]

- The SHARC runner, step 3: three new runs, bit-exact to the model like every other:
  osc 2 a fifth up on the last table swept by the scanner (`w3_osc2`); the same sound
  with LEV 0 as its control (`w3_off`, which must differ); LEV turned up mid-note
  (`w3_late`, the first blocks bit for bit the LEV-0 sound's).
- Decode: osc2.asm and osc2b.asm read as their sources to digikit and selmap; the
  cross-object jumps land on their labels.
- The emulator: page 2 shows DETN, LEV, POS, the table's name, then `-`, MPOS, MLEV,
  `-`, with osc 2's wave across the middle; each encoder moves its indicator, TBL its
  name and the wave.

## Open [O]

- How it sounds on the instrument, and the SHARC load with eight voices of two
  oscillators.
- Osc 2's own RATE and MOVE (a second scanner) would need two more 0..127 records;
  HOLD and DEC are the candidates, both defaulting to the top.
