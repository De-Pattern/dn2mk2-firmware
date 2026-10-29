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

**Exact reuse (owner, 2026-10-25).** Every build still gets a full gate run and its own
record. The SHARC runner runs alongside the ColdFire steps. A long step's earlier pass is
reused only when nothing that step read has changed. What it read is traced: every file
its processes opened, the directories they listed, the native libraries and programs they
ran, and the gate's own inputs. Each is hashed (sha256) when the step passes. One
differing byte, or a missing file, means the step runs again (`scripts/gate_cache.py`).
The record's `reused` field says which steps were reused and from which pass. Never
widen what counts as "unchanged". (v0.28, owner 2026-10-27: the SHARC runner's verdict is
`scripts/gate_sharc.py`'s, so its record holds what the runner read and that file, not
`ship_gate.py` or the ColdFire's artefacts, which it never reads; DSP identity, never
reused, ties its pass to the build.)

- The pass is recorded in `BUILD.syx.gate.json` with the build's sha256. A file
  whose sha256 differs from its record has not been gated.
- If any gate fails, or cannot run (missing tool, emulator, objdump), the answer
  is **do not flash**. An unchecked gate is a failed gate.
- When sending a build, say which gates passed and what remains unverified on
  hardware.
- A new mod that adds a gate (its own SHARC or ColdFire harness) adds it to
  `ship_gate.py` in the same commit.

See `docs/SAFETY.md` for the risks each gate covers.

## Every cleared build is published

When a build prints `CLEARED TO FLASH`, in the same session:

1. Give it the next version number and add its entry to `FIRMWARE.md` (top of the table
   and a section: file name, sha256, gate date, source commit, what it adds, numbered
   tests, known issues).
2. Copy it and its `.gate.json` to the `builds` branch as
   `vX.Y-NAME/DN2mod_vX.Y_NAME_OS1.11.syx` (a worktree), with `FIRMWARE.md` as that
   branch's `README.md`, and push. Renaming keeps the sha256, so the gate record holds.
3. Bundle it for the in-browser patcher (`docs/patcher.md`):
   `python scripts/web_bundle.py BUILD.syx X.Y NAME ../../dn2mk2/patcher`, then commit and
   push dn2mk2 (github.com/De-Pattern/dn2mk2, the site at de-pattern.github.io/dn2mk2; it
   replaced the older dn2-tools site on 2026-10-27). Its commits are signed
   `De-Pattern <239624238+De-Pattern@users.noreply.github.com>`, never with the owner's
   name or email (owner: the site must not link to his name). It refuses a build whose
   gate record does not clear it.
4. Firmware never goes on `main` (`.gitignore`); only the `builds` branch carries it.
5. Announce it: commit its Discord announcement as `releases/vX.Y.md` on `main`
   (`releases/README.md`: first line `# vX.Y · NAME`, then the post, with a **Coming next
   (not available yet)** section) and push it: a new `releases/v*.md` on `main` is the
   trigger (this session's git route cannot push tags). The workflow `discord-release.yml`
   makes the release and its tag from that file and posts it to Discord's #announcements as
   De-Pattern. Never attach firmware to a release.
