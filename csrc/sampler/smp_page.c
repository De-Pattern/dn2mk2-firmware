/* The sample machines' SRC page, after the Digitakt II's own (v0.15, docs/sampler.md).
 *
 *   ONESHOT, GRID: the top row's four widgets (TUNE, PLAY, the dotted box, SAMP), the
 *   sample's waveform across the middle with its markers, and the bottom row's labels.
 *   WERP, STRETCH, REPITCH: the two rows of widgets and labels, as the DT2 draws them.
 *
 * Drawn with our own widgets in the DT2's shapes (its widget classes are not in the DN2):
 * the bipolar box, the play-mode icon, the dotted empty box, the SAMP box (an inverted
 * bank letter and the slot), the knob, the fader, the segment ring and the bars.
 * Page 2, the recorder (smp_rec_draw): REC, SRC, THRS on top, RLEN and DEST below.
 *
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
typedef unsigned short u16;

#define GET_VALUE ((int (*)(void *, u32, u8 *))0x4006538E)
#define SET_PIXEL ((void (*)(void *, int, int, int))0x40113B90)
#define TEXT      ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545C)
#define FONT      0x44507ED8u
#define LABEL_FONT 0x40291760u                  /* the stock grid's 4 x 5 label font: the DT2's labels' */
/* the stock grid's label text (0x40115668, as 0x4006448a calls it for each cell's name):
 * (canvas, font, x, y, align 1 centred, frame 0 none, width template 0, format, ...) */
#define LABEL_TEXT ((void (*)(void *, u32, int, int, int, int, const char *, const char *, ...))0x40115668u)
#define LABEL(c, x, y, fmt, ...) LABEL_TEXT((c), LABEL_FONT, (x), (y), 1, 0, 0, fmt, __VA_ARGS__)
#define CENTRED   2
#define RECORD(id) ((const int *)(0x401F7F94u + 60u * (id)))
#define NAME_SHORT(id) (*(const char **)(0x401F7F94u + 60u * (id) + 0x30u))

#define CELL_X(k) (21 + 26 * (k))         /* v0.20: the DT2's centres, 33 + 26 k (its own screen, measured) */
#define TOP_Y 34
#define BOT_Y 7

extern int smp_count(void);
extern int smp_slot_empty(int k);
extern int smp_lstate;                  /* link.c: 0 idle, 4 done, else loading */
extern const char *smp_name(int k);
extern const u8 *smp_overview(int k);    /* 100 column peaks, 0..255 (link.c, v0.16) */
extern const u8 *smp_slices(int k, int *n);   /* v0.19: SLICE's starts as columns (link.c) */

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
    if ((kind == SMP_GRID_KIND || kind == SMP_SLICE_KIND) && id == SMP_SLEN_ID)
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

/* v0.20: the widgets in the DT2's own geometry, measured from its SRC page (OS 1.17 in
 * the emulator, digikit): a cell is 26 wide, centred at X + 12; a widget 17 rows tall from
 * Y; its label 7 below, in the 4 x 5 label font. */

/* the play-mode icon (PLAY, and WERP's MODE): FWD |->|, REV |<-|, the loops a loop */
static void w_play(void *c, int x, int y, int mode)
{
    int cx = x + 12, cy = y + 8, x0 = cx - 8, x1 = cx + 8;
    if (mode == 3 || mode == 0) {
        vline(c, x0, y + 2, y + 14, 0);
        vline(c, x1, y + 2, y + 14, 0);
        int fwd = mode == 3;                    /* PLAY_MODES: REV, REVL, FWDL, FWD */
        hline(c, fwd ? x0 : x0 + 2, fwd ? x1 - 2 : x1, cy, 0);
        int tip = fwd ? cx + 4 : cx - 4, d = fwd ? 1 : -1;
        vline(c, tip, cy - 2, cy + 2, 0);
        vline(c, tip + d, cy - 1, cy + 1, 0);
    } else {                                    /* a loop of arrows, F or R beside it */
        int lx = cx - 7;
        hline(c, lx + 2, lx + 8, cy + 4, 0);
        hline(c, lx + 2, lx + 8, cy - 4, 0);
        vline(c, lx, cy - 2, cy + 2, 0);
        vline(c, lx + 10, cy - 2, cy + 2, 0);
        on(c, lx + 1, cy + 3); on(c, lx + 9, cy + 3); on(c, lx + 1, cy - 3); on(c, lx + 9, cy - 3);
        int ax = mode == 2 ? lx + 7 : lx + 3, d = mode == 2 ? -1 : 1;
        on(c, ax + d, cy + 5); on(c, ax + d, cy + 3);
        LABEL(c, lx + 15, cy - 2, "%c", mode == 2 ? 'F' : 'R');
    }
}

static void w_bipolar(void *c, int x, int y, int v, int top)
{
    /* the DT2's TUNE: a box 21 x 15 with a tick at the middle of its top and bottom, the
     * value in the middle */
    int cx = x + 12, x0 = cx - 10, x1 = cx + 10, y0 = y + 1, y1 = y + 15;
    box(c, x0, y0, x1, y1, 0);
    vline(c, cx, y1 - 2, y1 - 1, 0);
    vline(c, cx, y0 + 1, y0 + 2, 0);
    int semis = v - top / 2;
    if (semis == 0)
        LABEL(c, cx + 1, y + 6, "%s", "0");
    else
        LABEL(c, cx + 1, y + 6, "%c%d", semis < 0 ? '-' : '+', semis < 0 ? -semis : semis);
}

static void w_empty(void *c, int x, int y)
{
    int cx = x + 12;                            /* the DT2's empty place: a dotted square */
    for (int k = -7; k <= 7; k += 2) {
        on(c, cx + k, y);
        on(c, cx + k, y + 16);
    }
    for (int r = 1; r <= 15; r += 2) {
        on(c, cx - 8, y + r);
        on(c, cx + 8, y + r);
    }
}

static void w_samp(void *c, int x, int y, int slot)
{
    /* the DT2's SAMP: a box 22 x 15, its left seven columns filled with the bank letter
     * cut out, the slot's number on the right */
    int cx = x + 12, x0 = cx - 10, x1 = cx + 10, y0 = y + 1, y1 = y + 15;
    hline(c, x0 + 1, x1 - 1, y0, 0);
    hline(c, x0 + 1, x1 - 1, y1, 0);
    vline(c, x1, y0 + 1, y1 - 1, 0);
    fill(c, x0, y0 + 1, x0 + 6, y1 - 1);
    /* the bank letter, cut out: the DT2's flat-topped A */
    static const unsigned char bank_a[5] = {7, 5, 7, 5, 5};      /* rows top..bottom, bit 2 = left */
    for (int r = 0; r < 5; r++)
        for (int b = 0; b < 3; b++)
            if (bank_a[r] & (4 >> b))
                SET_PIXEL(c, x0 + 2 + b, y + 10 - r, 0);
    if (slot == 0) {                            /* OFF: two dashes */
        glyph(c, cx + 0, y + 6, '-', 1);
        glyph(c, cx + 4, y + 6, '-', 1);
        return;
    }
    char d[4];
    int n = 0;
    if (slot >= 100) d[n++] = '0' + slot / 100;
    if (slot >= 10) d[n++] = '0' + slot / 10 % 10;
    d[n++] = '0' + slot % 10;
    int gx = cx + 2 - 2 * (n - 1);
    for (int k = 0; k < n; k++)
        glyph(c, gx + 4 * k, y + 6, d[k], 1);
}

/* the DT2's knob: a circle of radius 8 (its own pixels, by row from the centre) */
static const signed char knob_x[9][2] = {
    {8, 8}, {8, 8}, {8, 8}, {7, 7}, {7, 7}, {6, 6}, {5, 5}, {3, 4}, {0, 2}};

static void w_knob_ring(void *c, int cx, int cy)
{
    for (int r = 0; r <= 8; r++) {
        int a = knob_x[r][0], b = knob_x[r][1];
        for (int k = a; k <= b; k++) {
            on(c, cx - k, cy + r); on(c, cx + k, cy + r);
            on(c, cx - k, cy - r); on(c, cx + k, cy - r);
        }
    }
}

static void w_knob_at(void *c, int x, int y, int v, int top, int dotted)
{
    int cx = x + 12, cy = y + 8;
    w_knob_ring(c, cx, cy);
    int ang = 160 + v * 192 / (top ? top : 1);  /* 7 o'clock .. 5 o'clock, clockwise */
    /* the pointer: a line from the centre, 7 long (at 7:30, five steps on the diagonal,
     * as the DT2's); dotted, every other point of it */
    int ex = (sin256(ang) * 7 + (sin256(ang) < 0 ? -63 : 63)) / 127;
    int ey = (sin256(ang + 64) * 7 + (sin256(ang + 64) < 0 ? -63 : 63)) / 127;
    int dx = ex < 0 ? -ex : ex, dy = ey < 0 ? -ey : ey, sx = ex < 0 ? -1 : 1, sy = ey < 0 ? -1 : 1;
    int err = dx - dy, px = 0, py = 0;
    for (int k = 0; k < 16; k++) {
        if (!dotted || !(k & 1))
            on(c, cx + px, cy + py);
        if (px == ex && py == ey)
            break;
        int e2 = 2 * err;
        if (e2 > -dy) { err -= dy; px += sx; }
        if (e2 < dx) { err += dx; py += sy; }
    }
}

static void w_fader(void *c, int x, int y, int v, int top)
{
    /* the DT2's level fader: a 9 x 17 outline, filled from the bottom; two marks at its top */
    int cx = x + 12, x0 = cx - 4, x1 = cx + 4;
    hline(c, x0 + 1, x1 - 1, y, 0);
    hline(c, x0 + 1, x1 - 1, y + 16, 0);
    vline(c, x0, y + 1, y + 15, 0);
    vline(c, x1, y + 1, y + 15, 0);
    on(c, cx - 2, y + 14);
    on(c, cx + 2, y + 14);
    int h = top ? (v * 13 + top - 1) / top : 0;
    if (h > 13) h = 13;
    if (h > 0)
        fill(c, cx - 2, y + 2, cx + 2, y + 1 + h);
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
    /* the DT2's segment icon: a filled dot between two brackets, then 1/n */
    int cx = x + 12, cy = y + 12;
    fill(c, cx - 1, cy - 1, cx + 1, cy + 1);
    on(c, cx - 2, cy); on(c, cx + 2, cy); on(c, cx, cy + 2); on(c, cx, cy - 2);
    vline(c, cx - 5, cy - 1, cy + 1, 0); on(c, cx - 4, cy + 2); on(c, cx - 4, cy - 2);
    vline(c, cx + 5, cy - 1, cy + 1, 0); on(c, cx + 4, cy + 2); on(c, cx + 4, cy - 2);
    if (n > 1)
        TEXT(c, FONT, cx, y + 1, CENTRED, "1/%d", n);
    else
        TEXT(c, FONT, cx, y + 1, CENTRED, "1");
}

static void w_bars(void *c, int x, int y, int idx, const char *text)
{
    /* the DT2's BARS icon: 1, 2 or 4 blocks (v0.18: BARS 1, 2, 4, 8; 8 is four too) */
    int n = idx == 0 ? 1 : idx == 1 ? 2 : 4;
    int w = 12;
    int gap = n > 1 ? 2 : 0, each = (w - gap * (n - 1)) / n;
    int x0 = x + 12 - w / 2;
    for (int k = 0; k < n; k++)
        fill(c, x0 + k * (each + gap), y + 11, x0 + k * (each + gap) + each - 1, y + 13);
    TEXT(c, FONT, x + 12, y + 1, CENTRED, "%s", text);
}

static int steps_index(int v, const unsigned char *steps)
{
    int k = 0;
    while (k < 7 && v >= steps[k])
        k++;
    return k;
}

/* v0.22, GRID's and SLICE's own widgets, as the DT2 draws them: SLCE a keyboard while
 * NOTE picks the slice, else the slice's number; LEN the slices it plays on, under a
 * bracket; GRID a grid of four squares (its count is in the header as it turns) */
static void w_slce(void *c, int x, int y, int s)
{
    int cx = x + 12;
    if (s <= 0) {                               /* NOTE: three white keys, two black */
        box(c, cx - 7, y + 3, cx + 7, y + 13, 0);
        vline(c, cx - 2, y + 4, y + 12, 0);
        vline(c, cx + 2, y + 4, y + 12, 0);
        fill(c, cx - 4, y + 8, cx - 3, y + 12);
        fill(c, cx + 3, y + 8, cx + 4, y + 12);
        return;
    }
    LABEL(c, cx, y + 6, "%d", s);
}

static void w_slen(void *c, int x, int y, int n)
{
    int cx = x + 12;
    hline(c, cx - 7, cx + 7, y + 13, 0);        /* the bracket |----| */
    vline(c, cx - 7, y + 11, y + 15, 0);
    vline(c, cx + 7, y + 11, y + 15, 0);
    LABEL(c, cx, y + 4, "%d", n);
}

/* v0.25: GRID's icon as the DT2 draws it: the slice count as a grid of cells (2: 2 x 1,
 * 4: 2 x 2, 8: 4 x 2, 16: 4 x 4, 32: 8 x 4, 64: 8 x 8) in a 16 x 16 square */
static void w_gridicon(void *c, int x, int y, int n)
{
    int cx = x + 12, cols = 1, rows = 1;
    while (cols * rows < n) {
        if (cols <= rows) cols *= 2; else rows *= 2;
    }
    int w = 16 / cols, h = 16 / rows, x0 = cx - 8, y0 = y;
    for (int r = 0; r < rows; r++)
        for (int k = 0; k < cols; k++) {
            int a = x0 + k * w, b = y0 + r * h;
            if (w > 2 && h > 2)
                fill(c, a, b, a + w - 2, b + h - 2);
            else
                on(c, a, b);
        }
}

/* v0.27: a p-locked control drawn as stock draws it, its cell inverted (owner's photo: a
 * trig held, its locked parameters lit). The stock getter's flag (0x4006538e's third
 * argument) is what the stock grid (0x40017498) tests to draw a cell highlighted. The
 * canvas, as 0x40113b90 reads it: +4 width, +8 height, +12 words a column, +16 the bits
 * (a column's words, bit 31 - (y & 31) of word y >> 5). */
static int locked(void *view, u32 id)
{
    u8 flag = 0;
    if (!id)
        return 0;
    (void)GET_VALUE(view, id, &flag);
    return flag != 0;
}

static void invert(void *c, int x0, int y0, int x1, int y1)
{
    const int *cv = (const int *)c;
    u32 *bits = (u32 *)cv[4];
    for (int x = x0; x <= x1; x++)
        for (int y = y0; y <= y1; y++)
            if (x >= 0 && y >= 0 && x < cv[1] && y < cv[2] && y <= 53)
                bits[x * cv[3] + (y >> 5)] ^= 0x80000000u >> (y & 31);
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
    int sliced = kind == SMP_GRID_KIND || kind == SMP_SLICE_KIND;
    if (sliced && id == SMP_SLICE_ID)
        w_slce(c, x, y, v >> 1);                /* 0 NOTE, 1..63 */
    else if (sliced && id == SMP_SLEN_ID)
        w_slen(c, x, y, (v >> 1) + 1);
    else if (kind == SMP_GRID_KIND && id == SMP_GRID_ID) {
        int gi = v / 24;
        w_gridicon(c, x, y, smp_grids[gi > 4 ? 4 : gi]);
    }
    else if (w == W_BIPOLAR)
        w_bipolar(c, x, y, v, top);
    else if (w == W_PLAY)
        w_play(c, x, y, v * 4 / 128 > 3 ? 3 : v * 4 / 128);
    else if (w == W_EMPTY)
        w_empty(c, x, y);
    else if (w == W_SAMP)
        w_samp(c, x, y, v);
    else if (w == W_KNOB) {
        /* LOOP's pointer dotted while PLAY does not loop, as the DT2 draws it */
        int mode = kind == SMP_KIND0 && id == SMP_LOOP_ID ? value(view, SMP_PLAY_ID, 0) * 4 / 128 : 1;
        w_knob_at(c, x, y, v, top, mode != 1 && mode != 2);
    }
    else if (w == W_FADER) {
        if (pill)
            w_pill(c, x, y, v, top);
        else
            w_fader(c, x, y, v, top);
    } else if (w == W_SEG)
        w_seg(c, x, y, 32 >> steps_index(v, smp_seg_steps));    /* v0.18: a segment, 1/32 .. 1/8 */
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
        LABEL(c, x + 12, y - 7, "%.4s", label);
    if (locked(view, id))
        invert(c, x - 1, y - 8, x + 24, y + 19);
}

/* v0.20: RESONATOR's and CZ's first pages (page.c), as the Elektron grid: eight knobs at
 * the DT2's centres, each its label under it; an empty place (id 0) is left empty */
void smp_knob_page(void *view, void *c, const unsigned short *ids, const char *const *labels,
                   const char *const *texts)
{
    for (int i = 0; i < 8; i++) {
        int x = CELL_X(i & 3), y = i < 4 ? TOP_Y : BOT_Y;
        if (!ids[i])
            continue;
        if (texts[i]) {                         /* a choice: its name in a box, as the DT2's */
            int cx = x + 12;
            box(c, cx - 11, y + 3, cx + 11, y + 13, 0);
            LABEL(c, cx, y + 6, "%.5s", texts[i]);
        } else {
            int top, v = value(view, ids[i], &top);
            w_knob_at(c, x, y, v, top, 0);
        }
        LABEL(c, x + 12, y - 7, "%.5s", labels[i]);
    }
}

/* the waveform strip: the slot's sound, peak per column, from X0 across SMP_WAVE_W at
 * CY; 0 drawn if the slot is off or empty (a flat dotted line) */
static void waveform(void *c, int slot, int x0, int cy)
{
    /* v0.20: no test sounds any more (gone from the DSP since v0.17): a slot with nothing
     * loaded says so, rather than showing a wave that does not play */
    const u8 *ov = slot >= 1 ? smp_overview(slot - 1) : 0;
    if (!ov) {
        hline(c, x0, x0 + SMP_WAVE_W - 1, cy, 1);
        int bx = x0 + SMP_WAVE_W / 2;
        for (int y = cy - 4; y <= cy + 4; y++)
            for (int x = bx - 24; x <= bx + 24; x++)
                SET_PIXEL(c, x, y, 0);
        int named = slot >= 1 && slot <= smp_count() && smp_name(slot - 1)[0];
        int loading = named && smp_lstate != 0 && smp_lstate != 4;
        extern u32 smp_walk, smp_walk_total;    /* v0.31: how far the pool's load is */
        static char pc[12] __attribute__((section(".data")));
        if (loading && smp_walk_total) {
            u32 p = smp_walk_total > 0x01000000u ? smp_walk / (smp_walk_total / 100u)
                                                 : smp_walk * 100u / smp_walk_total;
            if (p > 99u)
                p = 99u;
            const char *w = "LOADING ";
            int i = 0;
            while (w[i]) { pc[i] = w[i]; i++; }
            if (p >= 10u)
                pc[i++] = (char)('0' + p / 10u);
            pc[i++] = (char)('0' + p % 10u);
            pc[i++] = '%';
            pc[i] = 0;
        }
        TEXT(c, FONT, bx, cy - 3, CENTRED, slot < 1 ? "OFF"
             : loading ? (smp_walk_total ? pc : "LOADING") : "EMPTY");
        return;
    }
    for (int k = 0; k < SMP_WAVE_W; k++) {
        int h = ov[k * 100 / SMP_WAVE_W] * SMP_WAVE_AMP / 255;
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

/* v0.25: the playhead, as the DT2 draws it over the strip: a double line where the voice
 * is reading (the DSP sends each track's position every block, link.c), cleared either
 * side so it reads over the wave */
extern int smp_playhead(int t);
#define UI_TRACK (*(volatile u8 *)0x42431A6Cu)

static u32 ph_drawn_at __attribute__((section(".data"))) = 0;    /* the waveform page's last draw */
static int ph_was __attribute__((section(".data"))) = -1;         /* the playhead it drew (-1 none) */

/* the UI loop asks (page.c's wr_poll): the waveform page is up and its playhead moves, or
 * has just stopped (one more draw clears it) */
int smp_wants_redraw(void)
{
    u32 now = *(volatile u32 *)0x4058E8D4u;
    if (now - ph_drawn_at > 1800u)              /* not drawn for over a second: not up (FRAMES: ~1500 a second) */
        return 0;
    int ph = smp_playhead(UI_TRACK);
    return ph >= 0 || ph_was >= 0;
}

static void playhead(void *c, int x0, int w, int cy)
{
    int ph = smp_playhead(UI_TRACK);
    ph_drawn_at = *(volatile u32 *)0x4058E8D4u;
    ph_was = ph;
    if (ph < 0)
        return;
    int x = x0 + (int)((unsigned)ph * (unsigned)(w - 2) / POS_ONE);
    for (int y = cy - SMP_WAVE_AMP - 1; y <= cy + SMP_WAVE_AMP + 1; y++) {
        SET_PIXEL(c, x - 1, y, 0);
        SET_PIXEL(c, x, y, 1);
        SET_PIXEL(c, x + 1, y, 0);
        SET_PIXEL(c, x + 2, y, 1);
        SET_PIXEL(c, x + 3, y, 0);
    }
}

/* the machine box at the left, as the DT2 labels it: SMP over the page number (the stock
 * page draws SYN there; its letters are overwritten in the same 3 x 6 hand) */
static void smp_box(void *c)
{
    static const char *g[3][6] = {
        {".##", "#..", "##.", ".##", "..#", "##."},             /* S */
        {"#.#", "###", "###", "#.#", "#.#", "#.#"},             /* M */
        {"##.", "#.#", "#.#", "##.", "#..", "#.."},             /* P */
    };
    for (int k = 0; k < 3; k++)
        for (int r = 0; r < 6; r++)
            for (int b = 0; b < 3; b++)
                SET_PIXEL(c, 2 + 4 * k + b, 48 - r, g[k][r][b] == '#');
}

/* a small icon for WERP's waveform page, as the DT2 draws its bottom row there */
static void mini_seg(void *c, int x, int y)
{
    vline(c, x + 6, y + 1, y + 5, 0);
    vline(c, x + 17, y + 1, y + 5, 0);
    hline(c, x + 6, x + 17, y + 3, 0);
}

static void mini_mode(void *c, int x, int y, int mode)
{
    vline(c, x + 5, y + 1, y + 5, 0);
    hline(c, x + 5, x + 14, y + 3, 1);
    on(c, x + 13, y + 4); on(c, x + 13, y + 2);
    TEXT(c, FONT, x + 18, y, CENTRED, "%c", mode == 0 || mode == 1 ? 'R' : 'F');
}

/* v0.25: the sample list as the DT2's (its manual 9.7): turning SAMP brings it up over the
 * right of the page, and it stays: SAMP (or UP / DOWN) moves through the slots -- the
 * track plays the one outlined, so its [TRIG] previews it -- YES keeps it, NO puts SAMP
 * back as it was, FUNC + YES opens the folder browser (ASSIGN SAMPLE, below). Pushing
 * SAMP keeps it too, and a page key closes it as YES does. Its keys are rec.c's
 * (smp_ui_pop). Long names and folders come from the import tool (link.c's meta). */
extern const char *smp_long_name(int k);
extern int smp_folder_count(void);
extern const char *smp_folder_name(int f);
extern int smp_folder_of(int k);
#define LIST_IDLE 30000u                         /* FRAMES (~1500 a second): 20 s untouched, it closes */
int smp_lst_open __attribute__((section(".data"))) = 0;
int smp_lst_orig __attribute__((section(".data"))) = 0;   /* SAMP when it came up */
void *smp_list_view __attribute__((section(".data"))) = 0;   /* the page it is on */
static int list_slot __attribute__((section(".data"))) = -1;
static u32 list_at __attribute__((section(".data"))) = 0;
int smp_overlay_dirty __attribute__((section(".data"))) = 0;   /* page.c's wr_poll redraws */

static void slot_name(int k, char *out, int max)   /* SAMP value K (0 OFF) */
{
    const char *n = 0;
    int cnt = smp_count();
    if (k <= 0)
        n = "OFF";
    else if (cnt >= 0 && k <= cnt && !smp_slot_empty(k - 1))
        n = smp_long_name(k - 1);
    if (k > 0 && !(n && n[0]) && !smp_slot_empty(k - 1))
        n = "SAMPLE";                           /* something there, without a name (v0.15's recordings) */
    if (!(n && n[0]))
        n = "---";                              /* the DT2's empty slot */
    int j = 0;
    for (; j < max && n[j]; j++)
        out[j] = n[j];
    out[j] = 0;
}

/* the list is up on VIEW's page (rec.c's key filter asks) */
int smp_list_up(void *view)
{
    return smp_lst_open && view == smp_list_view;
}

void smp_list_hold(void)
{
    list_at = *(volatile u32 *)0x4058E8D4u;
    smp_overlay_dirty = 1;
}

void smp_list_close(void)
{
    smp_lst_open = 0;
    smp_overlay_dirty = 1;
}

/* closed with SAMP set to V by us (NO, the browser): that change does not bring it back */
void smp_list_settle(int v)
{
    list_slot = v;
    smp_list_close();
}

static void num3(char *o, int k)
{
    o[0] = (char)('0' + k / 100 % 10);
    o[1] = (char)('0' + k / 10 % 10);
    o[2] = (char)('0' + k % 10);
    o[3] = 0;
}

static void scrollbar(void *c, int x, int y0, int y1, int at, int n)
{
    vline(c, x, y0, y1, 1);
    if (n <= 1)
        return;
    int h = y1 - y0 + 1, th = h / 6 < 3 ? 3 : h / 6;
    int ty = y1 - (h - th) * at / (n - 1) - th + 1;
    fill(c, x - 1, ty, x + 1, ty + th - 1);
}

static u32 lst_seen_at __attribute__((section(".data"))) = 0;    /* the page under it, last drawn */

u32 smp_samp_turned __attribute__((section(".data"))) = 0x80000000u;   /* when SAMP was last turned (fmt.c) */
static int list_trk __attribute__((section(".data"))) = -1;     /* the track it last saw */
static int list_kind __attribute__((section(".data"))) = -1;    /* and its machine */

static void sample_list(void *c, void *view, int slot, int kind)
{
    (void)c;
    u32 now = *(volatile u32 *)0x4058E8D4u;
    lst_seen_at = now;
    int trk = UI_TRACK;
    /* first sight of this page, another track or another machine: SAMP's value is taken as it is, and no
     * list comes up -- only turning SAMP brings it (v0.26: switching to a sample track
     * opened it, as its SAMP differed from the last track's) */
    if (view != smp_list_view || list_slot < 0 || trk != list_trk || kind != list_kind) {
        smp_list_view = view;
        list_slot = slot;
        list_trk = trk;
        list_kind = kind;
        smp_lst_open = 0;
        return;
    }
    if (slot != list_slot) {
        /* v0.27: only a turn of SAMP brings the list; a value set otherwise (TRACK + PLAY's
         * clear, a project or sound loaded) is taken as it is (owner: clearing a sample track
         * opened the list) */
        int turned = smp_samp_turned != 0x80000000u && now - smp_samp_turned < 3000u;
        smp_samp_turned = 0x80000000u;          /* one turn, one change */
        if (!smp_lst_open && !turned) {
            list_slot = slot;
            return;
        }
        if (!smp_lst_open) {
            smp_lst_open = 1;
            smp_lst_orig = list_slot;
            smp_overlay_dirty = 1;
        }
        list_slot = slot;
        list_at = now;
    }
    if (smp_lst_open && now - list_at >= LIST_IDLE) {   /* left alone: kept, as YES */
        smp_lst_open = 0;
        smp_overlay_dirty = 1;
    }
}

/* v0.33: the list belongs to the track it opened on. Another track active (its page drawn
 * by stock, or not yet drawn) means it is gone: it must not go on taking keys unseen */
int smp_list_elsewhere(void)
{
    return smp_lst_open && list_trk >= 0 && UI_TRACK != list_trk;
}

/* the list over the screen (page.c's wr_screen, after the page and its title bar): the
 * DT2's header in the title bar, the bank, five slots around SAMP's, the scroll bar */
int smp_list_visible(void)
{
    u32 now = *(volatile u32 *)0x4058E8D4u;
    return smp_lst_open && now - lst_seen_at < 3000u;
}

void smp_list_draw(void *c)
{
    int slot = list_slot < 0 ? 0 : list_slot;
    int x0 = 26, x1 = 127;
    for (int y = 0; y <= 63; y++)
        for (int x = x0; x <= x1; x++)
            SET_PIXEL(c, x, y, 0);
    vline(c, x0, 0, 54, 0);
    for (int y = 55; y <= 63; y++)              /* the title bar's name: the header goes there */
        for (int x = 15; x < x0; x++)
            SET_PIXEL(c, x, y, 0);
    /* the title bar: what YES, NO and FUNC + YES do, as the DT2 writes it there */
    LABEL(c, x0 + 51, 57, "%s", "YES:OK NO:X FN+YES:D");
    hline(c, x0 + 1, x1, 55, 0);
    /* the bank: the DN2 has the one bank of 128 */
    LABEL(c, x0 + 51, 47, "%s", "A");
    box(c, x0 + 45, 45, x0 + 57, 53, 0);
    /* five slots around the chosen one, it outlined */
    for (int r = 0; r < 5; r++) {
        int k = slot - 2 + r, y = 36 - 9 * r;
        if (k < 0 || k > 127)
            continue;
        char nm[19], num[4];
        slot_name(k, nm, 18);
        num3(num, k);
        TEXT(c, FONT, x0 + 3, y, 0, "%s", num);
        TEXT(c, FONT, x0 + 23, y, 0, "%s", nm);
        if (k == slot)
            box(c, x0 + 1, y - 2, x1 - 4, y + 7, 0);
    }
    scrollbar(c, x1 - 1, 1, 43, slot, 128);
}

/* -- v0.25: the folder browser (ASSIGN SAMPLE), FUNC + YES in the list, as the DT2's +Drive
 * browser (its manual 13.6): folders only at the top -- the import tool's, then INCOMING
 * (what was sent in no folder) and RECORDED (the recorder's) -- and a folder's samples
 * inside it, each with the slot it plays from (>A009), as the DT2 marks a loaded sample.
 * YES opens a folder, or ticks a sample (v0.33, in PROJECT RAM too, as the DT2's 13.6.2; it
 * gave the track the sample before); NO goes back up, and out at the top. RIGHT on a sample opens the SAMPLE ACTION menu: LOAD TO TRK,
 * RENAME, DELETE (asked first). Every sample is in RAM from power-on, so the DT2's LOAD
 * TO PROJECT has nothing to do here. Over the whole screen (page.c's wr_screen). */
extern int smp_is_recording(int k);
#define FB_INCOMING (-2)
#define FB_RECORDED (-3)
int smp_fb_open __attribute__((section(".data"))) = 0;
int smp_fb_folder __attribute__((section(".data"))) = -1;   /* -1 the top */
int smp_fb_cur __attribute__((section(".data"))) = 0;
int smp_fb_menu __attribute__((section(".data"))) = 0;      /* the SAMPLE ACTION menu: 0 shut, 1 up, 2 DELETE asked */
int smp_fb_mcur __attribute__((section(".data"))) = 0;
/* v0.29: multi-select (zugada_'s report: no way to delete all the samples sent in). FUNC +
 * YES marks a sample, or every sample of a folder at the top; SELECT ALL in the SAMPLE
 * ACTION menu marks the folder's; DELETE takes the marked ones if any, else the sample (or,
 * on a folder, the folder's samples). Marks last until the browser closes. */
static u32 fb_marks[4] __attribute__((section(".data"))) = {0, 0, 0, 0};
/* v0.31: the browser's two stores, as the DT2's SAMPLES menu (docs/drive-library-plan.md):
 * -1 the top (+DRIVE, PROJECT RAM), 0 PROJECT RAM (the pool, as before), 1 +DRIVE (the
 * library, lib.c). In +DRIVE an item's "slot" is a library entry. */
int smp_fb_store __attribute__((section(".data"))) = -1;
int smp_fb_last_store __attribute__((section(".data"))) = 0;   /* where the top's cursor lands (PROJECT RAM until +DRIVE is used) */
#define FB_DRIVE (-4)
#define FB_RAM (-5)
#define LB_CAP 2048
static u32 lb_marks[LB_CAP / 32] __attribute__((section(".data")));
extern int smp_lib_used(int k), smp_lib_folder_of(int k), smp_lib_slot_of(int k);
extern const char *smp_lib_name(int k), *smp_lib_folder_name(int f);
extern int smp_lib_delete(int k), smp_lib_load(int k), smp_lib_pending(void);

static int lb_in(int k, int folder) { return smp_lib_used(k) && smp_lib_folder_of(k) == folder; }

extern int smp_lib_folder_count(int f);
static int lb_has(int folder) { return smp_lib_folder_count(folder) > 0; }

static int lb_marked(int k) { return k >= 0 && k < LB_CAP && ((lb_marks[k >> 5] >> (k & 31)) & 1u); }

static void lb_mark(int k, int on)
{
    if (k < 0 || k >= LB_CAP)
        return;
    u32 b = 1u << (k & 31);
    if (on)
        lb_marks[k >> 5] |= b;
    else
        lb_marks[k >> 5] &= ~b;
}

static int fb_in(int k, int folder)              /* slot K (holding something) shows in FOLDER */
{
    int f = smp_folder_of(k);
    if (folder == FB_RECORDED)
        return f < 0 && smp_is_recording(k);
    if (folder == FB_INCOMING)
        return f < 0 && !smp_is_recording(k);
    return f == folder;
}

static int fb_has(int folder)
{
    for (int k = 0; k < 128; k++)
        if (!smp_slot_empty(k) && fb_in(k, folder))
            return 1;
    return 0;
}

int smp_fb_marked(int k)
{
    if (smp_fb_store == 1)
        return lb_marked(k);
    return k >= 0 && k < 128 && ((fb_marks[k >> 5] >> (k & 31)) & 1u);
}

void smp_fb_mark(int k, int on)
{
    if (smp_fb_store == 1) {
        lb_mark(k, on);
        return;
    }
    if (k < 0 || k >= 128)
        return;
    u32 b = 1u << (k & 31);
    if (on)
        fb_marks[k >> 5] |= b;
    else
        fb_marks[k >> 5] &= ~b;
}

extern int smp_fb_moving;
void smp_fb_unmark_all(void)
{
    smp_fb_moving = 0;
    for (int i = 0; i < 4; i++)
        fb_marks[i] = 0;
    for (int i = 0; i < LB_CAP / 32; i++)
        lb_marks[i] = 0;
}

int smp_fb_mark_count(void)
{
    int n = 0;
    if (smp_fb_store == 1) {
        for (int k = 0; k < LB_CAP; k++)
            n += lb_marked(k) && smp_lib_used(k);
        return n;
    }
    for (int k = 0; k < 128; k++)
        if (smp_fb_marked(k) && !smp_slot_empty(k))
            n++;
    return n;
}

/* FOLDER's samples: how many, and how many of them marked */
static int fb_size(int folder, int *marked)
{
    int n = 0, m = 0;
    if (smp_fb_store == 1) {
        for (int k = 0; k < LB_CAP; k++)
            if (lb_in(k, folder)) {
                n++;
                m += lb_marked(k);
            }
        if (marked)
            *marked = m;
        return n;
    }
    for (int k = 0; k < 128; k++)
        if (!smp_slot_empty(k) && fb_in(k, folder)) {
            n++;
            m += smp_fb_marked(k);
        }
    if (marked)
        *marked = m;
    return n;
}

/* every sample of FOLDER marked, or (all of them marked already) none */
void smp_fb_mark_folder(int folder)
{
    int m, n = fb_size(folder, &m), on = m < n;
    if (smp_fb_store == 1) {
        for (int k = 0; k < LB_CAP; k++)
            if (lb_in(k, folder))
                lb_mark(k, on);
        return;
    }
    for (int k = 0; k < 128; k++)
        if (!smp_slot_empty(k) && fb_in(k, folder))
            smp_fb_mark(k, on);
}

int smp_fb_folder_full(int folder)              /* every one of its samples marked */
{
    int m, n = fb_size(folder, &m);
    return n > 0 && m == n;
}

/* what DELETE takes: the marked samples, else SLOT, else FOLDER's samples */
int smp_fb_delete_count(int slot, int folder)
{
    int n = smp_fb_mark_count();
    if (n)
        return n;
    return slot >= 0 ? 1 : folder != -1 ? fb_size(folder, 0) : 0;
}

extern void smp_discard(int k);
void smp_fb_delete(int slot, int folder)
{
    if (smp_fb_store == 1) {                    /* v0.31: from the +Drive's library */
        if (smp_fb_mark_count()) {
            for (int k = 0; k < LB_CAP; k++)
                if (lb_marked(k) && smp_lib_used(k))
                    smp_lib_delete(k);
        } else if (slot >= 0)
            smp_lib_delete(slot);
        else if (folder != -1)
            for (int k = 0; k < LB_CAP; k++)
                if (lb_in(k, folder))
                    smp_lib_delete(k);
        smp_fb_unmark_all();
        return;
    }
    if (smp_fb_mark_count()) {
        for (int k = 0; k < 128; k++)
            if (smp_fb_marked(k) && !smp_slot_empty(k))
                smp_discard(k);
    } else if (slot >= 0)
        smp_discard(slot);
    else if (folder != -1)
        for (int k = 0; k < 128; k++)
            if (!smp_slot_empty(k) && fb_in(k, folder))
                smp_discard(k);
    smp_fb_unmark_all();
}

int smp_fb_load_project(int slot, int folder)
{
    int n = 0;
    if (smp_fb_store != 1)
        return 0;
    if (smp_fb_mark_count()) {
        for (int k = 0; k < LB_CAP; k++)
            if (lb_marked(k) && smp_lib_used(k))
                n += smp_lib_load(k) == 0;
    } else if (slot >= 0)
        n += smp_lib_load(slot) == 0;
    else if (folder != -1)
        for (int k = 0; k < LB_CAP; k++)
            if (lb_in(k, folder))
                n += smp_lib_load(k) == 0;
    smp_fb_unmark_all();
    return n;
}

/* the browser's items where it is: N of them; item I as a folder (-> its index, or
 * FB_INCOMING / FB_RECORDED; *slot -1) or a sample (-> -1, *slot its slot) */
/* v0.33: a +DRIVE folder's samples, listed once (Pablo: slowdowns with a large library; the
 * browser walked all 2,048 entries for its count and again for each of its six rows, every
 * redraw). Rebuilt when the folder or the library's index changes. */
extern u32 smp_lib_rev;
static u16 lb_list[LB_CAP] __attribute__((section(".data")));
static int lb_list_n __attribute__((section(".data"))) = 0;
static int lb_list_folder __attribute__((section(".data"))) = -100;
static u32 lb_list_rev __attribute__((section(".data"))) = 0xFFFFFFFFu;

static void lb_list_make(void)
{
    if (lb_list_folder == smp_fb_folder && lb_list_rev == smp_lib_rev)
        return;
    lb_list_n = 0;
    for (int k = 0; k < LB_CAP; k++)
        if (lb_in(k, smp_fb_folder))
            lb_list[lb_list_n++] = (u16)k;
    lb_list_folder = smp_fb_folder;
    lb_list_rev = smp_lib_rev;
}

int smp_fb_count(void)
{
    int n = 0;
    if (smp_fb_store == -1)
        return 2;                               /* v0.31: +DRIVE, PROJECT RAM */
    if (smp_fb_store == 1) {
        if (smp_fb_folder == -1) {
            for (int f = 0; f < 64; f++)
                n += lb_has(f);
            return n;
        }
        lb_list_make();
        return lb_list_n;
    }
    if (smp_fb_folder == -1) {                  /* v0.29: a folder emptied by DELETE is not shown */
        for (int f = 0; f < smp_folder_count(); f++)
            n += fb_has(f);
        return n + fb_has(FB_INCOMING) + fb_has(FB_RECORDED);
    }
    for (int k = 0; k < 128; k++)
        if (!smp_slot_empty(k) && fb_in(k, smp_fb_folder))
            n++;
    return n;
}

int smp_fb_item(int i, int *slot)
{
    *slot = -1;
    if (smp_fb_store == -1)
        return i == 0 ? FB_DRIVE : i == 1 ? FB_RAM : -1;
    if (smp_fb_store == 1) {
        if (smp_fb_folder == -1) {
            for (int f = 0; f < 64; f++)
                if (lb_has(f) && i-- == 0)
                    return f;
            return -1;
        }
        lb_list_make();
        if (i >= 0 && i < lb_list_n)
            *slot = lb_list[i];
        return -1;
    }
    if (smp_fb_folder == -1) {
        for (int f = 0; f < smp_folder_count(); f++)
            if (fb_has(f) && i-- == 0)
                return f;
        if (fb_has(FB_INCOMING) && i-- == 0)
            return FB_INCOMING;
        if (fb_has(FB_RECORDED) && i == 0)
            return FB_RECORDED;
        return -1;
    }
    for (int k = 0; k < 128; k++)
        if (!smp_slot_empty(k) && fb_in(k, smp_fb_folder) && i-- == 0) {
            *slot = k;
            return -1;
        }
    return -1;
}

/* the top's item that is folder F (to land on it coming back up) */
int smp_fb_index_of(int f)
{
    int keep = smp_fb_folder, n, slot;
    smp_fb_folder = -1;
    n = smp_fb_count();
    for (int i = 0; i < n; i++)
        if (smp_fb_item(i, &slot) == f && slot < 0) {
            smp_fb_folder = keep;
            return i;
        }
    smp_fb_folder = keep;
    return 0;
}

static const char *fb_folder_name(int f)
{
    if (f == FB_DRIVE)
        return "+DRIVE";
    if (f == FB_RAM)
        return "PROJECT RAM";
    if (smp_fb_store == 1)
        return smp_lib_folder_name(f);
    return f == FB_INCOMING ? "incoming" : f == FB_RECORDED ? "recorded" : smp_folder_name(f);
}

static void folder_icon(void *c, int x, int y)
{
    box(c, x, y, x + 8, y + 5, 0);
    hline(c, x + 1, x + 3, y + 6, 0);
    fill(c, x + 1, y + 1, x + 7, y + 4);
}

int smp_fb_visible(void)
{
    return smp_fb_open;
}

/* the SAMPLE ACTION menu: on a sample LOAD TRK n, RENAME, DELETE, SELECT ALL; on a folder
 * (v0.29) SELECT ALL, DELETE */
/* v0.33: +DRIVE's MOVE SELECTED (the ticked samples remembered), then MOVE HERE in the
 * folder they go to; CREATE FOLDER (the DT2's 13.6.5) */
int smp_fb_moving __attribute__((section(".data"))) = 0;

static int lib_actions(int on_folder, signed char *out)
{
    int n = 0;
    out[n++] = 4;                               /* LOAD TO PROJ */
    if (!on_folder)
        out[n++] = 0;                           /* LOAD TRK */
    out[n++] = 3;                               /* SELECT ALL */
    if (smp_fb_moving)
        out[n++] = 6;                           /* MOVE HERE */
    else if (!on_folder)
        out[n++] = 5;                           /* MOVE SELECTED */
    out[n++] = 2;                               /* DELETE */
    out[n++] = 7;                               /* CREATE FOLDER */
    return n;
}

int smp_fb_nactions(int on_folder)
{
    signed char a[8];
    if (smp_fb_store == 1)
        return lib_actions(on_folder, a);
    return on_folder ? 2 : 4;
}

/* the action at place A of the SAMPLE ACTION menu: 0 LOAD TO TRK, 1 RENAME, 2 DELETE (in
 * PROJECT RAM: UNLOAD), 3 SELECT ALL, 4 LOAD TO PROJECT (v0.31: +DRIVE), 5 MOVE SELECTED,
 * 6 MOVE HERE, 7 CREATE FOLDER (v0.33: +DRIVE) */
int smp_fb_action(int on_folder, int a)
{
    static const signed char ram_s[4] = {0, 1, 2, 3}, ram_f[2] = {3, 2};
    if (smp_fb_store == 1) {
        signed char l[8];
        int n = lib_actions(on_folder, l);
        return l[a < 0 ? 0 : a > n - 1 ? n - 1 : a];
    }
    return on_folder ? ram_f[a < 0 ? 0 : a > 1 ? 1 : a] : ram_s[a < 0 ? 0 : a > 3 ? 3 : a];
}

void smp_fb_draw(void *c, int samp)
{
    for (int y = 0; y <= 63; y++)
        for (int x = 0; x <= 127; x++)
            SET_PIXEL(c, x, y, 0);
    char num[4];
    num3(num, samp);
    int marks = smp_fb_mark_count(), pend = smp_lib_pending();
    if (pend)                                   /* v0.31: LOAD TO PROJECT under way */
        LABEL(c, 64, 57, "LOADING TO PROJECT %d", pend);
    else if (marks)
        LABEL(c, 64, 57, "%d SELECTED", marks);
    else if (smp_fb_store == -1)
        LABEL(c, 64, 57, "%s", "SAMPLES");
    else if (smp_fb_folder == -1 && smp_fb_store == 1)
        LABEL(c, 64, 57, "%s", "+DRIVE");
    else if (smp_fb_folder == -1)
        LABEL(c, 64, 57, "ASSIGN SAMPLE > A%s", num);
    else {
        folder_icon(c, 2, 57);
        LABEL(c, 64, 57, "%.22s", fb_folder_name(smp_fb_folder));
    }
    hline(c, 0, 127, 55, 0);
    int n = smp_fb_count();
    if (n == 0) {
        TEXT(c, FONT, 64, 28, CENTRED, "%s", smp_fb_store == 1 ? "+DRIVE EMPTY" : "NO SAMPLES");
        return;
    }
    if (smp_fb_cur >= n)
        smp_fb_cur = n - 1;
    if (smp_fb_cur < 0)
        smp_fb_cur = 0;
    int top = smp_fb_cur - 2;
    if (top > n - 6)
        top = n - 6;
    if (top < 0)
        top = 0;
    int wide = smp_fb_menu ? 62 : 123;          /* the action menu takes the right half */
    for (int r = 0; r < 6 && top + r < n; r++) {
        int i = top + r, y = 46 - 9 * r, slot;
        int f = smp_fb_item(i, &slot);
        if (slot < 0) {
            TEXT(c, FONT, 3, y, 0, smp_fb_menu ? "%.9s" : "%.18s", fb_folder_name(f));
            if (!smp_fb_menu)
                folder_icon(c, 112, y);
            if (smp_fb_folder_full(f))          /* v0.29: every sample in it marked */
                invert(c, 1, y - 1, wide - 1, y + 6);
        } else if (smp_fb_store == 1) {         /* v0.31: a library sample; its slot if in the pool */
            char sn[4];
            int s = smp_lib_slot_of(slot);
            TEXT(c, FONT, 3, y, 0, smp_fb_menu ? "%.9s" : "%.18s", smp_lib_name(slot));
            if (!smp_fb_menu && s >= 0) {
                num3(sn, s + 1);
                LABEL(c, 109, y, ">A%s", sn);
            }
            if (smp_fb_marked(slot))
                invert(c, 2, y - 1, wide - 1, y + 6);
        } else {
            char nm[21], sn[4];
            slot_name(slot + 1, nm, smp_fb_menu ? 9 : 14);
            TEXT(c, FONT, 3, y, 0, "%s", nm);
            if (!smp_fb_menu) {
                num3(sn, slot + 1);
                LABEL(c, 109, y, ">A%s", sn);  /* the slot it plays from */
                if (slot + 1 == samp)
                    fill(c, 0, y, 1, y + 4);   /* the track's own */
            }
            if (smp_fb_marked(slot))            /* v0.29: marked, drawn lit */
                invert(c, 2, y - 1, wide - 1, y + 6);
        }
        if (i == smp_fb_cur)
            box(c, 0, y - 2, wide, y + 7, 0);
    }
    scrollbar(c, 126, 1, 53, smp_fb_cur, n);
    if (smp_fb_menu) {                          /* SAMPLE ACTION, as the DT2's: a list at the right */
        for (int y = 0; y <= 54; y++)
            for (int x = 65; x <= 124; x++)
                SET_PIXEL(c, x, y, 0);
        vline(c, 65, 0, 54, 1);
        int slot, f = smp_fb_item(smp_fb_cur, &slot), on_folder = slot < 0;
        int del = smp_fb_delete_count(slot, f);
        if (smp_fb_menu == 2) {
            const char *w = smp_fb_store == 1 ? "DELETE" : "UNLOAD";   /* v0.31: the pool's is UNLOAD */
            if (del == 1)
                TEXT(c, FONT, 95, 38, CENTRED, "%s?", w);
            else
                TEXT(c, FONT, 95, 38, CENTRED, "%s %d?", w, del);
            LABEL(c, 95, 24, "%s", "YES / NO");
            return;
        }
        int all = smp_fb_folder_full(on_folder ? f : smp_fb_folder);
        for (int a = 0; a < smp_fb_nactions(on_folder); a++) {
            int y = 46 - 9 * a;
            int act = smp_fb_action(on_folder, a);
            const char *w = smp_fb_store == 1 ? "DELETE" : "UNLOAD";
            if (act == 4)
                TEXT(c, FONT, 68, y, 0, "%s", "LOAD TO PROJ");
            else if (act == 0)
                TEXT(c, FONT, 68, y, 0, "LOAD TRK %d", (int)UI_TRACK + 1);
            else if (act == 1)
                TEXT(c, FONT, 68, y, 0, "%s", "RENAME");
            else if (act == 5)
                TEXT(c, FONT, 68, y, 0, "%s", "MOVE SELECT");
            else if (act == 6)
                TEXT(c, FONT, 68, y, 0, "%s", "MOVE HERE");
            else if (act == 7)
                TEXT(c, FONT, 68, y, 0, "%s", "NEW FOLDER");
            else if (act == 2) {
                if (del > 1)
                    TEXT(c, FONT, 68, y, 0, "%s %d", w, del);
                else
                    TEXT(c, FONT, 68, y, 0, "%s", w);
            } else
                TEXT(c, FONT, 68, y, 0, "%s", all ? "CLEAR ALL" : "SELECT ALL");
            if (a == smp_fb_mcur)
                box(c, 66, y - 2, 124, y + 7, 0);
        }
    }
}

void smp_page_draw(void *view, void *c, int kind, int wave)
{
    u32 ids[8];
    extern int slc_page_seen;
    slc_page_seen = kind == SMP_SLICE_KIND ? 1 : kind == SMP_GRID_KIND ? 2 : 0;   /* YES: SLICE's menu, GRID's ALLOCATE SLICE (slice.c) */
    for (int i = 0; i < 8; i++)
        ids[i] = smp_ids[kind - SMP_KIND0][i];
    smp_box(c);
    if (!wave) {                                /* page 1: the widgets and their labels */
        for (int i = 0; i < 8; i++)
            cell(c, view, kind, ids[i], CELL_X(i & 3), i < 4 ? TOP_Y : BOT_Y, 1, 0);
        sample_list(c, view, value(view, SMP_SAMP_ID, 0), kind);
        return;
    }
    /* page 2: the top row, unlabelled, raised a little; the waveform; the bottom labels */
    for (int i = 0; i < 4; i++)
        cell(c, view, kind, ids[i], CELL_X(i), TOP_Y + 3, 0, 0);
    int slot = value(view, SMP_SAMP_ID, 0);
    int x0 = CELL_X(0) - 1, cy = 21;
    waveform(c, slot, x0, cy);
    int w = SMP_WAVE_W;
    if (kind == SMP_GRID_KIND || kind == SMP_SLICE_KIND) {
        /* v0.22, as the DT2: every slice's start marked down the strip, and the slices
         * that play (SLCE, then LEN of them) shaded with a dot matrix; NOTE shades none */
        int n = 0;
        const u8 *col = 0;
        if (kind == SMP_GRID_KIND) {
            int gi = value(view, SMP_GRID_ID, 0) / 24;
            n = smp_grids[gi > 4 ? 4 : gi];
        } else if (slot >= 1) {
            col = smp_slices(slot - 1, &n);
        }
        int s = value(view, SMP_SLICE_ID, 0) >> 1;    /* 0 NOTE, 1..63 */
        int len = (value(view, SMP_SLEN_ID, 0) >> 1) + 1;
#define SLICE_X(j) ((j) >= n ? x0 + w - 1 : col ? x0 + col[j] * (w - 1) / (100 - 1) : x0 + (j) * (w - 1) / n)
        if (n > 0 && slot >= 1 && smp_overview(slot - 1)) {     /* (nothing to slice: OFF, EMPTY) */
            if (s > 0) {
                int first = (s > n ? n : s) - 1, end = first + len > n ? n : first + len;
                int a = SLICE_X(first), b = SLICE_X(end);
                for (int x = a; x <= b; x++)
                    for (int y = cy - SMP_WAVE_AMP - 1; y <= cy + SMP_WAVE_AMP + 1; y++)
                        if (((x + y) & 1) == 0)
                            on(c, x, y);
            }
            for (int j = 0; j < n; j++) {
                int x = SLICE_X(j);
                vline(c, x, cy - SMP_WAVE_AMP - 2, cy + SMP_WAVE_AMP + 2, 0);
                on(c, x + 1, cy - 1); on(c, x + 1, cy); on(c, x + 1, cy + 1); on(c, x + 2, cy);   /* its flag */
            }
            vline(c, x0 + w - 1, cy - SMP_WAVE_AMP - 2, cy + SMP_WAVE_AMP + 2, 0);
            /* v0.27: the slice playing now (where the voice reads), a bar over and under it
             * (owner: as the DT2 lights the slice that plays) */
            int ph = smp_playhead(UI_TRACK);
            if (ph >= 0) {
                int xp = x0 + (int)((unsigned)ph * (unsigned)(w - 2) / POS_ONE);
                for (int j = 0; j < n; j++) {
                    int a = SLICE_X(j), b = SLICE_X(j + 1);
                    if (xp >= a && (xp < b || j == n - 1)) {
                        for (int x = a + 1; x < b; x++)
                            for (int y = 0; y < 2; y++) {
                                on(c, x, cy - SMP_WAVE_AMP - 4 + y);
                                on(c, x, cy + SMP_WAVE_AMP + 3 + y);
                            }
                        break;
                    }
                }
            }
        }
#undef SLICE_X
    } else if (kind == SMP_WERP_KIND) {         /* the whole sample, its segments marked */
        int n = (32 >> steps_index(value(view, SMP_SEG_ID, 0), smp_seg_steps))
                << steps_index(value(view, SMP_BARS_ID, 0), smp_bars_steps);   /* the segments: (32 >> SEG) << BARS */
        for (int j = 0; j <= n && n <= 32; j++)
            marker(c, x0 + j * (w - 1) / n, cy, j != 0 && j != n);
    } else {
        int a = value(view, SMP_STRT_ID, 0) * (w - 1) / 120;
        int b = a + value(view, SMP_LEN_ID, 0) * (w - 1) / 127;
        if (b > w - 1) b = w - 1;
        marker(c, x0 + a, cy, 0);
        marker(c, x0 + b, cy, 0);
        if (kind == SMP_STRETCH_KIND || kind == SMP_REPITCH_KIND) {
            /* v0.25: the region's bars (BARS 1, 2, 4, 8: what STRT..LEN lasts), dotted */
            int n = 1 << steps_index(value(view, SMP_BARS_ID, 0), smp_bars_steps);
            for (int j = 1; j < n; j++)
                marker(c, x0 + a + (b - a) * j / n, cy, 1);
        }
        if (kind == SMP_KIND0) {
            int lp = value(view, SMP_LOOP_ID, 0) * (w - 1) / 127;
            int mode = value(view, SMP_PLAY_ID, 0) * 4 / 128;
            if (mode == 1 || mode == 2)
                marker(c, x0 + lp, cy, 1);
        }
    }
    if (slot >= 1 && smp_overview(slot - 1))
        playhead(c, x0, w, cy);
    else
        ph_was = -1;
    /* the bottom row: E, F, G's labels (WERP: its icons), H's level as the DT2's pill */
    for (int i = 4; i < 7; i++) {
        if (!ids[i])
            continue;
        int x = CELL_X(i - 4);
        if (kind == SMP_WERP_KIND && ids[i] == SMP_SEG_ID)
            mini_seg(c, x, 0);
        else if (kind == SMP_WERP_KIND && ids[i] == SMP_MODE_ID)
            mini_mode(c, x, 0, value(view, SMP_MODE_ID, 0) * 4 / 128);
        else if (kind == SMP_WERP_KIND && ids[i] == SMP_BARS_ID)
            fill(c, x + 6, 2, x + 17, 4);
        else
            LABEL(c, x + 12, 0, "%.5s", NAME_SHORT(ids[i]));
    }
    if (ids[7]) {
        int top, v = value(view, ids[7], &top);
        w_pill(c, CELL_X(3), 0, v, top);
    }
    sample_list(c, view, slot, kind);
}

/* v0.22: the RECORDER, the DT2's SAMPLING screen as the DN2 has room for it, over the
 * whole screen while it is up (rec.c: FUNC + VOICE). Across the top RECORDER and the
 * source's meter, THRES ticked; SRC on the left; the RECORD box in the middle (what YES
 * does, or what the recorder is doing); THRES on the right; DEST, R.LEN, R.STRT and ARM's
 * switch along the bottom, each over its label, at the knobs' places. */
extern int rec_src, rec_thres, rec_dest, rec_rlen, rec_rstrt, rec_saved_slot;
extern int rec_state, rec_peak, rec_link;
extern u32 rec_frames, rec_heard, rec_room;
#define FRAMES_NOW (*(volatile u32 *)0x4058E8D4u)

static void clear(void *c, int x0, int y0, int x1, int y1)
{
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++)
            SET_PIXEL(c, x, y, 0);
}

/* a meter position for a level 0..32767: about 60 dB across W pixels (6 dB a step of W/10) */
static int meter_x(int v, int w)
{
    int x = 0, t = 32767;
    while (t > 32 && v < t) {                   /* each halving of the level: W/10 to the left */
        t >>= 1;
        x++;
    }
    int pos = w - x * w / 10;
    return pos < 0 ? 0 : pos;
}

/* v0.22: the DT2's steps after a recording (rec.c): TRIM, NAME, ASSIGN */
extern int rec_phase, trim_slot, nm_cur, as_done, smp_saved;
extern u32 trim_n, trim_s, trim_e;
extern char nm_text[8];

/* the recording's waveform in [x0, x1] about yc, +-h: the slot's overview (100 columns) */
static void wave(void *c, int slot, int x0, int x1, int yc, int h, u32 s, u32 e, u32 n)
{
    const u8 *o = smp_overview(slot);
    int w = x1 - x0 + 1;
    int sx = x0 + (int)((s >> 4) * (u32)w / ((n >> 4) + 1u));
    int ex = x0 + (int)((e >> 4) * (u32)w / ((n >> 4) + 1u));
    if (ex > x1) ex = x1;
    hline(c, x0, x1, yc, 1);
    if (o)
        for (int x = x0; x <= x1; x++) {
            int col = (x - x0) * 100 / w;
            int a = o[col] * h / 255;
            int inside = x >= sx && x <= ex;
            for (int y = yc - a; y <= yc + a; y++)
                if (inside || ((x + y) & 1) == 0)       /* outside the trim: half lit */
                    on(c, x, y);
        }
    vline(c, sx, yc - h - 2, yc + h + 2, 0);
    vline(c, ex, yc - h - 2, yc + h + 2, 0);
    fill(c, sx, yc + h + 1, sx + 2, yc + h + 2);
    fill(c, ex - 2, yc + h + 1, ex, yc + h + 2);
}

/* v0.25: the DT2's trim screen after a recording (its manual's 13.2 step 9; the owner's
 * photos): the keys across the top, the waveform with START and END, |<TRIM on E and
 * TRIM>| on H across the bottom */
/* v0.33: TRIM zoomed (F: 2, 4, 8 times; G moves along): the window [pos, pos + n >> zoom)
 * from the slot's fine waveform (link.c's analysis, 1,024 columns over the whole sample) */
extern int trim_zoom;
extern u32 trim_pos;
extern const u8 *smp_hires(void);
extern int smp_analysis(int *pct);

static void wave_zoom(void *c, int x0, int x1, int yc, int h, u32 s, u32 e, u32 n)
{
    const u8 *hr = smp_hires();
    u32 span = n >> trim_zoom, a = trim_pos;
    if (!span)
        span = 1;
    int w = x1 - x0 + 1;
    hline(c, x0, x1, yc, 1);
    for (int x = x0; x <= x1; x++) {
        u32 f0 = a + (u32)(x - x0) * (span / (u32)w), f1 = f0 + span / (u32)w;
        u32 c0 = f0 / ((n >> 10) + 1u), c1 = f1 / ((n >> 10) + 1u);   /* (1,024 columns) */
        int pk = 0;
        for (u32 k = c0; k <= c1 && k < 1024u; k++)
            if (hr[k] > pk)
                pk = hr[k];
        int amp = pk * h / 255, inside = f0 >= s && f0 < e;
        for (int y = yc - amp; y <= yc + amp; y++)
            if (inside || ((x + y) & 1) == 0)
                on(c, x, y);
    }
    if (s >= a && s < a + span) {               /* the ends, where they are in view */
        int sx = x0 + (int)((s - a) / ((span / (u32)w) + 1u));
        vline(c, sx, yc - h - 2, yc + h + 2, 0);
        fill(c, sx, yc + h + 1, sx + 2, yc + h + 2);
    }
    if (e > a && e <= a + span) {
        int ex = x0 + (int)((e - a) / ((span / (u32)w) + 1u));
        if (ex > x1) ex = x1;
        vline(c, ex, yc - h - 2, yc + h + 2, 0);
        fill(c, ex - 2, yc + h + 1, ex, yc + h + 2);
    }
    int bw = w >> trim_zoom;                    /* where the window is, along the top */
    int bx = x0 + (int)(a / ((n / (u32)w) + 1u));
    hline(c, bx, bx + (bw < 2 ? 2 : bw), yc - h - 3, 0);
}

static void trim_draw(void *c)
{
    box(c, 2, 55, 125, 63, 0);
    LABEL(c, 64, 57, "%s", "Y:SAVE FN+N:DEL FN+Y:PLAY");
    box(c, 2, 11, 125, 53, 0);
    if (trim_zoom > 0 && smp_analysis(0) == 2)
        wave_zoom(c, 4, 123, 32, 17, trim_s, trim_e, trim_n ? trim_n : 1);
    else if (smp_overview(trim_slot))
        wave(c, trim_slot, 4, 123, 32, 18, trim_s, trim_e, trim_n ? trim_n : 1);
    else
        LABEL(c, 64, 30, "%s", "NO WAVEFORM");
    LABEL(c, 16, 2, "%s", "|<TRIM");
    if (trim_zoom > 0)
        LABEL(c, 46, 2, "%s", trim_zoom == 1 ? "2X" : trim_zoom == 2 ? "4X" : "8X");
    LABEL(c, 72, 2, "%d.%d S", (int)((trim_e - trim_s) / 48000u), (int)((trim_e - trim_s) / 4800u % 10u));
    LABEL(c, 112, 2, "%s", "TRIM>|");
}

/* v0.25: FUNC held on FILE NAME: the DT2's character grid under the name */
extern const char nm_grid[];
extern int nm_gsel, smp_func_held;
static void name_grid_draw(void *c)
{
    LABEL(c, 64, 56, "%s", "FILE NAME");
    box(c, 6, 41, 121, 51, 0);
    for (int j = 0; j < 7; j++) {
        char ch = nm_text[j] ? nm_text[j] : ' ';
        if (ch != ' ')
            LABEL(c, 14 + 8 * j, 44, "%c", ch);
        if (j == nm_cur)
            fill(c, 11 + 8 * j, 42, 17 + 8 * j, 42);
    }
    for (int g = 0; nm_grid[g]; g++) {
        int col = g % 14, row = g / 14, x = 12 + 8 * col, y = 29 - 10 * row;
        if (g == nm_gsel)
            box(c, x - 4, y - 2, x + 4, y + 7, 0);
        if (nm_grid[g] != ' ')
            LABEL(c, x, y, "%c", nm_grid[g]);
        else
            hline(c, x - 2, x + 2, y, 1);
    }
}

/* v0.25: the DT2's FILE NAME screen */
static void name_draw(void *c)
{
    if (smp_func_held) {
        name_grid_draw(c);
        return;
    }
    LABEL(c, 64, 56, "%s", "FILE NAME");
    box(c, 6, 36, 121, 48, 0);
    for (int j = 0; j < 7; j++) {
        int x = 14 + 8 * j;
        char ch = nm_text[j] ? nm_text[j] : ' ';
        if (ch != ' ')
            LABEL(c, x, 40, "%c", ch);
        if (j == nm_cur)                        /* the cursor: a bar under it */
            fill(c, x - 3, 37, x + 3, 38);
    }
    LABEL(c, 34, 26, "%s", "FN+ARROW:EDIT");
    LABEL(c, 34, 19, "%s", "FN+NO:DELETE");
    LABEL(c, 34, 12, "%s", "FN+YES:INSERT");
    LABEL(c, 34, 5, "%s", "YES:SAVE");
    LABEL(c, 98, 26, "%s", "U/D:CHAR +/-");
    LABEL(c, 98, 19, "%s", "L/R:MOVE");
    LABEL(c, 98, 12, "%s", "NO:ABORT");
}

/* v0.25: ASSIGN, the DT2's question over the trim screen */
static void assign_draw(void *c)
{
    trim_draw(c);
    clear(c, 3, 18, 124, 46);
    box(c, 3, 18, 124, 46, 0);
    box(c, 5, 20, 122, 44, 0);
    LABEL(c, 64, 35, "%s", "ASSIGN SAMPLE TO TRACK?");
    LABEL(c, 64, 25, "%s", "TRG 1-16   NO:SKIP");
}

/* v0.25: NORMALIZING (and the +Drive's save before it), as the DT2 shows it */
static void work_draw(void *c)
{
    extern int smp_norm_state(void);
    extern int smp_work_pct(void);
    LABEL(c, 64, 34, "%s", smp_norm_state() ? "NORMALIZING..." : "SAVING...");
    int pct = smp_work_pct();
    box(c, 24, 20, 103, 26, 0);
    if (pct > 0)
        fill(c, 25, 21, 25 + (pct > 100 ? 100 : pct) * 77 / 100, 25);
}

/* v0.25: the DT2's screen while it records: the meter, the waveform as it comes in, the
 * time and YES: STOP */
extern u8 rec_wave[];
extern u32 rec_wave_span;
static void recording_draw(void *c, int heard)
{
    LABEL(c, 25, 57, "%s", "RECORDER");
    int mx0 = 54, mx1 = 126, my0 = 55, my1 = 62, w = mx1 - mx0 - 2;
    box(c, mx0, my0, mx1, my1, 0);
    int lv = heard ? meter_x(rec_peak, w) : 0;
    if (lv > 0)
        fill(c, mx0 + 1, my0 + 1, mx0 + lv, my1 - 1);
    box(c, 2, 11, 125, 53, 0);
    hline(c, 4, 123, 32, 1);
    u32 cols = rec_frames / rec_wave_span + 1u;
    for (int x = 0; x < 120 && (u32)x < cols; x++) {
        int a = rec_wave[x] * 19 / 255;
        vline(c, 4 + x, 32 - a, 32 + a, 0);
    }
    u32 sec = rec_frames / 48000u;
    LABEL(c, 22, 2, "%s", "RECORDING");
    LABEL(c, 64, 2, "%d:%d%d", (int)(sec / 60u), (int)(sec % 60u / 10u), (int)(sec % 10u));
    LABEL(c, 106, 2, "%s", "YES: STOP");
}

void rec_screen_draw(void *c)
{
    if (rec_phase) {
        clear(c, 0, 0, 127, 63);
        if (rec_phase == 1)
            trim_draw(c);
        else if (rec_phase == 2)
            name_draw(c);
        else if (rec_phase == 3)
            assign_draw(c);
        else
            work_draw(c);
        return;
    }
    int heard = rec_heard && FRAMES_NOW + 1u - rec_heard < 1500u;
    int state = heard ? rec_state : 0;
    clear(c, 0, 0, 127, 63);
    if (state == 2) {                           /* v0.25: recording: the DT2's screen */
        recording_draw(c, heard);
        return;
    }

    /* the title and the meter */
    LABEL(c, 25, 57, "%s", "RECORDER");
    hline(c, 0, 50, 54, 0);
    int mx0 = 54, mx1 = 126, my0 = 55, my1 = 62, w = mx1 - mx0 - 2;
    box(c, mx0, my0, mx1, my1, 0);
    int lv = heard ? meter_x(rec_peak, w) : 0;
    if (lv > 0)
        fill(c, mx0 + 1, my0 + 1, mx0 + lv, my1 - 1);
    int tx = mx0 + 1 + rec_thres * w / 120;
    vline(c, tx, my0 - 2, my0 - 1, 0);

    /* SRC, on the left: the source in two lines (EXT over L+R, TRK over its number) */
    const char *src = smp_rec_src[rec_src > SMP_REC_SOURCES - 1 ? SMP_REC_SOURCES - 1 : rec_src];
    char a[6] = {0}, b[6] = {0};
    int k = 0, j = 0;
    while (src[k] && src[k] != ' ' && k < 5) { a[k] = src[k]; k++; }
    if (src[k] == ' ') k++;
    while (src[k] && j < 5) b[j++] = src[k++];
    if (!b[0] && a[0] == 'T') {                 /* TRK12 -> TRK / 12 */
        b[0] = a[3]; b[1] = a[4]; a[3] = 0; a[4] = 0;
    }
    LABEL(c, 13, 43, "%s", a);
    if (b[0])
        LABEL(c, 13, 35, "%s", b);
    LABEL(c, 13, 25, "%s", "SRC");

    /* the RECORD box: what YES does, or what the recorder is doing */
    int bx0 = 29, bx1 = 97, by0 = 22, by1 = 48;
    box(c, bx0, by0, bx1, by1, 1);
    int cx = (bx0 + bx1) / 2;
    if (state == 2) {
        fill(c, bx0 + 5, by0 + 15, bx0 + 11, by0 + 21);   /* a solid dot: recording */
        int ds = (int)(rec_frames / 4800u);
        LABEL(c, cx + 6, by0 + 16, "%s", "REC");
        LABEL(c, cx, by0 + 8, "%d.%d S", ds / 10, ds % 10);
        LABEL(c, cx, by0 + 1, "%s", "YES:STOP");
    } else if (state == 1) {
        LABEL(c, cx, by0 + 16, "%s", "ARMED");
        LABEL(c, cx, by0 + 8, "%s", rec_rstrt ? "ON PLAY" : "ON THRES");
        LABEL(c, cx, by0 + 1, "%s", "NO:CANCEL");
    } else if (!heard || rec_link < 0) {
        LABEL(c, cx, by0 + 16, "%s", !heard ? "NO DSP" : "NO LINK");
        LABEL(c, cx, by0 + 8, "%s", !heard ? "STATUS" : "TO DSP");
    } else if (rec_room < 0x10000u) {
        LABEL(c, cx, by0 + 16, "%s", smp_slot_empty(rec_dest < 0 ? 0 : rec_dest) ? "NO ROOM" : "NO FREE SLOT");
        LABEL(c, cx, by0 + 8, "%s", "UNLOAD ONE");
    } else {
        fill(c, bx0 + 4, by0 + 14, bx0 + 18, by0 + 22);   /* YES, cut out of a filled badge */
        glyph(c, bx0 + 6, by0 + 16, 'Y', 0);
        glyph(c, bx0 + 10, by0 + 16, 'E', 0);
        glyph(c, bx0 + 14, by0 + 16, 'S', 0);
        LABEL(c, cx + 11, by0 + 16, "%s", state == 3 ? "AGAIN" : "RECORD");
        u32 secs = rec_room / 96000u;           /* int16 at 48 kHz */
        LABEL(c, cx, by0 + 6, "%d S FREE", (int)(secs > 999 ? 999 : secs));
        if (as_done >= 0 && rec_saved_slot >= 0)
            LABEL(c, cx, by0 + 0, "%d ON TRK %d", rec_saved_slot + 1, as_done + 1);
        else if (state == 3 && rec_saved_slot >= 0)
            LABEL(c, cx, by0 + 0, "SAVED %d", rec_saved_slot + 1);
    }

    /* THRES, on the right */
    LABEL(c, 113, 34, "%d", rec_thres);
    LABEL(c, 113, 22, "%s", "THRES");

    /* the bottom row: the slot the next recording goes into (v0.33: shown, not chosen: the
     * first empty one), R.LEN, R.STRT, ARM */
    w_samp(c, 1, 5, rec_dest < 0 ? 0 : rec_dest + 1);
    LABEL(c, 13, 0, "%s", "INTO");
    if (rec_rlen <= 0) {
        LABEL(c, 47, 12, "%s", "MAX");
    } else {
        LABEL(c, 47, 12, "%d", rec_rlen);
        LABEL(c, 47, 6, "%s", "STEPS");
    }
    LABEL(c, 47, 0, "%s", "R.LEN");
    LABEL(c, 80, 9, "%s", rec_rstrt ? "PLAY" : "THRES");
    LABEL(c, 80, 0, "%s", "R.STRT");
    int on = state == 1 || state == 2;           /* ARM's switch: what the DSP is doing */
    int sx0 = 104, sx1 = 122, sy0 = 8, sy1 = 15;
    box(c, sx0, sy0, sx1, sy1, 0);
    if (on)
        fill(c, sx1 - 8, sy0 + 2, sx1 - 2, sy1 - 2);
    else
        box(c, sx0 + 2, sy0 + 2, sx0 + 8, sy1 - 2, 0);
    LABEL(c, 113, 0, "%s", "ARM");
}
