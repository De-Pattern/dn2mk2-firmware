/* Three of LFO4's own dials, turned into instruments pointed at LFO4.
 *
 * **Why the page and not a counter dump.** Every remaining reading of the
 * intermittency -- wrong key, stale container, a lookup that misses under load
 * -- is a question about *numbers at the moment a note sounds*, and the
 * instrument is the only place those numbers exist. The emulator runs neither
 * the sequencer nor a pattern load, so it cannot be asked; and a counter in
 * BSS cannot be read from the front panel. But LFO4's page is ours end to end:
 * `csrc/lfo4/getter.c` already decides what every one of its eight columns
 * displays. So three of them display the measurement instead of the value.
 *
 * **What tick7 already settled, and why that narrows this to the lookup.**
 * `lfo4-tick7` drove the same two evaluator indices -- `%a5` in A, `%d0` in B
 * -- with a **static** sixteen-row table in the image, and on hardware on
 * 2026-09-20 it modulated *reliably*, each track reading its own row. Every
 * build since replaced that static table with `lfo4_refresh(track)`, and every
 * one of those is erratic. The engine path is therefore not the suspect: what
 * changed is that the row is now *looked up*, by a key the panel wrote under
 * and the tick asks under. These three dials watch exactly that join.
 *
 * **The readings are needles, not numbers.** LFO4's records carry LFO3's
 * ranges and nothing here knows how a widget formats 8.8 fixed point into the
 * number on the glass, so no reading is allowed to depend on that: each answer
 * is the parameter's own **full positive travel, full negative travel, or
 * centre**. A dial at its stop reads the same whatever the scale, which is
 * `docs/FEATURE-PLAYBOOK.md` §3 -- a demonstration has to be unmissable --
 * applied to a measurement.
 *
 *   SPD   the last lookup the **tick** made:  right = found a row,
 *         left = found nothing and took the defaults, centre = never looked.
 *   FADE  whether the **panel's** key is one the tick can ask for:
 *         right = the sound the knob wrote under is one of the sixteen the
 *         engine reads, left = it is not, and that alone is the whole fault.
 *   DEP   not a needle: the depth **the engine is holding right now**, read
 *         out of `lfo4_rows`. Turn DEP to its stop and watch this follow --
 *         or fall back to 0 on its own, which is the bug happening.
 *
 * The other five columns are untouched, so the page still works and a
 * destination can still be chosen while the three are read.
 *
 * **One knock-on, and it is cosmetic.** The waveform preview block added in
 * step 4e asks the page for `SPD` (entry 321) to animate at, and that read
 * comes through the same accessor, so the preview moves at the needle's rate
 * rather than the LFO's. Nothing downstream of the engine sees it: the tick
 * reads `lfo4_rows`, which carries the dialled value.
 *
 * One subject: turning run-time state into a displayable value. It does not
 * know what a slot id is (that is `getter.c`'s) and it never writes.
 */
#include "slots.h"

#define TRACKS     16
#define METER_MAX  0x7f00          /* inside every one of LFO4's ranges */

extern u16 lfo4_rows[TRACKS][EXT_PARAMS];
extern u32 lfo4_set_sound;         /* setter.c: the key the panel last wrote */
extern int lfo4_last_lookup;       /* bridge.c: +1 hit, -1 miss, 0 none yet */

u32 lfo4_sound_of(u32 track);

/* -> the track whose live sound the panel last wrote to, or -1.
 *
 * Asked of the firmware's own arithmetic, sixteen times, rather than by
 * dividing: `lfo4_sound_of` reads the container base out of `0x800052a0`
 * every call, so a base that has moved since the knob was turned shows up
 * here as "no track", which is precisely the failure being looked for.
 */
static int panel_track(void)
{
    u32 t;

    if (!lfo4_set_sound)
        return -1;
    for (t = 0; t < TRACKS; t++)
        if (lfo4_sound_of(t) == lfo4_set_sound)
            return (int)t;
    return -1;
}

/* -> what column `param` should display, with `*answered` set when this file
 * has an opinion at all. Columns it does not answer for keep their value. */
int lfo4_meter(u32 param, int *answered)
{
    int track;

    *answered = 1;
    switch (param) {
    case 0:                                   /* SPD */
        if (lfo4_last_lookup > 0)
            return METER_MAX;
        return lfo4_last_lookup < 0 ? -METER_MAX : 0;
    case 2:                                   /* FADE */
        return panel_track() >= 0 ? METER_MAX : -METER_MAX;
    case 7:                                   /* DEP */
        track = panel_track();
        return (int)(short)lfo4_rows[track < 0 ? 0 : track][7];
    default:
        *answered = 0;
        return 0;
    }
}
