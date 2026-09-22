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
 *   SPD   **the destination in the row the engine is holding**, which reads
 *         straight off the glass as the slot number (`DEST` is stored as
 *         `slot << 8` and this column divides by 256). `0.00` means the
 *         engine is aiming at nothing, which is silence however right
 *         everything else is.
 *
 *         It used to be a needle for the tick's last lookup, and that was
 *         **too weak to keep**: the tick refreshes sixteen tracks, so a hit on
 *         any one of them pinned it right while the track being played missed.
 *         From the instrument, 2026-09-22: it read hard right, `FADE` read
 *         hard right, `DEP` held the full dialled depth -- and nothing
 *         modulated. Two of those three are about the track in hand; the
 *         needle was not, so it could not narrow anything. `DEST` is.
 *   FADE  **nothing -- it is the parameter again**, and taking it back is a
 *         correction, not a simplification.
 *
 *         It was a needle for "is the panel's key one the tick asks for", it
 *         answered *yes* on the instrument on 2026-09-22, and it should have
 *         been given back the moment it had. It was not, and a diverted
 *         display on a parameter the owner can still **turn** is a trap: the
 *         knob writes a real value into the table that nobody can see. The
 *         owner then read the needle's full-scale 63 as LFO4's fade and set
 *         LFO3's fade to match -- and reported that LFO3 at fade 63 is
 *         *"almost just a blip"*, while at 0 it sweeps normally. That is a
 *         true and useful fact about fade, discovered against a number this
 *         file invented.
 *
 *         **Rule taken from it:** divert a column only while its answer is
 *         still unknown, and never one whose value has to be right for the
 *         test to mean anything.
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
extern u16 lfo4_rows[TRACKS][EXT_PARAMS];
extern u32 lfo4_set_sound;         /* setter.c: the key the panel last wrote */

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
        track = panel_track();
        return (int)(short)lfo4_rows[track < 0 ? 0 : track][3];
    case 7:                                   /* DEP */
        track = panel_track();
        return (int)(short)lfo4_rows[track < 0 ? 0 : track][7];
    default:
        *answered = 0;
        return 0;
    }
}
