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
#define CENTRED   2
#define RECORD(id) ((const int *)(0x401F7F94u + 60u * (id)))
#define NAME_SHORT(id) (*(const char **)(0x401F7F94u + 60u * (id) + 0x30u))

#define CELL_X(k) (25 + 26 * (k))
#define TOP_Y 34
#define BOT_Y 7

extern int smp_count(void);
extern const char *smp_name(int k);
extern const u8 *smp_overview(int k);    /* 100 column peaks, 0..255 (link.c, v0.16) */

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
    /* the DT2's TUNE: a rounded box, a dotted line through it, the value in the middle */
    int x0 = x + 1, x1 = x + 22, y0 = y + 3, y1 = y + 13, cy = (y0 + y1) / 2;
    box(c, x0, y0, x1, y1, 0);
    int semis = v - top / 2;
    hline(c, x0 + 2, x0 + 6, cy, 1);
    hline(c, x1 - 6, x1 - 2, cy, 1);
    if (semis == 0)
        TEXT(c, FONT, (x0 + x1) / 2 + 1, cy - 3, CENTRED, "0");
    else
        TEXT(c, FONT, (x0 + x1) / 2 + 1, cy - 3, CENTRED, "%c%d", semis < 0 ? '-' : '+',
             semis < 0 ? -semis : semis);
}

static void w_empty(void *c, int x, int y)
{
    box(c, x + 5, y + 1, x + 19, y + 15, 1);    /* the DT2's empty place: a dotted square */
}

static void w_samp(void *c, int x, int y, int slot)
{
    int x0 = x + 1, x1 = x + 22, y0 = y + 3, y1 = y + 13;
    fill(c, x0, y0, x0 + 8, y1);                /* the bank letter, cut out */
    box(c, x0, y0, x1, y1, 0);
    glyph(c, x0 + 3, y0 + 3, 'A', 0);
    if (slot == 0) {                            /* OFF: two dashes */
        glyph(c, x0 + 11, y0 + 3, '-', 1);
        glyph(c, x0 + 15, y0 + 3, '-', 1);
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
    for (int a = 0; a < 256; a += 2)            /* a whole ring, as the DT2 draws it */
        on(c, cx + sin256(a) * r / 127, cy + sin256(a + 64) * r / 127);
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
        TEXT(c, FONT, x + 12, y - 7, CENTRED, "%.4s", label);
}

/* the waveform strip: the slot's sound, peak per column, from X0 across SMP_WAVE_W at
 * CY; 0 drawn if the slot is off or empty (a flat dotted line) */
static void waveform(void *c, int slot, int x0, int cy)
{
    int test = smp_count() < 0 && slot >= 1 && slot <= SMP_SOUNDS;
    const u8 *ov = !test && slot >= 1 ? smp_overview(slot - 1) : 0;
    if (!test && !ov) {
        hline(c, x0, x0 + SMP_WAVE_W - 1, cy, 1);
        return;
    }
    for (int k = 0; k < SMP_WAVE_W; k++) {
        int h;
        if (test)
            h = smp_test_wave[slot - 1][k];
        else
            h = ov[k * 100 / SMP_WAVE_W] * SMP_WAVE_AMP / 255;
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
static void *list_view __attribute__((section(".data"))) = 0;
static u32 list_at __attribute__((section(".data"))) = 0;

static void slot_name(int k, char *out)
{
    const char *n = 0;
    int cnt = smp_count();
    if (k <= 0)
        n = "OFF";
    else if (k > SMP_REC_FIRST && k <= SMP_REC_FIRST + 4) {
        out[0] = 'R'; out[1] = 'E'; out[2] = 'C'; out[3] = ' ';
        out[4] = (char)('0' + k - SMP_REC_FIRST); out[5] = 0;
        return;
    } else if (cnt >= 0 && k <= cnt)
        n = smp_name(k - 1);
    else if (cnt < 0 && k <= SMP_SOUNDS)
        n = smp_sound[k - 1];
    int j = 0;
    if (n && n[0])
        for (; j < 7 && n[j]; j++)
            out[j] = n[j];
    else {                                      /* empty: its number */
        out[j++] = '-';
        out[j++] = '-';
    }
    out[j] = 0;
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
        cell(c, view, kind, ids[i], CELL_X(i), TOP_Y + 4, 0, 0);
    int slot = value(view, SMP_SAMP_ID, 0);
    int x0 = CELL_X(0) - 1, cy = 21;
    waveform(c, slot, x0, cy);
    int w = SMP_WAVE_W;
    if (kind == SMP_GRID_KIND) {
        int gi = value(view, SMP_GRID_ID, 0) / 24, n = smp_grids[gi > 4 ? 4 : gi];
        int s = value(view, SMP_SLICE_ID, 0) >> 1;    /* 0 NOTE (drawn at the first), 1..63 */
        s = s <= 0 ? 0 : (s > n ? n : s) - 1;
        int len = (value(view, SMP_SLEN_ID, 0) >> 1) + 1;
        for (int j = 0; j <= n && n <= 32; j++)
            vline(c, x0 + j * (w - 1) / n, cy - SMP_WAVE_AMP - 1, cy - SMP_WAVE_AMP + 1, 0);
        int a = x0 + s * (w - 1) / n, b = x0 + (s + len > n ? n : s + len) * (w - 1) / n;
        marker(c, a, cy, 0);
        marker(c, b, cy, 0);
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
            TEXT(c, FONT, x + 12, 0, CENTRED, "%.5s", NAME_SHORT(ids[i]));
    }
    if (ids[7]) {
        int top, v = value(view, ids[7], &top);
        w_pill(c, CELL_X(3), 0, v, top);
    }
    sample_list(c, view, slot);
}

/* page 3, the RECORDER, laid out as the DT2's (its manual 13.1 and the owner's photograph):
 * RECORDER and the input meter across the top; SRC on the left; the RECORD NOW box in the
 * middle (YES), THRES on the right; DEST (the DT2's MON place), R.LEN, R.STRT and ARM's
 * switch along the bottom. The page draws over the stock header and machine box. */
#define FONT_BIG 0x44507EF0u                    /* the stock header's 11-pixel font */
extern void *rec_view;
extern u32 rec_seen;
extern int rec_src, rec_chan, rec_thres, rec_dest, rec_rlen, rec_rstrt, rec_arm;
extern int rec_state, rec_peak;
extern u32 rec_frames, rec_heard;
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

void smp_rec_draw(void *view, void *c)
{
    int top;
    rec_view = view;
    rec_seen = FRAMES_NOW + 1u;
    rec_src = value(view, SMP_RSRC_ID, &top) * SMP_REC_SOURCES / (top + 1);
    rec_chan = value(view, SMP_RCHAN_ID, 0);
    rec_thres = value(view, SMP_RTHR_ID, 0);
    rec_dest = value(view, SMP_RDST_ID, 0);
    rec_rlen = value(view, SMP_RLEN_ID, 0);
    rec_rstrt = value(view, SMP_RSTRT_ID, 0);
    rec_arm = value(view, SMP_ARM_ID, 0);
    int heard = rec_heard && FRAMES_NOW + 1u - rec_heard < 1500u;
    int state = heard ? rec_state : 0;

    clear(c, 0, 0, 23, 52);                     /* the stock machine box and level */

    /* the input meter under the header: a bar, filled to the source's peak, THRES ticked */
    int mx0 = 2, mx1 = 125, my0 = 46, my1 = 51, w = mx1 - mx0 - 2;
    box(c, mx0, my0, mx1, my1, 0);
    int lv = heard ? meter_x(rec_peak, w) : 0;
    if (lv > 0)
        fill(c, mx0 + 1, my0 + 1, mx0 + lv, my1 - 1);
    int tx = mx0 + 1 + rec_thres * w / 120;
    vline(c, tx, my0 - 2, my0 - 1, 0);
    vline(c, tx, my1 + 1, my1 + 2, 0);

    /* SRC, on the left: the source over the channel */
    const char *src = smp_rec_src[rec_src > SMP_REC_SOURCES - 1 ? SMP_REC_SOURCES - 1 : rec_src];
    TEXT(c, FONT, 14, 37, CENTRED, "%.5s", src);
    TEXT(c, FONT, 14, 30, CENTRED, "%.3s", smp_rec_chan[rec_chan > 2 ? 2 : rec_chan]);
    TEXT(c, FONT, 14, 22, CENTRED, "SRC");

    /* the RECORD NOW box: what YES does, or what the recorder is doing */
    int bx0 = 31, bx1 = 95, by0 = 22, by1 = 43;
    box(c, bx0, by0, bx1, by1, 1);
    if (state == 2) {
        fill(c, bx0 + 4, by0 + 8, bx0 + 10, by0 + 14);   /* a solid dot: recording */
        int ds = (int)(rec_frames / 4800u);
        TEXT(c, FONT, bx0 + 14, by0 + 12, 0, "REC");
        TEXT(c, FONT, bx0 + 14, by0 + 4, 0, "%d.%d s", ds / 10, ds % 10);
    } else if (state == 1) {
        TEXT(c, FONT, (bx0 + bx1) / 2, by0 + 12, CENTRED, "ARMED");
        TEXT(c, FONT, (bx0 + bx1) / 2, by0 + 4, CENTRED, rec_rstrt ? "ON PLAY" : "ON THRES");
    } else {
        fill(c, bx0 + 3, by0 + 7, bx0 + 17, by0 + 15);   /* YES, cut out of a filled badge */
        glyph(c, bx0 + 5, by0 + 9, 'Y', 0);
        glyph(c, bx0 + 9, by0 + 9, 'E', 0);
        glyph(c, bx0 + 13, by0 + 9, 'S', 0);
        TEXT(c, FONT, bx0 + 20, by0 + 12, 0, "RECORD");
        TEXT(c, FONT, bx0 + 20, by0 + 4, 0, state == 3 ? "AGAIN!" : "NOW!");
    }

    /* THRES, on the right */
    TEXT(c, FONT, 111, 33, CENTRED, "%d", rec_thres);
    TEXT(c, FONT, 111, 22, CENTRED, "THRES");

    /* the bottom row: DEST, R.LEN, R.STRT, ARM */
    w_samp(c, 3, 4, SMP_REC_FIRST + 1 + rec_dest);
    TEXT(c, FONT, 14, 0, CENTRED, "DEST");
    if (rec_rlen <= 0) {
        TEXT(c, FONT, 50, 13, CENTRED, "MAX");
        TEXT(c, FONT, 50, 6, CENTRED, "%d.%d", SMP_REC_SECONDS10 / 10, SMP_REC_SECONDS10 % 10);
    } else {
        TEXT(c, FONT, 50, 13, CENTRED, "%d", rec_rlen);
        TEXT(c, FONT, 50, 6, CENTRED, "STEPS");
    }
    TEXT(c, FONT, 50, 0, CENTRED, "R.LEN");
    TEXT(c, FONT, 82, 8, CENTRED, rec_rstrt ? "PLAY" : "THRES");
    TEXT(c, FONT, 82, 0, CENTRED, "R.STRT");
    int on = state == 1 || state == 2;           /* ARM's switch: what the DSP is doing */
    int sx0 = 103, sx1 = 119, sy0 = 8, sy1 = 14;
    box(c, sx0, sy0, sx1, sy1, 0);
    if (on)
        fill(c, sx1 - 7, sy0 + 2, sx1 - 2, sy1 - 2);
    else
        box(c, sx0 + 2, sy0 + 2, sx0 + 7, sy1 - 2, 0);
    TEXT(c, FONT, 111, 0, CENTRED, "ARM");
}
