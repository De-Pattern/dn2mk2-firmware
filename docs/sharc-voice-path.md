# The SHARC voice path on DN2 1.11, and where a track becomes a voice

**Opened 2026-09-25.** The ColdFire side is finished: four stages measured,
all four track-indexed, LFO4 writing its destination every frame
(`docs/lfo4-build-plan.md`, final section). The voice gate the owner measured --
modulation audible only when the voice index equals the track index -- is
therefore **downstream of the ColdFire**. This document is the SHARC side.

## The bytes are the same bytes

digikit's finding 11 records a DN2 1.11 section-7 blob SHA-256 of
`336e340a...3115e2`. Extracting section 7 from our own
`Digitone_II_OS1.11_dist.zip` gives **exactly that hash**. So every DN2 1.11
address in their findings applies to our image with **no translation**, and this
document can cite them directly rather than re-deriving them.

That check is the reason to trust anything below. Two products, two extraction
paths, one hash.

## The chain, confirmed in our own database

`tools/sharcdb.py` from digikit (GPL-2.0; run as a tool, which entangles
nothing -- `docs/references.md`) builds a DN2 1.11 database in 41 s:
**1,157 functions, 142,921 instructions, 8,611 edges**. digikit reports 1,156
functions for this image; the one-function difference is unexplained and
recorded rather than smoothed over.

```
sw 0x1c9e76                      (159 instrs; matches DT2 FUN_1c75d8 by hash)
  |
  +-- 0x1c9fbc CALL --> sw 0x1c2712
                          |  DO 0x1c2ca1 UNTIL LCE at 0x1c2937, trip count 16
                          |  ** the per-TRACK loop **   (= DT2 FUN_1c2b24)
                          |
                          +-- 0x1c3044 CALL --> sw 0x1c8ef1
                                                 1,352 instrs (= DT2 FUN_1c642a)
                                                 ** the per-SLOT / voice dispatch **
                                                   |
                                                   +-- JUMP IF SZ 0x1c99a8 --> sw 0x1c9b73
```

Every edge above was read back out of our own build of the database, not copied
from the finding.

## The boundary: what the track loop hands the voice dispatch

```
0x1c3038  R12 = 0x257e6c
0x1c303b  R8  = 0x2554b8
0x1c303e  R4  = 0x241298
0x1c3041  I5  = modify(I4, 0x922)     [raw-byte offset]
0x1c3044  CALL (linked, delayed) target=0x1c8ef1
```

and the callee's prologue consumes them:

```
0x1c8f18  R2 = pass(R4); I4 = R8
0x1c8f1d  I9 = R2
0x1c8f1f  I5 = I9
```

So **`0x241298` arrives in R4 and becomes the walked base pointer `I9`/`I5`**,
and `0x2554b8` becomes `I4`.

**`0x241298` is NOT yet identified as the voice record array.** DT2's voice
record contract is 32 records at `0x2412cc`, stride `0x1d8` -- numerically close,
which is exactly the kind of resemblance this project has been wrong about
before. Against it: **`0x1d8` does not appear anywhere in `sw 0x1c8ef1`**, so if
these are records here, the stride differs. Marked **[O]**, open, until the
stride is read out of the body.

## A lead for new machines, and what would confirm it

Inside the 16-track loop:

```
0x1c293a  R2 = DM(I5 + 16), long        | a per-track word
0x1c2942  R1 = ashift(R1, R13); R8 = M5
0x1c2947  R2 = max(R2, R8)              | floor
0x1c294a  R0 = 0x4
0x1c294c  R2 = min(R2, R0)              | ** ceiling of 4 **
0x1c294f  R2 = lshift(R2, 9)            | x512
0x1c2952  I3 = R2
```

A per-track value clamped to `0..4` and multiplied by 512 to index something is
the shape of a **machine-type selector into a table of five 512-word records**.

Two independent things agree with it, which is why it is worth recording:
digikit note DN2's **"stage A bound is 5, not 6"** where DT2's is 6; and the
DN2 II front panel offers a small number of synth machines, so a ceiling of five
slots is the right order.

**This is [D] -- one structural read, no control.** What would settle it: find
the table at `I3`'s base and check it has five entries; and check whether the
ColdFire side's machine list has a matching bound. digikit's own open question
is the mirror of this one -- *"which ColdFire code limits the machine list to
7 types"* on DT2 -- so the two halves can be answered together.

**It is not yet evidence that a sixth machine can be added.** A ceiling tells
you where the wall is, not that it is the only one.

## The resemblance is dead: there is no `0x1d8` record stride here

`sw 0x1c8ef1` never strides `I9`/`I5` by a record size. It applies **field
offsets to one structure**: `+0x74`, `+0x230`, `+0x358`, `-0x228`, `-0x18c`,
`-0x11c`, `-0x9c`, plus `I4 = modify(I5, 0x1380c)` and
`I10 = modify(I9, 0x13ea0)` in PM. And `I5` is repeatedly re-based from saved
stack slots (`DM(I6-24)`, `-29`, `-31`).

So **`0x241298` is not a 32-record array of stride `0x1d8`**, and DT2's voice
record contract does not transfer to DN2 as written. ~~`0x241298` is the DN2
voice record array~~ -- withdrawn before it was ever relied on. The numerical
closeness to DT2's `0x2412cc` was a coincidence of layout, which is exactly what
this project has twice mistaken for a finding.

The 16-track loop itself streams: loads through `I5` with M-register
post-modify, stores through `I4` with M-register post-modify. **No track-indexed
addressing is visible in it at all** -- it is a sequential unpack, not an
indexed scatter.

## The control nobody has run, and it outranks more SHARC reading

Here is a question this project has never asked, and it is embarrassing that it
has not:

> **Does a stock LFO modulating the same destination also fire only on one
> voice?**

Everything about the "voice gate" rests on LFO4's behaviour, observed alone. On
2026-09-25 the owner pointed **LFO1** -- stock, known-good -- at the same
destination (`Syn Ratio C`, mirror slot 26 of track 7) to control a *probe*
address. Nobody checked **which voices it sounded on.**

Both LFOs write the same mirror slot, and the frame builder copies slots 25..99
per track. **The DSP cannot tell them apart.** So:

- **LFO1 sounds on every voice while LFO4 does not** -> the two are *not* both
  reaching the frame, even though both were measured in the mirror. The fault is
  back on the ColdFire, between the mirror and the frame -- and everything on
  this page is a detour.
- **LFO1 also sounds only on voice 7** -> the gate is a property of the
  destination or of how the DSP consumes it, **independent of which LFO
  writes**. LFO4 is then not faulty at all, and "the voice gate" has been
  misnamed since it was opened.

Either answer is worth more than the next week of static SHARC reading, and it
costs one minute at the instrument with no flash.

## Next

1. **Run that control.** It may invalidate the framing of this whole document.
2. Only if the gate survives it: find where a voice's record is chosen and
   whether a track index reaches it.
3. Then the machine ceiling (`min(R2, 4)`, `lshift 9`), still **[D]**.
