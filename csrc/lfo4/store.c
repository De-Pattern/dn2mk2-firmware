/* LFO4's eight values across a save and a load, through the reserved ids.
 *
 * `docs/lfo4-build-plan.md` §4 read both converters; step 2 is this. A stored
 * sound's value block starts at **+28** and is indexed by **p-lock id**, 107
 * wide. The fourth-LFO rank -- the ids `4 * param + 0` -- is reserved: DNX
 * found it `00 00` across the corpus, and the stock maps fold it onto slot 0,
 * the LFOs' no-destination sink. So LFO4 needs no new field and no version
 * bump; it needs those eight ids filled on the way out and read on the way in.
 *
 * **Which eight was measured, not assumed** (2026-09-20). Driving the save with
 * a marker in all 101 live slots showed the ids the save loop never writes:
 * **4, 8, 12, 16, 20, 24, 28 and 32** -- and that **id 0 is written twice**,
 * from live slot 0 and again from live slot 65, whichever comes last. Id 0 is
 * the sentinel both maps fold onto, so it is not ours to take: a stock save of
 * one of our sounds would drop slot 65's value on top of it. The rank simply
 * starts one param later and ends at 32.
 *
 * **Neither map is edited.** §4's design renumbered LFO4 into live slots
 * 101-108 and widened the loops to reach them. It is not needed and it is not
 * free: the two maps are adjacent in the image (`0x401fcf20` is 100 longwords,
 * `0x401fd0b0` starts immediately after), so neither can grow in place. Instead
 * each loop is left exactly as it is and the eight ids are handled once, after
 * it, from the sound's own address -- the key step 1 already carries.
 *
 * One subject: which stored bytes are LFO4's, and in which direction. Where the
 * hooks sit is `csrc/lfo4/hooks.S`; what the table does is `ext.c`.
 */
#include "ext.h"

#define STORED_VALUES 28              /* the stored block's first value byte */

/* id = 4 * param + lfo, lfo 0 being the rank Elektron left unused. Id 0 (param
 * 0) is excluded: the save loop writes it from two different live slots. */
static const u8 LFO4_ID[EXT_PARAMS] = {4, 8, 12, 16, 20, 24, 28, 32};

u32 lfo4_loads, lfo4_loads_carrying, lfo4_saves, lfo4_saves_carrying;

/* Byte at a time: a stored track's stride is 359, so every other one starts at
 * an odd address and a u16 access would be misaligned. */
static u32 offset_of(u32 k)
{
    return STORED_VALUES + 2u * LFO4_ID[k];
}

/* -> 1 when these eight values are LFO4's default row.
 *
 * **The default row is "no LFO4", and it has to be treated as one on both
 * sides.** A sound with no table entry reads `ext_default` -- SPD 0x7000, MULT
 * 0x0300, FADE and DEP 0x4000, the rest 0 -- which is correct for the page and
 * the tick. It was wrong for storage: `lfo4_on_save` wrote whatever `ext_get`
 * returned, so **every sound without an LFO4 was saved carrying the default
 * row** (owner's project "TEST_PERSIST_LF4", slot 11, 2026-09-25: all 2,016
 * stored sounds, every kit, identical `7000 0300 4000 0000 0000 0000 0000 4000`).
 *
 * The next load then saw a non-zero lane in every sound and inserted an entry
 * for each -- up to 2,192 into a 256-slot table -- so the table filled, and a
 * real LFO4 edit on a sound that missed out had nowhere to go. That is how an
 * explicit save came to lose track 7's LFO4: the save ran, and wrote the
 * defaults, because track 7's own entry was never in the table.
 *
 * Both sides now agree that the default row means nothing is set: the save
 * writes the lane as zeros, which a stock-saved sound already has, and the load
 * drops a lane that equals the default row -- which also cleans every project
 * already saved by an LFO4 build, on its first load. Dropping loses nothing: a
 * sound with no entry reads exactly these defaults.
 *
 * **What the sentinel costs, so it is not a puzzle later.** A user who
 * deliberately sets all eight LFO4 values to exactly this row has it treated as
 * "no LFO4" on the next load. Nothing audible is lost -- the row has no
 * destination (`DEST` 0) and a centred, zero depth (`DEP` 0x4000), so it does
 * nothing -- but the page will show it as untouched rather than as set.
 *
 * **When it can go:** the load-side half exists only to clean projects saved by
 * LFO4 builds before 2026-09-25. Once none of those can be in circulation, the
 * load check can return to `!any` alone. The save-side half (write zeros, not
 * the defaults) is permanent. DNX records the same pattern as "saved by an LFO4
 * test build", not as a real LFO4, in its own format notes. */
static int is_default(const u16 *v)
{
    u32 k;

    for (k = 0; k < EXT_PARAMS; k++)
        if (v[k] != ext_default[k])
            return 0;
    return 1;
}

void lfo4_on_load(void *live, const void *stored)
{
    const u8 *s = (const u8 *)stored;
    u16 value[EXT_PARAMS];
    u32 k, any = 0;

    lfo4_loads++;
    for (k = 0; k < EXT_PARAMS; k++) {
        u32 at = offset_of(k);

        value[k] = (u16)((s[at] << 8) | s[at + 1]);
        any |= value[k];
    }
    if (!any || is_default(value)) {
        /* Nothing stored -- a stock sound, one saved before this build, or one
         * saved by an LFO4 build that wrote the default row (`is_default`).
         * Drop the entry rather than fill it with zeros: no entry reads
         * `ext_default`, which is what a sound without an LFO4 should read,
         * and it keeps the table for the sounds that do have one.
         *
         * **This is the fourth place a row is removed, and the one
         * `LFO4_KEEP_ROWS` does not cover.** It is also the busiest: a single
         * boot runs `lfo4_on_load` 2,192 times. If sounds reload while a
         * pattern plays, an LFO4 edit that has not been saved is wiped by the
         * next load of that sound -- and trigging faster means more chances to
         * land between one load and the next, which is the shape the
         * instrument reports.
         *
         * `LFO4_KEEP_ALL` is the bisect that covers it. It is separate from
         * `LFO4_KEEP_ROWS` on purpose: `lfo4-keeprow` was built and gated with
         * only the copy and clear paths off, and its meaning must not change
         * under it. A build defining both removes every route by which a row
         * can disappear. */
#ifndef LFO4_KEEP_ALL
        ext_drop((u32)live);
#endif
        return;
    }
    lfo4_loads_carrying++;
    for (k = 0; k < EXT_PARAMS; k++)
        ext_set((u32)live, k, value[k]);
}

void lfo4_on_save(void *stored, const void *live)
{
    u8 *s = (u8 *)stored;
    u32 k, any = 0;

    const u16 *v = ext_find((u32)live);
    extern u32 lfo4_pending_sound;

    lfo4_saves++;
    /* The re-serialise an LFO4 edit asked for has run (setter.c, `announce`). */
    if ((u32)live == lfo4_pending_sound)
        lfo4_pending_sound = 0;
    /* No entry, or an entry at the defaults: store the lane as zeros, the
     * state a stock save leaves it in -- never `ext_get`'s default row. */
    if (v && is_default(v))
        v = 0;
    for (k = 0; k < EXT_PARAMS; k++) {
        u32 at = offset_of(k);
        u16 value = v ? v[k] : 0u;

        s[at] = (u8)(value >> 8);
        s[at + 1] = (u8)value;
        any |= value;
    }
    if (any)
        lfo4_saves_carrying++;
}
