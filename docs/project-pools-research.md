# Per-project sample pools: research (no build)

**2026-11-01. Research only.** Nothing here is in a firmware, and nothing was sent to an
instrument. It answers the open item in `docs/drive-library-plan.md` §4.2 and §7 ("where the
OS keeps the active project's slot number") and turns phase (d) of §6a into a design. The
report that started it: Kokozi, samples follow you from project to project, because there is
one pool for all of them.

Evidence: stock DN2 OS 1.11 MAIN OS (`../sec111/section_3_MAIN_OS.bin`, sha256 `57b06a79…`),
disassembled with `m68k-linux-gnu-objdump -b binary -m m68k:cfv4e --adjust-vma=0x40000400`,
the RTTI and string names in the image, and the ColdFire emulator (digikit **`21b38b9`**,
snapshots `boot400M` and `ui400M-c1` of `digikit/out/snapshots/dn2-1.11/`, run with
`DNFW_EMU_FLAGS='{"weakptr": false}'`, through `scripts/emulib/machine.py`).

Grades: **[D]** read from the disassembly; **[E]** run in the emulator (the claim and how is
given beside it); **[?]** not verified. The emulator serves no +Drive (`docs/emulator.md`), so
every [E] about load or save ran with the storage steps stubbed, and says so.

---

## The short answers

1. **The active project's slot is a signed byte at `0x405CD899`**: 0..127, or -1 for an
   unsaved project. It sits in the working-state header (`0x405CD85C`, magic `COKi`, the
   header of the image the OS keeps across power-off) and is restored from the +Drive by the
   boot task **before** the main application task, so before our `smp_boot`, starts. [D], the
   getter and setter [E].
2. **One setter writes it, `0x400BB696`**, through the wrapper `0x4003EB62(project, slot)`.
   LOAD sets it at `0x40042ED6`, after the project is in and the temp slot written; SAVE and
   SAVE AS set it at `0x40040300` and `0x40040360`; NEW, DELETE of the active slot, a project
   received over SysEx, FORMAT and the boot's fallback set -1; factory reset sets 0. COPY,
   PASTE and CLEAR of a slot do not touch it. [D], LOAD, SAVE, SAVE AS and DELETE [E] with
   stubs. **The hook:** one detour at **`0x40042ED2`** (stock `2f05 2f03 4eba bc8a`), the load
   path's success, so our code can tell a LOAD from a SAVE AS. Every other change of the byte
   needs no hook: our UI-loop poll sees it.
3. **The pool today** is one byte-for-byte image of the DSP's pool at sectors
   `0x600000..0x6C8000` and the library at `0x700000` up. **The design:** 129 small lists in
   the free gap, at **`0x6D0000..0x6D81FF`** (inside our region, 16 MB clear of the pool image,
   about 20 MB clear of the library). A list maps each slot to a library sample by its
   adler-32, frames, format and rate, with its names and slices. The DSP's pool becomes a
   cache: a switch rewrites the directory (a few KB) and sends only the samples B uses that
   are not already in the DSP's memory. Recordings and samples sent straight into the pool
   are first copied into the library, so a switch can never lose one.
4. **Migration:** today's pool becomes a **legacy list**, which every project without a list
   of its own uses. Nothing changes for anyone until they change a project's pool; from then
   on that project has its own. Before the first switch, every pool sample that is not in the
   library is copied into it.
5. **Risks:** eMMC writes (bounded and few), the OS's own load and save running in a worker
   task at the same time, the wrong samples playing for the seconds a switch takes, and slots
   changed behind our back (DNX or Transfer, COPY/PASTE). The gate needs a hook-site check, an
   emulator LOAD/SAVE AS/DELETE run on the build, and simulated +Drive runs for the switch,
   the migration and a cut power.

---

## 1. The active project's slot

### Where it is

| address | what | grade |
|---|---|---|
| `0x405CD85C` | the working-state header, 0x110 bytes: `+0` magic `COKi` (`0x434F4B69`), `+4` its check (`0x400BB34C`), `+8` version 6, `+0xC` 0x42 … The project image follows it at `0x405CD96C` (`= 0x405CD85C + 0x110`), the buffer `scripts/emu_project_load.py` already uses | [D]; the bytes [E] (`boot400M`: `434f4b69 095355e9 00000006 00000042 …`) |
| **`0x405CD899`** (header `+0x3D`) | **the active project's slot, a signed byte** | [D] |
| `0x400BB704` | its getter: `7139 405c d899 4e75` (`mvs.b 0x405cd899,d0; rts`) | [D] |
| `0x400BB696(slot)` | its setter: writes only when the value changes, through `0x400BB4F8`, which clears the header's magic, copies the byte and stamps the magic and check again (`0x400BB4CE`) | [D] |
| `0x4003EB8A(project)` | `Project`'s getter: -1 when the project has no storage attached (`project->vtable[+40]()`, `0x4019587A`, returns `project+16`), else `0x400BB704` | [D], [E] |
| `0x4003EB62(project, slot)` | `Project`'s setter: calls `0x400BB696` only when storage is attached | [D], [E] |
| `0x4018A97A()` | the `Project` singleton (`0x446CABF0` in the snapshots), whose `+16` is the project data `0x41218970` | [E] |

`0x405CD89A` (the next byte, getter `0x400BB70C`) is a second flag the setter `0x400BB6C8`
writes; it is not the slot. The UI numbers projects 1..128: the transfer route's
`/projects/N` takes `N = slot + 1` and refuses `N = 0` ("Active project not supported",
`0x400EB73E`). [D]

**[E], what was run** (`ui400M-c1`, stock): `0x4003EB8A(P)` returned -1 (the emulator
serves no +Drive, so the boot fell back to a new, unsaved project, below); after
`0x4003EB62(P, 5)` it returned 5, the byte read `05` and the header's check changed from
`0x0A5255E9` to `0x095855E9` with the magic `COKi` still in place.

### Reading it from our C code

```c
/* the active project: 0..127, -1 unsaved (OS 1.11, docs/project-pools-research.md) */
#define ACTIVE_PROJECT (*(volatile signed char *)0x405CD899u)
```

One byte, written in one instruction, so a read never sees half a value. The stock getter
`((int (*)(void *))0x4003EB8Au)(((void *(*)(void))0x4018A97Au)())` gives the same value, or
-1 while the project has no storage attached; use it as the check, not instead.

### Is it valid at power-on, before our pool load?

Yes. [D] The boot task (prio 1, entry `0x400CEC98`, `docs/coldfire-tasks.md`) runs, in order:

1. `0x400CEF9E` → `0x400F2004`: reads 256 bytes of the header from **sector `0x40000`
   (bank A) and `0x48000` (bank B)** into `0x405CD85C`, keeps the valid newer one
   (`0x400BB4C0`, `0x400F1EBE`), then reads that bank's whole 12,890,388-byte image (header
   and project). If neither bank is valid it initialises the header (`0x400BB394`: the slot
   byte 0) and sets bit 2 of `0x40287520`.
2. `0x400CEFAE` → `0x400BB532`: upgrades the header's settings by version.
3. `0x400CF00A` → `0x400BB25C`: deserialises the project from `0x405CD96C` into
   `0x41218970`. If that fails, or the flags ask for it, it builds the default project and
   **sets the slot to -1** (`0x400BB2F4`: `pea -1; jsr 0x400BB696`).
4. `0x400CF0EA` → `0x4002E8D0`: **creates the main application task** (`0x4002ED34`,
   prio 6), whose UI loop (`0x4002E322`) is where `wr_poll` and so `smp_boot` run.

So by the first `smp_boot` the byte holds the slot of the project that was active at
power-off (or -1). [D] In the emulator, `boot400M` (mid-boot) shows the byte 0 from step 1's
initialisation and `project+16` still 0; every later snapshot shows -1 from step 3's fallback,
because the emulator's +Drive reads zeros. [E] That it survives a real power cycle with the
right value is **[?]**: the header is written with the working state by the writer around
`0x400F1B4E` (table `0x401FF6F8`), apparently from the power-fail routine `0x400F1850`
(registered at `0x400F20C0`), not read further.

Service mode (bit 6 of `0x40287520`) skips steps 1-4 and parks; our code does not run there.

---

## 2. The code paths, and where to hook

### What changes the byte

Every call of the setter in the image (`0x400BB696` has two callers, `0x4003EB62` six). [D]

| action | path | when the slot is set | to | grade |
|---|---|---|---|---|
| **LOAD** (PROJECT menu, `ProjectManager::interactiveLoad`) | `0x4009C33A` → **`0x40042E6E`(project, slot, cb)**: `0x40042B92` opens and loads the slot, `0x40040190(project, 128)` writes the temp slot, **then** `0x40042ED6` sets the slot, then `0x4003EBE2(project, 0)` clears modified | only if both succeeded | `slot` | [D]; [E] with `0x40042B92` and `0x40040190` stubbed: success logged `open(17)`, `write(128)`, `set(17)`, active 17; with the open failing, `open(3)` only, active unchanged |
| LOAD of an **empty** slot | the same lambda, failure branch `0x4009C38C`: `0x400428C0(project, slot)` (new project) then `0x400402D8(project, slot)` (save) | by both | `slot` | [D] |
| **SAVE** / **SAVE AS** (`interactiveSave`) | `0x4009C268` → **`0x400402D8`(project, slot, cb)**: slot < 0 means the active one (`0x400402F2`); else `0x40040300` sets it **before** writing; `0x40040320` writes the slot (`0x40040288` → `0x40040190`), `0x4004034A` the temp slot, `0x40040360` sets it again, `0x40040368` clears modified | before the write, and again after | `slot` | [D]; [E] stubbed: SAVE AS 42 logged `set(42) write(42) write(128) set(42)`; SAVE (-1) `write(42) write(128) set(42)`; **a failed write still leaves the slot changed** (`set(9) write(9)` fails, active 9) |
| **NEW** project | `0x400428C0(project, slot)` sets `slot` at `0x40042AF6` (callers pass -1: `0x4009AB30`, `0x400F66FC`) | always | -1 (or the slot, above) | [D]; the emulator run did not complete, [?] |
| **DELETE** a slot that is the active one | lambda `0x4009B402`: `0x400F6568` per slot; if the slot is the active one, `0x4009B464` sets -1 | after the delete | -1 | [D]; [E] stubbed: deleting {3, 9} with 7 active leaves 7; {2, 7} sets -1 |
| CLEAR slots | lambda `0x4009B388` → `0x400F66E6`: a stored slot is reinitialised (`0x4003EA0E`, "NEW PROJECT") and written; slot -1 means the live project → `0x400428C0(project, -1)` | only for -1 | -1 | [D] |
| COPY / PASTE a slot | `0x4009B2E8` → `0x400F6AF8(cache, slot)`; `0x4009B30A` → `0x400F6C9E(cache, slot, 0)` writes the clipboard's image into the slot (`0x400F6960`) | never | — | [D] |
| RENAME | `0x4009B258`: if the slot is the active one, the live project is renamed too (`0x4003E800`) | never | — | [D] |
| A project **received as SysEx** ("Send project sysex") | `0x400D0522`, `0x400D0548`, `0x400D6F96` → `0x400403D6`, which loads it from memory and sets -1 at `0x40040632` | always | -1 | [D] |
| DNX / Transfer write of `/projects/N` | `ProjectHandler` routes (`docs/drive-storage-research.md` §2): MmcFs writes the stored slot; the live project and the byte are untouched | never | — | [D] for the route; [?] that no other path reloads |
| FORMAT +DRIVE | `0x4012F332`; `0x4012F598` sets -1 | always | -1 | [D] |
| Factory reset (startup menu) | `0x4002EA7C`: installs the factory content (`0x4012F608`), renames the live project, `0x4002EC26` sets 0 | always | 0 | [D] |
| Power-on | §1: restored with the working state, or -1 | — | — | [D] |

### The temp slot (128)

Not where the live project comes from at power-on (that is the working state, banks
`0x40000`/`0x48000`). It is a copy the OS keeps on the +Drive: written at every LOAD, SAVE
and NEW (`0x40040190(project, 128)`), and by the task `saveProjectToMmc(tempProject)`
(`0x4003FDEE`, string `0x40214BF6`), scheduled from the UI loop after "Write project MRAM"
(`0x4002D032`..`0x4002D058`) when the stored copy differs. `0x40044AA0` opens it
(`0x40044B1E`: `pea 0x80`) for the RELOAD-from-project actions. [D]; what reads it beyond that
is [?]. It never changes the slot byte, so per-project pools can ignore it.

### Where our code should learn "A changed to B"

**Poll, plus one hook.** Our UI-loop poll (`smp_boot`, every pass) compares `ACTIVE_PROJECT`
with the slot our pool belongs to (its **owner**, kept in our region). A change has two
meanings that the byte alone cannot tell apart:

- **LOAD**: the live project was replaced by slot B's. B's pool must come in.
- **Everything else** (SAVE AS, NEW, DELETE of the active slot, SysEx, FORMAT, factory
  reset): the live project is the same one, or a fresh one, and keeps the pool it has. If B
  >= 0, B's list becomes a copy of the current pool.

The hook marks LOAD. **Proposed: `0x40042ED2`, 8 bytes, stock `2f05 2f03 4eba bc8a`**
(`move.l d5,-(sp); move.l d3,-(sp); jsr 0x4003EB62`), reached only when the load and the
temp write both succeeded, with `d5` = the slot. It becomes `jmp cave` + `nop`; the cave:

```
    move.l  d5,-(sp)              ; the displaced instructions, the jsr made absolute
    move.l  d3,-(sp)
    jsr     0x4003EB62
    move.l  d5,smp_proj_loaded    ; payload: the slot loaded (absolute stores: no register used)
    addq.l  #1,smp_proj_loads     ;          a count, so the same slot loaded twice is seen
    jmp     0x40042EDA            ; back: clr.l -(sp) ... lea 16(sp),sp pops both pairs
```

The two pushes stay on the stack as in stock, because the cave is entered by `jmp`, not
`jsr`. `d0` (the setter's result) is dead after `0x40042EDA` (`0x40042EE6` overwrites it).
[D] The cave runs in the OS's load task; the poll in the UI task reads two aligned longwords,
`smp_proj_loads` last. The poll's rule: when `smp_proj_loads` moved and
`ACTIVE_PROJECT == smp_proj_loaded`, it was a LOAD of that slot; any other change of
`ACTIVE_PROJECT` is "keep the pool".

Why not elsewhere:

- **The setter `0x400BB696`** (stock `7339 405c d899 598f`) sees every change but cannot
  tell a LOAD from a SAVE AS: both call it with the new slot.
- **The entry of `0x40042E6E`** (stock `4fef ffdc 48d7 043c`) is reached by failed loads
  too; a flag set there goes stale.
- **SAVE AS** needs no hook: it is "keep the pool" with a new owner. If the owner wants a
  SAVE (to the same slot) to mark the list clean, `0x4004035C` (stock `2f04 2f02 4eba e800`,
  `d4` the slot) is the same pattern; not needed for correctness.
- **PASTE / DELETE / CLEAR** of a stored slot are optional hooks (§5, question 5):
  `0x400F6C9E` (stock entry `4e56 ffc8 48d7 047c`), `0x400F6568` (`2f02 70ff 242f 000c`).

None of these sites is patched by any mod in this repository today (grep of `src/`,
`patches/`, `csrc/`, `scripts/`). [D]

**Timing.** At the hook the OS has already applied the new project's kits and patterns.
Until our switch finishes, sample tracks would play whatever the old pool holds at their SAMP
numbers. So the switch's first step sends the directory with every entry empty (the loader's
existing `K_BLANK` step): sample tracks go silent at once, and each comes back as its sample
is in (§3).

---

## 3. The pool today, and per-project lists

### Today (v0.31..v0.37)

| sectors | what | code |
|---|---|---|
| `0x600000` | the pool image's header: `DN2Q`, version 2, its bytes, a check of the directory page, a check of the header | `link.c` `header_write` |
| `0x600001 ..` | the image, byte for byte as the DSP holds it, up to `POOL_BYTES` = 400 MB: | `image_read` / `image_write` |
| | `+0` the directory page (`DATA_OFFSET` 4 KB): `SMP1`, the count, 128 entries of 16 bytes (DDR address, frames, rate, format word: +12 format, +13 slices, +14 flags, bit 0 sliced on the instrument), the short names (8 bytes from `0x808`), the meta pointer (`0xC08`), the command block (`0xF00`) | |
| | frames from `0x1000`; the recordings' area 96..128 MB (slots 123..126 by default, any slot since v0.22), the tables at `0x7F60000`, the slice area (128 x 768 B) at `0x7FE0000`; the meta block (long names, folders) wherever its pointer says; yours below 96 MB and from 128 MB | `dnfw.sampler.machines` |
| `.. 0x6C8000` | the image's end (`0x600001 + 400 MB / 512`); **`0x6C8001` is the first sector not ours yet** | `lib.c` `POOL_STORE_END` |
| `0x700000` | the library: superblock `DN2L`; `+1..+256` 2,048 entries of 64 B (first sector, frames, rate, format, folder, flags, **adler-32 of the frames**, sectors, name of 36, entry check); `+257..+260` 64 folders; frames from `0x700105` | `lib.c` |

At power-on the whole image is sent to the DSP (`smp_load`, the kit's samples first since
v0.31), about 0.7 MB/s. LOAD TO PROJECT copies a library sample +Drive to +Drive into the
image, then sends that one slot (`lp_poll`). Recordings are written into the image only
(`smp_save_recording`), and the computer's `dn2samples.py` / import tool can still write a
whole image: **neither is in the library**. [D] from the code.

### The lists: where

| sectors | what |
|---|---|
| `0x6C8001 .. 0x6CFFFF` | left free: 16 MB between the pool image and the lists |
| **`0x6D0000`, `0x6D0001`** | the lists' superblock, two copies written alternately: `DN2J`, version, sequence, **owner** (-1..127), migration state, a check |
| `0x6D0010 .. 0x6D001F` | the resident table: what the DSP's memory holds now (up to 256 extents of 32 B: adler, frames, format, rate, pool offset, last used) |
| **`0x6D0100 + 0x100 x p`** | **list p** (p = 0..127 the projects, **128 the legacy list**), 256 sectors each, 129 lists: up to `0x6D81FF` |
| `0x6D8200 .. 0x6FFFFF` | free: about 76 MB below the library |

All of it lies inside the region our code already owns (`STORE_FLOOR` `0x458000` .. the
device's end), above the pool image's last sector `0x6C8000` and below `LIB_SECTOR`
`0x700000`. [D] arithmetic on `link.c` and `lib.c`; the build should hold it as
`_Static_assert`s (lists end <= `LIB_SECTOR`, start >= `POOL_STORE_END`), and every list
read and write goes through a bounded `pl_rd` / `pl_wr` as `lib_rd` / `lib_wr` do. No other
code in the repository uses sectors `0x6C8001..0x6FFFFF` (grep). These sectors lie beyond the
probable pSLC area (the first 3,120 MiB, `docs/drive-storage-research.md` §1), as the pool
image's upper part and the library already do; the lists are written rarely and small.

### A list (256 sectors)

| sector | what |
|---|---|
| 0 | header: `DN2K`, version, p, sequence, the records' check, a bitmap of slots with slices, a fingerprint of the stored project (below) |
| 1 .. 24 | 128 records of 96 B, one per pool slot (SAMP 1..128) |
| 25 .. 216 | 128 slice tables of 768 B (only the slots in the bitmap are read) |

A record: `+0` state (0 empty, 1 a library sample, 2 missing), `+1` format, `+2` slices,
`+3` flags (the entry's byte 14), `+4` frames, `+8` rate, `+12` **adler-32 of the frames**
(the library entry's `+16`), `+16` the library index it was found at (a hint, checked against
the adler), `+18` folder, `+24` short name (8), `+32` long name (36), the rest zero.

**Samples are found as the DT2 finds them, by content**: adler, frames, format and rate must
all match a used library entry; the index is only where to look first. Renaming or moving a
sample in the library breaks nothing; deleting it makes the slot "missing" (shown as such;
the DT2 does the same).

**Samples not in the library** (recordings, a whole image from the computer, anything in the
pool from before v0.31) are **adopted** before any switch can drop them: copied +Drive to
+Drive into the library (recordings into RECORDED, the rest into INCOMING or the folder the
meta block names), their adler computed while copying, then recorded like any other. Today a
LOAD TO PROJECT already knows its library entry, so it records it directly. New in the
library code: an on-instrument writer (today only the SysEx path `smp_lib_rx` writes entries;
`lib_room` already allocates).

**When a list is written:** the owner's list whenever the pool changes (LOAD TO PROJECT,
UNLOAD, a recording kept, RENAME, a slice edit, a computer send), records first, header
last. So a list on the +Drive is always what the pool held last, and nothing is lost if the
project is never saved. (Whether an unsaved pool change should instead be dropped on reload,
as an unsaved pattern edit is, is question 3 in §6.)

### A switch from A to B (on LOAD)

1. Silence: send the directory with every entry empty (`K_BLANK`).
2. Read list B. **No list** (never written, or its fingerprint does not match the stored
   project, §5): use the legacy list (§4).
3. For each slot of B: if its sample is **resident** (in the resident table: the same adler,
   frames, format, rate), point the slot's entry at that extent. **No frames move: a sample
   used by both projects, in any slot, costs nothing.**
4. The rest, the kit's SAMP slots first (`load_order`): room from `pool_room`, preferring
   extents no list recently used; the frames copied library to image (+Drive to +Drive); the
   slot sent to the DSP by the loader's checked path (frames, then entry), as `lp_poll` does
   now for one sample. The slot plays as soon as its entry is in.
5. The meta block (names, long names), the slice area for sliced slots, the directory page
   and the header written; the resident table updated; then the superblock's owner = B, last.

**Time.** Step 1 and 3 are a few kilobytes over the link: well under a second. Step 4 is
set by the bytes **B needs that the DSP does not hold**, at the link's 0.7 MB/s, plus the
+Drive copy (eMMC read and write, rate through the stock driver not measured: [?],
`docs/drive-library-plan.md` §7):

| B needs, not resident | about |
|---|---|
| nothing (same samples, or all shared) | < 1 s |
| a kit of 16 one-shots, 1.5 MB | 2 s |
| 20 MB | 30 s |
| 100 MB | 2.5 min |
| 400 MB (a full pool, nothing shared) | 10 min, as a power-on today |

Ways to keep it short, in order of value: (a) residency (step 3): the DSP pool is 400 MB, so
several projects' samples usually fit at once, and switching between them costs nothing;
(b) the kit's samples first, so the pattern plays within seconds; (c) eviction by least
recent use, so going back to the last project is cheap; (d) the +Drive copy and the link
overlap (the copy is not the bottleneck).

**Power-on** stays as today (the image is what the DSP held at power-off), with one check
added: if `ACTIVE_PROJECT` differs from our owner, the reconciliation in §5 runs before the
image loads.

---

## 4. Migration: today's single pool becomes per-project

**Safest default: nothing changes for anyone until they change a project's pool.**

1. First power-on with the new build: no `DN2J` superblock. The current pool's directory is
   written as the **legacy list** (list 128). The owner is set to `ACTIVE_PROJECT` (may be -1).
2. Every project without its own list **uses the legacy list**. Loading any old project
   therefore brings the same pool as today: no sample moves, no switch time.
3. The moment a project's pool changes (a LOAD TO PROJECT, an UNLOAD, a recording kept, a
   SAVE AS to it), that project gets a list of its own, starting from what the pool holds.
4. **Before any switch can drop a sample**, every pool sample not in the library is adopted
   (§3). This is a one-time +Drive copy of at most the user part of the pool (400 MB; the
   library holds about 19.5 GB), done in the background with LOADING n% shown, switching
   refused until it is done. If the library is full or absent, switching stays refused and
   the pool behaves as today: one pool for all.
5. Nothing is ever deleted by the migration: the pool image, the library and the projects
   are left as they are; the lists are added beside them. Going back to an older build reads
   the pool image as before and ignores the lists.

A choice for the owner is whether old projects should instead **start empty** (each project
then loads only what it needs) or all share the legacy pool (above). Starting empty would
silence every old project's sample tracks until their samples are loaded again by hand,
because a stored project records only SAMP numbers, not which sample; so the default above is
the only one that loses nothing.

---

## 5. Risks, and what the ship gate would need

### Risks

- **eMMC writes.** New writes go to a new range (`0x6D0000..0x6D81FF`) and, for adoption, to
  the library through its existing bounded writer. Each must pass a bounds check before the
  block driver is called; a wrong sector number lands in a user's projects (they are below
  `0x458000`, so the existing floor check catches that). Per switch: one list (only when it
  changed), the resident table (16 sectors) and one superblock sector; the superblock
  alternates between two sectors, so a write cut by power-off leaves the other one valid.
- **The OS's own load and save.** LOAD and SAVE run in a worker task ("Project Load" /
  "Project Save" names at `0x40219325`, `0x40219341`, run through `0x400F2494`), and SAVE
  PROJECT holds the CPU at 100 % for about a second (`docs/coldfire-tasks.md`). Our writes
  share the stock driver's lock (`0x4667AD00`), so they cannot interleave inside a transfer,
  but they slow each other. The switch starts only after the hook (the OS has finished its
  load and its temp write) and only while our loader and saver are idle, and yields one 64 KB
  chunk per UI pass, as `lp_poll` does.
- **A failed SAVE still changes the slot** (stock, [E] above). Our poll then sees "keep the
  pool" with a new owner, and B's list becomes a copy of the current pool: the right thing,
  since B's stored project is whatever the OS left there.
- **Power cut between the OS's working state and ours.** The OS writes its header with the
  working state, apparently at power-fail ([?], §1); we write our owner when we see the
  change. If ours is lost, at the next power-on `ACTIVE_PROJECT` (B) differs from our owner
  (A). Reconciliation: B has its own list → switch to it (right for a LOAD); B has none →
  adopt the current pool as B's (right for a SAVE AS to a new slot). The one wrong case is a
  SAVE AS over an existing slot with a list, cut within milliseconds; mitigated by writing
  the owner at once, and harmless in that nothing is deleted.
- **Slots changed behind our back.** DNX or Transfer writing `/projects/N`, COPY/PASTE,
  CLEAR and DELETE of a stored slot, FORMAT and factory reset leave B's list describing a
  project that is no longer there. Mitigation: a fingerprint of the stored project in each
  list's header, checked when B is loaded; a mismatch means "no list" (the legacy list, or the
  current pool). **What the fingerprint can be is [?]**: the slot's 512-byte header holds the
  magic, a length, a 16-byte name and a word (`docs/drive-storage-research.md` §1), and
  neither name nor length changes on a re-save; a check over the whole stored image (12.9 MB)
  would cost a read of about that per LOAD. Optional hooks at PASTE (`0x400F6C9E`, copy the
  list from the clipboard's slot) and DELETE (`0x400F6568`, drop the list) cover the
  instrument's own operations exactly.
- **Wrong samples during a switch.** Step 1 (silence) avoids it at the cost of sample tracks
  being silent for the switch's seconds.
- **Overbridge.** It carries audio and parameters, not projects; projects move only through
  the transfer routes above. [D] from the route table; nothing in Overbridge's path writes the
  slot byte.
- **The hook site moves in other OS versions.** This mod stays on 1.11; the gate asserts the
  stock bytes before writing (as `patch_sites` does).

### What the ship gate would need

1. **Hook site:** the 8 stock bytes at `0x40042ED2` asserted (`2f05 2f03 4eba bc8a`) and the
   cave's displaced instructions equal to them (absolute `jsr 0x4003EB62`).
2. **Emulator, on the build** (the [E] runs of §2, made a gate step): with `0x40042B92` and
   `0x40040190` stubbed, a LOAD of slot 17 sets `smp_proj_loaded = 17` and moves
   `smp_proj_loads` by 1; a failing LOAD moves nothing; SAVE AS 42 and SAVE move nothing;
   DELETE of the active slot moves nothing and leaves -1; the slot byte ends as on stock in
   each case (the stock run is the control).
3. **Simulated +Drive** (the `link16` disk of `emu_waverider_menu.py`): (a) migration of a
   pool holding library samples, a recording and a computer-sent sample: the legacy list
   equals the old directory; the two non-library samples adopted, their adler checked; (b)
   switches A→B→A: the directory after the round trip equals the one before; the link carries
   only the bytes of samples not resident (counted); shared samples are not sent; (c) every
   block write recorded: none below `0x600000`, none in `0x6C8001..0x6CFFFF` or
   `0x6D8200..0x6FFFFF`, none past the device; (d) power cut after each write in turn (replay
   the writes up to it, then power on): the superblock valid, the owner A or B, every record of
   every list either resolvable in the library or "missing", never a lost sample.
4. The existing steps unchanged: boot from reset, engine + SAVE/LOAD, the SHARC runner
   (no DSP change is needed: the switch uses the loader's existing commands).

**Unverifiable in the emulator, so for the owner on hardware:** the slot byte across a real
power cycle and a real LOAD (read-only: PEEK `0x405CD899` with the USB probe build,
`docs/usbprobe.md`, before and after loading project 5, then after a power cycle; expected
`04`); the switch's real time; the eMMC copy rate.

---

## 6. Questions only the owner can decide

1. **A new project** (NEW, or LOAD of an empty slot): start with an **empty pool** (as the
   DT2) or **keep the pool it had** (nothing unloaded; the default here)?
2. **Unsaved (-1)** after a SysEx receive, deleting the active project or FORMAT: keep the
   pool (default)?
3. **Unsaved pool changes:** written to the project's list at once (default: nothing lost),
   or kept only if the project is saved (as the DT2's project file does)?
4. **Adoption:** copy recordings and computer-sent pool samples into the library
   automatically (needed for switching to be lossless), and into which folders?
5. **COPY / PASTE / DELETE / CLEAR of a project slot:** two more hooks so lists follow them
   exactly, or a fingerprint check only?
6. **During a switch:** sample tracks silent until their sample is in (default), or keep
   playing whatever was in those slots?
7. **Migration:** old projects share the legacy pool (default, §4) or start empty?

---

## Reproducing

```sh
# the listing
m68k-linux-gnu-objdump -b binary -m m68k:cfv4e --adjust-vma=0x40000400 -D \
    ../sec111/section_3_MAIN_OS.bin > main111.dis
grep -n "405c d89[89]" main111.dis          # the byte's readers and writers
grep -n "4003eb62\|400bb696" main111.dis    # the setter's callers (§2's table)

# the emulator (digikit 21b38b9): getter, setter, and the LOAD / SAVE / DELETE paths
DNFW_EMU_FLAGS='{"weakptr": false}' DT2_SECTIONS=../sec111 \
DT2_MAIN_IMG=../sec111/section_3_MAIN_OS.bin ../digikit/.venv/bin/python -u probe.py
```

`probe.py`, in outline: `Machine(snapshot=".../ui400M-c1.snap", syx="../Digitone_II_OS1.11.syx",
digikit="../digikit")`; `P = m.call(0x4018A97A)`; code hooks logging the arguments of
`0x400BB696`, `0x40040190`, `0x40042B92`, `0x4003EBE2`, `0x400F6568`; `70014e75` (`moveq #1,d0;
rts`) written over `0x40040190`, `0x40042B92` and `0x400F6568` (and `70004e75` for the failing
runs); then `m.call(0x40042E6E, P, 17, fn)`, `m.call(0x400402D8, P, 42, fn)`,
`m.call(0x400402D8, P, -1, fn)`, and `0x4009B402` with a `std::vector<int>` of slots built in
scratch memory, reading `m.call(0x4003EB8A, P)` after each.
