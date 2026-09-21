/* The parameter table's runtime companion, rehoused so it can hold 331 entries.
 *
 * `0x400c241c` indexes a second table over the same entry space as the 60-byte
 * parameter records: **321 entries of 68 bytes at `0x4243325c`**, in RAM,
 * immediately after the page-record table at `0x42432c00`. It shares the `321`
 * because the bound is the entry space rather than either table, so widening
 * that space past 320 would walk this one off its end -- into whatever the
 * allocator put next -- on the first LFO4 parameter touched.
 *
 * So it moves here, into BSS this build owns, with room for the ten new
 * entries. Six literals in the firmware point at it, across five field
 * offsets, and `dnfw.patch.paramtable` rewrites all six.
 *
 * **Why BSS and not a copy.** Stock's table is zero at boot -- it sits in the
 * region the firmware's own BSS clear covers -- and only entry 0 is written
 * before anything reads it, by the absolute stores at `0x400c4024`, which the
 * same six-site patch redirects here. So an empty table *is* the stock state,
 * and copying anything would be copying zeros. The loader zeroes our BSS
 * before the firmware's clear runs (`csrc/runtime/loader.S`), which is early
 * enough: nothing has looked at a parameter yet.
 *
 * It is 22,508 bytes and it is never indexed from C -- only the firmware
 * reaches it, through the bases we rewrite. The array exists to own the
 * address and to have the loader zero it.
 */
#include "ext.h"

#define PRM_ENTRIES 331           /* 320 stock records + LFO4's ten, plus entry 0 */
#define PRM_STRIDE  68

u8 lfo4_prm68[PRM_ENTRIES * PRM_STRIDE];
