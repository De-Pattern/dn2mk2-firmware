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

static void w_gridicon(void *c, int x, int y)
{
    int cx = x + 12;
    fill(c, cx - 7, y + 9, cx - 1, y + 15);
    fill(c, cx + 1, y + 9, cx + 7, y + 15);
    fill(c, cx - 7, y + 1, cx - 1, y + 7);
    fill(c, cx + 1, y + 1, cx + 7, y + 7);
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
    else if (kind == SMP_GRID_KIND && id == SMP_GRID_ID)
        w_gridicon(c, x, y);
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
            for (int x = bx - 16; x <= bx + 16; x++)
                SET_PIXEL(c, x, y, 0);
        int named = slot >= 1 && slot <= smp_count() && smp_name(slot - 1)[0];
        TEXT(c, FONT, bx, cy - 3, CENTRED, slot < 1 ? "OFF"
             : named && smp_lstate != 0 && smp_lstate != 4 ? "LOADING" : "EMPTY");
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

/* the sample list (v0.16), as the DT2 shows its sample names while SAMP turns: for a second
 * after SAMP changes, five slots around the chosen one, the chosen one framed */
#define LIST_FRAMES 1500u
static int list_slot __attribute__((section(".data"))) = -1;
void *smp_list_view __attribute__((section(".data"))) = 0;   /* rec.c's UI filter asks after it */
#define list_view smp_list_view
static u32 list_at __attribute__((section(".data"))) = 0;

static void slot_name(int k, char *out)
{
    const char *n = 0;
    int cnt = smp_count();
    if (k <= 0)
        n = "OFF";
    else if (cnt >= 0 && k <= cnt)
        n = smp_name(k - 1);
    if (k > 0 && !(n && n[0]) && !smp_slot_empty(k - 1))
        n = "SAMPLE";                           /* something there, without a name (v0.15's recordings) */
    int j = 0;
    if (n && n[0])
        for (; j < 7 && n[j]; j++)
            out[j] = n[j];
    else {                                      /* v0.20: nothing loaded there */
        static const char e[] = "EMPTY";
        for (; e[j]; j++)
            out[j] = e[j];
    }
    out[j] = 0;
}

/* the list is up on VIEW's page (rec.c's key handler: UP and DOWN keep it, v0.20) */
int smp_list_up(void *view)
{
    u32 now = *(volatile u32 *)0x4058E8D4u;
    return view == list_view && list_slot >= 0 && now - list_at < LIST_FRAMES;
}

void smp_list_hold(void)
{
    list_at = *(volatile u32 *)0x4058E8D4u;
}

void smp_list_close(void)                       /* SAMP's knob pushed: the highlighted one it is */
{
    list_at = *(volatile u32 *)0x4058E8D4u - LIST_FRAMES;
}

static void sample_list(void *c, void *view, int slot)
{
    u32 now = *(volatile u32 *)0x4058E8D4u;
    if (view != list_view || list_slot < 0) {   /* first sight of this page: no list */
        list_view = view;
        list_slot = slot;
        list_at = now - LIST_FRAMES;
        return;
    }
    if (slot != list_slot) {
        list_slot = slot;
        list_at = now;
    }
    if (now - list_at >= LIST_FRAMES)
        return;
    int x0 = 26, x1 = 124, y0 = 1, y1 = 46;
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++)
            SET_PIXEL(c, x, y, 0);
    box(c, x0, y0, x1, y1, 0);
    for (int r = 0; r < 5; r++) {
        int k = slot - 2 + r, y = y1 - 9 - 8 * r;
        if (k < 0 || k > 127)
            continue;
        char nm[8], num[4];
        slot_name(k, nm);
        num[0] = k >= 100 ? (char)('0' + k / 100) : ' ';
        num[1] = k >= 10 ? (char)('0' + k / 10 % 10) : ' ';
        num[2] = (char)('0' + k % 10);
        num[3] = 0;
        TEXT(c, FONT, x0 + 3, y, 0, "%.3s", num);
        TEXT(c, FONT, x0 + 24, y, 0, "%.7s", nm);
        if (k == slot)
            box(c, x0 + 1, y - 1, x1 - 1, y + 7, 0);
    }
}

void smp_page_draw(void *view, void *c, int kind, int wave)
{
    u32 ids[8];
    for (int i = 0; i < 8; i++)
        ids[i] = smp_ids[kind - SMP_KIND0][i];
    smp_box(c);
    if (!wave) {                                /* page 1: the widgets and their labels */
        for (int i = 0; i < 8; i++)
            cell(c, view, kind, ids[i], CELL_X(i & 3), i < 4 ? TOP_Y : BOT_Y, 1, 0);
        sample_list(c, view, value(view, SMP_SAMP_ID, 0));
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
        if (kind == SMP_KIND0) {
            int lp = value(view, SMP_LOOP_ID, 0) * (w - 1) / 127;
            int mode = value(view, SMP_PLAY_ID, 0) * 4 / 128;
            if (mode == 1 || mode == 2)
                marker(c, x0 + lp, cy, 1);
        }
    }
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
    sample_list(c, view, slot);
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

void rec_screen_draw(void *c)
{
    int heard = rec_heard && FRAMES_NOW + 1u - rec_heard < 1500u;
    int state = heard ? rec_state : 0;
    clear(c, 0, 0, 127, 63);

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
        LABEL(c, cx, by0 + 16, "%s", "NO ROOM");
        LABEL(c, cx, by0 + 8, "%s", "CHANGE DEST");
    } else {
        fill(c, bx0 + 4, by0 + 14, bx0 + 18, by0 + 22);   /* YES, cut out of a filled badge */
        glyph(c, bx0 + 6, by0 + 16, 'Y', 0);
        glyph(c, bx0 + 10, by0 + 16, 'E', 0);
        glyph(c, bx0 + 14, by0 + 16, 'S', 0);
        LABEL(c, cx + 11, by0 + 16, "%s", state == 3 ? "AGAIN" : "RECORD");
        u32 secs = rec_room / 96000u;           /* int16 at 48 kHz */
        LABEL(c, cx, by0 + 6, "%d S FREE", (int)(secs > 999 ? 999 : secs));
        if (state == 3 && rec_saved_slot >= 0)
            LABEL(c, cx, by0 + 0, "SAVED %d", rec_saved_slot + 1);
    }

    /* THRES, on the right */
    LABEL(c, 113, 34, "%d", rec_thres);
    LABEL(c, 113, 22, "%s", "THRES");

    /* the bottom row: DEST, R.LEN, R.STRT, ARM */
    w_samp(c, 1, 5, rec_dest < 0 ? 0 : rec_dest + 1);
    LABEL(c, 13, 0, "%s", "DEST");
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
