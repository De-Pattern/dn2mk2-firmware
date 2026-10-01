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
#define IS_DIRTY   ((int (*)(void *))0x4011D2F4u)               /* screen: a redraw due? */
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
#define WR_MARKERS 1          /* the modulation markers and the redraw they need */
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
/* Modulation (docs/modulation-display.md). The audio tick keeps, per track, a target
 * array (the sound's values, refreshed when a note plays) and the value array it
 * smooths from it and then modulates in place (0x400db12a, 0x400db22c); slot s of
 * track t is at +34 + 202 t + 2 s in both, at the record's own scale for a linear
 * parameter (instrument, modview1, 2026-10-01: POS 74 with no LFO reads 0x4a00).
 *
 * The value array alone lags the knob: it holds what was last heard, so with the
 * sequencer stopped it does not follow a turn (owner, modview2b). So the markers
 * show the modulation as an offset, heard - target, drawn around the knob's own
 * value: the dot at knob + offset, and the range the offset swept lately around the
 * knob. A turn moves all three together. */
#define ACTIVE_TRACK (*(volatile u8 *)0x42431A6Cu)
#define TARGETS 0x80003AF0u
#define VALUES  0x800068E4u
/* the UI tick, about 120 a second (instrument, modview3, 2026-10-01: 239 in 2.0 s).
 * Not a millisecond count, as docs/display-path.md had it from the emulator. */
#define TICKS   (*(volatile u32 *)0x466758B0u)
#define TICK_HZ 120
#define SET_DIRTY ((void (*)(void *))0x4011D2FEu)               /* screen: redraw */

#define QUANT   0x300           /* an offset step worth a redraw: about half a pixel */
#define HOLD    (2 * TICK_HZ)   /* a range edge holds 2 s before it relaxes */
#define SHOWN   (TICK_HZ * 6 / 5)   /* 1.2 s: the stock UI redraws a shown page once a second */
#define FRAME   5               /* ticks: at most 24 redraws a second, about a turn's own rate */
#define MARKED  2               /* the places with markers: POS and TBL (TUNE is
                                 * pitch-converted in the array, so not yet) */

static int mod_offset(u32 id)
{
    int t = ACTIVE_TRACK, slot = RECORD(id)[1];
    if (t > 15 || slot < 0 || slot > 99)
        return 0;
    u32 at = 34u + 202u * t + 2u * slot;
    return *(volatile unsigned short *)(VALUES + at) - *(volatile unsigned short *)(TARGETS + at);
}

static const u32 marked[MARKED] = { WR_POS_ID, WR_TBL_ID };

/* per marked parameter: the offset range swept lately, and when each edge last grew */
struct sweep { int lo, hi; u32 lo_at, hi_at; };
static struct sweep sweeps[MARKED] __attribute__((section(".data"))) = { { 0, 0, 0, 0 }, { 0, 0, 0, 0 } };
/* what the last draw showed, for wr_poll to compare against */
static u32 drawn_at __attribute__((section(".data"))) = 0;
static u32 asked_at __attribute__((section(".data"))) = 0;
static int drawn_sig __attribute__((section(".data"))) = 0;
static int settling __attribute__((section(".data"))) = 0;

static int which(u32 id)
{
    for (int k = 0; k < MARKED; k++)
        if (marked[k] == id)
            return k;
    return -1;
}

/* How fast the parameter moves, from the settings of the LFOs aimed at it
 * (docs/modulation-display.md, "faster than the screen"): tier 0 is slow enough for
 * a moving dot (up to a redraw rate's eighth, 3 Hz at 24 a second), tier 1 is jerky
 * (up to half the rate, 12 Hz) and gets the dot over a dithered band, tier 2 would
 * alias and gets the band alone. The rate is the manual's table (p. 64):
 *   f = |SPD| x MULT x BPM / 30720 Hz, BPM 120 for a fixed MULT.
 * The LFO settings are the target array's slots 1..24, eight an LFO: SPD, MULT,
 * FADE, DEST, WAVE, SPH, MODE, DEP (the record table: ids 75..83, 85..93, 95..103).
 * DEST holds the destination's slot << 8 (docs/fx-master-modulation.md). */
#define TIER_FPS 24
#ifndef WR_BPM
#define WR_BPM() 120            /* the tempo; read from the project once located */
#endif

static int lfo_word(int t, int slot)
{
    return *(volatile unsigned short *)(TARGETS + 34u + 202u * t + 2u * slot);
}

static int tier(u32 id)
{
    int t = ACTIVE_TRACK, slot = RECORD(id)[1], fastest = 0;
    if (t > 15)
        return 0;
    for (int l = 0; l < 3; l++) {
        int base = 1 + 8 * l;
        int dep = lfo_word(t, base + 7) - 0x4000;
        if (lfo_word(t, base + 3) != slot << 8 || (dep < 0x80 && dep > -0x80))
            continue;
        int spd = lfo_word(t, base) - 0x4000, m = lfo_word(t, base + 1) >> 8;
        if (spd < 0) spd = -spd;
        /* MULT: twelve tempo-synced 1..2048, then twelve fixed at 120 BPM */
        int bpm = m < 12 ? WR_BPM() : 120, mult = 1 << (m < 12 ? m : m - 12);
        /* spd/16 x mult x bpm stays in 31 bits; Hz x 30720 x 256 / 16 = Hz x 491520 */
        int rate = (spd >> 4) * mult * bpm;
        int k = rate > 491520 * (TIER_FPS / 2) ? 2 : rate > 491520 * (TIER_FPS / 8) ? 1 : 0;
        if (k > fastest)
            fastest = k;
    }
    return fastest;
}

/* what a redraw would change: the offsets of the places slow enough to animate */
static int signature(void)
{
    int sig = 0;
    for (int k = 0; k < MARKED; k++)
        sig = sig * 131 + (tier(marked[k]) < 2 ? mod_offset(marked[k]) / QUANT : 0);
    return sig;
}

/* widen at once; after HOLD without growing, an edge relaxes toward the offset */
static void sweep(int k, int off, u32 now)
{
    struct sweep *w = &sweeps[k];
    if (off <= w->lo) { w->lo = off; w->lo_at = now; }
    else if (now - w->lo_at > HOLD) w->lo += (off - w->lo) / 4 + 1;
    if (off >= w->hi) { w->hi = off; w->hi_at = now; }
    else if (now - w->hi_at > HOLD) w->hi += (off - w->hi) / 4 - 1;
    if (w->lo > off) w->lo = off;
    if (w->hi < off) w->hi = off;
    if (w->hi - w->lo > QUANT)
        settling = 1;
}

/* Called by the UI task in place of its `isDirty(screen)` (0x4002e464), once a loop:
 * while Waverider's page is on screen (it drew in the last SHOWN) and a marker
 * would move, ask the stock redraw (0x4011d2fe), at most every FRAME. Off the
 * page, or with nothing modulated, it costs a compare and the stock call. */
int wr_poll(void *screen)
{
    u32 now = TICKS;
    if (now - drawn_at < SHOWN && now - asked_at >= FRAME
            && (settling || signature() != drawn_sig)) {
        asked_at = now;
        SET_DIRTY(screen);
    }
    return IS_DIRTY(screen);
}
#endif

#if !WR_MARKERS
/* the UI loop's redraw test, as stock: nothing on the page moves by itself */
int wr_poll(void *screen)
{
    return IS_DIRTY(screen);
}
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
/* a small "approximately" sign, two tildes 4 wide, 4 x 5, its bottom-left corner at
 * (x, y): each tilde low, high, low, high, so it reads as a wave and not as carets */
static void approx(void *c, int x, int y)
{
    for (int k = 0; k < 2; k++) {
        int yy = y + 1 + 3 * k;
        px(c, x, yy); px(c, x + 1, yy + 1); px(c, x + 2, yy); px(c, x + 3, yy + 1);
    }
}

/* x of value v on place cx's track, as `indicator` places it */
static int track_x(u32 id, int cx, int v)
{
    const int *r = RECORD(id);
    int lo = r[2], hi = r[3];
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return cx - BAR_HALF + (v - lo) * (2 * BAR_HALF) / (hi - lo);
}

/* Place i's modulation, on the row beside its track (y), option B: the range swept
 * lately around the knob, dotted, and a two-pixel dot at knob + offset. Nothing at
 * all while the parameter is not modulated. */
static void modulation(void *c, int cx, int y, int label_y, u32 id, int set, u32 now)
{
    int k = which(id);
    const int *r = RECORD(id);
    if (k < 0 || r[3] <= r[2])
        return;
    int off = mod_offset(id);
    sweep(k, off, now);
    struct sweep *w = &sweeps[k];
    if (w->hi - w->lo <= QUANT && off < QUANT && off > -QUANT)
        return;
    int a = track_x(id, cx, set + w->lo), b = track_x(id, cx, set + w->hi);
    int speed = tier(id);
    if (speed == 0) {
        for (int x = a; x <= b; x += 2)
            px(c, x, y);
    } else {
        for (int x = a; x <= b; x++)            /* the band: a 50 % dither, the panel's grey */
            for (int yy = y - 1; yy <= y; yy++)
                if (((x + yy) & 1) == 0)
                    px(c, x, yy);
    }
    if (speed < 2)
        column(c, track_x(id, cx, set + off), y - 1, y);
    else
        approx(c, cx + 10, label_y);            /* "too fast to draw" beside the label */
}
#endif

/* The frame the SHARC reader plays for the current TBL and POS, interpolated
 * between the two frames either side, one span a column; then the table's
 * position as a dotted bar with a marker. With the markers, the wave is the frame
 * heard (the knob plus the modulation), and a dotted marker above the bar shows
 * where the modulation has it, while the solid one stays on the knob. */
/* column x of the frame at (tbl, pos), interpolated: its span, in canvas rows */
static void span(int tbl, int pos, int x, int *lo, int *hi)
{
    int fx = pos >> 3;                      /* pos * 15 * 256 / 0x7800, exactly */
    int f = fx >> 8, frac = fx & 0xFF;
    int g = f < WR_FRAMES - 1 ? f + 1 : f;
    int l = wr_spans[tbl][f][0][x] + (((wr_spans[tbl][g][0][x] - wr_spans[tbl][f][0][x]) * frac) >> 8);
    int h = wr_spans[tbl][f][1][x] + (((wr_spans[tbl][g][1][x] - wr_spans[tbl][f][1][x]) * frac) >> 8);
    *lo = WAVE_CY + l * WAVE_AMP / 127;
    *hi = WAVE_CY + h * WAVE_AMP / 127;
}

static int clamp_pos(int pos)
{
    return pos < 0 ? 0 : pos > WR_POS_MAX ? WR_POS_MAX : pos;
}

#define GHOST_STEPS 8

static void wave(void *c, void *view)
{
    u8 flag;
    int tbl = GET_VALUE(view, WR_TBL_ID, &flag) >> 8;
    int pos = GET_VALUE(view, WR_POS_ID, &flag);
#if WR_MARKERS
    int set_pos = clamp_pos(pos);
    int moved = mod_offset(WR_POS_ID);
    int speed = tier(WR_POS_ID);
    pos += moved;
    tbl = (GET_VALUE(view, WR_TBL_ID, &flag) + mod_offset(WR_TBL_ID)) >> 8;
#endif
    if (tbl < 0) tbl = 0;
    if (tbl >= WR_TABLES) tbl = WR_TABLES - 1;
    pos = clamp_pos(pos);

#if WR_MARKERS
    if (speed > 0) {
        /* Faster than the screen: the ghost wave, the outline of every frame the
         * modulation sweeps, solid at its edges and dithered inside -- the blend
         * of frames that is being heard. */
        int from = clamp_pos(set_pos + sweeps[0].lo), to = clamp_pos(set_pos + sweeps[0].hi);
        for (int x = 0; x < WR_WIDTH; x++) {
            int bottom = 999, top = -999;
            for (int k = 0; k <= GHOST_STEPS; k++) {
                int lo, hi;
                span(tbl, from + (to - from) * k / GHOST_STEPS, x, &lo, &hi);
                if (lo < bottom) bottom = lo;
                if (hi > top) top = hi;
            }
            px(c, WAVE_X + x, bottom);
            px(c, WAVE_X + x, top);
            for (int y = bottom + 1; y < top; y++)
                if (((x + y) & 1) == 0)
                    px(c, WAVE_X + x, y);
        }
        for (int x = 0; x < WR_WIDTH; x += 2)
            px(c, WAVE_X + x, POS_Y);
        int a = WAVE_X + from * (WR_WIDTH - MARK) / WR_POS_MAX;
        int b = WAVE_X + to * (WR_WIDTH - MARK) / WR_POS_MAX + MARK - 1;
        for (int x = a; x <= b; x++)            /* the positions swept, above the bar */
            if ((x & 1) == 0)
                px(c, x, POS_Y + 3);
        int m = WAVE_X + set_pos * (WR_WIDTH - MARK) / WR_POS_MAX;
        for (int k = 0; k < MARK; k++)
            column(c, m + k, POS_Y, POS_Y + 1);
        return;
    }
#endif

    int last_lo = 0, last_hi = 0;
    for (int x = 0; x < WR_WIDTH; x++) {
        int lo, hi;
        span(tbl, pos, x, &lo, &hi);
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
    if (moved >= QUANT || moved <= -QUANT)
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
#if WR_MARKERS
    u32 now = TICKS;
    settling = 0;
    drawn_sig = signature();
#endif

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
        modulation(canvas, cx, top ? TOP_BAR_Y - 2 : BOT_BAR_Y + 3, top ? TOP_LABEL_Y : BOT_LABEL_Y,
                   id, set, now);
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
#if WR_MARKERS
    drawn_at = now;
#endif
#ifdef WR_PROBE
    wr_probe.draws++;
    wr_probe.ticks += DTCN0 - t0;
    wr_probe.marker_ticks += tm;
#endif
}
