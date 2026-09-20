# One firmware per backlog idea — the tracker

**Goal set by the owner, 2026-09-17:** *"deliver at least one firmware per idea
in the backlog."*

This file exists because that goal spans more sessions than any one of them can
hold, and because the honest answer for several entries is "not a firmware" or
"blocked on a named thing" rather than a build. It is the campaign's state; the
evidence stays in `docs/ideas-backlog.md` and the per-build script docstrings.

**A row moves to DELIVERED only when a `.syx` exists in
`00_Resources/02_Builds/` whose integrity checks pass and whose HMAC trailer is
reproduced.** Passing on hardware is a separate column, because a build that has
not been flashed has not been tested.

---

## State

| § | idea | build | on hardware |
|---|---|---|---|
| 1 | Reclaim space / grow section 3 | **DELIVERED** — `payload-section_DN2_1.11.syx`: section 3 grows by a payload that a boot hook copies above BSS before the clear. **Seen running end to end under the emulator**: cold boot copies the payload, the stamp reads it, `MOD` appears. The flash tests Elektron's bootloader, which the emulator cannot | **PASSED by proxy 2026-09-17** — `intro-bang` uses the same appended-data route and booted on the instrument |
| 2 | An emulator as a test harness | **not a firmware** — it is the harness the others are tested in, and it works | n/a |
| 3 | Expand the PCM catalogue | **not started — the cheap route is ruled out.** The two unreachable transients (slots 0 and 1) need `TRAN` −8 and −4; raising the maximum reaches up, not down, and dropping the −8 offset would move every existing sound onto a different transient. Growing the bank itself needs shipped bytes (§1's build) *and* the engine's slot bound, which is DSP-side (§7) | — |
| 4 | FX and Master open to LFO modulation | **SHIPPED** | **passed**, PR #61 |
| 5 | Bake an LFO's output into parameter locks | **not started** | — |
| 6 | A new ELE3 section as real address space | **covered by §1's build for now** — shipped bytes reach run time by growing section 3, which needs no new section id and no loader change. A separate section is only worth it if §1 fails on hardware | — |
| 7 | The DSP hunt | **parked**, with an explicit warning | — |
| 8 | New LFO waveforms | **DELIVERED** — ~~`lfo-waveshapes_DN2_1.11.syx`~~ **FAILED on hardware 2026-09-17** (ran as RND, named ERR: WAVE clamped to 6 in both evaluators, formatter bound 6). **v2 `lfo-waveshapes2_DN2_1.11.syx`** | **v2 PASSED on hardware 2026-09-17** — all three waves work; glyph still RND. NOI ignored SPD/MULT (shared state) → v3 `lfo-waveshapes3` **passed**; ~~v4~~ superseded; v5 partial (display used a heap-relative global); **v6 `lfo-waveshapes6` PASSED on hardware 2026-09-17** |
| 9 | A custom start-up animation | **DELIVERED** — `intro-tunnel_DN2_1.11.syx`: the intro is a 1/r polar tunnel, and two bytes re-scale it. **Seen running under the emulator**: 9,086 of 16,384 table entries change as predicted | awaiting a flash |
| 10 | The arpeggiator on MIDI tracks | **DELIVERED** — ~~`arp-on-midi_DN2_1.11.syx`, one byte~~ **FAILED on hardware 2026-09-17** (edited the FUNC branch; the MIDI gate sits before it). **v2 `arp-on-midi2_DN2_1.11.syx`**: the real gate, two NOPs. **v3 `arp-midi-play_DN2_1.11.syx`** (2026-09-17): the playback build — a MIDI track with the arp on takes the synth road to the ISR's arp, and the ISR's voice trigger turns its notes into MIDI records. Key-down/up routing **seen under the emulator** both ways (arp on → voice starter, off → MIDI sender); the ISR half cannot run there | v1 failed; **v2 PARTIAL** (menu opens; knobs jump to TRIG; notes do not arpeggiate); v3 silenced all MIDI notes (null sound pointer); play2 silent on the arp track (wrong gate filter, found with `arp-midi-diag`); play3 plays the arp with offsets but N.LEN lengths wrong (arp and trig length tables differ); **`arp-midi-play4_DN2_1.11.syx` PASSES 2026-09-17** (DNX capture: offsets, velocity, 1/16 at 125 ms, N.LEN 1/32..1/4 within 1 ms of the table, no stuck notes) |
| 11 | A real compatibility check between mods | **not a firmware** — it is a check over builds | n/a |
| 12 | P-locking the performance modulators | **not started** — route (b) scoped | — |
| 13 | A mod stamp on the intro screen | **DELIVERED** — `intro-stamp` (`MOD` beside the logo), then the owner's redesign: `intro-burst` (logo knocked out of a comic burst) and `intro-bang` (the burst flashes inverted, then explodes into the tunnel). **All seen running under the emulator.** Alternatives: flash one | **`intro-bang` PASSED on hardware 2026-09-17** |
| 14 | A shape bench for the LFO waveforms | **DELIVERED** — the tool, plus its firmware half: ~~`lfo-wavetable_DN2_1.11.syx`~~ (same two defects, never flashed) → **`lfo-wavetable2_DN2_1.11.syx`** takes the bench's own JSON export | **v2 PASSED on hardware 2026-09-17** |
| — | **Site: LFO waves with swappable wavetables** (owner goal, 2026-09-17) | **DELIVERED** — `site/lfo.html`, mod `lfowaves` (CLI + browser, byte parity), WAV/JSON wavetable import | page driven headless: builds and verifies 21/21 |
| 15 | A wavetable synth machine (the owner's actual meaning of "wavetable") | **not started** — audio is DSP-side, so it inherits §7's cost. First build: port digikit's Digitakt machine-slot Milestone A to the Digitone | — |
| 16 | A glitch-ASCII intro instead of the tunnel | **DELIVERED** 2026-09-18 — `bootscreen-ascii_DN2_1.11.syx` (DNX's loader in 3x5 ASCII), and the owner's 1966 spin as `bootscreen-spin_DN2_1.11.syx`; both an `ANIM` chunk of the `bootscreen` mod, on the Boot Screen page. **Seen running under the emulator** | **both PASSED on hardware 2026-09-18** (owner: upright, fluent, boot unaffected) |
| 17 | A performance mixer driven by MIDI controllers (DN1 and DN2) | **not started** — routing lives in MAIN OS as `BreakOutBoxSettings`; section 8 is the Outbox 8 firmware; levels/mutes/sends already have CCs 93-95, 29-31. **Cue:** route 1 (USB/Outbox pair, MAIN OS only) chosen, parked until the owner starts it | — |
| — | **LFO4** (the project's named goal) | **DELIVERED** — `lfo4-tick6a_DN2_1.11.syx` | **PASSED on hardware 2026-09-17** — owner: *"works"*. Next: parameters from storage and the UI (v4 page view) instead of the image |
| — | Transient Swapper | **SHIPPED** | **passed**, PR #64 |

## Four builds are waiting on the owner, and they are independent

Each was written to be flashed on its own and answers a different question, so
the order does not matter and a failure in one says nothing about the others.

1. **`lfo4-tick6a`** — **PASSED 2026-09-17** (owner: *"works"*). Does a fourth LFO generate and apply? Listen for a slow
   filter sweep on all sixteen tracks that no visible LFO explains.
0. **`lfo-wavetable`** — a waveform whose shape is 256 signed words in the image
   rather than arithmetic, with `SPH` as the read stride. Ships a trapezoid;
   `python scripts/build_lfo_wavetable.py shape.json` rebuilds it from anything
   the bench exports.
2. **`lfo-waveshapes`** — three new waveforms. Watch the `[MOD]` page when
   selecting them: its waveform-graph renderer is the one thing not read.
3. **`arp-on-midi`** — does the ARPEGGIATOR menu open on a MIDI track, and do
   the notes arpeggiate? Audio tracks are the control and must be unchanged.

## What actually blocks the rest

Grouped by the gate, because the gates are shared and clearing one clears
several entries.

**~~The boot draw path — blocks §9 and §13.~~ CLEARED 2026-09-17.** The intro
is one copy loop displacing a static source bitmap through an animated offset
table (`docs/display-path.md`). §13 is built on it. §9 is now a data problem: a
new offset table or a new source image. Recorded below as it stood before.

~~Neither the start-up animation's
frames nor the version string's composer has been located. Both are trace
questions, not scan questions: hook `Bitmap::setPixel` through the intro under
the emulator and the answer is a picture of which region is drawn by what.
`docs/display-path.md` already records that the intro draws through `setPixel`
while the running UI never calls it, so the hook has one caller family.
**The owner's shortcut applies here:** the Digitakt II 1.15C image is the one
digikit supports best, so trace it there first and carry the structure across.~~

**Address space — blocks §1, §3 and §6, and caps §14.** A wavetable waveform is
4,096 bytes; the PCM catalogue is far more; the largest verified-free cave run is
896 bytes. The 25.3 MB above BSS is usable at runtime but is not in the image, so
anything that must *ship* data needs either a grown section 3 or a new section.

**Narrowed 2026-09-17 by reading the boot clear.** BSS starts at `0x402fc000`,
which is **63,872 bytes below the loaded image's own end** (first written as 63,488 — an arithmetic slip, corrected) — the `.data`
initialiser tail is consumed and then wiped. So simply appending to section 3
buys nothing, and raising the clear's start immediate would leave real globals
uninitialised. **The build that would settle all three:** append past the
initialiser tail and copy it out in a cave *ahead of* `0x400004b2`, into the
25.3 MB the clear never reaches. One experiment, three entries.

**The per-track mirror's width — blocks §12, and LFO4's v6 needs the same fix.**
§12's gating question ("where are LFO1–3 applied?") was answered today, and the
answer reprices it: an LFO's `DEP` is p-lockable only because it is an ordinary
mirror slot, so route (b) means making the performance modulators' depths mirror
slots too. But **the mirror is exactly 101 u16 slots and index 100 is its last
cell** — the bitmap's spare 100–127 has no storage behind it. Relocating and
growing the mirror from 202 to 250 bytes per track is the shared prerequisite,
and it is the same work LFO4's v6 needs. Whichever is built first pays for it.

**Nothing at all — §5 is simply not started**, and needs a parallel store. It is
the least specified entry in the backlog.

## Rules this campaign keeps

- **A build asks one question.** Three of the four delivered this session
  deliberately do less than the feature they belong to, because a build that
  changes two things cannot be read when it fails.
- **Every edit is asserted against its stock bytes** before it is applied, so a
  patch written for 1.11 cannot half-apply to anything else.
- **Disassemble the build, not the plan.** Two errors in `lfo4-tick6a` were
  invisible in the reasoning and obvious in the output.
- **No firmware bytes in this repository, ever.** Every `.syx` here is produced
  from the owner's own image by the script beside it.
