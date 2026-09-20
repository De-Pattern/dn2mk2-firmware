/* Which parameter ids LFO4 answers to, and why those.
 *
 * The firmware's own setter (`docs/lfo4-build-plan.md` §"Step 4") guards its
 * write with `slot > 100 -> no write at all`, and the accessor at 0x400dc02c
 * carries the same bound. So ids **above** 100 are ones stock firmware already
 * handles by doing nothing: no stray write, no corrupted neighbour, and a
 * branch that is a well-defined place to divert from.
 *
 * LFO4 takes the eight just past it, in the sound `ParameterSet` order every
 * other LFO uses: SPD MULT FADE DEST WAVE SPH MODE DEP.
 *
 * One subject: the numbering. The table it maps onto is `ext.h`'s, which knows
 * nothing of parameter ids; the divert that uses both is `setter.c`. This
 * header is included by `hooks.S` too, so the numbers stay plain and the C
 * declarations stay behind the assembler guard.
 */
#ifndef LFO4_SLOTS_H
#define LFO4_SLOTS_H

#define LFO4_SLOT0  101                 /* SPD */
#define LFO4_LAST   108                 /* DEP -- inclusive; hooks.S compares `bgt` */
#define LFO4_SLOTN  (LFO4_LAST + 1)     /* one past the last */

#ifndef __ASSEMBLER__
#include "ext.h"

/* The numbering and the table have to agree about how many values there are,
 * and this is the cheapest place to find out that they stopped. */
typedef char lfo4_slots_span_matches_table[
    (LFO4_SLOTN - LFO4_SLOT0 == EXT_PARAMS) ? 1 : -1];
#endif

#endif
