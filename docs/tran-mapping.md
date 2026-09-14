# `TRAN` maps onto the transient bank at four units per slot

**Measured on hardware, 2026-09-14.** The question `docs/pcm-hunt.md` §16 left
open — *"how `TRAN`'s 125 positions map onto 34 entries"* — is answered for the
upper half of the bank, and the rule is exact:

```
TRAN = 4 x slot - 8            slot = TRAN / 4 + 2
```

**Two separate sweeps agree**, which matters more than either one's precision —
they differ in analysis bandwidth, and both land on a stride of 4 and an offset
of −8:

| sweep | band | fit over slots 16–32 | worst residual |
|---|---|---|---|
| `docs/data/tran-sweep-wide.csv` | ±150 Hz | `TRAN = 3.997 x slot - 7.92` | **0.07** |
| `docs/data/tran-sweep-narrow.csv` | ±55 Hz | `TRAN = 4.011 x slot - 8.06` | 0.38 |

Both raw sweeps are committed, and both reproduce:

```
python scripts/tran_fit.py docs/data/tran-sweep-wide.csv
```

`tran_fit.py` fits the uncontaminated range as well as the whole run. The wide
sweep places slot 33 at `TRAN` 124.0 — the exact top of the knob's travel.

Per-slot, from the wide sweep:

| slot | TRAN range | centre | `4 x slot - 8` | diff |
|---|---|---|---|---|
| 16 | 53–59 | 56.1 | 56 | +0.1 |
| 18 | 61–67 | 64.0 | 64 | 0.0 |
| 20 | 69–75 | 72.0 | 72 | 0.0 |
| 22 | 77–83 | 79.9 | 80 | −0.1 |
| 24 | 85–91 | 88.1 | 88 | +0.1 |
| 26 | 93–99 | 96.0 | 96 | 0.0 |
| 28 | 101–107 | 104.0 | 104 | 0.0 |
| 30 | 109–115 | 112.0 | 112 | 0.0 |
| 32 | 117–123 | 120.0 | 120 | 0.0 |

Each even slot is dominant across **seven consecutive `TRAN` values**, with a
**one-value gap** between runs — 60, 68, 76, 84, 92, 100, 108, 116 — where the
silent odd slot is at full weight and the synth body shows through at 278 Hz.

**So the engine interpolates**, over a four-unit stride, and the silent slots
prove it: they are not merely absent, they are audibly weighted in.

## How it was measured

The owner's design, and it is why this worked where the earlier attempt could
not.

`scripts/make_marker_transients.py` put five distinctive sounds at known slots
and asked which `TRAN` values played them. **That assumed each entry is heard at
one position.** It is not — the entries blend, so a marker fades in and out
across a range and every reading is an opinion about where the middle of a fade
was.

`scripts/make_probe_transients.py` instead puts a **pure tone in every even slot
and silence in every odd one**, each tone a different frequency. The energy in
tone *k*'s bin then *is* the weight the engine gives slot 2k, and the question
becomes "where is this maximal" — which survives blending instead of fighting
it.

`scripts/tran_sweep.py` drives it; `scripts/tran_fit.py` fits the result.

### `TRAN`'s MIDI address, confirmed twice

| source | value |
|---|---|
| Elektron manual, Appendix C — SYN page 4, data entry knob C | CC 72, NRPN MSB 1 / LSB 99 |
| our parameter table, the `Drum Transient` record | 227 = 1 x 128 + 99 |

**The value goes in the data-entry MSB (CC 6), not as a 14-bit pair.** Sending
`MSB = value >> 7` is the textbook encoding and it is wrong here: `TRAN` spans
0..124, so that MSB is always zero and the parameter never leaves its first
position. On the instrument it reads as *"it keeps repeating the same
transient"*, which is how the owner caught it after a refactor introduced it.

## The low half, and why its error is not a finding

Nine slots fit exactly. Below 3 kHz the measured centres sit high, and the
amount they sit high by **decays monotonically with the probe's frequency**
(narrow sweep, ±55 Hz — the wide one could not place these slots at all):

| slot | probe tone | measured | `4 x slot - 8` | bias |
|---|---|---|---|---|
| 0 | 650 Hz | 4.0 | −8 | **+12.0** |
| 2 | 950 Hz | 12.7 | 0 | **+12.7** |
| 4 | 1250 Hz | 21.2 | 8 | **+13.2** |
| 6 | 1550 Hz | 27.7 | 16 | +11.7 |
| 8 | 1850 Hz | 33.6 | 24 | +9.6 |
| 10 | 2150 Hz | 39.1 | 32 | +7.1 |
| 12 | 2450 Hz | 44.7 | 40 | +4.7 |
| 14 | 2750 Hz | 49.5 | 48 | +1.5 |
| 16–32 | 3050 Hz+ | — | — | **≈ 0** |

**A bias that tracks frequency is a property of the measurement, not of the
mapping.** If `TRAN` genuinely bent at the bottom of its range, the error would
not care what pitch the probe happened to use there.

The contaminant is the FM DRUM body — around 278 Hz, with harmonics at 834,
1112, 1668, 1946, 2224, 2502, 2780 Hz, each near a probe tone. **The body cannot
be silenced on this machine**, so two things were changed instead: the analysis
band was narrowed from ±150 Hz to **±55 Hz** (the FFT resolves ~11 Hz, so ±150
was about fourteen times wider than it needed to be), and the transient level
was pushed to maximum.

**Narrowing bought coherence, not accuracy, and it cost a little at the top.**
At ±150 Hz the low slots could not be placed at all — slot 0 was "loudest"
across `TRAN` 0..100 and slot 6 across 8..52, readings with no centre to speak
of. At ±55 Hz every low slot became a contiguous run, so the bias above is
measurable rather than noise; the centres are still high by the amounts shown.
The narrow sweep's high half is slightly the worse of the two (0.38 against
0.07), which is the expected cost of throwing away signal. Neither change moves
the answer: both sweeps give 4 and −8.

The original ±150 Hz was chosen to keep neighbouring probe tones from leaking
into each other, and never checked against the voice the tones are heard
*through*. That is the whole error, and it is the same shape as every detector
failure in `docs/pcm-hunt.md`.

## 32 of the 34 entries are reachable

Two independent arguments agree, and neither needs the contaminated half.

**Arithmetic.** `TRAN` spans 0..124, which is 125 values, and the measured
stride is 4. `124 / 4 = 31` steps, so **32 entries**. Thirty-four entries four
apart would need `33 x 4 = 132` values and only 125 exist — impossible.

**The fit.** `TRAN = 4 x slot - 8` places slot 2 at `TRAN` 0 and slot 33 at
`TRAN` 124. That is exactly 32 entries, slots 2 through 33.

So **slots 0 and 1 cannot be selected at all.** The bank holds 34 entries and
the sequencer reaches 32 of them.

This confirms an inference `docs/pcm-hunt.md` §14 has carried since the bank was
first measured — *"`TRAN` spanning 0..124 with 4-step interpolation implies
32"* — which was recorded there as a disagreement with the measured extent of 34.
Both were right: the extent is 34, the reachable count is 32.

## For the tool

The Transient Swapper should say that **slots 0 and 1 are not reachable from
`TRAN`**, and that every other slot sits at `TRAN = 4 x slot - 8`. A user
replacing slot 20 hears it at `TRAN` 72; a user replacing slot 0 hears nothing,
which is worth saying before they spend a sample on it.
