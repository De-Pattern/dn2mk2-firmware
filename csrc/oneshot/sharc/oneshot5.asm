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
//      unpack), builds a DT2-shaped voice record at 0x296000 + 0x1d8 t from six
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
//   0x295900  save area, 32 words: R0-R15, I0-I5, I12, M0-M4
//   0x295980  tracks left            0x295984  this track's index
//   0x295988  this track's record    0x29598c  this track's frame slot
//   0x295990  -> machine type word   0x295994  -> track buffer pointer
//   0x295998  this track's buffer    0x2959a0  six coarse parameters
//   0x296000  16 records of 0x1d8 bytes (a zero-fill block at boot)
//   0x297e00  256 steps, 2 words each (ours: 0.5 * 2^((c - 64) / 12), Q31)
//   0x298800  the sample bank: 'OSB1', count, (pointer, length, rate) ...
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
      DM(0x295900) = R0;
      DM(0x295904) = R1;
      DM(0x295908) = R2;
      DM(0x29590c) = R3;
      DM(0x295910) = R4;
      DM(0x295914) = R5;
      DM(0x295918) = R6;
      DM(0x29591c) = R7;
      DM(0x295920) = R8;
      DM(0x295924) = R9;
      DM(0x295928) = R10;
      DM(0x29592c) = R11;
      DM(0x295930) = R12;
      DM(0x295934) = R13;
      DM(0x295938) = R14;
      DM(0x29593c) = R15;
      DM(0x295940) = I0;
      DM(0x295944) = I1;
      DM(0x295948) = I2;
      DM(0x29594c) = I3;
      DM(0x295950) = I4;
      DM(0x295954) = I5;
      DM(0x295958) = I12;
      DM(0x29595c) = M0;
      DM(0x295960) = M1;
      DM(0x295964) = M2;
      DM(0x295968) = M3;
      DM(0x29596c) = M4;
      // Save I6/I7 too. The transplanted render ends in RFRAME, which sets
      // I6/I7 from the frame CJUMP built; on a never-triggered (word-0 = 0)
      // record it leaves the caller's I7 pointing at a word we did not own, and
      // the DN2 block loop carries I7 into the next block. Restored at the exit.
      R0 = I6;
      DM(0x295970) = R0;
      R0 = I7;
      DM(0x295974) = R0;

      R0 = 16;
      DM(0x295980) = R0;
      R0 = 0;
      DM(0x295984) = R0;
      R0 = 0x296000;
      DM(0x295988) = R0;
      R0 = 0x25c566;                    // the frame copy 0x25c48c + slot 218
      DM(0x29598c) = R0;
      R0 = 0x25566c;                    // &track[0].machine (0x2554b8 + 0x1b4)
      DM(0x295990) = R0;
      R0 = 0x254a60;                    // &track_buffer[0]
      DM(0x295994) = R0;

.GLOBAL os_loop.;
os_loop.:
      I4 = DM(0x295990);
      R2 = DM(0, I4);                   // this track's machine type
      I4 = DM(0x295994);
      R3 = DM(0, I4);                   // this track's buffer
      DM(0x295998) = R3;
      R1 = 5;
      COMP(R2, R1);
      IF NE JUMP 0x18121b;             // -> os_next.
      R1 = DM(0x298800);                // the bank's magic
      R2 = 0x3142534f;
      COMP(R1, R2);
      IF NE JUMP 0x18121b;             // -> os_next.

      // the note trigger: byte t of the words at engine + 0x138fc
      R0 = DM(0x295984);
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
      IF EQ JUMP 0x18120b;             // no trigger -> os_render.

      // six coarse parameters from the frame slot: word k at slot + 2k
      R8 = DM(0x29598c);
      R9 = 0xfffffffc;
      R10 = 2;
      R11 = 0;
      R12 = 0xff;
      R0 = R8;
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = LSHIFT R2 BY -8;
      R2 = R2 AND R12;
      DM(0x2959a0) = R2;
      R0 = R8 + R10;
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = LSHIFT R2 BY -8;
      R2 = R2 AND R12;
      DM(0x2959a4) = R2;
      R0 = R0 + R10;
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = LSHIFT R2 BY -8;
      R2 = R2 AND R12;
      DM(0x2959a8) = R2;
      R0 = R0 + R10;
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = LSHIFT R2 BY -8;
      R2 = R2 AND R12;
      DM(0x2959ac) = R2;
      R0 = R0 + R10;
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = LSHIFT R2 BY -8;
      R2 = R2 AND R12;
      DM(0x2959b0) = R2;
      R0 = R0 + R10;
      R1 = R0 AND R9;
      I4 = R1;
      R2 = DM(0, I4);
      R3 = R0 AND R10;
      R3 = LSHIFT R3 BY 3;
      R3 = R11 - R3;
      R2 = LSHIFT R2 BY R3;
      R2 = LSHIFT R2 BY -8;
      R2 = R2 AND R12;
      DM(0x2959b4) = R2;

      // SAMP through the directory; a slot past the count plays slot 0
      R1 = DM(0x2959a8);
      R2 = DM(0x298804);
      COMPU(R1, R2);
      IF GE R1 = R1 - R1;
      R2 = 12;
      R1 = R1 * R2 (SSI);
      R2 = 0x298808;
      R1 = R1 + R2;
      I4 = R1;
      R13 = DM(0, I4);                  // pointer
      R14 = DM(1, I4);                  // len

      // S = min((STRT * len) >> 7, len - 1)
      R0 = DM(0x2959ac);
      R0 = R0 * R14 (SSI);
      R0 = LSHIFT R0 BY -7;
      R1 = 1;
      R2 = R14 - R1;
      R0 = MIN(R0, R2);                 // R0 = S
      // L = LEN >= 127 ? len : (LEN * len) >> 7
      R3 = DM(0x2959b0);
      R4 = R3 * R14 (SSI);
      R4 = LSHIFT R4 BY -7;
      R5 = 127;
      COMP(R3, R5);
      IF GE R4 = PASS R14;
      // E = min(S + L, len); E <= S -> S + 1
      R4 = R0 + R4;
      R4 = MIN(R4, R14);
      R5 = R0 + R1;
      R4 = MAX(R4, R5);                 // R4 = E
      // P = (LOOP * len) >> 7; P >= E -> S
      R6 = DM(0x2959b4);
      R6 = R6 * R14 (SSI);
      R6 = LSHIFT R6 BY -7;
      COMP(R6, R4);
      IF GE R6 = PASS R0;               // R6 = P
      // PLAY: bit 0 reverse, bit 1 loop
      R7 = DM(0x2959a4);
      R8 = R7 AND R1;                   // reverse
      R9 = LSHIFT R7 BY -1;
      R9 = R9 AND R1;                   // loop
      // step = steps[TUNE + 128 * reverse], two words
      R10 = LSHIFT R8 BY 7;
      R11 = DM(0x2959a0);
      R10 = R10 + R11;
      R10 = LSHIFT R10 BY 3;
      R11 = 0x297e00;
      R10 = R10 + R11;
      I4 = R10;
      R10 = DM(0, I4);                  // step lo
      R11 = DM(1, I4);                  // step hi
      // phase = reverse ? E - 1 : S
      R12 = R4 - R1;
      R8 = PASS R8;
      IF EQ R12 = PASS R0;

      // the record
      R15 = DM(0x295988);
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
      R4 = DM(0x295988);
      R8 = DM(0x295998);
      R12 = DM(0x295924);               // the dispatch's R9: the block size
      // The transplanted render ends in a RETURN whose delay slot is RFRAME:
      // it needs both a PC-stack return and the frame link (I6 = I7, R2 = old
      // I6) that the donor's own frame-linked caller (0x1c6b00) sets up. CJUMP
      // does exactly both (digikit `_type_25a_direct`: call = True and the
      // cjump-frame), so the render is reached with CJUMP and the two software-
      // stack pushes, as machine5_dir reaches the reader.
      CJUMP 0x180800 (DB);             // the transplanted render
      DM(I7, M7) = R2;
      DM(I7, M7) = 0x18121a;           // return address - 1: os_next. - 1

.GLOBAL os_next.;
os_next.:
      R5 = DM(0x295984);
      R6 = 1;
      R5 = R6 + R5;
      DM(0x295984) = R5;
      R5 = DM(0x295988);
      R6 = 0x1d8;
      R5 = R6 + R5;
      DM(0x295988) = R5;
      R5 = DM(0x29598c);
      R6 = 146;
      R5 = R6 + R5;
      DM(0x29598c) = R5;
      R5 = DM(0x295990);
      R6 = 0x234;
      R5 = R6 + R5;
      DM(0x295990) = R5;
      R5 = DM(0x295994);
      R6 = 4;
      R5 = R6 + R5;
      DM(0x295994) = R5;
      R5 = DM(0x295980);
      R6 = 1;
      R5 = R5 - R6;
      DM(0x295980) = R5;
      IF NE JUMP 0x181080;             // -> os_loop.

      R0 = DM(0x295900);
      R1 = DM(0x295904);
      R2 = DM(0x295908);
      R3 = DM(0x29590c);
      R4 = DM(0x295910);
      R5 = DM(0x295914);
      R6 = DM(0x295918);
      R7 = DM(0x29591c);
      R8 = DM(0x295920);
      R9 = DM(0x295924);
      R10 = DM(0x295928);
      R11 = DM(0x29592c);
      R12 = DM(0x295930);
      R13 = DM(0x295934);
      R14 = DM(0x295938);
      R15 = DM(0x29593c);
      I0 = DM(0x295940);
      I1 = DM(0x295944);
      I2 = DM(0x295948);
      I3 = DM(0x29594c);
      I4 = DM(0x295950);
      I5 = DM(0x295954);
      I12 = DM(0x295958);
      M0 = DM(0x29595c);
      M1 = DM(0x295960);
      M2 = DM(0x295964);
      M3 = DM(0x295968);
      M4 = DM(0x29596c);
      R0 = DM(0x295970);
      I6 = R0;                          // the dispatch's frame, whatever the render left
      R0 = DM(0x295974);
      I7 = R0;

      // the two instructions the entry JUMP replaced (0x1c9448, 0x1c944a)
      I5 = DM(-24, I6);
      R10 = DM(-34, I6);
      JUMP 0x1c944c;
.os_type5..end:
      .type os_type5.,STT_FUNC;
