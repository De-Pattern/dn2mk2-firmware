# Does any Octatrack project develop the LFO? A survey

Asked 2026-09-12: before spending more on the modulation tick, check whether the
Octatrack reverse-engineering projects have already done LFO work we can learn
from. All four were cloned and read.

**Standing caveat, and it applies to every line below:** the Octatrack is a much
older device and its architecture may have nothing in common with the DN2.
Nothing here is evidence about the Digitone II. It is prior art about *what
people have managed to do to an Elektron box*, which is a different and weaker
thing.

Licences: midisc, octabam and octamax are MIT; **ems-octakit has no licence**, so
it is read for architecture only and nothing is ported (`docs/references.md`,
[[ems-octakit-license]]).

## The answer: nobody has added an LFO generator

| Project | LFO work | What kind |
|---|---|---|
| **ems-octakit** | `runtime/lfo_designer_editor.S`, `lfo_designer_operations.S`, `lfo_parameters.S`, `lfo_store.S` — 2,265 lines | The Octatrack's **LFO Designer**: its editor, parameter writes, and store/undo/paste. Hooks *stock* routines (`gk_stock_lfo_depth_write`, `gk_stock_lfo_store`) and replays displaced stock bytes with `.incbin "stock/NNNN.bin"`. **No generator.** |
| **midisc** | `docs/TECH.md` only | Mentions LFO as a **page mode** (`PAGE_MODE == 2`, "not 0/1 — those are NOTE/LFO"). It navigates around the existing LFO page. **No LFO code.** |
| **octamax** | none | No LFO files. |
| **octabam** | `modules/busverb/reverb_lforoll.asm`, plus `docs/effects/REVERB.md` and `VOICING.md` | Real LFO **generators** — eight of them, one per delay line — but **inside a DSP reverb**, on the DSP56xxx. Effect-internal modulation, not a modulation source a user can route. |

So there is **no prior art for adding a modulation LFO to an Elektron synth
engine.** The existing work is either UI and state manipulation around LFOs that
already exist, or LFOs living inside a DSP effect. That is worth knowing before
assuming the fourth LFO is a solved shape somewhere.

## What octabam's DSP LFOs are nonetheless worth reading for

Not for the DN2's architecture — for the *engineering traps*, which are
CPU-agnostic and which its docs record at length after measuring them:

- **Block-stepped LFOs cause audible artefacts.** The reverb advances its LFOs
  once per audio block rather than per sample; `VOICING.md` traces a crackle to
  exactly that (`dsp/reverb_server.asm:1112` "gates the LFO advance on the call")
  and records the fix as "advance the LFO per sample, or interpolate its value".
  A control-rate LFO that steps a *parameter* is usually fine; one that steps a
  *delay offset* is not.
- **An interpolation fraction must come from the same LFO as the integer part**,
  or the signal jumps backwards once per integer step (`REVERB.md`).
- **Phases of parallel LFOs are deliberately decorrelated** ("crosswise"), which
  matters if a fourth LFO ever shares a free-running phase base with the other
  three.

Read those before writing any LFO advance code, whichever CPU it ends up on.

## What it does not tell us

Nothing about where the DN2 computes its LFOs, how many its engine can run, or
whether its LFO state is an array or three named instances. Those stay open in
`docs/engine-state.md`.
