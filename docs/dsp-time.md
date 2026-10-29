# DSP time: what v0.32 changes, and how it is checked

The owner's priority after v0.31: the Machinedrum, Monomachine and sample machines stable in
DSP time. What we know (`docs/sharc-load.md`, `docs/others-dn2-research.md`): a frame is
about 666,667 cycles on the unit; the stock idles about 63-65 % of it; our heavy voices cost
34,000-78,000 instructions a block each in the emulator, and on the unit a DDR access costs
several times an instruction.

## v0.32

1. **The voices' working state in L2** (`dnfw.waverider.dsp`: MD_STATE_L2, MNM_SCRATCH_L2).
   The Machinedrum's 16 slots x 1 KB (the Monomachine voices keep theirs in the same slots)
   and the Monomachine's shared scratch (its render buffers, the voice keys, costs and order)
   move from DDR to L2 0x200A0000..0x200A8000, inside the range complex-ping's mods have proven
   on units and 64 KB clear of the stock image. The P-I delay lines (128 KB) and the tables
   stay in DDR; the delay lines are now loaded with zeros at power-on (DDR holds garbage, NaN
   among it, until written). Expected: the largest saving; not measurable in the emulator,
   which charges every access alike. To confirm on the unit with the load meter.
2. **The guard's limit, measured** (`dnfw.perc.guard.tail_limit`). The limit our voices must
   finish by was a fixed 0.6 of a frame, assuming the stock's work after them (the voice chain,
   FX, mix) took 0.29 of it, as measured with few voices; with sixteen it takes more. Now each
   frame the stock's tail is measured (idle_load's AFTER total, less our own time, from our
   end mark) and held at its peak, easing over about three seconds; the limit is
   min(0.6 P, max(P - tail - P/8, P/4)). No reading (no idle time) leaves 0.6 P, so it is
   never looser than v0.31.
3. **The load meter** (`guard.meter`, unit 18 of the idle packet; `link.c` smp_dsp_load):
   1000 - 1000 x idle/elapsed since the last packet, the half second's peak, shown in percent
   in the tempo's place on the PERC and Monomachine pages while FUNC is held.
4. **Machinedrum voices rest** (v0.31) once their sound has died away after the AMP.

## Checked

- Runner 3g: the measured tail sets the limit; no reading and a garbage reading leave 0.6 P.
- Runner 3s, the stress test: every read of the clock in our code gets K x the instructions
  run (K = 3), so the guard works as on a unit three times slower than the emulator. Sixteen
  PERC voices under dynamic allocation (a new note each block) and four Monomachine voices with
  four PERC: every block ends, our voices are done by 0.565 / 0.49 of the frame, voices are left
  out and counted when time is short (179 of 320 voice-blocks in A), and the newest note is
  heard in every block.
- Gate 6n: the meter's percent, its timeout, and its drawing; gate "DSP hardware rules":
  complex-ping's hwrules.py finds no violation in our code or round our patches.
