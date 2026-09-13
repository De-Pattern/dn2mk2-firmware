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
| **D** | A recompressed but unchanged image boots | **done 2026-09-11** — boots, behaves as stock |
| **E** | A patch we wrote is visible on the instrument | **done 2026-09-11** — `SETTINGS` shows `DNFW ALIVE!` |

A, B, C and F are `pytest`. Recovery, D and E need the instrument; the order
and the reasoning are in `docs/flashing.md`.

**Phase 1 is closed.** Both gates passed through the normal update path, and the
recovery route — which stalled at ~80% and looked for a while like an image
defect — was diagnosed as **the MIDI link, not the image**: stock 1.10E stalled
the same way, and stock 1.11 flashed through recovery cleanly over a fixed link
(`docs/flashing.md`). Two further things have been proved on the instrument
since, and they matter more to Phase 2 than the gates do:

- **Code caves execute.** A cave hooked into the boot path wrote `CAVE RAN!!!`
  over the SETTINGS string in RAM while the image still read `PERSONALIZE`
  (`docs/code-caves.md`). Injection works; every silent build before it was
  target selection, not mechanism.
- **`parameter_value_getter` is not the display path.** Forcing its return
  changed nothing on screen (`docs/version-anchors.md`). An address confirmed by
  an instruction pattern is not a confirmed *role*, and only the role justifies
  a hook.

### What is left in Phase 1

- Run `dnfw symbols --ghidra` against a Ghidra project to seed the 454 RTTI
  names, and start reading `11LfoPageView`.

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
`100-107`. `dnfw params --ids` reports the space; `docs/lfo-parameters.md`
carries the evidence.

> **[WRONG — corrected 2026-09-13]** This paragraph ended: *"It stays arithmetic
> until we know what consumes the table and whether the id is bounded — and
> **nothing in MAIN OS holds the table's address**, so the consumer is still
> unidentified."*
>
> **The consumer is identified** — `docs/parameter-table-consumer.md`. It is a
> family of ~50 accessors indexing `record[id] = base + id*60`, and the bound
> *is* known: `id < 0x141` (321). The reasoning is kept because the mistake
> recurs. "Nothing holds its address" was true of the search that was run and
> false of the image: the accessors reach the table by `lea`, and on 1.11 there
> are **44 `lea` sites and 53 four-byte references** to the base
> (`docs/version-anchors.md`). A scan that found none was a scan with a bug,
> not an image without references — the same shape as the regex that reported
> "0 source paths in section 7" (`docs/sharc-image.md`).
>
> **And the answer moved the problem rather than removing it.** The table's
> length is not a stored count: the bound is an immediate replicated across
> **~43 sites**, all of which must agree. That is what growing the table costs.

The original framing, kept because it is still the right question to ask of the
*engine* as opposed to the table:

Find the code that indexes the `30 + 8*p + 2*lfo` grid and look at the `3`:

- a loop bound or table length → a small change,
- three objects constructed by name, with unrolled parameter tables → large.

Everything else follows from that answer, so nothing should be designed before
it exists.

### The reachability question is answered, and the display path is next

**2026-09-13.** `param_index_in_page`, `parameter_value_getter` and one of the
page-view consumers all run **constantly** during normal UI operation — 2,798,
3,031 and 2,097 calls in a 209M-instruction window with the UI drawing
(`scripts/call_map.py`, `docs/trace-harness.md`). The hardware trace's nine
blank columns meant nothing about those functions; the readout was frozen.

So the parameter path is where its 34 callers always said it was, and the two
functions LFO4 must hook are still the ones to find: **the display path** and
**the engine-feed path**. `parameter_value_getter` is confirmed *not* the
display path — forcing its return changed nothing on screen — but it is now
confirmed to *run*, which makes it a live lead rather than a dead one.

`M` and `S` — the `updateMirror` lambda and its enclosing function — stayed
silent, and that is **not** a finding: digikit models no input, and the mirror
path is exactly what an encoder drives. Ask that question by hooking
`panel_diff` and walking back, or by teaching the emulator input; do not read it
off an undriven boot.

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
- ~~What `blob` holds (833 KB on the DN2). Relevant if LFO4 needs a UI asset.~~
  **Answered 2026-09-13:** `blob` (section 7) is the **SHARC program**, an ADI
  boot stream — `docs/sharc-image.md`. ~240 KB of it is code, and its execution
  addresses are mapped for one of two spaces — `docs/sharc-code-map.md`. It is
  not a UI asset store, so this no longer bears on LFO4; it bears on everything
  that touches audio, which is why `docs/ideas-backlog.md` §7 is largely
  answered and §8 (FX machines, issue #49) is now askable.
- **Reading a SHARC instruction.** Nothing in this repository decodes SHARC+
  VISA, and that is now the binding constraint on all DSP-side work rather than
  a hypothetical one. digikit has a disassembler; we have the code map to aim it
  with.
- Whether the bootloader checks the HMAC trailer at all.
