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

---

# The rest of the family, as reported by a third party — 2026-09-20

Relayed to this project by the owner from an outside account of the boards.
**None of it was measured here**, and it is written in our own words with the
part numbers kept, because part numbers are the checkable part. Treat every row
as a claim until a photograph or a datasheet settles it — the same standard
§"The parts" above met and this section does not.

| box | CPUs | FPGA |
|---|---|---|
| Digitone (2017) | **two** ColdFire `MCF54415CMJ250` | Xilinx Spartan `XC3S50A`, said to bridge the two |
| Digitakt (2017) | one ColdFire `MCF54415CMJ250` | — |
| Digitakt II | one ColdFire `MCF54415CMJ250` + **SHARC `ADSP-21569`** | — |
| Syntakt | **two** ColdFire `MCF54415CMJ250` | `XC3S50A` in the Digitone's position, plus an `XC3S200A` taken to drive the analogue side |

With `MCF54415CMJ250` given as 250 MHz with 64 KB of SRAM, and the
`ADSP-21569` as 800 MHz–1 GHz with 640 KB of L1 and 1 MB of L2.

The account adds that Digitakt II's new DSP capability comes from the SHARC,
and that the original Digitakt's single ColdFire is where its backward
compatibility comes from.

## What our own measurements say about it

Two of the claims are ones this repository can speak to, and both hold up:

- **The DN2 arrangement matches what is claimed for Digitakt II.** §"The parts"
  read `MCF5441SCMJ250` and `ADSP-21569` (U9) off the owner's photographs of
  PCBA0109B — one ColdFire and a SHARC, exactly the pairing described.
- **A Digitone with no SHARC has to do its audio somewhere, and we measured
  where.** `docs/dn1-dsp-comparison.md` counted **613 MAC/MSAC in DN1 1.43's
  code region against 50 in DN2 1.11's**, on near-identical `mulsl` counts.
  DN1's audio DSP runs on ColdFire. A second ColdFire carrying that load is a
  coherent explanation of a 12× difference that had none.

So the claim and our measurement corroborate each other from opposite ends:
the part list says DN1 has two ColdFires and no DSP chip, and the instruction
census says DN1's ColdFire side does twelve times the multiply-accumulate work.

It also answers, provisionally, the last open item above — *"the DN1's CPU
part, for a clean comparison"* — with `MCF54415`, an EMAC-equipped part of the
same generation as the DN2's. Provisionally, because it is a claim.

## The question it opens, and how to settle it

**If the DN1 has two ColdFires, where does the second one's program live?**
DN1 1.43's section table (`dn1-dsp-comparison.md`) has no second code section
at a second load address: MAIN OS at `0x40000400`, the updater at
`0x80000400`, an ARM Cortex-M accessory image, a raw `blob`, and **section 6 —
1,492 bytes, raw, DN1-only, still unidentified**.

Two readings, and they are separable with instruments we have:

1. **One image, two cores.** Both CPUs boot the same MAIN OS and branch on a
   core or strap identity. Then there is a read of a hardware ID near reset
   and a divergence after it — `dnfw fn callers` and the bootstrap section are
   where to look, and `docs/bootstrap.md` already covers that ground.
2. **The second core's code is data to the first.** It is loaded from the
   `blob`, or from flash that never appears in the update file at all — which
   §"What the board says about the DSP boot question" already found to be the
   DN2's situation for the SHARC.

Section 6 is tempting as the FPGA's configuration, and **the size argues
against it**: an `XC3S50A` bitstream is on the order of 50 KB, not 1.5 KB. So
section 6 is more likely a small table than a bitstream, and the Spartan is
probably configured from its own flash — recorded here so the next reader does
not spend the same guess twice.

## The speculation, marked as such

The same account suggests that because the Syntakt shares the Digitone's
two-ColdFire architecture, features from Syntakt's 1.30 update — Euclidean
sequencing, page looping, random name generation, saving a p-lock into a
preset, LFO slew — are ones a Digitone could plausibly receive.

That is speculation about Elektron's roadmap, not a reading of any binary, and
nothing here depends on it. It is kept because it names **features that already
run on this architecture**, which makes each one a prior-art question this
project can actually ask: if Syntakt does LFO slew on a ColdFire, its firmware
is evidence about what the LFO block can be made to do — the same use
`docs/octatrack-lfo-prior-art.md` makes of the Octatrack.
