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
