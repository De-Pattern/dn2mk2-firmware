# The engine index space, and the fourth LFO lane that is already in it

`docs/lfo4-feasibility.md` closed its generator hunt with a reframing: there is
no LFO generator class anywhere in MAIN OS, so the question stops being *"find
the tick in this image"* and becomes *"find what MAIN OS **tells** the engine
about LFOs, and whether the shape of that message has room for a fourth."*

This is that reading, and the answer is **yes, with a complete reserved lane** —
eight zero-filled entries sitting in the shipped firmware's own lookup tables.

## 1. Where the control side hands over: `Sound::updateMirror`

1.11, the function ending at `0x4004cc06`; the `Sound::updateMirror` trace
string at `0x4021564d` is pushed from its assert path at `0x4004cbde`. It walks
the list of changed parameters and copies each into the mirror the engine reads:

```
4004cae8:  movel %a4@+,%d2            ; d2 = runtime slot id, walking a vector
4004caec:  movel %d2,%sp@-
4004caee:  clrl %sp@-
4004caf0:  jsr %a5@                   ; 0x400dccfa  ->  d4 = engine index
...
4004cb04:  moveq #-9,%d0              ; ~8
4004cb06:  andl %d2,%d0
4004cb08:  mvsw %a0@(14,%d2:l:2),%d1  ; d1 = sound[0x14 + slot*2]   (the live value)
4004cb0c:  cmpl %d0,%d5               ; d5 = 4   ->  (slot & ~8) == 4 ?
4004cb0e:  beqs remap
4004cb10:  moveq #20,%d0
4004cb12:  cmpl %d2,%d0               ; ... or slot == 20 ?
4004cb14:  bnes store
   remap:
4004cb16:  asrl #8,%d1
4004cb1c:  jsr 0x400dccfa             ; translate the DESTINATION value too
4004cb26:  lsll #8,%d1
   store:
4004cb28:  movew %d1,%a3@(1c,%d4:l:2) ; mirror[0x1c + engine_index*2] = value
```

Two things to read carefully here.

**The displacement `14` is hex.** Indexed-mode displacements print in hex with
no prefix (`docs/version-anchors.md`, the objdump radix hazard), so
`%a0@(14,%d2:l:2)` is `sound + 0x14 + slot*2` — the same runtime LFO value array
`docs/engine-state.md` found from the value getter, reached here from the write
side.

**`(slot & ~8) == 4 || slot == 20` is the three-LFO hardcode.** It selects slots
**{4, 12, 20}**, which `scripts/dump_param_sets.py` resolves to **LFO1 DEST,
LFO2 DEST, LFO3 DEST** (parameter ids 78, 88, 98). Destination *values* are
themselves slot numbers, so they need the same translation as the index. A
fourth LFO's DEST would be slot 28 and is not covered.

That idiom appears in exactly **two** places in the whole image — `0x4004cb04`
and `0x4004cb70`, the two loops of this one function. Measured by scanning every
`moveq #-9,%dN` (27 sites) and keeping those with a `moveq #20` within ±48
bytes. So the DEST special-case is a two-site patch, not a scattered one.

Worth recording for later: the mask is written as `~8`, which covers {4, 12},
with `== 20` bolted on for the third. Writing it as **`~24`** would cover
**{4, 12, 20, 28}** in a single test — all four LFOs — and make the `== 20` arm
dead. `moveq #-9` is `0x70F7`; `moveq #-25` is `0x70E7`. **A two-byte,
same-length change at each of two sites.** Nothing else in this document depends
on that, and it is not a proposal to flash anything yet.

## 2. The translation: `slot_to_engine_index`, 1.11 `0x400dccfa`

```
400dccfa:  movel %d2,%sp@-
400dccfc:  moveq #16,%d2
400dccfe:  movel %sp@(8),%d1      ; arg1 = kind
400dcd02:  movel %sp@(12),%d0     ; arg2 = value
400dcd06:  cmpl %d1,%d2
400dcd08:  bcss return_0          ; kind > 16        -> 0
400dcd0a:  bnes other             ; kind != 16       -> the 100-entry table
400dcd0c:  moveq #69,%d1          ; kind == 16:
400dcd0e:  cmpl %d0,%d1
400dcd10:  bcss return_0          ; value > 69       -> 0
400dcd1e:  lea 0x401fcd50,%a0
   other:
400dcd14:  moveq #99,%d2
400dcd16:  cmpl %d0,%d2
400dcd18:  bccs use                ; value <= 99
400dcd1a:  clrl %d0 ; return 0
   use:
400dcd26:  lea 0x401fcf20,%a0
400dcd2c:  movel %a0@(0,%d0:l:4),%d0
```

`Sound::updateMirror` always passes **kind 0**, so the table in play is
`0x401fcf20`, bounded at **value ≤ 99**.

So the engine does **not** share MAIN OS's slot numbering. It has its own index
space, and the translation is a plain array of 32-bit words in read-only data.

## 3. The tables

| Table | Address (1.11) | Entries | Maps |
|---|---|---|---|
| forward | `0x401fcf20` | 100 (`0..99`) | runtime slot → engine index |
| inverse | `0x401fd0b0` | 112+ | engine index → runtime slot |
| (kind 16) | `0x401fcd50` | 70+ | a separate space, not LFO-relevant here |

The forward and inverse tables **round-trip exactly** — `inverse[forward[slot]]
== slot` for every slot that maps anywhere, checked over all 100 — which is the
guard that the anchors are right and not two plausible-looking neighbours.

They are adjacent: the forward table's 400 bytes end at `0x401fd0b0`, where the
inverse begins. **There is no slack between or after them**, which matters for
any plan that would want to extend either.

## 4. The finding: the LFO block is four wide, and one lane is empty

Read the LFO slots through the forward table:

```
slot:   1  2  3  4  5  6  7  8   9 10 11 12 13 14 15 16  17 18 19 20 21 22 23 24
engine: 1  5  9 13 17 21 25 29   2  6 10 14 18 22 26 30   3  7 11 15 19 23 27 31
```

That is exactly **`engine_index = 4*param + lfo`**, for `param` 0..7 and `lfo` in
{1, 2, 3} — verified for all 24 slots, not spot-checked. The block therefore
spans engine indices 1..32, and the residue class `≡ 0 (mod 4)` is the fourth
lane.

The inverse table says the same thing in the clearest possible form. Laid out as
`[param][lfo]`:

| param | lfo=0 | lfo=1 | lfo=2 | lfo=3 |
|---|---|---|---|---|
| SPD | **0** | 1 | 9 | 17 |
| MULT | **0** | 2 | 10 | 18 |
| FADE | **0** | 3 | 11 | 19 |
| DEST | **0** | 4 | 12 | 20 |
| WAVE | **0** | 5 | 13 | 21 |
| SPH | **0** | 6 | 14 | 22 |
| MODE | **0** | 7 | 15 | 23 |
| DEP | **0** | 8 | 16 | 24 |

**Eight literal zeros, one per LFO parameter, in a column that is otherwise the
three shipping LFOs.** The engine indices no slot reaches are exactly
`[4, 8, 12, 16, 20, 24, 28, 32]` — the complete lane plus the spare at the block
boundary, with engine index 33 starting the machine parameters (slot 25).

`scripts/dump_engine_map.py` re-derives all of this from a local image.

## 5. What it means

**Three of the four layers a fourth LFO must pass through already reserve one.**
Two were measured by DNX from hardware captures; the third is this document; the
fourth is the problem.

| Layer | Shape | A fourth? |
|---|---|---|
| Persisted sound storage | `30 + 8*param + 2*lfo` (DNX, `dn2-format.md`) | **Reserved** — the 4th of each group of 8 is unused |
| Pattern p-lock ids | `4*slot + lfo` (DNX, `dn2-pattern-format.md`) | **Reserved** — `4*slot + 0` is never used |
| **Engine index space** | `4*param + lfo` (this document) | **Reserved** — the lfo=0 lane, eight zeros |
| MAIN OS runtime slots | packed `1..99`, tables 101 wide | **Full** — slots 65 and 100 free, and a fourth LFO needs 8 |

The three reserved lanes are all the **same arithmetic** seen from three
independent places — the stored format, the pattern format, and the engine's
own lookup tables. That is not a coincidence to be explained; it is one design
decision, visible three times.

**So the binding constraint is a single one, and it is the least fundamental of
the four.** The persisted format is Elektron's and is on users' +Drives; the
pattern format likewise; the engine's numbering is the DSP's. MAIN OS's runtime
slot space is none of those — it is the transient middle layer's own private
indexing, and it is the only one with no room.

That inverts the verdict this project has been carrying. The audio engine was
the presumed make-or-break (`docs/lfo4-feasibility.md`, "the true open gate").
On this evidence the engine side is not the gate at all: it has a correctly
sized, contiguous, zero-filled lane waiting. **The gate is MAIN OS's own slot
space, and every structure that bounds it is either a static table in the image
or an allocation constant.**

## 6. What is not settled

**This shows the message has a fourth lane. It does not show the engine acts on
it.** A reserved index space is a strong signal that the engine's own code is
written over four, but the engine's code is not in this image and has not been
read. The zeros could equally be a lane the DSP never iterates. Nothing here
should be reported as "the engine can run four LFOs" — what is proven is that
**MAIN OS can address a fourth, and reserves the indices to do it.**

**The bound inconsistency is unexplained.** The `ParameterSet` slot tables are
101 entries (`docs/parameter-set-tables.md`), the sound value array is addressed
as `0x14 + slot*2`, and the forward map is bounded at slot ≤ 99 with 100
entries. Slot 100 is inside the first two and outside the third. Worth resolving
before anyone counts on slot 100 as usable.

**Where eight slots could come from is the open question**, and it is now *the*
question. Three shapes, none costed:

1. **Raise the forward-map bound and extend the table.** `moveq #99` → a larger
   immediate is two bytes, but the table has the inverse table immediately after
   it, so extending means relocating one of them into a cave.
2. **Reclaim slots.** Slot 65 is free, slot 100 may be; the `SLEW`/`SPH`
   collision (`docs/parameter-set-tables.md` §4) shows the space is not as
   tightly packed as the count suggests. Whether six more can be freed without
   losing a feature is unknown.
3. **Give the fourth LFO a different mapping** that does not need new slots —
   for instance sharing slots and distinguishing by page. Speculative.

## Anchors

| What | 1.11 | How to re-find it |
|---|---|---|
| `Sound::updateMirror` | ends `0x4004cc06` | the trace string `0x4021564d` is pushed at `0x4004cbde` |
| the two DEST special-cases | `0x4004cb04`, `0x4004cb70` | `moveq #-9,%dN` with a `moveq #20` within ±48 bytes — 2 of 27 sites |
| `slot_to_engine_index` | `0x400dccfa` | called twice per loop iteration from the above |
| forward map | `0x401fcf20` | `lea` at `0x400dcd26` |
| inverse map | `0x401fd0b0` | immediately after the forward table's 400 bytes |
| kind-16 map | `0x401fcd50` | `lea` at `0x400dcd1e` |

Not yet re-anchored on 1.10E. Re-find by pattern — the `moveq #-9` / `moveq #20`
pairing is distinctive — and never by applying an offset; the shifts between
these builds are not uniform.
