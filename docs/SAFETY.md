# Safety: how this project avoids harming a Digitone II

Two goals, in this order:

1. **Never lose the way back.** Whatever a build does, stock firmware can be
   restored.
2. **Never break what already works.** The five stock machines, the FX, the
   sequencer and your projects behave exactly as they do on stock.

No unofficial firmware can promise zero risk, and this document does not.
What it does is name every way harm could happen, and say what stops each one.

---

## What could go wrong, and what stops it

| risk | how bad | what stops it |
|---|---|---|
| **The bootstrap (section 2) is damaged.** It runs the Early Start-up Menu and the recovery flash, so losing it is the one true brick | permanent without a hardware programmer | **Enforced:** `dnfw mods apply` refuses to write any build whose section 2, 4, 5 or 8 differs from stock by a single byte (`src/dnfw/safety.py`, tested in `test/test_safety.py`). Mods only ever change MAIN OS (3) and the DSP program (7). |
| **Power is lost while the OS is being written to flash** | can be as bad as the above | Same risk as an official Elektron update. Use stable power, don't touch the unit during `UPGRADING… DO NOT TURN OFF`. |
| **The bootstrap is rewritten by an OS change.** Elektron: *"After some upgrades the bootstrap is also upgraded… right after the first restart."* 1.10 → 1.11 is such an upgrade. | as above, if power fails during it | Do that move **once, with Elektron's own stock 1.11**, on its own (below). After that, our builds carry 1.11's bootstrap byte for byte, so a unit on 1.11 has nothing left to rewrite. **From 1.10 or 1.12, read "Getting onto 1.11" first.** |
| **A build crashes MAIN OS or won't boot** | recoverable | Recovery runs from the bootstrap, not MAIN OS: [FUNC] at power-on → [TRIG 4] → stock 1.11 over **DIN MIDI**. Every build also boots from reset in the emulator first (`scripts/emu_boot_check.py`). |
| **The DSP stops and the unit goes silent** | recoverable | Upstream hit exactly this (`docs/waverider-dsp-silence.md`) and recovered by reflashing. Every build runs the DSP code in the SHARC emulator first; our code uses only instruction encodings found byte for byte in stock (the rule after upstream's negative-shift bug). |
| **Loud noise, DC or full-scale output** from a DSP bug | can harm speakers and ears | First test of every DSP build: **low volume, no headphones, monitors down.** And a rule for our DSP code: every engine sanitises its output (NaN/inf → 0, hard-clamped) before it reaches the stock chain. |
| **A stock machine, FX or the sequencer behaves differently** | a bug, not damage | The DSP gate checks that with no mod track playing, all 16 track buffers are **bit-identical to stock**, and that stock tracks beside a mod track are too (`scripts/sharc_waverider_m5.py` step 4). The ColdFire side lists every edit it makes; each is asserted against the stock bytes before it is written. |
| **Projects or sounds are damaged** | data loss | Back up the +Drive with Elektron Transfer before every flash. No mod writes to the +Drive directly. A track saved with a mod machine loads on stock firmware as FM Tone with its parameters kept. Upstream's `songguard` mod exists because a damaged project can halt even stock firmware, so test in a scratch project and keep real work out of it until a feature has been stable for a while. |
| **The recovery transfer stalls** (bar stops at e.g. 80 %) | annoying, not harmful | That's the MIDI link dropping packets, not the image. Upstream traced it to an interface going idle mid-transfer. Use a dedicated class-compliant USB-MIDI interface and turn off USB power-saving. Just retry: nothing is written to flash until reception completes. |

---

## Before the first flash, once

1. **Back up everything** with Elektron Transfer (projects, presets, samples).
2. **If your unit is on 1.10-anything, update it to stock 1.11 first** (see
   below). That's an official upgrade, and it rewrites the bootstrap.
3. **Prove recovery on your unit with stock 1.11**: DIN cable from the
   computer's MIDI OUT to the DN2's MIDI IN, hold [FUNC] at power-on, [TRIG 4],
   Transfer's *Legacy OS upgrade mode*, send `Digitone_II_OS1.11.syx`. It takes
   about 12 minutes; don't interrupt. Note which interface you used: that's
   your recovery cable from now on. Doing this *after* step 2 matters: it
   proves the recovery route of the bootstrap you will actually have.
4. Confirm the unit boots stock 1.11 and plays normally.

Until step 3 has worked once, flash nothing modified.

### Getting onto 1.11 from 1.10, 1.10A–E

This is an upgrade, the direction Elektron supports, but it **changes the
bootstrap**: 1.10E rebuilt it almost entirely (and moved its load address),
and 1.11 changed it again (`docs/os-versions.md`; measured here between 1.10A
and 1.11 too). Elektron's release notes: *"After some upgrades the bootstrap
is also upgraded. This upgrade is performed right after the first restart of
the device. Do not turn the power off during the upgrade."*

That restart is the most sensitive moment in the whole project, so it is kept
apart from everything else:

- Use **Elektron's own, unmodified `Digitone_II_OS1.11.syx`**, never a mod, for
  this step. The preflight guarantees our builds carry 1.11's bootstrap byte
  for byte, but the first move onto it should still involve nothing of ours.
- **Normal update route**: Transfer over USB to the running unit, as Elektron
  describe. Stable power; if you have a UPS or a reliable outlet, use it.
- After `UPGRADING… DO NOT TURN OFF` and the first restart, **leave it alone
  until it reaches the normal screen.** If it shows a bootstrap upgrade
  message, wait it out.
- Back up first. Elektron's own update is non-destructive to projects, but a
  backup is still the rule.

Upstream's unit made the same 1.10E → 1.11 move, through the recovery route,
and booted 1.11 cleanly (`docs/flashing.md`, 2026-09-11).

### Getting onto 1.11 if your unit runs 1.12

Every mod is built on 1.11. 1.12 only adds Outbox 8 main-output routing.
Going from 1.12 to 1.11 is a downgrade, which Elektron calls unsupported and
at your own risk, with possible loss of user content. So:

- Back up first (step 1).
- Send **stock 1.11**, unmodified, before any mod. That keeps the downgrade
  and the first modified flash as two separate steps.
- If the 1.12 bootstrap differs from 1.11's, that first flash may rewrite the
  bootstrap on restart. Give the project the 1.12 `.syx` and `dnfw diff` will
  say whether it does, before you commit to it.

---

## Every flash

1. **Build** with `dnfw mods apply` (it runs the preflight and refuses on any
   failure).
2. **`scripts/ship_gate.py` prints `CLEARED TO FLASH` on this exact file.** It
   runs every gate (preflight, DSP identity, SHARC runner incl. the
   stock-unchanged step, ColdFire instruction set, boot from reset, engine +
   SAVE/LOAD, unit tests) and records the pass, with the file's sha256, in
   `BUILD.syx.gate.json`. Every build, every time; no exceptions.
3. **Preflight the file you will actually send:**
   `dnfw preflight Digitone_II_OS1.11.syx build.syx` must print `PASS`.
4. **Back up** the +Drive.
5. **Flash** through the normal Transfer drop over USB. The DIN cable plays
   no part in this; the flash itself goes over USB alone. Have it within reach
   (plugged in is easiest) only so that, if the build does not boot, recovery
   is a cable you have already proven rather than a hunt for an interface. If it
   stays plugged in, make sure nothing (a sequencer, clock, DAW) is sending on
   it during the transfer.
6. **Low volume** for the first notes.
7. **Run the regression check** below before using it for music.
8. If anything is off: **recovery to stock 1.11**, then report what you saw.

### Regression check after a flash (about 10 minutes)

- Boots normally, no `EXCEPTION` screen.
- In a scratch project, one track each of **FM Tone, FM Drum, WaveTone,
  Swarmer**, and a **MIDI** track: all play and sound as before.
- Chorus, delay and reverb sends; the master overdrive and compressor.
- Pattern change, song mode, a parameter lock, an LFO on a stock machine.
- SAVE PROJECT, power-cycle, reload: everything comes back.
- Overbridge / USB audio if you use it.
- Then the new feature's own test.

---

## Rules for code written here

- Only sections 3 and 7 change. Enforced, not remembered.
- Never build on anything but stock 1.11, checked by hash.
- No DSP instruction form that isn't found byte for byte in stock's code.
- Every new engine sanitises its output (NaN/inf → 0, clamp) before the
  stock per-track chain.
- No raw +Drive writes. User data goes through formats DNX has measured.
- A feature reaches the instrument only after its gates pass, and only one
  new thing per flash.

## Residual risk, said plainly

These measures make a brick very unlikely, but they can't make it impossible.
The two remaining risks are the same ones every official update carries
(power loss while flash is being written, and flash wear or failure), plus
the downgrade case above. Everything else this project can do wrong is
recoverable over DIN MIDI, and is caught in the emulator before it gets there.
