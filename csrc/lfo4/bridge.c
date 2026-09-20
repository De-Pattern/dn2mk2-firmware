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
 * `sound(track) = LFO4_KIT + 52 + track * 1163`, read out of the v4 container
 * gate at `0x400ddc52` and checked against a snapshot: those addresses hold
 * FRAGILE BEINGS, DULCI SPACE, LAST BREAKFAST and WEAVING CIRCLE, in track
 * order (`docs/lfo4-build-plan.md`).
 */
#include "ext.h"

#ifndef LFO4_ROWS
#error "LFO4_ROWS must be defined: the address of the engine's parameter table"
#endif
#ifndef LFO4_KIT
#error "LFO4_KIT must be defined: the live container the sequencer is given"
#endif

#define TRACKS       16
#define ROW_BYTES    (2u * EXT_PARAMS)
#define SOUND_AT     52u                  /* the gate's `addil #52,%d3` */
#define SOUND_STRIDE 1163u                /* and its `addil #1163,%d3` */

u32 lfo4_refreshes, lfo4_copies_in;
static u32 seen_sound[TRACKS];
static u32 seen_generation[TRACKS];

u32 lfo4_sound_of(u32 track)
{
    return (u32)LFO4_KIT + SOUND_AT + track * SOUND_STRIDE;
}

/* -> the address of this track's row, current as of now. */
u32 lfo4_refresh(u32 track)
{
    u32 row = (u32)LFO4_ROWS + track * ROW_BYTES;
    u32 sound, generation;
    u16 *values;
    u32 k;

    if (track >= TRACKS)
        return (u32)LFO4_ROWS;            /* never index past the table */
    lfo4_refreshes++;
    sound = lfo4_sound_of(track);
    generation = ext_generation;
    if (sound == seen_sound[track] && generation == seen_generation[track])
        return row;

    seen_sound[track] = sound;
    seen_generation[track] = generation;
    lfo4_copies_in++;
    values = ext_find(sound);
    for (k = 0; k < EXT_PARAMS; k++)
        ((u16 *)row)[k] = values ? values[k] : ext_default[k];
    return row;
}
