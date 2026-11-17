/* v0.58: two microtonal scales in KB SETUP's SCALE (owner, 2026-11-16; docs/microtonal.md).
 *
 * The build (dnfw.waverider.scales) gives stock's five scale tables two rows more, in this
 * file's tables, and raises the SCALE clamps to 36: 35 POOLE ROD12, 36 POOLE12 MIN. Stock
 * then lists, names, lays out and plays them as it does any scale (ROD12 as Chromatic, MIN12 as
 * Aeolian). This file adds the tuning:
 *
 * - tn_poll (the UI loop, smp_ui_pop): each track's SCALE and ROOT, read through stock's own
 *   getters the way KB SETUP's dispatchers read them (0x4003bdb2 SCALE, 0x4003bce2 ROOT: the
 *   track's own value when that setting is per track, the keyboard's when not);
 * - tn_retune (the audio interrupt, ms_frame, after the frame is built): a voice whose track's
 *   SCALE is one of ours gets its note's cents (by the note's semitone above ROOT) added to its
 *   NOTE word (note << 8 | fine, the fine part in 1/256 semitone). A note off the scale's degrees
 *   (a sequenced one) is left at 12-TET. Nothing else changes: every other voice, track and
 *   scale is stock's. */
#define TUNE_C
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define D __attribute__((section(".data")))

#define VOICE_TRACK ((volatile u32 *)0x80005308u)
#define FRAME_NOTE(v) (1u + (v))                       /* u16 index: byte 2 + 2v */
#define KIT_POINTER (*(u8 *volatile *)0x800052A0u)

/* stock returns in d0, a pointer too (gcc's m68k ABI would read a pointer from a0) */
typedef u32 (*ctx_fn)(void);
typedef u32 (*obj_fn)(u32);
typedef int (*get_fn)(void *);
typedef unsigned char (*flag_fn)(void *);
typedef void (*set_fn)(void *, int);
#define CTX ((ctx_fn)0x4018A97Au)                       /* the UI's context */
#define PATTERN_OF ((obj_fn)0x4003EFA8u)                /* -> the object KB SETUP's dispatchers take */
#define KB_OF(x) ((void *)((u8 *)(x) + 44))             /* its keyboard settings (0x4003b394) */
#define TRACK_OF(x, t) ((void *)((u8 *)(x) + 70 + 132 * (t)))   /* track t's settings */
#define SCALE_PER_TRACK ((flag_fn)0x4003AC0Cu)          /* bit 2 of +33 */
#define ROOT_PER_TRACK ((flag_fn)0x4003AB54u)           /* bit 1 of +33 */
#define KB_SCALE ((get_fn)0x4003AA0Au)                  /* -1..36 (v0.58's clamp) */
#define KB_SCALE_SET ((set_fn)0x4003AA44u)
#define TRACK_SCALE ((get_fn)0x40050744u)
#define TRACK_SCALE_SET ((set_fn)0x4005077Eu)
#define KB_ROOT ((get_fn)0x4003AF20u)                   /* a byte, signed */
#define TRACK_ROOT ((get_fn)0x4005096Cu)

signed char tn_scale[16] D = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1};
signed char tn_root[16] D = {0};
u32 tn_polls D = 0;
u32 tn_last_x D = 0;                                    /* the object tn_poll read (the gate: stock's own) */
u32 tn_skips D = 0;                                     /* polls refused: an object without stock's vtable */

/* an object's first long is its vtable, in MAIN OS's constants: anything else is not the object
 * stock's getters expect, and calling through it would jump anywhere */
static int is_obj(const void *o)
{
    u32 vt = *(const u32 *)o;
    return vt >= 0x40000400u && vt < 0x40300000u && !(vt & 1u);
}
u32 tn_frames D = 0;                                    /* frames a voice was retuned in */
void tn_poll(void)
{
    if (!KIT_POINTER)
        return;
    u32 ctx = CTX();
    if (!ctx)
        return;
    void *x = (void *)PATTERN_OF(ctx);
    if (!x)
        return;
    tn_last_x = (u32)x;
    if (!is_obj(KB_OF(x))) {
        tn_skips++;
        return;
    }
    int sp = SCALE_PER_TRACK(KB_OF(x)) & 1, rp = ROOT_PER_TRACK(KB_OF(x)) & 1;
    if (sp || rp)                               /* the tracks' own objects, read only then */
        for (u32 t = 0; t < 16; t++)
            if (!is_obj(TRACK_OF(x, t))) {
                tn_skips++;
                return;
            }
    int ks = sp ? 0 : KB_SCALE(KB_OF(x)), kr = rp ? 0 : (signed char)KB_ROOT(KB_OF(x));
    for (u32 t = 0; t < 16; t++) {
        tn_scale[t] = (signed char)(sp ? TRACK_SCALE(TRACK_OF(x, t)) : ks);
        tn_root[t] = (signed char)(rp ? (signed char)TRACK_ROOT(TRACK_OF(x, t)) : kr);
    }
    tn_polls++;
}

void tn_retune(volatile u16 *f)
{
    int any = 0;
    for (u32 v = 0; v < 16; v++) {
        u32 t = VOICE_TRACK[v];
        if (t >= 16)
            continue;
        int s = tn_scale[t];
        if (s < TN_FIRST || s > TN_LAST)
            continue;
        u32 w = f[FRAME_NOTE(v)];
        int pc = ((int)(w >> 8) - tn_root[t]) % 12;
        if (pc < 0)
            pc += 12;
        int d = tn_fine[s - TN_FIRST][pc];
        if (!d)
            continue;
        int n = (int)w + d;
        f[FRAME_NOTE(v)] = (u16)(n < 0 ? 0 : n > 0x7FFF ? 0x7FFF : n);
        any = 1;
    }
    tn_frames += (u32)any;
}

/* the gate's (tune step): the keyboard's SCALE through stock's setter (SET >= -1), and what
 * stock's getter then gives; the same for track T's own SCALE */
int tn_kb_scale(int set)
{
    void *x = (void *)PATTERN_OF(CTX());
    if (set >= -1)
        KB_SCALE_SET(KB_OF(x), set);
    return KB_SCALE(KB_OF(x));
}

int tn_track_scale(int t, int set)
{
    void *x = (void *)PATTERN_OF(CTX());
    if (set >= -1)
        TRACK_SCALE_SET(TRACK_OF(x, t), set);
    return TRACK_SCALE(TRACK_OF(x, t));
}

int tn_kb_root(int set)                        /* the keyboard's ROOT (0..11), as tn_kb_scale */
{
    void *x = (void *)PATTERN_OF(CTX());
    if (set >= 0)
        ((set_fn)0x4003AF50u)(KB_OF(x), set);
    return (signed char)KB_ROOT(KB_OF(x));
}

int tn_kb_per_track(int set)                   /* SCALE per track (KB SETUP's flag), as tn_kb_scale */
{
    void *x = (void *)PATTERN_OF(CTX());
    if (set >= 0)
        ((set_fn)0x4003AC42u)(KB_OF(x), set);
    return SCALE_PER_TRACK(KB_OF(x)) & 1;
}

int tn_kb_mode(int set)                        /* the keyboard's MODE (chords), as tn_kb_scale */
{
    void *x = (void *)PATTERN_OF(CTX());
    if (set >= 0)
        ((set_fn)0x4003AED8u)(KB_OF(x), set);
    return (signed char)((get_fn)0x4003AEA8u)(KB_OF(x));
}
