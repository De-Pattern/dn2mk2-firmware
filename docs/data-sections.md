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

**To read it** you need an ARM disassembler; neither the WSL nor the native
binutils here has one (`objdump -i` lists only x86 and the m68k cross). Install
`binutils-arm-none-eabi` in WSL before trying.

## `blob` is mixed data, substantially float32

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
