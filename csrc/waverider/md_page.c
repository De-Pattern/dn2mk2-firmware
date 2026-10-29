/* PERC's pages drawn as the Machinedrum's main screen (docs/md.md, "The page", v0.20).
 *
 * Under the DN2's header (its title, and the value of a knob as it turns), the MD's main
 * screen, as its own screen code draws it (0x229dd2 and the routines beside it, run in an
 * m68k emulator, dnfw.md.ui), eight rows shorter: the MD's screen has no header.
 *
 *   right, x 48..127: the eight parameters in two rows of four cells 20 wide, each its
 *     name above a knob; dotted lines between the cells and under the names, a solid line
 *     along the bottom; a "clip" over two cells whose parameters belong together.
 *   left: the level bar (LEV); the kit box (inverted), here the track and the machine;
 *     a line under it, here PERC and the page; the machine line at the bottom, inverted:
 *     TRX > BD > SYNT (page 1) or TFX (page 2, the track effects).
 *
 * The knob, its 128 pointers, the clip and the three fonts are the Machinedrum's own,
 * read from the owner's MD OS when the build is made (dnfw.md.ui) and placed in RAM at
 * MDUI_LOAD by the mod; none of it is in this source. Without them (MDUI_LOAD does not
 * hold the blob) md_page_draw returns 0 and page.c draws the page as before.
 *
 *
 * Canvas: 128 x 64, y counting up from the bottom (the MD's own convention too).
 */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define GET_VALUE ((int (*)(void *, u32, u8 *))0x4006538E)
#define SET_PIXEL ((void (*)(void *, int, int, int))0x40113B90)
#define RECORD(id) ((const int *)(0x401F7F94u + 60u * (id)))
#define FRAMES (*(volatile u32 *)0x4058E8D4u)                      /* 1,500 a second */
#define UI_TRACK (*(volatile u8 *)0x42431A6Cu)
#define CTL_FRAME ((volatile u16 *)0x80005E60u)
#define TEMPO_WORD 108                                             /* BPM x 120 */
#define MDUI ((const u8 *)MDUI_LOAD)
#define NAME_SHORT_OF(id) (*(const char **)(0x401F7F94u + 60u * (id) + 0x30u))

enum { SMALL, SYM, BIG };

static int ok(void)
{
    return MDUI[0] == 'M' && MDUI[1] == 'D' && MDUI[2] == 'U' && MDUI[3] == 'I'
           && (MDUI[4] << 8 | MDUI[5]) == MDUI_VERSION;
}

static u16 be16(const u8 *p) { return (u16)(p[0] << 8 | p[1]); }

static void put(void *c, int x, int y, int on)
{
    if (x >= 0 && x < 128 && y >= 0 && y < 64)
        SET_PIXEL(c, x, y, on);
}

static void fill(void *c, int x0, int y0, int x1, int y1, int on)
{
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++)
            put(c, x, y, on);
}

/* a bitmap of columns (data, mask), bit r = row r up from Y: the mask's pixels cleared,
 * then the data's set, as the MD's blit (0x21124c) */
static void blit(void *c, int x, int y, int cols, int rows, const u8 *p, int wide)
{
    for (int k = 0; k < cols; k++) {
        u32 d = wide ? be16(p + 4 * k) : p[2 * k];
        u32 m = wide ? be16(p + 4 * k + 2) : p[2 * k + 1];
        for (int r = 0; r < rows; r++) {
            if (d >> r & 1)
                put(c, x + k, y + r, 1);
            else if (m >> r & 1)
                put(c, x + k, y + r, 0);
        }
    }
}

static const u8 *glyph(int font, int ch)
{
    if (ch < 32 || ch > 127)
        ch = '?';
    return MDUI + MDUI_FONT + MDUI_FONT_BYTES * font + 1 + MDUI_FONT_STRIDE * (ch - 32);
}

static int text_w(int font, const char *s, int n)
{
    int w = 0;
    for (int k = 0; k < n && s[k]; k++)
        w += glyph(font, (u8)s[k])[0] + 1;
    return w;
}

/* text from X, its bottom row at Y; LIT 0 cuts it out of a filled area. -> its width */
static int text(void *c, int font, int x, int y, const char *s, int n, int lit)
{
    int x0 = x, rows = MDUI[MDUI_FONT + MDUI_FONT_BYTES * font];
    for (int k = 0; k < n && s[k]; k++) {
        const u8 *g = glyph(font, (u8)s[k]);
        for (int col = 0; col < g[0]; col++)
            for (int r = 0; r < rows; r++)
                if (g[1 + col] >> r & 1)
                    put(c, x + col, y + r, lit);
        x += g[0] + 1;
    }
    return x - x0;
}

static int slen(const char *s, int n)
{
    int k = 0;
    while (k < n && s[k])
        k++;
    return k;
}

static int fmt_int(char *b, int v, int sign)
{
    int n = 0;
    if (v < 0) { b[n++] = '-'; v = -v; }
    else if (sign && v > 0) b[n++] = '+';
    char t[4];
    int k = 0;
    do { t[k++] = (char)('0' + v % 10); v /= 10; } while (v && k < 4);
    while (k)
        b[n++] = t[--k];
    b[n] = 0;
    return n;
}

/* a control's knob position 0..127, as the DSP reads it (dnfw.perc.live: the nearest of
 * the Machinedrum's 128) */
static int knob(void *view, u32 id)
{
    u8 flag;
    const int *r = RECORD(id);
    int lo = r[2] >> 8, top = (r[3] >> 8) - lo;
    int v = (GET_VALUE(view, id, &flag) >> 8) - lo;
    if (top <= 0) return 0;
    if (v < 0) v = 0;
    if (v > top) v = top;
    return (v * 127 + top / 2) / top;
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

/* the rows, under the header (y 54..63): the MD's, closed up by eight */
#define LINE_Y 0                /* the solid line along the bottom (MD 0) */
#define KNOB_B 3                /* the bottom row's knobs (MD 5) */
#define DOT_B 18                /* dotted, over the bottom row's knobs (MD 21) */
#define NAME_B 20               /* the bottom row's names (MD 24) */
#define DOT_M 27                /* dotted, between the rows (MD 31) */
#define KNOB_A 29               /* the top row's knobs (MD 36) */
#define DOT_A 44                /* dotted, under the top row's names (MD 53) */
#define NAME_A 46               /* the top row's names (MD 56) */
#define SEP_TOP 51              /* the cells' dotted separators end here (MD 61) */
#define CLIP_UP 10              /* the clip over a knob's top (MD 47 - 36, 15 - 5) */

static void grid(void *c)
{
    for (int x = 67; x <= 107; x += 20)
        for (int y = 1; y <= SEP_TOP; y += 2)
            put(c, x, y, 1);
    for (int x = 49; x <= 125; x += 2) {
        put(c, x, DOT_A, 1);
        put(c, x, DOT_M, 1);
        put(c, x, DOT_B, 1);
    }
    for (int x = 48; x <= 126; x++)
        put(c, x, LINE_Y, 1);
}

/* PAGE 0: the machine's eight; PAGE 1: AMD AMF EQF EQG / FLTF FLTW FLTQ TYPE */
int md_page_draw(void *view, void *c, int page, int type)
{
    if (!ok() || page < 0 || page > 1 || type < 0 || type >= PERC_N)
        return 0;
    const u8 *mach = MDUI + MDUI_MACH + MDUI_MACH_BYTES * type;
    u32 nib = (u32)mach[0] << 24 | (u32)mach[1] << 16 | (u32)mach[2] << 8 | mach[3];
    if (page == 1)
        nib = MD_FX_NIBBLES;
    int t = UI_TRACK;
    fill(c, 0, 0, 127, 53, 0);

    /* the right: the eight cells */
    grid(c);
    for (int s = 0; s < 8; s++) {
        int col = s & 3, row = s >> 2, n = nib >> (28 - 4 * s) & 15;
        u32 id = wr_ids[page][s];
        int x0 = 48 + 20 * col, ny = row ? NAME_B : NAME_A, ky = row ? KNOB_B : KNOB_A;
        if (!(n & 1) || !id)
            continue;
        const char *name = NAME_SHORT_OF(id);
        int len = slen(name, 4);
        text(c, SMALL, x0 + (20 - text_w(SMALL, name, len)) / 2, ny, name, len, 1);
        if (id == PERC_TYPE_ID) {                       /* TYPE: the machine, not a knob */
            const char *syn = (const char *)mach + 4, *m = (const char *)mach + 7;
            text(c, SMALL, x0 + (20 - text_w(SMALL, syn, 3)) / 2, ky + 7, syn, 3, 1);
            text(c, SYM, x0 + (20 - text_w(SYM, m, 2)) / 2, ky + 1, m, 2, 1);
            if (locked(view, id))               /* v0.27: p-locked, as stock lights it */
                invert(c, x0 + 1, row ? 1 : DOT_M + 1, x0 + 19, row ? DOT_M - 1 : 53);
            continue;
        }
        int v = knob(view, id);
        blit(c, x0 + 4, ky, MDUI_KNOB_COLS, 13, MDUI + MDUI_KNOB, 1);
        blit(c, x0 + 6, ky + 2, MDUI_PTR_COLS, 7, MDUI + MDUI_PTR + 2 * MDUI_PTR_COLS * v, 0);
        if ((n & 2) && col < 3)
            blit(c, x0 + 16, ky + CLIP_UP, MDUI_CLIP_COLS, 16, MDUI + MDUI_CLIP, 1);
        if (locked(view, id))                   /* v0.27: p-locked, as stock lights it */
            invert(c, x0 + 1, row ? 1 : DOT_M + 1, x0 + 19, row ? DOT_M - 1 : 53);
    }

    /* the left: the tempo */
    {
        u32 bpm120 = CTL_FRAME[TEMPO_WORD];
        char b[8];
        int n = fmt_int(b, (int)(bpm120 / 120u), 0);
        b[n++] = '.';
        b[n++] = (char)('0' + (bpm120 % 120u) / 12u);
        b[n] = 0;
        extern int smp_skipped_any(void);       /* v0.30: the DSP left a voice out for time */
        extern int smp_func_held, smp_dsp_load(void);
        int ld = smp_func_held ? smp_dsp_load() : -1;
        if (ld >= 0) {                          /* v0.32: FUNC held: the DSP's load, percent */
            char d[6];
            int m = fmt_int(d, ld > 999 ? 999 : ld, 0);
            d[m++] = '%';
            d[m] = 0;
            text(c, BIG, 1, 41, d, m, 1);
        } else if (smp_skipped_any())
            text(c, BIG, 1, 41, "CPU", 3, 1);
        else if (bpm120 >= 1200u)
            text(c, BIG, 1, 41, b, n, 1);
    }
    /* the level bar: the track's LEVEL */
    text(c, SMALL, 33, 48, "LEV", 3, 1);
    for (int y = 34; y <= 46; y += 3) {
        put(c, 33, y, 1); put(c, 34, y, 1);
        put(c, 43, y, 1); put(c, 44, y, 1);
    }
    {
        u8 flag;
        const int *r = RECORD(TRACK_LEVEL_ID);
        int span = r[3] - r[2], v = GET_VALUE(view, TRACK_LEVEL_ID, &flag) - r[2];
        int h = span > 0 ? v * 13 / span : 0;
        if (h > 13) h = 13;
        if (h > 0)
            fill(c, 37, 34, 40, 33 + h, 1);
    }
    /* the kit box: the track and the machine */
    fill(c, 2, 18, 45, 31, 1);
    {
        char b[8] = {'T', 'R', 'K', ':', 0, 0, 0, 0};
        b[4] = (char)('0' + (t + 1) / 10);
        b[5] = (char)('0' + (t + 1) % 10);
        text(c, SMALL, 2 + (44 - text_w(SMALL, b, 6)) / 2, 25, b, 6, 0);
        const char *w = perc_what_upper[type];
        int len = slen(w, 11);
        text(c, SMALL, 2 + (44 - text_w(SMALL, w, len)) / 2, 19, w, len, 0);
    }
    /* the line under it: what this is, and the page */
    text(c, SYM, 3, 11, page ? ">PERC 2" : ">PERC 1", 7, 1);
    /* the machine line: TRX > BD > SYNT / TFX, inverted */
    fill(c, 1, 2, 45, 6, 1);
    text(c, SMALL, 1, 2, (const char *)mach + 4, 3, 0);
    text(c, SYM, 13, 2, ">", 1, 0);
    text(c, SMALL, 17, 2, (const char *)mach + 7, 2, 0);
    text(c, SYM, 25, 2, ">", 1, 0);
    text(c, SMALL, 29, 2, page ? "TFX " : "SYNT", 4, 0);
    return 1;
}

/* -- v0.27: the Monomachine machines' page, drawn as the Monomachine draws it ---------------
 * (owner's screenshots of its manual, docs/mnm-pages-plan.md). The same screen as PERC's
 * (the Monomachine's and the Machinedrum's main screens are one design): the tempo, LEV, the
 * kit box (here the track and the machine's family), the machine line DPRO>WAVE; on the
 * right two rows of four cells, each its name over its control. A knob is the MD's knob; a
 * control with choices is drawn as the Monomachine draws it, its choice by name under it:
 *   MW_GRID   a box of rows the marker steps through, left to right, row by row (WAVE, CONS)
 *   MW_SLIDE  a bar sliding along a line (DDRW's WAV1/WAV2, DENS's WAVE)
 *   MW_VU     a needle at the bottom of a box, left to right (DENS's PCH2..4)
 *   MW_SWITCH a round switch, a line through it pointing at the position (SID's, WPRS, SYNC, V-SW)
 * An unused place (---, DENS's chorus) is left empty. */
static const char *const mnm_family[MNM_N] = {"SID", "DIGIPRO", "DIGIPRO", "DIGIPRO", "VO"};
static const char *const mnm_fam_short[MNM_N] = {"SID", "DPRO", "DPRO", "DPRO", "VO"};
static const char *const mnm_mach_short[MNM_N] = {"6581", "WAVE", "DDRW", "DENS", "VO-6"};

static int mnm_k(void *view, int j)             /* knob 0..127, as the DSP and page.c read it */
{
    u8 flag;
    int top = mnm_top[j];
    int v = (GET_VALUE(view, perc_param_ids[j], &flag) >> 8) - mnm_lo[j];
    v = v < 0 ? 0 : v > top ? top : v;
    return (v * 254 + top) / (2 * top);
}

static int mnm_choice_count(int n)
{
    return n == MNM_PCH ? mnm_pch_idx[127] + 1 : n;
}

static int mnm_choice_of(int n, int k)
{
    return n == MNM_PCH ? mnm_pch_idx[k > 127 ? 127 : k] : (k * n) >> 7;
}

static const char *mnm_value_text(int mi, int j, int c)
{
    static char num[6] __attribute__((section(".data")));
    int n = mnm_choices[mi][j];
    if (n == MNM_WAVES || n == 2 * MNM_WAVES) {
        int w = (c & (MNM_WAVES - 1)) + 1;
        num[0] = 'S'; num[1] = (char)('0' + w / 10); num[2] = (char)('0' + w % 10); num[3] = 0;
        return num;
    }
    return mnm_choice_names[mnm_choice_at[mi][j] + c];
}

static void line(void *c, int x0, int y0, int x1, int y1)
{
    int dx = x1 > x0 ? x1 - x0 : x0 - x1, dy = y1 > y0 ? y1 - y0 : y0 - y1;
    int sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, err = dx - dy;
    for (;;) {
        put(c, x0, y0, 1);
        if (x0 == x1 && y0 == y1)
            break;
        int e2 = 2 * err;
        if (e2 > -dy) { err -= dy; x0 += sx; }
        if (e2 < dx) { err += dx; y0 += sy; }
    }
}

static void mnm_widget_draw(void *c, int w, int x0, int ky, int ch, int count)
{
    int last = count > 1 ? count - 1 : 1;
    if (w == MW_GRID) {                         /* rows of dots; the marker steps along them */
        int rows = count > 24 ? 4 : 3, per = (count + rows - 1) / rows;
        int row = ch / per, col = ch % per;
        for (int r = 0; r < rows; r++) {
            int y = ky + 14 - 3 * r;
            for (int x = x0 + 3; x <= x0 + 16; x += 2)
                put(c, x, y, 1);
        }
        int mx = x0 + 3 + (per > 1 ? col * 12 / (per - 1) : 6), my = ky + 14 - 3 * row;
        fill(c, mx, my - 1, mx + 1, my + 1, 1);
    } else if (w == MW_SLIDE) {                 /* a bar along a line */
        for (int x = x0 + 2; x <= x0 + 17; x++)
            put(c, x, ky + 10, 1);
        int bx = x0 + 2 + ch * 15 / last;
        fill(c, bx, ky + 7, bx + 1, ky + 13, 1);
    } else if (w == MW_VU) {                    /* a meter's box, its needle from the bottom */
        for (int x = x0 + 2; x <= x0 + 17; x++)
            put(c, x, ky + 14, 1);
        fill(c, x0 + 2, ky + 11, x0 + 2, ky + 14, 1);
        fill(c, x0 + 17, ky + 11, x0 + 17, ky + 14, 1);
        for (int x = x0 + 4; x <= x0 + 15; x += 3)
            put(c, x, ky + 13, 1);
        int nx = x0 + 3 + ch * 13 / last;
        fill(c, nx, ky + 7, nx, ky + 12, 1);
    } else if (w == MW_SWITCH) {                /* a round switch, a line through it */
        static const signed char dir[5][2] = {{-3, 3}, {-1, 3}, {0, 3}, {1, 3}, {3, 3}};
        int cx = x0 + 10, cy = ky + 10;
        for (int x = 0, y = 4, e = 1 - 4; x <= y; x++) {          /* a circle, radius 4 */
            put(c, cx + x, cy + y, 1); put(c, cx - x, cy + y, 1); put(c, cx + x, cy - y, 1); put(c, cx - x, cy - y, 1);
            put(c, cx + y, cy + x, 1); put(c, cx - y, cy + x, 1); put(c, cx + y, cy - x, 1); put(c, cx - y, cy - x, 1);
            if (e < 0) e += 2 * x + 3;
            else { e += 2 * (x - y) + 5; y--; }
        }
        int d = count > 1 ? ch * 4 / last : 0;
        line(c, cx - dir[d][0], cy - dir[d][1], cx + dir[d][0], cy + dir[d][1]);
    }
}

int mnm_page_draw(void *view, void *c, int mi)
{
    if (!ok() || mi < 0 || mi >= MNM_N)
        return 0;
    int t = UI_TRACK;
    fill(c, 0, 0, 127, 53, 0);
    grid(c);
    for (int s = 0; s < 8; s++) {
        int col = s & 3, row = s >> 2;
        int x0 = 48 + 20 * col, ny = row ? NAME_B : NAME_A, ky = row ? KNOB_B : KNOB_A;
        int w = mnm_widget[mi][s];
        const char *name = mnm_labels[mi][s];
        if (w == MW_EMPTY || (name[0] == '-' && !name[1]))
            continue;
        int len = slen(name, 4);
        text(c, SMALL, x0 + (20 - text_w(SMALL, name, len)) / 2, ny, name, len, 1);
        int k = mnm_k(view, s), n = mnm_choices[mi][s];
        if (w == MW_KNOB || !n) {
            blit(c, x0 + 4, ky, MDUI_KNOB_COLS, 13, MDUI + MDUI_KNOB, 1);
            blit(c, x0 + 6, ky + 2, MDUI_PTR_COLS, 7, MDUI + MDUI_PTR + 2 * MDUI_PTR_COLS * k, 0);
        } else {
            int count = mnm_choice_count(n), ch = mnm_choice_of(n, k);
            if (ch > count - 1) ch = count - 1;
            mnm_widget_draw(c, w, x0, ky, ch, count);
            const char *v = mnm_value_text(mi, s, ch);
            int vl = slen(v, 4);
            text(c, SMALL, x0 + (20 - text_w(SMALL, v, vl)) / 2, ky, v, vl, 1);
        }
        if (locked(view, perc_param_ids[s]))   /* p-locked, as stock lights it */
            invert(c, x0 + 1, row ? 1 : DOT_M + 1, x0 + 19, row ? DOT_M - 1 : 53);
    }

    /* the left: the tempo, LEV, the kit box, the line under it, the machine line */
    {
        u32 bpm120 = CTL_FRAME[TEMPO_WORD];
        char b[8];
        int n = fmt_int(b, (int)(bpm120 / 120u), 0);
        b[n++] = '.';
        b[n++] = (char)('0' + (bpm120 % 120u) / 12u);
        b[n] = 0;
        extern int smp_skipped_any(void);       /* v0.30: the DSP left a voice out for time */
        extern int smp_func_held, smp_dsp_load(void);
        int ld = smp_func_held ? smp_dsp_load() : -1;
        if (ld >= 0) {                          /* v0.32: FUNC held: the DSP's load, percent */
            char d[6];
            int m = fmt_int(d, ld > 999 ? 999 : ld, 0);
            d[m++] = '%';
            d[m] = 0;
            text(c, BIG, 1, 41, d, m, 1);
        } else if (smp_skipped_any())
            text(c, BIG, 1, 41, "CPU", 3, 1);
        else if (bpm120 >= 1200u)
            text(c, BIG, 1, 41, b, n, 1);
    }
    text(c, SMALL, 33, 48, "LEV", 3, 1);
    for (int y = 34; y <= 46; y += 3) {
        put(c, 33, y, 1); put(c, 34, y, 1);
        put(c, 43, y, 1); put(c, 44, y, 1);
    }
    {
        u8 flag;
        const int *r = RECORD(TRACK_LEVEL_ID);
        int span = r[3] - r[2], v = GET_VALUE(view, TRACK_LEVEL_ID, &flag) - r[2];
        int h = span > 0 ? v * 13 / span : 0;
        if (h > 13) h = 13;
        if (h > 0)
            fill(c, 37, 34, 40, 33 + h, 1);
    }
    fill(c, 2, 18, 45, 31, 1);
    {
        char b[8] = {'T', 'R', 'K', ':', 0, 0, 0, 0};
        b[4] = (char)('0' + (t + 1) / 10);
        b[5] = (char)('0' + (t + 1) % 10);
        text(c, SMALL, 2 + (44 - text_w(SMALL, b, 6)) / 2, 25, b, 6, 0);
        const char *f = mnm_family[mi];
        int len = slen(f, 8);
        text(c, SMALL, 2 + (44 - text_w(SMALL, f, len)) / 2, 19, f, len, 0);
    }
    text(c, SYM, 3, 11, ">MNM", 4, 1);
    fill(c, 0, 1, 46, 7, 1);                    /* a row clear above and below the letters */
    {
        const char *f = mnm_fam_short[mi], *m = mnm_mach_short[mi];
        int x = 1 + text(c, SMALL, 1, 2, f, slen(f, 4), 0);
        x += text(c, SYM, x, 2, ">", 1, 0);
        text(c, SMALL, x + 1, 2, m, slen(m, 4), 0);
    }
    return 1;
}
