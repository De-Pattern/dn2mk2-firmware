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
//   SLOT  WaveTone's TBL1 (param 27), read from the frame image the unpack copied to
//         0x25c48c (offset 222 + 146t): 0x0000 or 0x0080 -- the ColdFire sends
//         every slot value at half the sound's (0x0100 >> 1, measured from its own
//         frame builder in the emulator); >> 7 is the slot,
//         resolved through the baked directory; at or above its count plays 0.
//   POS   WaveTone's WAV1 (param 26), from the same copy (offset 220 + 146t):
//         half the sound's coarse << 8 | fine, 0..0x3c00. min(WAV1, 0x3c00) << 6
//         is Q16 frames: 0x3c00 << 6 = 15 << 16, frame 15. The unpack does not put a type-5 track's
//         machine parameters in its record (measured), so the frame copy is read.
//   pitch the engine's note cell, engine +0x1387c + 4t = 0x254b14 + 4t, a float in
//         semitones (note + fine/256). Clamped to 0..127; k = trunc, fr = note - k;
//         inc = trunc(T[k] + fr * (T[k+1] - T[k])) from the baked 129-entry float
//         table T (dnfw.waverider.live.increment_table): 440 * 2^((k-69)/12) Hz as a
//         u32 phase step at 48 kHz.
//   phase kept in the reader block, per track, from block to block.
//
// A directory without the magic renders nothing (the track buffer is left as the
// dispatch left it).
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16ed00 (L1 block 1, byte 0x2dda00).
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
      IF NE JUMP 0x16ee14;              // -> wr_t5v_next.
      R4 = DM(0x2de600);                // the baked directory's magic
      R2 = 0x57525431;
      COMP(R4, R2);
      IF NE JUMP 0x16ee14;              // no directory: render nothing

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
      R5 = DM(1, I1);                   // the next one
      R7 = -16;
      R1 = PASS R1;
      IF EQ R5 = LSHIFT R4 BY R7;       // t even: WAV1 low, TBL1 high half of word 0
      IF NE R4 = LSHIFT R4 BY R7;       // t odd:  WAV1 high half of word 0, TBL1 low of 1
      R6 = 0xffff;
      R4 = R4 AND R6;                   // WAV1, half the sound's value, 0..0x3c00
      R5 = R5 AND R6;                   // TBL1, 0x0000 or 0x0080

      // SLOT = TBL1 >> 7, through the directory
      R1 = LSHIFT R5 BY -7;
      R2 = DM(0x2de604);                // the directory's count
      COMPU(R1, R2);
      IF GE R1 = R1 - R1;               // out of range -> slot 0
      R1 = LSHIFT R1 BY 2;
      R12 = 0x2de608;
      R1 = R12 + R1;
      I1 = R1;
      R2 = DM(0, I1);                   // directory.table[slot]
      DM(0, I4) = R2;                   // the reader block's table pointer

      // POS = min(WAV1, 0x3c00) << 6: Q16 frames, 0x3c00 << 6 = 15 << 16
      R2 = 0x3c00;
      R4 = MIN(R4, R2);
      R4 = LSHIFT R4 BY 6;
      DM(3, I4) = R4;                   // pos

      // pitch: this track's note cell, 0x254b14 + 4t
      R2 = LSHIFT R9 BY 2;
      R12 = 0x254b14;
      R2 = R12 + R2;
      I1 = R2;
      R8 = DM(0, I1);                   // note, float semitones
      R12 = 0x42fe0000;                 // 127.0
      F8 = MIN(F8, F12);
      R12 = R12 - R12;                  // 0.0
      F8 = MAX(F8, F12);
      R0 = TRUNC F8;                    // k, 0..127
      F1 = FLOAT R0;
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
      DM(I7, M7) = 0x16ee13;            // return address - 1: wr_t5v_next. - 1

.GLOBAL wr_t5v_next.;
wr_t5v_next.:
      R0 = DM(0x2dde80);
      R1 = 1;
      R0 = R0 - R1;
      DM(0x2dde80) = R0;
      IF NE JUMP 0x16ed5f;              // -> wr_t5v_loop.

      R0 = DM(0x2dde00);
      R1 = DM(0x2dde04);
      R2 = DM(0x2dde08);
      R3 = DM(0x2dde0c);
      R4 = DM(0x2dde10);
      R5 = DM(0x2dde14);
      R6 = DM(0x2dde18);
      R7 = DM(0x2dde1c);
      R8 = DM(0x2dde20);
      R9 = DM(0x2dde24);
      R10 = DM(0x2dde28);
      R11 = DM(0x2dde2c);
      R12 = DM(0x2dde30);
      R13 = DM(0x2dde34);
      R14 = DM(0x2dde38);
      R15 = DM(0x2dde3c);
      I0 = DM(0x2dde40);
      I1 = DM(0x2dde44);
      I2 = DM(0x2dde48);
      I3 = DM(0x2dde4c);
      I4 = DM(0x2dde50);
      I5 = DM(0x2dde54);
      I12 = DM(0x2dde58);
      M0 = DM(0x2dde5c);
      M1 = DM(0x2dde60);
      M2 = DM(0x2dde64);
      M3 = DM(0x2dde68);
      M4 = DM(0x2dde6c);

      // the two instructions the entry JUMP replaced (0x1c9448, 0x1c944a)
      I5 = DM(-24, I6);
      R10 = DM(-34, I6);
      JUMP 0x1c944c;
.wr_type5v..end:
      .type wr_type5v.,STT_FUNC;
