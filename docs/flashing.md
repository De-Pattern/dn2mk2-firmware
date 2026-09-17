# Flashing, and getting back

**Step 1 is done: the way back is proven.** The rest of the procedure was
written before it was needed, which is the point of it. Results are recorded
here as they happen, with dates.

## The order, and why it is this order

Each step fails differently from the one before it. Run them in order and a
failure tells you which part is wrong.

### 0. Back up the +Drive — before anything

Use DNX's `.dnx` backup. Firmware and user data are separate, and a firmware
flash should not touch projects — but "should not" is not a backup.

### 1. Prove the way back, with stock firmware — DONE 2026-09-08

**This gated every other hardware step, and it passed.** Stock
`Digitone_II_OS1.10E.syx` was sent to a Digitone II through the Early Start-up
Menu; the transfer reached 100%, the device rebooted, and it came up normally.

The route, as actually used:

1. Hold **`FUNC`** while powering the instrument on to reach the **Early
   Start-up Menu**, then press **`TRIG 4`** to select **OS UPGRADE**.
2. Connect the computer's MIDI **OUT** to the device's MIDI **IN** with a DIN
   cable. **USB MIDI does not work for this** — Elektron's own transfer tool
   says so, and the bootloader only listens on the DIN port.
3. Send the `.syx` with Elektron Transfer's **SysEx Transfer** window, which
   shows "Recovery mode" and a percentage.
4. The device shows `RECEIVING...` with a progress bar while it runs.

Interface used: a Focusrite USB MIDI interface.

**It is slow, and that is arithmetic rather than a fault.** MIDI DIN runs at
31,250 baud, ten bits to the byte, so 3,125 bytes per second. The 2,209,184-byte
image therefore cannot take less than **about 12 minutes**, and will take
somewhat longer. That figure is derived, not measured — the actual duration was
not timed. Do not interrupt it.

**Why this matters more than it looks.** This route lives in the bootloader,
not in MAIN OS, so it still works when a MAIN OS we built does not. It is the
reason anything modified can be flashed at all.

### 2. Gate D — a rebuild that changes nothing

```
dnfw build 00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip -o gate-d.syx
```

Byte-identical to stock, so this proves nothing on its own. Instead extract and
rebuild MAIN OS so the compressed bytes differ while the code does not:

```
dnfw extract <image> --section 3 -o out/
dnfw build <image> -s 3=out/section_3_MAIN_OS.aplib.bin -o gate-d.syx
```

Same code, different stream, valid checksums, valid HMAC. **If it boots, the
repack-and-sign pipeline is accepted by the device.** If it does not, the fault
is in packing or signing — nothing else changed.

### 3. Gate E — a patch you can see

```
dnfw patch apply 00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip -o gate-e.syx
```

Renames `SETTINGS > PERSONALIZE` to `DNFW ALIVE!`. Flash it, open SETTINGS,
photograph the screen.

That closes Phase 1: unpack, modify, repack, re-sign, flash, observe, as a loop
that can be run again.

**Both passed, through the normal update path** — Transfer's drop over USB to
a running instrument, not the Early Start-up Menu. Gate D booted and behaved as
stock; Gate E booted and `SETTINGS` shows `DNFW ALIVE!`. Phase 1 is closed.

## Two routes, and they are not equally forgiving

| | Normal update | Recovery |
|---|---|---|
| how | Transfer, drag the `.syx` onto a running device over USB | Early Start-up Menu, `TRIG 4`, DIN MIDI |
| who receives | the running MAIN OS | the **bootstrap** — section 2 of the last OS flashed |
| works when MAIN OS is broken | no | **yes — the only route that does** |
| accepted Gates D and E | **yes** | **no — stalls at ~80%** |

The recovery route is the one that matters if a build ever fails to boot, so an
image that only the normal route accepts is not safe to experiment with.

## The recovery stall was the MIDI link, not the image — 2026-09-11

Reported and diagnosed the same day. Gates D and E through the Early Start-up
Menu stalled: Transfer reported 100% sent, the device's `RECEIVING...` bar stuck
at about 80% with no error text. **Then stock 1.10E, re-sent through the same
route, stalled too** — the image that flashed cleanly on 2026-09-08. That is the
result that settles it: the fault is the transfer, not anything we built.

The bootstrap disassembly says why a bad link looks exactly like this
(`docs/bootstrap.md`). Reception has **no error recovery**: a data packet whose
sequence number is unexpected, or whose checksum fails, sets the receive state
to 0 and the bar simply freezes — no error screen, no retransmit, one-way over
DIN MIDI at 31,250 baud. A single corrupted packet anywhere in ~1.7 MB stops the
bar where it happened to be. And the bytes reception checks are sequence
counters and per-packet checksums, which are **content-independent** — Gate A
shows our transport is byte-for-byte stock's — so nothing there can tell our
image from stock. Stock stalling proves the mechanism is the link.

**What to do about it — and what it turned out to be.** Treat recovery as needing
a clean MIDI path: prove the link with **stock** first, and only once stock
completes is a modified image worth sending. On 2026-09-11 the specific cause was
found — the sends were going through a **Focusrite Scarlett 4i4**'s MIDI, and the
interface was going idle part-way through the twelve-minute transfer, dropping
packets (which is why it stalled at a different percentage each time). Stock 1.11
then flashed through recovery cleanly over a fixed link and the device booted it.
For a long recovery transfer, prefer a dedicated class-compliant USB-MIDI cable,
or stop the interface idling (Windows USB selective suspend off, the device's
power-management off). Until the link is proven, do not flash anything through
recovery that the device cannot already boot without.

**The padding and window fixes still matter, for a different reason.** They are
not about recovery *completing* — Phase 2 of the flash copies the container to
flash verbatim and never decompresses (`docs/bootstrap.md`). They are about the
next **boot**, when the freshly written OS is decompressed from flash. An
unpadded or over-reaching section could fail there. So `gate-d2`
(`0x716ce858`) remains the image to flash, once the link is proven — the fix is
correct, it was simply aimed at the wrong stage of the story at first.

## Standing rules

- **Verify before sending.** `dnfw inspect` on the file you are about to flash.
  `build` and `patch apply` already refuse to write anything that does not
  verify, but the file that reaches the instrument is the one to check.
- **One change at a time.** Gate D and Gate E are separate flashes on purpose.
- **Keep stock to hand.** The unmodified `.syx` is the recovery image; it stays
  in `00_Resources/00_Firmware/` and is never overwritten by a build output.
- **Do not patch the key material.** See `docs/ele3-format.md` §5.

## Record

| Date | Step | Result |
|---|---|---|
| 2026-09-08 | Recovery path, stock 1.10E via Early Start-up Menu | **Pass.** Transfer reached 100%, device rebooted, came up normally. |
| 2026-09-11 (reported) | Gate D — recompressed, unchanged, **normal update** | **Pass.** Boots, behaves as stock. |
| 2026-09-11 (reported) | Gate E — the PERSONALIZE patch, **normal update** | **Pass.** `SETTINGS` shows `DNFW ALIVE!`. |
| 2026-09-11 (reported) | Gates D and E through the **recovery** route | **Stall.** Transfer 100%, device bar ~80%, no error text. See above. |
| 2026-09-11 | **Stock 1.10E** re-sent through the **recovery** route | **Stall too**, ~80%. First sign the stall is the link, not the image. |
| 2026-09-11 | Recovery sends over a **Scarlett 4i4** MIDI interface | **Stall, varying %** (30/70/80). The interface was going idle mid-transfer, dropping packets. |
| 2026-09-11 | **Stock 1.11** through recovery over a **fixed link** | **Pass.** Reached 100%, rebooted, device boots 1.11. Recovery is sound; the culprit was the interface. |
| 2026-09-12 | **Mod-mask test** (`modmask-test_DN2_1.11.syx`) — two 4-byte writes opening Portamento Time and the AMP envelope Delay Time to modulation | **Pass, and the hypothesis confirmed.** `PORT Portamento Time` appears in MOD1's destination list **and is actually modulated**. First functional firmware modification. See `docs/modulation-mask.md`. |

This is the project's **first functional firmware modification** — Gate E changed
a string, this changed what the instrument can do.
| 2026-09-12 | **Expanded mod-destination test** (`moddest-expand_DN2_1.11.syx`) — 32 mask flips in three groups | **Pass, prediction confirmed.** All 13 Group A (per-voice) parameters appear as destinations; **none** of Group B (Chorus) or C (Master). The enumeration, not the mask, is the gate for global parameters. |
| 2026-09-12 | **LFO4 probe** (`lfo4-probe_DN2_1.11.syx`) — LFO3 re-pointed from engine lane 3 to the reserved lane 4 (engine indices 4, 8, 12, 16, 20, 24, 28, 32) | **RESULT WITHDRAWN 2026-09-12.** LFO3 still modulated, but the indices are **storage offsets**, not engine addressing, so a consistent forward/inverse round-trip predicts exactly this. The test could not distinguish it from an engine result. See `docs/engine-index-map.md` §15. |
| 2026-09-12 | **Coexistence probe** (`lfo4-probe-lfo2_DN2_1.11.syx`) — LFO2 re-pointed to the reserved lane, LFO1 and LFO3 left on lanes 1 and 3 | **RESULT WITHDRAWN 2026-09-12.** Same flaw as the probe above — only the storage round-trip was exercised. See `docs/engine-index-map.md` §15. |
| 2026-09-13 | **LFO4 shadow / canary / cave proof / inline proof** — four builds | **No observable change in any of them.** Each was investigated as a separate failure. All four shared one untested assumption: that the flashed image was running. |
| 2026-09-13 | **Flash control** (`flash-control_DN2_1.11.syx`) — the Gate E string `PERSONALIZE` → `DNFW ALIVE!` **plus** the inline getter edit, in one image | **Split result, and it settles two things.** `DNFW ALIVE!` **appears** → flashing works and our images run. `AMP VOL` still reads **110** → `parameter_value_getter` (`0x4006408a`) is **not the display path**, so `docs/version-anchors.md` is wrong about it. |
| 2026-09-13 | **Cave boot proof** (`cave-boot-proof_DN2_1.11.syx`) — a cave at `0x4028ea02` hooked into the boot path, overwriting the SETTINGS string in RAM | **Pass. CAVES EXECUTE.** `CAVE RAN!!!` shown, while the image itself still contains `PERSONALIZE` — so only the cave can have written it. **The project's first working code injection.** The cave mechanism, the assembler, the `jmp`+return hook form and the constants region are all sound. |
| 2026-09-12 | ~~**LFO4 shadow** (`lfo4-shadow_DN2_1.11.syx`)~~ | **[STALE ROW — WITHDRAWN, see `docs/engine-index-map.md` §15.]** It read *"Pass — our own code drives the engine's fourth LFO"*. §15 records the opposite: this build's results were **silent**, and that silence is what forced the check that overturned §§11 and 14. The row was never struck when the retraction landed. |
| 2026-09-12 | ~~**Coexistence probe** (`lfo4-probe-lfo2_DN2_1.11.syx`)~~ | **[STALE DUPLICATE — WITHDRAWN, see `docs/engine-index-map.md` §15.]** It read *"Pass. The engine side is now closed … four LFOs can run at once"* and cited §14, which is itself withdrawn. **The same build already appears above, correctly marked `RESULT WITHDRAWN`.** Both probes changed the forward *and* inverse maps together, so a consistent storage round-trip predicts the same positive with only three generators running — they never discriminated. |

> **Why these two rows are kept rather than deleted.** They contradicted the
> rows above them for three days, and on 2026-09-15 a reader (this project's
> own assistant) took the later position in the table for the newer result and
> reported to the owner that LFO4's engine side was **closed**. It is not; it is
> **unknown**. A log that states both verdicts for the same build is worse than
> one that states neither, and position in a table is not evidence of recency.
> `docs/engine-index-map.md` is authoritative for what the probes established.

| 2026-09-14 | **Transient markers** (`scripts/make_marker_transients.py`, base **1.11**) — five of the 34 FM drum transient entries in section 7 replaced with synthetic markers: entry 0 a 220 Hz square, 8 an 880 Hz tone, 16 a 3520 Hz tone, 25 flat noise, 33 silence | **Pass. Every marker played back from `TRAN`.** First change to the **SHARC** image rather than the ColdFire one, and the project's first user-facing mod. See `docs/pcm-hunt.md` §16. |

**This row was missing until 2026-09-14.** Every other hardware result was
logged here the day it happened; this one was written up in `docs/pcm-hunt.md`
and `docs/mods.md` and never reached the log, so for a day this file said the
last thing flashed was the cave boot proof. It surfaced when the `DNX` session
asked which image was on the instrument and the answer had to come from a
script's default argument instead of from here.

**What is on the DN2 right now is not recorded anywhere**, and cannot be — this
log records what was *sent*, not what is *resident*, and nothing writes a row
when the owner reflashes stock. Treat the last row as the last known flash, not
as the current state. The instrument answers the question directly: sweep `TRAN`
on an FM drum track, and a 3520 Hz beep or a silent slot means a marker build is
still on.

| 2026-09-15 | **Page renumber probe** (`page-renumber-test_DN2_1.11.syx`, base **1.11**) — the 22 parameter records on page `0x1d` (ten unlabelled TRIG, four `Retrig`, eight `Euclidean`) moved to page `0x1f`. **22 bytes, all `0x1d`→`0x1f`, no code edited** | **Fail, and a clean, informative one.** It boots and the pages still *draw*, but every moved parameter reads **zero** rather than its record default, and **no edit reaches the sequencer** — recorded trigs are unaffected by anything on the TRIG pages. `NOTE` shows C0, `PROB` 0%, `LFO.T`/`FLT.T` off, `VFAD` −64 (its minimum), `RATE` blank; `RATE` displays a value once set but still does nothing. Untouched parameters on other pages (`PTIM` 40, `PORT` off) read their normal defaults, so the damage is exactly the 22 moved records. **The negative the renumbering plan rested on is refuted: the page id *is* named elsewhere** — see `docs/lfo4-feasibility.md`, "What the flash answered". |

| 2026-09-15 | **Page renumber probe v2** (`page-renumber-test2_DN2_1.11.syx`, base **1.11**) — v1's 22 records plus **one code byte**: `moveq #29` → `moveq #31` at `0x400dc71e`, `param_set_tables_build`'s exact-match routing arm | **Fail, and indistinguishable from v1.** Same wrong values, same dead edits. The routing byte changed nothing observable, which is itself the finding: **populating the `ParameterSet` table is not the binding that matters.** The owner also noticed what v1 had hidden — p-locking `PROB` produces **modulation unrelated to probability**. The owner adds that **any parameter move clears it**, which places the write in the runtime mirror only — `0x400daf44` restores marked parameters from their base values. `VEL` *reads* 112 (LFO1 `SPD`'s default); `PROB` *modulates* (LFO2 `DEST`). The moved records are reading and writing the **sound** value array at index `record+0x04`. |

| 2026-09-16 | **Page classifier probe v3** (`page-classifier-test3_DN2_1.11.syx`, base **1.11**) — v1's 22 records plus **three** code bytes, all `moveq #29` → `moveq #31`: `0x400dc71e` (`param_set_tables_build` routing, v2 had this), **`0x400dbfa0` (`TrigParameterSet`'s ownership predicate, vtable slot `+0x54`)** and **`0x4003774e`** (a page-`0x1d` special case guarding parameter ids 310/311) | **PASS — all six observations.** Owner, flashed same day: *"all works as expected in the new firmware"*. It boots; `[TRIG]` draws real defaults; trig parameters p-lock; `Retrig` works; `Euclidean` works; **and nothing on the TRIG page moves an LFO** — the v2 symptom is gone. **The page-renumbering route is proven end to end and page `0x1d` is free for LFO4.** What v1 and v2 were missing was the *classifier*, not the builder. See `docs/lfo4-build-plan.md` §5b–§5c. |

**Why v3 worked where v2 did not, in one line:** parameter ownership is decided
by a **virtual predicate at vtable slot `+0x54`**, not by the boot-time table, and
no scan for a switch on a page id can find it. The two bytes v2 lacked were found
by scanning for comparisons against 29 **anchored on the 49 sites that load the
parameter table** rather than on the constant itself — three hits, all real,
against hundreds of noise hits the naive scan returns.

| 2026-09-16 | **LFO4 navigation test v4** (`lfo4-nav-test4_DN2_1.11.syx`, base **1.11**) — the `LfoPageView` id vector relocated to `0x402cf52c` as `{4,5,6,6}`, its length `moveq #3`→`#4` at `0x40061558`, the pointer at `0x40061564`, and the LFO-index clamp `moveq #2`→`#3` at `0x4010dbc6`. **16 data bytes, one pointer, two immediates** | **PASS on all five observations, with one cosmetic defect.** Owner: *"each LFO does what it needs to do and LFO page 4 clones the values of Page 3."* It boots; `[MOD]` cycles **four** pages; page four shows LFO3's nine columns; **editing page four moves LFO3** — the positive control; LFO1–3 unaffected. **Defect: the LFO waveform graph is blank on page four.** So `[MOD]` navigation is solved — the view will serve a fourth page and its value path works — and the remaining gap is the waveform renderer, localised below. |

**The blank graph, and why it is a good failure.** The wave display is fetched
through `sp@(disp, lfo_index:l:4)` at `0x4010d984` and `0x4010d9a2` — a
**three-element array indexed by the LFO index**. With index 3 it reads past the
array, so the graph draws nothing. Nothing else on the page depends on it, which
is why every other observation passed.

It is also the cheapest possible confirmation that `docs/lfo4-build-plan.md`
§5e was right to list the ten `+0x90` sites as unread: this is one of them, and
it is the kind of consumer no bound-scan would have found, because there is no
bound — just an array that happens to be three long.

| 2026-09-16 | **Stock 1.11 reflashed by the owner** | Between the v5 flash and DNX's arp capture, the owner returned the instrument to **unmodified 1.11** so the capture would be stock evidence. **The DN2 is on stock as of this row.** |
| 2026-09-17 | **The bang intro** (`intro-bang_DN2_1.11.syx`, base **1.11**) — MAIN OS **grown by 2,056 bytes** appended past its last byte; the startup calls at `0x4000053e` hooked to copy that data above BSS before the clear; the intro copy routine at `0x400d3886` hooked to write one of two full 128×64 images over the intro's source bitmap each frame, chosen by the intro's frame counter | **PASS.** Owner: *"the device boots up perfectly and shows the animation"*. **This is the first hardware proof that Elektron's bootloader accepts a MAIN OS section larger than stock, and that appended bytes reach run time** — the route §1 and §6 of `docs/ideas-backlog.md` were blocked on, and the one every data-carrying mod now uses. Observed on hardware and not seen under emulation: **the stock static logo with the firmware versions is shown first**, and the animation follows. That first screen is drawn by something the emulator snapshots start after, and is not yet located. |
| 2026-09-17 | **A fourth LFO, engine only** (`lfo4-tick6a_DN2_1.11.syx`, base **1.11**) — both LFO evaluators (`0x40137726`, `0x401373dc`) told to run four LFOs; the three per-track state arrays relocated and grown from 1,920 to 2,560 bytes; LFO4's eight parameters hard-coded in the image (`DEST` Filter BASE, `DEP` `0x7ffe`, free-running). 26 asserted edits, seven stubs | **PASS (owner's report).** Owner: *"`lfo4-tick6a_DN2_1.11.syx` -> works."* **The first hardware answer to the project's engine question: told to run four LFOs, the firmware generates and applies the fourth** — the stride arithmetic, relocated state and fourth-slot parameter read all hold on the instrument, not only in disassembly. The report is one word, so what it does not yet cover is recorded rather than assumed: **confirmed by the owner on follow-up:** LFO1–3 unaffected (each checked independently) and the sweep present **on every track**. **DNX read the saved sound: PASS** — lane 4 (offsets 36…92) all `00 00`; `4c 00` (the hard-coded DEST) appears nowhere in the 359-byte object; LFO1–3 inside corpus ranges. One coincidence noted: LFO3 `DEP` = `7ffe`, equal to the hard-coded LFO4 depth, but LFO3's other seven fields differ from LFO4's, so it reads as a user setting, not a leak — **owner confirmed: LFO1–3 were set by hand and LFO3 depth was at maximum**. ~~Pending: the DNX check~~ that a saved sound still reads `00 00` in lane 4 of bytes 36–93 (this build saves nothing of LFO4, so a non-zero lane would be a stray write). The saved sound is `dn_sysex/00_Examples/02_DN2/LFO4_TICK.dn2pst`, sent to DNX to read. **The DN2 then moved to `arp-on-midi`** (next row when reported). |
| 2026-09-17 | **Arpeggiator on MIDI tracks, v1** (`arp-on-midi_DN2_1.11.syx`, base **1.11**) — one byte, `beq.s`→`bra.s` at `0x4005f9da` | **FAIL.** Owner: *"arpegiator menu doesn't open on the midi track with the firmware"*. Boots; nothing else reported broken. Cause, read afterwards: the edited branch tests the key event's **FUNC** bit, and a MIDI-mask test (`0x40031274`, kit `+10,260`) exits before it for MIDI tracks. Expected side effect not observed because not tried: [FUNC]+[ARP] on an audio track opens the menu instead of toggling. v2 `arp-on-midi2` removes the mask test instead; `docs/ideas-backlog.md` §10. |
| 2026-09-17 | **Three LFO waveforms, v1** (`lfo-waveshapes_DN2_1.11.syx`, base **1.11**) — `STP`/`PLS`/`NOI` generators, relocated 10-entry waveform tables, WAVE maximum 6→9 | **FAIL.** Owner: three new positions after `RND`, **named `ERR`**; they sound like `RND`; no audible noise on the last; the `[MOD]` glyph shows `RND`. The wrap-around count confirmed three positions exist. Cause, read afterwards: both evaluators clamp WAVE to 6 (`0x40137880`, `0x401374a8`), so the generators never ran; the value formatter `0x400e34ac` has its own `> 6 → ERR` bound and name table. Boots and runs otherwise. v2 `lfo-waveshapes2`; `docs/ideas-backlog.md` §8. |
| 2026-09-17 | **Arpeggiator on MIDI tracks, v2** (`arp-on-midi2_DN2_1.11.syx`, base **1.11**) — the MIDI-mask `bne.w` at `0x4005f9c2` → `nop; nop` | **PARTIAL.** Owner: *"The menu opens! yeha!"* — **the UI gate is confirmed**. But turning a knob on that menu **drops back to the TRIG page and edits the matching trig parameter** — the knob path has its own MIDI routing. Owner's workaround: build an arp on a synth track and **copy it onto the MIDI track** — *"all the parameters are now there"*, so a MIDI track's preset stores and displays arp settings. **Notes do not arpeggiate.** DNX monitored USB MIDI out for 84 s with the pattern running: 22 note-ons, all **note 60 vel 100 on ch 1, every 4000 ms ±1**, each held until the next; no other channels, CCs or clock. The trig plays as written; the arp contributes nothing. **DNX read the saved project `TEST_MIDI_ARP` (+Drive slot 21), pattern A2:** the kit mask marks T16 as the only MIDI track, and T16's **sound slot** holds the copied arp byte for byte (bytes 324–353 identical to the source T3: MODE UP, SPD 14, RNG 1, N.LEN 14, LEN 16, all steps on, offsets −6..+6). But the track's separate **268-byte MIDI record** (kit +5964) carries no arp. The copy persists, in the sound slot, whose machine byte reads **MIDI (4)** (DNX corrected its first reading of it as a parked FM TONE sound). |
| 2026-09-17 | **Three LFO waveforms, v2** (`lfo-waveshapes2_DN2_1.11.syx`, base **1.11**) — v1 plus the four WAVE clamp immediates 6→9 in both evaluators, and both waveform value formatters (`0x400e34ac`, `0x4000766c`) replaced by a 10-name stub | **PASS.** Owner: *"All waves behave as they should!!!!!"* — STEP, PULS and NOIS named and working, SPH shaping each. **The first new LFO waveforms on the instrument.** Remaining cosmetic gap, as predicted: the `[MOD]` page glyph still draws RND for them. **Follow-up from the owner: *"SPD and MULT doesn't affect the noise at all."*** Cause: NOI's sample-and-hold kept **one** "last step" word shared by every LFO of every track, so 48 interleaved callers replaced it on almost every call — frame-rate noise regardless of rate. Fixed in `lfo-waveshapes3` (stateless). |
| 2026-09-17 | **Table-driven LFO waveform** (`lfo-wavetable2_DN2_1.11.syx`, base **1.11**) — a 256-word trapezoid `TRP` as waveform 7, `SPH` = repeats per cycle; the v2 clamp and formatter fixes shared with `lfo-waveshapes2` | **PASS.** Owner: *"works perfectly :)"*. The data-driven waveform route works on the instrument, so any 256-word shape the bench exports can ship this way. |

**This row exists because the gap above bit twice in one day.** This log records
what was *sent*, never what is *resident*, and nothing writes a row when the
owner reflashes stock. On 2026-09-16 that produced two wrong statements: DNX
told the owner the instrument was wearing the TRIG-page probe build when it was
on v5, and this project then told DNX it was on v5 when the owner had already
returned it to stock. Neither was caught by reading; both were caught by the
owner.

**So: write a row when stock goes back on, not only when a build goes out.** A
log that only records departures cannot answer "what is on it now", which is the
question anyone actually asks.
