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
    if (!any) {
        /* Nothing stored -- a stock sound, or one saved before this build.
         * Drop the entry rather than fill it with zeros: no entry reads
         * `ext_default`, which is what a sound without an LFO4 should read,
         * and it keeps the table for the sounds that do have one. */
        ext_drop((u32)live);
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

    lfo4_saves++;
    for (k = 0; k < EXT_PARAMS; k++) {
        u32 at = offset_of(k);
        u16 value = ext_get((u32)live, k);

        s[at] = (u8)(value >> 8);
        s[at + 1] = (u8)value;
        any |= value;
    }
    if (any)
        lfo4_saves_carrying++;
}
