# The UI, mapped under emulation — 2026-09-16

Captured headlessly from Digitone II OS 1.11 (`57b06a79…`) with digikit's
emulator. Every screen named here was photographed from the guest's framebuffer;
every class name comes from the firmware's own RTTI.

**Published as an artifact:** <https://claude.ai/artifact/VYNpR1vV6jCzJvNTrvCJag>

> **The snapshot is not a factory-default instrument.** `boot400M.snap` carries a
> project someone had already edited — the owner identified LFO speed as not its
> factory 16, and a modulation destination already assigned. **Structure is
> firmware and stands; any *value* in a capture belongs to that project.** If
> defaults ever matter, rebuild the ladder from a cold boot.

## 1. The control surface, from the firmware's own table

`panelin.control_names()` reads the factory-test tables at run time, so this
cannot drift from the image. **55 buttons, 10 encoder positions.**

| codes | controls |
|---|---|
| 1–6 | TRIG, SRC, FLTR, AMP, FX, MOD |
| 7–9 | PRESET, SETTINGS, TEMPO |
| 10–15 | YES, UP, NO, LEFT, DOWN, RIGHT |
| 16–24 | TRK, FUNC, KEYBOARD, RECORD, PLAY, STOP, PAGE, PTN, SONG |
| 25–40 | TRIG 1–16 |
| 41–48 | ENCODER A–H **as buttons** — they push |
| 49–54 | LEVEL, VOICE, ARP, PLUS, STACK, MINUS |
| encoders | A–H plus LEVEL |

## 2. View classes observed

**Ten so far**, each named by the tracer as it consumed a key:

| view | reached by |
|---|---|
| `MainScreenView@0x4476a3f0` | the parameter sections, `ARP`, `STACK`, `SONG` first press |
| `LfoPageView@0x447bf800` | `MOD` |
| `PatternSelectView@0x447bc200` | `PTN` |
| `QuickLedIntensityView@0x447e1a80` | `SETTINGS` **held** |
| `NoteEditorMenuView@0x447e2400` | `KEYBOARD`, `STACK` |
| `SongModePopup@0x447e1c00` | `SONG` held |
| `KeyboardView@0x447bc600` | `TRIG 1`–`16` — the step keys play notes |
| `HelpBubbleView`, `PatternGridView`, `TempoLedView` | in the offer chain, not yet seen to consume |

### Keys consumed by nobody, and why that is structural

`PRESET` (7), `LEVEL` (49) and `VOICE` (50) were **offered to every view and
consumed by none**, `PRESET` even when held and even with `FUNC`. `FUNC`
combinations with `PRESET`, `SETTINGS` and `TRK` reached `MainScreenView` or
nobody.

**That is not a dead key — it is the view stack.** A key does something only if a
view currently on the stack claims it, so "does this key work" is a property of
**what mode the machine is in**, not of the key. It is why a tap and a hold
differ, and why some keys need a mode entered first.

**Consequence for coverage: a single pass from the main screen cannot map this
UI.** Each key has to be exercised in each mode that might claim it. The map
below is one pass from one state.

### The ARP page, captured

`ARP` (51) draws **`ARPEGGIATOR > TRACK 1`** — `MODE OFF`, `SPEED 1/16`,
`RANGE 1`, `N.LEN 1/32`, a 16-step grid, `STEP 01 OFFSET 0`, `ARP LENGTH 16`.
That is manual §9.7's parameter list exactly (MODE, SPEED, RANGE, N.LEN, LEN,
OFS), and it is the first time this project has seen the page the firmware draws
for the arp block `docs/ideas-backlog.md` §10 wants to extend to MIDI tracks.

## 2b. Original list

Named by the tracer as each consumed a key:

`MainScreenView` · `LfoPageView` · `PatternSelectView` · `QuickLedIntensityView`
· `HelpBubbleView` · `KeyboardView` · `PatternGridView` · `TempoLedView`

A key is **offered to each view in turn until one consumes it**. `PRESET` was
offered to seven views and **consumed by none** in the state tested.

## 3. Behaviours worth knowing before driving the panel

- **A tap and a hold are different events.** Holding `SETTINGS` hands off from
  `MainScreenView` to `QuickLedIntensityView` mid-press. A tap of the same key
  changed nothing visible.
- **The page indicator is transient.** `MOD (1/3)` in the header reverts to the
  project name after a few million instructions, so a capture taken too late
  cannot identify which sub-page it is showing. **Capture ~5 M instructions
  after the release.**
- **Multi-page sections cycle; single-page sections reveal values.** A second
  press of `MOD` goes to LFO2. A second press of `SRC` **swaps labels for
  values** — `TUN2 −12.00`, `PD1 45%`. That is a way to **read parameters
  without touching an encoder**, which matters because edits do not land.
- **Some keys change machine state rather than opening a menu.** `PTN` reached
  the +Drive and reloaded the project.

## 4. Settings: the tree is in the manual, and the storage is not reachable

`dn_sysex/00_References` carries the manuals extracted to markdown. §13 gives the
whole tree without any button pressing:

```
13.1 PROJECT       load / save as / manage
13.2 SONG          rename / clear / load / save to proj
13.3 PATTERN       rename / clear / save to proj / reload from proj
13.4 MIDI CONFIG   sync / port config / channels
13.5 SYSEX DUMP    sysex send / sysex receive
13.6 AUDIO ROUTING to main / to send fx / usb in / usb out / int to main / …
13.7 PERSONALIZE   led intensity / …
```

### [OWNER] General settings live in the machine, not the project

And **§13.5.1 offers only three dump types — PROJECT, PATTERN, PRESETS.**
*"PROJECT will send the active project (settings, patterns, presets in the
pool)"*, which is **project-scoped** settings.

**There is no SETTINGS or GLOBAL dump type.** So machine-global settings —
MIDI config, audio routing, personalize — have **no documented backup route over
SysEx**. That is a gap in the protocol, not in any tool. Relayed to DNX, whose
project backups therefore cannot cover them however they are written.

**Hypothesis, from the parts list and not measured:** `docs/hardware.md` records a
**Winbond 25Q128JV, 16 MB SPI NOR**, separate from the eMMC that holds the
+Drive. Machine-global, project-independent state is what such a part usually
carries.

### And the device is always listening

§13.5.2: *"Digitone II is continuously listening for SysEx data so you can at any
time send backed up projects or patterns to the device."* **No arming needed** —
so a failed SysEx injection is not explained by an unopened receive menu, which
removes one candidate from `docs/lfo4-slot-plan.md`'s eDMA-receive problem.

## 5. What the method is, for whoever continues

To locate any setting: the tracer names the **view class** that consumes its key,
and the live object carries its own RTTI name at `+0x28` — `0x4021eb3e` reads
`"QuickLedIntensityView"`. Dump the object while the screen is up and follow its
fields. That is the same move that found the sound-object pool: hook the thing
that touches the data and read what it points at.

**Not yet done.** The LED intensity object was dumped — five vtable pointers,
the class-name string, a heap pointer, `0xfc000000` with `0x3ff` (the ColdFire
peripheral base and a mask), and `0x446cabf0`, the sound-object container. **The
intensity value itself was not identified**, and no settings store has been
located.

## 6. Coverage, honestly

**Explored:** the six parameter sections, `SETTINGS` held, `TRK`, `PTN`,
`PRESET`, boot phases.

**Not explored:** the menu trees behind `SETTINGS` (needs YES/UP/DOWN/NO walking,
which works — arrows are buttons), `ARP` (51), `VOICE` (50), `STACK` (53),
`LEVEL` (49), `KEYBOARD`, `SONG`, the 16 trig keys and note editing, the eight
push-encoders, and every `FUNC` combination.

**The manual is the map; the emulator is the camera.** Walking the tree blind
with arrow keys rediscovers what §13 and Appendix C already document.

## 7. Why the SETTINGS tree cannot be walked here: the +Drive is not modelled

Dated 2026-09-17. Five frames after a single tap of key 8 (`SETTINGS`) —
`--input 130M:press:8 --input 133M:release:8`, captured at +3M, +9M, +17M, +29M
and +47M instruction counts — are **byte-identical**, and all five show the same
screen:

```
        [ Elektron +Drive glyph ]
FACTORY PROJECT >> +DRIVE...
```

That is the +Drive transfer-progress screen, and it never clears. It is not a
menu that opened and closed, and it is not a missed keypress: `MainScreenView`
consumed the key (the tracer said so), the machine went somewhere, and where it
went was a storage operation that cannot finish.

**The owner settles the reading:** on the instrument `SETTINGS` opens
immediately. So this is not a UI question at all — the emulator has no eMMC
behind the +Drive, so any path that touches project storage parks on this screen
forever, and the settings menu sits behind such a path.

Consequences worth carrying forward:

- **The SETTINGS tree is not reachable under emulation** until the eMMC
  (Kingston EMMC32G-TX29) is modelled. Walking it with `DOWN`/`YES`/`NO` is not
  a matter of finding the right key sequence. Marked closed, not blocked on
  effort.
- **This screen is a probe.** Any future capture that lands on
  `FACTORY PROJECT >> +DRIVE...` means the firmware reached storage — which is a
  useful positive signal about what a key does, even though the screen after it
  never arrives.
- It is a **separate** gap from the unmodelled MIDI RX eDMA channel 34 and from
  the encoder edits that never land; nothing here explains those.

`docs/ui-map.md` §6's "not explored" list stands, but `SETTINGS` moves out of
"not yet walked" and into "not walkable under the current emulator".

## 8. The manual, on backing up settings — and it confirms the negative

Checked 2026-09-17 against the **Digitone II User Manual, OS 1.10D** (the owner's
own copy; not vendored here). Two routes exist and neither carries the machine's
own settings.

**SysEx dump (§13.5).** Two things can be sent, and the manual names their
contents exactly:

- `PROJECT` — *"will send the active project (settings, patterns, presets in the
  pool)"*
- `PATTERN` — the selected pattern

The word "settings" there is the **project's** settings — chapter 13.1's PROJECT
menu — not the machine's. The receive side is narrower still: §13.5.2 documents
only `PATTERN` and `PRESETS` as receive targets.

**Transfer (§6.8).** File-level copying of **projects, presets and samples** off
the +Drive. It moves the same objects, as files.

**[CORRECTED the same day, by the owner]** An earlier version of this section
listed MIDI CONFIG, AUDIO ROUTING, PERSONALIZE and SYSTEM as a table of things
with "no route out". **That table was an assumption, not a reading**, and the
owner corrected it: *"There are also a lot of routing and settings that do live
in a project."*

The manual backs the correction and does not resolve it. §4 says *"A project
contains 128 patterns. The project also stores general settings and states"* —
and never enumerates which. §13.5.1 says `PROJECT` sends *"settings, patterns,
presets in the pool"*. So an unknown share of chapter 13 **is** carried by a
project SysEx dump, and the set with genuinely no backup route is **narrower
than the chapter list and its membership is not established**.

What survives from the reading, and it is still the point:

- The **only** two SysEx send targets are `PROJECT` and `PATTERN`; the receive
  side documents only `PATTERN` and `PRESETS`. Transfer moves projects, presets
  and samples as files. There is **no "settings" object** in any of those routes.
- Therefore anything genuinely machine-level — whatever that set turns out to be
  — has no backup route, because no route carries a settings object at all. The
  owner's *"general settings live in the machine"* still stands for that residue.

**The experiment that settles membership, and it is cheap.** Dump a project over
SysEx, change one chapter-13 setting on the instrument, dump the same project
again, and diff. A setting that moves the bytes is project-scoped and already
backed up; one that does not is machine-level and is the real gap. Running that
once per menu page produces the membership list the manual withholds. **This is
DNX's instrument, not this repository's** — it is a data capture, and
`docs/PRINCIPLES.md`'s rule sends it there.

Until that runs, this section claims only the negative it measured: **no backup
route carries a settings object,** and which settings ride along inside a project
is open.
