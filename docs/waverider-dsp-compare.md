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

## 7. wtplace fails on silicon; the layout, the caches and the next three builds (2026-09-27)

**The instrument (owner):** `waverider-disc-wtplace` gives the stuck tone at the first
WaveTone trig; only power-off stops it. There is no type 5 in it, so **the type-5
plumbing is cleared**: the lookup, the splice at `0x1c9448` and the loop.

### M5d's block-1 layout, and who touches what

| byte | what | pre-trig loop (every block) | trig path (tail / reader / wtplace) |
|---|---|---|---|
| `0x2dd600..0x2dd75c` (+ NOPs to `0x2dda00`) | reader code, 348 B | - | **fetched** (reader) |
| `0x2dda00..0x2ddd20` (+ NOPs to `0x2dde00`) | type-5 loop, 800 B (wtplace: the adapter, 344 B) | **fetched** (head, next, exit) | fetched (tail; the adapter) |
| `0x2dde00..0x2dde6c` | save area | 14a stores and loads | 14a |
| `0x2dde80`, `0x2dde84` | tracks left, this reader block | 14a | 14a |
| `0x2ddf00..0x2de100` | 16 reader blocks (wtplace: one parameter block) | - | **DAG** stores `DM(k, I4)` (tail); DAG loads (reader); 14a stores (adapter) |
| `0x2de200..0x2de404` | increment table | - | DAG loads `DM(0/1, I1)` (M5d pitch block; not constpitch) |
| `0x2de600..0x2de610` (zeros to `0x2df000`) | directory (scratch output at `0x2de800`) | - | 14a magic and count; **DAG** load of the table pointer `DM(0, I1)` |
| `0x2df000..0x2e3000` | table 0 | - | **DAG** loads `DM(0, I0)` (reader) |
| `0x2e3000..0x2e7000` | table 1 | - | (TBL1 1 only) |

The pre-trig loop only **fetches code from block 1 and makes 14a (absolute) data
accesses to block 1**. Every trig path that died adds **DAG (I-register) data
accesses to block 1 while executing from block 1**:

- constpitch-nocall: `DM(0, I1)` at `0x2de608`, and `DM(k, I4)` into the reader block;
- the reader: `DM(k, I4)` and `DM(0, I0)`;
- wtplace: the reader's accesses.

nodir, in block 2, made only 14a accesses to block 2. The pattern is **[M]**, read
from the listings. That it is the cause is **[I]**.

### The caches, from the primary source [M]

SHARC+ Core Programming Reference Rev 1.4 (May 2021, "includes ADSP-215xx"), chapter
32, `SHL1C_CFG` (Table 32-2):

| field | bits | DN2 writes | meaning |
|---|---|---|---|
| ICAEN, ICAINV | 0, 6 | `0x41` | I-cache on, invalidate |
| ICASIZ | 2:1 | 0 (`lshift(0, 1)`) | **0 = 128 Kbit = 16 KB** |
| DMCAEN, DMCAINV | 8, 14 | `0x4100` | DM cache on, invalidate |
| DMCASIZ | 10:9 | 0 (`lshift(0, 9)`) | **0 = 16 KB** |
| PMCAEN, PMCAINV | 16, 22 | `0x410000` | PM cache on, invalidate |
| PMCASIZ | 18:17 | 0 (`lshift(0, 17)`) | **0 = 16 KB** |

- The size codes are 0 = 128 Kbit, 1 = 256 Kbit, 2 = 512 Kbit, 3 = 1 Mbit.
- "L1 cache uses upper portion of the L1 memory block" (Tables 8-1 and 8-2, note 1).
  So the DM cache is `0x2ec000..0x2effff` and the PM cache is `0x31c000..0x31ffff`,
  as decoded before. **Our span is not cache.** The `-low` build was therefore not
  made.
- **No later write enlarges the caches.** The only `SHL1C_CFG` (`0x3e000`) writers
  are `0xb8b93a`, which calls sw `0x1c0272` twice with `R14 | old`, and a read at
  `0x1c07fb`. The other stock writes, at sw `0x1c00ab` and `0x1c016d`, go to
  `0x3e002`, the range-enable register (`SHL1C_CFG2`). They clear and set 2-bit
  range fields for the non-cacheable ranges `0x200fa000..0x200fdfff` and
  `0x28240000..0x2839ffff`.
- **The same chapter has the rule we break** (section 8, "Functional Description"):
  *"Usage of remaining L1 space may be impacted in the following ways: **Code
  segments should not be placed in block1 and block2 when data caches are enabled in
  those blocks.** During certain cache operations DMAs/system requests may be
  delayed."* DN2 enables both data caches. Stock DN2 places no code in block 1 or 2.
  Its code is in block 3, L2, and the IVT in block 0.
  - Every Waverider and ONESHOT build runs code from block 1 or block 2.
  - The mechanism is not documented. That "fetch from a data-cache block plus a
    DAG access to the same block" is what hangs is **[I]**, from the pattern above.

### The three builds

All three are `scripts/build_waverider_disc_wtplace.py --variant ...` with section 3
from m5b.

| build | sha256 | section 7 | one change against |
|---|---|---|---|
| `waverider-disc-wtplace-b0code_DN2_1.11.syx` | `7147ae53bea0fccbc9e3d9180d9c9845b997d1506a6597895e9fbc5e219b5dd8` | `b04b94d8...` | wtplace: the adapter and the reader are **code in L1 block 0** (byte `0x26f800` / `0x26fa00`, sw `0x137c00` / `0x137d00`, above the system stack `0x26f000..0x26f7f4`), and the CALL goes there. The data stays in block 1 (save area, parameter block, table 0), and so do the DAG accesses |
| `waverider-disc-wtplace-passthru_DN2_1.11.syx` | `ab618a3a50135ea91aa7d0130484546ad4843794a130ea39f2bd50f127dea3f9` | `b3589de1...` | wtplace: the adapter at the same block-1 address saves and restores the same registers with 14a accesses, then `JUMP 0x1c6d4a` (a tail jump into the stock WaveTone render, whose frame and arguments are untouched). No reader, no DAG access to block 1 |
| `waverider-disc-wtplace-b2_DN2_1.11.syx` | `e646bb877d10bde5637c90093ac90b8dcb4e63757a97ed57ba48ad0aaf0567a1` | `e3099a76...` | wtplace relocated to M5's block-2 addresses: reader `0x300000`, adapter `0x300400`, save area `0x301000`, parameter block `0x301100`, table 0 `0x302000`. Block 1 is stock |

The top of block 0 (`0x26f7f4..0x270000`) is unloaded in the stock stream.
`mem_access`, `ptr`, `dataref` and `literals` show no reference into it in byte,
alias, NW or SW form. The system stack is circular (`B7 = 0x26f000`, `L7 = 0x1fd`
words, ending at `0x26f7f4`), so I7 cannot leave it. **Limit:** as before, an address
computed at run time is not excluded.

**Gates** (`scripts/sharc_waverider_wtplace_check.py`, 4 blocks from post-init, trig
on block 1, strict memory map on):

| build | runner | strict, our PCs | decode (sharcdb, our blocks added) | `dnfw inspect` |
|---|---|---|---|---|
| b0code | **PASS**: track-1 tap == constpitch's, 0 / 128, peak 0.993; other tracks and no-WaveTone runs bit-identical to stock | 0 | CALL `0x137d00`; reader jumps re-resolved (`0x137ca6`, `0x137c41`); the adapter calls `0x137c00` | 21/21 ok |
| passthru | **PASS** (`stock`): all 16 machine taps and end-of-dispatch buffers bit-identical to stock, WaveTone trigged | 0 | CALL `0x16ed00`; `JUMP 0x1c6d4a` at `0x16ed84` | 21/21 ok |
| b2 | **PASS**: 0 / 128, peak 0.993; others bit-identical | 0 | CALL `0x180200`; reader `0x1800a6`, `0x180041`; the adapter calls `0x180000` | 21/21 ok |

`test/test_waverider_dsp.py`: 12 passed, 5 skipped. The SHARC type-5 gate does not
apply (no type 5).

**Reading them** (the same protocol as wtplace: track 1 FM Tone playing, track 2
WaveTone trigged on every step):

| build | a normal / saw sound | the stuck tone | silence |
|---|---|---|---|
| **b0code** | **saw at C4, and track 1 plays: code in block 1 was the fault.** The fix is to move all our code out of blocks 1 and 2 (block 0's top, or L2) and keep the data where it is | code location is not it: the reader's DAG accesses to block-1 data, or the reader itself | as the stuck tone |
| **passthru** | a normal WaveTone: fetching code from block 1 on a trig, with 14a accesses, is survivable, as the pre-trig loop already showed | even this dies: any trig-time execution from block 1 does | as the stuck tone |
| **b2** | a saw: block 2 is fine and block 1 is special. That contradicts the PRM rule as a sufficient cause, and points at block-1 run-time ownership instead | block 2 fails too once DAG accesses are made there: consistent with the PRM rule | as the stuck tone |

Suggested order: **b0code first**. If it plays, it is the fix's shape. passthru and b2
then say how general the rule is.

## 8. The reader halved, the encoding audit, and a breadcrumb channel (2026-09-27)

**The instrument (owner), restated:** `wtplace-b0code` and `wtplace-b2` die at the
first WaveTone trig, and `wtplace-passthru` survives with a normal WaveTone. So do
`m5-nodir`'s trigs. The difference between passthru and every build that died is
the **reader** (`reader_m5.asm`), plus the adapter's parameter-block fill and its
call, which passthru skips.

### The six builds

`scripts/build_waverider_disc_wtplace.py --variant rb-*`. Each is **`b2` with one
early exit**: block-2 layout (reader `0x300000`, adapter `0x300400`, save area
`0x301000`, parameter block `0x301100`, table 0 `0x302000`), block 1 stock, section 3
from m5b. Everything before the exit runs exactly as in `b2`. The exit is the full
path's own return shape. Nothing writes a sample, so track 2 stays silent.

| build | runs, in order | exit |
|---|---|---|
| `rb-params` | adapter: 22 saves (14a), the parameter block filled (14a stores to `0x301100..`), 22 restores | the adapter's own return; the reader is never called |
| `rb-callret` | + the `CJUMP` to the reader and its two stack pushes | at the reader's entry: `I12 = DM(M7, I6)`, NOP, `JUMP (M14, I12) (DB)`, NOP, RFRAME |
| `rb-loads` | + `I4 = R4`, the six parameter loads `DM(k, I4)` from block 2, `I2 = R0` | the same inline return (still no DAG store) |
| `rb-setup` | + the frame-row arithmetic and the two row stores `DM(6/7, I4)`, the constants, the count test, the first tap address and the first `I0 = R3` | `JUMP wr5_done`: the full return, with the phase store `DM(1, I4) = R9` |
| `rb-oneread` | + the first table read `R4 = DM(0, I0)` (block 2, table 0) | `JUMP wr5_done` |
| `rb-noout` | the full render: 32 samples, all table reads, the count stores, the arithmetic | the full return; the output store `DM(I2, M6) = F4` is a NOP |
| (`wtplace-b2`) | the full render **with** the output store to the track buffer | **died on silicon** |

`rb-loads` is one more cut than asked for. It splits "DAG loads from our data" from
"DAG stores to it", which the `(iii)` cut would otherwise lump together.

| build | sha256 (.syx) | section 7 sha256 |
|---|---|---|
| `waverider-disc-rb-params_DN2_1.11.syx` | `19b61bcd6798940d02fdf0c5cb8b3772483e796a54d4bf5f1253fb5c3070c950` | `1c9fe24fe02404d8...` |
| `waverider-disc-rb-callret_DN2_1.11.syx` | `a4eb709e567e316b219907cf149eeaf9bbcb6c3292d4446356855ad7748b0ae8` | `6087d9ea5a2eeac8...` |
| `waverider-disc-rb-loads_DN2_1.11.syx` | `5ff785c46d2b4c40f464e2a2481f76231357db20439490218cc5b12a35a95012` | `efc2bc914ad51d2b...` |
| `waverider-disc-rb-setup_DN2_1.11.syx` | `f036f2bcc679e92441201cbc8e262edba4624f4d35c6d57ba179ed408bce08a7` | `540e9db6ceb0ec37...` |
| `waverider-disc-rb-oneread_DN2_1.11.syx` | `1ff9988e0e1dba7afadad64b427379a24d1452b11f61fb457b05a250f911b824` | `a2b8f5008047fe1b...` |
| `waverider-disc-rb-noout_DN2_1.11.syx` | `3337a7ccc47c08081e4cf74e479aa586a0531e791f1590129b78cfb47f7916e3` | `fa392d700348f326...` |

Gates, all six **[M]**:

| gate | result |
|---|---|
| `sharc_waverider_wtplace_check.py S7 silent` (4 blocks, trig on block 1) | **PASS** for each: track-1 tap 0 nonzero samples of 128; tracks != 1 bit-identical to stock (tap and end-of-dispatch buffers); no-WaveTone run bit-identical to stock |
| strict memory map, same run | **0** violations with the PC in our code, for each |
| sharcdb decode (DB per build, blocks `...,94,95`) | every decode `confident`; every branch and pushed return address lands on an instruction of our code (`JUMP 0x1800a9` = `wr5_done` in setup and oneread; the CALL to `0x180000`; the return to `0x180264`) |
| `sharc_encoding_audit.py` | 0 instructions whose opcode stock never uses (below) |
| `dnfw inspect` | 21/21 ok, HMAC reproduced, for each |
| `test/test_waverider_dsp.py` | 12 passed, 5 skipped |

The `silent` mode is new in the wtplace check. A -0.0 sample counts as silence:
the chain multiplies the untouched buffer and leaves -0.0 there, and 24 blocks in
the runner stay at exactly 0 **[M]**.

### Reading them on the instrument

Use the same protocol as for wtplace: a new project, track 1 FM Tone playing a
pattern, track 2 WaveTone trigged on every step, then listen for 4 bars.

| what you hear | reads as |
|---|---|
| **track 1 keeps playing, and track 2 is silent from the start** (before and after its trigs, since these builds never render a sample). The sequencer and the UI respond as normal | **survived**: everything this build runs is fine on silicon |
| the stuck 750 Hz tone, or **all** audio stops (track 1 too), at track 2's first trig; only power-off clears it | **died**: the fault is in what this build adds over the last survivor |

Track 2's silence is expected in every rb build. The signal is **track 1**: if it
stops, the build died.

### Flash order: halve the suspects

The suspects are ordered along the path: params < callret < loads < setup < oneread
< noout < (b2: output store). Assume a build that runs more than a dead build also
dies. Then:

1. **`rb-setup` first.**
   - Survives: the fault is the table read, the loop, or the output store. Go to 2a.
   - Dies: the fault is at or before the setup. Go to 2b.
2. a. **`rb-noout`**. Survives: the **output store** `DM(I2, M6) = F4` to the track
      buffer, alone. Dies: then flash `rb-oneread`, which splits the first table
      read from the loop.
   b. **`rb-callret`**. Survives: flash `rb-loads`, which splits the DAG loads and the
      R-to-I moves from the row and phase stores. Dies: flash `rb-params`, which
      splits the 14a parameter stores from the CJUMP and return.

Three flashes at most settle it to one step, two if 2a's first answer is "survives".

### The encoding audit [M, against the PRM]

`scripts/sharc_encoding_audit.py STOCK.sqlite B2.sqlite 180000-1800ae 180200-1802ac`
reads all 149 instructions of the b2 reader and adapter, against the 40,000-odd
aligned stock DN2 1.11 instructions in functions:

- **119** have an encoding (raw) stock never uses. That is expected: the addresses
  and immediates are ours.
- **41** have a form-plus-register combination stock never uses:
  - 23 `2a_short` computes, 11 `2c` computes, 5 `5b` moves, one `15b` and one `3c`.
- **0** have an opcode stock never uses. The opcode here is the form plus the
  mnemonic, with the data registers masked and the I/M registers kept.
  - Every unseen shape is a stock operation with other data registers. For
    example, `R4 = ashift(R4, R12)` has 7 stock uses of `2a_short ashift` by
    register, and `R7 = DM(I0 + 0)` has 31 stock uses of `15b` through I0.

The operand checks against the SHARC+ Core Programming Reference (Rev 1.4):

- **The universal-register moves into I registers are encoded correctly.**
  - The PRM's Figure 13-15 gives the field order of a 32-bit Type 5b move:
    `01110`, srcureghigh[4:0], cond[4:0] and srcureglow[1] in the first parcel, then
    srcureglow[0], dstureg[6:0] and seven fixed bits.
  - Read as bits 47:43, 42:38, 37:33, 32 | 31, 29:23, that layout decodes all
    3,192 stock 5b moves consistently with their meaning. Examples: `MODE1 = R0`
    at startup, `I4 = R4` pointer moves, `R2 = I5` saves. It also leaves bit 30 = 0
    and bits 22:16 = `0111111` in every one of them.
  - Under the PRM's UREG code table (Chapter 26), `703f883f` is src `0000011` =
    **R3**, dst `0010000` = **I0**, cond `11111`. `703e093f` is src `0000000` =
    **R0**, dst `0010010` = **I2**.
  - Both encodings are new only as a combination. Stock uses our source code R3 in
    those bit positions 6 times (`M2 = R3` is `703f913f`), our destination code I0
    32 times (`I0 = I13` is `71fe883f`, the same second parcel as ours), R0 34 times
    and I2 25 times. `I0 = Rn` itself occurs once (sw `0xb8ac10`). The R-to-I moves
    with an odd source register, which set srclow[0] in bit 31, occur 59 times.
  - **Verdict: no encoding error.** Our emulator and decoders share selache's and
    digikit's tables, and that path could hide a table error, so the check does not
    rest on them. It rests on the PRM's code table and on the stock corpus, whose
    fields sit where Figure 13-15 puts them.
- **`FLOAT Rx BY Ry`**, which digikit marks `!!GAP!!` as a task-flagged opcode. It is
  ALU opcode `11011010` = `0xDA`, `Fn = float Rx by Ry` (PRM Table 17-5), and stock
  uses it 41 times in `2a_short`. `LSHIFT/ASHIFT Rx BY Ry` are shifter opcodes
  `0x00`/`0x04` (Table 17-9). `min` is ALU `0x61`.
- **`2c` parcels 0xc000..0xc07f** (our `c018`, `R1 = R1 + R8`). This is the range
  runner gap G5 is about, because the Type 2b first parcel starts with the same
  bits (Figure 13-4). Stock has 43 `2c` parcels in exactly this range (`c02d`,
  `c010`, ...), and they run on silicon, so the silicon reads them as 16-bit. Ours
  is the same case. **[I, strong]**
- **17b immediates** (`R2 = 0xfff0` for -16, `R15 = 0xffe9`, `R8 = 0xfff1`): the
  PRM's `imm16visa` type is `-0x8000:0x7fff`, so they are sign-extended. They are
  used only as shift and scale counts.

The access list **[M, from the decode]**:

| question | ours |
|---|---|
| DAG1 vs DAG2 | data accesses only through DAG1: I0, I2, I4 (`15b` and `3c`), and I6/I7 (the stack and frame). DAG2 only in the stock return idiom: `I12 = DM(M7, I6)` loads I12, then `JUMP (M14, I12)` |
| PM-bus data accesses | **none** (`g = 0` on every `14a`, `15b`, `3b`, `3c`, `16a`) |
| I/M pairings stock never uses | **none**. `DM(I2, M6)` occurs 14 times in stock, `DM(I7, M7)` more than 1,500, and `DM(M7, I6)` 653 |
| long word, byte or short word modifiers | **none** (`l = 0`; no `bw`/`sw`). Our I registers hold **byte-space** addresses (`0x301100`, `0x302000..`), and so do stock's: 317 stock `15b` accesses resolve to byte-space L1 bases, e.g. `R12 = DM(I4 + 9)` with I4 = `0x241190` reads `0x2411b4`. The offsets are scaled by 4, as ours need |
| writes to B/L, I8-I15 (other than I12), M8-M15, USTAT, MODE1/2 | **none**. I12 is written only by the stock return idiom. I6 and I7 change only through the CJUMP, the pushes and RFRAME, and net to zero |

**So the reader contains no instruction whose operation, addressing mode or register
class is foreign to the stock image.** The fault is not an encoding. What is left is
what the instructions **do**: which memory they touch and when. The halving builds
measure that.

### Breadcrumbs: where the DSP already talks back to the ColdFire [M static, I for the transport]

The ColdFire's DSPI2 driver receives 2,748 bytes per frame into `0x800053a4`
(digikit 04). The DSP side of that link, in stock DN2 1.11:

- **Link setup, sw `0x1ca46a`** (called with R4 = `0xabc` at sw `0x1ca812`). It builds
  two descriptor rings of two descriptors each, with CFG `0x100000` and XMOD 2 (16-bit
  elements); the element counts it writes are `0xabc >> 1` = `0x55e`:
  - ring 1: `0x2c2960 <-> 0x2c297c`, buffers `0x2c39d0` / `0x2c29d0`;
  - ring 2: `0x2c2998 <-> 0x2c29b4`, buffers `0x2c59d0` / `0x2c49d0`.
- **Per-frame handler, sw `0x1c9d6b`.** It calls `0x1ca020`, which returns
  `p1 = 0x2c29d0 + (DM(0x2c0450) << 12)` and `p2 = 0x2c49d0 + (DM(0x2c0450) << 12)`;
  `0x1ca04a` toggles the page. The handler:
  - reads the command word at `p1` and dispatches through the table `0x268a68`,
    so **ring 1 is receive**;
  - and last, **writes one word into `p2 + 0`**: the handler's EMUCLK cycle count,
    halves swapped (`R2 = (d << 16) | (d >> 16)`, sw `0x1c9e4c..0x1c9e62`). So
    **ring 2 is the reply** the ColdFire receives at `0x800053a4`. The swap would
    put the 32-bit value in natural order for a big-endian reader of MSB-first
    16-bit halves **[I]**.
- **A heartbeat that needs no DSP change.** Reply word 0 changes every frame while
  the DSP runs. If the core stops, the TX ring keeps replaying its two pages
  without the core (descriptor-list mode, as the SPORT ring does in section 4), so
  word 0 **freezes at two alternating values**.
  - A local USB read of `0x800053a4` repeated after a stall separates "core
    stopped" (frozen) from "core running, silent" (changing). No DSP change is
    needed.
  - This is **[I]**: the transport is inferred from the descriptors, and the
    ColdFire side may slip frames (digikit's two-frame DMA slip).

**The stage-marker design (design only, not built):**

1. **Choose K**, a reply offset that nothing uses.
   - It must be written by no DSP handler case. The frame is 2,748 bytes and each
     page is 4 KB, so only offsets below `0xabc` travel.
   - It must be read by no ColdFire code. `0x800053c0` (K = `0x1c`) **is** read, by
     `0x40025e0a`.
   - Check both statically before use: the ColdFire readers of `0x800053a4 + K` in
     MAIN OS (DNX/Ghidra), and the DSP stores into `0x2c49d0..0x2c69d0`.
   - Candidate: the last word, K = `0xab8`. It must be checked against DT2's use of
     the reply tail (play positions at `2(0x54e + t)`, docs/dt2-machine-port.md). If
     DN2 has the same shape, that tail is taken, and a word just below
     `2 * 0x54e = 0xa9c` is the next candidate.
2. **Write the marker to both TX pages** with 14a absolute stores, the only access
   form passthru and nodir proved survivable: `DM(0x2c49d0 + K) = Rs;
   DM(0x2c59d0 + K) = Rs;`. It must go to both pages, because which page the DMA
   replays at the stall is not known.
   - Rs holds `0x5752` ("WR") in one half and a stage number in the other, halves
     swapped as the handler does for word 0.
   - Use a scratch register that is saved already; the adapter saves R0-R15.
3. **Stages:**

   | stage | where |
   |---|---|
   | 1 | adapter entry |
   | 2 | before the CJUMP |
   | 3 | reader entry |
   | 4 | after the parameter loads |
   | 5 | after the row stores |
   | 6 | after the first `I0 = R3` |
   | 7 | after the first table read |
   | 8 + (n << 8) | loop iteration n |
   | 9 | before the output store |
   | 10 | after the reader returns |
   | 11 | before the adapter returns |

   Each marker costs two 14a stores, about 2 cycles, so they perturb nothing that
   matters.
4. **Read back after the stall** with a local USB read of `0x800053a4 + K` on the
   ColdFire. Take two or three reads a frame apart: the marker should be stable, and
   word 0 frozen. The last stage written is where the core stopped.
   - **Control:** run the same build without a stall, for example with the WaveTone
     track muted before the trig. The marker must then read 11 and word 0 must keep
     changing. Without that control, a frozen or absent marker could simply mean the
     channel is not wired.
5. **Caveat.** Unless the ColdFire copies the reply into state, the DSP's next frame
   overwrites K with whatever the handler case writes there. That is why K must be
   one no case writes. Every write to the TX pages outside the handler's own stores
   is **[I]** until step 1's checks are done.

## 9. rb-setup died, rb-loads survived: the setup span split, and the parcel widths (2026-09-27)

**The instrument (owner), restated:**

- `rb-callret` survives: track 1 keeps playing.
- `rb-loads` survives.
- `rb-setup` dies: the whole device goes silent once track 2 plays.

So the fault is in what `rb-setup` runs after the parameter loads.

### The builds (`--variant rb-setup-*`, each exits through `JUMP wr5_done`, the full return)

| build | runs after rb-loads' span | sha256 (.syx) |
|---|---|---|
| `rb-setup-a` | the frame rows (`lshift`, `R2 = 1`, add, `R2 = 15`, `min`, two `lshift`, add), `DM(6, I4) = R0`, **`c018`** (`R1 = R1 + R8`, 2c), `DM(7, I4) = R1` | `7c5e535ceb4b51719a039c635b6b04886949377ec28414ca6e3e841a444c6175` |
| `rb-setup-a2` | as a, with that add written `R1 = R8 + R1`: selas emits `2a_short` `01801181` (32-bit) and no 16-bit parcel | `f0f42de15aca5c5e162cfeef30a2de04db939035f134a880b4a14662def2e4e1` |
| `rb-setup-b` | a + `R3 = 0xffff`, `R3 = R11 AND R3`, `R2 = -16`, `F11 = FLOAT R3 BY R2` | `c16a5adb9be4e9f5e339420d3e28b086c12cf3748d01cb67ceda5d5f485d7434` |
| `rb-setup-c` | b + `R13`, `R14`, `R15`, `R8` constants, `R12 = PASS R12`, `IF EQ JUMP` (8a abs, not taken), `R12 = -16` | `b6a66813f2c52d06aae5270a2c5ada8fda10ed12a9f3a762f990571fa45976d3` |
| `rb-setup-d` | c + the first tap address (four shifts, `R1 = R9 + R13`, `R2 = DM(6, I4)`, `R3 = R2 + R0`), stopping before `I0 = R3` | `8099e148f9cca349f12bc425afe87bd0518dc604f55e283e77e12e6eebe25fd3` |
| (`rb-setup`, died) | d + `I0 = R3` | |

Every one of these also makes the full return's phase store `DM(1, I4) = R9`, as `rb-setup` does.

**Gates [M], all five pass:**

- wtplace check `silent`: 0 nonzero samples of 128 on track 1; the other tracks and the no-WaveTone run bit-identical to stock.
- Strict memory: 0 violations with the PC in our code.
- sharcdb decode: all confident, every branch on an instruction boundary.
- Encoding audit: 0 opcodes that stock never uses.
- `dnfw inspect`: 21/21 ok, HMAC reproduced.
- Each .syx's section 7 is byte-identical to the gated one.

**Flash order:**

1. `rb-setup-a`.
   - **Dies:** flash `rb-setup-a2`.
     - a2 survives: the 16-bit parcel `c018` is the fault.
     - a2 dies: the fault is the row arithmetic or the DAG stores (`DM(6/7, I4)`, and the phase store `DM(1, I4)`), and the next cut is stores vs arithmetic.
   - **Survives:** flash `rb-setup-c`.
     - c dies: flash `b`. b survives: the fault is c's constants, PASS, JUMP or `R12`. b dies: it is b's AND or FLOAT BY.
     - c survives: flash `d`. d survives: the fault is **`I0 = R3`**. d dies: it is the tap-address block.

The readout is as in section 8. Track 1 must keep playing; track 2 is silent in every rb build.

### Instruction widths, from the PRM and not the tools [M for the PRM reading, I for the silicon]

**The PRM states no width rule.** Chapter 12 says only that VISA types are a = 48, b = 32, c = 16 bits.

So I extracted every opcode figure's fixed (grey) bits from the PDF with PyMuPDF, 51 figures (scratchpad `prmimg/figs.py`). For each of our 16-bit parcels I then listed the types whose first-parcel fixed bits it matches. Our 16-bit parcels:

- 2c: `c018`, `c2cc`, `cc32`, `c123`, `c954`, `c845`, `c976`, `c867`, `c964`, `c846`, `c09a`, `c101`, `c188`;
- 3c: `95b4`, `9ff2`;
- NOP: `0001`;
- RFRAME: `1901`.

Three overlaps exist in the PRM's own figures:

| parcel | 16-bit reading | the other figure it matches | ours |
|---|---|---|---|
| `0xc000..0xc07f` | 2c `Rn = Rn + Rx`, Rn in R0-R7 (ShortCompute opcode `0000`, Figure 17-2) | **Type 2b first parcel** `110000000` + compute[22:16] (Figure 13-4): a **32-bit** instruction | **`c018`** (in rb-setup's span) |
| `0xc080..0xc0ff`, `0xc180..0xc1ff` | 2c add/sub with Rn in R8-R15 | Type 11c `1100000x 1...` (Figure 14-6), a 16-bit conditional RTS/RTI | `c09a` (loop only), `c188` (adapter; ran in rb-params, which survived) |
| `0x0001` | 21c NOP | 22c `000000000.000001` | the return's NOP; 658 stock uses |

**The figures are not authoritative.**

- **11c:** the figure's grey `1100000` prefix is contradicted by all 12 stock 11c returns, which are `0x0abe`, `0x0afe` and `0x0bfe` (`0000101x 1...`, 11a's prefix).
- **2a:** the figure shows `001`, where the 3,278 stock `2a_short` and the 48-bit 2a start `00000001`.
- **25c:** the figure repeats 25a's first parcel; RFRAME is `0x1901`, used 983 times in stock.

So a figure's grey bits can be copy errors.

**The firmware is.** ADI's toolchain built stock, and stock has 16-bit 2c parcels in every overlap range, inside reached functions:

- 43 in `0xc000..0xc07f`. One is `c029` at sw `0x1c4f4a` on the WaveTone voice path, whose following code is coherent only if it is 16-bit (runner gap G5, docs/waverider-feasibility.md).
- 35 in `0xc080..0xc0ff`.
- 3 in `0xc180..0xc1ff`.

No in-function stock instruction is a confirmed Type 2b. The two sharcdb calls 2b (`0x1c0e13`, `0x1c4f4a`) are the G5 misreads.

**Verdict:**

- **[M]:** the PRM leaves `0xc000..0xc07f` ambiguous (2b and 2c).
- **[I, strong]:** the silicon reads it as 16-bit, as it does in stock's WaveTone every block. That makes `c018` an unlikely cause, but not an excluded one.
- **`rb-setup-a2` measures it.** If a dies and a2 survives, the silicon reads `c018` as a 32-bit 2b. Then the next parcel `0x9908` is taken as compute[15:0], `0x0087` starts a 48-bit Type 22a, and the stream is desynchronised. That would explain everything, and the fix would be to never emit `0xc000..0xc07f`.
- No other parcel of ours has an ambiguous width. `c09a` and `c188` overlap only the wrong 11c figure, and both readings of them are 16-bit.
