# HANDOFF: the second firmware (FASCIA first), 2026-11-12

Read this first in the new chat. It is written to be picked up cold.

## What the owner wants

From the Discord thread of 2026-11-12, and from the owner directly:

- **A new firmware, separate from the mod** (the "DN2mk2" line, v0.51 and on). It has no Machinedrum
  machines and no Monomachine machines. Owner: "just more complex versions of DT2 engines plus my new
  synthesis ideas with no compromises."
- **The engine first: the ORIGINAL FASCIA**, the build that made the demo tour the owner approved on
  2026-11-07 ("i love the new tour sounds. theyre all perfect ... that will be the new engine, exactly
  as you made it").
- **Minimal features to start.** Error Kit's advice, which the owner endorsed:
  - focus 100 % on the engine, plus FX if wanted, and a workflow that gets the most out of it;
  - add features later only where there is a reason and room;
  - don't assume 8 or 16 voices of a heavy engine.
- **Later, not now:** dreamsaremaps' auto-sampler idea (Vermona DRUMDING-style):
  - design a sound on the heavy engine, then auto-sample one hit, or an 8/16-hit chain with variation,
    onto a sample track (SLICE/GRID with an LFO across slices);
  - this frees the DSP.
  - FLEX's recorder code (v0.49..v0.51) is the starting point.

## Where everything is

### The approved sound: the original FASCIA model
- **Model:** `src/dnfw/fascia/model.py`, float64, block-wise (32 samples, coefficients once a block,
  48 kHz).
- **Commit:** `9a6877e`, "FASCIA: the approved sound locked (goldens test), docs/fascia.md with the full
  notes". It is on the `rift` and `fascia` branches of `De-Pattern/dn2mk2-firmware`; `073ced2` is the
  first RIFT design model.
- **Patches:** the 30 audition patches in `scripts/fascia_audition.py` at that commit.
- **Goldens (the approved pass-3 sound):** private bench repo `De-Pattern/dn2mk2-bench`, commit `f6972d6`:
  - `goldens/fascia/*.npy`: the first second of each patch;
  - `goldens/fascia/listen/`: the full renders the owner heard;
  - `GOLDENS-FASCIA.md`.
- **The 3-page v2,** approved on 2026-11-08 ("sounds amazing"):
  - model commit `6f6683a`, goldens commit `ec17692`;
  - it differs from pass 3 in 5 of the 30 patches (plasticine, tzfm clank, wood-to-glass morph,
    snap/click perc, tick on glass).
  - **Ask the owner which one he means by "the original".** Pass 3 (`9a6877e` + `f6972d6`) is the first
    one he approved.

### The DSP port, bit-exact to the model's float32 contract
- **Branch `fascia-saved`.**
  - `54e7843`: FASCIA's DSP program, a chained L2 program `smp -> FASCIA -> the PING_SW tail`.
  - It is bit-exact to `src/dnfw/fascia/live.py` (the float32, DSP-order version of the model;
    `c42d419`).
  - Velocity comes from frame header word `52+2t`, the note from header word `2+2t`.
  - Voice state is in L2, tables in DDR.
  - Runner parts: `fascia`, `fchords`, `fsilence`, `fgarbage`, `fstress`, `fcost`.
- **Branch `fascia-opt-wip`, `e86ad1a`:** the DSP speed-up. Unfinished and ungated, stopped on 2026-11-08.
- **ColdFire side:** `392fb41`. Type 18, 24 controls on 3 pages, and FASCIA's MACHINE SEL entry. In
  v0.45 (`834f6aa`) it was built and gated but left out of MACHINE SEL.
- **Backup:** `dn2mk2-bench/backups/fascia-2026-11-08.bundle`.
- **Docs:** `docs/fascia.md` (the pages, every control, what each part does, the owner's decisions),
  `docs/fascia-integration-plan.md`.

### Cost (to measure again first)
- A voice is up to about 60 two-pole resonators: 16 modes x 2 bodies, plus twins.
- The per-voice cost on the DSP was being measured (`fcost`) when FASCIA was moved to a later release.
- The DN2's whole DSP budget is about 666,667 cycles a frame. The stock engines use part of it; without
  the MD/MNM machines and our sample machines, more is free.
- No firm voice count yet: **measure it first.**

## The plan, in order

1. **New private repo** (suggested `De-Pattern/fascia-fw`). It never goes public, like heavylight's code.
   - Start from stock OS 1.11.
   - Copy in only the infrastructure, listed below. Not the MD, MNM or sampler mods.
   - Keep the history short: one commit "infrastructure from dn2mk2-firmware at <sha>".
2. **Pick the reference:** pass 3 or v2 (ask the owner). Copy its `model.py`, `live.py`, the audition
   patches and the goldens in. The goldens test (within 2 LSB) is the acceptance test for every change.
3. **Measure.**
   - Run FASCIA's DSP program alone (from `fascia-saved`) on the SHARC runner with nothing else of ours.
   - Count the voices that fit the frame. The guard's headroom stays as the mod's: the stock chain must
     never starve.
   - Report the count to the owner before any trimming. He wants "no compromises", so trimming FASCIA is
     his decision, not ours.
4. **Integrate as the mod did.** Type 18, its pages, p-locks, LFO targets, slides, MACHINE SEL. This time
   FASCIA is the only engine of ours.
5. **Minimal workflow.** What the owner asks for next: likely pages for the 4 x 8 controls, presets, FX.
6. **Gate from day one.** The same rules (below), a full gate on every build, publish as the mod does,
   with its own Discord line.

## Infrastructure to carry over (from dn2mk2-firmware)

### Building
- `src/dnfw`: the patch and build framework (`mods apply`), the ColdFire C toolchain (`cbuild`,
  `csrc/`), the composer and `waverider_code.json`.
- The SHARC DSL `dnfw.perc.dsl`: emit/run, so the model and the DSP are one program, bit for bit.
- The DSP image tools: `dnfw.waverider.dsp`, `section7`, the L2/DDR checks.

### The gate (`scripts/ship_gate.py`)
- preflight (bootstrap, updater, metadata, Outbox untouched, signature, DSP size);
- DSP identity, DSP hardware rules (`hwrules`), the ColdFire ISA check (scale-8), Overbridge untouched;
- unit tests, the SHARC runner (types 0-4 bit-identical to stock), boot from reset, the UI fuzz;
- engine + SAVE/LOAD, the exact-reuse cache (`gate_cache.py`), the PyPy speed-up and its CPython
  cross-check (`gate_crosscheck.py`, `docs/gate-speed.md`).

### Emulators
- `digikit` (ColdFire, Unicorn with the patched libunicorn) and `digikit-wt-sharcemu` (the SHARC tracer
  and runner).
- `emulib` (bounded, panel, machine).
- The coupled two-processor harness `scripts/emu_coupled.py`. Use the v0.51 version: every block is
  called with the same I7.
- The bench repo's `setup.sh` installs the goldens, the snapshots and the PyPy venv.

### Release plumbing
- `FIRMWARE.md`, the `builds` branch, the web patcher (`dn2mk2` site: `web_bundle.py`, Pages check),
  `releases/vX.Y.md` with the Discord workflow.
- The new firmware needs its own patcher entry, and a name the owner picks.

## Rules that carry over (from CLAUDE.md and the owner)

- **Nothing is flashed or sent** until `ship_gate.py` prints CLEARED TO FLASH on that exact file.
  "We absolutely CANNOT risk anything that will potentially harm my unit."
- **Each release:** bump VERSION, regenerate the code, step-by-step runs start with the preflight steps;
  make no test or script edit while a run that reads it is in progress.
- **Don't rebuild or delete the build file while a gate batch runs.** v0.51 lost a step that way.
- **Never weaken a gate.** Every gate keeps a negative control that must fail.
- **Commits:** as De-Pattern (`239624238+De-Pattern@users.noreply.github.com`), with the
  Co-Authored-By and Claude-Session trailers. No force-push, no bare `git stash`.
- **Nothing public shows the owner's name or email.**
- **At most 2 heavy jobs at once;** background jobs die at 2 h, so split gate runs into batches.
- **Features must come out cleanly.** One constant or one commit each.
- **The owner wants quick answers and ETAs,** and to be asked before any choice that changes the sound.

## Lessons learned (the expensive ones)

- **DSP time is the constraint, not voice count.**
  - The guard measures the frame and drops whole voices cleanly; v0.49 gave sample voices their time
    first.
  - Measure with the runner's `cost` step and the unit's load meter.
- **Exactness costs.**
  - v0.51 cut SID 64 %, DDRW 43 %, DENS 40 %, VO-6 9 % and TRX-CY 33 % by giving up bit-exactness
    (`docs/mnm-trim.md`), held instead to level and octave-band likeness with negative controls.
  - FASCIA's reference is our own model, so its float32 contract (`live.py`) is the target, not an
    old chip.
- **L1, L2 and DDR placement matters on the SHARC.**
  - Busy tables go in L2, render scratch in L1 (`dsp.py`'s map).
  - The engine task's stack is in the FreeRTOS heap (`0x2d08b8..0x2dd0b0`). Ours starts above
    `0x2dd600`.
- **ColdFire scale-8 addressing traps** (the CPU can't do it). The gate's objdump check also flags
  jump-table data. Fixes: `noipa`, `optimize("no-jump-tables")`.
- **Emulator pitfalls:**
  - **Harness I7 drift.** The coupled harness used to carry the DSP's I7 between blocks. Its frame walked
    into our scratch at block 459 and looked like a stack-smash ("return target 0x1"). Fixed in v0.51.
    Always ask whether a halt is the harness's before blaming the build.
  - **flexcore's SENTINEL return.** In flexcore's harness, a knob on our machine page returns the UI task
    through its SENTINEL. Knob checks belong in the coupled harness.
  - **Stock knobs need pulses.** A stock page needs SRC selected and several encoder pulses with gaps
    (`emu_fine_seq.py`).
  - **LEDs.** The panel's page LEDs never refresh in the emulator.
- **Screens.**
  - Every text must fit its place in every state, checked by pixels in the gate (`emu_rectext.py`).
  - The label font's capitals are about 5 px; the 3x5 glyphs are 4 px a character (`SMP_GLYPHS`).
  - Render and look before sending.
- **Sound-slot offsets:** a sound's slot s is at `sound + 20 + 2 s`. FLEX read `+48` for 5 releases.
- **The owner reviews sound by ear.** Any change to an approved sound needs his ear first, and then new
  goldens (`scripts/fascia_golden.py`).

## Open questions for the owner (ask at the start)

1. Pass 3 (`9a6877e`) or the 3-page v2 (`6f6683a`)?
2. The new firmware's name, and does it get its own Discord channel?
3. Which DT2 engines, and "more complex versions" of which? (ONESHOT/WERP/STRETCH/REPITCH/GRID/SLICE and
   FLEX exist in the mod's sampler.)
4. Polyphony target for FASCIA after the measurement: how many voices are enough?
5. FX: which, and per track or master?
