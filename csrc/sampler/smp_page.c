/* The sample machines' SRC page, after the Digitakt II's own (v0.15, docs/sampler.md).
 *
 *   ONESHOT, GRID: the top row's four widgets (TUNE, PLAY, the dotted box, SAMP), the
 *   sample's waveform across the middle with its markers, and the bottom row's labels.
 *   WERP, STRETCH, REPITCH: the two rows of widgets and labels, as the DT2 draws them.
 *
 * Drawn with our own widgets in the DT2's shapes (its widget classes are not in the DN2):
 * the bipolar box, the play-mode icon, the dotted empty box, the SAMP box (an inverted
 * bank letter and the slot), the knob, the fader, the segment ring and the bars.
 * Entered from page.c's wr_page_draw for a sample machine's track; page.c then draws the
 * stock grid's own tail (the level meter on the left and the page dots).
 *
 * Canvas: 128 x 64, y counting up from the bottom. The cells are the stock grid's:
 * columns at x 25 + 26 k, 24 wide; widgets in y 34..51 (top) and 7..24 (bottom), their
 * labels at y 27 and 0.
 */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned char u8;

#define GET_VALUE ((int (*)(void *, u32, u8 *))0x4006538E)
#define SET_PIXEL ((void (*)(void *, int, int, int))0x40113B90)
#define TEXT      ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545C)
#define FONT      0x44507ED8u
#define CENTRED   2
#define RECORD(id) ((const int *)(0x401F7F94u + 60u * (id)))
#define NAME_SHORT(id) (*(const char **)(0x401F7F94u + 60u * (id) + 0x30u))

#define CELL_X(k) (25 + 26 * (k))
#define TOP_Y 34
#define BOT_Y 7

extern int smp_count(void);
extern const char *smp_name(int k);
extern int smp_entry(int k, u32 *off, u32 *frames, u32 *fmt);
extern int smp_frame(u32 off, u32 fmt, u32 i);

static void on(void *c, int x, int y) { SET_PIXEL(c, x, y, 1); }

static void hline(void *c, int x0, int x1, int y, int dotted)
{
    for (int x = x0; x <= x1; x++)
        if (!dotted || ((x - x0) & 1) == 0)
            on(c, x, y);
}

static void vline(void *c, int x, int y0, int y1, int dotted)
{
    if (y0 > y1) { int t = y0; y0 = y1; y1 = t; }
    for (int y = y0; y <= y1; y++)
        if (!dotted || ((y - y0) & 1) == 0)
            on(c, x, y);
}

/* a rectangle with its corners cut (the DT2's rounded boxes), solid or dotted */
static void box(void *c, int x0, int y0, int x1, int y1, int dotted)
{
    hline(c, x0 + 1, x1 - 1, y0, dotted);
    hline(c, x0 + 1, x1 - 1, y1, dotted);
    vline(c, x0, y0 + 1, y1 - 1, dotted);
    vline(c, x1, y0 + 1, y1 - 1, dotted);
}

static void fill(void *c, int x0, int y0, int x1, int y1)
{
    for (int y = y0; y <= y1; y++)
        hline(c, x0, x1, y, 0);
}

/* the 3x5 glyphs (src/dnfw/font3x5.json), lit or cut out of a filled area */
static void glyph(void *c, int x, int y, char ch, int lit)
{
    for (int k = 0; smp_glyph_chars[k]; k++)
        if (smp_glyph_chars[k] == ch) {
            for (int r = 0; r < 5; r++)
                for (int b = 0; b < 3; b++)
                    if (smp_glyph[k][r] & (4 >> b))
                        SET_PIXEL(c, x + b, y + 4 - r, lit);
            return;
        }
}

/* a control's 0..top value, as the DSP reads it (dnfw.sampler.program.ctl), and its top */
static int value(void *view, u32 id, int *top)
{
    u8 flag;
    int v = GET_VALUE(view, id, &flag) >> 8;
    const int *r = RECORD(id);
    int lo = r[2] >> 8, t = (r[3] >> 8) - lo;
    v -= lo;
    if (top)
        *top = t;
    return v < 0 ? 0 : v > t ? t : v;
}

static int widget_of(u32 id, int kind)
{
    if (kind == SMP_GRID_KIND && id == SMP_GRID_ID)
        return W_BARS;                          /* GRID: the slice count, drawn as bars */
    if (kind == SMP_GRID_KIND && id == SMP_SLEN_ID)
        return W_KNOB;
    for (int k = 0; k < SMP_WIDGETS; k++)
        if (smp_widget_ids[k] == id)
            return smp_widget_kind[k];
    return W_NONE;
}

/* a small sine from the CZ page's table: x in 1/256 turn -> -127..127 */
static int sin256(int x)
{
    static const signed char q[17] = {0, 12, 25, 37, 49, 60, 71, 81, 90, 98, 106, 112, 117,
                                      122, 125, 126, 127};
    x &= 255;
    int s = x < 128 ? 1 : -1;
    x &= 127;
    int i = x < 64 ? x : 128 - x;               /* 0..64 */
    int a = q[i >> 2], b = q[(i >> 2) + (i < 64 ? 1 : 0)];
    return s * (a + (b - a) * (i & 3) / 4);
}

/* the play-mode icon (PLAY, and WERP's MODE): FWD |->|, REV |<-|, the loops a loop */
static void w_play(void *c, int x, int y, int mode)
{
    int cy = y + 8, x0 = x + 5, x1 = x + 18;
    if (mode == 3 || mode == 0) {
        vline(c, x0, cy - 4, cy + 4, 0);
        vline(c, x1, cy - 4, cy + 4, 0);
        hline(c, x0, x1, cy, 0);
        int tip = mode == 3 ? x1 - 1 : x0 + 1, d = mode == 3 ? -1 : 1;
        for (int k = 1; k <= 3; k++) {
            on(c, tip + d * k, cy + k);
            on(c, tip + d * k, cy - k);
        }
    } else {                                    /* a loop of arrows, F or R beside it */
        hline(c, x0 + 2, x0 + 8, cy + 4, 0);
        hline(c, x0 + 2, x0 + 8, cy - 4, 0);
        vline(c, x0, cy - 2, cy + 2, 0);
        vline(c, x0 + 10, cy - 2, cy + 2, 0);
        on(c, x0 + 1, cy + 3); on(c, x0 + 9, cy + 3); on(c, x0 + 1, cy - 3); on(c, x0 + 9, cy - 3);
        int ax = mode == 2 ? x0 + 7 : x0 + 3, d = mode == 2 ? -1 : 1;
        on(c, ax + d, cy + 5); on(c, ax + d, cy + 3);
        TEXT(c, FONT, x0 + 15, cy - 3, 0, "%c", mode == 2 ? 'F' : 'R');
    }
}

static void w_bipolar(void *c, int x, int y, int v, int top)
{
    int x0 = x + 1, x1 = x + 22, y0 = y + 4, y1 = y + 12;
    box(c, x0, y0, x1, y1, 0);
    hline(c, x0 + 2, x1 - 2, (y0 + y1) / 2, 1);
    int cx = (x0 + x1) / 2;
    vline(c, cx, y0 + 2, y1 - 2, 0);
    int at = x0 + 2 + v * (x1 - x0 - 4) / (top ? top : 1);
    vline(c, at, y0 + 1, y1 - 1, 0);
    vline(c, at + (at < cx ? 1 : -1), y0 + 1, y1 - 1, 0);
}

static void w_empty(void *c, int x, int y)
{
    box(c, x + 3, y + 3, x + 20, y + 13, 1);
}

static void w_samp(void *c, int x, int y, int slot)
{
    int x0 = x + 1, x1 = x + 22, y0 = y + 3, y1 = y + 13;
    fill(c, x0, y0, x0 + 8, y1);                /* the bank letter, cut out */
    box(c, x0, y0, x1, y1, 0);
    glyph(c, x0 + 3, y0 + 3, 'A', 0);
    if (slot == 0) {
        TEXT(c, FONT, x0 + 16, y0 + 2, CENTRED, "OFF");
        return;
    }
    char d[4];
    int n = 0;
    if (slot >= 100) d[n++] = '0' + slot / 100;
    if (slot >= 10) d[n++] = '0' + slot / 10 % 10;
    d[n++] = '0' + slot % 10;
    int gx = x0 + 11 + (3 - n) * 2;
    for (int k = 0; k < n; k++)
        glyph(c, gx + 4 * k, y0 + 3, d[k], 1);
}

static void w_knob(void *c, int x, int y, int v, int top)
{
    int cx = x + 12, cy = y + 8, r = 7;
    for (int a = 0; a < 256; a += 6) {          /* the ring, open at the bottom */
        if (a > 96 && a < 160)
            continue;
        on(c, cx + sin256(a) * r / 127, cy + sin256(a + 64) * r / 127);
    }
    int ang = 160 + v * 192 / (top ? top : 1);  /* 7 o'clock .. 5 o'clock, clockwise */
    for (int k = 0; k <= r - 1; k++)
        on(c, cx + sin256(ang) * k / 127, cy + sin256(ang + 64) * k / 127);
}

static void w_fader(void *c, int x, int y, int v, int top)
{
    int x0 = x + 9, x1 = x + 14, y0 = y + 1, y1 = y + 16;
    box(c, x0, y0, x1, y1, 0);
    int h = v * (y1 - y0 - 2) / (top ? top : 1);
    fill(c, x0 + 2, y0 + 1, x1 - 2, y0 + 1 + h);
}

/* a level as the DT2's ONESHOT shows it on its bottom row: a pill, filled to the value */
static void w_pill(void *c, int x, int y, int v, int top)
{
    int x0 = x + 1, x1 = x + 22, y0 = y + 1, y1 = y + 6;
    box(c, x0, y0, x1, y1, 0);
    int w = v * (x1 - x0 - 3) / (top ? top : 1);
    fill(c, x0 + 2, y0 + 2, x0 + 2 + w, y1 - 2);
}

static void w_seg(void *c, int x, int y, int n)
{
    int cx = x + 12, cy = y + 12;
    for (int a = 0; a < 256; a += 16)           /* a ring of segments */
        on(c, cx + sin256(a) * 3 / 127, cy + sin256(a + 64) * 3 / 127);
    on(c, cx - 6, cy); on(c, cx + 6, cy);
    if (n > 1)
        TEXT(c, FONT, cx, y + 1, CENTRED, "1/%d", n);
    else
        TEXT(c, FONT, cx, y + 1, CENTRED, "1");
}

static void w_bars(void *c, int x, int y, int idx, const char *text)
{
    for (int k = 0; k < 4; k++) {               /* four blocks, lit to the value's place */
        int bx = x + 4 + 4 * k;
        if (k <= idx / 2)
            fill(c, bx, y + 12, bx + 2, y + 14);
        else
            box(c, bx, y + 12, bx + 2, y + 14, 0);
    }
    TEXT(c, FONT, x + 12, y + 1, CENTRED, "%s", text);
}

static int steps_index(int v, const unsigned char *steps)
{
    int k = 0;
    while (k < 7 && v >= steps[k])
        k++;
    return k;
}

/* one cell: its widget at (X, Y) and, LABELLED, its label under it */
static void cell(void *c, void *view, int kind, u32 id, int x, int y, int labelled, int pill)
{
    int top, v, w = id ? widget_of(id, kind) : W_EMPTY;
    if (id)
        v = value(view, id, &top);
    else
        v = top = 0;
    const char *label = id ? NAME_SHORT(id) : "";
    if (w == W_BIPOLAR)
        w_bipolar(c, x, y, v, top);
    else if (w == W_PLAY)
        w_play(c, x, y, v * 4 / 128 > 3 ? 3 : v * 4 / 128);
    else if (w == W_EMPTY)
        w_empty(c, x, y);
    else if (w == W_SAMP)
        w_samp(c, x, y, v);
    else if (w == W_KNOB)
        w_knob(c, x, y, v, top);
    else if (w == W_FADER) {
        if (pill)
            w_pill(c, x, y, v, top);
        else
            w_fader(c, x, y, v, top);
    } else if (w == W_SEG)
        w_seg(c, x, y, 128 >> steps_index(v, smp_seg_steps));
    else if (w == W_BARS) {
        if (kind == SMP_GRID_KIND && id == SMP_GRID_ID) {
            static char g[4] __attribute__((section(".data")));
            int gi = v / 24, n = smp_grids[gi > 4 ? 4 : gi];
            g[0] = n >= 10 ? '0' + n / 10 : '0' + n;
            g[1] = n >= 10 ? '0' + n % 10 : 0;
            g[2] = 0;
            w_bars(c, x, y, gi * 2, g);
        } else {
            int bi = steps_index(v, smp_bars_steps);
            w_bars(c, x, y, bi, smp_bars[bi]);
        }
    }
    if (labelled && id)
        TEXT(c, FONT, x + 12, y - 7, CENTRED, "%.4s", label);
}

/* the waveform strip: the slot's sound, peak per column, from X0 across SMP_WAVE_W at
 * CY; 0 drawn if the slot is off or empty (a flat dotted line) */
static void waveform(void *c, int slot, int x0, int cy)
{
    u32 off, frames, fmt;
    int test = smp_count() < 0 && slot >= 1 && slot <= SMP_SOUNDS;
    int have = !test && slot >= 1 && smp_entry(slot - 1, &off, &frames, &fmt) && frames > 1;
    if (!test && !have) {
        hline(c, x0, x0 + SMP_WAVE_W - 1, cy, 1);
        return;
    }
    for (int k = 0; k < SMP_WAVE_W; k++) {
        int h;
        if (test) {
            h = smp_test_wave[slot - 1][k];
        } else {
            u32 a = (u32)k * frames / SMP_WAVE_W, b = (u32)(k + 1) * frames / SMP_WAVE_W;
            if (b <= a) b = a + 1;
            u32 step = (b - a) / 16 + 1;
            int peak = 0;
            for (u32 i = a; i < b; i += step) {
                int s = smp_frame(off, fmt, i);
                if (s < 0) s = -s;
                if (s > peak) peak = s;
            }
            h = peak * SMP_WAVE_AMP / 32767;
        }
        vline(c, x0 + k, cy - h, cy + h, 0);
    }
}

/* a marker over the strip: a solid line (start, end) or a dotted one (loop) */
static void marker(void *c, int x, int cy, int dotted)
{
    vline(c, x, cy - SMP_WAVE_AMP - 2, cy + SMP_WAVE_AMP + 2, dotted);
    if (!dotted) {
        on(c, x - 1, cy + SMP_WAVE_AMP + 2);
        on(c, x + 1, cy + SMP_WAVE_AMP + 2);
    }
}

void smp_page_draw(void *view, void *c, int kind)
{
    u32 ids[8];
    for (int i = 0; i < 8; i++)
        ids[i] = smp_ids[kind - SMP_KIND0][i];
    int strip = kind == SMP_KIND0 || kind == SMP_GRID_KIND;      /* ONESHOT, GRID */
    if (!strip) {
        for (int i = 0; i < 8; i++)
            cell(c, view, kind, ids[i], CELL_X(i & 3), i < 4 ? TOP_Y : BOT_Y, 1, 0);
        return;
    }
    /* the top row, unlabelled, raised a little; the strip; the bottom labels */
    for (int i = 0; i < 4; i++)
        cell(c, view, kind, ids[i], CELL_X(i), TOP_Y + 4, 0, 0);
    int slot = value(view, SMP_SAMP_ID, 0);
    int x0 = CELL_X(0) - 1, cy = 21;
    waveform(c, slot, x0, cy);
    int w = SMP_WAVE_W;
    if (kind == SMP_GRID_KIND) {
        int gi = value(view, SMP_GRID_ID, 0) / 24, n = smp_grids[gi > 4 ? 4 : gi];
        int s = (value(view, SMP_SLICE_ID, 0) >> 1) & (n - 1);
        int len = (value(view, SMP_SLEN_ID, 0) >> 1) + 1;
        for (int j = 0; j <= n && n <= 32; j++)
            vline(c, x0 + j * (w - 1) / n, cy - SMP_WAVE_AMP - 1, cy - SMP_WAVE_AMP + 1, 0);
        int a = x0 + s * (w - 1) / n, b = x0 + (s + len > n ? n : s + len) * (w - 1) / n;
        marker(c, a, cy, 0);
        marker(c, b, cy, 0);
    } else {
        int a = value(view, SMP_STRT_ID, 0) * (w - 1) / 120;
        int b = a + value(view, SMP_LEN_ID, 0) * (w - 1) / 127;
        if (b > w - 1) b = w - 1;
        int lp = value(view, SMP_LOOP_ID, 0) * (w - 1) / 127;
        marker(c, x0 + a, cy, 0);
        marker(c, x0 + b, cy, 0);
        int mode = value(view, SMP_PLAY_ID, 0) * 4 / 128;
        if (mode == 1 || mode == 2)
            marker(c, x0 + lp, cy, 1);
    }
    /* the bottom row: E, F, G's labels, H's level as the DT2's pill */
    for (int i = 4; i < 7; i++)
        if (ids[i])
            TEXT(c, FONT, CELL_X(i - 4) + 12, 0, CENTRED, "%.4s", NAME_SHORT(ids[i]));
    if (ids[7]) {
        int top, v = value(view, ids[7], &top);
        w_pill(c, CELL_X(3), 0, v, top);
    }
}
