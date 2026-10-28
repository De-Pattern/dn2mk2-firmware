# The +Drive sample library: research and plan (for the owner's approval)

**2026-10-28. A plan, not a build.** Nothing here is in a firmware yet. It builds on
`docs/drive-storage-research.md` (the eMMC, its free region, the block driver) and on
what v0.16..v0.29 already do (`docs/sampler.md`). Sources: the Digitakt II manual (OS
1.17, §9.1, §13.3, §13.6), our own code (`csrc/sampler/link.c`, `rec.c`, `smp_page.c`),
and the owner's reports (O12; the YouTube requests from paQ75 and DrLaemmerbein).

## 1. Why: what is slow today, and why

Today the +Drive holds **one image of the DSP's sample pool**, byte for byte (up to
400 MB: 122 of your slots and the recorder's 4). At every power-on the whole image is read
and sent to the DSP over our TDM link, which carries about **0.7 MB/s**, and every 64 KB
is checked. So:

| what is in the pool | power-on load |
|---|---|
| 20 MB | about 30 s |
| 100 MB | about 2.5 min |
| 400 MB | about 10 min |

Two things follow: (1) the time is set by **how much is in the pool**, not by the
+Drive; (2) a library on the +Drive cannot make the link faster. What it can do is let you
keep **far more** on the +Drive (about 20 GB free) while the pool only holds **what this
project uses**, and load the samples the current pattern needs first.

## 2. What the Digitakt II does (the model to copy)

From the DT2 manual, in short:

- **Two stores.** The **+Drive library** (about 20 GB, folders, every sample you own) and
  the **project's RAM pool** (up to 400 MB, slots 1..1016). A track plays only what is in
  the pool. Loading into the pool is an explicit action; power-on loads the active
  project's pool.
- **SAMPLES menu** (FUNC + SAMPLING on the DT2): UP/DOWN chooses **+DRIVE** or
  **PROJECT RAM**, YES opens it.
- **+DRIVE**: folders FACTORY (write-protected), INCOMING (where transfers land),
  RECORDED (appears after the first recording), plus your own. UP/DOWN moves, YES opens a
  folder, NO goes up one level, **NO held goes to the top**. A sample already in the
  project's pool shows its slot number.
  - **YES** ticks or unticks a sample; **FUNC + YES** previews about 10 s of it on the
    active track's voice.
  - **RIGHT** opens SAMPLE ACTION: **LOAD TO PROJECT** (the ticked ones into the first
    empty slots; FUNC + YES there picks a RAM bank), **LOAD TO TRK**, **RENAME**, **MOVE
    SELECTED** / **MOVE HERE**, **DELETE**, **CREATE DIR**, **UPLOAD HERE** (where a
    transfer lands), **SELECT ALL**.
- **PROJECT RAM**: the 1016 slots. **UNLOAD** (one or the ticked), **SELECT UNUSED**
  (samples no pattern uses: "UNLOAD X SAMPLES? CONFIRM? Y/N"), **REPLACE** (browse the
  +Drive for a slot's new sample).
- **Samples are found by hash**, not by name or folder, so renaming or moving a sample
  on the +Drive does not break a project that uses it; deleting it does.

## 3. What we have already (most of the pieces)

| piece | where | state |
|---|---|---|
| Our eMMC region from sector `0x600000` (3 GiB), read and written through the stock block driver, bounded to the region | `link.c` | in use since v0.15 |
| The pool in the DSP (400 MB, 128 slots, the recorder's 4) and its checked loader | `link.c`, DSP `tdm_rx` | in use |
| A DT2-style sample list (the pool's slots) and folder browser (INCOMING, RECORDED, the import tool's folders), SAMPLE ACTION (load, rename, delete), multi-select, FUNC + YES preview | `rec.c`, `smp_page.c` | v0.25..v0.29 |
| The import tool (browser) and `tools/dn2samples.py`, writing the **whole** pool image | site, tools | in use |
| Recordings saved to the +Drive | `link.c` | in use |

What is missing is the split: the browser today shows the **pool** grouped by folder; there
is no store bigger than the pool, and no "load this into the project".

## 4. The proposal

### 4.1 Storage on the +Drive (our region, nothing of Elektron's touched)

```
sector 0x600000   our superblock: magic, version, checksum, layout (as today's header, extended)
                  the CURRENT POOL image (as today: what power-on loads), unchanged format
then              the LIBRARY: an index + sample files
```

- **Library index**: a table of entries, each **name (36 chars), folder, size, frames,
  rate/channels, xxHash32 of the frames, start sector, length**, plus a folder table
  (INCOMING, RECORDED and yours; there is no factory set). xxHash32 is
  already in the DN2 image (`docs/drive-storage-research.md` §4).
- **Sample files**: contiguous extents, int16 as the DSP plays them (no conversion at
  load), allocated from the end of the index upward; deleting frees an extent, and the
  import tool compacts when it needs room (the computer is the master copy, as DNX
  planned).
- **Every write bounded** to the region (as `link.c` already does) and checked against
  the device size. Projects, presets, kits: untouched, as today.
- **Room**: about 20 GB (3 GiB .. 23 GiB). Sending from the computer runs at the USB
  SysEx link's speed (a few hundred KB/s), so a large library is filled once and kept;
  only the samples a project loads cross the slower DSP link afterwards.

### 4.2 The pool stays what it is, but holds only the project's samples

- **LOAD TO PROJECT** copies a library sample into the first empty pool slot: read from
  the +Drive, sent over the link, checked (the loader we have, for one sample: seconds,
  not minutes). The pool image on the +Drive is updated so power-on reloads it.
- **Power-on**: loads the pool image as today, but **the samples the current pattern's
  tracks use go first** (SAMP of each sample track read from the kit), so the pattern can
  play while the rest loads. The page shows LOADING n/N meanwhile (today: nothing).
- **Per project**: the DN2 has no place in its own project files for our list, so the
  pool would belong to **the active project slot** by its number (128 pools' lists in our
  region; switching project loads that project's list). *To be researched: where the OS
  keeps the active project's slot number; until then, one pool for all projects, as
  today.*
- **Slots stay 1..127** (our SAMP parameter is 0..127; the DT2's 1016 would need a new
  parameter range and bank pages, a much bigger change).

### 4.3 Menus and keys (as the DT2's, on keys the DN2 has)

| | DT2 | here |
|---|---|---|
| open | FUNC + SAMPLING | **FUNC + YES on a sample page** opens the browser (as today), its top now **+DRIVE / PROJECT RAM** |
| +DRIVE | folders, YES ticks, FUNC + YES previews, RIGHT: SAMPLE ACTION | the same; NO up a level, NO held to the top; a sample in the pool shows its slot |
| SAMPLE ACTION (+DRIVE) | LOAD TO PROJECT, LOAD TO TRK, RENAME, MOVE, DELETE, CREATE DIR, SELECT ALL | the same (MOVE and CREATE DIR in phase 3) |
| PROJECT RAM | slots, UNLOAD, SELECT UNUSED, REPLACE | the same (today's list, renamed); SELECT UNUSED in phase 3 |
| the SAMP knob | the pool's slots | unchanged: the pool's slots |

### 4.4 The computer side

- The import tool (site) and `dn2samples.py` send samples **into the library**
  (INCOMING, or a folder you name) instead of rewriting the whole pool; one sample at a
  time, each checked. Nothing in the pool changes until you load it.
- A list of what is on the +Drive (names, sizes, folders), and delete from the computer.

## 5. Phases (each its own build, each through the full gate)

1. **Library store + import into it** (no UI change): the superblock and index, the tool
   writes library samples; the pool works as today. Gate: emulator writes and reads the
   index (bounds checked), the runner unchanged. *Risk: medium (eMMC writes): bounded like
   today's.*
2. **+DRIVE / PROJECT RAM in the browser, LOAD TO PROJECT, UNLOAD, LOAD TO TRK,
   preview from the library**. Gate: the 6f/6i-style emulator checks for each action.
3. **Priority loading at power-on, LOADING n/N, SELECT UNUSED, MOVE, CREATE DIR,
   REPLACE.**
4. **Per-project pools** (after finding the active project's slot number).

## 6. Decisions for you

1. **Approve the shape**: library + per-project pool (the DT2's), slots staying 1..127?
2. **Where the browser opens**: FUNC + YES on a sample page as today, or another
   combination you prefer?
3. **Phase order**: is priority loading at power-on (phase 3) more urgent than the menus
   (phase 2)? It is the quickest win for the slow start.
4. **One pool for all projects** until phase 4, as today: OK?

## 7. Open research before phase 1

- The active project's slot number in the OS (for phase 4).
- The read speed of the eMMC through the stock driver while the sequencer runs (it is
  not the bottleneck today, the TDM link is; to confirm for priority loading).
- Whether the link's 0.7 MB/s can be raised (more TDM slots, or the RGPIO page link
  `docs/drive-storage-research.md` §4 describes): a separate, riskier project.
