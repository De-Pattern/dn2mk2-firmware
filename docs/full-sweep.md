# The full sweep: smooth, stable, like stock (planned)

Owner, 2026-11-14: after the next two builds or releases (stereo's test build, then the
next one), a full sweep of the whole mod for optimisation and stability. Not only CPU: the
aim is that the DN2 with our mod feels as snappy, reliable, smooth and intuitive as stock
Elektron machines do, with every small thing accounted for.

## What it covers

- **CPU and audio**: DSP cost per block (ours against stock's), drops, voice stealing
  beyond stock's own, clicks, underruns.
- **Motion and feel**: knob turns (response, step size, acceleration, the value's
  latency to the sound and to the screen), encoder detents, held-key behaviour.
- **Screens and visuals**: redraw rate, flicker, consistency with stock's look, how our
  pages and overlays draw.
- **Navigation**: how users reach and leave every feature of ours, against stock's
  conventions (FUNC combos, YES/NO, page order).
- **How features are implemented**: each feature's hooks, its cost on paths it doesn't
  use, what can be simplified or removed.
- **Lag and drops**: UI latency, MIDI timing, sequencer jitter, save/load times.

## Comparing against stock and other Elektron machines

Research first how to measure each of these, then measure stock DN2 and our build the same
way, and where useful the Digitakt II, Analog Rytm, Octatrack:

- DSP: the SHARC runner's instructions per block, stock and ours, every machine type.
- ColdFire: cycles per UI tick and per redraw in the emulator; idle headroom.
- On the instrument: measurement builds (as `modview1/2` did for the redraw rate) for
  knob-to-sound and knob-to-screen latency, frame times, and MIDI in/out timing.
- A checklist of stock behaviours each of our screens should match.

## Order

1. Stereo test build (0.54-t1).
2. The next build or release.
3. This sweep (before or alongside the MD/MM rewrite, docs/md-mm-rewrite.md, as the owner
   decides).
