/* v0.23: SLICE's own menus, as the Digitakt II's (its manual, 13.4 and the SLICE machine):
 *
 *   YES on a SLICE track's page   the SLICE menu: EDIT SLICE POINTS, CREATE SLICE GRID,
 *                                CREATE LINEAR LOCKS, CREATE RANDOM LOCKS (v0.25)
 *   YES on a GRID track's page    ALLOCATE SLICE: CREATE LINEAR / RANDOM LOCKS, NO cancels (v0.25)
 *   CREATE SLICE GRID            SLICES (E) 2..64, TR.DET (H) off/on; YES makes them, NO cancels
 *                                (TR.DET: a slice at each transient, as many as SLICES at most)
 *   EDIT SLICE POINTS            the sample's waveform with its slices; LEFT/RIGHT pick one,
 *                                E START, H END, D LOOP, F ZOOM (FUNC + F: the height), G POS;
 *                                FUNC + YES adds a slice where the view is, FUNC + NO removes
 *                                the picked one; NO leaves, keeping the edit
 *
 * The slices are kept in the pool's slice area (link.c's smp_slices_set): on the +Drive,
 * and in the DSP at once; the SLICE machine plays them (dnfw.sampler.program.slice_bounds).
 * A sample's fine waveform and its transients come from reading it back from the +Drive
 * (link.c's smp_analyse), a chunk a UI pass.
 */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define SET_PIXEL ((void (*)(void *, int, int, int))0x40113B90)
#define LABEL_FONT 0x40291760u
#define LABEL_TEXT ((void (*)(void *, u32, int, int, int, int, const char *, const char *, ...))0x40115668u)
#define LABEL(c, x, y, fmt, ...) LABEL_TEXT((c), LABEL_FONT, (x), (y), 1, 0, 0, fmt, __VA_ARGS__)
#define FRAMES (*(volatile u32 *)0x4058E8D4u)
#define KIT (*(volatile u32 *)0x800052A0u)
#define ACTIVE_TRACK (*(volatile u8 *)0x42431A6Cu)
#define SOUND(t) (KIT + 52u + 1163u * (u32)(t))
#define SLICE_TYPE 13                           /* dnfw.sampler.machines.TYPE_OF["SLICE"] */
#define RECORD(id) ((const int *)(0x401F7F94u + 60u * (id)))
/* a record's value in a sound: the u16 at 20 + 2 x its slot (record + 4), the value in the
 * high byte, offset by the record's low (record + 8); as stock's setter 0x40037b74 stores it
 * (its values object at sound + 6: SAMP, slot 43, at sound + 0x6a, seen in the emulator) */
#define SOUND_VALUE(snd, id) ((int)(*(volatile u16 *)((snd) + 20u + 2u * (u32)RECORD(id)[1]) >> 8) - (RECORD(id)[2] >> 8))
#define KEYNOTES ((u32 (*)(u32, u32 *, u32))0x40034460u)   /* KEYBOARD: a trig key's notes */
#define SLMAX 64

#define IT_KEY 0
#define IT_KNOB 1
#define IT_DROP 0xFF
#define F_PRESS 0x01
#define F_RELEASE 0x10
enum { K_YES = 10, K_UP = 11, K_NO = 12, K_LEFT = 13, K_DOWN = 14, K_RIGHT = 15, K_FUNC = 17 };

extern u32 smp_slot_frames(int k, int *i16);
extern int smp_analyse(int k);
extern int smp_analysis(int *pct);
extern const u8 *smp_hires(void);
extern int smp_onsets(u32 *out, int most);
extern int smp_slices_get(int k, u32 *t);
extern int smp_slices_set(int k, const u32 *t, int n);
extern int smp_area_ok(void);

enum { S_OFF, S_MENU, S_GRID, S_WAIT, S_EDIT, S_ALLOC };   /* v0.25: ALLOC, GRID's ALLOCATE SLICE */
int slc_state __attribute__((section(".data"))) = S_OFF;
int slc_page_seen __attribute__((section(".data"))) = 0;   /* smp_page.c: 1 a SLICE page is up, 2 GRID's */
static int menu_sel __attribute__((section(".data"))) = 0;
int slc_stock_asked __attribute__((section(".data"), aligned(4))) = 0;   /* v0.29: FUNC + a key since the last YES/NO */
#define MENU_N 5                                /* v0.29: and CLEAR SLICE GRID (owner) */
int slc_grid_n __attribute__((section(".data"))) = 16;
static int grid_tr __attribute__((section(".data"))) = 0;
static int slot __attribute__((section(".data"))) = -1;
u32 slc_nfr __attribute__((section(".data"))) = 0;
static int wait_for __attribute__((section(".data"))) = 0;   /* S_GRID or S_EDIT: what the analysis is for */
static int func __attribute__((section(".data"))) = 0;
static const char *msg __attribute__((section(".data"))) = 0;
static u32 msg_at __attribute__((section(".data"))) = 0;
/* the editor */
u32 slc_sl[3 * SLMAX] __attribute__((section(".data")));
int slc_ns __attribute__((section(".data"))) = 0;
int slc_cur __attribute__((section(".data"))) = 0;
static int zoom __attribute__((section(".data"))) = 0;      /* 0..5: the view is frames >> zoom */
static int vzoom __attribute__((section(".data"))) = 0;     /* 0..3: the height x 1, 2, 4, 8 */
static u32 view0 __attribute__((section(".data"))) = 0;     /* the view's first frame */
static int dirty __attribute__((section(".data"))) = 0;
static int pv_on __attribute__((section(".data"))) = 0;      /* FUNC + YES's preview playing */
static u32 pv_at __attribute__((section(".data"))) = 0;      /* v0.30: FRAMES when it started */
static int pv_loop __attribute__((section(".data"))) = 0;    /* v0.30: D: 0 once, 1 looping */

int slc_visible(void)
{
    return slc_state != S_OFF || (msg && FRAMES - msg_at < 2250u);
}

int slc_busy(void)                              /* a note is up (it goes after 1.5 s) */
{
    return msg && FRAMES - msg_at < 2250u;
}

static void note(const char *m)
{
    msg = m;
    msg_at = FRAMES;
}

static int track_slot(void)                     /* the active track's sample, if it is on SLICE */
{
    u32 t = ACTIVE_TRACK;
    if (!KIT || t > 15)
        return -2;
    volatile u8 *s = (volatile u8 *)SOUND(t);
    if ((signed char)s[0xDE] != SLICE_TYPE)
        return -2;
    return SOUND_VALUE(SOUND(t), SMP_SAMP_ID) - 1;   /* SAMP 0 is OFF */
}

/* -- drawing --------------------------------------------------------------------------- */

static void on(void *c, int x, int y) { if (x >= 0 && x < 128 && y >= 0 && y < 64) SET_PIXEL(c, x, y, 1); }
static void off(void *c, int x, int y) { if (x >= 0 && x < 128 && y >= 0 && y < 64) SET_PIXEL(c, x, y, 0); }
static void hline(void *c, int x0, int x1, int y, int dot) { for (int x = x0; x <= x1; x++) if (!dot || !((x - x0) & 1)) on(c, x, y); }
static void vline(void *c, int x, int y0, int y1, int dot) { for (int y = y0; y <= y1; y++) if (!dot || !((y - y0) & 1)) on(c, x, y); }
static void clear(void *c, int x0, int y0, int x1, int y1) { for (int y = y0; y <= y1; y++) for (int x = x0; x <= x1; x++) off(c, x, y); }
static void box(void *c, int x0, int y0, int x1, int y1)
{
    hline(c, x0 + 1, x1 - 1, y0, 0); hline(c, x0 + 1, x1 - 1, y1, 0);
    vline(c, x0, y0 + 1, y1 - 1, 0); vline(c, x1, y0 + 1, y1 - 1, 0);
}

static void popup(void *c, int x0, int y0, int x1, int y1)   /* a framed box over the page */
{
    clear(c, x0 - 1, y0 - 1, x1 + 1, y1 + 1);
    box(c, x0, y0, x1, y1);
}

static void secs(void *c, int x, int y, u32 f)
{
    u32 ms = f / 48u;
    LABEL(c, x, y, "%d.%d%dS", (int)(ms / 1000u), (int)(ms / 100u % 10u), (int)(ms / 10u % 10u));
}

/* -- v0.25: slices to the placed trigs, as the DT2's CREATE LINEAR / RANDOM LOCKS --------- */
/* The stock's own lock calls on the active track (the knob-and-held-trig path's: its
 * parameter set's vtable at 0x401db7fc, +0x40, +0x44, +0x48): a lock's value is the raw
 * value << 8, as setValue's; GET answers -1 for none. A track's trigs: its pattern track
 * (0x4003b2ea(0x4003efa8(owner), track)), its length (0x4004f896) and whether a step holds
 * a note trig (0x4004f0f4: a trig, and not a lock trig). Found in the emulator: a held
 * [TRIG] and a turned knob in GRID RECORDING reach 0x4003ceee through these. */
#define LOCK_GET ((int (*)(u32, u32, u32))0x40037C52u)            /* (this, id, step) */
#define LOCK_SET ((u32 (*)(u32, u32, u32, u32))0x40037CB6u)       /* (this, id, value << 8, step) */
#define LOCK_CLEAR ((u32 (*)(u32, u32, u32))0x40037D22u)          /* (this, id, step) */
#define UI_OWNER ((u32 (*)(void))0x4018A97Au)
#define PATTERN_OF ((u32 (*)(u32))0x4003EFA8u)
#define PTRACK ((u32 (*)(u32, u32))0x4003B2EAu)
#define PTRACK_LEN ((int (*)(u32))0x4004F896u)
#define PTRACK_NOTE ((u32 (*)(u32, u32))0x4004F0F4u)
#define GRID_TYPE 12
#define STEPS 128
static short lk_old[STEPS] __attribute__((section(".data")));       /* the SLICE locks before */
static int lk_kept __attribute__((section(".data"))) = 0;            /* lk_old holds them */
static u32 lk_rand __attribute__((section(".data"))) = 0x2545F491u;
int slc_alloc_n __attribute__((section(".data"))) = 0;               /* the trigs it locked */

static u32 ptrack(void)
{
    u32 owner = UI_OWNER();
    if (!owner || ACTIVE_TRACK > 15)
        return 0;
    u32 pat = PATTERN_OF(owner);
    return pat ? PTRACK(pat, ACTIVE_TRACK) : 0;
}

static int track_slices(void)                    /* the active track's slices: GRID's count, SLICE's own */
{
    u32 t = ACTIVE_TRACK;
    if (!KIT || t > 15)
        return 0;
    volatile u8 *s = (volatile u8 *)SOUND(t);
    if ((signed char)s[0xDE] == GRID_TYPE) {
        int gi = SOUND_VALUE(SOUND(t), SMP_GRID_ID) / 24;
        return smp_grids[gi > 4 ? 4 : gi];
    }
    int k = track_slot();
    if (k < 0)
        return 0;
    static u32 t3[3 * SLMAX] __attribute__((section(".data")));
    return smp_slices_get(k, t3);
}

/* RANDOM 0: slice 1, 2, 3 .. on the note trigs in order (wrapping round the slices);
 * 1: a slice at random each. -> the trigs locked */
static int alloc_locks(int random)
{
    u32 tr = ptrack();
    int n = track_slices();
    if (!tr || n <= 0)
        return 0;
    if (n > 63)
        n = 63;                                 /* SLICE's top: slice 63 */
    int len = PTRACK_LEN(tr);
    if (len > STEPS)
        len = STEPS;
    if (!lk_kept) {
        for (int k = 0; k < STEPS; k++)
            lk_old[k] = (short)(k < len ? LOCK_GET(0, SMP_SLICE_ID, (u32)k) : -1);
        lk_kept = 1;
    }
    int j = 0;
    lk_rand ^= FRAMES;
    for (int k = 0; k < len; k++) {
        if (!(PTRACK_NOTE(tr, (u32)k) & 0xFF))
            continue;
        int sl;
        if (random) {
            lk_rand ^= lk_rand << 13; lk_rand ^= lk_rand >> 17; lk_rand ^= lk_rand << 5;
            sl = (int)(lk_rand % (u32)n) + 1;
        } else
            sl = j % n + 1;
        LOCK_SET(0, SMP_SLICE_ID, (u32)(2 * sl) << 8, (u32)k);
        j++;
    }
    slc_alloc_n = j;
    return j;
}

static void alloc_cancel(void)                  /* NO: the locks as they were */
{
    if (!lk_kept)
        return;
    for (int k = 0; k < STEPS; k++) {
        int v = lk_old[k];
        if (v >= 0)
            LOCK_SET(0, SMP_SLICE_ID, (u32)v, (u32)k);
        else if (LOCK_GET(0, SMP_SLICE_ID, (u32)k) >= 0)
            LOCK_CLEAR(0, SMP_SLICE_ID, (u32)k);
    }
    lk_kept = 0;
}

static void menu_draw(void *c)
{
    popup(c, 12, 1, 115, 61);
    static const char *items[MENU_N] = {"EDIT SLICE POINTS", "CREATE SLICE GRID", "CREATE LINEAR LOCKS",
                                        "CREATE RANDOM LOCKS", "CLEAR SLICE GRID"};
    for (int k = 0; k < MENU_N; k++) {
        int y = 51 - 9 * k;
        if (k == menu_sel)
            box(c, 15, y - 2, 112, y + 6);
        LABEL(c, 64, y, "%s", items[k]);
    }
    LABEL(c, 64, 4, "%s", "YES:OPEN  NO:CLOSE");
}

static void alloc_draw(void *c)                 /* GRID's, as the DT2 draws it */
{
    popup(c, 10, 12, 117, 54);
    static const char *items[2] = {"CREATE LINEAR LOCKS", "CREATE RANDOM LOCKS"};
    for (int k = 0; k < 2; k++) {
        int y = 43 - 10 * k;
        if (k == menu_sel)
            box(c, 13, y - 2, 114, y + 6);
        LABEL(c, 64, y, "%s", items[k]);
    }
    LABEL(c, 64, 17, "%s", "NO: CANCEL LOCKS");
}

static void grid_draw(void *c)
{
    popup(c, 10, 8, 117, 56);
    LABEL(c, 64, 47, "%s", "CREATE SLICE GRID");
    LABEL(c, 38, 37, "%s", "SLICES");
    LABEL(c, 38, 27, "%d", slc_grid_n);
    LABEL(c, 38, 19, "%s", "(E)");
    LABEL(c, 90, 37, "%s", "TR.DET");
    LABEL(c, 90, 27, "%s", grid_tr ? "ON" : "OFF");
    LABEL(c, 90, 19, "%s", "(H)");
    LABEL(c, 64, 10, "%s", "Y:CONFIRM  N:CANCEL");
}

static void wait_draw(void *c)
{
    int pct = 0;
    smp_analysis(&pct);
    popup(c, 20, 20, 107, 44);
    LABEL(c, 64, 34, "%s", "READING THE SAMPLE");
    LABEL(c, 64, 25, "%d%%", pct > 100 ? 100 : pct);
}

static u32 view_n(void)
{
    u32 v = slc_nfr >> zoom;
    return v < 128u ? (slc_nfr < 128u ? slc_nfr : 128u) : v;
}

static int fx(u32 f)                            /* a frame's column in the view, or -1 */
{
    u32 v = view_n();
    if (f < view0 || f > view0 + v)
        return -1;
    return 1 + (int)((u32)((f - view0) >> 4) * 125u / ((v >> 4) + 1u));
}

static void edit_draw(void *c)
{
    clear(c, 0, 0, 127, 63);
    /* the top: < SLICE 01/08 > and the slice's length; LOOP on the right */
    LABEL(c, 34, 57, "< SLICE %d%d/%d%d >", (slc_cur + 1) / 10, (slc_cur + 1) % 10, slc_ns / 10, slc_ns % 10);
    if (slc_ns)
        secs(c, 84, 57, slc_sl[3 * slc_cur + 1] - slc_sl[3 * slc_cur]);
    /* v0.30: D is the preview's play mode, drawn as the DT2's PLAY icons (owner): an arrow
     * to a bar, once; an arrow round a loop, looping */
    hline(c, 106, 116, 59, 0);
    on(c, 115, 58); on(c, 115, 60); on(c, 114, 57); on(c, 114, 61);
    if (pv_loop) {
        vline(c, 106, 56, 59, 0);
        hline(c, 106, 120, 56, 0);
        vline(c, 120, 56, 59, 0);
        hline(c, 117, 120, 59, 0);
    } else
        vline(c, 118, 56, 62, 0);
    hline(c, 0, 127, 54, 0);
    /* the waveform */
    const u8 *hr = smp_hires();
    int yc = 31, h = 20;
    u32 v = view_n();
    for (int x = 1; x <= 126; x++) {
        u32 f0 = view0 + (u32)(x - 1) * (v / 126u);
        u32 col = slc_nfr ? (f0 >> 6) * 1024u / ((slc_nfr >> 6) + 1u) : 0;
        int a = (col < 1024u ? hr[col] : 0) * h << vzoom;
        a /= 255;
        if (a > h) a = h;
        vline(c, x, yc - a, yc + a, 0);
    }
    /* the slices: each start a line with its number's box at the top; the picked one's
     * span lit, start and end solid; its loop point dotted */
    for (int k = 0; k < slc_ns; k++) {
        int xs = fx(slc_sl[3 * k]);
        if (xs >= 0) {
            vline(c, xs, yc - h - 1, yc + h + 1, k != slc_cur);
            if (k == slc_cur) {
                for (int yy = yc + h - 4; yy <= yc + h + 1; yy++)
                    hline(c, xs, xs + 5, yy, 0);
            }
        }
    }
    if (slc_ns) {
        int xe = fx(slc_sl[3 * slc_cur + 1]), xl = fx(slc_sl[3 * slc_cur + 2]);
        if (xe >= 0) {
            vline(c, xe, yc - h - 1, yc + h + 1, 0);
            hline(c, xe - 3, xe, yc - h - 1, 0);
        }
        if (xl >= 0)
            vline(c, xl, yc - h, yc + h, 1);
    }
    /* v0.30: where the preview is (owner: the track's playhead, drawn here before, drifted
     * with whatever the track was doing): the frames since it started, 32 a 1.5 kHz tick,
     * from the slice's start; wrapping round the slice when it loops, gone at its end */
    if (pv_on && slc_ns) {
        u32 *sl = &slc_sl[3 * slc_cur], len = sl[1] > sl[0] ? sl[1] - sl[0] : 1u;
        u32 run = (FRAMES - pv_at) * 32u;
        int xp = -1;
        if (pv_loop)
            run %= len;
        if (run < len)
            xp = fx(sl[0] + run);
        if (xp >= 2 && xp <= 125)
            for (int yy = yc - h - 1; yy <= yc + h + 1; yy++) {   /* cleared either side, so */
                off(c, xp - 1, yy);                              /* it reads over the wave */
                on(c, xp, yy);
                off(c, xp + 1, yy);
            }
    }
    hline(c, 0, 127, 9, 0);
    LABEL(c, 13, 1, "%s", "START");
    LABEL(c, 47, 1, "%s", "ZOOM");
    LABEL(c, 80, 1, "%s", "POS");
    LABEL(c, 113, 1, "%s", "END");
    if (msg && FRAMES - msg_at < 2250u) {
        popup(c, 24, 26, 103, 38);
        LABEL(c, 64, 29, "%s", msg);
    }
}

void slc_draw(void *c)
{
    if (slc_state == S_MENU)
        menu_draw(c);
    else if (slc_state == S_GRID)
        grid_draw(c);
    else if (slc_state == S_WAIT)
        wait_draw(c);
    else if (slc_state == S_EDIT)
        edit_draw(c);
    else if (slc_state == S_ALLOC)
        alloc_draw(c);
    if (slc_state != S_EDIT && msg && FRAMES - msg_at < 2250u) {
        popup(c, 20, 26, 107, 38);
        LABEL(c, 64, 29, "%s", msg);
    }
}

/* -- the work ---------------------------------------------------------------------------- */

static void from_starts(const u32 *st, int n)    /* each to the next start, the last to the end */
{
    slc_ns = n > SLMAX ? SLMAX : n;
    for (int k = 0; k < slc_ns; k++) {
        slc_sl[3 * k] = st[k];
        slc_sl[3 * k + 1] = k + 1 < slc_ns ? st[k + 1] : slc_nfr;
        slc_sl[3 * k + 2] = st[k];
    }
}

static void make_grid(void)
{
    u32 st[SLMAX];
    int n = slc_grid_n;
    if (grid_tr) {
        n = smp_onsets(st, slc_grid_n);
        if (n < 1) {
            st[0] = 0;
            n = 1;
        }
    } else {
        for (int k = 0; k < n; k++)
            st[k] = (u32)((slc_nfr / (u32)n) * (u32)k);
    }
    from_starts(st, n);
    if (smp_slices_set(slot, slc_sl, slc_ns) == 0)
        note(grid_tr ? "SLICED AT HITS" : "GRID MADE");
    else
        note("COULD NOT SAVE");
}

static void edit_open(void)
{
    slc_ns = smp_slices_get(slot, slc_sl);
    slc_cur = 0;
    zoom = 0;
    vzoom = 0;
    view0 = 0;
    dirty = 0;
    if (!slc_ns) {                                  /* none yet: one slice, the whole sample */
        u32 z = 0;
        from_starts(&z, 1);
        dirty = 1;
    }
    slc_state = S_EDIT;
}

static void edit_close(void)
{
    if (dirty && smp_slices_set(slot, slc_sl, slc_ns) != 0)
        note("COULD NOT SAVE");
    slc_state = S_OFF;
}

static void follow_view(void)                   /* the picked slice's start in view */
{
    u32 v = view_n();
    u32 s = slc_sl[3 * slc_cur];
    if (s < view0 || s >= view0 + v)
        view0 = s > v / 4u ? s - v / 4u : 0u;
    if (view0 + v > slc_nfr)
        view0 = slc_nfr > v ? slc_nfr - v : 0u;
}

static void start_analysis(int then)
{
    int i16;
    slc_nfr = smp_slot_frames(slot, &i16);
    if (!slc_nfr || !i16) {
        note("NO SAMPLE");
        slc_state = S_OFF;
        return;
    }
    if (smp_analyse(slot) != 0) {
        note("CANNOT READ IT");
        slc_state = S_OFF;
        return;
    }
    wait_for = then;
    slc_state = S_WAIT;
}

/* from the UI loop (page.c's wr_poll), every pass */
void slc_poll(void)
{
    if (slc_state != S_WAIT)
        return;
    int st = smp_analysis(0);
    if (st == 2) {
        if (wait_for == S_GRID) {
            make_grid();
            edit_open();                        /* v0.26: on to the editor, as the DT2's */
        } else {
            edit_open();
        }
    } else if (st < 0) {
        note("CANNOT READ IT");
        slc_state = S_OFF;
    }
}

static u32 step_of(void)                        /* a detent: a 128th of the view */
{
    /* v0.27: the same with FUNC held (owner: FUNC is held for FUNC + YES's preview between
     * every small move; v0.23..v0.26 moved a frame a detent with FUNC, which crawled) */
    u32 s = view_n() / 128u;
    return s ? s : 1u;
}

static void move(u32 *v, int d, u32 lo, u32 hi)
{
    u32 s = step_of() * (u32)(d < 0 ? -d : d);
    if (d < 0)
        *v = *v > lo + s ? *v - s : lo;
    else
        *v = *v + s < hi ? *v + s : hi;
}

static void edit_knob(int idx, int d)
{
    if (!slc_ns && idx != 6 && idx != 7)
        return;
    u32 *s = &slc_sl[3 * slc_cur], *e = s + 1, *l = s + 2;
    switch (idx) {
    case 4:                                                       /* D: the preview's mode (v0.30) */
        pv_loop = d > 0;
        (void)l;
        return;
    case 5: move(s, d, 0, *e - 1u); if (*l < *s) *l = *s; break;  /* E START */
    case 6:                                                       /* F ZOOM; FUNC: the height */
        if (func)
            vzoom = vzoom + d < 0 ? 0 : vzoom + d > 3 ? 3 : vzoom + d;
        else
            zoom = zoom + d < 0 ? 0 : zoom + d > 5 ? 5 : zoom + d;
        follow_view();
        return;
    case 7: {                                                     /* G POS */
        if (func && slc_ns) {                   /* v0.26, FUNC + G: the whole slice moves, */
            u32 len = *e - *s, lo = *l - *s;    /* its length kept (the DT2's) */
            u32 st3 = view_n() / 128u ? view_n() / 128u : 1u;   /* (not FUNC's fine step) */
            u32 a = st3 * (u32)(d < 0 ? -d : d);
            if (d < 0)
                *s = *s > a ? *s - a : 0u;
            else
                *s = *s + a + len <= slc_nfr ? *s + a : slc_nfr - len;
            *e = *s + len;
            *l = *s + lo;
            follow_view();
            dirty = 1;
            return;
        }
        u32 v = view_n(), m = slc_nfr > v ? slc_nfr - v : 0u, st2 = v / 16u ? v / 16u : 1u;
        u32 a = st2 * (u32)(d < 0 ? -d : d);
        view0 = d < 0 ? (view0 > a ? view0 - a : 0u) : (view0 + a < m ? view0 + a : m);
        return;
    }
    case 8: move(e, d, *s + 1u, slc_nfr); if (*l >= *e) *l = *e - 1u; break;   /* H END */
    default: return;
    }
    dirty = 1;
}

/* v0.26: FUNC + YES plays the current slice while held (the recorder's preview, after the
 * engine's mix: rec.c's TRIM preview), as the DT2's slice editor previews it */
#define CMD_PREVIEW 9
extern u32 smp_command(u32 cmd, u32 src, u32 chan, u32 thres, u32 dest_frames);
/* (pv_on, pv_at, pv_loop: with the editor's state, above) */

static void slice_preview(int on)
{
    if (on && slc_ns && slot >= 0) {
        u32 *sl = &slc_sl[3 * slc_cur];
        smp_command(CMD_PREVIEW, (u32)slot, sl[0], sl[1], (u32)pv_loop);   /* v0.30: and its mode */
        pv_on = 1;
        pv_at = FRAMES;
    } else if (pv_on) {
        smp_command(CMD_PREVIEW, (u32)(slot < 0 ? 0 : slot), 0, 0, 0);
        pv_on = 0;
    }
}

/* the slice editor's keys, as the DT2's (its manual, A.2.5 USING THE SLICE EDITOR):
 * LEFT / RIGHT the previous / next slice; FUNC + RIGHT splits the current slice in two (the
 * others as they were); FUNC + LEFT removes it (the audio stays); FUNC + YES previews it
 * while held; YES or NO closes the editor. v0.25's FUNC + YES added a slice at the view's
 * middle, which could land out of sight, and FUNC + NO removed one. */
static void edit_key(u32 code, int chord)
{
    int fn = chord || func;
    if (code == K_RIGHT && fn) {                 /* split the current slice in two */
        if (slc_ns == 0 && slc_nfr > 1u) {        /* none yet: the whole sample is one */
            slc_sl[0] = 0;
            slc_sl[1] = slc_nfr;
            slc_sl[2] = 0;
            slc_ns = 1;
            slc_cur = 0;
        }
        if (slc_ns > 0 && slc_ns < SLMAX) {
            u32 *c = &slc_sl[3 * slc_cur];
            u32 st = c[0], en = c[1];
            if (en > st + 1u) {
                u32 mid = st + (en - st) / 2u;
                for (int k = slc_ns; k > slc_cur + 1; k--)     /* room after the current */
                    for (int w = 0; w < 3; w++)
                        slc_sl[3 * k + w] = slc_sl[3 * (k - 1) + w];
                c[1] = mid;
                if (c[2] >= mid)
                    c[2] = st;
                slc_sl[3 * (slc_cur + 1)] = mid;
                slc_sl[3 * (slc_cur + 1) + 1] = en;
                slc_sl[3 * (slc_cur + 1) + 2] = mid;
                slc_ns++;
                follow_view();
            }
        }
        dirty = 1;
    } else if (code == K_LEFT && fn) {           /* remove the current slice */
        if (slc_ns > 0) {
            for (int k = slc_cur; k + 1 < slc_ns; k++)
                for (int w = 0; w < 3; w++)
                    slc_sl[3 * k + w] = slc_sl[3 * (k + 1) + w];
            slc_ns--;
            if (slc_cur >= slc_ns)
                slc_cur = slc_ns > 0 ? slc_ns - 1 : 0;
            dirty = 1;
        }
    } else if (code == K_LEFT && slc_cur > 0) {
        slc_cur--;
        follow_view();
    } else if (code == K_RIGHT && slc_cur + 1 < slc_ns) {
        slc_cur++;
        follow_view();
    } else if (code == K_YES && fn) {
        slice_preview(1);
    } else if (code == K_YES || code == K_NO) {
        slice_preview(0);
        edit_close();
    }
}

/* the UI queue (rec.c's smp_ui_pop asks here first): -> 1 if the item was ours */
int slc_pop(u8 *it)
{
    u32 code = (u32)it[4] << 24 | (u32)it[5] << 16 | (u32)it[6] << 8 | it[7];
    u32 flags = (u32)it[8] << 24 | (u32)it[9] << 16 | (u32)it[10] << 8 | it[11];
    int press = it[0] == IT_KEY && (flags & F_PRESS) && !(flags & F_RELEASE);
    extern int smp_func_held;                   /* v0.25: rec.c keeps FUNC for all (the key */
    func = smp_func_held;                       /* items' bit 1 is not FUNC: see there) */
    if (it[0] == IT_KEY && code == K_FUNC)
        return 0;                               /* FUNC goes on to stock */
    if (slc_state == S_OFF) {
        extern int smp_lst_open, smp_fb_open;   /* v0.26: YES with the sample list or the */
        if (smp_lst_open || smp_fb_open)        /* browser up is theirs (keep the sample), */
            return 0;                           /* not the slice menus' */
        /* v0.29: FUNC + a key may put up a stock question over the page (FUNC + SETTINGS:
         * "SAVE ALL PATTERNS AND PROJ SETTINGS? Y/N", owner's photo): its YES or NO is the
         * question's, not the slice menus' */
        /* v0.33: only FUNC + a page or menu key (1..8: TRIG..MOD, PRESET, SETTINGS) can put up
         * such a question; v0.29..v0.32 took any FUNC combo (FUNC + an arrow, a [TRIG], ...),
         * and the next YES on a SLICE track was swallowed (the owner: YES did nothing) */
        if (press && func && code >= 1 && code <= 8)
            slc_stock_asked = 1;
        if (press && (code == K_YES || code == K_NO) && slc_stock_asked && !func) {
            slc_stock_asked = 0;
            return 0;
        }
        /* v0.30: YES with a [TRIG] held (TRIG + YES: stock's sound preview) is stock's. v0.33:
         * the [TRIG] keys only (25..40), not any key: MACHINE SEL (FUNC + SRC) takes its
         * keys' releases itself, so SRC stayed "held" and every later YES was stock's until
         * SRC was pressed again (the owner's dead SLICE and GRID menus; held_lo 0x404 in the
         * emulator after it) */
        extern int smp_trig_held(void);
        if (press && code == K_YES && smp_trig_held())
            return 0;
        /* YES on a SLICE track's page opens the menu */
        if (press && code == K_YES && slc_page_seen == 2 && !func) {   /* v0.25: GRID's ALLOCATE SLICE */
            menu_sel = 0;
            lk_kept = 0;
            slc_state = S_ALLOC;
            return 1;
        }
        if (press && code == K_YES && slc_page_seen == 1 && !func) {
            int k = track_slot();
            if (k == -2)
                return 0;
            slot = k;
            if (k < 0 || !smp_slot_frames(k, 0)) {
                note("NO SAMPLE ON SAMP");
                return 1;
            }
            if (!smp_area_ok()) {
                note("SLICE AREA IN USE");
                return 1;
            }
            menu_sel = 0;
            slc_state = S_MENU;
            return 1;
        }
        if (press && ((code >= 1 && code <= 8) || code == 16 || code == 23 || code == 24 || code == 50))
            slc_page_seen = 0;                  /* off the page: smp_page.c says when it is back */
        return 0;
    }
    if (slc_state == S_WAIT)
        return it[0] == IT_KEY || it[0] == IT_KNOB;   /* nothing while it reads */
    if (it[0] == IT_KNOB) {
        int d = (signed char)it[8];
        if (code < 1 || code > 9)
            return 0;
        if (slc_state == S_GRID) {
            if (code == 5)
                slc_grid_n = slc_grid_n + d < 2 ? 2 : slc_grid_n + d > 64 ? 64 : slc_grid_n + d;
            else if (code == 8)
                grid_tr = d > 0;
        } else if (slc_state == S_EDIT) {
            edit_knob((int)code, d);
        }
        return 1;
    }
    if (it[0] != IT_KEY)
        return 0;
    int ours = code == K_YES || code == K_NO || (code >= K_UP && code <= K_RIGHT) || (code >= 41 && code <= 48);
    if (!ours)
        return 0;
    if (!press) {
        if (code == K_YES && pv_on)             /* v0.26: the preview while held */
            slice_preview(0);
        return 1;
    }
    int chord = func;
    if (slc_state == S_ALLOC) {
        if (code == K_UP || code == K_DOWN)
            menu_sel ^= 1;
        else if (code == K_NO) {
            alloc_cancel();
            slc_state = S_OFF;
        } else if (code == K_YES) {
            int n = alloc_locks(menu_sel);
            if (!n)
                note("NO TRIGS TO LOCK");
            if (menu_sel == 0 || !n) {               /* LINEAR: done; RANDOM: again on YES */
                lk_kept = 0;
                slc_state = S_OFF;
            }
        } else if (code == K_LEFT) {                 /* kept, closed */
            lk_kept = 0;
            slc_state = S_OFF;
        }
    } else if (slc_state == S_MENU) {
        if (code == K_UP)
            menu_sel = (menu_sel + MENU_N - 1) % MENU_N;
        else if (code == K_DOWN)
            menu_sel = (menu_sel + 1) % MENU_N;
        else if (code == K_NO)
            slc_state = S_OFF;
        else if (code == K_YES && menu_sel == 0)
            start_analysis(S_EDIT);
        else if (code == K_YES && menu_sel == 1)
            slc_state = S_GRID;
        else if (code == K_YES && menu_sel == 4) {   /* v0.29: CLEAR SLICE GRID: none, it plays whole */
            note(smp_slices_set(slot, 0, 0) == 0 ? "SLICES CLEARED" : "NOTHING TO CLEAR");
            slc_state = S_OFF;
        } else if (code == K_YES) {                  /* v0.25: CREATE LINEAR / RANDOM LOCKS */
            lk_kept = 0;
            if (!alloc_locks(menu_sel == 3))
                note("NO TRIGS TO LOCK");
            lk_kept = 0;
            slc_state = S_OFF;
        }
    } else if (slc_state == S_GRID) {
        if (code == K_NO)
            slc_state = S_OFF;
        else if (code == K_YES) {
            if (grid_tr) {
                start_analysis(S_GRID);         /* the transients need the sample read */
            } else {
                int i16;
                slc_nfr = smp_slot_frames(slot, &i16);
                make_grid();
                start_analysis(S_EDIT);         /* v0.26: on to the editor (its waveform read), as the DT2's */
            }
        }
    } else if (slc_state == S_EDIT) {
        edit_key(code, chord);
    }
    return 1;
}

/* v0.23, the DT2's SLICES trig mode: in KEYBOARD mode, on a SLICE track whose SLCE is NOTE,
 * trig key K plays slice K + 1 (the note C1 + K, which SLCE's NOTE mode turns into slice K:
 * dnfw.sampler.program.slice_bounds), as one note. Everything else stock's: the call the
 * KeyboardView makes for a key's notes (0x40058be8, coldfire.py's KEYNOTES_SITE) comes here.
 * VEC is the stock vector (begin, end, capacity) of 32-bit notes; -> nonzero: notes given. */
/* v0.25: GRID too (its SLICE at NOTE), and more than 16 slices: KEYBOARD's octave (stock's,
 * [KEYBOARD] + [UP]/[DOWN], or [UP]/[DOWN] with U/D KEY MODE at KB OCT) moves the keys on
 * by 16 slices an octave, as the DT2's octave moves its notes on. The octave is read from
 * the note stock gives [TRIG 9] (the octave's lowest; KB_C0 at the middle octave). */
#define GRID_TYPE 12                            /* dnfw.sampler.machines.TYPE_OF["GRID"] */
#define KB_C0 60u
u32 slc_kb_c __attribute__((section(".data"))) = 0;
u32 slc_keynotes(u32 kbd, u32 *vec, u32 k)
{
    u32 t = ACTIVE_TRACK;
    if (KIT && t <= 15 && k < 16 && vec && vec[0] && vec[2] >= vec[0] + 4u) {
        volatile u8 *s = (volatile u8 *)SOUND(t);
        int ty = (signed char)s[0xDE];
        if ((ty == SLICE_TYPE || ty == GRID_TYPE) && SOUND_VALUE(SOUND(t), SMP_SLICE_ID) == 0) {
            /* v0.26: the slices in the order of the keys' notes, as the keyboard lays them
             * out (chromatic: its lit keys; a folded scale: all 16): the key with the
             * lowest note plays slice 1, the next slice 2 .., as the DT2's KEYBOARD with
             * SLICE at NOTE ("slices play from C1 upwards, wrapping after the last"). Each
             * octave up or down (KEYBOARD + UP/DOWN) moves them on by as many slices as the
             * keys play. v0.25 gave TRIG k slice k, so the unlit keys' slices could not be
             * played (and the lit ones' came out of order) */
            u32 buf[8], tv[3];
            int note[16], mine = -1;
            for (u32 j = 0; j < 16u; j++) {
                tv[0] = tv[1] = (u32)buf;
                tv[2] = (u32)(buf + 8);
                note[j] = KEYNOTES(kbd, tv, j) && tv[1] > tv[0] ? (int)buf[0] : -1;
            }
            mine = note[k];
            if (mine < 0)
                return 0;                       /* a key with no note: none */
            int rank = 0, per = 0;
            for (int j = 0; j < 16; j++) {      /* distinct notes: below the key's, and in all */
                if (note[j] < 0)
                    continue;
                int dup = 0;
                for (int i = 0; i < j; i++)
                    if (note[i] == note[j])
                        dup = 1;
                if (dup)
                    continue;
                per++;
                if (note[j] < mine)
                    rank++;
            }
            int bank = 0;                       /* the octave: TRIG 9's note against the middle C */
            if (note[8] >= 0) {
                bank = (note[8] - (int)KB_C0) / 12;
                if (note[8] < (int)KB_C0 && ((int)KB_C0 - note[8]) % 12)
                    bank--;
            }
            slc_kb_c = (u32)mine;
            int idx = (rank + per * bank) % 64;
            if (idx < 0)
                idx += 64;
            *(u32 *)vec[0] = 24u + (u32)idx;    /* the DSP: (note - 24) mod the slices (v0.33: from C1) */
            vec[1] = vec[0] + 4u;
            return 1;
        }
    }
    return KEYNOTES(kbd, vec, k);
}
