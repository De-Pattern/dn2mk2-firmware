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

#define SEG_DETENTS 3                           /* v0.25: WERP's SEG, detents a choice */
#define CHOICE_DETENTS 4                        /* v0.26: PLAY, MODE, BARS, GRID */
#define SOUND_TYPE 0xDE                         /* the sound's machine type byte */
#define SOUND_VALUES 0x14                       /* its values, a 16-bit word a slot */
#define MNM_TUNE_J 7                            /* TUNE: knob H on every Monomachine machine */
#define MNM_TUNE_REC 240u                       /* its record (perc_param_ids[7]) */
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

/* v0.47: the Monomachine's TUNE (owner: FUNC + turn did not snap; the header said 0%..100%).
 * TUNE is the Monomachine's knob 0..127, 64 in tune, 32 a semitone (dnfw.mnm.machines: F =
 * note x 2048 / 12 + TUNE x 683 / 128): -2..+2 semitones. Its record spans 0..100, and the
 * knob is that x 127 / 100, rounded (page.c mnm_knob, the DSP's), so not every knob is there:
 * a value is written as the record value whose knob is nearest (perc.live.knob_word). FUNC +
 * turn moves to the next semitone the knob's way: 0, 32, 64, 96, 127. */
static int mnm_val_for(int j, int k, int t, int dir)
{
    /* the record's coarse value whose knob is past K the knob's way and nearest T (a tie: the
     * one further that way), so a click always moves */
    int top = mnm_top[j], best = -1, bd = 1000;
    for (int v = 0; v <= top; v++) {
        int kv = (v * 254 + top) / (2 * top);
        if (dir > 0 ? kv <= k : kv >= k)
            continue;
        int d = kv - t;
        if (d < 0) d = -d;
        if (d < bd || (d == bd && dir > 0)) { bd = d; best = v; }
    }
    return best < 0 ? -1 : mnm_lo[j] + best;
}

static int mnm_tune_step(int old, int dir)
{
    int k = mnm_kn(MNM_TUNE_J, old >> 8), t;
    if (dir > 0)
        t = k >= 127 ? 127 : (k / 32 + 1) * 32;
    else
        t = k <= 0 ? 0 : ((k - 1) / 32) * 32;
    if (t > 127) t = 127;
    int v = mnm_val_for(MNM_TUNE_J, k, t, dir);
    return v < 0 ? old : v << 8;                /* at the end already: as it is */
}

static int fq_click __attribute__((section(".data"))) = 0;      /* v0.32: a FUNC click (+1/-1), else 0 */

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
        int need = fq_click ? 1 : count <= 8 ? 4 : 1;   /* v0.32: FUNC: one a click */
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

/* v0.45: FASCIA's choices (TYPA, TYPB 6; BODA 9; BODB 10; XMOD 5: dnfw.fascia.machines), four
 * detents a choice, every one of them (the owner: the v0.26 feel; mnm_quant gives a list of
 * more than eight one detent each). The knob is the value over its record's span x 127,
 * rounded (0..127 records: the value), the choice (knob x n) >> 7, the model's choice(); a
 * choice is written as the middle of its knob range; a jump lands in the choice it reaches. */
#define FSC_DETENTS 4

static int fsc_j(int slot)                      /* the control on SLOT, or -1 */
{
    for (int j = 0; j < FSC_N; j++)
        if (fsc_slot[j] == slot)
            return j;
    return -1;
}

static int fsc_kn(int j, int c)                 /* coarse value -> knob 0..127 */
{
    int top = fsc_top[j];
    c -= fsc_lo[j];
    c = c < 0 ? 0 : c > top ? top : c;
    return top == 127 ? c : (c * 254 + top) / (2 * top);
}

static int fsc_rep(int j, int o)                /* the coarse value in the middle of choice O */
{
    int n = fsc_choices[j], a = -1, b = -1;
    for (int k = 0; k < 128; k++)
        if (((k * n) >> 7) == o) {
            if (a < 0)
                a = k;
            b = k;
        }
    if (a < 0)
        a = b = 0;
    int k = (a + b) / 2, top = fsc_top[j];
    if (top == 127)
        return fsc_lo[j] + k;
    int best = 0, bd = 1000;                    /* the value whose knob is nearest k (as */
    for (int v = 0; v <= top; v++) {            /* dnfw.fascia.machines word_of) */
        int d = (v * 254 + top) / (2 * top) - k;
        d = d < 0 ? -d : d;
        if (d < bd) {
            bd = d;
            best = v;
        }
    }
    return fsc_lo[j] + best;
}

int fsc_q_off __attribute__((section(".data"))) = 0;   /* MACHINE SEL's defaults (rec.c): as written */

static int fsc_quant(int slot, int old, int value)
{
    int j = fsc_j(slot);
    if (fsc_q_off || j < 0 || !fsc_choices[j])
        return value;                           /* not FASCIA's, or a knob */
    int n = fsc_choices[j];
    int oc = old >> 8, nc = (value >> 8) & 0xFF, d = nc - oc;
    if (nc == oc)
        return value;
    int c;
    if (d >= -8 && d <= 8) {
        static int f_acc __attribute__((section(".data"))) = 0;
        static u32 f_at __attribute__((section(".data"))) = 0;
        static int f_slot __attribute__((section(".data"))) = -1;
        int need = fq_click ? 1 : FSC_DETENTS;  /* FUNC: one a click */
        u32 now = *(volatile u32 *)0x4058E8D4u;
        int dir = d > 0 ? 1 : -1;
        if (now - f_at > 3000u || (f_acc > 0) != (dir > 0) || f_slot != slot)   /* 2 s */
            f_acc = 0;
        f_at = now;
        f_slot = slot;
        f_acc += dir;
        if (f_acc > -need && f_acc < need)
            return old;                         /* not yet: the choice stays */
        f_acc = 0;
        c = ((fsc_kn(j, oc) * n) >> 7) + dir;
    } else
        c = (fsc_kn(j, nc) * n) >> 7;           /* a jump: the choice it lands in */
    if (c < 0) c = 0;
    if (c > n - 1) c = n - 1;
    return fsc_rep(j, c) << 8;
}

/* v0.32: FUNC + turn on our machines' controls (a tester's list, v0.30; the owner: a
 * control that jumps with FUNC should go on jumping to its next value, one that does not
 * should not move). Stock gives some parameter records a FUNC jump (WaveTone's TUNE by
 * octaves, its waves). Our controls sit on stock records, and on most of the ones that
 * carry a jump the stock jump lands on one fixed value and stays there (TUNE at 50, BR1 SU
 * at 0, PLAY MODE at 0 ...). So, with FUNC held, a fresh knob turn and a track on one of
 * our machines, each control is one of:
 *   KEEP    stock's jump is right for it: the sample machines' TUNE and PERC's first
 *           control (record 238: by octaves), PERC's TYPE;
 *   CHOICE  a control of choices (waves, modes, voice types, SEG, BARS, PCH): the next
 *           choice the way the knob turned, one a click;
 *   NONE    anything else: it does not move, as a stock control with no jump.
 * The knob comes from the UI item (rec.c smp_ui_pop: smp_knob_d, smp_knob_at). */
extern int smp_func_held;
extern int smp_knob_d;
extern u32 smp_knob_at;
#define KNOB_FRESH 150u                         /* 100 ms: the turn this write comes from */
enum { F_OFF, F_KEEP, F_CHOICE, F_NONE, F_TUNE };
#define OWN_REC_FIRST 238u                      /* our records (dnfw.perc / dnfw.sampler machines) */
#define OWN_REC_LAST 260u

static int func_kind(u8 *s, int slot, u32 id)
{
    if (!smp_func_held || !smp_knob_d || *(volatile u32 *)0x4058E8D4u - smp_knob_at > KNOB_FRESH)
        return F_OFF;
    int ty = (signed char)s[SOUND_TYPE];
    /* v0.33: only our machines' own controls, records 238..260 (PERC's, the Monomachine's
     * and the sample machines' pages); LFO, filter, amp and FX keep stock's FUNC jumps (the
     * owner and a tester: LFO DEPTH and SPEED snapped to nothing on our tracks in v0.32) */
    if (ty == FSC_TYPE) {                       /* v0.45: FASCIA's 24 (some on FM Tone's records): */
        int j = fsc_j(slot);                    /* a choice steps, a knob stays put */
        return j < 0 || fsc_rid[j] != id ? F_OFF : fsc_choices[j] ? F_CHOICE : F_NONE;
    }
    if (id < OWN_REC_FIRST || id > OWN_REC_LAST)
        return F_OFF;
    if (ty == 5)                                /* PERC */
        return slot == PERC_PTCH_SLOT || slot == PERC_TYPE_SLOT ? F_KEEP : F_NONE;
    int mi = mnm_index(ty - 4);
    if (mi >= 0) {
        for (int j = 0; j < 8; j++)
            if (mnm_slot[j] == slot) {
                if (j == MNM_TUNE_J && mnm_labels[mi][j][0] == 'T' && mnm_labels[mi][j][1] == 'U')
                    return F_TUNE;              /* v0.47: by semitones (the owner) */
                return mnm_choices[mi][j] ? F_CHOICE : F_NONE;
            }
        return F_NONE;
    }
    int type = SMP_IDX(ty - 4);                 /* v0.44: the sample row (BOUNCE's is 6, type 17) */
    if (type < 0)
        return F_OFF;                           /* a stock machine: stock's */
    if (slot == SMP_TUNE_SLOT)
        return F_KEEP;
    for (int k = 0; k < SMP_NQ; k++)
        if (smp_q[k].slot == slot && (smp_q[k].types & (1 << type)))
            return F_CHOICE;
    for (int k = 0; k < SMP_NQS; k++)
        if (smp_qs[k].slot == slot && (smp_qs[k].types & (1 << type)))
            return F_CHOICE;
    return F_NONE;
}

/* from the setter's write (hooks.S, smp_quant_hook): S = the sound, SLOT, VALUE the
 * value about to be written (coarse << 8 | fine), ID its record -> the value to write */
int smp_quant(u8 *s, int slot, int value, u32 id)
{
    int fk = func_kind(s, slot, id);
    int old0 = *(volatile u16 *)(s + SOUND_VALUES + 2 * slot);
    if (fk == F_NONE)
        return old0;
    if (fk == F_TUNE)
        return mnm_tune_step(old0, smp_knob_d > 0 ? 1 : -1);
    if (fk == F_CHOICE) {                       /* one choice a click, the knob's way: a */
        fq_click = smp_knob_d > 0 ? 1 : -1;     /* detent's worth past the old value, */
        int oc0 = old0 >> 8;                    /* each table's own step below */
        if ((oc0 == 0 && fq_click < 0) || (oc0 == 255 && fq_click > 0)) {
            fq_click = 0;
            return old0;                        /* at the end already */
        }
        value = (oc0 + fq_click) << 8;
    } else
        fq_click = 0;
    if ((signed char)s[SOUND_TYPE] == FSC_TYPE)             /* v0.45: FASCIA */
        return fsc_quant(slot, *(volatile u16 *)(s + SOUND_VALUES + 2 * slot), value);
    int mi = mnm_index((signed char)s[SOUND_TYPE] - 4);     /* v0.27: is_wr's kind */
    if (mi >= 0)
        return mnm_quant(mi, slot, *(volatile u16 *)(s + SOUND_VALUES + 2 * slot), value);
    int type = SMP_IDX((signed char)s[SOUND_TYPE] - 4);   /* v0.44: BOUNCE's row too */
    if (type < 0)
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
            int need = fq_click ? 1 : slot == SMP_SEG_SLOT ? SEG_DETENTS : CHOICE_DETENTS;
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

static void f_buf(int v, char *buf)             /* v0.46 BOUNCE's BUF: 1..8 (depaffect: it read 0%..100%) */
{
    int b = coarse(v, SMP_BUF_ID);
    put_num(buf, (b < 0 ? 0 : b > 7 ? 7 : b) + 1);
}

/* v0.47: the Monomachine's TUNE as a signed knob, -64..+63 (0 in tune, 32 a semitone),
 * not stock's percentage of the record it sits on */
static void f_mtune(int v, char *buf)
{
    int k = mnm_kn(MNM_TUNE_J, (v >> 8) & 0xFF) - 64;
    if (k > 0) {
        buf[0] = '+';
        put_num(buf + 1, k);
    } else
        put_num(buf, k);
}

/* v0.45: FASCIA's values in the header (and its page with SYN held): a knob 0..127, the
 * bipolar four (TUNE, GEOM, SKIN, SHIFT) -64..+63, a choice its option's name. One formatter
 * a control: the stock formatter is handed the value only. */
static void fsc_text(int j, int v, char *buf)
{
    int k = fsc_kn(j, (v >> 8) & 0xFF), n = fsc_choices[j];
    if (n) {
        int o = (k * n) >> 7;
        put(buf, fsc_choice_name[fsc_choice_at[j] + (o > n - 1 ? n - 1 : o)], 7);
    } else if (fsc_bipolar[j]) {
        if (k == 64)
            put(buf, "0", 2);
        else {
            buf[0] = k > 64 ? '+' : '-';
            put_num(buf + 1, k > 64 ? k - 64 : 64 - k);
        }
    } else
        put_num(buf, k);
}
#define FSC_F(j) static void fsc_f##j(int v, char *b) { fsc_text(j, v, b); }
FSC_F(0) FSC_F(1) FSC_F(2) FSC_F(3) FSC_F(4) FSC_F(5) FSC_F(6) FSC_F(7)
FSC_F(8) FSC_F(9) FSC_F(10) FSC_F(11) FSC_F(12) FSC_F(13) FSC_F(14) FSC_F(15)
FSC_F(16) FSC_F(17) FSC_F(18) FSC_F(19) FSC_F(20) FSC_F(21) FSC_F(22) FSC_F(23)
static void (*const fsc_fns[])(int, char *) = {
    fsc_f0, fsc_f1, fsc_f2, fsc_f3, fsc_f4, fsc_f5, fsc_f6, fsc_f7, fsc_f8, fsc_f9, fsc_f10, fsc_f11,
    fsc_f12, fsc_f13, fsc_f14, fsc_f15, fsc_f16, fsc_f17, fsc_f18, fsc_f19, fsc_f20, fsc_f21, fsc_f22, fsc_f23};
_Static_assert(sizeof fsc_fns / sizeof fsc_fns[0] == FSC_N, "one formatter a FASCIA control");
static void *fsc_stock_fmt[FSC_N] __attribute__((section(".data")));

/* the records whose text is ours on a sample machine's track; 239, SLCE's and LEN's
 * records only on GRID's (ONESHOT's STRT, LOOP and CFAD are the same records) */
static const u16 fmt_ids[] = {SMP_PLAY_REC, SMP_MODE_REC, SMP_BARS_REC, SMP_SEG_REC, SMP_GRID_REC,
                              SMP_SAMP_REC, SMP_SLICE_ID, SMP_SLEN_ID, SMP_BUF_ID, MNM_TUNE_REC};
static void (*const fmt_fns[])(int, char *) = {f_play, f_mode, f_bars, f_seg, f_grid, f_samp,
                                               f_slce, f_slen, f_buf, f_mtune};   /* (v0.22: the recorder's are a screen's now) */
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
        for (int j = 0; j < FSC_N; j++)         /* v0.45: FASCIA's, before anything is swapped */
            fsc_stock_fmt[j] = RECORD_FMT(fsc_rid[j]);
        fmt_saved = 1;
    }
    for (int j = 0; j < FSC_N; j++)             /* v0.45: stock's back first (the sample */
        RECORD_FMT(fsc_rid[j]) = fsc_stock_fmt[j];   /* machines' share five of the records) */
    int smp = SMP_IDX(kind) >= 0;   /* (v0.26: 10.. the Monomachine's; v0.44: 13 BOUNCE) */
    for (int k = 0; k < NFMT; k++) {
        void *f = stock_fmt[k];
        if (fmt_ids[k] == MNM_TUNE_REC) {       /* v0.47: on a Monomachine machine's track only */
            RECORD_FMT(fmt_ids[k]) = mnm_index(kind) >= 0 ? (void *)fmt_fns[k] : f;
            continue;
        }
        int grid_only = fmt_ids[k] == SMP_GRID_REC;
        int slices = fmt_ids[k] == SMP_SLICE_ID || fmt_ids[k] == SMP_SLEN_ID;  /* GRID's, SLICE's */
        if (smp && (!grid_only || kind == SMP_GRID_KIND)
            && (!slices || kind == SMP_GRID_KIND || kind == SMP_SLICE_KIND)
            && (fmt_ids[k] != SMP_MODE_REC || kind == SMP_WERP_KIND)
            && (fmt_ids[k] != SMP_BUF_ID || kind == SMP_BOUNCE_KIND))     /* v0.46: 244 is stock's elsewhere */
            f = (void *)fmt_fns[k];
        RECORD_FMT(fmt_ids[k]) = f;
    }
    if (kind == FSC_KIND)                       /* v0.45: FASCIA's, last */
        for (int j = 0; j < FSC_N; j++)
            RECORD_FMT(fsc_rid[j]) = (void *)fsc_fns[j];
}
