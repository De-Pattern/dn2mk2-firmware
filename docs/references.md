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

Its LFO content is a page-mode constant and nothing more — see
`docs/octatrack-lfo-prior-art.md` for the survey of what the four Octatrack
projects have and have not done with LFOs.

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

<https://github.com/emuyia/ems-octakit>, by emuyia. ~~**No licence file** — so
its code is *not* ported; it is read only for architecture.~~ **Corrected
2026-09-13, heading left stale until now:** the repo added an **MIT LICENSE**
that day (see the Licence audit below) — it *may* be ported with attribution.
Nothing has been ported yet regardless, so "inspiration only" still describes
current practice, just not current permission.

**Update, 2026-09-27.** Its development builds are also offered from the
author's own site, <https://www.junes.website/goodies/octakit> — the same
project, not a second one; the page states only "do not redistribute the
generated `.syx`, share this page instead," which is a restriction on the
generated firmware file, not a separate code licence. And `sambanks/octabam`
now carries it as the **OCTAKIT** module (`modules/octakit/`): 256 Kits per
Project replacing the stock 64 Parts, built from a pinned submodule of this
repo and reproduced byte for byte against emuyia's own build before being
proven on hardware (`ok-ms`, 14 Sep 2026) — a second independent
byte-identity check of the kind this project has had little of.

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

## Licence audit, 2026-09-13

Re-checked all seven reference repositories after the owner listed them. **Two
findings change what may be copied**, and both moved since this project started:

| repo | licence | may we port? |
|---|---|---|
| `mischa85/elektron-firmware-tool` | MIT | yes — already the ancestor of `dnfw`'s container and aPLib code |
| `sambanks/octabam` | MIT | yes |
| `bkkbrls-del/midisc` | MIT | yes — `patch/coldfire.py` is ported from it |
| `bryantysinger/octa-bt-pt` | MIT | yes — the patch-spec model |
| `nordseele/octalab-notes` | MIT | yes, though it is **docs only**: no firmware, no build, no flashing procedure |
| **`emuyia/ems-octakit`** | **MIT — added 2026-09-12** | **yes, newly.** This repo was unlicensed for the whole of this project's life; the condition recorded against it has now been met, so its `.S` stubs, `link.ld` and `firmware.json` manifest may be ported with attribution |
| **`mxldyn/octamax`** | **NONE** | **no.** No LICENSE file and no statement in its README. Architecture-only inspiration, never copied |
| **`m-dwyer/digikit`** | **GPL-2.0-or-later** | **yes, with care** — see below. Taken forward as GPLv3 it combines with this repo's AGPL-3.0-or-later; **using it as a tool entangles nothing at all**, which is the route to prefer |
| **`irpina/digiemu`** (added 2026-09-24) | **GPL-2.0-or-later** | **yes, with care.** Taken forward as GPLv3 it combines with this repo's AGPL-3.0-or-later, and it is GPL-2.0-compatible for digikit. Its six files are *Unicorn* patches, so **using them is using a tool and entangles nothing at all** -- the route to prefer, exactly as with digikit |
| `js216/selache` (added 2026-09-19) | GPL-3.0; `libsel` MIT | may link (GPL-3.0 combines with our AGPL-3.0) but **not vendored**: `tools/selmap` is our own harness over a local checkout. Never into digikit, which is GPL-2.0 |
| **`irpina/elekloader`** (added 2026-09-27) | **GPL-2.0-only** — `NOTICE` states "version 2" explicitly, no "or later" anywhere, confirmed 2026-09-27 | **no.** Not combinable with AGPL-3.0-or-later. Design reference and tool only |
| **`irpina/digihealth`** (added 2026-09-27) | **GPL-2.0-only** — same as elekloader; re-checked 2026-09-27 against `LICENSE` and three source headers, all silent, none contradict | **no.** Design reference and tool only |
| **`irpina/digislicer`** (new 2026-09-27) | **GPL-2.0-only** — same bare GPL-2.0 text, no "or later" | **no.** Design reference and tool only |
| **`timhastie/octatrick`** (new 2026-09-27) | **MIT**, plus a trailing paragraph scoping the grant to the repo's own code (not Elektron firmware, not submodule content) — this appended text is why GitHub's API reports "NOASSERTION"/"Other" rather than plain MIT | **yes, for octatrick's own code**, with attribution. Ported submodule content (`octatrick-modules`) and any Elektron material stay out of the grant |
| **`timhastie/octa-panel`** (licence checked for the first time 2026-09-27) | **MIT**, identical carve-out text to octatrick's (same appended paragraph, same reason for "NOASSERTION") | **yes**, with attribution, for the same reason as octatrick — though see the correction below: this repo is now a historical dev log, not the live location |
| **`Zac-Kyoti/octatrack-kyoti-fw`** (new 2026-09-27) | **MIT with explicit exclusions**: `tools/attic/` (inherited from `mxldyn/octamax`, tagged `SPDX-License-Identifier: NONE`), patches to third-party tools and anything fetched at build time (keeps its own upstream licence — `dsp56300/dsp56300` is GPLv3, `octabam` is MIT), and all Elektron material | **yes, for the covered code**, with attribution. `tools/attic/` and vendored/patched third-party code are **not** covered — same "no" as octamax for the attic specifically |

**The restriction moved rather than lifted.** `ems-octakit` was the one to avoid
and is now free to use; `octamax` is now the one to avoid. Earlier notes in this
repository describing "midisc/octamax" as MIT are **wrong about octamax**.

**Re-check `ls <repo>/LICENSE` before porting from any of them.** This changed
once during the project and can change again — and an expected licence is not a
granted one, while a granted one can also arrive late, as it did here.

### `nordseele/octalab-notes`, new to the set

Docs only, MIT, and explicit that it "publishes no firmware, no build and no
flashing procedure". It records what its author learned about OT 1.40C while
adding creative helpers — a topographic trig generator in the style of Mutable
Instruments' Grids. Useful as reverse-engineering knowledge and as a second
account of the Octatrack's internals beside octabam's; nothing to port.

---

## `m-dwyer/digikit` — an emulator for our exact CPU, and the closest prior art yet

<https://github.com/m-dwyer/digikit>, GPL-2.0-or-later. Added 2026-09-13 by the
owner. **Still in development**, and its handover notes are dated the same week
as ours — this is a live parallel effort, not an archive.

It is the project the owner asked about on 2026-09-11 — *"would an emulator
solve our growing stack questions?"* — built by someone else and already
further along than anything here.

### What it is

A Python 3.12 emulator for the **Digitakt II's control processor**, on Unicorn,
that boots the main OS, spawns the RTOS tasks, reaches the message loop and
**renders the UI to the 128×64 panel** — pattern and project names, tempo,
encoder parameters — live or exported as PNG. ~10M instructions/second against a
modelled 4.68 MHz, so 20–25 fps with tempo holding.

Its hardware model is our hardware, independently arrived at:

| | digikit | this project (`docs/hardware.md`) |
|---|---|---|
| control CPU | Freescale **MCF54415**, big-endian | **MCF5441SCMJ250**, from the owner's board photos |
| audio DSP | **ADSP-21569 SHARC+**, separate firmware, out of scope | ADSP-21569 SHARC+ (U9) |
| MAIN OS load base | `0x40000400` | `0x40000400` |

Two independent routes to the same answer, which is the kind of corroboration
this project has had little of.

### It supports the Digitone II

```sh
uv run python -m emu.run Digitone_II_OS1.10E.syx
```

Section extraction is identical to the Digitakt, and the decompressor has been
verified byte-identical across DT2 1.15C and DN2 1.10E.

> **Correction, same day.** This section first said, from `README.md` and
> `docs/DIGITONE.md`, that on the DN2 *"the main application task never wakes"*
> — blocked on mutex `0x44460e40` from a lost timer-wheel wakeup — and therefore
> that **the UI renders for the Digitakt and not the Digitone**.
>
> **That is stale and wrong as a statement of current state.** The author's own
> account, relayed by the owner 2026-09-13: *"basic emulator for latest Digitakt
> 2 and Digitone 2 firmware… it works"*, and `docs/HANDOVER-2026-09-13.md`
> records **"You can press buttons and turn encoders on both builds, and the
> firmware responds."** Front-panel input, UART8 at 156250 baud, event decoding
> through a `queue_send` hook, and control-name resolution from the firmware's
> own tables are all working.
>
> The lesson is about *this* repository, not that one: **a project under active
> development has a stale README, and its handover notes are the live
> document.** Reading the tidiest file and asserting current state from it is
> the same error this project has made against its own firmware all week.

Current, from the author and the latest handover:

| | state |
|---|---|
| DN2 boot + UI | **works** |
| buttons and encoders | work on both builds — but the author flags **encoder turn/deltas as buggy and needing fixing** |
| page buttons | momentary — the page reverts shortly after release |
| DT2 `boot280M.snap` | renders a blank screen post-intro, so screen-based identification fails on that build |
| storage (eSDHC/eMMC) | identification only; `CMD18` reads return zeros |
| audio (SHARC+) | out of scope, separate firmware |

**Which DN2 version is unresolved.** The README documents 1.10E; the author says
"latest". Ours is 1.11. Worth asking rather than assuming — and it decides
whether our anchors transfer directly or need re-deriving.

### DN2 1.10E addresses it names

Ours are anchored to 1.11 and would need re-deriving, but these name *roles*,
which is exactly what this project keeps getting wrong by pattern-matching:

| role | DN2 1.10E |
|---|---|
| `set_pixel` / `get_pixel` | `0x40105964` / `0x40105a30` |
| main application task entry (prio 6) | `0x4002e688` |
| `flash_read` | `0x40126b46` |
| `current_tcb` | `0x46487fdc` |
| `intro_pit3_isr` | `0x400d4fb8` |
| soft-float block | `0x401685fc–0x40169f5c` |

`set_pixel` is the one to note. **Everything drawn on that screen passes through
it**, so the display path we have failed twice to identify is reachable by
hooking one function and walking back — against a named role rather than a
guessed one.

And with encoder input working in the emulator, the question that has cost this
project four flashes — *which functions run when you turn an encoder?* — becomes
a trace, not a guess. The author's caveat that **encoder deltas are buggy** is
the thing to verify before trusting such a trace: a broken delta could deliver
the event without the value change, which would light exactly the wrong half of
the path and look like a result.

### The landmine it saves us from

**Stock Unicorn cannot run this firmware.** digikit ships
`tools/install-patched-unicorn.sh` for a "destructive SR read" defect that
corrupts the condition flags. Anyone standing up a ColdFire emulator from
scratch would hit silently wrong flag behaviour and debug the firmware instead
of the emulator — the same failure mode octabam recorded for radare2's m68k
backend, and which `docs/mainos-image.md` already treats as a rule: **validate
the tool before trusting its output.**

### What it already caught

Setting it up made an independent extraction available, and **four of our five
sections came out byte-identical while section 4 differed by exactly eight
bytes** — a header this project was writing out as payload. `docs/emulator.md`
has the finding in full. Two things about it are worth carrying here:

* digikit does not reimplement aPLib. It **runs the updater's own depacker under
  Unicorn**, so the agreement is between our Python and *the device's own code
  executed* — a stronger cross-check than the one `elektron-firmware-tool` was
  being kept around for and never gave, for want of a C compiler.
* The bug was a plausible untested model sitting in the repository looking
  settled — *"a raw section is stored raw, so write it out"* — which is the
  week's pattern in its mildest form.

### What it would have caught here

The crash on 2026-09-13 (`docs/flashing.md`) was a cave placed in a live
16-record array that the firmware overwrites at runtime. **An emulator watching
writes to that range would have shown it in seconds, without a flash and without
an exception on the owner's instrument.** Every cave placement question this
project has guessed at is a memory-watch away in a tool that already exists.

### Licence, and the route to prefer

GPL-2.0-or-later. Taken forward as GPLv3 it is compatible with this repository's
AGPL-3.0-or-later, so porting with attribution is *possible* — but
**running digikit as a separate tool entangles nothing**, and that is the route
to prefer until there is a specific reason to copy code. Flag any actual port to
the owner first: it is their public repository and their licensing decision.

## Community Octatrack reverse-engineering, shared 2026-09-13

Two documents from the Octatrack RE community, passed on by the owner as
reference. **Not used by anything here** — recorded because the overlap is real
and because re-deriving what someone else has already published is waste.

| Document | What it holds |
|---|---|
| `TABLE_ATLAS.md` | A shape-level catalogue of every X/Y data table the Octatrack's ColdFire uploads to its DSP56300s at boot, from OS 1.40C. Addresses, word counts and decoded curve shapes; attribution deliberately out of scope. |
| `octatrack-delay-architecture.md` | Where the Echo Freeze delay actually lives, and why earlier searches missed it. |

Two things in them bear on this project, and neither is a coincidence:

**The control CPU ships the DSP its tables at boot.** That is the same
architecture we have on the DN2 — ColdFire plus a separate audio DSP, with the
DSP's program and data arriving from the update image. Their `X:0x06c00`
container holds a 1,024-word sin/cos wavetable next to a single-cycle ramp/saw,
which the author reads as an **LFO/oscillator waveform bank**. If the DN2's LFO
waveforms live SHARC-side in the same way, that is directly relevant to §7 and
to what a fourth LFO does *not* need: a fourth generator reuses those tables
rather than adding any.

**Their method is ours, one device over.** Shape-level cataloguing with
attribution held back until it is earned is exactly the discipline
`docs/PRINCIPLES.md` asks for, and their atlas openly marks a segmentation its
own disassembly later contradicted rather than quietly fixing it.

The Octatrack's DSP is a **DSP56300**, not a SHARC+, so no address, encoding or
table layout transfers. What transfers is the architecture and the method.

---

## SHARC reverse-engineering leads, assessed (2026-09-14)

A set of community/AI-sourced pointers was passed in explicitly as *leads, not
confirmed fact*. Assessing them against what this repository has already
measured is cheap, and two of them would have cost real time if taken at face
value. Recorded in full, including the ones that are wrong, because a lead that
was checked and rejected is worth as much as one that was adopted
(`docs/PRINCIPLES.md`).

| Lead | Verdict |
|---|---|
| No commercial C decompiler exists for SHARC+ | **Agrees** with `docs/sharc-disassembly.md`. Hex-Rays has no SHARC+ decompiler. |
| Ghidra via a custom SLEIGH module is the route | **Agrees, and is what we run.** |
| "reverse engineers frequently construct custom SHARC processor definitions" | **Overstated.** A GitHub code search for `extension:slaspec` mentioning SHARC returns **exactly one** repository — digikit's. It is the state of the art, not one of many. |
| IDA Pro plugins for ADSP-214xx, "requires updating for 2156x" | **Unchecked, and likely the same trap as `g21k`/`sharc_asm`:** 214xx is classic SHARC with a fixed 48-bit encoding. Ours is SHARC+ **VISA**, 16/32/48-bit. A classic decoder mis-lengths and desyncs. |
| **ADI's open-source `analogdevicesinc/adsp-ldr`** | **Genuinely useful — adopted as a cross-check.** See below. |
| Firmware is an `.ldr` on SPI flash; carve it out with a hex editor | **Not our situation.** The boot stream is section 7 of a signed `ELE3` container delivered over MIDI SysEx (`docs/ele3-format.md`). No flash carving is involved and none should be. |
| "L1 blocks start with `0x2c`, L2 blocks with `0x20`" | **Contradicted by measurement.** Our L1 is `0x20000000` and L2 is `0x28000000`, from 9 regions the boot stream itself describes (`docs/sharc-code-map.md`). |
| "configure your disassembler for 32-bit/40-bit SHARC instruction alignment" | **Wrong, and expensively so.** 40 bits is SHARC's extended-precision *data* word, not an instruction length. SHARC+ VISA instructions are 16/32/48-bit. A disassembler set to a 40-bit stride would desync on the first instruction and produce confident nonsense — the exact failure `docs/mainos-image.md` records for radare2 on ColdFire. |
| Re-pack with CrossCore `elfloader.exe`, reflash via CH341A / `flashrom` / `ccsfp.exe` | **Out of scope and against the standing rules.** We have a proven, reversible update path through the normal OS-upgrade route with a verified recovery menu (`docs/flashing.md`). Swapping it for an external SPI programmer trades a working way back for a brick risk, and touches hardware nothing has authorised. |
| Pipeline hazards/stalls obscure static control flow | **True but not our blocker.** Pipeline behaviour affects *timing*, not instruction boundaries. What blocks us is one length ambiguity (`docs/sharc-reading.md` §5). |

### `adsp-ldr` is a second opinion on our boot-stream reader

`https://github.com/analogdevicesinc/adsp-ldr` is Analog Devices' own
open-source loader-stream tool, covering the ADSP-SCxxx family including its
SHARC cores.

Its value here is not that we need it to parse anything — `dnfw ldr` already
does — but that it is an **independent implementation of the same header
format, written by the vendor**. That is precisely the role
`elektron-firmware-tool` plays for the container: a second opinion from code
sharing no lineage with ours.

And it corroborates immediately. `src/dnfw/image/bootstream.py` parses a
**16-byte header** as `<IIII` — block code with signature byte `0xAD`, target
address, byte count, argument — with `FILL`, `IGNORE` and `FINAL` flags. That is
ADI's documented block layout, arrived at here from the bytes and the
contiguity test rather than from the manual. Two derivations, one from a vendor
specification and one from counting where block targets land, agreeing on the
structure.

**What it does not do** is help us read instructions. It unpacks a boot stream;
the blocker is decoding what the blocks contain. It also does not supply a
re-packer we can use, because our output is an `ELE3` section with a content
checksum and an HMAC trailer, not a standalone `.ldr`.


## elektroid — the Elektron transfer protocol, already implemented

<https://github.com/dagargo/elektroid>, by David García Goñi. **GPLv3.**

A sample and MIDI device manager for Elektron gear, packaged in Debian and
Ubuntu and on Flathub, whose supported-device list includes **Digitone I and II**
by name.

It matters here because `docs/midi-rpc.md` catalogued a large RPC surface on the
running device — `FsRaw*`, `FsSample*`, `Data*`, `Screenshot` — and planned to
derive its wire format by reading `MidiRpcDispatcher::handleMessageAndCreateResponse`.
That is avoidable. elektroid speaks the protocol today, with a CLI shaped
`connector:filesystem:command`, and `elektroid-cli info` reports which
filesystems a given device actually exposes.

For `docs/pcm-hunt.md` that single command decides between the two live
hypotheses about where the FM drum transients live, read-only, without us
implementing a byte of transport.

**GPLv3 against this repository's AGPL-3.0-or-later is compatible for porting**,
should any of it ever be worth porting. Running it raises no licence question.

## transientsplit — separating a transient from a pitched sample

<https://github.com/mikkovihonen/transientsplit>, by Mikko Vihonen. **MIT**
(stated in the README; there is no `LICENSE` file, so GitHub's API reports the
repository as unlicensed — the owner's call was to treat the README's statement
as the grant).

A browser tool that splits a mono sample into **transient, tonal and residual**
components, using the Sound Design Toolkit's `SDTDemix` compiled to WebAssembly
plus a TypeScript HPSS implementation in a Web Worker. Everything runs locally;
no audio is uploaded.

It matters to `docs/mods.md`'s transient mod because the mod solves a different
problem from the one users actually have. A slot is 100 ms of percussive attack;
a user's sample is whatever it is. Two separable jobs:

| job | who does it |
|---|---|
| **fit** — mono, 48 kHz, 100 ms, starting at the attack | `dnfw mods apply --prepare` |
| **separate** — pull the percussive layer out of a pitched sample | transientsplit |

**Linked, not bundled**, and deliberately. The separation half is real DSP:
SDT is a *separate* project with its own licence and is not vendored into
transientsplit either — its README says clone it yourself. Porting the HPSS
would mean an FFT and therefore numpy, against a package that currently declares
**zero dependencies**. A worse copy of a working tool is not worth that.

The MIT grant means porting stays available with attribution if the case ever
becomes strong; it is recorded here so that decision starts from the licence
rather than rediscovering it.

---

## `js216/selache` — an open-source SHARC+ toolchain

<https://github.com/js216/selache>, by Jakob Kastelic. GPL-3.0 (its C library
MIT). Added 2026-09-19 by the owner. It includes an assembler, a C99 compiler,
an LDF linker, an ELF → LDR boot-stream writer, and `selinstr`, a VISA
encoder/decoder.

Scored against our DSP image in `docs/sharc-selache.md`. Its instruction lengths
land 99.0% of the spans between known instruction starts, and a late-start
control lands 94.9%. It produced two decode-table fixes, ~~now upstream as
`m-dwyer/digikit#31`~~. **Corrected 2026-09-26:** #31 was closed unmerged on
2026-09-20, after our own measurement. The fixes are not upstream. Its disassembly reassembles byte-identically for only
83.9% of encodings, so patches are written as source. Built in WSL; not vendored.

---

## `Bezronczek/syntakt-firmware-workbench` — the first project to cite *us*

<https://github.com/Bezronczek/syntakt-firmware-workbench>, by Bezronczek.
**MIT** — the LICENSE's scope is stated narrowly in the README: *"The license
covers the code and text in this repository only."* Added 2026-09-22 by the
owner.

A browser-only workbench that inserts **custom single-cycle waveforms into the
Syntakt's `SY CHORD` machine**. Plain HTML/CSS/JavaScript with no external
dependencies, a Node test suite under `web/test/`, and a small Windows MIDI
loopback utility in `tools/`. It targets **Syntakt OS 1.41 and nothing else**,
and refuses any other version rather than patch blind. The author reports
hardware verification: waveform output within 1% and the screen rendering
checked on the device.

**It names this project as its model**, which is the first time our own
published work has come back as somebody else's reference:

> "[dn2_firmware_explore](https://angellinares.github.io/dn2_firmware_explore/)
> — the model for a browser-only tool that works on the owner's own file."

It credits `elektron-firmware-tool` beside us, which is the same format
groundwork this repository ports from, so the three projects share a lineage.

### Why it is worth tracking, beyond the citation

| what it is evidence of | why that matters here |
|---|---|
| a **third** Elektron platform (Syntakt) opened by an outsider, on a machine-by-machine basis | the `SY CHORD` waveform table is the Syntakt's analogue of our LFO wavetable work; a second implementation of the same idea is a free cross-check |
| the **browser-only, own-file** shape working for someone else | the page's stance — the owner supplies their own firmware, nothing is redistributed — is not just our preference, it travels |
| a **version-locked refusal** rather than a best-effort patch | the same rule as our `STOCK_SHA256` guard, arrived at independently |

**Nothing to port yet and no claim staked.** The MIT grant means porting stays
open if a case appears; recorded here so that decision starts from the licence.
Its firmware findings are the author's, on a device we do not have, so they are
cited in our own words if they are ever used — the same rule as the lalzart
notes.

## `irpina/digiemu` — a booting Digitakt, and four Unicorn patches we do not have

**Added 2026-09-24**, on the owner's instruction. GPL-2.0-or-later, Python 3.12
over a **patched Unicorn**, 2 stars and 7 commits — small and new, and that is
not the measure of it.

### What it is

An unofficial **Digitakt mk1** emulator that runs the real firmware (tested on
OS 1.53) and reaches a **live clickable front panel with 48 kHz audio**: keys,
encoders, key LEDs, the sequencer, patterns, the `+Drive` with projects and
samples, sample loading, and session persistence between launches.

Different device, **same CPU family** — ColdFire — which is the whole reason it
transfers. `firmware/`, `patches/`, `docs/mk1/`, `tools/`.

### Why it matters here, and it is not the Digitakt

**Two of its six Unicorn patches are already in `digikit-up/patches/` under
identical filenames** (`m68k-emac-mac-load`, `m68k-hook-ccr-sync`), and two more
are *named after digikit*. So there is shared lineage with the emulator this
project already runs on, and **four patches we do not have**:

| patch | what it does | why we would want it |
|---|---|---|
| `m68k-emac-modes` | EMAC fractional/integer and signed/unsigned modes: product rounding, store shifting, S/U bit reading, accumulator repacking across mode changes | correctness in exactly the arithmetic an audio engine lives in |
| `m68k-fast-mem` | inline memory paths for pages with no hooks, dirty-page tracking, selective slow-path routing | **speed** |
| `m68k-digikit-accel` | **CFV4E ISA: `FF1`, `BITREV`, `BYTEREV`**, budget-based TB limiting, native eDMA channels | see below |
| `m68k-digikit-speed` | fused MAC/MSAC, native `RTE`, optional memory-exit checks, deferred PC sync | **speed** |

**Speed is not a luxury here.** A shipping-gate run is ~19 minutes at ~4.5
min/100M instructions, and backlog item 21 (profiling our builds against
factory) is blocked partly on harness cost. Two of these four exist only to
address that.

**`FF1` is the pointed one, and it was checked rather than assumed.** `FF1.L` is
the instruction in the caller loop at `0x400271a2` that objdump prints as
`.short 0x04c1` — the one that turns a voice mask into a bit index, read on
2026-09-24. Unicorn 2.1.4 does not decode it. **digikit already emulates it in
software** (`emu/boot.py`'s `ff1()`, counted as `ff1_count` in `dspboot.py`), so
every emulator result this project has taken off that path is sound. The
`digikit-accel` patch would make it *native* instead — faster, and one less
hand-written stub between us and the machine.

### The one to read first, because it questions our own results

`m68k-hook-ccr-sync` exists because **"a code hook, or a `count=` stop, can
return to the host mid-block"** before condition flags are committed, so a
branch afterwards can take the wrong path. This project drives the emulator
almost entirely through code hooks — the shipping gate's routine counters, the
fault reporter at `0x4011ea6a`, and `emu_lfo4_frame.py`'s stub hook all work
that way. digikit **already carries this patch**, so our runs are covered; the
value is in knowing *why* it is there, because a hooked emulator without it is a
machine that can quietly disagree with the hardware.

### Status

**Corpus, not adopted.** Nothing has been built or run from it. The next step,
when the emulator is next worth an afternoon, is to apply the four missing
patches to the local Unicorn build and re-measure the gate's wall-clock against
today's ~19 minutes — with a stock-control boot beside it, because a faster
emulator that is subtly wrong is worse than a slow one.

---

## Survey, 2026-09-26: what changed in the references

The clones were fetched read-only. What matters here, ranked:

1. **digikit has a SHARC core.** Branch `work/sharc-emulator` (tip `6f812e9`,
   unmerged) is a working SHARC+ executor: `tools/sharc_core/` holds the
   semantics and `tools/sharc_run.py` provides a runner.
   - It renders one DT2 1.16 voice correctly, at about 270k instructions/s under
     PyPy.
   - The claim in `docs/waverider-feasibility.md` that no SHARC core exists is
     therefore out of date. Wavefinder Milestone 1 runs that emulator as an
     external tool.
   - The branch also fixes several decode errors (`DB_VERSION` 13), one of which
     wrongly marked DN2's loader block 57 as stale. Our SHARC databases should be
     rebuilt against it.
2. **octabam's module system solves the clash in our compatibility matrix**
   (MIT, portable with attribution).
   - One platform loader (`tools/remix/loader.S`) owns the start-up hook and the
     appended area. Modules contribute payload entries to its table.
   - The DRAM units of every module are linked together in one link.
   - `tools/remix/ledger.py` checks every claim before any byte is written:
     caves, hook sites, pokes, pinned return addresses, "one appended runtime per
     image".
   - `tools/remix/index.py` prints the pairwise matrix from that check rather than
     keeping it in a README. `dnfw mods matrix` follows the same principle
     (`docs/mods-compatibility.md`).
   - Adopting the platform loader is what would let lfowaves, bootscreen and lfo4
     combine. Not done yet.
3. **`irpina/digiemu` v0.2.0** (GPL-2.0+). It emulates the Digitakt mk1 and the
   Digitone mk1; on the Digitone the second ColdFire runs the FM voices.
   - It is not a SHARC core, and it cannot run DN2 1.11.
   - Its `emu.fwcheck` is worth learning from: it boots stock and custom builds
     fresh, diffs their screens as PNGs, and checks render margin. That is a
     stronger shipping gate than ours.
4. **`gdeo607/DT1_8_POLY_OSC`** (MIT, for its own code). Eight-voice poly as a
   fifth SRC machine on the Digitakt 1.53.
   - Everything happens on the ColdFire, because the DT1 renders audio there.
   - The method is instructive for DN2 voice work. A hook rewrites the trig
     message's voice index but keeps the control track's parameter pointer. It
     then clears the engine's per-voice cache, so the next trig copies the
     parameters in full.
5. **`Bezronczek/syntakt-firmware-workbench`** has added two LFO shapes on the
   Syntakt, confirmed on hardware. That is the first public added LFO shape on an
   Elektron box.
   - One of its pre-download checks confirms that each tool stayed inside the
     regions it declared. We check that in tests for each mod
     (`test_changes_nothing_outside_its_extents`), not at apply time.
6. **`bkkbrls-del/midisc`** has a hardware negative worth heeding. Persisting a
   setting as a project-settings text key bricked the device on Project Save.
   Persistence should ride the binary project path, as LFO4's does.
7. **`emuyia/ems-octakit`**: its exception reporter stamps a build identity into
   the crash screen, a cheap addition to our fault reporting. **octabam** also
   documents Octatrack LFO evaluation on the ColdFire (`docs/firmware/LFO.md`).
8. ~~**`timhastie/octa-panel`** is a paraphonic FM engine on the Octatrack's
   ColdFire. Its licence is not checked, so inspiration only.~~ **Corrected
   2026-09-27:** octa-panel is Tim Hastie's dev log for a real-time C++
   ColdFire+DSP56300 emulator with a virtual front panel, and the earlier home
   of the synth/quantizer/direct-jump modules now live at `timhastie/octatrick`
   and merged upstream into `sambanks/octabam`. Its licence is now checked —
   MIT, same terms as octabam's. See the full entries below.

No new commits in: elektron-firmware-tool, octa-bt-pt, octamax, selache,
adsp-ldr. lalzart has only its CC0 commit.

## `irpina/elekloader` and `irpina/digihealth`: a mod loader, and a runtime probe over USB (added 2026-09-27)

By the author of digiemu. Both target the **Digitakt mk1, OS 1.53**, not the DN2.
Tracked at the owner's request.

**Licence: GPL-2.0.** The NOTICE says "version 2", and the file headers checked
carry no "or later". Read that as **GPL-2.0-only**, which cannot be combined with
this repository's AGPL-3.0-or-later. **Treat both as design references; copy no
code.** elekloader's codec and ISA files come from digikit, which we already use
as a tool.

### elekloader: the loader model we are converging on
- **A mod ships only its author's bytes plus hashes of the stock bytes it
  expects.** Runs of 8 or more bytes that repeat stock are stored as references
  and refilled from the user's own file. This is the same stance as our
  `Extent`/stock-guard model and our transplant rule (donor bytes read at apply
  time). It is also a cleaner general mechanism for "a displaced instruction is
  stock".
- **A `core` mod owns the shared hook sites and turns them into events**
  (`ev_tick`, `ev_draw`, `ev_key`, `ev_enc`, `ev_settings`, `ev_render_in/out`).
  Other mods subscribe with an `order`, and a linker places their code and
  resolves symbols. This is the octabam platform-loader idea, carried through:
  exactly what would lift our **lfo4 / lfowaves / bootscreen mutual exclusion**,
  which all three have because each needs the start-up hook
  (`docs/mods-compatibility.md`). Also: named resources (`sysex:0x7d`,
  `settings:ROW`, `drive:/path`) are claimed and checked for clashes.
- **What a build guarantees:** only the main OS section changes; the bootloader
  is never touched; the unpack is simulated in place over the bootloader's
  staged copy before the file is written. The in-place check is one we do not
  run.
- **For the DN2 it lacks the HMAC trailer** (`docs/DEVICES.md` says so: it
  refuses sealed devices until ported). We have the trailer.

**Correction, 2026-09-27 (same-day fact update, not a reversal).** v0.3.0
(commit `640c580`) added a second device profile: the **Octatrack MKI/MKII, OS
1.40C**. This is whole-image (format-1) support only — `elekloader` rebuilds
and re-flashes the Octatrack's `.syx`/`.bin` container byte for byte — not the
`core`/hook-bus mod system above. `docs/DEVICES.md` names why: the Octatrack's
bootloader staging address is unknown, so the in-place unpack cannot be
simulated, and its free run-time areas are unmapped, so there is no linker
layout for it yet. Digitakt mk1 remains the only device with linkable
(format-2) mods.

### digihealth: the runtime probe
- **FAST AUDIO:** copies the render's hot code (~19 KB) into free on-chip SRAM
  that the OS clears at boot and never uses. It checksums the copy once a second
  and falls back to the original if anything has written over it. Measured on a
  unit: 537 → 480 µs a block; DSP load 80.5 → 72.0 %. That is a ColdFire-side
  render on the mk1, but the technique (self-checking relocation with fallback)
  is directly relevant to our SHARC relocation problem
  (`docs/waverider-dsp-silence.md`).
- **The probe:** a **read-only SysEx channel over USB**, using Elektron's
  manufacturer header and device byte **0x7D**, which no Elektron machine uses,
  so a stock OS ignores it. Commands:
  - `HELLO`;
  - `STATS`: once a second, render and idle time, the heap by block size, free
    sample memory;
  - `PEEK ADDR LEN`: DDR and SRAM only.

  Client: `tools/digiusb.py` (Windows winmm through ctypes; close Transfer first).
- **Why it matters here:** it is the runtime-dump instrument we have been
  missing. Our `lfo4-tlm` probe read one value over CC25. A DN2 equivalent would:
  - let the owner read live ColdFire state on the instrument with a read-only
    allow list, instead of flashing a telemetry build per question;
  - measure DSP and CPU load for the save-while-playing stutter directly;
  - read the ColdFire's copy of DSP state (the frame, the machine type) while the
    DSP silence is happening.

  It would be our own implementation, with a read-only allow list.
  **Not built.** A DN2 port needs our own hook, and a claim on a device byte that
  checks for clashes with DNX's SysEx traffic.

### Status
**[O]**: read from the repositories' READMEs, NOTICE, DEVICES.md and ADAPTING.md
on 2026-09-27. Nothing run.

---

## `irpina/digislicer` — a slice editor built as an elekloader mod

<https://github.com/irpina/digislicer>, by irpina. Targets the **Digitakt
mk1, OS 1.53**, confirmed from its own README rather than assumed from
elekloader's other mods. Two releases: v1.0 (2026-09-26), v1.1 (2026-09-27,
knob A-D labels and smooth knob-D zoom).

**Licence: GPL-2.0.** Same bare Version 2 text as elekloader and digihealth,
no "or later" anywhere in `LICENSE` or the README's licence line. Read as
**GPL-2.0-only**, not combinable with our AGPL-3.0-or-later. Design reference
and tool only, same as the rest of the irpina set.

It adds a slice editor for the Digitakt's **SLICE machine**: hold YES for
about a second on a SLICE track's SRC page to open it, then knobs A-D
select/move/fine-move/zoom a slice boundary. Slices persist per sample by
content hash to the `+Drive` (`/cfw/slices.a`, `/cfw/slices.b`), and v1.1
added a GRID `AUTO` position that runs transient-based auto-slicing. It is
built on elekloader's **format-2** (linkable, hook-bus) mod architecture — the
same `core`-owned event system documented above — and is checked against a
specific `core` version (2.0a) before it will load.

**Why it matters here:** it is a second, independent mod built on the loader
model we are already reading as a design template, and it is the first of
that set to touch persistent per-sample state on the `+Drive` rather than
just RAM or settings — closer to our own project/kit persistence problem than
elekloader's own core is.

**Status: [O].** Read from the README and LICENSE on 2026-09-27. Nothing run,
nothing ported.

---

## `www.junes.website/goodies/octakit` — the same Octakit, hosted as a browser build

<https://www.junes.website/goodies/octakit>, by June Kiff (`emuyia`) — this is
**the same project as `emuyia/ems-octakit`**, already tracked above, not a
second author or a second tool. The page hosts development builds of the
Octatrack Kits patch (256 Kits per Project replacing the stock 64 Parts) that
can be applied in-browser to the visitor's own OS 1.40C file, as an
alternative to cloning the repository and patching locally.

**Licence: none stated for the code.** The page carries only a usage
restriction on the *output*, quoted verbatim: *"DO NOT redistribute the
generated .syx. Share this page instead."* It also flags these as
"bleeding-edge development builds, intended only for testing purposes," with
the usual crash/data-loss caveats. Since the underlying project (`ems-octakit`)
is MIT as of 2026-09-12, that licence — not this page — is what governs the
code; the page is a distribution surface, not a separate grant or a separate
restriction on the source.

**Why this needed checking at all:** two names that read as two Octakits
("junes' octakit" and "ems-octakit") are one project with one author and one
licence. Recorded here so the next reader does not open a second investigation
into a repository that does not exist.

**Status: [O].** Read from the page on 2026-09-27 (`WebFetch`), cross-checked
against `emuyia/ems-octakit`'s own README, which links this exact URL as
"Development builds." Nothing run.

---

## `timhastie/octatrick` and `timhastie/octa-panel` — modules built by hardware confirmation, now upstream in octabam

Two repositories by Tim Hastie, both forks of `sambanks/octabam`. Together
they are the working record of how three Octatrack modules — a two-operator
FM synth machine, a scale quantizer, and a "direct jump" pattern-chain
feature — went from an idea to hardware-confirmed code merged into octabam's
own module table.

**Licence: MIT**, on both repositories, with an appended paragraph scoping the
grant to "this repository's own source code and documentation" and explicitly
excluding Elektron firmware and the content of any submodule. This is the
*same* text as octabam's own `LICENSE`, copied forward with Sam Banks' original
copyright line intact (both repos derive most of their tree from his), which
is exactly why GitHub's API reports their licence as `NOASSERTION`/"Other"
rather than plain MIT — the trailing carve-out paragraph breaks the exact/fuzzy
matcher. Read correctly it is MIT for the repositories' own code, **yes,
portable with attribution** — not for the `octatrick-modules` submodule's own
content or for anything Elektron's, which stay under their own terms.

### `timhastie/octatrick` (branch `main`) — the live location
Composes three modules, consumed as the `timhastie/octatrick-modules` submodule
pinned to a tag (`v9.1`, hardware build `OCTATRICK9`):

| module | what it does |
|---|---|
| **SYNTH MACHINE** | a FLEX track whose sample is named `SYNTH*.wav` becomes a two-operator FM voice (PTCH/RATO/INDX/RATE/FDBK/DEC); VOIC 1-4 gives mono through paraphonic; 32 lockable chord shapes snapped to scale |
| **SCALE QUANTIZER** | a SCALE row (24 scales) snaps PTCH, locks and chromatic-key trigs; a GLIDE row gives 303-style legato; live-recorded notes write AMP HOLD length locks |
| **DIRECT JUMP** | CHAIN AFTER gains a DIRECT option: a pattern change lands on the next step at the old pattern's step count, instead of restarting (the A4/Rytm-style behaviour) |

Two remixes, `octatrick` (stock effects plus the three modules) and
`octatrick-usb` (adds `markandrus/octemu`'s USB MIDI/audio) — confirmed on the
author's MKI for all 20 USB audio channels.

**For our methodology:** the discipline is **pin to a tag, then re-verify byte
identity on relink before trusting the port** — the same stance our transplant
work takes toward donor bytes, independently arrived at here for a ColdFire
module rather than a SHARC voice.

### `timhastie/octa-panel` (branch `panel-ui`) — the historical dev log, now superseded as the live location
Built a real-time C++ ColdFire+DSP56300 emulator (`tools/emu/ot_emu`) with a
virtual front panel, and is where the three modules above were first written,
tested and flashed — its README now says plainly: *"Looking for the firmware
modules? Their current home is `timhastie/octatrick`."* The panel/emulator work
itself was merged upstream into `sambanks/octabam` via PR #458 with
attribution.

**For our methodology, the more useful thing than the panel itself:** every
commit (prefixed `CONTEXT:`) reads as a two-stage gate — a feature is built and
checked against the emulator, then flashed and given a *dated* hardware
confirmation, and only then treated as done. Emulator agreement alone never
closes anything. We follow this in practice already (the Waverider milestones
are dated and hardware-checked); it is not written down as a rule anywhere in
our own docs, and this is a second project doing it independently, which is
reason to write it down.

**Status: [O]** for both. Read from READMEs and LICENSE files on 2026-09-27.
Nothing ported, nothing run.

---

## `Zac-Kyoti/octatrack-kyoti-fw` — a personal Octatrack fork with a mechanically enforced dead-end tier

<https://github.com/Zac-Kyoti/octatrack-kyoti-fw>, by Zac-Kyoti. Targets the
**Octatrack MKI, OS 1.40C**, credits `sambanks/octabam` as the DNA it is built
on (not a submodule fork of it), and is extremely active: 47 commits in the
24 hours before this survey.

**Licence: MIT with explicit exclusions**, stated in unusual and useful detail.
The grant covers everything in the repository — RE notes, analysis/emulation/
diagnostic scripts, ColdFire and DSP patch sources, build tooling, docs —
**except**: (1) all Elektron material (none is distributed; the user supplies
their own OS); (2) `tools/attic/`, inherited from `mxldyn/octamax` and tagged
`SPDX-License-Identifier: NONE` in-place, kept only as a reverse-engineering
cross-reference and never built; (3) patches to third-party tools and anything
fetched at build time, which keep their own upstream licence (`dsp56300/dsp56300`
is GPLv3, `octabam` is MIT — read as reference, never copied in if GPL-family);
and (4) any third-party source generally, never copied in unless MIT-compatible
with its own notice retained. **Verdict: yes, portable with attribution, for
the repository's own code** — `tools/attic/` is a hard no, same reasoning as
octamax itself.

Three things earn it a full entry rather than a mention:

- **A mechanically enforced SUPERSEDED tier.** Builds are FINAL, PREVIEW, WIP
  or SUPERSEDED; a SUPERSEDED builder stays in `tools/` for its reasoning but
  **refuses to build** unless `KYOTI_ALLOW_SUPERSEDED=1` is set, and names its
  replacement. `tools/kyoti_status.py` enforces this in code — "the gates are a
  courtesy, not a lock." Eleven dead-end builders are kept this way. This is
  our own "keep superseded paths, mark them, never delete" practice, but
  enforced by a script instead of a convention — worth mirroring literally.
- **A documented history of hardware-rejected attempts**, kept beside the
  eventual fix rather than replaced by it. `reference/handoffs/DIRECTJUMP_PHASE_HANDOFF.md`
  and the README's version table run V5.1 through V5.11 for the DIRECT JUMP
  feature: V5.1 is marked "DO NOT FLASH — hardware-rejected," an attempt at
  "clearing the hold mask `0x80006626`" (Hook Q) is logged as rejected because
  it did not fix the bug, and V5.8 ("THE WRAP FIX") is the point the actual
  cause — a step count that should preserve across a pattern wrap, not
  recompute — was isolated. Our own "a closed path is still a valid signal"
  practice, independently arrived at.
- **A concrete emulator-speed data point.** Route A is octabam's Unicorn-based
  ColdFire harness (Python, hook-instrumented, control-flow only): raw Unicorn
  TCG throughput on the author's machine is 154-252 MIPS with no hooks — faster
  than the real ColdFire's ~176 MIPS — but 435 per-instruction code hooks at
  EMAC macload sites degrade it to a measured "121-143x" slowdown (an
  `emu_pattern_led.py` diagnostic: 183.8 s stock / 190.0 s patched). The same
  diagnostic ported to `ot_emu`, octabam's native C++ ColdFire+DSP56300 port,
  ran 16.7 s / 16.4 s — an **11x** wall-clock speedup, byte-identical output.
  The author's own conclusion: "Route A cannot be micro-optimised into speed …
  reach for the C++ port, not a faster route A." That is a direct, measured
  answer to the same question this project has open against its own ~4.5
  min/100M-instruction emulator cost.

**Status: [O].** Read from the README, LICENSE, NOTES.md and
`DIRECTJUMP_PHASE_HANDOFF.md` on 2026-09-27. Nothing run, nothing ported.

---

## Survey, 2026-09-27

Fetched read-only via the GitHub API and raw file access, plus one `WebFetch`
for the one non-repository source. What matters here, ranked:

1. **`sambanks/octabam` has repositioned itself as an "unofficial community
   remixer"** (its own words, README rewritten 2026-09-26) and gained
   real verification tooling in the same push:
   - **CI on GitHub** (`.github/workflows/ci.yml`): three jobs, all
     firmware-free (no stock OS, no project, no hardware needed) — an
     acceptance-runner test, a `dsp56300` + our-patch toolchain build, and
     ColdFire-port unit tests, each matrixed over Ubuntu and macOS, actions
     pinned to commit SHAs rather than tags. **We have no CI at all**; even
     this firmware-free subset (parser/codec unit tests, a `dnfw mods matrix`
     staleness check) is something ours currently lacks.
   - **CF METER**, a module that turns the ColdFire's own frame-interrupt
     timing into readable audio: a DMA timer stamps interrupt entry and exit,
     the durations are packed into a per-frame table, and a 29-word DSP insert
     reads that table back as an 8-slot square wave on a spare track,
     decoded offline by `tools/harness/cfmeter.py` from a WAV capture. Full
     mechanism in `modules/cfmeter/README.md`. This is a genuinely new
     technique for us: **runtime telemetry delivered through the audio path
     we already capture**, not a new USB or SysEx channel.
   - The module table and remix index are now rendered from the modules' own
     manifests, with `make check` refusing a stale copy (`verify_docs`), and
     `verify_scenesp2` measures its "fader-0 MODE" expectation from a live run
     with an empty pool rather than hard-coding the literal 0 — the same
     "measured, not asserted" discipline `docs/PRINCIPLES.md` already asks of
     us, seen enforced by someone else's tooling.
   - `tools/remix/loader.S` and `tools/remix/ledger.py` — the platform-loader
     and claim-checking ledger noted in the 2026-09-26 survey — are unchanged
     and still there; the new `modules/`/`remixes/` layout sits on top of them
     as content, not a replacement.
   - Licence re-checked: still MIT. The `LICENSE` file carries a trailing
     paragraph scoping the grant to octabam's own code and excluding Elektron
     material and submodule content, which is why GitHub's API reports it as
     `NOASSERTION` rather than plain MIT — read past that, it is unchanged and
     still portable with attribution.
2. **Three Octatrack modules — a two-op FM synth, a scale quantizer, and
   "direct jump" — went from `timhastie/octa-panel`'s dev log through
   `timhastie/octatrick` to merged, hardware-confirmed modules in octabam.**
   New full entries above cover both repositories; the short version is that
   `octa-panel` is now a historical record and `octatrick` the live one, and
   the two-stage "emulator pass, then dated hardware confirmation" gate they
   both practise is worth stating as an explicit rule in our own docs, not
   just a habit.
3. **`Zac-Kyoti/octatrack-kyoti-fw`**, new to the set, ships a mechanically
   enforced SUPERSEDED build tier (`tools/kyoti_status.py`, gated behind
   `KYOTI_ALLOW_SUPERSEDED=1`) and a measured emulator-speed finding: a
   Unicorn-plus-435-hooks harness costs 121-143x against real ColdFire speed,
   while a native C++ ColdFire+DSP56300 port costs only ~11x, byte-identical.
   Full entry above. Directly bears on our own emulator-speed backlog item.
4. **`irpina/elekloader` v0.3.0 added Octatrack MKI/MKII, OS 1.40C support**
   — whole-image (format-1) only, since the Octatrack's bootloader staging
   address and free run-time areas are not yet known to it, so no linkable
   (format-2, hook-bus) mods exist for it yet. The Digitakt mk1 remains the
   only device with the `core`/event architecture we are reading as a design
   template. `irpina/digihealth`'s licence was re-checked and its
   "GPL-2.0-only" reading confirmed (`NOTICE` says "version 2" outright;
   three source file headers checked, none contradict).
5. **`irpina/digislicer`**, new to the set: a slice editor for the Digitakt's
   SLICE machine, built on elekloader's format-2 mod architecture and the
   first mod in that family to touch persistent per-sample state on the
   `+Drive`. GPL-2.0-only, same as the rest of the irpina set. Full entry
   above.
6. **`irpina/digiemu`: one fact correction.** Commit `3206402` corrects the
   Digitakt mk1's DDR from a previously assumed 64 MB to the actual **128 MB**,
   measured under stock OS 1.53 load. Licence re-confirmed GPL-2.0-or-later
   (the README states "or-later" outright — the only one of the four irpina
   repositories whose own text does).
7. **`www.junes.website/goodies/octakit` is `emuyia/ems-octakit`'s own site,
   not a second project.** Full entry above; the `ems-octakit` section is
   corrected in place to stop reading as unlicensed and to note the site and
   octabam's `OCTAKIT` module.
8. **`nordseele/octalab-notes`**: 13 commits, all either a proposed **OTX**
   shared project-settings/storage format for Octatrack tools (drafted with
   Sam Banks, now at "draft 2," with a fresh/recovered/damaged card-state
   table) or USB-audio-input testing on the MKI. Not adopted here — the
   Octatrack's `+Drive` layout is not ours — but a cross-tool interchange
   proposal for the same shape of problem our own project/kit persistence
   work has is worth a re-read if it stabilises. Licence unchanged, MIT.
9. **Our own site** (`angellinares.github.io/dn2_firmware_explore`) is up and
   current: nine tool pages plus the LFO Shape Bench design tool, the
   compatibility matrix at the top, generated by `dnfw mods matrix`.

**Licence re-checks with no change:** `mischa85/elektron-firmware-tool` (MIT),
`bryantysinger/octa-bt-pt` (MIT), `bkkbrls-del/midisc` (MIT — same trailing
carve-out paragraph as octabam's, hence also reported `NOASSERTION` by the
API), `emuyia/ems-octakit` (MIT, confirmed unmoved since 2026-09-12),
`js216/selache` (GPL-3.0), `m-dwyer/digikit` (GPL-2.0-or-later),
`dagargo/elektroid` (GPL-3.0), `lalzart/digitakt-ii-firmware-research-public`
(CC0-1.0), `Bezronczek/syntakt-firmware-workbench` (MIT).

**No new commits since 2026-09-26 in:** elektron-firmware-tool, octa-bt-pt,
ems-octakit, midisc, `js216/selache`, `m-dwyer/digikit`,
`dagargo/elektroid`, `Bezronczek/syntakt-firmware-workbench`,
`lalzart/digitakt-ii-firmware-research-public`. `mxldyn/octamax` has one
(`3083f69`, a MIDI-mode fix) — still **NO** licence file, still
inspiration-only.

### What would improve our debugging and methodology

Ranked by how directly each closes a gap this project already has open.

1. **Runtime telemetry over the audio path we already capture** — from
   octabam's CF METER. Concrete step: prototype a SHARC- or ColdFire-side
   probe that stamps frame timing (or a value from `docs/waverider-dsp-silence.md`'s
   open questions) into an unused sample slot or a spare channel of a render
   we already take, and write the small decoder now, rather than waiting on a
   DN2 port of digihealth's USB channel to get any runtime number at all.
2. **A native, from-scratch emulator core beats a faster hooked interpreter**
   — from `octatrack-kyoti-fw`'s measured 121-143x-vs-11x finding. Concrete
   step: when the emulator work is next worth an afternoon (already flagged
   against digikit and digiemu), weigh octabam's `ot_emu` C++ architecture
   directly rather than continuing to patch Unicorn — this is now a second,
   independently measured data point saying the same thing.
3. **A mechanically enforced dead-end tier**, not a convention — from
   `octatrack-kyoti-fw`'s `KYOTI_ALLOW_SUPERSEDED` gate. Concrete step: give
   our own rejected builds (flashed and reverted) a code-level gate the same
   way, so a superseded build can't be picked up by a script by accident, the
   way our own `docs/PRINCIPLES.md` already asks us to keep them recorded but
   currently only in prose.
4. **State the two-stage confirmation gate as a rule, not a habit** — from
   `octatrick`/`octa-panel`: emulator agreement is necessary but never
   sufficient; a feature is done only once a *dated* hardware confirmation
   exists beside it. Concrete step: add this one sentence to
   `docs/PRINCIPLES.md` — we already do it (the Waverider milestones), but it
   is not written down as a rule anyone else could check us against.
5. **Firmware-free CI**, even a subset — from octabam's three SHA-pinned
   GitHub Actions jobs. Concrete step: put our own parser/codec unit tests and
   a `dnfw mods matrix` staleness check into a GitHub Actions workflow; none of
   it needs Elektron bytes, so none of it is blocked by the no-firmware-in-
   the-repo rule.
6. **A device-profile checklist for "what a new device needs"** — from
   elekloader's `docs/DEVICES.md` (`releases`, `sysex_id`, `main_section`,
   `stage`, `trailer`, `isa`, `areas`, `protected`, `blob_max`, `toolchain`,
   plus named tests before anything is flashed). Concrete step: use this as
   the checklist shape if this project ever formalises its own DN1/DN2/DT2
   device-profile split, rather than growing the distinction ad hoc across
   `docs/hardware.md` and `docs/DEVICES.md`-equivalents.
