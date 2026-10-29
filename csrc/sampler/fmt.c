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
#define SEG_DETENTS 3                           /* v0.25: WERP's SEG, detents a choice */
#define CHOICE_DETENTS 4                        /* v0.26: PLAY, MODE, BARS, GRID */
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

/* v0.27: the Monomachine machines' choices (waves, switches, consonants, PCH's steps) as the
 * sample machines' (owner: "remember the detents ... on the ones with choices"): a short list
 * (8 or fewer) four detents a choice, a long one (the 32/64 waves, the 21 consonants, PCH's 33
 * steps) one detent a choice; a knob as it is. The choice is the page's (page.c mnm_text):
 * knob = the value over its record's span x 127, rounded; choice = knob x n / 128, or PCH's
 * table. A choice is written as the middle of its knob range. */
static int mnm_kn(int j, int v)
{
    int top = mnm_top[j];
    v -= mnm_lo[j];
    v = v < 0 ? 0 : v > top ? top : v;
    return (v * 254 + top) / (2 * top);
}

static int mnm_ch(int n, int k)
{
    return n == MNM_PCH ? mnm_pch_idx[k > 127 ? 127 : k] : (k * n) >> 7;
}

static int mnm_rep(int j, int n, int c)        /* the value (coarse) in the middle of choice C */
{
    int a = -1, b = -1;
    for (int k = 0; k < 128; k++)
        if (mnm_ch(n, k) == c) {
            if (a < 0)
                a = k;
            b = k;
        }
    if (a < 0)
        a = b = 0;
    int k = (a + b) / 2, top = mnm_top[j];
    return mnm_lo[j] + (k * 2 * top + 127) / 254;
}

static int mnm_quant(int mi, int slot, int old, int value)
{
    int j = 0;
    while (j < 8 && mnm_slot[j] != slot)
        j++;
    if (j == 8 || !mnm_choices[mi][j])
        return value;                           /* not one of the eight, or a knob */
    int n = mnm_choices[mi][j], count = n == MNM_PCH ? mnm_pch_idx[127] + 1 : n;
    int oc = old >> 8, nc = (value >> 8) & 0xFF, d = nc - oc;
    if (nc == oc)
        return value;
    int c;
    if (d >= -8 && d <= 8) {
        static int m_acc __attribute__((section(".data"))) = 0;
        static u32 m_at __attribute__((section(".data"))) = 0;
        static int m_slot __attribute__((section(".data"))) = -1;
        int need = count <= 8 ? 4 : 1;
        u32 now = *(volatile u32 *)0x4058E8D4u;
        int dir = d > 0 ? 1 : -1;
        if (now - m_at > 3000u || (m_acc > 0) != (dir > 0) || m_slot != slot)   /* 2 s */
            m_acc = 0;
        m_at = now;
        m_slot = slot;
        m_acc += dir;
        if (m_acc > -need && m_acc < need)
            return old;                         /* not yet: the choice stays */
        m_acc = 0;
        c = mnm_ch(n, mnm_kn(j, oc)) + dir;
    } else {
        c = mnm_ch(n, mnm_kn(j, nc));          /* a jump: the choice it lands in */
    }
    if (c < 0) c = 0;
    if (c > count - 1) c = count - 1;
    return mnm_rep(j, n, c) << 8;
}

/* v0.32: FUNC + turn on our machines' controls (a tester's list, v0.30). Stock gives some
 * parameter records a FUNC jump (WaveTone's TUNE by octaves, its waves); our controls sit on
 * stock records, and on the ones that carry a jump the stock jump lands on one fixed value
 * and stays there whatever the turn (TUNE at 50, BR1 SU at 0, PLAY MODE at 0 ...). So when
 * FUNC is held, the track is on one of our machines and the value the stock wants to write
 * did not move the way the knob turned, the turn is taken as a plain one: the old value
 * moved by the knob's own detents, kept inside the record's range. A stock jump that does
 * move with the knob (PERC's PTCH by intervals, DPRO WAVE's waves) is left as it is. The
 * knob and its detents come from the UI item (rec.c smp_ui_pop: smp_knob_d, smp_knob_at). */
extern int smp_func_held;
extern int smp_knob_d;
extern u32 smp_knob_at;
#define RECORDS_N 1100u                         /* records at 0x401F7F94, 60 bytes each */
#define KNOB_FRESH 150u                         /* 100 ms: the turn this write comes from */

static int ours(u8 *s)
{
    int ty = (signed char)s[SOUND_TYPE];
    return ty == 5 || mnm_index(ty - 4) >= 0 || (ty >= TYPE_FIRST && ty < TYPE_FIRST + TYPES);
}

static int func_turn(u8 *s, int slot, int value, u32 id)
{
    if (!smp_func_held || !smp_knob_d || id >= RECORDS_N || !ours(s))
        return value;
    if (*(volatile u32 *)0x4058E8D4u - smp_knob_at > KNOB_FRESH)
        return value;
    const int *r = (const int *)(0x401F7F94u + 60u * id);
    if (r[1] != slot)
        return value;                           /* not the record this slot is */
    int old = *(volatile u16 *)(s + SOUND_VALUES + 2 * slot);
    int d = ((value >> 8) & 0xFF) - (old >> 8);
    if (d != 0 && (d > 0) == (smp_knob_d > 0))
        return value;                           /* stock's jump moves with the knob: kept */
    int lo = r[2] >> 8, hi = r[3] >> 8, c = (old >> 8) + smp_knob_d;
    if (hi < lo)
        return value;
    if (c < lo) c = lo;
    if (c > hi) c = hi;
    return c << 8 | (old & 0xFF);
}

/* from the setter's write (hooks.S, smp_quant_hook): S = the sound, SLOT, VALUE the
 * value about to be written (coarse << 8 | fine), ID its record -> the value to write */
int smp_quant(u8 *s, int slot, int value, u32 id)
{
    value = func_turn(s, slot, value, id);
    int mi = mnm_index((signed char)s[SOUND_TYPE] - 4);     /* v0.27: is_wr's kind */
    if (mi >= 0)
        return mnm_quant(mi, slot, *(volatile u16 *)(s + SOUND_VALUES + 2 * slot), value);
    int type = (signed char)s[SOUND_TYPE] - TYPE_FIRST;
    if (type < 0 || type >= TYPES)
        return value;
    if (slot == SMP_SAMP_SLOT) {                /* v0.27: SAMP turned by hand (smp_page.c's list) */
        extern u32 smp_samp_turned;
        smp_samp_turned = *(volatile u32 *)0x4058E8D4u;
    }
    int old = *(volatile u16 *)(s + SOUND_VALUES + 2 * slot);
    int oc = old >> 8, nc = (value >> 8) & 0xFF, d = nc - oc;
    for (int k = 0; k < SMP_NQ; k++) {
        const struct smp_q *q = &smp_q[k];
        if (q->slot != slot || !(q->types & (1 << type)))
            continue;
        if (nc == oc)
            return value;                       /* a fine move: as it is */
        int zo = zone_of(q, oc), z = zone_of(q, nc);
        if (d >= -8 && d <= 8) {
            /* a few detents a choice: v0.25, WERP's SEG three (owner: one detent each made
             * the middle choice easy to skip, and left the knob most of its turn with
             * nothing to do); v0.26, PLAY, MODE, BARS and GRID four (owner: their choices
             * sat in a sliver of the turn). A pause or a turn back starts the count again */
            static int q_acc __attribute__((section(".data"))) = 0;
            static u32 q_at __attribute__((section(".data"))) = 0;
            static int q_slot __attribute__((section(".data"))) = -1;
            int need = slot == SMP_SEG_SLOT ? SEG_DETENTS : CHOICE_DETENTS;
            u32 now = *(volatile u32 *)0x4058E8D4u;
            int dir = d > 0 ? 1 : -1;
            if (now - q_at > 3000u || (q_acc > 0) != (dir > 0) || q_slot != slot)   /* 2 s */
                q_acc = 0;
            q_at = now;
            q_slot = slot;
            q_acc += dir;
            if (q_acc > -need && q_acc < need)
                return old;                     /* not yet: the choice stays */
            q_acc = 0;
        }
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
    int smp = kind >= SMP_KIND0 && kind < SMP_KIND0 + SMP_N;   /* (v0.26: 10.. the Monomachine's) */
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
