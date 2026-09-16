# The non-code sections: `blob` and section 8

`docs/ele3-format.md` records the container's shape and that `blob` (id 7) and
section 8 are carried through verbatim. Neither had ever been opened. Both are
now at least partly identified, which settles one parked idea and reshapes
another.

Measured on DN2 1.11 (build 40059), 2026-09-12.

## Section 8 is ARM Cortex-M firmware — a second processor

Section 8 is **new in 1.11** (~160 KB) and was the reason `dnfw extract` had to
be fixed: `ele3.name` returns `?` for an unidentified section, which is an
illegal Windows filename.

Decompressed it is 159,948 bytes with this layout:

| Offset | Size | Contents |
|---|---|---|
| `0x00000` | 4,096 | `0xff` fill |
| `0x01000` | 48 | a descriptor (below) |
| `0x01030` | 4,048 | `0xff` fill |
| `0x02000` | 100,944 | **vector table + code** |
| `0x1aa50` | 16 | `0xff` |
| `0x1aa60` | 48 | a second descriptor |
| `0x1aa90` | 32 | `0xff` |
| `0x1aab0` | 50,720 | data |

**`0x02000` is an ARM Cortex-M vector table**, and it is unambiguous:

```
0x20010000   initial stack pointer   -- 0x20000000 is Cortex-M SRAM
0x6004220d   Reset handler           -- odd: the Thumb bit
0x600421e5   NMI handler             -- odd
0x6004de01   HardFault               -- odd
0x6004de41 / 0x6004de49 / 0x6004de51  -- odd
0x00000000 × 4                        -- the reserved entries, exactly where
                                         the ARM vector layout puts them
```

Every handler address is **odd** (Thumb) and every reserved slot is zero. The
descriptor at `0x1000` agrees: it names a flash window at **`0x60000000`** of
**`0x100000`** (1 MB) and an image at **`0x60042000`**, which is precisely the
file's `0x02000` at a `0x60040000` load base.

So section 8 is a **complete firmware image for an ARM Cortex-M**, shipped
inside the Digitone II OS update and flashed to some other processor. Given it
arrived in the same release that added Outbox support, and that the DN2's own
CPU is ColdFire, the **Outbox** is the obvious candidate — but that is an
inference from timing, not something read out of the bytes, and the image
carries no identifying string. Do not write it down as fact until something
names it.

**This answers the parked "remove the Outbox chunk for space" idea** (§1 of
`docs/ideas-backlog.md`) more sharply than before: section 8 is not DN2 code at
all, so deleting it frees **flash and update size only** — no ColdFire address
space, which is the thing a fourth LFO actually needs. It also means deleting
it would leave an attached Outbox running whatever firmware it already has.

### [CONFIRMED 2026-09-16] Section 8 is the same image on a different product

The Outbox attribution was recorded as *"an inference from timing, not something
read out of the bytes… do not write it down as fact until something names it."*
It still is not named, but it is no longer a guess about which device it belongs
to.

**Digitakt mk1 OS 1.53** (product code 44, unsigned, MAIN OS 2,475,584 B) carries
a section 8 that is **byte-for-byte identical** to Digitone II 1.11's:

```
DT1 1.53 section 8 : 159,948 bytes  sha256 6943b2f27773f40f1e7857ea6fa7a121…
DN2 1.11 section 8 : 159,948 bytes  sha256 6943b2f27773f40f1e7857ea6fa7a121…
                                    IDENTICAL
```

**The same ARM Cortex-M firmware ships inside the update for two different
instruments** — a first-generation Digitakt and a Digitone II, different CPUs,
different feature sets, different MAIN OS entirely. Device-specific code could
not be identical across those. A **shared accessory's** firmware is exactly what
would be.

So section 8 is confirmed to be **neither product's own code**, and to be a
common payload both updaters carry. That is the shape of the Outbox and nothing
else on either machine, though the image still carries no identifying string and
the name remains an inference.

**It also settles the space question harder.** `docs/ideas-backlog.md` §1 asks
whether deleting section 8 buys room for a fourth LFO. It does not — already
established, because its `dest` is `0x00000000` and it claims no ColdFire address
space. Now there is a second reason: **deleting it from a DN2 image would strand
a shared accessory** whose firmware arrives by this route on every Elektron
product that supports it, not merely on this one.

**To read it** you need an ARM disassembler; neither the WSL nor the native
binutils here has one (`objdump -i` lists only x86 and the m68k cross). Install
`binutils-arm-none-eabi` in WSL before trying.

## `blob` is mixed data, substantially float32 [SUPERSEDED -- see docs/engine-index-map.md section 10: measured 35% float plausibility, below random]

`blob` (id 7) decompresses to 836,956 bytes. It is **not** a single array:

- Read as 209,239 IEEE-754 floats, **57%** (big-endian) to **66%**
  (little-endian) of the values land in `[-1.5, 1.5]`, and 95–99% are finite.
  A pure audio or coefficient array would be near 100%; a pure code or index
  blob would be near 0%. So it is a **container of several kinds of data**, a
  large part of which is float32.
- The `0x3f`-heavy byte pattern that makes the strings dump look like noise is
  the float32 exponent for values in `[0.5, 1.0)` — consistent with wavetables,
  window functions or filter coefficients.

**This reshapes the "expand the PCM catalogue" idea** (§3 of
`docs/ideas-backlog.md`): if the FM drum machine's PCM content is here, it is
**float32**, not the 16-bit PCM that idea implicitly assumed, and it shares the
section with other data — so the first job is to map `blob`'s internal layout
and find its index, not to look for a WAV-like header.

## What this says about where the engine runs

Worth stating because it bears on the modulation tick, and because it is a
narrowing rather than an answer.

> **[WRONG — corrected 2026-09-13, see `docs/sharc-image.md`.]** Section 7 *is*
> the SHARC program: an ADI boot stream built with CrossCore Embedded Studio and
> FreeRTOS for the ADSP-215xx, carrying its port layer's own source paths and a
> task named `Audio Task`. The paragraph below is kept because the reasoning
> that produced it recurs: a test for a *raw* 48-bit instruction stream cannot
> see code inside a block-structured boot container, and its negative was read
> as an absence rather than as a limit of the test.

The whole update contains: ColdFire code (MAIN OS, bootstrap, updater), ARM
Thumb code (section 8), and data (`blob`). **There is no SHARC program anywhere
in the update.** The `Digisharc` class names in MAIN OS are the project's own
name, not proof of a shipped DSP image.

Two readings survive, and they are not equally cheap to act on:

1. **The synthesis engine runs on the ColdFire**, and `Digisharc` is just the
   product codename. Then the modulation tick is in MAIN OS and findable with
   the tools already in this repository.
2. **A DSP runs the engine from its own flash**, never updated by an OS release.
   Then engine changes could not ship in an OS update — which is hard to square
   with Elektron adding machines in point releases, but is not impossible.

A scan of every section for smooth 16-bit curve tables — the signature of a
waveform or envelope lookup — found **none anywhere**, including MAIN OS. That
is evidence against a table-driven LFO on the ColdFire, and equally against one
in `blob`. It does not settle the question: triangle, saw, square and ramp need
no table, and a sine can be computed. The next test is whether `blob` contains
48-bit-structured data (the SHARC instruction width) rather than only floats.
