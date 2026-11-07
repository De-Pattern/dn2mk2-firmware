# Handoff, 2026-11-07: live sampling (REC trigs, the buffers, the recorder) needs a redesign

For the next session (the owner is switching to Claude Fable). Read this first, then
`CLAUDE.md` (the rules: they are not optional), then `docs/rectrig.md` and `docs/sampler.md`.

## 0. Rules while v0.43 is still in its gate (read before doing anything)

**v0.43 ROOM was published 2026-11-07 06:50 (sha256 `4089df39...`): these rules no longer bind.
The redesign's proposal is `docs/rec-v2-design.md` on branch `rec-v2` (worktree
`/home/claude/dn2/recv2-wt`, main merged in), awaiting the owner's four decisions.**

v0.43's gate may still be running when you start (check: `pgrep -fa ship_gate`, and
`gh api repos/De-Pattern/dn2mk2-firmware/releases/latest --jq .tag_name` says v0.43 once it is
out). Until v0.43 is published:

1. **Do not touch `/home/claude/dn2/v043-wt` or the `v043` branch** except to finish v0.43's gate
   and publish it. Any edit to a file a gate step read (tests, scripts, sources, the build)
   makes that step run again: hours lost.
2. **Start the redesign on a new branch from `main`** in its own worktree
   (`git worktree add ../recv2-wt -b rec-v2 origin/main`), and merge `v043` into it once v0.43 is
   on `main`.
3. **No heavy jobs while the gate runs.** The machine has 2 cores and the gate uses both: no
   builds, `ship_gate.py` runs, SHARC or ColdFire emulator runs or pytest suites of your own.
   Read code, plan, write; build and test after v0.43 is published.
4. **Never stop or re-launch the gate's jobs from another session.** Only the session that
   started them does that (a job killed at its 2-hour limit is re-launched as a smaller
   `--only` batch; passes are cached).
5. Keep to `CLAUDE.md` throughout: the gate, publishing, commits as De-Pattern.

## 1. What the owner wants

Octatrack-style live sampling on the Digitone II mod, **intuitive to set up**, working on the
unit, proven end to end, not conflicting with any other key combination, shortcut or process.
The owner (2026-11-07, after trying v0.42 on his unit): *"none of this is working ... it should
be more intuitive than this anyway ... there are a lot of confusing things here."* He asked for
a redesign that "accounts for all real variables, test it, ensure it works, ensure its easy and
intuitive to set up and implement, and doesnt conflict with other combo controls/shortcuts or
other processes."

Earlier decisions of his that still stand (2026-11-06):

- **"2+1"** for continuous live resampling: a sample track is the buffer's player, plus an
  optional MUTE handoff (stock mutes, visible), later perhaps glitchy norns-MLR-style tricks
  with reverse trigs. He did not understand a "two buffers" concept I had proposed; explain
  anything like it plainly or drop it.
- Direct "save the take into a slot" is wanted (he asked 2026-11-07 whether REC 1/2 can be
  saved without resampling: today they cannot).
- Don't touch global settings; don't change stock behaviour (stock FUNC + turn, etc.).

## 2. The honest state: what was claimed, what was proven

**v0.41 (LOOP) shipped REC trigs, two buffers, QREC, QPLAY and a REC TRIGS page. It does not
work on the unit for the owner, NiKo or depaffect, and nothing ever proved it end to end.**

The emulator cannot run the sequencer (`docs/emulator.md`). So `scripts/emu_rectrig.py` (the
gate's `rectrig` step, "22/22 checks") never placed a REC lock through the real panel during
playback and never had a real sequencer step fire it. It:

- sets the lock by calling `sl_lock_set` directly (REC 1 on step 4, REC 2 on step 8);
- fires the "trig" by calling stock's note-block functions by hand (`0x400D85E8` the lock-list
  builder, `0x400DB092` the applier, which reach our `sl_apply` and so `rt_trig`);
- then checks the command words, the packets, `rt_map`, QPLAY's switch, and so on;
- with `--png-dir` it turns H with a step held on the RECORDER (the panel path for the
  lock's value only).

The DSP side of a buffer take (recording into slots 123..126) was tested separately in the
SHARC runner (`rec`, `recwhole`, `mainrec`), never driven by a real REC trig. So each piece
was tested alone; the chain step, trig, lock, `rt_trig`, link, DSP, buffer, playback was not.

## 3. What is implemented today (v0.41 .. v0.43; v0.43 does not touch any of it)

### Pages (the RECORDER is FUNC + VOICE over a sample machine's page; it is the third SYN page)

Page 1, **RECORDER** (`csrc/sampler/smp_page.c`, `rec_screen_draw`; knobs `csrc/sampler/rec.c`, `knob()`):

| knob | shown as | does |
|---|---|---|
| A | SRC (IN, MAIN, TRK1..16) | the source |
| B | (no label) the line under SRC: L+R / L / R | the channel. **The owner did not find it: there is no "CHAN" label** |
| C | the RECORD box | YES records at once, YES again stops (QREC may make it wait: WAITING) |
| D | THRES 0..120 | threshold (0: learns the noise floor) |
| E | **INTO n** (`w_samp`) | **not a control**: the first empty slot the next manual take goes into. The owner read it as a setting ("A on rec page 1 is still set to INTO 1") |
| F | R.LEN (MAX, 1..127 steps) | length |
| G | R.STRT (THRES / PLAY) | what an ARM waits for |
| H | **ARM** (a switch drawn) | arms the **manual** recorder; with a step held: **TRIG** (that step's REC lock) |

Page 2, **REC TRIGS** (RIGHT from page 1, LEFT back; `rt_view_draw`):

| knob | shown as | does |
|---|---|---|
| A, B | SRC and its channel | as page 1 |
| (box) | REC 1 / REC 2 status: EMPTY, REC, NEXT, PLAY, seconds; v0.42: BUFS OFF / MANUAL REC / NO ROOM / NOT ARMED for 4,500 frames after a refusal | |
| (grid) | the active track's REC locks on the 16 steps of its page (4 x 4) | |
| E | Q.REC (OFF, 1..64, PLEN) | RECORD NOW waits for a boundary |
| F | Q.PLAY (default PLEN) | when a new take is heard |
| G | R.LEN | as page 1 |
| H | **ARM** OFF / ONCE / ON | **a different thing from page 1's ARM**: whether this track's REC trigs record. With a step held: **TRIG** again |

Both pages: a step held (`sl_rec_held`/`sl_rec_knob`, `csrc/slides/slide.c`, needs stock's
held-step object, i.e. GRID RECORDING) makes H that step's REC lock: OFF / REC 1 / REC 2, four
detents a choice (`SL_CHOICE_DETENTS`). Two knobs called ARM and a lock on H on both pages:
this is the confusion the owner names.

### The REC lock and firing

- A third lock record beside SLD/SLEN (RAM head `0x52`, stored id 202): saved, loaded, copied,
  pasted, undone, cleared with them (`docs/slides.md`). Stock's LOAD skips id 202.
- **It fires only when stock applies the step's lock list to a voice**: `sl_apply` (our
  replacement of the applier, `csrc/slides/slide.c` ~line 215) calls `rt_trig(track, step, buf)`
  after `trigger()`, if the step's ext record carries REC 1/2. **A step with no trig is never
  applied, so a REC lock on an empty step does nothing and shows nothing.** `docs/rectrig.md`
  claims "a trigless lock trig records without playing a note": only true if the step is
  already a stock trigless lock trig; placing the REC lock via H does not create one. This is
  the most likely reason the owner, depaffect and NiKo see "REC1 EMPTY" with no message.
- `rt_trig` (`csrc/sampler/rectrig.c` ~line 179) refuses (and sets `rt_why`, shown on page 2):
  track not armed (4, NOT ARMED); buffers off (1, BUFS OFF: a project with saved samples in
  SAMP 124..127 from v0.32 or older); a manual take running (2, MANUAL REC); under 0.1 s of room
  or a clash (3, NO ROOM). Otherwise it writes a NOW command (seq with bit 15 of the low half:
  a buffer take) into `rt_w[]`; the link's audio interrupt (`smp_tdm`, `csrc/sampler/link.c`)
  sends it ahead of the UI's queue as CMD_REPEAT packets. About 1 ms from step to DSP start.
- Arm state `rt_arm[16]` (OFF/ONCE/ON) is RAM only, not saved with the pattern.

### The buffers

- REC 1 = SAMP 124, REC 2 = SAMP 125 as the user sees them. Behind them two halves each:
  REC 1 slots 123 and 125, REC 2 slots 124 and 126 (`HALF[b][half]`); a take records into the
  half not playing; `rt_map` (in `smp_mod_apply`, every frame) maps SAMP 124/125 to the playing
  half; SAMP 126/127 play nothing while the buffers are on. RAM only: gone on project change or
  power off. One recorder: a REC trig while the other buffer records cuts that take.
- QPLAY (`rt_frame`, audio interrupt): at a master step on the QPLAY boundary a finished take
  switches in. QREC: RECORD NOW waits for the boundary.

### The manual recorder (works for the owner in general; see section 4 for MAIN)

YES or ARM, then SAVING, NORMALIZING (to full scale, v0.40), TRIM (E/H move START/END, **FUNC + YES
plays while both are held**, YES keeps, FUNC + NO drops), FILE NAME, ASSIGN SAMPLE TO TRACK? (a
[TRIG] key, or NO). The take goes into the project's pool, slot INTO; the box says SAVED n or
n ON TRK t.

## 4. Reports (verbatim where I have them)

- **Owner, 2026-11-07, v0.42 on his unit**: "i dont se any word popping up but none of this is
  working. it could be because A on rec page 1 is still set to "INTO 1" or it could be because
  the ARM control is duplicated on both pages. it could be because of how trigs are handling
  actions. but this was not implemented properly ... it should be more intuitive than this".
  Also: "we dont have a CHAN control" (it exists, unlabelled, knob B).
- **NiKo** (Discord, v0.41/0.42): "I don't get the rec trigs thing... the track keeps
  recording on a classic sample slot but not on rec1, which stays empty" (v0.42 added the
  refusal reasons for him).
- **depaffect** (Discord, 2026-11-07, v0.42, a brand new project): "record screen has some
  issues still - i can't get any level in MAIN, and when i've recorded something (ie by
  selecting track 1 etc), i cannot preview the recording by pressing function+yes ... it looks
  like it's previewing the recording; but there is no sound". And: "even when armed is set to
  "on" or "once" on that "REC TRIGS" screen, nothing seems to happen when i play the pattern -
  it always just says "REC1 EMPTY / REC2 EMPTY"".

### MAIN and the preview: an older open problem

The recorder's MAIN reads `MAIN_TAP` (L2 `0x200A9000`) and the preview (CMD_PREVIEW) is added to
the output by **`wr_pvmix`, hooked at the driver's master-mix call (`0x1c9d3f`, `PVMIX_SITE`)**
(`src/dnfw/sampler/program.py` ~1744, 2013, 2975; `src/dnfw/waverider/dsp.py`). If that hook does
not run on a unit, MAIN shows nothing and the preview is silent: exactly depaffect's two
symptoms together. `docs/user-reports.md` T3 (v0.37, "SRC MAIN still doesn't get any signal")
was never resolved on hardware; T4 (preview) was closed as "hold both keys" after the owner
heard it on v0.37. The SHARC runner cannot model the master FX path (its master goes NaN after
two blocks), so the gate's `mainrec`/`pvmix` parts pass without proving this on hardware.
Candidates, none proven: Overbridge / USB audio routing, the master FX, or project routing
taking a path that skips `0x1c9d3f`. Ask depaffect: Overbridge? USB audio mode? master FX?

## 5. How the Octatrack does it (the reference)

From the Octatrack manual (manualsdir copy, p. 144, "Sampling using recorder trigs"):

- Select the track whose recorder you use with its [TRACK] key. Open RECORD SETUP 1 with
  [FUNCTION] + [AUDIO RECORD AB]. Set the sources (INAB, INCD, SRC3), RLEN and TRIG.
- **GRID RECORDING mode ([REC]); then a [TRIG] key places a recorder trig. While a RECORD SETUP
  menu is open, the sequencer shows only recorder trigs.** That is the key point: no knob, no
  p-lock: the recorder's own page turns the 16 keys into recorder-trig keys.
- A recorder trig samples all enabled sources by default; [TRIG] + [AUDIO RECORD AB/CD] or
  [MIDI] deactivates a source for that trig.
- **One-shot recorder trigs: [FUNCTION] + [TRIG]** (yellow LEDs): they sample once and need no
  removing afterwards (live sampling).
- [PLAY]: when the sequencer reaches the trig, the track's recorder samples.
- Captured samples are in the **recorder buffers**, listed above the first Flex sample in the
  Flex slot list ([UP] to reach them); they behave as Flex samples and are assigned to machines
  the same way. Eight buffers: one per track's recorder.

From memory, to verify in the manual before relying on it: RECORD SETUP 1's TRIG (ONE, ONE2,
HOLD) and LOOP; RECORD SETUP 2's QREC and QPLAY; one-shot trigs re-armed with a key combination
([FUNCTION] + [PLAY] or similar); manual sampling with [TRACK] + [AUDIO RECORD AB/CD]; the
Pickup machines as the looper.

Sources: [Octatrack manual p.144](https://www.manualsdir.com/manuals/657165/elektron-octatrack.html?page=144),
[Elektronauts: recording past RLEN](https://www.elektronauts.com/t/help-octatrack-recording-past-rlen-why/52307),
[Elektronauts: ending a one-shot recorder trig early](https://www.elektronauts.com/t/prematurely-ending-the-sampling-from-a-one-shot-recorder-trig/150311),
[Elektronauts: pickup looper using flex](https://www.elektronauts.com/t/pickup-looper-using-flex-update/249796?page=2).

## 5b. The owner's idea: a FLEX (or RAM) machine that owns the recorder (2026-11-07)

The owner, in his words: *"if a new track type will work, will fit in memory, and will make this
easier and more intuitive for both rec trigs and playback trigs, we can make it kind of a one
shot DT2 implementation of that machine we already have, but name it FLEX or RAM and have only
that one hold the new rec menu (if thats better than a page 2, which i dont mind but maybe this
is more intuitive?), and it can handle both the rec trigs and playback trigs by only showing the
rec trigs on the grid when the rec menu is open and the normal trigs only show when rec menu is
closed."*

So, to evaluate and, if it holds up, build:

- **A new sample machine type, FLEX (or RAM)**: ONESHOT's playback (the DT2's one-shot machine
  we already have) with the track's own recorder buffer as its sample, and the only machine
  that carries the new recorder menu. The Octatrack's Flex machine playing its track
  recorder's buffer is the model (manual 9.2.3, 11.1, 11.3).
- **One grid, two layers**: with the recorder menu open, the 16 [TRIG] keys and their LEDs are
  the track's **recorder trigs** (place, remove, FUNC + [TRIG] one-shot); with it closed, the
  normal (playback) trigs. As the Octatrack (manual 12.4.8, 12.10.4: "in the RECORD SETUP
  menus, the sequencer shows only recorder trigs").
- **QREC / QPLAY** as the Octatrack's (manual 9.1.3, the RECORDING SETUP 2 menu).
- **Check first that it fits**: the sample machines are types 8.. (`dnfw.sampler.machines.TYPE_OF`:
  ONESHOT, WERP, STRETCH, REPITCH, GRID, SLICE); a new type needs its MACHINE SEL entry, the
  DSP's dispatch, its frame words, its pages, and room: the sample machines' L2 code span
  (`dsp.SMP_L2_SPAN`, 24 KB, refused with under 64 bytes spare), each voice's 128 bytes of L1
  state (`SMP_STATE_DM`), the L1 tail (`dsp.REGION`; v0.43 put the Monomachine render scratch at
  0x2e5400..0x2e6400), the ColdFire's code room, and the recorder slots (123..126 today; per-track
  buffers as the Octatrack's eight would need more pool room). If it does not fit, or is not
  clearly easier, say so and propose the alternative (a fixed page 2 done properly).
- Whether there is one buffer per FLEX track (the Octatrack: one per track recorder) or the two
  shared ones, ask the owner before building.

### The Octatrack manual (OS 1.40A), what to read

The owner attached it (2026-11-07). In this container: `/home/claude/dn2/refs/Octatrack-User-Manual_OS1.40A.pdf`
(text: `ot.txt` beside it). If you are in a new session without it, ask the owner to attach it
again. It is Elektron's: never commit it to a repo. Pages (the PDF's page numbers):

| pages | sections |
|---|---|
| 17 | 4.4 Flex and static sample slot lists (where the recorder buffers sit) |
| 45-47 | 9.1 Recording edit and setup menus: 9.1.2 RECORDING SETUP 1 (sources, RLEN, TRIG, LOOP...), 9.1.3 RECORDING SETUP 2 (QREC, QPLAY, ...) |
| 48 | 9.2.1 Manual sampling |
| 49 | 9.2.2 Recorder trig sampling, 9.2.3 Playback of captured recorder samples |
| 50-51 | 9.3 Pickup machine sampling (the looper) |
| 56-57 | 11.1 Flex vs static machines, 11.3 assigning samples (and buffers) to machines |
| 66 | 12.3 Recording modes (GRID RECORDING) |
| 67-68 | 12.4 Trig types: trigless locks, trigless trigs, **one shot trigs**, slide trigs, **recorder trigs** |
| 74-75 | 12.10 Track trig edit menu: 12.10.4 RECORDER TRIGS |
| 81 | 13.1.3 the audio editor from track recorders |
| 105-107 | 17.1 Track recorder sampling, recorder trigs, playback of captured samples, pickup machines (the tutorial versions) |

## 6. What a redesign has to get right (the real variables)

- **Placing**: the Octatrack's model (recorder page open + GRID RECORDING: the [TRIG] keys
  toggle recorder trigs, LEDs show only them; FUNC + [TRIG] one-shot) is far clearer than a
  lock on H. It must make the step a trig the sequencer applies (or fire from the sequencer's
  step itself, not from a voice's lock list), so it records whether or not a note plays.
- **Conflicts to audit** (all live on or near the RECORDER): [TRIG] keys already mean "assign
  the take to this track" on ASSIGN SAMPLE TO TRACK?; FUNC + YES (preview on TRIM), FUNC + NO
  (drop), FUNC + PLAY (name cleared), LEFT/RIGHT (page 1/2, TRIM's ends), YES/NO stock questions
  (`question` gate step), FUNC + turn, SLD/SLEN on TRIG page 2 (slides, same lock store),
  Direct Jump (PTN + YES/NO), the +Drive browser and SLICE menus (their YES/NO and let-go rules:
  `alloc`, `hooks` steps), the DN2's own GRID RECORDING and live recording keys. `docs/ui-map.md`
  and `csrc/sampler/rec.c` (`smp_key` and friends) are where the keys are taken.
- **One ARM, named for what it does**; page 1's INTO shown as "INTO SAMP n" (or as a result,
  not a control); label the channel.
- **Feedback for every outcome**: armed with no REC trigs, a trig that fired, a refusal (and
  why), REC, NEXT, PLAY, where a take is and how to play it.
- **Save a take**: copy the playing buffer half into the next empty slot and save it.
- **Per-track or two buffers**: the Octatrack has eight (one per track recorder). Decide with
  the owner; keep the 2+1 player idea.
- **Sources**: MAIN depends on `wr_pvmix` running (section 4): settle that on hardware first, or
  every MAIN take is silent and will look like a REC trig bug.
- **Project and power**: arm state and buffers are RAM only; buffers off in old projects.
- **Timing**: tempo, R.LEN MAX = pattern length, QPLAY boundaries, song mode, pattern changes
  (Direct Jump), a REC trig while the other buffer records.

## 7. Proving it this time

- The emulator does not play the sequencer. Either make a harness that runs the real
  sequencer's step path for a few steps (find where stock walks steps and applies trigs), or
  accept that the end-to-end proof is on the unit and design for it: a visible debug line on
  page 2 (trigs seen, fired, refused and why, takes done) so the owner's one test tells you
  exactly where it stopped.
- Write the owner's hardware test as numbered steps in FIRMWARE.md, from a new project.
- Then the usual: `--only` step by step, the full gate, CLEARED TO FLASH on the exact file.

## 8. Where things stand (2026-11-07 04:40)

- **v0.42 LEAN published** (sha256 `8a8be7ac...`; FIRMWARE.md, builds branch, patcher, Pages
  checked, Discord). It changed nothing in the recorder; the rec-trig refusal reasons came in it.
- **v0.43 ROOM in its gate** (worktree `/home/claude/dn2/v043-wt`, branch `v043`, build
  `out/v043.syx`, sha256 `4089df39f689...`): 128 +Drive folders (Wolljamin), the Monomachine
  render scratch in L1 (SID -36 %, VO-6 -32 %, DENS/WAVE -30 %, DDRW -25 % per voice, bit-exact;
  `docs/dsp-cost.md`), the gate's boot steps faster (`docs/emu-speed.md`, identical state at
  700M instructions). Passed so far: unit 635, SHARC 8 of 10, ColdFire sample link, pools, boot.
  Remaining: SHARC link/rec/mainrec/pvmix/tdm and recwhole; ColdFire link16-dead, drive, jump,
  slice, slides, then erase, drivenav, samplist, colsw, fuzz, engine, meter, keepsamp,
  functurn, aniz, recorder, mnmpages, question, mnmdefaults, alloc, multisel, hooks, recflow,
  rectrig; then the full gate (reuses every pass) and publishing (CLAUDE.md steps 1-5, the
  release notes draft is in the old session's scratchpad: rewrite from FIRMWARE.md).
- **This machine**: 8 GB, 2 cores, at most two heavy jobs; a background job dies at 2 hours
  (split `--only` batches under it; passes are cached and reused); the container restarts now
  and then (re-launch; the cache survives). The SHARC runner needs
  `out/waverider/m2_init_75fdd2cdcbab.snap/.json` in the worktree (copy it from another one).
- **Commits** as De-Pattern (`git -c user.name=De-Pattern -c
  user.email=239624238+De-Pattern@users.noreply.github.com commit`), never the owner's name
  or email; never force-push; never bare `git stash`; firmware never on `main`. heavylight's
  Capicola source (in `/home/claude/dn2/capicola-src`) never goes into a public repo.
- **Still owed to the owner** (from the old session): depaffect's MAIN/THRES-0 answers, the
  Overbridge checklist, the 42-channel repo, the Aggregat read, the Capicola decision items, the
  paQ erase rerun, Pablo's encoder, confirming the LINKED default, the ultra-stable pass.

## Appendix: the v0.43 release notes draft (for `releases/v0.43.md` once it clears; `@@SHA@@` the build's sha256)

```
# v0.43 · ROOM

patcher: de-pattern.github.io/dn2mk2/patcher.html

room on the +Drive and on the DSP: the library holds 128 folders (it stopped at 64), and the Monomachine machines take a quarter to a third less of the DSP, same sound bit for bit.

**changed**
- **128 +Drive library folders**: the import page's "command 30: refused" came from the library's 64 folders being full (thanks Wolljamin). it now holds 128, folders inside folders past 64 too. an older library reads as it was; the extra folders are made the first time they're needed
- **lighter Monomachine machines**: their working memory moved to the DSP's fastest memory. per voice: SID 36% lighter, VO-6 32%, DENS and WAVE 30%, DDRW 25%. every output word is the same as v0.42's
- update the import page (the patcher site has it): it lists past 64 folders

**test**
1. import a pack with more than 64 folders (or keep making folders): no "command 30: refused" until 128
2. reboot: every folder and sample where it was, folders inside folders kept
3. a busy pattern with SID, VO-6, DDRW voices: hold FUNC on a Monomachine page and compare the load meter with v0.42's
4. everything from v0.42 (Machinedrum voices clean on a machine change, GRID/SLICE menus, REC trigs)

**known issues**
- one recorder: a REC trig while the other buffer records cuts that take
- buffers are off in a project with saved samples in SAMP 124-127 (from v0.32 or older)
- an LFO on SAMP or SLCE doesn't step through the loaded samples yet
- preset pool trig locks don't work with the mod's machines yet

**coming next (not available yet)**
- slides on the Monomachine, RESONATOR and CZ controls
- the naming screen as the Elektron one (UP/DOWN through characters)
- live resampling: a sample track playing the recorder's buffer as it records

sha256 `@@SHA@@` · back up your +Drive first · not made or supported by Elektron
```
