# Test points, and joining static findings to one real transaction

**For lalzart, 2026-09-16**, answering: *"Has anyone already investigated
accessible test points or captured either connection?"*

Short answer: **we have never probed the hardware.** Longer answer: most of what
a capture would tell you about the SHARC link is already pinned from firmware,
and the specific experiment you describe — change one known parameter, see which
bytes move — runs today in software, byte-exact and repeatable.

Everything below is measured on **Digitone II 1.11** unless it says otherwise.

---

## 1. Test points: no, and we cannot help there

Nothing in this repository touches a scope, a logic analyzer, JTAG or BDM. Our
only hardware ground truth is `docs/hardware.md`, read off the owner's
**photographs** of board `PCBA0109B` (`©2023 Elektron Music Machines MAV AB`):
part numbers and reference designators only. **No pad map, no probe points, no
captures.**

What that file does give, in case it helps you find pads:

| Ref | Part | What |
|---|---|---|
| — | `COLDFIRE MCF5441SCMJ250` | main CPU, MCF5441x, 250 MHz |
| **U9** | **`ADSP-21569`** | SHARC+ DSP, `KBCZ10`, date code 2341 |
| U25 | `D2516ECMDXGJD` | DDR3 beside the SHARC — the DSP's own memory |
| U8 | `EMMC32G-TX29` | eMMC, the +Drive |
| U14 | `AK4621EF` | audio codec |
| Y4 | FOX 20.000 MHz | crystal by the SHARC |

One correction that came out of reading those photographs, since it invalidated
an argument we had published: the DN2's CPU is an **MCF5441x**, not the ColdFire
**V4e** this project had assumed by analogy with the Octatrack.

---

## 2. There are two ColdFire↔SHARC connections, not one

Worth separating before any capture, because they are different peripherals with
different contracts.

| | **boot link** | **runtime link** |
|---|---|---|
| peripheral | a DSPI at `0xec038000` | **DSPI2** |
| what moves | section 7, the SHARC program, pushed **byte at a time** | one fixed **2,748-byte** full-duplex frame (`0x55e` 16-bit words) |
| when | every power-up, SPI **slave** boot | periodic, interrupt-driven |
| registers | `PUSHR +0x34`, `SR +0x2c` | CTAR0 |
| transport | PIO | **eDMA 29 TX / 28 RX** |
| mode | — | **SPI mode 1, MSB-first, PCS0** |
| entry | `0x400cf34c` | vector 191 handler |

So mode, bit order, framing, chip select and length are **already known from
firmware**. A passive capture would be *confirming* that contract rather than
discovering it — worth knowing before spending a session on rigging.

### The payload length, and a trap in how it reads

The frame is **one fixed full-duplex 2,748-byte transfer**. Both eDMA
descriptors take their word count from the **same variable**, configured once at
boot by a function returning `0xabc`.

**There is no separate RX length to look for.** The first argument to the driver
is how many real payload words get copied in — **2,688 on DN2, 2,050 on DT2** —
and the remainder is tag-only. Wording in digikit's `FINDINGS.md` that reads like
"TX `0x802` … RX `0xabc`" invites exactly the misreading we made first; we raised
it as PR #12 and m-dwyer confirmed it against 1.16's decompilation and added a
correction note.

---

## 3. The experiment you describe already runs, in software

Your roadblock — *"I can often show where a buffer originates and where it lands,
but not confidently identify every changing live value"* — is the half the
emulator solves completely.

`tools/sharcframe.py` in digikit captures the frame the ColdFire builds, from a
snapshot, and already carries the two flags this needs:

```
tools/sharcframe.py SNAPSHOT --compare FRAME.bin --poke ADDR=LONG --open-gate
```

`--compare` diffs against a previous capture; `--poke` sets a value before the
frame is built. So: capture, change one parameter, capture, diff.

**It beats a logic analyzer on your stated problem in three ways.** It is
byte-exact rather than decoded from edges; it is perfectly repeatable; and a
write watch will name **the PC that wrote the changed byte**, which no passive
capture can do.

This is not hypothetical — m-dwyer already got a result this way: a track's
machine type reaches the SHARC in the TX payload at **`0x94 + 2i`**. That is
precisely "change one known parameter, see which field moves", with no hardware.

### Be clear about what it does not do

`sharcframe` raises vector 191 itself and **hooks the driver so DSPI2 and eDMA
are never touched**. It captures the frame the ColdFire *built*, not a bus
transaction.

So it answers **content** — which fields change, and who wrote them — and
answers **nothing** about the physical bridge, signal integrity, or timing. If
your question is genuinely "prove the physical connection and its timing", the
emulator cannot help and a capture is the right instrument. If the question is
"which live values change and where do they come from", the capture is the
harder way round.

### What it needs first

`tools/framelink.py` keys its profile by the **SHA-256 of the MAIN OS image**,
and today carries only **Digitakt II 1.15C and 1.16**. Any other image stops the
tool rather than using wrong addresses — deliberately. Running this on a third
image means adding its profile: vector, handler, driver, pacing counter, and the
gate/countdown/mode/stop variables.

---

## 4. On the project-sample path: there may be a third processor

You mention a separate path for project-sample data where both processor-side
endpoints are visible but the board-level connection is not. One finding from
our side that is worth ruling in or out before assuming it is SHARC-related:

**Section 8 of the DN2 update is a complete ARM Cortex-M firmware image.** The
vector table at `0x02000` is unambiguous — initial stack pointer `0x20010000`,
which is Cortex-M SRAM, and the reset/handler layout matches the ARM vector
order. It is ~160 KB, and it arrived in **1.11**, the release that added Outbox
support.

We inferred Outbox from that timing and **deliberately did not write it down as
fact**, because the image carries no identifying string. But it means this system
has a third processor whose firmware ships in the same update, and if one of your
two endpoints is not the SHARC, that is a candidate.

**And the +Drive is not SPI.** It is eMMC (`EMMC32G-TX29`, U8) reached through
**eSDHC with eDMA**. digikit models the controller in `emu/esdhc.py` and notes
that CMD18 bulk reads move through the SoC eDMA with `SADDR=DATPORT` and nothing
backing them yet — so bulk sample data is exactly the part the emulator does
*not* currently serve.

---

## 5. What we can offer

- The **DN2 1.11 side of the frame contract**, already cross-checked with
  m-dwyer (digikit PR #12): payload 2,688 words, the single-length correction,
  and the per-track `0x60`-stride record that is the same structure as
  `0xee..0xf8 + i*0x60` on DT2.
- **Board part numbers and designators** from `docs/hardware.md`, if they help
  locate pads.
- A **`framelink` profile for DN2 1.11**, if it would be useful to have a third
  image in the comparison — we have the emulator booting this build and driving
  its panel, so the handler and driver addresses are findable.

What we cannot offer is any hardware measurement. The only DN2 here is the
owner's instrument, and opening or probing it is their call, not ours.

---

*Addresses here are ours, measured on DN2 1.11 in this repository. Where this
refers to your DT2 1.15C work it does so in our own words and by citation, per
the licensing note we keep in `docs/references.md`.*
