# Architecture principles

**Binding on every change.** A change that cannot follow one of these says so
and explains why; silently breaking one is not an option.

The first eleven are inherited wholesale from `DNX/docs/PRINCIPLES.md` and are
not repeated here — read that file, it is the same author's hard-won list and
it governs this repository too. The short form:

1. One job per module — nameable in a sentence with no "and" in it.
2. Anything a second caller needs moves up.
3. The layering goes one way.
4. Reuse means the shared thing, not a copy of it.
5. Anything reused says what it assumes.
6. A default that gets smarter needs a caller sweep.
7. Verify through the surface the user touches.
8. Never invent data.
9. Report volume is a design decision.
10. Vocabulary follows the hardware.
11. Documentation is written for the people who come after.

What follows is what this repository adds, because firmware is not a file
format — it is the thing an instrument boots.

## 12. Nothing is flashed that the toolchain cannot verify end to end

Every integrity field present in the original must verify in the rebuild before
the file is written, let alone sent. `dnfw build` and `dnfw patch apply`
re-load and re-verify their own output and refuse to write if anything fails.
That check is not a convenience and is not to be bypassed for a quick test.

A field that is absent is reported as absent, never as passing —
`firmware.verify` says "unsigned image, no digest to check" rather than a tick.

## 13. A recovery path is proven before it is needed

Before any modified image goes near the instrument, the Early Start-up Menu
route is exercised by reflashing **stock** firmware through it. A recovery path
that has never been used is a belief, not a path. See `docs/flashing.md`.

## 14. How a section is stored is read from the image, never assumed

On both Digitones some sections are aPLib streams and some are stored raw, and
which is which differs between the two devices. The only reliable test is
whether the bytes depack. `firmware.build.replacement` therefore takes that
decision from the original section rather than from an argument.

Compressing a raw section — or storing a compressed one raw — produces a file
that passes every checksum and bricks the instrument. There is no feedback from
the device between those two facts.

## 15. Ported code says where it came from and where it diverges

Three MIT repositories did most of this work already. Every module that ports
from one names it in the header, and — more importantly — names the places it
does something *different*, with the reason.

`codec/aplibpack.py` is the example to follow: it says the parse strategy is
not the C's, why Python cannot run the C's, and what that costs measured
against the sections Elektron ship.

## 16. C that relies on unsigned wraparound is a porting hazard

Two bugs during the port, both the same shape: the C computes something in a
`uint32_t` and depends on it wrapping.

- The end-of-stream token is a gamma of `0x1000002` and a `0xFF` byte, which
  only equals the offset bias after the high bits fall off a 32-bit register.
- A raw offset below the bias becomes a huge unsigned value in C and is caught
  by a range test. In Python it stays negative, passes the test, and indexes
  off the end of the output.

Both are regression tests in `test/test_aplib.py`. When porting the next piece
of C, look for arithmetic whose correctness depends on the register width.

## 17. Everything is reachable from the CLI

One entry point, `dnfw`, with one file per subcommand under `cli/`. A
subcommand does argument handling and I/O; the work lives in the library module
it calls. **A capability with no subcommand is not finished** — it cannot be
used by hand, which means it cannot be checked by hand.

## 18. The canvas is updated with the work, not after it

`docs/STATUS.md` is the project canvas: every feature, every research item
open / closed / retracted, the idea list and the request queue, each linked to
the document that holds the evidence. The Obsidian baton
(`00_Notes/AS/ZZ_Personal Projects/03_dn2_firmware/Next_Session.md`) points at
it and carries the short version.

**A finding that is not in the canvas does not exist**, and a canvas that has
drifted is worse than none — it is a confident wrong answer to "where are we?".
So updating it is part of the change, in the same commit, not a tidy-up
afterwards. Specifically:

- A result **closes** a research item only with a named measurement and a
  document. Move the row, do not just add prose somewhere.
- A retraction **stays visible**, struck, with a pointer to what replaced it.
  Never delete a superseded conclusion; a closed path is still a signal.
- Anything a peer or the owner asks for goes in the **queue** the moment it is
  asked, even when it will not be done — parked work that is not written down
  is lost work.
- Never record the same result in two places that can disagree. One of them
  wins; say which.

This principle exists because of a specific failure. On 2026-09-15
`docs/flashing.md` carried one build twice with opposite verdicts, and the
assistant read the lower row, took position in a table for recency, and told the
owner that LFO4's engine side was closed when it was unknown. Documentation
drift is not untidiness; it produces confidently wrong answers.

## 19. A negative is only as good as the instrument that produced it

Every expensive wrong answer this project has produced has been a **negative**,
and every one of them came from an instrument that could not have found the
thing it was looking for. Not one was a bad inference from good data.

| The negative | What the instrument actually could not see |
|---|---|
| "There is no SHARC program in the update" | It searched for a raw 48-bit instruction stream. Section 7 is an ADI **boot stream**. |
| "No upload path in MAIN OS", hence the engine is unmodifiable | It searched the `0xec09xxxx` window. The channel is the **DSPI next door** at `0xec038000`. |
| "No reference to any SHARC landmark anywhere" | Landmarks were searched at load addresses; SHARC code addresses live in a **different space**. |
| "The PRM publishes no register encodings" | It read pages 308–425 of a **798-page** manual, then generalised. |
| "87.82% is 100% of what the figures contain" | It was blind to the **yellow** *unused* cell colour. |
| "220 accesses across 50 addresses" (2026-09-16) | The opcode mask matched only the **`d0` spelling** of each `move`, and missed the SHARC's boot data port. |

The shape is always the same: a search runs, finds nothing, and the *nothing*
is reported as a property of the firmware rather than a property of the search.
A negative reads as clean and final in a way a positive never does, which is
exactly why it gets less scrutiny than it needs.

So, before writing down that something is not there:

- **Validate the instrument on a known positive first.** If the scan cannot find
  a thing you already know is present, its zero means nothing. This is the whole
  check, and it is usually one line.
- **Say what the search covered**, in the same sentence as the result — which
  addresses, which pages, which encodings, which spellings. A negative without
  its scope is not a finding.
- **Prefer "not found by X" to "not present."** They are different claims and
  only one of them is supported.
- **Name the disproof.** `engine-index-map.md` §9 did this well and it is why
  the error was eventually caught: it said which observation would overturn it.
  Ranking its own branches wrongly cost months; naming the disproof saved it.

Positives get a matching caution from §15's retraction — a test that cannot
*distinguish* between two explanations has not confirmed either. Between the
two, this project's failures cluster heavily on the negative side.

## Applying these to a change

- Can each file you touched be described without an "and"?
- Does anything in `src/dnfw/` outside `cli/` touch the filesystem or argv?
- Did you port from a reference without saying so, or diverge without saying why?
- Did you add a capability without a subcommand?
- Did you run `dnfw` on a real image, not only the tests?
- Would the change let something unverified be written to disk?
- **Does `docs/STATUS.md` still describe reality after this change?**
- **Did this answer, park, or retract anything? Then a row moves.**
- **Did you write down a negative? Then say what the search covered, and show
  the instrument finding a known positive.**
