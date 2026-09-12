# The MAIN OS memory map

Where the code, its constants, and its runtime state live in the ColdFire V4e
address space, reconstructed from the startup routine and the cross-references.
A visual explorer of this is an Artifact with a version selector (link in the
project notes); this is the written record.

**Two builds are mapped: 1.11 (the target — what the device runs) and 1.10E
(kept for comparison).** Every address moves on a relink, so nothing is shared
between them: each column below was measured from its own image. Never carry an
address from one release to another — the parameter table alone moved ~90 KB.

## The image versus runtime RAM — the distinction that matters

The MAIN OS section is loaded at `0x40000400` and holds **code, read-only data,
and the initializers for RAM** — it is not where the running firmware keeps its
mutable state. The startup code makes this explicit: it copies a region of the
image to external SDRAM and clears BSS there before entering `main`.

**There are two runtime data regions, not one.** An earlier version of this
document said "runtime data lives at `0x80000000`, not in the image". That is
true of the initialized `.data` — about 64 KB — and wrong about everything else.
`0x4000053e` calls the copy routine and *then* the BSS clear, and the BSS clear
covers **~100 MB immediately after the image**, in the same `0x40000000` SDRAM
space:

```
400004ba:  moveal #0x402fc000,%a0    ; BSS start  (1.10E: 0x402e2000)
400004c0:  movel  #0x466b74d0,%d1    ; BSS end    (1.10E: 0x464f47d0)
400004c6:  subl   %a0,%d1 ; asrl #4,%d1
400004d2:  moveml %d4-%d7,%a0@       ; zero 16 B at a time, d4-d7 cleared
```

| Build | BSS start | BSS end | Size |
|---|---|---|---|
| 1.10E | `0x402e2000` | `0x464f47d0` | 102,836,176 B |
| 1.11 | `0x402fc000` | `0x466b74d0` | 104,576,208 B |

BSS starts at exactly the address this map calls the ".data initializer block 1"
— not a contradiction, but an ordering: the copy routine consumes that image tail
into `0x80000000` first, and the clear routine then recycles it as the first
bytes of BSS. A second, independent reason those trailing bytes are not free cave
space.

**The top of SDRAM is `0x48000000`, and 25.3 MB above BSS is unclaimed.**
Measured 2026-09-12, answering the gating question in `docs/ideas-backlog.md`
§6. The C runtime's first instruction sets the stack pointer:

```
400004f2:  moveal #0x48000000,%sp     ; before the .data copy and BSS clear
```

Stacks descend on ColdFire, so that pins the top of usable RAM: SDRAM spans
`0x40000000`–`0x48000000`, **128 MB**. BSS ends at `0x466b74d0`, leaving
**26,512,176 bytes (25.3 MB)** between the two.

That window is genuinely unclaimed, by three independent measurements:

| Evidence | Result |
|---|---|
| Immediates naming an address in `[BSS start, top of RAM)` | **7,043** — BSS is densely named |
| The highest of them | `0x466b7420`, `0x466b7456`, `0x466b748c` — **within 68 bytes of the BSS end** |
| Immediates naming anything **above** the BSS end | **none** |

The four values the scan returns above `0x466b74d0` are not addresses:
`0x466b74d0` itself is the clear loop's own bound, `0x474e5543` is the ASCII
`"GNUC"`, and `0x47efffff` (twice) is a float constant. Statics climb to within
68 bytes of the BSS end and then stop dead — which is what a linker-computed
`_end` looks like, and means **the heap is a static arena inside BSS, not a
region above it.** That is also why BSS is 100 MB: it is globals *plus* the
pool.

So the window's only occupant is the stack, descending from `0x48000000`. Its
depth is unmeasured. **The safe end of the window is therefore the bottom** —
just above `0x466b74d0`, where the stack would have to descend 25 MB to reach
it — not the top, which is where the stack already is.

**Use the BSS span as a validity filter.** An absolute long decoded out of the
image is only plausibly a data reference if it lands inside it. Scanning 1.11 for
`lea`/`pea` of absolutes above the image end yields apparent targets at
`0x4e541300` and `0x5a2967c1`; both fall outside BSS and are opcode bytes
masquerading as addresses. The `0x42c6xxxx` and `0x4464xxxx` clusters fall
inside, and `docs/parameter-set-tables.md` identifies what they hold.

## 1.11 — the build target (build 40059, MAIN OS 3,192,192 B)

The startup routine at `0x4000045c` runs **two** copy loops, where 1.10E ran
one, and clears twice as much BSS:

```
0x4000045c  lea 0x402fc000,%a2 ; lea 0x80000000,%a1   ; copy .data block 1
            movel %a2@+,%a1@ ... cmpal #0x40304000    ; until 0x40304000
            clrl %a0@+ ... cmpal #0x80008000          ; clear BSS to 0x80008000
0x40000486  lea 0x40304000,%a2 ; lea 0x80008000,%a1   ; copy .data block 2
            movel %a2@+,%a1@ ... cmpal #0x4030b980    ; until section end
            clrl %a0@+ ... cmpal #0x80010000          ; clear BSS to 0x80010000
```

| Range | What | Notes |
|---|---|---|
| `0x40000400`–`~0x40000600` | reset vector + C runtime bring-up | writes `0xfc080000` (memory controller); two copy loops |
| `~0x40000600`–`~0x401d0000` | **program code** (~1.95 MB) | grew ~104 KB over 1.10E, pushing everything below it later |
| `~0x401d0000`–`~0x40287000` | **read-only data**: parameter tables, vtables, RTTI, strings | the DN2 parameter table is **`0x401f7fc4`** |
| `~0x40287000`–`0x402fc000` | packed data records + **unreferenced padding runs** | the only free space: 41 runs ≥256 B, **~29 KB**, largest ~1 KB (`dnfw cave scan`) |
| `0x402fc000`–`0x40304000` | **.data/BSS initializer block 1** | copied to `0x80000000` — **not free space** |
| `0x40304000`–`0x4030b980` | **.data/BSS initializer block 2** | copied to `0x80008000` — **not free space** |
| `0x4030b980` | end of the loaded MAIN OS section | exactly where copy loop 2 stops |
| `0x402fc000`–`0x466b74d0` | **main BSS, ~100 MB** | cleared at `0x400004b2`; recycles the initializer tail. Holds the `ParameterSet` slot tables at `0x42c6xxxx` (`docs/parameter-set-tables.md`) |
| `0x80000000`–`0x80010000` | **fast SRAM**: the copied `.data` + its own small BSS | cleared to `0x80010000` — double 1.10E. **Section 4 (the *updater*, not DSP) loads at `0x80000400`**; this is not the main heap |
| inside the per-track object (`~+0x4f2e0`) | **engine modulation state** | measured on 1.10E; **re-anchor pending on 1.11** |
| ELE3 dest `0x02010000` | **bootstrap** (recovery receiver) | 1.10E used `0x02000000` |
| ELE3 section id **8** | **new in 1.11** — 103,416 → 159,948 B, dest 0 | ships with Outbox-8 support; see below |
| `0xfc000000`–`0xfc0fffff` | **ColdFire peripherals** (MBAR) | startup writes `0xfc080000` |

**The parameter table, verified.** `0x401f7fc4` is the origin whose record+0 is
a short-name pointer: `record[id] = 0x401f7fc4 + id*60`, and indexing it returns
`SPD MULT FADE DEST WAVE SLEW SPH MODE DEP MULT` at ids 75–84 (LFO1) and again
at 95–104 (LFO3), exactly as 1.10E's `0x401e29d0` does. An earlier note recorded
`0x401f7fc8`; that was **four bytes into this origin** — the same field-offset
confusion `docs/parameter-table-consumer.md` records for 1.10E. Use `0x401f7fc4`.

**Function-level RE is not yet re-anchored on 1.11.** The page renderer, the
`is_lfo_param_modulatable` 3-LFO gate, the LFO-speed handler and the bootstrap
functions were all located on 1.10E. Their 1.11 addresses are unknown and must
be re-found, not extrapolated.

## 1.10E — kept for comparison (build 40050, MAIN OS 3,085,696 B)

One copy loop: `lea 0x402e2000,%a2; lea 0x80000000,%a1; copy…; clrl (BSS)`.

| Range | What | Notes |
|---|---|---|
| `~0x40000600`–`~0x401bxxxx` | program code (~1.9 MB) | Gate-F cleared |
| `~0x401bae00`–`~0x40260000` | read-only data | parameter table `0x401e29d0`; `LfoPageView` vtable `0x401ecf7c` |
| `~0x4026e000`–`0x402e2000` | padding runs | `LFO4` label written at `0x4026eff6` |
| `0x402e2000`–`0x40300000` | .data/BSS initializer | copied to `0x80000000` |
| `0x402f1980` | end of the loaded section | |
| `0x402e2000`–`0x464f47d0` | **main BSS, ~98 MB** | cleared at `0x400004b2`; sound slot table at `0x42aa6914` |
| `0x80000000`–`~0x8001e000` | fast SRAM (`.data` + small BSS) | cleared to `0x80008000` |
| `0x800003fc` | bootstrap runtime address | ELE3 dest `0x02000000` |

Located on 1.10E: `parameter_page_renderer` `0x40016f38`,
`is_lfo_param_modulatable` `0x400de34e` (hardcodes group ∈ {26,27,28}),
LFO-speed handler `0x40035f32`, `recovery_receive_loop` `0x80003e5a`,
`verify_and_flash_container` `0x80003c9c`.

## What the map settles

**Code caves are scarce, and the obvious space is a trap.** The trailing zeros
before the section end read as free but are the **.data/BSS initializer**,
copied to SDRAM at boot — overwriting them changes the program's initial RAM
state. The only safe space is the **unreferenced padding inside the constants
region**: ~29 KB on 1.11 in runs of ~1 KB. `dnfw cave scan` finds them per
image; `docs/code-caves.md` is the mechanism for using them.

**A new container section is not a route to more code space.** 1.11 added
section id 8 for the Outbox, which shows Elektron growing the *container* — but
a section with `dest 0` is loaded **data**, not code at a virtual address, and
the behavior that uses it lives in the recompiled MAIN OS. We cannot recompile
MAIN OS, so new behavior must be spliced into section 3 with code caves. Adding
or deleting container sections changes flash and file size, **not** the virtual
address space a fourth LFO needs. See `docs/ideas-backlog.md` for the variant of
this idea that *does* pay off (repurposing dead code inside section 3).

**The engine's state is in SDRAM, so the generator is too.** A parameter's live,
modulated value is read from `~+0x4f2e0` inside the per-track engine object in
SDRAM. Nothing in the image holds it. The LFO generator writes it on the
real-time modulation tick — the write-side code that remains the make-or-break
for a fourth LFO, and the reason it cannot be found by reading the image's data.

## Method note

The address-reference histogram over the raw image is **noisy** — scanning every
2-byte offset catches ColdFire opcode bytes (`0x4e`, `0x2f`, `0x48`…) as false
"addresses". The reliable sources are the **startup routine** (which names the
copy and clear boundaries outright) and **targeted cross-reference counts** for a
specific address, not a blind histogram. The parameter table was re-found on
1.11 the reliable way: locate the `SPD` string, find the pointer to it, and
subtract `id*60`.
