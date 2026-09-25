# Notes for digikit's SHARC runner: DN2 1.11, and a program of our own (2026-09-26)

These notes are for digikit's `work/sharc-emulator` branch at `6f812e9`. They
record findings with no change of ours to land, so they are written up here,
not sent as a PR. Our measurement is `docs/wavefinder-feasibility.md`,
"Milestone 1", and `scripts/sharc_wavefinder_render.py` reproduces it. We call
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
