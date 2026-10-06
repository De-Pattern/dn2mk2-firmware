```
  ▗▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▖
  ▐█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█▌
  ▐█   ▐█▌   ▐█▌   █▌    ██████╗ ███╗   ██╗██████╗
  ▐█ ▝▀▘   ▝▀▘   █▌    ██╔══██╗████╗  ██║╚════██╗
 ▂▃▅▇█▇▅▃▂   █▌    ██║  ██║██╔██╗ ██║ █████╔╝
  ▐█▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█▌    ██║  ██║██║╚██╗██║██╔═══╝
  ▐█▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌▐▌    ██████╔╝██║ ╚████║███████╗
  ▝▀▘▝▘▝▘▝▘▝▘▝▘▝▘▝▘▝▘    ╚═════╝ ╚═╝  ╚═══╝╚══════╝
     ▘ ▝       ▘ ▝         m k 2   ·   m o d
```

# DN2-mk2-Mod

**New synth engines and effects for the Elektron Digitone II, built as
firmware mods you apply to your own OS file.**

The Digitone II ships five machines. This project adds more: wavetable,
granular, resonator and others, running on the instrument's own SHARC+ DSP and
sitting in MACHINE SEL beside the stock ones. Every change is checked in an
emulator before it goes near hardware, and the way back to stock is always one
MIDI transfer away.

It builds on [**dn2_firmware_explore**](https://github.com/xrcstrecords/dn2_firmware_explore)
by Ángel Linares, which mapped the firmware, wrote the tooling, and put the
first new machine (Waverider) on the instrument. Everything from upstream is
here with its history; this repository adds engines on top. The upstream
README is kept at [`docs/UPSTREAM-README.md`](docs/UPSTREAM-README.md).

> **No Elektron firmware lives in this repository, original or modified, and
> none ever will.** You bring the OS file Elektron publish for your instrument;
> every mod applies to *your* copy and checks it is the exact file it was
> measured against before writing anything.

---

## The engines

| | engine | what it is | state |
|---|---|---|---|
| 🌊 | **Waverider** | two-oscillator wavetable machine, after Tonverk's Wavefinder (upstream) | DSP core **passed on hardware** upstream; full build **emulator-gated** here from OS 1.11 |
| ✨ | **GRAINS** | granular synthesis on wavetables, after the Virus TI grain tables: formant grains (SYNC) and clouds (CLOUD) | **reference model + demos**; control layout awaiting sign-off → [`docs/grains.md`](docs/grains.md) |
| 🔀 | **Frequency shifter** | a send/master effect after Tonverk's | planned, next after GRAINS G1 |
| 🎻 | **Resonator** | polyphonic string/modal resonator, after Mutable Instruments Rings (MIT) | planned: port of open-source C to the SHARC |
| 🥁 | **Digitakt II machines** | same DSP family, so their code moves across; you supply both OS files and nothing of Elektron's is redistributed | upstream proved it offline (ONESHOT) |
| 🧪 | **Syntakt / Model:Cycles / Monomachine / Machinedrum voices** | those boxes run their engines on different processors (ColdFire, DSP56300), so these are **new implementations by ear**, not ports | later |

### Hear GRAINS before it exists

`grains/demos/` holds renders from the reference model on Waverider's two
built-in tables:

| file | what to listen for |
|---|---|
| `01_sync_formant_sweep.wav` | one held C2, FMNT −12 → +24: the vowel moves, the pitch does not |
| `02_sync_size_sweep.wav` | SIZE 1 → 4: buzzy and wide → ringing and vocal |
| `03_sync_spread.wav` | SPRD 0 → 7: a doubled, chorused formant |
| `04_sync_talking_bass.wav` | POS and FMNT moving together on the harmonic table |
| `05_sync_melody.wav` | a short line, to hear it as an instrument |
| `06_cloud_density.wav` | CLOUD: sparse → dense, scattered and scanning |
| `07_cloud_pitch_jitter.wav` | CLOUD with pitch scatter: shimmer and smear |

Regenerate them with `python grains/demos.py`.

---

## Before you flash anything

1. **Use OS 1.11.** Every address in this project is measured on Digitone II
   OS 1.11 (sha256 `2af43e65…472e0`). The tools refuse anything else.
2. **Have a 5-pin DIN MIDI cable to the DN2's MIDI IN.** Recovery (hold
   [FUNC] at power-on → [TRIG 4] → Transfer's *Legacy OS upgrade*) does not
   work over USB.
3. **Prove recovery on your unit first** by sending stock 1.11 that way.
4. Then flash a mod through Transfer as you would any OS update.

Recovery is proven on hardware upstream (`docs/flashing.md`). Still: this is
unofficial firmware, Elektron does not support it, and you flash it at your own
risk. Back up your +Drive with Transfer first.

---

## Quick start

Python 3.11+, no runtime dependencies for the tools themselves.

```sh
pip install -e .
dnfw inspect Digitone_II_OS1.11.syx
dnfw mods list
dnfw mods apply Digitone_II_OS1.11.syx --mod waverider -o waverider.syx
```

The upstream mods (`lfo4`, `arpmodes`, `fxmod`, `moddest`, `lfowaves`,
`midiarp`, `arpplocks`, `bootscreen`, `transients`, `songguard`) all work the
same way; see `docs/UPSTREAM-README.md` and `docs/mods.md`.

### The gates

| gate | command | needs |
|---|---|---|
| unit tests | `pytest -m "not slow"` | pytest, numpy |
| GRAINS model | `pytest test/test_grains_model.py` | numpy |
| integrity + signature | `dnfw inspect build.syx` | — |
| boot from reset | `scripts/emu_boot_check.py` | [digikit](https://github.com/m-dwyer/digikit) (ColdFire emulator) |
| DSP voice | `scripts/sharc_waverider_m5.py` | digikit's `work/sharc-emulator`, [selache](https://github.com/js216/selache) |

Upstream works on Windows + WSL. This fork also runs the DSP gates natively on
Linux (`sharc_waverider_render.py` skips the WSL hop when there is none).
Several scripts still expect upstream's paths under `/mnt/d/01_Code/Z_Personal/`;
symlinking your checkouts there is the quickest way through for now.

---

## Layout

```
src/dnfw/         the tool: container, codec, integrity, mods, waverider
grains/           GRAINS: model.py (the reference), demos.py, demos/*.wav
csrc/             our own ColdFire C/asm and SHARC asm (waverider/, lfo4/, ...)
scripts/          builders and emulator gates
test/             pytest
docs/             everything measured, with evidence; grains.md is new here
site/             upstream's in-browser patcher
```

## Changes from upstream

As required by the AGPL, a dated record of what this repository changes:

- **2026-10-06** — forked from `dn2_firmware_explore` at `8c40698`
  (2026-10-01).
- **2026-10-06** — `scripts/sharc_waverider_render.py`: run selache natively
  when WSL is absent.
- **2026-10-06** — GRAINS: `grains/` (reference model, demos),
  `test/test_grains_model.py`, `docs/grains.md`.
- **2026-10-06** — this README; the upstream README moved to
  `docs/UPSTREAM-README.md`.

## Credits

- **[dn2_firmware_explore](https://github.com/xrcstrecords/dn2_firmware_explore)**
  — Ángel Linares. The firmware map, the tooling, the upstream mods and
  Waverider. Its own credits (elektron-firmware-tool, octa-bt-pt, octabam,
  digikit, selache, DNX) are in `docs/UPSTREAM-README.md` and
  `THIRD-PARTY.md`.
- **[digikit](https://github.com/m-dwyer/digikit)** — the ColdFire and
  SHARC emulators (GPL-2.0-or-later), used as external tools.
- **[selache](https://github.com/js216/selache)** — the SHARC+ assembler and
  C compiler (GPL-3.0), used as an external tool.

Not affiliated with Elektron. *Digitone*, *Digitakt*, *Syntakt*, *Tonverk*,
*Model:Cycles*, *Monomachine* and *Machinedrum* are Elektron's; *Virus* is
Access Music's; *Rings* is Mutable Instruments'. Names are used only to
describe what an engine is modelled on.

## Licence

[GNU AGPL-3.0-or-later](LICENSE), as upstream. Use it, fork it, change it;
keep the notices and pass on the same freedoms. A modified version you
distribute, or run as a service, stays open.
