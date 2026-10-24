/* The sample machines' controls as the DT2 handles them (v0.15, docs/sampler.md):
 *
 *   smp_quant   one detent a choice. A control with a few choices (PLAY, MODE, BARS,
 *               SEG, GRID, SLCE, the recorder's SRC) sits on a record of 0..127 or so;
 *               the stock setter (0x40037b74) now asks smp_quant before it writes the
 *               value, and a small turn moves to the next choice instead of the next
 *               value. Only for a sound whose machine is one of ours, only these slots.
 *   smp_formats the value the header shows when a control moves: the choice's name
 *               (FWD, 1/4, 1/16, a sample's name, IN, TRK3, MONO L, ON ...) instead of
 *               WaveTone's (Prim., Harm., a number). The records' formatters are swapped
 *               while a sample machine's track is the active one, as wr_names swaps their
 *               names, and put back otherwise.
 */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define TYPE_FIRST 8
#define TYPES 6                                 /* v0.19: SLICE */
#define SOUND_TYPE 0xDE                         /* the sound's machine type byte */
#define SOUND_VALUES 0x14                       /* its values, a 16-bit word a slot */
#define RECORD_FMT(id) (*(void **)(0x401F7F94u + 60u * (id) + 0x34u))
#define RECORD_LO(id) (((const int *)(0x401F7F94u + 60u * (id)))[2] >> 8)

extern int smp_count(void);
extern const char *smp_name(int k);

static int zone_of(const struct smp_q *q, int c)
{
    int z = 0;
    while (z < q->n - 1 && c >= q->th[z])
        z++;
    return z;
}

/* from the setter's write (hooks.S, smp_quant_hook): S = the sound, SLOT, VALUE the
 * value about to be written (coarse << 8 | fine) -> the value to write */
int smp_quant(u8 *s, int slot, int value)
{
    int type = (signed char)s[SOUND_TYPE] - TYPE_FIRST;
    if (type < 0 || type >= TYPES)
        return value;
    int old = *(volatile u16 *)(s + SOUND_VALUES + 2 * slot);
    int oc = old >> 8, nc = (value >> 8) & 0xFF, d = nc - oc;
    for (int k = 0; k < SMP_NQ; k++) {
        const struct smp_q *q = &smp_q[k];
        if (q->slot != slot || !(q->types & (1 << type)))
            continue;
        if (nc == oc)
            return value;                       /* a fine move: as it is */
        int zo = zone_of(q, oc), z = zone_of(q, nc);
        if (d >= -8 && d <= 8) {                /* a detent (or a pushed one): the next choice */
            z = zo + (d > 0 ? 1 : -1);
            if (z < 0) z = 0;
            if (z > q->n - 1) z = q->n - 1;
        }
        return q->rep[z] << 8;
    }
    for (int k = 0; k < SMP_NQS; k++) {
        const struct smp_qs *q = &smp_qs[k];
        if (q->slot != slot || !(q->types & (1 << type)))
            continue;
        if (nc == oc)
            return value;
        int c = nc;
        if (d >= -8 && d <= 8)
            c = oc + (d > 0 ? q->step : -q->step);
        c = q->lo + (c - q->lo) / q->step * q->step;
        if (c < q->lo) c = q->lo;
        if (c > q->hi) c = q->hi - (q->hi - q->lo) % q->step;
        return c << 8;
    }
    return value;
}

/* -- the header's text -------------------------------------------------------------------- */

static void put(char *buf, const char *s, int max)
{
    int k = 0;
    while (k < max && s[k]) {
        buf[k] = s[k];
        k++;
    }
    buf[k] = 0;
}

static void put_num(char *buf, int v)
{
    char t[8];
    int n = 0, neg = v < 0;
    if (neg) v = -v;
    do {
        t[n++] = '0' + v % 10;
        v /= 10;
    } while (v && n < 6);
    int k = 0;
    if (neg) buf[k++] = '-';
    while (n)
        buf[k++] = t[--n];
    buf[k] = 0;
}

static int coarse(int v, u32 id)
{
    return ((v >> 8) & 0xFF) - RECORD_LO(id);
}

static int steps_at(int v, const unsigned char *steps)
{
    int k = 0;
    while (k < 7 && v >= steps[k])
        k++;
    return k;
}

static void f_play(int v, char *buf)
{
    static const char *n[4] = {"REV", "REV LOOP", "FWD LOOP", "FWD"};
    int c = coarse(v, SMP_PLAY_REC) >> 5;
    put(buf, n[c > 3 ? 3 : c], 9);
}

static void f_mode(int v, char *buf)
{
    static const char *n[4] = {"REV", "REV LOOP", "FWD LOOP", "FWD"};
    int c = coarse(v, SMP_MODE_REC) >> 5;
    put(buf, n[c > 3 ? 3 : c], 9);
}

static void f_bars(int v, char *buf)
{
    put(buf, smp_bars[steps_at(coarse(v, SMP_BARS_REC), smp_bars_steps)], 4);
}

static void f_seg(int v, char *buf)
{
    int n = 32 >> steps_at(coarse(v, SMP_SEG_REC), smp_seg_steps);   /* v0.18: 1/32, 1/16, 1/8 (the DT2's) */
    if (n == 1) {
        put(buf, "1", 2);
        return;
    }
    buf[0] = '1';
    buf[1] = '/';
    put_num(buf + 2, n);
}

static void f_grid(int v, char *buf)
{
    int g = coarse(v, SMP_GRID_REC) / 24;
    put_num(buf, smp_grids[g > 4 ? 4 : g]);
}

static void f_samp(int v, char *buf)
{
    int s = coarse(v, SMP_SAMP_REC);
    if (s <= 0) {
        put(buf, "OFF", 4);
        return;
    }
    int n = smp_count();
    if (n >= 0 && s <= n) {                     /* your samples: their names */
        const char *nm = smp_name(s - 1);
        if (nm[0]) {
            put(buf, nm, 7);
            return;
        }
    }
    put_num(buf, s);                            /* nothing there (v0.20: no test sounds) */
}

static void f_slce(int v, char *buf)            /* GRID's SLCE: NOTE, then 1..63 (v0.18, the DT2's) */
{
    int s = coarse(v, SMP_SLICE_ID) >> 1;
    if (s <= 0)
        put(buf, "NOTE", 4);
    else
        put_num(buf, s);
}

static void f_slen(int v, char *buf)            /* GRID's LEN: how many slices, 1..64 */
{
    put_num(buf, (coarse(v, SMP_SLEN_ID) >> 1) + 1);
}

/* the records whose text is ours on a sample machine's track; 239, SLCE's and LEN's
 * records only on GRID's (ONESHOT's STRT, LOOP and CFAD are the same records) */
static const u16 fmt_ids[] = {SMP_PLAY_REC, SMP_MODE_REC, SMP_BARS_REC, SMP_SEG_REC, SMP_GRID_REC,
                              SMP_SAMP_REC, SMP_SLICE_ID, SMP_SLEN_ID};
static void (*const fmt_fns[])(int, char *) = {f_play, f_mode, f_bars, f_seg, f_grid, f_samp,
                                               f_slce, f_slen};   /* (v0.22: the recorder's are a screen's now) */
#define NFMT (int)(sizeof fmt_ids / sizeof fmt_ids[0])
static void *stock_fmt[NFMT] __attribute__((section(".data")));
static int fmt_saved __attribute__((section(".data"))) = 0;

/* from wr_names, when the active track's machine changes: KIND as is_wr answers it
 * (SMP_KIND0.. for the sample machines) */
void smp_formats(int kind)
{
    if (!fmt_saved) {
        for (int k = 0; k < NFMT; k++)
            stock_fmt[k] = RECORD_FMT(fmt_ids[k]);
        fmt_saved = 1;
    }
    int smp = kind >= SMP_KIND0;
    for (int k = 0; k < NFMT; k++) {
        void *f = stock_fmt[k];
        int grid_only = fmt_ids[k] == SMP_GRID_REC;
        int slices = fmt_ids[k] == SMP_SLICE_ID || fmt_ids[k] == SMP_SLEN_ID;  /* GRID's, SLICE's */
        if (smp && (!grid_only || kind == SMP_GRID_KIND)
            && (!slices || kind == SMP_GRID_KIND || kind == SMP_SLICE_KIND)
            && (fmt_ids[k] != SMP_MODE_REC || kind == SMP_WERP_KIND))
            f = (void *)fmt_fns[k];
        RECORD_FMT(fmt_ids[k]) = f;
    }
}
