# PING: Waverider's filter section, as a reference model first

**Status: reference model + audition WAVs (2026-10-13). No firmware yet.** The owner
picks and tunes the sound by ear; then the DSP code is written to match this model
bit for bit, as W2's scanner matches `dnfw.waverider.live`. Design and history are
in `docs/ROADMAP.md` ("A pingable filter").

`ping/model.py` (the model), `ping/demos.py` (renders `ping/demos/*.wav`),
`test/test_ping_model.py`.

## The section

One filter per voice after the wavetable reader. TYPE picks the core; all four share
one zero-delay-feedback (TPT) engine, keytracking, its own envelope, a built-in
strike, a loop limiter and a hard output ceiling.

| TYPE | core | sounds like |
|---|---|---|
| SVF | trapezoidal state-variable, low-pass | clean, glassy plucks |
| LADR | 4 one-pole stages in a tanh-compressed loop (Roland/Moog topology) | thick, round, squelchy |
| VCFQ | resonant band-pass that can tip into a soft, bounded self-oscillation | the marble on the bowl |
| LPG | vactrol (fast rise, slow, darkening fall) opening level and cutoff together | the bongo |

Controls: TYPE FREQ RES DRIVE / ATK DEC CURVE ENV, plus STRIKE (the click's level).

## Three choices, and why

- **RES is ring time, not Q.** With a fixed Q, a filter rings for less time the higher
  the note. So RES sets the ring's time constant directly (1 ms to 2 s), and the
  damping is derived from it and the cutoff, so a ping decays the same at every
  pitch (`test_res_is_ring_time_and_the_same_at_every_pitch`).
- **The loop limiter is transparent below its knee.** The first version softened
  every sample, which acted as extra damping and killed every ring within ~50 ms. Now
  it is exactly linear up to 1.0 and only rounds a hard hit at high RES.
- **The strike is scaled by pitch** for SVF and VCFQ: a struck SVF rings in
  proportion to its coefficient g (measured: ~35 g per unit of click), so the click
  is scaled by 1/g. Unscaled, a note-72 ping drove the limiter and came out with its
  3rd harmonic at -1 dB: exactly the "too dirty" sound. Scaled, the marble's 2nd
  harmonic is at -116 dB and its 3rd at -30 dB (`test_the_ring_is_round`).

Every type stays below the ceiling at full RES, DRIVE, STRIKE and ENV on a loud saw
(`test_every_type_is_bounded_at_its_most_extreme`).

## The audition WAVs

| file | what to listen for |
|---|---|
| `01_svf_glass` | glassy keytracked plucks |
| `02_ladr_thick` | the 4-pole on a saw bass, envelope opening it |
| `03_vcfq_marble` | strike-led, high Q, short exp decay: the marble |
| `04_lpg_bongo` | the vactrol tail |
| `05_curve_log_lin_exp` | one ping, CURVE log, linear, exp (two each) |
| `06_resonance_rise_all_types` | each type struck as RES rises: round, never blown out |
| `07_types_side_by_side` | the same phrase through SVF, LADR, VCFQ, LPG on the VOX table |
| `08_vcfq_liquid_fast` | 16ths at 150 BPM near self-oscillation |

## Open

- The owner's verdict on each type, by ear, and tuning from it.
- Where its eight controls live (Waverider's own records: `docs/ROADMAP.md`).
- The DSP cost: a 4-pole loop per sample for 16 voices, measured with the idle-load
  probe before anything ships.
