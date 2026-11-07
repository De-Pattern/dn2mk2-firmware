# Live sampling, second design (rec-v2) — proposal, 2026-11-07

**As built (v0.44, the same day; `docs/rectrig.md` is the reference).** The owner's decisions
on the open points, and what changed from the proposal below:

- The machine is **BOUNCE** (type 17), not FLEX; to the DSP it is **STRETCH** on its buffer,
  not ONESHOT, so a take follows the tempo (the DSP's `tempo()` takes the take's steps in
  place of BARS). It costs DSP code after all: the buffer directory (`SM.BUF_DIR`, 16 halves
  of address, frames, steps) and SAMP 129..144.
- **Eight buffers, one per BOUNCE track by its BUF control** (1..8), two halves each; not the
  two shared REC 1 / REC 2 slots. "2+1" is two tracks on one BUF.
- Recorder trigs are placed on the **BOUNCE REC panel** (FUNC + VOICE on a BOUNCE track) with
  the [TRIG] keys whether or not GRID RECORDING is on; the panel owns PAGE (its own page
  counter: stock's grid-page variable was not found), and the **screen's 4 x 4 grid** shows
  the page's trigs — the LEDs are not mirrored (stock's LED driver owns them).
- **YES YES** (twice within 0.4 s) re-arms the one-shots; a single YES stays the manual
  RECORD NOW. **FUNC + YES** saves the playing take to the next empty pool slot and the
  +Drive. NO closes the panel (no "disarm").
- The RECORDER keeps one page for every machine (page 2 gone); Q.REC and Q.PLAY live on the
  BOUNCE panel's bottom row (E, F), R.LEN on G, the one-shots' count on H.
- The lock table's offset was settled in the emulator: PATTERN + 97,872 (the model's getter
  returns `*(model + 16)`); the harness checks it every run, so no RAM mirror was needed.
- The status lines are those in `docs/rectrig.md` (section 4's wording changed).

Replaces v0.41's REC trigs / REC TRIGS page. Owner's brief: Octatrack-style, intuitive, proven
end to end, no conflicts with other keys. Read with `docs/HANDOFF-2026-11-07-rec-trigs.md`
(what exists and what went wrong) and the Octatrack manual OS 1.40A (9.1–9.2, 12.4.5, 12.4.8).

## Why v0.41's did not work, in one paragraph

A REC trig was a p-lock (hold a step, turn H) that fired only when stock applied that step's
lock list to a voice: a step without a note trig never fired, silently. Two knobs were called
ARM on two pages and meant different things. There was no feedback for "armed but nothing
placed". The emulator never ran the sequencer, so none of this was seen before it shipped.

## The design

### 1. One machine owns it: FLEX

A new entry in MACHINE SEL's sample column: **FLEX**. To the DSP it *is* ONESHOT (same type
word, same render; no DSP code, no DSP memory): the ColdFire sends ONESHOT's type and maps SAMP
to the track's recorder buffer. So "will it fit" is answered: yes, it costs ColdFire code only
(the sample machines' DSP span has 2.7 KB spare and FLEX needs none of it).

- A FLEX track plays **its own recorder buffer**: no SAMP to set, no REC 1 / REC 2 to find.
  Its SAMP page shows `BUFFER · EMPTY` or `BUFFER · 2.0 s`.
- FLEX's third SYN page is the **RECORDER**, the same page every sample machine has today (SRC,
  CHAN, YES, THRES, R.LEN, R.STRT, ARM), with these changes for every machine:
  - B labelled **CHAN**; E labelled **INTO SAMP n** (a result, drawn dim, not a knob);
  - the manual recorder's **ARM** keeps its name (it is the DT2's word).
- On a FLEX track only, the RECORDER page is also the **recorder-trig layer** (section 2) and
  gets a status line (section 4).
- The other sample machines keep the RECORDER exactly as the DT2's: manual sampling into a slot.
  The REC TRIGS page 2 goes away.

### 2. Placing recorder trigs: the Octatrack's way

With a FLEX track active, **the RECORDER page open and GRID RECORDING on**, the 16 [TRIG] keys
and LEDs are the track's **recorder trigs**:

| key | does |
|---|---|
| [TRIG n] | toggles a recorder trig on step n (LED red) |
| FUNC + [TRIG n] | toggles a **one-shot** recorder trig (LED yellow; it records once, then disarms) |
| [TRIG n] held | nothing else (no locks on this layer) |
| PAGE | the pattern's pages, as stock |
| YES | re-arms the track's one-shot recorder trigs ("ARM REC TRK"); NO disarms them (the Octatrack's [TRACK] + YES/NO) |
| LEFT / RIGHT | the RECORDER's other pages, as today |

With the RECORDER page closed (any other page), the keys and LEDs are the **normal trigs**
again, untouched. Recorder trigs are their own set, per track, per pattern: they never create,
remove or alter a note trig, and a note trig never creates one. A step can hold both (the
Octatrack's SRC3 rule: on the same step the note plays the buffer as it was before the take).

Storage: the lock-store record of kind 2 (id 202) already saves 16 bits a step per track with
the pattern, through SAVE/LOAD/copy/paste/undo/clear (v0.41 proved that part). It keeps that
job, as the trig's **store**, with two values: 1 recorder trig, 2 one-shot (armed), 3 one-shot
(spent; re-armed to 2 by YES). It is no longer a p-lock and no longer read by the lock-list path.

### 3. Firing: from the sequencer's own step, not from a voice

`rt_frame` already runs every audio frame and watches the master step. It now also watches each
track's own step (`TRACK_CUR[t]`, what Direct Jump and the slides read): when FLEX track t's step
changes, it reads that step's recorder-trig value from the playing pattern's lock table
(`PATTERN` → the model's table, the same table `sl_lock_get` reads) and fires `rt_trig`. So a
recorder trig fires **whether or not the step has a note**, on the step boundary, with a
step's accuracy (the audio interrupt is 1,500 Hz; a 1/16 at 120 BPM is 187 frames).

Open point to settle in the emulator before coding (one afternoon): the lock table's offset
inside the pattern object, so the ISR reads it without the UI's track context. If that is not
stable, the fallback is a 16 x 128-bit RAM mirror of the recorder trigs, rebuilt from the table
on PLAY and on every edit.

What `rt_trig` does is unchanged (a NOW command into the buffer's idle half, R.LEN steps at the
tempo, SRC/CHAN from the RECORDER), minus the ARM check: **a FLEX track with recorder trigs on
it is armed by having them**; one-shots carry their own armed/spent state.

### 4. Feedback: the RECORDER page always says what happened

A status line on the FLEX RECORDER, under the meter, updated every frame:

- `NO REC TRIGS · [TRIG] PLACES ONE` when the track has none and GRID RECORDING is on
- `REC TRIGS ON 1, 5, 9 · PLAY TO RECORD` when it has some and the sequencer is stopped
- `REC 2.3 s` while a take records; `TAKE READY · PLAYS AT PLEN` while QPLAY waits; `PLAYING 2.0 s`
- a refusal, for 3 s, in words: `NO ROOM`, `MANUAL REC RUNNING`, `BUFFERS OFF (OLD PROJECT)`
- `ONE-SHOT SPENT · YES RE-ARMS`

### 5. The buffers

Keep two buffers (REC 1 / REC 2, the pool's four recorder slots) for now: FLEX track 1..16 →
buffer by choice on its SAMP page (`BUF 1` / `BUF 2`), default 1. Two FLEX tracks on one buffer
are the owner's "2+1": one records, both play, mutes do the handoff. Eight per-track buffers
as the Octatrack's need pool room and a DSP slot change: a later step, if wanted.

QPLAY (default PLEN) and QREC stay as v0.41's, shown on the RECORDER page as **Q.PLAY** (E's
place on FLEX, where INTO is meaningless) and **Q.REC** (G's place; R.STRT moves under THRES).

### 6. Saving a take

On a FLEX track, **FUNC + YES on the RECORDER page** (not TRIM: there is no TRIM for a buffer
take) copies the playing half into the next empty pool slot and saves it as a manual recording
does (SAVING, NORMALIZING, FILE NAME, ASSIGN). The status line says `SAVED SAMP n`.

### 7. Keys audited against everything else on or near the RECORDER

| key | today | in rec-v2 |
|---|---|---|
| [TRIG] on the RECORDER | ASSIGN SAMPLE TO TRACK? (after a manual take) | unchanged on non-FLEX; on FLEX only the ASSIGN prompt takes it, otherwise the trig layer |
| FUNC + YES | TRIM preview (held) | unchanged on TRIM; on FLEX's RECORDER: save the take |
| FUNC + NO | TRIM drop | unchanged |
| FUNC + PLAY | name cleared (NAME) | unchanged |
| YES / NO | RECORD NOW / stock questions (`question` step) | unchanged outside the FLEX trig layer; inside it, with GRID RECORDING on: arm / disarm one-shots |
| LEFT / RIGHT | pages; TRIM's ends | unchanged (page 2 gone) |
| H with a step held | the REC lock | **gone** (no lock on H) |
| SLD / SLEN (TRIG page 2) | slides | unchanged (same store, other records) |
| PTN + YES / NO | Direct Jump | unchanged |
| +Drive browser, SLICE menus | their YES/NO, let-go rules | unchanged (`alloc`, `hooks` steps) |
| stock GRID RECORDING, LIVE RECORDING | [RECORD], [RECORD]+[PLAY] | unchanged; the trig layer only reads the mode |

### 8. Proving it

- **Harness**: `emu_rectrig` is rewritten to drive the real thing: GRID RECORDING on, the
  RECORDER open, [TRIG] presses through the panel, then the sequencer's per-track step counter
  advanced by the tick path the Direct Jump harness already drives (`emu_jump` runs stock's
  tick ISR), and the fire observed at `rt_trig` and in the link's packets. The one piece still
  simulated is the DSP; the SHARC runner's `rec` parts cover that side as today.
- **On the unit**, from a new project, numbered in FIRMWARE.md: FLEX on T1, RECORDER, SRC IN,
  [RECORD], [TRIG 1], PLAY: the status line must read REC, then PLAYING, and T1 must play the
  loop with a trig on step 1 of its (normal) page. Then MAIN as SRC: that settles depaffect's
  MAIN question on hardware too.

## Decisions for the owner

1. **FLEX machine** (this doc) or keep every sample machine able to hold recorder trigs with a
   fixed page 2? FLEX is simpler to explain and to prove; page 2 is more flexible.
2. **Two shared buffers with a BUF 1/2 choice** (this doc), or one buffer per FLEX track (more
   pool room, a later step)?
3. **Name**: FLEX (the Octatrack's word) or RAM?
4. One-shot re-arm on **YES** (the Octatrack's) or on a knob?
