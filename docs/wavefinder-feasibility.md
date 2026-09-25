# Wavefinder on the DN2: what it is, and what it would take

**Opened 2026-09-25**, at the owner's request: emulate Tonverk's **Wavefinder**
as a sixth DN2 machine. The mockup is a published artifact, built on the real
factory wavetables.

## What the machine is, from Elektron's own manual

Tonverk User Manual OS 1.4.1, section **A.2.5**, cited in our words:

> Two independent wavetable oscillators that can be blended and modulated
> separately. The position within a wavetable selects which waveform plays, and
> animating that position over time is what makes the timbre evolve. SRC Page 1
> is oscillator 1, Page 2 is oscillator 2.

**Sixteen parameters over two pages of eight** — which is exactly the DN2's page
shape, so the control surface maps with nothing left over:

| | page 1 | page 2 |
|---|---|---|
| A | `TUNE` bipolar pitch | `DTUN` detune from osc 1 |
| B | `LEV` | `LEV` |
| C | `POS` position in the table, **interpolated between waves** | `POS` |
| D | `SLOT` wavetable, **127 per project, p-lockable per step** | `SLOT` |
| E | `SPD` one cycle of the ANIM shape; looping shapes snap to beat divisions | `SPD` |
| F | `A.LEV` modulator depth on LEV | `A.LEV` |
| G | `A.POS` modulator depth on POS, **signed** | `A.POS` |
| H | `ANIM` which modulator shape | `ANIM` |

`ANIM` has **12 shapes**: five one-shots (Exp Down, Ramp Down, Tri, Ramp Up,
Exp Up), four looping (Ramp Down, Tri, Square, Ramp Up), Random, Sample and
Hold, and "Wavetable 1/2" — the *other* oscillator's output used as a modulator.

## The data, measured from Elektron's own tables

`Wavetables.zip`, the factory set for the Wavefinder SRC machine:

| | |
|---|---|
| tables | **75** |
| format | **IEEE float32, mono, 48 kHz**, uniformly |
| frame size | **2048 samples** — every file's length divides by it; no `clm` chunk |
| frames per table | **2 to 64** (64 is the most common; Bowed Lowed has 15) |
| total | **30.3 MB**; largest single table **512 KB** |

Our own `src/dnfw/wavetable.py` already reads exactly this shape — float32 WAV,
2048-sample frames when the length divides by it. So the import side is **done,
not estimated**.

## The gap, in five parts

### 1. Control surface and parameters — the part already proven

Adding a page of eight parameters with names, ranges, display and p-locks is
what LFO4's fourth `[MOD]` page did, end to end, on hardware. The machine list
ceiling is now read (`docs/machine-list.md`): `moveq #4` at `0x400dc332` and
`0x400dc358`, table at `0x401f77f4`, rows of 12 bytes.

**Known. Days, not weeks** — with the one real trap already recorded: the 192
zeroed bytes after the table are a live 16-long array indexed at `0x400dc1fe`,
so a sixth row needs space found elsewhere.

### 2. Storage — settled, and it is the cheap half

**Tonverk has an SD card. The DN2 does not.** That looked like the blocking
problem. It is not, because of a decision the owner made on 2026-09-25 that
removes the expensive part entirely:

> **The wavetable set ships with the firmware.** The user picks their tables in
> our own tooling and bakes them into the image **before flashing**. No browser,
> no file navigation, no user-facing storage management at all — `SLOT` simply
> indexes a fixed set.

That is not a new mechanism to invent. **`lfowaves` already does exactly this**:
`dnfw mods apply firmware.syx --mod lfowaves --wavetable N=FILE`, WAV or JSON in,
byte-identical between the CLI and the browser page. Wavefinder is the same
pattern with bigger tables, so the import path is not merely designed, it is
**shipped and parity-checked**.

And it removes the item that makes every DT2 machine expensive: a file browser
grafted into someone else's UI framework (`docs/dt2-machine-port.md`).

**Two variants, and the simpler one is probably right.**

| | where tables live | cost |
|---|---|---|
| **A — in the image** | a new ELE3 section, read-only, indexed by `SLOT` | no `+Drive` writes, no new format work |
| **B — delivered to the `+Drive`** | firmware carries blobs and writes them out on first boot | needs `+Drive` write code and the project format; DNX is the authority |

The owner proposed B. **A gets the same result with less**, because the premise
already accepts a reflash to change tables — so the delivery step buys capacity
and per-project independence, and costs a write path into storage we do not yet
write to. Worth taking A first and keeping B for when capacity actually binds.

**Sizing, at int16, against a section budget the firmware already normalises**
(section 7 is 837 KB; section 8 is 160 KB):

| geometry | per table | tables in 256 KB |
|---|---|---|
| 16 frames x 256 points | 8 KB | **32** |
| 16 frames x 512 points | 16 KB | **16** |
| 32 frames x 512 points | 32 KB | 8 |
| 16 frames x 2048 points | 64 KB | 4 |
| 64 frames x 2048 points (as shipped) | 256 KB | 1 |

For comparison, the whole LFO4 feature grew MAIN OS by **23.7 KB**.

**The geometry is not decidable yet.** How few points per frame stay clean
depends on the oscillator's interpolation and any oversampling — a DSP question,
and part 4 is where it gets answered. What is decidable now is the *budget*: a
few hundred KB is ordinary for this firmware, and at 16 x 512 that is sixteen
tables, which is a real instrument rather than a demo.

### 3. Machine dispatch — partly mapped, on the wrong device

digikit have DT2 1.16's ColdFire dispatch at `0x400caf48` and the DSP selector
chain `0x2567c0[0x255970[track]]`. **Our DN2 equivalents are not located**,
beyond the name-table bound above and a per-track clamp `min(R2, 4)` in
`sw 0x1c2712` that three structures now agree on.

**Weeks.** Ordinary static work of the kind this project does well.

### 4. The DSP render code — this is the feature

A wavetable oscillator on the SHARC: two readers, linear interpolation between
frames *and* between samples, per voice, at 48 kHz, plus a 12-shape modulator
and the blend. **Sixteen voices x two oscillators = 32 readers.**

None of it exists. And the blocker is not the DSP code itself:

- there is **no SHARC core** in any emulator — no QEMU or Unicorn target — and
  digikit cost writing one at **one to two weeks of sessions** before a first
  sound;
- we can assemble SHARC with selache, but it is **GPL-3.0, so never into
  digikit**;
- our own SHARC reading is thinner than theirs, and their DN2 work is
  `[D]`-graded structural comparison, not verified semantics.

**Months, and gated on the emulator.** Writing DSP code that cannot be run is
how `lfo4-bridge` reached the instrument and faulted.

### 5. Persistence and the sequencer

`SLOT` is p-lockable per step on Tonverk. The DN2's reserved p-lock ids and the
sound-object holes are already mapped from the LFO4 work, so this is the same
shape of problem, solved once already.

**Weeks**, after part 2 decides where wavetables live.

## The measured gap

| part | state | cost |
|---|---|---|
| wavetable import | **done** (`wavetable.py` reads the exact format) | — |
| control surface, parameters, pages | **proven** by LFO4 | days |
| machine list ceiling | **read** (`docs/machine-list.md`) | done |
| storage decision | **open, and blocking** | a decision |
| DN2 machine dispatch | partly mapped, DT2 only | weeks |
| **SHARC render code** | **nothing exists; no emulator** | **months** |
| persistence, p-locks | same shape as LFO4 | weeks |

**The feature is not close.** The nearest honest milestone is not Wavefinder; it
is a SHARC emulator good enough to run one voice render offline, which digikit
have already scoped and which we would share. Everything in part 4 is
unreachable without it, and everything else is comparatively cheap.

**What is worth doing now**, in order:

1. **Take the storage decision** — baked-in tables, or `+Drive` project data. It
   changes three of the five parts and costs nothing but a conversation.
2. **Locate the DN2 machine dispatch**, the mirror of digikit's `0x400caf48`.
   Static, our home turf, and useful whatever is decided.
3. **Do not start SHARC render code** until something can run it.

## Status

**[D]** for the gap estimates — they are reasoned from measured facts (the file
format, the firmware's free space, the machine table bound) but no part of the
feature has been attempted. The manual citation and the wavetable measurements
are **[V]**: read directly from Elektron's own document and files.
