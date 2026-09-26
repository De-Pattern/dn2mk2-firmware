// machine5_dir.asm -- Waverider Milestone 4, Part B: the type-5 render loop, reading
// its wavetable from a directory baked into section 7.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and
// never linked in). It is run offline in digikit's SHARC executor inside the
// DN2 1.11 image; it has never run on a DSP.
//
// The same loop as machine5.asm (Milestone 3) -- scan the 16 track records and
// call wr_render (reader.asm, sw 0x180000) for every track of machine type 5 --
// with one change: the voice block's table pointer is no longer written by the
// harness. Each voice block carries a SLOT number, and this loop resolves it
// through a wavetable directory that the boot stream itself loads:
//
//   DM 0x28c000  directory: +0 magic 'WRT1' (0x57525431), +4 count,
//                +8 table pointer [0], +12 table pointer [1], ...
//
// A slot at or above the count plays slot 0; a directory without the magic
// renders nothing (the track buffer is left as the dispatch cleared it).
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x180200. The absolute targets
// below are written for that address from selas's own symbol table
// (out of a labelled reassembly); scripts/sharc_waverider_m4.py checks the decoder lands
// on every assembler boundary and runs the loop.
//
// DM (byte addresses, the form the firmware uses; spans the boot stream never
// loads, checked by the gate):
//   0x284200  save area, 32 words: R0-R15, I0-I5, I12, M0-M4
//   0x284280  tracks left (loop counter)
//   0x284284  this track's voice block (walks 0x284300 + 32 * t)
//   0x284300  16 voice blocks of 8 words: wr_render's six (table, phase, inc,
//             pos, count, out), then slot, then a spare word. The host writes
//             phase, inc, pos and slot; this loop writes table, count and out.
//
// Only forms the firmware itself uses, as for machine5.asm.

.SECTION/PM seg_pmco;

.GLOBAL wr_type5d.;
wr_type5d.:
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

.GLOBAL wr_t5d_loop.;
wr_t5d_loop.:
      R2 = DM(I3, M4);                  // this track's machine type; I3 -> next
      R3 = DM(I5, M6);                  // this track's buffer; I5 -> next
      R1 = 5;
      COMP(R2, R1);
      IF NE JUMP 0x18029f;              // -> wr_t5d_next. (0x180200 + 159)
      R1 = DM(0x28c000);                // the baked directory's magic
      R2 = 0x57525431;
      COMP(R1, R2);
      IF NE JUMP 0x18029f;              // no directory: render nothing
      R4 = DM(0x284284);
      I4 = R4;
      R1 = DM(6, I4);                   // the voice's slot
      R2 = DM(0x28c004);                // the directory's count
      COMPU(R1, R2);
      IF GE R1 = R1 - R1;               // out of range -> slot 0
      I1 = 0x28c008;                    // &directory.table[0]
      M1 = R1;
      // Not `R2 = DM(M1, I1)`: selas compresses that pre-modify, no-update read
      // to a 16-bit Type 3c, which digikit's executor runs as a post-modify
      // with update -- it read entry 0 and advanced I1 (Milestone 4). A
      // post-modify dummy read moves I1, then a plain post-modify read takes
      // the entry; both toolchains agree on both.
      R0 = DM(I1, M1);                  // I1 -> &directory.table[slot]
      R2 = DM(I1, M6);                  // directory.table[slot]
      DM(0, I4) = R2;                   // the voice block's table pointer
      R0 = DM(0x284224);                // the dispatch's R9: the block size
      DM(4, I4) = R0;                   // count
      DM(5, I4) = R3;                   // out: the track buffer
      CJUMP 0x180000 (DB);              // wr_render(R4 = voice block)
      DM(I7, M7) = R2;
      DM(I7, M7) = 0x18029e;            // return address - 1: wr_t5d_next. - 1

.GLOBAL wr_t5d_next.;
wr_t5d_next.:
      I4 = DM(0x284284);
      M0 = 8;
      R0 = DM(I4, M0);                  // I4 += 8 words; the word is discarded
      DM(0x284284) = I4;
      R0 = DM(0x284280);
      R1 = 1;
      R0 = R0 - R1;
      DM(0x284280) = R0;
      IF NE JUMP 0x180267;              // -> wr_t5d_loop. (0x180200 + 103)

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
.wr_type5d..end:
      .type wr_type5d.,STT_FUNC;
