// wt_place.asm -- DISCRIMINATOR ONLY, never shipped: our reader in WaveTone's place.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in). docs/waverider-dsp-compare.md says why this exists.
//
// The build (scripts/build_waverider_disc_wtplace.py) changes one CALL in stock
// section 7: the WaveTone arm's `CALL 0x1c6d4a` at sw 0x1c9611 becomes `CALL 0x16ed00`,
// this code. Nothing else of Waverider's plumbing is present: no machine-type lookup
// patch (no type 5), no entry JUMP at sw 0x1c9448, no type-5 loop.
//
// It is entered exactly as WaveTone's render is, through the firmware's own call:
//   R4  = this track's WaveTone voice state (unused here)
//   R8  = this track's record + 0x9c (unused)
//   R12 = this track's buffer, DM(0x254a60 + 4t): 32 floats
//   the stack: R9 (the block size) pushed by the arm; I6 = the frame the call made,
//   DM(0, I6) = the caller's I6, DM(-1, I6) = the return address - 1.
//
// It is a C-ABI callee, unlike wr_render5 (which clobbers callee-saved registers and
// relies on its caller, the type-5 loop, to save everything): it saves every R and
// the I registers the reader touches, fills one parameter block with constants (table
// 0 frame 0, the saw; note 60; POS 0; 32 samples), calls wr_render5 at sw 0x16eb00 the
// way the type-5 loop does, restores, and returns in the firmware's shape.
//
// A shared parameter block: every WaveTone track shares one phase. The test uses one.
//
// DM (byte addresses, the same block-1 region as M5c/M5d, written end to end at boot):
//   0x2dde00  save area: R0-R15, I0-I5
//   0x2ddf00  the parameter block: table, phase, inc, pos, count, out

.SECTION/PM seg_pmco;

.GLOBAL wr_wtplace.;
wr_wtplace.:
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

      R8 = 0x2df000;                    // table 0 (saw -> sine); POS 0 is the saw
      DM(0x2ddf00) = R8;
      R8 = 23409860;                    // inc for note 60 (dnfw.waverider.live.increment)
      DM(0x2ddf08) = R8;
      R8 = R8 - R8;
      DM(0x2ddf0c) = R8;                // pos 0
      R8 = 32;                          // count: the block size (0x257e6c word 0 = 32,
      DM(0x2ddf10) = R8;                // written once, at engine init, sw 0x1c14a8)
      DM(0x2ddf14) = R12;               // out: this track's buffer
      R4 = 0x2ddf00;                    // wr_render5's argument: the parameter block
      CJUMP 0x16eb00 (DB);              // wr_render5(R4)
      DM(I7, M7) = R2;
      DM(I7, M7) = 0x16ed48;            // return address - 1: wr_wt_back. - 1

.GLOBAL wr_wt_back.;
wr_wt_back.:
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
      I12 = DM(M7, I6);                 // the return address - 1, as the firmware's callees
      R0 = DM(0x2dde00);                // one instruction between the load and the jump
      JUMP (M14, I12) (DB);
      NOP;
      RFRAME;
.wr_wtplace..end:
      .type wr_wtplace.,STT_FUNC;
