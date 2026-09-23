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

/* -> the address of this track's row, current as of now. */
u32 lfo4_refresh(u32 track)
{
    u32 row = (u32)lfo4_rows + track * ROW_BYTES;
    u32 sound, generation;
    u16 *values;
    u32 k;

    if (track >= TRACKS)
        return (u32)lfo4_rows;            /* never index past the table */
    lfo4_refreshes++;
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
