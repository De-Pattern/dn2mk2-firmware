/* Parameter slides (A4 mk2 / Overtone style), the ColdFire half. docs/slides.md.
 *
 * A trig with SLIDE on: every continuous parameter its p-locks change glides from the value
 * the track had (the smoothed value of the track's last voice) to the locked one over SLEN,
 * instead of jumping. Nothing slides on a trig with no stock p-lock, or with SLIDE off: then
 * every routine below hands over to stock and writes nothing (OFF is stock, byte for byte).
 *
 * The mirror is per VOICE (16 blocks of 101 slots): the target the sound and the locks write
 * (SRC, 0x80003af0), the one-pole smoother's 16.16 state (STATE, 0x8000de60) and its output
 * the frame is built from (OUT, 0x800068e4), word index 17 + 101 v + s in each. A lock jumps
 * STATE (0x400db092); the slide puts it back on the previous value and then moves STATE and
 * OUT together every frame, after the smoother, before the modulation is added (so LFOs ride
 * on top). It lands on the target exactly, where the smoother then rests. A slot leaves the
 * slide the frame its SRC stops being the target (a knob, a new sound, a new trig): STATE
 * then holds the slide's last value and the smoother glides on from there.
 *
 * Length: SLEN in 1/24 of a step (sl_units), at the tempo the frame carries (BPM x 120,
 * frame word 108) and the track's scale (the pattern's, or the track's in per-track mode).
 *
 * Per-trig storage: lock records of their own in the pattern's lock pool, RAM header
 * (SL_RAM_SLD / SL_RAM_SLEN, track | SL_TAG), stored (SL_ID_SLD / SL_ID_SLEN, track). The
 * lock-list builder copies the step's two values past the list's stock entries (SL_EXT).
 */
#define SLIDE_C
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef signed char s8;

#define D __attribute__((section(".data")))

#define NV 16
#define NS 101
#define IDX(v, s) (17u + 101u * (u32)(v) + (u32)(s))
#define STATE ((volatile u32 *)0x8000DE60u)
#define SRC ((volatile u16 *)0x80003AF0u)
#define OUT ((volatile u16 *)0x800068E4u)
#define OWNER ((volatile u32 *)0x80005308u)             /* voice -> track (0x40026a3c) */
#define VSOUND(v) (*(u8 *volatile *)(0x800052A8u + 4u * (u32)(v)))   /* voice -> sound */
#define SOUND_TYPE 0xDE
#define FRAMES (*(volatile u32 *)0x4058E8D4u)           /* frames since boot, 1,500 a second */
#define TEMPO (((volatile u16 *)0x80005E60u)[108])      /* the frame's BPM x 120 */
#define PATTERN (*(u8 *volatile *)0x42C5A9A0u)          /* the pattern playing */
#define SCALE_TICKS(i) (((const u8 *)0x401F6B08u)[4 * (i) + 3])   /* ticks a step: 3..48 */
#define SMOOTHER ((u32 (*)(void *))0x400DB12Au)
#define RECS 80
#define REC 258

/* the stock routines' bodies, entered past the bytes our hooks replaced (hooks.S) */
extern void sl_apply_stock(u32 v, u8 *list, void *mirror);
extern void sl_build_stock(int track, u8 *list, u8 *table, void *sound, int step, int a6, int a7);
extern int sl_clear_stock(void *model, int track, int step);
extern int sl_load_stock(u8 *ram, u8 *stored);
extern int sl_save_stock(u8 *stored, u8 *ram);

struct ext {                                    /* in a lock list at SL_EXT */
    u32 magic;                                  /* 'SL' << 16 | track << 8 | step */
    u16 sld, slen;                              /* the step's values, 0xffff: no lock */
    u32 frame;                                  /* FRAMES + 1 of its last apply; 0 never */
    u16 rec, pad;                               /* v0.41: its REC trig's buffer (1, 2), 0xffff none */
};
_Static_assert(SL_EXT + sizeof(struct ext) <= 20 + 202 * 8, "our values fit in the lock list's spare tail");

/* v0.41: a record's head byte for each of our locks: k 0 SLD, 1 SLEN, 2 REC (rectrig.c) */
static u8 head_of(u32 k)
{
    return k == 0 ? SL_RAM_SLD : k == 1 ? SL_RAM_SLEN : SL_RAM_REC;
}
static int our_head(u8 h)
{
    return h == SL_RAM_SLD || h == SL_RAM_SLEN || h == SL_RAM_REC;
}
static u32 k_of(u8 h)
{
    return h == SL_RAM_SLD ? 0 : h == SL_RAM_SLEN ? 1 : 2;
}

struct slide {
    u16 n;                                      /* slots sliding, 0: none */
    u16 units;                                  /* length, 1/24 step */
    u32 prog;                                   /* elapsed, units << 16 */
    u32 mul;                                    /* 6 / ticks-a-step, 8.8 */
    u8 slot[NS];
    u16 from[NS], to[NS];
};

struct slide sl_v[NV] D;
u16 sl_cap[NV][NS] D;                           /* per track: the values before the trig */
u32 sl_cap_frame[NV] D = {0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu,
                          0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu,
                          0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu,
                          0xFFFFFFFFu};
u8 sl_cap_ok[NV] D;
s8 sl_lastv[NV] D = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1};
u32 sl_started D;                               /* slides begun (a counter for the checks) */
u32 sl_ticks D;                                 /* frames the tick has run */

static void capture(u32 t, u32 from_voice)
{
    for (u32 s = 0; s < NS; s++)
        sl_cap[t][s] = (u16)((STATE[IDX(from_voice, s)] + 0x8000u) >> 16);
    sl_cap_ok[t] = 1;
}

/* A note's voice v on track t, at 0x40026bac (before its sound copy, the locks' undo and the
 * applier): v's own slide ends (the voice plays something new); the track's values before
 * this trig are kept (once a frame: a chord's second voice finds them kept), from the voice
 * the track last played on. */
void sl_pre(u32 v, u32 t)
{
    if (v >= NV || t >= NV)
        return;
    sl_v[v].n = 0;
    u32 f = FRAMES;
    if (sl_cap_frame[t] != f) {
        sl_cap_frame[t] = f;
        sl_cap_ok[t] = 0;
        if (sl_lastv[t] >= 0)
            capture(t, (u32)sl_lastv[t]);
    }
    sl_lastv[t] = (s8)v;
}

static int continuous(int type, u32 slot, u32 v)
{
    if (slot > 100 || type < 0 || type == 4)
        return 0;
    if ((sl_shared[slot >> 5] >> (slot & 31)) & 1)
        return 1;
    if (type < 4)
        return (sl_machine[type][slot >> 5] >> (slot & 31)) & 1;
    /* v0.41 (dnfw.slides SAMPLE_SLIDE, MD_MIDNOTE): the sample machines' controls read while
     * the note sounds; PERC's track effects, and the controls of its machine (TYPE's value as
     * the DSP reads it: the voice's target, 0..127 over the machines) that its code hears
     * mid-note. Choices, and controls taken only at the note, never slide */
    if (type >= 8 && type <= 13)
        return (sl_samp[type - 8][slot >> 5] >> (slot & 31)) & 1;
    if (type == 17)                                 /* v0.44: BOUNCE, the seventh row */
        return (sl_samp[6][slot >> 5] >> (slot & 31)) & 1;
    if (type == SL_PERC_TYPE) {
        if ((sl_perc_fx[slot >> 5] >> (slot & 31)) & 1)
            return 1;
        u32 tv = SRC[IDX(v, SL_PERC_TYPE_SLOT)] >> 8;
        u32 m = (tv > 127 ? 127 : tv) * SL_PERC_N >> 7;
        for (u32 k = 0; k < 8; k++)
            if (sl_perc_slot[k] == slot)
                return (sl_perc_bits[m < SL_PERC_N ? m : SL_PERC_N - 1] >> k) & 1;
    }
    return 0;
}

static u32 ticks_a_step(u32 t)
{
    u8 *p = PATTERN;
    if (!p)
        return 6;
    s8 i = p[122201] == 1 ? (s8)p[1701u * t + 1167u] : (s8)p[122202];
    if (i < 0 || i > 6)
        return 6;
    u32 n = SCALE_TICKS(i);
    return n ? n : 6;
}

static void trigger(u32 v, u32 t, u8 *list)
{
    int count = *(int *)(list + 8);
    if (count <= 0 || !sl_cap_ok[t])
        return;
    struct ext *e = (struct ext *)(list + SL_EXT);
    if ((e->magic >> 16) != 0x534Cu || ((e->magic >> 8) & 0xFF) != t)
        return;
    e->frame = FRAMES + 1;                      /* (kept for the checks: when it last applied) */
    if (e->sld != 1)
        return;
    u8 *snd = VSOUND(v);
    if (!snd)
        return;
    int type = (s8)snd[SOUND_TYPE];
    struct slide *sl = &sl_v[v];
    u32 n = 0;
    if (count > NS)
        count = NS;
    for (int j = 0; j < count; j++) {
        u32 slot = *(u16 *)(list + 20 + 8 * j);
        if (!continuous(type, slot, v))
            continue;
        u32 i = IDX(v, slot);
        u16 to = SRC[i], from = sl_cap[t][slot];
        if (to == from)
            continue;
        int dup = 0;
        for (u32 k = 0; k < n; k++)
            dup |= sl->slot[k] == slot;
        if (dup)
            continue;
        sl->slot[n] = (u8)slot;
        sl->from[n] = from;
        sl->to[n] = to;
        STATE[i] = (u32)from << 16;
        n++;
    }
    if (!n)
        return;
    u32 len = e->slen < SL_NLEN ? e->slen : SL_LEN_DEFAULT;
    sl->units = sl_units[len];
    sl->prog = 0;
    sl->mul = (6u << 8) / ticks_a_step(t);
    sl->n = (u16)n;
    sl_started++;
}

/* The lock applier 0x400db092(voice, list, mirror), both callers (a note's voice, and a
 * trigless lock on each voice of its track): stock's, then the slide this trig asks for. */
void sl_apply(u32 v, u8 *list, void *mirror)
{
    if (v >= NV || !list) {
        sl_apply_stock(v, list, mirror);
        return;
    }
    u32 t = OWNER[v];
    if (t >= NV) {
        sl_apply_stock(v, list, mirror);
        return;
    }
    u32 f = FRAMES;
    if (sl_cap_frame[t] != f) {                 /* trigless: the values are this voice's own */
        sl_cap_frame[t] = f;
        capture(t, v);
        sl_lastv[t] = (s8)v;
    }
    sl_v[v].n = 0;
    sl_apply_stock(v, list, mirror);
    trigger(v, t, list);
    /* (v0.41..v0.43 fired a REC trig from here, so a step with no note never recorded; v0.44:
     * rectrig.c's rt_frame fires from the sequencer's own step, whatever the step holds) */
}



/* Every frame, at 0x4002717e: the stock smoother, then every slide one frame on. */
u32 sl_smooth(void *src)
{
    u32 base = SMOOTHER(src);
    sl_ticks++;
    u32 w = TEMPO;
    if (w < 1200 || w > 60000)
        w = 120 * 120;
    u32 inc = (w << 16) / 112500u;              /* 1/24 steps a frame, 16.16, at 1x */
    for (u32 v = 0; v < NV; v++) {
        struct slide *sl = &sl_v[v];
        if (!sl->n)
            continue;
        sl->prog += (inc * sl->mul) >> 8;
        u32 frac = sl->prog / (2u * sl->units); /* 0..32768 */
        int done = frac >= 32768u;
        if (done)
            frac = 32768u;
        for (u32 k = 0; k < sl->n;) {
            u32 i = IDX(v, sl->slot[k]);
            if (SRC[i] != sl->to[k]) {          /* its source changed: it leaves the slide */
                u32 last = --sl->n;
                sl->slot[k] = sl->slot[last];
                sl->from[k] = sl->from[last];
                sl->to[k] = sl->to[last];
                continue;
            }
            int a = sl->from[k], d = (int)sl->to[k] - a;
            u32 val = (u32)(a + ((d * (int)frac) >> 15));
            OUT[i] = (u16)val;
            STATE[i] = val << 16;
            k++;
        }
        if (done)
            sl->n = 0;
    }
    return base;
}

/* ---- the lock records ---------------------------------------------------------------- */

static int ours(const u8 *r, u32 t)
{
    return our_head(r[0]) && r[1] == (SL_TAG | t);
}

/* the step's SLD (k 0), SLEN (k 1) or REC (k 2, v0.41) lock in TABLE, 0xffff: none */
u32 sl_lock_get(const u8 *table, u32 t, u32 step, u32 k)
{
    if (!table || t >= NV || step > 127 || k > 2)
        return 0xFFFF;
    u8 head = head_of(k);
    for (u32 i = 0; i < RECS; i++) {
        const u8 *r = table + REC * i;
        if (r[0] == head && r[1] == (SL_TAG | t))
            return *(const u16 *)(r + 2 + 2 * step);
    }
    return 0xFFFF;
}

/* set (VALUE <= 0x7fff) or clear (0xffff) a lock; -> 0 when no record is free. A new record is
 * taken only while more than RESERVE are free (v0.40 review: a paste leaves stock's locks still to
 * come the records they need; stock's own allocation skips a lock when none is free). */
static int lock_set(u8 *table, u32 t, u32 step, u32 k, u32 value, u32 reserve)
{
    if (!table || t >= NV || step > 127 || k > 2)
        return 0;
    u8 head = head_of(k);
    u8 *rec = 0, *free = 0;
    u32 nfree = 0;
    for (u32 i = 0; i < RECS; i++) {
        u8 *r = table + REC * i;
        if (r[0] == head && r[1] == (SL_TAG | t))
            rec = r;
        else if (r[0] == 0xFF) {
            if (!free)
                free = r;
            nfree++;
        }
    }
    if (!rec) {
        if (value == 0xFFFF)
            return 1;
        if (!free || nfree <= reserve)
            return 0;
        rec = free;
        for (u32 s = 0; s < 128; s++)
            *(u16 *)(rec + 2 + 2 * s) = 0xFFFF;
        rec[1] = SL_TAG | t;
        rec[0] = head;
    }
    *(u16 *)(rec + 2 + 2 * step) = (u16)value;
    if (value == 0xFFFF) {                      /* the record's last lock: the record freed */
        u32 s = 0;
        while (s < 128 && *(u16 *)(rec + 2 + 2 * s) == 0xFFFF)
            s++;
        if (s == 128) {
            rec[0] = 0xFF;
            rec[1] = 0xFF;
        }
    }
    return 1;
}

int sl_lock_set(u8 *table, u32 t, u32 step, u32 k, u32 value)
{
    return lock_set(table, t, step, k, value, 0);
}

/* the lock-list builder 0x400d85e8(track, list, table, sound, step, ...): stock's, then the
 * step's SLD and SLEN past its entries */
void sl_build(int track, u8 *list, u8 *table, void *sound, int step, int a6, int a7)
{
    sl_build_stock(track, list, table, sound, step, a6, a7);
    if (!list || track < 0 || track >= NV || step < 0 || step > 127)
        return;
    struct ext *e = (struct ext *)(list + SL_EXT);
    e->sld = (u16)sl_lock_get(table, (u32)track, (u32)step, 0);
    e->slen = (u16)sl_lock_get(table, (u32)track, (u32)step, 1);
    e->rec = (u16)sl_lock_get(table, (u32)track, (u32)step, 2);
    e->pad = 0;
    e->frame = 0;
    e->magic = 0x534C0000u | ((u32)track << 8) | (u32)step;
}

/* clear a step's locks 0x4003d14e(model, track, step): stock's, then ours on that step */
int sl_clear(void *model, int track, int step)
{
    int r = sl_clear_stock(model, track, step);
    if (!model)
        return r;
    if (track < 0) track = 0;
    if (track > 15) track = 15;
    if (step < 0) step = 0;
    if (step > 127) step = 127;
    /* the model's lock table (vtable +40). Declared as returning an integer: stock returns it
     * in d0, and GCC would take a returned pointer from a0 */
    u8 *table = (u8 *)((u32 (*)(void *))((*(void ***)model)[10]))(model);
    sl_lock_set(table, (u32)track, (u32)step, 0, 0xFFFF);
    sl_lock_set(table, (u32)track, (u32)step, 1, 0xFFFF);
    sl_lock_set(table, (u32)track, (u32)step, 2, 0xFFFF);
    return r;
}

/* the pattern's lock table, RAM -> stored 0x400de718(stored, ram): stock's, then our
 * records' headers as their stored ids (stock wrote each record i to i) */
int sl_save(u8 *stored, u8 *ram)
{
    int r = sl_save_stock(stored, ram);
    if (!stored || !ram)
        return r;
    for (u32 i = 0; i < RECS; i++) {
        const u8 *m = ram + REC * i;
        u8 *s = stored + REC * i;
        if (our_head(m[0]) && (m[1] & 0xF0) == SL_TAG) {
            s[0] = m[0] == SL_RAM_SLD ? SL_ID_SLD : m[0] == SL_RAM_SLEN ? SL_ID_SLEN : SL_ID_REC;
            s[1] = m[1] & 0x0F;
        }
    }
    return r;
}

/* stored -> RAM 0x400de51e(ram, stored): stock's (it skips our ids, leaving record i free),
 * then ours back in */
int sl_load(u8 *ram, u8 *stored)
{
    int r = sl_load_stock(ram, stored);
    if (!ram || !stored)
        return r;
    for (u32 i = 0; i < RECS; i++) {
        const u8 *s = stored + REC * i;
        u8 *m = ram + REC * i;
        if ((s[0] != SL_ID_SLD && s[0] != SL_ID_SLEN && s[0] != SL_ID_REC) || s[1] > 15 || m[0] != 0xFF)
            continue;
        for (u32 b = 2; b < REC; b++)
            m[b] = s[b];
        m[1] = SL_TAG | s[1];
        m[0] = s[0] == SL_ID_SLD ? SL_RAM_SLD : s[0] == SL_ID_SLEN ? SL_RAM_SLEN : SL_RAM_REC;
    }
    return r;
}

int sl_ours_any(const u8 *table, u32 t)
{
    for (u32 i = 0; i < RECS; i++)
        if (ours(table + REC * i, t))
            return 1;
    return 0;
}

/* ---- the TRIG page: SLD and SLEN in its second page's two empty places ------------------
 *
 * "Retrig Parameters (2/2)" has RTRG VFAD LEN RATE above, two empty places, PTIM and PORT
 * below. Every cell of a stock page is drawn by 0x4006448a(view, canvas, x, y, id) and told
 * to wr_cell (page.c) as it finishes: PTIM (record 34) at (76, 0) means this page is being
 * drawn, so the two places to its left, (24, 0) and (50, 0), get SLD and SLEN, which encoders
 * E and F set. A trig held: its own value (the first held step's), drawn inverted when it is
 * a lock, as stock draws a p-lock; turning sets it on every held step. No trig held: what a
 * trig gets with no lock (OFF, 1 step), and turning does nothing. */
#define SET_PIXEL ((void (*)(void *, int, int, int))0x40113B90u)   /* (canvas, x, y, on) */
#define TEXT ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545Cu)
#define CENTRED 2
#define APP ((u32 (*)(void))0x4018A97Au)
#define TRACK_CTX ((u32 (*)(u32))0x4003EFDEu)
#define PATTERN_LEN ((u32 (*)(u32))0x4004F896u)
#define HELD_OBJ (*(u8 *volatile *)0x446478C8u)
#define BIT_TEST ((u32 (*)(void *, u32))0x4019C40Cu)
#define PTIM_ID 34
#define SL_X0 24                                /* encoder E's place; F's is a column on */
#define SL_COLW 26

u32 sl_page_seen D;                             /* draws of the page (for the checks) */
static int sl_seen_now D;                       /* drawn in this screen pass */
int sl_page_up D;                               /* the last screen drawn shows it, nothing over it */
u8 *sl_ui_table D;                              /* the lock table the last turn wrote (for the checks) */
extern int smp_overlay_dirty;

struct held {
    u8 *table;
    void *model;
    u32 track, len, first, any;
};

static int held(struct held *h)
{
    u8 *obj = HELD_OBJ;
    h->any = 0;
    if (!obj || !obj[616])
        return 0;
    u32 ctx = TRACK_CTX(APP());
    if (!ctx)
        return 0;
    void *model = *(void **)(ctx + 44);
    u32 t = *(u32 *)(ctx + 60);
    if (!model || t >= NV)
        return 0;
    u32 len = PATTERN_LEN(ctx);
    if (len > 128)
        len = 128;
    h->model = model;
    h->table = (u8 *)((u32 (*)(void *))((*(void ***)model)[10]))(model);
    h->track = t;
    h->len = len;
    for (u32 s = 0; s < len; s++)
        if (BIT_TEST(obj + 600, s) & 0xFF) {
            h->first = s;
            h->any = 1;
            return h->table != 0;
        }
    return 0;
}

/* v0.40 (owner, on v0.39's page: "match identically the toggle icon from RTRG above SLD ...
 * SLEN should resemble the LEN box above"): each place is drawn as stock's cell routine
 * 0x4006448a draws RTRG and LEN in theirs, through stock's own routines with stock's
 * arguments (measured in the emulator, TRIG page 2: RTRG at (24, 27), LEN at (76, 27), PORT
 * at (102, 0); canvas y up, the label at y, the widget from y + 7):
 *
 * - SLD: RTRG's widget, drawn by stock's widget routine 0x40036560 with RTRG's record (id
 *   0x132; its toggle 0x400bc414 blits the sheet's frame value >> 8 at (x + 1, y + 11)), the
 *   value 0 (OFF) or 0x100 (ON), as RTRG's own;
 * - SLEN: LEN's box, as LEN's widget 0x400cc2b4 draws it (its font 0x40293c64, the text
 *   centred at (x + 9, y + 13), the box (x, y + 7) .. (x + 18, y + 23)): our text, as LEN's
 *   own table has no "1", "1.5" ... (its "1/8" is two steps);
 * - the label as the cell routine draws it (0x40115668, font 0x40291760, centred at x + 9 on
 *   a cleared "XXXX" width: x - 2 .. x + 20);
 * - a lock (a trig's own value): stock's p-lock look, the widget's area inverted, 0x40114842
 *   (x - 3, y + 6, x + 21, y + 24, -1), as the cell routine does for a locked parameter.
 *
 * The place is cleared first (stock's empty place shows a dotted frame there). */
#define CELL_TEXT ((void (*)(void *, u32, int, int, int, int, u32, u32, const char *))0x40115668u)
#define CELL_FONT 0x40291760u
#define CELL_FMT_W 0x402170B9u                  /* "XXXX": the label's width */
#define FMT_S 0x40219C2Du                       /* "%s" */
#define FILL ((void (*)(void *, int, int, int, int, int))0x40114842u)   /* (c, x0, y0, x1, y1, mode) */
#define WIDGET ((void (*)(void *, u32, u32, u32, void *, void *, int, int))0x40036560u)
#define RTRG_ID 0x132u
#define BOX_FONT_INIT ((void (*)(void *, u32))0x40115E6Cu)
#define BOX_FONT_FREE ((void (*)(void *))0x40115CE8u)
#define BOX_FONT 0x40293C64u
#define RECT ((void (*)(void *, int, int, int, int, int))0x40114626u)    /* (c, x0, y0, x1, y1, 1) */

static void clear(void *c, int x0, int y0, int x1, int y1)
{
    for (int x = x0; x <= x1; x++)
        for (int y = y0; y <= y1; y++)
            SET_PIXEL(c, x, y, 0);
}

static void label(void *c, int x, int y, const char *name, int locked)
{
    CELL_TEXT(c, CELL_FONT, x + 9, y, 1, 0, CELL_FMT_W, FMT_S, name);
    if (locked)
        FILL(c, x - 3, y + 6, x + 21, y + 24, -1);
}

/* exported for the emulator check (scripts/emu_slides.py draws both on a canvas of its own,
 * beside stock's RTRG and LEN drawn there by stock's routines) */
void sl_draw_sld(void *c, int x, int y, int on, int locked)
{
    clear(c, x - 3, y, x + 21, y + 24);
    WIDGET(0, RTRG_ID, on ? 0x100u : 0u, 0, 0, c, x, y + 7);
    label(c, x, y, "SLD", locked);
}

void sl_draw_slen(void *c, int x, int y, u32 i, int locked)
{
    static u32 font[8] D;                       /* the font object (stock's: on its stack) */
    clear(c, x - 3, y, x + 21, y + 24);
    BOX_FONT_INIT(font, BOX_FONT);
    TEXT(c, (u32)font, x + 9, y + 13, CENTRED, (const char *)FMT_S, sl_len_text[i < SL_NLEN ? i : SL_LEN_DEFAULT]);
    BOX_FONT_FREE(font);
    RECT(c, x, y + 7, x + 18, y + 23, 1);
    label(c, x, y, "SLEN", locked);
}

void sl_cell(void *view, void *canvas, int x, int y, u32 id)
{
    (void)view;
    if (id != PTIM_ID || x != SL_X0 + 2 * SL_COLW || y != 0)
        return;
    sl_seen_now = 1;
    sl_page_seen++;
    struct held h;
    u32 sld = 0xFFFF, slen = 0xFFFF;
    if (held(&h)) {
        sld = sl_lock_get(h.table, h.track, h.first, 0);
        slen = sl_lock_get(h.table, h.track, h.first, 1);
    }
    sl_draw_sld(canvas, SL_X0, 0, sld == 1, sld != 0xFFFF);
    sl_draw_slen(canvas, SL_X0 + SL_COLW, 0, slen != 0xFFFF ? slen : SL_LEN_DEFAULT, slen != 0xFFFF);
}

/* wr_screen (page.c), around each draw of the screen: PHASE 0 before, 1 after (COVERED: one
 * of our screens drawn over it) */
void sl_screen(int phase, int covered)
{
    if (!phase)
        sl_seen_now = 0;
    else
        sl_page_up = sl_seen_now && !covered;
}

/* v0.41 (the owner: "detent the slide length knob as we did with the others"): SLEN, a
 * choice control of 15 steps, four detents a choice as PLAY, MODE, BARS, GRID (fmt.c
 * CHOICE_DETENTS) and the RECORDER's SRC and CHAN (rec.c rec_choice_step). A turn back, or a
 * pause of 2 s, starts the count again; a fast turn's item carries several detents and counts
 * them all. SLD is a switch (the turn's direction sets it) and keeps one detent */
#define SL_CHOICE_DETENTS 4
static int slk_acc __attribute__((section(".data"))) = 0;
static u32 slk_at __attribute__((section(".data"))) = 0;

static int sl_choice_step(int delta)            /* -> the choices to move */
{
    u32 now = *(volatile u32 *)0x4058E8D4u;     /* the 1.5 kHz ticks */
    if (now - slk_at > 3000u || (slk_acc > 0 && delta < 0) || (slk_acc < 0 && delta > 0))
        slk_acc = 0;
    slk_at = now;
    slk_acc += delta;
    int n = slk_acc / SL_CHOICE_DETENTS;        /* (toward 0: the remainder kept) */
    slk_acc -= n * SL_CHOICE_DETENTS;
    return n;
}

/* an encoder turned (smp_ui_pop): E or F while the page is up -> 1, taken */
int sl_knob(u32 index, int delta)
{
    if ((index != 5 && index != 6) || !sl_page_up)
        return 0;
    if (!delta)
        return 1;
    struct held h;
    if (!held(&h))
        return 1;                               /* no trig held: nothing to set */
    u8 *obj = HELD_OBJ;
    u32 k = index == 6;
    u32 cur = sl_lock_get(h.table, h.track, h.first, k);
    u32 v;
    if (!k)
        v = delta > 0 ? 1 : 0;
    else {
        int step = sl_choice_step(delta);       /* v0.41: four detents a choice */
        if (!step)
            return 1;
        int n = (int)(cur != 0xFFFF ? cur : SL_LEN_DEFAULT) + step;
        v = (u32)(n < 0 ? 0 : n >= SL_NLEN ? SL_NLEN - 1 : n);
    }
    for (u32 s = 0; s < h.len; s++)
        if (BIT_TEST(obj + 600, s) & 0xFF)
            sl_lock_set(h.table, h.track, s, k, v);
    sl_ui_table = h.table;
    /* the pattern changed, as the stock clear tells it (vtable +16, no detail) */
    ((void (*)(void *, void *))((*(void ***)h.model)[4]))(h.model, 0);
    smp_overlay_dirty = 1;
    return 1;
}

/* ---- v0.41: the REC trig's lock, from the RECORDER overlay (rec.c, rectrig.c) -----------
 *
 * The RECORDER is ours (an overlay, over any track's page), so it is where a REC trig is
 * set: a step held (in GRID RECORDING, as for any p-lock), knob H steps its REC lock
 * through OFF, REC 1, REC 2, four detents a choice; every held step gets it, as SLD/SLEN.
 * Any track: the lock lives on the held step of the active track, whatever its machine. */
static int srk_acc D = 0;
static u32 srk_at D = 0;
static u32 srk_key D = 0xFFFFFFFFu;             /* the held step the count is for */
u8 *sl_rec_table D;                             /* the table the last REC turn wrote (for the checks) */

int sl_rec_held(u32 *val)                       /* a step held -> 1, *VAL its REC (0xffff none) */
{
    struct held h;
    if (!held(&h))
        return 0;
    *val = sl_lock_get(h.table, h.track, h.first, 2);
    return 1;
}

/* v0.41 (the REC TRIGS view's grid): the active track's REC locks on the 16 steps of the page it
 * plays (or played last) -> the first step's number, OUT[16] each step's (0 none, 1, 2); -1 none */
#define TRACK_CUR ((volatile u8 *)0x42C5A984u)
int sl_rec_page(u8 *out)
{
    u32 ctx = TRACK_CTX(APP());
    if (!ctx)
        return -1;
    void *model = *(void **)(ctx + 44);
    u32 t = *(u32 *)(ctx + 60);
    if (!model || t >= NV)
        return -1;
    u8 *table = (u8 *)((u32 (*)(void *))((*(void ***)model)[10]))(model);
    u32 len = PATTERN_LEN(ctx);
    if (!table || len == 0)
        return -1;
    if (len > 128)
        len = 128;
    u32 first = (TRACK_CUR[t] % len) & ~15u;
    for (u32 i = 0; i < 16; i++) {
        u32 v = first + i < len ? sl_lock_get(table, t, first + i, 2) : 0xFFFF;
        out[i] = (u8)(v == 1 || v == 2 ? v : 0);
    }
    return (int)first;
}

int sl_rec_knob(int delta)                      /* -> 1: a step is held and H was its REC's */
{
    struct held h;
    if (!held(&h))
        return 0;
    u32 now = FRAMES, key = h.track << 8 | h.first;
    if (key != srk_key || now - srk_at > 3000u || (srk_acc > 0 && delta < 0) || (srk_acc < 0 && delta > 0))
        srk_acc = 0;                            /* (another step held: counted from nothing) */
    srk_key = key;
    srk_at = now;
    srk_acc += delta;
    int n = srk_acc / SL_CHOICE_DETENTS;
    srk_acc -= n * SL_CHOICE_DETENTS;
    if (!n)
        return 1;
    u32 cur = sl_lock_get(h.table, h.track, h.first, 2);
    int i = cur == 1 ? 1 : cur == 2 ? 2 : 0;    /* OFF, REC 1, REC 2 */
    i += n;
    if (i < 0) i = 0;
    if (i > 2) i = 2;
    u32 v = i == 0 ? 0xFFFFu : (u32)i;
    u8 *obj = HELD_OBJ;
    for (u32 st = 0; st < h.len; st++)
        if (BIT_TEST(obj + 600, st) & 0xFF)
            sl_lock_set(h.table, h.track, st, 2, v);
    sl_rec_table = h.table;
    ((void (*)(void *, void *))((*(void ***)h.model)[4]))(h.model, 0);   /* the pattern changed */
    smp_overlay_dirty = 1;
    return 1;
}

/* ---- v0.40: copy and paste carry SLD/SLEN ----------------------------------------------
 *
 * v0.39's known issue: stock's copies match lock records by track, and ours are tagged
 * (track | SL_TAG), so no copy took them, and the trig copy keeps its own slot/value list.
 * The hooks (hooks.S) are the arp p-locks' sites and shapes (scripts/build_arp_plocks.py):
 *
 * - page and track paste (and their UNDO): the paste loops over the clipboard's records; one
 *   of ours of the copied track is written onto the destination track here (sl_paste), as
 *   stock writes its own. Stock cleared the destination's steps first through 0x4003d14e
 *   (sl_clear: ours on those steps too), so the pasted steps' slides are the clipboard's,
 *   exactly as their other locks, and the track's other steps keep theirs.
 * - track clear (0x400e745c, FUNC + PLAY): it frees the track's records by their track byte;
 *   the tag cleared there, ours go with them.
 * - shift and page autocopy: the tag cleared in their track compare, so ours move with
 *   their steps inside the record.
 * - trig copy / paste: each copied trig's two values kept by its clipboard entry (sl_tclip),
 *   written onto the step it is pasted on (cleared by stock just before).
 * - v0.40 review: a paste takes a free record for ours only while more are free than stock's
 *   locks still to come in the same paste need (lock_set's RESERVE), so a nearly full lock table
 *   drops slides, never a stock lock.
 * - pattern copy/paste: whole-pattern copies (122,478 bytes, the lock table inside) carry
 *   our records as bytes. */
static u8 *ctx_table(void *ctx)
{
    void *model = *(void **)((u8 *)ctx + 44);
    if (!model)
        return 0;
    return (u8 *)((u32 (*)(void *))((*(void ***)model)[10]))(model);
}

u32 sl_pasted D;                                /* our values written by pastes (for the checks) */
u32 sl_paste_dropped D;                         /* our values a paste left out: no record to spare */

/* does stock's paste still need a new record for this clipboard record? (its loop: a record of the
 * clipboard's track, slot byte not 0xff, and no record of that slot on the destination track in
 * the index at +20640; 0x40053246 and its three siblings). Counted generously: a slot out of the
 * index's range counts too. */
static int stock_needs(const u8 *r, const u8 *table, int dt, u32 ct)
{
    if (r[0] == 0xFF || (s8)r[1] != (int)ct)
        return 0;
    if (r[0] > 100)
        return 1;
    return (s8)table[20640 + 101 * (u32)dt + r[0]] < 0;
}

int sl_paste(const u8 *rec, const u8 *vals, u8 *table, int first, int count, int dt, u32 ct,
             const u8 *clip)
{
    int tb = (s8)rec[1];
    if (!our_head(rec[0]) || (rec[1] & 0xF0) != SL_TAG
        || (u32)(rec[1] & 0x0F) != ct || dt < 0 || dt >= NV || !table || first < 0 || count < 0)
        return tb;
    /* v0.40 review: stock's loop takes the clipboard's records in order and allocates each
     * destination record as it goes, skipping a lock when none is free; ours are written here,
     * inside that loop, so the stock records after this one keep the free records they need */
    u32 reserve = RECS;                         /* (no clipboard to read: never take a free one) */
    if (clip && rec >= clip && (u32)(rec - clip) < REC * RECS) {
        reserve = 0;
        for (u32 j = (u32)(rec - clip) / REC + 1; j < RECS; j++)
            reserve += (u32)stock_needs(clip + REC * j, table, dt, ct);
    }
    u32 k = k_of(rec[0]);
    for (int i = 0; i < count && first + i < 128; i++) {
        u32 v = *(const u16 *)(vals + 2 + 2 * i);
        if (v == 0xFFFF)
            continue;
        if (lock_set(table, (u32)dt, (u32)(first + i), k, v, reserve))
            sl_pasted++;
        else
            sl_paste_dropped++;
    }
    return -2;
}

#define TCLIP 128
u32 sl_tclip[TCLIP] D = {[0 ... TCLIP - 1] = 0xFFFFFFFFu};                          /* a copied trig's SLEN << 16 | SLD (0xffff none) */
u8 sl_tclip_rec[TCLIP] D = {[0 ... TCLIP - 1] = 0xFFu};                            /* v0.41: its REC (0xff none) */

void sl_tcopy(u32 off, void *ctx, u32 step)
{
    u32 e = off / 72u;
    if (e >= TCLIP)
        return;
    sl_tclip[e] = 0xFFFFFFFFu;
    sl_tclip_rec[e] = 0xFFu;
    u8 *table = ctx ? ctx_table(ctx) : 0;
    u32 t = ctx ? *(u32 *)((u8 *)ctx + 60) : NV;
    if (!table || t >= NV || step > 127)
        return;
    sl_tclip[e] = sl_lock_get(table, t, step, 0) | sl_lock_get(table, t, step, 1) << 16;
    u32 r = sl_lock_get(table, t, step, 2);
    sl_tclip_rec[e] = r == 0xFFFF ? 0xFFu : (u8)r;
}

/* the records stock's trig paste still needs (v0.40 review): entries E.. of the clipboard's
 * vector (VEC: its entries from +4 to +8, 72 bytes each; an entry's locks from +48 to +52, 8 bytes
 * each, {value, slot}, written by 0x4003ceee after this hook), each slot of track T with no record
 * in the index counted once. Anything out of shape: RECS (no free record taken). */
static u32 tstock_needs(const u8 *vec, u32 e, const u8 *table, u32 t)
{
    if (!vec)
        return RECS;
    const u8 *b = *(const u8 *const *)(vec + 4), *end = *(const u8 *const *)(vec + 8);
    if (!b || end < b || (u32)(end - b) > 72u * 4096u)
        return RECS;
    u32 seen[4], n = 0;
    seen[0] = seen[1] = seen[2] = seen[3] = 0;
    for (const u8 *en = b + 72u * e; en + 72 <= end; en += 72) {
        const u8 *p = *(const u8 *const *)(en + 48), *q = *(const u8 *const *)(en + 52);
        if (!p || q < p || (u32)(q - p) > 8u * 4096u)
            return RECS;
        for (; p + 8 <= q; p += 8) {
            u32 slot = *(const u32 *)(p + 4);
            if (slot > 100 || (s8)table[20640 + 101 * t + slot] >= 0)
                continue;                       /* stock's setter refuses it, or has a record */
            if (!((seen[slot >> 5] >> (slot & 31)) & 1)) {
                seen[slot >> 5] |= 1u << (slot & 31);
                n++;
            }
        }
    }
    return n;
}

void sl_tpaste(u32 off, void *ctx, u32 step, const u8 *vec)
{
    u32 e = off / 72u;
    if (e >= TCLIP || !ctx || step > 127)
        return;
    u8 *table = ctx_table(ctx);
    u32 t = *(u32 *)((u8 *)ctx + 60);
    if (!table || t >= NV)
        return;
    u32 c = sl_tclip[e];
    u32 cr = sl_tclip_rec[e];
    if (c == 0xFFFFFFFFu && cr == 0xFFu)
        return;
    u32 reserve = tstock_needs(vec, e, table, t);
    for (u32 k = 0; k < 3; k++) {
        u32 v = k < 2 ? (c >> (16 * k)) & 0xFFFF : cr == 0xFFu ? 0xFFFFu : cr;
        if (v == 0xFFFF)
            continue;
        if (lock_set(table, t, step, k, v, reserve))
            sl_pasted++;
        else
            sl_paste_dropped++;
    }
}

/* v0.44: the UI's pattern's lock table (rec.c: the recorder trigs placed and read on the
 * BOUNCE RECORDER page), 0 when there is none */
u8 *sl_ui_table_now(void)
{
    u32 ctx = TRACK_CTX(APP());
    if (!ctx)
        return 0;
    return ctx_table((void *)ctx);
}
