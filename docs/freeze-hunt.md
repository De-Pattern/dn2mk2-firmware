# The freeze and dead-key hunt (v0.33, 2026-10-30)

Reports: the unit freezes on the sample list (zugada_ U2, the owner O5, Pablo Se7en's video:
ONESHOT, the SAMP list up, keys do nothing, no audio, a pattern playing); SLICE / GRID's YES
does nothing until a track is cleared or the machine changed twice; slowdowns with a large
+Drive library (Pablo); a track stuck on its machine (Pablo).

## Found and fixed

| where | what went wrong | fix | checked by |
|---|---|---|---|
| rec.c, the held keys | MACHINE SEL (FUNC + SRC) takes SRC's release itself: SRC stayed "held", and a YES with any key held went to stock: SLICE / GRID's YES menus dead until SRC was pressed again | only a [TRIG] held (pressed in the last 10 s) makes YES stock's | emulator repro (held_lo 0x404 after MACHINE SEL); gate 6e goes through MACHINE SEL |
| rec.c, the eaten keys | a key whose press we took waits for its release; a release that went elsewhere left every later press of that key going to stock | a press of a key still waiting is a new press | code review (the same class as the above) |
| slice.c, the stock question | any FUNC combination marked a stock question pending, and the next YES or NO was given to it | only FUNC + a page or menu key can raise one | gate 6e (YES after FUNC + LEFT) |
| rec.c / smp_page.c, the sample list | left open when another track became active (a stock machine's page never closes it), it went on taking UP, DOWN, YES and NO unseen for up to 20 s | the list closes when the active track is not its own | code review |
| smp_page.c, +DRIVE | the folder's count and each of six rows walked all 2,048 library entries every redraw | the folder's list built once (rebuilt when the folder or the index changes) | gate 6l |
| link.c, SAMP modulation | in the audio interrupt, up to 4,096 slot checks a frame (16 voices with SAMP modulated) | the loaded slots listed once a frame | gate 6h (modulation through the slots) |
| the DSP's sample reader | a slot's entry was trusted as it was: one outside the pool (half-written by the link, stale, garbage) read DDR at a stray address (garbage, or NaN: one NaN in a feedback state silences the unit) | an entry outside the pool plays as an empty slot | runner step 3b, six bad entries, bit-exact |
| fmt.c, FUNC + turn | v0.32 held every control it did not know on our tracks, the LFO pages' too | only our machines' records (238..260) | gate 6m, LFO controls on three machine kinds |

## New checks

- `scripts/emu_fuzz_ui.py`: random sequences on the sample pages (SAMP turns, the list, the
  browser, its menu, page and [TRIG] keys, MACHINE SEL, the machine changed under the page,
  PLAY) with the audio interrupt's frame build between them; a seed fails on a run that does
  not finish (an exception), a memory fault in our code, or a last probe that changes nothing
  on screen (hung).
- Runner step 3g: every Machinedrum and Monomachine machine started on voice state and
  scratch full of NaN or random words: every block returns, finite, PERC bit-exact.
- Runner step 4: each Monomachine machine beside stock tracks: the stock tracks bit-identical.
- The gate's first steps: the ColdFire code current against `csrc/`, and the build this
  tree's, byte for byte (v0.33's first builds were tested on stale compiled code).

## Not reproduced

- Pablo's exact freeze (the screen frozen and no audio). On the unit, both stopping at once
  points at the audio interrupt or the DSP: the DSP stopping (a stray read is the likeliest
  way, now closed for sample entries) leaves the ColdFire waiting on it. The fixes above
  close the paths found; the report stays open until a tester confirms.
- "Stuck on its machine" (Pablo, PERC): needs which control (MACHINE SEL, or PERC's TYPE).
  TYPE is p-lockable: a pattern with TYPE locks keeps those trigs' machines whatever the
  knob says, and clearing the track removes the locks.
