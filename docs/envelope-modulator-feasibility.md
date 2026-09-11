# An envelope modulator instead of a fourth LFO

The question: rather than a fourth LFO, could the vacant `[MOD]` slot hold an
**assignable envelope** — an envelope generator routed to a chosen destination,
the way the LFOs are? This is the assessment, with a same-platform Elektron box
that already ships the feature as the reference.

## The reference box: Analog Four MKII

The Analog Four / Analog Keys have **assignable envelope modulators** — `ENV2`
and `ENVF` route to destinations, alongside the LFOs. And crucially the A4 MKII
is the **same platform** as the Digitone II:

```
dnfw inspect Analog-Four_MKII_OS1.55D.zip
  device 0x0b   MAIN OS at 0x40000400 (same load base as DN2)
  ELE3 container, aPLib sections, ColdFire   —   unsigned (no HMAC)
```

So `dnfw` reads it, the disassembler reads it, and it is directly comparable.
(It is not committed — it is Elektron's firmware. It lives in the local corpus.)

## Both machines share one modulation framework

The decisive finding. The A4's modulation is a general matrix — strings
`ModDestListView`, `ModConfig`, `SoundModConf`, `SoundModConfParam`, `Dest A/B`,
`Depth A/B`, with `ENV1 ENV2 ENVF LFO1 LFO2` as sources routed to destinations.

**The Digitone II has the same framework.** Its MAIN OS carries `ModConfig`,
`ModDestListView`, `SoundModConf`, `ModSetupView`, `ModulationCopy`,
`MODULATION SETUP` — the same class family, shared Elektron code. The DN2 differs
in two ways: it exposes three LFOs (not envelopes) as sources, and it is
**single-destination** — each source has one `DEST`, where the A4 has `Dest A`
*and* `Dest B` with independent depths. So the DN2 runs the simpler subset of the
same framework: one source → one destination.

That changes the picture. The two are not different modulation designs to bridge;
they are the **same design** with different sources wired up. An envelope
modulator on the DN2 is a question of exposing an envelope *source* through a
framework the DN2 already runs — not of porting the A4's system onto a foreign
architecture.

## Feasibility, compared to a fourth LFO

The dominant cost is the same for both. A fourth `[MOD]` slot — LFO or envelope —
needs the structural work in `docs/lfo4-feasibility.md`: a parameter block (table
relocation, ~56 base repoints), ~43 bound bumps, a page-view, and MOD-key
navigation. Neither option avoids that.

The two differ only in the **source**:

| | Fourth LFO | Envelope modulator |
|---|---|---|
| Generator | 3 working LFO instances to clone | envelope generators exist (Amp, Filter) but are fixed-destination |
| Destination routing | the single-`DEST` path, proven, 3× live | the **same single-`DEST` path** — the routing half already exists and runs; only the envelope *source* is new |
| Page-view | clone `LfoPageView` | a new or adapted page-view for envelope params |
| Precedent on the platform | on the DN2 itself | on the A4 (same framework, same CPU) |

**Verdict.** A fourth LFO is the lower-risk first build, because the DN2 already
ships three complete, working `LFO-with-DEST` instances to clone wholesale — the
generator, the routing, and the page-view all exist and run. An envelope
modulator is genuinely feasible and arguably more musically interesting, and the
A4 proves it works on this exact platform and framework — but it needs one thing
the fourth LFO does not: **an envelope generator wired as a source into the DN2's
single-destination `ModConfig` path.** The routing itself is not the gap — the
DN2's one-`DEST` mechanism is exactly what an envelope modulator would use, the
same as an LFO. The gap is only the source type. Whether that path is already latent in the DN2 (inherited
from the shared code the A4 uses) or must be added is the pivotal unknown, and it
is answerable by reading the DN2's mod-source dispatch — the code behind
`ModConfig`/`ModDestListView` — and checking whether it enumerates a source type
that an envelope can be, as the A4's does.

## What to read next, in both images

1. **DN2 `ModConfig` / `ModDestListView`** — how a mod source is represented and
   dispatched, and whether the source type is open (could be an envelope) or
   hardcoded to LFOs. This is the whole question.
2. **A4 `ENV2`/`ENVF` as a source** — how the A4 registers an envelope with the
   shared framework. Because the frameworks are the same code, whatever the A4
   does to add an envelope source is close to what the DN2 would need. This is
   the value of having the A4 firmware: it is a **worked example of the exact
   change**, on the same CPU and the same modulation system.

If the DN2's framework already admits an envelope source, an envelope modulator
could be *less* work than a fourth LFO. If it is LFO-specific, the two converge
on the same effort, and the fourth LFO wins on having three live templates.

Either way the first build is the same: the inert bounds sweep of
`docs/lfo4-feasibility.md` Stage 1, which the slot needs regardless of what fills
it.
