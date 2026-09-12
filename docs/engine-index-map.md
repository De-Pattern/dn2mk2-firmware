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

## 6b. The bound inconsistency, resolved — and it is worse than it looked

The `ParameterSet` slot tables are 101 entries (`docs/parameter-set-tables.md`),
the sound value array is addressed `0x14 + slot*2`, and the forward map is 100
entries bounded at slot ≤ 99. Slot 100 is inside the first two and outside the
third. Followed through, all three of the "free" sound slots end at the same
place:

| slot | forward map | why |
|---:|---|---|
| 0 | → engine **0** | in the table, explicitly 0 |
| 65 | → engine **0** | in the table, explicitly 0 — the gap |
| 100 | → engine **0** | **out of bounds**; `slot_to_engine_index` returns 0 |

So `Sound::updateMirror` would write `mirror[0x1c + 0*2]` for a parameter at any
of them. **There are not two free sound slots. There are zero usable ones** —
the earlier count was of table holes, not of routes to the engine, and a hole
that maps to engine 0 is a hole that silently writes to the wrong place.

**Slot 100 is the worst of the three**, because it fails *outside* the table
rather than in it: nothing marks it, the bound simply returns 0. Anything built
on "slot 100 is spare" would appear to work in the destination list and quietly
corrupt engine index 0 on every value change.

**But slot 65 is repairable with one 4-byte write.** It is a real, in-bounds
entry that currently holds 0. Pointing it at a free engine index is a static
data edit of the same kind already flashed twice. Slot 100 is not repairable
that cheaply — it needs the bound raised *and* the table extended, and the
inverse table starts immediately after it with no slack (§3).

### A consequence for the fourth lane

Engine index 0 is doing double duty: it is the "no mapping" return value **and**
nominally `4*param + lfo` with both zero. That settles which indices a fourth
LFO should actually use. The genuinely unreachable set measured in §4 is

```
[4, 8, 12, 16, 20, 24, 28, 32]
```

— eight values, and **0 is not among them**, because slots 0 and 65 do reach it.
So the fourth LFO's lane is `4*param + 4`, running 4..32, not `4*param + 0`
running 0..28. Had it been the latter, LFO4's Speed would have shared an address
with the sink that every unmapped slot writes to, and every stray write would
have landed on it.

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

---

## 7. Retracted: "the engine's code is not in this image"

§6 said the engine's code "is not in this image and has not been read". **That
was an over-claim, prompted and corrected by the owner 2026-09-12**, and the
correction matters because it reopens the generator hunt.

**The Octatrack precedent is real.** octabam's `docs/firmware/DSP.md` documents
the OT's DSP56300 program as **embedded inside its MAIN OS section as data**,
uploaded at boot from `0x4000050c`: bootstrap A at `0x400e21e0` (50 words),
payload A at `0x400e2324` (79,563 B), bootstrap B at `0x400e2276`, payload B at
`0x400f59ef` (77,061 B) — all ColdFire virtual addresses in the same image we
would call "MAIN OS". Same platform family, same ELE3 container. So "the DSP
program ships inside MAIN OS" is the *normal* arrangement here, not an exotic
one, and the DN2 should be assumed to do it until shown otherwise.

### What was checked, and what it showed

| Candidate | Result |
|---|---|
| **Section 4** (`dest 0x80000400`, 32,776 B, raw) | **Not DSP — it is the *updater*, and it is ColdFire.** Its body opens `46fc 2700` (`move #$2700,%sr`), the same instruction MAIN OS opens with. `docs/ele3-format.md` had this right all along as "updater"; `memory-map.md` and `parameter-set-tables.md` called it "the DSP section" and were **wrong**. Both corrected. |
| **`blob`** (id 7, 836,956 B) | **Not a 48-bit instruction stream.** Per-byte-position entropy at stride 6 is flat (spread 0.36) where stride 4 shows real column structure (spread 1.58, final byte 5.59) — the signature of little-endian float32, not SHARC's 48-bit words. Consistent with the existing "mixed data, largely float32" reading. |
| **Section 8** | Already identified as a complete ARM Cortex-M image (`docs/data-sections.md`). |
| **A DSP upload routine in MAIN OS** | **Not found.** The three early-boot calls at `0x4000052c` / `0x40000532` / `0x40000538` are a table fill, a `movec %d0,%vbr`, and interrupt handlers. `0x8c000004`, which looked promising for sitting beside octabam's `FUN_40001b18`, is written from a **panic handler** (`rte`, `bras .`). |

### The open candidate

A **~320 KB region at `0x40238000`–`0x40287000`** is high-entropy (mean ≈ 7.3–7.6
per 4 KB block), non-string, non-sparse, and **almost entirely unreferenced by
absolute address**: of 38 code references into `0x40238000`–`0x40288000`, 34 land
in the string pool just above `0x40287000` and only **four** point into the body.

That is what an embedded payload addressed by a base-and-length pair looks like.
It is *also* what `docs/memory-map.md` already labels "packed data records", so
this is a candidate and **not** a finding. The four interior references are
`0x402572d0` (from `0x400ceff6`, `0x400d050c`) and `0x402765c0` / `0x40281ec0`
(from `0x4012f7d8`, `0x4012f892`).

### The decisive next test

Find the uploader by its shape rather than its address: **a tight loop that reads
sequentially from a source pointer and writes to a *fixed* absolute address.**
The external-bus windows the firmware actually touches are `0xec09xxxx` (270
absolute accesses), `0xec07xxxx` (38), `0xec03xxxx` (15) and `0x8c00xxxx` (25) —
a DSP host port would be among them. If such a loop exists and its source lies
inside `0x40238000`–`0x40287000`, the DSP program is in this image and the
generator becomes findable.

Until then the honest position is: **the engine's code has not been located, and
it has not been ruled out of this image either.** §6's reserved-lane finding is
unaffected — that rests on MAIN OS's own tables, not on where the DSP code lives.

## 8. Can the LFO be routed to a different mirror or table?

Asked by the owner, and it splits into three parts with different answers.

**The index mapping: yes, and cheaply.** The forward map at `0x401fcf20` is
static data. Changing which engine index a slot maps to is a 4-byte write — that
is exactly the repair §6b proposes for slot 65.

**The mirror itself: no, not usefully.** The mirror base is `%a3` in
`Sound::updateMirror`, taken from the object rather than a constant. Redirecting
it at the FX mirror would need a cave *and* would be wrong in granularity:
`Sound::updateMirror` runs per sound, so it would write the single global FX
mirror once per sound per change.

**Applying modulation control-side instead — hooking `FxSetup::updateMirror` to
fold in an LFO value before mirroring — is blocked, and the owner's own device
observation is what blocks it.** Control-side application requires the ColdFire
to know the LFO's *instantaneous* output. It evidently does not: LFO modulation
**does not move displayed values**, while external MIDI modulation does. If the
ColdFire held the modulated value the display could show it, and the
long-standing user request for exactly that would not exist. So the LFO's running
value appears never to exist on the control side at all — it is produced and
applied engine-side.

That would also make control-side application the wrong *shape* even if it were
possible: it would run at UI update rate, not audio rate.

**So both questions converge.** Reaching an FX parameter with an LFO, and finding
the generator, are the same problem seen twice: both need the engine side, and
the engine side is either absent from this image or is the unreferenced 320 KB
above. That is now the single highest-value unknown in the project, and §7 names
the test that settles it.

---

## 9. Settled: the audio engine's code is not in this firmware file

§7 reopened the question after the owner pointed out that the Octatrack ships its
DSP code. The right move was to check rather than assume, and checking gives a
clear answer — **the opposite one to the Octatrack's.**

### The ColdFire does no audio DSP

Disassembling the whole code region (`0x40000400`–`0x401d0000`) with the
Gate-F-cleared reference objdump:

| Measure | Count |
|---|---|
| instructions decoded | **582,407** |
| floating-point instructions (`fmove`, `fmul`, `fadd`, …) | **0** |
| MAC/MSAC instructions (`macl`, `msacl`, `macw`, `msacw`) | **50** |
| `mulsl` | 916 |

An audio engine — oscillators, filters, envelopes, reverb — running on this CPU
would show thousands of MACs. Fifty across 1.95 MB is incidental arithmetic.
**The ColdFire is a control processor here and nothing more.**

> **The zero-FPU half of this argument is withdrawn (2026-09-12).** The board
> carries an **MCF5441x**, not the V4e this repository assumed from octabam's
> Octatrack (`docs/hardware.md`). If that part has no hardware FPU, a count of
> zero FPU instructions is what *any* code on it would give, DSP or not, and it
> proves nothing. **The MAC comparison stands and was always the stronger
> half** — 50 here against the DN1's 613 in tight four-accumulator EMAC loops
> (`docs/dn1-dsp-comparison.md`) — and it does not depend on the FPU question.
> The conclusion survives on that evidence alone.

This is also the proper basis for a claim an earlier session made and then
withdrew on weak grounds. The withdrawal was correct at the time — it rested on
a display-update argument the owner refuted — but the conclusion happens to
hold, for this much better reason.

### No section carries a DSP instruction stream

| Section | Verdict |
|---|---|
| 2, bootstrap (30,302 B) | ColdFire, the recovery receiver (`docs/bootstrap.md`) |
| 3, MAIN OS (3,192,192 B) | ColdFire control code — measured above |
| 4, updater (32,776 B) | ColdFire; opens `46fc 2700` like MAIN OS (§7) |
| 7, `blob` (836,956 B) | **32-bit word data.** Column-entropy spread by stride, whole file and by 200 KB chunk: **stride 3 = 0.01** (DSP56300's 24-bit word) and **stride 6 = 0.99** against **stride 4 = 1.17** and stride 8 = 1.18. A 24-bit instruction stream is ruled out outright; 48-bit (SHARC) tracks stride 4's structure only because 6 and 4 share a factor. The low-entropy final byte of each 32-bit group is the little-endian float32 exponent. |
| 8, ARM Cortex-M (159,948 B) | **New in 1.11**, and the DN2 made sound in 1.10E — so it cannot be the engine. |

**So the engine's program ships on a processor with its own storage, and this
update file never touches it.** That is a real difference from the Octatrack,
where octabam found the DSP56300 payloads inside MAIN OS at `0x400e2324` and
`0x400f59ef`. Same vendor, same container format, different arrangement — which
is exactly why it needed measuring rather than assuming, in either direction.

The 320 KB candidate region from §7 (`0x40238000`–`0x40287000`) is therefore
**not** a DSP payload. It is what `docs/memory-map.md` always called it: packed
data records. §7's candidate is withdrawn.

### What this does to the project

**It removes an option and sharpens the thesis.**

We cannot modify the audio engine. Not "have not yet found how" — the code is
not in the file we can write. Every cave, every table edit, every hook reaches
the control processor only.

So **a fourth LFO exists if and only if the engine already implements one**, and
the whole project now rests on the reserved lane in §4: engine indices
`4, 8, 12, 16, 20, 24, 28, 32`, eight entries wide, zero-filled, sitting in the
map the control side uses to address the engine. That finding stops being an
interesting curiosity and becomes the entire basis of the work.

It is corroborated, and this is the part that makes it more than a hopeful
reading: the **same** fourth slot is reserved in the persisted sound format and
in the pattern p-lock ids, both measured by DNX from hardware captures, neither
of which has anything to do with this index table. Three independent structures,
one shape. Elektron laid out four everywhere and shipped three.

**And it makes the decisive experiment cheap and safe.** Build the control side —
records, enumeration, slots — point its mirror writes at the reserved lane, and
listen. If the engine runs a fourth LFO, it modulates. If it does not, nothing
moves. One build, one flash, a silent and harmless failure, and a definite
answer to the question the project has been circling since it started.

That is now the shortest path to knowing whether this is possible at all, and it
is shorter than it looked when the engine seemed patchable.

---

## 10. Correction: the DN2's DSP is a SHARC, and §9's `blob` test was the wrong one

The owner: **the DN2 uses a SHARC, not a DSP56300.** The `Digisharc` namespace
on every mirrored type says so, and §9 leaned on a stride-3 test that rules out
the **Octatrack's** 24-bit DSP56300 word — a chip the DN2 never had. Re-tested
against what the DN2 actually uses.

### Two measurement errors, both mine

**The stride comparison was measuring 16-bit structure, not word size.** Reading
the per-byte-position entropies rather than just their spread shows a clean
**period-2 alternation** in every region of `blob`:

```
whole      stride4 cols  7.70 6.77 7.67 6.52   | stride6 cols  7.69 6.71 7.68 6.70 7.69 6.69
700-836K   stride4 cols  7.98 5.88 7.95 5.57   | stride6 cols  7.97 5.78 7.97 5.78 7.97 5.78
```

High, low, high, low — at *both* strides, because both are even. §9 concluded
"32-bit word data" from stride 4 scoring higher than stride 6; that comparison
was an artefact of how each stride aligns with a period-2 signal, and it
**cannot distinguish 32-bit from 48-bit at all.**

**`blob` is not float32.** Interpreted as float32 and counting values that are
zero or finite with magnitude between 1e-8 and 1e8: **35.3% little-endian, 22.3%
big-endian**. Random bytes score about **62%** on that test. So `blob` is not
merely "not obviously float" — it is *less* float-like than noise, and the
"57–66% float32" reading carried in `docs/data-sections.md` and
`docs/ideas-backlog.md` §3 is wrong.

The period-2 structure with the *second* byte of each pair carrying lower
entropy is the signature of **little-endian 16-bit words whose high byte is
constrained** — which is what 16-bit PCM looks like. That is a hypothesis, not a
finding, but it points `docs/ideas-backlog.md` §3 back at `blob` with a better
idea of what to look for than "float32 coefficient tables".

### The test that is actually valid for a SHARC

A SHARC instruction is **48 bits = 6 bytes**. Any genuine 6-byte periodicity
must also produce 3-byte structure, because sampling a period-6 signal every 3
bytes pairs positions (0,3), (1,4), (2,5) — and those differ in real code, where
the opcode bits sit at the top of the word.

Scanning `blob` in 32 KB windows:

| | |
|---|---|
| windows scanned | 25 |
| **stride-3 column-entropy spread** | **0.00 – 0.10 in every window** |
| stride 2 / 4 / 6 | track each other closely, 0.13 – 4.62 |
| windows whose structure is not period-2 | **0** |

**No region of `blob` has 3-byte or 6-byte periodicity.** So `blob` contains no
*raw* 48-bit SHARC instruction stream. That conclusion now rests on the right
test for the right chip.

### What this does and does not settle

**§9's headline survives, and its main evidence was never in doubt:** the
ColdFire does no audio DSP — 582,407 instructions, zero FPU, 50 MAC, against the
DN1's 613 MACs in a hand-pipelined EMAC kernel (`docs/dn1-dsp-comparison.md`).
Whatever runs the DN2's engine, it is not the CPU whose code we hold.

**But "the engine's code is not in this firmware file" is weaker than §9 and
PR #32 stated it.** One gap is now explicit:

**~350 KB of `blob` is structureless.** Windows from `0x20000` to `0x78000`
score 0.13–0.82 spread at *every* stride, with per-byte entropy 7.3–7.6 — near
uniform. That is what compressed or packed content looks like, and **a
compressed SHARC image would show exactly this and defeat every periodicity
test above.** Ruling out a raw instruction stream does not rule out a packed
one.

So the honest state is: **no raw SHARC code is present, and a packed image
cannot be excluded by these methods.** §9 should have said that and did not.

### What would settle it

Two routes, neither taken:

1. **Find the boot path, not the bytes.** A SHARC boots from SPI/EEPROM, from a
   link port, or from its host port. If the DN2's SHARC boots from its own flash,
   nothing about it is in this file and the question is closed. If the ColdFire
   uploads it, there is code that reads `blob` (or another region) and drives a
   port or a DMA channel — and *that* is findable, because it must know where
   `blob` sits in flash. `blob` has `dest 0`, so MAIN OS addresses it explicitly
   somewhere.
2. **Decompress the structureless region.** If it unpacks with the container's
   own aPLib variant, or any common scheme, its contents can be tested for the
   48-bit periodicity directly.

Route 1 is cheaper and answers the question either way.

---

## 11. CONFIRMED ON HARDWARE: the engine implements a fourth LFO

**2026-09-12.** `scripts/build_lfo4_probe.py` re-pointed LFO3 from engine lane 3
to the reserved lane 4 — engine indices `4, 8, 12, 16, 20, 24, 28, 32` — with no
other change: same records, same page, same UI, same slots, 24 bytes touched,
all inside the two mapping tables.

**LFO3 still modulates.**

That is the positive outcome §4 predicted and PR #33 set up to test, and it is
conclusive in the direction that matters. The engine was handed eight parameter
values at indices no shipping firmware ever writes, and it produced modulation
from them. **The reserved lane is live capability, not layout.**

### What it settles

| Question | Answer |
|---|---|
| Does the audio engine implement a fourth LFO? | **Yes.** |
| Is the lane `4*param + 4` the right one? | **Yes** — all eight parameters were driven through it at once. |
| Is a fourth LFO an engine problem? | **No. It never was, and now we know.** |

The engine's code is not in this firmware file and cannot be patched
(§9, and `docs/dn1-dsp-comparison.md` — the DN2's ColdFire does no DSP at all).
That was the project's worst-case scenario: an unreachable engine that might
only run three. **It runs four.** Everything that remains is on the control side,
where we can write bytes.

It also closes, positively, the loop that three independent structures opened:
the persisted sound format reserves a fourth slot per group of eight (DNX), the
pattern p-lock ids reserve `4*slot + 0` (DNX), and this index map reserves the
`4*param + 4` lane. All three were measured separately, and the engine has now
been shown to *act* on the third. Elektron built a fourth LFO and shipped three.

### What it does not settle

**Whether a fourth LFO can run *alongside* the three.** The probe moved LFO3; it
did not add anything. Lane 3 was vacated at the moment lane 4 was driven, so
this shows lane 4 works, not that lanes 3 and 4 work simultaneously. Nothing
suggests they cannot — they are separate indices in the same block — but it is
untested and should not be stated as fact.

**Whether all eight parameters behave fully.** Modulation was heard; whether
`WAVE`, `MULT`, `FADE`, `SPH` and `MODE` each take effect on lane 4 exactly as
on lane 3 has not been checked parameter by parameter. A partially wired lane
would still have produced audible modulation. This is a device check, costs
nothing, and should be done before any build depends on a specific parameter.

### What is now the whole of the job

A fourth LFO needs **eight runtime slots**, and §6b measured one repairable free
slot. That is the only structural problem left, and every piece of it is now
identified:

| Piece | Today | To reach 108 slots |
|---|---|---|
| forward map `0x401fcf20` | 100 entries, bound `slot <= 99` | relocate to a cave (432 B — fits a ~1 KB run) and repoint its **4** `lea` sites; raise the bound immediate |
| inverse map `0x401fd0b0` | 107 entries | **no growth needed** — write slots 100–107 into the reserved lane's entries |
| sound `ParameterSet` table `0x42c64b3c` | 101 entries, BSS | relocate into the 25 MB of unclaimed RAM above the BSS end (`docs/memory-map.md`) and repoint its **5** `lea` sites |
| destination builder bound | `i != 0x65` (101) | one immediate |
| **the sound object's value array** | addressed `0x14 + slot*2` | **unmeasured — this is the open one.** Its size is an allocation constant somewhere, and if it cannot hold 108 entries the rest does not matter |

Four of the five are tractable and two are single immediates. **The sound
object's size is the next thing to measure**, because it decides whether this is
finishable.

---

## 12. The DSP, identified from the board: ADSP-21569 (SHARC+)

**2026-09-12, from the owner's photograph of the mainboard (PCBA0109B).**

| | |
|---|---|
| **U9** | **Analog Devices ADSP-21569** — SHARC+, `KBCZ10`, date code `2341`, Korea |
| **U25** | **Kingston `D2516ECMDXGJD`** — DDR3 SDRAM, immediately beside the DSP |
| Y4 | FOX 20.000 MHz crystal |

This retires the chip question for good. It is a **SHARC**, as `Digisharc`
always implied — and specifically a **2156x-generation SHARC+**, not the classic
2126x/2136x parts and certainly not the Octatrack's DSP56300.

A build path left in an assert corroborates the platform naming:

```
0x4021b74f   ../../../firmware/digisharc/cf/intro/intro_dither.c
0x???????    ../../../lib/shared/sm/fade.c
```

**`firmware/digisharc/cf/`** — `cf` is ColdFire. So "digisharc" is Elektron's
name for the *whole platform*, and the ColdFire firmware is one subdirectory of
it. A sibling tree for the DSP side almost certainly exists in their build; it
simply is not shipped here.

### What the part number invalidates in §10

**§10's 48-bit periodicity test was never the right disproof, and this is the
second time this question has been tested against the wrong premise.** §9 used a
stride-3 test valid for the DSP56300 — a chip the DN2 never had. §10 corrected
that to stride 3/6 for a 48-bit SHARC word. But an **ADSP-2156x boot image is an
LDR boot stream**: 32-bit words organised into blocks with 16-byte headers, not
a raw instruction array. Instructions are packed into that 32-bit stream. So
"no 6-byte periodicity" does not rule out a SHARC+ image either.

The right test for this part is the **LDR block structure**, and `blob` fails it
too:

| Test | Result |
|---|---|
| 32-bit-aligned words whose top byte is `0xAD` (the ADI block-code marker) | **345 of 209,239 = 0.16%** — *below* the 0.39% expected by chance, so not enriched at all |
| Walking a block chain from offset 0 | Two plausible headers at `0x0` and `0x10`, then **breaks** — the third header is not a block code |

So `blob` is not an ADI boot stream. Three tests, three chips' worth of
premises, and the same answer each time.

### What the board suggests instead

**The DDR3 sits next to the SHARC, not the ColdFire.** The DSP has its own large
working memory. That fits `blob` (836,956 B, 16-bit-word structured, §10) being
**data destined for the DSP's DDR3** — samples or wavetables — rather than code,
which is also what its lack of any instruction-like periodicity says.

**And the ADSP-21569 has no on-chip flash.** It must boot from SPI master (its
own serial flash), SPI slave or link port (a host pushes the image), or UART. If
it boots from its own flash, its program is not in this update file and never
will be. If the ColdFire boots it, there is an upload path in MAIN OS — and none
was found: the external windows the firmware touches (`0xec03xxxx`,
`0xec07xxxx`, `0xec09xxxx`, `0x8c00xxxx`) are all narrow register interfaces,
mostly byte-wide reads across a handful of addresses, which is a peripheral or
FPGA control surface, not a boot channel.

### Honest verdict, stated with the right confidence

**Leading hypothesis: the SHARC boots from its own serial flash, and its program
is not in this firmware file.** Supporting it: no boot stream in any section
under three different chip premises, no upload path in MAIN OS, a DSP with its
own DDR3, and a ColdFire that does no DSP at all
(`docs/dn1-dsp-comparison.md`).

**But this has been claimed too strongly twice already** — §9 said "settled" and
was not, §10 narrowed it and was still testing the wrong packing. It is recorded
here as the leading reading with its disproof named, not as fact.

**The check that settles it is on the board, not in the bytes.** SPI master boot
requires a serial flash wired to the DSP — typically an 8-pin SOIC/WSON part
within a few centimetres of U9. If one is there, the question is closed and the
DN2's engine is permanently unmodifiable. If there is no flash near the SHARC,
the ColdFire must be booting it and the image is in this file somewhere the
three tests above have not looked.

### Does any of this matter for LFO4?

**No.** §11 confirmed on hardware that the engine implements a fourth LFO. That
result is about behaviour, not code, and holds whichever way this goes. What
this question decides is whether engine-side modification is *ever* possible —
a separate ambition, and not one the project currently needs.

---

## 13. The sound object's value array is exactly 101 entries, and it is boxed in

§11 named this the one unmeasured piece — the array the whole LFO4 build depends
on. **Measured 2026-09-12, and it is the hardest constraint in the project.**

### The size

A loop that fills the array states its own bound:

```
4004408e:  ... compute value into %d0 ...
400440a2:  movew %d0,%a0@(14,%d3:l:2)   ; array[d3] = value   (0x14 is hex)
400440a6:  addql #1,%d3
400440a8:  moveq #101,%d0
400440aa:  cmpl %d3,%d0
400440ac:  bnes 0x4004408e               ; d3 runs 0..100
```

**101 entries, slots 0..100**, spanning `+0x14` to `+0x14 + 101*2 - 1 = +0xDD`.

That is the same 101 as the `ParameterSet` slot tables
(`docs/parameter-set-tables.md`) and the same 101 the destination builder walks
(`i != 0x65`). Three independent structures agreeing on 101 is not a coincidence
to explain; it is one array size propagated.

### What sits immediately above it

The call site at `0x40036738` reads the machine and filter type **through the
same `vtable[+0x28]` accessor** that `Sound::updateMirror` reads the value array
from — so it is the same object:

```
40036734:  jsr %a0@                ; vtable[+0x28] -> the sound value object
40036738:  mvsb %a0@(222),%d2      ; +0xde  machine type
4003674c:  mvsb %a0@(223),%d0      ; +0xdf  filter type
40036758:  jsr 0x400dc02a          ; param_set_slot_to_id(slot, machine, filter)
```

| offset | holds |
|---|---|
| `+0x14` … `+0xDD` | the value array, slots 0..100 |
| **`+0xDE`** | **machine type** |
| **`+0xDF`** | **filter type** |

**The array is flush against them.** Slot 101 would land on `+0xDE` and
overwrite the machine type on every parameter change.

This also explains, exactly, the bound mismatch §6b recorded: the array and the
`ParameterSet` tables hold 101 slots, the forward map holds 100 bounded at 99.
Slot 100 has *storage* and *enumeration* but no engine mapping — it is the last
entry that physically exists, and the engine map simply never claimed it.

### What it rules out

**Extending the array in place is impossible.** There is no padding to grow into.

**Growing the object by shifting everything above `+0xDD` is not realistic
either.** The same scan finds live fields at `+0xE0`, `+0xE4`, `+0xE8`, `+0xEC`,
`+0xF0`, `+0xF4`, `+0xFC`, `+0x100`, `+0x114`, `+0x11C`, `+0x146` and well
beyond — the array sits in the *middle* of a large structure, not at its end.
Every one of those displacements would have to move, and the object is
persisted, pooled and mirrored to the engine, so its layout is load-bearing in
three directions at once.

**Relocating just the array is more tractable but not cheap.** All **29** access
sites use the *brief* extension word — `%aN@(14,%dM:l:2)`, an 8-bit
displacement. Any new base above `+0x7F` needs the **full** extension word,
which is longer, so none of the 29 can be patched in place; each would need a
cave. 29 detours for one feature is a poor trade.

### The route that is left

**Do not grow the array — source LFO4's values from beside it.** The value array
is read and written at a small number of choke points, not at all 29 sites
equally:

| Path | Site |
|---|---|
| control → engine | `Sound::updateMirror`, the two loops at `0x4004cb04` / `0x4004cb70` |
| engine → control | the reverse copy at `0x400dd25e` |
| UI read | `parameter_value_getter` `0x4006408a` |

A hook at those points could serve slots ≥ 101 from a separate 8-entry array
placed in the **25 MB of unclaimed RAM above the BSS end**
(`docs/memory-map.md`), leaving the sound object untouched at its current size
and layout. The storage path would need the same treatment for LFO4's values to
survive a save — and that is the part that is not yet scoped.

**This is now the decision the project turns on**, and it is an engineering
choice rather than an unknown: a handful of caves at known choke points, against
a struct change that three subsystems depend on. Neither is small. What is no
longer in doubt is that **the engine will modulate** once the values arrive
(§11) — the remaining work is entirely about getting eight more values to it.
