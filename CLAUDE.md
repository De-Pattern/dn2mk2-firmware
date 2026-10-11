# Rules for this repository

## The shipping rule — no exceptions

**No build goes to the owner for flashing until `scripts/ship_gate.py` has printed
`CLEARED TO FLASH` on that exact file.** Not a smaller change, not a rebuild of
something that passed before, not a docs-only rebuild. Every build, every time.
(Owner, 2026-10-11: *"we absolutely CANNOT risk anything that will potentially harm
my unit."*)

    DT2_SECTIONS=../sec111 python scripts/ship_gate.py ../Digitone_II_OS1.11.syx BUILD.syx

It runs, in order, and stops at the first failure: preflight (bootstrap, updater,
metadata, Outbox untouched; signature; DSP size) → DSP identity → SHARC runner
(types 0–4 bit-identical to stock) → ColdFire instruction-set check → boot from
reset → engine + SAVE/LOAD → unit tests. About an hour; run it in the background.

- The pass is recorded in `BUILD.syx.gate.json` with the build's sha256. A file
  whose sha256 differs from its record has not been gated.
- If any gate fails, or cannot run (missing tool, emulator, objdump), the answer
  is **do not flash**. An unchecked gate is a failed gate.
- When sending a build, say which gates passed and what remains unverified on
  hardware.
- A new mod that adds a gate (its own SHARC or ColdFire harness) adds it to
  `ship_gate.py` in the same commit.

See `docs/SAFETY.md` for the risks each gate covers.
