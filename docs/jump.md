# DIRECT JUMP: an instant pattern switch

**Owner's request (the Discord audit, `docs/ROADMAP.md`): "instant pattern switch".** With
the sequencer playing, a pattern cued with PTN + TRIG starts at once, on the step it would be
on had it been playing since PLAY, instead of at the end of the playing pattern.

- **Turn it on:** hold **PTN** and press **YES**. The title bar says `DIRECT JUMP ON`.
  **Off:** hold PTN and press NO (`DIRECT JUMP OFF`). Default: off, so the instrument behaves
  as stock until the user turns it on.
- **It survives power-off:** it is the instrument's setting (like PERSONALIZE's), not a
  project's, kept in the mod's own settings sector on the +Drive.
- **Only PTN + TRIG jumps.** Chains, songs and MIDI program changes cue through the
  sequencer's other callers and keep stock's behaviour (the change at the pattern's end, or
  at its CHANGE length).

Code: `csrc/jump/jump.c`, `csrc/jump/hooks.S`; the edits in `dnfw.waverider.coldfire`
(`JUMP_*`). Check: `scripts/emu_jump.py`, the ship gate's step **DIRECT JUMP (ColdFire)**.

## 1. What stock 1.11 offers: no pattern-change modes

The first question was whether stock already had a mode list to add DIRECT JUMP to, as the
Digitakt (1) does (SEQUENTIAL / DIRECT START / DIRECT JUMP / TEMP JUMP). **It does not.**

- No string for any such mode is in MAIN OS (`SEQUENTIAL`, `DIRECT`, `TEMP JUMP`: none).
- The Digitakt II manual (OS 1.17, §10.1, §10.7) has none either: a cue changes at the
  pattern's end, or at CHANGE (`PATTERN` column of PAGE SETUP in per-track mode).
- `docs/overtone-map.md` read `0x42c5a91e` as a "pattern-change mode byte compared with 2".
  **It is the sequencer's tick within the step** (`0x400da2c2`: incremented each tick,
  wrapped at `0x401f6b08[scale]` = 3, 4, 6, 8, 12, 24, 48 ticks a step for 2x .. 1/8x). The
  compare with 2 is "the second tick of the step", where stock looks at the queue.

So the UX is a toggle, Overtone's own combination (PTN held + YES / NO), with the stock
message line as the confirmation. In stock, YES or NO in the PTN view closes the view; held
PTN + YES / NO without FUNC is taken by us, everything else (FUNC + YES: the chain creator;
YES / NO without PTN held; releases and repeats) goes to stock's handler.

## 2. How stock changes pattern (measured in the emulator)

The sequencer is the timer ISR `0x400d987a` (vector 121). It runs four entries a tick at the
snapshot's tempo; the emulator does not fire it by itself, so `emu_jump.py` enters it as the
interrupt would, and the sequencer plays (stock: step 0 at PLAY, then one step every six
ticks at 1x).

- **The cue.** PTN + TRIG: `0x400fa11e` builds a 24-byte entry (pattern
  `0x4121898c + 122478 n`, kit `0x4210c08c + 23921 n`) and posts it with `0x400d93f0`
  (at `0x400fa1da`). Stopped, stock applies it at once.
- **Arming,** on tick 2 of each step (`0x400da406` → `0x400da416`): the queue's head; if this
  is the last step before the change (`0x400da45a`: CHANGE `0x42c5aab4`, or the length
  `pattern+122196`), it arms at `0x400da4d2` (next pattern, MIDI program change out,
  `0x42c5aaac` = 1). Its start step `0x42c5a9c4` is set to 0.
- **The switch,** at the next step boundary (tick 0, `0x400da584`): the queue is advanced, the
  new pattern installed (`0x42c5a9a0`), the start step copied to `0x42c5a9bc` and the
  change counter `0x42c5a91c`, and each track's start step computed from it
  (`0x400da7c2..0x400da8c8` into `0x42c5a9ea[t]`, taken at `0x400da904`). The boundary where
  the switch happens still plays the old pattern's step (measured: A01's last step 7 at the
  switch, A02's step 0 at the boundary after).

## 3. What DIRECT JUMP changes (five 6-byte sites and one vtable slot)

| site | stock | ours |
|---|---|---|
| `0x400fa1da` | `jsr 0x400d93f0` (the PTN view's one-pattern cue) | `jmp_cue`: stock's cue, then armed if the setting is on and it plays (`0x42c5a918` = 1) |
| `0x400da406` | `move.b 0x42c5a91e,%d1` | `jmp_tick`: armed, on a tick that is not a step boundary and with no stop pending (`0x42c5a9e9`), the queue path runs now (d1 = 2) |
| `0x400da45a` | `mvs.w 0x42c5aab4,%d1` | `jmp_arm`: armed and the head is another pattern: straight to stock's arming `0x400da4d2` (the "last step?" test skipped) |
| `0x400da6e6` | `lea 0x42c5a9c4,%a1` | `jmp_switch`: for the switch we armed (`0x42c5a9a0` / `0x42c5a9a8` match), the start step from `jmp_position()`; stock's per-track code then reads the new pattern (a5) |
| `0x400da8cc` | `pea 0x401f6b25` | `jmp_tracks`: each track's start step wrapped by its length |
| `0x402008cc` | the PTN view's key handler `0x400fa6be` | `jmp_key`: PTN + YES / NO; everything else to `0x400fa6be` |

Every site's stock bytes are checked before the write, and 11 guards cover what the shims
return to and rely on (`JUMP_GUARDS`, recorded in `waverider_code.json`).

**The start step.** At the switch the ticks since PLAY (`6 * 0x42c5a9d0 + 0x42c5a9d4`, read
before the ISR counts this tick) are one short of whole steps, and the step that plays next
is the one after: `pos = (ticks + 1) / div + 1`, `div` = 6 in per-track mode (stock's master
step there), else `0x401f6b08[scale]`; then `pos mod length` when the length is above 1 (as
stock wraps; 1 or less is no wrap). This is Overtone's formula (`docs/overtone-map.md` §4),
now measured: with it every track lands where stock plays that pattern from PLAY.

**Per-track mode.** Stock's per-track code after a switch reads the *old* pattern's mode and
scales through a5 (harmless for stock: its start step is always 0). For our jump a5 is the
new pattern, and each track's step is wrapped by its own length (stock adds no wrap there).

**The latency.** Cued during step g, the switch is at the next boundary (g + 1, which still
plays the old pattern's step, as stock's own changeover does), and the new pattern sounds
from step g + 2 on. Measured: cued 3 ticks into step 3, switched 2 ticks later, its first
step at step 5, on step 5 of its own.

## 4. Where the setting persists, and why it is safe

One 512-byte sector, **`0x6FF000`** on the +Drive (eMMC), through the stock block driver
(`0x4012c59a` / `0x4012c780`) as the sample link and the library already use it:

- `'DN2S'`, version 1, flags (bit 0: DIRECT JUMP), a check (`~magic ^ version ^ flags`);
  anything else reads as "off". The mod's own settings sector: a later setting takes a bit.
- **It is ours.** The stock store ends below `0x458000` (`docs/drive-storage-research.md`);
  the mod's region starts at `0x600000`: the pool's image `0x600000 .. 0x6C8001`, the
  library from `0x700000`. `0x6FF000` lies between them, written by nothing else
  (`_Static_assert` in `jump.c`). Not a project byte, not a stock setting: Overtone's
  `PROJECT+0x50 +14` byte (open question 1 there) is not used.
- Read once the device is up, written only when YES / NO changes it, both from the UI loop
  (`wr_poll` → `jmp_poll`), never from the ISR or the key handler. A device smaller than the
  sector: nothing read or written, the setting stays off.

## 5. Verified in the emulator (`scripts/emu_jump.py`, digikit `ui800M-v014`)

A01 16 steps, A02 12 (per pattern) or per track (master 16; tracks 16, 5, 7, 3), 1x; PLAY,
A02 cued at global step 3, tick 3, played to step 36:

| run | result |
|---|---|
| off, this build vs the stock image | every tick's sequencer state identical (trace digest `377d5149…` both); the change at A01's end (step 15, A02's step 0 at 16) |
| on (PTN + YES) | `DIRECT JUMP ON` shown; sector `444e3253 00000001 00000001 bbb1cdac` written; switch 2 ticks after the cue (step 4), start step 5; steps 5..36 identical to stock playing A02 from PLAY |
| on, per track | the same, every track (lengths 16, 5, 7, 3) identical to the reference from step 5 |
| on, cued through `0x400d93f0` directly (program change / chain / song path) | stock's: trace digest `377d5149…`, no jump |
| persist | on, power-on reads it back on; PTN + NO off, written, power-on reads it off; only `0x6FF000` read or written |

No fault in any run. Boot from reset and the UI fuzz pass on the build.

## 6. Not verified, and open

- **Hardware.** Nothing here has been on an instrument. Audio is not modelled: the trace is
  the sequencer's state, not what sounds.
- The position follows the global grid since PLAY. After a pattern of odd length has run
  (stock's changes restart at step 0), a jump lands on the global grid, not on "the step the
  playing pattern is on". With patterns of one length started from PLAY the two agree.
- The legacy chain gesture (PTN + TRIG held, more TRIGs) cues the first pattern through the
  single cue, so with the setting on that first pattern jumps; the chain then changes at the
  pattern's end as stock.
- Differing master scales between the two patterns were not exercised (each is 1x here).
- A cue armed, the setting turned off and another pattern cued within the same step: the
  second pattern is switched to at once, at step 0 (a race of one step; not reachable by
  ordinary use).
