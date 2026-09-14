# Cross-check against an independent SHARC+ reverse-engineering account

A write-up of a SHARC+ Chorus reverse-engineering effort on Digitone II 1.10E
reached this project on 2026-09-14, from someone who reports having built a new
chorus FX and modified song mode. It is written as a method paper, not a claim
sheet, and several of its statements are checkable against images we hold.

They were checked. This file records what agreed, what did not, and what we
changed as a result — including one change of ours that turned out to matter far
less than the argument for it suggested.

## 1. What their account gets exactly right

Every figure below was recomputed here from `Digitone_II_OS1.10E_dist.zip`
through our own container, depacker and boot-stream walker, which share no code
or lineage with theirs.

| their claim | ours |
|---|---|
| section 7 decompresses to **833,060 bytes** | 833,060 |
| SHA-256 `174b391822bbe33a99e5f42bd02ef3ea75c0e79351caae6ba90e4cd2c4de5350` | identical |
| **96 LDR blocks** | 96, walk complete, ends exactly on the last byte |
| the `final` block gives entry point `0x001C12E2` | the final block's target is `0x001c12e2` |
| a block targets `0x283825C4` | yes — 20 bytes at that address |
| `"Audio Task"` is a landmark string | present, exactly once |

**Two independent toolchains agreeing on a SHA-256 is the strongest single
corroboration this project has received from outside.** It validates the whole
chain — SysEx transport, ELE3 container, aPLib depack, boot-stream walk — end to
end, from code that has never seen ours.

Our block count for **1.11 is 95**, not 96. That is a version difference, not a
disagreement; their work is on 1.10E.

### The entry point, and a detail worth writing down

`0x001C12E2` is a **VISA address in 16-bit halfwords**, and the final block's
`target` field carries it directly rather than a byte load address:

    0x001C12E2 * 2 + 0x28000000 = 0x283825C4

`bootstream.entry_point` returns that field raw, so a reader who assumes it is a
load address will be wrong by a factor of two and a base. Noted here because
nothing in that module said so.

## 2. The one discrepancy, and it is theirs

> "`0xC7C0` in the decompressed stream maps into the block targeting
> `0x283825C4`."

It does not. In our walk `0xC7C0` sits inside the block targeting `0x28268a40`,
and the block targeting `0x283825C4` begins at file offset `0x5CF84`.

What `0xC7C0` actually is: **the file offset of the `"Audio Task"` string**,
exactly. Two true facts appear to have been merged into one false sentence. Both
halves check out separately.

## 3. Their address rules, against ours

They give two linear maps:

    0x28000000 region:   load = 2 * visa + 0x28000000
    0x20000000 region:   load = 2 * visa + 0x1E900000

Ours (`scripts/sharc_callgraph.py`) matched on the target's top byte instead —
`0x1C` for the first space, `0xB8` for the second — and masked the second to 16
bits. **Where both apply they agree on every address tested**, including the
entry point and all five chorus addresses in their §8.

The masked form is nevertheless wrong in principle, and measurably so: each
space spans several 64K VISA pages, not one.

| region | VISA range | pages |
|---|---|---|
| `0x20000000 .. 0x200872fc` | `0x00B80000 .. 0x00BC397E` | `0xB8`–`0xBC` |
| `0x28240000 .. 0x2839bff8` | `0x00120000 .. 0x001CDFFC` | `0x12`–`0x1C` |

`exec_to_load` now doubles the target and tries both biases, keeping whichever
lands inside a span the image actually loads. **The image is the oracle**, so a
target resolving in neither space is genuinely unresolvable rather than merely
outside a page someone hardcoded.

### What the correction was worth: almost nothing

| image | call sites | old rule | new rule | functions |
|---|---|---|---|---|
| 1.10E | 1,621 | 1,620 (99.9%) | 1,621 (100%) | 459 → **460** |
| 1.11 | 1,606 | 1,606 (100%) | 1,606 (100%) | 461 → **461** |

Zero disagreements where both resolve. One extra call site and one extra
function on 1.10E; nothing at all on 1.11.

**[CORRECTION — mine, 2026-09-14.]** The argument for making this change was
that our rule "silently returned `None` for 35.9% of L2 targets". That figure is
wrong, and wrong in a way this project keeps repeating. It came from scanning
*every 24-bit field* in the L2 image whose top byte fell in `0xB8..0xBC` — a
proxy for call targets, not call targets. Real `cjump` targets almost all sit in
the `0xB8` page, so the masked rule was very nearly right in practice.

The fix is kept because it is correct, general and self-checking. But it was
sold on a measurement of the wrong population, and the honest headline is
**+1 call site**, not +36%.

## 4. Where our results differ from theirs, in our favour

> "Section 7 has virtually no spare compressed space. The method does not
> naively recompress the entire stream: a surgical token-level patcher decodes
> the compression tokens, applies an exact list of changed bytes, and then
> optimizes only the affected literal sequences."

We do not need token-level surgery, because our packer beats Elektron's:

| image | raw | Elektron's stream | ours | headroom |
|---|---|---|---|---|
| 1.10E | 833,060 | 600,147 | **596,466** | **+3,681** |
| 1.11 | 836,956 | 602,067 | **598,410** | **+3,657** |

`src/dnfw/codec/aplibpack.py` — greedy with one-position lazy lookahead over a
2-byte hash chain, decided by `compress.c`'s cost model and bounded by
`codec/limits.py`. Around 8 s for section 7 in Python; the JavaScript port in
`site/js/aplibpack.js` does the same parse in 177 ms and emits byte-identical
output.

Every compressed section of both images comes out smaller than shipped, so a
rebuild never needs more flash than the image it replaces. Whole-image rebuilds
verify 21/21 and have been flashed.

**This is worth passing back to them.** If their constraint is really a maximum
section size rather than their packer's ratio, we would like to know the number —
we have not found one and have been assuming none exists beyond the flash
partition.

## 5. What we are taking from it

Leads, not conclusions. None of these are verified here yet.

- **ADI vendor fixtures.** Official `runtime-sharc-loader` source/LDR pairs for
  ADSP-SC589 as decoder ground truth, with `0x0001` a compact NOP and `0x0081` a
  compact IDLE. Our decoder sits at 44.9% against a cjump oracle and has never
  had a positive sample of known-correct encodings — which is the same gap that
  cost this project three failed audio detectors (`docs/pcm-hunt.md`).
- **VISA suffixes encode length**: `c` = 16-bit, `b` = 32-bit, `a`/`d` = 48-bit.
  That reframes the Type5a/5b discriminator question (digikit issue #8) as a
  length question rather than a family question.
- **`R2` and `F2` are the same physical register**, read as integer or float.
  Our decoder does not track numeric domain at all.
- **Delay slots**: two instructions execute after a branch carrying `DB`.
  A walker that ignores them manufactures false continuations and false returns.
  We do not handle them, and this is a candidate explanation for decode gaps we
  have been attributing to the decoder.
- **Send-effect chain**: Chorus `0x00B84630` → Delay `0x00B83F1A` → Reverb
  `0x00B83550`, with the chorus wrapper's five sub-calls listed. Relevant to
  `docs/ideas-backlog.md`'s FX work.
- **Parameter mirror**: `address = 0x0025CE96 + 2 * runtime_index`, chorus
  parameters at indices `0x1A`–`0x20`. Checked here only to the extent that
  private `0x0025CE96` → system `0x2825CE96` lands inside a **fill** block —
  zeroed RAM, which is where a runtime mirror belongs. Its contents are written
  over SPORT at runtime and are not in the file, so static analysis cannot
  confirm the indices; that needs the ColdFire side or hardware.

## 6. Their evidence discipline

Their §11 grades every conclusion — binary fact, proven boundary, proven
provenance, DSP interpretation, sonic inference, hardware validation — and their
§12 keeps the probe builder separate from the audit that reopens the built image
from disk, "so the builder cannot validate its own assumptions".

That is the same separation `docs/PRINCIPLES.md` argues for and the same reason:
an instrument that can only return one answer has told you about itself, not
about the image. Worth noting that two efforts arrived at it independently,
which is mild evidence it is the right shape rather than a local habit.
