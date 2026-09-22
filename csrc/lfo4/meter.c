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
 *   SPD   **the mirror cell LFO4 is aiming at, read live.** Not the setting --
 *         the place the modulation lands. If LFO4's contribution reaches the
 *         engine, this number moves on its own, continuously, whether or not a
 *         note is playing.
 *
 *         It has been the tick's last-lookup needle and then the row's `DEST`,
 *         and both of those questions are now answered -- the keys agree and
 *         the row carries the right destination at the right depth. What is
 *         not answered is whether the **contribution arrives in the mirror**,
 *         and only the instrument can say, because in the emulator it does.
 *
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
 *   DEP   **the mirror cell LFO3 is aiming at**, the same way, and it is the
 *         control -- the thing three flashes on 2026-09-22 were missing. On
 *         the instrument LFO3 sweeps every time and LFO4 about one trig in
 *         fifteen, while in the emulator the two are **byte-identical**
 *         through the same evaluator over 240 frames
 *         (`scripts/emu_lfo4_vs_lfo3.py`). Which of these two numbers moves
 *         decides where the fault is, and neither reading means anything
 *         without the other.
 *
 *         **Set the two LFOs to different destinations**, or they stack into
 *         one cell and both columns show the same thing.
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

/* The per-track parameter mirror, and the arithmetic is the firmware's own:
 * `mirror[block][slot] = 0x800068e4 + 34 + 202*block + 2*slot`, derived from six
 * `pea` displacements in the frame builder and confirmed by construction when a
 * hand-computed cell in block 16 turned out to be the parameter the formula
 * named (`docs/fx-master-modulation.md` §9). */
#define MIRROR_BASE  0x800068E4u
#define MIRROR_AT    34u
#define MIRROR_STRIDE 202u

#define LFO3_DEST_SLOT 20                 /* 8*2 + 4; the record table agrees */

/* -> the destination slot LFO4 is aiming at, out of the row the engine holds. */
static u32 lfo4_dest_of(void)
{
    int track = panel_track();

    return (u32)(lfo4_rows[track < 0 ? 0 : track][3] >> 8) & 0x7Fu;
}

/* -> the destination slot LFO3 is aiming at, out of the mirror, where the
 * firmware keeps its own LFOs' parameters. */
static u32 lfo3_dest_of(void)
{
    int track = panel_track();
    u32 at = MIRROR_BASE + MIRROR_AT
             + MIRROR_STRIDE * (u32)(track < 0 ? 0 : track) + 2u * LFO3_DEST_SLOT;

    return (u32)(*(volatile u16 *)at >> 8) & 0x7Fu;
}

/* -> what that track's mirror currently holds at `slot` -- the cell an LFO
 * writes its contribution into, read live. */
static int cell(u32 slot)
{
    int track = panel_track();
    u32 at = MIRROR_BASE + MIRROR_AT
             + MIRROR_STRIDE * (u32)(track < 0 ? 0 : track) + 2u * slot;

    return (int)(short)*(volatile u16 *)at;
}

/* -> what column `param` should display, with `*answered` set when this file
 * has an opinion at all. Columns it does not answer for keep their value. */
int lfo4_meter(u32 param, int *answered)
{
    *answered = 1;
    switch (param) {
    case 0:                                   /* SPD */
        return cell(lfo4_dest_of());
    case 7:                                   /* DEP */
        return cell(lfo3_dest_of());
    default:
        *answered = 0;
        return 0;
    }
}
