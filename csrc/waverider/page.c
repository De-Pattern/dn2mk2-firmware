/* Waverider's SYN page (M8.1): the wave across the middle, the controls in two
 * slim strips around it.
 *
 * The layout is Tonverk's Wavefinder page (User Manual OS 1.4.1, p. 94), on a
 * screen of the same size, drawn with our own widgets: encoders A..D are a strip
 * above the wave, E..H a strip below it, and each control is its label with a
 * small indicator, not a dial. So all eight controls of an oscillator fit on one
 * page, and the wave is on every page. `docs/waverider-m7-pages.md`, "M8.1".
 *
 * Entered from `wr_grid` (dnfw.waverider.pages) in place of the stock grid
 * `0x40017428(view, canvas)`, on a Waverider track only. It keeps the grid's own
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
 * from dnfw.waverider.pages and .wave.
 */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned char u8;

#define GET_VALUE  ((int (*)(void *, u32, u8 *))0x4006538E)   /* (view, id, &flag) */
#define SET_PIXEL  ((void (*)(void *, int, int, int))0x40113B90)  /* (canvas, x, y, on) */
#define TEXT       ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545C)
#define PAGE_COUNT ((int (*)(void *))0x400173CA)
#define PAGE_DOTS  ((void (*)(void *, void *, int, int, int))0x4006598A)
#define FONT       0x44507ED8u                                  /* the grid's label font */
#define CENTRED    2                                            /* TEXT flag: x is the centre */

/* a parameter record: +8 min, +12 max, +16 default (TUN1: 0x400, 0x7c00, 0x4000) */
#define RECORD(id) ((const int *)(0x401F7F94u + 60u * (id)))

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
#define MARK    3

#ifndef WR_MARKERS
#define WR_MARKERS 0
#endif

#ifdef WR_PROBE
/* Measurement builds only (scripts/build_modview_probe.py; tools/dn2modview.py reads
 * this over the probe's PEEK). DTCN0 is the free-running timer the probe also reads
 * (132 MHz on the instrument), so `ticks` over `draws` is the time one page draw
 * takes, and `marker_ticks` the part the markers take. */
#define DTCN0   (*(volatile u32 *)0xFC07000Cu)
struct wr_probe { u32 magic, draws, ticks, marker_ticks, markers, spare; };
volatile struct wr_probe wr_probe __attribute__((section(".data"))) =
    { 0x57525052u, 0, 0, 0, WR_MARKERS, 0x2D2D2D2Du };
#endif

#if WR_MARKERS
/* The value heard: the per-track array the audio tick fills from each sound and then
 * modulates in place (0x400db12a, 0x400db22c): slot s of track t at
 * 0x800068e4 + 34 + 202 t + 2 s, at half the record's scale for a linear parameter
 * (emulator: WAV1 at POS 120 reads 0x3c00). TUNE goes through a pitch conversion, so
 * its marker is only indicative. docs/modulation-display.md. */
#define ACTIVE_TRACK (*(volatile u8 *)0x42431A6Cu)
#define VALUES 0x800068E4u

static int heard(u32 id, int fallback)
{
    int t = ACTIVE_TRACK, slot = RECORD(id)[1];
    if (t > 15 || slot < 0 || slot > 99)
        return fallback;
    return 2 * *(volatile unsigned short *)(VALUES + 34u + 202u * t + 2u * slot);
}

/* the range each place has swept lately: widened at once, relaxed slowly */
static int span_lo[8] __attribute__((section(".data"))) = { -1, -1, -1, -1, -1, -1, -1, -1 };
static int span_hi[8] __attribute__((section(".data"))) = { -1, -1, -1, -1, -1, -1, -1, -1 };
static int span_id[8] __attribute__((section(".data"))) = { -1, -1, -1, -1, -1, -1, -1, -1 };
#endif

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

#if WR_MARKERS
/* x of value v on place cx's track, as `indicator` places it */
static int track_x(u32 id, int cx, int v)
{
    const int *r = RECORD(id);
    int lo = r[2], hi = r[3];
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return cx - BAR_HALF + (v - lo) * (2 * BAR_HALF) / (hi - lo);
}

/* Place i's modulation, on the row beside its track (y): the range it swept lately,
 * dotted, and a two-pixel dot at the value heard. Drawn for every working place on
 * every draw, modulated or not: the worst case, which is what build 2 measures. */
static void modulation(void *c, int i, int cx, int y, u32 id, int set)
{
    const int *r = RECORD(id);
    if (r[3] <= r[2])
        return;
    int now = heard(id, set);
    if (span_id[i] != (int)id) {
        span_id[i] = id;
        span_lo[i] = span_hi[i] = now;
    }
    if (now < span_lo[i]) span_lo[i] = now;
    if (now > span_hi[i]) span_hi[i] = now;
    span_lo[i] += (now - span_lo[i]) / 64;          /* relax toward what is heard */
    span_hi[i] += (now - span_hi[i]) / 64;
    int a = track_x(id, cx, span_lo[i]), b = track_x(id, cx, span_hi[i]);
    for (int x = a; x <= b; x += 2)
        px(c, x, y);
    column(c, track_x(id, cx, now), y - 1, y);
}
#endif

/* The frame the SHARC reader plays for the current TBL and POS, interpolated
 * between the two frames either side, one span a column; then the table's
 * position as a dotted bar with a marker. Build 2 draws the wave as heard, and
 * a second marker above the bar at the position heard. */
static void wave(void *c, void *view)
{
    u8 flag;
    int tbl = GET_VALUE(view, WR_TBL_ID, &flag) >> 8;
    int pos = GET_VALUE(view, WR_POS_ID, &flag);
#if WR_MARKERS
    int set_pos = pos < 0 ? 0 : pos > WR_POS_MAX ? WR_POS_MAX : pos;
    pos = heard(WR_POS_ID, pos);
    tbl = heard(WR_TBL_ID, tbl << 8) >> 8;
#endif
    if (tbl < 0) tbl = 0;
    if (tbl >= WR_TABLES) tbl = WR_TABLES - 1;
    if (pos < 0) pos = 0;
    if (pos > WR_POS_MAX) pos = WR_POS_MAX;

    int fx = pos >> 3;                      /* pos * 15 * 256 / 0x7800, exactly */
    int f = fx >> 8, frac = fx & 0xFF;
    int g = f < WR_FRAMES - 1 ? f + 1 : f;
    const signed char *a = wr_spans[tbl][f][0], *b = wr_spans[tbl][g][0];
    const signed char *A = wr_spans[tbl][f][1], *B = wr_spans[tbl][g][1];

    int last_lo = 0, last_hi = 0;
    for (int x = 0; x < WR_WIDTH; x++) {
        int lo = a[x] + (((b[x] - a[x]) * frac) >> 8);
        int hi = A[x] + (((B[x] - A[x]) * frac) >> 8);
        lo = WAVE_CY + lo * WAVE_AMP / 127;
        hi = WAVE_CY + hi * WAVE_AMP / 127;
        if (x == 0) {
            last_lo = lo;
            last_hi = hi;
        }
        /* reach the last column's span, so neighbours always meet */
        column(c, WAVE_X + x, lo < last_hi ? lo : last_hi, hi > last_lo ? hi : last_lo);
        last_lo = lo;
        last_hi = hi;
    }

    for (int x = 0; x < WR_WIDTH; x += 2)
        px(c, WAVE_X + x, POS_Y);
#if WR_MARKERS
    int m = WAVE_X + set_pos * (WR_WIDTH - MARK) / WR_POS_MAX;
    int h = WAVE_X + pos * (WR_WIDTH - MARK) / WR_POS_MAX;
    for (int k = 0; k < MARK; k += 2)
        px(c, h + k, POS_Y + 3);
#else
    int m = WAVE_X + pos * (WR_WIDTH - MARK) / WR_POS_MAX;
#endif
    for (int k = 0; k < MARK; k++)
        column(c, m + k, POS_Y, POS_Y + 1);
}

void wr_page_draw(void *view, void *canvas)
{
#ifdef WR_PROBE
    u32 t0 = DTCN0, tm = 0;
#endif
    int page = ((int (*)(void *))method(view, 132))(view);
    if (page < 0 || page >= WR_PAGES)
        page = 0;

    wave(canvas, view);

    for (int i = 0; i < 8; i++) {
        int top = i < 4;
        int cx = COL0 + COLW * (i & 3) + COLW / 2;
        u32 id = wr_ids[page][i];
        TEXT(canvas, FONT, cx, top ? TOP_LABEL_Y : BOT_LABEL_Y, CENTRED, "%.5s", wr_labels[page][i]);
        if (!id)
            continue;
        u8 flag;
        int set = GET_VALUE(view, id, &flag);
        indicator(canvas, cx, top ? TOP_BAR_Y : BOT_BAR_Y, id, set);
#if WR_MARKERS
#ifdef WR_PROBE
        u32 m0 = DTCN0;
#endif
        modulation(canvas, i, cx, top ? TOP_BAR_Y - 2 : BOT_BAR_Y + 3, id, set);
#ifdef WR_PROBE
        tm += DTCN0 - m0;
#endif
#endif
    }

    /* the stock grid's own tail: the level meter, then the page dots */
    ((void (*)(void *, void *, int))method(view, 184))(view, canvas, 0);
    int n = PAGE_COUNT(view);
    if (n > 1)
        PAGE_DOTS(view, canvas, n, page, 7);
#ifdef WR_PROBE
    wr_probe.draws++;
    wr_probe.ticks += DTCN0 - t0;
    wr_probe.marker_ticks += tm;
#endif
}
