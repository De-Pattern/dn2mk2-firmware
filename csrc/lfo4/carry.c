/* What a `memcpy` or a `memset` of the firmware's means for the table.
 *
 * `docs/lfo4-build-plan.md` §8 enumerated how a live sound moves. Two of the
 * three ways are these two routines: 32 whole-sound copies and clears with the
 * literal 1,163, and ~9 whole-kit and pattern copies. The third, save / load,
 * is step 2 and is hooked elsewhere.
 *
 * One subject: the size policy. It is deliberately **not** a list of the sizes
 * that were enumerated. A copy is carried by the range it covers, so a
 * container this reading missed carries its sounds anyway; the enumeration then
 * only has to be right about which *routines* move a sound, not about every
 * caller's size. What it costs is a range test on copies of 1,163 bytes or
 * more -- two compares while nothing is tracked near them (`ext.c`, `touches`).
 *
 * The hooks that reach here are `csrc/lfo4/hooks.S`, at both routines' entries,
 * with the caller's own arguments.
 */
#include "ext.h"

#define SOUND_BYTES 1163u             /* one live sound; the plan's stride */

u32 lfo4_copies, lfo4_sound_copies, lfo4_range_copies, lfo4_clears, lfo4_reentered;

/* Which block sizes the firmware actually moves, as {size, calls} pairs. The
 * design does not need this -- the carry is by range, not by size -- but the
 * next steps do: it is the only place a real boot says which containers hold a
 * sound, and it costs nothing on the fast path. */
#define SIZES 12
u32 lfo4_sizes[SIZES][2], lfo4_sizes_dropped;

static void log_size(u32 n)
{
    u32 i;

    for (i = 0; i < SIZES; i++) {
        if (lfo4_sizes[i][0] == n) {
            lfo4_sizes[i][1]++;
            return;
        }
        if (!lfo4_sizes[i][0]) {
            lfo4_sizes[i][0] = n;
            lfo4_sizes[i][1] = 1;
            return;
        }
    }
    lfo4_sizes_dropped++;
}

/* Both routines are called from interrupt context too, and the table work is
 * neither atomic nor reentrant -- it walks buffers of its own and shifts probe
 * clusters about. Whether an interrupt ever copies 1,163 bytes or more while
 * another such copy is in flight is not known, so this counts it rather than
 * assuming either way: `lfo4_reentered` is read by `scripts/emu_lfo4_boot.py`
 * and belongs in step 5's driven session. While it stays zero, skipping is
 * free; if it ever moves, the answer is to mask interrupts here, and we will
 * then know it is worth the microseconds. */
static u32 busy;

void lfo4_on_memcpy(void *dst, const void *src, u32 n)
{
    if (n < SOUND_BYTES)              /* the fast path: 2,347 calls in 60 M instructions */
        return;
    if (busy) {
        lfo4_reentered++;
        return;
    }
    busy = 1;
    lfo4_copies++;
    log_size(n);
    if (n == SOUND_BYTES) {
        lfo4_sound_copies++;
        ext_copy((u32)dst, (u32)src);
    } else {
        lfo4_range_copies++;
        ext_carry((u32)dst, (u32)src, n);
    }
    busy = 0;
}

/* Whatever byte it fills, a sound the size of the fill is no longer that sound:
 * its entry goes, and the slot reads `ext_default` again -- which is what a
 * cleared sound should read, and why this drops rather than zeroes. */
void lfo4_on_memset(void *dst, int fill, u32 n)
{
    (void)fill;
    if (n < SOUND_BYTES)
        return;
    if (busy) {
        lfo4_reentered++;
        return;
    }
    busy = 1;
    lfo4_clears++;
    log_size(n);
    ext_clear((u32)dst, n);
    busy = 0;
}
