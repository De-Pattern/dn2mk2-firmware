# Waverider vs the stock machines on the DSP: a contract comparison (2026-09-27)

The question: what does a stock DN2 machine (WaveTone, FM Tone, FM Drum, Swarmer) do
on the SHARC+ that our type-5 code does not, such that our builds stop the DSP at the
first WAVERIDER trig and the stock machines do not.

Everything here is static, read from digikit's `tools/sharcdb.py` databases (run as a
tool, GPL-2.0, nothing copied), plus one runner check. **[M]** = measured (a query,
a decode, or a runner run). **[I]** = inferred. No Elektron bytes are quoted beyond
instruction encodings needed to name a form.

## Databases

`sharcdb` from m-dwyer/digikit `work/sharc-emulator` (`2cd02ee`), DB_VERSION 13, in a
detached worktree, WSL CPython 3.12 with networkx 3.4.2 installed to a side directory.

| image | section 7 sha256 | blocks | build |
|---|---|---|---|
| stock DN2 1.11 | `336e340a...` | known | 278 s (two builds in parallel) |
| DT2 1.16 | `0f514a12...` | known | 161 s |
| constpitch | `ac2c867d...` | **refused** without `--blocks` (sha unknown); built with the stock list `56,57,66,68,70,78,81,83` **plus 94, 95** (our reader and loop, `0x282dd600`, `0x282dda00`) | 269 s |
| M5d | `b13a1362...` | the same list | 255 s |
| m5c-nocall (D5a) | `5a42f7e9...` | the same list | 166 s |
| m5-nodir | `5ee78350...` | the same list (our blocks are 94, 95 at `0x28300000`, `0x28300400`) | 211 s |
| m5d-constpitch-callonly | | the same list | ~180 s |
| wtplace (below) | `fda474d0...` | the same list | 179 s |

`decomp` is empty for every SHARC image (it is Ghidra-only), so the contract below is
read from `insn`, `regdef`/`reguse`, `mem_access`, `ptr`, `dataref`, `edges` and `loops`.

## 1. The machine-render contract (stock) [M]

| routine | entry | frame | callee-saved registers it saves | L/B writes | MODE1 | loops |
|---|---|---|---|---|---|---|
| WaveTone render `0x1c6d4a` (CALL at `0x1c9611`) | R4 = voice state `+0x2408+0x30c t`, R8 = record `+0x9c`, R12 = track buffer, R9 pushed | `I7 = modify(I7, -14)` | R6, R7, R10, R11, R13, I15, ... | none | ALUSAT set `0x1c6d7c`, cleared `0x1c6e92`; SIMD on/off twice, balanced | 3 DO |
| WaveTone setup arm `0x1c91dc` | in the dispatch | none | n/a (arm) | none | none | none |
| setup callees `0x1c694a`, `0x1c6757`, `0x1c6c13` | R4 = state, R8 = I5 - 0x18c | -20 / 0 / -8 words | R3, R5-R7, R10, R11 / - / R10, R11, R13-R15 | none | none | none |
| FM Tone `0x1c54c7` + `0xb82728` | R4, R8, R12, R9 pushed | -26 / -14 | R3, R5, R7, R11, R13, R14 ... | none | none | 2 DO |
| FM Drum `0x1c778b` | same | -12 | R10, R11, R13-R15 | none | SIMD, balanced | 7 DO |
| Swarmer `0x1c85ad` | same | -12 | I14, I15, R11, R13-R15 | none | ALUSAT, balanced | 5 DO |

- **No DN2 machine render, setup routine, the dispatch `0x1c8ef1`, the chain call
  `0xb8251b` or the amp `0xb80345` writes any L or B register** (`regdef`, zero rows).
  The startup zeroes L0-L5 and L8-L15 and sets `L6 = L7 = 0x1fd`, `B7 = 0x26f000`,
  `I7 = 0x26f7f0` (sw `0x1c0eae..0x1c0ec0`).
- Every render is a C-ABI callee: it saves what it uses of R3, R5-R7, R9-R11,
  R13-R15, I0-I3, I5, I8-I11, I14, I15, returns with `I12 = DM(M7, I6)`,
  `JUMP (M14, I12) (DB)` and RFRAME.
- **What the dispatch does after each render returns.** Each arm pops its argument
  (`I7 = modify(I7, 2)` in the delay slot) and jumps back into its 16-track scan
  (`0x1c9407` for WaveTone). The live registers there are R15 (tracks left), R14
  (state pointer), R10 (stride), R11 (= 0 throughout the dispatch, sw `0x1c8f55`),
  R9 (block size), I3 and I5 (walkers), M3 (record stride), I6, I7, I9 (engine base).
- **After the splice point, sw `0x1c944c` onwards**, the dispatch reads R10 and I5
  (the two loads our entry JUMP displaced, re-executed by our code), R9, R11, I6, I7,
  I9 and M5-M7. **ASTAT is dead there**: the first conditional after `0x1c944c` is
  `JUMP IF NE` at `0x1c9461`, after `R15 = dec(R15)` at `0x1c9460`.

## 2. Our code against that contract [M]

Registers our code writes (`regdef` over our spans): constpitch `R0-R15, I0-I5, I12,
M0-M4, I7`; M5d the same; nodir the same plus LCNTR (nodir still carries M5's DO-loop
reader, which it never calls). Everything but I7 is saved at entry and restored before
`JUMP 0x1c944c`; I7 changes only inside the reader call and nets to zero.

| state | stock expectation at `0x1c944c` | ours | differs? |
|---|---|---|---|
| R0-R15, I0-I5, I12, M0-M4 | the dispatch's values | saved to `0x2dde00..0x2dde6c`, restored | no |
| I8-I11, I13-I15, M5-M15 | constants (M5 = 0, M6 = 1, M7 = -1, M14 = 1 ...) and walkers | never written | no |
| L0-L15, B0-B15 | L = 0 except L6/L7 | never written | no |
| MODE1/MODE2, IMASK, USTAT, PX, MRF/MRB, LCNTR | SISD, CBUFEN on | never written | no |
| PC, loop and status stacks | balanced | nothing pushed: CJUMP is a jump plus `R2 = I6, I6 = I7`, no DO loop, no PUSH | no |
| I6, I7 after the reader | the dispatch's | CJUMP at D7: `[D7] = D6`, `[D7-1] = ret-1`, I7 = D7-2; `I12 = DM(D7-1)`; RFRAME: I7 = D7, I6 = `[D7]` = D6 | no |
| ASTAT | dead | ALU and shifter flags changed | not observable |
| STKY | not read by engine code (only the context switch tests LSEM) | unchanged in constpitch | no |

The call and return are the firmware's own forms, byte for byte in form: call
`25a 18040016eb00`, slots `3c 9ff2` and `16a 9fc0...`; stock `25a 180400b809cb`,
`9ff2`, `9fc0...`. Return `3b 4dfe0e3f`, one instruction, `9b 83f343f` (RETURN), `21c`
NOP, `25c 1901` RFRAME. The stock corpus uses `83f343f` 942 times, with the slots
RFRAME+NOP (237) or a frame load + RFRAME (most of the rest); ours puts NOP first and
RFRAME second, a pairing not in the top of that census. The owner's constpitch-nocall
result (it skips the call) makes this moot.

A register write followed at once by an access through it (`I0 = R3; R4 = DM(0, I0)`
in the reader, `I1 = R2; R4 = DM(I1 + 0)` in the tail) is common in stock too: `move`
I-register -> next `15b` 13 times, `3b` 16 times, e.g. sw `0x1c3556` `I4 = R4` then
`DM(I4 + 30) = R8`.

**So the tail's architectural side effects are only its writes into our own region and
the (dead) flags.** Nothing it does is visible to stock code through registers. That
holds for the pitch block too (constpitch removes it and still stops). **[M]** for the
registers and memory forms, **[I]** that nothing else is architectural.

## 3. Who owns our memory [M, with limits]

| region | static owner found | evidence |
|---|---|---|
| block 1 tail `0x2dd600..0x2e7000` (byte, `0x28` alias, NW `0xb7580..`, SW `0x16eb00..`) | none | `mem_access`, `ptr` (address and base), `dataref`, `literals`: 0 rows. Loaded-word scan of every non-fill block: no byte, alias or NW hit; SW hits are code parcels |
| highest stock pointer into block 1 | `0x2dd488` + 20n | a 20-byte record table searched at sw `0xb8ecff`/`0xb8ee27`; the loaded data ends at `0x2dd52c` (8 records) |
| FreeRTOS heap (task stacks, TCBs) | **`0x2d08b8 .. 0x2dd0b0`** | heap init at sw `0xb89c53..0xb89c7d`: `ucHeap = 0x2d08b8`, `pxEnd = 0x2dd0b0 & ~7`, allocator state at `0x2dd0b8..0x2dd0e0` |
| system stack | `0x26f000..0x26f7f4` (block 0), circular, L7 = `0x1fd` words | sw `0x1c0eae..0x1c0ec0` |
| engine task | created at sw `0x1ca013` (`xTaskCreate` helper `0xb88839`): entry `0x1c9fe7`, stack `0x3e8` words, priority 5, so its stack is inside the heap | `roots` (`rtos_task`) |
| block 2 `0x300000..0x320000` | none (one literal `0x300000` is an AND mask) | as above |

**Answer to "is our span a stack or heap at run time":** no. The heap ends at
`0x2dd0b0`, stacks grow down inside it or in block 0, and our state and save area
(`0x2dde00..`, the counter at `0x2dde80`) are 3.4 KB above the heap's end. The reverse
holds too: none of our writes can reach the dispatch's frame. **Coverage limit:** a
pointer computed at run time (an index nothing bounds, a heap pointer walked past its
block, a DMA descriptor built from arguments) is not excluded. The `ptr` table holds
3,126 resolved accesses and 188 with an unknown address.

## 4. What the stuck tone does and does not say [M for the descriptors, I for the mode]

The SPORT output pages are built at sw `0x1ca167`: descriptor A at `0x2c0878`
(start `0x2c0478`, next `0x2c0894`) and descriptor B at `0x2c0894` (start `0x2c0578`,
next `0x2c0878`). **The descriptors point at each other.** The engine task writes the
page the DMA is not reading (`0x2c0478 + (DM(0x268a38) << R11)`, sw `0x1c9fc6`).

If the DMA runs that ring in descriptor-list mode (the FLOW field is not visible
statically; digikit finding 06 records the template CFG `0x00100000` as incomplete),
it replays the two pages **without the core**. Then **any** stop replays the last two
pages as a 750 Hz buzz: a task-level stall **and** a trap. A trap spins at
`0x1c07c6` (`EMU 0; JUMP 0x1c07c7`), entered from EMUI, PARI and ILOPI. So:

- a stuck tone means the core stopped while the pages held audio;
- silence means the pages held silence (or a DC word) when it stopped, or the core
  never stopped and the master is silent;
- **tone and silence do not separate a trap from a stall.** The "two faults" reading
  (trap in the pitch path, stall after it) is not supported by the output alone.

**No loop in the per-track chain can spin on sample data.** Downstream of the splice,
the only non-counted loop is the amp's envelope-segment loop (`0xb80345`, header
`0xb803c6`). Its exit tests the envelope level, not the samples. The filters are
counted DO loops. The coverage is static call edges plus the filter arms named in
`sharc-voice-path.md`. The runtime-filled table `0x8052dbc0` is not resolved.

## 5. Ranked differences

The static contract finds no difference in registers, stacks, frames, L/B, modes or
memory ownership. What is left is dynamic, ranked:

1. **When does a track's record first hold type 5?** [I, open, cheap to settle] The
   unpack stores it every frame, unconditionally, from the frame nibble (sw `0x1c2997`,
   in a delay slot). If the ColdFire sends 5 from **select**, the tail and reader ran
   for many blocks before the trig without harm, and the trig itself must be what
   changes. If it sends 5 only **once the track is trigged**, "dies at the first trig"
   is simply "dies on the tail's first run". Settle it with one ColdFire-emulator frame
   dump after MACHINE SEL -> WAVERIDER with no trig (ask DNX). Every reading below
   depends on it.
2. **A trap in the tail, not a stall** [I] consistent with the stuck tone (section 4).
   The tail's addresses do not depend on the data. The slot is bounded by the
   directory count (2), and the frame-copy offset depends only on t. So a
   data-dependent PARI or ILAD is excluded. An encoding the silicon rejects (ILOPI)
   would fire on the first run. That fits only rank 1's "type 5 at trig" branch, and
   constpitch's two rendered pages argue against it (the tail ran at least twice).
3. **Location** [I] Every dying build since m5c is block-1 layout. The one build whose
   tail never ran, nodir, is block-2 layout. **There is no build where the tail ran
   and survived, in either block.** The other agent's `exitmagic` separates "the tail
   runs" from "the location".
4. **An SHARC+ anomaly on the delayed indirect return** [I, weak]. Older SHARCs have an
   anomaly where RFRAME's `i6 = dm(0, i6)` fails after an indirect delayed branch
   through DAG2 registers, under IMDW conditions. The ADSP-2156x anomaly sheet could
   not be fetched from here. The owner's constpitch-nocall result (no call, still
   stops) takes it out of the way for now.

## 6. The discriminator: our reader in WaveTone's place

`00_Resources/02_Builds/waverider-disc-wtplace_DN2_1.11.syx`, sha256
`5a1a8a0e5131235cef569714377eaeda68374aba885babaacb1b832ddb92c8e6`; section 7
`fda474d041f1014a...` (876,492 bytes). Built by
`scripts/build_waverider_disc_wtplace.py` from `csrc/waverider/sharc/wt_place.asm`
(344 B). Section 3 is m5b's.

It is stock section 7 plus exactly:

- the WaveTone arm's `CALL 0x1c6d4a` at sw `0x1c9611` retargeted to `0x16ed00`;
- our block-1 region as M5d ships it, with a **C-ABI adapter** in the loop's span. It
  saves every R and I0-I5, fills one parameter block with constants (table 0 frame 0,
  the saw; note 60; POS 0; 32 samples; out = the call's R12, this track's buffer),
  calls `wr_render5`, restores, and returns in the firmware's shape.

It has **no lookup patch** (no track is ever type 5), **no entry JUMP** at `0x1c9448`
and no type-5 loop. A WaveTone track calls our code every block through the firmware's
own call and frame, and the chain after it is WaveTone's.

Gates:

| gate | result |
|---|---|
| decode (sharcdb, our blocks added) | the call decodes `25a CALL 0x16ed00`; the adapter is all `confident`; its return is `3b` + `14a` + `9b RETURN` + `21c` + `25c` |
| runner, `wtplace_check` (4 blocks, trig on block 1) | **PASS**: track 1 (WaveTone) machine tap == constpitch's type-5 tap, **0 mismatches of 128**, peak 0.993; tracks != 1 bit-identical to stock (tap and end of dispatch); with no WaveTone track all 16 buffers bit-identical to stock |
| strict memory map (same run) | **0** violations with the PC in our code |
| `test/test_waverider_dsp.py` | 12 passed, 5 skipped |
| `dnfw inspect` | all ok, HMAC reproduced |
| `dnfw diff` vs lookup-only | section 7 only: the lookup byte (back to stock), the 3-byte call target, our blocks (+39,536 bytes) |

**How to read it on the instrument** (new project; track 1 FM Tone, track 2 WaveTone;
play track 1, then trig track 2 on every step, as the m5c protocol):

| outcome | reads as |
|---|---|
| track 2 plays a **loud buzzy saw** at C4 (261.6 Hz), steady, whatever WAV/TBL say, and track 1 keeps playing | our block-1 code, our reader, its reads, and a trigged track carrying our signal through the chain are all fine on silicon. The fault needs **type 5**: the lookup, the splice at `0x1c9448`, the type-5 loop, or the stock code's handling of a type-5 track |
| a stuck **750 Hz** tone (or any tone that does not stop) | the core stops with our code running as a proper C callee on a stock WaveTone track: the reader, or executing and reading our block-1 region, is enough. The type-5 plumbing is exonerated |
| **silence** from the trig | the same as the stuck tone (section 4: the output ring replays whatever it last held) |

This is not a duplicate of the other agent's builds: all of those keep type 5 and the
splice.

## Notes for digikit

`docs/for-digikit-sharcdb-patched-images.md`.
