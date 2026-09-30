// block_count.asm -- how often the per-block routine runs, so the ColdFire can see it.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in).
//
// The build's entry JUMP at sw 0x1c9448 (in the machine dispatch of the per-block
// routine sw 0x1c2712, after the Swarmer render loop; dnfw.waverider.dsp patch 2)
// comes here instead of straight to the type-5 loop. Every block passes it, whatever
// the machines: it adds 1 to a running count, writes the count, halves swapped as the
// per-frame handler stores reply word 0, to reply word 2 of both reply pages (bytes the
// ColdFire never reads), and goes on to the type-5 loop at sw 0x16ed00, unchanged.
//
// Why: on the Waverider build the SHARC's load falls about 23 points after a Waverider
// note (docs/sharc-load.md), about 154,000 cycles a frame, which is close to the
// per-block routine's own cost in the emulator (about 153,000 instructions). The count
// per second says whether that routine runs less often in the low state.
//
// It uses R8 and R9, saved to its own words. ASTAT is left as the type-5 loop leaves
// it anyway (the loop compares before its first test).
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f580 (L1 block 1, byte 0x2deb00).
//
// DM (byte addresses, in the state block the build zero-fills):
//   0x2de118  blocks, cumulative (mod 2^32)
//   0x2de11c  save: R8;  0x2de120  save: R9
//   0x2c49d8, 0x2c59d8  reply word 2 of the two reply pages

.SECTION/PM seg_pmco;

.GLOBAL wr_count.;
wr_count.:
      DM(0x2de11c) = R8;
      DM(0x2de120) = R9;
      R8 = DM(0x2de118);
      R9 = 1;
      R8 = R8 + R9;                     // blocks
      DM(0x2de118) = R8;
      R9 = LSHIFT R8 BY 16;
      R8 = LSHIFT R8 BY -16;
      R8 = R8 OR R9;                    // halves swapped, as reply word 0
      DM(0x2c49d8) = R8;                // reply word 2, both pages
      DM(0x2c59d8) = R8;
      R8 = DM(0x2de11c);
      R9 = DM(0x2de120);
      JUMP 0x16ed00;                    // on to the type-5 loop
.wr_count..end:
