/* v0.69: PERFORM, the Analog Four MKII's performance macros (owner, 2026-11-21; docs/perform.md,
 * the A4 MKII manual 9.3).
 *
 * Eight macros, one on each encoder. Each moves up to five parameters, on any track, by its own
 * depth: an OFFSET on top of what the track already plays (the sound, its locks, its LFOs). The
 * sound itself never changes: the offset is added to the modulated parameter mirror after
 * stock's modulation (link.c smp_mod_apply, the audio interrupt), and taken off again when the
 * macro returns to 0, PERF MUTE is on, or a target is changed.
 *
 * - [MOD] + [FX]: PERFORM (again, or NO: closed). A..H turn the macros; a pushed encoder (or
 *   YES on the last one turned) opens its MODULATION SETUP; FUNC + a pushed encoder puts that
 *   macro back to 0; FUNC + YES: PERF MUTE.
 * - MODULATION SETUP: five targets. A..E their DEPTH; LEFT / RIGHT the selected target; F its
 *   track, G its parameter (the track's LFO destinations, named as the LFO page names them);
 *   H the macro's value (a preview); H pushed: BIPOLAR (-64..+63) or not (0..127); YES: the
 *   macro's name (the stock NAME screen); FUNC + NO: the macro cleared; NO: back.
 * - Per project: a record in the +Drive's free range 0x6E0500..0x6E05FF (two copies a
 *   project, the newer wins, as microtuning's), written two seconds after the last change. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef signed char s8;

#define D __attribute__((section(".data")))

#define UI_TRACK (*(volatile u8 *)0x42431A6Cu)
#define NOW (*(volatile u32 *)0x4058E8D4u)
#define ACTIVE_PROJECT (*(volatile signed char *)0x405CD899u)
#define BLK_READ  ((int (*)(u32, u32, void *))0x4012C59Au)
#define BLK_WRITE ((int (*)(u32, u32, const void *))0x4012C780u)
#define BLK_READY (*(volatile u32 *)0x4461B68Cu)
#define BLK_SECTORS (*(volatile u32 *)0x4461B6B0u)

#define SET_PIXEL ((void (*)(void *, int, int, int))0x40113B90)
#define TEXT      ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545C)
#define FONT      0x44507ED8u
#define TITLE_FONT 0x44507EF8u                          /* MACHINE SEL's title (0x4005b820) */
#define LABEL_FONT 0x40291760u
#define LABEL_TEXT ((void (*)(void *, u32, int, int, int, int, const char *, const char *, ...))0x40115668u)
#define LABEL(c, x, y, fmt, ...) LABEL_TEXT((c), LABEL_FONT, (x), (y), 1, 0, 0, fmt, __VA_ARGS__)
#define CENTRED 2

/* the modulated parameter mirror, a voice slot's 101 u16 cells (value << 8 | fine) */
#define MIRROR_CELL(b, s) ((volatile u16 *)(0x800068E4u + 34u + 202u * (u32)(b) + 2u * (u32)(s)))
#define VOICE_SOUND(b) (*(u8 *volatile *)(0x800052A8u + 4u * (u32)(b)))

/* a track's parameter set and its destinations (as the LFO page's DEST: 0x400c2530) */
#define UI_A ((u32 (*)(void))0x4018A97Au)
#define UI_B ((u32 (*)(u32))0x4003E41Au)
#define PSET ((u32 (*)(u32, int))0x400312FEu)     /* (stock returns in d0: never a pointer type here) */
#define REC_GROUP ((int (*)(int))0x400DBCE8u)
#define GROUP_NAME ((u32 (*)(int))0x400DC3F0u)
#define PARAM_TABLE 0x401F7F94u
#define NSLOTS 101
extern u32 wr_lfo_mask(u32 rec);

#define PF_AT 0x6E0500u
#define PF_END (PF_AT + 256u)
_Static_assert(PF_AT >= 0x6E0500u && PF_END <= 0x6E0600u, "the free range between the tunings and the bank lists");
#define PF_MAGIC 0x444E3250u                            /* 'DN2P' */
#define PF_VERSION 1u
#define PF_CHECK_AT 508u
#define PF_N 8
#define PF_T 5
#define PF_NAME 8
#define NO_TRK 0xFF

#define IT_KEY 0
#define IT_KNOB 1
#define F_PRESS 0x01
#define F_REPEAT 0x08
#define F_RELEASE 0x10
enum { K_FX = 5, K_MOD = 6, K_YES = 10, K_UP = 11, K_NO = 12, K_LEFT = 13, K_DOWN = 14, K_RIGHT = 15,
       K_FUNC = 17, K_ENC_A = 41, K_ENC_H = 48 };

extern int smp_er_lock;
extern int smp_overlay_dirty;
extern int smp_func_held;
extern u32 smp_held_lo;
extern volatile u32 smp_pj_loads, smp_pj_news, smp_pj_last;
extern volatile int smp_pj_slot, smp_pj_newslot;
extern int rec_running(void);
extern void smp_knob(void *c, int x, int y, int v, int top, int dotted);   /* smp_page.c: the DT2's knob */
extern int smp_name_screen(const char *title, const char *text, int max, void (*done)(const char *));

/* -- the state ----------------------------------------------------------------------------- */

struct pf_target { u8 trk, slot; s8 depth; } __attribute__((packed));
struct pf_macro { char name[PF_NAME + 1]; u8 bip; s8 val; struct pf_target t[PF_T]; } __attribute__((packed));
_Static_assert(sizeof(struct pf_macro) == 26, "a macro: 26 bytes (scripts/emu_perform.py, ship_gate.py perform)");
struct pf_macro pf[PF_N] D;
int pf_mute D = 0;
int pf_ui D = 0;                                /* 0 closed, 1 PERFORM, 2 MODULATION SETUP */
int pf_sel D = 0;                               /* the macro last turned / being set up */
int pf_col D = 0;                               /* SETUP's target */
int pf_owner D = -2;
u32 pf_opens D = 0, pf_frames D = 0, pf_writes D = 0, pf_reads D = 0, pf_bad D = 0;

/* what the interrupt applies: a list of (track, slot, offset), published as a pair of tables.
 * v0.76 (D4, 2026-11-25: a macro move jumped and zippered): the offset is in the cell's own
 * units (1/256 of a step, the cell's fine byte), not whole steps, and the interrupt glides the
 * applied offset to it (SLEW, below) instead of jumping: stock's smoother is before us, so a
 * move needs a smoother of its own */
struct pf_apply { u8 trk, slot; short pad; int off; int pad2; };   /* 12 bytes: an 8-byte stride is a
                                                                   * scaled index of 8, which the V4e lacks */
struct pf_pub { int n; struct pf_apply a[PF_N * PF_T]; };
struct pf_pub pf_tab[2] D;
volatile int pf_tsel D = 0;
volatile u32 pf_gen D = 0;                      /* each publish: the interrupt re-reads on a change */
/* the interrupt's own: what it last wrote into each cell, and what was there before it */
static u16 wrote[PF_N * PF_T][16] D;            /* v0.70: per voice (the mirror's blocks are voices) */
static u16 base[PF_N * PF_T][16] D;
static u16 held[PF_N * PF_T] D;                 /* bit v: voice v's cell holds our offset now */
static struct pf_apply live[PF_N * PF_T] D;
static int cur[PF_N * PF_T] D;                  /* v0.76: the offset applied now, gliding to live[i].off */
static int ncur[PF_N * PF_T] D;
/* the glide: each frame an eighth of the way left (at least what is left under 8: 1/32 of a
 * step), so a jump of a whole range settles in about 50 frames (some 35 ms) with no steps in it */
#define SLEW 8
static int glide(int c, int target)
{
    int d = target - c, st = d / SLEW;
    return c + (st ? st : d);
}
static int nlive D = 0;
static u32 seen_gen D = 0xFFFFFFFFu;

static int dirty D = 0;
static u32 dirty_at D = 0;
static u32 seen_loads D = 0, seen_news D = 0;
static u32 owner_seq D = 0;
static int owner_copy D = 1;
static u8 rec[512] D = {0};

static int clamp(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }
static int inited D = 0;

static void reset(void)
{
    inited = 1;
    for (int m = 0; m < PF_N; m++) {
        for (int k = 0; k <= PF_NAME; k++)
            pf[m].name[k] = 0;
        pf[m].bip = 0;
        pf[m].val = 0;
        for (int k = 0; k < PF_T; k++) {
            pf[m].t[k].trk = NO_TRK;
            pf[m].t[k].slot = 0;
            pf[m].t[k].depth = 0;
        }
    }
    pf_mute = 0;
}

/* the macros' offsets into the idle table, then flip (the interrupt takes it at its next frame) */
void pf_publish(void)
{
    struct pf_pub *p = &pf_tab[pf_tsel ^ 1];
    int n = 0;
    for (int m = 0; m < PF_N; m++)
        for (int k = 0; k < PF_T; k++) {
            const struct pf_target *t = &pf[m].t[k];
            if (t->trk >= 16 || t->slot >= NSLOTS || !t->depth)
                continue;
            int off = pf_mute ? 0 : pf[m].bip ? t->depth * pf[m].val * 256 / 64 : t->depth * pf[m].val * 256 / 127;
            int j = 0;                          /* one entry a cell: two macros on one add */
            while (j < n && !(p->a[j].trk == t->trk && p->a[j].slot == t->slot))
                j++;
            if (j == n) {
                p->a[n].trk = t->trk;
                p->a[n].slot = t->slot;
                p->a[n].pad = 0;
                p->a[n].pad2 = 0;
                p->a[n].off = 0;
                n++;
            }
            p->a[j].off += off;
        }
    p->n = n;
    pf_tsel ^= 1;
    pf_gen++;                                   /* (two publishes between frames: still seen) */
}

void pf_mark(void)                              /* (a change to be written; the gate's too) */
{
    dirty = 1;
    dirty_at = NOW;
}

static void changed(void)
{
    pf_publish();
    dirty = 1;
    dirty_at = NOW;
    smp_overlay_dirty = 1;
}

/* the audio interrupt, after stock's modulation (link.c smp_mod_apply): each cell a macro moves
 * gets its offset on top of what stock put there. The mirror's blocks are VOICES (202 bytes a
 * voice; link.c MIRROR_CELL: the sound on voice b at 0x800052A8 + 4 b), and with the DN2's voice
 * allocation a track's notes play on any of them: so a target on track t moves the cell of every
 * voice the ColdFire's voice -> track table (0x80005308, link.c SLOT_TRACK) gives to t, and puts
 * back the cell of a voice that has gone to another track. (v0.69 took block t for track t:
 * right only while voice t played track t, so a macro moved the wrong track or nothing, and
 * worked "on some trigs" -- Dubmaster, 2026-11-22. The emulator's tracks each sat on their own
 * voice.) A cell stock has not rewritten since (it still holds what we wrote) gets the offset on
 * top of what was there before us, so it never piles up. */
#define VOICE_TRACK ((volatile u32 *)0x80005308u)

static void put_back_voice(int i, int v)
{
    if (held[i] >> v & 1u) {
        volatile u16 *cell = MIRROR_CELL(v, live[i].slot);
        if (*cell == wrote[i][v])
            *cell = base[i][v];
        held[i] &= (u16)~(1u << v);
    }
}

static void put_back(int i)
{
    for (int v = 0; v < 16; v++)
        put_back_voice(i, v);
}

void pf_apply(void)
{
    int s = pf_tsel;
    u32 g = pf_gen;
    if (g != seen_gen) {                       /* a new table: cells no longer moved as they were */
        const struct pf_pub *p = &pf_tab[s];
        int same = p->n == nlive;
        for (int i = 0; same && i < nlive; i++)
            same = p->a[i].trk == live[i].trk && p->a[i].slot == live[i].slot;
        for (int i = 0; i < p->n; i++) {         /* a cell still moved keeps its glide */
            ncur[i] = 0;
            for (int j = 0; j < nlive; j++)
                if (live[j].trk == p->a[i].trk && live[j].slot == p->a[i].slot)
                    ncur[i] = cur[j];
        }
        if (!same) {
            for (int i = 0; i < nlive; i++)
                put_back(i);
            nlive = p->n;
        }
        for (int i = 0; i < p->n; i++) {
            live[i].trk = p->a[i].trk;          /* (field by field: a 12-byte copy is a memcpy call) */
            live[i].slot = p->a[i].slot;
            live[i].off = p->a[i].off;
            cur[i] = ncur[i];
        }
        seen_gen = g;
    }
    for (int i = 0; i < nlive; i++) {
        int t = live[i].trk, off = cur[i] = glide(cur[i], live[i].off);
        for (int v = 0; v < 16; v++) {
            if (t > 15 || !off || VOICE_TRACK[v] != (u32)t || !VOICE_SOUND(v)) {
                put_back_voice(i, v);
                continue;
            }
            volatile u16 *cell = MIRROR_CELL(v, live[i].slot);
            u16 now = *cell;
            u16 was = (held[i] >> v & 1u) && now == wrote[i][v] ? base[i][v] : now;
            int nv = clamp((int)was + off, 0, 0x7FFF);
            *cell = (u16)nv;
            base[i][v] = was;
            wrote[i][v] = (u16)nv;
            held[i] |= (u16)(1u << v);
            pf_frames++;
        }
    }
}

/* -- the record ---------------------------------------------------------------------------- */

static u32 csum(const u8 *p, u32 n)
{
    u32 a = 1, b = 0;
    for (u32 k = 0; k < n; k++) {
        a += p[k];
        b += a;
    }
    return b << 16 ^ a;
}
static u32 be32(const u8 *p) { return (u32)p[0] << 24 | (u32)p[1] << 16 | (u32)p[2] << 8 | p[3]; }
static void put32(u8 *p, u32 v) { p[0] = (u8)(v >> 24); p[1] = (u8)(v >> 16); p[2] = (u8)(v >> 8); p[3] = (u8)v; }
static u32 sector_of(int p, int c) { return PF_AT + 2u * (u32)p + (u32)c; }
static int ready(void) { return BLK_READY && BLK_SECTORS >= PF_END; }
#define M_AT(m) (20 + 28 * (m))                 /* a macro: its name (8), BIPOLAR, value, 5 x (trk, slot, depth) */

static u32 copy_read(int p, int c)
{
    u32 s = sector_of(p, c);
    if (!ready() || s < PF_AT || s >= PF_END || BLK_READ(s, 512u, rec))
        return 0;
    pf_reads++;
    if (be32(rec) != PF_MAGIC || be32(rec + 4) != PF_VERSION || be32(rec + 8) != (u32)p
        || be32(rec + PF_CHECK_AT) != (csum(rec, PF_CHECK_AT) ^ 0x50455246u)) {
        if (be32(rec) == PF_MAGIC)
            pf_bad++;
        return 0;
    }
    for (int m = 0; m < PF_N; m++) {
        const u8 *q = rec + M_AT(m);
        for (int k = 0; k < PF_NAME; k++)
            if (q[k] && (q[k] < ' ' || q[k] > '~'))
                return 0;
        if (q[8] > 1 || (q[8] ? ((s8)q[9] < -64 || (s8)q[9] > 63) : (s8)q[9] < 0))
            return 0;
        for (int k = 0; k < PF_T; k++) {
            const u8 *t = q + 10 + 3 * k;
            if ((t[0] >= 16 && t[0] != NO_TRK) || t[1] >= NSLOTS || (s8)t[2] < -64 || (s8)t[2] > 63)
                return 0;
        }
    }
    return be32(rec + 12);
}

static int load(int p, int apply)
{
    u32 s0 = copy_read(p, 0), s1 = copy_read(p, 1), best = s0;
    int c = 0;
    if (s1 > best) {
        best = s1;
        c = 1;
    }
    owner_seq = best;
    owner_copy = best ? c : 1;
    if (!best || !apply)
        return best != 0;
    if (c == 0)
        copy_read(p, 0);
    pf_mute = rec[16] & 1;
    for (int m = 0; m < PF_N; m++) {
        const u8 *q = rec + M_AT(m);
        for (int k = 0; k < PF_NAME; k++)
            pf[m].name[k] = (char)q[k];
        pf[m].name[PF_NAME] = 0;
        pf[m].bip = q[8];
        pf[m].val = (s8)q[9];
        for (int k = 0; k < PF_T; k++) {
            pf[m].t[k].trk = q[10 + 3 * k];
            pf[m].t[k].slot = q[11 + 3 * k];
            pf[m].t[k].depth = (s8)q[12 + 3 * k];
        }
    }
    pf_publish();
    return 1;
}

static int store(int p)
{
    if (p < 0 || p > 127 || smp_er_lock || !ready())
        return -1;
    for (u32 k = 0; k < 512u; k++)
        rec[k] = 0;
    put32(rec, PF_MAGIC);
    put32(rec + 4, PF_VERSION);
    put32(rec + 8, (u32)p);
    put32(rec + 12, owner_seq + 1u);
    rec[16] = (u8)(pf_mute & 1);
    for (int m = 0; m < PF_N; m++) {
        u8 *q = rec + M_AT(m);
        for (int k = 0; k < PF_NAME; k++)
            q[k] = (u8)pf[m].name[k];
        q[8] = pf[m].bip;
        q[9] = (u8)pf[m].val;
        for (int k = 0; k < PF_T; k++) {
            q[10 + 3 * k] = pf[m].t[k].trk;
            q[11 + 3 * k] = pf[m].t[k].slot;
            q[12 + 3 * k] = (u8)pf[m].t[k].depth;
        }
    }
    put32(rec + PF_CHECK_AT, csum(rec, PF_CHECK_AT) ^ 0x50455246u);
    int c = owner_copy ^ 1;
    u32 s = sector_of(p, c);
    if (s < PF_AT || s >= PF_END || BLK_WRITE(s, 512u, rec))
        return -1;
    owner_seq++;
    owner_copy = c;
    pf_writes++;
    return 0;
}

static int is_default(void)
{
    if (pf_mute)
        return 0;
    for (int m = 0; m < PF_N; m++) {
        if (pf[m].name[0] || pf[m].bip || pf[m].val)
            return 0;
        for (int k = 0; k < PF_T; k++)
            if (pf[m].t[k].trk != NO_TRK)
                return 0;
    }
    return 1;
}

static int active(void)
{
    int a = ACTIVE_PROJECT;
    return a >= 0 && a < 128 ? a : -1;
}

/* the UI loop (rec_poll): follow the project, write a change once it has settled */
void pf_poll(void)
{
    if (!ready())
        return;
    if (pf_owner == -2) {
        seen_loads = smp_pj_loads;
        seen_news = smp_pj_news;
        pf_owner = active();
        reset();
        if (pf_owner >= 0)
            load(pf_owner, 1);
        pf_publish();
        return;
    }
    u32 L = smp_pj_loads, N = smp_pj_news;
    if (L != seen_loads || N != seen_news) {
        seen_loads = L;
        seen_news = N;
        if (dirty && pf_owner >= 0)
            store(pf_owner);
        dirty = 0;
        int isnew = smp_pj_last == 2;
        int s = isnew ? smp_pj_newslot : smp_pj_slot;
        pf_owner = s >= 0 && s < 128 ? s : -1;
        reset();
        if (pf_owner >= 0) {
            int found = load(pf_owner, !isnew);
            if (isnew && found) {
                dirty = 1;
                dirty_at = NOW;
            }
        }
        pf_publish();
        pf_ui = 0;
        smp_overlay_dirty = 1;
        return;
    }
    int act = active();
    if (act != pf_owner) {
        pf_owner = act;
        if (act >= 0 && (load(act, 0) || !is_default())) {
            dirty = 1;
            dirty_at = NOW;
        }
    }
    if (dirty && pf_owner >= 0 && NOW - dirty_at > 3000u && !rec_running()) {
        if (store(pf_owner) == 0)
            dirty = 0;
        else
            dirty_at = NOW;
    }
}

/* -- names --------------------------------------------------------------------------------- */

static void *pset(int t) { return (void *)PSET(UI_B(UI_A()), t); }

static int slot_rid(void *set, int slot)
{
    void **vt = *(void ***)set;
    return ((int (*)(void *, int))vt[0x50 / 4])(set, slot);
}

u32 pf_dbg[4] D = {0};                          /* (the gate's: the set, a slot, its record, its mask) */
static int dest_ok(void *set, int slot)
{
    int rid = slot_rid(set, slot);
    pf_dbg[0] = (u32)set;
    pf_dbg[1] = (u32)slot;
    pf_dbg[2] = (u32)rid;
    pf_dbg[3] = rid > 0 && rid < 321 ? wr_lfo_mask((u32)rid) : 0xFFFFFFFFu;
    return rid > 0 && rid < 321 && (wr_lfo_mask((u32)rid) & 0x200u);
}

/* the target's two lines, as the LFO page's DEST names them */
static void dest_names(int trk, int slot, const char **g, const char **n)
{
    *g = "";
    *n = "--";
    if (trk >= 16)
        return;
    void *set = pset(trk);
    int rid = set ? slot_rid(set, slot) : 0;
    if (rid <= 0 || rid >= 321)
        return;
    *g = rid == 19 ? (const char *)0x40218572u : (const char *)GROUP_NAME(REC_GROUP(rid));
    if (rid >= 168 && rid <= 183) {
        void **vt = *(void ***)set;
        *n = (const char *)((u32 (*)(void *, int))vt[0x58 / 4])(set, rid);
    } else
        *n = *(const char **)(PARAM_TABLE + 60u * (u32)rid + 0x30u);
    if (!*g)
        *g = "";
    if (!*n)
        *n = "--";
}

/* the next of the track's destinations from SLOT in direction D (wrapping); SLOT itself if none */
static int dest_step(int trk, int slot, int d)
{
    void *set = pset(trk);
    if (!set)
        return slot;
    for (int k = 1; k <= NSLOTS; k++) {
        int s = ((slot + d * k) % NSLOTS + NSLOTS) % NSLOTS;
        if (dest_ok(set, s))
            return s;
    }
    return slot;
}

static void letter_name(int m, char *o)          /* the macro's name, or its letter */
{
    if (pf[m].name[0]) {
        int k = 0;
        for (; k < PF_NAME && pf[m].name[k]; k++)
            o[k] = pf[m].name[k];
        while (k > 0 && o[k - 1] == ' ')
            k--;
        o[k] = 0;
        if (k)
            return;
    }
    o[0] = (char)('A' + m);
    o[1] = 0;
}

/* -- the screens (y counts from the bottom, as the panel's) -------------------------------- */

static void px(void *c, int x, int y, int on) { if (x >= 0 && x < 128 && y >= 0 && y < 64) SET_PIXEL(c, x, y, on); }
static void fillv(void *c, int x0, int y0, int x1, int y1, int on)
{
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++)
            px(c, x, y, on);
}
static void rbox(void *c, int x0, int y0, int x1, int y1, int dotted)   /* corners cut, as the DT2's */
{
    for (int x = x0 + 1; x < x1; x++)
        if (!dotted || !((x - x0) & 1)) { px(c, x, y0, 1); px(c, x, y1, 1); }
    for (int y = y0 + 1; y < y1; y++)
        if (!dotted || !((y - y0) & 1)) { px(c, x0, y, 1); px(c, x1, y, 1); }
}
static void invert(void *c, int x0, int y0, int x1, int y1)
{
    const int *cv = (const int *)c;
    u32 *bits = (u32 *)cv[4];
    for (int x = x0; x <= x1; x++)
        for (int y = y0; y <= y1; y++)
            if (x >= 0 && y >= 0 && x < cv[1] && y < cv[2])
                bits[x * cv[3] + (y >> 5)] ^= 0x80000000u >> (y & 31);
}

#define CELL_X(k) (21 + 26 * (k))               /* the stock pages' cells, as smp_page.c */
#define TOP_Y 34
#define BOT_Y 7

/* the title bar, as stock's: its text drawn, then the bar inverted round it (black on white) */
static void title(void *c, const char *left, const char *right)
{
    TEXT(c, TITLE_FONT, 2, 56, 0, "%s", left);
    if (right && right[0])
        LABEL(c, 104, 57, "%s", right);
    invert(c, 0, 55, 127, 63);
}

static void draw_page(void *c)
{
    char nm[PF_NAME + 2];
    letter_name(pf_sel, nm);
    char right[24];
    int v = pf[pf_sel].val;
    {   /* "B:BIG DROP", or "B" unnamed */
        int k = 0;
        right[k++] = (char)('A' + pf_sel);
        if (pf[pf_sel].name[0]) {
            right[k++] = ':';
            for (int j = 0; nm[j] && k < 11; j++)
                right[k++] = nm[j];
        }
        right[k] = 0;
    }
    title(c, pf_mute ? "PERFORM  MUTED" : "PERFORM", right);
    /* the left column: the selected macro's value, as stock's LEV fader */
    rbox(c, 1, 8, 15, 50, 0);
    LABEL(c, 8, 44, "%c", 'A' + pf_sel);
    {
        int h = pf[pf_sel].bip ? (v + 64) * 30 / 127 : v * 30 / 127;
        if (pf[pf_sel].bip) {
            int mid = 10 + 15;
            fillv(c, 4, mid, 12, mid, 1);
            if (v > 0)
                fillv(c, 6, mid, 10, mid + v * 15 / 64, 1);
            else if (v < 0)
                fillv(c, 6, mid + v * 15 / 64, 10, mid, 1);
        } else if (h > 0)
            fillv(c, 5, 10, 11, 10 + h, 1);
    }
    LABEL(c, 8, 1, "%d", v);
    for (int m = 0; m < PF_N; m++) {
        int x = CELL_X(m & 3), y = m < 4 ? TOP_Y : BOT_Y;
        int top = pf[m].bip ? 127 : 127, val = pf[m].bip ? pf[m].val + 64 : pf[m].val;
        int used = 0;
        for (int k = 0; k < PF_T; k++)
            used |= pf[m].t[k].trk != NO_TRK;
        smp_knob(c, x, y, val, top, !used || pf_mute);   /* dotted: nothing assigned, or muted */
        letter_name(m, nm);
        LABEL(c, x + 12, y - 7, "%.4s", nm);
        if (m == pf_sel)
            invert(c, x - 1, y - 8, x + 24, y + 19);
    }
}

static void draw_setup(void *c)
{
    char nm[PF_NAME + 2];
    struct pf_macro *M = &pf[pf_sel];
    letter_name(pf_sel, nm);
    char t[20];
    {
        int k = 0;
        t[k++] = (char)('A' + pf_sel);
        if (M->name[0]) {
            t[k++] = ':';
            for (int j = 0; nm[j] && k < 9; j++)
                t[k++] = nm[j];
        }
        t[k] = 0;
    }
    title(c, "MODULATION SETUP", t);
    /* the left column: BIPOLAR or not, and the macro's value as a bar (the A4's) */
    LABEL(c, 7, 46, "%s", M->bip ? "+-" : "0+");
    rbox(c, 1, 8, 13, 42, 0);
    {
        int v = M->val;
        if (M->bip) {
            int mid = 25;
            fillv(c, 3, mid, 11, mid, 1);
            if (v > 0) fillv(c, 4, mid, 10, mid + v * 15 / 64, 1);
            else if (v < 0) fillv(c, 4, mid + v * 15 / 64, 10, mid, 1);
        } else if (v > 0)
            fillv(c, 4, 10, 10, 10 + v * 30 / 127, 1);
        LABEL(c, 7, 1, "%d", v);
    }
    /* five columns: the track, the parameter's two lines, its depth's knob and number */
    for (int k = 0; k < PF_T; k++) {
        int x0 = 17 + 22 * k, cx = x0 + 11;
        const struct pf_target *tg = &M->t[k];
        if (k)
            for (int y = 2; y < 53; y += 2)
                px(c, x0, y, 1);                /* the dotted dividers */
        const char *g, *n;
        if (tg->trk == NO_TRK) {
            LABEL(c, cx, 46, "%s", "--");
        } else {
            LABEL(c, cx, 46, "T%d", tg->trk + 1);
            dest_names(tg->trk, tg->slot, &g, &n);
            LABEL(c, cx, 38, "%.4s", g);
            LABEL(c, cx, 31, "%.4s", n);
            smp_knob(c, cx - 12, 9, tg->depth + 64, 127, 0);
            LABEL(c, cx, 1, "%d", tg->depth);
        }
        if (k == pf_col)
            invert(c, x0 + 1, 44, x0 + 21, 52);
    }
}

static void init(void)
{
    if (!inited) {                              /* (before the +Drive is up: eight empty macros) */
        reset();
        pf_publish();
    }
}

void pf_draw(void *c)
{
    init();
    fillv(c, 0, 0, 127, 63, 0);
    if (pf_ui == 2)
        draw_setup(c);
    else
        draw_page(c);
}

int pf_visible(void) { return pf_ui != 0; }

/* -- the keys and knobs (smp_ui_pop) ------------------------------------------------------- */

static u32 eaten D = 0;
static u32 eaten_hi D = 0;                      /* the encoders' pushes, codes 41..48 */
static int f_acc D = 0, g_acc D = 0;

static void named(const char *n)
{
    struct pf_macro *M = &pf[pf_sel];
    int k = 0;
    for (; k < PF_NAME && n && n[k]; k++)
        M->name[k] = n[k];
    while (k > 0 && M->name[k - 1] == ' ')
        k--;
    for (; k <= PF_NAME; k++)
        M->name[k] = 0;
    changed();
}

static void open_setup(int m)
{
    pf_sel = m;
    pf_col = 0;
    pf_ui = 2;
    smp_overlay_dirty = 1;
}

static void knob(int k, int d)
{
    struct pf_macro *M = &pf[pf_sel];
    if (pf_ui == 1) {                           /* A..H: the macros */
        if (k < 1 || k > 8)
            return;
        struct pf_macro *X = &pf[k - 1];
        pf_sel = k - 1;
        X->val = (s8)(X->bip ? clamp(X->val + d, -64, 63) : clamp(X->val + d, 0, 127));
        changed();
        return;
    }
    struct pf_target *t = &M->t[pf_col];
    if (k >= 1 && k <= 5) {                     /* A..E: the five depths */
        struct pf_target *u = &M->t[k - 1];
        if (u->trk == NO_TRK)
            return;
        u->depth = (s8)clamp(u->depth + d, -64, 63);
    } else if (k == 6) {                        /* F: the selected target's track (two detents a step) */
        f_acc += d;
        if (f_acc > -2 && f_acc < 2)
            return;
        int step = f_acc > 0 ? 1 : -1;
        f_acc = 0;
        int tr = t->trk == NO_TRK ? (step > 0 ? 0 : -1) : t->trk + step;
        if (tr < 0 || tr > 15) {
            t->trk = NO_TRK;
            t->depth = 0;
        } else {
            t->trk = (u8)tr;
            void *set = pset(tr);
            if (!set || !dest_ok(set, t->slot))
                t->slot = (u8)dest_step(tr, t->slot, 1);
        }
    } else if (k == 7) {                        /* G: its parameter */
        if (t->trk == NO_TRK)
            return;
        g_acc += d;
        if (g_acc > -2 && g_acc < 2)
            return;
        int step = g_acc > 0 ? 1 : -1;
        g_acc = 0;
        t->slot = (u8)dest_step(t->trk, t->slot, step);
    } else if (k == 8) {                        /* H: the macro's value (a preview) */
        M->val = (s8)(M->bip ? clamp(M->val + d, -64, 63) : clamp(M->val + d, 0, 127));
    } else
        return;
    changed();
}

static int held_both(u32 code)
{
    u32 other = code == K_FX ? K_MOD : K_FX;
    return (smp_held_lo >> other & 1u) != 0;
}

int pf_pop(u8 *it)                              /* 1: the item was ours */
{
    u32 code = (u32)it[4] << 24 | (u32)it[5] << 16 | (u32)it[6] << 8 | it[7];
    u32 flags = (u32)it[8] << 24 | (u32)it[9] << 16 | (u32)it[10] << 8 | it[11];
    int down = (flags & F_PRESS) && !(flags & F_RELEASE);
    int fresh = down && !(flags & F_REPEAT);
    init();
    if (it[0] == IT_KEY && code < 32 && code != K_FUNC && (eaten >> code & 1u)) {
        if (!down)
            eaten &= ~(1u << code);
        return 1;
    }
    if (it[0] == IT_KEY && code >= K_ENC_A && code <= K_ENC_H && (eaten_hi >> (code - K_ENC_A) & 1u)) {
        if (!down)
            eaten_hi &= ~(1u << (code - K_ENC_A));
        return 1;
    }
    /* [MOD] + [FX] (either held, the other pressed): PERFORM, or closed if it is up */
    if (it[0] == IT_KEY && (code == K_FX || code == K_MOD) && fresh && held_both(code)) {
        eaten |= 1u << code;
        if (pf_ui)
            pf_ui = 0;
        else {
            pf_ui = 1;
            pf_opens++;
        }
        smp_overlay_dirty = 1;
        return 1;
    }
    if (!pf_ui)
        return 0;
    if (it[0] == IT_KEY && (code == K_MOD || code == K_FX)) {
        if (fresh)                              /* [MOD] or [FX] alone while it is up: kept, it may */
            eaten |= 1u << code;                /* be the start of [MOD] + [FX] (which closes it) */
        return 1;
    }
    if (it[0] == IT_KEY && down && code >= 1 && code <= 8) {
        pf_ui = 0;                              /* another page key: stock's, and ours closes */
        smp_overlay_dirty = 1;
        return 0;
    }
    if (it[0] == IT_KNOB) {
        knob((int)code, (signed char)it[8]);
        return 1;
    }
    if (it[0] != IT_KEY || code == K_FUNC)
        return 0;
    if (code >= K_ENC_A && code <= K_ENC_H) {   /* an encoder pushed */
        if (fresh) {
            eaten_hi |= 1u << (code - K_ENC_A);
            int k = (int)(code - K_ENC_A);
            if (pf_ui == 1) {
                if (smp_func_held) {            /* FUNC + push: that macro back to 0 */
                    pf[k].val = 0;
                    pf_sel = k;
                    changed();
                } else
                    open_setup(k);
            } else if (k == 7) {                /* SETUP, H pushed: BIPOLAR */
                struct pf_macro *M = &pf[pf_sel];
                M->bip ^= 1;
                M->val = (s8)(M->bip ? clamp(M->val - 64, -64, 63) : clamp(M->val + 64, 0, 127));
                changed();
            } else if (k < PF_T) {
                pf_col = k;
                smp_overlay_dirty = 1;
            }
        }
        return 1;
    }
    if (code == K_YES || code == K_NO || (code >= K_UP && code <= K_RIGHT)) {
        if (fresh) {
            eaten |= 1u << code;
            if (pf_ui == 1) {
                if (code == K_NO)
                    pf_ui = 0;
                else if (code == K_YES && smp_func_held) {
                    pf_mute ^= 1;               /* FUNC + YES: PERF MUTE */
                    changed();
                } else if (code == K_YES)
                    open_setup(pf_sel);
                else if (code == K_LEFT || code == K_RIGHT)
                    pf_sel = (pf_sel + (code == K_RIGHT ? 1 : PF_N - 1)) % PF_N;
                else if (code == K_UP || code == K_DOWN)
                    pf_sel = (pf_sel + 4) % PF_N;
            } else {
                if (code == K_NO && smp_func_held) {   /* FUNC + NO: the macro cleared */
                    struct pf_macro *M = &pf[pf_sel];
                    for (int k = 0; k < PF_T; k++) {
                        M->t[k].trk = NO_TRK;
                        M->t[k].slot = 0;
                        M->t[k].depth = 0;
                    }
                    M->val = 0;
                    changed();
                } else if (code == K_NO)
                    pf_ui = 1;
                else if (code == K_YES) {
                    char nm[PF_NAME + 2];
                    int k = 0;
                    for (; k < PF_NAME && pf[pf_sel].name[k]; k++)
                        nm[k] = pf[pf_sel].name[k];
                    nm[k] = 0;
                    smp_name_screen("MACRO NAME", nm, PF_NAME, named);
                } else if (code == K_LEFT || code == K_RIGHT)
                    pf_col = clamp(pf_col + (code == K_RIGHT ? 1 : -1), 0, PF_T - 1);
            }
            smp_overlay_dirty = 1;
        }
        return 1;
    }
    return 0;                                   /* the [TRIG] keys, the keyboard: stock plays them */
}

/* the gate's: a macro set directly */
void pf_set(int m, int val, int bip, int trk, int slot, int depth)
{
    if (m < 0 || m >= PF_N)
        return;
    pf[m].bip = (u8)(bip ? 1 : 0);
    pf[m].val = (s8)(bip ? clamp(val, -64, 63) : clamp(val, 0, 127));
    pf[m].t[0].trk = (u8)(trk < 0 || trk > 15 ? NO_TRK : trk);
    pf[m].t[0].slot = (u8)clamp(slot, 0, NSLOTS - 1);
    pf[m].t[0].depth = (s8)clamp(depth, -64, 63);
    changed();
}
