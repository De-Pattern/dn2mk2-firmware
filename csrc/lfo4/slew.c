/* The four `SLEW` entries, because the firmware's three cannot grow.
 *
 * `0x40205454` holds `{80, 90, 100}` -- the `SLEW` entry of each LFO, indexed
 * by the MOD page's own index. The next byte after the third is the first of
 * a mangled RTTI string (`*ZNK11LfoPage...`), so a fourth longword there would
 * land on somebody else's data. This is that table with LFO4's entry added,
 * and the `lea` at `DN2_SLEW_TABLE` is repointed at it.
 *
 * **The build asserts the first three against the firmware's own**, so a table
 * that drifted from the one it replaces cannot ship: the point of copying is
 * that LFO1, LFO2 and LFO3 keep reading exactly what they read before.
 *
 * One subject: four numbers and where LFO4's comes from.
 */
#include "slots.h"

const u32 lfo4_slew_entries[DN2_SLEW_COUNT] = {80, 90, 100, LFO4_E_SLEW};
