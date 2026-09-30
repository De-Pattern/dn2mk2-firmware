// entry_mark.asm -- EMUCLK as the per-frame handler calls the per-block routine.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in).
//
// The handler calls the per-block routine sw 0x1c2712 from sw 0x1c9fbc (`cjump 0x1c2712
// (db)`), after loading its first argument at sw 0x1c9fb9: `r4 = 0x268438`. The build
// replaces that one 48-bit load with `JUMP 0x16f680`; this stores EMUCLK as MARK0,
// performs the load it displaced, and jumps back to the cjump. idle_load.asm splits each
// busy stretch at MARK0 (the handler, and whatever it waits on, before the call) and at
// block_count.asm's MARK (the machine dispatch's splice).
//
// It uses R9 only, saved to its own word: R4, R8 and R12 are the call's arguments.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f680 (L1 block 1, byte 0x2ded00).
//
// DM (byte addresses, in the state block the build zero-fills):
//   0x2de138  save: R9
//   0x2de13c  MARK0

.SECTION/PM seg_pmco;

.GLOBAL wr_emark.;
wr_emark.:
      DM(0x2de138) = R9;
      R9 = EMUCLK;
      DM(0x2de13c) = R9;                // MARK0
      R9 = DM(0x2de138);
      R4 = 0x268438;                    // the displaced load
      JUMP 0x1c9fbc;                    // back to the call
.wr_emark..end:
