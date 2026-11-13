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
#define RECORD_FMT(id) (*(void **)(0x401F7F94u + 60u * (id) + 0x34u))   /* v0.35: its value text */
#define LABEL_FONT 0x40291760u                  /* the stock grid's 4 x 5 label font: the DT2's labels' */
/* the stock grid's label text (0x40115668, as 0x4006448a calls it for each cell's name):
 * (canvas, font, x, y, align 1 centred, frame 0 none, width template 0, format, ...) */
#define LABEL_TEXT ((void (*)(void *, u32, int, int, int, int, const char *, const char *, ...))0x40115668u)
#define LABEL(c, x, y, fmt, ...) LABEL_TEXT((c), LABEL_FONT, (x), (y), 1, 0, 0, fmt, __VA_ARGS__)
#define CENTRED   2
#define RECORD(id) ((const int *)(0x401F7F94u + 60u * (id)))
extern int smp_values_held(void);                /* v0.35: SYN held long: the pages show their values (rec.c) */
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

/* v0.48: STRT, LEN, LOOP's place across W, from the whole word (0..120.00 in 1/256, fmt.c
 * smp_fine), as the DSP reads it (dnfw.sampler.program.ctl_pos) */
static int pos_x(void *view, u32 id, int w)
{
    u8 flag;
    int v = GET_VALUE(view, id, &flag);
    v = v < 0 ? 0 : v > 0x7800 ? 0x7800 : v;
    return v * w / 0x7800;
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

/* v0.51 (impbox: "the tuning display could probably also just use the WAVETONE's display"; the
 * owner's photos of WaveTone's Osc1 Tune, the same record 238): a ruler that scrolls under a fixed
 * centre tick, a pixel a semitone: the octave's number every 12 (-5..5), a dot every 3 between,
 * the value itself in the label while turned (7.22). v0.20..v0.50 showed the DT2's box with the
 * whole semitones in it */
static void glyph_in(void *c, int x, int y, char ch, int xa, int xb)   /* a glyph cut at xa..xb */
{
    for (int k = 0; smp_glyph_chars[k]; k++)
        if (smp_glyph_chars[k] == ch) {
            for (int r = 0; r < 5; r++)
                for (int b = 0; b < 3; b++)
                    if ((smp_glyph[k][r] & (4 >> b)) && x + b >= xa && x + b <= xb)
                        SET_PIXEL(c, x + b, y + 4 - r, 1);
            return;
        }
}

/* v0.51: a short word in the 3x5 glyphs, centred at CX, its bottom row at Y */
static void glyphs_at(void *c, int cx, int y, const char *s)
{
    int n = 0;
    while (s[n])
        n++;
    int x = cx - (4 * n - 1) / 2;
    for (int k = 0; k < n; k++)
        glyph(c, x + 4 * k, y, s[k], 1);
}

static void w_bipolar(void *c, int x, int y, int word, u32 id)
{
    int cx = x + 12, x0 = cx - 10, x1 = cx + 10, y0 = y + 1, y1 = y + 15;
    box(c, x0, y0, x1, y1, 0);
    vline(c, cx, y1 - 2, y1 - 1, 0);
    vline(c, cx, y0 + 1, y0 + 2, 0);
    const int *r = RECORD(id);
    int d = word - (r[2] + r[3]) / 2;           /* from the middle, in 1/256 semitone */
    int s0 = (d >> 8) - 11;
    for (int s = s0; s <= s0 + 23; s++) {
        if (s < -60 || s > 60)
            continue;
        int q = s * 256 - d;
        int px = cx + (q + (q >= 0 ? 128 : -128)) / 256;
        if (s % 12 == 0) {
            int n = s / 12;
            glyph_in(c, px - 1, y + 6, (char)('0' + (n < 0 ? -n : n)), x0 + 1, x1 - 1);
            if (n < 0)
                glyph_in(c, px - 5, y + 6, '-', x0 + 1, x1 - 1);
        } else if (s % 3 == 0 && px > x0 && px < x1)
            SET_PIXEL(c, px, y + 6, 1);
    }
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

/* v0.47: the RECORDER's INTO, smaller than SAMP's (the owner: "shorter and slightly less
 * wide"): a box 20 x 11 (SAMP's 21 x 15), its left six columns filled with the bank letter cut out */
static void w_samp_small(void *c, int x, int y, int slot)
{
    int cx = x + 12, x0 = cx - 9, x1 = cx + 10, y0 = y + 3, y1 = y + 13;
    hline(c, x0 + 1, x1 - 1, y0, 0);
    hline(c, x0 + 1, x1 - 1, y1, 0);
    vline(c, x1, y0 + 1, y1 - 1, 0);
    fill(c, x0, y0 + 1, x0 + 5, y1 - 1);
    static const unsigned char bank_a[5] = {7, 5, 7, 5, 5};
    for (int r = 0; r < 5; r++)
        for (int b = 0; b < 3; b++)
            if (bank_a[r] & (4 >> b))
                SET_PIXEL(c, x0 + 2 + b, y + 10 - r, 0);
    if (slot == 0) {
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

/* v0.48 (impbox: "no numbers show below [the knob] when moving or locking parameter values
 * on the sample based machines"): as stock's pages, the control a knob has just turned (a
 * value or, with a trig held, its lock) shows its value in its label's place for a second;
 * with SYN held, every control's (v0.35). CELL_I is the cell being drawn: knob A..H's place */
#define VALUE_SHOW 1500u                        /* a second of frames */
static int cell_i __attribute__((section(".data"))) = -1;
static int shows(int i)
{
    extern int smp_knob_code;
    extern u32 smp_knob_at;
    return smp_values_held() || (i >= 0 && smp_knob_code == i + 1
                                 && *(volatile u32 *)0x4058E8D4u - smp_knob_at < VALUE_SHOW);
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
    else if (w == W_BIPOLAR) {
        u8 bflag;
        w_bipolar(c, x, y, GET_VALUE(view, id, &bflag), id);
    }
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
    extern int smp_values_held(void);
    if (labelled && id && shows(cell_i)) {     /* v0.35: SYN held (v0.48: or just turned): the value, as the record's */
        char vb[32];                            /* formatter writes it for the header (O14) */
        u8 flag;
        vb[0] = 0;
        ((void (*)(int, char *))RECORD_FMT(id))(GET_VALUE(view, id, &flag), vb);
        vb[6] = 0;
        LABEL(c, x + 12, y - 7, "%s", vb);
    } else if (labelled && id)
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
        if (shows(i)) {                         /* v0.35: SYN held (v0.48: or just turned): the value (O14) */
            char vb[32];
            u8 flag;
            vb[0] = 0;
            ((void (*)(int, char *))RECORD_FMT(ids[i]))(GET_VALUE(view, ids[i], &flag), vb);
            vb[6] = 0;
            LABEL(c, x + 12, y - 7, "%s", vb);
        } else
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

static int ph_was __attribute__((section(".data"))) = -1;         /* the playhead it drew (-1 none) */
/* v0.40 (owner: "the slice machine's on-screen indicators are a little slow to catch up"; the
 * main cause was the voice drawn, link.c's smp_playhead): v0.25..v0.39 asked for a redraw 25
 * times a second while anything played, and took the page as up while drawn in the last
 * 1.2 s (stock redraws an idle page about every 0.4 s, emulator). Now the page is up while
 * the screen's LAST draw drew it (page.c counts the draws), and a redraw is asked for when
 * the column the playhead falls in differs from the one drawn (nothing else on the page is
 * drawn from the position: the playhead, SLICE / GRID's playing-slice bar), 37 a second at
 * most; a still playhead asks for none */
extern u32 wr_draws;
static u32 ph_draw_n __attribute__((section(".data"))) = 0xFFFFFFFFu;   /* wr_draws when last drawn */
static int ph_x0 __attribute__((section(".data"))) = 0, ph_w __attribute__((section(".data"))) = 2;
static int ph_col __attribute__((section(".data"))) = -1;        /* the column drawn (-1 none) */

static int ph_column(int ph)                    /* the playhead's column, or -1 */
{
    return ph < 0 ? -1 : ph_x0 + (int)((unsigned)ph * (unsigned)(ph_w - 2) / POS_ONE);
}

/* the UI loop asks (page.c's wr_poll): the waveform page is up, and its playhead (and the
 * slice it lights) would be drawn elsewhere now */
int smp_wants_redraw(void)
{
    if (ph_draw_n != wr_draws)                  /* the last screen drawn was not the page */
        return 0;
    return ph_column(smp_playhead(UI_TRACK)) != ph_col;
}

static void playhead(void *c, int x0, int w, int cy)
{
    int ph = smp_playhead(UI_TRACK);
    ph_draw_n = wr_draws;
    ph_x0 = x0;
    ph_w = w;
    ph_was = ph;
    ph_col = ph_column(ph);
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
/* (noipa: not inlined nor cloned for its constant x, where GCC folds x x words x 4 into a scaled index of 8, a 68020 mode
 * the ColdFire refuses -- cbuild's check caught it on 2026-11-12) */
__attribute__((noipa)) static int pixel(void *c, int x, int y)   /* the canvas's pixel (invert()'s layout) */
{
    const int *cv = (const int *)c;
    const u32 *bits = (const u32 *)cv[4];
    if (x < 0 || y < 0 || x >= cv[1] || y >= cv[2])
        return 0;
    return (bits[x * cv[3] + (y >> 5)] >> (31 - (y & 31))) & 1;
}

static void smp_box(void *c)
{
    static const char *g[3][6] = {
        {".##", "#..", "##.", ".##", "..#", "##."},             /* S */
        {"#.#", "###", "###", "#.#", "#.#", "#.#"},             /* M */
        {"##.", "#.#", "#.#", "##.", "#..", "#.."},             /* P */
    };
    /* v0.50 (impbox: "holding TRK inverts the track area, but a sample track's text is not
     * inverted"): with TRK held stock draws the box filled and SYN cut out of it. Stock's S is
     * ours, so its first pixel (a gap in S's top row) is the box's ground: lit, the box is
     * filled and SMP is cut out of it as SYN was */
    int filled = pixel(c, 2, 48);
    for (int k = 0; k < 3; k++)
        for (int r = 0; r < 6; r++)
            for (int b = 0; b < 3; b++)
                SET_PIXEL(c, 2 + 4 * k + b, 48 - r, (g[k][r][b] == '#') != filled);
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
    extern int rt_on;
    if (k <= 0)
        n = "OFF";
    else if (rt_on && k - 1 >= REC_FIRST && k - 1 < REC_FIRST + 4)
        n = k - 1 == REC_FIRST ? "REC 1" : k - 1 == REC_FIRST + 1 ? "REC 2" : "---";   /* v0.41: the buffers */
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

/* v0.39: a name in W characters, as the DT2's lists: whole if it fits (a file's extension
 * dropped); else its head, "...", its tail (the part a pack's names differ in: v0.38 showed
 * six hi-hats as one "AT BIRDHOUSE HI-HA"); OFF >= 0: the W characters from OFF (the
 * selected row's marquee, below) -> OUT */
static int name_len(const char *n)
{
    int L = 0;
    while (n[L] && L < 64)
        L++;
    for (int e = L - 1; e >= L - 5 && e > 0; e--)
        if (n[e] == '.') {
            char x[5] = {0, 0, 0, 0, 0};
            for (int j = 0; j < 4 && e + 1 + j < L; j++)
                x[j] = (char)(n[e + 1 + j] >= 'a' && n[e + 1 + j] <= 'z' ? n[e + 1 + j] - 32 : n[e + 1 + j]);
            if (L - e - 1 >= 3 && ((x[0] == 'W' && x[1] == 'A' && x[2] == 'V' && !x[3])
                                   || (x[0] == 'A' && x[1] == 'I' && x[2] == 'F' && (!x[3] || x[3] == 'F'))
                                   || (x[0] == 'M' && x[1] == 'P' && x[2] == '3' && !x[3])
                                   || (x[0] == 'F' && x[1] == 'L' && x[2] == 'A' && x[3] == 'C')))
                return e;
            break;
        }
    return L;
}

static void fit_name(const char *n, int w, int off, char *out)
{
    int L = name_len(n), o = 0;
    if (L <= w) {
        for (; o < L; o++)
            out[o] = n[o];
    } else if (off >= 0) {
        if (off > L - w)
            off = L - w;
        for (; o < w; o++)
            out[o] = n[off + o];
    } else {
        int head = (w - 3) / 2 + 1, tail = w - 3 - head;
        for (; o < head; o++)
            out[o] = n[o];
        out[o++] = '.';
        out[o++] = '.';
        out[o++] = '.';
        for (int j = L - tail; j < L; j++)
            out[o++] = n[j];
    }
    out[o] = 0;
}

/* v0.39: the selected row's marquee: a long name rests a second on its start, steps on five
 * characters a second to its end, rests a second there and starts again; a new selection
 * starts it from the start, and the row left shows head...tail again. smp_marquee_poll
 * (rec_poll, every UI pass) asks for a redraw only when the shown part moves */
#define MQ_REST 1500u                           /* the 1.5 kHz ticks of 0x4058e8d4: a second */
#define MQ_STEP 300u                            /* a character each 0.2 s */
static u32 mq_key __attribute__((section(".data"))) = 0xFFFFFFFFu;
static u32 mq_at __attribute__((section(".data"))) = 0;
int smp_mq_off __attribute__((section(".data"))) = 0;      /* the selected row's first character */
/* the shown part of the row selected now: from its start until the poll has seen it */
static int mq_off(u32 key) { return key == mq_key ? smp_mq_off : 0; }
#define LIST_KEY(slot) (0x40000000u | (u32)(slot))

static int mq_steps __attribute__((section(".data"))) = 0;  /* its characters past the row's */

/* the row KEY selected now (its name N in W characters; N 0: none) */
static void mq_follow(u32 key, const char *n, int w)
{
    u32 now = *(volatile u32 *)0x4058E8D4u;
    if (key != mq_key) {
        mq_key = key;
        mq_at = now;
        mq_steps = n ? name_len(n) - w : 0;
        if (smp_mq_off)
            smp_overlay_dirty = 1;
        smp_mq_off = 0;
        return;
    }
    int steps = mq_steps;
    if (steps <= 0)
        return;
    u32 t = (now - mq_at) % (2u * MQ_REST + (u32)steps * MQ_STEP);
    int off = t < MQ_REST ? 0 : (int)((t - MQ_REST) / MQ_STEP);
    if (off > steps)
        off = steps;
    if (off != smp_mq_off) {
        smp_mq_off = off;
        smp_overlay_dirty = 1;
    }
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

#define LIST_W 14                               /* v0.39: the list's characters a name (x 49..123) */
_Static_assert(LIST_W < 19, "the list's name buffer");
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
        char ln[64], nm[19], num[4];
        slot_name(k, ln, 63);
        fit_name(ln, LIST_W, k == slot ? mq_off(LIST_KEY(slot)) : -1, nm);   /* v0.39 */
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
int smp_fb_menu __attribute__((section(".data"))) = 0;      /* the SAMPLE ACTION menu: 0 shut, 1 up, 2 DELETE asked;
                                                               * v0.39: 3 +DRIVE's ERASE MOD DATA, 4 and 5 its questions, 6 erasing */
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
/* v0.43: the +Drive library's folders (lib.c LIB_FOLDERS: 64 until v0.42, 128 since; a
 * static assert in lib.c holds the two together) */
#define SMP_LIB_FOLDERS 128
#define LB_CAP 16384                            /* v0.45: the library's 16,384 (lib.c) */
static u32 lb_marks[LB_CAP / 32] __attribute__((section(".data")));
extern int smp_lib_used(int k), smp_lib_folder_of(int k), smp_lib_slot_of(int k);
extern const char *smp_lib_name(int k), *smp_lib_folder_name(int f);
extern int smp_lib_delete(int k), smp_lib_load(int k), smp_lib_pending(void);

static int lb_in(int k, int folder) { return smp_lib_used(k) && smp_lib_folder_of(k) == folder; }
/* v0.40: folders inside folders (lib.c's tree): a folder's row stands for all it holds */
extern int smp_lib_folder_parent(int f), smp_lib_folder_depth(int f), smp_lib_folder_under(int g, int f);
static int lb_under(int k, int folder) { return smp_lib_used(k) && smp_lib_folder_under(smp_lib_folder_of(k), folder); }

extern int smp_lib_folder_count(int f);
/* v0.33: a named folder shows even empty (NEW FOLDER's, and so a MOVE HERE target; the
 * review: an empty new folder was hidden and could not be used) */
static int lb_has(int folder)
{
    const char *n = smp_lib_folder_name(folder);
    return smp_lib_folder_count(folder) > 0 || (n && n[0]);
}

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

/* v0.45: SELECT UNUSED (the DT2's, manual 13.6.6: "remove all samples that are not used in
 * any pattern in the project from the RAM memory"; Wolljamin). The whole project is in RAM:
 * 128 patterns at project + 0x1C, 122,478 bytes apart, and their 128 kits at project +
 * 0xEF371C, 23,921 apart (dn2_111.h; the live kit is the active pattern's own). A slot is
 * used if any pattern's kit has a sample machine (types 8..13) on a track with SAMP on it,
 * or any SAMP p-lock (slot 43) of that pattern's track names it. The project's base is
 * found from the playing pattern and the live kit, which must agree on one pattern index;
 * if they don't, nothing is marked (never a guess that unloads a sample in use). */
#define SEQ_PATTERN_PTR (*(u8 *volatile *)0x42C5A9A0u)
#define KIT_LIVE (*(u8 *volatile *)0x800052A0u)
#define PRJ_PATTERNS 0x1Cu
#define PRJ_PATTERN_BYTES 122478u
#define PRJ_KITS 0xEF371Cu
#define PRJ_KIT_BYTES 23921u
#define PAT_LOCKS 97872u                        /* the pattern's lock table (rectrig.c) */
#define LK_RECS 80
#define LK_REC 258u
#define LK_INDEX 20640u
#define SAMP_FSLOT 43                           /* SAMP's frame slot: sound + 20 + 2 x 43 */

int smp_fb_unused_scan(u32 used[4])
{
    for (int i = 0; i < 4; i++)
        used[i] = 0;
    u8 *pat = SEQ_PATTERN_PTR, *kit = KIT_LIVE;
    if (!pat || !kit)
        return -1;
    int d = (int)(PRJ_KITS - PRJ_PATTERNS) - (int)((u32)kit - (u32)pat);   /* = 98,557 p */
    const int step = (int)PRJ_PATTERN_BYTES - (int)PRJ_KIT_BYTES;
    if (d < 0 || d % step || d / step > 127)
        return -1;
    u8 *proj = pat - PRJ_PATTERNS - PRJ_PATTERN_BYTES * (u32)(d / step);
    for (u32 n = 0; n < 128; n++) {
        const u8 *k = proj + PRJ_KITS + PRJ_KIT_BYTES * n;
        const u8 *table = proj + PRJ_PATTERNS + PRJ_PATTERN_BYTES * n + PAT_LOCKS;
        for (u32 t = 0; t < 16; t++) {
            const u8 *snd = k + 52u + 1163u * t;
            u8 ty = snd[0xDE];
            if (ty < 8 || ty > 13)
                continue;
            u32 s = snd[20 + 2 * SAMP_FSLOT];   /* 0 OFF, k: slot k - 1 */
            if (s >= 1 && s <= 128)
                used[(s - 1) >> 5] |= 1u << ((s - 1) & 31);
            signed char r = (signed char)table[LK_INDEX + 101u * t + SAMP_FSLOT];
            if (r < 0 || r >= LK_RECS)
                continue;
            const u8 *rec = table + LK_REC * (u32)r;
            if (rec[0] != SAMP_FSLOT || rec[1] != t)
                continue;                       /* (an index that doesn't point at its record: skip) */
            for (u32 st = 0; st < 128; st++) {
                u32 v = rec[2 + 2 * st];        /* the value's high byte: SAMP */
                if (rec[2 + 2 * st] == 0xFF && rec[3 + 2 * st] == 0xFF)
                    continue;                   /* no lock on this step */
                if (v >= 1 && v <= 128)
                    used[(v - 1) >> 5] |= 1u << ((v - 1) & 31);
            }
        }
    }
    return 0;
}

int smp_fb_mark_unused(void)
{
    u32 used[4];
    smp_fb_unmark_all();
    if (smp_fb_unused_scan(used))
        return -1;
    int n = 0;
    for (int k = 0; k < 128; k++)
        if (!smp_slot_empty(k) && !((used[k >> 5] >> (k & 31)) & 1u)) {
            smp_fb_mark(k, 1);
            n++;
        }
    return n;
}

int smp_fb_mark_count(void)
{
    int n = 0;
    if (smp_fb_store == 1) {                    /* v0.45: only the ticked bits (each redraw asks: */
        for (int i = 0; i < LB_CAP / 32; i++)   /* 16,384 entries one by one lagged the keys) */
            for (u32 w = lb_marks[i], b = 0; w; w >>= 1, b++)
                if (w & 1u)
                    n += smp_lib_used(32 * i + (int)b);
        return n;
    }
    for (int k = 0; k < 128; k++)
        if (smp_fb_marked(k) && !smp_slot_empty(k))
            n++;
    return n;
}

/* FOLDER's samples: how many, and how many of them marked; v0.40: in +DRIVE, DEEP counts
 * those in its folders too (a folder's row), else only its own (the list inside it) */
static int fb_size_d(int folder, int *marked, int deep)
{
    int n = 0, m = 0;
    if (smp_fb_store == 1) {                    /* v0.40: the folders it covers, then lib.c's */
        u32 in[SMP_LIB_FOLDERS / 32];
        for (int w_ = 0; w_ < SMP_LIB_FOLDERS / 32; w_++)
            in[w_] = 0;                     /* counts and only the marked entries (each */
        for (int g = 0; g < SMP_LIB_FOLDERS; g++)            /* folder row asks this, each redraw) */
            if (deep ? smp_lib_folder_under(g, folder) : g == folder) {
                in[g >> 5] |= 1u << (g & 31);
                n += smp_lib_folder_count(g);
            }
        for (int i = 0; i < LB_CAP / 32 && marked; i++)
            for (u32 w = lb_marks[i], b = 0; w; w >>= 1, b++)
                if (w & 1u) {
                    int f = smp_lib_folder_of(32 * i + (int)b);
                    m += f >= 0 && (in[f >> 5] >> (f & 31) & 1u);
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

static int fb_size(int folder, int *marked) { return fb_size_d(folder, marked, 1); }

/* every sample of FOLDER marked, or (all of them marked already) none; v0.40: in +DRIVE,
 * DEEP: those in its folders too */
static void fb_mark_d(int folder, int deep)
{
    int m, n = fb_size_d(folder, &m, deep), on = m < n;
    if (smp_fb_store == 1) {
        for (int k = 0; k < LB_CAP; k++)
            if (deep ? lb_under(k, folder) : lb_in(k, folder))
                lb_mark(k, on);
        return;
    }
    for (int k = 0; k < 128; k++)
        if (!smp_slot_empty(k) && fb_in(k, folder))
            smp_fb_mark(k, on);
}

void smp_fb_mark_folder(int folder) { fb_mark_d(folder, 1); }   /* a folder's row: all it holds */
void smp_fb_mark_here(void) { fb_mark_d(smp_fb_folder, 0); }     /* v0.40: SELECT ALL in a list: its samples */

static int lb_any_marks(void)
{
    for (int i = 0; i < LB_CAP / 32; i++)
        if (lb_marks[i])
            return 1;
    return 0;
}

int smp_fb_folder_full(int folder)              /* every one of its samples marked */
{
    if (smp_fb_store == 1 && !lb_any_marks())   /* v0.40: (each folder row asks, each redraw) */
        return 0;
    int m, n = fb_size(folder, &m);
    return n > 0 && m == n;
}

int smp_fb_here_full(void)                      /* v0.40: every sample of the open list marked */
{
    int m, n = fb_size_d(smp_fb_folder, &m, 0);
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
        /* v0.40: the folders that go, deepest first (lib.c refuses one that still holds a
         * sample or a folder, so a folder goes only once all inside it has gone: a power cut
         * between any two writes leaves every sample not yet deleted in a folder shown) */
        u32 drop[SMP_LIB_FOLDERS / 32];
        for (int w_ = 0; w_ < SMP_LIB_FOLDERS / 32; w_++)
            drop[w_] = 0;
        int chain[8], nc = 0;                   /* where the browser is, and the folders above */
        for (int g = smp_fb_folder; g >= 0 && nc < 8; g = smp_lib_folder_parent(g))
            chain[nc++] = g;
        if (smp_fb_mark_count()) {
            /* v0.35: a folder emptied this way (ticked whole, FUNC + YES, then DELETE) goes
             * too, as one deleted by name does (Kokozi, v0.33: deleted folders stayed in the
             * list, empty); v0.40: and a folder every sample of which was ticked (its row's
             * FUNC + YES), with the folders inside it */
            for (int f = 2; f < SMP_LIB_FOLDERS; f++)
                if (smp_fb_folder_full(f))
                    for (int g = 2; g < SMP_LIB_FOLDERS; g++)
                        if (smp_lib_folder_under(g, f))
                            drop[g >> 5] |= 1u << (g & 31);
            for (int k = 0; k < LB_CAP; k++)
                if (!lb_marks[k >> 5])
                    k |= 31;                    /* v0.45: a word with nothing ticked, skipped */
                else if (lb_marked(k) && smp_lib_used(k)) {
                    int f = smp_lib_folder_of(k);
                    if (f >= 2 && f < SMP_LIB_FOLDERS)
                        drop[f >> 5] |= 1u << (f & 31);
                    smp_lib_delete(k);
                }
        } else if (slot >= 0)
            smp_lib_delete(slot);
        else if (folder != -1) {
            for (int k = 0; k < LB_CAP; k++)    /* v0.40: and in its folders, any depth */
                if (lb_under(k, folder))
                    smp_lib_delete(k);
            for (int g = 2; g < SMP_LIB_FOLDERS; g++)        /* v0.33: emptied: the folder goes too; v0.40: */
                if (smp_lib_folder_under(g, folder))    /* with its folders */
                    drop[g >> 5] |= 1u << (g & 31);
        }
        extern int smp_lib_folder_drop(int f);
        for (int d = 8; d >= 1; d--)
            for (int f = 2; f < SMP_LIB_FOLDERS; f++)
                if ((drop[f >> 5] >> (f & 31) & 1) && smp_lib_folder_depth(f) == d)
                    smp_lib_folder_drop(f);     /* (refused while it still holds anything) */
        if (nc && smp_fb_folder >= 0 && smp_lib_folder_count(smp_fb_folder) == 0
            && !smp_lib_folder_name(smp_fb_folder)[0]) {
            int to = -1;                        /* v0.40: the browser was in a folder that went: */
            for (int j = 1; j < nc && to < 0; j++)       /* to the nearest one above still there */
                if (smp_lib_folder_name(chain[j])[0])
                    to = chain[j];
            smp_fb_folder = to;
            smp_fb_cur = 0;
        }
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
            if (!lb_marks[k >> 5])
                k |= 31;                        /* v0.45: a word with nothing ticked, skipped */
            else if (lb_marked(k) && smp_lib_used(k))
                n += smp_lib_load(k) == 0;
    } else if (slot >= 0)
        n += smp_lib_load(slot) == 0;
    else if (folder != -1)
        for (int k = 0; k < LB_CAP; k++)
            if (lb_under(k, folder))            /* v0.40: and its folders' */
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
/* v0.45: 32 KB at 16,384 entries: in the mirror (lib.c's free part, + 0x3E0000) */
#define lb_list ((u16 *)(SMP_MIRROR + 0x3E0000u))
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
    if (smp_fb_store == 1) {                    /* v0.40: the folders in it, then its samples */
        for (int f = 0; f < SMP_LIB_FOLDERS; f++)
            n += lb_has(f) && smp_lib_folder_parent(f) == smp_fb_folder;
        if (smp_fb_folder == -1)
            return n;
        lb_list_make();
        return n + lb_list_n;
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
    if (smp_fb_store == 1) {                    /* v0.40: the folders in it, then its samples */
        for (int f = 0; f < SMP_LIB_FOLDERS; f++)
            if (lb_has(f) && smp_lib_folder_parent(f) == smp_fb_folder && i-- == 0)
                return f;
        if (smp_fb_folder == -1)
            return -1;
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

/* the item that is folder F in the list it is in (to land on it coming back up): the top's,
 * v0.40: in +DRIVE its parent's */
int smp_fb_index_of(int f)
{
    int keep = smp_fb_folder, n, slot;
    smp_fb_folder = smp_fb_store == 1 ? smp_lib_folder_parent(f) : -1;
    n = smp_fb_count();
    for (int i = 0; i < n; i++)
        if (smp_fb_item(i, &slot) == f && slot < 0) {
            smp_fb_folder = keep;
            return i;
        }
    smp_fb_folder = keep;
    return 0;
}

/* v0.40: NO (or LEFT) in a folder: up a level, onto the folder left. -> 0 at a store's top */
int smp_fb_up(void)
{
    if (smp_fb_folder == -1)
        return 0;
    int back = smp_fb_folder;
    smp_fb_cur = smp_fb_index_of(back);         /* (its parent's list) */
    smp_fb_folder = smp_fb_store == 1 ? smp_lib_folder_parent(back) : -1;
    return 1;
}

/* v0.40: the open folder's path for the title, "TRANCE STARTER PACK/KICKS/808" */
static void fb_path(int f, char *out, int room)
{
    int chain[8], n = 0, o = 0;
    for (; f >= 0 && n < 8; f = smp_lib_folder_parent(f))
        chain[n++] = f;
    while (n-- > 0) {
        const char *nm = smp_lib_folder_name(chain[n]);
        for (int j = 0; nm[j] && j < 31 && o < room - 2; j++)
            out[o++] = nm[j];
        if (n && o < room - 2)
            out[o++] = '/';
    }
    out[o] = 0;
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
    return on_folder ? 3 : 5;                   /* v0.45: SELECT UNUSED */
}

/* the action at place A of the SAMPLE ACTION menu: 0 LOAD TO TRK, 1 RENAME, 2 DELETE (in
 * PROJECT RAM: UNLOAD), 3 SELECT ALL, 4 LOAD TO PROJECT (v0.31: +DRIVE), 5 MOVE SELECTED,
 * 6 MOVE HERE, 7 CREATE FOLDER (v0.33: +DRIVE), 8 SELECT UNUSED (v0.45: PROJECT RAM) */
int smp_fb_action(int on_folder, int a)
{
    static const signed char ram_s[5] = {0, 1, 2, 3, 8}, ram_f[3] = {3, 2, 8};   /* v0.45: 8 SELECT UNUSED, last: DELETE keeps its place */
    if (smp_fb_store == 1) {
        signed char l[8];
        int n = lib_actions(on_folder, l);
        return l[a < 0 ? 0 : a > n - 1 ? n - 1 : a];
    }
    return on_folder ? ram_f[a < 0 ? 0 : a > 2 ? 2 : a] : ram_s[a < 0 ? 0 : a > 4 ? 4 : a];
}

/* v0.39: ERASE MOD DATA's screens (erase.c; the keys in rec.c): the two questions, the
 * progress, the result. -> 1 if drawn */
static void hex6(char *o, u32 v)
{
    for (int k = 0; k < 6; k++)
        o[k] = "0123456789ABCDEF"[(v >> (20 - 4 * k)) & 15u];
    o[6] = 0;
}

static int er_draw(void *c)
{
    extern int smp_er_shown(void), smp_er_err, smp_er_can_resume(void);
    extern u32 smp_er_percent(void), smp_er_sector;
    int es = smp_er_shown();
    if (smp_fb_menu < 4 && !es)
        return 0;
    LABEL(c, 64, 57, "%s", "ERASE MOD DATA");
    hline(c, 0, 127, 55, 0);
    if (es == 1 || es == 2) {
        int pc = (int)smp_er_percent();
        TEXT(c, FONT, 64, 40, CENTRED, "%s %d%%", es == 1 ? "ERASING" : "VERIFYING", pc > 100 ? 100 : pc);
        box(c, 14, 25, 113, 33, 0);
        if (pc > 0)
            fill(c, 15, 26, 15 + (97 * (pc > 100 ? 100 : pc)) / 100, 32);
        LABEL(c, 64, 12, "%s", "DO NOT POWER OFF");
    } else if (es == 3) {
        TEXT(c, FONT, 64, 38, CENTRED, "%s", "ERASED");
        LABEL(c, 64, 24, "%s", "RESTART THE DIGITONE");
        LABEL(c, 64, 12, "%s", "YES / NO: CLOSE");
    } else if (es == 4) {
        /* v0.40: what failed, where, and what to do: a failure a new try may get past carries
         * on when asked again (the samples are already gone: their headers went first) */
        static const char *const why[7] = {"", "REFUSED", "CARD ERASE FAILED", "CARD READ FAILED", "NOT ERASED",
                                           "+DRIVE NOT READY", "CARD STAYED BUSY"};
        char h[7];
        hex6(h, smp_er_sector);
        int go_on = smp_er_can_resume();
        TEXT(c, FONT, 64, 42, CENTRED, "%s", go_on ? "ERASE PAUSED" : "ERASE FAILED");
        LABEL(c, 64, 31, "%s", why[smp_er_err >= 1 && smp_er_err <= 6 ? smp_er_err : 0]);
        LABEL(c, 64, 22, "AT SECTOR %s", h);
        LABEL(c, 64, 10, "%s", go_on ? "ASK AGAIN TO CONTINUE" : "RESTART, THEN AGAIN");
    } else if (smp_fb_menu == 4) {
        TEXT(c, FONT, 64, 40, CENTRED, "%s", "ERASE ALL SAMPLES");
        TEXT(c, FONT, 64, 30, CENTRED, "%s", "AND MOD DATA?");
        LABEL(c, 64, 14, "%s", "YES / NO");
    } else {
        TEXT(c, FONT, 64, 40, CENTRED, "%s", "ARE YOU SURE?");
        TEXT(c, FONT, 64, 30, CENTRED, "%s", "IT CANNOT BE UNDONE");
        LABEL(c, 64, 14, "%s", "YES / NO");
    }
    return 1;
}

/* v0.39: the browser's characters a name: what fits before the slot (">A003") or the
 * folder icon at x 109 in the widest glyphs (five pixels; v0.38 cut at 18 and let the
 * rest run under the label); with the action menu up, before it (x 62) */
#define FB_W 21
#define FB_SLOT_W 21
#define FB_MENU_W 11
_Static_assert(FB_SLOT_W <= FB_W && FB_MENU_W <= FB_W && FB_W < 24, "a row's name fits its buffers (FB_W + 3, the record's 24)");
char smp_fb_rowtext[6][24] __attribute__((section(".data")));   /* each row's name as drawn, once all are (the gate reads it) */
#define FB_TITLE_W 22                           /* v0.40: +DRIVE's title, the open folder's path */
char smp_fb_titletext[24] __attribute__((section(".data")));    /* as last drawn (the gate reads it) */
static char rows_drawn[6][24] __attribute__((section(".data")));
static void row_text(int r, const char *nm)
{
    int j = 0;
    for (; j < 23 && nm[j]; j++)
        rows_drawn[r][j] = nm[j];
    for (; j < 24; j++)
        rows_drawn[r][j] = 0;
}
static u32 fb_key(void)                         /* which row is selected, where */
{
    return 0x80000000u | (u32)((smp_fb_store + 2) & 3) << 28 | (u32)((smp_fb_folder + 8) & 0xFF) << 20
           | (u32)(smp_fb_menu & 7) << 16 | (u32)(smp_fb_cur & 0xFFFF);   /* 0..6: v0.39's ERASE menus too */
}

/* rec_poll, every UI pass: the selected row's marquee (above) */
void smp_marquee_poll(void)
{
    if (smp_fb_open) {
        u32 key = fb_key();
        if (key == mq_key) {                    /* the same row: only the clock (no lookups) */
            mq_follow(key, 0, 0);
            return;
        }
        int n = smp_fb_count(), slot;
        if (smp_fb_cur < 0 || smp_fb_cur >= n || smp_fb_menu == 2) {
            mq_follow(key, 0, 0);
            return;
        }
        int f = smp_fb_item(smp_fb_cur, &slot), w = smp_fb_menu ? FB_MENU_W : FB_W;
        char ln[64];
        const char *nm = ln;
        if (slot < 0)
            nm = fb_folder_name(f);
        else if (smp_fb_store == 1)
            nm = smp_lib_name(slot);
        else {
            slot_name(slot + 1, ln, 63);
            w = smp_fb_menu ? FB_MENU_W : FB_SLOT_W;
        }
        mq_follow(key, nm, w);
    } else if (smp_lst_open && list_slot >= 0) {
        char ln[64];
        if (LIST_KEY(list_slot) == mq_key)
            mq_follow(mq_key, 0, 0);
        else {
            slot_name(list_slot, ln, 63);
            mq_follow(LIST_KEY(list_slot), ln, LIST_W);
        }
    } else
        mq_key = 0xFFFFFFFFu;                   /* closed: it starts again when opened */
}

void smp_fb_draw(void *c, int samp)
{
    for (int y = 0; y <= 63; y++)
        for (int x = 0; x <= 127; x++)
            SET_PIXEL(c, x, y, 0);
    if (er_draw(c))
        return;
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
    else if (smp_fb_store == 1) {               /* v0.40: the path, head...tail if long */
        char path[200], t[FB_TITLE_W + 3];
        fb_path(smp_fb_folder, path, (int)sizeof path);
        fit_name(path, FB_TITLE_W, -1, t);
        folder_icon(c, 2, 57);
        LABEL(c, 64, 57, "%s", t);
        for (int j = 0; j < 24; j++)
            smp_fb_titletext[j] = j < FB_TITLE_W + 2 ? t[j] : 0;
    } else {
        folder_icon(c, 2, 57);
        LABEL(c, 64, 57, "%.22s", fb_folder_name(smp_fb_folder));
    }
    hline(c, 0, 127, 55, 0);
    int n = smp_fb_count();
    if (n == 0) {
        TEXT(c, FONT, 64, 28, CENTRED, "%s", smp_fb_store == 1 ? (smp_fb_folder == -1 ? "+DRIVE EMPTY" : "EMPTY FOLDER")
                                                 : "NO SAMPLES");
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
    for (int r = 0; r < 6; r++)
        row_text(r, "");
    for (int r = 0; r < 6 && top + r < n; r++) {
        int i = top + r, y = 46 - 9 * r, slot;
        int f = smp_fb_item(i, &slot);
        if (slot < 0) {
            char nm[FB_W + 3];
            fit_name(fb_folder_name(f), smp_fb_menu ? FB_MENU_W : FB_W, i == smp_fb_cur ? mq_off(fb_key()) : -1, nm);
            TEXT(c, FONT, 3, y, 0, "%s", nm);
            row_text(r, nm);
            if (!smp_fb_menu)
                folder_icon(c, 112, y);
            if (smp_fb_folder_full(f))          /* v0.29: every sample in it marked */
                invert(c, 1, y - 1, wide - 1, y + 6);
        } else if (smp_fb_store == 1) {         /* v0.31: a library sample; its slot if in the pool */
            char sn[4];
            int s = smp_lib_slot_of(slot);
            char nm[FB_W + 3];                       /* v0.39: head...tail; the selected one scrolls */
            fit_name(smp_lib_name(slot), smp_fb_menu ? FB_MENU_W : FB_W, i == smp_fb_cur ? mq_off(fb_key()) : -1, nm);
            TEXT(c, FONT, 3, y, 0, "%s", nm);
            row_text(r, nm);
            if (!smp_fb_menu && s >= 0) {
                num3(sn, s + 1);
                LABEL(c, 109, y, ">A%s", sn);
            }
            if (smp_fb_marked(slot))
                invert(c, 2, y - 1, wide - 1, y + 6);
        } else {
            char ln[64], nm[FB_W + 3], sn[4];
            slot_name(slot + 1, ln, 63);
            fit_name(ln, smp_fb_menu ? FB_MENU_W : FB_SLOT_W, i == smp_fb_cur ? mq_off(fb_key()) : -1, nm);
            TEXT(c, FONT, 3, y, 0, "%s", nm);
            row_text(r, nm);
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
    for (int r = 0; r < 6; r++)
        for (int j = 0; j < 24; j++)
            smp_fb_rowtext[r][j] = rows_drawn[r][j];
    scrollbar(c, 126, 1, 53, smp_fb_cur, n);
#ifdef MOD_VERSION
    if (smp_fb_store == -1 && !smp_fb_menu)     /* v0.39: the mod's version under the two stores */
        LABEL(c, 64, 3, "%s", "MOD v" MOD_VERSION);
#endif
    if (smp_fb_menu == 3) {                     /* v0.39: +DRIVE's own menu (the top): ERASE MOD DATA */
        for (int y = 0; y <= 54; y++)
            for (int x = 65; x <= 124; x++)
                SET_PIXEL(c, x, y, 0);
        vline(c, 65, 0, 54, 1);
        TEXT(c, FONT, 68, 46, 0, "%s", "ERASE MOD");
        TEXT(c, FONT, 68, 37, 0, "%s", "DATA");
        box(c, 66, 35, 124, 54, 0);
        return;
    }
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
        int all = on_folder ? smp_fb_folder_full(f) : smp_fb_here_full();   /* v0.40: a list: its own */
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
            else if (act == 8)
                TEXT(c, FONT, 68, y, 0, "%s", "SEL UNUSED");
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
    extern u32 slc_seen_draw;
    slc_page_seen = kind == SMP_SLICE_KIND ? 1 : kind == SMP_GRID_KIND ? 2 : 0;   /* YES: SLICE's menu, GRID's ALLOCATE SLICE (slice.c) */
    slc_seen_draw = wr_draws;                   /* v0.42: drawn in this screen (slice.c's page_up) */
    for (int i = 0; i < 8; i++)
        ids[i] = smp_ids[SMP_IDX(kind)][i];
    smp_box(c);
    if (!wave) {                                /* page 1: the widgets and their labels */
        for (int i = 0; i < 8; i++) {
            cell_i = i;
            cell(c, view, kind, ids[i], CELL_X(i & 3), i < 4 ? TOP_Y : BOT_Y, 1, 0);
        }
        cell_i = -1;
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
        int a = pos_x(view, SMP_STRT_ID, w - 1);   /* v0.48: the fine word, 0..120.00 */
        int b = a + pos_x(view, SMP_LEN_ID, w - 1);
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
            int lp = pos_x(view, SMP_LOOP_ID, w - 1);
            int mode = value(view, SMP_PLAY_ID, 0) * 4 / 128;
            if (mode == 1 || mode == 2)
                marker(c, x0 + lp, cy, 1);
        }
    }
    if (slot >= 1 && smp_overview(slot - 1))
        playhead(c, x0, w, cy);
    else {
        ph_was = -1;
        ph_draw_n = wr_draws - 1u;              /* (no playhead on it: nothing to follow) */
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
        else if (shows(i)) {                    /* v0.35: SYN held (v0.48: or just turned): the value (O14) */
            char vb[32];
            u8 flag;
            vb[0] = 0;
            ((void (*)(int, char *))RECORD_FMT(ids[i]))(GET_VALUE(view, ids[i], &flag), vb);
            vb[6] = 0;
            LABEL(c, x + 12, 0, "%s", vb);
        } else
            LABEL(c, x + 12, 0, "%.5s", NAME_SHORT(ids[i]));
    }
    for (int i = 0; i < 4; i++)                 /* v0.35: the top row's too (unlabelled: on the knobs' line) */
            if (ids[i] && shows(i)) {
                char vb[32];
                u8 flag;
                vb[0] = 0;
                ((void (*)(int, char *))RECORD_FMT(ids[i]))(GET_VALUE(view, ids[i], &flag), vb);
                vb[6] = 0;
                LABEL(c, CELL_X(i) + 12, TOP_Y + 3 - 7, "%s", vb);
            }
    if (ids[7]) {
        int top, v = value(view, ids[7], &top);
        w_pill(c, CELL_X(3), 0, v, top);
    }
    /* v0.50 (impbox: "p-locks are not visible on sample page 2"): a locked control's place on
     * the bottom row inverted, as page 1's cells are (cell()); v0.20..v0.49 drew this row's
     * labels and LEV's pill without looking */
    for (int i = 4; i < 8; i++)
        if (ids[i] && locked(view, ids[i]))
            invert(c, CELL_X(i - 4) - 1, 0, CELL_X(i - 4) + 24, 6);
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
extern char nm_text[36];
extern int nm_max;
/* v0.46: the name field shows 14 of up to 35 characters, scrolled to keep the cursor in view;
 * << and >> where there is more of the field either side (the DT2's >>) */
#define NM_VIEW 14
static int nm_off __attribute__((section(".data"))) = 0;
static void name_field(void *c, int y, int bar_y0, int bar_y1)
{
    if (nm_cur < nm_off)
        nm_off = nm_cur;
    if (nm_cur >= nm_off + NM_VIEW)
        nm_off = nm_cur - NM_VIEW + 1;
    if (nm_off > 0 && nm_max <= NM_VIEW)
        nm_off = 0;
    for (int v = 0; v < NM_VIEW && nm_off + v < nm_max; v++) {
        int j = nm_off + v, x = 14 + 8 * v;
        char ch = nm_text[j] ? nm_text[j] : ' ';
        if (ch != ' ')
            LABEL(c, x, y, "%c", ch);
        if (j == nm_cur)                        /* the cursor: a bar under it */
            fill(c, x - 3, bar_y0, x + 3, bar_y1);
    }
    if (nm_off > 0)
        LABEL(c, 10, y + 10, "%s", "<<");
    if (nm_off + NM_VIEW < nm_max)
        LABEL(c, 118, y + 10, "%s", ">>");
}

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

/* v0.40: the TRIM preview's playhead (rec.c's rec_pv_frame), a column across the waveform
 * at the frame playing, cleared either side so it reads over the wave; the column drawn
 * kept for the checks (-1: none) */
int trim_head_x __attribute__((section(".data"))) = -1;
extern int rec_pv_frame(void);

static void trim_head(void *c, int x0, int x1, int yc, int h, int zoomed)
{
    int f = rec_pv_frame(), x = -1;
    u32 n = trim_n ? trim_n : 1u, w = (u32)(x1 - x0 + 1);
    if (f >= 0 && (u32)f < n) {
        if (!zoomed)
            x = x0 + (int)(((u32)f >> 4) * w / ((n >> 4) + 1u));
        else {
            u32 span = n >> trim_zoom, a = trim_pos;
            if (!span)
                span = 1;
            if ((u32)f >= a && (u32)f < a + span)
                x = x0 + (int)(((u32)f - a) / ((span / w) + 1u));
        }
    }
    if (x > x1)
        x = x1;
    trim_head_x = x;
    if (x < x0)
        return;
    for (int y = yc - h - 1; y <= yc + h + 1; y++) {
        if (x > x0)
            SET_PIXEL(c, x - 1, y, 0);
        on(c, x, y);
        if (x < x1)
            SET_PIXEL(c, x + 1, y, 0);
    }
}

static void trim_draw(void *c)
{
    box(c, 2, 55, 125, 63, 0);
    LABEL(c, 64, 57, "%s", "Y:SAVE FN+N:DEL FN+Y:PLAY");
    box(c, 2, 11, 125, 53, 0);
    extern int smp_analysis_slot(void);
    trim_head_x = -1;
    if (trim_zoom > 0 && smp_analysis(0) == 2 && smp_analysis_slot() == trim_slot) {
        wave_zoom(c, 4, 123, 32, 17, trim_s, trim_e, trim_n ? trim_n : 1);
        trim_head(c, 4, 123, 32, 17, 1);
    } else if (smp_overview(trim_slot)) {
        wave(c, trim_slot, 4, 123, 32, 18, trim_s, trim_e, trim_n ? trim_n : 1);
        trim_head(c, 4, 123, 32, 18, 0);
    } else {
        LABEL(c, 64, 30, "%s", "NO WAVEFORM");
        trim_head(c, 4, 123, 32, 18, 0);
    }
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
    name_field(c, 44, 42, 42);
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
    name_field(c, 40, 37, 38);
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

/* v0.41 (docs/rectrig.md): H's place with a step held: that step's REC trig (OFF, REC 1,
 * REC 2), drawn inverted when the step has one, as a p-lock; -> 1 drawn */
/* v0.44 BOUNCE: the RECORDER of a BOUNCE track (rec.c bn_*; rectrig.c), one page: its title,
 * meter and SRC/CHAN (drawn by rec_screen_draw), then the RECORD box's place as the status
 * line (what the buffer and the track's recorder trigs are doing, always), THRES's place
 * the page's sixteen steps (a filled cell a recorder trig, an open one a one-shot, a struck
 * one a spent one-shot; the [TRIG] keys toggle them, PAGE turns the page), and the bottom
 * row E Q.REC, F Q.PLAY, G R.LEN, H the one-shots (YES YES arms them again) */
/* v0.49 FLEX REC (docs/flex-design.md; the owner's mockup sheets, docs/flex-mockups/): two pages,
 * LEFT and RIGHT between them. REC TRIGS: the title with the track and the page of steps, the
 * buffer's state (EMPTY, READY and its length, REC with its steps so far and a progress bar),
 * what just happened or what to do, the page's 16 steps as two rows of eight numbered cells
 * (filled a recorder trig, hatched a one-shot, struck a spent one, the playing step underlined),
 * and the legend. REC SETUP: the grid of eight, A SRC, B CHAN, C BUF (inverted, as the track's
 * BUF), D R.LEN, E ARM, F Q.REC, each a choice in its box, its name under it (four detents a
 * choice; G GAIN, v0.52 H MUTE SRC, the meter in the left column). Every value at its cell's place and baseline */
static void choice(void *c, int k, int y, const char *text, const char *name, int inverted)
{
    int x = CELL_X(k), cx = x + 12;
    box(c, cx - 11, y + 3, cx + 11, y + 13, 0);
    LABEL(c, cx, y + 6, "%.5s", text);
    if (inverted)
        invert(c, cx - 10, y + 4, cx + 10, y + 12);
    LABEL(c, cx, y - 7, "%.5s", name);
}

static void step_cell(void *c, int x, int y, u32 v, int head)
{
    if (v == 1)
        fill(c, x, y, x + 6, y + 6);                     /* a recorder trig: filled */
    else if (v == 2) {                                   /* a one-shot: hatched */
        box(c, x, y, x + 6, y + 6, 0);
        for (int j = 1; j <= 5; j++) {
            on(c, x + j, y + j);
            if (j <= 3) on(c, x + j + 2, y + j);
            if (j >= 3) on(c, x + j - 2, y + j);
        }
    } else if (v == 3) {                                 /* a spent one-shot: dotted, one stroke */
        box(c, x, y, x + 6, y + 6, 1);
        for (int j = 1; j <= 5; j++)
            on(c, x + j, y + j);
    } else
        box(c, x, y, x + 6, y + 6, 1);                   /* none: a dotted cell */
    if (head)
        hline(c, x, x + 6, y - 2, 0);
}

static void bn_view_draw(void *c, int heard)
{
    extern int rt_on, rt_qrec, rt_arm, rec_rlen, bn_page, bn_sub, rec_src, rec_chan, rec_gain;
    extern u32 rt_why, rt_why_at, rt_why_trk, rt_fired_at, rt_fired_trk, bn_said_at, bn_nothing_at;
    extern int bn_said_n;
    extern int rt_state(int b, int *tenths, int *steps);
    extern u32 rt_buf_of(u32 t);
    extern const char *rt_qname(int q);
    extern unsigned char *sl_ui_table_now(void);
    extern u32 rt_trig_get(const unsigned char *table, u32 t, u32 step);
    extern u32 rt_count(const unsigned char *table, u32 t, u32 *trigs, u32 *oneshots, u32 *spent);
    extern u32 bn_pages(void);
    extern int rt_req_waiting(void);
    static const char *const WHY[5] = {"", "NO BUFFERS", "MANUAL REC", "NO ROOM", "BUSY"};
    u32 t = UI_TRACK;
    u32 b = rt_buf_of(t);
    char tl[24];
    /* v0.51 (owner; Error Kit: "how do I delete a buffer?"): FUNC + NO on REC SETUP asks before
     * the track's buffer is emptied (rec.c bn_clear_ask, rectrig.c rt_clear) */
    extern int bn_clear_ask, bn_cleared;
    extern u32 bn_cleared_at;
    if (bn_sub && bn_clear_ask) {
        LABEL_TEXT(c, LABEL_FONT, 2, 57, 0, 0, 0, "T%02d FLEX REC SETUP", (int)t + 1);
        hline(c, 0, 127, 54, 0);
        TEXT(c, FONT, 64, 38, CENTRED, "CLEAR BUF %02d?", (int)b + 1);
        LABEL(c, 64, 26, "%s", "ITS TAKE IS GONE");
        LABEL(c, 64, 12, "%s", "YES / NO");
        return;
    }
    if (bn_sub) {                                /* REC SETUP */
        LABEL_TEXT(c, LABEL_FONT, 2, 57, 0, 0, 0, "T%02d FLEX REC SETUP", (int)t + 1);
        hline(c, 0, 127, 54, 0);
        const char *src = smp_rec_src[rec_src > SMP_REC_SOURCES - 1 ? SMP_REC_SOURCES - 1 : rec_src < 0 ? 0 : rec_src];
        static const char *const CH[3] = {"L+R", "L", "R"};
        char bufs[4], rl[6];
        bufs[0] = '0'; bufs[1] = (char)('1' + b); bufs[2] = 0;
        if (rec_rlen <= 0) {
            rl[0] = 'M'; rl[1] = 'A'; rl[2] = 'X'; rl[3] = 0;
        } else {
            int n = rec_rlen, k = 0;
            if (n >= 100) rl[k++] = (char)('0' + n / 100);
            if (n >= 10) rl[k++] = (char)('0' + n / 10 % 10);
            rl[k++] = (char)('0' + n % 10);
            rl[k] = 0;
        }
        choice(c, 0, TOP_Y, src, "SRC", 0);
        choice(c, 1, TOP_Y, CH[rec_chan < 0 ? 0 : rec_chan > 2 ? 2 : rec_chan], "CHAN", 0);
        choice(c, 2, TOP_Y, bufs, "BUF", 1);
        choice(c, 3, TOP_Y, rl, "RLEN", 0);
        choice(c, 0, BOT_Y, rt_arm ? "ON" : "OFF", "ARM", rt_arm);
        choice(c, 1, BOT_Y, rt_qname(rt_qrec), "QREC", 0);
        /* v0.50 (impbox: takes far quieter than their source): G GAIN, the take's level in dB (0:
         * at the FLEX track's defaults a take plays as loud as its source), set before recording
         * with H's meter: the source as the take will hold it, GAIN applied, full scale at its
         * right end */
        {
            char gb[5];
            int g = rec_gain < -24 ? -24 : rec_gain > 38 ? 38 : rec_gain, k = 0, m = g < 0 ? -g : g;
            gb[k++] = g < 0 ? '-' : g > 0 ? '+' : ' ';
            if (m >= 10) gb[k++] = (char)('0' + m / 10);
            gb[k++] = (char)('0' + m % 10);
            gb[k] = 0;
            choice(c, 2, BOT_Y, g ? gb : "0", "GAIN", 0);
            /* v0.52 (owner: MUTE SRC in the meter's place): the meter in the left column, its top level
             * with the bottom row's boxes' (two rows clear of the arrow); CLIP over it in the 3x5
             * glyphs when the take would clip, under the take's length */
            int mx0 = 1, mx1 = 17, my0 = BOT_Y + 7, my1 = BOT_Y + 13, w = mx1 - mx0 - 2;
            box(c, mx0, my0, mx1, my1, 0);
            int lv = heard ? meter_x(rec_peak, w) : 0;
            if (lv > 0)
                fill(c, mx0 + 1, my0 + 1, mx0 + lv, my1 - 1);
            if (heard && rec_peak >= 32700)     /* at full scale: the take clips */
                glyphs_at(c, 9, BOT_Y + 15, "CLIP");
        }
        /* v0.52 (owner, option B): H MUTE SRC: ON takes the SRC track out of the mix (LEVEL and the
         * sends, rectrig.c ms_frame) while it is ON; "--" when SRC is IN or MAIN (nothing to mute) */
        {
            extern int bn_mute;
            int trk = rec_src >= 2 && rec_src - 2 != (int)t;
            choice(c, 3, BOT_Y, trk ? (bn_mute ? "ON" : "OFF") : "--", "MUTE", trk && bn_mute);
        }
        /* v0.49 (owner): the buffer's state, no box: a dot and REC while it records, WAIT while a
         * take waits for Q.REC, else READY and its length, or EMPTY. v0.50: in the title line's
         * right end (G and H are GAIN and the meter). v0.51 (owner: "weirdly shifted to the right";
         * the grid leaves the screen's left 21 pixels free, the DT2's way): in that left column,
         * the word level with the top row's values, the take's length under it, LEFT's arrow at
         * the bottom */
        {
            /* in the 3x5 glyphs (4 pixels a character: READY and EMPTY fit the 21-pixel column;
             * the label font's capitals did not) */
            int tenths, steps, st = rt_state((int)b, &tenths, &steps);
            (void)steps;
            const char *word = st == 1 ? "REC" : st ? "READY" : "EMPTY";
            if (bn_cleared == 2 && FRAMES_NOW - bn_cleared_at < 3000u)   /* v0.51: CLEAR while it records */
                word = "BUSY";
            else if (rt_req_waiting())
                word = "WAIT";
            glyphs_at(c, 9, TOP_Y + 7, word);
            if (st == 1 && word[0] == 'R')                       /* recording: a dot over the word */
                fill(c, 8, TOP_Y + 14, 10, TOP_Y + 16);
            if (st) {
                char len[8];
                int k = 0, s10 = tenths / 10;
                if (s10 >= 10) len[k++] = (char)('0' + s10 / 10 % 10);
                len[k++] = (char)('0' + s10 % 10);
                len[k++] = '.';
                len[k++] = (char)('0' + tenths % 10);
                len[k++] = 'S';
                len[k] = 0;
                glyphs_at(c, 9, TOP_Y - 6, len);
            }
        }
        LABEL_TEXT(c, LABEL_FONT, 2, 0, 0, 0, 0, "%s", "<");
        return;
    }
    /* REC TRIGS */
    u32 pages = bn_pages(), first = (u32)bn_page * 16u;
    tl[0] = 0;
    LABEL_TEXT(c, LABEL_FONT, 2, 57, 0, 0, 0, "T%02d FLEX REC TRIGS", (int)t + 1);
    if (pages > 1)
        LABEL_TEXT(c, LABEL_FONT, 125, 57, 2, 0, 0, "%d/%d", bn_page + 1, (int)pages);
    hline(c, 0, 127, 54, 0);
    unsigned char *table = sl_ui_table_now();
    u32 nt = 0, no = 0, ns = 0, all = table ? rt_count(table, t, &nt, &no, &ns) : 0;
    int tenths, steps, st = rt_state((int)b, &tenths, &steps);
    /* line 1: the buffer */
    int y1 = 46, y2 = 38;
    if (!rt_on)
        LABEL_TEXT(c, LABEL_FONT, 2, y1, 0, 0, 0, "%s", "NO +DRIVE POOL");
    else if (st == 1) {
        fill(c, 2, y1 + 1, 4, y1 + 3);           /* a solid dot: recording */
        LABEL_TEXT(c, LABEL_FONT, 7, y1, 0, 0, 0, "BUF%02d REC %d.%dS", (int)b + 1, tenths / 10, tenths % 10);
    } else if (st)
        LABEL_TEXT(c, LABEL_FONT, 2, y1, 0, 0, 0, "BUF%02d READY %d.%dS", (int)b + 1, tenths / 10, tenths % 10);
    else
        LABEL_TEXT(c, LABEL_FONT, 2, y1, 0, 0, 0, "BUF%02d EMPTY", (int)b + 1);
    /* line 2: what just happened, else what to do */
    u32 now = FRAMES_NOW;
    if (rt_req_waiting())
        LABEL_TEXT(c, LABEL_FONT, 2, y2, 0, 0, 0, "WAIT REC: QREC %s", rt_qname(rt_qrec));
    else if (bn_nothing_at && now - bn_nothing_at < 3000u)
        LABEL_TEXT(c, LABEL_FONT, 2, y2, 0, 0, 0, "%s", "NOTHING TO SAVE");
    else if (bn_said_at && now - bn_said_at < 3000u)
        LABEL_TEXT(c, LABEL_FONT, 2, y2, 0, 0, 0, "%d ONE-SHOTS ARMED", bn_said_n);
    else if (rt_why_at && now - rt_why_at < 4500u && rt_why_trk == t && rt_why >= 1 && rt_why <= 4)
        LABEL_TEXT(c, LABEL_FONT, 2, y2, 0, 0, 0, "REC REFUSED: %s", WHY[rt_why]);
    else if (rt_fired_at && now - rt_fired_at < 1500u && rt_fired_trk == t)
        LABEL_TEXT(c, LABEL_FONT, 2, y2, 0, 0, 0, "%s", "TRIG: RECORDING");
    else if (!rt_arm)
        LABEL_TEXT(c, LABEL_FONT, 2, y2, 0, 0, 0, "%s", "ARM OFF: TRIGS KEPT");
    else if (!all)
        LABEL_TEXT(c, LABEL_FONT, 2, y2, 0, 0, 0, "%s", "[TRIG] PLACES A ONE-SHOT");
    else
        LABEL_TEXT(c, LABEL_FONT, 2, y2, 0, 0, 0, "%d REC  %d ONE-SHOT", (int)nt, (int)(no + ns));
    /* the page's 16 steps: two rows of eight, numbered */
    for (int i = 0; i < 16; i++) {
        int col = i & 7, row = i >> 3;
        int x = 4 + 16 * col, y = row ? 8 : 22;
        u32 step = first + (u32)i;
        u32 v = table ? rt_trig_get(table, t, step) : 0xFFFFu;
        LABEL(c, x + 3, y + 8, "%d", (int)step + 1);
        step_cell(c, x, y, v == 0xFFFFu ? 0 : v, 0);
    }
    /* the legend */
    fill(c, 4, 1, 7, 4);
    LABEL_TEXT(c, LABEL_FONT, 10, 0, 0, 0, 0, "%s", "REC");
    box(c, 34, 0, 40, 6, 0);
    on(c, 35, 1); on(c, 36, 2); on(c, 37, 3); on(c, 38, 4); on(c, 39, 5);
    LABEL_TEXT(c, LABEL_FONT, 44, 0, 0, 0, 0, "%s", "ONE");
    LABEL_TEXT(c, LABEL_FONT, 125, 0, 2, 0, 0, "%s", ">");
    (void)heard;
    (void)tl;
}

static int rt_h_draw(void *c)
{
    (void)c;
    return 0;                                   /* v0.44: no lock on H any more (BOUNCE's [TRIG] keys) */
}

/* (v0.41's REC TRIGS view, rt_view_draw, is gone in v0.44: BOUNCE tracks have bn_view_draw) */
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
    extern int rec_rt_take;
    clear(c, 0, 0, 127, 63);
    if (state == 2 && !rec_rt_take) {           /* v0.25: recording: the DT2's screen */
        recording_draw(c, heard);
        return;
    }

    extern int bn_active(void);
    if (bn_active()) {                          /* v0.49: FLEX REC, its two pages, its own layout */
        bn_view_draw(c, heard);
        return;
    }
    /* the title and the meter */
    LABEL(c, 25, 57, "%s", "RECORDER");
    hline(c, 0, 50, 54, 0);
    int mx0 = 68, mx1 = 126, my0 = 55, my1 = 62, w = mx1 - mx0 - 2;
    box(c, mx0, my0, mx1, my1, 0);
    int lv = heard ? meter_x(rec_peak, w) : 0;
    if (lv > 0)
        fill(c, mx0 + 1, my0 + 1, mx0 + lv, my1 - 1);
    int tx = mx0 + 1 + rec_thres * w / 120;
    vline(c, tx, my0 - 2, my0 - 1, 0);

    /* SRC, on the left, and over it CHAN (knob B) as its own icon, the DT2's way (v0.44; v0.33
     * ..v0.43 wrote L+R / L / R under SRC): an L and an R cell, the recorded ones filled
     * (L+R both, L or R one). The same on the BOUNCE panel, whose right column is the grid. */
    extern int rec_chan;
    const char *src = smp_rec_src[rec_src > SMP_REC_SOURCES - 1 ? SMP_REC_SOURCES - 1 : rec_src];
    LABEL(c, 13, 32, "%s", src);
    LABEL(c, 13, 22, "%s", "SRC");
    {
        int ch = rec_chan < 0 ? 0 : rec_chan > SMP_REC_CHANS - 1 ? SMP_REC_CHANS - 1 : rec_chan;
        int cy0 = 41, cy1 = 47;
        for (int k = 0; k < 2; k++) {
            int x0 = 6 + 8 * k, x1 = x0 + 6;
            int lit = ch == 0 || ch == k + 1;   /* L+R, or this side */
            if (lit) {
                fill(c, x0, cy0, x1, cy1);
                glyph(c, x0 + 2, cy0 + 1, k ? 'R' : 'L', 0);
            } else {
                box(c, x0, cy0, x1, cy1, 1);
                glyph(c, x0 + 2, cy0 + 1, k ? 'R' : 'L', 1);
            }
        }
    }

    /* the RECORD box: what YES does, or what the recorder is doing */
    int bx0 = 29, bx1 = 97, by0 = 22, by1 = 48;
    box(c, bx0, by0, bx1, by1, 1);
    int cx = (bx0 + bx1) / 2;
    extern int rt_q_waiting(void), rt_qrec;
    extern const char *rt_qname(int q);
    if (rt_q_waiting()) {                       /* v0.41: QREC: the take waits for its step */
        LABEL(c, cx, by0 + 16, "%s", "WAITING");
        LABEL(c, cx, by0 + 8, "Q.REC %s", rt_qname(rt_qrec));
        LABEL(c, cx, by0 + 1, "%s", "NO:CANCEL");
    } else if (state == 2 && rec_rt_take) {     /* v0.41: a REC trig's take, into a buffer */
        fill(c, bx0 + 5, by0 + 15, bx0 + 11, by0 + 21);
        int ds = (int)(rec_frames / 4800u);
        LABEL(c, cx + 6, by0 + 16, "%s", "TRIG");
        LABEL(c, cx, by0 + 8, "%d.%d S", ds / 10, ds % 10);
        LABEL(c, cx, by0 + 1, "%s", "YES:RECORD");
    } else if (state == 2) {
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
        /* v0.48: three lines inside the box (rows 24..28, 30..34, 38..42): the third sat on the border */
        u32 secs = rec_room / 96000u;           /* int16 at 48 kHz */
        LABEL(c, cx, by0 + 8, "%d S FREE", (int)(secs > 999 ? 999 : secs));
        if (as_done >= 0 && rec_saved_slot >= 0)
            LABEL(c, cx, by0 + 2, "%d ON TRK %d", rec_saved_slot + 1, as_done + 1);
        else if (state == 3 && rec_saved_slot >= 0) {
            extern int smp_rs_last;             /* v0.46: RECORDED full: the take is in the pool only */
            LABEL(c, cx, by0 + 2, smp_rs_last == 2 ? "%d +DRV FULL" : "SAVED %d", rec_saved_slot + 1);
        }
    }

    /* THRES, on the right */
    LABEL(c, 113, 34, "%d", rec_thres);
    LABEL(c, 113, 22, "%s", "THRES");

    /* the bottom row: the slot the next recording goes into (v0.33: shown, not chosen: the
     * first empty one), R.LEN, R.STRT, ARM */
    w_samp_small(c, 1, 5, rec_dest < 0 ? 0 : rec_dest + 1);   /* v0.47: smaller */
    LABEL(c, 13, 0, "%s", "INTO");
    /* v0.48 (owner: every value of a control at one place and size): R.LEN's MAX and its step
     * counts on R.STRT's line (y 9), one line, no STEPS under some values and not others; the label
     * says what the number is */
    if (rec_rlen <= 0)
        LABEL(c, 47, 9, "%s", "MAX");
    else
        LABEL(c, 47, 9, "%d", rec_rlen);
    LABEL(c, 47, 0, "%s", "R.LEN");
    LABEL(c, 80, 9, "%s", rec_rstrt ? "PLAY" : "THRES");
    LABEL(c, 80, 0, "%s", "R.STRT");
    if (rt_h_draw(c))                           /* v0.41: a step held: its REC trig */
        return;
    int on = (state == 1 || state == 2) && !rec_rt_take;   /* ARM's switch: what the DSP is doing */
    int sx0 = 104, sx1 = 122, sy0 = 8, sy1 = 15;
    box(c, sx0, sy0, sx1, sy1, 0);
    if (on)
        fill(c, sx1 - 8, sy0 + 2, sx1 - 2, sy1 - 2);
    else
        box(c, sx0 + 2, sy0 + 2, sx0 + 8, sy1 - 2, 0);
    LABEL(c, 113, 0, "%s", "ARM");
}
