# Roadmap

The goal: fill the vacant fourth page under the Digitone II's `[MOD]` key with
a fourth LFO behaving exactly like LFO1–3.

`docs/PRINCIPLES.md` governs how things get built. This file says what to
build, and what is already settled.

## Phase 1 — the build loop

| Gate | What it proves | Status |
|---|---|---|
| **A** | Transport round-trip is byte-identical on both images | **done** |
| **B** | `depack(pack(x)) == x`, including adversarial input | **done** |
| **C** | A rebuild with recompressed sections verifies, signature included | **done** |
| **F** | The disassembler in use agrees with `objdump -m m68k:cfv4e` | **done** — Ghidra passes, Capstone fails |
| **Recovery** | The Early Start-up Menu reflashes stock firmware | **done 2026-09-08** — the way back is proven |
| **D** | A recompressed but unchanged image boots | next — unblocked |
| **E** | A patch we wrote is visible on the instrument | not started — patch is written and builds |

A, B, C and F are `pytest`. Recovery, D and E need the instrument; the order
and the reasoning are in `docs/flashing.md`.

### What is left in Phase 1

- Run `dnfw symbols --ghidra` against a Ghidra project to seed the 454 RTTI
  names, and start reading `11LfoPageView`.
- The hardware sequence.

The reference decoder is `m68k-linux-gnu-objdump` from Ubuntu's
`binutils-m68k-linux-gnu`, reached through WSL. **Ghidra 12.1.3 with the
`68000:BE:32:Coldfire` language passes** and is cleared for use. Capstone
**fails**, which also condemns radare2, whose m68k backend is Capstone — the
numbers for both are in `docs/mainos-image.md`.

## Phase 2 — the fourth LFO

**The persisted format already has room.** DNX established both halves from
hardware captures, and neither is in doubt:

- Sound object: `offset = 30 + 8*parameter + 2*lfo` for `lfo` 0..2, bytes
  30–90. The fourth slot of each group of eight — 36, 44, 52, 60, 68, 76, 84,
  92 — is unused. (`DNX/docs/dn2-format.md`)
- Parameter locks: `id = 4*slot + lfo` for `lfo` 1..3. `4*slot + 0` — ids 0, 4,
  8, 12, 16, 20, 24, 28 — belongs to no LFO. (`DNX/docs/dn2-pattern-format.md`)

So a fourth LFO may need no storage-version bump at all. **This is evidence,
not proof.** Reserved bytes say Elektron left room; they do not say the runtime
can use it.

### The first question is answered: it is a table

**`docs/lfo-parameters.md`.** Each LFO is a block of ten 60-byte records in one
flat array, and the three blocks are identical but for the page label, a group
number, the ids and the controller numbers. Nothing is hard-coded to three.

The constraint is the id space, but **not** in the way this paragraph first
said. It claimed LFO3 ends at 24 and Chorus starts at 25, so a fourth block
could not continue the sequence. Walking the whole array killed that: it is 320
records covering the entire instrument, and 68 of the 100 ids in use are
claimed by more than one group. Chorus's 25 and LFO3's 24 are not in one
sequence.

The real constraint is that one LFO4 block is shared by every track type that
has LFOs, so its eight ids must be free in all of them at once. That points at
`100-107`. It stays arithmetic until we know what consumes the table and
whether the id is bounded -- and **nothing in MAIN OS holds the table's
address**, so the consumer is still unidentified. `dnfw params --ids` reports
the space; `docs/lfo-parameters.md` carries the evidence.

The original framing, kept because it is still the right question to ask of the
*engine* as opposed to the table:

Find the code that indexes the `30 + 8*p + 2*lfo` grid and look at the `3`:

- a loop bound or table length → a small change,
- three objects constructed by name, with unrolled parameter tables → large.

Everything else follows from that answer, so nothing should be designed before
it exists.

### Where to start reading

`11LfoPageView` is in the image with its address (`dnfw symbols --grep Lfo`).
The LFO parameter names sit together in the string pool, and the page labels
`LFO1`, `LFO2`, `LFO3` are three separate strings with no fourth — see
`docs/mainos-image.md`.

### If new code is needed

`octabam` adds real ColdFire code to Elektron firmware today using **code
caves**: a hook address, the stock bytes asserted before patching, and the
displaced instructions replayed inside the cave. That is direct evidence the
approach works on this platform, and it is the model to copy.

`patch/cave.py` does **not exist yet**, deliberately. Writing a cave applier
before there is a real hook to test it against would be inventing a mechanism
and calling it done. It gets written when Phase 2 has a hook.

### How the result gets verified

Not by looking at the screen. Patched firmware saves a project, DNX reads that
project's sound objects, and we check whether LFO4's values landed in the
reserved holes at 36/44/52/60/68/76/84/92 — a byte-level check against a map
derived independently, from hardware, by a different tool.

## Later, unscheduled

- The Digitone 1. Its firmware is unsigned, which makes the tooling side
  easier, but its flash and RAM are likely tighter and the feature question is
  the same one over again.
- What `blob` holds (833 KB on the DN2). Relevant if LFO4 needs a UI asset.
- Whether the bootloader checks the HMAC trailer at all.
