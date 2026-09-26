# Notes for digikit's SHARC runner: DN2 1.11, and a program of our own (2026-09-26)

These notes are for digikit's `work/sharc-emulator` branch at `6f812e9`. They
record findings with no change of ours to land, so they are written up here,
not sent as a PR. Our measurement is `docs/waverider-feasibility.md`,
"Milestone 1", and `scripts/sharc_waverider_render.py` reproduces it. We call
digikit as a tool from a checkout you name, and copy none of its code.

## 1. `Runner` runs DN2 1.11 unchanged

`sharcldr.LoadedMemory.from_stream(section 7)` is all it takes. The DN2 1.11
blob is sha256 `336e340a...3115e2`, the same bytes as your finding 11.

`sw 0x1c0790` is a 13-instruction leaf with three return paths: it removes the
`0x28000000` alias from an address in `0x28240000..0x2839ffff`. We ran it for
11 inputs, including every boundary of its two `compu` tests. All 11 returned at
`sw 0x1c07a6` with the R0 a static reading predicts. selache's `selmap` agrees
with your decoder at every boundary of that function.

## 2. Where DN2 stops from a cold start

We used your CLI on a `dn2-1.11` sharcdb:

| start | halt |
|---|---|
| `0x1c2712` (16-track loop) | 1,673 instructions, then a fork at `0xb8b513` (`GE`; ASTATX AN/AZ/AV unknown, last written at `0xb8b511`), with or without `--explicit-memory-model` |
| `0x1c8ef1` (slot dispatch) | 198 instructions, then a fork at `0x1c909f`. With `--explicit-memory-model`, 247 instructions, then *unsupported full compute cu=0x2 opcode=0x90* at `0x1c4f4a` (2b) |
| `0x1c9e76` | returns after 136 instructions, at `0x1c9e71` |

The forks are the expected result without a booted state. The shifter opcode
`0x90` at `0x1c4f4a` is the first unmodelled operation we met on the DN2 voice
path.

## 3. Type 13a is decoded but not executed

A standalone `DO <end> UNTIL LCE` with the count already in `LCNTR` decodes as
13a and halts with *unsupported form 13a*. Your finding 11 notes that DN2 1.11
uses form 13a, so DN2 code will reach it. The combined `LCNTR = ureg, DO`
(12a_ureg) runs fine.

## 4. Your decoder is the one that matches the firmware, not selas

We assembled our own code with selache's `selas`. Its output disagreed with
your decoder in two places. In both, the firmware sides with you:

- **MODIFY.** selas's 48-bit `MODIFY (I4, M4)` is `0x04240f800000`. The
  firmware's is `0x043f20000000`, and all 497 of DN2 1.11's 48-bit MODIFYs use
  that layout. selas's compressed `MODIFY (I0, M0)` is `0x043e0000`, which
  lacks the `0x3f` width marker that DN2's 37 Type 7b MODIFYs carry (for
  example `0x043f653f`). Your decoder reads it as the start of a 48-bit 7a.
- **Immediate ASHIFT.** selas encodes `ASHIFT R0 BY -31` as `0x023e0020e100`.
  Your decoder rejects it (*unsupported ShiftImm opcode 0x20*), and the
  firmware's immediate ASHIFTs carry a different field there.

We avoided both forms. After that, our 75-instruction program decodes on
exactly the assembler's boundaries, runs, and matches a float32 reference bit
for bit over 48,000 samples. **Your executor ran a program neither Elektron
nor you wrote, correctly.** That is some evidence that its semantics are
general and not fitted to the firmware. It covers the forms that program uses:
5b, 15b, 6b, 17a/b, 2a, 2a_short, 12a_ureg, 5a, 3a/b/c, 9b and 25c.

## 5. Speed, for the record

We measured 45,000-48,000 instructions/s on CPython 3.13, on a machine that
was also running ColdFire emulator boots. That is consistent with your
90-100k figure on an idle machine. We did not try PyPy.

# Part 2: running the DN2 voice path (2026-09-26, Milestone 2)

These sections come from `scripts/sharc_waverider_voice.py` and the
workarounds in `scripts/sharc_dn2_fixups.py`, measured on DN2 1.11 with your
branch at `6f812e9`. With them, the DN2 engine init (`sw 0x1c1445`) runs to
its return and the slot dispatch (`sw 0x1c8ef1`) returns on every block.
Each gap below is something the runner does with your code as it stands. The
workaround is ours and lives in our repository; the proper fix belongs in
yours. **PR candidates are marked.** We have opened none.

## 6. SIMD: PEy is modelled in five forms only (PR candidate)

`_compute_simd` is used by Types 2c and 2a_short, and the memory companion
(`_simd_ureg_mem_companion`) by 14a, 3b and 15a. In SIMD mode every other
form runs PEx only. That covers the compute of 2a, 2b, 1a, 3a, 4a, 5a_move,
6a/6b and the compute-bearing flow forms (8a/9a/11a), and the companion
transfer of 3a, 4a, 4b (normal word) and 15b.

DN2 relies on PEy from the start. Init's first table (`sw 0x1c463b`, a
1024-point sine at `0x8052fbe0`) is built by a SIMD loop: PEx computes the
even samples and PEy the odd ones. Without PEy the odd half stays zero.

Our workaround runs each such instruction twice in SISD:

1. PEy first, on a copy with R<->S swapped (and ASTATX/Y, STKYX/Y,
   USTAT1/2 and USTAT3/4), the transfer address one normal word up, and a
   copy-on-write overlay.
2. PEx on the real state.
3. PEy's registers, its status and, for a complementary register, its
   memory write are merged in.

Init executes about 1.6 million instructions this way. It is a stand-in, not
a model. It ignores MSF/MRF, since the multiplier accumulators are not per-PE
in it, and it does not handle a SIMD branch whose PEs disagree.

## 7. SIMD: `Rn = data32` does not reach Sn (PR candidate; needs the PRM)

Types 17a and 17b write only the named register in SIMD mode. The firmware
assumes both PEs get the value. The same sine loop loads its constants in
SIMD with `R1 = 0x3f000000` (0.5) and `R12 = 0xfff6` (-10), then reads PEy's
copy back through a companion load.

**Control:** with the PEy copy, the table equals sin((k + 0.5) 2pi/1024) at
all 1024 entries, max error 3.9e-7. Without it, the odd entries are off by up
to 1. We have not found the PRM sentence for this, so the rule is inferred
from the firmware, not cited.

## 8. (LW) pairs in Types 4b and 3b

For (LW), `_type_4b` and `_type_3b` compute an 8-byte width and call
`_dm_read(..., 8)` / `_dm_write(..., 8)`. By design those return None and
False. So a long-word load reads Unknown and a long-word store writes
nothing. Types 3a, 14a, 15a and 15b already handle the register pair
(`_lw_load_codes`, `_lw_store_pair`); 4b and 3b only need to call the same
helpers.

DN2 init does 336 long-word 4b loads and 124 stores, plus 8 of each in 3b.
The first is at `0x1c45f1`, in a peak search over the sine table. Its load
reads Unknown, the loop's running max goes Unknown with it, and the run forks
at `0x1c4610`.

## 9. L1 normal-word addresses read as byte addresses (PR candidate)

The math library (`sw 0x1c0efe`, `sw 0x1c10e3`, ...) loads coefficient
pointers such as `I1 = 0x90119` and walks them with `M6 = 1`. `0x90119` is
an L1 normal-word address. Its byte image, `4 x 0x90119 = 0x240464`, is where
the loaded image holds 1/pi, a Cody-Waite split of pi and the sinf polynomial
(`0x3ea2f983, 0xb715777a, ..., 0xbe2aaaa4`). The runner treats `0x90119` as
a byte address and reads zeros, so `sinf(x)` returns `x`. Every table init
built from sin came out as a ramp.

Our workaround multiplies an NW immediate loaded into an I register by 4. It
applies to `0x90000 <= v < 0xe8000`, the NW image of the L1 byte range
`0x240000..0x39ffff` that `sw 0x1c0790` names. With it, sinf in the runner
agrees with float32(math.sin) to within 1 ulp on 58 inputs, in 35
instructions.

The proper fix is an address-space model: an NW address maps to 4x in byte
space, and a DAG step on an NW pointer is one word, not four bytes.

## 10. Type 2b shadows the 16-bit Type 2c (PR candidate: the decode table)

`Type2b` (mask `0xff80`, value `0xc000`) and `Type2c` (mask `0xf000`, value
`0xc000`) both match a first parcel in `0xc000..0xc07f`, and 2b wins. At all
three places we checked, the parcel is a 16-bit 2c. Reading it as 32 bits
throws every later instruction off its boundary:

| image | sw | parcel | selache reads | and what follows |
|---|---|---|---|---|
| DN2 1.11 | `0x1c0e13` | `0xc020` | `r2 = r2 + r0` | `r0 = 0x14057b7e; r2 = r1 + r0 + ci; ...; rframe`: the high word of the PCG increment `0x14057b7ef767814f`, then a 64-bit add with carry |
| DN2 1.11 | `0x1c4f4a` | `0xc029` | `r2 = r2 + r9` | `r0 <<= 8; r2 <<= 8; r2 += r0; ...; r14 = min(r2, 0x7f0000)` |
| DT2 1.16 | `0x1c32ab` | `0xc011` | `r1 = r1 + r1` | `r0 = r15 + r1; r2 = r2 + r1; r12 = 0x252df8; ...` (0x252df8 is your `TRACK_MIX_BASE`) |

In each case your decoder agrees with selache again from the next boundary on.

This rewrites two earlier stops:

- **`0x1c4f4a` is not an unmodelled shifter op** (Part 1, section 2). It is
  this misdecode.
- **Your provisional `21p_undoc16` at `0x1c32b0` and `8p_undoc48` at
  `0x1c32b4`** come from the same misread at `0x1c32ab`. That code computes
  track-mix addresses from `0x252df8`, which may bear on the per-track
  accumulate you currently inject by hand.

We do not know the architectural rule that separates 2b from 2c. DN2 has 31
decoded 2b. The two above are the only ones in code blocks; the other 29 sit
in block 57 (`0xb8f69a..0xb96bc4`), which decodes like data. A rule that sends
all three sites to 2c would be the fix, and the PRM figure for Type 2b is the
place to look.

## 11. Conditional Types 6a/6b halt

`_type_6b_shiftimm` and `_type_6a_mem` stop on any condition other than
"always" ("unsupported Type6b predicate"). WaveTone's oscillator 2
(`sw 0x1c43ca`) has one at `0x1c4470`. Our workaround evaluates the predicate
and either runs the form unconditionally or skips it (64 times a block).

## 12. SIMD predicates on EQ/NE

In SIMD mode `_predicate` returns None for EQ/NE ("does not yet model the
companion PASS"), so a SIMD conditional compute forks. An example is
`IF EQ R12 = M7` at `0x1c0716`, inside the divide helper. `_predicate_pe`
already exists, and the per-PE conditional compute of section 6 makes this
one go away.

## 13. Not needed on this path, and still open

- **Type 13a** (Part 1, section 3) did not come up on this path.
- **WaveTone's 2:1 decimator `sw 0xb8286b`** (fixed point, MR MACs). Run
  alone from a zero state, it is linear and stable: an impulse of 2^24 decays
  by a factor of -0.716 a sample. Called from the WaveTone render in a real
  block, it ends a block of zero input with non-zero state (`state + 26..29`).
  From the second block on it emits a steady ±113, ±81, ±58... pattern, which
  the render clips to ±1 at Nyquist. We have not found why. Two suspects: the
  multiplier result registers under our SIMD stand-in (section 6), and the MR
  data moves.
- **Speed.** With the SIMD two-pass, init is 5.0 M instructions in 840-1,100
  s, depending on the machine's load. That figure includes two accelerations of ours, each checked against the
  emulated code: sinf computed as float32(math.sin), and the 12,819
  additive-synthesis loops of `sw 0x1c463b` computed natively. Emulated in
  full, those loops are about 90 M instructions, around 1.7 hours. One
  dispatch with only track 0 active is about 54 k instructions, about 3 s.
