# The Digitone II mainboard, read from the part numbers

Everything below is read off the owner's photographs of **PCBA0109B**
(`©2023 Elektron Music Machines MAV AB`, board serial `0109B6E24090318`),
2026-09-12. This is the hardware ground truth the memory map and the CPU
assumptions should be checked against — and checking them corrected two things
the repository had wrong.

## The parts

| Ref | Part | What it is |
|---|---|---|
| — | **`COLDFIRE MCF5441SCMJ250`** | the main CPU — an **MCF5441x**, 250 MHz |
| — | **NANYA `NT5TU128M8HE-AC`** | **DDR2 SDRAM, 128M×8 = 128 MB** — the ColdFire's RAM |
| — | **Winbond `25Q128JVFQ`** | **W25Q128JV — 128 Mbit = 16 MB SPI NOR flash** |
| U8 | Kingston `EMMC32G-TX29` | eMMC — mass storage, the +Drive |
| **U9** | **Analog Devices `ADSP-21569`** | **SHARC+ DSP**, `KBCZ10`, date code `2341` |
| U25 | Kingston `D2516ECMDXGJD` | DDR3 SDRAM — sits beside the SHARC, so it is the **DSP's** memory |
| U14 | **AKM `AK4621EF`** | audio codec |
| Y4 | FOX 20.000 MHz | crystal by the SHARC |

## Correction 1 — the CPU is an MCF5441x, not the V4e this repo assumed

`docs/mainos-image.md`, `docs/memory-map.md`, `docs/references.md` and
`docs/ideas-backlog.md` all describe the DN2 as **ColdFire V4e**. That came from
octabam, and it is the **Octatrack's** part (MCF547x/548x family), inherited by
analogy rather than measured.

The DN2 is an **MCF5441x**, a later and different family. **The V4e/V4m
distinction and whether this part has a hardware FPU must be confirmed from
NXP's datasheet before anything is built on it** — but the implication is
serious enough to record now, because it invalidates an argument this project
used.

### What it invalidates: the zero-FPU evidence

`docs/engine-index-map.md` §9 argued the ColdFire does no audio DSP from two
measurements: **zero floating-point instructions** and **50 MAC instructions** in
582,407 decoded instructions.

**If the MCF5441x has no FPU, the first measurement proves nothing.** Code
compiled for a part without an FPU contains no FPU instructions whatever it is
doing; the count would be zero for a pure DSP kernel just as surely as for a
menu system. That half of the argument is **void** and is withdrawn.

**The MAC evidence stands, and it was always the stronger half.** 50 MAC
instructions against the DN1's **613** — concentrated there in a ~20 KB region of
tight four-accumulator EMAC loops (`docs/dn1-dsp-comparison.md`) — is a
comparison between two ColdFire builds, both on parts with an EMAC, and it does
not depend on the FPU question at all. The conclusion that the DN2's ColdFire
does no audio DSP survives on that evidence alone.

### What it means for the disassembler

`dnfw disasm` and every analysis in this repository use
`m68k-linux-gnu-objdump -m m68k:cfv4e`. Gate F validated that setting against
Ghidra on real DN2 code, so it decodes this image correctly in practice — cfv4e
is a superset for the instructions actually present. No re-validation is urgent,
but the setting is now known to name a **different core** than the board carries,
and that should not be mistaken for a measurement.

## Correction 2 — nothing, actually: the RAM size is confirmed

`docs/memory-map.md` deduced **128 MB of SDRAM spanning `0x40000000`–`0x48000000`**
from a single instruction — `moveal #0x48000000,%sp` at `0x400004f2`, the stack
pointer set at C-runtime entry, on the reasoning that stacks descend from the top
of RAM.

The board says **NANYA NT5TU128M8HE-AC — 128M×8 DDR2 = 128 MB.**

An inference from one immediate, confirmed by a part number. That is the kind of
cross-check this project is meant to run, and it is worth recording as a hit
rather than quietly assuming it.

## What the board says about the DSP boot question

`docs/engine-index-map.md` §12 left this open: the ADSP-21569 has no on-chip
flash, so it boots from its own serial flash (SPI master), from a host pushing
the image (SPI slave or link port), or from UART. The photograph was taken to
look for a serial flash beside the DSP.

**There is no flash chip adjacent to the SHARC.** The only SPI NOR on the board
is the **Winbond W25Q128JV**, and it sits across the board **by the ColdFire**,
not by the DSP.

That points away from SPI master boot and towards the ColdFire booting the SHARC
— which would mean the DSP image exists in this device but is loaded by code we
hold. It does **not** mean the image is in the update file: 16 MB of SPI NOR is
far more than the ~2.4 MB update, and a factory-programmed DSP image that OS
updates never replace fits every measurement made so far —

- no boot stream found in any ELE3 section, under three different chip premises
  (`docs/engine-index-map.md` §§9, 10, 12);
- no bulk upload path found in MAIN OS;
- `blob` structured as 16-bit data, sized and shaped like samples for the DSP's
  own DDR3 rather than code.

**So the practical conclusion is unchanged and the reasoning behind it is
better:** the DSP's program cannot be altered by patching the update file,
because it is not in the update file — whether or not it is in the device's
flash. Changing it would mean writing to the SPI NOR directly, which is a
different project with a different risk profile and no recovery path proven.

## Open

- **Confirm the exact MCF5441x variant and its FPU/core** from NXP's datasheet,
  then correct `mainos-image.md`, `memory-map.md`, `references.md` and
  `ideas-backlog.md` at source.
- **Where in the 16 MB SPI NOR the ELE3 payload lands**, and what else occupies
  it. That would settle the DSP-image question outright and is also the
  groundwork for anything that ever wants to write flash directly.
- The DN1's CPU part, for a clean comparison with `docs/dn1-dsp-comparison.md` —
  its MAC count is the load-bearing number there and it should be known to be an
  EMAC-equipped part of comparable generation.
