# ERASE MOD DATA (v0.39)

The owner approved an on-device action that removes everything the mod keeps on the
+Drive, so a unit can go back to stock firmware clean. **Erase on the mod first, then
flash stock**: stock firmware has no way to remove our data. It never reads our sectors,
so they would only sit there unused.

Code: `csrc/sampler/erase.c` (the erase, the verify, the write latch); the keys in
`csrc/sampler/rec.c`, the screens in `csrc/sampler/smp_page.c`, link commands 28/29 in
`csrc/sampler/link.c`, the button in `tools/web/index.html` (section 7). Check:
`scripts/emu_erase.py`, the ship gate's step **`erase`**.

## Using it

On the instrument: on a sample track, open the sample list (turn SAMP), **FUNC + YES**:
the browser's top, the two stores. Put the cursor on **+DRIVE** and press **RIGHT**: a
one-item menu, **ERASE MOD DATA**. **YES**: "ERASE ALL SAMPLES AND MOD DATA?"; **YES**:
"ARE YOU SURE? IT CANNOT BE UNDONE"; **YES**: it erases. **NO** at either question (or
LEFT out of the menu) closes it and erases nothing.

While it runs the screen shows ERASING, then VERIFYING, with a progress bar, and takes
every key. At the end: **ERASED, RESTART THE DIGITONE**, or **ERASE FAILED** with the
reason and the sector (REFUSED, TRIM ERROR, READ ERROR, NOT ERASED, +DRIVE NOT READY).
YES or NO closes it. After a failure it can be asked again.

**Restart after it.** From the first erase command until power-off nothing of the mod
writes to the +Drive (the pool image, the per-project lists, the library, the settings
sector all refuse), so what the mod still holds in RAM is never written back. After the
restart the mod comes up as on a fresh install: no samples, no library, no lists,
DIRECT JUMP off.

From the computer (the import page, section 7 "Erase mod data"): two confirmations in
the browser, then link command 28 with the word `ERASE`; the page polls command 29 and
shows the progress and the result. The instrument runs the same erase, from its UI loop.

## What is erased (docs/memory-map.md's +Drive table)

| sectors | what |
|---|---|
| `0x600000` .. `0x6C8000` | the pool image (header `DN2Q`, then 400 MB) |
| `0x6D0000` .. `0x6E02FF` | the per-project pools: superblocks, 129 lists x 2 copies |
| `0x6FF000` | the mod's settings sector (`DN2S`: DIRECT JUMP) |
| `0x700000` .. the device's last sector | the +Drive library: superblock, index, folders, frames |

Nothing else. The stock store (below `0x458000`), the factory buffer (`0x458000` ..
`0x5D7FFF`) and the free gaps between our regions (`0x5D8000` .. `0x5FFFFF`,
`0x6C8001` .. `0x6CFFFF`, `0x6E0300` .. `0x6FEFFF`, `0x6FF001` .. `0x6FFFFF`) are never
named. `erase.c` asserts it twice: statically (each region's bounds against the other
files' constants and against the floor `0x600000`, above the factory buffer) and on every
call (`er_inside`: one range inside exactly one of the four regions, at most 2,048 sectors,
never past the device; otherwise the erase stops with REFUSED before the driver is called).

## How

The eMMC's own erase command: the stock block driver's TRIM, `0x4012c4b2(sector, count)`,
which takes the driver's lock and sends **CMD35** (start), **CMD36** (start + count - 1),
**CMD38 argument 1** (TRIM), then waits for the card. Calls of **2,048 sectors (1 MiB)**,
exactly as stock's FORMAT +DRIVE makes them (`0x4012f3cc`): the call size every unit has
run. That routine has no bounds check of its own, which is why every call passes
`er_inside` first. About 20,400 calls on a reconfigured 32 GB part, made from the UI loop
at most 40 ms (or 256 calls) a pass, so the screen keeps drawing.

**Order** (each step's header before any bulk, so a power cut anywhere leaves a +Drive the
mod boots from as empty):

1. the pool image's header (`0x600000`);
2. the lists' region, `0x6D0000` up (its two superblocks first, then every list);
3. the settings sector;
4. the library's superblock, index and folders (`0x700000` .. `0x700104`);
5. the pool image's frames;
6. the library's frames, to the device's end.

**Verify**: every header sector (the pool's, the two superblocks, all 258 list-copy
headers, the settings, the library's 261) and 64 sectors spread over each of the pool's
frames, the lists and the library (the first and the last of each among them) are read
back. Each must read as erased: 512 bytes all `0x00` or all `0xFF` (the card's
ERASED_MEM_CONT decides which; JEDEC: trimmed blocks read as erased). The first that does
not stops it with NOT ERASED and its sector.

**Secure erase / secure trim: not used.** They need CMD38 with other arguments
(`0x80000001` / `0x80008000`), which no stock routine sends, so it would be a new driver
path never run on a unit. The emulator's card cannot answer for it either. JEDEC also made
both obsolete from eMMC 4.51 on. Link command 29 reports the card's EXT_CSD as the driver
read it at power-on (SEC_FEATURE_SUPPORT, ERASED_MEM_CONT, EXT_CSD_REV), when that copy is
still intact (its SEC_COUNT equals the device's size). That way a unit's answer can settle
the question later. TRIM unmaps the blocks in the card's FTL, and they read back erased.
That is what a clean return to stock needs.

## Power loss during the erase

Each part's boot already treats a missing or invalid header as empty:

- the pool image: no `DN2Q` header, so `smp_dir_ok` 0, an empty pool (link.c `header_read`);
- the per-project lists: no superblock means a first power-on with the feature (pools.c,
  case 1). It writes an empty legacy list and a new superblock, as a fresh install does. A
  list's header that does not check out is ignored;
- the settings: no `DN2S` means DIRECT JUMP off;
- the library: no `DN2L` superblock means no library (`smp_lib_state` 1); it is formatted on
  first use.

The gate powers the mod on (its RAM fresh, its boot run) on the +Drive as the erase left
it after the 1st TRIM call, inside the lists (12th), after the lists (34th), after every
header (36th), inside the pool's frames (200th), inside the library's (2,000th), and at the
end. Every one boots without a fault, reads the pool as empty and writes only inside its
regions. After the whole erase the boot is the same, state and writes, as on a +Drive the
mod never wrote. A cut erase is finished by asking again.

## The gate's step (`erase`, scripts/emu_erase.py)

The +Drive is played by Python, as in link16 and pools: the driver's three entries
(read, write, TRIM) are stubbed and every call is logged as the eMMC commands the stock
routine sends for it. The device is the owner's size (48,340,992 sectors).

- **ui**: data in every region, in the stock store, the factory buffer and the gaps; the
  browser opened as a person opens it. RIGHT on +DRIVE, the menu; NO at the first
  question; NO at the second; LEFT out of the menu: after each, no command but reads, the
  +Drive as it was. Then three YES: ERASED. TRIM ranges only in the four regions, covering
  each exactly once, headers first; no write from the first TRIM on (a setting changed
  afterwards is not written); every byte outside the regions as it was; every written
  sector of the regions erased; the verify's reads inside the regions; YES closes.
- **link**: command 28 with a wrong word refused, nothing done; `ERASE`: ERASED on a card
  whose erased state is `0xFF`, command 29 reporting it; a card that keeps one sector:
  NOT ERASED at that sector; a TRIM that returns an error: TRIM ERROR at its sector, the
  erase stopped there; a failure closed may be asked again.
- **boot**: the power-ons above.

## Not verified (hardware)

- The stock TRIM routine's behaviour on the card is stock's: FORMAT +DRIVE runs it the
  same way. But nobody has timed ~20,400 calls on a unit (expect tens of seconds to a
  few minutes), or seen whether the Kingston part reads trimmed sectors as `0x00` or `0xFF`.
  If it read old data, the verify would say NOT ERASED with the sector. It would not say
  ERASED.
- The eSDHC level: under the emulator the driver's entries are stubbed (as for every
  +Drive check of the mod), so the command sequence is the routine's, read from its
  code, not seen on the bus.
- The EXT_CSD copy at `0x4e6f1100` being intact after power-on (the status says when it
  is not).
