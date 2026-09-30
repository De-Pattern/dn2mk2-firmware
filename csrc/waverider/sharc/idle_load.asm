// idle_load.asm -- the SHARC's idle time, and how its busy time falls around the dispatch.
//
// Our own code, assembled with selache's `selas` (GPL-3.0, used as a tool and never
// linked in).
//
// The SHARC runs FreeRTOS, and its idle task (prvIdleTask, sw 0xb88aa6: created by
// vTaskStartScheduler at sw 0xb887db with the name "IDLE", 0x2d0760) spins:
//
//   b88aab  call prvCheckTasksWaitingTermination
//   b88ab2  if more than one task is ready at the idle priority, yield
//   b88abb  jump b88aab                      <- the build makes this `JUMP 0x16f500`
//
// so this runs once a pass. It reads EMUCLK; d = the cycles since the previous pass.
//
// - d < THRESHOLD: the idle task going round. d is added to the idle total, which goes
//   (halves swapped, as the per-frame handler stores reply word 0, so the ColdFire reads
//   a big-endian u32) to reply word 1 of both reply pages.
// - d >= THRESHOLD: the idle task was preempted, and a busy stretch ran from the previous
//   pass (`last`) to now. Two marks split it: MARK0 (entry_mark.asm: EMUCLK as the
//   handler calls the per-block routine) and MARK (block_count.asm: EMUCLK where the
//   machine dispatch passes our splice, sw 0x1c9448). When MARK0 lies inside the stretch,
//   MARK0 - last (A: the handler, and whatever it waits on) goes to the BEFORE total
//   (reply word 3); when MARK does, now - MARK (C: the per-track chain, FX, mix) goes to
//   the AFTER total (reply word 4). The host has B (the routine from its entry to the
//   splice: the frame unpack and the stock render loops) as busy - A - C.
//
// Reply words 1-4 (bytes 4..0x13) are bytes the ColdFire never reads
// (docs/for-digikit-waverider-dsp-stop.md); word 5 is not used, since +0x16 is the
// compressor's gain reduction. The host differences readings (tools/dn2sharc_load.py).
//
// It uses R8-R11, saved to its own area (the render loop's save area is not shared: the
// audio task can preempt the idle task at any instruction), and leaves ASTAT to the idle
// loop, which recomputes what it tests.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f500 (L1 block 1, byte 0x2dea00).
//
// DM (byte addresses, in the state block the build zero-fills):
//   0x2de100  save: R8, R9, R10;  0x2de134  save: R11
//   0x2de10c  EMUCLK at the previous pass
//   0x2de110  idle cycles, cumulative (mod 2^32)
//   0x2de114  passes, cumulative
//   0x2de124  MARK (written by block_count.asm);  0x2de13c  MARK0 (entry_mark.asm)
//   0x2de128  BEFORE, cumulative;  0x2de12c  AFTER, cumulative
//   0x2c49d4 / 0x2c59d4, 0x2c49dc / 0x2c59dc, 0x2c49e0 / 0x2c59e0  reply words 1, 3, 4

.SECTION/PM seg_pmco;

.GLOBAL wr_idle.;
wr_idle.:
      DM(0x2de100) = R8;
      DM(0x2de104) = R9;
      DM(0x2de108) = R10;
      DM(0x2de134) = R11;

      R9 = DM(0x2de114);
      R10 = 1;
      R9 = R9 + R10;
      DM(0x2de114) = R9;                // passes

      R8 = EMUCLK;                      // now
      R9 = DM(0x2de10c);                // last
      DM(0x2de10c) = R8;
      R10 = R8 - R9;                    // d
      R11 = 4096;                       // THRESHOLD
      COMPU(R10, R11);
      IF GE JUMP 0x16f53d;              // -> wr_idle_busy.

      R9 = DM(0x2de110);
      R9 = R9 + R10;                    // idle cycles, cumulative
      DM(0x2de110) = R9;
      R10 = LSHIFT R9 BY 16;
      R9 = LSHIFT R9 BY -16;
      R9 = R9 OR R10;                   // halves swapped, as reply word 0
      DM(0x2c49d4) = R9;                // reply word 1, both pages
      DM(0x2c59d4) = R9;
      JUMP 0x16f57b;                    // -> wr_idle_out.

.GLOBAL wr_idle_busy.;
wr_idle_busy.:
      R11 = DM(0x2de13c);               // MARK0: the handler calling the per-block routine
      R11 = R11 - R9;                   // MARK0 - last
      COMPU(R11, R10);                  // inside the stretch (0 <= MARK0 - last < d)?
      IF GE JUMP 0x16f55a;              // -> wr_idle_after. (not in it)
      R9 = DM(0x2de128);
      R9 = R9 + R11;                    // BEFORE (A: stretch start -> MARK0), cumulative
      DM(0x2de128) = R9;
      R8 = LSHIFT R9 BY 16;
      R9 = LSHIFT R9 BY -16;
      R9 = R9 OR R8;
      DM(0x2c49dc) = R9;                // reply word 3, both pages
      DM(0x2c59dc) = R9;

.GLOBAL wr_idle_after.;
wr_idle_after.:
      R8 = DM(0x2de10c);                // now (stored as LAST above)
      R11 = DM(0x2de124);               // MARK: the machine dispatch's splice
      R11 = R8 - R11;                   // now - MARK
      COMPU(R11, R10);                  // inside the stretch (0 <= now - MARK < d)?
      IF GE JUMP 0x16f57b;              // -> wr_idle_out. (not in it)
      R9 = DM(0x2de12c);
      R9 = R9 + R11;                    // AFTER (C: MARK -> stretch end), cumulative
      DM(0x2de12c) = R9;
      R8 = LSHIFT R9 BY 16;
      R9 = LSHIFT R9 BY -16;
      R9 = R9 OR R8;
      DM(0x2c49e0) = R9;                // reply word 4, both pages
      DM(0x2c59e0) = R9;

.GLOBAL wr_idle_out.;
wr_idle_out.:
      R8 = DM(0x2de100);
      R9 = DM(0x2de104);
      R10 = DM(0x2de108);
      R11 = DM(0x2de134);
      JUMP 0xb88aab;                    // back to the idle loop's top
.wr_idle..end:
