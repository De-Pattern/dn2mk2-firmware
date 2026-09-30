// idle_load.asm -- the SHARC's idle time, so its whole load can be read from the ColdFire.
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
// so this runs once a pass. It reads EMUCLK and adds the cycles since the previous
// pass to a running total when they are fewer than THRESHOLD: a short gap is the idle
// task going round, a long one is the idle task having been preempted by real work.
// The total, halves swapped as the per-frame handler stores reply word 0 (so the
// ColdFire reads it as a big-endian u32), goes to reply word 1 of both reply pages,
// bytes the ColdFire never reads (docs/for-digikit-waverider-dsp-stop.md). The host
// differences two readings: idle = d(total) / d(cycles), with the cycles taken from
// the ColdFire's own frame count (1,500 frames/s at 1 GHz: docs/sharc-load.md).
//
// It uses R8-R10 only, saved to its own area (the render loop's save area is not
// shared: the audio task can preempt the idle task at any instruction), and leaves
// ASTAT to the idle loop, which recomputes what it tests.
//
// PLACEMENT IS FIXED: this code loads at PM sw 0x16f500 (L1 block 1, byte 0x2dea00).
//
// DM (byte addresses, in the state block the build zero-fills):
//   0x2de100  save area: R8, R9, R10
//   0x2de10c  EMUCLK at the previous pass
//   0x2de110  idle cycles, cumulative (mod 2^32)
//   0x2de114  passes, cumulative
//   0x2c49d4, 0x2c59d4  reply word 1 of the two reply pages

.SECTION/PM seg_pmco;

.GLOBAL wr_idle.;
wr_idle.:
      DM(0x2de100) = R8;
      DM(0x2de104) = R9;
      DM(0x2de108) = R10;

      R9 = DM(0x2de114);
      R10 = 1;
      R9 = R9 + R10;
      DM(0x2de114) = R9;                // passes

      R8 = EMUCLK;
      R9 = DM(0x2de10c);                // the previous pass's EMUCLK
      DM(0x2de10c) = R8;
      R8 = R8 - R9;                     // cycles since the previous pass
      R10 = 4096;                       // THRESHOLD
      COMPU(R8, R10);
      IF GE JUMP 0x16f536;              // -> wr_idle_out. (preempted: other work)

      R9 = DM(0x2de110);
      R9 = R9 + R8;                     // idle cycles, cumulative
      DM(0x2de110) = R9;
      R10 = LSHIFT R9 BY 16;
      R9 = LSHIFT R9 BY -16;
      R9 = R9 OR R10;                   // halves swapped, as reply word 0
      DM(0x2c49d4) = R9;                // reply word 1, both pages
      DM(0x2c59d4) = R9;

.GLOBAL wr_idle_out.;
wr_idle_out.:
      R8 = DM(0x2de100);
      R9 = DM(0x2de104);
      R10 = DM(0x2de108);
      JUMP 0xb88aab;                    // back to the idle loop's top
.wr_idle..end:
