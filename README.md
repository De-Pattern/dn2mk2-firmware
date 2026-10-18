# Firmware versions

Every build of this mod, newest first, with what it adds and what to test after
flashing it. Each build **contains everything before it**, so you only ever flash the
newest one. All builds are on stock Digitone II **OS 1.11**.

**Download:** the `.syx` files are on the **`builds`** branch, one folder per
version (`builds/vX.Y-NAME/`), each beside its gate record (`.gate.json`). On GitHub,
switch the branch selector from `main` to `builds`, open the version's folder, click
the `.syx`, then **Download raw file**. They are kept off `main` so that the code
branch never holds Elektron firmware (see the note at the end).

**v0.4 to v0.7 are withdrawn (2026-10-18).** Their images are larger than the 2 MiB the
OS's USB upgrade receives into, and the receiver does not check: the transfer stalls at
the very end (nothing is written to flash; a power cycle clears it). Their sections
below are kept for the record; the files are gone from `builds`. Every build from v0.8
on is checked against that limit by the gate (`docs/usb-upgrade-limit.md`).

**Only flash a file whose sha256 matches its gate record** (`CLEARED TO FLASH` from
`scripts/ship_gate.py`; CLAUDE.md). The sha256 is listed below and in the
`.gate.json` beside it. On Windows: `certutil -hashfile FILE SHA256`.

Every flash, every version:

1. **Back up the +Drive** with Elektron Transfer.
2. **Low volume.** Flash over USB as usual; keep the proven DIN recovery cable at hand.
3. Run the **regression check** (about 10 minutes, `docs/SAFETY.md`): boots with no
   `EXCEPTION`; one track each of FM Tone, FM Drum, WaveTone, Swarmer and a MIDI track
   all play as before; chorus, delay, reverb, master overdrive and compressor;
   pattern change, song mode, a p-lock, an LFO on a stock machine; SAVE PROJECT,
   power-cycle, reload.
4. Then the version's own tests, below. If anything is off: recovery to stock 1.11,
   then tell Claude what you saw.

| version | date | adds | download | gated |
|---|---|---|---|---|
| **v0.8** | 2026-10-18 | Everything in v0.7 (CZ PHASE, RESONATOR, SHIFT, PING, Waverider), sized to fit the USB upgrade: Waverider has 9 tables (BITS, PHAS out) | `builds/v0.8-CZ/` | yes |
| v0.7 | 2026-10-18 | CZ PHASE machine (Casio CZ phase distortion), 8-step DCW envelope on pages 2–3, up to 6 voices | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.6 | 2026-10-18 | RESONATOR machine (Rings-style modal resonator), up to 4 voices | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.5 | 2026-10-18 | SHIFT filter type (frequency shifter) beside PING; DSP memory packed tighter | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.4 | 2026-10-13 | PING filter type (SVF / LADR / VCFQ / LPG) on the FLTR page, any machine | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.3 | 2026-10-11 | Waverider W2: all page-1 controls, built-in scanner, its names in the LFO lists | `builds/v0.3-Waverider-W2/` | yes |
| v0.2 | 2026-10-11 | Waverider W5: 11 tables, POS glide, display that follows the sound | none (superseded) | before the gate |
| v0.1 | 2026-10-06 | Waverider: a wavetable machine in MACHINE SEL | none (superseded) | before the gate |

---

## v0.8 — CZ PHASE, sized for the USB upgrade

`DN2mod_v0.8_CZ_OS1.11.syx`
sha256 `5301fb4169f9d5f97c35109a15216c847e69106b56e06dc571ca4f6562fdf897`
Gate: CLEARED TO FLASH, 2026-10-18, including the new USB-size check (2,076,863 of
2,097,152 bytes, 20,289 to spare). Source: commit `89b057b`. Docs: `docs/cz.md`,
`docs/usb-upgrade-limit.md`.

**What it is.** v0.7's contents (CZ PHASE, RESONATOR, SHIFT, PING, Waverider W2) in an
image small enough for the OS's USB upgrade: Waverider's factory set is **9 tables**
(PRIM HARM PWM SYNC VOX FM FOLD ORGN RESO); BITS and PHAS are out. v0.4 to v0.7 never
install over USB (see the top).

**Test:** flash over USB from Transfer as usual; it should finish and reboot like stock.
Then the v0.7 tests below (CZ, 1–11), then v0.6 (RESONATOR), v0.5 (SHIFT) and v0.4
(PING) — none of them has run on hardware yet — and Waverider: TBL now steps through 9
tables (a saved Waverider sound may land on a different table).

**Known:** as v0.7 (CZ's steps after sustain do not run at note-off). The image is 20 KB
under the USB limit; new features must pay for their size.

---

## v0.7 — CZ PHASE (Casio CZ phase-distortion machine) — WITHDRAWN (over 2 MiB, see the top)

`DN2mod_v0.7_CZ_OS1.11.syx`
sha256 `0751bb0dfab83d4e9d227db7d1f9eb1ce2a1967b0e93d3db40e5901cf56c4527`
Gate: CLEARED TO FLASH, 2026-10-18. Source: commit `37fd1f4`. Docs: `docs/cz.md`.

**Adds.** A new machine, **CZ PHASE**, in MACHINE SEL after RESONATOR: the CZ-101 /
CZ-3000's phase distortion. Eight waves (saw, square, pulse, double, saw-pulse, and the
three resonance waves) and their pairs, two lines, ring and noise, and the CZ's 8-step
DCW envelope across pages 2 and 3. The DCA is the DN2's AMP page. Polyphonic up to
**6 voices** (a 7th and 8th are silent, by design). Everything else is as v0.6.

    page 1  WAVE  SEL   DET   OCT   /  MOD   DCW   KF    SUS
    page 2  R1    R2    R3    R4    /  L1    L2    L3    L4
    page 3  R5    R6    R7    R8    /  L5    L6    L7    L8

| control | what it does |
|---|---|
| WAVE | 33 choices: the 8 waves, then pairs (e.g. SW+SQ) that alternate cycle by cycle |
| SEL | lines: 1, 2, 1+1' (line 2 detuned), 1+2' (line 2 detuned, octave, MOD) |
| DET | line 2 detune, ±1 semitone |
| OCT | line 2 octave: 0, +1, −1 |
| MOD | in 1+2': RING, OFF, NOISE |
| DCW | how far the envelope bends the wave (0 = sine) |
| KF | key follow: higher notes duller |
| SUS | which step the envelope holds on (SUS1–SUS8), or NOSUS |
| R1–R8 / L1–L8 | the DCW envelope: rate and level of each step |

Page 1 draws the wave pair as it sounds at the top of the envelope; pages 2 and 3 draw
the envelope, the page's four steps solid, the sustain step marked.

**Test:**
1. FUNC + SYN, scroll to **CZ PHASE** (after RESONATOR), YES.
2. Page 1 reads SAW 1 DET OCT0 / OFF DCW KFOFF SUS1 with a wave in the middle. Turn
   WAVE: the label and the picture change (SAW, SQR… then pairs like SW+SQ).
3. Play: a bright saw that settles. DCW to 0: a pure sine. DCW up: brighter.
4. Pages 2 and 3 (press SYN again): the envelope picture follows R1–R8 / L1–L8. Set
   SUS to NOSUS and short rates: a plucky sweep; long rates: slow filter-like sweeps.
5. SEL 1+1' with DET a little off centre: chorus-like doubling. SEL 1+2', OCT +1,
   MOD RING: bell tones; MOD NOISE: a gritty, noisy line.
6. WAVE on RS1 / RS2 / RS3 with the envelope sweeping: the CZ resonance sweep.
7. Chords up to 6 notes (VOICE SETUP 6 or fewer): all sound.
8. **Load test:** 6 CZ voices plus 4 RESONATOR voices plus a busy pattern: any crackle?
   (Not measured on hardware; about 7,700 cycles a CZ voice a block, by instruction count.)
9. Save a CZ sound, reload: still CZ PHASE. Save the project, power-cycle, reload.
10. WaveTone's page 3 still shows its own envelope widgets (this build re-routes page 3
    for CZ tracks only).
11. RESONATOR (moved its tables and scratch to make room), PING, SHIFT and Waverider
    briefly, as in v0.6.

**Known:** the steps after the sustain step do not run at note-off yet (the envelope
holds on SUS until the next note; the frame's note-off is not located). The AMP
envelope still ends the note. One wave choice and one DCW envelope for both lines
(the DN2 sound has 25 machine parameters). A CZ sound loads as FM Tone on stock firmware.

---

## v0.6 — RESONATOR (Rings-style machine) — WITHDRAWN (over 2 MiB, see the top)

`DN2mod_v0.6_RESONATOR_OS1.11.syx`
sha256 `920ee105803cd1114770b38bdf94b8de325539c73b31371144795d495f5dd847`
Gate: CLEARED TO FLASH, 2026-10-18. Source: commit `8e6854e`. Docs: `docs/rings.md`.

**Adds.** A new machine, **RESONATOR**, in MACHINE SEL after WAVERIDER. Each note hits a
bank of 24 resonant modes with a mallet or a noise burst: strings, marimba bars, bells,
plates, glass and drums. Polyphonic up to **4 voices** (set the track's VOICE SETUP to
4 or fewer; a 5th and 6th voice are silent, by design, to keep the DSP load bounded).

    TUNE  LEV   STRC  BRIT  /  DAMP  POS   EXCT  HIT

| control | what it does |
|---|---|
| TUNE | pitch, ±5 octaves |
| LEV | level (100 = unity) |
| STRC | structure: left = harmonic (a string), middle = a bar (marimba), right = a plate / bell |
| BRIT | brightness: the mallet's hardness, and how fast the high modes die |
| DAMP | decay, 0.1 s to 12 s |
| POS | where it is hit: the middle mutes every other mode (hollow), the edge keeps them all |
| EXCT | the exciter: left = mallet, right = a noise burst, between = both |
| HIT | how hard it is hit |

The page draws the modes as lines: STRC moves their spacing, POS their heights.

**Test:**
1. FUNC + SYN, scroll to **RESONATOR** (after WAVERIDER), YES. VOICE SETUP: 4 voices.
2. The page reads TUNE LEV STRC BRIT / DAMP POS EXCT HIT, with the lines in the middle.
3. Play notes: a long, bright string (the defaults). Sweep STRC left to right: string →
   marimba → bell. Then BRIT and DAMP short for drums; POS for hollow vs full.
4. EXCT to the right with a low note: a noisy, struck plate.
5. Chords of 3–4 notes: all sound. A 5-note chord with VOICE SETUP above 4: the extra
   notes are silent (expected).
6. **Load test:** 4 voices ringing with long DAMP plus a busy pattern on other tracks:
   any crackle or dropouts? (Not measured on hardware yet; estimated ~8 % of the DSP.)
7. RESONATOR through PING and SHIFT (FLTR page): works on it like any machine.
8. LFO page on a RESONATOR track: DEST shows Structure, Brightness, Damping…; a
   WaveTone or Waverider track: their own names.
9. Save a RESONATOR sound, reload: still RESONATOR. Save the project, power-cycle,
   reload.
10. The v0.5 / v0.4 tests briefly (PING, SHIFT, Waverider as before).

**Known:** MODAL only (the plucked STRING model in the first demo is not in the machine:
a delay line a voice does not fit the DSP memory; STRC at the left is the string-like
setting). Low notes with the bright default can push into a soft limiter (LEV down).
A RESONATOR sound loads as FM Tone on stock firmware.

---

## v0.5 — SHIFT (frequency shifter) — WITHDRAWN (over 2 MiB, see the top)

`DN2mod_v0.5_SHIFT_OS1.11.syx`
sha256 `1ff987df0d6dd8ef3ed718682bf9e899b1f9af2fe8b71995c29d66a63e315e98`
Gate: CLEARED TO FLASH, 2026-10-18. Source: commit `be8d0ad`. Docs: `docs/shft.md`.

**Adds.** An 8th filter type, **SHIFT**, last in the FLTR tab (after PING), on every
machine. A frequency shifter: every partial moves by the same number of Hz, so sounds
go metallic and bell-like, small shifts shimmer, and feedback makes the endless
"barber-pole" climb. It takes the track's filter slot (no low-pass on a SHIFT track;
BASE / WDTH on page 2 still work).

    FLTR page 1   ATK  DEC  MIX  -    /  SHFT FDBK MODE ENV
    FLTR page 2   DRIV  .    .   KEY.T / BASE WDTH BW.RT RSET

| control | what it does |
|---|---|
| SHFT | the shift: centre (64) is none, left shifts down, right up, to ±2.5 kHz; fine near the centre |
| FDBK | feedback through the shifter (the barber-pole), soft-limited |
| MODE | thirds: UP (shifts the way SHFT points), DOWN (the opposite way), BOTH (both sidebands: ring-mod bells) |
| ENV | the envelope's push on the shift (centre is none) |
| ATK / DEC | the envelope, restarted by each note |
| MIX | dry → wet |
| DRIV | level into the shifter |
| KEY.T | the shift follows the note |

Also: the DSP code's empty blocks now load as "fill" blocks, as Elektron's own code
does; the DSP memory after boot is identical, with 10.6 KB more room in the upload.

**Test:**
1. A WaveTone or FM track: FUNC + SYN, RIGHT to FLTR, scroll to **SHIFT** (last), YES.
2. The FLTR page reads ATK DEC MIX - / SHFT FDBK MODE ENV.
3. MIX to the top. SHFT a little right of centre on a held chord: slow shimmer. Further:
   metallic. Left of centre: shifts down.
4. MODE through its thirds (UP, DOWN, BOTH) with SHFT ~ 3/4 right.
5. FDBK up with SHFT just off centre on a long note: the endless climb (or fall). Turn
   FDBK fully up: it must stay controlled, never blast.
6. ENV up, short DEC, on hits: a zap on each note.
7. PING and SHIFT on different tracks at once; then switch a SHIFT track back to
   Multi-Mode: stock labels return and it sounds as before.
8. Save a sound with SHIFT, load it back: still SHIFT. Save the project, power-cycle,
   reload.
9. The v0.4 PING tests, briefly.

**Known:** SHFT's readout is Multi-Mode's cutoff number, not Hz (64 = no shift); MODE's
icon is Multi-Mode's LP/BP/HP picture; REL on page 1 does nothing (`-`).

---

## v0.4 — PING filter — WITHDRAWN (over 2 MiB, see the top)

`DN2mod_v0.4_PING-filter_OS1.11.syx`
sha256 `86fc590931251776b14b7bad075336177f5b20aca60fc6c8bf557ec892d427dc`
Gate: CLEARED TO FLASH, 2026-10-13. Source: commit `43e4d58`. Docs: `docs/ping.md`.

**Adds.** A 7th filter type, **PING**, last in the FLTR tab of MACHINE SEL
(FUNC + SYN, then RIGHT to the FLTR tab). It works on every machine, the stock ones
included. A resonant filter with its own fast envelope and a built-in strike, made for
liquid, hard-hitting pings and percussion.

    FLTR page 1   ATK  DEC  CURV STRK  /  FREQ RING TYPE ENV
    FLTR page 2   DRIV  .    .   KEY.T /  BASE WDTH BW.RT RSET

| control | what it does |
|---|---|
| TYPE | the core, in four ranges low to high: **SVF** (clean, glassy), **LADR** (Roland-style, thick), **VCFQ** (Serge-style ping), **LPG** (vactrol low-pass gate, the bongo) |
| FREQ | the cutoff / the ring's pitch |
| RING | how long it rings (the resonance) |
| ATK / DEC | PING's own envelope, from 0.1 ms |
| CURV | the envelope's curve: log ← lin → exp |
| STRK | the level of the built-in strike (the "hit") |
| ENV | the envelope's depth on the cutoff |
| DRIV | the drive into the filter |
| KEY.T | how far the cutoff follows the note |

**Test:**
1. A WaveTone or FM track: FUNC + SYN, RIGHT to FLTR, scroll to **PING**, YES.
2. The FLTR page shows ATK DEC CURV STRK / FREQ RING TYPE ENV, with the curve under
   FREQ and RING moving as you turn them.
3. TYPE at the top (LPG), FREQ mid, RING up, DEC short: a round, bongo-like ping.
   Then each TYPE range (SVF, LADR, VCFQ) by ear. **Note how each sounds**, and any
   setting that is too quiet, too loud, harsh or blown out.
4. Turn STRK up and down; CURV left and right with a long DEC.
5. Choose another filter (e.g. Multi-Mode): the stock labels (SUS, REL, RESO) come back
   and it sounds as before.
6. Save a sound with PING, load it back: still PING. Save the project, power-cycle,
   reload.
7. **Load test:** PING on 4–8 tracks playing at once: any crackle or dropouts?
8. The v0.3 tests, briefly (Waverider still as before).

**Known:** TYPE's icon is Multi-Mode's LP/BP/HP picture, not the four PING names; the
curve drawn is Multi-Mode's shape. A sound saved with PING loads as Multi-Mode on stock
firmware.

---

## v0.3 — Waverider W2

`DN2mod_v0.3_Waverider-W2_OS1.11.syx`
sha256 `8cd7236c2e84b8e931174b91c99f16393cd899b6bcd602ea6de044ffee194da0`
Gate: CLEARED TO FLASH, 2026-10-11. Source: commit `3514819`. Docs: `docs/w2-scanner.md`.

**Adds.** Every control on Waverider's page 1, and a scanner (a per-voice modulator):

    TUNE   LEV    POS    TBL   /   RATE   MPOS   MLEV   MOVE

LEV (level), RATE (scanner speed), MPOS (sweep depth on POS, ±), MLEV (depth on level,
±), MOVE (shape: TRI SAW RAMP SQR RND S&H ONE ENV). Waverider's names in the LFO and
modulation destination lists. Defaults change nothing in a v0.2 sound.

**Test:**
1. A v0.2 sound sounds exactly as before.
2. Page 1 shows all eight: LEV, RATE, MPOS, MLEV, MOVE (with the shape's name).
3. MPOS up, RATE ~60, MOVE `TRI`: the timbre sweeps the table. Try `ONE`, `RND`, `S&H`.
4. MLEV up with MOVE `ENV`: each note decays. MLEV down with `SQR`: a gate.
5. LFO page on a Waverider track: DEST lists *Wave Table*, *Wave Position*,
   *Scan Rate*… A WaveTone track: WaveTone's names, unchanged.

---

## v0.2 — Waverider W5 (superseded, no download)

Built before the ship gate existed, so it is not offered; v0.3 and later contain all
of it. 11 factory tables (`PRIM HARM PWM SYNC VOX FM FOLD ORGN RESO BITS PHAS`), TBL
shows the table's name, POS glides (~21 ms) instead of stepping, the wave display
follows what you hear. Docs: `docs/w5-tables.md`.

## v0.1 — Waverider (superseded, no download)

Built before the ship gate existed. WAVERIDER in MACHINE SEL: a wavetable machine,
polyphonic (set VOICE SETUP above 1), two tables, TUNE / POS / TBL. Flashed and
working on the owner's unit, 2026-10-11.

---

**About where the files live.** The repository's `.gitignore` says it holds no
Elektron firmware, original or modified: a modified build is Elektron's OS with our
changes in it. That keeps `main` safe to make public one day. The builds branch is
private with the repository; **delete the `builds` branch before the repository is
ever made public.**
