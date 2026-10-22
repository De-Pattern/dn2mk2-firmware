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
    return m >= 5 && m <= 12 ? m - 4 : 0;
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

/* the UI loop's redraw test, as stock (and the names kept current, once a loop; and
 * v0.15: the sample link's +Drive copy loaded once the device is up) */
extern void smp_boot(void);

int wr_poll(void *screen)
{
    smp_boot();
    wr_names();
    ping_names();
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
    if (id == SMP_SEG_ID) {                     /* segments: 128 >> index */
        int v = smp_get(view, id), k = 0;
        while (k < 7 && v >= smp_seg_steps[k])
            k++;
        int n = 128 >> k;
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
        int n = 128 >> j;
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
    int res = kind == 2;                        /* RESONATOR's page */
    int cz = kind == 3;                         /* CZ's */
    int smp = kind >= SMP_KIND0;                /* a sample machine's: one page */
    if (page < 0 || page >= (smp ? 1 : cz ? CZ_PAGES : res ? RES_PAGES : WR_PAGES))
        page = 0;
    if (kind == 1) {                            /* PERC: the names TYPE has now */
        u8 flag;
        perc_seen = perc_of(GET_VALUE(view, PERC_TYPE_ID, &flag));
    }
    wr_names();

    if (smp) {                                  /* v0.15: the DT2's own SRC page */
        extern void smp_page_draw(void *view, void *canvas, int kind);
        smp_page_draw(view, canvas, kind);
        ((void (*)(void *, void *, int))method(view, 184))(view, canvas, 0);
        return;
    }
    if (cz && page == 0)
        cz_wave_picture(canvas, view);
    else if (cz)
        cz_envelope(canvas, view, page);
    else if (res)
        modes(canvas, view);
    else if (smp)
        smp_picture(canvas, view, kind);
    else
        perc_picture(canvas, view);

    for (int i = 0; i < 8; i++) {
        int top = i < 4;
        int cx = COL0 + COLW * (i & 3) + COLW / 2;
        u32 id = smp ? smp_ids[kind - SMP_KIND0][i] : cz ? cz_ids[page][i] : res ? res_ids[page][i]
                 : wr_ids[page][i];
        const char *label = smp ? "-" : cz ? cz_labels[page][i] : res ? res_labels[page][i]
                            : wr_labels[page][i];
        if (cz)
            label = cz_text(view, id, label);   /* CZ: page 1's values as text */
        else if (!res && id)
            label = NAME_SHORT(id);             /* PERC, samples: the name wr_names gave the record */
        if (smp && id)
            label = smp_text(view, id, kind, label);
        TEXT(canvas, FONT, cx, top ? TOP_LABEL_Y : BOT_LABEL_Y, CENTRED, "%.5s", label);
        if (!id || (!res && !cz && label[0] == '-' && !label[1]))
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
