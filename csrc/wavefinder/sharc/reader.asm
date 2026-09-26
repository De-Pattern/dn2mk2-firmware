// reader.asm -- Wavefinder Milestone 1: a minimal SHARC+ wavetable reader.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and
// never linked in; docs/wavefinder-feasibility.md, "Milestone 1"). It is run
// offline in digikit's SHARC executor and checked against
// dnfw.wavefinder.render, the Python reference. It has never run on a DSP.
//
// wf_render(R4 = params): render N samples from one 16 x 512 int16 wavetable,
// linearly interpolated between neighbouring samples AND between neighbouring
// frames.
//
// The parameter block, one 32-bit word each (DM, normal-word addressing):
//   +0  table   pointer to the table: 16 frames x 256 words, frame-major, each
//               word two int16 samples, the even sample in the low half
//               (little-endian int16 -- dnfw.wavefinder.render.dsp_bytes)
//   +1  phase   u32 phase accumulator: bits 31..23 are the sample index 0..511,
//               bits 22..0 the fraction between it and the next. Wraps mod 2^32,
//               which is exactly mod 512 samples. Written back on return.
//   +2  inc     u32 phase increment per output sample
//   +3  pos     frame position, Q16: bits 19..16 frame 0..15, bits 15..0 the
//               fraction towards the next frame; at most 15 << 16 (frame
//               15 interpolates with itself)
//   +4  count   N, at least 1
//   +5  out     pointer to N float32 words; full scale is 1.0 (int16 / 32768)
//
// Addressing uses only DAG modify / indexed access (M registers), never ALU
// arithmetic on an address, so the word stride is the DAG's, not ours.
//
// Clobbers R0-R15, I0-I2, I4, M0-M3, LCNTR, ASTAT. Uses M6 = 1, M7 = -1,
// M14 = 1 as fixed by the SHARC C ABI. Not yet ABI-clean (callee-saved
// registers are not saved): an offline-gate routine, not a drop-in.

.SECTION/PM seg_pmco;

.GLOBAL wf_render.;
wf_render.:
      I4 = R4;                          // I4 -> parameter block
      R8 = DM(0, I4);                   // table
      R9 = DM(1, I4);                   // phase
      R10 = DM(2, I4);                  // inc
      R11 = DM(3, I4);                  // pos, Q16
      R12 = DM(4, I4);                  // N
      R0 = DM(5, I4);
      I2 = R0;                          // out

      // Frame rows: f0 = pos >> 16, f1 = min(f0 + 1, 15); 256 words a frame.
      R0 = LSHIFT R11 BY -16;
      R2 = 1;
      R1 = R0 + R2;
      R2 = 15;
      R1 = MIN(R1, R2);
      R0 = LSHIFT R0 BY 8;
      R1 = LSHIFT R1 BY 8;
      // I0 += M0 by a post-modify load, not MODIFY. selas encodes MODIFY (I4, M4)
      // as 0x04240f800000 (and, compressed in this file, MODIFY (I0, M0) as
      // 0x043e0000); the shipping firmware's MODIFY (I4, M4) is the 48-bit Type
      // 7a 0x043f20000000. digikit's decoder follows the firmware and reads
      // selas's forms as other instructions. A post-modify load is the same DAG
      // operation in a form both toolchains encode alike; the word is discarded.
      I0 = R8;
      M0 = R0;
      R3 = DM(I0, M0);                  // I0 -> frame f0
      I1 = R8;
      M1 = R1;
      R3 = DM(I1, M1);                  // I1 -> frame f1

      // Frame fraction ff = (pos & 0xffff) * 2^-16, exact in float32.
      R3 = 0xffff;
      R3 = R11 AND R3;
      R2 = -16;
      F11 = FLOAT R3 BY R2;

      R13 = 0x800000;                   // half a sample: w1 = (phase + 2^23) >> 24
      R14 = 0x7fffff;                   // sample fraction mask
      R15 = -23;                        // sample fraction scale, 2^-23
      R8 = -15;                         // int16 -> float full scale, 2^-15

      // Every ASHIFT takes its count from a register. selas encodes the
      // immediate `R0 = ASHIFT R0 BY -31` as 0x023e0020e100, where the
      // firmware's immediate ASHIFTs carry a different shifter-op field
      // (digikit: "unsupported ShiftImm opcode 0x20"); selache's own runtime
      // library avoids the immediate ASHIFT for the same reason and uses the
      // register form. N moves to R2 so R12 is free for the count: a separate
      // `LCNTR = R12; DO ...` is Type 13a, which digikit's executor does not
      // run, while the combined form below is the one the firmware uses.
      R2 = PASS R12;
      R12 = -16;
      LCNTR = R2, DO .wf_loop_end UNTIL LCE;
            // The two samples either side of the phase are indices k and k+1
            // (mod 512), which always differ in parity: when k is even they
            // share word k>>1 (low, then high half); when k is odd they are
            // the high half of word k>>1 and the low half of the next word.
            R0 = LSHIFT R9 BY -24;      // w0 = k >> 1
            R1 = R9 + R13;
            R1 = LSHIFT R1 BY -24;      // w1 = (k + 1) >> 1, mod 256
            R2 = 16;
            R3 = LSHIFT R9 BY -19;
            R3 = R3 AND R2;             // shB = 16 * (k & 1)
            R2 = R3 XOR R2;             // shA = 16 - shB
            M2 = R0;
            M3 = R1;

            R4 = DM(M2, I0);            // frame f0
            R5 = DM(M3, I0);
            R4 = LSHIFT R4 BY R2;
            R4 = ASHIFT R4 BY R12;      // s00 = sample k
            R5 = LSHIFT R5 BY R3;
            R5 = ASHIFT R5 BY R12;      // s01 = sample k + 1
            F4 = FLOAT R4 BY R8;
            F5 = FLOAT R5 BY R8;

            R6 = DM(M2, I1);            // frame f1
            R7 = DM(M3, I1);
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
.wf_loop_end:
            DM(I2, M6) = F4;

      DM(1, I4) = R9;                   // phase, for the next block
      I12 = DM(M7, I6);
      JUMP (M14, I12) (DB);
      RFRAME;
      NOP;
.wf_render..end:
      .type wf_render.,STT_FUNC;
