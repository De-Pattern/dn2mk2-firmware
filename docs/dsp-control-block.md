# The ColdFire's control block for the SHARC, and how the audio slots are chosen

**Read 2026-09-20**, continuing from `docs/audio-dma.md`. That note identified
the audio crossing — SSI0, eDMA channels 48 and 50, two double-buffered windows
in 64-byte TDM frames. It left one thing open: **which slots of the frame the
audio uses.** The answer is that they are not fixed. They are read out of a
shared SRAM block, and that block is fed from the instrument's own settings and
from the kit.

## Three layers, not one link

| layer | mechanism | where it is read |
|---|---|---|
| boot | DSPI upload of section 7 | `docs/for-digikit-coldfire-sharc-link.md` §1 |
| control | a shared SRAM block at `0x80005xxx`, pushed periodically over the same DSPI | that note's §3, and this one |
| audio | SSI0 + eDMA 48/50, `0x4E6DF100` in, `0x4E6E0100` out | `docs/audio-dma.md` |

The three were easy to confuse, and §3 of the for-digikit note explicitly
wondered whether its periodic ~2.7 KB DSPI push carried audio. It does not: the
audio has its own path, and what the DSPI push carries is the block below.

## The slots are configuration, not constants

The engine writes into the transmit window through **indices it loads from
SRAM** (`0x40025f9c`):

```
0x40025f9c  tstb 0x80005366          ; enabled?
0x40025fa6  d0 = the half (0 or 1)
0x40025fac  mvs.b 0x80005368,%d1     ; one slot index
0x40025fba  mvs.b 0x80005367,%d2     ; the other
0x40025fb8  d0 <<= 9                 ; half * 512 longwords = 2,048 bytes
0x40025fc6  d1 += d0 ; d2 += d0
0x40025fca  d1 <<= 2 ; d2 <<= 2      ; longwords -> bytes
0x40025fd0  d2 += 0x4e6e0100         ; the window
```

So a stream's position in the frame is `window + ((half << 9) + slot) * 4`, and
**`slot` is a byte in the control block**. `0x80005366` enables the pair,
`0x80005367` and `0x80005368` are its two slots — a stereo pair whose place in
the TDM frame is assigned at run time.

## What writes those bytes

`0x40025982` is the applier: given two longwords it sets `0x80005362`–
`0x80005368` by cases —

- `0x80005366` / `0x80005367` / `0x80005368` from the first argument: `(1,0,1)`,
  `(0,0,1)` or `(0,·,·)`, i.e. enable plus the pair's two slots;
- `0x80005362`–`0x80005365`, four bytes, from `arg & 3`: `(1,0,0,1)` in the zero
  case, other shapes for 1 and 2. A second stream's four slots, or a second
  pair plus flags.

Its single caller `0x40025a5c` takes them **straight out of an object**:

| source | destination | clamp |
|---|---|---|
| `obj+248` | `0x80005361` | 0..2 |
| `obj+252`, `obj+256` | the applier's two arguments | — |
| `obj+260` | (next field) | 0..3 |
| `obj+36`, `obj+40` | `0x80005218`, `0x8000521c` | — |

Small integers clamped to 0..2 and 0..3, written straight through to the DSP's
control block: that is a **menu enum reaching the DSP**, which is what a routing
setting looks like from this side. The object is not identified yet, and it is
not called one here.

A second setter, `0x40025b76`, fills three more fields from a **much larger
object**:

```
0x40025b7c  pea %a2@(23840)      ; passed to 0x4002a5c2 first
0x40025b88  0x8000536c <- [a2 + 23762]   (long)
0x40025b92  0x80005370 <- [a2 + 23766]   (long)
0x40025b9a  0x8000537c <- [a2 + 23770]   (word)
```

**A kit is 23,921 bytes** (`docs/lfo4-build-plan.md` §8), which puts `+23,762`
in its last 160 bytes — consistent with these being kit-level fields, and worth
saying only that far. What is certain is that per-kit state reaches the DSP
through this block.

## Why this matters

- **For the DSP work:** the interface is now three named layers instead of one
  unknown, and the audio's frame layout is configurable state we can read rather
  than a constant we would have had to guess.
- **For backlog §17, the performance mixer:** routing settings and kit fields
  reaching the DSP through a readable block, with per-stream slot assignment, is
  the mechanism that idea needs. §17 assumed the per-track split lived in
  section 8; it does not, and this is where it actually goes.
- **For anyone reading the DSPI stream:** its payload is this block, so a
  capture of the stream is a capture of these fields.

## The block's shape, counted rather than guessed

`scripts/sram_field_map.py` walks the section for absolute-addressing
instructions naming an address in a range and reports, per address, the width,
the direction and the sites. It decodes the MOVE family properly -- a move's
destination is stored reg-then-mode, the reverse of its source -- so it tells a
read from a write, and it prints anything it cannot name as `?` with the opcode
word rather than dropping it.

    python scripts/sram_field_map.py <image> 0x80005340 0x800053e0

Over `0x80005340`-`0x800053e0` on 1.11: **30 addresses, 133 sites.** The shape
is a struct, and the widths separate it into three kinds of field:

| range | width | what the counts say |
|---|---|---|
| `0x80005360`-`0x8000536b` | **byte** | twelve one-byte fields, each written from one or two sites and read from one or two. The slot indices and enables above live here |
| `0x8000536c`-`0x80005380` | long / word | six fields written from the kit-side and settings setters |
| `0x80005394`-`0x800053a0` | long | the busy end: `0x80005398` alone has **22 reads and 5 writes** |
| `0x800053a4`, `0x800053ba`, `0x800053c0` | -- | only ever taken as addresses (`pea`/`lea`): buffers, not fields |

### `0x80005394` and `0x80005398`: a region, and a pointer into it

All 27 sites of `0x80005398` were read. The two halves looked like they
disagreed, and the field beside it settles them.

**Consumed as an address.** At `0x40025ee0` it is loaded with `movea.l` and then
indexed -- `lea %a0@(0,%d0:l:2),%a0` -- and the result stored as a working
pointer. At `0x400268b4` it is read, **90,000** added, and pushed as an argument
to `0x40138b5c`; the *other* branch of that same `if` builds the same argument
from `[%a1+4]`, a genuine pointer out of a structure, plus the same 90,000. Two
branches producing one argument, one of them unambiguously a pointer.

**Produced as an accumulator.** Its five writes are all in the transport
cluster, and the one at `0x400d98a8` is plain:

```
0x400d98a2  lea 0x42c4e900,%a0
0x400d98a8  movel %a0@,0x80005398        ; the block gets the current value
0x400d98ae  movel 0x42c4e900,%d0
0x400d98b4  addil #900000,%d0            ; and the source advances by 900,000
0x400d98ba  movel %d0,0x42c4e900
```

`0x42c4e900` is one of four longwords (`+0`, `+4`, `+8`, `+0xc`) that the
`0x400d7xxx`-`0x400dAxxx` transport code works over -- 51 sites between them --
and several of those sites *add* it to something rather than dereference it.

**Resolved by a bounds check** (`0x40027b32`), which names the size:

```
0x40027b32  cmpil #899999,%d0          ; d0 below the region?
0x40027b38  blss <reject>
0x40027b3a  moveal 0x80005394,%a0      ; the neighbouring field: a BASE
0x40027b42  subal %a0,%a1              ; a1 = d0 - base
0x40027b44  cmpal #900000,%a1
0x40027b4a  bhis <reject>              ; unsigned: reject unless 0 <= d0 - base < 900,000
```

So **`0x80005394` is the base of a 900,000-byte region and `0x80005398` is a
pointer into it**, validated against exactly that window. The two halves stop
disagreeing: the "accumulator" writes are pointer arithmetic inside the scheme —
`0x400d98b4` steps to the next 900,000-byte block, and the two writes that
compute `base + delta` do so with **interrupts masked to IPL 7**
(`movew #9984,%sr` at `0x400d81ca`), which is what a write pointer shared with
an interrupt handler needs. The fixed **90,000** — a tenth of the region — is
used as an offset at four sites, one of them inside the modulation kernel
(`0x400db4e8`).

**Still not named:** what the region holds. 900,000 bytes is 225,000 longwords,
and the frame the audio path uses is three longwords wide, but nothing read here
connects the two, and the arithmetic that would settle it has not been found.
The constant appears at **12 sites** across the transport and engine, so
whatever it is, those subsystems share it.

## Not read

- **What the 900,000-byte region holds**, per above.
- The fields at `0x80005348`, `0x8000539c` and `0x800053a0`, and where
  `0x42c4e900`'s four longwords are initialised.
- **Which slots**, in practice: the applier writes small constants, but nothing
  here enumerates the frame's sixteen slots or says which carry per-track
  audio — if any do.
- The identity of the `obj` at `0x40025a5c`, and whether `a2` at `0x40025b76` is
  the kit or something that contains it.

## Reproducing

```
dnfw disasm <image.syx> 0x40025f60 120      # the slot arithmetic
dnfw disasm <image.syx> 0x40025982 130      # the applier
dnfw disasm <image.syx> 0x40025a5c 80       # where its arguments come from
dnfw disasm <image.syx> 0x40025b76 60       # the kit-side setter

python scripts/sram_field_map.py <image.syx> 0x80005340 0x800053e0
```
