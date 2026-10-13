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

## As a filter type on every machine: feasibility (2026-10-13)

The owner wants PING on the FLTR page, for any machine. Answered with the instruments:

**ColdFire [D].** The FLTR tab of MACHINE SEL is built like the SYN tab Waverider
extended:
- the list `0x401ddd40` = `{0, 1, 4, 3, 5, 2}` (6 entries, UI order), copied into a
  `std::vector` by `0x4004dae2` (`pea 0x18`, called from the view's builder at
  `0x4005b4de`), beside the machine list `0x401ddd58` / `0x4004d8b6`;
- the names: 12-byte rows `{long, short, 0}` at `0x401f77ac` (Multi-Mode/MM, Lowpass
  4/LP4, Equalizer/EQU, Comb-/COMB-, Legacy LP/HP/LEG, Comb+/COMB+), read by
  `0x400dc3a4` (long) and `0x400dc3ca` (short), each `moveq #5` bounded. The row after
  Comb+ is the machine table's FM Tone, so a 7th name goes in a cave, as Waverider's
  machine names did.
So a 7th filter repeats Waverider's ColdFire steps (`docs/machine-list.md`): the list,
the names, then whatever else bounds a filter type at 5 (stored-sound LOAD, the FLTR
page tables, the slot-to-id map), with type 6 shown to the UI as Multimode, whose page
fits PING one to one (ATK DEC SUS->CURVE REL->STRIKE / FREQ RESO->ring TYPE->sub-type
ENV).

**DSP [E].** `scripts/sharc_filter_probe.py` runs the stock per-block routine on the
stock section 7 with each filter type in frame field `180 + 2t`, and reads the record:

| ColdFire type | 0 | 1 | 2 | 3 | 4 | 5 | **6** | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| DSP number (record `+0x1dc`) | 1 | 3 | 2 | 4 | 5 | 6 | **0** | 0 | 0 | 1 |

DSP number 0 is "no filter": the per-track chain skips the filter stage
(`0x8052dbc0[n]`, bound `r1 = 7; compu(r2, r1); if ge jump` at sw `0x1c9581`). So
**type 6 already reaches the DSP as a track with no filter, and no stock DSP table,
bound or map needs to change.** PING runs inside Waverider's own per-block loop
(`machine5_live.asm`), which is entered after every machine has rendered and before
the per-track chain: for every track whose frame filter type is 6, whatever its
machine, it filters the track buffer where the stock filter would have, reading the
filter settings the unpack already put in the track record as floats (`+0x1c8` TYPE,
`+0x1cc` FREQ, `+0x1d0` RESO, `+0x1ec..+0x1fc` the envelope, `+0x204` depth, `+0x208`
key tracking).

To confirm while building: that every machine's buffer is complete at the loop's
entry, and that nothing in the chain runs before the filter stage.

## Open

- The owner's verdict on each type, by ear, and tuning from it.
- Where its eight controls live (Waverider's own records: `docs/ROADMAP.md`).
- The DSP cost: a 4-pole loop per sample for 16 voices, measured with the idle-load
  probe before anything ships.
