/* What runs once, from the startup loader, before anything else of ours can.
 *
 * The loader calls this after copying the code and zeroing its BSS, and
 * *before* the firmware's own BSS clear (`csrc/runtime/loader.S`), so it may
 * touch only our memory -- no firmware state exists yet. Reading the image is
 * fine: it is loaded, and the parameter table is part of it.
 *
 * It is its own file because every later step adds to it, and because the
 * loader needs exactly one address to call.
 */
#include "ext.h"

/* Which of LFO3's ten records each of LFO4's eight values comes from. The
 * group of ten is eight value slots plus two alternates, and the alternates --
 * `SLEW` at position 5 and the second `MULT` at 9 -- share a slot with a
 * primary, so the eight are positions 0-4 and 6-8. Same list as `page.c`'s,
 * for the same reason. */
static const u8 POSITION[EXT_PARAMS] = {0, 1, 2, 3, 4, 6, 7, 8};

/* **A value nobody has set is the record's default, not zero.**
 *
 * `ext_add` seeds a new entry from `ext_default` and `ext_get` falls back to
 * it, so one array decides what an untouched LFO4 reads -- and it was left as
 * the zeros BSS gives it. On the instrument that showed as `FADE` reading
 * **-64** and `DEP` **-128**: both are bipolar with a record default of
 * `0x4000`, which displays as 0, so a stored 0 displays at the bottom of the
 * range. `SPD` and `MULT` were wrong the same way and less visibly, at 0
 * instead of 112 and at the lowest multiplier instead of the third.
 *
 * The defaults are read from **LFO3's own records**, not written down here:
 * LFO4's ten records are copies of LFO3's, so this cannot disagree with them,
 * and a number typed into this file could.
 */
static void defaults(void)
{
    u32 k;

    for (k = 0; k < EXT_PARAMS; k++) {
        const u32 *record = (const u32 *)(DN2_PARAM_TABLE
                                          + DN2_PARAM_STRIDE * (LFO3_RECORD0 + POSITION[k]));
        ext_default[k] = (u16)record[DN2_PARAM_DEFAULT / 4];
    }
}

void lfo4_init(void)
{
    defaults();
    ext_init();
}
