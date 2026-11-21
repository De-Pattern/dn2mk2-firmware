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

`src/dnfw/sampler/guardrail.py` generates `csrc/sampler/guard_tab.h`. A machine's weight is the
cycles a voice of it costs as the frame guard sees them (the SHARC runner's memory clock,
controls moving at random: the slope from 2 to 6 voices), times the voices a track of it holds:
a Monomachine/FM+ track 2 (v0.36), every other track 1. PERC's TYPE can be p-locked, so it
weighs its heaviest family's voice (P-I).

| Machine | Per voice | Voices | Weight |
|---|---:|---:|---:|
| DPRO DENS | 58,339 | 2 | 116,678 |
| VO-6 | 46,210 | 2 | 92,420 |
| DPRO DDRW | 31,685 | 2 | 63,370 |
| FM+ PAR | 29,731 | 2 | 59,462 |
| DPRO WAVE | 27,337 | 2 | 54,674 |
| FM+ STAT | 22,010 | 2 | 44,020 |
| FM+ DYN | 21,976 | 2 | 43,952 |
| SID 6581 | 18,915 | 2 | 37,830 |
| PERC (any Machinedrum machine) | 45,035 | 1 | 45,035 |
| ONESHOT, WERP, REPITCH, GRID, SLICE, FLEX | 28,800–29,400 | 1 | the same |
| STRETCH | 11,278 | 1 | 11,278 |

**LIMIT is 320,000.** The frame guard lets our voices run until 0.6 of the frame (401,040 on the
runner) and, before each voice, wants its expected cost (its last cost x 1.5, at least 60,000)
to fit; our dispatch's own work is about 30,000 a block. So a kit's voices all fit while their
total is at most 401,040 - 30,000 - max(60,000, 1.5 c) + c for the last voice's cost c: about
322,000 at the least (STRETCH last). In tracks: three VO-6 tracks (277,260) are allowed and a
fourth refused; two DENS; seven PERC; eleven sample tracks (or more STRETCH).

The first weights (v0.69's first try: the cost step's instructions + 4 x L2 + 10 x DDR, with a
limit of 225,000) were too light: four VO-6 tracks, inside that limit, still lost voices on the
runner (7 in 128 voice-blocks), so they were measured again as the guard sees them.

## Where it lives

- `csrc/sampler/guard.c`: `gr_kit_total`, `gr_allowed(track, type)`, `gr_visible`, `gr_draw`.
- `csrc/sampler/rec.c` `smp_machine_commit` asks `gr_allowed` first.
- `csrc/waverider/page.c` `wr_screen` draws the box last, over any page.

## How it is checked

- Gate step `guardrail` (ColdFire emulator): three VO-6 tracks poked in, a fourth refused with the
  box drawn, the commit refused with the track's machine unchanged, a stock machine allowed, and
  VO-6 allowed again once the others are back to stock.
- SHARC runner, `stress` part, on the memory clock: H (three VO-6 tracks, 277,260), H2 (seven
  P-I tracks, 315,245) and H3 (eleven ONESHOTs, 318,043) play every block with no voice left out;
  I (sixteen VO-6 voices, past the limit) does leave voices out.
- `test/test_guardrail.py`: the header is current, every mod machine weighs and stock does not.

## Limits

- It counts every track as sounding. A kit whose tracks rarely play together could fit more, and
  the frame guard stays as the backstop for what a weight can't see (p-locks of other parameters,
  the unit's real memory stalls, not yet measured on hardware).
- It checks MACHINE SEL only. A project or kit loaded from before v0.69 that is already past the
  limit loads as it is (the frame guard handles it as before).
