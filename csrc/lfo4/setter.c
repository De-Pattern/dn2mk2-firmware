/* A turn that lands on one of LFO4's slots.
 *
 * The firmware writes a parameter value at 0x40037be8 as `values[d2] = d3`,
 * reached only when `d2 <= 100`. `csrc/lfo4/hooks.S`'s `lfo4_set_stub` takes
 * over that bound: slots the firmware owns go on to its own write untouched,
 * and 101..108 come here instead with the live sound the firmware's own
 * virtual call produced -- the same pointer, not one this code went looking
 * for.
 *
 * One subject: turning a parameter id into a table write. It does not know how
 * the sound was found, what a page is, or how a value is displayed.
 */
#include "slots.h"

/* What happened, for the harness: a count says a turn arrived, the slot says
 * which parameter, and `lfo4_set_sound` says which sound took it. A probe that
 * only counts cannot tell a write to the right slot from a write to slot 1. */
u32 lfo4_sets, lfo4_sets_ignored;
u32 lfo4_set_sound, lfo4_set_slot, lfo4_set_value;

void lfo4_on_set(u32 sound, u32 slot, u32 value)
{
    if (slot < LFO4_SLOT0 || slot >= LFO4_SLOTN || !sound) {
        lfo4_sets_ignored++;
        return;
    }
    lfo4_sets++;
    lfo4_set_sound = sound;
    lfo4_set_slot = slot;
    lfo4_set_value = value & 0xFFFF;
    ext_set(sound, slot - LFO4_SLOT0, (u16)value);
}
