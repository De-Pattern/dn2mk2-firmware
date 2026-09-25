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
- **NO**: refused. Either the bytes overlap, or neither order applies.

## What it does not promise

- **Not a hardware result.** No combined image has been flashed. Each mod on its own
  has been confirmed on the instrument; pairs have not.
- **Functional clashes are not detected.** Two mods can write disjoint bytes and still
  fight over one feature. What is known about that is in each pair's note. A pair
  with no note has simply not been examined beyond bytes and apply.
- **Boot.** Every combinable pair touching MAIN OS is also booted from reset in the
  emulator (`scripts/emu_boot_check.py`). The results are recorded below the table.

## Why the three appending mods exclude each other

lfowaves, bootscreen and lfo4 each install their own start-up loader at
`0x4000053e`, and each requires MAIN OS to end exactly where stock 1.11 ends,
because each appends its own data area there. They cannot be combined yet.

octabam solves the same problem with one platform loader that owns the hook and
the append, and a table of payloads that modules contribute to. That is the way to
lift this limit (`docs/references.md`). It has not been done here yet.

## The table

<!-- dnfw:matrix -->
<!-- /dnfw:matrix -->

## Boot from reset, per pair

Filled in from `out/mod-pairs/*/boot.txt`.
