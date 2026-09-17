# dn_firmware

Tools for inspecting, modifying and rebuilding **Elektron Digitone** firmware —
the Digitone II (DN2) and the original Digitone / Digitone Keys (DN1).

The end goal is to fill the vacant fourth page under the Digitone II's `[MOD]`
key with a fourth LFO behaving exactly like LFO1–3. Getting there needs a build
loop first, and that is what exists today.

**This repository holds code and documentation only.** It contains no Elektron
firmware, original or modified, and never will. Bring your own OS file — the
one Elektron publish for your instrument.

## Status

| | |
|---|---|
| Read an OS `.syx`, report every layer and integrity field | done |
| Decode and re-encode an image **byte-identically** | done — Gate A, both images |
| aPLib depack and pack | done — Gate B, and smaller than stock on every section |
| Rebuild with replaced sections, re-signed and verified | done — Gate C |
| Declarative patches with guards | done |
| A disassembler validated against objdump | done — Gate F; **Ghidra passes**, Capstone fails |
| Recovery path proven on hardware | done — stock reflash through the Early Start-up Menu |
| A patch confirmed on the instrument | **done** — Gates D and E boot through the normal update path |
| Our images through the recovery path | **open** — they stall at ~80%; fix built, awaiting a test (`docs/flashing.md`) |
| A fourth LFO | Phase 2 — the parameter table is mapped; what reads it is not |

## Install and run

Python 3.11+, no dependencies.

```
pip install -e .
dnfw inspect 00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip
```

Or without installing: `PYTHONPATH=src python -m dnfw.cli.main ...`

A `.zip` as Elektron ship it is accepted anywhere a `.syx` is.

### Commands

| Command | Does |
|---|---|
| `dnfw inspect <image>` | report transport, container, sections and every integrity field |
| `dnfw extract <image> -o DIR` | write each section out, depacked where it is compressed |
| `dnfw build <image> -s 3=FILE -o OUT` | rebuild with a replaced section, recomputing every checksum |
| `dnfw patch list [--image IMG]` | show declared patches, and whether they apply |
| `dnfw patch apply <image> -o OUT` | apply patches and rebuild |
| `dnfw symbols <image> [--ghidra FILE]` | the C++ names GCC left in the image |
| `dnfw symbolmap <image> [--ghidra FILE]` | curated names + RTTI for a section, and a Ghidra seeding script |
| `dnfw disasm <image> ADDR [N]` | disassemble a span (ColdFire V4e, via objdump) |
| `dnfw validate-disasm <image> ADDR [N]` | Gate F: check another disassembler against objdump |

`build` and `patch apply` re-load and re-verify their own output before writing
it. Nothing leaves this tool that it cannot check.

## What the firmware is

Measured from the two images, 2026-09-07. Evidence in `docs/ele3-format.md`.

- An `ELE3` container inside a block-streaming SysEx transport.
- Sections compressed with an aPLib variant. `MAIN OS` on both devices loads at
  `0x40000400`; on the DN2 it is **3,085,696 bytes** of big-endian **ColdFire**
  code, built with GCC and still carrying its **C++ RTTI names**.
- The DN2 container is signed with **HMAC-SHA256**, keyed from material in the
  image itself — so a modified image can be signed correctly. The DN1 container
  is **unsigned**: its trailer is 32 zero bytes.

## Testing

```
pytest -m "not slow"     # 53 tests, about 16 seconds
pytest                   # adds the 3 MB MAIN OS rebuild, about 35 seconds
```

Gate F needs an m68k objdump; on Windows,
`wsl -u root apt-get install -y binutils-m68k-linux-gnu`. Without it those
tests skip and say so. Capstone (`pip install capstone`) is optional and only
used as the engine under test.

Corpus-dependent tests skip cleanly when `00_Resources/` is absent, and say so.

## Documentation

| File | Subject |
|---|---|
| `docs/PRINCIPLES.md` | how code here is built, and why |
| `docs/ele3-format.md` | the transport, container, codec and integrity layers |
| `docs/mainos-image.md` | the CPU, the load address, and which disassembler to trust |
| `docs/flashing.md` | the recovery path, and the order hardware steps happen in |
| `docs/ROADMAP.md` | the gates, and the Phase 2 LFO4 investigation |
| `docs/lfo-parameters.md` | the LFO parameter tables, and what a fourth LFO needs |
| `docs/service-commands.md` | the factory service command strings, including the serial number |
| `docs/references.md` | prior art, what each is good for, and its licence |

## Licence

**[GNU AGPL-3.0-or-later](LICENSE).** Use it, fork it, change it; keep the
notices and pass on the same freedoms. A modified version you distribute — or
run as a service — stays open. Same licence as DNX, for the same reasons.

Parts of it derive from three MIT projects, whose notices are carried in
[THIRD-PARTY.md](THIRD-PARTY.md).

## Credit

The container, transport, codec and integrity work stands on
[mischa85/elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool)
(MIT). The patch model comes from
[bryantysinger/octa-bt-pt](https://github.com/bryantysinger/octa-bt-pt) (MIT),
and the ColdFire disassembly findings from
[sambanks/octabam](https://github.com/sambanks/octabam) (MIT). The Digitone
data formats come from the sibling project DNX. What was taken from each, and
where this project deliberately diverges, is in `docs/references.md`.

None of them is affiliated with Elektron, and neither is this. Everything in
`docs/` was measured from OS files Elektron publish; no Elektron code has been
copied into this repository and no firmware is redistributed by it.
