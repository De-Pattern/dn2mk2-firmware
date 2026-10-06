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
| **The bootstrap is rewritten by a downgrade.** Elektron: *"After some upgrades the bootstrap is also upgraded… right after the first restart."* | as above, if power fails during it | Stay on the version the mods are built for (**1.11**). Our builds carry 1.11's bootstrap byte for byte, so a unit already on 1.11 has nothing to rewrite. **If your unit is on 1.12, read "Getting onto 1.11" below first.** |
| **A build crashes MAIN OS or won't boot** | recoverable | Recovery runs from the bootstrap, not MAIN OS: [FUNC] at power-on → [TRIG 4] → stock 1.11 over **DIN MIDI**. Every build also boots from reset in the emulator first (`scripts/emu_boot_check.py`). |
| **The DSP stops and the unit goes silent** | recoverable | Upstream hit exactly this (`docs/waverider-dsp-silence.md`) and recovered by reflashing. Every build runs the DSP code in the SHARC emulator first; our code uses only instruction encodings found byte for byte in stock (the rule after upstream's negative-shift bug). |
| **Loud noise, DC or full-scale output** from a DSP bug | can harm speakers and ears | First test of every DSP build: **low volume, no headphones, monitors down.** And a rule for our DSP code: every engine sanitises its output (NaN/inf → 0, hard-clamped) before it reaches the stock chain. |
| **A stock machine, FX or the sequencer behaves differently** | a bug, not damage | The DSP gate checks that with no mod track playing, all 16 track buffers are **bit-identical to stock**, and that stock tracks beside a mod track are too (`scripts/sharc_waverider_m5.py` step 4). The ColdFire side lists every edit it makes; each is asserted against the stock bytes before it is written. |
| **Projects or sounds are damaged** | data loss | Back up the +Drive with Elektron Transfer before every flash. No mod writes to the +Drive directly. A track saved with a mod machine loads on stock firmware as FM Tone with its parameters kept. Upstream's `songguard` mod exists because a damaged project can halt even stock firmware, so test in a scratch project and keep real work out of it until a feature has been stable for a while. |
| **The recovery transfer stalls** (bar stops at e.g. 80 %) | annoying, not harmful | That's the MIDI link dropping packets, not the image. Upstream traced it to an interface going idle mid-transfer. Use a dedicated class-compliant USB-MIDI interface and turn off USB power-saving. Just retry: nothing is written to flash until reception completes. |

---

## Before the first flash, once

1. **Back up everything** with Elektron Transfer (projects, presets, samples).
2. **Prove recovery on your unit with stock 1.11**: DIN cable from the
   computer's MIDI OUT to the DN2's MIDI IN, hold [FUNC] at power-on, [TRIG 4],
   Transfer's *Legacy OS upgrade mode*, send `Digitone_II_OS1.11.syx`. It takes
   about 12 minutes; don't interrupt. Note which interface you used: that's
   your recovery cable from now on.
3. Confirm the unit boots stock 1.11 and plays normally.

Until step 2 has worked once, flash nothing modified.

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
2. **Gates** pass on this exact build: boot from reset, and for anything that
   touches the DSP, the SHARC runner, including the stock-unchanged step.
3. **Preflight the file you will actually send:**
   `dnfw preflight Digitone_II_OS1.11.syx build.syx` must print `PASS`.
4. **Back up** the +Drive.
5. **Flash** through the normal Transfer drop over USB. Keep the DIN recovery
   cable connected and ready.
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
