/* LFO4's eight values per live sound, in a table the firmware knows nothing of.
 *
 * `docs/lfo4-build-plan.md` §8: a live sound has no eight free slots and cannot
 * grow, so LFO4's values live outside it, in a table keyed by **the live
 * sound's own address**. That makes correctness one question -- does every way
 * a live sound moves carry its entry? -- and the plan enumerates that set:
 * whole-sound copies and clears, whole-kit and pattern copies, and save / load.
 * The first two are `csrc/lfo4/carry.c`; save / load is step 2.
 *
 * One subject here: the table. It knows an address, a span, and eight u16
 * values; it does not know what a sound is, what `memcpy` is, or which value
 * is DEPTH. Policy -- which sizes mean what -- is the carry's.
 *
 * **A drop may move other entries** (deletion shifts a probe cluster back), so
 * a pointer from `ext_find` / `ext_add` must never be held across one.
 */
#ifndef LFO4_EXT_H
#define LFO4_EXT_H

#include "dn2_111.h"

#define EXT_PARAMS 8              /* SPD MULT FADE DEST WAVE SPH MODE DEP */
#define EXT_SHIFT  8
#define EXT_SLOTS  (1u << EXT_SHIFT)   /* entries; 16 tracks x several buffers, with room */
#define EXT_SPAN   1163u          /* bytes a tracked object occupies from its key */
#define EXT_BATCH  32             /* tracked objects one range operation may carry */

/* The table. Public so the harness and, later, the page can read it. */
extern u32 ext_key[EXT_SLOTS];               /* 0 = free; no tombstones */
extern u16 ext_val[EXT_SLOTS][EXT_PARAMS];
extern u16 ext_default[EXT_PARAMS];          /* a sound with no entry reads this */

/* What happened, for the harness and for a later load meter. */
extern u32 ext_live, ext_lo, ext_hi;
/* Bumped by every mutator, so a reader can tell "nothing has changed since"
 * with one compare instead of a lookup (`csrc/lfo4/bridge.c`). */
extern u32 ext_generation;
extern u32 ext_inserts, ext_drops, ext_full, ext_overflow;

void ext_init(void);
u16 *ext_find(u32 key);                      /* the values, or 0 */
u16 *ext_add(u32 key);                       /* find, or a new entry; 0 if full */
void ext_drop(u32 key);
void ext_copy(u32 dst, u32 src);             /* one object moved */
void ext_carry(u32 dst, u32 src, u32 n);     /* a block moved: every object inside it */
void ext_clear(u32 at, u32 n);               /* a block overwritten: every object inside it */

/* What a slot reads and writes, entry or no entry. */
u16 ext_get(u32 key, u32 param);
void ext_set(u32 key, u32 param, u16 value);

#endif
