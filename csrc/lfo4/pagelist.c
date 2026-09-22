/* The four MOD page ids, where the firmware's three are built from.
 *
 * `0x40061562` hands a **three**-entry list at `0x401e0048` and the count `3`
 * to the mode's page-vector constructor at startup. The list is `{4, 5, 6}`
 * and the longword after it is `16`, belonging to the next registration in a
 * packed pool with no gaps -- so a fourth id cannot be appended where it
 * stands, and the list is rehoused here instead.
 *
 * **This is where the fourth page should have been added all along.**
 * `page.c` swaps the vector later, the first time a mode header is drawn, and
 * that is one frame too late: a project that opens on the MOD page draws three
 * page dots until `[MOD]` is pressed once. Reported from the instrument,
 * 2026-09-22, and the boot gate had already said so -- `lfo4_pages` was listed
 * as never exercised in a 450 M-instruction boot to a drawn frame.
 *
 * It is also the safer of the two. The constructor **copies** this list into
 * the vector's own storage, so nothing afterwards points at memory the
 * firmware's allocator never handed out -- which is the one thing `page.c`
 * says it cannot prove about its swap.
 *
 * One subject: four numbers, and which page each names.
 */
#include "slots.h"

const u32 lfo4_mod_pages[4] = {4, 5, 6, LFO4_PAGE};
