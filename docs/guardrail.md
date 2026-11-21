# The voice/load guardrail (v0.69)

Suggested by tester _aLinG_; asked for by the owner (2026-11-19, 2026-11-21: "push the guardrail
into that one as well").

## What it does

The DSP's frame is 666,667 cycles. The stock engines and the silent frame take about 416,000
(docs/sharc-load.md), so about 250,000 are left for the mod's machines. Past that the frame
guard (v0.27/v0.36) leaves the oldest voices out and notes drop. The guardrail stops a kit from
asking for that: **MACHINE SEL refuses a machine that would take the kit's total past the
limit**, and a box says so for two seconds:

    DSP LIMIT
    TOO MANY HEAVY
    MACHINES IN KIT

The track keeps the machine it had. A machine lighter than the one it replaces, and every stock
machine (FM TONE, FM DRUM, WAVETONE, SWARMER, MIDI), is always allowed, so a kit can always be
made lighter.

## The numbers

`src/dnfw/sampler/guardrail.py` generates `csrc/sampler/guard_tab.h`. A machine's weight is its
per-voice cost (instructions + 4 x L2 + 10 x DDR a block) times the voices a track of it holds:
a Monomachine/FM+ track 2 (v0.36), every other track 1.

| Machine | Per voice | Voices | Weight |
|---|---:|---:|---:|
| VO-6 | 26,251 | 2 | 52,502 |
| DPRO DDRW | 15,320 | 2 | 30,640 |
| FM+ PAR | 14,081 | 2 | 28,162 |
| DPRO WAVE | 13,892 | 2 | 27,784 |
| FM+ DYN | 9,525 | 2 | 19,050 |
| FM+ STAT | 9,454 | 2 | 18,908 |
| DPRO DENS | 8,517 | 2 | 17,034 |
| SID 6581 | 8,408 | 2 | 16,816 |
| PERC (Machinedrum) | 21,000 | 1 | 21,000 |
| ONESHOT, FLEX and the sample machines | ~17,500 | 1 | ~17,500 |

LIMIT is 225,000: 0.9 of what is free, leaving room for what the runner does not model (the
unit's memory stalls vary). So four VO-6 tracks (210,008) are allowed and a fifth is refused.

The Monomachine/FM+ costs were measured on v0.69's DSP program on the SHARC runner
(`DNFW_COST_ONLY=mnm --steps cost`, 2026-11-21); PERC's and the sample machines' are from
docs/dsp-cost.md (v0.39; the Machinedrum machines have been lighter since v0.51, so theirs is
on the safe side).

## Where it lives

- `csrc/sampler/guard.c`: `gr_kit_total`, `gr_allowed(track, type)`, `gr_visible`, `gr_draw`.
- `csrc/sampler/rec.c` `smp_machine_commit` asks `gr_allowed` first.
- `csrc/waverider/page.c` `wr_screen` draws the box last, over any page.

## How it is checked

- Gate step `guardrail` (ColdFire emulator): four VO-6 tracks poked in, a fifth refused with the
  box drawn, the commit refused with the track's machine unchanged, a stock machine allowed, and
  VO-6 allowed again once the others are back to stock.
- SHARC runner, `stress` part: scenario H (8 VO-6 voices, 210,008) and H2 (6 P-I tracks + 5
  ONESHOTs, 213,655) play with no voice left out on the memory clock; scenario I (16 VO-6
  voices, past the limit) does leave voices out, so the margin is real.
- `test/test_guardrail.py`: the header is current, every mod machine weighs and stock does not.

## Limits

- The weight is a typical track's, not its worst case: a Machinedrum TYPE p-locked to a heavy
  machine can cost more than 21,000. The frame guard still catches it.
- It checks MACHINE SEL only. A project or kit loaded from before v0.69 that is already past the
  limit loads as it is (the frame guard handles it as before).
