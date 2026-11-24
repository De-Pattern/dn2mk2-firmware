/* Explicit engine selection. UI task only; never used by metadata refresh/recall.
 * Native setters update both kit values and active voice mirrors. Capture keeps
 * the old complete snapshot while those sixteen setters run, then sees the new
 * identity and values together on the next frame. IRQs remain enabled. */
#include "wr_gen.h"
#include "ui.h"
#include "sound.h"
#define SET_VALUE ((sc_u32 (*)(sc_u32, sc_u32, sc_u32, sc_u32, sc_u32, sc_u32, sc_u32))0x40037326u)
#define OWNER ((sc_u32 (*)(void))0x4018a97au)
#define PARAM_SET ((sc_u32 (*)(sc_u32, sc_u32, sc_u32))0x40041a40u)
#define RECORD(id) ((volatile sc_u32 *)(0x401f7f94u + 60u * (id)))
#define ENTRY(id) ((volatile sc_u32 *)(0x4243325cu + 68u * (id) + 4u))
#define D __attribute__((section(".data"), aligned(4)))
static sc_u32 selecting D, failed_kit D, failed_loads D, failed_news D;
extern volatile sc_u32 smp_pj_loads, smp_pj_news;

/* Cover native machine initialization as well as the subsequent sixteen setters:
 * a frame interrupt must not export an intermediate legacy Perkons identity. */
int sc_select_hold(sc_u32 track)
{
    if(track>=8 || selecting || (sc_edit_mask && sc_edit_mask!=(1u<<track))) return 0;
    failed_kit=*(volatile sc_u32 *)0x800052a0u;
    failed_loads=smp_pj_loads; failed_news=smp_pj_news;
    sc_edit_mask=1u<<track;
    __asm__ volatile ("" ::: "memory");
    return 1;
}

/* A failed rollback holds only the damaged track. A fresh loaded/new project
 * or kit must not inherit that hold. UI task only, never during a transaction. */
void sc_select_poll(void)
{
    if (!selecting && sc_edit_mask &&
        (failed_kit != *(volatile sc_u32 *)0x800052a0u ||
         failed_loads != smp_pj_loads || failed_news != smp_pj_news)) sc_edit_mask = 0;
}

static sc_u16 value(const volatile sc_u8 *sound, sc_u32 i)
{
    sc_u32 slot = RECORD(sc_all_ids[i])[1];
    sound += 20 + 2 * slot;
    return (sc_u16)((sound[0] << 8) | sound[1]);
}

/* The prepared entry point also lets the emulator execute the real transaction
 * and native setters without pretending to construct a whole UI object tree.
 * Return 1 committed, 0 rejected/restored, -1 rollback failed (capture stays held).
 * The caller must not substitute a different descriptor after confirmation. */
int sc_select_apply(sc_u32 track, volatile sc_u8 *sound, const sc_u32 *sets,
                    const ScUiView *v)
{
    if (track >= 8 || !sound || sound[0xde] != SC_TYPE || !sets || !v ||
        (v->state != 0 && v->state != 1) || !sc_id_ok(v->id) || selecting ||
        (sc_edit_mask && sc_edit_mask != (1u << track))) return 0;
    for (sc_u32 i = 0; i < 16; i++)
        if (!sets[i] || v->knob[i].min > v->knob[i].def ||
            v->knob[i].def > v->knob[i].max || v->knob[i].max > 127) return 0;
    int held = sc_edit_mask != 0;
    sc_u16 old[16];
    sc_u32 ranges[16][4], types[16][4];
    for (sc_u32 i = 0; i < 16; i++) {
        old[i] = value(sound, i);
        for (sc_u32 k = 0; k < 4; k++) {
            ranges[i][k] = RECORD(sc_all_ids[i])[2 + k];
            types[i][k] = ENTRY(sc_all_ids[i])[k];
        }
    }
    selecting = 1;
    sc_edit_mask = 1u << track;
    __asm__ volatile ("" ::: "memory");
    for (sc_u32 i = 0; i < 16; i++) {
        volatile sc_u32 *r = RECORD(sc_all_ids[i]);
        /* The previous engine's UI ranges must not clamp the new defaults. */
        r[2] = 0; r[3] = 0x7fff; r[4] = 0; r[5] = RECORD(261)[5];
        for (sc_u32 k = 0; k < 4; k++) ENTRY(sc_all_ids[i])[k] = types[0][k];
        SET_VALUE(sets[i], sc_all_ids[i], (sc_u32)v->knob[i].def << 8, track, 0, 0, 0);
    }
    int okay = 1;
    for (sc_u32 i = 0; i < 16; i++)
        if (value(sound, i) != (sc_u16)(v->knob[i].def << 8)) okay = 0;
    if (okay) okay = sc_sound_store(sound, v->id);
    int restored = 1;
    if (!okay) {
        for (sc_u32 i = 0; i < 16; i++)
            SET_VALUE(sets[i], sc_all_ids[i], old[i], track, 0, 0, 0);
        for (sc_u32 i = 0; i < 16; i++) if (value(sound, i) != old[i]) restored = 0;
    }
    for (sc_u32 i = 0; i < 16; i++) for (sc_u32 k = 0; k < 4; k++) {
        RECORD(sc_all_ids[i])[2 + k] = ranges[i][k];
        ENTRY(sc_all_ids[i])[k] = types[i][k];
    }
    __asm__ volatile ("" ::: "memory");
    if (okay || (restored && !held)) sc_edit_mask = 0;
    else {
        failed_kit = *(volatile sc_u32 *)0x800052a0u;
        failed_loads = smp_pj_loads; failed_news = smp_pj_news;
    }
    selecting = 0;
    return okay ? 1 : restored && !held ? 0 : -1;
}

int sc_select(sc_u32 track, const ScUiView *v)
{
    volatile sc_u8 *kit = *(volatile sc_u8 *volatile *)0x800052a0u;
    if (track >= 8 || track != *(volatile sc_u8 *)0x42431a6cu || !kit) return 0;
    extern int gr_allowed(sc_u32, sc_u32);
    if (!gr_allowed(track, SC_TYPE)) return 0;
    sc_u32 owner = OWNER(), sets[16];
    if (!owner) return 0;
    for (sc_u32 i = 0; i < 16; i++) sets[i] = PARAM_SET(owner, sc_all_ids[i], track);
    return sc_select_apply(track, kit + 52 + 1163 * track, sets, v);
}
