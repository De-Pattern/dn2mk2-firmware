# Waverider M5 and ONESHOT: the whole DN2 goes silent (2026-09-27)

**What the instrument did (owner, 2026-09-27):**

- `waverider-m5_DN2_1.11.syx`: boots, UI works, no track of any machine makes a
  sound, in any project. Not tested: whether it played before WAVERIDER was selected.
- `waverider-m5-cfonly_DN2_1.11.syx` (M5's section 3, **stock** section 7): every
  other machine plays before and after WAVERIDER is selected. **The fault needs our
  section 7.**
- `oneshot_DN2_1.11.syx`: ONESHOT selects, its page shows, all tracks play **until
  the ONESHOT track is trigged**; from then on every track is silent. ONESHOT never
  sounds.

This is an offline investigation. **No single cause is proven.** Below: what the
evidence rules out, what is still open (ranked), and two discriminator builds that
split the open cases on the instrument.

## What ONESHOT's hardware result proves, and what it does not

ONESHOT uses the same entry (`JUMP` at sw `0x1c9448`) and puts code and data in L1
block 2 (adapter sw `0x185800` = byte `0x30b000`, save area DM `0x30c000`, records
`0x30e000`, bank `0x310000..0x317df8`). Every block, before any trig, its
pass-through runs on silicon without harm:

- the entry `JUMP` (48-bit `8a_abs`, then the firmware's 16-bit NOP) and the return
  `JUMP 0x1c944c`;
- **VISA code fetched from block 2** (byte `0x30b000..`, sw `0x185800..`);
- Type 14a absolute stores and loads at `0x30c000..0x30c0a0`, Type 15b `DM(0, I4)`
  reads of stock records, `COMP` and `IF NE JUMP` into block 2 and back.

So **suspect 2 (block 2 cannot hold code, or needs another address form) is ruled
out** for that range. The sw and byte forms we wrote map to what the silicon fetches.

What it does **not** prove:

- **That the bank magic at `0x310800` read back correctly.** If it did not, ONESHOT's
  loop skips all type-5 work and "never sounds" follows by itself. The trig-kill
  would then have to come from somewhere else.
- **That ONESHOT's silence comes from section 7 at all.** There is no ONESHOT
  cfonly control. ONESHOT's ColdFire half differs from M5's, and a trig is where
  it does something new. The M5 cfonly result covers M5, not ONESHOT.
  (*Run a control beside a negative.*)

## The boot stream (suspect 5): ruled out as the cause

`dnfw ldr` on the M5 build: 102 blocks, the walk ends exactly at the section end
(`0xd504c`). Our 7 blocks sit between the stock stream's last block and its `final`
block, and each carries a valid header checksum. The stock `FIRST` block's
argument (`0xc9bd8`, the DXE's size) is left at the stock value, which the ONESHOT
stream does too, and ONESHOT boots and runs from block 2. The same holds for the
ONESHOT build (104 blocks, including its zero-`FILL` at `0x30e000`). **Within
block 2, no stock block of either stream, loaded or filled, overlaps our spans.**
The ColdFire's uploader mallocs 1 MB for the image. Section 7 is 872,524 bytes, so
it fits.

## What a static scan of block 2 now shows (suspect 1)

**The claim "L1 block 2 is free" (`waverider-m5-dsp.md`, correction 1) is
superseded here.** It was "free by every static test", and the tests were right
about the image. They missed the part itself:

- ADI's ADSP-2156x material states that **the PM data cache is attached to L1
  block 2**, and the I-cache to block 3. Each cache is configurable from 0 to
  128 KB, and at 128 KB the whole of block 2 is cache. Sources:
  [EngineerZone, *Cache Examples for ADSP-2156x*](https://ez.analog.com/dsp/sharc-processors/adsp-2156x/w/documents/15757/cache-examples-for-adsp-2156x);
  the [ADSP-2156x datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/adsp-21562-21563-21565-21566-21567-21569.pdf)
  ("up to 1 Mb ... for DM, PM, and instruction cache each"). The page text was
  read through a search index, not from the PDFs; the HRM chapter was not
  reachable from here. **[D]**
- The stock image leaves **block 2 entirely empty**: no loaded byte and no fill.
  It is the only one of the four L1 blocks the stream never touches, while block 0
  is packed to its last 4 KB. That is what a block reserved for a cache looks like.
  It does not prove the block is reserved.
- The startup cache routine sw `0xb8b93a` builds `SHL1C_CFG` (MMR `0x3e000`) from
  **three enable patterns**, one per cache: `0x41`, `0x4100` and `0x410000`. It ORs
  in size fields computed from link-time constants: `lshift ... by 1`, `by 9`,
  `by 0x11`. It then writes non-cacheable ranges `0x200fa000..0x200fdfff` and
  `0x28240000..0x2839ffff`. The M5 doc read only the `0x4100` constant. **Which of
  the three enables are set at run time, and what size the PM cache gets, was not
  settled here**: they depend on the routine's arguments, which come from the
  startup path. That path is the next static target, and a runner run of
  `0xb8b93a` from the real startup state would settle it.
- No loaded data word names block 2 in byte, normal-word (`0xc0000..`) or
  short-word (`0x180000..`) form in L1 block 0/1 data. The L2 and DDR hits are
  instruction parcels or int16 table pairs, which agrees with correction 1.
- The runtime meminit (sw `0x1c0efe`, table-driven copy and zero-fill loops, run
  from `__start` at sw `0x1c0e70`) was located but its table was not decoded. It
  would show up as a zero-fill of block 2 only if its table named block 2, and no
  data word does.
- Free L2 above the image (`0x20088240..`) **is not free**: data words point to
  `0x200918c0`, `0x200c0008` and `0x200c1f84`. Do not relocate there.

**Why a PM cache in block 2 is the leading suspect, and where it falls short.** If
the PM cache owns part of block 2, then after it is enabled that SRAM is the
cache's data array. Our boot-loaded bytes there are not guaranteed to survive, and
**our writes into it corrupt cached external PM data**, which can crash the
firmware. That fits both builds only if the cache covers our *data* but not
ONESHOT's pass-through at `0x30b000..0x30c0a0`, for example a 64 KB cache at the
block's top, `0x310000..0x31ffff`. That range holds ONESHOT's bank and magic, and
none of M5's spans (M5 ends at `0x30a000`). So a top-carved cache explains ONESHOT
"never sounding", but **not M5's silence**. Neither explains ONESHOT's trig-kill.
It stays a suspect, not the answer.

## Instruction forms (suspect 3): checked, none found

- **Returns.** Both our returns are `I12 = DM(M7, I6); JUMP (M14, I12) (DB)`,
  back to back. The compiler always puts at least one instruction between them
  (e.g. sw `0x1c9d62..0x1c9d66`). This is probably interlocked on SHARC+, but it is
  a difference from compiled code, and it costs nothing to match.
- **Loops.** The DO-loop `mode` bit (bit 23 of Type 12a/13a, "mode" in the SHARC+
  PRM figure 15-8): M5's reader emits `0d0200000072`, mode 0. Compiled code uses
  both, e.g. mode 1 at sw `0x1c0f0f` (`0d0000800015`) and mode 0 at `0x1c0fc1`
  (`0d0000000053`), a loop with branches in its body. **The runner records the
  bit and ignores it.** Mode 0 is therefore a form the silicon runs, but which
  loop type it selects is not documented here. ONESHOT's own adapter has no DO
  loop, so this cannot be a shared cause.
- **Calls.** `CJUMP` is a jump plus `R2 = I6, I6 = I7` (PRM Table 16-1), not a
  PC-stack call. digikit's executor runs it as a call and checks the matching
  return. Our code returns through the software frame, as the firmware does, so
  that runner difference is not reached.
- **SIMD.** No `MODE1` write in the dispatch `0x1c8ef1..0x1c9448`, and the C ABI
  enters functions in SISD, so our loop runs SISD.

## The runner's workarounds (suspect 4)

G1-G11 are listed in `scripts/sharc_dn2_fixups.py`. The one that bears on this
problem is structural rather than one fixup: **the runner models flat memory with
no cache**. Any L1 range the PM or DM cache owns reads back in the runner exactly
as the boot stream wrote it. That is the same class of blind spot as correction 1
(the 0x280000 "hole"). G4 (NW→byte rescaling) applies only to immediates in
`0x90000..0xe7fff` and does not touch our addresses.

## M5's pass-through differs from ONESHOT's in one way that could fail on its own

M5's loop runs from boot every block for every track: it saves registers to
`0x301000..` and scans types. Its **last instruction, `JUMP 0x1c944c`, is the last
word of its span** (byte `0x3006f6`). Past it lies never-written L1: power-up
contents, which may carry bad parity. ONESHOT's pass-through ends in `JUMP 0x1c944c`
followed by more of its own code (`os_quiet`), so the sequencer's prefetch past the
jump reads written memory. The failing paths of both builds do end at span edges:
M5's reader ends at `0x300176`, and ONESHOT's divide helper and decimator end at
`0x30a9de` and `0x30ac0a`. That is **a pattern, not a mechanism**. Whether an L1
parity error on a discarded prefetch faults the ADSP-21569 was not established
here. The stock stream leaves small holes after code too: 8 bytes at L2
`0x2001e880`, 4 bytes at `0x283825c0`.

## Ranked causes

| rank | cause | for | against | settles it |
|---|---|---|---|---|
| 1 | our block-2 use collides with the **PM data cache** (block 2 is its home), or with another run-time owner the static scan cannot see | ADI: PM cache is attached to block 2; stock leaves the whole block empty; the runner has no cache model | a top-carved cache spares M5's spans and ONESHOT's pass-through; enables and sizes not read | the startup's `SHL1C_CFG` value; D2 below |
| 2 | stock DSP code faults on a **real type 5** (the lookup patch), on a path the runner never runs (another task, a note path outside `0x1c2712`) | the lookup patch is the one change common to both builds; cfonly (lookup stock) plays | `0x25d748` and record `+0x1b4` are read only in the unpack and dispatch, in both block 3 and L2 code; the runner ran those with type 5 | **D1** below |
| 3 | prefetch or parity past the end of a code span into never-written L1 | fits every failing path; M5's pass-through ends at a span edge, ONESHOT's does not | no documented mechanism; stock has small holes too | pad each span (the fix below) |
| 4 | ONESHOT's trig-kill comes from its ColdFire half, not section 7 | no ONESHOT cfonly control | the symptom is DSP-shaped | an ONESHOT cfonly build |

Ruled out: the boot stream (5); executing from block 2 or its address form (2);
the instruction forms and runner workarounds checked above (3, 4).

## Discriminator builds (in `00_Resources/02_Builds/`, both pass `dnfw inspect`)

Section 3 in both is M5's, byte-identical to `waverider-m5-cfonly` (`dnfw diff`),
so `emu_boot_check` does not apply. Only section 7 differs, and by a few bytes.

- **D1 `waverider-disc-lookup-only_DN2_1.11.syx`**: stock section 7 plus **only**
  the lookup `0x25d748[5] = 5` (1 byte, stream `+0x3034`). No entry JUMP, nothing
  in block 2. **If it goes silent** when WAVERIDER is selected or trigged: rank 2,
  and every block-2 fix is moot until the stock type-5 path is handled. **If it
  plays**: the fault is in our block-2 code or data.
- **D2 `waverider-disc-m5-nodir_DN2_1.11.syx`**: the M5 section 7 with the
  directory magic at `0x301800` cleared (4 bytes, stream `+0xcd00c`). The loop
  still runs from block 2 on every block, saves and restores through `0x301000`,
  and checks types. It never reads the tables, never calls the reader, and never
  writes a track buffer (a type-5 track stays silent, as MIDI does). **Silent from
  boot, before WAVERIDER is selected**: M5's own pass-through (its span-edge JUMP,
  or its state at `0x301000`) kills the DSP, which ONESHOT's does not. **Plays
  before, and silent after selecting WAVERIDER**: the same answer as D1 would give.
  **Plays throughout, with a silent WAVERIDER track**: the fault is in the reader
  path (tables at `0x302000..0x30a000`, the CJUMP/loop/return, the buffer write).

**Test protocol for each** (restate what the instrument did before concluding):

1. Boot a new project, play an FM Tone track **before touching WAVERIDER** (this
   check has never been done for M5).
2. Select WAVERIDER on another track **without trigging it**; play FM Tone again.
3. Trig the WAVERIDER track; play FM Tone again.
4. Reboot between builds.

## Proposed fix (to build once D1 and D2 have answered)

If D1 plays (the fault is ours):

1. **Leave block 2.** The cache's home is not proven free at run time, and the
   stock image avoids it on purpose. Candidates in order: (a) block 1's gap above its
   last load, `0x2dd540..`, kept well below the block's top (the DM cache is
   carved from block 1; with `0x4100` set, keep at least 64 KB clear, so
   `0x2dd540..0x2e0000`, 10.9 KB). M5's code, state, increment table and directory
   fit (about 3.2 KB). (b) The 32 KB of tables go to DDR. The stream's big zero
   fill ends at `0x804ace8c + 0x80904`; a span must be shown unreferenced first,
   as was done for block 2, and DDR reads go through the DM cache, which is
   correct for read-only tables.
2. **Pad every code span** with a zero-fill (NOP) tail of at least 64 bytes, and
   put a zero-`FILL` block over any gap between our spans, so no fetch or read
   ever touches never-written L1.
3. **Match the compiler's return shape**: one instruction between
   `I12 = DM(M7, I6)` and `JUMP (M14, I12) (DB)`, with `RFRAME` in the second
   delay slot.
4. For ONESHOT, the same relocation plus a **cfonly control** before any
   conclusion about its trig-kill.

If D1 goes silent (rank 2), the lookup patch alone is unsafe on silicon. The next
step is to trace what else consumes the machine type outside `0x1c2712`.

## Tools used

`dnfw ldr`, `dnfw build/inspect/diff`; selache `selmap` (through a Python wrapper)
with digikit `decode_at` boundaries for every listing; ad-hoc scans in the
session scratchpad (block-2 pointer scan in byte, NW and SW forms, loop-mode
census, span overlap). None of them is committed; each is a few lines over
`dnfw.image.bootstream`.

## Hardware results of the discriminators (owner, 2026-09-27)

- **D1 `waverider-disc-lookup-only` PLAYS.** The other tracks play normally with
  WAVERIDER not selected, selected, and trigged. The WAVERIDER track itself is
  silent. **Rank 2 is ruled out**: on silicon, stock DSP code handles a real
  type 5 (MIDI's no-setup arm).
- **D2 `waverider-disc-m5-nodir` PLAYS**, in all three steps. So on silicon the
  following are fine:
  - the always-running type-5 loop in block 2 (sw `0x180200`);
  - its absolute state reads and writes (`0x301000..0x301084`) and its read of
    the directory word (`0x301800`, here 0);
  - the entry and the return, **including a final `JUMP` that is the last word of
    its span** (byte `0x3006f6`).

  **The fault is on the path the directory magic enables**: the reader call and
  the reader's code, its reads of the directory, pitch table and two 16 KB
  tables, and its writes into the track buffer.

### Re-ranked with D1 and D2

1. ~~**The reader's hardware DO loop**: open, leading~~ -- **ruled out by hardware
   (m5c, 2026-09-27)**: m5c has no DO loop and still dies on a WAVERIDER trig. The reader ran
   `LCNTR = R2, DO ... UNTIL LCE` (`0d0200000072`, loop-`mode` bit 23 clear) with
   pre-modify `DM(M4, I0)` taps. It is the only hardware loop in our code.
   - The firmware sets the mode bit on every short straight-line loop: the
     dispatch's own `lcntr=r12, do 0x80000c` at sw `0x1c9492`, and `0x1c990b`,
     `0x1c995a`, `0x1c9a19`, `0x1c9a91`.
   - It clears the bit only on loops with branches in the body or immediate
     counts (`0x1c0fc1`, `0x1c9478`).
   - digikit's executor records the bit and ignores it.
   - If the silicon ends a mode-0 straight-line loop differently, the loop
     overruns the 32-float track buffer or never ends. Either kills every track.
2. **The CJUMP into block-2 code, and our back-to-back `I12` load and return
   jump**: open. The form is the firmware's own; only the spacing differs.
3. **Reads of the tables at `0x302000..0x30a000` and the pitch table at
   `0x301400`**: weak. Wrong data still yields bounded floats: POS is clamped to
   frame 15 and the sample index is masked to 0..255 words. The PM data cache
   sits at the top of block 2 (`0x31c000..`, below), which M5 never touches.
4. **The reader's last word at the end of its span**: weak. D2 ran the same
   shape every block without harm (the loop's final `JUMP` at `0x3006f6`).
5. **The track-buffer write address or length**: weak.
   - The pointer comes from the same array (`0x254a60 + 4t`) as the stock
     machines use.
   - The length comes from the same dispatch register: the R9 that the stock
     chain pushes as its own block-size argument at sw `0x1c9456`.
   - Both match what the runner saw: 32 floats, with tracks 1-15 bit-identical
     to stock.
   - A wrong length could only come from the loop, which is rank 1.

### The startup cache configuration, decoded

sw `0xb8b93a` (called from `__start`, sw `0x1c0ef6`) computes `SHL1C_CFG`
(`0x3e000`). Opcode `0x08` of the immediate shifter is `Rn = Rn OR LSHIFT`
(digikit's `compute_shift._shift_immediate` treats `0x08`/`0x09` as the OR forms).

```
r13 = m7 (-1)                                  ; the "not configured" sentinel
r11 = 0; r14 = 0x4100;   r14 |= r11 << 9       ; DM cache: enable 0x4100, size code 0
r10 = 0; r2  = 0x410000; r2  |= r10 << 17      ; PM cache: enable 0x410000, size code 0
if eq (r13 == r11) r14 = 0                     ; not taken: 0 != -1
if ne r14 |= r2                                ; PM cache on
r1 = 0;  r2  = 0x41;     r2  |= r1 << 1        ; I-cache: enable 0x41, size code 0
if ne r14 |= r2                                ; I-cache on
SHL1C_CFG |= r14 (0x414141)                    ; sw 0xb8b9ac..0xb8b9b2, through sw 0x1c0272
```

**All three caches are enabled, each with size code 0.** The size fields come from
link-time constants that resolved to 0 in this image. Size code 0 is 16 KB, carved
from the top of its block. The evidence is the I-cache, which is enabled with the
same code 0: the stock stream stops filling block 3 at `0x39bffc`, exactly 16 KB
below the block's end (`0x3a0000`). So:

| cache | block | owns (byte) |
|---|---|---|
| I-cache | 3 | `0x39c000..0x39ffff` |
| DM data cache | 1 | `0x2ec000..0x2effff` |
| PM data cache | 2 | `0x31c000..0x31ffff` |

This retires rank 1 of the first ranking for M5, whose spans end at `0x30a000`.
ONESHOT's spans end at `0x317df8` and are clear too.

## Milestone 5c: the fix build

`waverider-m5c_DN2_1.11.syx` is m5b's section 3 (the menu fix, sha256
`85debe72...`, passed on hardware) plus a new section 7 with three changes.

**1. Everything moves out of L1 block 2 into block 1's free tail,
`0x2dd600..0x2e7000`:** ~~(the fix)~~ -- **ruled out as the cause by hardware (m5c
still dies on a trig, 2026-09-27): the block-2 location was not it.**

| span | byte | sw | bytes |
|---|---|---|---|
| `reader_m5.asm` | `0x2dd600` | `0x16eb00` | 350 code + 674 zeros |
| `machine5_live.asm` | `0x2dda00` | `0x16ed00` | 758 code + 266 zeros |
| state (save area, counters, 16 reader blocks) | `0x2dde00` | | 1,024 |
| increment table | `0x2de200` | | 516 + 508 zeros |
| directory | `0x2de600` | | 16 + 2,544 zeros |
| table 0 (saw -> sine) | `0x2df000` | | 16,384 |
| table 1 (overtones) | `0x2e3000` | | 16,384 |

How the region was shown free:

- The stock stream's last byte in block 1 is `0x2dd52c` (`dnfw ldr`: data block
  `0x282dd3d0 + 0x15c`). No block, loaded or filled, reaches past it.
- The DM cache owns `0x2ec000..` (above). The region ends 20 KB below that and
  also clears a 32 KB DM cache (`0x2e8000..`). `dsp._check_free` refuses any span
  outside `REGION`, and refuses a `REGION` that is not between those bounds.
- No loaded data word in L1 block 0 or 1 names the region, in byte, `0x28`-alias,
  normal-word (`0xb754b..`) or short-word (`0x16ea96..`) form. The hits are L2/L3
  instruction parcels and DDR int16 pairs, the same noise profile as the block-2
  scan.
- **Limit:** as for block 2, this cannot exclude an address computed at run time.
  The difference is what the memory is:
  - Block 1 is the image's own data block. The linker filled it with `.bss` up to
    `0x2dd0c0` and data up to `0x2dd52c`, and the region is the tail it left.
  - Block 2 was a whole block the image never used, and it is the PM cache's home.
- Nothing is left in block 2 (a test asserts it).

**2. The region is written end to end.** Every payload is zero-padded to the next
span. Each code object is followed by at least 64 bytes of zeros (NOPs), and no
byte is left to power-up contents. Tests assert both.

**3. The reader has no hardware loop and no pre-modify access** (rank 1 above) --
**ruled out as the cause by hardware (m5c, 2026-09-27)**:

- The count word of the parameter block is decremented and stored each sample,
  then `IF NE JUMP` goes back, the form D2 proved on silicon.
- Each of the four taps is byte arithmetic, then `I0 = Rn`, then `DM(0, I0)`
  (Type 15b).
- A count of 0 jumps straight to the return.
- The float arithmetic is unchanged and in the same order, so the output is
  bit-identical.
- I3 and I5 (the loop's own pointers) are untouched.
- **The return takes the firmware's shape**: `I12 = DM(M7, I6)`, one instruction
  (the phase store), `JUMP (M14, I12) (DB)`, `NOP`, and `RFRAME` in the second
  delay slot.

The entry is `JUMP 0x16ed00` + NOP at sw `0x1c9448` (bytes `3e06160000ed0100`).
The lookup `[5] = 5` is unchanged.

**Cost:** about 16 more instructions a sample, so about 500 more a block for each
type-5 track, against about 154 k a block for the whole engine.

### A remaining discriminator (not waited on)

m5c changes two things at once: the location and the loop. If m5c plays, a build
with **only the loop change, left in block 2**, would say which one mattered. That
build is a cheap reassembly of `reader_m5.asm` for sw `0x180000` with the M5
layout. It does not decide whether m5c ships.

### Test plan for `waverider-m5c_DN2_1.11.syx`

Flash it. Before concluding anything, restate what the instrument did at each step.

1. **The always-running path.** Boot, open a new project, and play an FM Tone or
   WaveTone track **before touching WAVERIDER**. It must sound normal. The m5c loop
   now runs from block 1 every block for every track; D2 proved the same loop from
   block 2.
2. **Select.** On track 2, MACHINE SEL -> WAVERIDER (m5b's menu). Play track 1
   again: it must still sound normal.
3. **Trig: the demo.** Put a trig on **every step** of track 2 (16 trigs, note C3,
   i.e. 48), press PLAY, and listen:
   - **Within the first bar**, track 2 is a **loud, buzzy saw**: SLOT 0 at POS 0,
     the 32-harmonic saw, the init sound.
   - **While it plays, turn `WAV1`** (SYN 1, encoder B) from 0 to 120 over about
     one bar. The saw **darkens to a pure sine** as you turn; turn back and it
     brightens again. That is the table being read live: 16 frames, interpolated.
   - Optional: `TBL1` (SYN 2, encoder B) to 1, then sweep `WAV1`. The overtone
     series climbs from partial 1 to partial 16.
   - Keep track 1 playing throughout: it must never drop out.

   What to listen for is `m5_demo_pos_sweep_preview.wav` (note 48, POS 0 -> 120).
   The runner renders of this build are the `m5_*_m5c` files below.

| outcome | reads as |
|---|---|
| 1-3 all normal and the saw darkens | fixed. Then the block-2-only-loop build (above) says whether the loop or the location mattered |
| 1 normal, silence from 3 | the fault moved with the code or is in the reader path in any location. Next: the loop-only build in block 2, and a reader with the loop but no track-buffer write |
| silence at 1 | the block-1 region is not free at run time. Revert to D2's layout for the loop |

## What the same move means for ONESHOT (PR #136)

- **ONESHOT's own adapter has no hardware DO loop**: it zeroes the buffer with 32
  unrolled stores. Its trig path calls the **transplanted DT2 render**, which is
  compiled code whose loops carry the compiler's own mode bits (DT2-native). So
  rank 1 does not transfer to ONESHOT as it stands.
- **What does transfer:**
  - the move out of block 2;
  - the zero padding: its divide helper and decimator end at span edges
    `0x30a9de` and `0x30ac0a`, with unwritten gaps after them;
  - the firmware's return shape, which the DT2 code already has.
- **It does not fit beside m5c's margin.** ONESHOT's stream adds 50,588 bytes to
  block 2 (`dnfw ldr`):
  - render, divide helper and decimator: 3.0 KB;
  - the block at `0x30c400`: 6 KB;
  - the adapter: 1.6 KB;
  - steps: 2 KB;
  - the bank: 30 KB;
  - the record fill: 7.5 KB.

  Block 1's tail from `0x2dd540` holds 43,712 bytes below a 32 KB DM cache
  (`0x2e8000`) and 60,096 bytes below the 16 KB one the startup configures
  (`0x2ec000`). So ONESHOT fits beside nothing else only against the 16 KB bound,
  or against the 32 KB bound with the bank trimmed by about 7 KB. It cannot share
  the tail with Waverider's 38.5 KB in one image; one of the two would need DDR.
- **Before any ONESHOT fix build**, ONESHOT needs its own controls, like
  Waverider's:
  - an ONESHOT cfonly build (its section 3, stock section 7), because its trig
    path is new on the ColdFire too;
  - its own D2 analogue (magic cleared).

  The trig-kill has not been pinned on its section 7.
- **Not built** here, on purpose: it is not trivial (relocating the transplant
  touches `dnfw.transplant`'s relocation sites and the bank), and its evidence
  base is weaker than Waverider's.

### m5c gates (2026-09-27, digikit `6f812e9`)

| gate | result |
|---|---|
| `test_waverider_dsp.py` | 17 passed. New tests: no span in block 2; the region written end to end; at least 64 zero bytes after each code object; the firmware's return shape |
| `sharc_waverider_m5.py --blocks 8` (its own frames) | **PASS, 23 of 23** (444 s). The numbers are the same as M5's; details below the table |
| the same, `--frame-be` on the ColdFire's own frames (init, WAV1 max, WAV1 max + TBL1 1) | **PASS, 26 of 26** for each (540, 522 and 524 s). Step 5: every type-5 track is bit-exact to the reference |
| `dnfw inspect waverider-m5c_DN2_1.11.syx` | 21 of 21 ok, HMAC reproduced |
| `dnfw diff` m5b -> m5c | only section 7 differs (872,524 -> 876,492 bytes). Section 3 is identical to m5b (sha256 `85debe72...`), so `emu_boot_check` is not needed |
| `dnfw ldr` | 102 blocks, and the walk ends at the section's end. Our region `0x282dd600..0x282e7000` (39,424 bytes) is one contiguous span. Nothing is at `0x2830xxxx` |

The gate on its own frames, in detail:

- decode: 0 disagreements;
- the loop is entered 8 times in 8 blocks, and takes the no-setup arm 8 times in 8;
- the machine tap has **0 float32 mismatches** in all five runs;
- amp out: peak 0.0665, rms 0.0343, r = 0.934;
- POS 120 centroid 410 Hz, against 735 Hz at POS 0;
- TBL1 1 selects the table at `0x2e3000`;
- note 72 gives an increment of 46,819,720, exactly 2 x 23,409,860;
- no trigger: peak 0.0031;
- types 0-4 are bit-identical to stock;
- cost: 155,017 instructions a block (M5: about 154.5 k).

The gate's reader-block check now reads the parameter block on the reader's entry
(sw `READER_SW`), because the 5c reader counts its count word down to 0. The first
run, before that change, failed only this check, on `count` = 0 at resume. It
looked like a regression and was not one.

Section 7: sha256 `7f451c57e9ed83d0...`, 876,492 bytes.

## m5c on the instrument (owner, 2026-09-27): still silent on a trig

`waverider-m5c` goes silent right after the WAVERIDER track is trigged, as M5 and
ONESHOT did. Steps 1-2 (play before selecting, then select) are presumed fine;
this is being confirmed with the owner. **Neither the block-2 location nor the
hardware DO loop was the cause.** Both are marked above.

### The track-buffer hypothesis, tested in the runner: not supported

The hypothesis: a type-5 track takes MIDI's no-setup arm, so its buffer pointer
at `0x254a60 + 4t` might be unset, stale or shared on hardware, and writing 32
floats through it would corrupt DSP state.

**Who writes the pointer array.** The array is engine `+0x137c8` (engine base
`0x241298`).

- The only instruction in the image that names it as an immediate is
  `i4 = 0x254a60` at sw `0x1c14db`, in the engine init (`sw 0x1c1445`). It is
  followed by the loop `lcntr = 8, do ... until lce` at sw `0x1c14de`, which fills
  it for all 16 tracks, two per pass.
- The only other code that forms the address is the slot dispatch,
  `i3 = modify(i2, 0x137c8)` at sw `0x1c8f63`. It **reads** it; its store at
  `0x1c8f88` goes to `i3 + 0x295` words, which is not the array.
- No L2 code names `0x254a60` or offset `0x137c8`.
- **Nothing in the writer depends on the machine type or on a setup arm.**

**What the array holds, traced in the runner.** This is `scratchpad bufptr.py`,
run on the m5c image from the post-engine-init snapshot. The snapshot is the
runner's own run of `sw 0x1c1445`, which executed the writer loop above.

- 16 distinct pointers, `0x804acf90 + 0x80 t`. That is 16 contiguous buffers of
  exactly 32 floats (128 bytes) each, in DDR `.bss` (inside the stream's zero fill
  `0x804ace8c + 0x80904`).
- Over 3 blocks, with track 0 type 5 (trigged on block 1), track 1 WaveTone,
  track 2 MIDI and track 3 FM Tone, **no pointer changed** at any dispatch.
- The type-5 track's buffer (`0x804acf90`) is as valid as the WaveTone track's
  (`0x804ad010`), the MIDI track's (`0x804ad090`) and the FM Tone track's
  (`0x804ad110`).

**The write length.** Our reader writes `count` floats. `count` is the dispatch's
R9, the same register the stock chain pushes as its block size at sw `0x1c9456`.
It is 32 in every runner block, exactly one buffer. The type-5 buffer is also
processed in place by the stock chain every block: in the scratch run below, track
0's buffer holds the chain's own data at resume.

**ONESHOT's output path is the same array.** Its adapter reads the pointer from
`0x254a60 + 4t` (`os_loop`, `R3 = DM(0, I4)`) and hands it to the DT2 render as
R8, with R12 = the dispatch's R9. Its idle path `os_quiet` writes 32 zeros
through that same pointer on **every** block once a type-5 track is selected. On
hardware that phase played normally. So a write of 32 floats to a type-5 track's
buffer was harmless on silicon, **provided** ONESHOT's bank magic read back, which
is still unconfirmed.

**Conclusion: step 1 does not prove the hypothesis.** The pointers are set once
at init, for every track, independent of machine type, and a 32-float write stays
inside the track's own buffer. **No m5d is built** on this basis. The runner cannot
show a run-time rewrite of the array on silicon, but no code in the image performs
one.

### D3: the scratch discriminator (built anyway, it is cheap and decisive)

`waverider-disc-m5c-scratch_DN2_1.11.syx` is m5b's section 3 plus m5c's section 7
with **one change**: the reader's `out` load `R0 = DM(5, I4)` becomes
`R0 = 0x2de800`. That is 2 KB of the directory's zero padding, inside our block-1
region. The reader still runs in full: the CJUMP, every read of the frame copy,
the note cell, the pitch table, the directory and the tables, and the return. It
writes nothing into the track buffer, so WAVERIDER stays silent.

- Built by `scripts/build_waverider_disc_scratch.py`. It derives the reader from
  `reader_m5.asm` at build time, assembles it with selas, re-resolves the two
  absolute jumps (reader 352 B), and refuses an existing output.
- `dnfw inspect`: 21 of 21 ok. `dnfw diff` against m5c: only section 7, 314
  bytes, all in the reader's block (stream `0xcc574..0xcc6bb`). Section 7 sha256
  `246ed02e9ac1b6c1...`.
- Runner, 3 blocks, track 0 type 5, trigged (`scratchpad scratchcheck.py`):
  - both builds return every block, with 3 loop entries;
  - the scratch span equals m5c's track-0 machine tap bit for bit on all 3
    blocks, so the reader did exactly the same work;
  - tracks 1-15 are bit-identical between the two builds.

**Reading it on the instrument** (same three steps as m5c):

| outcome | reads as |
|---|---|
| plays through the trig, WAVERIDER silent | the fault is the write into the track buffer (then: what on silicon differs about that buffer, e.g. the chain reading our floats) |
| still dies on the trig | the reader call or its reads. What is left: the CJUMP/return mechanics in our code, and the reads of the frame copy and note cell. A note cell that is NaN or huge on silicon would make `TRUNC` raise an invalid-operation sticky, which only matters if an FP exception interrupt is enabled. Not checked; a candidate for the next static pass |

## D4: the sanitised-output discriminator, and the value hypothesis (2026-09-27) -- **the value/NaN hypothesis is ruled out by hardware (D3, 2026-09-27)**

**The hypothesis (the coordinator's).** Writing the buffer is harmless: ONESHOT's
`os_quiet` wrote zeros into it every block, and that played. What changes at the
trig is the values. NaN, Inf or huge output would enter the per-track chain and
the shared FX feedback and poison the master mix, while the DSP keeps running.

### What our reader can output, by construction

Every output sample is `y = a + ff (b - a)`, where:

- `a = s00 + fr (s01 - s00)` and `b = s10 + fr (s11 - s10)`;
- each `s` is an int16 word from the table, scaled by `FLOAT ... BY -15`, so
  `|s| <= 1`;
- `fr = FLOAT(phase & 0x7fffff) BY -23` is in `[0, 1)`;
- `ff = FLOAT(pos & 0xffff) BY -16` is in `[0, 1)`.

No input can make a NaN or an Inf through that arithmetic: `|y| <= 1` always. A
wrong input only changes which words are read and where:

| input | wrong value | effect |
|---|---|---|
| note cell | NaN | `TRUNC` saturates, so it gives a wild pitch-table index |
| pitch-table index | out of range | shifted by 2 and added to the table base, it wraps to a nearby word of our own block-1 region |
| inc | wrong | a wrong pitch |
| POS, SLOT | wrong | clamped (POS <= frame 15; a SLOT >= the count plays slot 0) |

So **a NaN/Inf/huge output from our code is not possible on silicon either**,
unless the silicon's FLOAT/MIN/MAX differ from IEEE float32. ONESHOT's DT2 render
is the DT2's own shipped code and is equally bounded. Any poisoning therefore has
to be **downstream of a bounded, non-zero input**: a per-track chain stage whose
state or coefficients are wrong for a type-5 track, so that it blows up only when
excited. D1 fits this: it trigs a type-5 track with a zero buffer and plays. D4
tests the level, not NaN.

### D4 `waverider-disc-m5c-sanitise_DN2_1.11.syx`

m5b's section 3 plus m5c's section 7, with **one change**: 12 instructions inserted
before the reader's store `DM(I2, M6) = F4`:

```
16eb9c  r0 = lshift r4 by -23 ; r1 = 0xff ; r0 = r0 and r1 ; comp(r0, r1)
16eba3  if eq r4 = r4 - r4          ; exponent 0xff (NaN, Inf) -> +0
16eba6  r0 = 0x3f800000 ; f4 = min(f4, f0)     ; <= +1
16ebab  r0 = 0xbf800000 ; f4 = max(f4, f0)     ; >= -1
16ebb0  r0 = 0x3f000000 ; f4 = f4 * f0         ; x 0.5
16ebb4  dm(i2, m6) = r4
```

The listing above is digikit's boundaries with selmap's text, and the two agree
on every instruction.

- Built by `scripts/build_waverider_disc_scratch.py --variant sanitise` (reader
  398 B, jumps re-resolved).
- `dnfw inspect`: 21 of 21 ok.
- `dnfw diff` against m5c: only section 7, 72 bytes inside the reader's block;
  section 3 identical.
- Section 7 sha256 `f0a7dff6cbeabeda...`.

**Runner** (`scratchpad d4check.py`, 4 blocks each, digikit `6f812e9`):

| case | result |
|---|---|
| track 0 type 5 trigged, tracks 1-4 WaveTone/FM Tone/FM Drum/Swarmer trigged | D4's machine tap = m5c's x 0.5, **0 mismatches in 128** (peak 0.9926 -> 0.4963); tracks 1-15 **bit-identical to stock** |
| POS 120 | 0 mismatches in 128 (0.5550 -> 0.2775) |
| TBL1 1, WAV1 0x2000 | 0 mismatches in 128 (0.9992 -> 0.4996) |
| no type-5 track | all 16 buffers bit-identical to stock |

Not run: the full 26-check gate, whose bit-exactness check expects x 1. The
comparisons above are its x 0.5 counterparts.

### (a) The mode and interrupt state the dispatch runs with

From `__start` (sw `0x1c0e70`):

- `bit set mode1 0x78`, then `bit clr mode1 0xa078`, then
  `bit set mode1 0x1011800`. That gives:
  - **RND32 = 1** (bit 16, 32-bit float);
  - **TRUNC = 0** (bit 15, round to nearest);
  - **ALUSAT = 0** (bit 13, fixed-point wraps);
  - NESTM and IRPTEN on;
  - **CBUFEN = 1** (bit 24, circular buffering enabled).
- `L0-L5` and `L8-L15` are zeroed there; `L6 = L7 = 0x1fd`.
- The slot dispatch `0x1c8ef1..0x1c9448` writes no MODE1, MODE2, L or B register.
  It switches SIMD (bit 21) on and off only after `0x1c944c`.
- **Our code writes no mode register.** It relies on:
  - RND32 = 1, so float32 matches the reference;
  - ALUSAT = 0, since the phase accumulator wraps mod 2^32;
  - L0, L2 and L4 = 0, since `DM(I2, M6)` post-modifies with CBUFEN on. That is
    the C ABI's own invariant, and the stock code relies on it the same way.

  `TRUNC` and `FLOAT` are explicit instructions and do not depend on the TRUNC
  bit. Only the multiplies and adds do, and round-to-nearest is what the
  reference assumes.
- **FP-exception interrupts: not settled statically.** `IMASK` is cleared at
  startup (`bit clr imask`, sw `0x1c0e79`). Bits are then set through a generic
  per-bit table in L2 (sw `0x2000b63b..0x2000b6a9`, one `bit set imask` per bit),
  whose callers decide which are enabled at run time. Our code cannot raise an
  overflow or an invalid operation from bounded data except through `TRUNC` of a
  NaN note. Whether FLTII is enabled is an open, cheap follow-up (the callers of
  that table).

### (b) Inputs the reader reads, and where the runner gets them

| input | in the runner | on silicon | could differ? |
|---|---|---|---|
| WAV1, TBL1 in the frame copy `0x25c48c` | written by the stock unpack (code that ran) from the harness's frame, or from the ColdFire emulator's own frames (init, WAV1 max, TBL1 1) | the ColdFire's DMA frame | yes, but a wrong value is clamped |
| note cell `0x254b14 + 4t` | written by the stock unpack from the **harness's** note and trigger fields (note 60, trigger) | the unpack of a frame **from a played note**, which was never captured (M5: "the ISR entered with a trig held did not reach the builder") | **yes: the least-tested input.** A wrong value gives a wrong pitch, never a non-finite sample |
| pitch table, directory, tables | our boot blocks | the same boot blocks; D2 proved the block reads in block 2 | unlikely |
| count (the dispatch's R9) | code that ran; 32 | the same code | unlikely |
| buffer pointer `0x254a60 + 4t` | written by the engine init (sw `0x1c14de`) that ran | the same | no (traced above) |
| I6/I7 frame | the harness's `unpack_call` frame | the engine task's stack | our code pushes two words and pops them with RFRAME; the stock callers do the same |
| the engine state behind the chain | the post-init snapshot (the runner ran `0x1c1445`) plus per-block frames | init plus every frame since boot, including the track's previous machine | **yes: the chain's per-track state for a track that became type 5 is never set up by a per-type arm** |

### Reading D4 on the instrument

| outcome | reads as |
|---|---|
| plays **and** makes a quiet saw | level/overload, not NaN: something in the chain overloads at full scale on a type-5 track. D4's clamp and scale join the fix |
| plays, WAVERIDER silent | our values are 0 on silicon: the inputs are wrong (the note cell or frame copy of a real trig) |
| still dies at the trig | not our values' magnitude. Flash D3 next. **D3 plays and D4 dies** means that exciting the chain with any bounded non-zero signal kills it: a per-track stage that is unstable for a type-5 track. The next static target is then the per-track chain state that WaveTone's setup arm writes and MIDI's does not |

## The uninitialised-chain hypothesis: tried offline, **not reproduced** (2026-09-27) -- **ruled out by hardware (D3 writes nothing into the track and still dies)**

**The hypothesis (the coordinator's).**

- A type-5 track takes MIDI's no-setup arm, so its per-track chain state is never
  initialised.
- Zeros through that chain are harmless. That fits D1 (stock DSP, MIDI arm) and
  D2 (the reader never runs).
- The first non-zero audio makes it diverge: M5, m5c and ONESHOT all die at the
  first trig. The divergence poisons the shared FX and the master.

### 1. What the setup arms write

The per-type setup table `0x8052db90`:

| entry | machine | handler |
|---|---|---|
| `[0]` | FM Tone | `0x1c90b2` |
| `[1]` | WaveTone | `0x1c91dc` |
| `[4]` | MIDI | `0x1c90d4` |

- **WaveTone's arm (`0x1c91dc`)** makes three calls:
  - `sw 0x1c694a` (R4 = `DM(-0x24, I6)`, R8 = `I5 - 0x18c`);
  - `sw 0x1c6757`;
  - `sw 0x1c6c13`.

  Each takes the WaveTone voice state for the track: engine `+0x2408 + 0x30c t`
  (Milestone 2), i.e. **the machine's own oscillator and decimator state**. The
  arm then jumps back into the dispatch.
- **FM Tone's arm (`0x1c90b2`)** calls `sw 0x1c4f04` on its own state the same
  way.
- **The MIDI arm (`0x1c90d4`) is not an arm that skips the chain.** It is the
  dispatch's common continuation, which the other arms jump back into. The
  per-track chain after it runs for every type:
  - the filter setup through `0x8052dba4[filter type]` at `0x1c91ad`;
  - the filter renders, the amp stage `sw 0xb80345`, and the DC blocker at engine
    `+0xe088 + 0x70 t`.
- So, as far as the reading goes, **the setup arms initialise machine state, not
  chain state**.
- A type-5 track's chain state is whatever the engine init and the per-block chain
  code leave there. That is `.bss` zero-filled by the stream (block 0
  `0x28241290` fill `0x1c028`, DDR fill `0x804ace8c + 0x80904`), and then updated
  every block by code that does not look at the machine type.

### 2. The runner, from post-engine-init

`scratchpad chaintrace.py`: 8 blocks. Track 0 has never had an audio machine; it
is typed from the first frame. Track 1 is WaveTone. Both are trigged on block 2.
Recorded per block:

- the master mix at `0x268438` (the 64 floats `sw 0x1c9d3f` FIXes into the output
  DMA buffer `0x2c0478..`);
- the track buffers after the whole chain;
- a census of NaN/Inf words in engine memory.

| run | track 0 after the chain | engine NaN/Inf census | master `0x268438` |
|---|---|---|---|
| **m5c, track 0 type 5** | finite every block; peak 0.002 -> **0.051**, rising after the trig | 49 at init, 49 after every block | NaN from block 1 |
| **stock, track 0 WaveTone** (control) | finite; peak 0.006 -> 0.118 | 49 / 49 | **NaN from block 1** |
| **stock + lookup `[5]=5` (D1, which PLAYS on hardware)** | finite; peak 0.0013 -> 0.020 | 49 / 49 | **NaN from block 1** |

**The kill does not reproduce offline, and the runner cannot judge the master.**

- The type-5 track's chain output stays finite and bounded after a trig, as the
  WaveTone control's does.
- Nothing new goes non-finite in engine memory.
- The master buffer goes NaN in the runner **in both controls**, the stock
  WaveTone image and D1, and both play on silicon. So the runner's master/FX
  path is not modelled well enough to show whether our track poisons it. That is
  a new runner gap, to be written up for digikit, and not evidence either way.

  Track 1's buffer is 0 in all three runs: the runner's WaveTone did not render
  there. That is a known runner limitation (Milestone 2's decimator, and the
  captured-frame audibility failure).

The fresh-boot memory behind the chain is `.bss`, filled by the boot stream, so
"unwritten" does not arise and zeros-versus-random has no case to test. **No m5d
is built**: step 1 found nothing for a sixth setup entry to initialise in the
chain, and step 2 did not reproduce.

### What is next: D3

**D3 `waverider-disc-m5c-scratch_DN2_1.11.syx` is the next flash.** It runs
everything m5c runs (the call, every read, the return) but feeds the track's
chain nothing new. How to read it:

| D3 on the instrument | reads as |
|---|---|
| **plays through the trig** | the reader's code is fine on silicon. The kill needs our non-zero samples in the track's buffer: the chain or FX reacting to real audio on a type-5 track, which the runner cannot show. Then D4 (half level, clamped) says whether the level matters |
| **still dies** | it is the reader call or its reads, independent of the chain. What is left: the CJUMP/return in our code, and the reads of the frame copy, the note cell and our block-1 data. Next, a D3 variant with the reader's CJUMP replaced by an inline no-op, to split the call from the reads |

## D3 on the instrument (owner, 2026-09-27): the DSP stops at the first trig

With D3, selecting WAVERIDER leaves the other tracks playing. **The first trig of
the WAVERIDER track silences everything**, and switching that track back to FM
Tone does **not** bring the sound back. D3 writes nothing into the track, so:

- our samples are not the cause: the **chain and NaN hypotheses are ruled out**
  (marked above);
- the DSP halts or hangs and stays that way; the mix is not poisoned;
- the cause is on the reader path, on its first run: the loop's type-5 tail, the
  software call and return, or the reader's body. D2 never reached any of them
  and played.

### Strict memory map: no violation from our code

`scripts/sharc_strict_memory.py` wraps digikit's `_dm_read`/`_dm_write` bindings
and `Runner._decode` from outside; digikit itself is untouched. It flags every
access that is:

- outside the ADSP-21569's real memory: L1 blocks 0-3 at their real sizes in byte,
  `0x28`-alias and normal-word form, L2 1 MB, DDR, and the MMR windows;
- inside the 16 KB caches at the tops of blocks 1-3;
- misaligned;
- an L1 read of a byte never loaded or written;
- a fetch outside code memory.

The harness's own stand-ins are counted separately and not flagged: the runner's
stack, which grows down from `0x300000`, and `UNPACK_LOCAL`.
(`scratchpad strictrun.py`; 3 blocks from post-engine-init, trig on block 1.)

**The stock control is not clean**, and every one of its hits is explained:

| stock hits | cause |
|---|---|
| "outside" near 0 and near `0xffffff00`, from sw `0x1c1b65..0x1c314e` | null and negative pointers read from the caller locals the harness zeroes |
| 24-38 misaligned 4-byte accesses in the frame copy (e.g. sw `0x1c28e3`, byte `0x25c4ae`) | 16-bit fields; the silicon evidently tolerates it, since stock plays |
| never-written reads at `0x300000..0x300054` from sw `0x1c26b7..0x1c26c2` | the harness frame's stack arguments, which sit over the first bytes of L1 block 2. In the M5 run they overlay **M5's own reader code** (`0x300000..`), a runner-only overlap |

The same hits appear in every run below. So the test is the violations raised
**with the PC in our own code**:

| run | violations from our code (sw `0x16eb00..0x16ee7c`, or block 2 for M5/ONESHOT) |
|---|---|
| m5c, type 5 trigged | **0** (3 blocks) |
| D3 (scratch) | **0** |
| M5 | **0** |
| D5a, D5b (below) | **0** |
| **ONESHOT** | **6 per block**: the transplanted render (sw `0x1853fa..0x185421`) reads 16-bit samples at `0x317df8..0x317f26`, **past the end of its bank** (`0x310800 + 0x75f8 = 0x317df8`), in never-written L1 |

**The table of every address the m5c reader path forms** (static; each is checked
against the boot stream):

| what | instruction form | address | lands in |
|---|---|---|---|
| save area, counters | 14a absolute | `0x2dde00..0x2dde84` | block 1, loaded (zeros) |
| directory magic, count, table pointer | 14a; 15b `DM(0, I1)` | `0x2de600`, `0x2de604`, `0x2de608 + 4 slot` (slot 0-1) | block 1, loaded |
| WAV1/TBL1 | 15b `DM(0/1, I1)`, `I1 = (0x25c568 + 146 t) & ~3` | `0x25c568..0x25d0f8`, 4-aligned | block 0 `.bss`, filled |
| note cell | 15b | `0x254b14 + 4 t` | block 0 `.bss` |
| pitch table | 15b `DM(0/1, I1)` | `0x2de200 + 4 k`, k 0..127 (+1). A NaN note's `TRUNC` wraps to `0x2de1fc` or `0x2de200` | block 1, loaded |
| reader block | 15b | `0x2ddf00 + 32 t`, words 0-7 | block 1, loaded |
| table rows and taps | 15b `DM(0, I0)` | table + 1024 f + 4 w, f <= 15, w <= 255: at most `0x2e6ffc` | block 1, loaded |
| track buffer | 3c `DM(I2, M6)` post-modify, L2 = 0 | `0x804acf90 + 128 t`, 32 words | DDR `.bss` |
| frame pushes | 3c / 16a `DM(I7, M7)` | the task stack, 2 words | as the stock callers |
| fetch | | sw `0x16eb00..0x16ebaf`, `0x16ed00..0x16ee7c` = byte `0x2dd600..`, `0x2dda00..` | block 1, loaded, NOP-padded |

**Strict mode is clean for Waverider.** Nothing our code touches is outside real,
written memory. The ONESHOT overrun is a real ONESHOT bug, **independent of
Waverider**:

- The render's playhead runs past the last sample of the bank. With the harness's
  frame, SAMP/LEN are WaveTone's values, not a real ONESHOT sound's, so whether a
  real sound reaches it is open.
- The fix for ONESHOT is to pad the bank's end with zeros, at least the render's
  6-tap reach plus one block's advance, and to clamp the end address.

### The call and return, compared with a stock call in the same dispatch

| | stock (sw `0x1c9151`, the call of `0xb809cb`) | ours (m5c sw `0x16ee0d`) |
|---|---|---|
| call | `cjump 0xb809cb (db)`, 25a, 48-bit | `cjump 0x16eb00 (db)`, 25a, 48-bit |
| delay slot 1 | `dm(i7,m7)=r2`, 3c `f29f` | `dm(i7,m7)=r2`, 3c `f29f` |
| delay slot 2 | `dm(i7,m7)=0x1c9157`, 16a, the next address - 1 | `dm(i7,m7)=0x16ee13`, 16a, the next address - 1 |
| return | `i12=dm(m7,i6)` 3b `fe4d3f0e`; one instruction; `jump (m14,i12) (db)` `3f083f34`; slot; `rframe` `0119` (e.g. sw `0x1c9d62..0x1c9d6a`) | `fe4d3f0e`; `dm(1,i4)=r9`; `3f083f34`; `nop`; `0119`: the same forms, in the same order |

What differs: the stock callee allocates a frame (`i7 = modify(i7, -n)(nw)`)
before it touches memory, and our reader allocates none. It needs none: it uses
no stack.

**Instruction shapes our code uses and the stock corpus does not.** The corpus is
31,102 walked stock instructions (the dispatch, the unpack, block 3 `0x1c3400..`,
L2 `0xb80000..`). Normalised for registers and constants, the shapes absent from
it, all on the D3-only path, are:

- the conditional computes `if eq r5 = lshift r4 by r7` (sw `0x16eda7`),
  `if ne r4 = lshift r4 by r7` (`0x16edaa`) and `if ge r1 = r1 - r1` (`0x16edba`);
- `f1 = float r0` (`0x16edea`);
- `r2 = r3 xor r2` (`0x16eb71`).

All five decode alike in selmap and digikit. They are candidates, not findings.

## D5a and D5b: bisect the reader path

`scripts/build_waverider_disc_bisect.py` makes two builds, each m5c's section 7
with one byte patch plus m5b's section 3. Both pass `dnfw inspect` (21/21); `dnfw
diff` against m5c shows only section 7, 11 and 8 bytes; section 3 is identical.

| build | patch | runs | skips |
|---|---|---|---|
| **D5a `waverider-disc-m5c-nocall`** | sw `0x16ee0d`: the 14-byte call (`cjump`, 2 pushes) becomes `jump 0x16ee14` + NOPs | the whole loop tail: frame copy, note cell, pitch table, directory, the five novel shapes, the reader-block writes | the call |
| **D5b `waverider-disc-m5c-callonly`** | sw `0x16eb02`: the reader's second instruction becomes `jump 0x16eba7` (its own return sequence) | the loop tail, the CJUMP and both pushes, `I12 = DM(M7, I6)`, the return jump and RFRAME | the reader's body; no buffer is written |

In the runner, both return every block for 3 blocks with a type-5 trig, with 0
strict violations from our code. The patched sites decode as intended.

| D5a | D5b | reads as |
|---|---|---|
| dies | (dies too) | the **loop tail** kills it: suspect the novel conditional shapes and the reads of the frame copy and note cell |
| plays | dies | the **software call/return** into our code is what silicon refuses |
| plays | plays | the **reader's body** (D3 minus the call) |

Flash D5a first. Flash D5b only if D5a plays.

## Does any SHARC DMA target our memory? (static, 2026-09-27)

The lead comes from irpina's Digitakt mk1 probing handoff
(`00_Resources/01_Reference/PROBING-HANDOFF.md`): "DMA writes are invisible to
[the emulator]", and on the mk1 a DDR range is the delay effect's DMA ring. A DMA
engine writing into our reader's code or tables would fault the first call, and
neither emulator would show it.

**Where DN2's SHARC programs DMA.** No DMA channel MMR (`0x31022000..0x3102ffff`)
appears as an instruction immediate in block-3 or L2 code. The drivers take their
channel bases from static device tables in block-0 data:

- the SPORT/DMA pairs `{SPORT base, DMA base, ...}` at `0x268d98..0x269000`: DMA0
  `0x31022000` .. DMA15 `0x31023380`, with SPORT0A `0x31002000` .. SPORT4B;
- the MDMA streams at `0x268cd0..0x268d40`: `0x3102d000/0x3102d080`,
  `0x3102d100/0x3102d180` and `0x3102d200/0x3102d280`, with `0x3102e000` and
  `0x3102f000`.

These are the ADI drivers' full tables, not a list of the channels in use.
Descriptors are built at run time by `0x1ca58a` and submitted by `0x1ca7e4`
(digikit finding 06). Their `ADDRSTART` values are passed in as immediates or
data, and every one resolved so far is in block 0 or at the start of block 1:

| what | buffers | source |
|---|---|---|
| output rings A-D (TX, `CFG 0x00100000`) | `0x261cc8..0x261ec8`, `0x261ec8..0x2620c8`, `0x262138..0x263138`, `0x263138..0x264138`; heads `0x2620c8`, `0x262100`, `0x264138`, `0x264170` | digikit 06 |
| the ColdFire link receive ring | `0x264220/0x265220` and `0x266220/0x267220` (`command_word`), lists `0x2641b0/0x2641cc`, `0x264204` | digikit 04, lane G1 |
| receive descriptor | `0x268220`, `ADDRSTART 0x268240`, 1,025 words -> `0x269244` | digikit 06 |
| per-block frame and audio pages (sw `0x1c9e76`) | `0x2c0478 + (page << 8)`, `0x2c0678..`, `0x2c08e8 + (page << 11)`, `0x2c18e8..` | the driver's own listing; ends before `0x2c2100` |

**Against our spans.** No data word anywhere in the image names m5c's block-1
region `0x2dd600..0x2e7000` in byte, `0x28`-alias, normal-word or short-word
form.

- The only alias-form hits, `0x282e9f08`/`0x282e9608` (L2 `0x20015758`,
  `0x200158c0`) and `0x282e00b8`, decode as instruction bytes: e.g. sw `0xb8abac`
  is `dm(0x2e, i7) = s0`, and `0x2838d064` is a `cjump` word.
- Block 2 has no hits either, so ONESHOT's `0x30a000..0x317df8` is equally clear.
- Silicon agrees where it has been tested:
  - D2's absolute state at `0x301000..` survived every block;
  - D3's always-running loop at byte `0x2dda00..0x2ddd00` survived every block
    until the trig.

  Neither would hold if a DMA ring swept those addresses.

**Limit.** A descriptor whose `ADDRSTART` is computed at run time, for example a
heap-allocated MDMA copy, cannot be excluded statically. No such descriptor is
known, and every resolved one lands in block 0 or below `0x2c2100`.

**Consequence for D5b.** The reader's code at byte `0x2dd600..0x2dd75e` is executed
there only at its entry (`I4 = R4`, then the patched jump) and in its return
sequence. A corruption of the reader's middle would pass D5b and fail only in D3.
So "D5b plays, D3 dies" would point at the reader's body **or** at what lies in the
middle of the span. A cheap check then is **D5c**: D3 with the reader moved again,
to the directory padding (byte `0x2de800`). The DMA reading predicts no change.

## D5a on the instrument (owner, 2026-09-27): dies, so the cause is in the loop's tail

D5a (`waverider-disc-m5c-nocall`) never calls the reader, and it still dies at the
trig. Steps 1-2 play. **The cause is in the loop's tail**: the 73 instructions from
sw `0x16ed73` to the call, which run once a type-5 track's record holds type 5.
D5b is not needed.

### 1. FP-exception interrupts: not enabled (static). Illegal opcode and parity are, and both are fatal

**The IVT** (L1 `0x28240000`, 32 vectors of 4 x 48 bits). Its slots follow the
SHARC+ PRM Table 4-46 (digikit's `IVT_VECTOR_NAMES`):

| vector | name | slot holds |
|---|---|---|
| 0 | EMUI | `jump 0xb8b546`: records error `0x507` and the return address at `0x26ef88..0x26ef94`, then `jump 0x1c07c6` |
| 1 | RSTI | `jump 0x1c12e2` (the entry) |
| 3 | **PARI** (L1 parity) | `jump 0xb8b57c`: records `0x502` and PCSTK, then `jump 0x1c07c6` |
| 4 | **ILOPI** (illegal opcode) | `jump 0xb8b560`: records `0x501` and core MMR `0x300ec`, then `jump 0x1c07c6` |
| 2, 9, 10, 16-19 | reserved | `RTI` x 4 |
| 5-8, 11-15, 20-31 | the rest, incl. **FIXI 23, FLTOI 24, FLTUI 25, FLTII 26** | `jump 0x1c0a70 (db)`, with the vector's dispatch id in the delay slot (the ADI dispatcher) |

**Who sets IMASK.** Bits are set only through the routine at sw `0xb8b5b0` (and
`0xb8b598` for SEC ids). It takes an id whose top byte is the IMASK bit and indexes
a table of `bit set imask 1 << n` at sw `0xb8b60e..`. Its callers pass:

| call site | id | enables |
|---|---|---|
| `__start` sw `0x1c13c7` | `0x04000001` | bit 4, **ILOPI** |
| `__start` sw `0x1c13d1` | `0x03000000` | bit 3, **PARI** |
| sw `0xb8b3b8` | `0x1600000d` | bit 22, TMZLI |
| sw `0xb8b3dd` | `0x1f000016` | bit 31, SFT3I |
| sw `0xb8b4a5` | `DM(0x26ef84)` | the RTOS's own run-time id |
| sw `0xb8cee4` (via `0xb8b598`) | an argument `<= 0xffff` | a SEC id, not IMASK |

No call passes 23-26. Startup clears IMASK first (sw `0x1c0e79`). **The
FP-exception interrupts are not enabled.** A `TRUNC` or `FIX` of a NaN sets only
the sticky flag, so the FP-exception hypothesis is **not supported**.

**What is enabled and fatal**: an L1 parity error (PARI) and an **illegal opcode
(ILOPI)**. Both record an error code and jump to `0x1c07c6`, which never returns:
the DSP stops, permanently, which matches every failed build.

- The strict memory run found no read of never-written L1 from our code, which
  speaks against PARI.
- ILOPI is exactly what our three toolchains cannot see: an encoding selas emits,
  and selmap and digikit both accept, that the silicon rejects.

### 2. The tail's trig path, instruction by instruction

The full listing is `scratchpad tail_d5a.txt` (D5a's section 7, digikit
boundaries, selmap text). Shape counts are for normalised shapes in the
31,102-instruction stock corpus.

| sw | encoding | instruction | input | can fault / set a flag on silicon | in stock? |
|---|---|---|---|---|---|
| `16ed73..16ed9d` | 14a, 17, 2a_short, 6b, 2c | t, reader block, 146t | state, constants | no (fixed-point, no overflow for t <= 15) | yes |
| `16eda0`, `16eda2` | 15b | read WAV1/TBL1 words | frame copy `0x25c568..`, 4-aligned | no | yes |
| **`16eda7`** | 2a `000120004705` | **`if eq r5 = lshift r4 by r7`** | | **a conditional shifter op: no stock example** | **0** |
| **`16edaa`** | 2a `200120004704` | **`if ne r4 = lshift r4 by r7`** | | same | **0** |
| `16edad..16edb8` | 17, 2c, 6b, 14a, 2a_short | masks, slot, `compu` | | no | yes |
| **`16edba`** | 2a `220100001121` | **`if ge r1 = r1 - r1`** | | conditional ALU sub; stock has only `if le`, `if lt`, `if not sz` forms (e.g. `b86f23` `040100000220`) | shape rare; this cond never |
| `16edbd..16edd2` | 6b, 17, 2a_short, 15b | directory, POS | | no | yes |
| `16edde` | 15b | `r8 = dm(0, i1)`, the note | note cell `0x254b14 + 4t` | no | yes |
| `16ede3`, `16ede6` | 2a_short | `f8 = min(f8, f12)`, `f8 = max(...)` | note | on NaN: result NaN, sticky only | yes |
| `16ede8` | 2a_short `8c0180d0` | `r0 = trunc f8` | | NaN/overflow: sticky invalid (FLTII not enabled) | yes (exact) |
| **`16edea`** | 2a_short `8c0100a1` | **`f1 = float r0`** | | **no stock example of a standalone 32-bit FLOAT without BY**: stock uses FLOAT with BY (35 x `8d01...`), or FLOAT paired with a move (4a/5a) | **0** |
| `16edec..16edfe` | 2c, 6b, 17, 2a_short, 15b | fr, T[k], T[k+1], interpolation | pitch table | on NaN: sticky only | yes |
| `16edff` | 2a_short `8c0110d1` | `r1 = trunc f1` | | sticky only | yes |
| `16ee01..16ee0a` | 15b, 14a | reader-block writes | | no | yes |

**What the note cell holds on a real trig.** It is a float written by the frame
unpack from the 16-bit header field `NOTE + 2t` (note << 8 | fine), as note +
fine/256. The per-track init (sw `0x1c8bb7..0x1c8bbd`) stores `0x42700000` = 60.0
there.

- The captured ColdFire frames (init, WAV1 max, TBL1 1, note, screens) all carry
  NOTE = 0 and trigger mask 0: no played note was ever captured.
- The runner fed `0x3C00` (60.0), `0x4800` (72.0) and `0x3C80` (60.5).
- Either way, the value is **a conversion of a 16-bit integer, so always finite**.

The pitch path cannot see a NaN, and none of its conversions can overflow. That
agrees with part 1: the pitch path is an unlikely culprit, and the three shapes
with no stock example are the likely ones.

### 3. M5d: `waverider-m5d_DN2_1.11.syx`

M5d is built from `fix/waverider-dsp-silence` with `main` merged in (PRs #135-#139,
including the menu fix), via `dnfw mods apply --mod waverider`. It is
**byte-identical** to the file in `00_Resources/02_Builds/`:

- section 3 sha256 `85debe72...`, the same as m5b's, so `emu_boot_check` is not
  needed;
- section 7 sha256 `b13a1362e973b50e...`, 876,492 bytes;
- `dnfw inspect` 21/21.

Its changes, all in our code:

- **No conditional computes.**
  - The WAV1/TBL1 halves are chosen with `IF NE JUMP` (the form D2 proved) and
    unconditional `lshift ... by r7`.
  - The slot clamp is `IF LT JUMP` around `r1 = r1 - r1`.
- **The note is validated in the integer domain before any float operation.** An
  exponent field of `0xff` (NaN, Inf) or a set sign bit gives +0.0, by `lshift`,
  `and`, `comp`, `pass` and conditional jumps. Then come `min` with 127.0 and
  `trunc`. The float `max` is gone: the value is already >= 0.
- **`f1 = float r0 by r12`** (with r12 = 0) replaces `f1 = float r0`: the FLOAT
  shape the stock code uses.
- In the reader, **`r2 = r2 - r3`** replaces `r2 = r3 xor r2` (shA = 16 - shB, the
  same value).
- The loop is 800 bytes and the reader 348. Both keep at least 64 zero bytes in
  their spans.
- Every absolute target is re-resolved from selas's layout by the new
  `scripts/sharc_resolve_jumps.py`, which reads the `// -> label.` comments.

### 4. `waverider-disc-m5c-constpitch_DN2_1.11.syx`

M5d's loop with the pitch block (the note read, validation, `min`, `trunc`,
`float` and the interpolation) replaced by the constant increment for note 60
(`R1 = 23409860`): no conversion and no float operation. It otherwise has no novel
shape. It passes `dnfw inspect` (21/21). Built by
`scripts/build_waverider_disc_scratch.py --variant constpitch`.

| M5d | constpitch | reads as |
|---|---|---|
| plays, and the saw sounds | | fixed: it was one of the removed shapes (most likely ILOPI) |
| dies | plays | the pitch path (the note read or conversions), against the reading above |
| dies | dies | neither the novel shapes nor the pitch: next, the frame-copy and directory reads |

### M5d and constpitch: gates (2026-09-27, digikit `6f812e9`, after `main` was merged)

| gate | result |
|---|---|
| `test_waverider_dsp.py` | 17 passed |
| `sharc_waverider_m5.py --blocks 8 --tag m5d` | **PASS 23/23** (617 s): decode 0 disagreements (selas, digikit, selmap); machine tap **0 float32 mismatches** in all five runs; amp out peak 0.0665; note 72 inc ratio 2.0; types 0-4 bit-identical to stock; 155,025 instructions a block |
| the same, on the ColdFire's init frame (`--tag m5d_cfinit`, selmap skipped) | **PASS 26/26** (803 s), step 5 bit-exact |
| strict memory map, constpitch, 3 blocks with a type-5 trig | returns every block; **0** violations from our code |
| `dnfw inspect` | m5d 21/21; constpitch 21/21 |
| m5d section 3 | `85debe72...`, identical to m5b's; built from the merged source by `dnfw mods apply --mod waverider`, and byte-identical to the file in `02_Builds` |
