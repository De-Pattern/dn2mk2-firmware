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

## What these 128 entries are: still unidentified

Two parallel 128-entry arrays (960 and 1163 bytes per entry) is a strong,
specific fingerprint, but nothing yet **names** them. Candidates not
distinguished: 128 sound/patch slots, 128 pattern steps (a DN2 pattern runs to
128 steps), or 128 voice/note slots. Deciding this is the next concrete step,
and the way to decide it is the callers — the thunk has **24**, and the
cluster at `0x40016xxx` sits in the page-rendering region, so those should say
what is being displayed.

**The modulation tick has not been found.** `FUN_4004dc62` is an
initialise-or-apply-to-all pass, not a real-time tick; `FUN_4004dfb0` is pure
address arithmetic. Neither advances an LFO. The write-side code remains open.

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
