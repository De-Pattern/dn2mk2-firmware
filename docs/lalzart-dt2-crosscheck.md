# A third independent reading: `lalzart/digitakt-ii-firmware-research-public`

**2026-09-16.** `https://github.com/lalzart/digitakt-ii-firmware-research-public`
— *"Sanitized documentation of independent Digitakt II OS 1.15C firmware
architecture research"*. Created 2026-08-10, last pushed 2026-08-16, 45 KB,
documentation only. Twelve Markdown files, no code, no firmware bytes.

This is the **third** independent account of this hardware we now have, after
ours and `m-dwyer/digikit`. It is the most valuable kind: it worked the
**Digitakt II 1.15C** from a different direction — an offline simulator with
formal, hash-bound controls — and it reaches into the SHARC further than either
of the other two.

## Licence: CC0 1.0 since 2026-09-15 — the restriction is lifted

**Updated 2026-09-16.** This section previously read *"read, cite, do not
copy"*, on the strength of a `NOTICE.md` that granted no licence. **That is no
longer true.**

Commit `b2f93c1`, **"License research under CC0 1.0"** (2026-09-15), added a
`LICENSE` file and revised `NOTICE.md`, which now reads:

> *"To the extent the contributors own the necessary rights, the original
> contents of this repository are dedicated to the public domain under CC0 1.0
> Universal."*

**So we may now quote it directly, copy its text, and vendor its files.** The
earlier constraint — cite only in our own words, never copy, never vendor, same
footing as `ems-octakit` — is **withdrawn**.

Two things that do *not* change:

- **The carve-out.** CC0 covers only what the contributors can grant rights in.
  Their own `NOTICE.md` is explicit that it does not grant rights in Elektron
  firmware, vendor code, third-party works, patents, product names or
  trademarks. Their prose is free; Elektron's bytes are not, and this
  repository's no-firmware rule is untouched.
- **We keep attributing them anyway.** CC0 does not require it, but this project
  names whose reading a claim came from so that a merged claim can be re-checked
  later. Attribution here is a working practice, not a licence obligation.

**`ems-octakit` is unaffected** and remains unlicensed and inspiration-only.
Do not generalise this change to it (`docs/references.md`).

Everything already written in this document was composed from scratch under the
old constraint. It stays as it is — it is accurate — but future work may quote
them directly where a quotation is clearer than a paraphrase.

## What it settles that we had open

### The SHARC Audio Task's structure

Our canvas carried this as **open**, and `docs/engine-index-map.md` had it as a
shared blocker with digikit — *"entry pointer unresolved"*. They have the chain:
FreeRTOS startup → Audio Task creation → notification wait → a recurring root
→ a main processor routine → per-unit/lane traversal → common processing →
output copy → return. A status word gates it: zero returns, bit 0 does
housekeeping, bit 1 enters processing.

They name a **six-entry selector table** for the machine roles, with a public
identity → selector role mapping that is **not** one-to-one (seven identities
onto six roles, with two identities sharing role 0). Slice arrives in the
1.10A→1.15 boundary as a new role, and its helper shares a large block of
instructions with Grid's — bounded shared ancestry rather than a separate
algorithm.

All addresses are SHARC **short-word** addresses in the `0x001cxxxx` space,
which is the same coordinate system digikit uses (`docs/sharc-code-map.md`,
`load = exec × 2 + 0x28000000`). So the three accounts are directly comparable
without conversion.

### The DSP's actual work

They classify individual DSP routines rather than the program shape: a bounded
phase-indexed interpolation/resampling reader, a six-vector coefficient-
scheduled multiply-add, a block-to-block scalar gain smoother, and a group of
routines whose tested behaviour clips `±2.0` to `±1.0`. They are careful to say
these are classifications under controlled screens, not public algorithm
identities.

**Relevant to LFO4, negatively and usefully:** none of it is a modulator. The
six selector roles are **machine types**, and the DSP work they characterise is
voice/sample DSP. That is consistent with our finding that modulation is
generated and applied on the ColdFire (`docs/engine-state.md`) — though as an
absence in someone else's survey it is corroboration, not proof (Principle 19).

## What it corrects in our own account

**The frame is full-duplex with one padded size, not two lengths.** We had
described `0x400cf7be`'s arguments as `(tx_len, tx_buf, rx_len, rx_buf)` and
observed that the second length is `0xabc` on both instruments while the first
differs. Their reading is better: the **frame** is a padded `0xabc` = 2,748
bytes, full-duplex, and the **payload** inside it is device-specific — `0x802`
= 2,050 on the DT2, against the `0xa80` = 2,688 we measured on the DN2.

That explains the pattern we reported rather than contradicting it, and it is
the more useful statement. Corrected in `docs/sharc-image.md`.

**The follow-up this paragraph said was owed to digikit PR #12 is already
settled, upstream, and not by us** — checked 2026-09-22 against
`origin/main`. `docs/FINDINGS.md` carries the corrected reading in full: one
variable written once at boot returns `0xabc`, both eDMA descriptors take their
word count from it, the first argument is the payload word count (`0x802` on
DT2, `0xa80` on DN2) and the rest of the frame is tag-only, and the frame
offsets are unaffected because payload words map one to one onto frame data
words. It is attributed to us and cross-checked there against `FUN_400cd2bc` on
1.16. So there is nothing left to send, and this note exists to stop the debt
being paid twice.

They add the direction of digikit's eDMA channels — **29 transmits** through
`DSPI2_SOUT`, **28 receives** through `DSPI2_SIN` — and the physical contract:
CTAR0, SPI mode 1, **16-bit MSB-first**, active-low PCS0, one continuous
`0x55e`-word window. `0x55e` = 1,374 words = **2,748 bytes**, which closes the
frame size independently. The recurring publication is a **level-5 interrupt,
software-forced from a level-6 eDMA-completion path**.

**Sixteen per-track unit records**, `0x60` = 96 bytes each on the DT2. We
measured **146** bytes per track on the DN2 — a bigger per-track record for the
FM machines, which is what one would expect, and an independent confirmation
that the per-track block structure we read is real.

## What it adds that is new to us

- **A minimum-version check in the update path.** They record MAIN validating
  checksum, minimum-version *and* the cryptographic trailer before erase and
  program. We have the checksum and the HMAC trailer in `docs/ele3-format.md`;
  **a minimum-version gate is not recorded anywhere in this repository**, and it
  would matter to anyone flashing a modified or downgraded image. Worth
  checking on the DN2.
- **`0x80000` is a nonvolatile offset — a third confirmation.** They describe
  the staged ELE3 slot as beginning at nonvolatile offset `0x80000`, which is
  exactly what digikit's boot trace showed and what closed our own open gate
  (`docs/ideas-backlog.md` §6). Three independent readings now agree.
- **DT2 1.15C: a 1,708,064-byte SysEx carrying a 1,347,728-byte container with
  five sections.** Our DN2 1.11 has six. Section 3 expands to 3,177,312 bytes
  against our 3,192,192; section 4 is 32,776 bytes, the same as ours.
- **Their view of SHARC slack is bleak and worth heeding.** Seven represented
  gaps totalling 4,855,924 bytes, and their verdict is that **zero bytes are
  proved reusable** — stack, heap, aliases, DMA-time ownership and layout
  constraints do not jointly close. Anyone tempted to treat the SHARC image as
  having free space should read that first.
- **Two SHARC modifications proved offline**, in a simulator: a size-preserving
  selector reroute, and a same-width sign transform on a selected bank, the
  second reusing 24 existing instruction bytes and changing 3. Notably they also
  record a *rejected* fixture placement and the repair — the same habit of
  keeping the wrong turn visible that this repository tries to keep.
- **Overbridge is in scope for them**, with a Digitakt II-specific 80-byte
  inbound decoder identified in 2.25.7 and a host shared-memory path in 2.21.3.
  We have not looked at Overbridge at all.

## Their stance, which is not ours and should not be mistaken for it

Their `modification-gates.md` states plainly that nothing in their work
authorises flashing, signing, transmitting, installing, or communicating with
hardware, and their gate table marks hardware execution **absent** and
deployment **unproved**. Everything they have is offline and simulator-bounded.

That is a different project posture from this one — we flash, and we have a
proven recovery path (`docs/flashing.md`). Their caution is not a constraint on
us, but their *gates* are a good checklist: re-encoding a modified section,
whole-container compatibility, and recovery selection after reset are all things
they mark unproved and we should not assume either. In particular their note
that **the updater instance selected after reset is not proved to be the one in
the rewritten slot** is a sharper statement of a risk our own recovery
documentation treats loosely.

## What to do with it

1. **Check the minimum-version gate on the DN2** — it is the one actionable
   difference, and it is cheap.
2. **Point digikit at it.** Her `machine-engine-link` branch is mapping the DSP
   program in Ghidra right now and lists the Audio Task's structure as open;
   this is the same address space and goes further. **Under CC0 we may now send
   her their text directly**, not only the pointer — though the pointer remains
   the better courtesy.
3. **Do not treat the SHARC image as having slack** until their gap analysis is
   contradicted rather than ignored.
