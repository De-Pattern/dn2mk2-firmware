# The MAIN OS memory map

Where the code, its constants, and its runtime state live in the ColdFire V4e
address space, reconstructed from the startup routine at `0x40000400` and the
cross-references. A visual explorer of this is an Artifact (link in the project
notes); this is the written record.

## The image versus runtime RAM — the distinction that matters

The MAIN OS section is loaded at `0x40000400` and holds **code, read-only data,
and the initializers for RAM** — it is not where the running firmware keeps its
mutable state. The startup code makes this explicit (disassembled at
`0x4000045c`): it copies a region of the image to external SDRAM and clears BSS
there before entering `main`.

```
lea 0x402e2000,%a2      ; source: the .data image, inside the section
lea 0x80000000,%a1      ; destination: external SDRAM
  movel %a2@+,%a1@       ; copy words until %a2 reaches 0x40300000
clrl %a0@+              ; then zero-fill BSS, up to 0x80008000
```

So **runtime data lives at `0x80000000`, not in the image.**

## The regions

| Range | What | Notes |
|---|---|---|
| `0x40000400`–`~0x40000600` | reset vector + C runtime bring-up | sets SR, memory controller, copies `.data`, clears BSS |
| `~0x40000600`–`~0x401bxxxx` | **program code** (~1.9 MB) | sequencer, UI, parameter framework, modulation subsystem, drivers; GCC + RTTI; Gate-F cleared |
| `~0x401bae00`–`~0x40260000` | **read-only data**: parameter tables, vtables, RTTI, string pool | the DN2 parameter table is `0x401e29d0` |
| `~0x4026e000`–`0x402e2000` | packed data records + **unreferenced ~1 KB padding runs** | the only genuinely free space (~75 KB total, in small runs) |
| `0x402e2000`–`0x40300000` | **`.data` / BSS initializer** | copied to `0x80000000` at boot — **not free space** |
| `0x402f1980` | end of the loaded MAIN OS section | |
| `0x80000000`–`~0x8001e000` | **runtime SDRAM**: `.data`, BSS | mutable globals and objects |
| inside the per-track object (`~+0x4f2e0`) | **engine modulation state** | the resolver reads modulated values here; the LFO generator writes them |
| above data/BSS | **heap and stack** | why appending a cave to the section end risks a heap collision |
| `0x800003fc` | **bootstrap** (recovery receiver), ELE3 dest `0x02000000` | see `docs/bootstrap.md` |
| `0x80000400` | updater section (id 4) dest | |
| `0xfc000000`–`0xfc0fffff` | **ColdFire peripherals** (MBAR): memory controller, chip selects, UART, timers | startup writes `0xfc008000`, `0xfc050014` |
| `0xfff00000`–`0xffffffff` | upper peripheral window | heavily referenced high MMIO |
| `0x00000000`–`~0x10000000` | **DSP / low region — unconfirmed** | the SHARC (`Digisharc`) synthesis side; the 833 KB blob may be its program or wavetables |

## What the map settles

**Code caves are scarce, and the obvious space is a trap.** The 64 KB of trailing
zeros from `0x402e1bf4` reads as free but is the **`.data`/BSS initializer** —
overwriting it changes the program's initial RAM state. The only safe space is
the **unreferenced padding inside the constants region** (`0x4026e…`); it holds
strings and small tables but not a whole page-view instance. The `LFO4` label
for the test firmware lives in one such run at `0x4026eff6`
(`docs/lfo4-feasibility.md`). A larger cave means either finding more padding or
growing the section, and a section-grow needs the heap boundary above pinned so
the new bytes do not collide with it.

**The engine's state is in SDRAM, so the generator is too.** A parameter's live,
modulated value is read from `~+0x4f2e0` inside the per-track engine object in the
`0x80000000` SDRAM. Nothing in the image holds it. The LFO generator writes it on
the real-time modulation tick — the write-side code that remains the make-or-break
for a fourth LFO. Its state being in SDRAM, not the image, is why it cannot be
found by reading the image's data and must be traced through the tick.

## Method note

The address-reference histogram over the raw image is **noisy** — scanning every
2-byte offset catches ColdFire opcode bytes (`0x4e`, `0x2f`, `0x48`…) as false
"addresses". The reliable sources are the **startup routine** (which names the
copy and clear boundaries outright) and **targeted cross-reference counts** for a
specific address, not a blind histogram.
