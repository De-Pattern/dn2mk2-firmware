# v0.55: FLEX buffers in every sample machine (owner, 2026-11-15)

> "is that possible to just add the recorded buffers (1-8) to the end of the project ram list?
> lets do that first"

## What it does

- SAMP on ONESHOT, WERP, STRETCH, REPITCH, GRID and SLICE goes past 127 to **B1..B8**, the eight
  FLEX buffers. The knob turns onto them (D at 127, a detent right: B1), the sample list shows
  them as rows ` B1`..` B8` after slot 127 ("FLEX BUF n" when the buffer holds a take,
  "FLEX EMPTY n" when not), and UP/DOWN in the list steps through them.
- A track on Bn plays buffer n's **playing half**: the take FLEX plays, swapped when a new take
  lands. An empty buffer plays nothing (SAMP OFF to the DSP).
- A SAMP p-lock can name a buffer: the voice hears the lock's buffer (`smp_mod_apply` reads the
  voice's target cell, the lock applied).
- Page 2 shows "FLEX BUF n" / "FLEX EMPTY n" in place of the waveform (the take has no overview).

## How

- **Codes.** Buffer b's SAMP value is half 0's, `BUF_SAMP0 + 2b` (129, 131, .. 143), the value
  the DSP already plays from the buffer directory (`rt_buf_code`, `rt_samp_buf`, rectrig.c).
- **The voice.** `smp_mod_apply` (link.c), before the pool's own SAMP handling: a sample machine
  whose target SAMP is a buffer code gets the mirror cell `rt_buf_samp(b)`, the playing half's
  SAMP, or 0 when empty. The DSP's `start()` plays SAMP >= 129 through `BUF_DIR` for every
  sample machine (STRETCH fits the take to its steps, as FLEX does). Nothing changed on the DSP.
- **The knob.** SAMP's record (256) is 0..0x7F00 in the stock table, and stock's setter path
  clamps to it, so:
  - from a buffer, a turn reaches the setter clamped to 127; `smp_quant` (fmt.c) takes the
    knob's own direction (`smp_knob_d`) and steps rows 0..135;
  - at 127, a turn up never reaches the setter (the value would not change): `smp_ui_pop`
    (rec.c) takes knob D's item on a sample machine's SRC page (`smp_samp_page`) and sets B1
    itself, dropping the item;
  - `smp_set_samp` writes a buffer code through the stock `SET_VALUE` with an in-range value
    (other than the one held, so it is not skipped) and `smp_quant` substitutes the code
    (`smp_samp_direct`), so the stock path after the write (locks, the screen) carries it.
- MIDI CC on SAMP is unchanged (0..127 as before).

## FLEX MUTE SRC (v0.55, reworked in v0.57)

**v0.57** (NiKo, 2026-11-15: the mute came on as soon as a take existed, and stock unmute could
not bring the SRC back): the SRC track is muted only while the FLEX track **plays**, i.e. a voice
of the FLEX track has its note on and is heard.
- The note's state comes from the frame's trigger words: note-on is word 34, note-off is word 36,
  bit v for voice v (measured in the coupled emulator).
- The DSP's play positions were tried first. A FLEX voice's take loops on silently after its
  release, so they never end.
- "Heard" means its frame LEVEL is above 0.
- The mute is held 300 frames (about 0.2 s) past the note-off.

So stopping or muting the FLEX track gives the SRC back. Gate: `mute` links 1b..1e; `flexplay` M1..M3, with a real take.

### v0.55

Owner: muting the SRC track as soon as MUTE is ON left a gap until FLEX played a take ("trigger
the mute when the rec trig ends"). Now the SRC track is muted only once the FLEX track's buffer
holds a take (`ms_mask_now`: `rt_buf_samp(rt_buf_of(t))` nonzero). The first take records with
the source heard; from then on FLEX's loop replaces it; CLEAR BUF gives it back.

The owner's other idea (the source heard *through* the FLEX track, post-amp) needs a DSP thru
path for the FLEX voice; not done.

## Gate

- `flexpool` (ColdFire): the knob's steps over the 127/B1 edge both ways, B8 held, 5 -> 6 and
  122 -> 123 as before, a stale knob as before; knob D at 127 turned by the panel's encoder:
  B1 and the list up; DOWN/UP through B1, B2, 127; the list and both pages drawn and told apart.
- `flexplay` (coupled): `emu_coupled_flex.py --pool`: a take recorded into buffer 1, then a
  ONESHOT track on B1: its voice sent SAMP 129, the DSP renders it, the render is the take at
  the note's pitch. Negative control `--break poolsamp` (SAMP 127): fails at P1.
- `mute` (coupled): link 1b, ON with no take leaves the track heard; negative control
  `--break notake`.
