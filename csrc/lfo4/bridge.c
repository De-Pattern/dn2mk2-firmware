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
#ifdef WAVERIDER_M0
#include "waverider.h"
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


#ifndef LFO4_TRACK_KEYED
/* -> the live sound that owns voice `v`, or 0; and in `lfo4_owner[v]` the
 * track it belongs to (126 empty, 127 not one of the sixteen live sounds).
 *
 * **Why this replaces a lookup instead of adding one.** The owner asked on
 * 2026-09-25 why LFO4 needs a lookup at all, when LFO1-3 plainly do not. The
 * answer took the whole day and it is the fix: the firmware does not keep one
 * block per track. It keeps **one per voice**, and fills each from the sound
 * of whichever track owns that voice -- which is why stock LFO3 on track 7
 * appeared in every block and every frame record once track 7 had played on
 * all sixteen voices, while LFO4, read from a table keyed by track, appeared
 * in block 6 alone (`lfo4-framescan`, runs A and B, other tracks unchanged).
 *
 * The sound on each voice is recorded by the delivery itself,
 * `0x4002549c`, in `DN2_VOICE_SOUND` -- the same routine that copies the
 * sound's parameters into that voice's block (`dn2_111.h`). Our table is
 * keyed by live sound pointer, so that record *is* the key and nothing
 * needs translating.
 *
 * ~~`DN2_OWNER_REG`~~ was the first version of this and read 127 on every
 * voice on the instrument: it is what the fan-out writers compare against,
 * not the sound.
 *
 * **Checked, not trusted.** The entry must be exactly one of the sixteen live
 * sounds (`lfo4_sound_of`) before it is used; anything else falls back to the
 * old behaviour and says so in telemetry, so a wrong guess about what the
 * array holds is visible on the first burst rather than silent. The check runs
 * only when an entry changes -- voices change hands per note, the tick runs
 * 23,500 times a second, and sixteen compares per tick would be the cost of
 * not caching it. */
u32 lfo4_owner[TRACKS];
static u32 owner_raw[TRACKS];
static u32 owner_sound[TRACKS];
/* Checked once per change, not once per tick. The first version re-ran
 * all sixteen compares on every call whenever the entry was not a live
 * sound -- which, on the wrong array, was every call. */
static u8 owner_seen[TRACKS];

static u32 lfo4_voice_sound(u32 v)
{
    u32 raw = *(volatile u32 *)(DN2_VOICE_SOUND + 4u * v);

    if (!owner_seen[v] || raw != owner_raw[v]) {
        u32 t;

        owner_seen[v] = 1;
        owner_raw[v] = raw;
        owner_sound[v] = 0;
        lfo4_owner[v] = raw ? 127u : 126u;
        if (raw)
            for (t = 0; t < TRACKS; t++)
                if (lfo4_sound_of(t) == raw) {
                    owner_sound[v] = raw;
                    lfo4_owner[v] = t;
                    break;
                }
    }
    return owner_sound[v];
}
#endif

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
/* **The voice probe lived here, and it answered.** `param_5` and `param_6` were
 * measured to reach this stub at `frame + 116` and `frame + 120`
 * (`scripts/emu_lfo4_frame.py`, which passes those pointers itself and then
 * finds them -- a control on both arms). Read there on the instrument, both are
 * **-1 for all sixteen tracks on every one of 468 bursts** while the sequencer
 * played. So they are not "the voice allocated to this track"; they are the
 * voice whose LFO state must be *migrated* this frame, and in steady state that
 * path correctly does nothing. The helper is gone because the question is
 * answered -- `docs/lfo4-build-plan.md` keeps the reasoning. */

#ifdef LFO4_FRAMEREAD
/* -> the address in the DSP frame that this mirror slot is copied to, or 0.
 *
 * **Why read the frame and not only the mirror.** LFO4's value is measured
 * arriving in the mirror every frame (graded control, 2026-09-24). If it is
 * still inaudible on most voices, the next question is narrow: does it survive
 * the copy into the frame the DSP actually receives? This answers that in one
 * flash instead of a week of SHARC reading.
 *
 * The geometry is read from the frame builder at `0x400274ba`, not guessed.
 * `%a4` starts at `0x80005e60` and strides **146 per track**; the loop runs 16
 * times (`%d2` steps by 2 to 32). Four `memcpy`s move mirror slots into it:
 *
 *   dst %a4@(218) <- %a5@(84)  82 B   slots 25..65
 *   dst %a4@(300) <- %a5@(166) 28 B   slots 66..79
 *   dst %a4@(328) <- %a5@(194) 26 B   slots 80..92
 *   dst %a4@(354) <- %a5@(224) 10 B   slots 95..99
 *
 * A row's slots start at `+34`, so `%a5@(84)` is slot 25 and the four ranges
 * tile 25..99 with **93 and 94 deliberately absent** -- a gap worth knowing
 * about before reading a zero there as a finding.
 *
 * The frame lives in fast SRAM (`0x80000000`..`0x80010000`), which is mapped
 * and small; the furthest address this can produce is
 * `0x80005e60 + 146*15 + 354 + 8`, comfortably inside it. **No unmapped read
 * is reachable from here**, which is the constraint the +508 walk violated. */
#define FRAME_BASE   0x80005E60u
#define FRAME_STRIDE 146u

static u32 frame_word_for(u32 track, u32 slot)
{
    u32 rec = FRAME_BASE + FRAME_STRIDE * track;

    if (slot >= 25u && slot <= 65u) return rec + 218u + 2u * (slot - 25u);
    if (slot >= 66u && slot <= 79u) return rec + 300u + 2u * (slot - 66u);
    if (slot >= 80u && slot <= 92u) return rec + 328u + 2u * (slot - 80u);
    if (slot >= 95u && slot <= 99u) return rec + 354u + 2u * (slot - 95u);
    return 0u;                       /* 93, 94 and everything outside: not copied */
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
            /* **The sweep is over: it found the pair, and then could not read
             * it.** Walking 32 words gave one sample per (word, track) pair,
             * and a voice exists only while a note is sounding on one track --
             * so sixteen samples spread across sixteen tracks were never going
             * to catch one. Words 29 and 30 duly read -1 every time. That is
             * the probe being blind, not the array being empty, and reading it
             * as a negative result would have been the fourth uncontrolled one
             * in this file's history.
             *
             * What the sweep did establish, over 585 bursts with `probe_a`
             * reading 99 on every one: **`frame+116` and `frame+120` are the
             * only adjacent pair in the window that are valid frame pointers**,
             * and `param_5`/`param_6` at `%sp@(96)`/`%sp@(100)` are adjacent
             * and 4 apart. Everything else read 126 (not a pointer) except one
             * word holding unrelated bytes.
             *
             * So both are now read **every burst**. The track still cycles, so
             * each track is sampled every 16 bursts -- about 1.4 s -- instead
             * of once per 45-second sweep. A voice held for the length of a
             * note cannot hide from that. */
            /* **Read the PREVIOUS track's destination slot, not this one's.**
             *
             * The first attempt read this track's slot and was blind by
             * design. The engine's order within one audio frame is: regenerate
             * the whole mirror from the control side, apply the six MIDI
             * performance modulators, run the LFOs, build the DSP frame
             * (`0x400274ba`), send it. This stub fires at the *start* of this
             * track's LFO4 iteration -- so the mirror it sees has been
             * regenerated and no LFO has written to it yet. It read a constant
             * on all sixteen tracks, and it would have read a constant whether
             * LFO4 worked perfectly or not at all.
             *
             * Track `t-1` is the fix and it costs nothing. Its whole LFO pass
             * finished moments ago and its mirror row is not regenerated until
             * the next frame, so its destination slot holds **base plus
             * whatever the LFOs just wrote**. A value that moves is a value
             * being written every frame.
             *
             * **No new reach.** One 202-byte record below, inside the same
             * array the evaluator walks, and bounded against `lfo4_block_base`
             * -- which is *learned*, not assumed, so nothing here depends on a
             * constant that a project load could move.
             *
             * The control is unchanged and it is the point: **every track
             * reports**. Tracks with no LFO4 must show `DEST = 0` and a value
             * that does not move. If they move too, this is measuring
             * something other than LFO4 and none of it counts. */
            u32 prev = (track + (TRACKS - 1u)) & (TRACKS - 1u);
            u16 *prow = (u16 *)((u32)lfo4_rows + prev * ROW_BYTES);
            u32 dest = ((u32)prow[3] >> 8) & 0x7Fu;
            u16 at_dest = 0;
            u32 base = lfo4_block_base;

            if (base != 0xFFFFFFFFu && dest <= 100u) {
                u32 row_ptr = base + MIRROR_STRIDE * prev;

                /* **`block + 2*slot`, and the 34 is NOT subtracted here.**
                 *
                 * The first two builds read `block - 34 + 2*slot` and were 34
                 * bytes -- seventeen slots -- low, reporting slot 9 while
                 * calling it slot 26. Both duly read a constant, and the
                 * constant was nearly taken as "LFO4 never writes".
                 *
                 * The owner's control is what caught it: with **LFO1** pointed
                 * at the same destination and audibly modulating, the value
                 * still did not move. A known-good LFO showing nothing means
                 * the probe is wrong, not the LFO -- which is the whole reason
                 * to run a positive control beside a negative result.
                 *
                 * The geometry: `mirror = 0x800068e4 + 34 + 202*block +
                 * 2*slot`, so the **+34 is a one-time offset to the start of
                 * the array**, not a per-record header. `%a4` already points at
                 * `param_1 + 34 + 202*track`, so slots run from it directly.
                 *
                 * Confirmed against the evaluator's own read: after
                 * `lea %a4@(-34),%a4` it takes a parameter from `%a4@(68)`,
                 * which is `block + 34` = **slot 17** = `8*2+1`, LFO3's first
                 * parameter. The mapping can only be `block + 2*slot`. */
                at_dest = *(volatile u16 *)(row_ptr + 2u * dest);
            }
            lfo4_word = at_dest;
            tlm_cc(TLM_CC_TRACK, (u8)prev);
            tlm_cc(TLM_CC_DEST, (u8)dest);
#ifndef LFO4_TRACK_KEYED
            tlm_cc(TLM_CC_OWNER, (u8)lfo4_owner[prev]);
#endif
            tlm_cc14(TLM_CC_OWN_LO, TLM_CC_OWN_HI, (u16)(at_dest >> 2));
#ifdef LFO4_FRAMEREAD
            /* **The same value, one copy later.** If the mirror pair moves and
             * this pair does not, the value is lost between the LFO stage and
             * the frame -- on this processor, and findable. If both move, the
             * value reaches the DSP and nothing on the ColdFire is at fault.
             *
             * The control is free and already present: put a stock LFO on the
             * same destination and **both** pairs must move. If they do not,
             * this address is wrong and no reading from it counts. That is the
             * check that was missing when the probe read seventeen slots low. */
            {
                u32 fa = frame_word_for(prev, dest);
                u16 fv = fa ? *(volatile u16 *)fa : 0u;

                (void)fv;
                /* **A zero here has two meanings, and they point opposite ways.**
                 *
                 * `frame_word_for` returns 0 for a slot the builder never
                 * copies -- 93, 94, and everything outside its four tiled
                 * ranges -- and the read above then reports `0`, which is
                 * indistinguishable from a frame word that genuinely holds
                 * zero. One says "this destination cannot reach the DSP at
                 * all", which would be the whole answer; the other says "it
                 * can, and nothing wrote it". Leaving them to look identical is
                 * how a probe comes back uninterpretable, which has already
                 * cost this project two flashes.
                 *
                 * So the status is sent beside the value: **0** the address was
                 * valid and read, **1** this destination is never copied into
                 * the frame, **2** no destination is set on that row. */
                tlm_cc(TLM_CC_FRAME_ST, (u8)(dest == 0u ? 2u : (fa ? 0u : 1u)));

                /* **Rotate through all sixteen, and report both copies.**
                 *
                 * The block scan settled where the mirror is written: track
                 * 7's own block sweeps the full range for 104 seconds while the
                 * owner hears it on voice 7 only. So the mirror is right, and
                 * the question has moved one hop on -- the sixteen DSP frame
                 * records the builder fills from it.
                 *
                 * **Why rotate instead of picking the furthest from neutral.**
                 * The argmax this replaces assumed neutral was 0x1000, which is
                 * true of the mirror and *unknown* of the frame -- every frame
                 * read so far has been of the driven record. It also produced
                 * an artefact on the mirror: when the driven block passed near
                 * neutral, a block with a small static offset won, and block 0's
                 * resting 3890 was reported as "the sweeping block" for a third
                 * of the capture. A probe that has to be explained is a probe
                 * that will eventually be misread.
                 *
                 * Rotating assumes nothing. Each burst reports block and record
                 * `scan_idx`, cycling 0..15, both at this row's destination;
                 * over a long capture every record is sampled many times, and
                 * the host asks which ones *vary*. A record that varies carries
                 * a modulation, whatever its resting value turns out to be.
                 *
                 * **Run it twice, and the second run is the control.** With
                 * stock LFO3 driving, a record that varies besides this track's
                 * own -- or one that changes as the allocator moves the note --
                 * means the firmware replicates a stock LFO into the voice's
                 * record. If LFO4 then varies only in its own, that is the
                 * difference, and it is ColdFire code. If both vary only in
                 * their own, the ColdFire treats them identically and the
                 * difference is inside the SHARC. */
                if (base != 0xFFFFFFFFu && dest != 0u && dest <= 100u) {
                    static u32 scan;
                    u32 b = scan++ & (TRACKS - 1u);
                    u32 fb = frame_word_for(b, dest);
                    u16 mv = *(volatile u16 *)(base + MIRROR_STRIDE * b + 2u * dest);
                    u16 rv = fb ? *(volatile u16 *)fb : 0u;

                    tlm_cc(TLM_CC_SCAN_IDX, (u8)b);
                    tlm_cc14(TLM_CC_SMIR_LO, TLM_CC_SMIR_HI, (u16)(mv >> 2));
                    tlm_cc14(TLM_CC_SFRM_LO, TLM_CC_SFRM_HI, (u16)(rv >> 2));
                }
            }
#endif
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
#ifdef WAVERIDER_M0
        /* Waverider Milestone 0 rides this burst, right after the constant
         * that says the burst can be trusted: one baked-table probe and one
         * checksum slice (`csrc/waverider/table.c`). It reads its own data
         * and nothing of LFO4's. */
        wr_m0_report();
#endif
#ifdef LFO4_PERSIST
        /* **Where LFO4 is lost across a reboot, in two numbers.**
         *
         * The save side is not in doubt: the boot's own serialisation of the
         * working kit calls SAVE with the live container's sixteen addresses --
         * this table's keys (`emu_lfo4_persist.py --boot-only`, 2026-09-25). So
         * the loss is one of two things, and these counters separate them:
         *
         *   `sv_carry` rises after an LFO4 edit -> the working state was saved
         *     with LFO4 in it. It stays flat -> nothing saved after the edit:
         *     the stock setter's tail broadcasts `SoundParamChangedInfo` and
         *     ours skips it, so the project may never be marked dirty.
         *   `ld_carry` > 0 after a reboot -> it was stored and brought back, and
         *     something removed it afterwards (`ext_drop` counts that). 0 -> it
         *     was never in storage.
         *
         * Built with release semantics: `LFO4_KEEP_*` off, so `lfo4_on_load`
         * drops entries exactly as the shipped build does. */
        {
            extern u32 lfo4_saves, lfo4_saves_carrying, lfo4_loads_carrying;

            tlm_cc(TLM_CC_SV_CARRY, (u8)(lfo4_saves_carrying & 0x7Fu));
            tlm_cc(TLM_CC_LD_CARRY, (u8)(lfo4_loads_carrying & 0x7Fu));
            tlm_cc(TLM_CC_EXT_LIVE, (u8)(ext_live > 127u ? 127u : ext_live));
            tlm_cc(TLM_CC_EXT_DROP, (u8)(ext_drops & 0x7Fu));
            tlm_cc(TLM_CC_SAVES, (u8)(lfo4_saves & 0x7Fu));
        }
#endif
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
#ifndef LFO4_TRACK_KEYED
    /* **The index is a voice. Ask the firmware whose voice it is.**
     *
     * The default since 2026-09-25, verified on the instrument with a
     * negative control (`docs/lfo4-build-plan.md`, "FIXED"). The engine
     * keeps one block per voice, filled from the sound on that voice; reading
     * this index as a track is what made LFO4 audible only where the two
     * numbers agreed.
     *
     * `LFO4_TRACK_KEYED` restores the old key, for bisecting only. It is the
     * bug, reproducible on demand, and no shipped build defines it. */
    sound = lfo4_voice_sound(track);
    if (!sound)
        sound = lfo4_sound_of(track);
#else
    sound = lfo4_sound_of(track);   /* treats the index as a track -- it is a voice */
#endif
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
    /* **One track, or the test proves nothing.**
     *
     * Forcing *every* track's row makes all sixteen identical, so a bug that
     * picks the wrong row becomes invisible: the wrong row and the right row
     * hold the same values. `lfo4-loud` did exactly that and was read as
     * "the modulation is on every voice", which it cannot show.
     *
     * With `LFO4_FORCE_TRACK` set, only that track gets the forced row and the
     * other fifteen get depth zero. Then:
     *   - a sweep on **every voice** means the row is selected by track, and
     *     the engine is correct;
     *   - a sweep only when the voice index equals `LFO4_FORCE_TRACK` means the
     *     row is selected by **voice**, which is the owner's original report and
     *     a real defect.
     * The two outcomes finally look different, which is the whole point. */
#ifdef LFO4_FORCE_TRACK
    if (track != (u32)LFO4_FORCE_TRACK) {
        ((u16 *)row)[7] = 0x4000;          /* DEP neutral: no modulation */
        ((u16 *)row)[3] = 0;               /* DEST none */
        return row;
    }
#endif
    {
        static const u16 forced[EXT_PARAMS] = {
            /* **SPD and MULT are build-time, because the right rate is a
             * question the instrument answers, not the source.**
             * 0x7000 is the stock default, not "fast" as this comment used to
             * claim. At MULT index 8 the owner reported every track and every
             * voice gurgling rather than sweeping -- modulation everywhere, too
             * fast to hear as movement. `--force-spd` and `--force-mult` let the
             * rate be dialled without touching this file. */
#ifndef LFO4_FORCE_SPD
#define LFO4_FORCE_SPD  0x7000
#endif
#ifndef LFO4_FORCE_MULT
#define LFO4_FORCE_MULT 0x0800
#endif
            LFO4_FORCE_SPD,
            LFO4_FORCE_MULT,
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
