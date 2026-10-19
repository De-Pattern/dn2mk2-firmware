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

/* W2: is the active track a Waverider? (pages.is_wr's test: the active track's sound,
 * [0x800052a0] + 52 + 1163 t, has machine type 5 at +0xDE) */
static int wr_active(void)
{
    u8 t = UI_TRACK;
    unsigned char *kit = KIT_POINTER;
    if (t > 15 || !kit)
        return 0;
    signed char m = (signed char)kit[52u + 1163u * t + 0xDEu];
    return m == 5 ? 1 : m == 6 ? 2 : m == 7 ? 3 : 0;   /* Waverider, RESONATOR, CZ (docs/cz.md) */
}

/* W2 (docs/w2-scanner.md): while the active track is a Waverider, WaveTone's records
 * carry Waverider's names, so the LFO and modulation destination lists, the LFO page's
 * DEST field and the header's parameter line all say TBL / Wave Table where they said
 * DRIF / Osc Drift; as soon as it is not, the stock pointers go back. Only the two
 * name pointers of the records in wr_named_ids are written, and only on a change. The
 * table is in RAM, and ACR0 (0x4007e020, set at 0x40000564) leaves 0x40000000-
 * 0x47ffffff writable: its W bit is clear. */
static const char *stock_long[WR_NAMED] __attribute__((section(".data")));
static const char *stock_short[WR_NAMED] __attribute__((section(".data")));
static int names_on __attribute__((section(".data"))) = -1;

static void wr_names(void)
{
    int on = wr_active();
    if (on == names_on)
        return;
    for (int k = 0; k < WR_NAMED; k++) {
        u32 id = wr_named_ids[k];
        if (names_on < 0) {                     /* the first call: keep the stock pointers */
            stock_long[k] = NAME_LONG(id);
            stock_short[k] = NAME_SHORT(id);
        }
        const char *l = on ? wr_named_long[on - 1][k] : 0;
        const char *sh = on ? wr_named_short[on - 1][k] : 0;
        NAME_LONG(id) = l ? l : stock_long[k];
        NAME_SHORT(id) = sh ? sh : stock_short[k];
    }
    names_on = on;
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
#define FRAME   4               /* ticks: at most 30 redraws a second (W5; 5, 24 a second, before) */
#define MARKED  2               /* the places with markers: POS and TBL (TUNE is
                                 * pitch-converted in the array, so not yet) */

static int which(u32 id);
static int live(int k, u32 id);

static int mod_offset(u32 id)
{
    int t = ACTIVE_TRACK, slot = RECORD(id)[1];
    if (t > 15 || slot < 0 || slot > 99)
        return 0;
    int k = which(id);
    if (k >= 0 && !live(k, id))                 /* W5: a stale difference is not modulation */
        return 0;
    u32 at = 34u + 202u * t + 2u * slot;
    return *(volatile unsigned short *)(VALUES + at) - *(volatile unsigned short *)(TARGETS + at);
}

/* W5 (measured in the emulator, 2026-10-11): the target array is the live sound --
 * a knob turn writes it at once (TBL: 0x0000 -> 0x6800 on a turn), and a p-lock
 * reaches it while it plays. The value array is the audio tick's: the target,
 * smoothed, plus every modulator; on the instrument it does not follow a turn while
 * the sequencer is stopped (owner, modview2b), and the emulator never runs it. So the
 * value array is believed only once it has moved since the target last did; until
 * then the target (the knob, or the lock) is what the page shows, and no modulation
 * is drawn from a stale difference. */
static int array_word(u32 base, u32 id)
{
    int t = ACTIVE_TRACK, slot = RECORD(id)[1];
    if (t > 15 || slot < 0 || slot > 99)
        return -1;
    return *(volatile unsigned short *)(base + 34u + 202u * t + 2u * slot);
}

static const u32 marked[MARKED] = { WR_POS_ID, WR_TBL_ID };
/* per marked parameter: the target and the value at the last look, and when each last
 * moved. A first look marks the target as the newer, so the page starts on the sound
 * and waits for the audio tick to say otherwise. */
static int last_target[MARKED] __attribute__((section(".data"))) = { -1, -1 };
static int last_value[MARKED] __attribute__((section(".data"))) = { -1, -1 };
static u32 target_at[MARKED] __attribute__((section(".data"))) = { 0, 0 };
static u32 value_at[MARKED] __attribute__((section(".data"))) = { 0, 0 };

/* note what moved; -> 1 when the value array is live (moved since the target did) */
static int live(int k, u32 id)
{
    int target = array_word(TARGETS, id), value = array_word(VALUES, id);
    u32 now = TICKS;
    if (target < 0)
        return 0;
    if (last_target[k] < 0) {
        last_target[k] = target;
        last_value[k] = value;
        target_at[k] = now;
        value_at[k] = now - 1;
    }
    if (target != last_target[k]) { last_target[k] = target; target_at[k] = now; }
    if (value != last_value[k]) { last_value[k] = value; value_at[k] = now; }
    return (int)(value_at[k] - target_at[k]) >= 0;
}

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
/* The tempo, as BPM x 120: 14400 at 120.0, 14520 at 121.0 (instrument, modview3b,
 * 2026-10-01, three snapshots of the on-chip RAM, stopped). The control frame for the
 * SHARC carries a copy at 0x80005f38. */
#define TEMPO_X120 (*(volatile unsigned short *)0x800026C2u)

static int bpm(void)
{
    int t = TEMPO_X120 / 120;
    return t >= 20 && t <= 400 ? t : 120;
}

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
        /* MULT: 0..11 are 1..2K BPM, synced; 12..23 are 1..2K fixed at 120 BPM
         * (instrument, modview3b: raw 8 reads "256 BPM", 0 "1 BPM", 12 "1") */
        int beats = m < 12 ? bpm() : 120, mult = 1 << (m < 12 ? m : m - 12);
        /* spd/16 x mult x bpm stays in 31 bits; Hz x 30720 x 256 / 16 = Hz x 491520 */
        int rate = (spd >> 4) * mult * beats;
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
    for (int k = 0; k < MARKED; k++) {
        sig = sig * 131 + (tier(marked[k]) < 2 ? mod_offset(marked[k]) / QUANT : 0);
        sig = sig * 131 + array_word(TARGETS, marked[k]) / QUANT;  /* W5: a lock, a motion or a turn */
    }
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
    wr_names();
    ping_names();
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
    wr_names();
    ping_names();
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
 * heard (the knob plus the modulation), and a dotted marker under the bar shows
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

/* The frame at (tbl, pos) as a thin line. Each column is its span drawn solid --
 * its real extent, as Tonverk's Wavefinder draws a column -- with a span of two
 * pixels or less shrunk to its middle pixel, and joined to the column before only
 * across the gap between them, if there is one. A smooth stretch is one pixel
 * thick, a steep one a single solid stroke. Drawing each span by its two edges
 * instead split every steep slope into two traces (modview4e, on the instrument). */
static void curve(void *c, int tbl, int pos)
{
    int last_lo = 0, last_hi = 0;
    for (int x = 0; x < WR_WIDTH; x++) {
        int lo, hi;
        span(tbl, pos, x, &lo, &hi);
        if (hi - lo <= 2)                   /* a smooth stretch: one pixel, at its middle */
            lo = hi = (lo + hi) >> 1;
        column(c, WAVE_X + x, lo, hi);
        if (x > 0 && lo > last_hi)
            column(c, WAVE_X + x, last_hi + 1, lo);
        else if (x > 0 && hi < last_lo)
            column(c, WAVE_X + x, hi, last_lo - 1);
        last_lo = lo;
        last_hi = hi;
    }
}

/* W5: the value a place sounds at -- the live sound (the knob, or a p-lock while it
 * plays), plus the modulation once the audio tick has caught up -- and the knob's own
 * value in *set */
static int heard(void *view, u32 id, int *set)
{
    u8 flag;
    int v = GET_VALUE(view, id, &flag);
    *set = v;
#if WR_MARKERS
    int target = array_word(TARGETS, id);
    if (which(id) >= 0 && target >= 0)
        v = target;
    v += mod_offset(id);
#endif
    return v;
}

/* W5: TBL's value -> the table the SHARC plays, through the same table it uses */
static int table_of(int v)
{
    v >>= 8;
    if (v < 0) v = 0;
    if (v > 127) v = 127;
    return wr_slot[v];
}

/* W3: page 2's picture, osc 2's wave: as page 1's, without the modulation markers */
static void wave2(void *c, void *view)
{
    u8 f;
    int pos = clamp_pos(GET_VALUE(view, WR_POS2_ID, &f));
    curve(c, table_of(GET_VALUE(view, WR_TBL2_ID, &f)), pos);
    for (int x = 0; x < WR_WIDTH; x += 2)
        px(c, WAVE_X + x, POS_Y);
    int m = WAVE_X + pos * (WR_WIDTH - MARK) / WR_POS_MAX;
    for (int k = 0; k < MARK; k++)
        column(c, m + k, POS_Y, POS_Y + 1);
}

static void wave(void *c, void *view)
{
    int set_pos, set_tbl;
    int pos = heard(view, WR_POS_ID, &set_pos);
    int tbl = table_of(heard(view, WR_TBL_ID, &set_tbl));
#if WR_MARKERS
    int moved = pos - set_pos;
    int speed = tier(WR_POS_ID);
    set_pos = clamp_pos(set_pos);
#endif
    pos = clamp_pos(pos);

#if WR_MARKERS
    if (speed > 0) {
        /* Faster than the screen: the two frames at the ends of the sweep, drawn as
         * ordinary curves, with a sparse dotted fill between them (one pixel in
         * nine) -- the frames being heard lie in there. A dense 50 % envelope read
         * as too heavy on the panel (owner, modview4b). */
        int from = clamp_pos(set_pos + sweeps[0].lo), to = clamp_pos(set_pos + sweeps[0].hi);
        curve(c, tbl, from);
        curve(c, tbl, to);
        for (int x = 0; x < WR_WIDTH; x += 3) {
            int alo, ahi, blo, bhi;
            span(tbl, from, x, &alo, &ahi);
            span(tbl, to, x, &blo, &bhi);
            int y0, y1;                         /* the gap between the two curves */
            if (ahi < blo) { y0 = ahi; y1 = blo; }
            else if (bhi < alo) { y0 = bhi; y1 = alo; }
            else continue;                      /* they touch in this column */
            for (int y = y0 + 2; y <= y1 - 2; y++)
                if (y % 3 == 0)
                    px(c, WAVE_X + x, y);
        }
        for (int x = 0; x < WR_WIDTH; x += 2)
            px(c, WAVE_X + x, POS_Y);
        int a = WAVE_X + from * (WR_WIDTH - MARK) / WR_POS_MAX;
        int b = WAVE_X + to * (WR_WIDTH - MARK) / WR_POS_MAX + MARK - 1;
        for (int x = a; x <= b; x++)            /* the positions swept, under the bar */
            if ((x & 1) == 0)
                px(c, x, CURSOR_Y);
        int m = WAVE_X + set_pos * (WR_WIDTH - MARK) / WR_POS_MAX;
        for (int k = 0; k < MARK; k++)
            column(c, m + k, POS_Y, POS_Y + 1);
        return;
    }
#endif

    curve(c, tbl, pos);

    for (int x = 0; x < WR_WIDTH; x += 2)
        px(c, WAVE_X + x, POS_Y);
#if WR_MARKERS
    int m = WAVE_X + set_pos * (WR_WIDTH - MARK) / WR_POS_MAX;
    int h = WAVE_X + pos * (WR_WIDTH - MARK) / WR_POS_MAX;
    /* while POS is modulated at all (the range swept is wider than a step), even
     * as the cursor passes under the knob's own marker (owner, modview4f) */
    if (sweeps[0].hi - sweeps[0].lo > QUANT || moved >= QUANT || moved <= -QUANT)
        for (int k = 0; k < MARK; k += 2)
            px(c, h + k, CURSOR_Y);
#else
    int m = WAVE_X + pos * (WR_WIDTH - MARK) / WR_POS_MAX;
#endif
    for (int k = 0; k < MARK; k++)
        column(c, m + k, POS_Y, POS_Y + 1);
}

/* RESONATOR's picture across the middle: one vertical line a mode, at its pitch above
 * the note (STRC moves them from harmonic through a bar to a plate), its height the
 * mode's level at POS (sin(pi n POS), dnfw.rings.live), the first 24 within 4 octaves.
 * Integers only: the anchors in tenths of a semitone (res_anchor), a 64-step sine. */
static const unsigned char res_sin64[65] = {
    0, 6, 12, 19, 25, 31, 37, 43, 49, 54, 60, 65, 71, 76, 81, 85, 90, 94, 98, 102, 106, 109,
    112, 115, 117, 120, 122, 123, 125, 126, 126, 127, 127, 127, 126, 126, 125, 123, 122, 120,
    117, 115, 112, 109, 106, 102, 98, 94, 90, 85, 81, 76, 71, 65, 60, 54, 49, 43, 37, 31, 25,
    19, 12, 6, 0};

static int res_sin(int x)                       /* x in 1/128 of a half turn -> +-127 */
{
    x &= 255;
    int s = x < 128 ? 1 : -1;
    x &= 127;
    return s * res_sin64[x >> 1];
}

#define RES_SPAN 480                            /* tenths of a semitone across the picture */
#define RES_BASE 24                             /* canvas row of the baseline */
#define RES_TALL 12

static void modes(void *c, void *view)
{
    u8 flag;
    int st = GET_VALUE(view, 239, &flag);       /* STRC: WAV1, 0..0x7800 */
    int pos = GET_VALUE(view, 246, &flag);      /* POS: OFS1, 0..0x6400 */
    if (st < 0) st = 0;
    if (st > 0x7800) st = 0x7800;
    if (pos < 0) pos = 0;
    if (pos > 0x6400) pos = 0x6400;
    int a, frac;                                /* the anchor pair and 0..256 between them */
    if (st <= 0x3C00) { a = 0; frac = st * 256 / 0x3C00; }
    else { a = 1; frac = (st - 0x3C00) * 256 / 0x3C00; }
    int p = 2 + 48 * pos / 0x6400;              /* POS, in hundredths of a length: 2..50 */
    for (int x = 0; x < WR_WIDTH; x += 2)
        px(c, WAVE_X + x, RES_BASE);
    for (int n = 0; n < 24; n++) {
        int lo = res_anchor[a][n], hi = res_anchor[a + 1][n];
        int semi = lo + (hi - lo) * frac / 256;
        if (semi > RES_SPAN)
            break;
        int x = WAVE_X + semi * (WR_WIDTH - 1) / RES_SPAN;
        int amp = res_sin((n + 1) * p * 128 / 100);
        if (amp < 0) amp = -amp;
        int h = 1 + amp * RES_TALL / 127;
        column(c, x, RES_BASE + 1, RES_BASE + h);
    }
}

/* CZ (docs/cz.md). Page 1: the wave pair as the voice plays it with the DCW envelope
 * at its top (two cycles, the pair's first wave then its second, at DCW depth), and its
 * enumerated controls' values as text where their labels would be. Pages 2 and 3: the
 * DCW envelope, eight steps of (rate, level), the page's four steps solid and the
 * others dotted, a mark at the sustain step. Integers only: a phase in 1/256 turn, the
 * DCW in 1/256, res_sin's 64-step sine. dnfw.cz.live.wave is the sound; this is its
 * picture. */
static const char cz_wave_names[8][4] = {"SAW", "SQR", "PLS", "DBL", "SWP", "RS1", "RS2", "RS3"};
static const char cz_wave_short[8][3] = {"SW", "SQ", "PL", "DB", "SP", "R1", "R2", "R3"};
static const char cz_sel_names[4][5] = {"1", "2", "1+1'", "1+2'"};
static const char cz_oct_names[3][6] = {"OCT0", "OCT+1", "OCT-1"};
static const char cz_mod_names[3][6] = {"RING", "OFF", "NOISE"};
static const char cz_sus_names[9][6] = {"SUS1", "SUS2", "SUS3", "SUS4", "SUS5", "SUS6",
                                        "SUS7", "SUS8", "NOSUS"};

static int cz_get(void *view, u32 id)
{
    u8 flag;
    int v = GET_VALUE(view, id, &flag);
    const int *r = RECORD(id);
    return v < r[2] ? r[2] : v > r[3] ? r[3] : v;
}

static int cz_wave_index(void *view)        /* 0..32, as dnfw.cz.live.controls */
{
    int k = cz_get(view, 239) * 33 / 0x7800;
    return k > 32 ? 32 : k;
}

static int cz_knee(int x, int d)            /* phase bent at d: 0..d -> 0..128, d..256 -> 128..256 */
{
    return x < d ? x * 128 / d : 128 + (x - d) * 128 / (256 - d);
}

/* wave W at phase p (0..255) and DCW d (0..256) -> -127..127 */
static int cz_wave(int w, int p, int d)
{
    int f;
    if (w == 0) {
        f = cz_knee(p, 128 - 125 * d / 256);
    } else if (w == 1) {
        int wd = 128 - 125 * d / 256, h = p < 128 ? p : p - 128;
        int q = h * 128 / wd;
        f = (p < 128 ? 0 : 128) + (q > 128 ? 128 : q);
    } else if (w == 2) {
        int wd = 256 - 243 * d / 256;
        f = p * 256 / wd;
        if (f > 256) f = 256;
    } else if (w == 3) {
        f = p < 128 ? p * (256 + d) / 256 : 128 * (256 + d) / 256 + (p - 128) * (256 - d) / 256;
    } else if (w == 4) {
        int x = 2 * p > 256 ? 256 : 2 * p;
        int g = p < 128 ? cz_knee(x, 26) : 256;
        f = ((256 - d) * p + d * g) / 256;
    } else {
        int k = 256 + 15 * d;                   /* the resonance, harmonic 1..16, in 1/256 */
        int x = (k * p / 256) & 255;
        int r = (127 - res_sin(x + 64)) / 2;    /* 0..127 */
        int win = w == 5 ? 256 - p : w == 6 ? 256 - (2 * p > 256 ? 2 * p - 256 : 256 - 2 * p)
                : (2 * (256 - p) > 256 ? 256 : 2 * (256 - p));
        return r * win / 128 - 127;
    }
    return -res_sin(f + 64);
}

static void cz_wave_picture(void *c, void *view)
{
    int k = cz_wave_index(view);
    int d = cz_get(view, 241) * 256 / 0x7F00;   /* DCW depth, the envelope at its top */
    int half = WR_WIDTH / 2, last = 0;
    for (int x = 0; x < WR_WIDTH; x++) {
        int w = cz_combos[k][x < half ? 0 : 1];
        int p = (x % half) * 256 / half;
        int y = WAVE_CY + cz_wave(w, p, d) * WAVE_AMP / 127;
        if (x == 0 || x == half)
            column(c, WAVE_X + x, y, y);
        else
            column(c, WAVE_X + x, last, y);
        last = y;
    }
}

static int cz_99(void *view, u32 id)        /* a rate's or level's 0..99 */
{
    const int *r = RECORD(id);
    int span = r[3] - r[2];
    return span > 0 ? (cz_get(view, id) - r[2]) * 99 / span : 0;
}

static void cz_line(void *c, int x0, int y0, int x1, int y1, int dotted)
{
    int dx = x1 - x0, dy = y1 > y0 ? y1 - y0 : y0 - y1, sy = y1 > y0 ? 1 : -1;
    int err = dx - dy, n = 0;
    for (;;) {
        if (!dotted || (n++ & 1) == 0)
            px(c, x0, y0);
        if (x0 == x1 && y0 == y1)
            break;
        int e2 = 2 * err;
        if (e2 > -dy) { err -= dy; x0++; }
        if (e2 < dx) { err += dx; y0 += sy; }
    }
}

#define CZ_ENV_BASE 14
#define CZ_ENV_TALL 26

static void cz_envelope(void *c, void *view, int page)
{
    int wid[8], total = 0;
    for (int k = 0; k < 8; k++) {
        wid[k] = 3 + (99 - cz_99(view, cz_rate_ids[k])) / 6;   /* slower: wider */
        total += wid[k];
    }
    int sus = cz_get(view, 243) * 9 / 0x7800;
    int x = WAVE_X, y = CZ_ENV_BASE, used = 0;
    for (int k = 0; k < 8; k++) {
        used += wid[k];
        int nx = WAVE_X + used * (WR_WIDTH - 1) / total;
        int ny = CZ_ENV_BASE + cz_99(view, cz_level_ids[k]) * CZ_ENV_TALL / 99;
        cz_line(c, x, y, nx, ny, (k >> 2) != page - 1);
        if (k == sus)
            for (int yy = CZ_ENV_BASE; yy <= CZ_ENV_BASE + CZ_ENV_TALL; yy += 3)
                px(c, nx, yy);
        x = nx;
        y = ny;
    }
}

static const char *cz_text(void *view, u32 id, const char *label)
{
    static char pair[6] __attribute__((section(".data")));
    if (id == 239) {
        int k = cz_wave_index(view), a = cz_combos[k][0], b = cz_combos[k][1];
        if (a == b)
            return cz_wave_names[a];
        pair[0] = cz_wave_short[a][0]; pair[1] = cz_wave_short[a][1]; pair[2] = '+';
        pair[3] = cz_wave_short[b][0]; pair[4] = cz_wave_short[b][1]; pair[5] = 0;
        return pair;
    }
    int v = cz_get(view, id) >> 8;
    if (id == 248)
        return cz_sel_names[v > 3 ? 3 : v];
    if (id == 259)
        return cz_oct_names[v > 2 ? 2 : v];
    if (id == 249)
        return cz_mod_names[v > 2 ? 2 : v];
    if (id == 247)
        return v ? "KF ON" : "KFOFF";
    if (id == 243) {
        int k = cz_get(view, id) * 9 / 0x7800;
        return cz_sus_names[k > 8 ? 8 : k];
    }
    return label;
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
#ifdef WR_PROBE
    u32 t0 = DTCN0, tm = 0;
#endif
    int page = ((int (*)(void *))method(view, 132))(view);
    int kind = wr_active();
    int res = kind == 2;                        /* RESONATOR's page, not Waverider's */
    int cz = kind == 3;                         /* CZ's */
    if (page < 0 || page >= (cz ? CZ_PAGES : res ? RES_PAGES : WR_PAGES))
        page = 0;
#if WR_MARKERS
    u32 now = TICKS;
    settling = 0;
    drawn_sig = signature();
#endif

    if (cz && page == 0)
        cz_wave_picture(canvas, view);
    else if (cz)
        cz_envelope(canvas, view, page);
    else if (res)
        modes(canvas, view);
    else if (page == 1)
        wave2(canvas, view);
    else
        wave(canvas, view);

    for (int i = 0; i < 8; i++) {
        int top = i < 4;
        int cx = COL0 + COLW * (i & 3) + COLW / 2;
        u32 id = cz ? cz_ids[page][i] : res ? res_ids[page][i] : wr_ids[page][i];
        const char *label = cz ? cz_labels[page][i] : res ? res_labels[page][i] : wr_labels[page][i];
        if (cz) {
            label = cz_text(view, id, label);   /* CZ: page 1's values as text */
        } else if (res) {
            /* RESONATOR: plain labels */
        } else if (id == WR_TBL_ID) {                  /* W5: the table's name where TBL would be */
            int set_tbl;
            label = wr_table_names[table_of(heard(view, WR_TBL_ID, &set_tbl))];
        } else if (id == WR_TBL2_ID) {                 /* W3: osc 2's */
            u8 f;
            label = wr_table_names[table_of(GET_VALUE(view, id, &f))];
        } else if (id == WR_MOVE_ID) {          /* W2: the scanner's shape where MOVE would be */
            u8 f;
            int v = GET_VALUE(view, id, &f) >> 8;
            label = wr_shape_names[((v < 0 ? 0 : v > 127 ? 127 : v) * 8) >> 7];
        }
        TEXT(canvas, FONT, cx, top ? TOP_LABEL_Y : BOT_LABEL_Y, CENTRED, "%.5s", label);
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
