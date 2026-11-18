/* v0.61: microtuning (owner, 2026-11-17/18; docs/microtuning.md).
 *
 * One tuning per project: 12 offsets in tenths of a cent, one per semitone above the tuning's
 * ROOT, repeating every octave (the factory ones: dnfw.waverider.tunings; USER 1..8 the owner's
 * own). Each track is TUNED or not (16 switches). Saved per project in its own record.
 *
 * - tn_retune (the audio interrupt, ms_frame, after the frame is built): a voice whose track is
 *   tuned gets its note's offset (by the note's semitone above ROOT) added to its NOTE word
 *   (note << 8 | fine, fine in 1/256 semitone). Every other voice is stock's. (v0.58's way; it
 *   never touches stock's scale tables, so KB SETUP's SCALE and the chord MODEs are stock's.)
 *   The interrupt reads one of two snapshots (tuning, ROOT, switches); the UI writes the other
 *   and then flips, so a frame never sees half a change.
 * - KB SETUP's empty H slot (the KeyboardSetup view on top of the screen's views) is TUNE:
 *   turning it tunes this track (OFF, or one of the tunings: the project's tuning becomes it);
 *   pushing H opens TUNING.
 * - TUNING (our overlay): A TUNE, B ROOT, C TRK (this track), D ALL; the 16 tracks' switches.
 *   YES on a USER tuning: EDIT (A NOTE, B CENT, C .1 CENT, D FROM; FUNC + YES copies FROM
 *   in). NO goes back.
 * - The record: TN_AT + 2 p + c, project p (0..127), copy c, written in turn (the newer
 *   sequence wins; a record that does not check out is not used: 12-TET, every track off).
 *   Written two seconds after the last change; read when a project is loaded; NEW resets. */
#define TUNE_C
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define D __attribute__((section(".data")))

#define VOICE_TRACK ((volatile u32 *)0x80005308u)
#define FRAME_NOTE(v) (1u + (v))                       /* u16 index: byte 2 + 2v */
#define UI_TRACK (*(volatile u8 *)0x42431A6Cu)
#define KIT (*(volatile u32 *)0x800052A0u)
#define SOUND_TYPE(t) (*(volatile signed char *)(KIT + 52u + 1163u * (u32)(t) + 0xDEu))
#define GRID_TYPE 12                            /* dnfw.sampler.machines.TYPE_OF */
#define SLICE_TYPE 13
#define NOW (*(volatile u32 *)0x4058E8D4u)               /* the UI's clock (1,500 a second) */
#define ACTIVE_PROJECT (*(volatile signed char *)0x405CD899u)

#define BLK_READ  ((int (*)(u32, u32, void *))0x4012C59Au)
#define BLK_WRITE ((int (*)(u32, u32, const void *))0x4012C780u)
#define BLK_READY (*(volatile u32 *)0x4461B68Cu)
#define BLK_SECTORS (*(volatile u32 *)0x4461B6B0u)

#define SET_PIXEL ((void (*)(void *, int, int, int))0x40113B90)
#define TEXT      ((void (*)(void *, u32, int, int, int, const char *, ...))0x4011545C)
#define FONT      0x44507ED8u
#define LABEL_FONT 0x40291760u
#define LABEL_TEXT ((void (*)(void *, u32, int, int, int, int, const char *, const char *, ...))0x40115668u)
#define LABEL(c, x, y, fmt, ...) LABEL_TEXT((c), LABEL_FONT, (x), (y), 1, 0, 0, fmt, __VA_ARGS__)
#define CENTRED 2

/* the screen's coordinates: y up, a text's y its bottom (smp_page.c's RECORDER at 57) */
#define TN_HX0 100                              /* KB SETUP's H slot (its dotted box: 105..122, 8..26) */
#define TN_HX1 127
#define TN_HY0 0
#define TN_HY1 27
#define TN_HLABEL_Y 20
#define TN_HVALUE_Y 9
#define TN_HKEY_Y 0
#define TN_TITLE_Y 57                           /* TUNING and EDIT */
#define TN_NAME_Y 46
#define TN_TRK_Y0 28
#define TN_TRK_Y1 34
#define TN_MARK_Y 25
#define TN_BAR_Y0 17
#define TN_BAR_Y1 41
#define TN_KVALUE_Y 9
#define TN_KLABEL_Y 0
#define KB_VT 0x401D5650u                               /* KeyboardSetup's vtable ("KeyboardSetup", +0x24) */

#define IT_KEY 0
#define IT_KNOB 1
#define IT_DROP 0xFF
#define F_PRESS 0x01
#define F_REPEAT 0x08
#define F_RELEASE 0x10
enum { K_YES = 10, K_UP = 11, K_NO = 12, K_LEFT = 13, K_DOWN = 14, K_RIGHT = 15, K_FUNC = 17,
       K_ENC_H = 48 };

/* the region: above the per-project lists (0x6E02FF), below the library's extension (0x6F0000) */
#define TN_AT 0x6E0400u
#define TN_END (TN_AT + 256u)
_Static_assert(TN_AT >= 0x6E0300u && TN_END <= 0x6F0000u, "between the lists and the library's extension");
#define TN_MAGIC 0x444E3254u                            /* 'DN2T' */
#define TN_VERSION 1u
#define TN_ALL (TN_FACTORY + TN_USER)
#define TN_CHECK_AT 508u

extern int smp_er_lock;
extern int smp_overlay_dirty;
extern int smp_func_held;
extern volatile u32 smp_pj_loads, smp_pj_news, smp_pj_last;
extern volatile int smp_pj_slot, smp_pj_newslot;
extern int rec_running(void);

/* -- the state ----------------------------------------------------------------------------- */

short tn_user[TN_USER][12] D = {{0}};          /* tenths of a cent */
int tn_cur D = 0;                               /* 0..TN_ALL-1: factory, then USER 1..8 */
int tn_root D = 0;                              /* 0..11 (C..B) */
u32 tn_mask D = 0;                              /* the tuned tracks */
int tn_ui D = 0;                                /* 0 closed, 1 TUNING, 2 EDIT */
int tn_note D = 0, tn_from D = 0;               /* EDIT's note and source */

struct snap { short fine[12]; short root; u16 mask; };
struct snap tn_snap[2] D = {{{0}, 0, 0}, {{0}, 0, 0}};
volatile int tn_sel D = 0;                      /* the interrupt's snapshot */
u32 tn_frames D = 0;                            /* frames a voice was retuned in (the gate) */
u32 tn_writes D = 0, tn_reads D = 0, tn_bad D = 0;   /* records written, read, refused */
int tn_owner D = -2;                            /* whose tuning this is (-1 unsaved, -2 not yet read) */
static int dirty D = 0;
static u32 dirty_at D = 0;
static u32 seen_loads D = 0, seen_news D = 0;
static u32 owner_seq D = 0;                     /* the owner's newest record's sequence */
static int owner_copy D = 1;                    /* and its copy */
static u8 rec[512] D = {0};

static int clamp(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

int tn_offset(int t, int pc)                    /* tenths of a cent: tuning T at semitone PC */
{
    if (t < 0 || t >= TN_ALL || pc < 0 || pc > 11)
        return 0;
    return t < TN_FACTORY ? tn_factory[t][pc] : tn_user[t - TN_FACTORY][pc];
}

static int fine_of(int tenths)                  /* -> 1/256 semitone, rounded half away from 0 */
{
    int n = tenths * 256;
    return n >= 0 ? (n + 500) / 1000 : -((-n + 500) / 1000);
}

void tn_publish(void)                           /* the UI's state into the idle snapshot, then flip */
{
    int s = tn_sel ^ 1;
    for (int k = 0; k < 12; k++)
        tn_snap[s].fine[k] = (short)fine_of(tn_offset(tn_cur, k));
    tn_snap[s].root = (short)tn_root;
    tn_snap[s].mask = (u16)tn_mask;
    tn_sel = s;
}

static void changed(void)
{
    tn_publish();
    dirty = 1;
    dirty_at = NOW;
    smp_overlay_dirty = 1;
}

static void reset(void)                         /* 12-TET, every track off, the user slots blank */
{
    for (int u = 0; u < TN_USER; u++)
        for (int k = 0; k < 12; k++)
            tn_user[u][k] = 0;
    tn_cur = 0;
    tn_root = 0;
    tn_mask = 0;
    tn_publish();
}

/* -- the audio interrupt ------------------------------------------------------------------- */

void tn_retune(volatile u16 *f)
{
    const struct snap *s = &tn_snap[tn_sel & 1];
    if (!s->mask)
        return;
    int any = 0;
    for (u32 v = 0; v < 16; v++) {
        u32 t = VOICE_TRACK[v];
        if (t >= 16 || !(s->mask >> t & 1u))
            continue;
        /* SLICE and GRID: the note picks the slice (the DSP truncates it: a note a fraction
         * flat would play the slice below) and the sample keeps its pitch: never retuned */
        if (KIT) {
            int ty = SOUND_TYPE(t);
            if (ty == SLICE_TYPE || ty == GRID_TYPE)
                continue;
        }
        u32 w = f[FRAME_NOTE(v)];
        int pc = ((int)(w >> 8) - s->root) % 12;
        if (pc < 0)
            pc += 12;
        int d = s->fine[pc];
        if (!d)
            continue;
        int n = (int)w + d;
        f[FRAME_NOTE(v)] = (u16)(n < 0 ? 0 : n > 0x7FFF ? 0x7FFF : n);
        any = 1;
    }
    tn_frames += (u32)any;
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

static u32 sector_of(int p, int c) { return TN_AT + 2u * (u32)p + (u32)c; }

static int ready(void) { return BLK_READY && BLK_SECTORS >= TN_END; }

/* copy C of project P into rec -> its sequence, 0 none or bad */
static u32 copy_read(int p, int c)
{
    u32 s = sector_of(p, c);
    if (!ready() || s < TN_AT || s >= TN_END || BLK_READ(s, 512u, rec))
        return 0;
    tn_reads++;
    if (be32(rec) != TN_MAGIC || be32(rec + 4) != TN_VERSION || be32(rec + 8) != (u32)p
        || be32(rec + TN_CHECK_AT) != (csum(rec, TN_CHECK_AT) ^ 0x54554E45u)) {
        if (be32(rec) == TN_MAGIC)
            tn_bad++;
        return 0;
    }
    if (rec[16] >= TN_ALL || rec[17] > 11)
        return 0;
    for (int k = 0; k < TN_USER * 12; k++) {
        int v = (short)(rec[20 + 2 * k] << 8 | rec[21 + 2 * k]);
        if (v < -999 || v > 999)
            return 0;
    }
    return be32(rec + 12);
}

/* project P's newest record: applied if APPLY (else only its sequence and copy noted) -> 1 found */
static int load(int p, int apply)
{
    u32 s0 = copy_read(p, 0), s1 = 0;
    u32 best = s0;
    int c = 0;
    s1 = copy_read(p, 1);
    if (s1 > best) {
        best = s1;
        c = 1;
    }
    owner_seq = best;
    owner_copy = best ? c : 1;
    if (!best || !apply)
        return best != 0;
    if (c == 0)
        copy_read(p, 0);                       /* rec holds copy 1: the newer copy again */
    tn_cur = rec[16];
    tn_root = rec[17];
    tn_mask = (u32)rec[18] << 8 | rec[19];
    for (int u = 0; u < TN_USER; u++)
        for (int k = 0; k < 12; k++) {
            int i = 20 + 2 * (12 * u + k);
            tn_user[u][k] = (short)(rec[i] << 8 | rec[i + 1]);
        }
    tn_publish();
    return 1;
}

static int store(int p)                         /* the state as project P's, into its older copy */
{
    if (p < 0 || p > 127 || smp_er_lock || !ready())
        return -1;
    for (u32 k = 0; k < 512u; k++)
        rec[k] = 0;
    put32(rec, TN_MAGIC);
    put32(rec + 4, TN_VERSION);
    put32(rec + 8, (u32)p);
    put32(rec + 12, owner_seq + 1u);
    rec[16] = (u8)tn_cur;
    rec[17] = (u8)tn_root;
    rec[18] = (u8)(tn_mask >> 8);
    rec[19] = (u8)tn_mask;
    for (int u = 0; u < TN_USER; u++)
        for (int k = 0; k < 12; k++) {
            int i = 20 + 2 * (12 * u + k);
            rec[i] = (u8)((u16)tn_user[u][k] >> 8);
            rec[i + 1] = (u8)tn_user[u][k];
        }
    put32(rec + TN_CHECK_AT, csum(rec, TN_CHECK_AT) ^ 0x54554E45u);
    int c = owner_copy ^ 1;
    u32 s = sector_of(p, c);
    if (s < TN_AT || s >= TN_END || BLK_WRITE(s, 512u, rec))
        return -1;
    owner_seq++;
    owner_copy = c;
    tn_writes++;
    return 0;
}

static int is_default(void)
{
    if (tn_cur || tn_root || tn_mask)
        return 0;
    for (int u = 0; u < TN_USER; u++)
        for (int k = 0; k < 12; k++)
            if (tn_user[u][k])
                return 0;
    return 1;
}

static int active(void)
{
    int a = ACTIVE_PROJECT;
    return a >= 0 && a < 128 ? a : -1;
}

/* the UI loop (rec_poll): follow the project, write a change once it has settled */
void tn_poll(void)
{
    if (!ready())
        return;
    if (tn_owner == -2) {                       /* power-on: the active project's tuning */
        seen_loads = smp_pj_loads;
        seen_news = smp_pj_news;
        tn_owner = active();
        reset();
        if (tn_owner >= 0)
            load(tn_owner, 1);
        smp_overlay_dirty = 1;
        return;
    }
    u32 L = smp_pj_loads, N = smp_pj_news;
    if (L != seen_loads || N != seen_news) {
        seen_loads = L;
        seen_news = N;
        if (dirty && tn_owner >= 0)
            store(tn_owner);                    /* the old project's last change */
        dirty = 0;
        int isnew = smp_pj_last == 2;
        int s = isnew ? smp_pj_newslot : smp_pj_slot;
        tn_owner = s >= 0 && s < 128 ? s : -1;
        reset();
        if (tn_owner >= 0) {
            int found = load(tn_owner, !isnew); /* a NEW: its old record's sequence only, */
            if (isnew && found) {               /* and that record replaced by 12-TET */
                tn_publish();
                dirty = 1;
                dirty_at = NOW;
            }
        }
        tn_ui = 0;
        smp_overlay_dirty = 1;
        return;
    }
    int act = active();
    if (act != tn_owner) {                      /* SAVE AS, a slot taken: the tuning goes with it */
        tn_owner = act;
        /* written only if there is something to keep, or an old record there to replace (a
         * project that never had a tuning writes nothing: the other gates' write bounds hold) */
        if (act >= 0 && (load(act, 0) || !is_default())) {
            dirty = 1;
            dirty_at = NOW;
        }
    }
    if (dirty && tn_owner >= 0 && NOW - dirty_at > 3000u && !rec_running()) {
        if (store(tn_owner) == 0)
            dirty = 0;
        else
            dirty_at = NOW;                     /* try again later */
    }
}

/* -- the screens --------------------------------------------------------------------------- */

static int ram_ok(u32 a) { return a >= 0x44000000u && a < 0x48000000u && !(a & 1u); }

int tn_kb_up(void)                              /* KB SETUP is the screen's top view */
{
    extern void *wr_screen_obj;
    u32 s = (u32)wr_screen_obj;
    if (!ram_ok(s))
        return 0;
    u32 node = *(volatile u32 *)(s + 28);
    if (!ram_ok(node) || node == s + 20)
        return 0;
    u32 v = *(volatile u32 *)(node + 8);
    return ram_ok(v) && *(volatile u32 *)v == KB_VT;
}

int tn_visible(void) { return tn_ui != 0; }

static const char *const notes[12] = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"};
static const char *const ushort[TN_USER] = {"USER1", "USER2", "USER3", "USER4", "USER5", "USER6", "USER7", "USER8"};
static const char *const ulong[TN_USER] = {"USER 1", "USER 2", "USER 3", "USER 4", "USER 5", "USER 6", "USER 7", "USER 8"};

static const char *short_of(int t) { return t < TN_FACTORY ? tn_short[t] : ushort[t - TN_FACTORY]; }
static const char *long_of(int t) { return t < TN_FACTORY ? tn_long[t] : ulong[t - TN_FACTORY]; }

static void clear(void *c, int x0, int y0, int x1, int y1)
{
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++)
            SET_PIXEL(c, x, y, 0);
}

static void box(void *c, int x0, int y0, int x1, int y1, int filled)
{
    for (int y = y0; y <= y1; y++)
        for (int x = x0; x <= x1; x++)
            if (filled || y == y0 || y == y1 || x == x0 || x == x1)
                SET_PIXEL(c, x, y, 1);
}

/* what KB SETUP's H shows for this track: OFF, or the project's tuning */
static int h_value(void)
{
    int t = UI_TRACK & 15;
    return tn_mask >> t & 1u ? tn_cur : -1;
}

/* KB SETUP's H slot (wr_screen, after stock drew the page) */
void tn_kb_draw(void *c)
{
    if (!tn_kb_up() || tn_ui)
        return;
    clear(c, TN_HX0, TN_HY0, TN_HX1, TN_HY1);
    int v = h_value();
    LABEL(c, (TN_HX0 + TN_HX1) / 2, TN_HLABEL_Y, "%s", "TUNE");
    TEXT(c, FONT, (TN_HX0 + TN_HX1) / 2, TN_HVALUE_Y, CENTRED, "%s", v < 0 ? "OFF" : short_of(v));
    LABEL(c, (TN_HX0 + TN_HX1) / 2, TN_HKEY_Y, "%s", "(H)");
}

static void cents_text(char *o, int tenths)     /* "+12.3" */
{
    int a = tenths < 0 ? -tenths : tenths;
    o[0] = tenths < 0 ? '-' : '+';
    int i = 1;
    if (a >= 100)
        o[i++] = (char)('0' + a / 100);
    o[i++] = (char)('0' + a / 10 % 10);
    o[i++] = '.';
    o[i++] = (char)('0' + a % 10);
    o[i] = 0;
}

void tn_draw(void *c)
{
    clear(c, 0, 0, 127, 63);
    if (tn_ui == 1) {
        LABEL(c, 64, TN_TITLE_Y, "%s", "TUNING");
        TEXT(c, FONT, 64, TN_NAME_Y, CENTRED, "%s  ROOT %s", long_of(tn_cur), notes[tn_root]);
        for (int t = 0; t < 16; t++) {         /* the tracks: filled tuned, the active one marked */
            int x0 = 1 + 8 * t, x1 = x0 + 5;
            box(c, x0, TN_TRK_Y0, x1, TN_TRK_Y1, (int)(tn_mask >> t & 1u));
            if (t == (UI_TRACK & 15))
                box(c, x0, TN_MARK_Y, x1, TN_MARK_Y, 1);
        }
        int on = (int)(tn_mask >> (UI_TRACK & 15) & 1u), n = 0;
        for (int t = 0; t < 16; t++)
            n += (int)(tn_mask >> t & 1u);
        static const char *const lab[4] = {"TUNE", "ROOT", "TRK", "ALL"};
        for (int k = 0; k < 4; k++)
            LABEL(c, 16 + 32 * k, TN_KLABEL_Y, "%s", lab[k]);
        TEXT(c, FONT, 16, TN_KVALUE_Y, CENTRED, "%s", short_of(tn_cur));
        TEXT(c, FONT, 48, TN_KVALUE_Y, CENTRED, "%s", notes[tn_root]);
        TEXT(c, FONT, 80, TN_KVALUE_Y, CENTRED, "%s", on ? "ON" : "OFF");
        TEXT(c, FONT, 112, TN_KVALUE_Y, CENTRED, "%d", n);
        return;
    }
    /* EDIT: the 12 notes above ROOT, the picked one's cents */
    int u = tn_cur - TN_FACTORY;
    LABEL(c, 64, TN_TITLE_Y, "EDIT %s", ulong[u < 0 ? 0 : u]);
    char cs[8];
    cents_text(cs, tn_offset(tn_cur, tn_note));
    TEXT(c, FONT, 64, TN_NAME_Y, CENTRED, "%s  %s CENT", notes[(tn_root + tn_note) % 12], cs);
    for (int k = 0; k < 12; k++) {             /* each note's offset as a bar from the middle */
        int x0 = 4 + 10 * k, x1 = x0 + 6;
        int o = tn_offset(tn_cur, k);          /* +-99.9 cent: +-12 pixels, any offset at least 1 */
        int h = o / 83;
        if (!h && o)
            h = o > 0 ? 1 : -1;
        int mid = (TN_BAR_Y0 + TN_BAR_Y1) / 2;
        box(c, x0, mid, x1, mid, 1);
        if (h > 0)
            box(c, x0 + 2, mid, x1 - 2, mid + h, 1);
        else if (h < 0)
            box(c, x0 + 2, mid + h, x1 - 2, mid, 1);
        if (k == tn_note)
            box(c, x0, TN_BAR_Y0, x1, TN_BAR_Y0, 1);
    }
    static const char *const lab[4] = {"NOTE", "CENT", ".1CT", "FROM"};
    for (int k = 0; k < 4; k++)
        LABEL(c, 16 + 32 * k, TN_KLABEL_Y, "%s", lab[k]);
    TEXT(c, FONT, 16, TN_KVALUE_Y, CENTRED, "%s", notes[(tn_root + tn_note) % 12]);
    TEXT(c, FONT, 48, TN_KVALUE_Y, CENTRED, "%s", cs);
    TEXT(c, FONT, 112, TN_KVALUE_Y, CENTRED, "%s", short_of(tn_from));
}

/* -- the keys and knobs (smp_ui_pop, before stock and our other screens) ------------------- */

static u32 eaten D = 0;                         /* keys whose press we took: their release too */
static int h_acc D = 0;

static void set_tune(int t) { tn_cur = clamp(t, 0, TN_ALL - 1); }

static void knob(int k, int d)
{
    int tr = UI_TRACK & 15;
    if (tn_ui == 1) {
        if (k == 1)
            set_tune(tn_cur + d);
        else if (k == 2)
            tn_root = clamp(tn_root + d, 0, 11);
        else if (k == 3)
            tn_mask = d > 0 ? tn_mask | 1u << tr : tn_mask & ~(1u << tr);
        else if (k == 4)
            tn_mask = d > 0 ? 0xFFFFu : 0;
        else
            return;
    } else {
        if (tn_cur < TN_FACTORY)
            return;
        short *o = &tn_user[tn_cur - TN_FACTORY][0];
        if (k == 1)
            tn_note = clamp(tn_note + d, 0, 11);
        else if (k == 2)
            o[tn_note] = (short)clamp(o[tn_note] + 10 * d, -999, 999);
        else if (k == 3)
            o[tn_note] = (short)clamp(o[tn_note] + d, -999, 999);
        else if (k == 4)
            tn_from = clamp(tn_from + d, 0, TN_ALL - 1);
        else
            return;
    }
    changed();
}

/* KB SETUP's H turned: this track OFF or tuned with the next tuning (12-TET is OFF's place) */
static void h_turn(int d)
{
    h_acc += d;
    if (h_acc > -2 && h_acc < 2)                /* two detents a step, as stock's lists */
        return;
    int step = h_acc > 0 ? 1 : -1;
    h_acc = 0;
    int t = UI_TRACK & 15;
    int v = h_value();                          /* -1 off, else 1..TN_ALL-1 (0 reads as off) */
    if (v == 0)
        v = -1;
    int pos = v < 0 ? 0 : v;                    /* 0 OFF, 1.. the tunings past 12-TET */
    pos = clamp(pos + step, 0, TN_ALL - 1);
    if (pos == 0)
        tn_mask &= ~(1u << t);
    else {
        tn_cur = pos;
        tn_mask |= 1u << t;
    }
    changed();
}

u32 tn_opens D = 0;

int tn_pop(u8 *it)                              /* 1: the item was ours (the caller drops it) */
{
    u32 code = (u32)it[4] << 24 | (u32)it[5] << 16 | (u32)it[6] << 8 | it[7];
    u32 flags = (u32)it[8] << 24 | (u32)it[9] << 16 | (u32)it[10] << 8 | it[11];
    int down = (flags & F_PRESS) && !(flags & F_RELEASE);
    if (it[0] == IT_KEY && code < 32 && code != K_FUNC && (eaten >> code & 1u)) {
        if (!down)
            eaten &= ~(1u << code);
        return 1;                               /* a key we took: its repeat and release too */
    }
    if (it[0] == IT_KEY && code == K_ENC_H) {   /* (48: past eaten's 32 bits, tracked apart) */
        static int h_down D = 0;
        if (down && !(flags & F_REPEAT) && !tn_ui && tn_kb_up()) {
            tn_ui = 1;
            tn_opens++;
            h_down = 1;
            smp_overlay_dirty = 1;
            return 1;
        }
        if (h_down) {
            if (!down)
                h_down = 0;
            return 1;
        }
        return tn_ui != 0;
    }
    if (!tn_ui) {
        if (it[0] == IT_KNOB && code == 8 && tn_kb_up()) {
            h_turn((signed char)it[8]);
            return 1;
        }
        return 0;
    }
    /* TUNING or EDIT is up */
    if (it[0] == IT_KEY && down && code >= 1 && code <= 8) {
        tn_ui = 0;                              /* a page or menu key: stock's, and ours closes */
        smp_overlay_dirty = 1;
        return 0;
    }
    if (it[0] == IT_KNOB) {
        if (code >= 1 && code <= 4) {
            knob((int)code, (signed char)it[8]);
            return 1;
        }
        return 1;                               /* E..H: nothing under our screen */
    }
    if (it[0] != IT_KEY || code == K_FUNC)
        return 0;
    if (code == K_YES || code == K_NO || (code >= K_UP && code <= K_RIGHT) || (code >= 41 && code <= 47)) {
        if (down && !(flags & F_REPEAT)) {
            if (code < 32)
                eaten |= 1u << code;
            if (code == K_NO)
                tn_ui = tn_ui == 2 ? 1 : 0;
            else if (code == K_YES && tn_ui == 1 && tn_cur >= TN_FACTORY) {
                tn_ui = 2;
                tn_note = 0;
            } else if (code == K_YES && tn_ui == 2 && smp_func_held && tn_cur >= TN_FACTORY) {
                for (int k = 0; k < 12; k++)    /* FUNC + YES: FROM's offsets into this slot */
                    tn_user[tn_cur - TN_FACTORY][k] = (short)tn_offset(tn_from, k);
                changed();
            } else if (tn_ui == 2 && (code == K_LEFT || code == K_RIGHT))
                tn_note = clamp(tn_note + (code == K_RIGHT ? 1 : -1), 0, 11);
            smp_overlay_dirty = 1;
        }
        return 1;
    }
    return 0;                                   /* the [TRIG] keys, the keyboard: stock plays them */
}

/* the gate's: set the state directly (tuning, root, mask) and publish it */
void tn_set(int t, int root, int mask)
{
    tn_cur = clamp(t, 0, TN_ALL - 1);
    tn_root = clamp(root, 0, 11);
    tn_mask = (u32)mask & 0xFFFFu;
    changed();
}
