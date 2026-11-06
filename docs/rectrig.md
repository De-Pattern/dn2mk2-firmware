# REC trigs, the REC buffers, QREC and QPLAY (v0.41)

Octatrack-style sampling from the sequencer (owner, 2026-11-04 and 11-06): a trig that records,
two buffers that play what was recorded, and quantised starts. The ColdFire only: the DSP's
recorder, its four recorder slots and its commands are v0.40's, unchanged.

Code: `csrc/sampler/rectrig.c`; the REC lock in `csrc/slides/slide.c` (beside SLD/SLEN); the
link's real-time command in `csrc/sampler/link.c` (`smp_tdm`); the RECORDER's keys, knobs and
QREC in `csrc/sampler/rec.c`; the views in `csrc/sampler/smp_page.c`. Check:
`scripts/emu_rectrig.py`, the ship gate's step **rectrig**.

## Using it

- **Place a REC trig**: FUNC + VOICE (the RECORDER, over any track's page), hold a step (in
  GRID RECORDING, as for a p-lock) and turn **H**: OFF, REC 1, REC 2, four detents a choice.
  The place shows TRIG and the value, inverted when the step has one (a p-lock's look). Any
  track, any machine: the REC lock lives on that track's step. A trigless lock trig records
  without playing a note.
- **What it records**: the RECORDER's SRC and CHAN (IN, MAIN, TRK1..16), for R.LEN steps at
  the tempo; R.LEN MAX on a REC trig is the pattern's length.
- **Play it**: SAMP **REC 1** (124) or **REC 2** (125) on any sample machine's track.
- **QPLAY** (REC TRIGS view, F; default PLEN): a new take is heard from the first QPLAY
  boundary after it has ended, so a loop never plays a half-recorded take; until then the
  buffer plays its previous take. OFF: heard as it records.
- **QREC** (REC TRIGS view, E; default OFF): with the sequencer playing, RECORD NOW (YES)
  waits for the next boundary (WAITING; YES or NO cancels). The take is a manual one: saved,
  normalised, TRIM, as before.
- Boundaries: every N steps of the master position (1, 2, 4, 8, 16, 32, 64), or PLEN, the
  pattern's first step, as the Octatrack quantises to the pattern.
- **RIGHT** on the RECORDER: the REC TRIGS view (both buffers: EMPTY, REC, NEXT (a take
  waiting for QPLAY), PLAY, and each take's length; Q.REC, Q.PLAY, R.LEN). **LEFT**: back.

## How it works

- **The lock**: a third record kind beside SLD and SLEN (RAM head `0x52`, stored id 202), so
  it is saved, loaded, copied, pasted, undone and cleared with them (`docs/slides.md`).
- **Firing**: the lock applier (`sl_apply`, in the sequencer's timer interrupt) calls
  `rt_trig` once per trig (a chord's other voices, and a second apply in the frame, do not
  fire again). It writes a NOW (a sequence number with bit 15 of its low half set: a buffer
  take's) into a slot of its own; the link's audio interrupt sends it ahead of the UI's
  queue, CMD_REPEAT packets as a queued command, but never in the middle of a queued
  command's repeats (the DSP would take that one again after: a STOP would end the take).
  About a millisecond from the step to the DSP's start. A generation counter hands the words
  from one interrupt to the other.
- **The buffers**: REC 1 is SAMP 124 and REC 2 SAMP 125; behind them, REC 1 uses slots 123
  and 125, REC 2 slots 124 and 126 (the DSP records into slots up to 126 and plays the four
  whatever the pool's count). A take records into the half not playing. `smp_mod_apply`
  writes each sample voice's SAMP into the frame: REC 1 / REC 2 become the half that plays
  (`rt_map`); SAMP 126 and 127 play nothing while the buffers are on. A voice takes SAMP at
  its note, so a note playing the old take finishes on it.
- **QPLAY's switch** (`rt_frame`, every frame in the audio interrupt): at a new master step,
  a buffer whose take is over (its R.LEN steps counted) switches if the step is on QPLAY's
  boundary. Stopped: once the take's time is up.
- **Takes are RAM only**: not saved, not normalised (seconds each), not in the ColdFire's
  directory; gone at a project change (pools.c blanks the DSP's entries) or a power cycle.
- **Room**: `rt_poll` (the UI loop, every 150 ms or after a take) plans each buffer's next
  place with the recordings' allocator (`smp_rec_place`), which keeps clear of the saved
  recordings, other projects', every live buffer take and the other buffer's plan; a take is
  never longer than its plan (a tempo slowed since the last plan shortens it a little,
  never overruns), and refused if under a tenth of a second.

## Guards

- A manual take armed, recording or waiting for QREC: REC trigs record nothing (rt_why 2).
  A manual take started while a buffer take runs ends it (one recorder); a take waiting for
  QPLAY, cut short, is dropped (the buffer keeps playing what it played).
- A project with a saved sample in SAMP 124..127 (v0.32's DEST, or a recording into a full
  pool before v0.41): the buffers are off there (rt_why 1), and those slots play what they
  hold. Manual recordings no longer go into 124..127 (SAMP 1..123 only).
- One recorder: a REC trig of one buffer while the other's take runs cuts that take.
- v0.41 also clamps a **manual** take to the room the allocator found: v0.22..v0.40 sent R.LEN
  alone, and the DSP stops only at the area's end, so a long take in a fragmented area ran
  into the next recording's RAM until the next power-on.

## Checked (scripts/emu_rectrig.py, 19 checks)

The buffers on and off; the lock through SAVE/LOAD and the clear; a trig's command (sequence,
NOW, SRC/CHAN, place, slot, length) once per trig; the packets carry it, the UI's queue is
untouched; QPLAY PLEN switches on the pattern's first step and not before, OFF at once;
SAMP 126/127; a manual take's turn; saved samples; the allocator keeps clear; QREC 8; the
RECORDER's H with a step held through the panel (three detents nothing, the fourth REC 1, the
step lets go); RIGHT/LEFT. Unverified on hardware: the take's start against the step, by ear.
