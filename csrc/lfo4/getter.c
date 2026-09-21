/* A read that lands on one of LFO4's slots: step 4a in the other direction.
 *
 * `scripts/emu_value_reads.py` hooked all 119 instructions in the image that
 * address the sound's value array -- displacement 20, long index, scale 2 --
 * and opened the MOD pages. **Two fired.** One of them, `0x40030f34`, clamps
 * its index to 0..15 before it gets there, so no LFO slot can reach it. The
 * other is the page's, and it opens exactly as the setter does:
 *
 *     0x4003717c  moveq #100,%d0
 *                 cmpl %d2,%d0
 *                 blts <return 0>          ; six bytes, and above 100: nothing
 *
 * The same six-byte shape step 4a diverted on the write side, at a site found
 * by running rather than by reading -- 117 of those 119 candidates never
 * execute while a MOD page is drawn, and no amount of staring at the image
 * would have said which two do.
 *
 * So the page asks for slot 101 and gets it from here instead of from
 * `sound->values[101]`, which is `+0xDE`: the machine-type byte, not a value
 * of LFO4's at all. The value it returns is the one `lfo4_on_set` put in the
 * table when the knob was turned.
 *
 * One subject: turning a parameter id into a table read. Symmetrical with
 * `setter.c` down to the guard, and deliberately so -- the two are one
 * mechanism seen from both ends, and they should be read together.
 */
#include "slots.h"

/* What happened, for the harness. As with the setter, a count alone cannot
 * tell a read of the right slot from a read of slot 1. */
u32 lfo4_gets, lfo4_gets_ignored;
u32 lfo4_get_sound, lfo4_get_slot, lfo4_get_value;

/* -> the value, sign-extendable to what `mvs.w` would have produced.
 *
 * The firmware's own read is `mvs.w`, so the value reaches the caller **sign
 * extended**. The table holds u16 and every parameter range in the image is
 * signed in the same 16 bits, so this returns the same shape: widen through
 * `short`, not through `u16`, or a depth of -1 reads as 65535.
 */
u32 lfo4_on_get(u32 sound, u32 slot)
{
    short value;

    if (slot < LFO4_SLOT0 || slot >= LFO4_SLOTN || !sound) {
        lfo4_gets_ignored++;
        return 0;
    }
    lfo4_gets++;
    value = (short)ext_get(sound, slot - LFO4_SLOT0);
    lfo4_get_sound = sound;
    lfo4_get_slot = slot;
    lfo4_get_value = (u32)(int)value;
    return (u32)(int)value;
}
