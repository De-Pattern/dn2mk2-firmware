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
