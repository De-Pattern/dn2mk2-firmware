# Reading SHARC+ instructions: what exists, and what it costs

**Surveyed and run 2026-09-14.** `docs/ideas-backlog.md` §7 has been parked on
one sentence — *"nothing in this repository decodes SHARC+ VISA"* — and
`docs/ROADMAP.md` calls it the binding constraint on all DSP-side work. It is no
longer true, and the tool is one we already had cloned.

## The premise to correct first

The concern relayed from a user was that SHARC work "would require a costly
subscription to Analog Devices CrossCore Embedded Studio".

**CrossCore is a toolchain for *building* code, not a prerequisite for reading
it.** The encodings are published: ADI's **SHARC+ Core Programming Reference**
is a free 771-page PDF, and that document is sufficient to write a decoder.
Nothing below needs a licence.

## What exists, publicly

| Project | Target | Use to us |
|---|---|---|
| **`m-dwyer/digikit`** — `tools/ghidra/SHARC/` + `tools/sharc_disasm.py` | **SHARC+ VISA (ADSP-215xx)** | **exactly our chip family; already cloned** |
| `sualk/ghidra-blackfin` (28★) | Blackfin | precedent for an ADI SLEIGH module, different ISA |
| `sergev/g21k` | ADSP-21000 (classic SHARC) | GCC port; **classic 48-bit ISA, not VISA** |
| `mikewolak/sharc_asm` | ADSP-21060/61/62 | two-pass assembler; **classic, not VISA** |

**The last two do not transfer.** Our ADSP-21569 is **SHARC+**, which adds
**VISA** — variable-length 16/32/48-bit encoding. A decoder written for the
classic fixed-48-bit ADSP-2106x will mis-length VISA instructions and desync,
which is the failure mode this project already knows from radare2's m68k backend
(`docs/mainos-image.md`).

**A GitHub code search for `extension:slaspec` mentioning SHARC returns exactly
one repository: digikit's.** As far as public code goes, that module is the
state of the art, and it targets our chip.

## What digikit's module actually is

Two artefacts from one source of truth:

- **`tools/sharc_visa_tables.py`** — 1,659 lines of instruction encodings
  transcribed from the SHARC+ Core Programming Reference. The method is
  documented in its own docstring and is unusually careful: figures re-extracted
  with `pdftoppm` at **400 DPI** because at screen resolution the *gray shading*
  that marks a fixed opcode bit is not reliably legible, with gray (fixed),
  white (operand field) and yellow (reserved) cells distinguished explicitly.
- **`tools/ghidra/gen-sharc-slaspec.py`** → a **47-constructor** Ghidra
  processor module, generated rather than hand-written so the tables stay the
  single source of truth.

Plus **`tools/sharc_disasm.py`**, a stdlib-only linear disassembler using the
same tables, which needs no Ghidra and no Java.

### The limitation that matters: it disassembles, it does not decompile

From the generator's own docstring: *"Only control-flow types carry semantics:
p-code is not needed for disassembly, call graphs or xrefs, which is all this is
for."*

So Ghidra will give **instruction boundaries, call graphs and xrefs** — not C.
Producing decompiled output means writing p-code semantics for the arithmetic
and memory types, which is the substantial remaining work and is what the "vibe
code a SLEIGH module" suggestion would actually be aimed at. The encoding half
is done; the semantic half is not.

It also **refuses to guess**: when it cannot determine a length it emits one
`unknown` and stops, because a wrong length silently desyncs everything after
it. That is the same rule this project applies to its own tools.

## Run against our image, today

`docs/sharc-code-map.md` gives the L2 code region and the boot stream's entry
point `0x001c12e2` → **`0x283825c4`**, which is the region's first byte.
Disassembling from there:

```
0x283825c4  6 bytes  Type14a  confident   g=0 d=0 ureg=0 l=0
0x283825ca  2 bytes  Type2c   confident   compute=574
0x283825cc  6 bytes  Type21a  confident
0x283825d2  6 bytes  Type21a  confident
...
```

**97 confident instructions from the entry point** before it stops honestly. The
mixed 6/2/6-byte lengths are VISA decoding working.

Across the whole L2 code region, restarting after each stop:

| kind | count |
|---|---|
| confident | **3,249** |
| length_only | 271 |
| unknown | 480 |

**~81% confidently decoded.** That is a working disassembler on our firmware,
not a prototype.

### It independently confirms our address mapping

The generator's addressing note says code addresses are **16-bit short-word
units**, so a program is imported at byte base `2 × word address` and branch
targets are doubled. `docs/sharc-code-map.md` derived
**`load = exec × 2 + 0x28000000`** from the entry point landing exactly on a
block boundary and 591/591 targets resolving. Two unrelated derivations — one
from a vendor manual's addressing model, one from counting where cjump targets
land — agreeing on the factor of two.

## What this unparks

`docs/ideas-backlog.md` §7 was parked because the DSP hunt had no way to read
what it found. It now has one, and `docs/sharc-code-map.md` tells it where to
point: ~240 KB of code in two regions, with a confirmed mapping for the `0x1c`
space.

The standing LFO4 question — **where the LFO generators live, given MAIN OS
contains no generator of any kind** (`docs/display-path.md`) — is now a question
that can be *asked of instructions* rather than of strings.

**What is still missing:** Ghidra itself is not installed on this machine (no
Java; it lives on the flashing machine, `docs/HANDOVER.md`). The Python
disassembler runs here today; the Ghidra module needs the other machine or an
install.

---

# Installed and running in Ghidra, 2026-09-14

Ghidra **is** set up on this machine, natively on Windows (the earlier note that
it was only on the flashing machine was wrong — `docs/HANDOVER.md` is from
before `33d0e0d`):

```
C:\tools\ghidra_12.1.3_PUBLIC        Ghidra 12.1.3
C:\Tools\jdk-21.0.12.1+1             JDK 21 (Temurin)
```

Stock Ghidra 12.1.3 ships **no SHARC, Blackfin or ADSP processor** — confirmed
by listing `Ghidra\Processors` (39 modules, none of them ADI).

## Installing the module

```
copy  digikit\tools\ghidra\SHARC  ->  <ghidra>\Ghidra\Processors\SHARC
<ghidra>\support\sleigh.bat -a <ghidra>\Ghidra\Processors\SHARC\data\languages
```

Result: **`1 languages successfully compiled`**, with
`WARN 45 NOP constructors found` — which is the documented limitation showing
up honestly, not a fault: only control-flow types carry p-code, so 45 of the 47
constructors decode and print without semantics.

### The trap: SLEIGH enforces the path's exact case

The first compile failed with:

```
BailoutException: input file "...\sharc.slaspec" is not properly case dependent
  Canonical path: C:\tools\ghidra_12.1.3_PUBLIC\...
  User path:      C:\Tools\ghidra_12.1.3_PUBLIC\...
```

The directory on disk is `C:\tools` (lowercase). Windows does not care;
**SLEIGH does**, and it fails with a case-comparison error rather than
"file not found", which reads like a spec problem and is not one. Use the
canonical casing. `ghidra\analyze.bat` globs `C:\Tools\ghidra_*`, which works
for everything else but would reproduce this if used to compile a spec.

## Importing our SHARC code

Addressing follows the module: code addresses are 16-bit short-word units, so
the byte base is `2 × word address`. For the L2 code region, whose load address
`docs/sharc-code-map.md` puts at `0x283825c4`:

```
byte base = 0x283825c4 - 0x28000000 = 0x003825c4      (= 2 x 0x1c12e2, the entry)
```

```
analyzeHeadless <proj> sharcL2 -import out\sharc_l2_code.bin \
    -processor SHARC:LE:32:VISA -loader BinaryLoader -loader-baseAddr 0x3825c4
```

**Import and analysis succeeded**, and `ghidra/ExportDisassembly.java` — written
for Gate F against ColdFire, reused unchanged — produced a listing:

```
003825c4  001003000014  t14a 0x3,0x1400
003825ca  3e02          t2c
003825cc  300000000011  t21a 0x0,0x1100
003825d2  030000140000  t21a 0x1400,0x0
```

**796 instructions, 25 undecodable** over the first 4 KB. The 6/2/6-byte
lengths are VISA decoding working, and they agree instruction-for-instruction
with `tools/sharc_disasm.py`'s independent walk of the same bytes.

## A false positive to know about before reading any listing

Many early lines decode as `t21a 0x0,0x0` from **all-zero bytes**. An all-zero
48-bit word satisfies Type21a's mask, so **zero padding disassembles as valid
code** and does so "confidently" in both tools.

That matters because the region's first bytes are largely zero: a listing taken
at the entry point is mostly padding wearing an instruction's clothes. Use the
cjump density in `docs/sharc-code-map.md` to aim at real code rather than
trusting that decoding succeeded — *a decoder that never fails on zeros cannot
tell you it has left the code.*
