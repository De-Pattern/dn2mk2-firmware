# BOUNCE out of the firmware (v0.48): the plan

Owner, 2026-11-09: "pull it out for now, without breaking or affecting anything else about the
engine AT ALL or risking any type of crash"; v0.47 hides it (MACHINE SEL); "do it for the next
release. be extremely careful not to mess anything up". It is to be redesigned from scratch later.

## The rule

Remove what BOUNCE **does**. Keep what an **old project** needs to load: a project saved on
v0.44..v0.47 may hold a BOUNCE track (type 17) and patterns with recorder trigs. Nothing in the
DSP changes.

## What stays (compatibility)

| piece | why | where |
|---|---|---|
| type 17 known to every table (name, pages, sample row 6, MACHINE SEL group) | v0.44's freeze was a type our tables did not cover (`wr_label` read past its table). A loaded BOUNCE track must hit known rows | `sampler/machines.py` (BOUNCE_LISTED False stays), `pages.py`, `coldfire.py` |
| the lock store's third record kind (stored id 202), `slide.c` unchanged | recorder trigs are saved in the pattern beside the slides; reading, saving, copying, undoing them must not change, or the slides and locks beside them could be misread | `csrc/slides/slide.c`, `dnfw/slides.py` |
| the DSP: buffer directory, SAMP 129..144, STRETCH on a take's steps | the sample engine's layout; untouched DSP is the condition | `sampler/program.py`, `dsp.py` |
| a type-17 voice's SAMP written OFF (0) every frame | a loaded BOUNCE track plays nothing, never a stale or another track's slot | `link.c` `smp_mod_apply` (its branch kept, `want = 0`) |

## What goes (ColdFire only)

| piece | where | callers to cut |
|---|---|---|
| the recorder-trig engine: firing, buffers, QPLAY, QREC, plans | `csrc/sampler/rectrig.c` (the whole file) | `link.c` `smp_mod_apply` (`rt_frame`, `rt_bounce_samp`), `smp_tdm` (`rt_w`/`q_w` packets), the allocator's `rt_regions` and the buffer spans (`rt_rplace`, `rt_rbytes`, `rt_nx_*`, ~1361, ~1398), the span check (`rt_gen`, ~2483); `rec.c` `rec_poll` (`rt_poll`), `send()` (`rt_cut`, `rt_quantised`, `rt_q_set`), `rt_q_waiting`, `rt_manual`; `smp_page.c` (`rt_state`, `rt_count`, `rt_*` status) |
| the BOUNCE REC panel: keys, knobs, FUNC + YES save, YES YES, PAGE, the grid | `rec.c` `bn_*`, `knob()`'s BOUNCE branch; `smp_page.c` `bn_view_draw` | `bn_active()` callers in `rec.c` and `smp_page.c` |
| the trig-LED takeover | `rec.c` `bn_led_walk`, `bn_led_poll`; **the patch at the LED compose's walk (`coldfire.py` LED_SITE): stock's `jsr 0x4011d3b2` back**, checked byte for byte | |
| BUF's header text (v0.46) | `fmt.c` `f_buf` | record 244 is stock's on every machine again |
| the gate's `rectrig` step | `scripts/emu_rectrig.py` | replaced by `bouncegone` (below) |

Each of these is reached today only from a BOUNCE track (`rt_is_bounce`, `bn_active`), or does
nothing without one: `rt_regions` reserves nothing with no buffer used, `rt_cut` ends nothing with
no buffer take, `rt_quantised` is false with Q.REC OFF, and Q.REC is set only on the BOUNCE panel.
So for every project without a BOUNCE track the behaviour is unchanged by construction, and the
checks below test it.

## The order of work

1. **Neutralise, smallest diff first:** `bn_active()` 0, `rt_is_bounce()` 0, the type-17 SAMP
   branch writes 0. Build; run the steps that cover recording (recorder, recflow, link16, pools,
   machines, fuzz). Behaviour now equals the removal's.
2. **Delete what step 1 made unreachable,** one caller at a time, the compiler's errors as the
   list; no logic rewritten around it. The LED site back to stock's bytes.
3. **Measure** the image room and the audio interrupt's time freed (the meter step).

## Checks (gate)

- `machines`: unchanged: the power-on with every one of our types in the kit, type 17 included,
  and every MACHINE SEL row picked (no read below 0x40000000, no EXCEPTION).
- New `bouncegone` (replaces `rectrig`):
  - a BOUNCE track loaded (type 17 in the kit) plays SAMP OFF every frame, the sequencer
    playing over recorder trigs on its steps: no command to the DSP, nothing allocated;
  - FUNC + VOICE on it opens the ordinary RECORDER (YES records into the pool as on any track);
  - a pattern with recorder trigs (id 202) through SAVE/LOAD, copy/paste and undo keeps them
    byte for byte, and the slides on the same steps;
  - the LED compose's site holds stock's bytes;
  - record 244's text is stock's on every machine.
- Everything else as always; the full gate.

## Release note

BOUNCE removed (to be redesigned). A project with a BOUNCE track still loads; that track is
silent (pick another machine for it). Recorder trigs saved in patterns are kept, unused.
