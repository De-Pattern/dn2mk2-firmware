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
| 1 | Reclaim space / grow section 3 | **not started** — and the cheap version is now known not to work | — |
| 2 | An emulator as a test harness | **not a firmware** — it is the harness the others are tested in, and it works | n/a |
| 3 | Expand the PCM catalogue | **not started** | — |
| 4 | FX and Master open to LFO modulation | **SHIPPED** | **passed**, PR #61 |
| 5 | Bake an LFO's output into parameter locks | **not started** | — |
| 6 | A new ELE3 section as real address space | **not started** | — |
| 7 | The DSP hunt | **parked**, with an explicit warning | — |
| 8 | New LFO waveforms | **DELIVERED** — `lfo-waveshapes_DN2_1.11.syx` (`STP`, `PLS`, `NOI`) | awaiting a flash |
| 9 | A custom start-up animation | **not started** — same gate as §13 | — |
| 10 | The arpeggiator on MIDI tracks | **DELIVERED** — `arp-on-midi_DN2_1.11.syx`, one byte | awaiting a flash |
| 11 | A real compatibility check between mods | **not a firmware** — it is a check over builds | n/a |
| 12 | P-locking the performance modulators | **not started** — route (b) scoped | — |
| 13 | A mod stamp on the intro screen | **not started** — same gate as §9 | — |
| 14 | A shape bench for the LFO waveforms | **DELIVERED** — the tool, plus its firmware half: `lfo-wavetable_DN2_1.11.syx` takes the bench's own JSON export | awaiting a flash |
| — | **LFO4** (the project's named goal) | **DELIVERED** — `lfo4-tick6a_DN2_1.11.syx` | awaiting a flash |
| — | Transient Swapper | **SHIPPED** | **passed**, PR #64 |

## Four builds are waiting on the owner, and they are independent

Each was written to be flashed on its own and answers a different question, so
the order does not matter and a failure in one says nothing about the others.

1. **`lfo4-tick6a`** — does a fourth LFO generate and apply? Listen for a slow
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

**The boot draw path — blocks §9 and §13.** Neither the start-up animation's
frames nor the version string's composer has been located. Both are trace
questions, not scan questions: hook `Bitmap::setPixel` through the intro under
the emulator and the answer is a picture of which region is drawn by what.
`docs/display-path.md` already records that the intro draws through `setPixel`
while the running UI never calls it, so the hook has one caller family.
**The owner's shortcut applies here:** the Digitakt II 1.15C image is the one
digikit supports best, so trace it there first and carry the structure across.

**Address space — blocks §1, §3 and §6, and caps §14.** A wavetable waveform is
4,096 bytes; the PCM catalogue is far more; the largest verified-free cave run is
896 bytes. The 25.3 MB above BSS is usable at runtime but is not in the image, so
anything that must *ship* data needs either a grown section 3 or a new section.

**Narrowed 2026-09-17 by reading the boot clear.** BSS starts at `0x402fc000`,
which is **63,488 bytes below the loaded image's own end** — the `.data`
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
