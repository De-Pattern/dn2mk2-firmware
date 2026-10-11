```
  ▐█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█▌
  ██████╗ ███╗   ██╗██████╗
  ██╔══██╗████╗  ██║╚════██╗
  ██║  ██║██╔██╗ ██║ █████╔╝
  ██║  ██║██║╚██╗██║██╔═══╝
  ██████╔╝██║ ╚████║███████╗
  ╚═════╝ ╚═╝  ╚═══╝╚══════╝
  ▘ ▝   m k 2   ·   m o d
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
| 🌊 | **Waverider** | wavetable machine after Tonverk's Wavefinder (upstream): **W5** adds 11 original tables, TBL with table names, a smooth POS glide, a display that follows p-locks and motion; **W2** puts every page-1 control to work (LEV, and a per-voice scanner: RATE, MPOS, MLEV, MOVE with 8 shapes) and gives the LFO/MOD lists Waverider's own names | upstream DSP core **passed on hardware**; W5 **flashed and working** on the owner's unit (tables, save/load); W2 **emulator-gated**, awaiting a flash → [`docs/w2-scanner.md`](docs/w2-scanner.md), [`docs/w5-tables.md`](docs/w5-tables.md) |
| ✨ | **GRAINS** | granular synthesis on wavetables, after the Virus TI grain tables: formant grains (SYNC) and clouds (CLOUD) | **reference model + demos**; control layout awaiting sign-off → [`docs/grains.md`](docs/grains.md) |
| 🔀 | **Frequency shifter** | a send/master effect after Tonverk's | planned, next after GRAINS G1 |
| 🎻 | **Resonator** | polyphonic string/modal resonator, after Mutable Instruments Rings (MIT) | planned: port of open-source C to the SHARC |
| 🥁 | **Digitakt II machines** | same DSP family, so their code moves across; you supply both OS files and nothing of Elektron's is redistributed | upstream proved it offline (ONESHOT) |
| 🧪 | **Syntakt / Model:Cycles / Monomachine / Machinedrum voices** | those boxes run their engines on different processors (ColdFire, DSP56300), so these are **new implementations by ear**, not ports | later |

### Make a wavetable from any sample

`dnfw waverider slice voice.wav -o voice_wt.wav --preview sweep.wav` turns any
short WAV into a wavetable the way Tonverk does: one exact cycle per frame where the
sound is pitched (so a voice becomes a playable table of its own waveforms), fixed
windows where it is not (`_wt1024` in the name sets their size, as on Tonverk), each
frame band-limited. The output is a standard wavetable WAV (Serum, Vital, Tonverk).

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

**Read [`docs/SAFETY.md`](docs/SAFETY.md).** It lists every way a flash could
harm a DN2 and what stops each one. In short:

1. **Use OS 1.11.** Every address in this project is measured on Digitone II
   OS 1.11 (sha256 `2af43e65…472e0`). The tools refuse anything else.
2. **The bootstrap is never touched.** `dnfw mods apply` refuses to write a
   build whose bootstrap, updater, metadata or Outbox section differs from
   stock by a single byte, so the recovery route always survives.
3. **Have a 5-pin DIN MIDI cable to the DN2's MIDI IN.** Recovery (hold
   [FUNC] at power-on → [TRIG 4] → Transfer's *Legacy OS upgrade*) does not
   work over USB. **Prove it once with stock 1.11** before flashing anything
   modified.
4. **Preflight the exact file you send:**
   `dnfw preflight Digitone_II_OS1.11.syx build.syx` must print `PASS`.
5. **Back up the +Drive**, start at **low volume**, and run the regression
   check in `docs/SAFETY.md` after every flash.

This is unofficial firmware. Elektron does not support it, and you flash it at
your own risk.

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
| **safety preflight** | `dnfw preflight STOCK.syx build.syx` (also run by `mods apply`) | — |
| safety guard's own tests | `pytest test/test_safety.py` | stock 1.11 in `00_Resources/` |
| **everything, on the file you flash** | `scripts/ship_gate.py STOCK.syx build.syx` → `CLEARED TO FLASH` | all of the below |
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
- **2026-10-06** — safety: `src/dnfw/safety.py` (the preflight, enforced in
  `dnfw mods apply`), `dnfw preflight`, `test/test_safety.py`,
  `docs/SAFETY.md`.
- **2026-10-11** — Waverider W5: `dnfw.waverider.factory` (11 original tables),
  the tables moved to DSP DDR, TBL on `DRIF`, the POS glide (`machine5_live.asm`,
  `live.glide`), the display following the heard value (`page.c`), the display data
  as its own RAM chunk; the preflight's DSP limit tightened to the uploader's real
  check; `scripts/sharc_ddr_ceiling.py`, `scripts/emu_install_snapshot.py`;
  `docs/w5-tables.md`.
- **2026-10-11** — `scripts/ship_gate.py`: every gate on the exact file, every build
  (`CLAUDE.md`); `docs/SAFETY.md`: the recovery cable's role.
- **2026-10-11** — Waverider W2: LEV and the scanner (RATE, MPOS, MLEV, MOVE) on page
  1, in `machine5_live.asm` and `live` (bit-exact); Waverider's names in every
  destination list (`wr_names`, `page.c`); the code ranges a CODE chunk executes,
  recorded for the gate (`__text_end`, `labels`); `dnfw waverider slice`
  (`waverider.slicer`); `docs/w2-scanner.md`.

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
