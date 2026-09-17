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

- **No section's *unpacked content* changes length.** Every address after a
  resized payload moves and nothing here fixes up the code that refers to them.
  A mod needing more room is a code-cave or new-section problem
  (`docs/ideas-backlog.md` §1a, §6).

  **Sharpened 2026-09-14.** This used to read "no section changes length",
  which is wrong in a way that only became visible once a section's *stored*
  length actually changed. The two lengths are different things. The **stored**
  length is the compressed bytes in the container, and the section table records
  where each section sits, so changing it moves nothing an address ever points
  at — `ele3.assemble` rewrites the offsets, and a rebuild re-signs over the
  result. The **unpacked** length is what lands at `dest`, and that is the one
  the code's addresses are relative to. The old wording forbade both.

  This matters beyond pedantry: every replacement of a compressed section
  changes its stored length a little, because compression depends on content.
  Reading the rule as forbidding that would rule out the whole mods system.

  **Sharpened again 2026-09-17, on hardware.** The unpacked length of MAIN OS
  *may* grow — **only by appending past its last byte**, into one shared area.
  Nothing addresses that space, so nothing moves; the boot hook that copies it
  above BSS is the only reader. `intro-bang_DN2_1.11.syx` did exactly that and
  booted on the instrument. The area is a directory of named chunks
  (`scripts/gen_bootscreen_code.py`), so several data-carrying mods can share one
  copy hook instead of each appending their own; merging chunks from two mods is
  the next piece of the compatibility system, and until it exists a mod that
  appends refuses an image that already has an area.
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

**A real check is filed as `docs/ideas-backlog.md` §11**, to be built when two
mods first share a section or a processor. Until then the two that exist cannot
collide — `moddest` writes ColdFire data in section 3, `transients` writes SHARC
data in section 7 — so the overlap test returns the right answer and would
return the right answer if it did nothing at all. That is worth knowing about a
check before trusting it.

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

### What the flashed image actually differs by

Measured 2026-09-14 by rebuilding the marker image and diffing it against stock
1.11, on unpacked content:

| id | name | unpacked | result |
|---|---|---|---|
| 5 | meta | 15 | identical |
| 2 | bootstrap | 30,302 | identical |
| 3 | MAIN OS | 3,192,192 | **identical** |
| 4 | updater | 32,768 | identical |
| 7 | blob (SHARC) | 836,956 | 47,529 bytes differ, offsets 497,108..823,506 |
| 8 | ? | 159,948 | identical |

The bank runs from section-7 offset 497,108 to 823,508, so the diff stops two
bytes inside its end: **the mod wrote nothing outside the bank.** 47,529 bytes
is right for five replaced entries of 34 — 5 × 9,600 = 48,000 less the bytes
that coincide, mostly zeros.

This was measured to answer a question from the `DNX` session, which read all
16 patterns of bank A as **storage version 4** over the dump protocol while
+Drive project files from the same OS decode as version 3, and could not tell
whether that was 1.11 or our build. It is not ours: every storage-format
decision lives in MAIN OS, and MAIN OS is byte-identical. One hypothesis
eliminated by measurement rather than by argument.

Worth keeping for its own sake too: it is the evidence that **a mod's declared
extents match what it actually writes.** `extents()` is the whole basis of mod
compatibility, and until this it was a promise the code made about itself.

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

## Mod 3: `bootscreen`

The start-up animation: a user-supplied 128×64 mark written into the intro's
source bitmap every frame, static or flashing, and the tunnel's texture scale.
All choices are data in a `BOOT` chunk of the appended area; the 200 bytes of
code are assembled once into `src/dnfw/mods/bootscreen_code.json` and shared with
the site. `src/dnfw/mods/bootscreen.py` carries the evidence.

    dnfw mods apply <image> --mod bootscreen --boot-image mark.pgm --boot-invert         --boot-slow 4 --boot-fast 3 --boot-rush 48 --boot-stop 72 --tunnel 128 64 -o out.syx

Built through this command, it behaves identically to the hand-built
`intro-bang` that passed on hardware: filmed under the emulator from the same
snapshot, every frame whose intro frame number matches is byte-identical — the
only differences are slices that land on a different frame, because the
directory lookup spends a few more instructions per frame.

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

**Status: built, and live at `site/transients.html`.** The page loads a real
`.syx`, derives its signing key, depacks and repacks section 7, replaces any of
the 34 transients with the user's own audio, reassembles the container,
re-signs, re-verifies, and offers the result for download — and the image it
produces is **byte-identical to the one the Python tool builds**, and 4,608
bytes **smaller** than stock 1.11.

What remains untested is the page's *layout* — the logic behind it is checked
against real firmware in `test/test_js_{codec,firmware,mod}.py`, but nobody has
looked at it in a browser yet.

**The requirement, from the owner: zero CLI, zero cloning.** A user opens a web
page, picks their own firmware file and their own samples, adjusts each one,
hears the result, and downloads a firmware image. Everything client-side —
GitHub Pages is static, and nothing should be uploaded anywhere, which is also
what `transientsplit` does and the right posture for someone's firmware.

### What the browser has to do

| step | difficulty | state |
|---|---|---|
| SysEx transport decode/encode (8-in-7) | easy | **done** — `syx/` |
| ELE3 container parse and rebuild | moderate | **done** — `container/` |
| aPLib **depack** of section 7 | moderate — port of `codec/aplib.py` | **done** |
| aPLib **pack** of section 7 | was **the blocker** | **done** — full parse port, plus a store-only fallback |
| content checksum + HMAC-SHA256 | easy, `SubtleCrypto` | **done** — `integrity/` |
| the transients mod itself | moderate — bank offset through the boot stream | **done** — `mods/transients.js`, `bootstream.js` |
| audio decode, fit, preview | easy, Web Audio | **done** — `audio.js` |
| the UI | — | **done** — `transients.html`, not yet seen in a browser |
| transient/tonal separation | **not ours** — link to `transientsplit` | n/a |

`site/js/` mirrors `src/dnfw/`'s module layout deliberately — `syx/`,
`container/`, `integrity/`, `mods/`, `aplib.js` and `aplibpack.js` split the
same way the Python is, and one `firmware.js` for the order they go in. Two
implementations that drift are a liability; two that sit side by side with the
same names make the drift visible.

### The decision on packing: store-only first, then the real packer

**[SUPERSEDED 2026-09-14 — store-only shipped, then was replaced. Kept because
the reasoning that led to it was sound and the failure was in what it left
unmeasured.]**

The original decision was a literal-only encoder. Only section 7 is modified,
so sections 2, 3 and 8 keep their original stored bytes and never need
repacking; that reduces the problem to one section, and a store-only stream is
the easiest kind of aPLib stream to be sure of — one token type and the
terminator, no offsets, no lengths, no reuse state. Porting the real packer was
called "the blocker" and routed around.

It worked, and it cost this:

```
section 7:  602,076 stored  ->  836,956 unpacked  ->  941,583 store-only
.syx:     2,389,280  ->  2,819,488   (+430,208)
```

**What was wrong with it was not the size. It was that the size was never
compared against anything.** 340 KB was written down as a cost and filed as
acceptable, next to a note that the device had never been given a larger
section 7. Those two facts belonged together and were not put together.

The owner put them together: the transient entries are fixed-size slots
replaced in place, so why does anything grow? It doesn't. The **unpacked**
section is 836,956 bytes whatever you put in it. Only the compressed size
moves, and only because compression finds redundancy and how much is there
depends on the audio. Measured on 1.11 section 7:

| content | stored | `.syx` | vs stock |
|---|---|---|---|
| stock | 602,076 | 2,389,280 | — |
| **markers — the image flashed 2026-09-14** | 564,196 | 2,341,280 | **−48,000** |
| 34 realistic decaying drum hits | 576,364 | 2,356,640 | **−32,640** |
| 34 slots of white noise (worst case) | 653,852 | 2,454,816 | +65,536 |
| store-only | 941,583 | 2,819,488 | **+430,208** |

So the real packer stays within ±64 KB and is *smaller* for anything musical —
and **the image confirmed on hardware was 48,000 bytes smaller than stock.** It
never tested a larger image because it never was one. Store-only bought a day
of work and paid for it with an untested hardware condition on the one path a
user would actually take.

**`site/js/aplibpack.js` is now a full port** of `codec/aplibpack.py`'s parse —
greedy with one-position lazy lookahead over a 2-byte hash chain, decided by
`compress.c`'s cost model, bounded by `codec.limits`. Measured on DN2 1.11:

| section | raw | JS packed | Elektron | vs stock | JS time | Python time |
|---|---|---|---|---|---|---|
| 2 bootstrap | 30,302 | 16,138 | 16,166 | −28 | 9 ms | 0.2 s |
| 3 MAIN OS | 3,192,192 | 1,129,103 | 1,130,517 | −1,414 | 629 ms | 25.9 s |
| 7 blob | 836,956 | 598,410 | 602,067 | −3,657 | 177 ms | 8.8 s |
| 8 | 159,948 | 102,552 | 103,407 | −855 | 27 ms | 1.2 s |

Every section comes out smaller than Elektron's own, and a full browser rebuild
of 1.11 is **2,384,672 bytes — 4,608 smaller than stock.** The size risk is
gone rather than documented.

**`packStore` is kept** as the fallback whose correctness can be argued in a
sentence, and as the control `pack` is measured against. It is not dead code:
`test_js_codec.py` asserts it still emits no matches, because that is what
makes it the simple thing.

The lesson is not "store-only was a bad idea". It was a reasonable first move.
The failure was writing down a number that differed from every image the device
had ever accepted, and not asking what that difference cost.

### How it was verified, which is the part that matters

A second implementation of a format that writes firmware people flash is a real
correctness risk, so it does not get trusted because it looks right. These
checks were written down **before any of the code existed**, and all now run in
`test/test_js_codec.py` against real firmware — `scripts/js_codec_check.mjs` is
the JS half.

| # | check | result |
|---|---|---|
| 1 | **Depack agreement** — JS depack of every compressed section == Python's | **pass**, byte for byte |
| 2 | **Self round-trip** — JS depack of JS `pack` and `packStore` output == input | **pass** |
| 3 | **Cross-check** — JS output depacked by `codec/aplib.py` | **pass**, 836,956 bytes identical |
| 4 | **Whole-image rebuild** — section 7 repacked, container reassembled | **pass, 21/21 integrity checks** |
| 5 | **Packer agreement** — JS `pack` output == Python `pack` output | **pass**, byte-identical on all four compressed sections |
| 6 | **Size** — every section at or under Elektron's own stored length | **pass**, all four smaller |
| 7 | **Limits** — no offset past `PACK_MAX_OFFSET`, no match over `MAX_MATCH` | **pass** |

**Check 5 is the sharpest thing in this file.** A packer has enormous freedom —
any parse that round-trips is correct — so "it round-trips" leaves most of the
implementation untested. Demanding the *same bytes* as `codec/aplibpack.py`
pins the cost model, the tie-breaking between equally long matches, the
lazy-lookahead arithmetic, the offset window, the chain depth, and the exact
point in the loop where the hash chain is updated. Any one of those differing
shows up immediately.

That is only a fair demand because the JS packer is a deliberate port of that
parse. Where the two implementations are meant to be *independent* — the
depacker, the container, the transport — the standard is agreement on content,
not on bytes, and checks 1, 3 and 4 are written that way.

Check 4 is not a codec check at all: it asks whether the container still adds
up when a section changes stored length. It does, and the trailer and content
checksum re-sign correctly over the result.

Check 7 is the one that matters for the device rather than for correctness. A
stream can checksum perfectly and still reach further back or copy longer than
anything Elektron ship, and images of ours that did exactly that **stalled in
the Early Start-up Menu's recovery flash**. It is the failure this project has
actually hit, so it is asserted rather than reasoned about.

### The stack above the codec, and its two harder checks

`test/test_js_firmware.py`, over the whole pipeline:

| check | result |
|---|---|
| **Round-trip** — load a real image, build it straight back, nothing replaced | **byte-identical** |
| Signing key recovered from the image's own material | **pass**, derived from `"Multiplier"` |
| Every integrity field on the original | **9/9** |
| Repacked rebuild reloads, re-verifies, section content unchanged | **9/9** |
| **JS-built image vs Python-built image, same input** | **byte-identical** |
| Full browser rebuild of 1.11 | **2,384,672 bytes — 4,608 smaller than stock** |

The round-trip is `docs/ROADMAP.md`'s **Gate A in JavaScript**: one comparison
exercises SysEx framing, 8-in-7, per-packet checksums, marker counters, the
container layout, the content checksum and the HMAC trailer at once, and any one
of them being wrong shows up as a differing byte.

The last row is the one that would catch a shared *assumption* rather than a
coding slip — the failure mode where both implementations are wrong in the same
direction, which no amount of self-checking can find.

**The key never leaves the browser, and is never stored.** It is derived from
the user's own firmware file in their own tab, the way `integrity/keyderive.py`
does it, and a candidate is only accepted when it reproduces that image's own
trailer — so a wrong guess cannot pass as the right one.

**What none of this proves: that the device accepts an image this toolchain
built.** Every check above is offline.

The size question that was open here is **closed**: the browser now emits an
image 4,608 bytes smaller than stock, and every section packs smaller than
Elektron's own, so nothing about these images is larger than what the device
already accepts. The store-only route would have put a 340 KB-larger image in
front of a recovery bootloader, and that risk is gone rather than documented.

What is still untested is narrower and honest: **no image built by the
JavaScript path has been flashed.** The Python path has been, repeatedly, and
the two produce byte-identical output on every input tried — which is strong,
but it is an inference, not a flash. The first hardware run of a
browser-produced image should be treated as a first run.
