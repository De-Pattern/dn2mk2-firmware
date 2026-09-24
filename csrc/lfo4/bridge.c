/* From the table to the engine: the tick pulls, nothing pushes.
 *
 * Steps 1-2 put LFO4's values in a table keyed by the **live sound's address**;
 * step 3 made the engine read a **per-track row**. This joins them, and it does
 * so from the engine side on purpose.
 *
 * The push alternative was to hook the control path, `Sound::updateMirror`.
 * Reading it killed that: it is a *per-parameter* update -- one slot at a time,
 * `mvsw %a0@(14,%d2:l:2),%d1` at `0x4004cb08` -- and LFO4's parameters are not
 * slots of a sound, so there is nothing there to hook. Worse, a push only
 * covers the paths we have enumerated.
 *
 * So `a4_top` and `b_top`, which already run once per track with the track
 * index in hand, call this instead. It copies only when the track's sound has
 * changed or when something has edited the table, which is two loads and two
 * compares in the common case -- and it is right for **every** edit path,
 * named or not, the same argument that made step 1's carry range-based rather
 * than a list of sizes.
 *
 * `sound(track) = *(0x800052a0) + 52 + track * 1163`, which is the firmware's
 * own arithmetic at `0x40025bda` including where it gets the base. An earlier
 * version of this file held that base as a build-time constant and it was the
 * reason a fully working page modulated nothing.
 */
#include "ext.h"
#ifdef LFO4_TELEMETRY
#include "tlm.h"
#endif

#define TRACKS       16
#define ROW_BYTES    (2u * EXT_PARAMS)

/* The rows the engine reads, and **they live here, in our own BSS.**
 *
 * They used to sit in the code cave inside MAIN OS, at an address passed in as
 * `LFO4_ROWS`. That was wrong on its own terms: a cave is a gap in somebody
 * else's *code*, and these are mutable state written every tick. Step 3 got
 * away with it because its table was written once at build time and only ever
 * read; the bridge writes to it at run time, which is a different thing to ask
 * of a code region.
 *
 * Owning them here also deletes a build-time constant: the stubs get the
 * address from `lfo4_refresh`'s return value, so nothing has to agree about a
 * number in two places. */
u16 lfo4_rows[TRACKS][EXT_PARAMS];

u32 lfo4_refreshes, lfo4_copies_in;

/* Did the last lookup the tick actually performed find a row? `+1` yes, `-1`
 * no, `0` not once yet. It is deliberately the last *lookup* and not the last
 * call: the cached path returns without asking the table, so this stays what
 * the row now in use was built from, which is the question. `csrc/lfo4/meter.c`
 * puts it on the page. */
u32 lfo4_hits, lfo4_misses;
int lfo4_last_lookup;

/* **The index the engine actually hands us, recorded rather than inferred.**
 *
 * On 2026-09-23 the owner found LFO4 modulating only on one voice, and the
 * voice number follows the *track index* of whichever track has LFO4
 * configured -- two configured tracks gave two working voices, on any track.
 * So the row is being selected by something that is not the track, and
 * `lfo4_refresh`'s only guard is `track >= TRACKS`, which any 0..15 passes.
 *
 * Both call sites name their register in a comment in `build_lfo4_tick7.py`
 * and **neither was ever measured**. That is the bug's whole origin, so this
 * one is measured: whatever arrives is stored here and put on the page. */
u32 lfo4_last_index;

/* **The highest index ever handed to us, because "the last one" was clobbered.**
 *
 * The first attempt recorded only the most recent call. Both patch sites call
 * this function, so a site that fires constantly with 0 hides a site that fires
 * occasionally with the real index -- and the page duly read 0 for ever while
 * the instrument was plainly selecting rows by voice. A running maximum cannot
 * be hidden that way: if any call ever arrives with 10, this reads 10 and stays
 * there. */
u32 lfo4_index_max;

/* **The DEST of the row we actually hand back, recorded at the moment we hand
 * it back.**
 *
 * Two measured facts do not fit together: the index reaching this function is
 * always 0, so only row 0 is ever populated -- and row 0 is filled from track
 * 1's sound, which has no LFO4 settings, so its DEST should be None and LFO4
 * should never modulate anything. Yet on the instrument it modulates on the
 * voice matching whichever track has LFO4 configured.
 *
 * So either the row is not what this function thinks it is, or the evaluator
 * is not reading the row this function returns. This records the first half:
 * the destination code sitting in the row at the moment it is returned. If it
 * is None while the instrument is plainly modulating, the evaluator is getting
 * LFO4's parameters from somewhere other than here. */
u32 lfo4_row_dest;

/* **The calls that never get counted, which may be all the interesting ones.**
 *
 * The range guard returns before `lfo4_refreshes++`, so a call with an index of
 * 16 or more is invisible to every counter here -- it just gets row 0's base
 * back. `%a5` at evaluator A's site is an *address* register, and an address
 * passed as an index would do exactly that, every time, leaving the visible
 * counters reading a steady 0 while the real traffic went unrecorded. Measured
 * rather than assumed, because assuming what a register holds is the mistake
 * this whole bug is made of. */
u32 lfo4_out_of_range;
static u32 seen_sound[TRACKS];
static u32 seen_generation[TRACKS];

/* -> where the firmware keeps this track's live sound, or 0 before there is
 * one.
 *
 * **The base is read, not assumed.** It used to be `LFO4_KIT`, a constant
 * measured once out of a snapshot, and the snapshot agreed with it because
 * that is where it was measured. The firmware's own routine
 * (`0x40025bda`) reads a global instead, and so does this: the container moves
 * when a project loads, and a stale base means `ext_find` misses every key the
 * setter writes -- the page works, sounds save, and nothing modulates.
 *
 * A zero base means no container yet. Returning 0 is safe: `ext_find(0)` has
 * always answered "no entry", and the row is then the defaults. */
u32 lfo4_sound_of(u32 track)
{
    u32 base = *(volatile u32 *)DN2_LIVE_CONTAINER;

    return base ? base + DN2_SOUND_AT + track * DN2_SOUND_STRIDE : 0;
}

/* The mirror geometry, from `docs/fx-master-modulation.md` §9 and the
 * evaluator's own arithmetic at `0x400db092`: `202*block + 34`. */
#define MIRROR_BASE   0x800068E4u
#define MIRROR_AT     34u
#define MIRROR_STRIDE 202u

/* What the block pointer resolved to, for the page. A wrong answer here is
 * visible instead of silent, which is the whole lesson of this bug. */
u32 lfo4_block_track = 0xFFu;
u32 lfo4_block_ptr;                  /* the last block, for the page */
u32 lfo4_beat;                       /* telemetry heartbeat, steps per burst */
u32 lfo4_frame;                      /* the stub's stack pointer */
u32 lfo4_word;                       /* the frame word currently being reported */
u32 lfo4_block_base = 0xFFFFFFFFu;   /* the lowest block seen = track 0's */

u32 lfo4_refresh(u32 track);

/* -> the row for the track whose mirror block this is.
 *
 * **Why a pointer and not an index.** Both patch sites used to pass a register
 * named "the track index" in a comment that was never measured. `%a5` turned
 * out to be zeroed at the evaluator's entry and only advanced by the per-track
 * `outer` stub, which does not run here -- so the index was 0 on every track,
 * on every voice, for months, and LFO4 read one fixed row.
 *
 * `%sp@(56)` is the pointer the stock code uses for LFO1-3: `outer` advances it
 * by 202 per track, and `a4_bottom` restores `%a4` from it. Deriving the track
 * from it means LFO4 and LFO1-3 cannot disagree about which track they are on,
 * because they are reading the same pointer. That is a guarantee by
 * construction rather than by a comment, which is the point. */
/* -> the byte `param_5[track]` would hold if `w` were `param_5`, or a sentinel.
 *
 * **The static read says where to look; this says whether it is right.**
 * Evaluator A takes seven arguments (the call site's `lea %sp@(28),%sp` counts
 * them) and `param_5`, at its `%sp@(96)`, is a pointer to a sixteen-byte array
 * holding **one signed byte per track: the voice allocated to that track, or
 * -1**. The caller builds it at `0x400271a2` -- both arrays default to -1 (`st
 * %d4`) and a real value is written only where `0x40138664(bit)` returns the
 * same object as `0x4002b22e(track)`, which is what makes the byte a voice.
 *
 * What is *not* known is where that argument sits relative to this stub's
 * `%sp`. The stub is reached by `jmp` from inside evaluator A, and the frame
 * map read on the instrument does not line up with the arithmetic cleanly
 * enough to name one offset. Three offsets have now been guessed at this frame
 * and all three were wrong, so this one is not guessed: the existing walk
 * already visits all 32 words of the safe window, and each is asked the same
 * question. Whichever word is `param_5` will answer with a small number that
 * follows the voice allocation display; the rest will answer with a sentinel.
 *
 * **The guard, and why it needs no constant.** `param_5` points at
 * `%fp@(-88)` in *the caller's* frame, so it is a stack address above this one
 * and close to it. `frame` is itself a stack address, so the check is
 * self-referential -- nothing hardcoded to be wrong when the task stack moves.
 * A word failing it is never dereferenced.
 *
 * **A read is not free.** Extending the walk to +508 killed the instrument's
 * MIDI output on 2026-09-23 -- audio kept playing, notes and telemetry both
 * stopped. This adds no reach at all: the same 32 words, plus one dereference
 * that must first prove it points just above our own stack pointer. */
#ifdef LFO4_TELEMETRY
#define TLM_V_NOTPTR  126u    /* the word is not a plausible frame pointer */
#define TLM_V_NONE    127u    /* it is, and the track has no voice (-1) */

static u8 voice_at(u32 w, u32 track, u32 frame)
{
    signed char v;

    /* above us, and within one frame's reach: the caller's locals, nothing else */
    if (w <= frame || (w - frame) > 0x400u || (w & 1u))
        return (u8)TLM_V_NOTPTR;
    v = *(volatile signed char *)(w + track);
    if (v < 0)
        return (u8)TLM_V_NONE;
    return (u8)(v & 0x7Fu);
}
#endif

u32 lfo4_row_for_block(u32 block, u32 frame)
{
    u32 track;

    /* **`%a4` already holds it, and Ghidra is what showed that.**
     *
     * Two stack offsets were tried and both were wrong -- `%sp@(72)` read a
     * constant 52 on the instrument -- because `a4_top` and `a4_bottom` are
     * patched at different addresses and the stock code between them moves the
     * stack. Guessing frame layout by hand cost five flashes.
     *
     * The decompiler settles it. Evaluator A keeps the per-track mirror pointer
     * in a local:
     *
     *     local_18 = param_1 + 0x22;        // the buffer + 34
     *     do {                               // once per track
     *       iVar12 = local_18 + -0x22;       // the instruction a4_top replaced
     *       ... *(short *)(iVar12 + 0x44)    // %a4@(68), the LFO reads
     *
     * So the displaced `lea %a4@(-34),%a4` means **`%a4` holds that pointer on
     * entry to the stub** -- which our own stub source already said in a
     * comment, and which nobody checked. It is a register, not a stack slot,
     * so there is no frame layout left to get wrong.
     *
     * The base is still unknown, and it must not be assumed a second time: the
     * buffer is low in RAM, not the global mirror. `local_18` advances 202 per
     * track, so the lowest value ever seen is track 0's and every other track
     * is a whole number of strides above it. */
    if (block < lfo4_block_base)
        lfo4_block_base = block;
    lfo4_block_ptr = block;
    lfo4_frame = frame;               /* the stub's %sp: a window into the caller */
    track = (block - lfo4_block_base) / MIRROR_STRIDE;
    if (track >= TRACKS)
        track = 0;
    lfo4_block_track = track;
#ifdef LFO4_TELEMETRY
    /* **The first thing this channel ever sends, and it is built to be read
     * even if it is wrong.**
     *
     * `marker` is a counter that steps 0..127 on every emission: a value that
     * visibly sweeps proves the path is alive independently of whether any
     * diagnostic number is correct, and its rate tells us how often this
     * function actually runs, which nothing has measured. `track` and the mask
     * are the real payload -- the mask being the question six flashes failed to
     * answer, because a display that renders only the high byte cannot show a
     * 14-bit value at all.
     *
     * **The period must be coprime with 16, and 2048 was not.** The engine walks
     * the sixteen tracks in order, so the track a burst lands on is the call
     * index modulo 16 -- and 2048 mod 16 is 0, which pinned every burst to the
     * same track for ever. The first run duly reported `track = 15` on every
     * sample and looked like the firmware pinning something. It was the
     * sampling period, not the firmware.
     *
     * 2049 mod 16 is 1, so each burst steps to the next track and all sixteen
     * are reported in sixteen bursts -- about 1.4 s at the measured rate.
     *
     * Rate: the marker stepped every ~87 ms at 2048, so this function runs
     * about 23,500 times a second, or ~1,470 evaluator passes across 16 tracks.
     * Nothing had measured that before. Four messages per 87 ms is ~46/s
     * against MIDI's ~1,040/s ceiling, so there is room. */
    if (tlm_every(0, 2049)) {
        /* **Walk the caller's frame instead of guessing one slot.**
         * `probe_b` says which word is being reported and `mask_lo`/`mask_hi`
         * carry its low 14 bits; the index advances every burst, so 32 words --
         * 128 bytes of evaluator A's frame -- are mapped in 32 bursts, under
         * three seconds. The enable mask is in there somewhere and will show
         * itself as a value that is neither 0 nor a pointer. */
        {
            /* **Reach past the locals to the arguments.** The first walk
             * covered +0..+124 and found the frame's own working set: the
             * per-track mirror pointer at +8 stepping by 202, a second pointer
             * at +80 and +100 stepping by 153 -- both strides matching `outer`
             * -- and the 0x3840 scale at +104. No enable mask, and that is
             * where it should be: `%sp@(88)` was read at the *function entry*
             * frame, and this stub runs below all of evaluator A's locals, so
             * the arguments sit further up. This walks +0..+508. */
            /* **Back to 32 words, because 128 broke the instrument's MIDI.**
             * The +0..+124 walk ran cleanly and produced a usable frame map.
             * Extending it to +0..+508 in one step killed MIDI output entirely
             * -- the instrument kept playing audio and stopped sending notes
             * *and* telemetry, which is what a dead transmit task looks like.
             * Nothing else changed between the two builds.
             *
             * So this is not a free read. 512 bytes above the stub's stack
             * pointer is past evaluator A's own frame; "over-reach and discard"
             * was wrong, and the reach is now part of what has to be earned
             * rather than assumed. */
            u32 k = (lfo4_beat >> 4) & 31u;        /* hold each word for 16 bursts */
            u32 w = *(volatile u32 *)(frame + 4u * k);

            lfo4_word = w;
            tlm_cc(TLM_CC_TRACK, (u8)track);
            tlm_cc(TLM_CC_PROBE_B, (u8)k);
            tlm_cc14(TLM_CC_MASK_LO, TLM_CC_MASK_MID, (u16)(w & 0x3FFFu));
            tlm_cc(TLM_CC_VOICE, voice_at(w, track, frame));
        }
        tlm_cc(TLM_CC_MARKER, (u8)(++lfo4_beat & 0x7Fu));
        /* **A constant whose correct answer is known before the flash.**
         * Twice now a number was read off an instrument of this project's own
         * making without checking that the instrument reports faithfully: the
         * LFO4 page renders only the high byte, and the first sampling period
         * was a multiple of the loop length. Both looked like findings. So one
         * signal carries 99 and nothing else: if `probe_a` reads 99, the values
         * beside it can be trusted; if it does not, none of them can, and that
         * is visible instead of silent. */
        tlm_cc(TLM_CC_PROBE_A, 99);
    }
#endif
    return lfo4_refresh(track);
}

/* -> the address of this track's row, current as of now. */
u32 lfo4_refresh(u32 track)
{
    u32 row = (u32)lfo4_rows + track * ROW_BYTES;
    u32 sound, generation;
    u16 *values;
    u32 k;

    if (track >= TRACKS) {
        lfo4_out_of_range++;
        return (u32)lfo4_rows;            /* never index past the table */
    }
    lfo4_refreshes++;
    lfo4_last_index = track;
    if (track > lfo4_index_max && track < TRACKS)
        lfo4_index_max = track;
    sound = lfo4_sound_of(track);
    generation = ext_generation;
    if (sound == seen_sound[track] && generation == seen_generation[track])
        return row;

    seen_sound[track] = sound;
    seen_generation[track] = generation;
    lfo4_copies_in++;
    values = ext_find(sound);
    if (values) {
        lfo4_hits++;
        lfo4_last_lookup = 1;
    } else {
        lfo4_misses++;
        lfo4_last_lookup = -1;
    }
    lfo4_row_dest = (u32)(((u16 *)row)[3] >> 8) & 0x7Fu;
    for (k = 0; k < EXT_PARAMS; k++)
        ((u16 *)row)[k] = values ? values[k] : ext_default[k];
#ifdef LFO4_FORCE_ROW
    /* **A bisect switch, off in every shipped build.**
     *
     * The instrument reports a fourth page that works and modulates nothing.
     * Two halves could be at fault and the emulator cannot separate them: the
     * lookup above (does the table hold what the panel wrote, under the key
     * the tick asks for?) or everything below it (do the evaluator stubs
     * actually turn a row into sound?).
     *
     * With this defined the lookup's answer is discarded and every track gets
     * `tick7`'s row -- the one combination already proved audible on the
     * instrument. If that sweeps, the engine path is fine and the lookup is
     * the fault; if it does not, the engine path broke when the bridge
     * replaced tick7's fixed table with a call.
     *
     * It is deliberately *after* the lookup, so the lookup still runs and its
     * counters still move: a build that crashed in `ext_find` would not be
     * silently exonerated by skipping it.
     */
    {
        static const u16 forced[EXT_PARAMS] = {
            0x7000,     /* SPD  -- fast */
            0x0800,     /* MULT -- middle, not the slowest: tick7's lesson */
            0x4000,     /* FADE -- neutral */
            76 << 8,    /* DEST -- the slot tick7 swept audibly on hardware */
            0x0100,     /* WAVE -- a continuous shape */
            0x0000,     /* SPH */
            0x0000,     /* MODE */
            0x7FFE,     /* DEP  -- maximum */
        };

        for (k = 0; k < EXT_PARAMS; k++)
            ((u16 *)row)[k] = forced[k];
    }
#endif
    return row;
}
