/* The SYN pages of our machines on the ColdFire: PERC (type 5, docs/perc.md),
 * RESONATOR (6) and CZ (7), and the TYPE cell of PING's, SHFT's and GRAN's filter pages.
 *
 * The layout is Tonverk's Wavefinder page (User Manual OS 1.4.1, p. 94), on a screen of
 * the same size, drawn with our own widgets: encoders A..D are a strip above a picture,
 * E..H a strip below it, and each control is its label with a small indicator, not a
 * dial. (Waverider, type 5 until v0.11, drew its wave there; PERC draws its machine's
 * name.) `docs/waverider-m7-pages.md`, "M8.1".
 *
 * Entered from `wr_grid` (dnfw.waverider.pages) in place of the stock grid
 * `0x40017428(view, canvas)`, on one of our tracks only. It keeps the grid's own
 * tail: the level meter on the left (`view->vtable[184]`) and the page dots on
 * the right (`0x4006598a`). The encoders, the value line in the header, p-locks
 * and SAVE/LOAD are untouched: they go through the page descriptor's record ids,
 * which stay WaveTone's.
 *
 * Coordinates are the canvas's own: 128 x 64, y counting up from the bottom
 * edge (the SYN page's blits place cell row 0 at y 34..51). The header takes
 * the top ten rows, the level meter and track box the left 18 columns.
 *
 * One subject: drawing the page. What the controls are is `wr_gen.h`, generated
 * from dnfw.waverider.pages and dnfw.ping.pages.
 */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned char u8;

#define GET_VALUE  ((int (*)(void *, u32, u8 *))0x4006538E)   /* (view, id, &flag) */
#define SET_PIXEL  ((void (*)(void *, int, int, int))0x40113B90)  /* (canvas, x, y, on) */
#define TEXT       ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545C)
#define PAGE_COUNT ((int (*)(void *))0x400173CA)
#define PAGE_DOTS  ((void (*)(void *, void *, int, int, int))0x4006598A)
#define IS_DIRTY   ((int (*)(void *))0x4011D2F4u)               /* screen: a redraw due? */
#define SET_DIRTY  ((void (*)(void *))0x4011D2FEu)              /* screen: ask for one */
#define FRAMES_NOW (*(volatile u32 *)0x4058E8D4u)               /* 1,500 a second */
#define REC_REDRAW 60u                                          /* the recorder's: 25 a second */
#define FONT       0x44507ED8u                                  /* the grid's label font */
#define CENTRED    2                                            /* TEXT flag: x is the centre */

/* a parameter record: +8 min, +12 max, +16 default (TUN1: 0x400, 0x7c00, 0x4000) */
#define RECORD(id) ((const int *)(0x401F7F94u + 60u * (id)))

/* W2: the record's name pointers, as every stock reader takes them (0x401f7f94 +
 * 60 id, then +0x28 the long name, +0x30 the short one: getLongName 0x400365c8,
 * getShortName 0x400372da, and the eleven places that read +0x30 directly, among
 * them the LFO destination list's row label 0x40105b72) */
#define NAME_LONG(id)  (*(const char **)(0x401F7F94u + 60u * (id) + 0x28u))
#define NAME_SHORT(id) (*(const char **)(0x401F7F94u + 60u * (id) + 0x30u))
#define KIT_POINTER (*(unsigned char *volatile *)0x800052A0u)
#define UI_TRACK    (*(volatile u8 *)0x42431A6Cu)

/* the strips: four columns of 25 across x 22..121 */
#define COL0  22
#define COLW  25
#define TOP_LABEL_Y 46
#define TOP_BAR_Y   43
#define BOT_BAR_Y   9
#define BOT_LABEL_Y 1
#define BAR_HALF    10

/* the wave, and the position bar under it */
#define WAVE_X  24
#define WAVE_CY 28
#define WAVE_AMP 11
#define POS_Y   15
#define CURSOR_Y (POS_Y - 2)    /* the LFO's position cursor: under the bar (owner) */
#define MARK    3

#define WR_WIDTH 96              /* the picture's width, from WAVE_X */

/* is the active track one of ours? (pages.is_wr's test: the active track's sound,
 * [0x800052a0] + 52 + 1163 t, has machine type 5..12 at +0xDE) -> 1 PERC,
 * 2 RESONATOR, 3 CZ, 4..8 the sample machines (types 8..12, docs/sampler.md), 0 none */
static int wr_active(void)
{
    u8 t = UI_TRACK;
    unsigned char *kit = KIT_POINTER;
    if (t > 15 || !kit)
        return 0;
    signed char m = (signed char)kit[52u + 1163u * t + 0xDEu];
    return m >= 5 && m <= WR_TYPES_LAST ? m - 4 : 0;   /* v0.19: 13 SLICE; v0.26: the Monomachine's 14.. */
}

/* v0.22: the LFOs' destination list (0x4003951e) asks each of the track's 101 slots'
 * record for its modulation mask (0x400dc30e) and lists it if the LFO's bit is set. On a
 * track of ours, a WaveTone record our machine does not use (its name made "-" by
 * wr_names) answers 0, and is left out of the list. Every other record, and every other
 * track, as stock. */
#define STOCK_MASK ((u32 (*)(u32))0x400DC30Eu)
u32 wr_lfo_mask(u32 rec)
{
    if (rec >= 238u && rec <= 262u && wr_active()) {
        const char *sh = NAME_SHORT(rec);
        if (sh && sh[0] == '-' && sh[1] == 0)
            return 0;
    }
    return STOCK_MASK(rec);
}

/* TYPE's value (0..0x7f00) -> the machine, as the DSP reads it (dnfw.perc.program) */
static int perc_of(int v)
{
    v >>= 8;
    if (v < 0) v = 0;
    if (v > 127) v = 127;
    return (v * PERC_N) >> 7;
}

/* the machine the PERC page last read from TYPE (GET_VALUE, as the page draws it). v0.11
 * read the sound's target array instead, and on the instrument that did not follow TYPE:
 * every machine kept one set of names. */
static int perc_seen __attribute__((section(".data"))) = 0;

static int perc_type(void)
{
    return perc_seen;
}

/* While the active track is one of ours, WaveTone's records carry our names, so the LFO
 * and modulation destination lists, the LFO page's DEST field, the header's parameter
 * line and our own page all say what the record does on this machine; as soon as it is
 * not, the stock pointers go back. On a PERC track the parameters' names follow TYPE
 * (perc_short / perc_long). Only the two name pointers of the records in wr_named_ids are
 * written, and only on a change. The table is in RAM, and ACR0 (0x4007e020, set at
 * 0x40000564) leaves 0x40000000-0x47ffffff writable: its W bit is clear. */
static const char *stock_long[WR_NAMED] __attribute__((section(".data")));
static const char *stock_short[WR_NAMED] __attribute__((section(".data")));
static int names_on __attribute__((section(".data"))) = -1;

static void wr_names(void)
{
    int on = wr_active();
    int key = on == 1 ? 16 + perc_type() : on;   /* PERC: one set of names a machine */
    if (key == names_on)
        return;
    extern void smp_formats(int kind);
    smp_formats(on);                            /* v0.15: the sample machines' value text */
    for (int k = 0; k < WR_NAMED; k++) {
        u32 id = wr_named_ids[k];
        if (names_on < 0) {                     /* the first call: keep the stock pointers */
            stock_long[k] = NAME_LONG(id);
            stock_short[k] = NAME_SHORT(id);
        }
        const char *l = on ? wr_named_long[on - 1][k] : 0;
        const char *sh = on ? wr_named_short[on - 1][k] : 0;
        if (on == 1)
            for (int j = 0; j < 8; j++)
                if (perc_param_ids[j] == id) {
                    l = perc_longs[perc_long[key - 16][j]];
                    sh = perc_short[key - 16][j];
                }
        NAME_LONG(id) = l ? l : stock_long[k];
        NAME_SHORT(id) = sh ? sh : stock_short[k];
    }
    names_on = key;
}

/* PING (src/dnfw/ping/pages.py): while the active track's filter is PING (type 6, the
 * byte at sound+0xDF), Multi-Mode's and the filter envelope's records whose meaning
 * PING changes carry PING's names; the stock pointers go back when it is not. The
 * same mechanism as wr_names, on records it does not touch. */
static const char *ping_stock_long[PING_NAMED] __attribute__((section(".data")));
static const char *ping_stock_short[PING_NAMED] __attribute__((section(".data")));
static int ping_on __attribute__((section(".data"))) = -2;   /* -2: not yet run */

/* -> which of ping_filters the active track's filter is (0..PING_SETS-1), or -1 */
static int ping_active(void)
{
    u8 t = UI_TRACK;
    unsigned char *kit = KIT_POINTER;
    if (t > 15 || !kit)
        return -1;
    signed char f = (signed char)kit[52u + 1163u * t + 0xDFu];
    for (int k = 0; k < PING_SETS; k++)
        if (f == ping_filters[k])
            return k;
    return -1;
}

static void ping_names(void)
{
    int on = ping_active();
    if (on == ping_on)
        return;
    for (int k = 0; k < PING_NAMED; k++) {
        u32 id = ping_named_ids[k];
        if (ping_on == -2) {                    /* the first call: keep the stock pointers */
            ping_stock_long[k] = NAME_LONG(id);
            ping_stock_short[k] = NAME_SHORT(id);
        }
        const char *l = on >= 0 ? ping_named_long[on][k] : 0;
        const char *sh = on >= 0 ? ping_named_short[on][k] : 0;
        NAME_LONG(id) = l ? l : ping_stock_long[k];
        NAME_SHORT(id) = sh ? sh : ping_stock_short[k];
    }
    ping_on = on;
}

/* v0.22: the UI loop's draw of its screen (0x4011d32a(screen, canvas), at 0x4002e4ca),
 * then, while it is up, the RECORDER over all of it (rec.c, smp_page.c) */
#define SCREEN_DRAW ((void (*)(void *, void *))0x4011D32Au)
void wr_screen(void *screen, void *canvas)
{
    extern int rec_visible(void);
    extern void rec_screen_draw(void *canvas);
    extern int slc_visible(void);
    extern void slc_draw(void *canvas);
    extern int smp_fb_visible(void);
    extern void smp_fb_draw(void *canvas, int samp);
    extern int smp_samp_of(int track);
    extern int smp_list_visible(void);
    extern void smp_list_draw(void *canvas);
    SCREEN_DRAW(screen, canvas);
    if (rec_visible())
        rec_screen_draw(canvas);
    else if (slc_visible())
        slc_draw(canvas);
    else if (smp_fb_visible())                  /* v0.25: the folder browser (ASSIGN SAMPLE) */
        smp_fb_draw(canvas, smp_samp_of(UI_TRACK));
    else if (smp_list_visible())                /* v0.25: the sample list, over the title bar too */
        smp_list_draw(canvas);
}

/* the UI loop's redraw test, as stock (and the names kept current, once a loop; and
 * v0.15: the sample link's +Drive copy loaded once the device is up) */
extern void smp_boot(void);

int wr_poll(void *screen)
{
    extern void rec_poll(void);
    extern int rec_visible(void);
    smp_boot();
    rec_poll();
    wr_names();
    ping_names();
    /* the RECORDER's meter and state move: a redraw asked for as stock asks (the dirty
     * byte), 25 times a second. v0.15..v0.19 answered 1 here without setting the byte:
     * the loop then pushed its other buffer undrawn (0x4011d32a draws only when the byte
     * is set), and the page flashed between the last two screens it had (owner, v0.19) */
    static u32 rec_next __attribute__((section(".data"))) = 0;
    extern void slc_poll(void);
    extern int slc_visible(void);
    extern int slc_busy(void);
    slc_poll();
    static int slc_was __attribute__((section(".data"))) = 0;
    int slc = slc_visible() || slc_busy();      /* v0.23: SLICE's menus, and their notes */
    extern int smp_wants_redraw(void);          /* v0.25: a sample page's moving playhead */
    extern int smp_overlay_dirty;               /* v0.25: the sample list and the browser */
    extern int slc_state;                       /* v0.25: a SLICE/GRID menu opening or moving */
    static int slc_last __attribute__((section(".data"))) = 0;   /* on is drawn at once, not */
    if (smp_overlay_dirty || slc_state != slc_last) {            /* at the next redraw tick */
        smp_overlay_dirty = 0;
        slc_last = slc_state;
        SET_DIRTY(screen);
    }
    if ((rec_visible() || slc || slc_was || smp_wants_redraw()) && (int)(FRAMES_NOW - rec_next) >= 0) {
        rec_next = FRAMES_NOW + REC_REDRAW;
        SET_DIRTY(screen);
        slc_was = slc;                          /* once more after it closes: the page again */
    }
    return IS_DIRTY(screen);
}

static void *method(void *obj, int offset)
{
    return *(void **)(*(char **)obj + offset);
}

static void px(void *c, int x, int y)
{
    SET_PIXEL(c, x, y, 1);
}

static void column(void *c, int x, int y0, int y1)
{
    if (y0 > y1) {
        int t = y0; y0 = y1; y1 = t;
    }
    for (int y = y0; y <= y1; y++)
        px(c, x, y);
}

/* A control's value under its label: a dotted track with the value filled in,
 * from the left, or from the centre for a control whose default is the middle
 * of its range (TUNE). A control of a few steps (TBL: 0..0x100) is drawn as
 * that many segments with the current one filled. */
static void indicator(void *c, int cx, int y, u32 id, int v)
{
    const int *r = RECORD(id);
    int lo = r[2], hi = r[3], def = r[4], span = hi - lo;
    if (span <= 0)
        return;
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    int x0 = cx - BAR_HALF, x1 = cx + BAR_HALF;

    if (span % 0x100 == 0 && span / 0x100 < 8) {
        int n = span / 0x100 + 1, at = (v - lo) / 0x100;
        int w = (x1 - x0 + 2) / n;
        for (int k = 0; k < n; k++) {
            int a = x0 + k * w, b = a + w - 2;
            for (int x = a; x <= b; x++) {
                px(c, x, y);
                if (k == at)
                    px(c, x, y + 1);
            }
        }
        return;
    }

    for (int x = x0; x <= x1; x += 2)
        px(c, x, y);
    int at = x0 + (v - lo) * (x1 - x0) / span;
    int from = (2 * def == lo + hi) ? cx : x0;
    column(c, at, y, y + 1);
    for (int x = (from < at ? from : at); x <= (from < at ? at : from); x++)
        px(c, x, y + 1);
}

/* PERC's picture: the machine TYPE selects, its name and what it is, in the middle,
 * with its place among the machines as a row of dots under them */
static void perc_picture(void *c, void *view)
{
    u8 flag;
    int k = perc_of(GET_VALUE(view, PERC_TYPE_ID, &flag));
    TEXT(c, FONT, WAVE_X + WR_WIDTH / 2, 30, CENTRED, "%.6s", perc_machine[k]);
    TEXT(c, FONT, WAVE_X + WR_WIDTH / 2, 20, CENTRED, "%.11s", perc_what[k]);
    for (int j = 0; j < PERC_N; j++) {
        int x = WAVE_X + 12 + j * 3;
        px(c, x, 15);
        if (j == k) {
            px(c, x, 16);
            px(c, x + 1, 15);
            px(c, x + 1, 16);
        }
    }
}

/* v0.26: the Monomachine's machines (types 6, 7: docs/mnm.md), each one page of its eight
 * parameters on PERC's eight records. A parameter's knob (0..127) as the DSP reads it
 * (dnfw.perc.program: p = clamp((value >> 8) - lo, 0, top) / top, knob = p x 127, rounded);
 * an enumerated one shows its choice by name, as the Monomachine's screen does. */
static int mnm_knob(void *view, int j)
{
    u8 flag;
    int v = (GET_VALUE(view, perc_param_ids[j], &flag) >> 8) - mnm_lo[j];
    int top = mnm_top[j];
    v = v < 0 ? 0 : v > top ? top : v;
    return (v * 127 * 2 + top) / (2 * top);
}

static const char *mnm_text(void *view, int m, int j)
{
    static char num[6] __attribute__((section(".data")));
    int n = mnm_choices[m][j];
    if (!n)
        return 0;                                   /* a knob */
    int k = mnm_knob(view, j);
    if (n == MNM_PCH)                               /* DENS's PCH2..4: by the ROM's table */
        return mnm_choice_names[mnm_choice_at[m][j] + mnm_pch_idx[k > 127 ? 127 : k]];
    int c = (k * n) >> 7;
    if (n == MNM_WAVES || n == 2 * MNM_WAVES) {     /* the ROM waves: S01..S32 (DDRW, DENS: the */
        c &= MNM_WAVES - 1;                         /* Digibank's 64, here the 32 twice) */
        num[0] = 'S'; num[1] = '0' + (c + 1) / 10; num[2] = '0' + (c + 1) % 10; num[3] = 0;
        return num;
    }
    return mnm_choice_names[mnm_choice_at[m][j] + c];
}

/* The sample machines (docs/sampler.md). A control's 0..top value, as the DSP reads it
 * (dnfw.sampler.program.ctl). */
static int smp_get(void *view, u32 id)
{
    u8 flag;
    int v = GET_VALUE(view, id, &flag) >> 8;
    const int *r = RECORD(id);
    int lo = r[2] >> 8, top = (r[3] >> 8) - lo;
    v -= lo;
    return v < 0 ? 0 : v > top ? top : v;
}

/* the pool's names: the sample link's (csrc/sampler/link.c) once a pool has been sent,
 * the built-in test sounds until then; 0 for a slot the pool does not hold (K from 1) */
extern int smp_count(void);
extern const char *smp_name(int k);

static const char *sound_name(int k)
{
    int n = smp_count();
    if (n >= 0)
        return k <= n ? smp_name(k - 1) : 0;
    return k <= SMP_SOUNDS ? smp_sound[k - 1] : 0;
}

static const char *smp_text(void *view, u32 id, int kind, const char *label)
{
    static char buf[6] __attribute__((section(".data")));
    if (id == SMP_PLAY_ID) {
        int k = smp_get(view, id) * 4 / 128;
        return smp_play[k > 3 ? 3 : k];
    }
    if (id == SMP_SAMP_ID) {
        int k = smp_get(view, id);
        if (k == 0)
            return "OFF";
        const char *nm = sound_name(k);
        if (nm && nm[0])
            return nm;
        buf[0] = '0' + k / 100; buf[1] = '0' + k / 10 % 10; buf[2] = '0' + k % 10; buf[3] = 0;
        return buf[0] == '0' ? buf + 1 : buf;
    }
    if (id == SMP_BARS_ID) {                    /* the DSP's index: the thresholds it compares */
        int v = smp_get(view, id), k = 0;
        while (k < 7 && v >= smp_bars_steps[k])
            k++;
        return smp_bars[k];
    }
    if (id == SMP_SEG_ID) {                     /* a segment, 1/n of a bar: 32 >> index (v0.18) */
        int v = smp_get(view, id), k = 0;
        while (k < 7 && v >= smp_seg_steps[k])
            k++;
        int n = 32 >> k;
        buf[0] = 'S';
        if (n >= 100) { buf[1] = '1'; buf[2] = '2'; buf[3] = '8'; buf[4] = 0; }
        else if (n >= 10) { buf[1] = '0' + n / 10; buf[2] = '0' + n % 10; buf[3] = 0; }
        else { buf[1] = '0' + n; buf[2] = 0; }
        return buf;
    }
    if (id == SMP_MODE_ID) {
        int k = smp_get(view, id) * 4 / 128;
        return smp_play[k > 3 ? 3 : k];
    }
    if (kind == SMP_GRID_KIND && id == SMP_GRID_ID) {
        int g = smp_get(view, id) / 24;
        int n = smp_grids[g > 4 ? 4 : g];
        buf[0] = 'G'; buf[1] = '0' + n / 10; buf[2] = '0' + n % 10; buf[3] = 0;
        if (n < 10) { buf[1] = '0' + n; buf[2] = 0; }
        return buf;
    }
    return label;
}

/* the picture: the machine and the sound in the middle; under them the sample as a bar,
 * the part that plays solid (STRT..STRT+LEN, or GRID's slice) and LOOP's point marked */
static void smp_picture(void *c, void *view, int kind)
{
    int k = smp_get(view, SMP_SAMP_ID);
    const char *snd = k == 0 ? "OFF" : sound_name(k);
    if (!snd)
        snd = "EMPTY";
    TEXT(c, FONT, WAVE_X + WR_WIDTH / 2, 30, CENTRED, "%.7s", smp_machine[kind - SMP_KIND0]);
    TEXT(c, FONT, WAVE_X + WR_WIDTH / 2, 21, CENTRED, "%.5s", snd);
    int w = WR_WIDTH - 8, x0 = WAVE_X + 4, a, b, loop = -1;
    if (kind == SMP_GRID_KIND) {
        int g = smp_get(view, SMP_GRID_ID) / 24, n = smp_grids[g > 4 ? 4 : g];
        int s = (smp_get(view, SMP_SLICE_ID) >> 1) & (n - 1);
        int len = (smp_get(view, SMP_SLEN_ID) >> 1) + 1;
        a = s * w / n;
        b = (s + len) * w / n;
        for (int j = 0; j <= n && n <= 32; j++)
            px(c, x0 + j * w / n, POS_Y + 2);
    } else if (kind == SMP_WERP_KIND) {         /* the whole sample, its segments ticked */
        int v = smp_get(view, SMP_SEG_ID), j = 0;
        while (j < 7 && v >= smp_seg_steps[j])
            j++;
        int n = 32 >> j;                        /* (per bar; the ticks are drawn up to 32) */
        a = 0;
        b = w;
        for (int i = 0; i <= n && n <= 32; i++)
            px(c, x0 + i * w / n, POS_Y + 2);
    } else {
        a = smp_get(view, SMP_STRT_ID) * w / 120;
        b = a + smp_get(view, SMP_LEN_ID) * w / 127;
        loop = smp_get(view, SMP_LOOP_ID) * w / 127;
    }
    if (b > w) b = w;
    for (int x = 0; x <= w; x += 2)
        px(c, x0 + x, POS_Y);
    for (int x = a; x <= b; x++) {
        px(c, x0 + x, POS_Y);
        px(c, x0 + x, POS_Y + 1);
    }
    if (loop >= 0) {
        int pmode = smp_get(view, SMP_PLAY_ID) * 4 / 128;
        if (pmode == 1 || pmode == 2)               /* REVL, FWDL: the loop point */
            column(c, x0 + loop, POS_Y - 2, POS_Y + 3);
    }
}

/* PING and SHFT (src/dnfw/ping/pages.py): every cell widget of a stock page is drawn by
 * 0x4006448a(view, canvas, x, y, id, ...), and as each one finishes (wr_cell_tail) this
 * is told which. The cell of Multi-Mode's Filter Type (record 38) -- PING's TYPE, SHFT's
 * MODE -- then shows the name of what it selects, with a dot a choice under it, in place
 * of Multi-Mode's LP/BP/HP icons. The widget is x..x+23, y+8..y+23 (canvas, y up); the
 * label under it is untouched. Any other cell, and any track whose filter is neither,
 * is left as stock drew it. */
void wr_cell(void *view, void *canvas, int x0, int y0, u32 id)
{
    if (id != PING_TYPE_ID)
        return;
    int set = ping_active();
    if (set < 0)
        return;
    for (int x = x0; x < x0 + 24; x++)
        for (int y = y0 + 8; y < y0 + 24; y++)
            SET_PIXEL(canvas, x, y, 0);
    u8 flag;
    const int *r = RECORD(id);
    int n = ping_type_count[set], span = r[3] - r[2];
    int v = GET_VALUE(view, id, &flag) - r[2];
    int at = span > 0 ? v * n / span : 0;     /* as the DSP: trunc(v / span * n), the top clamped */
    if (at < 0) at = 0;
    if (at >= n) at = n - 1;
    TEXT(canvas, FONT, x0 + 12, y0 + 14, CENTRED, "%.4s", ping_type_text[set][at]);
    for (int j = 0; j < n; j++) {                 /* a dot a choice, the current one bold */
        int cx = x0 + 12 + (2 * j - (n - 1)) * 3;
        px(canvas, cx, y0 + 10);
        if (j == at) {
            px(canvas, cx, y0 + 11);
            px(canvas, cx + 1, y0 + 10);
            px(canvas, cx + 1, y0 + 11);
        }
    }
}

void wr_page_draw(void *view, void *canvas)
{
    int page = ((int (*)(void *))method(view, 132))(view);
    int kind = wr_active();
    int mi = mnm_index(kind);                   /* v0.26: a Monomachine machine's: one page */
    int mnm = mi >= 0;
    int smp = kind >= SMP_KIND0 && kind < SMP_KIND0 + SMP_N;   /* a sample machine's */
    if (page < 0 || page >= (smp ? 2 : mnm ? 1 : WR_PAGES))
        page = 0;
    if (kind == 1) {                            /* PERC: the names TYPE has now */
        u8 flag;
        perc_seen = perc_of(GET_VALUE(view, PERC_TYPE_ID, &flag));
    }
    wr_names();
    if (kind == 1) {                            /* v0.20: the Machinedrum's own screen */
        extern int md_page_draw(void *view, void *canvas, int page, int type);
        if (md_page_draw(view, canvas, page, perc_seen))
            return;
    }

    if (smp) {                                  /* the DT2's SRC pages 1 and 2 (v0.22: the recorder is FUNC + VOICE) */
        extern void smp_page_draw(void *view, void *canvas, int kind, int wave);
        smp_page_draw(view, canvas, kind, page == 1);
        ((void (*)(void *, void *, int))method(view, 184))(view, canvas, 0);
        int n = PAGE_COUNT(view);
        if (n > 1)
            PAGE_DOTS(view, canvas, n, page, 7);
        return;
    }
    if (mnm) {                                  /* v0.27: the Monomachine's own screen */
        extern int mnm_page_draw(void *view, void *canvas, int mi);
        if (mnm_page_draw(view, canvas, mi))
            return;
    }
    if (mnm) {                                  /* the Monomachine's grid of eight (no MD OS read) */
        extern void smp_knob_page(void *view, void *canvas, const unsigned short *ids,
                                  const char *const *labels, const char *const *texts);
        const char *labels[8], *texts[8];
        for (int i = 0; i < 8; i++) {
            labels[i] = mnm_labels[mi][i];
            texts[i] = mnm_text(view, mi, i);
        }
        smp_knob_page(view, canvas, perc_param_ids, labels, texts);
        ((void (*)(void *, void *, int))method(view, 184))(view, canvas, 0);
        int n = PAGE_COUNT(view);
        if (n > 1)
            PAGE_DOTS(view, canvas, n, page, 7);
        return;
    }
    if (smp)
        smp_picture(canvas, view, kind);
    else
        perc_picture(canvas, view);

    for (int i = 0; i < 8; i++) {
        int top = i < 4;
        int cx = COL0 + COLW * (i & 3) + COLW / 2;
        u32 id = smp ? smp_ids[kind - SMP_KIND0][i] : wr_ids[page][i];
        const char *label = smp ? "-" : wr_labels[page][i];
        if (id)
            label = NAME_SHORT(id);             /* PERC, samples: the name wr_names gave the record */
        if (smp && id)
            label = smp_text(view, id, kind, label);
        TEXT(canvas, FONT, cx, top ? TOP_LABEL_Y : BOT_LABEL_Y, CENTRED, "%.5s", label);
        if (!id || (label[0] == '-' && !label[1]))
            continue;                           /* an empty place, or a parameter this machine lacks */
        u8 flag;
        int set = GET_VALUE(view, id, &flag);
        indicator(canvas, cx, top ? TOP_BAR_Y : BOT_BAR_Y, id, set);
    }

    /* the stock grid's own tail: the level meter, then the page dots */
    ((void (*)(void *, void *, int))method(view, 184))(view, canvas, 0);
    int n = PAGE_COUNT(view);
    if (n > 1)
        PAGE_DOTS(view, canvas, n, page, 7);
}
