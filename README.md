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
| **v0.17** | 2026-10-22 | PERC is the Machinedrum: its 25 TRX/EFM/GND machines from the MD's own firmware (every reference case matches), TYPE p-lockable as before | `builds/v0.17-MACHINEDRUM/` | yes |
| v0.16 | 2026-10-22 | 96 MB of your samples on the +Drive, loaded at power-on over a fast checked link; recordings kept after power-off; the SAMP name list; waveforms for every slot | `builds/v0.16-DRIVE/` | yes |
| v0.15 | 2026-10-22 | DT2 SRC pages (knobs, waveform, RECORDER), one encoder click a choice, value names in the header, loops follow the knobs live; RECORDER: SRC IN/MAIN/TRK1-16, CHAN, YES records, ARM, R.LEN, R.STRT | `builds/v0.15-RECORDER/` | yes |
| v0.14 | 2026-10-22 | Sampling: page 2 of every sample machine records IN / IN L / IN R / MAIN into SAMP 124-127 (threshold, length); ONESHOT's CFAD heard | `builds/v0.14-SAMPLING/` | yes |
| v0.13 | 2026-10-22 | The Digitakt II's sample machines (ONESHOT, WERP, STRETCH, REPITCH, GRID) with DT2-style pages; four test sounds; your WAVs over USB, kept on the +Drive | `builds/v0.13-SAMPLER/` | yes |
| v0.12 | 2026-10-21 | PERC: labels follow TYPE; page 1 the machine's 8 parameters; page 2 TYPE + Machinedrum effects (AMD AMF EQF EQG FLTF FLTW FLTQ); no stray ring | `builds/v0.12-PERC-FX/` | yes |
| v0.11 | 2026-10-20 | PERC: your 24 Ravel drum machines (TRX/EFM/GND) as a machine, TYPE + 8 named parameters; Waverider removed | `builds/v0.11-PERC/` | yes |
| v0.10 | 2026-10-20 | No more dead notes on RESONATOR/CZ (voice stealing); PING/SHFT TYPE by name; Waverider osc 2 (page 2); GRAN granular filter type | `builds/v0.10-GRAN/` | yes |
| v0.9 | 2026-10-19 | CZ's release: the DCW envelope runs on past its sustain step at note-off, as on a real CZ | `builds/v0.9-CZ-release/` | yes |
| v0.8 | 2026-10-18 | Everything in v0.7 (CZ PHASE, RESONATOR, SHIFT, PING, Waverider), sized to fit the USB upgrade: Waverider has 9 tables (BITS, PHAS out) | `builds/v0.8-CZ/` | yes |
| v0.7 | 2026-10-18 | CZ PHASE machine (Casio CZ phase distortion), 8-step DCW envelope on pages 2–3, up to 6 voices | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.6 | 2026-10-18 | RESONATOR machine (Rings-style modal resonator), up to 4 voices | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.5 | 2026-10-18 | SHIFT filter type (frequency shifter) beside PING; DSP memory packed tighter | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.4 | 2026-10-13 | PING filter type (SVF / LADR / VCFQ / LPG) on the FLTR page, any machine | **withdrawn**: too big for the USB upgrade (`docs/usb-upgrade-limit.md`) | yes, but over 2 MiB |
| v0.3 | 2026-10-11 | Waverider W2: all page-1 controls, built-in scanner, its names in the LFO lists | `builds/v0.3-Waverider-W2/` | yes |
| v0.2 | 2026-10-11 | Waverider W5: 11 tables, POS glide, display that follows the sound | none (superseded) | before the gate |
| v0.1 | 2026-10-06 | Waverider: a wavetable machine in MACHINE SEL | none (superseded) | before the gate |

---

## v0.17 — PERC is the Machinedrum

`DN2mod_v0.17_MACHINEDRUM_OS1.11.syx`
sha256 `9803119ed145485d8b5c9e1067eaec366b4bb24a8d08128f85634e5936cb878c`
Gate: CLEARED TO FLASH, 2026-10-23 (USB size 1,982,125 of 2,097,152; DSP 1,037,552 of 1,048,575). Source: commit `f98caa6`. Docs: `docs/md.md`.

**Adds.**
- **PERC's drum machines are the Machinedrum's own** (SPS-1 UW, OS 1.63): all 25 — TRX
  BD B2 SD XT CP RS CB CH OH CY MA CL XC S2, EFM BD SD XT CP RS CB HH CY, GND SN NS IM —
  ported from DSP2's code in your Machinedrum firmware file and checked against the MD's
  own output, case by case (most within 75..120 dB of it, several bit-exact). They run at
  the MD's 44.1 kHz and are resampled to the DN2's 48 kHz.
- **TYPE stays** (page 2, with the track effects AMD..FLTQ): it picks one of the 25 and
  is latched by each note, so p-locking TYPE still plays a different machine on each step.
- Page 1 is the machine's eight parameters under the MD's names; each knob lands on one of
  the MD's 128 positions.
- As on the Machinedrum, **the note does not tune** a machine (PTCH does).

**Test** (after the regression check; **back up the +Drive first**):
1. A PERC track: turn TYPE through all 25; each name shows and each sounds on a trig
   (TRX-MA, the maracas, builds up over a second).
2. P-lock TYPE on a few steps: each step plays its own machine.
3. Page 1: the eight names change with TYPE; turn each knob on a few machines.
4. Page 2: AMD..FLTQ still change the sound.
5. If you have your Machinedrum: same machine, same settings, side by side.
6. **DSP load**: eight PERC tracks of TRX-CY / EFM-CY / TRX-CH ringing together, with the
   rest of a busy pattern: listen for crackles or dropouts and report them.
   (`python tools/dn2sharc_load.py` on a usbprobe build measures it.)
7. The sample machines play your +Drive samples as before (SAMP 1..).

**Known issues.**
- **The four test sounds are gone from the image** (the Machinedrum's tables needed the
  room): SAMP 1..4 are empty until you send samples (`tools/dn2samples.py send`), which
  then load at every power-on as in v0.16.
- **TYPE's machines changed**: a sound saved with a PERC TYPE on v0.11..v0.16 (the Ravel
  set) now plays the MD machine at that TYPE position.
- **DSP cost**: the MD's machines are heavier than the Ravel ones: 3.5k..31k DSP
  instructions a block each (a stock synth is about 8..11k); TRX-CP/CY/MA/S2 and the EFMs
  are the heavy ones. A machine stops costing anything once its sound has died away, but
  many long cymbals at once could overload the DSP (crackles). Not measured on the
  instrument yet.
- For the first 0.7 s after power-on the DSP is still filling the MD's sine and tables
  (a note in that time sounds wrong).
- PERC's level (0.7 of the MD's full scale) is a guess; how it sits beside the DN2's own
  machines is for you to say.

## v0.16 — 96 MB of samples on the +Drive, recordings kept, the sample list

`DN2mod_v0.16_DRIVE_OS1.11.syx`
sha256 `98da318511036ff8acf8349f8f0d83c7052f35270a75774aa8570f0dd665af29`
Gate: CLEARED TO FLASH, 2026-10-22 (USB size 1,961,622 of 2,097,152). Source: commit `b502e6d`. Docs: `docs/sampler.md` (v0.16 section), `docs/link-research.md`.

**Adds.**
- **128 MB sample pool**: 96 MB for your samples (about 18 minutes of 16-bit mono at
  44.1 kHz, up from 5 MB), and four recorder slots of 8 MB (a recording runs up to 66 s).
- **Your samples live on the +Drive** and load at every power-on, as the DT2's do: the
  tool (`tools/dn2samples.py send ...`, update it from the repo) writes them straight to
  the +Drive's private region, then the instrument loads them into the DSP. `--keep` and
  `save` are no longer needed.
- **Recordings are kept**: when the RECORDER stops, the recording is saved to the +Drive by
  itself and SAMP 124..127 still hold it after a power cycle.
- **A fast link** to the DSP (spare TDM slots, about 0.7 MB/s; 20× v0.15's), every 64 KB
  checked by the DSP's own sums and sent again if wrong; if the fast link does not
  check out it falls back to the old one (slow, but always there).
- **Slots play as soon as they are in**: while a big pool loads, each sample becomes
  playable when its frames have arrived.
- **The sample list**: turning SAMP shows five sample names around the chosen one for a
  second, the chosen one framed.
- **The waveform** (SYN page 2) is drawn for every slot, the recorder's included, and for
  samples of any length.

**Test** (after the regression check; **back up the +Drive first**):
1. Power on with nothing sent: the four test sounds play as before (SAMP 1..4).
2. `python tools/dn2samples.py hello`: "sample link 3: room for 100,663,296 bytes".
3. `send` a folder of a few WAVs: the tool shows "to the +Drive" then "into the DSP"
   and says whether the fast link was used. Play them on SAMP 1..
4. Send something big (tens of MB): note the time "into the DSP" took, and whether it said
   "(slow link)".
5. Power-cycle: the samples come back by themselves (a big pool takes a while; small
   samples are playable first).
6. RECORDER: record a few seconds into SAMP 124 (YES, YES). Wait a few seconds, power-cycle:
   SAMP 124 still plays it, and page 2 draws its waveform.
7. Send samples again after recording: the recording is still in SAMP 124.
8. Turn SAMP on SYN page 1 or 2: the list of names appears and goes after a second.
9. `python tools/dn2samples.py status`: `fast_link` 1 is the fast link working; 0 is the
   fallback; `retried` counts chunks sent again.

**Known issues.**
- The fast link and the readback of recordings rely on two TDM details only the hardware
  can confirm (which 24 bits arrive, and that slots 14..15 come back from the DSP).
  If either is wrong the samples still load over the slow link (36 KB/s: 5 MB takes
  about 2.5 minutes; 96 MB would take most of an hour), and recordings are not kept
  (`status` shows `fast_link` 0). Please report what `status` says.
- A full 96 MB pool takes over two minutes to load at power-on even on the fast link.
- Writing to the +Drive happens while you play (64 KB at a time); a project save at the
  same moment waits for it.
- The sample list's timing comes from the audio clock; how it feels is for the
  instrument to say.

## v0.15 — DT2 pages, the RECORDER, track sampling, live loops

`DN2mod_v0.15_RECORDER_OS1.11.syx`
sha256 `ac54c048b93474ed8f0bd12abd07966b8589400710de75150f9c59c535df2edf`
Gate: CLEARED TO FLASH, 2026-10-22 (USB size 1,957,986 of 2,097,152). Source: commit `6032b50`. Docs: `docs/sampler.md` (v0.15 sections), `docs/link-research.md`.

**Adds.**
- **Loops and reverse follow the knobs while they play**: on ONESHOT, STRETCH and REPITCH,
  turning LEN, LOOP, STRT or PLAY changes a held loop at once (before, only the next trig
  did). GRID takes its slice at the trig; WERP its segments. A loop lasts as long as the
  track's AMP envelope, as on the DT2: set AMP's hold/sustain long to hear it loop.
- **One encoder click a choice** on PLAY, WERP's MODE, BARS, SEG, GRID, SLCE/LEN (GRID)
  and the recorder's SRC; ARM, R.STRT, CHAN and DEST step natively.
- **The header names the value**: REV / REV LOOP / FWD LOOP / FWD, 1/4, 1/16, OFF / ON,
  MONO L, TRK3, and SAMP shows the sample's name (KICK, your WAV's name, REC 1..4). No
  more "Prim." / "Harm.".
- **The DT2's SRC pages**: SYN page 1 the knobs (labelled), page 2 the same with the
  waveform, the machine box reading SMP; widgets redrawn after the DT2's (TUNE's value in
  its box, whole knob rings, the dotted square, BARS blocks, the SEG icon).
- **The RECORDER**, SYN page 3 of every sample machine, laid out as the DT2's: SRC (IN,
  MAIN, **TRK1..TRK16**), CHAN (MONO L+R / L / R), the RECORD NOW box (**YES** records,
  YES again stops), THRES, DEST (SAMP 124..127), R.LEN (MAX or steps at the tempo),
  R.STRT (THRES or PLAY: the first note of the pattern), ARM (turn to arm, turn again to
  stop), and an input meter. **Nothing about the recorder is saved with a sound** any
  more.
- CFAD is gone from ONESHOT (the DT2's ONESHOT has an empty place there).

**Test** (after the regression check; **back up the +Drive first**):
1. ONESHOT, SAMP 1 (KICK) or a longer sample of yours: SYN page 1 shows knobs with labels;
   SYN again: the waveform page; SYN again: RECORDER; SYN again: back to page 1.
2. PLAY: each click is one mode (FWD, FWD LOOP, REV LOOP, REV), and the header names it.
3. Set AMP hold/sustain long. PLAY FWD LOOP, hold a note (or a long trig): turn LEN and
   LOOP while it plays: the loop's end and start move at once. Switch PLAY to REV LOOP
   while it plays: it turns round. STRETCH and REPITCH: the same with LEN.
4. SAMP: the header shows KICK, SNARE, HAT, BEAT (or your samples' names).
5. WERP: SEG and BARS and MODE one click a choice; GRID: GRID, SLCE one click each.
6. RECORDER: a synth into the inputs, SRC IN, the meter moves with it. YES: the box shows
   REC and the seconds; YES again: stops. Page 1, SAMP 124: your recording.
7. THRES up to about the middle, ARM (turn H): the box says ARMED; play loud: it records.
   R.STRT PLAY, ARM, then start the pattern: it starts with the pattern.
8. SRC TRK3 (a track playing a pattern), YES, a few bars, YES; SAMP 125 (set DEST first):
   track 3's sound. SRC MAIN: the whole mix.
9. R.LEN 16 (steps): it stops by itself after a bar.
10. SAVE PROJECT with the RECORDER page showing ARM turned on, power-cycle, reload: nothing
    records on its own.

**Known issues.**
- Recordings are still lost at power-off (keeping them on the +Drive is the next build),
  and the waveform is not drawn for SAMP 124..127.
- The TRK sources and the input meter read DSP buffers whose meaning was read from the
  code (`docs/link-research.md`), not yet heard on the instrument: if TRK records the
  wrong track or the wrong level, say which.
- R.STRT PLAY starts at the first note any track plays, not at the PLAY key itself.
- The DN2's header is kept above the RECORDER (the DT2 shows a big "RECORDER" title).
- STEREO recording is not offered (the DN2's tracks are mono).
- The emulator showed the one-click-a-choice turns working, but its encoder is not a
  real one: how a fast spin feels is for the instrument to say.

## v0.14 — sampling, and CFAD

`DN2mod_v0.14_SAMPLING_OS1.11.syx`
sha256 `fd3253d66e16cd72c9ec7dc47e9b149820464a99588333b9cb134fe2beb0ac25`
Gate: CLEARED TO FLASH, 2026-10-22 (USB size 1,955,057 of 2,097,152). Source: commit `eb06398` (gated with the runner of `6a30218`). Docs: `docs/sampler.md` ("Page 2: sampling").

**Adds.**
- **Sampling**, as on the DT2: every sample machine (ONESHOT, WERP, STRETCH, REPITCH,
  GRID) has a **second page** (press **SYN** again): **REC** (the button fills when on),
  **SRC** (IN, IN L, IN R, or MAIN — the DN2's own mix), **THRS** (0 starts at once;
  above it waits for a hit that loud), **RLEN** (MAX = 21.8 s, else the seconds shown),
  **DEST** (the recorder's own slots, **SAMP 124-127**).
- What you record plays at once: set SAMP to its slot (124-127) on any sample track,
  and play it with every machine (GRID slices it, REPITCH fits it to BARS, ...).
- **CFAD on ONESHOT is heard now**: in FWD LOOP it crossfades the loop's end into the
  audio before LOOP, so a loop cut anywhere does not click. Drawn as a knob.
- Your USB samples use SAMP 1-122 (124-127 are the recorder's); the tool refuses more.

**Test** (after the regression check; **back up the +Drive first**, as always):
1. ONESHOT track, SAMP 1: CFAD (C) is a knob. PLAY to FWDL, LEN short, LOOP part-way;
   hold a note: with CFAD 0 the loop clicks, turned up it is smooth.
2. Page 2 (press SYN again): `Sampling (2/2)`, REC SRC THRS on top, RLEN (MAX) and DEST
   (`A 124`) below; the page dots show two pages.
3. A synth into the DN2's inputs. SRC IN, THRS 0, DEST 124: REC on, play a few seconds,
   REC off. Page 1: SAMP 124, play the track: your recording.
4. THRS up (half), REC on, wait (silence: nothing recorded), then play loud: it starts
   with the first hit.
5. SRC MAIN, DEST 125: record a pattern running on other tracks; SAMP 125 plays it.
6. RLEN to 1.0 s: the recording stops by itself after a second.
7. GRID on SAMP 125: slices of what you recorded.
8. `python tools/dn2samples.py send FOLDER` while a recording is in SAMP 124: your
   samples arrive in 1.., and SAMP 124 still plays the recording.
9. Leave REC off before SAVE (REC is saved with the sound; a sound saved with REC on
   starts recording when loaded).

**Known issues.**
- **Recordings are lost at power-off** and are not kept on the +Drive (`--keep` keeps
  only your USB samples): the ColdFire cannot read the DSP's memory back yet.
- The waveform is not drawn for SAMP 124-127 (same reason); the slot box shows the
  number.
- No input-level meter and no armed/recording indicator on page 2 (the DSP's state is
  not visible to the ColdFire); REC's button shows only that REC is on.
- One recorder: with REC on on several sample tracks, the lowest-numbered one records.
- The inputs are read as the DN2's engine converts them (the block the DSP's driver
  writes at `0x268538`); proven in the SHARC runner, not yet heard on the instrument.
  MAIN is the previous block's mix (one block, 0.7 ms, late).
- From v0.13: WERP/STRETCH/REPITCH are our readings of the manual; the widgets are close
  to the DT2's, not pixel-identical; the +Drive region (3 GiB in) and the DSP load with
  many STRETCH tracks are untested on the instrument.

## v0.13 — the Digitakt II's sample machines, and your samples

`DN2mod_v0.13_SAMPLER_OS1.11.syx`
sha256 `ae5637c4b5a04661179d7d36d1619901662958c0fa788f2328a7c0f659c61fdb`
Gate: CLEARED TO FLASH, 2026-10-22 (USB size 1,953,542 of 2,097,152). Source: commit `602ee63`. Docs: `docs/sampler.md`.

**Adds.**
- **Five Digitakt II machines** in MACHINE SEL, a section of their own after PERC,
  RESONATOR and CZ: **ONESHOT, WERP, STRETCH, REPITCH, GRID**.
- **Their pages look like the DT2's SRC page**: TUNE as the bipolar box, PLAY as the
  play icon, the dotted empty box, SAMP as the box with the bank letter and slot on top;
  ONESHOT and GRID show the sample's waveform across the middle with the start, end and
  loop (or slice) markers, STRT LEN LOOP (SLCE LEN GRID) under it and LEV as a pill;
  WERP, STRETCH and REPITCH show knobs, the SEG ring, MODE, BARS and the LEV fader.
- PLAY is REV, REVL, FWDL, FWD as on the DT2; SAMP 0 is OFF; BARS (1/8 to 16 bars)
  follows the DN2's tempo. Every control is an ordinary parameter: p-lockable (sample
  locks), an LFO destination, saved with the sound.
- **Four built-in test sounds** in slots 1-4 until you send your own: KICK, SNARE, HAT,
  BEAT.
- **Your own samples over USB**: `python tools/dn2samples.py send FOLDER --keep`
  (Windows, no packages; close Elektron Transfer first). The WAVs go to slots 1, 2, 3,
  ... with their names, and `--keep` stores them on the +Drive so they load at
  power-on. Up to 128 slots, 5 MB (about 54 s of mono at 48 kHz).
- They are kept in a part of the +Drive the DN2 never uses (above 3 GiB): projects,
  presets and kits are not touched.

**Test** (after the regression check; **back up the +Drive first**, as always):
1. MACHINE SEL: after CZ PHASE a dotted line, then ONESHOT, WERP, STRETCH, REPITCH,
   GRID, a dotted line, MIDI.
2. ONESHOT: the page as on the DT2 (TUNE box, PLAY icon, dotted box, SAMP box with
   `A --`). Turn SAMP (D) to 1-4: KICK, SNARE, HAT, BEAT appear as a waveform. Play.
3. PLAY: REV, REVL, FWDL (the loop marker appears, dotted), FWD. STRT and LEN move the
   markers and shorten the sound; a held note loops in FWDL.
4. GRID on BEAT: GRID (G) to 16, SLCE (E) through the hits, LEN (F) for several.
5. With a pattern running: REPITCH on BEAT, BARS 1, 2, 1/2 (speeds and pitch follow
   the tempo); STRETCH the same, pitch kept; WERP with SEG and MODE.
6. Your samples: `python tools/dn2samples.py hello` answers. Then
   `python tools/dn2samples.py send FOLDER --keep` with a few WAVs; when it says done,
   SAMP shows them and plays them; the waveform is theirs. Play a pattern on other tracks
   while it sends: nothing else should glitch.
7. Power-cycle: after the boot, SAMP shows your samples again and they play (the
   instrument loads them; give it a few seconds). `python tools/dn2samples.py forget`,
   power-cycle: the test sounds are back.
8. A sound with a sample machine: SAVE PROJECT, power-cycle, reload: machine and
   parameters come back.
9. Eight sample tracks at once with a pattern: listen for crackles (STRETCH is the
   heaviest).

**Known issues.**
- CFAD is shown but not heard yet (heard from v0.14).
- WERP, STRETCH and REPITCH are our own readings of the DT2 manual; the DT2's own
  algorithms are not public, so they are close in kind, not identical.
- The widgets are drawn in the DT2's shapes by our own code; they are close, not
  pixel-identical.
- No sampling from the inputs yet; no comb filter.
- The +Drive keep was proven in the emulator (save, clear, reload at boot, checksum
  checked) with the region moved inside the emulator's small device; the real region
  (3 GiB in) is untested until your unit runs it.
- The DSP's load with many STRETCH tracks has not been measured on the instrument.

## v0.12 — PERC pages and effects

`DN2mod_v0.12_PERC-FX_OS1.11.syx`
sha256 `c441b07c26e42a31b77ac3c366724fba7a7c84b5f7fa11ffab410b14a26dbb79`
Gate: CLEARED TO FLASH, 2026-10-21 (USB size 1,915,364 of 2,097,152, 181,788 to spare). Source: commit `0c682bf`. Docs: `docs/perc.md`.

**Adds / fixes.**
- **Labels follow TYPE.** v0.11's labels came from a copy of the sound that does not follow
  the knob, so they showed another machine's names (they only changed on a pattern change).
  Now they are read from TYPE as the page reads it: turn TYPE and every label changes
  with the name in the middle.
- **Page 1 is the machine:** its eight synthesis parameters on A–H, as on the Machinedrum
  (TRX-BD: PTCH DEC RAMP RDEC / STRT NOIS HARM CLIP).
- **Page 2 is TYPE and the Machinedrum's track effects**, ported from your Ravel code:
  AMD AMF EQF on the top row with TYPE; EQG FLTF FLTW FLTQ below. All off at their
  defaults (AMD 0, EQG centre, FLTF 0, FLTW full), so a sound plays as before until you
  turn them.
  - AMD / AMF: amplitude modulation depth and rate (0.1 Hz to 2.3 kHz).
  - EQF / EQG: one EQ band, 40 Hz to 19 kHz, ±18 dB.
  - FLTF / FLTW / FLTQ: a band filter, with a high pass at FLTF (0 is off) and a low pass
    at FLTF + FLTW (full is off), and resonance.
- **No stray ring.** A track that stops being PERC has its voice silenced, so coming back
  to PERC it waits for a note (the brief ring you heard on v0.11).
- Parameter 4 moved from one WaveTone record to another to free a record for FLTQ: on
  PERC sounds saved with v0.11, knob D of page 1 starts from a different value.

**Test** (after the regression check):
1. A PERC track: turn TYPE (page 2, A) slowly through all 24. On page 1 the labels change
   with the machine every step (TRX-BD: PTCH DEC RAMP RDEC STRT NOIS HARM CLIP; TRX-CP:
   CLPY TONE HARD RICH RATE ROOM RSIZ RTUN; GND-NS: DEC and seven `-`).
2. On a few machines, turn each labelled knob while it plays: each does what it says.
3. Page 2: with a pattern running, turn AMD up (tremolo), then AMF (its rate); EQG away
   from centre and sweep EQF; FLTF up (thinner), FLTW down (darker), FLTQ up
   (resonant). Return them to their defaults: the sound is back as it was.
4. The LFO DEST list on a PERC track shows the machine's names and AMD..FLTQ.
5. Switch a ringing PERC track to another machine and back (MACHINE SEL): no ring until
   the next trig.
6. Eight PERC tracks at once, some with the effects on: listen for crackles.
7. SAVE PROJECT, power-cycle, reload: TYPE, the parameters and the effects come back.

**Known:**
- The header line and LFO lists take the names of the machine the PERC page last showed:
  switching to another PERC track shows its names once its SYN page is drawn.
- PERC's code in L2 and the DSP's load with many PERC tracks: as v0.11.
- A sound saved with PERC, loaded on stock firmware, loads as FM Tone.

---

## v0.11 — PERC

`DN2mod_v0.11_PERC_OS1.11.syx`
sha256 `9e44b90562348210be34a8edb549599b35306795a94507e5db6ddf340764f13d`
Gate: CLEARED TO FLASH, 2026-10-20 (USB size 1,914,556 of 2,097,152, 182,596 to spare). Source: commit `5ff5e05`. Docs: `docs/perc.md`.

**Adds.**
- **PERC**, in MACHINE SEL where Waverider was (after Swarmer): your Ravel PERC drum
  machines on the Digitone, one a track. **TYPE** (page 1, A) picks one of 24:
  TRX BD B2 SD XT CP RS CB CH OH CY MA CL XC, EFM BD SD XT CP RS CB HH CY, GND SN NS IM.
  The middle of the page names it (`TRX-BD`, `Bass Drum`).
- **Eight parameters** follow it: B–H on page 1, A on page 2, named per machine as in
  Ravel (TRX-BD: PTCH DEC RAMP RDEC STRT NOIS HARM CLIP; `-` where a machine has fewer).
  The names also show in the header line and the LFO destination lists. Every one is a
  normal parameter: p-locks, LFOs, SAVE/LOAD all work.
- A note keeps the machine TYPE had when it started; the parameters are live.
- **Waverider is removed** (its tables, display and osc 2). A saved Waverider sound
  loads as PERC.
- Inside: PERC's code runs from the DSP's L2 memory (it is too big for the L1 space the
  other machines use), checked bit for bit in the runner against the same program run
  in Python, which is itself checked against your C.

**Test** (after the regression check):
1. A new track: MACHINE SEL → PERC. Page 1 shows TYPE and TRX-BD / Bass Drum; trig it.
   A kick.
2. Turn TYPE through all 24: the name, the description, the dot and the labels follow;
   trig each. All 24 sound (several peak loud: TRX-CB, TRX-MA, GND-IM, as in Ravel).
3. On a few machines turn each labelled knob while a pattern plays; a `-` knob does
   nothing.
4. Note pitch: play the track chromatically from the keys (TRX-RS, EFM-BD): pitch follows.
5. P-lock TYPE on one step and a parameter on another; an LFO on PTCH. Check the LFO
   DEST list shows PERC's names while the PERC track is active and WaveTone's on a
   WaveTone track.
6. **Load:** eight PERC tracks playing at once (a busy beat). Listen for crackles or
   dropouts, and check the stock tracks and FX still sound right.
7. SAVE PROJECT with a PERC track, power-cycle, reload: TYPE and the parameters are
   back.
8. RESONATOR, CZ, PING, SHIFT and GRAN as in v0.10.

**Known:**
- PERC's code in L2 (`0x200c0000`) is memory the stock firmware never touched in the
  emulator (from a fresh boot of the engine, every stock machine); untested on hardware.
  The DSP's load with many PERC tracks is not measured on the instrument (step 6).
- Selecting PERC starts from WaveTone's knob defaults, not each machine's Ravel defaults.
- P-I (the modal machines) is not ported.
- A sound saved with PERC, loaded on stock firmware, loads as FM Tone.

---

## v0.10 — GRAN, osc 2, voice stealing

`DN2mod_v0.10_GRAN_OS1.11.syx`
sha256 `fb18ef71eda483bd0592b145fd6b567b340c0317cc8c092fcf52b88ce8400910`
Gate: CLEARED TO FLASH, 2026-10-20 (USB size 2,080,802 of 2,097,152, 16,350 to spare).
Source: commit `456d4b9`. Docs: `docs/gran.md`, `docs/w3-osc2.md`, `docs/cz.md`
("Voice stealing"), `docs/ping.md`.

**Adds.**
- **Voice stealing on RESONATOR and CZ.** The newest notes sound, up to each machine's
  cap (RESONATOR 4, CZ 6); the oldest is stolen. With the dynamic voice setting, notes no
  longer drop out.
- **TYPE by name** on the FLTR page: PING shows SVF / LADR / VCFQ / LPG; SHIFT's MODE
  shows UP / DOWN / BOTH.
- **Waverider osc 2** on page 2: DETN LEV POS TBL / - MPOS MLEV -. Its LEV starts at 0 (off),
  so saved Waverider sounds play exactly as before.
- **GRAN (GRAINS)**, a granular effect as a new filter type, last in the FLTR list:
  SIZE DENS MODE SPRD on the bottom row, FDBK and MIX on the top, DRIV on page 2. MODE is
  NORM / UP / DOWN / REV. **MIX starts at 0: turn it up to hear it.**
- Inside: PING's and SHIFT's tables moved to the DSP's DDR to make room; they are
  checked bit for bit as before.

**Test** (after the regression check):
1. RESONATOR, then CZ, with the Voice Setup page on dynamic allocation: play fast
   chords and runs of 8+ notes. No dead notes; when the cap is reached the oldest
   note cuts off.
2. The same with a fixed 8 voices: as v0.9.
3. FLTR page on PING: turn TYPE; the cell reads SVF, LADR, VCFQ, LPG. On SHIFT, MODE reads
   UP, DOWN, BOTH. On Multi-Mode the TYPE cell is the stock picture.
4. Waverider: load a saved Waverider sound; it sounds the same as on v0.9. Page 2: turn
   LEV up, then DETN (+7 is a fifth), POS and TBL (the wave and the name follow), then
   MPOS/MLEV with a scanner RATE set on page 1.
5. Any machine, FLTR > GRAINS. MIX up. Try each MODE; SIZE short and long; DENS; SPRD
   away from the centre; FDBK high (it should build and smear but stay bounded).
6. SAVE PROJECT with a GRAN track and a Waverider osc-2 sound; power-cycle; reload:
   both come back.
7. CPU: a few tracks on GRAN at once, and 8 Waverider voices with osc 2 on. Listen for
   crackles.

**Known:**
- GRAN's buffers sit in DSP memory (DDR at `0x81400000`) that nothing has used before on
  the instrument. The same DDR area holds Waverider's tables and RESONATOR/CZ state,
  which play fine on your unit. This exact range is untested on hardware.
- A sound saved with GRAN, loaded on stock firmware, loads as Multi-Mode.
- Osc 2 shares osc 1's scanner (no RATE or MOVE of its own).

---

## v0.9 — CZ release

`DN2mod_v0.9_CZ-release_OS1.11.syx`
sha256 `850bd00abd6f9f84c112e7ac7d6681339bdcb9e2542286337357e9f7c4a51c2d`
Gate: CLEARED TO FLASH, 2026-10-19 (USB size 2,076,863 of 2,097,152). Source: commit
`b782505`. Docs: `docs/cz.md` ("The release").

**Adds.** CZ PHASE's DCW envelope now behaves like the CZ's at key-up: it holds on
the SUS step while the note is held, and on note-off runs on from the step after SUS
to step 8 (a key-up before SUS is reached jumps straight to the release). NOSUS runs
all eight steps as before. Everything else is as v0.8.

**Test** (after v0.8's list):
1. CZ PHASE, SUS2, short R3–R8, L3 high, L4–L8 falling to 0. Hold a note: the tone
   holds after its first sweep. Let go: the second part of the sweep plays as the AMP
   release fades it. (Give the AMP page a release long enough to hear it.)
2. Same with sequencer trigs of different lengths: longer trigs hold longer.
3. Release before the sweep reaches SUS: it jumps to the release part.
4. NOSUS: the whole sweep runs whatever the note length.

**Known:** the note-off is the frame flag that releases the DN2's ADSR amp envelope
(measured in the DSP emulator); that the ColdFire sends it for a CZ track as for
WaveTone is for the instrument to confirm. If it does not, the envelope simply holds
on SUS as in v0.8.

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
