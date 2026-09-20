/* What runs once, from the startup loader, before anything else of ours can.
 *
 * The loader calls this after copying the code and zeroing its BSS, and
 * *before* the firmware's own BSS clear (`csrc/runtime/loader.S`), so it may
 * touch only our memory -- no firmware state exists yet.
 *
 * It is its own file because every later step adds to it (the defaults a slot
 * reads, the state arrays, the page), and because the loader needs exactly one
 * address to call.
 */
#include "ext.h"

void lfo4_init(void)
{
    ext_init();
}
