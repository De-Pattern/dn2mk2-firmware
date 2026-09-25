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

/* **An LFO4 edit announces itself the way a stock sound change does.**
 *
 * Measured on the instrument 2026-09-25 (two read-only `#MRAM_DUMP`s): an
 * unsaved stock edit is in the working-state image after a power-cycle, at its
 * stored record, and an unsaved LFO4 edit is not. The stock writer is
 * `Sound::updateMirror`; it is told about a change by an event through the
 * sound's holder. A stock knob sends `SoundParamChangedInfo` with its slot --
 * no good for LFO4, whose slots 101..108 the writer and the engine would both
 * index out of range. So LFO4 sends what a stock *whole-sound* change sends,
 * `SoundConfigChangedInfo`, byte for byte as the sender at `0x4004b25a` does.
 * The writer then re-serialises this sound into its stored record through
 * `SAVE`, and `lfo4_on_save` puts LFO4's lane in with everything else. The
 * firmware does the writing and the addressing; LFO4 only supplies its values
 * (owner, 2026-09-25: *"provide our values to it so it persists them together
 * with the factory values"*).
 *
 * **Once per pending job, not once per knob step.** The re-serialise is a
 * queued job and the queue does not collapse repeats; it reads the table when it
 * runs, so one queued job carries every edit made before it runs. `lfo4_on_save`
 * clears the mark when that job saves this sound. A mark older than roughly
 * four seconds of ticks is treated as lost, so an announcement is never
 * suppressed for good. */
struct lfo4_info { u32 vtable; u8 flag; u8 pad[3]; };
typedef void (*notify_fn)(u32 holder, struct lfo4_info *info);

u32 lfo4_announced, lfo4_announce_held;
u32 lfo4_pending_sound;
static u32 pending_at;
extern u32 lfo4_refreshes;

static void announce(u32 sound, u32 holder)
{
    struct lfo4_info info;
    u32 vt;

    if (!holder)
        return;
    if (lfo4_pending_sound == sound && lfo4_refreshes - pending_at < 100000u) {
        lfo4_announce_held++;
        return;
    }
    vt = *(volatile u32 *)holder;
    if (!vt)
        return;
    info.vtable = DN2_SOUND_CONFIG_CHANGED;
    info.flag = 1;
    info.pad[0] = info.pad[1] = info.pad[2] = 0;
    lfo4_pending_sound = sound;
    pending_at = lfo4_refreshes;
    lfo4_announced++;
    ((notify_fn)(*(volatile u32 *)(vt + DN2_HOLDER_NOTIFY)))(holder, &info);
}

void lfo4_on_set(u32 sound, u32 slot, u32 value, u32 holder)
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
    announce(sound, holder);
}
