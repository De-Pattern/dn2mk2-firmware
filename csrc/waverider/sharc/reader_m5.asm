// reader_m5.asm -- Waverider Milestone 5: reader.asm (Milestone 1) restricted to the
// instruction forms the shipping firmware itself uses, for the first flash.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). Run offline in digikit's SHARC executor and checked bit for bit against
// dnfw.waverider.render (float32); it has never run on a DSP.
//
// Same contract as reader.asm -- wr_render(R4 = params), 16 frames x 512 int16, linear
// between samples and between frames; the block is (table, phase, inc, pos, count,
// out) -- and the same arithmetic, in the same order, so it is bit-identical. What
// changed, and why (docs/waverider-m5-dsp.md, "Instruction forms"):
//
// 1. **No DAG1 M0-M3 in a memory access.** Of the firmware's 1,266 16-bit Type 3c
//    accesses, every one names M4-M7; M0-M3 appear in no Type 3a/3c access at all.
//    For M0-M3 selas and selache's own disassembler disagree -- selas's
//    `R3 = DM(I0, M0)` (0x9013) reads to selmap as a load into DADDR, and
//    `R4 = DM(M2, I0)` as `DM(M6, I0)` -- so which one the silicon follows is not
//    known, and reader.asm's frame-row dummy reads and inner-loop taps used them.
//    Here the rows are byte arithmetic on the table pointer (a frame is 1,024 bytes),
//    the firmware's own idiom (`r1 = r4 + r1` at 0x1c9259), and the taps use M4.
// 2. **Pre-modify reads only inside the DO loop**, where selas emits the 48-bit Type
//    3a. Outside a loop it compresses `R4 = DM(M4, I0)` to the same 16-bit parcel as
//    the post-modify `R4 = DM(I0, M4)` (0x9114), which updates I0.
// 3. **An add whose first operand is R8-R15** where the 16-bit form would be a
//    parcel 0xc000..0xc07f, which digikit's decoder can read as the first half of a
//    32-bit Type 2b (runner gap G5); selas then emits a 32-bit form both decoders
//    read alike.
//
// The gate (scripts/sharc_waverider_m5.py) checks that selmap and digikit read every
// instruction here as its source line says.
//
// Clobbers R0-R15, I0-I2, I4, M4, LCNTR, ASTAT. Uses M6 = 1, M7 = -1, M14 = 1 as fixed
// by the SHARC C ABI. Not ABI-clean: machine5_live.asm saves what it needs.

.SECTION/PM seg_pmco;

.GLOBAL wr_render5.;
wr_render5.:
      I4 = R4;                          // I4 -> parameter block
      R8 = DM(0, I4);                   // table (a byte address)
      R9 = DM(1, I4);                   // phase
      R10 = DM(2, I4);                  // inc
      R11 = DM(3, I4);                  // pos, Q16
      R12 = DM(4, I4);                  // N
      R0 = DM(5, I4);
      I2 = R0;                          // out

      // Frame rows: f0 = pos >> 16, f1 = min(f0 + 1, 15); a frame is 256 words,
      // 1,024 bytes.
      R0 = LSHIFT R11 BY -16;
      R2 = 1;
      R1 = R0 + R2;
      R2 = 15;
      R1 = MIN(R1, R2);
      R0 = LSHIFT R0 BY 10;
      R1 = LSHIFT R1 BY 10;
      R0 = R8 + R0;
      I0 = R0;                          // I0 -> frame f0
      R1 = R1 + R8;
      I1 = R1;                          // I1 -> frame f1

      // Frame fraction ff = (pos & 0xffff) * 2^-16, exact in float32.
      R3 = 0xffff;
      R3 = R11 AND R3;
      R2 = -16;
      F11 = FLOAT R3 BY R2;

      R13 = 0x800000;                   // half a sample: w1 = (phase + 2^23) >> 24
      R14 = 0x7fffff;                   // sample fraction mask
      R15 = -23;                        // sample fraction scale, 2^-23
      R8 = -15;                         // int16 -> float full scale, 2^-15

      // Register-count ASHIFT and the combined LCNTR/DO, as in reader.asm.
      R2 = PASS R12;
      R12 = -16;
      LCNTR = R2, DO .wr5_loop_end UNTIL LCE;
            // Samples k and k+1 (mod 512) always differ in parity: when k is even
            // they share word k>>1 (low, then high half); when k is odd they are
            // the high half of word k>>1 and the low half of the next word.
            R0 = LSHIFT R9 BY -24;      // w0 = k >> 1
            R1 = R9 + R13;
            R1 = LSHIFT R1 BY -24;      // w1 = (k + 1) >> 1, mod 256
            R2 = 16;
            R3 = LSHIFT R9 BY -19;
            R3 = R3 AND R2;             // shB = 16 * (k & 1)
            R2 = R3 XOR R2;             // shA = 16 - shB

            M4 = R0;
            R4 = DM(M4, I0);            // frame f0, word w0
            R6 = DM(M4, I1);            // frame f1, word w0
            M4 = R1;
            R5 = DM(M4, I0);            // frame f0, word w1
            R7 = DM(M4, I1);            // frame f1, word w1

            R4 = LSHIFT R4 BY R2;
            R4 = ASHIFT R4 BY R12;      // s00 = sample k
            R5 = LSHIFT R5 BY R3;
            R5 = ASHIFT R5 BY R12;      // s01 = sample k + 1
            F4 = FLOAT R4 BY R8;
            F5 = FLOAT R5 BY R8;

            R6 = LSHIFT R6 BY R2;
            R6 = ASHIFT R6 BY R12;      // s10
            R7 = LSHIFT R7 BY R3;
            R7 = ASHIFT R7 BY R12;      // s11
            F6 = FLOAT R6 BY R8;
            F7 = FLOAT R7 BY R8;

            R0 = R9 AND R14;
            F0 = FLOAT R0 BY R15;       // sample fraction, exact

            F5 = F5 - F4;
            F5 = F0 * F5;
            F4 = F4 + F5;               // a = s00 + fr * (s01 - s00)
            F7 = F7 - F6;
            F7 = F0 * F7;
            F6 = F6 + F7;               // b = s10 + fr * (s11 - s10)
            F6 = F6 - F4;
            F6 = F11 * F6;
            F4 = F4 + F6;               // y = a + ff * (b - a)

            R9 = R9 + R10;              // phase += inc, mod 2^32
.wr5_loop_end:
            DM(I2, M6) = F4;

      DM(1, I4) = R9;                   // phase, for the next block
      I12 = DM(M7, I6);
      JUMP (M14, I12) (DB);
      RFRAME;
      NOP;
.wr_render5..end:
      .type wr_render5.,STT_FUNC;
