# Firmware versions

Every build of this mod, newest first, with what it adds and what to test after
flashing it. Each build **contains everything before it**, so you only ever flash the
newest one. All builds are on stock Digitone II **OS 1.11**.

**Download:** the `.syx` files are on the **`builds`** branch, one folder per
version (`builds/vX.Y-NAME/`), each beside its gate record (`.gate.json`). On GitHub,
switch the branch selector from `main` to `builds`, open the version's folder, click
the `.syx`, then **Download raw file**. They are kept off `main` so that the code
branch never holds Elektron firmware (see the note at the end).

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
| **v0.4** | 2026-10-13 | PING filter type (SVF / LADR / VCFQ / LPG) on the FLTR page, any machine | `builds/v0.4-PING/` | yes |
| v0.3 | 2026-10-11 | Waverider W2: all page-1 controls, built-in scanner, its names in the LFO lists | `builds/v0.3-Waverider-W2/` | yes |
| v0.2 | 2026-10-11 | Waverider W5: 11 tables, POS glide, display that follows the sound | none (superseded) | before the gate |
| v0.1 | 2026-10-06 | Waverider: a wavetable machine in MACHINE SEL | none (superseded) | before the gate |

---

## v0.4 — PING filter

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
