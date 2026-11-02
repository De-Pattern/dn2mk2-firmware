# Per-project sample pools (v0.38, branch `pools`)

Each of the 128 project slots keeps its own pool: which samples sit in which of its 128
sample slots. LOAD a project and its samples come back; NEW starts with an empty pool;
projects made before this feature share today's pool until their pool changes. The design
research and the owner's four decisions are in `docs/project-pools-research.md`; this page
is what was built. Code: `csrc/sampler/pools.c` (the lists, the switch, power-on),
`csrc/sampler/hooks.S` (the four detours), `csrc/sampler/link.c` (the loader's sums and
resident spans, the reserved extents, the immediate blank). Emulator check:
`scripts/emu_pools.py` (the ship gate's step **per-project pools (ColdFire)**).

## The idea

The pool image on the +Drive (sectors `0x600000..`, `docs/sampler.md`) is unchanged: the
DSP's pool byte for byte, now a **shared heap of frames**. What is new is a **list** per
project: a copy of the image's 4 KB directory page (the 128 entries, the short names, the
meta pointer), its meta block (long names, folders) and its slice tables. A LOAD makes the
loaded project's list the image's directory again and sends the DSP what it needs.

- **Nothing is copied or moved on a switch.** Frames stay where they are in the image; a
  list only points at them. A frame extent (or meta block) that **any** list names is never
  given to a new sample, a LOAD TO PROJECT, a preview or a recording (`smp_pl_clash`, used
  by `pool_room` and `smp_rec_place`), so a switch can never lose a sample that another
  project uses, recordings included, and no adoption into the library is needed.
- **A sample already in the DSP's memory costs nothing.** The loader remembers what it sent
  this power-on and the DSP checked (a *span*: the slot's sector-rounded frames, with their
  sum, overview and slice columns); a slot of the new project on the same span gets only its
  16-byte entry. Anything else written there (the image, the preview, the tables, a
  recording) drops the span.
- **Silent, never wrong** (decision 4). From the moment the OS starts a LOAD or a NEW (the
  detour bumps `smp_blank_req`), the audio ISR's next 5 TDM packets empty the DSP's 128
  directory entries, ahead of any other job; the UI pass then sends the same, checked
  (`K_BLANK`). The new pool then loads as at power-on: the kit's samples first, each slot's
  entry only after its frames are in and checked, so a track plays as soon as its own sample
  has arrived and is silent until then.

## The hooks (stock 1.11, each a `jmp` to a cave that replays what it replaced)

| site | stock bytes | what it is | the cave |
|---|---|---|---|
| `0x40042E6E` | `4fef ffdc 48d7 043c` | ProjectManager's load(project, slot, cb), its entry | `smp_pj_begins++`, `smp_blank_req++`; back to `0x40042E76` |
| `0x40042ED2` | `2f05 2f03 4eba bc8a` | its success, after the +Drive read and the temp-slot write (`d5` the slot) | the slot set by stock's setter `0x4003EB62`, then `smp_pj_slot = d5`, `smp_pj_last = 1`, `smp_pj_loads++`; back to `0x40042EDA` |
| `0x40042EE6` | `1004 4cd7 043c 4fef 0024` | its exit, whatever came of it | `smp_pj_ends++`, then stock's `move.b`, `movem`, `lea`, `rts` |
| `0x40042AF0` | `2eae 000c 2f0a 4eba c06a` | NEW(project, slot) 0x400428C0 where it sets the slot (`12(%fp)` the slot: -1 for NEW and CLEAR, the slot for a LOAD of an empty one) | the slot set by stock's setter, then `smp_pj_newslot`, `smp_pj_last = 2`, `smp_pj_news++`, `smp_blank_req++`; back to `0x40042AFA` |

The composer checks the stock bytes of each site and of the instructions each cave returns
to; no other mod in the repository touches these ranges, and no branch in stock lands
inside one (objdump of MAIN OS). The caves run in the OS's own task and only count; the
work is done in the UI loop (`smp_pl_poll`, every pass, from `smp_boot`).

What the poll does with them:

| seen | meaning | action |
|---|---|---|
| `begins != ends` | a LOAD is running | silence (blank), wait |
| it ends, no success, no NEW within half a second | the LOAD failed | the pool as it was (reloaded; resident: entries only) |
| `loads` moved | LOAD of `smp_pj_slot` | switch to that project's list, or the legacy list if it has none (decision 3) |
| `news` moved | NEW (or LOAD of an empty slot) | switch to an empty pool (decision 1); a slot >= 0 gets an empty list at once |
| the slot byte `0x405CD899` moved, no event | SAVE AS, DELETE of the active slot, a project received as SysEx, FORMAT, factory reset | the pool stays and is the new slot's (its list written) |
| the pool changed (an edit, a recording kept, LOAD TO PROJECT, a slice table) | | the owner's list rewritten at once (decision 2) |

A switch: (1) silence, the recorder stopped (its take is saved into the old project's
pool), LOAD TO PROJECT's queue and the preview dropped; (2) wait until nothing of the old
pool still moves (a recording's save, a directory write; six seconds at most); (3) the old
project's list written if it changed; (4) the superblock records the switch's intent; (5)
the new list's directory, meta block and slice area into the image and RAM; (6) the
superblock names the new owner; (7) the loader sends the DSP what it needs.

## The flash layout (all inside our region, above the pool image's last sector `0x6C8000`, below the library at `0x700000`)

| sectors | what |
|---|---|
| `0x6C8001 .. 0x6CFFFF` | free (between the pool image and the lists) |
| `0x6D0000`, `0x6D0001` | the **superblock**, two copies written in turn |
| `0x6D0100 + 256 x (2p + c)` | **list p** copy c: p = 0..127 the projects, **128 the legacy list**; c = 0, 1 |
| `.. 0x6E02FF` | the lists' end (`PL_END = 0x6E0300`) |
| `0x6E0300 .. 0x6FEFFF` | free |
| `0x6FF000` | Direct Jump's global settings sector (`DN2S`, branch `jump`): not ours; a `_Static_assert` keeps the lists below it |

Every read and write goes through `pl_rd` / `pl_wr`, which refuse anything outside
`0x6D0000 .. 0x6E02FF` or past the device; the pool image only through `link.c`'s bounded
`image_write`. `_Static_assert`s hold the region above the pool image and below the library.
The lists need no more of the device than the library already does (`BLK_SECTORS >= PL_END`,
else the feature stays off: one pool, as v0.37).

### The superblock (one sector, native big-endian words)

| word | what |
|---|---|
| 0 | `0x444E324A` `DN2J` |
| 1 | version, 1 |
| 2 | sequence (the newer of the two copies wins) |
| 3 | **generation**: lists of another generation are void (a send from the computer bumps it) |
| 4 | **owner**: the project (-1..127) whose pool the image's directory is |
| 5, 6 | a switch in progress: kind (0 none, 1 LOAD, 2 NEW) and its slot |
| 7 | the checksum of the image's directory page as last written into the owner's list (`dirsum`) |
| 8 | the checksum of the directory a switch in progress is writing (`tdirsum`) |
| 10 | the superblock's check: `checksum(words 0..9) ^ 0x504C5342` |

### A list (one copy: 218 of its 256 sectors)

| sector | what |
|---|---|
| +0 | header, written **last**: `0x444E324B` `DN2K`, version 1, p, sequence, generation, flags (1 meta block, 2 slice area), the checks of the sums, the directory, the meta block, the slice area, the meta room (8 KB), and its own check (`checksum(words 0..10) ^ 0x504C4B31`) |
| +1 | the slots' **sums**: 128 x u32, the loader's checksum of each slot's sector-rounded frames as it read them (0: not known yet) |
| +2 .. +9 | the directory page (4 KB), exactly as the image holds it (`SMP1`, count, 128 entries, names, meta pointer) |
| +10 .. +25 | the meta block (8 KB), if flag 1 |
| +26 .. +217 | the slice area (128 x 768 B), if flag 2 (a slot has a table made on the instrument) |

The checksum is the image header's (`link.c`'s `checksum`, a Fletcher-like pair). A copy is
whole only if its header checks out, belongs to list p and to the superblock's generation,
and every part it names checks out.

## Power loss

- **A list** is written into its **older** copy, parts first, header last. A reader takes
  the newer copy that is whole, else the older: a list cut half way leaves the previous one
  in force (checked: a power cut after each sector of a pool change).
- **The superblock** likewise (two copies, the sequence decides).
- **A switch** writes its intent (kind, slot) to the superblock before anything moves, then
  the target directory's checksum, then the image, then the new owner. At power-on: if the
  OS came back with the new project active, the switch is done again; if it came back with
  the old one and the image already holds the new pool, the old project's pool is put back;
  otherwise nothing had moved (checked: a cut after each sector of a switch, both ways).
- **The image changed after its list** (a cut between the image's directory write and the
  list's, or an older build in between): its checksum differs from `dirsum`; the image is
  the newest pool there is, and becomes the owner's list.
- **The image's directory unreadable** (a torn header): the active project's list (or the
  legacy one) is written back into it.

## Migration (first power-on with this build)

No superblock: today's pool (the image's directory, meta block and slice area) is written as
the **legacy list** (128), then the superblock (generation 1, owner = the active project).
The pool image is not written at all (checked). Every project without a list of its own
uses the legacy list, so nothing changes for anyone until a project's pool changes; from
then on that project has its own list (decision 3). The legacy list's sums are filled in
once the power-on load has read the frames.

## A send from the computer (the host tool, the web import tool)

A whole-image send (SysEx BEGIN .. END) or FORGET replaces the pool **of every project**, as
it always did: BEGIN bumps the generation (every list void), END writes the new pool as the
legacy list. (Other projects' frames are overwritten by the send, so their lists could not
stand.) The library's SysEx commands (16..23, 26) do not touch the pool or the lists.
`tools/web` needs no change to keep working; its send dialog could say "replaces the pool of
every project" (not done here).

## Downgrade to v0.37, and back

v0.37 reads the pool image as it always did and ignores the lists: it boots and plays the
pool of the project that was active at power-off (checked: the image's header and directory
are v0.37's format, every entry's frames whole). Coming back:

- if v0.37 changed the pool, the image's checksum differs from `dirsum`: the image is kept as
  the owner's list (nothing it added is lost);
- v0.37 knows nothing of the other projects' extents and may have written a new sample over
  one: each slot's **sum** is checked when its list is loaded, and a slot whose frames no
  longer match is emptied (silent), never played as another sample. (A slot whose sum was
  not known yet -- one trimmed since its last load -- is not checked.)

## Known limits

- **An unsaved project's pool** (owner -1, after NEW) is not kept when another project is
  loaded, as the unsaved project itself is not. Samples from the library are still in the
  library; **a recording made in an unsaved project is lost with it unless the project is
  saved** (SAVE AS writes its list). Copying recordings into the library's RECORDED folder
  (the research's "adoption", question 4) would remove this; it is not built.
- **Slots changed behind the OS's back** (DNX/Transfer writing `/projects/N`, COPY/PASTE,
  CLEAR or DELETE of a stored slot) keep their old list until the project there is saved
  again; a deleted project's list keeps its extents reserved (space, not data).
- **The pool image is still 400 MB for all projects together**: samples of every project's
  list share it. LOAD TO PROJECT says FULL when the 400 MB are used, as before.
- **A switch reloads what is not resident**: after a power-on, the first LOAD of a project
  sends all of its samples (the kit's first), at the link's 0.7 MB/s.
- The superblock and lists are written from the UI task, and on BEGIN / END / FORGET from
  the MIDI task (as the image itself already was); two writes racing would leave one copy
  of the superblock torn, which its check rejects (the other copy stands).

## Unverified on hardware

- That the slot byte `0x405CD899` holds the right project after a real power cycle (the
  research's [?]): if it came back -1 the pool stays and changes go to no list until a
  project is saved or loaded; if it came back as another project with a list, that list
  would load. **Check first, read-only** (`docs/project-pools-research.md` section 5).
- A real LOAD and NEW through the detours (the emulator runs the OS's code with the +Drive
  read stubbed, and NEW from its slot-setting site), the switch's real time, the eMMC's
  write time for a list (10 to 218 sectors).

## Verified in the emulator (2026-11-02, `scripts/emu_pools.py`)

ColdFire emulator (digikit snapshot `ui800M-v014`), the build installed, the +Drive and the
DSP played by Python; the OS's own LOAD (`0x40042E6E`, its +Drive read and temp-slot write
stubbed to succeed), NEW (entered at its slot-setting site) and SAVE AS (`0x400402D8`, its
writes stubbed). Every audio period, every DSP directory entry was checked against the
switched-to pool and its frames against the sample's own bytes (10,409 entry checks).

| check | result |
|---|---|
| migration (a v0.37 image of 3 samples, no lists) | legacy list == the image's directory byte for byte; superblock owner 4; 0 sectors written to the pool image; the legacy list's sums filled in after the load |
| LOAD 7 (no list) | the legacy pool; the DSP's directory empty 1 period after the LOAD; 3 slots resident, 0 frame words sent |
| LOAD TO PROJECT in 7 | 7's own list written at once, with the new slot's sum |
| LOAD 9 (no list), then a slot emptied and a library sample loaded in 9 | the legacy pool, 7's sample silent; the new sample placed at `0x3400..0x3A40`, clear of 7's at `0x2800..0x33B8` |
| LOAD 7, 9, 7 | each its own slots; 0 frame words sent (all resident) |
| NEW (-1), NEW in 12, LOAD 5 (old), LOAD 12 | empty; empty and 12's list empty; today's pool; empty |
| SAVE AS 42 from 9 | the slot byte 42; 42's list == 9's pool, 9's kept; LOAD 42 gives it |
| power cycle (7 active, its kit's track on slot 4) | 7's pool, load order slot 4 first (`[3, 0, 1, 2]`); 9's change kept |
| list 9's newest copy corrupted / both | its previous copy (HAT, not HATTWO) / the legacy pool |
| a sector of 7's library sample changed on the +Drive | 1 mismatch: that slot never reached the DSP, emptied; the other three played |
| the image's directory changed behind our back | boot case 6: kept, into 7's list |
| power cut after each write (and torn inside each multi-sector write) of a rename (20 sectors) and of a switch 7 -> 9 (12 sectors), the OS back with 9 and with 7 | 26 power-ons, every one a whole pool, the right owner's, lists 7 and 9 intact |
| every sector written | inside the pool image, the lists' region or the library; the final image's header and directory as v0.37 reads them, every entry's frames whole |
| the DSP | never held another project's sample nor one half sent (after the harness fix of its own expected-bytes table) |
