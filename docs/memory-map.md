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

## Where each mod lives — measured 2026-09-17

`scripts/memory_map.py` diffs every current build against stock 1.11 and
attributes each changed run to a cave, an in-place edit, the appended area, or
(from the build scripts' constants) RAM above BSS. Output
`out/memory-map/map.json`; published as a visual map for the owner.

| | |
|---|---|
| zero runs ≥32 B in `0x4026e000`–`0x402e2000` | 217 runs, 33,125 B |
| **clean** runs (pass the stride and reference checks) | **70 runs, 7,065 B**; only three are large: `0x402cf52c`, `0x402d0664`, `0x402dfa1c`, 896 B each |
| RAM above BSS (`0x466b74d0`–`0x48000000`) | 25.3 MB, mods use 80 KB — 57 KB of it step 4b's two relocated tables |

| mod | caves | in-place edits | appended | RAM |
|---|---|---|---|---|
| `lfo4-tick6a` | 210 B at `0x402dfa1c` | 137 B, 33 sites | — | 12,288 B at `0x46700000` |
| `lfo-waveshapes8` | 668 B `0x402cf52c` + 746 B `0x402d0664` | 83 B, 26 sites | — | 8,192 B NOI state + 336 B glyph tiles |
| `lfo-wavetable4` | 676 B + 560 B, same two caves | 80 B, 25 sites | — | glyph tile |
| `arp-on-midi2` | — | 4 B, 1 site | — | — |
| `bootscreen-bang` | 200 B at `0x402dfa1c` | 15 B, 2 sites | 2,092 B | 2,056 B at `0x46710000` |
| `c-hello` (LFO4 step 0) | loader 132 B at `0x4028da70` (cave `0x4028da6e`, 138 B) | 16 B, 2 sites (startup calls, `memcpy` entry) | 164 B `CODE` chunk | 156 B at `0x46800000` -- **LFO4's code region** |
| `lfo4-ext` (LFO4 step 1) | the same loader, 132 B at `0x4028da70` | 24 B, 3 sites (startup calls, `memcpy` and `memset` entries) | 1,564 B `CODE` chunk | 7,732 B at `0x46800000` — 1,548 B of code, then the 5,120-byte table and its counters |
| `lfo4-bridge` (step 3) | 376 B: the loader plus 246 B of engine stubs at `0x402dfa1c` | 174 B, 38 sites | 2,304 B `CODE` chunk | at `0x46800000` |
| `lfo4-slots` (step 4a) | the same 376 B | 180 B, 39 sites | 2,304 B | at `0x46800000` |
| `lfo4-table` (step 4b, part 1) | the same 376 B | **483 B, 156 sites** — 117 of them the relocated table's bases and bounds | 22,140 B in **two** `CODE` chunks | 57,124 B: 29,124 B at `0x46800000` (code, the extension table, and the 22,508-byte runtime parameter table) and 19,808 B at `0x46900000` (the 330 parameter records) |
| `lfo4-page` (step 4b, part 2) | the same 376 B | 495 B, 158 sites | 22,484 B | the same 57,124 B |
| `intro-tunnel` | — | 2 B, 2 sites | — | — |
| `intro-stamp` | 184 B at `0x402dfa1c` | 8 B, 1 site | — | — |

**Conflicts today:** the two LFO waveform builds share both caves and every hook;
`lfo4-tick6a`, `bootscreen-bang` and `intro-stamp` share `0x402dfa1c`. **Clean
caves are the scarce resource; the appended area (proven by `intro-bang`) and
RAM above BSS are not.** The mix-and-match registry (backlog §11) must allocate
caves and RAM, not just check hooks.

