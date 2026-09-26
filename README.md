# dn_firmware

Tools for inspecting, modifying and rebuilding **Elektron Digitone** firmware —
the Digitone II (DN2) and the original Digitone / Digitone Keys (DN1) — and a
set of mods for the Digitone II built with them.

**This repository holds code and documentation only.** It contains no Elektron
firmware, original or modified, and never will. Bring your own OS file — the
one Elektron publish for your instrument. Every mod applies to *your* copy of
it, and checks that copy is the one it was measured against before it writes.

## Mods for the Digitone II 1.11

Applied with `dnfw mods apply`, or in the browser on the project site,
**<https://angellinares.github.io/dn2_firmware_explore/>**, which runs entirely
in your browser, with nothing uploaded. The browser and the command line
produce the same file, byte for byte; that is tested.

| Mod | What it does | Status | In the browser |
|---|---|---|---|
| `lfo4` | A fourth LFO under `[MOD]`, like LFO1–3. Modulates on every voice; kept by SAVE PROJECT and across a power-cycle | confirmed on hardware | yes |
| `arpmodes` | SHUF and RAND as real arpeggiator modes | confirmed on hardware | in progress |
| `fxmod` | An LFO can be aimed at 24 Chorus, Delay and Reverb parameters | confirmed on hardware | yes |
| `moddest` | 13 more per-voice parameters open as LFO destinations | confirmed on hardware | yes |
| `lfowaves` | Seven new LFO waveforms, three of them your own wavetables | confirmed on hardware | yes |
| `midiarp` | The arpeggiator on MIDI tracks | confirmed on hardware | yes |
| `arpplocks` | MODE, SPEED, RANGE and N.LEN lockable per trig | confirmed on hardware; changed since, emulator-checked | no |
| `bootscreen` | Your own mark in the start-up animation | confirmed on hardware | yes |
| `transients` | Replace the FM drum transient bank with your own samples | confirmed on hardware | yes |

**Combining them.** `dnfw mods matrix` tries every pair in both orders and
writes the result into `docs/mods-compatibility.md` and the site. Most pairs
combine freely; a few need an order (`dnfw mods apply` applies them in it), and
`lfo4`, `lfowaves` and `bootscreen` exclude each other because each needs the
start-up hook. No combined image has been flashed as a pair yet.

**A known problem:** a project saved by stock firmware with damaged LFO values
can halt a modded build on load (`EXCEPTION DS0059`). A fix is in progress; see
`docs/mods-compatibility.md` and the open PRs.

**In development: Waverider**, a wavetable machine for the Digitone II modelled
on Tonverk's Wavefinder (`docs/waverider-feasibility.md`). A baked table has been
read back on the instrument (Milestone 0), and Milestones 1–4 run offline in
digikit's SHARC emulator: our own SHARC reader, inside a real DN2 voice, through
the per-track chain, with its tables baked into the DSP image. The first
flashable build is Milestone 5.

## Install and run

Python 3.11+, no dependencies.

```
pip install -e .
dnfw inspect 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip
dnfw mods apply Digitone_II_OS1.11.syx --mod lfo4 -o modded.syx
```

Or without installing: `PYTHONPATH=src python -m dnfw.cli.main ...`

A `.zip` as Elektron ship it is accepted anywhere a `.syx` is.

### Commands

| Command | Does |
|---|---|
| `dnfw inspect <image>` | report transport, container, sections and every integrity field |
| `dnfw extract <image> -o DIR` | write each section out, depacked where it is compressed |
| `dnfw build <image> -s 3=FILE -o OUT` | rebuild with a replaced section, recomputing every checksum |
| `dnfw diff <a> <b>` | compare two images section by section |
| `dnfw mods list` / `apply` / `extract` | the mods above: list them, apply them, extract their factory content |
| `dnfw mods matrix <image>` | try every pair of mods and report which combine |
| `dnfw patch list` / `apply` | declarative single patches with stock-byte guards |
| `dnfw params <image>` | find and dump the instrument's parameter table |
| `dnfw symbols` / `symbolmap <image>` | the C++ names GCC left in the image; a Ghidra seeding script |
| `dnfw disasm <image> ADDR [N]` | disassemble a span (ColdFire V4e, via objdump) |
| `dnfw validate-disasm <image> ADDR [N]` | check another disassembler against objdump |
| `dnfw cave <image>` | find free space and size a hook for a code-cave detour |
| `dnfw fn <image> ADDR` | count direct callers of an address, or find the function containing it |
| `dnfw ldr <image>` | walk the SHARC program (section 7) as an ADI boot stream |
| `dnfw waverider ...` | Waverider's tables: scan and reduce WAVs, bake, render a reference, build a frame |

`build`, `patch apply` and `mods apply` re-load and re-verify their own output
before writing it. Nothing leaves this tool that it cannot check.

## How a change is checked before it reaches an instrument

- **Integrity:** every checksum and the HMAC-SHA256 signature are recomputed and
  re-verified on the rebuilt file.
- **Boot from reset in an emulator:** `scripts/emu_boot_check.py`, on digikit's
  ColdFire emulator, against a stock control. A snapshot of a machine that has
  already booted does not count (`docs/emulator.md`).
- **The engine and save/load:** `scripts/emu_boot_engine.py` runs the audio
  engine's evaluator and a stored sound through LOAD and SAVE.
- **ColdFire encodings:** `scripts/check_coldfire.py` rejects an addressing mode
  the chip refuses and generic emulators run.
- **Per-mod harnesses** under `scripts/emu_*.py`, each with a stock control.
- **DSP code** runs offline in digikit's SHARC runner and is compared with a
  Python reference (`scripts/sharc_waverider_*.py`).
- **On the instrument:** each hardware test has a written pass and fail in the
  project's test plan before anything is flashed. The recovery route (stock
  through the Early Start-up Menu) is proven; send it over a clean MIDI link
  (`docs/flashing.md`).

## What the firmware is

Measured from the images. Evidence in `docs/ele3-format.md` and
`docs/mainos-image.md`.

- An `ELE3` container inside a block-streaming SysEx transport.
- Sections compressed with an aPLib variant. `MAIN OS` loads at `0x40000400`:
  big-endian **ColdFire V4e** code, built with GCC and still carrying its **C++
  RTTI names**. Section 7 is the **SHARC+ DSP** program, as an ADI boot stream.
- The DN2 container is signed with **HMAC-SHA256**, keyed from material in the
  image itself, so a modified image can be signed correctly. The DN1 container
  is **unsigned**: its trailer is 32 zero bytes.
- The +Drive is a 32 GB eMMC with no filesystem: fixed slots for projects,
  presets and kits, and about 21 GiB the stock firmware never touches
  (`docs/drive-storage-research.md`).

## Testing

```
pytest -m "not slow"     # the fast set
pytest                   # everything, a few minutes
```

Gate F needs an m68k objdump; on Windows,
`wsl -u root apt-get install -y binutils-m68k-linux-gnu`. The browser parity
tests need Node. The emulator gates need digikit (`docs/emulator.md`). Tests
that need something absent — the OS images in `00_Resources/`, objdump, Node —
skip and say so.

## Documentation

| File | Subject |
|---|---|
| `docs/PRINCIPLES.md` | how code here is built, and why |
| `docs/mods.md` | every mod: what it changes, how it was verified |
| `docs/mods-compatibility.md` | which mods combine, generated by `dnfw mods matrix` |
| `docs/flashing.md` | the recovery path, and the order hardware steps happen in |
| `docs/emulator.md` | running builds in digikit's ColdFire emulator |
| `docs/instruments.md` | which tool answers which question |
| `docs/lfo4-build-plan.md` | the whole LFO4 story, including the dead ends |
| `docs/waverider-feasibility.md` | Waverider, milestone by milestone |
| `docs/drive-storage-research.md` | the +Drive, and where a sample library could live |
| `docs/ideas-backlog.md` | ideas, costed, with their state |
| `docs/ele3-format.md` | the transport, container, codec and integrity layers |
| `docs/mainos-image.md` | the CPU, the load address, and which disassembler to trust |
| `docs/sharc-voice-path.md` | the DSP voice path, as measured in the runner |
| `docs/references.md` | prior art, what each is good for, and its licence |

## Licence

**[GNU AGPL-3.0-or-later](LICENSE).** Use it, fork it, change it; keep the
notices and pass on the same freedoms. A modified version you distribute — or
run as a service — stays open. Same licence as DNX, for the same reasons.

Parts of it derive from MIT projects, whose notices are carried in
[THIRD-PARTY.md](THIRD-PARTY.md).

## Credit

The container, transport, codec and integrity work stands on
[mischa85/elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool)
(MIT). The patch model comes from
[bryantysinger/octa-bt-pt](https://github.com/bryantysinger/octa-bt-pt) (MIT),
and the ColdFire disassembly findings from
[sambanks/octabam](https://github.com/sambanks/octabam) (MIT). The ColdFire and
SHARC emulators are [m-dwyer/digikit](https://github.com/m-dwyer/digikit)'s
(GPL-2.0-or-later), used as external tools; our own SHARC code is assembled with
[js216/selache](https://github.com/js216/selache) (GPL-3.0). The Digitone data
formats come from the sibling project DNX. What was taken from each, and where
this project deliberately diverges, is in `docs/references.md`.

None of them is affiliated with Elektron, and neither is this. Everything in
`docs/` was measured from OS files Elektron publish; no Elektron code has been
copied into this repository and no firmware is redistributed by it.
