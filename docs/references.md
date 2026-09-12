# Reference material

Elektron publish no format documentation, so everything in `docs/` was derived
from real files or from the projects below. Licences were checked before
anything was ported; all three firmware projects are **MIT**, which is why this
repository ports from them with attribution rather than reimplementing. Their
notices are carried in `THIRD-PARTY.md`; this project is AGPL-3.0-or-later.

Working copies are cloned into the private corpus at
`00_Resources/01_Reference/` and are not part of this repository.

## elektron-firmware-tool — the format reference

<https://github.com/mischa85/elektron-firmware-tool>, by Marcel Bierling. MIT.

A C tool that inspects and modifies Elektron OS `.syx` files. It is the source
for the container and transport layout, the codec, and the integrity
algorithms. What was ported, and into what:

| From | Into |
|---|---|
| `format.h` — field offsets, packet geometry, device ids, section ids | `syx/`, `container/` |
| `decompress.c` — `ap_depack`, 8-in-7 decode, transport decode | `codec/aplib.py`, `syx/` |
| `compress.c` — `ap_pack` cost model, bit encoding, `syx_encode` | `codec/aplibpack.py`, `syx/transport.py` |
| `integrity.c` — content checksum, packet checksum, key derivation | `integrity/` |
| `main.c` — `rebuild_container`, `append_trailer`, `build_preamble` | `container/ele3.py`, `firmware/build.py` |

**Where we diverge, and why**, so the next reader does not assume a faithful
copy:

- The **parse strategy** in `aplibpack.py` is greedy with a lazy lookahead, not
  the C's cost-optimal dynamic program, which Python cannot run at this scale.
  The bit encoding and cost model are the C's. Measured cost: none — see
  `docs/ele3-format.md`.
- The **section header** belongs to `container/section.py` here, not to the
  codec. It is a property of an ELE3 section, not of the compression.
- **Legacy transports** (Machinedrum/Monomachine 2+7+7, Octatrack ELEK) are not
  implemented. No Digitone uses them, and shipping an untested implementation of
  a format we hold no file for would be a liability.
- Two places the C relies on 32-bit unsigned wraparound needed explicit masks;
  both are regression tests. `docs/PRINCIPLES.md` §16.

**Keep it buildable as a cross-check.** Its `-i` inspect over our rebuilds is a
second opinion from code that no longer shares a lineage with ours. Not yet
done — there is no C compiler on this machine.

## octa-bt-pt — the patch model

<https://github.com/bryantysinger/octa-bt-pt>, by Bryan Tysinger. MIT.

Patches Octatrack firmware — **the same CPU family** — through a Streamlit UI
that edits parameter defaults. "This tool patches values, not code."

What was taken is the shape of `tools/patchlib.py`: declarative patch records
carrying the bytes they expect, a hash guard that refuses to apply to the wrong
image, ColdFire virtual-address-to-file-offset resolution, and `discover()`
loading `patches/*.py` in sorted order with duplicate ids refused.

Two deliberate differences in `patch/spec.py`: a patch names the **device,
build and version** it targets, so a refusal says which one disagreed rather
than only that a hash did not match; and every patch carries `expect`, checked
at the target before anything is written, because a whole-image hash cannot
catch a patch pointed at the wrong offset inside the right image.

## octabam — ColdFire prior art, and the disassembler warning

<https://github.com/sambanks/octabam>, by Sam Banks. MIT.

Writes custom DSP effects into Octatrack MKII firmware, composing modules into
"remixes" that replace stock effects. Genuine reverse engineering, not
decompiler output.

Two things it establishes that saved us directly:

1. **The Octatrack's ColdFire MAIN OS loads at `0x40000400`** — the same
   address we measure on both Digitones, reached independently. One Elektron
   platform convention rather than two coincidences.
2. **radare2's m68k backend cannot read this CPU and fails silently**, measured
   30 Aug 2026. The numbers and the reasoning are in `docs/mainos-image.md`;
   the conclusion is that `m68k-elf-objdump -m m68k:cfv4e` is the reference and
   everything else gets validated against it.

Its **code-cave** model — hook address, asserted stock bytes, displaced
instructions replayed in the cave — is the mechanism to copy when Phase 2 needs
to add code rather than change it. See `modules/cfprobe/manifest.py` and
`modules/_template/manifest.py`.

## midisc — the ColdFire assembler we port

<https://github.com/bkkbrls-del/midisc>, by Sam Banks. MIT (its notice also
credits **octamax**, below, from which parts of its analysis tooling derive).

Adds MIDI scenes to the Octatrack 1.40C OS by splicing ColdFire code into
`SAFE_CAVE` regions of the stock image. The Octatrack is a different, older
device — its engine, its DSP and its per-track layout tell us **nothing** about
the DN2, and none of that is assumed here. What transfers is purely
**CPU-level**, because both boxes run the same ColdFire V4e core:

| From | Into | Why it transfers |
|---|---|---|
| `tools/ot3_asm.py` — the `Asm` class, every encoding checked against a stock instruction, `.link()` resolving `.w` branch displacements | `patch/coldfire.py` | ColdFire ISA, not device-specific |
| `tools/midisc/util.py` — `jmp_abs`, `jsr_abs`, `off()`, `fix_jsr`, the "cave not empty" guard | `patch/cave.py` | same |

Its `docs/TECH.md` records the Octatrack's own `SAFE_CAVE` at
`0x400D24D0…0x400D2CDC`; those addresses are **the Octatrack's, not ours** — the
DN2's safe space is mapped independently in `docs/memory-map.md`.

## octamax — midisc's upstream

<https://github.com/mxldyn/octamax>, by Maxolydian. MIT. The analysis tooling
midisc builds on. Its account of the Octatrack architecture (a double-buffered
parameter frame the ColdFire fills and a **DSP56xxx** reads over MMIO) is a
2011-era design and is treated here strictly as a **hypothesis to disprove**,
not a map: the DN2 is a 2024 SHARC-based box, and every engine claim about it
must be read from the DN2 image itself.

## ems-octakit — inspiration only, not ported

<https://github.com/emuyia/ems-octakit>, by emuyia. **No licence file** — so
its code is *not* ported; it is read only for architecture.

It patches the same Octatrack 1.40C but takes a more industrial route than a
hand-rolled encoder: hand-written `.S` ColdFire assembly (`runtime/*.S`)
assembled with the real GNU toolchain against a `link.ld` linker script that
drops each stub into a cave, driven by a `firmware.json` hook manifest and a
Rust patcher. The device-agnostic lesson — **prefer a real assembler over a
hand-encoder for anything non-trivial** — is why `patch/assemble.py` shells to
`m68k-linux-gnu-as` (present in WSL, the same suite as our Gate-F objdump), with
the ported `patch/coldfire.py` encoder kept only as a no-toolchain fallback and
for one-line hook branches. Its Octatrack-specific `.S` internals
(`lfo_*.S`, `audio_*.S`) are not a model for the DN2's engine.

## DNX — the data-format authority

`C:\ZZ_Code\ZZ_Personal\DNX`, same author. TypeScript; stays its own
repository, and no code is shared.

It decoded the Digitone project, pattern, kit and sound formats from hardware
captures and matched-pair corpora. Two of its findings are the reason the LFO4
goal is credible rather than wishful, and both are quoted in
`docs/ROADMAP.md` — the unused fourth slot in the sound object's LFO grid, and
the unused `4*slot + 0` band in the parameter-lock table.

It is also the **verification instrument** for Phase 2: it can read the sound
objects out of a project saved by patched firmware, which is a better check on
where LFO4's bytes land than anything visible on screen.

Its `docs/PRINCIPLES.md` governs this repository too.

**Treat the whole of DNX as reference material for this project, not only the
two format documents.** It is the same author's prior investigation of the same
hardware, and its measurements repeatedly settle questions that are expensive to
answer from the image alone — `docs/device-model.md` exists because DNX's
`+Drive` listings named what a 128-entry array in the firmware actually was.
Worth knowing is there:

| In DNX | Why it matters here |
|---|---|
| `docs/device-storage.md` | the `+Drive` store: projects, soundbanks, kits, and the read/write protocol |
| `docs/dn2-format.md`, `dn2-pattern-format.md`, `dn2-song-format.md` | the decoded project, pattern and song formats, with offsets |
| `docs/sysex-format.md`, `capture-protocol.md`, `device-probing.md` | the SysEx object types and how the device answers — the same object classes the firmware's own strings name |
| `docs/sound-mapping.md`, `SOUND-AND-KIT-PLAN.md` | which byte is which parameter |
| `docs/dn1-project-format.md`, `dn1-tail-format.md` | the DN1 equivalents, for when this project reaches the DN1 |
| `docs/references.md`, `PRINCIPLES.md`, `KNOWN-ISSUES.md` | its own sources, working rules and recorded traps |

The Obsidian vault at
`C:\ZZ_Code\00_Notes\AS\ZZ_Personal Projects\02_DNX\` carries the narrative
record — *Digitone architecture - Lessons Learnt* especially, which holds the
storage-layout diagrams and the reasoning behind them.

The rule that makes this pay: **check what DNX already measured before inferring
anything about the device from the firmware image.** See
`docs/device-model.md`.

## Elektron manuals

The authority for the user-facing side — parameter names, ranges, page layouts.
Check the OS version before trusting a parameter list; controls move and
disappear between releases, and where the manual and the device disagree, the
device wins.

Local copies live in the private corpus, not here.
