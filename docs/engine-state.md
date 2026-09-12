# The engine's runtime state, and the hunt for the modulation tick

`docs/memory-map.md` establishes that the sound engine's mutable state lives in
SDRAM at `0x80000000`, not in the image, and that a fourth LFO ultimately needs
the **write side** — the tick that advances the LFOs and applies them. This is
the record of that hunt on **1.11**: what is pinned, what is not, and what was
got wrong along the way.

## The accessor, decompiled

Reached through a thunk that adds the modulation-state offset to a per-track
object pointer, then jumps:

```
0x4003e426   move.l #0x4f358,%d0 ; add.l %d0,4(%sp) ; jmp 0x4004dfb0
```

```c
/* FUN_4004dfb0 */
int accessor(int base, int index) {
  if (index < 0)    index = 0;
  else if (index > 0x7f) index = 0x7f;
  return base + 0x30 + index * 0x3c0;
}
```

So: **an array of 128 entries, 960 (`0x3c0`) bytes each, at
`track_obj + 0x4f358`, with the field of interest at `+0x30` (48)** inside each
entry. 128 × 960 = 122,880 bytes (`0x1e000`) — a substantial block, consistent
with 1.11 clearing BSS to `0x80010000`.

The same shape appears in the bulk pass `FUN_4004dc62`, which walks **exactly
128 entries** — `d2` steps by 1163 to a limit of 148,864, and 1163 × 128 =
148,864 — advancing a second, parallel array at stride 1163 while stepping the
960-byte array, and calling `FUN_4004afec` on each pair. That callee is object
setup: it stores a pointer, calls vtable slots `+0x3c` and `+0x10`, and builds
six sub-objects at stride `0x98` from 16-byte source records at stride `0x10`.

## What these 128 entries are: **Presets**, named by the UI

The callers settle it. `FUN_40016480`, one of the 24 that reach the thunk, calls
the accessor and then formats the result:

```c
uVar3 = FUN_4003e426(*(param_1 + 0x68), (int)cVar4);   /* thunk -> accessor */
FUN_4004b1f4(uVar3);
FUN_400562e6(*(param_1 + 0x6c), "Preset: %d %s", cVar4 + 1, local_c);
```

The literal at `0x402127c8` is **`"Preset: %d %s"`**, and the index is passed as
`cVar4 + 1` — 0-based internally, displayed 1-based. Its neighbours in the
string pool are all page-view UI: `SourcePageView`, `MultiSourcePageView`,
`Reload Page %s`, `COPY PAGE %.16s`, `PASTE PAGE %s`, `CLEAR PAGE %s`, and the
FM operator labels `RATIO`, `RATIO OFFSET`, `KEY TRACK`.

So the array is **128 Presets of 960 bytes each**, reached from a page-view
object's member at `+0x68` (the engine/project pointer), and the clamp to
`0..0x7f` is the preset index range.

**Correction to an earlier label:** this had been carried forward as a
"per-track object". A 128-entry preset array is project-wide, so the base is the
**engine/project root**, not a per-track object. `docs/memory-map.md`'s
"per-track object" wording predates this and should be read with that caveat.

### 128 is not a unique fingerprint — the object classes, from the firmware

`128` recurs across unrelated DN2 entities, so counting alone proves nothing.
The SysEx receive handler `FUN_4002d8b2` names the classes outright:

| String | What it shows |
|---|---|
| `Received PATTERN %c%02d` | bank letter + 2 digits — **16 banks × 8 patterns = 128** |
| `Received SEQ %c%02d` | same bank-letter addressing |
| `Received PRESET %c:%03d` | letter + 3 digits (the larger preset pool) |
| `Received PRESET %d`, `Received KIT %d` | plain index |
| `Received MIDI PRESET`, `Received SETTINGS` | further distinct classes |

So **PATTERN, SEQ, KIT, PRESET, MIDI PRESET and SETTINGS are separate object
classes.** Patterns are 128 and bank-addressed, exactly as the hardware presents
them — but a pattern is 89,088 bytes (DNX), not 960, so the array here is not the
pattern array. The accessor's index is displayed as a **Preset**.

### Preset is what the DN2 calls a Sound

DNX measures the DN2's **sound pool at 128 × 359** and names it "Sound" after the
SysEx dump type. The firmware calls the same thing a **Preset** — Elektron
renamed Sound to Preset on the Digitone II. The two vocabularies describe one
array, which is why the count (128), the role (a project-wide pool indexed
0..127) and the size (359 B serialized → 960 B with runtime state) all agree.

That makes the identification **corroborated rather than inferred**, though the
last step — matching a known preset's field values byte-for-byte against a
DNX-decoded sound — has not been done and would settle it beyond argument.

**The modulation tick has not been found.** `FUN_4004dc62` is an
initialise-or-apply-to-all pass, not a real-time tick; `FUN_4004dfb0` is pure
address arithmetic. Neither advances an LFO. The write-side code remains open.

## The LFO's runtime slots — found, and there is no room for a fourth

Found 2026-09-12 by decompiling the 1.11 parameter value getter, `FUN_4006408a`
(the 1.11 counterpart of 1.10E's `parameter_value_getter 0x40064786`):

```c
if (param_3 >= 0) {
  if (FUN_400dbee6(param_id)) {                      /* is_lfo_param_modulatable */
    if (vtable[0x68](engine + 0x4f358, slot)) {
      obj  = FUN_4003e426(engine, slot);             /* thunk -> preset accessor */
      idx  = FUN_400dbcc4(param_id);                 /* = record[id] + 0x04      */
      sub  = vtable[0x28](obj);
      return *(short *)(sub + 0x14 + idx * 2);       /* <-- the LFO's value      */
    }
  }
}
```

So an LFO parameter's runtime value is a **16-bit word at `sub + 0x14 + idx*2`**,
where `idx` is the record's **parameter-id-within-page** field (`record+0x04`,
`docs/modulation-mask.md`). `FUN_400dbcc4` is exactly that field's getter.

### The index space is packed, 1..99

Reading `record+0x04` across every page that belongs to a **sound** — the SYN
machine pages, Filter, Amp, FX, Portamento and LFO1-3:

| Indices | Block |
|---|---|
| **1–8** | **LFO1** — `SPD MULT FADE DEST WAVE SLEW/SPH MODE DEP` |
| **9–16** | **LFO2** |
| **17–24** | **LFO3** |
| 25–64 | the SYN machine parameters |
| **65** | **free — the only gap in the whole space** |
| 66–85 | Filter |
| 86–88 | FX sends |
| 89–99 | Amp, Portamento, the FX block |

**98 distinct indices in use out of 1..99, with one free slot at 65** — and 65 is
the alignment boundary between the machine block and the filter block, not a
reserve.

This is corroborated by the destination-list builder `FUN_4003951e`, which walks
**`i = 0 .. 0x64`** — 101 slots, exactly `0..100` for an index space that runs
`1..99`. Two independent readings of the same number.

### What that means for a fourth LFO

A fourth LFO needs **eight contiguous slots**. There are none. The options are:

1. **Extend the space past 99** and put LFO4 at 100–107. Index 100 is already
   inside the enumerator's bound; 101–107 are not, so the `0x65` bound has to be
   raised wherever it is replicated — the same replicated-immediate problem as
   the parameter table's `#321`, and not yet counted.
2. **Displace existing parameters** to open a run of eight. Every index is a
   position in a runtime array *and* a key the stored format has to agree with,
   so this moves far more than it looks.

### A distinction worth keeping straight

DNX measured the **stored** sound format as `30 + 8*param + 2*lfo`, with the
fourth slot of each group of eight unused — Elektron left room there. The
**runtime** index space above has no such reservation: it is packed, and LFO3 is
immediately followed by the machine parameters.

So the two sides disagree, and both readings are right about their own side:
**a fourth LFO already has a home in storage and does not have one in RAM.**
That is the sharper version of the open question, and it is the second time this
document has had to separate the stored layout from the runtime one — see the
retraction below.

**Caveat.** The `sub + 0x14 + idx*2` read is on a branch gated by
`is_lfo_param_modulatable`; non-LFO parameters take a different path
(`vtable[0xc4]`). So "LFO1-3 occupy indices 1-24" is **measured**, while "the
machine parameters share the same array" is **inferred** from their sharing the
same index field and starting exactly where the LFOs stop. Reading the
`vtable[0xc4]` path would settle it.

## A correction, recorded because it nearly became a patch

An earlier reading of this accessor took its displacement as **+30 decimal** and
matched it against DNX's independently decoded sound object, whose LFO block is
at `offset = 30 + 8*parameter + 2*lfo` with the fourth slot of each group
unused. That looked like a striking convergence of two independent derivations.

**It was wrong.** The displacement is `0x30` = **48**, not 30. objdump prints an
indexed-mode displacement in *hex without a prefix* while printing `d16(An)` in
decimal — see `docs/mainos-image.md`, "objdump prints displacements in two
different radixes". Ghidra printed `0x30` correctly, and assembling both
candidates settled it in seconds.

The retraction matters beyond the number: **the runtime layout has not been
shown to match the serialized sound format.** DNX's reserved fourth LFO slot is
a fact about the *file* format and remains excellent evidence that Elektron left
room; it is not yet evidence about the engine's in-memory structure. The 960-byte
runtime entry and the 359-byte stored sound are, so far, unrelated measurements.

## Method notes that worked

- **Re-anchoring an object offset across builds**: histogram the immediates of
  `adda.l #imm,%aN` / `move.l #imm,%dN` in a plausible range. Every *other*
  offset matching across 1.10E and 1.11 is what makes the one that moved
  trustworthy (`+0x4f2e0` → `+0x4f358`). See `docs/version-anchors.md`.
- **Anchor on instruction sequences, not addresses** — the sequences around
  these constants were byte-identical between builds.
- **When two disassemblers disagree about a number, assemble both candidates.**
