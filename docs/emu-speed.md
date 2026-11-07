# The gate's boot steps, faster (v0.43)

The owner, 2026-11-06: the gate takes too long. Where the time went, per release (v0.42's run):
the SHARC runner's recording parts (39, 31 and 30 min), boot from reset (32 min), the sample
link (23 min), the engine boot (17 min), on two cores.

## What changed

`emu.dspboot.run` (digikit) adds one **global** Unicorn code hook, `cover`: a Python call on
every instruction, counting instructions and collecting the addresses seen. The boot steps
(`emu_boot_check.py`, `emu_boot_engine.py`) never read what it collects: their verdicts come
from per-address hooks (the frame, the fault reporter, the build's routines, the start-up
animation), and the run's length is `emu_start(count=limit)`, which Unicorn counts natively.
`scripts/emulib/quickboot.py` runs the same boot with that one hook left out. digikit itself
is not changed.

## The proof

`scripts/emu_quickboot_proof.py MODE IMAGE N` boots N instructions and hashes the end state:
every mapped byte of memory, PC, SR, A0-A7, D0-D7, plus the scheduler's spin count and the
tasks started. v0.43's build (2026-11-07):

| N | with the hook | without | end state |
|---|---|---|---|
| 30M | 84.8 s | 49.7 s | identical (mem `81653df900d2ffde`, regs `e3933f3811975aac`) |
| 700M (the boot check's length) | 2,033 s | 1,258 s | identical (mem `51db344158bcbb34`, regs `8949aeb1dd4a0ede`, 227,137,071 spins, 8 tasks) |

So the machine runs the same instructions to the same state; only the Python work per
instruction is gone (1.6-1.7x).

## What was tried and not taken

- **No `count=`** (Unicorn's own per-instruction budget, the larger cost: longrun.py measured
  7.6x): without it this boot ends in an unhandled CPU exception, so the run is not the same.
  Kept.
- **longrun's `_FastStepper`** (a block-entry budget): it changes the instruction stream
  (digikit says so itself). Not for the gate.

## What is lost

The instruction number at which a run stopped early (a fault) is not counted any more; the
fault itself, its record and every verdict are unchanged.
