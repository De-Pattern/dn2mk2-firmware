// machine5.asm -- Waverider Milestone 3: a render loop for machine type 5.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and
// never linked in). It is run offline in digikit's SHARC executor inside the
// DN2 1.11 image; it has never run on a DSP.
//
// sw 0x1c8ef1 (the slot dispatch) has four per-type render loops, one per
// machine type 0..3 (0x1c93e5, 0x1c9401, 0x1c941c, 0x1c943b). Each walks the
// 16 track records' machine-type word with M = 0x8d words (0x234 bytes) and
// calls that machine's render with the track buffer and the block size. This
// is a fifth loop in the same shape: for every track whose type is 5 it calls
// wr_render (reader.asm, loaded at sw 0x180000) on that track's voice block.
//
// Entry: a JUMP patched over 0x1c9448..0x1c944b, right after the Swarmer
// loop and before the per-track chain (sw 0xb8251b at 0x1c9459). The two
// instructions it replaced run at the end, and control returns to 0x1c944c.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x180100. The absolute
// targets below (0x180167, 0x180181/0x180182) are written for that address
// from selas's own symbol table; scripts/sharc_waverider_m3.py re-reads the
// symbols and refuses a mismatch. 0x180000 is wr_render (reader.asm).
//
// DM (byte addresses, the form the firmware uses; spans the boot stream never
// loads, checked by the gate):
//   0x284200  save area, 32 words: R0-R15, I0-I5, I12, M0-M4
//   0x284280  tracks left (loop counter)
//   0x284284  this track's voice block (walks 0x284300 + 24 * t)
//   0x284300  16 voice blocks of 6 words, wr_render's parameter layout
//             (table, phase, inc, pos, count, out); the host writes table,
//             phase, inc and pos, this loop writes count and out.
//
// Only forms the firmware itself uses, as for reader.asm: absolute CJUMP /
// JUMP (25a_direct / 8a_abs), Type 14a absolute loads and stores, Type 16a
// immediate stores, and the post-modify load in place of MODIFY.

.SECTION/PM seg_pmco;

.GLOBAL wr_type5.;
wr_type5.:
      DM(0x284200) = R0;
      DM(0x284204) = R1;
      DM(0x284208) = R2;
      DM(0x28420c) = R3;
      DM(0x284210) = R4;
      DM(0x284214) = R5;
      DM(0x284218) = R6;
      DM(0x28421c) = R7;
      DM(0x284220) = R8;
      DM(0x284224) = R9;
      DM(0x284228) = R10;
      DM(0x28422c) = R11;
      DM(0x284230) = R12;
      DM(0x284234) = R13;
      DM(0x284238) = R14;
      DM(0x28423c) = R15;
      DM(0x284240) = I0;
      DM(0x284244) = I1;
      DM(0x284248) = I2;
      DM(0x28424c) = I3;
      DM(0x284250) = I4;
      DM(0x284254) = I5;
      DM(0x284258) = I12;
      DM(0x28425c) = M0;
      DM(0x284260) = M1;
      DM(0x284264) = M2;
      DM(0x284268) = M3;
      DM(0x28426c) = M4;

      I3 = 0x25566c;                    // &track[0].machine (0x2554b8 + 0x1b4)
      I5 = 0x254a60;                    // &track_buffer[0]
      M4 = 0x8d;                        // record stride in words (0x234 bytes)
      R0 = 16;
      DM(0x284280) = R0;
      R0 = 0x284300;
      DM(0x284284) = R0;

.GLOBAL wr_t5_loop.;
wr_t5_loop.:
      R2 = DM(I3, M4);                  // this track's machine type; I3 -> next
      R3 = DM(I5, M6);                  // this track's buffer; I5 -> next
      R1 = 5;
      COMP(R2, R1);
      IF NE JUMP 0x180182;              // -> wr_t5_next. (0x180100 + 130)
      R4 = DM(0x284284);
      I4 = R4;
      R0 = DM(0x284224);                // the dispatch's R9: the block size
      DM(4, I4) = R0;                   // count
      DM(5, I4) = R3;                   // out: the track buffer
      CJUMP 0x180000 (DB);              // wr_render(R4 = voice block)
      DM(I7, M7) = R2;
      DM(I7, M7) = 0x180181;            // return address - 1: wr_t5_next. - 1

.GLOBAL wr_t5_next.;
wr_t5_next.:
      I4 = DM(0x284284);
      M0 = 6;
      R0 = DM(I4, M0);                  // I4 += 6 words; the word is discarded
      DM(0x284284) = I4;
      R0 = DM(0x284280);
      R1 = 1;
      R0 = R0 - R1;
      DM(0x284280) = R0;
      IF NE JUMP 0x180167;              // -> wr_t5_loop. (0x180100 + 103)

      R0 = DM(0x284200);
      R1 = DM(0x284204);
      R2 = DM(0x284208);
      R3 = DM(0x28420c);
      R4 = DM(0x284210);
      R5 = DM(0x284214);
      R6 = DM(0x284218);
      R7 = DM(0x28421c);
      R8 = DM(0x284220);
      R9 = DM(0x284224);
      R10 = DM(0x284228);
      R11 = DM(0x28422c);
      R12 = DM(0x284230);
      R13 = DM(0x284234);
      R14 = DM(0x284238);
      R15 = DM(0x28423c);
      I0 = DM(0x284240);
      I1 = DM(0x284244);
      I2 = DM(0x284248);
      I3 = DM(0x28424c);
      I4 = DM(0x284250);
      I5 = DM(0x284254);
      I12 = DM(0x284258);
      M0 = DM(0x28425c);
      M1 = DM(0x284260);
      M2 = DM(0x284264);
      M3 = DM(0x284268);
      M4 = DM(0x28426c);

      // the two instructions the entry JUMP replaced (0x1c9448, 0x1c944a)
      I5 = DM(-24, I6);
      R10 = DM(-34, I6);
      JUMP 0x1c944c;
.wr_type5..end:
      .type wr_type5.,STT_FUNC;
