/* v0.23: SLICE's own menus, as the Digitakt II's (its manual, 13.4 and the SLICE machine):
 *
 *   YES on a SLICE track's page   the SLICE menu: EDIT SLICE POINTS, CREATE SLICE GRID
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

enum { S_OFF, S_MENU, S_GRID, S_WAIT, S_EDIT };
int slc_state __attribute__((section(".data"))) = S_OFF;
int slc_page_seen __attribute__((section(".data"))) = 0;   /* smp_page.c: a SLICE page is up */
static int menu_sel __attribute__((section(".data"))) = 0;
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

static void menu_draw(void *c)
{
    popup(c, 14, 14, 113, 52);
    static const char *items[2] = {"EDIT SLICE POINTS", "CREATE SLICE GRID"};
    for (int k = 0; k < 2; k++) {
        int y = 41 - 12 * k;
        if (k == menu_sel)
            box(c, 17, y - 3, 110, y + 7);
        LABEL(c, 64, y, "%s", items[k]);
    }
    LABEL(c, 64, 18, "%s", "YES:OPEN  NO:CLOSE");
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
    LABEL(c, 115, 57, "%s", "LOOP");
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
    if (slc_state != S_EDIT && msg && FRAMES - msg_at < 2250u) {
        popup(c, 20, 26, 107, 38);
        LABEL(c, 64, 29, "%s", msg);
    }
}

/* -- the work ---------------------------------------------------------------------------- */

static void sort_slices(void)
{
    for (int i = 1; i < slc_ns; i++)
        for (int j = i; j > 0 && slc_sl[3 * j] < slc_sl[3 * (j - 1)]; j--)
            for (int w = 0; w < 3; w++) {
                u32 t = slc_sl[3 * j + w];
                slc_sl[3 * j + w] = slc_sl[3 * (j - 1) + w];
                slc_sl[3 * (j - 1) + w] = t;
            }
}

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
            slc_state = S_OFF;
        } else {
            edit_open();
        }
    } else if (st < 0) {
        note("CANNOT READ IT");
        slc_state = S_OFF;
    }
}

static u32 step_of(void)                        /* a detent: a 128th of the view (FUNC: a frame) */
{
    u32 s = view_n() / 128u;
    return func ? 1u : (s ? s : 1u);
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
    case 4: move(l, d, *s, *e - 1u); break;                      /* D LOOP */
    case 5: move(s, d, 0, *e - 1u); if (*l < *s) *l = *s; break;  /* E START */
    case 6:                                                       /* F ZOOM; FUNC: the height */
        if (func)
            vzoom = vzoom + d < 0 ? 0 : vzoom + d > 3 ? 3 : vzoom + d;
        else
            zoom = zoom + d < 0 ? 0 : zoom + d > 5 ? 5 : zoom + d;
        follow_view();
        return;
    case 7: {                                                     /* G POS */
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

static void edit_key(u32 code, int chord)
{
    if (code == K_LEFT && slc_cur > 0) {
        slc_cur--;
        follow_view();
    } else if (code == K_RIGHT && slc_cur + 1 < slc_ns) {
        slc_cur++;
        follow_view();
    } else if (code == K_YES && (chord || func) && slc_ns < SLMAX) {   /* a slice at the view's middle */
        u32 at = view0 + view_n() / 2u;
        if (at >= slc_nfr)
            at = slc_nfr - 1u;
        slc_sl[3 * slc_ns] = at;
        slc_sl[3 * slc_ns + 1] = slc_nfr;
        slc_sl[3 * slc_ns + 2] = at;
        slc_ns++;
        sort_slices();
        for (int k = 0; k < slc_ns; k++) {
            if (slc_sl[3 * k] == at)
                slc_cur = k;
            if (k + 1 < slc_ns && slc_sl[3 * k + 1] > slc_sl[3 * (k + 1)])
                slc_sl[3 * k + 1] = slc_sl[3 * (k + 1)];
        }
        dirty = 1;
    } else if (code == K_NO && (chord || func)) {                  /* the picked slice goes */
        if (slc_ns > 1) {
            for (int k = slc_cur; k + 1 < slc_ns; k++)
                for (int w = 0; w < 3; w++)
                    slc_sl[3 * k + w] = slc_sl[3 * (k + 1) + w];
            slc_ns--;
            if (slc_cur >= slc_ns)
                slc_cur = slc_ns - 1;
            dirty = 1;
        }
    } else if (code == K_NO) {
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
        /* YES on a SLICE track's page opens the menu */
        if (press && code == K_YES && slc_page_seen && !func) {
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
    if (!press)
        return 1;
    int chord = func;
    if (slc_state == S_MENU) {
        if (code == K_UP || code == K_DOWN)
            menu_sel ^= 1;
        else if (code == K_NO)
            slc_state = S_OFF;
        else if (code == K_YES && menu_sel == 0)
            start_analysis(S_EDIT);
        else if (code == K_YES)
            slc_state = S_GRID;
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
                slc_state = S_OFF;
            }
        }
    } else if (slc_state == S_EDIT) {
        edit_key(code, chord);
    }
    return 1;
}

/* v0.23, the DT2's SLICES trig mode: in KEYBOARD mode, on a SLICE track whose SLCE is NOTE,
 * trig key K plays slice K + 1 (the note C0 + K, which SLCE's NOTE mode turns into slice K:
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
            u32 buf[8], tv[3] = {(u32)buf, (u32)buf, (u32)(buf + 8)};
            int bank = 0;
            if (KEYNOTES(kbd, tv, 8u) && tv[1] > tv[0]) {
                slc_kb_c = buf[0];
                bank = ((int)buf[0] - (int)KB_C0) / 12;
                if ((int)buf[0] < (int)KB_C0 && ((int)KB_C0 - (int)buf[0]) % 12)
                    bank--;
            }
            int idx = (16 * bank + (int)k) % 64;
            if (idx < 0)
                idx += 64;
            *(u32 *)vec[0] = 12u + (u32)idx;
            vec[1] = vec[0] + 4u;
            return 1;
        }
    }
    return KEYNOTES(kbd, vec, k);
}
