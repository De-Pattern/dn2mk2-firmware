# Gate speed: what takes the time, and what cuts it (2026-11-11, after v0.49)

The owner asked (2026-11-11) for ways to speed up the gate and the checks before a release
"that won't really be a significant detriment". Rule for everything here: **a speed-up is
only taken if every step's report comes out byte-identical** (or, for floating-point
analysis done after the emulation, equal to the last digits), checked against a pass of the
same build. No check is dropped, no threshold loosened, no negative control removed.

## Where the time goes (measured on v0.49)

The machine has **2 CPU cores** (hence the two-heavy-jobs rule). Every emulator is
single-threaded, so more parallelism cannot help: only less work per step can.

Step times on v0.49 (CPython, minutes): FLEX 60, link16 54, link16-dead 40, pools 36,
UI fuzz 29, machines ~30, boot 17, slice ~21, slides 16, fineknob 15, +DRIVE ~26, jump 13,
unit 13, erase 11, engine 8, thres 6, the rest ~25; the SHARC runner's ten parts ~181.
About **8 h of ColdFire work and 3 h of SHARC work**: over 5 h on two cores at best, so the
gate has to be run in batches under the 2-hour job limit.

Profiled with py-spy (`--native`):

- **link16 / pools / dead link**: 76% of the time in Unicorn's `helper_uc_tracecode`.
  Two things made Unicorn call it on *every* instruction: `guest_call`'s instruction
  counter (a Python callback per instruction, used only for printing), and
  `emu_start(count=limit)` itself (Unicorn implements `count=` as a hidden code hook on
  every address). With a code hook covering every address, each instruction walks all
  ~330 code hooks (272 of them the FF1/MOVEC patches).
- **FLEX (coupled)**: ~85% in the SHARC emulator, which is pure Python (decoding, symbolic
  `Const`/`Affine` values, `name_address` on every DSP read/write). About 9 s of computer
  time per 0.7 ms of audio.
- **SHARC runner**: the same pure-Python SHARC emulator.

## Found and measured

| change | what | measured | reports |
|---|---|---|---|
| A. guest_call's count only for callers that print it | removes a Python callback per instruction | link16 3250 → 2196 s | 10/10 byte-identical |
| B. guest_call's runaway guard = the fast stepper's block budget, not `count=` | no per-instruction hook at all; running out of budget now raises (count= truncated silently) | link16 3250 → **161 s**; pools 2184 → **118 s**; dead link 2410 → **127 s** | all byte-identical |
| C. PyPy (a faster Python, no code change) for the SHARC runner | JIT for the SHARC interpreter | wipe 124 → 58 s; chords 1306 → **302 s** | identical but timing fields |
| D. PyPy for the coupled tests (FLEX, THRES) | same, with the same patched libunicorn | FLEX's take 2422 → **735 s** (whole test ~60 → ~17 min) | emulation identical; two correlations differ in the 16th digit (numpy after the run) |

## B across the gate: verified on v0.49's build (2026-11-12)

`emulib/bounded.py` (the block budget) in every harness that stopped a call with `count=`. Every
ColdFire step re-run in speed-wt on `out/v049.syx` and each step's report files compared with
the v0.49 gate's: **all identical** (JSON reports equal once the work folder's path, which they
record, is normalised; every PNG, snapshot and dump byte-identical). 51 steps, no failures.

| step | v0.49 (min) | with B (min) |
|---|---|---|
| link16 | 54 | **2.7** |
| link16-dead | 40 | **2.1** |
| pools | 36 | **2.1** |
| flexcore, rectext, kbrec, fineswap | | 1.4-2.4 each |
| UI fuzz | 29 | 29 |
| boot | 17 | 17.5 |
| fineknob | 15 | 15.5 |
| erase | 11 | 11.7 |
| engine | 8 | 8 |
| machines (power-on + MACHINE SEL) | ~30 | 29 |
| +DRIVE (browser, nested, keys) | ~26 | 26 |
| jump (rapid presses 13 of it) | 13 | 18 (alone on the cores) |
| slides | 16 | 16.5 |

(Two batches ran side by side on the 2 cores, so the unchanged steps' times include sharing.)

B cuts about **2 h 10 min** of ColdFire work. The steps it did not speed up spend their time
elsewhere. Profiled: **boot from reset is 97% `helper_uc_tracecode`** too, but from digikit's
`emu/dspboot.run`, which puts a Python code hook on every instruction on purpose: it counts
instructions (the boot's frame timing and its 450M-instruction budget are counted in
instructions), records coverage and detects stalls. That count *is* what the step measures, so
a block budget would change where the boot stops, and the reports would not be identical. Not
proposed as a quick change; the steps built on that boot (engine, erase, fuzz, machines, +DRIVE,
fineknob) are likely the same, to be profiled one by one. A possible later route, if wanted: an
exact instruction count kept in C (a counting hook in our patched libunicorn), not in Python.
digikit is m-dwyer's toolkit, so a change there is a change to a dependency, not to our gate.

## Proposed plan

1. **B everywhere** (low risk, large): the same `emu_start(count=)` guard is copied into
   about a dozen gate scripts (emu_coupled, emu_jump, emu_erase, emu_slides, emu_rectext,
   emu_flexcore, emu_encoder_trace, emu_rectrig, emulib.machine ...). One shared helper,
   each step re-run and its report compared byte for byte with a v0.49 pass. Expected:
   most ColdFire steps several times faster.
2. **PyPy for the SHARC runner and the coupled tests** (owner's call: it changes the
   interpreter the gate runs on). The gate cache already hashes the interpreter, so a
   switch reruns everything once. Proposed safeguard: one full gate run under both
   interpreters on the same build with every report compared, and after that a CPython
   cross-check run of the SHARC runner once per release (in the background, not blocking).
3. **Cheap SHARC-interpreter fixes** (later, ~10-20%): `name_address` called on every DSP
   memory access, dataclass construction per value.
4. **Pre-release extras** (not gate steps, owner's call): a test's negative controls rerun
   when that test or its harness changes, not on every release.

Estimate if 1 and 2 hold up across all steps: the full gate from scratch about **1.5-2 h
instead of 5+ h**, likely inside one 2-hour job, so no more batching. Not yet measured for
every step; the numbers above are the ones measured.

## Not proposed

- Faster tempo or shorter takes in the coupled tests: it would change what is tested.
- Skipping steps or sampling scenarios: it would weaken the gate.
