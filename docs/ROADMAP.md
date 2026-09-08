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
| **F** | The disassembler in use agrees with `objdump -m m68k:cfv4e` | **done for Capstone** (it fails, as expected); Ghidra still to check |
| **Recovery** | The Early Start-up Menu reflashes stock firmware | **not started — gates all hardware work** |
| **D** | A recompressed but unchanged image boots | not started |
| **E** | A patch we wrote is visible on the instrument | not started — patch is written and builds |

A, B, C and F are `pytest`. Recovery, D and E need the instrument; the order
and the reasoning are in `docs/flashing.md`.

### What is left in Phase 1

- Set up the Ghidra project, run `dnfw symbols --ghidra` against it, and put
  Ghidra through Gate F before trusting a byte of its output. That needs its
  disassembly exported in a form `image/instruction.py` can compare; the
  comparison itself already exists.
- The hardware sequence.

The reference decoder is `m68k-linux-gnu-objdump` from Ubuntu's
`binutils-m68k-linux-gnu`, reached through WSL. Capstone has been measured and
**fails**, which also condemns radare2, whose m68k backend is Capstone — the
numbers are in `docs/mainos-image.md`.

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

The constraint is the id space: LFO3 ends at id 24 and Chorus starts at 25, so
a fourth block cannot simply continue the sequence. What else indexes that
space is the next thing to find out, along with whether anything stores the
table's length.

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
