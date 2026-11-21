# PERFORM (v0.69): Analog Four MKII-style performance macros

Owner, 2026-11-21. The design and decisions: the Project doc `claude/perf-mode-design.md`
(offset, per project, [MOD] + [FX], no recording yet), modelled on the A4 MKII manual §9.3
(OS 1.56: PERFORMANCE mode, SETUP, CONFIGURE, RENAME, TRACK MUTE, BIPOLAR, PERF MUTE).

## Research notes (stock DN2 OS 1.11)

**The DN2 has the A4's MODULATION SETUP screen.** Strings at 0x4021f2a0: `MODULATION SETUP`,
`COPY MODULATIONS`, `CLEAR MODULATIONS`, `PASTE MODULATIONS`, `BIPOLAR`, `MOD4`; classes
`ModSetupView`, `ModDestListView`, `GroupedModDestListView`.

- `ModSetupView` typeinfo 0x40203994; primary vtable 0x402039c8 (slot 4, the draw: 0x401072a8,
  which prints "MODULATION SETUP" at 0x401072fa); five secondary vtables 0x40203a18..0x40203a68.
- Its constructor is **0x40106eac**. Mangled lambda names give its signature:
  `ModSetupView(std::function<ModConfig*()>, std::function<bool(int)>, const char *title,
  std::function<long()>, std::function<void(long)>, std::function<std::string(long)>, int)`.
  So it is generic: whoever opens it hands it the config (five targets), a title, and the
  macro value's getter / setter / formatter.
- It is built in six places, 0x400ba32c .. 0x400baf6e (the SOUND menu's VELOCITY MOD,
  MODULATION WHEEL, BREATH CONTROLLER, AFTERTOUCH, ... ; title strings e.g. 0x40219fc2), each
  making its std::function objects on the stack (0x40120264 allocates, the manager pointers
  0x400b6772 / 0x400b67c4 / 0x400b6816 and invokers 0x400b7de6 / 0x400b86a4 / 0x400b7488), the
  view object 0x1ec bytes (vtable 0x401f18dc on its shared_ptr control block), then pushed on the
  screen (0x4018816a, 0x401d3b60).
- `ModDestListView(trackID, ParameterSet&, physicalParamID, logicalParamID, int, modFlags, ...)`:
  the parameter picker is per track; the A4 mixes tracks in one macro, so either one picker per
  target column (its track chosen first, as the A4's "T1" header) or our own list.

**Next:** in the emulator, open VELOCITY MOD on a stock track and screenshot MODULATION SETUP
(the look reference), then read `ModConfig`'s layout (five targets: destination id + depth,
the BIPOLAR flag) from the getter the velocity menu passes. If a `ModConfig` of ours can be
handed to stock's view, PERF SETUP is stock's screen. Then: is [MOD] + [FX] free; the mod
mirror's room.

**The velocity menu's config getter** (std::function invoker 0x400b7de6): the active track
(0x4018a97a -> 0x4003e40e -> 0x40046bfe), then its sound (0x4004bb94 via 0x40030e66), and the
**ModConfig is the sound's own, at sound + 44**. So stock's MODULATION SETUP edits a config that
lives in a Sound, for that track's parameters. A macro of ours needs a ModConfig of the same
layout in our own memory (its size and fields next: read sound + 44 .. in a snapshot, and the
code that applies velocity mod), and the A4's per-target track (T1..T6 header) is not in stock's
view: either one track per macro (stock's picker as is) or our own column header and picker.
The value formatter (invoker 0x400b7488) prints value/2 + 60 clamped at 127 via 0x4014fde4
(a note name?) -- one of the six is KEY TRACKING.
