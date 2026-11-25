/* v0.69: the voice/load guardrail (src/dnfw/sampler/guardrail.py, docs/guardrail.md).
 *
 * Each machine type weighs the DSP cycles a track of it takes (guard_tab.h). MACHINE SEL's commit
 * (rec.c smp_machine_commit) asks gr_allowed() first: a machine that would take the kit's total
 * past GR_LIMIT, heavier than the track's machine now, is refused, and a message says so for two
 * seconds. Stock machines weigh 0; a lighter machine is always allowed. */
#include "guard_tab.h"

typedef unsigned int u32;
typedef unsigned char u8;
#define D __attribute__((section(".data")))

#define KIT (*(volatile u32 *)0x800052A0u)
#define SOUND_TYPE(t) (*(volatile signed char *)(KIT + 52u + 1163u * (u32)(t) + 0xDEu))
#define NOW (*(volatile u32 *)0x4058E8D4u)
#define SET_PIXEL ((void (*)(void *, int, int, int))0x40113B90)
#define TEXT      ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545C)
#define FONT      0x44507ED8u
#define CENTRED 2
#define GR_SHOW 3000u                           /* two seconds of the UI's clock */

u32 gr_refused D = 0, gr_total D = 0;
static u32 gr_at D = 0;
static int gr_up D = 0;

static u32 w(int t) { return t >= 0 && t < GR_TYPES ? gr_weight[t] : 0u; }

u32 gr_kit_total(void)
{
    u32 s = 0;
    if (!KIT)
        return 0;
    for (int t = 0; t < 16; t++)
        s += w(SOUND_TYPE(t));
    return s;
}

/* 1: TRACK may change to TYPE */
int gr_allowed(u32 track, u32 type)
{
    if (track > 15 || !KIT)
        return 1;
    int old = SOUND_TYPE(track);
    u32 now = gr_kit_total(), want = now - w(old) + w((int)type);
    gr_total = want;
    if (w((int)type) <= w(old) || want <= GR_LIMIT)
        return 1;
    gr_refused++;
    gr_at = NOW;
    gr_up = 1;
    extern int smp_overlay_dirty;
    smp_overlay_dirty = 1;
    return 0;
}

int gr_visible(void)
{
    if (gr_up && NOW - gr_at > GR_SHOW) {
        gr_up = 0;
        extern int smp_overlay_dirty;
        smp_overlay_dirty = 1;
    }
    return gr_up;
}

/* the message, over whatever is up (page.c wr_screen, last) */
void gr_draw(void *c)
{
    int x0 = 10, x1 = 117, y0 = 14, y1 = 49;
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++)
            SET_PIXEL(c, x, y, y == y0 || y == y1 || x == x0 || x == x1);
    TEXT(c, FONT, 64, 38, CENTRED, "%s", "DSP LIMIT");
    TEXT(c, FONT, 64, 27, CENTRED, "%s", "TOO MANY HEAVY");
    TEXT(c, FONT, 64, 18, CENTRED, "%s", "MACHINES IN KIT");
}
