# The +Drive: what it is, how it is used, and where a sample library fits

**2026-09-26. Research only.** Nothing here was sent to an instrument. The
evidence is stock DN2 1.11 MAIN OS (`out/main111.dis`), stock DT2 1.16 MAIN OS
(disassembled the same way), both SHARC images through digikit's `sharcdb`, the
owner's captures in `00_Resources/07_DataCapture/`, and DNX's storage documents.

**The goal, restated.** Keep everything the +Drive already holds (projects,
presets, kits, the working state) and add a samples library beside it, which
DNX manages. That library is what the Wavefinder tables
(`docs/wavefinder-feasibility.md`) and any ported Digitakt II machine
(`docs/dt2-machine-port.md`) will read from.

Grades: **[V]** verified, meaning something was run (a script over the image
or a capture, or a tool). **[D]** derived, meaning read from the disassembly.
**[S]** speculative. A static reading is never graded [V].

---

## The short answer

1. **The +Drive is a Kingston 32 GB eMMC, and the firmware sees 23.05 GiB of it.**
   It is not 128 GB. The firmware carries a table of the eMMC parts it
   accepts. The part on the owner's board is the only 32 GB entry, and that
   entry gives the user area as **48,340,992 sectors (23.05 GiB)** once the
   factory "reconfigure" has run. **[D]**, and the table's bytes are **[V]**.
2. **There is no filesystem on it.** The DN2 stores everything in fixed slots at
   fixed sector addresses, one slot per project, preset and kit, plus two banks
   for the working state. The paths DNX uses (`/projects/3`, `/kits/A/1`) are a
   routing layer drawn over those slots. They are not directories on the disk.
   **[D]**
3. **About 2.1 GiB of the 23 GiB is in use, and the rest is never touched.** The
   stock storage code refuses by its own bounds check to write past
   2,224 MiB. Format and factory reset erase only their own slots. No stock
   code reads anything above 2,224 MiB, or between 36 and 128 MiB. **[D]**
4. **The Digitakt II keeps its samples in exactly that unused space.** It
   carries the same slot store and adds a second store, a real filesystem with
   the magic `ekFS`, starting at **sector `0x5D8000` (2,992 MiB)** and running
   to the end of the device, about 20 GiB. The DN2 has the slot store and the
   block driver, byte for byte. It has neither `ekFS` nor the code that serves
   it. **[D]**
5. **So a sample library is a new region, not a new folder.** The cheapest
   route: the firmware reads and writes our own region through the block driver
   it already has, and DNX reaches that region through a new route
   (`/samples/...`) on the transfer protocol it already speaks. **[D]** for the
   parts that exist. The plan itself is **[S]** until the experiments in §6
   run.

---

## 1. What the +Drive physically is

### The part: 32 GB, not 128 GB

| source | reading | grade |
|---|---|---|
| Board photo, `docs/hardware.md` | U8 = Kingston **`EMMC32G-TX29`** | [V], photo |
| Firmware table of accepted eMMC parts, DN2 1.11 **`0x4029f554`**, 7 × 32-byte entries | Kingston (manufacturer `0x70`), product names **`TX2932`** and `TS0A32`, both 32 GB | [V] bytes, [D] meaning |
| Same table in DT2 1.16 (`0x402b4a24`) and DN2 1.10E (`0x40286030`) | **identical entries** | [V] |

The owner's "128 GB" matches neither the board nor the firmware. The only
parts the firmware accepts are 4 GB (Toshiba `004G..` ×4, Samsung `4FTE4R`) and
32 GB (Kingston ×2). A 128 GB part fails the table lookup at `0x4012c0ec`, and
the reconfigure step then refuses it. My guess at the source of the number is
**[S]**: the unit has 128 MB of DDR2 and holds 128 projects. §7, experiment E1,
settles it.

### Each table entry, decoded (`0x4012c250`, `0x4012c2a0`, `0x4012c360`)

The fields are read against the card's EXT_CSD register. The eSDHC stores it
byte-swapped per 32-bit word, so buffer offset `0x98` is EXT_CSD byte 155.

| field | Kingston 32 GB entry | meaning |
|---|---|---|
| +0 | `0x70` | CID manufacturer |
| +4 | `"TX2932"` | CID product name |
| +8 | `0x4db` | expected MAX_ENH_SIZE_MULT |
| +12, +16 | 16, 1 | expected HC_WP_GRP_SIZE, HC_ERASE_GRP_SIZE |
| +20 | **`0x186` (390)** | the ENH_SIZE_MULT the firmware writes |
| +24 | **61,120,512** sectors = 29.14 GiB | the size it expects **before** reconfigure |
| +28 | **48,340,992** sectors = 23.05 GiB | the size it expects **after** reconfigure |

**The reconfigure** (`0x4012c360`) runs only if PARTITION_SETTING_COMPLETED is
not already 1 (the check is `0x4012c140`). It sends four CMD6 SWITCH writes:
ENH_SIZE_MULT bytes 140 and 141, PARTITIONS_ATTRIBUTE = 1 (enhanced user
area), and PARTITION_SETTING_COMPLETED = 1. **It never writes ENH_START_ADDR.**
**[D]**

The arithmetic: 390 × 16 × 512 KiB = **3,120 MiB of pseudo-SLC**. The device
shrinks by 12,779,520 sectors, which is 6,240 MiB, exactly twice the enhanced
area. So the part is TLC and pays three raw units per pSLC unit. **[D]**,
arithmetic on the table. ENH_START_ADDR is left at its default, which JEDEC
sets to 0. If that holds, **the first 3,120 MiB is the fast, durable pSLC
region**, and it covers every stock slot (all below 2,224 MiB) as well as the
DT2's `ekFS` metadata (2,992 to 3,037 MiB). **[S]** on the default. The fit
suggests Elektron planned the layout around it.

**How capacity reaches the code.** At card init, `0x4012c086` stores EXT_CSD
SEC_COUNT (buffer `0x4e6f11d4`) in `0x4461b6b0`. Both block routines reject a
sector at or beyond that value. At boot, `0x4012c2a0` checks the value against
the table entry and returns −4 on a mismatch. That failure is where
`MMC NOT IN SLC MODE` (`0x40213cf9`, tested at `0x4002f03e`) comes from.
**[D]**

### The block device and its driver

| routine | what it does | grade |
|---|---|---|
| **`0x4012c59a(sector, bytes, buf)`** | CMD18 multi-block read through the eSDHC at `0xfc0cc000`. Recurses in 64 KiB pieces, uses a bounce buffer at `0x4e6f1300` when `buf` is unaligned, and holds a driver lock (`0x4667ad00`, taken by `0x400015a0`, released by `0x400016d2`), so it is safe to call from any task | [D] |
| **`0x4012c780(sector, bytes, buf)`** | CMD25 multi-block write. Same shape and same lock, and it rejects a range that runs past capacity | [D] |
| **`0x4012c4b2(sector, count)`** | CMD35/36/38 with argument 1, i.e. **TRIM** | [D] |
| `0x400f166a` / `0x400f16bc` | read and write wrappers in 32 KiB chunks. The MRAM code uses these. **Only 7 read sites and 8 write sites call the primitives in the whole image, and no pointer table holds their addresses** | [V] byte search, [D] |

Addresses are **512-byte sectors, 32-bit**, so the driver reaches 2 TB. The
stream layer above it (`MmcStreamReader` / `MmcStreamWriter`, `0x400f0154`,
`0x400f045e`) keeps a **32-bit byte offset** (`stream+44`, `>> 9` at the call).
That caps it at the first 4 GiB. A library above 4 GiB must call the sector
routines directly. **[D]**

### The sector map, DN2 1.11

Read from the slot-store code (`MmcFs`, the singleton returned by `0x4018ddc8`).
Each row names the routine that computes the address.

| sectors | bytes | contents | computed by | grade |
|---|---|---|---|---|
| `0x000000` | 0 | store header: magic **`0xBEEFBACE`** + one word | read `0x4012d206`; format (`0x4012f332`) sets it at `0x4012f516` and writes it via `0x4012e662` | [D] |
| `0x000800` | 1 MiB | write-protect bitmap, 400 bytes = 128 + 2,048 + 1,024 bits | `0x4012d2b4`, tested at `0x4012d5a8` | [D] |
| `0x001000`–`0x001FFF` | 2–4 MiB | **2,048 presets** × 1 KiB (8 banks × 256) | `0x4012de66`: `(i + 2048) × 2` | [D] |
| `0x002000`–`0x011FFF` | 4–36 MiB | **1,024 kits** × 32 KiB (8 banks × 128) | `0x401308ac`: `(i << 15 + 4 MiB) >> 9` | [D] |
| `0x012000`–`0x03FFFF` | 36–128 MiB | **not referenced by any DN2 code** (the DT2 moved its presets and kits here, see §4) | — | [D] |
| `0x040000` | 128 MiB | working state, bank A, 16 MiB. Magic **`COKi`**, 12,890,388-byte image | `0x400f1d3e`, table `0x401ff6f8` | [D]; magic [V] |
| `0x048000` | 144 MiB | working state, bank B | same | [D] |
| `0x050000` | 160 MiB | project slot "128", the temporary / active project (`saveProjectToMmc(tempProject)`) | `0x4012d7c2`, the id-128 case | [D] |
| `0x058000`–`0x457FFF` | 176–2,224 MiB | **128 projects** × 16 MiB | `0x4012d7c2`: `((p + 11) << 24) >> 9` | [D] |
| `0x458000` | 2,224 MiB | written only by the factory `#RECEIVE_AUDIO` path (`0x400cd55a`, `READY FOR SAMPLE DATA`). **No normal-mode code reads it** | `0x400cd548` | [D] |
| `0x458000`–end | 2,224 MiB – 23.05 GiB | **never read or written in normal operation** | — | [D] |

The DNX listing sizes match these slot sizes exactly. They are the
allocations, as DNX suspected: **16,777,216** per project, **262,144** per
preset bank (256 × 1 KiB) (`DNX/docs/device-storage.md` §5a). **[V]** by DNX's
listings, and the match to the slot map is [D].

**Every slot starts with a 512-byte header** (the boot scan at `0x4012d940`
reads it). The header holds a magic (`0xBEEFBACE`, or the legacy import magics
`DN1P`/`DT1P`), a length word, a 16-byte name, and a further word. A slot whose
magic is none of these is simply treated as empty. **[D]**. `0xBEEFBACE` is
also the record magic inside the project image: it sits at `+0x110` in both
MRAM dumps and at `+0x1f` in `projects_11_12890159B.bin`, and repeats through
the kit area. **[V]** (scanned).

### How much is used and how much is free

| | size | grade |
|---|---|---|
| Allocated by the stock firmware | 36 MiB (header, presets, kits) + 2,096 MiB (MRAM, temp, projects) = **2,132 MiB ≈ 2.08 GiB** | [D] |
| Actually written | less. A stored project is ~90 KB, and only occupied slots are written (DNX) | [V] DNX |
| **Free and contiguous above the projects** | 2,224 MiB → 23.05 GiB = **≈ 20.9 GiB** (≈ 26.97 GiB if the unit was never reconfigured) | [D] |
| Free hole | 36–128 MiB = 92 MiB | [D] |

---

## 2. How the DN2 reads and writes today

### Layer by layer

```
DNX / Elektron Transfer
   │  SysEx "Data" API 0x53..0x5e  (list, open, read, close, write-open,
   │  write-chunk, commit, move, copy, delete, swap, rename)
   ▼
RouteResolver   patterns → std::function handlers (28-byte vector entries)
   ├─ ProjectHandler    /projects   /projects/*   /projects/*/.metadata
   ├─ SoundbankHandler  /soundbanks /soundbanks/* /soundbanks/*/* /soundbanks/*/*/.metadata
   ├─ KitHandler        /kits       /kits/*       /kits/*/*       /kits/*/*/.metadata
   └─ BackupHandler     "/" root, move, swap
   │  each handler yields a FileStorageInfo {ok, kind, permission mask,
   │  BYTE OFFSET, size, index, ...}
   ▼
Backup{Export,Import}Adapter → Buffered/MmcStream{Reader,Writer}, SafeMmcStreamWriter
   ▼
MmcFs (slot store): directory of 129 + 2,048 + 1,024 entries in RAM
   ▼
block driver 0x4012c59a / 0x4012c780 / 0x4012c4b2  →  eSDHC  →  eMMC
```

**[D]** throughout. Addresses:

- **Route strings** sit at `0x4021ddf6`–`0x4021dfd8`. They are registered at
  `0x400ebc30…` (projects), `0x400ed922…` (presets) and `0x400eeed0…` (kits),
  each as a pattern plus a lambda (for projects: manager `0x400eb0b6`, invoker
  `0x400ebb54`) appended to the resolver's vector.
- **The handler vtables** have four slots only: two destructors, `0x400eb084`
  and `register_route` (projects at `0x401feb88`, presets at `0x401fef4c`, kits
  at `0x401ff2d8`). A new route type is therefore a small class plus one
  registration.
- **An unknown path** answers `Error: Could not resolve path` (`0x4021de5c`,
  pushed at `0x401b2d74`, `0x401b2f0c` and `0x401b3098` in the resolver) or
  `Unable to handle path` (`0x4021de46`, `0x401b2c8c`).
- **Project `FileStorageInfo`**, built at `0x400eb776`: kind 2, permission
  `0x12` or `0x7e` from `0x4012d5a8` (the mask DNX decoded, §8 of its doc),
  **byte offset `(id + 10) << 24`**, size **12,890,116** (`0x00c4b004`, the
  exact length of the image the MRAM dumps carry after their 0x110 header),
  index `id − 1`. **[D]**, and the size match is **[V]** against both dumps.

### The MmcFs API

| address | role | grade |
|---|---|---|
| `0x4012d334` | constructor: 129 × 28-byte project entries at `+16`, 2,048 × 36 preset entries at `+0xe2c`, 1,024 × 32 kit entries at `+0x12e2c`, mutex at `+0x1e030` | [D] |
| `0x4012d0b4(fs, sector, bytes, buf)` | read under the MmcFs mutex | [D] |
| `0x4012e586(fs, sector, bytes, buf, …)` | write. **Refuses any sector above `0x457FFF` and any range ending past 2,224 MiB** | [D] |
| `0x4012d13e(fs, sector, count, …)` | TRIM | [D] |
| `0x4012d7c2` / `0x4012de66` / `0x401308ac` | the project, preset and kit sector for an index | [D] |
| `0x4012d82e` | open or load a project slot (checks formatted, then occupied) | [D] |
| `0x4012eb6c` | save a project (called near `saveProjectToMmc(tempProject)`) | [D] |
| `0x4012d522`, `0x4012d5a8`, `0x4012d6fa` | occupied, write-protected, stored length | [D] |
| `0x4012d1a4` | store state: 0 unreadable, 1 no magic, 2 formatted | [D] |
| `0x4012f332` | **format** | [D] |
| `0x4012f608` | install the factory project, presets and kits | [D] |

### The transfer protocol DNX already speaks

DNX has this working on a DN2 (`DNX/docs/device-storage.md` §1, §5a, §7, §9,
§10, §11). Summarised in my words:

- **list** `0x53 path [start count]`. Paginated, with 32-bit cursors. Each
  entry is a name plus a kind marker, so **directories are part of the wire
  format**: a directory entry carries a child count.
- **read** is open `0x54 path chunk [form]`, then chunks by sequence number
  `0x55`, then close `0x56`.
- **write** is open `0x57 length path`, then chunks `0x58` carrying a
  CRC-32-zero-init checksum, then commit `0x59`.
- **move, copy, delete** are `0x5a`, `0x5b`, `0x5c`.
- **Throughput is ≈ 350 KB/s**, from a 12.9 MB project read in ~37 s. At that
  rate **1 GB of samples takes about 50 minutes.** [V] by DNX, arithmetic [D].

The Fs families the DT2 uses (`FsSample*` at `0x10`–`0x13`, `FsRaw*`) are
compiled into the DN2 as message classes. The DN2 does not advertise them
(`docs/midi-rpc-dispatch.md`). **New here:** the DN2 has **no
`FsRequestHandler`**, the class that serves them on the DT2
(`N16FsRequestHandler10FileWriterE` exists only in DT2 1.16). This settles that
note's open question statically: advertising `10 13 11 12` would find nothing
to dispatch to. **[D]**. An RTTI name can be missing for reasons other than an
absent class, so the flash test described there would still be the definitive
negative. It is no longer the cheap one.

---

## 3. Can a new folder with arbitrary files coexist?

**On this device "a folder" means a region plus a route.** The questions
become: does anything stock ever touch the region, and does anything stock
destroy it?

| event | effect on sectors outside the stock map | grade |
|---|---|---|
| Normal operation (load, save, autosave to MRAM, browse) | none. Every block access goes through the sites listed in §1, and each is bounded to its own region | [D] |
| MmcFs writes | refused past 2,224 MiB by its own guard (`0x4012e5cc`) | [D] |
| **FORMAT +DRIVE** (system menu, `0x40098dfe` → `0x4012f332`) | TRIMs projects (`0x400000` sectors from project 0), presets (`0x1000`), kits (`0x10000`), 4,263,936 sectors in all, then rewrites the header and bitmap. **Nothing else** | [D] |
| **Factory reset** (startup menu, `0x4002eb40`) | the format above, then the factory content (`0x4012f608`) into its own slots | [D] |
| **RECONF. +DRIVE** / `#MMC_RECONFIGURE` | **destroys everything** if it runs, because it repartitions the card. It is a no-op on a unit already reconfigured: `ALREADY CONFIG` / `ALREADY RECONFIGURED` | [D] |
| DNX backup / restore | reads and writes only through routes. A region with no route is invisible to it | [D] |
| `Update MMC Caches` (startup menu, `0x4002ee32`) | rewrites the MRAM header (`0x400f1dc4`) and calls three MmcFs-area routines not read here | [D], partial |
| Factory `#RECEIVE_AUDIO` (service mode) | writes a received buffer from sector `0x458000` in 64 KiB steps | [D] |
| Going back to stock Elektron firmware | our data stays and is ignored | [D] |
| **A future Elektron DN2 OS that adds sampling** | would very likely use the DT2 layout: a cache at `0x458000` and `ekFS` at `0x5D8000` through the end of the device. It would treat our data as an unformatted sample store and offer to format it | [S] |

**So the firmware neither chokes on unknown content nor deletes it. It never
looks.** Garbage inside a *stock* slot is different: an unrecognised magic
reads as "empty", and the next save overwrites it. **[D]**

**Design consequences** (all [S], because they are recommendations):

- **Leave `0x458000`–`0x5D7FFF` alone.** That is the factory buffer on the DN2
  and the cache on the DT2.
- **DNX is the master copy and the device is a cache.** No +Drive backup
  covers the region, and a 20 GB backup over this link would take about 17
  hours anyway. The library needs a content index (name, size, hash) so DNX
  can send only what is missing. The DT2 thinks the same way: its RPC can look
  a file up by hash and size (`FsRawGetFileInfoFromHashAndSize`), and the DN2's
  own `.metadata` JSON already has a `"sample_references":[{"hash":…,"size":…}]`
  template at `0x4023640c`.
- **Put our own superblock at the region's start**, with a magic, a version
  and a checksum. Firmware and DNX can then detect a region that has been
  clobbered (by a reconfigure or a future Elektron OS) instead of reading
  garbage as samples.
- **Bound every write we add**, the way MmcFs bounds its own. One wrong sector
  number in a raw write lands in a user's project.

---

## 4. How the Digitakt II stores samples, and what the DN2 shares

### Two stores on one device

| | DT2 1.16 | DN2 1.11 |
|---|---|---|
| eMMC part table | identical | identical, [V] |
| Block driver | read `0x4012deda`, write `0x4012e0c0`, same shape | `0x4012c59a` / `0x4012c780` |
| MmcFs slot store, projects | same formula, **16 MiB from 176 MiB**, temp project at `0x50000` (`0x4012eef2`) | same, [D] |
| MmcFs presets and kits | **moved**: presets 4 KiB each from `0x12000` (36 MiB), kits 64 KiB each from 44 MiB (`0x40132516`). Code at `0x40130b38` migrates the old DN2-style layout into the new one | 1 KiB at 2 MiB, 32 KiB at 4 MiB, [D] |
| Format extent | 4,341,760 sectors (projects + 8 MiB + 64 MiB) | 4,263,936 |
| Cache from `0x458000` (magic `MaGj`, read by `0x4002ccd0` and its callers) | read in normal operation | written only by the factory path |
| **`ekFS` sample filesystem** | superblock at **`0x5D8000`**, magic `0x656b4653` = **`ekFS`**, xxHash32 (seed `"1234"`) over the first `0x1fc` bytes, version 3 or 4 (`0x4015a450`). Metadata at `0x5D8040` / `0x5D80C0` / `0x5D8180`, and 32 KiB blocks from `0x5EE180` / `0x5EE980` to the end of the device | **absent**: 0 hits for the magic, [V] grep |
| `fs_rebuild_index`, `fs_run_corruption_check`, `File`, `Directory`, `FileSystemDirectory`, `FileOutputStream`, `FsRequestHandler`, `SampleManager`, `SamplePicker`, `SampleListView`, `FreeSpaceMenuView` | present | **absent** |
| `SampleLoaderBgWorker`, `SampleWaveformsFactory`, the `MidiRpcFsSample*` / `MidiRpcFsRaw*` message classes, `sample_file.*` query keys | present | **present**, [D] from strings |
| xxHash32 constants | present | present, same counts. It is a shared library, so it is **reusable for our index** |

**[D]** except where marked. So the ColdFire storage code the two share is the
**block driver, the slot store and the transfer routing**. The whole sample
side is DT2-only: the filesystem, its request handler, the sample manager UI,
and loader logic beyond the class shell.

### From file to voice on the DT2

- **Sample memory is a 400 MiB pool, not a stream.** `0x40153814` returns
  `0x19000000` (419,430,400) as the free total. Allocations are rounded to
  8 KiB (`0x40154476`). The pool is a vector of 52-byte records at
  `0x405a0f64`. Loading and unloading are explicit user actions
  (`Load Samples`, `SAMPLE MEMORY FULL`, `ALL SAMPLES WONT FIT IN %s`). **[D]**
- **So "streaming from the +Drive into the voice at trigger time"
  (`docs/dt2-machine-port.md`) is not how the DT2 works.** It loads a
  project's samples into RAM ahead of time, and the voice reads RAM. **[D]**
- **The pool cannot live in ColdFire RAM** (128 MB). It must sit in the SHARC's
  DDR3. The DT2's SHARC image zero-fills an extra **32 MiB at `0x80a00000`**,
  plus a `0x1c4`-byte control block at `0x82a00000`, which the DN2 image does
  not have. **[V]** (`dnfw ldr` on both images). Five DT2 SHARC functions
  address that control block (`0x1c4547`, `0x1c455c`, `0x1c4703`, `0x1c4820`,
  `0x1c483d`, two of them labelled block-copy by sharcdb). The orchestrator
  above them is `0x1c3bef`, and **none of the six has a DN2 twin**. [V]
  (sharcdb query). What the 32 MiB is for is **[S]**: a streaming or page
  buffer fits.
- **The transport.** Third-party research (lalzart, DT2 1.15C, unlicensed, so
  cited in my words) traces samples reaching the SHARC as 4 KiB pages plus
  five-word slot descriptors. They are pushed byte by byte over the ColdFire's
  Rapid-GPIO block at `0x8c000000` and received by the SHARC's link port 0
  under DMA, into a table of about a thousand sample resources. The same
  research describes a DT2 sample file as a 64-byte header (mono/stereo flag,
  payload length, rate 48,000), the raw 16-bit payload, and a 16-byte trailer.
- **The DN2 carries the same CPU end of that link.** It enables the port
  identically (`RGPIOBAR ← 0x8c000035` at DN2 `0x400cf4ae`, DT2 `0x400cd0d6`),
  and both images access the port 25 times, with the transport at DN2
  `0x400cf0f2` (`docs/display-path.md` found it never runs in an emulator
  boot). **[D]** The SHARC receiver is another matter. The DT2 functions that
  use the 0x401 (1,025) geometry, `0x1c3f78`, `0x1c3fe5`, `0x1c7e35` and
  `0x1c7ec5` (the last a DMA-descriptor builder), have no DN2 twins. **[V]**
  query, and the reading of what they are is [S].
- **The per-project pool size of 1016** is the manual's figure
  (`docs/dt2-machine-port.md`). No `1016` literal appears in either ColdFire
  image. The SHARC table is about 1,025 entries (lalzart). **[S]** on how the
  two relate.

**The DN2 side, physically.** The DSP's DDR3 part on the owner's board
(`D2516ECMDXGJD`, `docs/hardware.md`) is a 4 Gbit, 512 MB device **[S]**, from
the part-number convention. The DN2's SHARC image claims only
0x80000000–0x8052fbe0, about 5.2 MiB, statically **[V]**. Runtime use is
unmeasured. So the memory a sample pool needs is probably present and unused.

---

## 5. What it would take: a staged plan

Every stage lists what exists, what must be built, the risk, and the cheapest
proof. Device-side proofs are written out in §7.

### (a) Firmware reads a file from our region

- **Exists:** `0x4012c59a(sector, bytes, buf)`. It is lock-protected, takes
  sector addresses and reaches the whole device. It is callable from a cave
  exactly as the MRAM code calls it.
- **Build:** one cave that reads N sectors at our base into a buffer. For the
  demo it also puts one byte of what it read on screen, obviously and within a
  bar (`demo-builds-must-be-obvious`).
- **Region choice [S]:** start at **`0x5D8000`** (2,992 MiB) only if we choose
  to be `ekFS`-compatible (see stage c). Otherwise start at **`0x600000`**
  (3,072 MiB). That is past the DT2's `ekFS` metadata, still inside the
  probable pSLC 3,120 MiB for our index, and below 4 GiB. Bulk sample data then
  continues upward.
- **Risk: low.** A read cannot damage anything. The one hazard is an
  out-of-range sector: the driver returns −1 and the buffer is left stale.
- **Cheapest proof:** a build with **three reads side by side**. A positive
  control: sector 0, which must show `BE EF BA CE`. A second positive: the
  first sector of project slot 0 (`0x58000`), which must carry the slot magic
  or zeros. The unknown: our base. Read through `#MMCDUMP` first (E2), so the
  expected value is known before the build runs
  (`run-a-control-beside-a-negative`).

### (b) DNX writes and manages the region

Two routes, in increasing cost:

- **B1, recommended first: a `/samples` route on the Data API DNX already
  speaks.** Register one more RouteTypeHandler, with patterns `/samples`,
  `/samples/*` and `/samples/*/.metadata`, whose `FileStorageInfo` points into
  our region. DNX's list, read, write, commit and delete code is reused
  unchanged, including the checksum. **Exists:** the resolver, the pattern
  mechanism, the adapters and the stream classes. **Build:** the handler class,
  its registration (a cave at the end of an existing `register_route`), and a
  **bounded** writer, because the stock stream's 32-bit byte offset caps it at
  4 GiB and the MmcFs guard refuses our sectors, correctly. **Risk: medium.** A
  write routed to the wrong sector destroys user data, so the bounds check is
  the first line of code and not the last.
- **B2: port `FsRequestHandler` and the FsSample opcodes from the DT2.** This
  matches what elektroid already implements for the DT2. **Build:** the handler
  plus a filesystem under it (stage c). **Risk: high**, and it is a much larger
  port.
- **Cheapest proof for B1:** a **read-only** route. `/samples` lists one
  synthetic entry, and a DNX listing of `/` shows four directories instead of
  three. It writes nothing and proves registration, dispatch and the listing
  format end to end.

### (c) A sample library index

- **Exists:** xxHash32 and LZ4 in the DN2 image. `ekFS` exists only as a
  reference in the DT2 image. Its superblock shape (magic, version, hash over
  `0x1fc` bytes) is a model worth copying in outline.
- **Build [S]:** a superblock (our own magic, version, xxHash32) and a flat
  index table. Each entry holds a name or path string, size, content hash,
  start sector and length. Allocation is contiguous extents, compacted by DNX
  (the master copy) rather than by the device. Directories can live in the
  path strings: the Data API's listing already carries a directory kind, so
  the firmware can present `/samples/Drums/` without a tree on disk.
- **Decision to take with DNX:** **our own format** (simple, and DNX is the
  format authority) or **`ekFS`-compatible at `0x5D8000`** (DT2 code and a
  future Elektron DN2 OS might read it, at the cost of porting and matching a
  filesystem we have only skimmed). I lean towards our own format at
  `0x600000`. **[S]**
- **Risk: medium.** Almost all of it is design risk rather than device risk.
- **Cheapest proof:** DNX writes an index and one known file through B1.
  `#MMCDUMP` (E2) then reads the index sector back, and it must match
  byte for byte.

### (d) A sample reaches a voice

- **Exists:** the ColdFire end of the DT2's page link (`0x400cf0f2`, `RGPIOBAR`
  set at `0x400cf4ae`) and probably ~500 MB of unused DSP DDR3. **Nothing on
  the SHARC side.** The DT2's receiver, pool manager and voice render have no
  DN2 twins (§4, and `docs/dt2-machine-port.md`).
- **Build:** a SHARC-side receiver and page table, a player (a wavetable reader
  for Wavefinder, a sample reader for ONESHOT), a ColdFire loader from our
  region through the link, and the UI. Loading happens at project load or on
  demand. **It is not a stream at trigger time.**
- **Risk: high.** It is blocked on executing modified SHARC code at all, the
  same blocker Wavefinder already names.
- **Cheapest proof, before any SHARC work:** prove the link carries our bytes.
  That is a ColdFire-only build which calls the transport with a recognisable
  4 KiB page. On the SHARC side the first observable is whatever digikit's
  SHARC tooling can show. Until then, **Wavefinder's "bake tables into section
  7 or ELE3" route remains the only one that reaches a voice without this
  link.**

---

## 6. What changes for Wavefinder and the DT2 port

- **Wavefinder (`docs/wavefinder-feasibility.md` §2).** "At flash time the
  firmware writes the tables into the +Drive" is now concrete. On the first
  boot of a new build, read our superblock through `0x4012c59a`. If the
  version is older or the magic is missing, write the tables through
  `0x4012c780` into our region and update the superblock. **No filesystem
  port, no route and no DNX change** is needed for that step. The expensive
  half is still the voice (stage d). **[D]** for the routines, [S] for the
  design.
- **DT2 port (`docs/dt2-machine-port.md`).** Two corrections, recorded there:
  the DT2 **preloads into a RAM pool** rather than streaming from the +Drive at
  trigger time, and the DN2 already has **the CPU half of the sample link and
  the free storage**. The conclusion stands: the SHARC engine is the cost, and
  Wavefinder comes first.
- **Chimera (`docs/chimera-feasibility.md` §4).** "A path-addressed store" is
  accurate at the protocol level only. On disk it is fixed slots.

---

## 7. The cheapest next experiments

Device-side steps are written for the owner. **Each one is read-only.** Nothing
here writes to the instrument.

**E1. Identify the part and its state (device, read-only, already on the allow
list).**
1. Enter maintenance mode, as for `#MRAM_DUMP`.
2. `python scripts/service_console.py "#STATUS" "#MMC_GET_RECONFIGURED" "#MMC_GET_HEALTH"`
3. Report the `MMC` line of `#STATUS` and both replies back verbatim.
   - Expected: the MMC section names manufacturer `70` and product `TX2932`
     (or `TS0A32`), `#MMC_GET_RECONFIGURED` answers `TRUE`, and health reads
     low.
   - A `FALSE` means the unit runs at 29.14 GiB unreconfigured. **Then no
     library may be written until that is understood**, because a later
     reconfigure would wipe it.

**E2. Look at the free space (device, read-only; needs one tooling change
first).** `#MMCDUMP` has now been read (`0x400ce0da`–`0x400ce1be`). It parses
`#MMCDUMP SSSSSSSS LLLLLLLL` (sector, then byte count, both 8 hex digits at
fixed columns), reads with the driver's read routine only, and sends the raw
bytes with no header, 512 at a time, through `0x400053d4`. **It writes
nothing.** One caveat: an out-of-range sector returns stale buffer contents,
not an error. To run it, `scripts/service_console.py` needs `#MMCDUMP` on its
allow list, plus a raw-read mode that expects exactly `LLLLLLLL` bytes. That
is a tooling change for the owner or the main session. I did not make it.
Then run each dump separately and report its first 16 bytes and whether the
whole dump is `00` or `FF`:

| command | expect |
|---|---|
| `#MMCDUMP 00000000 00000200` | control: `BE EF BA CE …` |
| `#MMCDUMP 00040000 00000200` | control: `43 4F 4B 69` (`COKi`) or the bank-B pattern |
| `#MMCDUMP 00458000 00000200` | factory test audio or erased. Tells us if the factory wrote here |
| `#MMCDUMP 005D8000 00000200` | erased. Anything else means something unknown lives there |
| `#MMCDUMP 00600000 00000200` | erased. This is the proposed base |
| `#MMCDUMP 00012000 00000200` | erased (the 92 MiB hole) |

**E3. Read-only `/samples` route (static build, then device).** This is stage
(b)'s proof. It registers only a list handler, so it writes nothing. Boot it
in the emulator first (`use-every-tool`). The emulator does not serve storage
(`docs/emulator.md`), so what can be checked there is that the route
registers, not that it lists.

**E4. Static, no device.** Trace the DN2's `0x400cf0f2` caller `0x40186d0e`
to learn what the stock DN2 sends over the page link, if anything. Then use
sharcdb to look for the SHARC link-port-0 receive handler in the DN2 image.

---

## Open questions

- **The owner's "128 GB".** Where does the number come from? E1 answers it.
- **Is the unit reconfigured?** E1.
- **Is the free region blank on the owner's unit?** Did the factory
  `#RECEIVE_AUDIO` leave data at `0x458000`? E2.
- **Is ENH_START_ADDR 0,** so that the pSLC area is the first 3,120 MiB?
  EXT_CSD can only be read on the device, and no read-only command prints it.
- **What does the DN2 send over the `0x8c000000` link?** E4.
- **What is the DT2's 32 MiB DDR region at `0x80a00000` for?**
- **How much of the DN2's DDR3 is used at runtime?**

### For DNX

1. **B1 or B2?** Would DNX rather reach the library through a new `/samples`
   route on the Data API it already implements, or through the FsSample/FsRaw
   families (as elektroid does for the DT2)?
2. **Format authority.** Which on-device sample file format do we use (raw PCM
   with our own header, the DT2 container, or WAV)? What does the index entry
   hold?
3. **Master copy.** Does DNX accept being the master copy, with the device as a
   cache synchronised by content hash? A full +Drive backup of 20 GB at
   ~350 KB/s is not practical.
4. **Unknown slot magics.** Has DNX ever seen a project, preset or kit slot
   listed as empty that should not be? The firmware treats unknown slot magics
   as empty.

---

## Status

**[D]** for the storage map, the routing layer, the format and reset extents,
and the DT2 comparison, all from a single reading of each image. **[V]** for
the eMMC table bytes in three images, the magics in the captures, the image
size match, the SHARC load regions (`dnfw ldr`) and the sharcdb twin queries.
**Nothing was run on an instrument.** The plan in §5 is **[S]** until E1–E3
run.

## Reproducing

```sh
# DT2 listing, same flags as out/main111.dis
dnfw extract Digitakt_II_OS1.16.syx -o dt2/
m68k-linux-gnu-objdump -b binary -m m68k:cfv4e --adjust-vma=0x40000400 -D dt2/section_3_MAIN_OS.aplib.bin > dt2main116.dis

# the eMMC table: 7 × 32 bytes at DN2 0x4029f554 / DT2 0x402b4a24,
# {u32 mfr, char *name, u32 maxenh, u32 wp, u32 erase, u32 enh, u32 sectors, u32 sectors_after}

# SHARC load regions
dnfw ldr Digitakt_II_OS1.16.syx --limit 400
dnfw ldr Digitone_II_OS1.11_dist.zip --limit 400

# SHARC databases (digikit tools/sharcdb.py, from the refscan worktree)
python tools/sharcdb.py build <section_7 blob> --name dt2-1.16 --out dt2.sqlite
```

Key greps over `out/main111.dis`: `4012c59a`, `4012c780` and `4012c4b2` for
every block access. `#4554751` finds the MmcFs write guard. `#4263936` is the
format extent. `#4554752` is the factory audio write.
