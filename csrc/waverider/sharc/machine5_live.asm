// machine5_live.asm -- Waverider Milestone 5: the type-5 render loop a flashable build
// ships. Every voice parameter comes from the firmware's own per-track state; nothing
// is written by a harness.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). It is run offline in digikit's SHARC executor inside the DN2 1.11
// image (scripts/sharc_waverider_m5.py); it has never run on a DSP.
//
// Entered by the JUMP the build writes at sw 0x1c9448 (after the Swarmer render loop
// in sw 0x1c8ef1, before the per-track chain), once per block. It scans the 16 track
// records and, for every track whose machine type is 5, fills that track's reader
// block and calls wr_render5 (reader_m5.asm, sw 0x16eb00) into the track buffer:
//
//   W5 (DN2-mk2-Mod, 2026-10-11): SLOT now comes from WaveTone's DRIF (param 38, 0..127,
//         offset 244 + 146t, the same half-word as WAV1 six words on) through a
//         128-entry TBL -> slot table after the directory (0x2de800), so the knob
//         spreads over every table; and POS glides (below). The text from here to
//         POS describes M5's TBL1 and is kept for the record.
//   SLOT  WaveTone's TBL1 (param 27), read from the frame image the unpack copied to
//         0x25c48c (offset 222 + 146t): 0x0000 or 0x0100, the sound's own value
//         (read on the instrument through the USB probe, 2026-09-30); >> 8 is the
//         slot, resolved through the baked directory; at or above its count plays 0.
//   POS   WaveTone's WAV1 (param 26), from the same copy (offset 220 + 146t): the
//         sound's coarse << 8 | fine, 0..0x7800 (probe: 0x7800 at the knob's top).
//         min(WAV1, 0x7800) << 5 is Q16 frames: 0x7800 << 5 = 15 << 16, frame 15.
//         The unpack does not put a type-5 track's machine parameters in its
//         record (measured), so the frame copy is read.
//         Until 2026-09-30 this read half the sound's value, which the emulator's
//         frames had shown; those frames were caught while the values were still
//         gliding to their targets. On the instrument WAV1 reached the last frame
//         halfway up and TBL1 1 never chose table 1.
//   pitch the engine's note cell, engine +0x1387c + 4t = 0x254b14 + 4t, a float in
//         semitones (note + fine/256), plus TUN1 (Milestone 6): WaveTone's param 25 at
//         offset 218 + 146t, frame word / 256 - 64 semitones (+-60, the display's
//         +-5 octaves). Clamped to 0..127; k = trunc, fr = note - k;
//         inc = trunc(T[k] + fr * (T[k+1] - T[k])) from the baked 129-entry float
//         table T (dnfw.waverider.live.increment_table): 440 * 2^((k-69)/12) Hz as a
//         u32 phase step at 48 kHz.
//   phase kept in the reader block, per track, from block to block.
//   glide (W5) POS reaches the reader through a one-pole per voice: s += (target - s)
//         >> 5 each block (32 samples at 48 kHz: a time constant of about 21 ms), so
//         a knob's coarse steps, a p-lock or a recorded motion no longer step the
//         timbre. s is set to the target outright in the block whose frame triggers
//         this voice (TRIG_NOTE, frame offset 34, bit t), so a new note never sweeps in
//         from where the voice last played. (Track record word 113, tried first, stays
//         0 through a trigger in the runner.) State: 0x2dee00 + 4t (s, Q16).
//
// A directory without the magic renders nothing (the track buffer is left as the
// dispatch left it).
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f780 (L1 block 1, byte 0x2def00;
// 0x16ed00 / 0x2dda00 until W5, when it outgrew that 1 KB slot).
// The absolute targets below are written for that address from selas's own symbol
// table (a labelled reassembly); the gate checks the decoder lands on every
// assembler boundary.
//
// DM (byte addresses, L1 block 1's free tail -- Milestone 5c; M5 used L1 block 2,
// which silenced the instrument, docs/waverider-dsp-silence.md; every byte of the
// region is written by a boot block the build ships, zeros or data):
//   0x2dde00  save area, 28 words: R0-R15, I0-I5, I12, M0-M4
//   0x2dde80  tracks left, 16 - t (the loop counter; every per-track address is
//             computed from it, so no pointer has to survive the reader call)
//   0x2dde84  this track's reader block, 0x2ddf00 + 32 * t
//   0x2ddf00  16 reader blocks of 8 words: wr_render's six (table, phase, inc, pos,
//             count, out), then two spare words. This loop writes all but phase.
//   0x2de200  the increment table, 129 floats
//   0x2de600  directory: +0 magic 'WRT1' (0x57525431), +4 count, +8 table[0], ...
//
// Only forms the firmware itself uses: no DAG1 M0-M3 in a memory access and no
// pre-modify read outside a DO loop (reader_m5.asm says why); addresses are byte
// arithmetic, then `In = Rn`, as the firmware's own code does.

.SECTION/PM seg_pmco;

.GLOBAL wr_type5v.;
wr_type5v.:
      DM(0x2dde00) = R0;
      DM(0x2dde04) = R1;
      DM(0x2dde08) = R2;
      DM(0x2dde0c) = R3;
      DM(0x2dde10) = R4;
      DM(0x2dde14) = R5;
      DM(0x2dde18) = R6;
      DM(0x2dde1c) = R7;
      DM(0x2dde20) = R8;
      DM(0x2dde24) = R9;
      DM(0x2dde28) = R10;
      DM(0x2dde2c) = R11;
      DM(0x2dde30) = R12;
      DM(0x2dde34) = R13;
      DM(0x2dde38) = R14;
      DM(0x2dde3c) = R15;
      DM(0x2dde40) = I0;
      DM(0x2dde44) = I1;
      DM(0x2dde48) = I2;
      DM(0x2dde4c) = I3;
      DM(0x2dde50) = I4;
      DM(0x2dde54) = I5;
      DM(0x2dde58) = I12;
      DM(0x2dde5c) = M0;
      DM(0x2dde60) = M1;
      DM(0x2dde64) = M2;
      DM(0x2dde68) = M3;
      DM(0x2dde6c) = M4;

      I3 = 0x25566c;                    // &track[0].machine (0x2554b8 + 0x1b4)
      I5 = 0x254a60;                    // &track_buffer[0]
      R0 = 16;
      DM(0x2dde80) = R0;                // tracks left, 16 - t

.GLOBAL wr_t5v_loop.;
wr_t5v_loop.:
      M4 = 0x8d;                        // record stride in words (0x234 bytes); the
                                        // reader uses M4, so it is set every track
      R2 = DM(I3, M4);                  // this track's machine type; I3 -> next record
      R3 = DM(I5, M6);                  // this track's buffer; I5 -> next
      R4 = 5;
      COMP(R2, R4);
      IF NE JUMP 0x16fba0;              // -> wr_t5v_next.
      R4 = DM(0x2de600);                // the baked directory's magic
      R2 = 0x57525431;
      COMP(R4, R2);
      IF NE JUMP 0x16fba0;              // -> wr_t5v_next. (no directory: render nothing)

      // t, and from it every per-track address (no pointer survives the reader call)
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R2 = LSHIFT R9 BY 5;              // 32 bytes a reader block
      R12 = 0x2ddf00;
      R2 = R12 + R2;
      DM(0x2dde84) = R2;
      I4 = R2;                          // this track's reader block

      // WAV1 and TBL1 (params 26, 27) from the frame image the unpack copied to
      // 0x25c48c: offsets 220 + 146t and 222 + 146t, 16-bit words, little-endian.
      // (every add here has R8-R15 first: selas then emits a 32-bit form, never a
      // 16-bit parcel 0xc000..0xc07f that digikit can misread as a Type 2b, G5)
      R10 = LSHIFT R9 BY 7;
      R11 = LSHIFT R9 BY 4;
      R10 = R10 + R11;
      R11 = LSHIFT R9 BY 1;
      R10 = R10 + R11;                  // 146t
      R12 = 0x25c568;                   // 0x25c48c + 220
      R2 = R12 + R10;                   // &WAV1, 2-byte aligned
      R1 = 2;
      R1 = R2 AND R1;                   // 2 when t is odd
      R4 = -4;
      R2 = R2 AND R4;
      I1 = R2;
      R4 = DM(0, I1);                   // the word holding WAV1
      R5 = DM(6, I1);                   // W5: the word holding DRIF (param 38), same half as WAV1
      // M6: TUN1 (param 25) is the half-word before WAV1: t even -> the high half
      // of the word before (218 + 146t is 2 mod 4), t odd -> the low half of WAV1's
      R12 = -4;
      R12 = R12 + R2;
      I1 = R12;
      R13 = DM(0, I1);                  // the word before WAV1's
      // M5d: no conditional computes (the stock corpus has no conditional shift);
      // the firmware's own `IF cond JUMP abs` and unconditional shifts instead
      R7 = -16;
      R1 = PASS R1;
      IF NE JUMP 0x16f836;                   // -> wr_t5v_odd.
      R13 = LSHIFT R13 BY R7;           // t even: TUN1 high half of the word before
                                        //         (WAV1 and DRIF are the low halves)
      JUMP 0x16f83c;                         // -> wr_t5v_halves.
.GLOBAL wr_t5v_odd.;
wr_t5v_odd.:
      R13 = R13 - R13;                  // t odd:  TUN1 low half of word 0
      R13 = R13 + R4;
      R4 = LSHIFT R4 BY R7;             // t odd:  WAV1 high half of word 0
      R5 = LSHIFT R5 BY R7;             //         DRIF high half of word 6
.GLOBAL wr_t5v_halves.;
wr_t5v_halves.:
      R6 = 0xffff;
      R4 = R4 AND R6;                   // WAV1, the sound's value, 0..0x7800
      R13 = R13 AND R6;                 // TUN1, the sound's value, 0x0400..0x7c00
      R5 = R5 AND R6;                   // DRIF, 0x0000..0x7f00 (TBL on Waverider's page)

      // SLOT = lut[DRIF >> 8], then through the directory
      R1 = LSHIFT R5 BY -8;
      R2 = 127;
      R1 = MIN(R1, R2);
      R1 = LSHIFT R1 BY 2;
      R12 = 0x2de800;                   // the TBL -> slot table
      R1 = R12 + R1;
      I1 = R1;
      R1 = DM(0, I1);                   // the slot
      R2 = DM(0x2de604);                // the directory's count
      COMPU(R1, R2);
      IF LT JUMP 0x16f85e;                   // -> wr_t5v_slot_ok.
      R1 = R1 - R1;                     // out of range -> slot 0
.GLOBAL wr_t5v_slot_ok.;
wr_t5v_slot_ok.:
      R1 = LSHIFT R1 BY 2;
      R12 = 0x2de608;
      R1 = R12 + R1;
      I1 = R1;
      R2 = DM(0, I1);                   // directory.table[slot]
      DM(0, I4) = R2;                   // the reader block's table pointer

      // POS = min(WAV1, 0x7800) << 5: Q16 frames, 0x7800 << 5 = 15 << 16
      R2 = 0x7800;
      R4 = MIN(R4, R2);
      R4 = LSHIFT R4 BY 5;              // the target, Q16 frames

      // W5 glide: this voice's note trigger, bit t of the frame's TRIG_NOTE word (offset
      // 34), read from the frame copy the unpack made: 0x25c48c + 34 = 0x25c4ae, the
      // high half of the word at 0x25c4ac
      R0 = DM(0x25c4ac);
      R0 = LSHIFT R0 BY -16;            // TRIG_NOTE
      R2 = 1;
      R2 = LSHIFT R2 BY R9;             // 1 << t
      R0 = R0 AND R2;
      R2 = LSHIFT R9 BY 2;
      R12 = 0x2dee00;                   // s[0]
      R2 = R12 + R2;
      I1 = R2;
      R14 = DM(0, I1);                  // s
      R0 = PASS R0;
      IF EQ JUMP 0x16f892;              // -> wr_t5v_glide.
      R14 = PASS R4;                    // a note starts on this voice: start at the target
      JUMP 0x16f899;                    // -> wr_t5v_glided.
.GLOBAL wr_t5v_glide.;
wr_t5v_glide.:
      R15 = R4 - R14;                   // target - s
      R12 = -5;
      R15 = ASHIFT R15 BY R12;          // / 32, toward -inf (an exact arrival from above)
      R14 = R14 + R15;
.GLOBAL wr_t5v_glided.;
wr_t5v_glided.:
      DM(0, I1) = R14;

      // ---- W2 (docs/w2-scanner.md): the scanner, MPOS, MLEV, LEV. dnfw.waverider.live
      // (Scanner, scanned, gain, ramp) is the contract, operation by operation. ----
      DM(0x2dde88) = R14;               // the glided POS, Q16
      R12 = LSHIFT R9 BY 6;             // 64 bytes of W2 state a voice
      R11 = 0x2df900;
      R12 = R11 + R12;
      I2 = R12;                         // this voice's W2 state (the reader clobbers I2 later)
      R7 = -16;
      R6 = 0xffff;
      // the five controls, each a 16-bit word of the frame copy, into state 8..12
      R11 = 0x25c570;                 // LEV1: 0x25c48c + its offset
      R0 = R11 + R10;                   // + 146t
      R1 = 2;
      R1 = R0 AND R1;                   // 2: the high half
      R2 = -4;
      R0 = R0 AND R2;
      I1 = R0;
      R0 = DM(0, I1);
      R1 = PASS R1;
      IF EQ JUMP 0x16f8c3;                   // -> wr_w2_lev1_lo.
      R0 = LSHIFT R0 BY R7;
.GLOBAL wr_w2_lev1_lo.;
wr_w2_lev1_lo.:
      R0 = R0 AND R6;
      DM(8, I2) = R0;              // state 8: LEV1
      R11 = 0x25c584;                 // ATK: 0x25c48c + its offset
      R0 = R11 + R10;                   // + 146t
      R1 = 2;
      R1 = R0 AND R1;                   // 2: the high half
      R2 = -4;
      R0 = R0 AND R2;
      I1 = R0;
      R0 = DM(0, I1);
      R1 = PASS R1;
      IF EQ JUMP 0x16f8dc;                   // -> wr_w2_atk_lo.
      R0 = LSHIFT R0 BY R7;
.GLOBAL wr_w2_atk_lo.;
wr_w2_atk_lo.:
      R0 = R0 AND R6;
      DM(9, I2) = R0;              // state 9: ATK
      R11 = 0x25c56c;                 // OFS1: 0x25c48c + its offset
      R0 = R11 + R10;                   // + 146t
      R1 = 2;
      R1 = R0 AND R1;                   // 2: the high half
      R2 = -4;
      R0 = R0 AND R2;
      I1 = R0;
      R0 = DM(0, I1);
      R1 = PASS R1;
      IF EQ JUMP 0x16f8f5;                   // -> wr_w2_ofs1_lo.
      R0 = LSHIFT R0 BY R7;
.GLOBAL wr_w2_ofs1_lo.;
wr_w2_ofs1_lo.:
      R0 = R0 AND R6;
      DM(10, I2) = R0;              // state 10: OFS1
      R11 = 0x25c56e;                 // PD1: 0x25c48c + its offset
      R0 = R11 + R10;                   // + 146t
      R1 = 2;
      R1 = R0 AND R1;                   // 2: the high half
      R2 = -4;
      R0 = R0 AND R2;
      I1 = R0;
      R0 = DM(0, I1);
      R1 = PASS R1;
      IF EQ JUMP 0x16f90e;                   // -> wr_w2_pd1_lo.
      R0 = LSHIFT R0 BY R7;
.GLOBAL wr_w2_pd1_lo.;
wr_w2_pd1_lo.:
      R0 = R0 AND R6;
      DM(11, I2) = R0;              // state 11: PD1
      R11 = 0x25c58a;                 // NLEV: 0x25c48c + its offset
      R0 = R11 + R10;                   // + 146t
      R1 = 2;
      R1 = R0 AND R1;                   // 2: the high half
      R2 = -4;
      R0 = R0 AND R2;
      I1 = R0;
      R0 = DM(0, I1);
      R1 = PASS R1;
      IF EQ JUMP 0x16f927;                   // -> wr_w2_nlev_lo.
      R0 = LSHIFT R0 BY R7;
.GLOBAL wr_w2_nlev_lo.;
wr_w2_nlev_lo.:
      R0 = R0 AND R6;
      DM(12, I2) = R0;              // state 12: NLEV

      // this voice's note trigger (TRIG_NOTE bit t), into state 7
      R0 = DM(0x25c4ac);
      R0 = LSHIFT R0 BY -16;
      R2 = 1;
      R2 = LSHIFT R2 BY R9;
      R0 = R0 AND R2;
      DM(7, I2) = R0;
      // MOVE: shape = (min(NLEV >> 8, 127) * 8) >> 7, into state 15
      R0 = DM(12, I2);
      R0 = LSHIFT R0 BY -8;
      R1 = 127;
      R0 = MIN(R0, R1);
      R0 = LSHIFT R0 BY 3;
      R0 = LSHIFT R0 BY -7;
      DM(15, I2) = R0;
      // a note restarts the scanner: phase 0, not done, the next random value
      R0 = DM(7, I2);
      R0 = PASS R0;
      IF EQ JUMP 0x16f98f;                   // -> wr_w2_running.
      R0 = R0 - R0;
      DM(0, I2) = R0;                   // phase
      DM(4, I2) = R0;                   // done
      // twice: a note starts the random walk from a fresh value, not the last one
      R1 = DM(2, I2);
      DM(1, I2) = R1;                   // a = b
      R1 = DM(3, I2);                   // idx
      R2 = 255;
      R2 = R1 AND R2;
      R2 = LSHIFT R2 BY 2;
      R11 = 0x2e0100;                   // the random table
      R2 = R11 + R2;
      I1 = R2;
      R2 = DM(0, I1);
      DM(2, I2) = R2;                   // b = rnd[idx & 255]
      R12 = 1;
      R1 = R12 + R1;
      DM(3, I2) = R1;                   // idx + 1
      R1 = DM(2, I2);
      DM(1, I2) = R1;                   // a = b
      R1 = DM(3, I2);                   // idx
      R2 = 255;
      R2 = R1 AND R2;
      R2 = LSHIFT R2 BY 2;
      R11 = 0x2e0100;                   // the random table
      R2 = R11 + R2;
      I1 = R2;
      R2 = DM(0, I1);
      DM(2, I2) = R2;                   // b = rnd[idx & 255]
      R12 = 1;
      R1 = R12 + R1;
      DM(3, I2) = R1;                   // idx + 1
.GLOBAL wr_w2_running.;
wr_w2_running.:
      // ph = (phase >> 8) * 2^-24, exact
      R0 = DM(0, I2);
      R0 = LSHIFT R0 BY -8;
      R1 = -24;
      F8 = FLOAT R0 BY R1;
      // u (F10) and s (F11) by shape
      R0 = DM(15, I2);
      R1 = 1;
      COMP(R0, R1);
      IF EQ JUMP 0x16f9e8;                   // -> wr_w2_s1.
      R1 = 2;
      COMP(R0, R1);
      IF EQ JUMP 0x16f9f3;                   // -> wr_w2_s2.
      R1 = 3;
      COMP(R0, R1);
      IF EQ JUMP 0x16f9fd;                   // -> wr_w2_s3.
      R1 = 4;
      COMP(R0, R1);
      IF EQ JUMP 0x16fa11;                   // -> wr_w2_s4.
      R1 = 5;
      COMP(R0, R1);
      IF EQ JUMP 0x16fa23;                   // -> wr_w2_s5.
      R1 = 6;
      COMP(R0, R1);
      IF EQ JUMP 0x16fa2e;                   // -> wr_w2_s6.
      R1 = 7;
      COMP(R0, R1);
      IF EQ JUMP 0x16fa3e;                   // -> wr_w2_s7.
      // TRI: q = ph + 0.25, wrapped; u = 2q below a half, else 2 - 2q
      R12 = 0x3e800000;
      F2 = F8 + F12;
      R12 = 0x3f800000;
      COMP(F2, F12);
      IF LT JUMP 0x16f9d1;                   // -> wr_w2_tri_in.
      F2 = F2 - F12;
.GLOBAL wr_w2_tri_in.;
wr_w2_tri_in.:
      F10 = F2 + F2;
      R12 = 0x3f000000;
      COMP(F2, F12);
      IF LT JUMP 0x16f9df;                   // -> wr_w2_tri_up.
      R12 = 0x40000000;
      F10 = F12 - F10;
.GLOBAL wr_w2_tri_up.;
wr_w2_tri_up.:
      F11 = F10 + F10;
      R12 = 0x3f800000;
      F11 = F11 - F12;                  // s = 2u - 1
      JUMP 0x16fa4c;                         // -> wr_w2_shaped.
.GLOBAL wr_w2_s1.;
wr_w2_s1.:
      F10 = PASS F8;                    // SAW: u = ph
      F11 = F10 + F10;
      R12 = 0x3f800000;
      F11 = F11 - F12;                  // s = 2u - 1
      JUMP 0x16fa4c;                         // -> wr_w2_shaped.
.GLOBAL wr_w2_s2.;
wr_w2_s2.:
      R12 = 0x3f800000;
      F10 = F12 - F8;                   // RAMP: u = 1 - ph
      F11 = PASS F10;                   // s = u
      JUMP 0x16fa4c;                         // -> wr_w2_shaped.
.GLOBAL wr_w2_s3.;
wr_w2_s3.:
      R10 = 0x3f800000;                 // SQR: u = 1 below half a cycle, else 0
      R12 = 0x3f000000;
      COMP(F8, F12);
      IF LT JUMP 0x16fa08;                   // -> wr_w2_sqr_hi.
      R10 = R10 - R10;
.GLOBAL wr_w2_sqr_hi.;
wr_w2_sqr_hi.:
      F11 = F10 + F10;
      R12 = 0x3f800000;
      F11 = F11 - F12;                  // s = 2u - 1
      JUMP 0x16fa4c;                         // -> wr_w2_shaped.
.GLOBAL wr_w2_s4.;
wr_w2_s4.:
      R1 = DM(1, I2);                   // a
      R2 = DM(2, I2);                   // b
      F10 = F2 - F1;
      F10 = F10 * F8;
      F10 = F1 + F10;                   // RND: u = a + (b - a) ph
      F11 = F10 + F10;
      R12 = 0x3f800000;
      F11 = F11 - F12;                  // s = 2u - 1
      JUMP 0x16fa4c;                         // -> wr_w2_shaped.
.GLOBAL wr_w2_s5.;
wr_w2_s5.:
      R10 = DM(1, I2);                  // S&H: u = a
      F11 = F10 + F10;
      R12 = 0x3f800000;
      F11 = F11 - F12;                  // s = 2u - 1
      JUMP 0x16fa4c;                         // -> wr_w2_shaped.
.GLOBAL wr_w2_s6.;
wr_w2_s6.:
      F10 = PASS F8;                    // ONE: u = ph, or 1 once done
      R0 = DM(4, I2);
      R0 = PASS R0;
      IF EQ JUMP 0x16fa39;                   // -> wr_w2_s6_on.
      R10 = 0x3f800000;
.GLOBAL wr_w2_s6_on.;
wr_w2_s6_on.:
      F11 = PASS F10;                   // s = u
      JUMP 0x16fa4c;                         // -> wr_w2_shaped.
.GLOBAL wr_w2_s7.;
wr_w2_s7.:
      R12 = 0x3f800000;
      F10 = F12 - F8;                   // ENV: u = 1 - ph, or 0 once done
      R0 = DM(4, I2);
      R0 = PASS R0;
      IF EQ JUMP 0x16fa4a;                   // -> wr_w2_s7_on.
      R10 = R10 - R10;
.GLOBAL wr_w2_s7_on.;
wr_w2_s7_on.:
      F11 = PASS F10;                   // s = u
.GLOBAL wr_w2_shaped.;
wr_w2_shaped.:
      DM(13, I2) = R10;                 // u
      DM(14, I2) = R11;                 // s
      // the phase advances by RATE's step; a wrap ends a cycle: a one-shot is done,
      // and the random walk takes its next value
      R0 = DM(9, I2);
      R0 = LSHIFT R0 BY -8;
      R1 = 127;
      R0 = MIN(R0, R1);
      R0 = LSHIFT R0 BY 2;
      R11 = 0x2dfd00;                   // the RATE table
      R0 = R11 + R0;
      I1 = R0;
      R1 = DM(0, I1);                   // the step
      R0 = DM(0, I2);                   // the phase
      R8 = DM(0, I2);
      R8 = R8 + R1;                     // + step, mod 2^32
      DM(0, I2) = R8;
      COMPU(R8, R0);
      IF LT JUMP 0x16fa74;                   // -> wr_w2_wrap.
      JUMP 0x16fa9e;                         // -> wr_w2_advanced.
.GLOBAL wr_w2_wrap.;
wr_w2_wrap.:
      R0 = DM(15, I2);
      R1 = 6;
      COMP(R0, R1);
      IF LT JUMP 0x16fa80;                   // -> wr_w2_cycle.
      R1 = 1;
      DM(4, I2) = R1;                   // ONE, ENV: done
.GLOBAL wr_w2_cycle.;
wr_w2_cycle.:
      R1 = DM(2, I2);
      DM(1, I2) = R1;                   // a = b
      R1 = DM(3, I2);                   // idx
      R2 = 255;
      R2 = R1 AND R2;
      R2 = LSHIFT R2 BY 2;
      R11 = 0x2e0100;                   // the random table
      R2 = R11 + R2;
      I1 = R2;
      R2 = DM(0, I1);
      DM(2, I2) = R2;                   // b = rnd[idx & 255]
      R12 = 1;
      R1 = R12 + R1;
      DM(3, I2) = R1;                   // idx + 1
.GLOBAL wr_w2_advanced.;
wr_w2_advanced.:
      // POS = trunc(clamp(float(glided) + (s * MPOS) * 983040.0, 0, 983040.0))
      R5 = DM(10, I2);                  // OFS1
      R1 = 0x3200;
      R5 = R5 - R1;                     // signed, the centre is 0
      R1 = R1 - R1;
      F0 = FLOAT R5 BY R1;
      R1 = 0x38a3d70a;                  // 1 / 0x3200
      F0 = F0 * F1;                     // MPOS depth, -1..+1
      R11 = DM(14, I2);                 // s
      F0 = F11 * F0;
      R1 = 0x49700000;                  // 983040.0: 15 frames, Q16
      F0 = F0 * F1;
      R2 = DM(0x2dde88);                // the glided POS
      R1 = R1 - R1;
      F2 = FLOAT R2 BY R1;
      F2 = F2 + F0;
      F2 = MAX(F2, F1);                 // >= 0.0
      R1 = 0x49700000;
      F2 = MIN(F2, F1);                 // <= 983040.0
      R4 = TRUNC F2;
      DM(3, I4) = R4;                   // pos
      // the gain: LEV x the scanner's level
      R5 = DM(11, I2);                  // PD1 (MLEV)
      R1 = 0x3200;
      R5 = R5 - R1;
      R1 = R1 - R1;
      F0 = FLOAT R5 BY R1;
      R1 = 0x38a3d70a;
      F0 = F0 * F1;                     // MLEV depth, -1..+1
      R10 = DM(13, I2);                 // u
      R12 = 0x3f800000;
      R5 = PASS R5;
      IF LT JUMP 0x16fae2;                   // -> wr_w2_mlev_neg.
      F2 = F12 - F10;                   // 1 - u
      F2 = F0 * F2;
      F2 = F12 - F2;                    // a = 1 - d (1 - u)
      JUMP 0x16fae6;                         // -> wr_w2_mlev_done.
.GLOBAL wr_w2_mlev_neg.;
wr_w2_mlev_neg.:
      F2 = F0 * F10;
      F2 = F12 + F2;                    // a = 1 + d u
.GLOBAL wr_w2_mlev_done.;
wr_w2_mlev_done.:
      R0 = DM(8, I2);                   // LEV1
      R0 = LSHIFT R0 BY -8;
      R1 = 127;
      R0 = MIN(R0, R1);
      R0 = LSHIFT R0 BY 2;
      R11 = 0x2dff00;                   // the LEV table
      R0 = R11 + R0;
      I1 = R0;
      R1 = DM(0, I1);                   // LEV's gain
      F2 = F1 * F2;
      DM(6, I2) = R2;                   // g, this block's gain
      R0 = DM(7, I2);
      R0 = PASS R0;
      IF EQ JUMP 0x16fb07;                   // -> wr_w2_gain_set.
      DM(5, I2) = R2;                   // a note starts at its own gain
.GLOBAL wr_w2_gain_set.;
wr_w2_gain_set.:

      // pitch: this track's note cell, 0x254b14 + 4t
      R2 = LSHIFT R9 BY 2;
      R12 = 0x254b14;
      R2 = R12 + R2;
      I1 = R2;
      R8 = DM(0, I1);                   // note, float semitones
      // M5d: the note is validated in the integer domain before any float operation:
      // an exponent field of 0xff (NaN, Inf) or a set sign bit gives +0.0
      R2 = LSHIFT R8 BY -23;
      R12 = 0xff;
      R2 = R2 AND R12;                  // the exponent field
      COMP(R2, R12);
      IF EQ JUMP 0x16fb24;                   // -> wr_t5v_note0.
      R8 = PASS R8;
      IF LT JUMP 0x16fb24;                   // -> wr_t5v_note0.
      JUMP 0x16fb25;                         // -> wr_t5v_note_ok.
.GLOBAL wr_t5v_note0.;
wr_t5v_note0.:
      R8 = R8 - R8;                     // +0.0
.GLOBAL wr_t5v_note_ok.;
wr_t5v_note_ok.:
      // M6: + TUN1 in semitones. Read on the instrument through the USB probe
      // (2026-09-30): the frame carries the sound's own value, 0x4000 at 0,
      // 0x4100 at +1, 0x4c00 at +12, 0x3400 at -12. So coarse - 64 + fine / 256
      // semitones = frame word / 256 - 64 (the display shows it as -5..+5 octaves)
      R12 = -8;
      F13 = FLOAT R13 BY R12;           // frame word / 256
      R12 = 0x42800000;                 // 64.0
      F13 = F13 - F12;
      F8 = F8 + F13;                    // note + TUN1
      R8 = PASS R8;
      IF LT JUMP 0x16fb35;                   // -> wr_t5v_tune_low.
      JUMP 0x16fb36;                         // -> wr_t5v_tuned.
.GLOBAL wr_t5v_tune_low.;
wr_t5v_tune_low.:
      R8 = R8 - R8;                     // below note 0 -> +0.0
.GLOBAL wr_t5v_tuned.;
wr_t5v_tuned.:
      R12 = 0x42fe0000;                 // 127.0
      F8 = MIN(F8, F12);                // 0 <= note <= 127, finite
      R0 = TRUNC F8;                    // k, 0..127
      R12 = R12 - R12;                  // 0: the scale of FLOAT ... BY (the stock corpus
      F1 = FLOAT R0 BY R12;             // has FLOAT only with BY or with a parallel move)
      F8 = F8 - F1;                     // fr, 0 <= fr < 1
      R0 = LSHIFT R0 BY 2;
      R12 = 0x2de200;                   // &T[0]
      R0 = R12 + R0;
      I1 = R0;                          // &T[k]
      R1 = DM(0, I1);                   // T[k]
      R2 = DM(1, I1);                   // T[k + 1]
      F2 = F2 - F1;
      F2 = F8 * F2;
      F1 = F1 + F2;                     // T[k] + fr * (T[k+1] - T[k])
      R1 = TRUNC F1;
      DM(2, I4) = R1;                   // inc

      R0 = DM(0x2dde24);                // the dispatch's R9: the block size
      DM(4, I4) = R0;                   // count
      DM(5, I4) = R3;                   // out: the track buffer
      R4 = DM(0x2dde84);                // wr_render5's argument: the reader block
      CJUMP 0x16eb00 (DB);              // wr_render5(R4 = reader block)
      DM(I7, M7) = R2;
      DM(I7, M7) = 0x16fb67;                 // return address - 1: wr_t5v_gain. - 1

      // ---- W2: the gain, ramped across the block from the last block's: step =
      // (g - gp) / 32, accumulated before each sample (live.ramp) ----
.GLOBAL wr_t5v_gain.;
wr_t5v_gain.:
      R0 = DM(0x2dde80);
      R1 = 16;
      R9 = R1 - R0;                     // t
      R12 = LSHIFT R9 BY 6;
      R11 = 0x2df900;
      R12 = R11 + R12;
      I2 = R12;                         // this voice's W2 state
      R0 = DM(0x2dde84);
      I4 = R0;                          // the reader block
      R0 = DM(5, I4);
      I1 = R0;                          // the track buffer
      R1 = DM(5, I2);                   // gp
      R2 = DM(6, I2);                   // g
      DM(5, I2) = R2;                   // the next block starts from g
      F3 = F2 - F1;
      R4 = 0x3d000000;                  // 1/32
      F3 = F3 * F4;                     // step
      R5 = DM(0x2dde24);                // the block size
      R5 = PASS R5;
      IF EQ JUMP 0x16fba0;                   // -> wr_t5v_next.
.GLOBAL wr_t5v_ramp.;
wr_t5v_ramp.:
      F1 = F1 + F3;
      R0 = DM(0, I1);
      F0 = F0 * F1;
      DM(I1, M6) = F0;
      R12 = 1;
      R5 = R5 - R12;
      IF NE JUMP 0x16fb95;                   // -> wr_t5v_ramp.

.GLOBAL wr_t5v_next.;
wr_t5v_next.:
      R0 = DM(0x2dde80);
      R1 = 1;
      R0 = R0 - R1;
      DM(0x2dde80) = R0;
      IF NE JUMP 0x16f7df;              // -> wr_t5v_loop.

      // PING (ping.asm, docs/ping.md) takes the tail: it filters every track whose
      // filter type is 6, then restores what this loop saved and rejoins the chain at
      // 0x1c944c, as this tail did before PING.
      JUMP 0x172980;                    // rings.asm's wr_rings (dnfw.waverider.dsp.RINGS_SW), which goes on to wr_ping
.wr_type5v..end:
      .type wr_type5v.,STT_FUNC;
