# Which mods combine

**Generated, not kept.** The table below is rewritten by

    dnfw mods matrix 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \
        --page docs/mods-compatibility.md --page site/index.html

which tries **every pair of mods, in both orders**, on stock 1.11 (`src/dnfw/mods/matrix.py`).
A table kept by hand is a copy, and it goes stale the first time a mod changes.
octabam's remixer makes the same choice: its `matrix()` prints from the conflict
check rather than from a README (`docs/references.md`).

## What each mark means

- **yes**: the two mods write disjoint bytes and each accepts the image the other
  produced, in either order.
- **order**: they combine in one order only:
  - **The wrong order is refused.** Every mod checks the stock bytes it replaces, so
    that order fails with an error rather than a broken image. Example: bootscreen
    after arpplocks.
  - **Or the wrong order would silently lose an edit.** A mod that *copies* part of
    the image declares it (`COPIES`). lfo4 copies the stock parameter table into its
    appended area. Applied after lfo4, a table edit such as moddest's thirteen masks
    or fxmod's Chorus records still finds its stock bytes and applies cleanly, but it
    lands on a table the firmware no longer reads. `dnfw mods apply` therefore
    applies lfo4 last, whatever order it is given.

    Neither edit is left to order alone any more. moddest refuses an lfo4 image
    (it finds two candidate tables), and since 2026-09-26 fxmod does too: it checks
    that all 56 of the table's accessor bases still reach the stock table
    (`paramtable.base_sites`) and otherwise says to apply fxmod first. The browser
    pages carry the same checks, which matters there: each page applies one mod
    and the user chains them by loading one page's download into the next, so the
    page, not the CLI, has to enforce the order. `site/lfo4.html` accepts an image
    fxmod, moddest or midiarp already built (arpplocks too, from the CLI), and
    refuses lfowaves and bootscreen images on their length.
- **NO**: refused. Either the bytes overlap, or neither order applies.

## What it does not promise

- **Not a hardware result.** No combined image has been flashed. Each mod on its own
  has been confirmed on the instrument; pairs have not.
- **Functional clashes are not detected.** Two mods can write disjoint bytes and still
  fight over one feature. What is known about that is in each pair's note. A pair
  with no note has simply not been examined beyond bytes and apply.
- **Boot.** Every combinable pair that includes a loader mod (lfo4, lfowaves or
  bootscreen) was booted from reset in the emulator (`scripts/emu_boot_check.py`),
  2026-09-26: **12 of 12 booted and drew their UI.**
  - The other pairs were not booted: a boot runs a mod's loader and init and
    nothing else, so it would run neither mod's code. Pairs with transients only
    change section 7.
  - The results are recorded below the table.

## Why the three appending mods exclude each other

lfowaves, bootscreen and lfo4 each install their own start-up loader at
`0x4000053e`, and each requires MAIN OS to end exactly where stock 1.11 ends,
because each appends its own data area there. They cannot be combined yet.

octabam solves the same problem with one platform loader that owns the hook and
the append, and a table of payloads that modules contribute to. That is the way to
lift this limit (`docs/references.md`). It has not been done here yet.

## The table

<!-- dnfw:matrix -->
| | `arpplocks` | `bootscreen` | `fxmod` | `lfo4` | `lfowaves` | `midiarp` | `moddest` | `transients` |
|---|---|---|---|---|---|---|---|---|
| `arpplocks` | - | order | **NO** | yes | yes | yes | yes | yes |
| `bootscreen` | order | - | yes | **NO** | **NO** | yes | yes | yes |
| `fxmod` | **NO** | yes | - | order | yes | yes | yes | yes |
| `lfo4` | yes | **NO** | order | - | **NO** | yes | order | yes |
| `lfowaves` | yes | **NO** | yes | **NO** | - | yes | yes | yes |
| `midiarp` | yes | yes | yes | yes | yes | - | yes | yes |
| `moddest` | yes | yes | yes | order | yes | yes | - | yes |
| `transients` | yes | yes | yes | yes | yes | yes | yes | - |

- **arpplocks + bootscreen: order**: bootscreen refuses after arpplocks: the boot-screen code space is already in use by another mod. *Note:* bootscreen reserves 0x380 bytes at 0x402dfa1c for its code and refuses if any is used; its code is 366 bytes and ends 2 bytes before arpplocks' cave at 0x402dfb8c, so bootscreen first then arpplocks writes disjoint bytes. Whether bootscreen uses the rest of its reservation at run time is not measured.
- **arpplocks + fxmod: NO**: arpplocks and fxmod both write section 3 0x0028e604..0x0028e682 (126 bytes).
- **bootscreen + lfo4: NO**: bootscreen and lfo4 both write section 3 0x0000013f..0x00000146 (7 bytes).
- **bootscreen + lfowaves: NO**: bootscreen and lfowaves both write section 3 0x0000013f..0x00000146 (7 bytes).
- **fxmod + lfo4: order**: fxmod refuses after lfo4: the parameter table has been moved (expected 53 site(s) holding 0x401f7f94 (table - 60 + 8), found 0); lfo4 does that, and fxmod opens records in the stock table, which nothing reads once it has moved: apply fxmod first, then lfo4. *Note:* emulator, 2026-09-26: the LFO4 slot harness and a turn of all eight LFO4 dials match lfo4 alone; fxmod's DEST checks and names match fxmod alone; every LFO page, LFO4's included, gains the same 24 FX destinations. The hooks are on different paths (fxmod's slot lookup at 0x400dc02a is asked above slot 100 only while the DEST list is built). Not exercised: LFO4 aimed at an FX destination. fxmod's own helper at 0x4028ea02 keeps the stock table bounds, so it would answer LFO4's own entries with -1; it is only ever called with destination entries.
- **lfo4 + lfowaves: NO**: lfo4 and lfowaves both write section 3 0x0000013f..0x00000146 (7 bytes).
- **lfo4 + moddest: order**: moddest refuses after lfo4: found 2 candidate parameter tables, expected 1; this image's layout is not the one this mod was measured against. *Note:* measured: with moddest applied first, all 13 masks it opens are in lfo4's relocated table (test/test_lfo4_mod.py).
<!-- /dnfw:matrix -->

## Boot from reset, per pair

Written from `out/mod-pairs/*/boot.txt` (`--boots out/mod-pairs`). A boot runs the loader and
the init, so only pairs that include a loader mod are booted; the rest say why they were skipped.

<!-- dnfw:boots -->
- `arpplocks` + `bootscreen`: booted and drew its UI (1 frame(s), control 1).
- `arpplocks` + `lfo4`: booted and drew its UI (1 frame(s), control 1).
- `arpplocks` + `lfowaves`: booted and drew its UI (1 frame(s), control 1).
- `arpplocks` + `midiarp`: SKIPPED: no loader in this pair; a boot runs neither mod's code
- `arpplocks` + `moddest`: SKIPPED: no loader in this pair; a boot runs neither mod's code
- `arpplocks` + `transients`: SKIPPED: transients writes section 7 only, so this MAIN OS is the other mod's alone
- `bootscreen` + `fxmod`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `midiarp`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `moddest`: booted and drew its UI (1 frame(s), control 1).
- `bootscreen` + `transients`: SKIPPED: transients writes section 7 only, so this MAIN OS is the other mod's alone
- `fxmod` + `lfo4`: booted and drew its UI (1 frame(s), control 1).
- `fxmod` + `lfowaves`: booted and drew its UI (1 frame(s), control 1).
- `fxmod` + `midiarp`: SKIPPED: no loader in this pair; a boot runs neither mod's code
- `fxmod` + `moddest`: SKIPPED: no loader in this pair; a boot runs neither mod's code
- `fxmod` + `transients`: SKIPPED: transients writes section 7 only, so this MAIN OS is the other mod's alone
- `lfo4` + `midiarp`: booted and drew its UI (1 frame(s), control 1).
- `lfo4` + `moddest`: booted and drew its UI (1 frame(s), control 1).
- `lfo4` + `transients`: SKIPPED: transients writes section 7 only, so this MAIN OS is the other mod's alone
- `lfowaves` + `midiarp`: booted and drew its UI (1 frame(s), control 1).
- `lfowaves` + `moddest`: booted and drew its UI (1 frame(s), control 1).
- `lfowaves` + `transients`: SKIPPED: transients writes section 7 only, so this MAIN OS is the other mod's alone
- `midiarp` + `moddest`: SKIPPED: no loader in this pair; a boot runs neither mod's code
- `midiarp` + `transients`: SKIPPED: transients writes section 7 only, so this MAIN OS is the other mod's alone
- `moddest` + `transients`: SKIPPED: transients writes section 7 only, so this MAIN OS is the other mod's alone
<!-- /dnfw:boots -->
