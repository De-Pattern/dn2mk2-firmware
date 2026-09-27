// oneshot5.asm -- the ONESHOT port: a type-5 render loop that drives the
// Digitakt II's own voice render, transplanted into the DN2 at apply time.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and
// never linked in). Run offline in digikit's SHARC executor inside the DN2 1.11
// image; it has never run on a DSP. The render it calls is NOT in this file or
// this repository: `dnfw.transplant` copies it from the user's own DT2 1.16 OS
// file into sw 0x180800 when the transplant is applied.
//
// The loop has Milestone 3's shape (machine5.asm): scan the 16 track records and
// act on every track whose machine type is 5. For such a track t it
//
//   1. on a note trigger (the byte engine +0x138fc + t, raised by the frame
//      unpack), builds a DT2-shaped voice record at 0x30e000 + 0x1d8 t from six
//      machine-page parameters of the frame (indices 25..30: TUNE, PLAY, SAMP,
//      STRT, LEN, LOOP, coarse byte), resolving SAMP through the sample bank
//      directory (magic 'OSB1') baked into section 7;
//   2. calls the render with R4 = the record, R8 = the track buffer, R12 = the
//      block size, as the DT2's own dispatch calls it (DT2 0x1c6afd).
//
// Without a trigger the record carries on as the last block left it (a one-shot
// ends by clearing its own ACTIVE; the render then writes silence). Without the
// directory magic the loop renders nothing.
//
// The record arithmetic is `dnfw.oneshot.params.record_fields`, which the gate
// compares with what this loop writes, word for word:
//   S = min((STRT * len) >> 7, len - 1)
//   L = LEN >= 127 ? len : (LEN * len) >> 7;  E = min(S + L, len); E <= S -> S + 1
//   P = (LOOP * len) >> 7;  P >= E -> S
//   PLAY: bit 0 reverse, bit 1 loop;  step = steps[TUNE + 128 * reverse]
//   phase = reverse ? E - 1 : S
//
// PLACEMENT IS FIXED at PM sw 0x181000. Absolute targets are written for that
// address from selas's own symbol table (a labelled reassembly); the gate
// decodes the spliced code and checks every target lands on our labels.
//
// DM (byte addresses; spans the DN2 boot stream never loads, checked by the gate):
//   0x30c000  save area, 32 words: R0-R15, I0-I5, I12, M0-M4
//   0x30c080  tracks left            0x30c084  this track's index
//   0x30c088  this track's record    0x30c08c  this track's frame slot
//   0x30c090  -> machine type word   0x30c094  -> track buffer pointer
//   0x30c098  this track's buffer    0x30c0a0  six coarse parameters
//   0x30e000  16 records of 0x1d8 bytes (a zero-fill block at boot)
//   0x310000  256 steps, 2 words each (ours: 0.5 * 2^((c - 64) / 12), Q31)
//   0x310800  the sample bank: 'OSB1', count, (pointer, length, rate) ...
//
// selas compresses `R0 = R0 + R1` to the 16-bit parcel 0xc001, which digikit's
// decoder reads as a 32-bit Type 2b (docs/for-digikit-sharc-runner-dn2.md 10),
// and `R5 = R5 + R6` to 0xc056 the same way; os_next. writes `R5 = R6 + R5`,
// which selas emits in 48 bits and both toolchains read alike.
//
// Only forms the firmware itself uses, as machine5.asm: absolute JUMP/CJUMP,
// Type 14a absolute loads and stores, Type 15b I+displacement, 16a immediate
// stores, and no MODIFY and no DM(Mb, Ia) read (docs/for-digikit-sharc-runner-dn2.md 4, 19).

.SECTION/PM seg_pmco;

.GLOBAL os_type5.;
os_type5.:
      DM(0x30c000) = R0;
      DM(0x30c004) = R1;
      DM(0x30c008) = R2;
      DM(0x30c00c) = R3;
      DM(0x30c010) = R4;
      DM(0x30c014) = R5;
      DM(0x30c018) = R6;
      DM(0x30c01c) = R7;
      DM(0x30c020) = R8;
      DM(0x30c024) = R9;
      DM(0x30c028) = R10;
      DM(0x30c02c) = R11;
      DM(0x30c030) = R12;
      DM(0x30c034) = R13;
      DM(0x30c038) = R14;
      DM(0x30c03c) = R15;
      DM(0x30c040) = I0;
      DM(0x30c044) = I1;
      DM(0x30c048) = I2;
      DM(0x30c04c) = I3;
      DM(0x30c050) = I4;
      DM(0x30c054) = I5;
      DM(0x30c058) = I12;
      DM(0x30c05c) = M0;
      DM(0x30c060) = M1;
      DM(0x30c064) = M2;
      DM(0x30c068) = M3;
      DM(0x30c06c) = M4;
      // Save I6/I7 too. The transplanted render ends in RFRAME, which sets
      // I6/I7 from the frame CJUMP built; on a never-triggered (word-0 = 0)
      // record it leaves the caller's I7 pointing at a word we did not own, and
      // the DN2 block loop carries I7 into the next block. Restored at the exit.
      R0 = I6;
      DM(0x30c070) = R0;
      R0 = I7;
      DM(0x30c074) = R0;

      R0 = 16;
      DM(0x30c080) = R0;
      R0 = 0;
      DM(0x30c084) = R0;
      R0 = 0x30e000;
      DM(0x30c088) = R0;
      R0 = 0x25c566;                    // the frame copy 0x25c48c + slot 218
      DM(0x30c08c) = R0;
      R0 = 0x25566c;                    // &track[0].machine (0x2554b8 + 0x1b4)
      DM(0x30c090) = R0;
      R0 = 0x254a60;                    // &track_buffer[0]
      DM(0x30c094) = R0;

.GLOBAL os_loop.;
os_loop.:
      I4 = DM(0x30c090);
      R2 = DM(0, I4);                   // this track's machine type
      I4 = DM(0x30c094);
      R3 = DM(0, I4);                   // this track's buffer
      DM(0x30c098) = R3;
      R1 = 5;
      COMP(R2, R1);
      IF NE JUMP 0x185a47;             // -> os_next.
      R1 = DM(0x310800);                // the bank's magic
      R2 = 0x3142534f;
      COMP(R1, R2);
      IF NE JUMP 0x185a47;             // -> os_next.

      // the note trigger: byte t of the words at engine + 0x138fc
      R0 = DM(0x30c084);
      R1 = 3;
      R4 = R0 AND R1;                   // t & 3
      R5 = R0 - R4;                     // t & ~3
      R6 = 0x254b94;
      R6 = R6 + R5;
      I4 = R6;
      R7 = DM(0, I4);
      R4 = LSHIFT R4 BY 3;              // 8 * (t & 3)
      R5 = 0;
      R4 = R5 - R4;
      R7 = LSHIFT R7 BY R4;
      R1 = 0xff;
      R7 = R7 AND R1;
      R7 = PASS R7;
      IF EQ JUMP 0x185a20;             // no trigger -> os_render.

      // the DT2 records' values from the frame slot: slot s at byte 2 * (s - 25).
      // The ColdFire sends every slot at HALF the sound's value, rounded
      // (Waverider M5's frame comparison: 0x6117 -> 0x308c), so TUNE 25 and PLAY 26
      // are read coarse as frame >> 7; SAMP 28 as the frame word itself (a slot is
      // SAMP / 2, rounded); STRT 31, LEN 32 and LOOP 33 as frame words, which are
      // half of 8.8 values whose 0x7800 (120.00) is the sample's end.
      R8 = DM(0x30c08c);
      R9 = 0xfffffffc;
      R10 = 2;
      R11 = 0;
      R12 = 0xffff;
      R13 = 0xff;
      R0 = R8;
      // TUNE, slot 25: +0
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = LSHIFT R2 BY -7;
      R2 = R2 AND R13;
      DM(0x30c0a0) = R2;
      R0 = R0 + R10;
      // PLAY, slot 26: +2
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = LSHIFT R2 BY -7;
      R2 = R2 AND R13;
      DM(0x30c0a4) = R2;
      R0 = R0 + R10;
      R0 = R0 + R10;
      // SAMP, slot 28: +6
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = R2 AND R12;
      DM(0x30c0a8) = R2;
      R0 = R0 + R10;
      R0 = R0 + R10;
      R0 = R0 + R10;
      // STRT, slot 31: +12
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = R2 AND R12;
      DM(0x30c0ac) = R2;
      R0 = R0 + R10;
      // LEN, slot 32: +14
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = R2 AND R12;
      DM(0x30c0b0) = R2;
      R0 = R0 + R10;
      // LOOP, slot 33: +16
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = R2 AND R12;
      DM(0x30c0b4) = R2;

      // SAMP through the directory; a slot past the count plays slot 0
      R1 = DM(0x30c0a8);
      R2 = DM(0x310804);
      COMPU(R1, R2);
      IF GE R1 = R1 - R1;
      R2 = 12;
      R1 = R1 * R2 (SSI);
      R2 = 0x310808;
      R1 = R1 + R2;
      I4 = R1;
      R13 = DM(0, I4);                  // pointer
      R14 = DM(1, I4);                  // len

      // S = min(2 f * len / 30720, len - 1), f the STRT frame word (0x3c00 = the end)
      R0 = DM(0x30c0ac);
      R0 = R0 * R14 (SSI);
      R0 = LSHIFT R0 BY -9;
      R2 = 2185;                        // 65536 / 30, so (x >> 10) * 2185 >> 16 = x / 30720
      R0 = R0 * R2 (SSI);
      R0 = LSHIFT R0 BY -16;
      R1 = 1;
      R2 = R14 - R1;
      R0 = MIN(R0, R2);                 // R0 = S
      // L = 2 f * len / 30720, f the LEN frame word
      R3 = DM(0x30c0b0);
      R4 = R3 * R14 (SSI);
      R4 = LSHIFT R4 BY -9;
      R2 = 2185;
      R4 = R4 * R2 (SSI);
      R4 = LSHIFT R4 BY -16;
      // E = min(S + L, len); E <= S -> S + 1
      R4 = R0 + R4;
      R4 = MIN(R4, R14);
      R5 = R0 + R1;
      R4 = MAX(R4, R5);                 // R4 = E
      // P: a LOOP frame word of 0 is OFF, loop from S; else (2 f - 1) * len / 30720; P >= E -> S
      R7 = DM(0x30c0b4);
      R6 = LSHIFT R7 BY 1;
      R6 = R6 - R1;
      R6 = MAX(R6, R11);
      R6 = R6 * R14 (SSI);
      R6 = LSHIFT R6 BY -10;
      R2 = 2185;
      R6 = R6 * R2 (SSI);
      R6 = LSHIFT R6 BY -16;
      COMP(R6, R4);
      IF GE R6 = PASS R0;
      R7 = PASS R7;
      IF EQ R6 = PASS R0;               // R6 = P
      // PLAY, the DT2's order: 0 REV, 1 REV.L, 2 FWD.L, 3 FWD
      R7 = DM(0x30c0a4);
      R9 = LSHIFT R7 BY -1;
      R9 = R9 AND R1;                   // 0 0 1 1: forward
      R8 = R1 - R9;                     // reverse
      R10 = R7 AND R1;                  // 0 1 0 1
      R9 = R9 XOR R10;                  // loop: 0 1 1 0
      // step = steps[TUNE + 128 * reverse], two words
      R10 = LSHIFT R8 BY 7;
      R11 = DM(0x30c0a0);
      R10 = R10 + R11;
      R10 = LSHIFT R10 BY 3;
      R11 = 0x310000;
      R10 = R10 + R11;
      I4 = R10;
      R10 = DM(0, I4);                  // step lo
      R11 = DM(1, I4);                  // step hi
      // phase = reverse ? E - 1 : S
      R12 = R4 - R1;
      R8 = PASS R8;
      IF EQ R12 = PASS R0;

      // the record
      R15 = DM(0x30c088);
      I4 = R15;
      DM(0, I4) = R13;                  // +0x000 sample pointer
      R2 = 0x17c;
      R2 = R15 + R2;
      I4 = R2;
      R3 = 0;
      DM(0, I4) = R3;                   // +0x17c declick one-shots
      DM(1, I4) = R3;                   // +0x180 previous sample
      DM(3, I4) = R14;                  // +0x188 length
      DM(4, I4) = R3;                   // +0x18c
      R2 = LSHIFT R6 BY 31;
      DM(5, I4) = R2;                   // +0x190 loop start
      R2 = LSHIFT R6 BY -1;
      DM(6, I4) = R2;
      R2 = LSHIFT R0 BY 31;
      DM(7, I4) = R2;                   // +0x198 start
      R2 = LSHIFT R0 BY -1;
      DM(8, I4) = R2;
      R2 = LSHIFT R4 BY 31;
      DM(9, I4) = R2;                   // +0x1a0 end
      R2 = LSHIFT R4 BY -1;
      DM(10, I4) = R2;
      DM(11, I4) = R10;                 // +0x1a8 step
      DM(12, I4) = R11;
      R2 = LSHIFT R12 BY 31;
      DM(13, I4) = R2;                  // +0x1b0 phase
      R2 = LSHIFT R12 BY -1;
      DM(14, I4) = R2;
      R2 = LSHIFT R8 BY 24;
      R2 = R2 + R1;
      DM(15, I4) = R2;                  // +0x1b8 ACTIVE = 1, +0x1bb REVERSE
      DM(16, I4) = R9;                  // +0x1bc LOOP

.GLOBAL os_render.;
os_render.:
      R4 = DM(0x30c088);
      R8 = DM(0x30c098);
      // An idle voice (no sample pointer, or ACTIVE clear) is not handed to the
      // render: its own zero-fill arm for that case is the DT2's, and in the DN2's
      // per-block run it did not come back (the runner halted at PC 0 on the first
      // idle block -- #133's "setup table" blocker was this, not the table). The
      // adapter writes the block's 32 zeros itself.
      I4 = R4;
      R2 = DM(0, I4);                   // +0x000 sample pointer
      R3 = 0x1b8;
      R3 = R4 + R3;
      I4 = R3;
      R3 = DM(0, I4);                   // +0x1b8 ACTIVE (low byte)
      R1 = 0xff;
      R3 = R3 AND R1;
      R2 = PASS R2;
      IF EQ JUMP 0x185aea;             // -> os_quiet.
      R3 = PASS R3;
      IF EQ JUMP 0x185aea;             // -> os_quiet.
      R12 = DM(0x30c024);               // the dispatch's R9: the block size
      // The transplanted render ends in a RETURN whose delay slot is RFRAME:
      // it needs both a PC-stack return and the frame link (I6 = I7, R2 = old
      // I6) that the donor's own frame-linked caller (0x1c6b00) sets up. CJUMP
      // does exactly both (digikit `_type_25a_direct`: call = True and the
      // cjump-frame), so the render is reached with CJUMP and the two software-
      // stack pushes, as machine5_dir reaches the reader.
      CJUMP 0x185000 (DB);             // the transplanted render
      DM(I7, M7) = R2;
      DM(I7, M7) = 0x185a46;           // return address - 1: os_next. - 1

.GLOBAL os_next.;
os_next.:
      R5 = DM(0x30c084);
      R6 = 1;
      R5 = R6 + R5;
      DM(0x30c084) = R5;
      R5 = DM(0x30c088);
      R6 = 0x1d8;
      R5 = R6 + R5;
      DM(0x30c088) = R5;
      R5 = DM(0x30c08c);
      R6 = 146;
      R5 = R6 + R5;
      DM(0x30c08c) = R5;
      R5 = DM(0x30c090);
      R6 = 0x234;
      R5 = R6 + R5;
      DM(0x30c090) = R5;
      R5 = DM(0x30c094);
      R6 = 4;
      R5 = R6 + R5;
      DM(0x30c094) = R5;
      R5 = DM(0x30c080);
      R6 = 1;
      R5 = R5 - R6;
      DM(0x30c080) = R5;
      IF NE JUMP 0x185880;             // -> os_loop.

      R0 = DM(0x30c000);
      R1 = DM(0x30c004);
      R2 = DM(0x30c008);
      R3 = DM(0x30c00c);
      R4 = DM(0x30c010);
      R5 = DM(0x30c014);
      R6 = DM(0x30c018);
      R7 = DM(0x30c01c);
      R8 = DM(0x30c020);
      R9 = DM(0x30c024);
      R10 = DM(0x30c028);
      R11 = DM(0x30c02c);
      R12 = DM(0x30c030);
      R13 = DM(0x30c034);
      R14 = DM(0x30c038);
      R15 = DM(0x30c03c);
      I0 = DM(0x30c040);
      I1 = DM(0x30c044);
      I2 = DM(0x30c048);
      I3 = DM(0x30c04c);
      I4 = DM(0x30c050);
      I5 = DM(0x30c054);
      I12 = DM(0x30c058);
      M0 = DM(0x30c05c);
      M1 = DM(0x30c060);
      M2 = DM(0x30c064);
      M3 = DM(0x30c068);
      M4 = DM(0x30c06c);
      R0 = DM(0x30c070);
      I6 = R0;                          // the dispatch's frame, whatever the render left
      R0 = DM(0x30c074);
      I7 = R0;

      // the two instructions the entry JUMP replaced (0x1c9448, 0x1c944a)
      I5 = DM(-24, I6);
      R10 = DM(-34, I6);
      JUMP 0x1c944c;

      // os_quiet sits out of line: the instruction after the render's CJUMP and
      // its delay slots is where the render's RETURN comes back to (the PC stack),
      // so that must stay os_next.
.GLOBAL os_quiet.;
os_quiet.:
      I4 = R8;
      R3 = 0;
      DM(0, I4) = R3;
      DM(1, I4) = R3;
      DM(2, I4) = R3;
      DM(3, I4) = R3;
      DM(4, I4) = R3;
      DM(5, I4) = R3;
      DM(6, I4) = R3;
      DM(7, I4) = R3;
      DM(8, I4) = R3;
      DM(9, I4) = R3;
      DM(10, I4) = R3;
      DM(11, I4) = R3;
      DM(12, I4) = R3;
      DM(13, I4) = R3;
      DM(14, I4) = R3;
      DM(15, I4) = R3;
      DM(16, I4) = R3;
      DM(17, I4) = R3;
      DM(18, I4) = R3;
      DM(19, I4) = R3;
      DM(20, I4) = R3;
      DM(21, I4) = R3;
      DM(22, I4) = R3;
      DM(23, I4) = R3;
      DM(24, I4) = R3;
      DM(25, I4) = R3;
      DM(26, I4) = R3;
      DM(27, I4) = R3;
      DM(28, I4) = R3;
      DM(29, I4) = R3;
      DM(30, I4) = R3;
      DM(31, I4) = R3;
      JUMP 0x185a47;                   // -> os_next.
.os_type5..end:
      .type os_type5.,STT_FUNC;
