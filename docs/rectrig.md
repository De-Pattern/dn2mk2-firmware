> **v0.48: BOUNCE is out of the firmware** (docs/bounce-removal-plan.md). This page describes
> v0.44..v0.47, for the redesign.

# BOUNCE: recorder trigs, the eight buffers, QREC and QPLAY (v0.44)

Octatrack-style sampling from the sequencer (owner, 2026-11-04, 11-06 and 11-07): a machine
whose track records into its own buffer on recorder trigs and plays that buffer, quantised
starts and switches, and a take saved to the pool when wanted. Replaces v0.41's REC trigs
(a p-lock on H that fired from a voice's lock list, so a step with no note never recorded;
two knobs called ARM; a second RECORDER page: "none of this is working" — the owner, NiKo,
depaffect). `docs/rec-v2-design.md` is the design it was built from and lists what changed.

Code: `csrc/sampler/rectrig.c` (the trigs, the buffers, QREC/QPLAY, firing); the BOUNCE
RECORDER's keys, knobs and the save in `csrc/sampler/rec.c` (`bn_*`); the panel in
`csrc/sampler/smp_page.c` (`bn_view_draw`); the store in `csrc/slides/slide.c` (the third
record, beside SLD and SLEN); the DSP side in `src/dnfw/sampler/program.py` (the buffer
directory, `SM.BUF_DIR`; the recorder's buffer destination; STRETCH on a take's steps) and
`src/dnfw/sampler/machines.py` (BOUNCE, type 17). Checks: `scripts/emu_rectrig.py` (the gate's
**rectrig** step, 37 checks) and the SHARC runner's **rec** step (a take into a buffer half,
played back bit-exact).

## Using it

1. **MACHINE SEL → BOUNCE** on a track (the last of the sample machines). Its SYN page:
   TUNE, PLAY, BUF, STRT, LEN, LEV. **BUF** (knob D) is the buffer it records into and plays,
   1..8; the default is 1. Two BOUNCE tracks on one BUF is the owner's "2+1": one records,
   both play.
2. **FUNC + VOICE** on that track: the **BOUNCE REC** panel (the RECORDER of a BOUNCE track).
   SRC (A) and CHAN (B, drawn as the L/R icon) say what it records: IN, MAIN or a track, L+R,
   L or R. THRES is not used by a trig's take (the take starts on the step).
3. **[TRIG 1..16]** on that panel places or removes a **recorder trig** on that step of the
   page shown (a filled cell in the 4 x 4 grid). **FUNC + [TRIG]** places a **one-shot**
   (an open cell: it records once, then is spent — a struck cell). **PAGE** turns the page
   (the panel opens on the page the track is playing). The trigs are the track's, per
   pattern, saved with it; they never touch the note trigs on the same steps, and GRID
   RECORDING does not matter here (the panel owns the keys while it is open).
4. **PLAY.** When the track's step reaches a recorder trig, the take starts: SRC/CHAN, for
   **R.LEN** steps (G; MAX = the pattern's length) at the tempo, into the half of the buffer
   that is not playing. When it ends, the track hears the new half at the first **Q.PLAY**
   boundary (F; default PLEN, the pattern's first step; OFF: at once). Until then it plays the
   previous take. The panel's status lines say it all: `BUF1 EMPTY` / `[TRIG] PLACES A REC
   TRIG`, `3 TRIGS: PLAY RECORDS`, `BUF1 REC 1.2s` / `TRIG: RECORDING`, `BUF1 NEXT 2.0s`
   (waiting for Q.PLAY), `BUF1 PLAYS 2.0s` / `8 STEPS, FN+YES SAVES`, a refusal for three
   seconds (`MANUAL REC`, `NO ROOM`, `NO BUFFERS`, `NO +DRIVE POOL`), `SPENT: YES YES ARMS`,
   `n ARMED` after YES YES. The bottom row: E Q.REC, F Q.PLAY, G R.LEN, H the one-shots
   (`1SHOT armed/placed`).
5. **The track plays its buffer** with its own note trigs, as a STRETCH machine does: the
   take is fitted to its steps at the tempo, so a loop recorded at 120 stays in time at 100.
   STRT and LEN pick a part of it; PLAY as on STRETCH.
6. **YES YES** (twice within 0.4 s) on the panel arms the track's spent one-shots again.
   A single YES is the manual RECORD NOW, as on every RECORDER (into the next empty pool slot,
   not the buffer).
7. **FUNC + YES** on the panel saves the buffer's playing take into the next empty pool slot
   and to the +Drive (RECORDED), as a manual recording is saved: SAVING, NORMALIZING, TRIM,
   FILE NAME, ASSIGN. The buffer goes on playing the take; its next take goes elsewhere.
   With nothing to save, or a take still recording or waiting, the line says `NOTHING TO
   SAVE`.
8. **Q.REC** (E; default OFF): with the sequencer playing, a manual RECORD NOW (YES) waits for
   the next boundary (`WAITING`, `NO:CANCEL`). Boundaries are every N steps of the master
   position (1, 2, 4, 8, 16, 32, 64) or PLEN.

Takes are RAM only: never normalised, not in the ColdFire's directory, gone at a project
change or a power cycle — until FUNC + YES saves one.

## How it works

- **The store**: a recorder trig is a value on a step in the lock store's third record kind
  (RAM head `0x52`, stored id 202; `docs/slides.md`): 1 a trig, 2 a one-shot armed, 3 a
  one-shot spent. Saved, loaded, copied, pasted, undone and cleared with the pattern. It is
  not a p-lock and the lock-list path never reads it.
- **Firing**: `rt_frame`, every audio frame (1,500 Hz), watches each BOUNCE track's own step
  (`TRACK_CUR`, what Direct Jump and the slides read). When it changes, it reads that step's
  value from the playing pattern's lock table (inside the pattern object at +97,872; the
  model's getter returns `*(model + 16)` and the harness checks the two agree) and calls
  `rt_trig`: a NOW command (sequence bit 15: a buffer take's) into a slot of its own, which
  the link's audio interrupt sends ahead of the UI's queue, never in the middle of a queued
  command's repeats. A one-shot is spent only when its take started (a refusal leaves it
  armed). About a millisecond from the step to the DSP.
- **The buffers**: eight, two halves each, in the recordings' area; the DSP's buffer
  directory (`SM.BUF_DIR`, 16 entries of address, frames, steps) holds each half's take. A
  BOUNCE track's voice plays SAMP `129 + 2 b + h` (half h of buffer b; `smp_mod_apply` writes
  it into the frame from the track's BUF and the half that plays, `rt_bounce_samp`), as
  STRETCH, with the take's steps in place of BARS. SAMP 1..128 are the pool's; the knob stays
  within them.
- **QPLAY's switch**: at a new master step, a buffer whose take is over switches halves if
  the step is on the boundary; stopped, once the take's time is up.
- **Room**: `rt_poll` (the UI loop) plans each used buffer's next place with the recordings'
  allocator (`smp_rec_place`), clear of saved recordings, other projects', live takes and the
  other buffers' plans; a take never outruns its plan and is refused under a tenth of a
  second (`NO ROOM`).
- **Saving** (`bn_save`): the playing half's frames are handed over to the pool slot where
  they lie (`rt_take_handover`, `smp_save_recording`, `smp_push_slot`); the buffer keeps
  playing them and allocates its next take elsewhere.

## Guards

- A manual take armed, recording or waiting for QREC: recorder trigs record nothing
  (`MANUAL REC`). A manual take started while a buffer take runs ends it (one recorder).
- One recorder: a trig on one buffer while another's take runs cuts that take.
- A project with a saved sample in SAMP 124..127 (v0.32's DEST): the buffers are off there
  (`NO BUFFERS`); manual recordings go into SAMP 1..123 only.
- LEDs are not mirrored to recorder trigs (stock's LED driver owns them); the panel's grid is
  the view.

## Checked (scripts/emu_rectrig.py, 37 checks)

The playing pattern's lock table offset; the buffers used by BOUNCE tracks' BUF; a trig on a
step the track reaches starts a take into the idle half (the command ahead of the queue,
never mid-repeat), the same steps on an ONESHOT track record nothing; a one-shot fires once
and is spent only when its take started; a manual take's turn and NO ROOM refuse; QREC 8
holds a manual NOW; QPLAY PLEN switches on the pattern's first step; the store through
SAVE/LOAD (id 202) and the clear; the take's handover to a slot; the panel: [TRIG 3] toggles
(and places no note trig), YES YES arms, NO closes; the RECORDER of an ONESHOT track with knob
B turning CHAN; FILE NAME's UP/DOWN, RIGHT, NO, NO. The DSP side: the SHARC runner's rec step
(a NOW into buffer half 0 with 4 steps, the directory entry, SAMP 129 played back bit-exact).
Unverified on hardware: the take's start against the step, by ear.
