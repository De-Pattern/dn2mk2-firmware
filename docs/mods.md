# Firmware mods: the model, and the first one

`dnfw mods` is the user-facing half of this project. Everything else in `docs/`
is how things were found out; this is what someone who owns a Digitone II can
actually do with it.

## What a mod is

A named, declared change to one or more container sections, expressed as bytes
written at known offsets. Deliberately a larger idea than `dnfw.patch`, which
models one same-length edit with `expect` guards — a mod may rewrite hundreds of
kilobytes and carries its own notion of what the user supplies.

Two rules, both enforced rather than remembered:

- **No section changes length.** Every address after a resized section moves and
  nothing here fixes up the code that refers to them. A mod needing more room is
  a code-cave or new-section problem (`docs/ideas-backlog.md` §1a, §6).
- **Integrity is not the mod's business.** A mod produces section payloads;
  `dnfw build` recomputes the section byte-sum, the content checksum and the
  HMAC-SHA256 trailer, and re-verifies before anything is written.

## Compatibility, and what it does not promise

The goal is mixing mods. That only works if each declares, *before* writing,
which bytes it will touch — so every mod implements `extents()` and
`check_compatible()` compares every pair.

**Byte-range overlap is the whole test.** Two mods writing disjoint bytes can
still fight over the same feature, and nothing here detects that. It is the
weakest useful guarantee; it is enforced because it is the part that is
checkable, and the limit is written down rather than glossed.

Every pair is compared, not each against the last: "A is fine with B" and "B is
fine with C" says nothing about A and C.

## Mod 1: `transients`

Replaces the FM drum transient bank (`docs/pcm-hunt.md` §14).

| | |
|---|---|
| section | 7, the SHARC image |
| bank | DDR `0x8045b000`–`0x804ac000`, bounded by float32 tables either side |
| entries | **34**, each 4,800 samples = exactly 100.0 ms at 48 kHz, 16-bit mono LE |
| phase | 2,496 samples into the region |

The load address is mapped to a file offset by walking the boot stream for the
block that covers it — the payloads are scattered across L1, L2 and DDR, so an
offset into the section is not an address, and writing to the wrong one would
corrupt an unrelated region.

### What validates it

**Extracting the factory bank and writing it straight back produces a
byte-identical section 7.** That is a strong check rather than a pleasant one:
a wrong offset, entry size, count, endianness or sample width would each corrupt
bytes, and none does. Rebuilds pass 21 of 21 integrity checks.

### CONFIRMED ON HARDWARE — 2026-09-14

An image carrying marker samples at five known slots
(`scripts/make_marker_transients.py`) was flashed to a Digitone II, and **every
marker played back from `TRAN`.**

That closes both questions this section previously listed as open:

| was open | now |
|---|---|
| never flashed — a file transformation, not a proven firmware change | **flashed and heard** |
| not traced from `TRAN` (id 286) to these bytes | **`TRAN` plays them** — an empirical trace, which is the stronger kind |

It validates the whole chain in one step: locate a bank by statistics, map its
load address to a file offset through the boot stream, replace entries, rebuild,
re-sign, flash, hear. No part of that sequence was previously known to work end
to end.

**What stays conditional:** the bank's location, format, entry length and count
are *measured*, not documented by Elektron, so another OS release could move
them. The mod resolves the address through the boot stream at apply time and
refuses an image whose layout it does not recognise, rather than trusting a
constant.

### The count, resolved

`docs/pcm-hunt.md` §14 recorded a disagreement: the measured extent gives 34
entries, while `TRAN` spanning 0..124 with 4-step interpolation implies 32.

**34 is right.** The owner auditioned the cut bank and entries 32 and 33 are
both good transients. So the interpolation model's step count or mapping is
wrong, not the measurement — and the mapping from `TRAN`'s 125 positions onto 34
entries is still unknown.

## Adding a mod

Implement in `src/dnfw/mods/<id>.py`: `ID`, `NAME`, `SUMMARY`, `DEVICE`,
`SECTION`, `extents(firmware)`, and `apply(firmware, ...) -> Result`. Register it
in `src/dnfw/cli/mods.py`'s `REGISTRY`. Declare extents honestly — a mod that
under-declares breaks the only compatibility guarantee the system offers.

## The site

`site/index.html`, published to GitHub Pages by `.github/workflows/pages.yml`.

It lives in `site/` rather than `docs/` on purpose: `docs/` is the research
record, and Pages would turn ~40 files of measurements and retractions into
public pages. The site is a small front door that points back here for detail.

---

## The browser tool

**Status: the codec is built and proven; nothing else is.** `site/js/aplib.js`
exists and passes all four checks below. The container, transport, integrity and
UI layers are still only the plan under them.

**The requirement, from the owner: zero CLI, zero cloning.** A user opens a web
page, picks their own firmware file and their own samples, adjusts each one,
hears the result, and downloads a firmware image. Everything client-side —
GitHub Pages is static, and nothing should be uploaded anywhere, which is also
what `transientsplit` does and the right posture for someone's firmware.

### What the browser has to do

| step | difficulty | state |
|---|---|---|
| SysEx transport decode/encode (8-in-7) | easy | not started |
| ELE3 container parse and rebuild | moderate | not started |
| aPLib **depack** of section 7 | moderate — port of `codec/aplib.py` | **done** |
| aPLib **pack** of section 7 | was **the blocker** | **done**, store-only |
| content checksum + HMAC-SHA256 | easy, `SubtleCrypto` | not started |
| WAV decode, trim, preview | easy, Web Audio | not started |
| transient/tonal separation | **not ours** — link to `transientsplit` | n/a |

### The decision on packing: store-only

Only **section 7** is modified, so every other section keeps its original
stored bytes untouched — sections 2, 3 and 8 never need repacking at all. That
reduces the problem to one section, and makes a literal-only encoder viable:

```
section 7:  602,076 stored  ->  836,956 unpacked  ->  941,583 store-only
```

Measured, and exactly 9/8 of the input plus the terminator, because every byte
costs one control bit and itself. The `.syx` grows from 2,389,280 to 2,819,488
bytes — 430,208 more, larger than the 339,507 the section gained because the
SysEx transport carries seven bits per byte.

The image grows by roughly 340 KB. `docs/ideas-backlog.md` §1 cares about space
*inside* section 3's address range, which this does not touch, so the cost is
file size and flash, not addressable room.

**Rejected for now:** porting the cost-optimal DP packer from `codec/aplibpack.py`.
`docs/ROADMAP.md` is right that a greedy packer is the wrong choice when the
goal is byte-exact reproduction of Elektron's own output — but that is not the
goal here. The goal is a stream the device's depacker accepts, and a store-only
stream is the easiest kind to be sure of. The cost-optimal port stays available
if size ever matters.

digikit took the same route (`dt2/aplib.py`, "store-only packer for the device's
aPLib variant"), which is weak corroboration that the device tolerates it —
weak because their note also says the rebuilt image is about 3x original size,
and nothing says it was flashed.

### How it was verified, which is the part that matters

A second implementation of a format that writes firmware people flash is a real
correctness risk, so it does not get trusted because it looks right. These four
checks were written down **before any of the code existed**, and all four now
run in `test/test_js_codec.py` against real firmware — `scripts/js_codec_check.mjs`
is the JS half.

| # | check | result |
|---|---|---|
| 1 | **Depack agreement** — JS depack of every compressed section == Python's | **pass**, byte for byte, all sections of DN2 1.10E |
| 2 | **Self round-trip** — JS depack of JS `packStore` output == input | **pass** |
| 3 | **Cross-check** — JS `packStore` output depacked by `codec/aplib.py` | **pass**, 836,956 bytes identical |
| 4 | **Whole-image rebuild** — section 7 store-only, container reassembled | **pass, 21/21 integrity checks** |

Check 3 is the one that matters: two implementations sharing no lineage, read in
both directions, and neither consulted while the other ran. Check 4 is not a
codec check at all — it asks whether the *container* still adds up when a
section changes length, which is the assumption the whole store-only decision
rests on, and it had never been tested. It does, and the trailer and content
checksum re-sign correctly over the larger image.

A fifth property falls out for free and is asserted anyway: a store-only stream
contains **no matches**, so it cannot violate either bound in `codec.limits` —
there is nothing to violate them with. Those limits are why images of ours once
stalled in recovery (`docs/flashing.md`), so the safest possible stream on that
axis is the one this emits.

**What none of this proves: that the device accepts it.** Every check above is
offline. A larger section 7 has never been flashed, and the recovery bootloader
may have a partition size or a layout expectation that nothing here models. That
is the next hardware test, and it is a real risk — not a formality.
