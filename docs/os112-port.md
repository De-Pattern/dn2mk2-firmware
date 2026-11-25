# The port to stock OS 1.12

Owner, 2026-11-24: start after v0.72 ("you can do it after this release"); Outbox 8 testers on
Discord, the owner has no Outbox. A test build first (`X.Y-tN`, `--test` on the patcher), announced
only when the owner says.

## What 1.12 changes (docs/os-versions.md)

MAIN OS only: +4,096 bytes; about 25 functions changed size, so code after `+0x48a86` sits at
shifts between 0 and +1,344 (`dnfw.osport.addrmap`, 41 matched runs). The bootstrap, the updater,
the DSP program and the Outbox 8's own firmware are byte-identical. BSS and the heap moved by
exactly +4,096 (the BSS end `0x466b74d0` -> `0x466b84d0`, still clear of our RAM from `0x46700000`);
fast SRAM (`0x8000xxxx`) did not move.

## How: port the built image, not the sources

The sources stay in 1.11's addresses (1,370 address literals in about 100 files; rewriting them
would fork every mod). A gated 1.11 build is ported to 1.12 by `dnfw.osport.port`:

1. **Edits.** Each run of bytes where the build's MAIN OS differs from stock 1.11 moves to its 1.12
   place; the stock code under and around it must be the same in both images (a relinked pointer
   aside), or the port refuses.
2. **Operands.** In the edits and in every CODE chunk's code (the ranges the gate's ColdFire step
   already records), each 1.11 address an instruction carries is found by disassembly (objdump,
   ColdFire V4e) and translated: in the image by its matched run (its own bytes checked in both
   images), in RAM by the references stock's own code makes to it or a base near it (at least 95 %
   agreeing). Four-character codes (`'DNFW'`) are left alone.
3. **Data.** A chunk's data is copied as it is. Every word that reads as a moved 1.11 address is
   reported and classified: a pointer to a stock string identical in 1.12 is translated (MACHINE
   SEL's stock names: "FM Tone", "FMT", ...; "MIDI" is a shared string tail); text and anything
   else stay. The DSP's tables (`0x47000000`) are never ColdFire addresses.
4. **The image:** stock 1.12 with the ported MAIN OS and the build's DSP section (identical stock
   DSP in both OSes, so the build's own section 7 holds).

v0.72 ported: 114 edits moved, 827 operands translated, 10 data pointers, nothing refused.

## The gate on 1.12

Scripts and the gate are written in 1.11's addresses too. `dnfw.osport.os.A(x)` gives `x` on 1.11
and its translation on 1.12 (`DN2_OS`), refusing an address it cannot place; a literal goes through
`A` only where its 1.12 address differs. The emulator cannot translate behind a script's back (a
pointer read from 1.12 RAM is already a 1.12 address). Per-OS inputs: the stock image and sections
(`../sec112`), the snapshots (`digikit/out/snapshots/dn2-1.12`), the boot control's cache.

## What the 1.12 gate found (and the rules it gave)

- **A hook sharing a byte with stock's target.** Our `jsr 0x46ac022a` replaced stock's
  `jsr 0x4011d32a`: the last byte was the same, so it was not part of the edit, and on 1.12 stock's
  relinked `0x4011d60a` made it `jsr 0x46ac020a`. Three hooks into our code in MAIN OS's padding
  (0x402d06xx) kept their 1.11 targets the same way. Rule: an edit takes the whole of any relinked
  word it covers in part (translated when it is a stock address). `verify_calls` now proves every
  absolute call and jump in the edits reaches the same code on 1.12 as on 1.11 (it refuses the old
  port's four); the gate's meter step caught the first through its low-memory read trap.
- **Immediates are numbers until proven addresses.** BSS moved as one block (its start and end both
  +4,096, read from the clear loop), and an address operand in it moves with it; but an immediate
  (`#n`) is translated only on stock code's own evidence: four-character codes ('DNFW', 'DN2T') and
  bounds (`ram_ok`'s 0x44000000) lie in BSS's numeric range and stay as they are.
- **One translation, at the parser.** The gate speaks 1.11 everywhere; each harness translates the
  addresses in its steps and options (results keyed by the 1.11 address asked for). Translating in
  both put a poke 8 KB off.
- **The emulator's own hooks** (digikit's instruction patches) come from scanning the image it
  runs: only hooks our scripts set are audited.

## Status

- [x] the translator, and the port of v0.72 (no refusals)
- [x] stock 1.12 boots in the emulator (snapshots to 400M)
- [x] the ported build boots from reset (emu_boot_check on 1.12)
- [x] the gate's scripts through `A`, the gate's stock/sections/snapshots per OS (1.12 UI snapshot: v0.14 ported, as `ui800M-v014`)
- [ ] the full gate on the 1.12 build: CLEARED TO FLASH
- [ ] test build v0.73-t1 OS112 on `builds` (test/) and the patcher (--test)
