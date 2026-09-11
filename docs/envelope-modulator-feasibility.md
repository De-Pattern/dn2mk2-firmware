# An envelope modulator instead of a fourth LFO

The question: rather than a fourth LFO, could the vacant `[MOD]` slot hold an
**assignable envelope** — an envelope generator routed to a chosen destination?
This is the full assessment, with a same-platform Elektron box that ships the
feature, its firmware read, and a direct comparison to the fourth-LFO path.

## The reference box: Analog Four MKII

The Analog Four / Analog Keys have **assignable envelope modulators** — `Env2`
and `EnvF` route to destinations alongside the LFOs. And the A4 MKII is the
**same platform** as the Digitone II:

```
dnfw inspect Analog-Four_MKII_OS1.55D.zip
  device 0x0b   MAIN OS at 0x40000400 (same load base as DN2)
  ELE3 container, aPLib sections, ColdFire   —   unsigned (no HMAC)
```

`dnfw` reads it, the disassembler reads it, and its parameter table decodes with
the same tooling (14-word/56-byte records, 102 of them, at `0x401870ac`). It is
not committed — it is Elektron's firmware — and lives in the local corpus.

## What the A4 shows: an envelope is just another mod-source page

The decisive finding, read straight from the A4 parameter table. Its modulation
sources — envelopes and LFOs alike — are **the same shape**: a page of six
source-shaping parameters followed by identical destination routing.

| Source | Shaping parameters | Routing |
|---|---|---|
| **Env2** | Attack, Decay, Sustain, Release, Shape, GateLen | **Dest A, Depth A, Dest B, Depth B** |
| **EnvF** | Attack, Decay, Sustain, Release, Shape, GateLen | **Dest A, Depth A, Dest B, Depth B** |
| **LFO1** | Speed, Multiplier, Fade, Start Phase, Trig Mode, Waveform | **Dest A, Depth A, Dest B, Depth B** |
| **LFO2** | (same as LFO1) | (same) |

So on the A4 an "envelope modulator" is not a special subsystem — it is a
modulation-source page whose shaping half is an ADSR instead of an LFO's
waveform controls, wired to the **same** destination routing. Env and LFO are
interchangeable at the framework level.

## The Digitone II already has both halves

An assignable envelope needs two things: an **envelope generator** and
**destination routing**. The DN2 ships both, just never combined:

- **Envelope generators.** The Amp envelope (group 11: Delay, Attack, Hold,
  Decay, Sustain, Release — AHDSR) and the Filter envelope (group 13: Env Delay,
  Attack, Decay, Sustain, Release, Env Depth — ADSR). These are complete
  envelope generators; they are *fixed-destination* (amplitude, filter cutoff).
- **Destination routing.** Each LFO carries a `DEST` field, applied through the
  shared `ModConfig` / `ModDestListView` framework the DN2 runs
  (`docs/parameter-table-consumer.md`). The DN2 is **single-destination** — one
  `DEST` per source — where the A4 has `Dest A` and `Dest B`.

An assignable envelope on the DN2 is therefore: an envelope generator (which
exists) whose output goes to a `DEST` (which exists for LFOs). The A4 proves
that exact combination runs on this CPU and this framework.

## Feasibility, compared to a fourth LFO

The **structural cost is identical**. A fourth `[MOD]` slot — LFO or envelope —
needs the same work from `docs/lfo4-feasibility.md`: a parameter block
(repurpose ten dead ERR records, done for the LFO in `scripts/build_lfo4_test.py`),
a page-view, MOD-key wiring, and the engine made to run a fourth source. Neither
option escapes that.

They differ only in the **source**:

| | Fourth LFO | Envelope modulator |
|---|---|---|
| Parameter block | clone an LFO block (SPD MUL FADE DEST WAVE SLEW SPH MODE DEP) | build from Amp/Filter env params (ATK DEC SUS REL … ) + a DEST |
| Generator | **3 complete LFO instances to clone** | **envelope generators exist (Amp, Filter)** but are fixed-destination |
| Destination routing | the single-`DEST` path, proven, 3× live | the **same** single-`DEST` path |
| Precedent | on the DN2 itself | on the A4 (same CPU, same framework), `Env2` page = the template |
| Engine change | run a 4th LFO in the modulation tick | run an envelope generator as a mod source in the tick |

**Verdict.** Both are feasible and cost about the same structurally. The
**fourth LFO is the lower-risk first build**, because the DN2 already ships three
complete `LFO-with-DEST` sources to clone wholesale — nothing about the source is
new. The **envelope modulator is genuinely feasible and arguably more musically
useful**: its two halves (an envelope generator, a `DEST`) both exist in the
DN2, and the A4 is a same-platform worked example of marrying them — its `Env2`
page is the literal template for the parameter block. What it adds over the LFO
is the *integration*: wiring an existing envelope generator to run as a
`DEST`-routed mod source, a combination the DN2 does not currently ship as a
unit even though both pieces are present.

The engine gate is the same for both (`docs/lfo4-feasibility.md`): the
modulation tick must run the new source. For an envelope that means running an
envelope generator — code the DN2 already has for Amp and Filter — as a
destination-routed source, exactly as the A4's tick does through the shared
framework.

## Recommendation

Prove the mechanism with the **fourth LFO first** — it is a straight clone of a
working source, so it isolates the MOD-slot infrastructure (table, page-view,
nav, engine bound) without any novel generator. Once that path works, the
**envelope modulator reuses the same infrastructure** with an envelope generator
swapped in for the LFO generator and its `DEST` routed the same way. The A4's
`Env2`/`EnvF` pages show the target shape, and the DN2's Amp/Filter envelopes
supply the generator. So the envelope is not an alternative that avoids the
fourth-LFO work — it is the natural *second* modulator once that work is done.

## What was read, and what is still worth a look

- The A4 and DN2 parameter tables (structure and modulation-source layout) —
  the decisive evidence above, from the disassembled firmware.
- The DN2's own envelope generators (Amp AHDSR, Filter ADSR) confirmed present.
- Still worth reading, if the envelope is pursued: the A4's modulation tick —
  how it advances an envelope source and applies it through `Dest A/B` — because
  the frameworks are shared, that is close to what the DN2's tick would do for a
  single-`DEST` envelope source. This is the same write-side tick that
  `docs/lfo4-feasibility.md` needs for the LFO, so the two investigations
  converge.
