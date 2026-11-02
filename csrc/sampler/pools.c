/* v0.38: per-project sample pools (docs/project-pools.md; the research and the owner's four
 * decisions: docs/project-pools-research.md).
 *
 * The pool image (link.c, sectors 0x600000..) stays what it was: the DSP's pool byte for
 * byte, a shared heap of frames. What is new is a LIST per project: which samples sit in
 * which of its 128 slots -- a copy of the image's directory page (entries, short names, the
 * meta pointer), its meta block (long names, folders) and its slice tables. A LOAD makes
 * the loaded project's list the image's directory and sends the DSP what it needs.
 *
 *   0x6D0000, 0x6D0001   the superblock, two copies written in turn ('DN2J')
 *   0x6D0100 + 256 x (2p + c)   list p (0..127 the projects, 128 the LEGACY list: the pool
 *                        of every project made before this feature), copy c (0, 1):
 *                          +0 header ('DN2K', version, p, sequence, generation, flags,
 *                             the checks of each part, its own check), written LAST
 *                          +1 the slots' sums (128 x u32, 0: not known)
 *                          +2..+9 the directory page (4 KB)
 *                          +10..+25 the meta block (8 KB), if the list has one
 *                          +26..+217 the slice area (96 KB), if any slot has a table there
 *   .. 0x6E02FF          the lists' end; 0x6E0300..0x6FFFFF free
 *
 * All of it is above the pool image's last sector (0x6C8000) and below the library
 * (0x700000), checked before every read and write (pl_in).
 *
 * Power loss: a list is written into its OLDER copy, parts first, header last; a reader
 * takes the copy with the higher sequence whose header and every part check out, so a list
 * cut half way leaves the previous one in force. The superblock likewise. A frame extent
 * that any list names is never given to a new sample or recording (smp_pl_clash), so a
 * switch never loses one; and each slot's sum (link.c, of its frames as the loader read
 * them) is checked when a list is loaded again: frames that changed behind our back (an
 * older build after a downgrade) play as silence, never as a wrong sample.
 *
 * Nothing here writes anything but its RAM (SMP_MIRROR + 0x140000 .. + 0x214000) and the
 * region above; the pool image only through link.c's bounded image_write. */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define D_ __attribute__((section(".data")))

#if !defined(SMP_MIRROR) || !defined(POOL_BYTES) || !defined(META_PTR) || !defined(SLICE_AREA)
#error "the sampler's constants are passed by the build (dnfw.waverider.cpage)"
#endif

#define BLK_READ  ((int (*)(u32, u32, void *))0x4012C59Au)
#define BLK_WRITE ((int (*)(u32, u32, const void *))0x4012C780u)
#define BLK_READY (*(volatile u32 *)0x4461B68Cu)
#define BLK_SECTORS (*(volatile u32 *)0x4461B6B0u)
/* the active project's slot: 0..127, -1 unsaved (docs/project-pools-research.md section 1) */
#define ACTIVE_PROJECT (*(volatile signed char *)0x405CD899u)

#define POOL_STORE_END (0x600000u + 1u + POOL_BYTES / 512u)   /* link.c's image ends below */
#define LIB_SECTOR 0x700000u                                   /* lib.c's library */
#define PL_SB 0x6D0000u
#define PL_LISTS 0x6D0100u
#define PL_SPAN 256u
#define PL_N 129
#define PL_LEGACY 128
#define PL_END (PL_LISTS + 2u * (u32)PL_N * PL_SPAN)
_Static_assert(PL_SB >= POOL_STORE_END, "the lists lie above the pool image");
_Static_assert(PL_END <= LIB_SECTOR, "the lists lie below the library");
#define JUMP_SETTINGS 0x6FF000u                                /* Direct Jump's settings sector ('DN2S') */
_Static_assert(PL_END <= JUMP_SETTINGS, "the lists lie clear of Direct Jump's settings sector");

#define DIR_BYTES DATA_OFFSET
#define META_ROOM 0x2000u
#define SLICE_TB 768u
#define SLAREA_BYTES (POOL_SLOTS * SLICE_TB)
#define L_SUMS 1u
#define L_DIR 2u
#define L_META (L_DIR + DIR_BYTES / 512u)
#define L_AREA (L_META + META_ROOM / 512u)
_Static_assert(L_AREA + SLAREA_BYTES / 512u <= PL_SPAN, "a list fits its span");
_Static_assert(META_BYTES <= META_ROOM, "the meta block fits a list");

#define SB_MAGIC 0x444E324Au                                   /* 'DN2J' */
#define L_MAGIC 0x444E324Bu                                    /* 'DN2K' */
#define PL_VERSION 1u
#define F_META 1u
#define F_AREA 2u

/* our RAM */
#define PLR (SMP_MIRROR + 0x140000u)
#define SBUF ((u32 *)PLR)
#define HBUF ((u32 *)(PLR + 0x200u))
#define LDIR(p) ((u8 *)(PLR + 0x1000u + 0x1000u * (u32)(p)))   /* each list's directory page */
#define LSUM(p) ((u32 *)(PLR + 0x82000u + 0x200u * (u32)(p)))  /* .. and its sums */
#define W_BASE (PLR + 0x93000u)                                /* a list's sectors 1.., as on the +Drive */
#define W_SUMS ((u32 *)W_BASE)
#define W_DIR ((u8 *)(W_BASE + 0x200u))
#define W_META ((u8 *)(W_BASE + 0x200u + DIR_BYTES))
#define W_AREA ((u8 *)(W_BASE + 0x200u + DIR_BYTES + META_ROOM))
#define RLO ((u32 *)(PLR + 0xB0000u))                          /* reserved extents: starts */
#define RHI ((u32 *)(PLR + 0xC1000u))                          /* .. and ends */
#define RES_MAX 0x4400u
#define EXPECT ((u32 *)(PLR + 0xD2000u))                       /* the sums this load must meet */
#define EXPECT_E(k) ((u8 *)(PLR + 0xD2200u + 16u * (u32)(k)))   /* .. for these entries */
#define LINFO ((struct linfo *)(PLR + 0xD3000u))
_Static_assert(0x93000u + 0x200u + DIR_BYTES + META_ROOM + SLAREA_BYTES <= 0xB0000u, "the staging fits");
_Static_assert(0xB0000u + RES_MAX * 4u <= 0xC1000u && 0xC1000u + RES_MAX * 4u <= 0xD2000u, "the reserved extents fit");
_Static_assert(0x140000u + 0xD4000u <= 0x220000u, "below link.c's resident spans");
_Static_assert(RES_MAX >= (u32)PL_N * (POOL_SLOTS + 1u), "every list's extents fit");

struct linfo { u8 valid, copy, flags, pad; u32 seq; u32 spare[2]; };   /* 16 B: no 8-byte index (ColdFire) */

extern int smp_dir_ok, smp_meta_ok;
extern u32 smp_hi;
extern u8 *smp_pl_dirp(void);
extern u8 *smp_pl_metap(void);
extern u8 *smp_pl_areap(void);
extern int smp_pl_image_read(u32 off, u32 bytes, void *buf);
extern int smp_pl_image_write(u32 off, u32 bytes, const void *buf);
extern int smp_pl_dir_commit(u32 bytes);
extern void smp_pl_read_image(void);
extern u32 smp_pl_slot_sum(int k);
extern void smp_pl_quiesce(void);
extern int smp_pl_idle(int force);
extern int smp_pl_list_ok(void);
extern int smp_pl_bad_any(void);
extern void smp_pl_bad_fix(void);
extern int smp_area_ok(void);
extern void smp_load(void);
extern int smp_lstate;
extern volatile u32 smp_periods;
extern int rec_busy(void);
extern int rec_running(void);

/* the hooks' counters (hooks.S): the OS's LOAD (0x40042E6E) begun, succeeded (with the slot),
 * ended; its NEW (0x400428C0, with the slot); which came last (1 LOAD, 2 NEW). Written by
 * the OS's own task, read here in the UI task. */
volatile u32 smp_pj_begins D_ = 0;
volatile u32 smp_pj_ends D_ = 0;
volatile u32 smp_pj_loads D_ = 0;
volatile u32 smp_pj_news D_ = 0;
volatile int smp_pj_slot D_ = -1;
volatile int smp_pj_newslot D_ = -1;
volatile u32 smp_pj_last D_ = 0;

int smp_pl_on D_ = 0;                   /* 0 off (one pool, as v0.37), 1 on */
int smp_pl_owner D_ = -1;               /* whose pool the image's directory is */
int smp_pl_state D_ = 0;                /* 0 idle, 1 a LOAD running, 2 a switch waiting, 3 restoring */
u32 smp_pl_writes D_ = 0;               /* sectors written, for the gate */
u32 smp_pl_switches D_ = 0;             /* switches applied */
u32 smp_pl_lists_written D_ = 0;
u32 smp_pl_events D_ = 0;               /* LOAD / NEW events taken */
int smp_pl_src D_ = -2;                 /* the last switch's source: a list, -1 empty */
int smp_pl_boot_case D_ = 0;            /* what the power-on found (docs/project-pools.md) */
u32 smp_pl_gen D_ = 0;

static u32 sb_seq D_ = 0, sb_dirsum D_ = 0, sb_tdirsum D_ = 0;
static int sb_cur D_ = -1;              /* the sector holding the newest superblock */
static int sb_pend D_ = 0, sb_pslot D_ = -1;
static int dirty D_ = 0;                /* the pool changed since its list was written */
static u32 seen_loads D_ = 0, seen_news D_ = 0;
static int sw_kind D_ = 0, sw_slot D_ = -1;
static u32 sw_since D_ = 0, end_at D_ = 0;
static int sw_blank2 D_ = 0, sw_rec D_ = 0;
static u32 res_rev D_ = 1, res_built D_ = 0;
static u32 res_n D_ = 0;
static int res_owner D_ = -2;

static u32 le32(const u8 *p) { return p[0] | p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
static void put_le32(u8 *p, u32 v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }

static u32 csum(const u8 *p, u32 n)            /* link.c's checksum (the image header's) */
{
    u32 a = 1, b = 0;
    for (u32 k = 0; k < n; k++) {
        a += p[k];
        b += a;
    }
    return b << 16 ^ a;
}

static void copy(u8 *d, const u8 *s, u32 n) { for (u32 k = 0; k < n; k++) d[k] = s[k]; }
static void zero(u8 *d, u32 n) { for (u32 k = 0; k < n; k++) d[k] = 0; }

/* -- the region, bounded --------------------------------------------------------------- */

static int pl_in(u32 sector, u32 bytes)
{
    u32 n = bytes / 512u;
    return BLK_READY && bytes && !(bytes & 511u) && sector >= PL_SB && sector < PL_END
           && n <= PL_END - sector && BLK_SECTORS >= PL_END;
}

static int pl_rd(u32 sector, u32 bytes, void *buf)
{
    return pl_in(sector, bytes) ? BLK_READ(sector, bytes, buf) : -1;
}

static int pl_wr(u32 sector, u32 bytes, const void *buf)
{
    if (!pl_in(sector, bytes))
        return -1;
    smp_pl_writes += bytes / 512u;
    return BLK_WRITE(sector, bytes, buf);
}

static u32 list_sector(int p, int c) { return PL_LISTS + PL_SPAN * (2u * (u32)p + (u32)c); }

static int active(void)
{
    int a = ACTIVE_PROJECT;
    return a >= 0 && a < 128 ? a : -1;
}

/* -- the superblock ---------------------------------------------------------------------- */

static u32 sb_check(const u32 *s) { return csum((const u8 *)s, 40) ^ 0x504C5342u; }

static int sb_load(void)                       /* -> 1 found, 0 none, -1 the device refused */
{
    int best = -1;
    u32 bseq = 0;
    for (int c = 0; c < 2; c++) {
        if (pl_rd(PL_SB + (u32)c, 512u, SBUF) != 0)
            return -1;
        if (SBUF[0] != SB_MAGIC || SBUF[1] != PL_VERSION || SBUF[10] != sb_check(SBUF))
            continue;
        if (best < 0 || SBUF[2] > bseq) {
            best = c;
            bseq = SBUF[2];
        }
    }
    if (best < 0)
        return 0;
    if (pl_rd(PL_SB + (u32)best, 512u, SBUF) != 0)
        return -1;
    sb_cur = best;
    sb_seq = SBUF[2];
    smp_pl_gen = SBUF[3];
    smp_pl_owner = (int)SBUF[4];
    if (smp_pl_owner < -1 || smp_pl_owner > 127)
        smp_pl_owner = -1;
    sb_pend = (int)SBUF[5];
    sb_pslot = (int)SBUF[6];
    sb_dirsum = SBUF[7];
    sb_tdirsum = SBUF[8];
    return 1;
}

/* into the older copy; the newer stays until this one is whole */
static int sb_store(void)
{
    for (int k = 0; k < 128; k++)
        SBUF[k] = 0;
    SBUF[0] = SB_MAGIC;
    SBUF[1] = PL_VERSION;
    SBUF[2] = sb_seq + 1u;
    SBUF[3] = smp_pl_gen;
    SBUF[4] = (u32)smp_pl_owner;
    SBUF[5] = (u32)sb_pend;
    SBUF[6] = (u32)sb_pslot;
    SBUF[7] = sb_dirsum;
    SBUF[8] = sb_tdirsum;
    SBUF[9] = 0;
    SBUF[10] = sb_check(SBUF);
    int c = sb_cur == 0 ? 1 : 0;
    if (pl_wr(PL_SB + (u32)c, 512u, SBUF) != 0)
        return -1;
    sb_cur = c;
    sb_seq++;
    return 0;
}

/* -- the lists --------------------------------------------------------------------------- */

static u32 h_check(const u32 *h) { return csum((const u8 *)h, 44) ^ 0x504C4B31u; }

static int h_ok(const u32 *h, int p)
{
    return h[0] == L_MAGIC && h[1] == PL_VERSION && h[2] == (u32)p && h[4] == smp_pl_gen
           && h[11] == h_check(h);
}

/* list P's copy C into W_*: its header in HBUF, every part checked -> 0 */
static int copy_read(int p, int c)
{
    u32 s = list_sector(p, c);
    if (pl_rd(s, 512u, HBUF) != 0 || !h_ok(HBUF, p))
        return -1;
    u32 fl = HBUF[5];
    if (pl_rd(s + L_SUMS, 512u + DIR_BYTES, (void *)W_BASE) != 0
        || csum((const u8 *)W_SUMS, 512u) != HBUF[6] || csum(W_DIR, DIR_BYTES) != HBUF[7]
        || le32(W_DIR) != POOL_MAGIC)
        return -1;
    if (fl & F_META) {
        if (pl_rd(s + L_META, META_ROOM, W_META) != 0 || csum(W_META, META_ROOM) != HBUF[8])
            return -1;
    }
    if (fl & F_AREA) {
        if (pl_rd(s + L_AREA, SLAREA_BYTES, W_AREA) != 0 || csum(W_AREA, SLAREA_BYTES) != HBUF[9])
            return -1;
    }
    return 0;
}

/* the newest whole copy of list P into W_* (and the cache) -> 0; -1 none */
static int list_read(int p)
{
    u32 hs[2] = {0, 0};
    int ok[2] = {0, 0};
    for (int c = 0; c < 2; c++)
        if (pl_rd(list_sector(p, c), 512u, HBUF) == 0 && h_ok(HBUF, p)) {
            ok[c] = 1;
            hs[c] = HBUF[3];
        }
    struct linfo *li = &LINFO[p];
    u32 top = hs[0] > hs[1] ? hs[0] : hs[1];
    int first = ok[1] && (!ok[0] || hs[1] > hs[0]) ? 1 : 0;   /* the newer header first */
    for (int t = 0; t < 2; t++) {
        int c = t == 0 ? first : 1 - first;
        if (!ok[c] || copy_read(p, c) != 0)
            continue;
        li->valid = 1;
        li->copy = (u8)c;
        li->flags = (u8)HBUF[5];
        li->seq = top;                          /* the next write goes past both */
        copy(LDIR(p), W_DIR, DIR_BYTES);
        copy((u8 *)LSUM(p), (const u8 *)W_SUMS, 512u);
        res_rev++;
        return 0;
    }
    li->valid = 0;
    li->seq = top;
    res_rev++;
    return -1;
}

static void empty_dir(u8 *d)
{
    zero(d, DIR_BYTES);
    put_le32(d, POOL_MAGIC);
}

/* W_* := the pool as it is now (the image's directory, meta block and slice area) ->
 * its flags, or -1 */
static int snapshot(void)
{
    u8 *dir = smp_pl_dirp();
    int fl = 0;
    if (!smp_dir_ok || !smp_hi || le32(dir) != POOL_MAGIC) {
        empty_dir(W_DIR);
        for (int k = 0; k < 128; k++)
            W_SUMS[k] = 0;
        return 0;
    }
    copy(W_DIR, dir, DIR_BYTES);
    for (int k = 0; k < 128; k++)
        W_SUMS[k] = k < POOL_SLOTS ? smp_pl_slot_sum(k) : 0;
    if (smp_meta_ok && le32(dir + META_PTR) == META_PTR_MAGIC) {
        copy(W_META, smp_pl_metap(), META_ROOM);
        fl |= F_META;
    }
    int area = 0;
    for (u32 k = 0; k < POOL_SLOTS; k++)
        if (dir[8 + 16 * k + 14] & 1)
            area = 1;
    if (area && smp_area_ok()) {
        /* the +Drive's slice area (link.c writes a table there before its entry's
         * directory: no edit is pending while a list is written, smp_pl_list_ok) */
        if (smp_pl_image_read(SLICE_AREA, SLAREA_BYTES, W_AREA) != 0)
            return -1;
        fl |= F_AREA;
    }
    return fl;
}

/* W_* (with FL) as list P: into its older copy, the parts, then the header -> 0 */
static int list_write(int p, int fl)
{
    if (p < 0 || p >= PL_N || fl < 0)
        return -1;
    struct linfo *li = &LINFO[p];
    int c = li->valid ? 1 - li->copy : 0;
    u32 s = list_sector(p, c), seq = li->seq + 1u;
    u32 *h = HBUF;
    for (int k = 0; k < 128; k++)
        h[k] = 0;
    h[0] = L_MAGIC;
    h[1] = PL_VERSION;
    h[2] = (u32)p;
    h[3] = seq;
    h[4] = smp_pl_gen;
    h[5] = (u32)fl;
    h[6] = csum((const u8 *)W_SUMS, 512u);
    h[7] = csum(W_DIR, DIR_BYTES);
    h[8] = fl & F_META ? csum(W_META, META_ROOM) : 0;
    h[9] = fl & F_AREA ? csum(W_AREA, SLAREA_BYTES) : 0;
    h[10] = META_ROOM;
    h[11] = h_check(h);
    if (pl_wr(s + L_SUMS, 512u + DIR_BYTES, (const void *)W_BASE) != 0
        || ((fl & F_META) && pl_wr(s + L_META, META_ROOM, W_META) != 0)
        || ((fl & F_AREA) && pl_wr(s + L_AREA, SLAREA_BYTES, W_AREA) != 0)
        || pl_wr(s, 512u, h) != 0) {
        li->seq = seq;                          /* that copy is not to be trusted now */
        if (li->valid && li->copy == (u8)c)
            li->valid = 0;
        return -1;
    }
    li->valid = 1;
    li->copy = (u8)c;
    li->flags = (u8)fl;
    li->seq = seq;
    copy(LDIR(p), W_DIR, DIR_BYTES);
    copy((u8 *)LSUM(p), (const u8 *)W_SUMS, 512u);
    res_rev++;
    smp_pl_lists_written++;
    return 0;
}

/* -- extents no new sample may take ------------------------------------------------------- */

static void res_add(u32 lo, u32 hi)
{
    if (hi > lo && res_n < RES_MAX) {
        RLO[res_n] = lo;
        RHI[res_n] = hi;
        res_n++;
    }
}

/* every frame extent and meta block a list other than the owner's names (the owner's pool is
 * the image's directory, which link.c's own checks already keep), sorted and merged */
static void res_build(void)
{
    res_n = 0;
    for (int p = 0; p < PL_N; p++) {
        if (!LINFO[p].valid || p == smp_pl_owner)
            continue;
        const u8 *d = LDIR(p);
        for (u32 k = 0; k < POOL_SLOTS; k++) {
            const u8 *e = d + 8 + 16 * k;
            u32 addr = le32(e), fr = le32(e + 4), fmt = e[12];
            if (addr < SMP_POOL_DDR + DATA_OFFSET || !fr)
                continue;
            u32 lo = addr - SMP_POOL_DDR, n = fr * (fmt ? 2u : 4u);
            u32 ns = e[13] > 64 ? 64u : e[13];
            if (ns && !(e[14] & 1))
                n = (((lo + n + 3u) & ~3u) - lo) + 12u * ns;
            res_add(lo & ~511u, (lo + n + 511u) & ~511u);
        }
        if (le32(d + META_PTR) == META_PTR_MAGIC) {
            u32 mo = le32(d + META_PTR + 4), mn = le32(d + META_PTR + 8);
            if (mn <= META_ROOM)
                res_add(mo & ~511u, (mo + mn + 511u) & ~511u);
        }
    }
    /* shell sort by lo, then merge */
    for (u32 gap = res_n / 2u; gap > 0; gap /= 2u)
        for (u32 i = gap; i < res_n; i++) {
            u32 lo = RLO[i], hi = RHI[i], j = i;
            while (j >= gap && RLO[(j - gap)] > lo) {
                RLO[j] = RLO[(j - gap)];
                RHI[j] = RHI[(j - gap)];
                j -= gap;
            }
            RLO[j] = lo;
            RHI[j] = hi;
        }
    u32 m = 0;
    for (u32 i = 0; i < res_n; i++) {
        if (m && RLO[i] <= RHI[(m - 1)]) {
            if (RHI[i] > RHI[(m - 1)])
                RHI[(m - 1)] = RHI[i];
            continue;
        }
        RLO[m] = RLO[i];
        RHI[m] = RHI[i];
        m++;
    }
    res_n = m;
    res_built = res_rev;
    res_owner = smp_pl_owner;
}

static void res_fresh(void)
{
    if (res_built != res_rev || res_owner != smp_pl_owner)
        res_build();
}

/* [LO, HI) of the pool (byte offsets) against every other list's extents -> the end of the
 * first reserved extent it meets (all free up to the next), 0: none */
u32 smp_pl_clash(u32 lo, u32 hi)
{
    if (!smp_pl_on || hi <= lo)
        return 0;
    res_fresh();
    u32 a = 0, b = res_n;                       /* the first extent whose end is past LO */
    while (a < b) {
        u32 m = (a + b) / 2u;
        if (RHI[m] <= lo)
            a = m + 1;
        else
            b = m;
    }
    return a < res_n && RLO[a] < hi ? RHI[a] : 0;
}

/* the first reserved extent starting at or after AT -> its start, 0xFFFFFFFF none */
u32 smp_pl_next(u32 at)
{
    if (!smp_pl_on)
        return 0xFFFFFFFFu;
    res_fresh();
    for (u32 i = 0; i < res_n; i++)
        if (RLO[i] >= at)
            return RLO[i];
    return 0xFFFFFFFFu;
}

int smp_pl_res_count(void) { if (!smp_pl_on) return 0; res_fresh(); return (int)res_n; }
u32 smp_pl_res_end(int i) { return i >= 0 && (u32)i < res_n ? RHI[i] : 0; }

/* the sum the loader must find for slot K's frames, whose entry is E: what the list it came
 * from recorded for that very entry; 0: none asked (another entry, or not known) */
u32 smp_pl_expect(int k, const u8 *e)
{
    if (!smp_pl_on || k < 0 || k >= POOL_SLOTS || !EXPECT[k])
        return 0;
    const u8 *x = EXPECT_E(k);
    for (int j = 0; j < 16; j++)
        if (x[j] != e[j])
            return 0;
    return EXPECT[k];
}

static void expect_clear(void)
{
    for (int k = 0; k < POOL_SLOTS; k++)
        EXPECT[k] = 0;
}

int smp_pl_busy(void) { return smp_pl_on && smp_pl_state != 0; }

/* -- a switch ----------------------------------------------------------------------------- */

/* the end of the directory's extents: the image header's bytes */
static u32 dir_extent_end(const u8 *d)
{
    u32 top = DIR_BYTES;
    for (u32 k = 0; k < POOL_SLOTS; k++) {
        const u8 *e = d + 8 + 16 * k;
        u32 addr = le32(e), fr = le32(e + 4);
        if (addr < SMP_POOL_DDR + DATA_OFFSET || !fr)
            continue;
        u32 end = addr - SMP_POOL_DDR + fr * (e[12] ? 2u : 4u) + 12u * 64u;
        if (end > top && end <= POOL_BYTES)
            top = end;
    }
    if (le32(d + META_PTR) == META_PTR_MAGIC) {
        u32 end = le32(d + META_PTR + 4) + le32(d + META_PTR + 8);
        if (end > top && end <= POOL_BYTES)
            top = end;
    }
    return (top + 511u) & ~511u;
}

static int meta_place_ok(const u8 *d)
{
    u32 off = le32(d + META_PTR + 4), n = le32(d + META_PTR + 8);
    n = (n + 511u) & ~511u;
    return le32(d + META_PTR) == META_PTR_MAGIC && n && n <= META_ROOM && !(off & 511u)
           && off >= DATA_OFFSET && off + n <= POOL_BYTES && !(off < REC_END && off + n > REC_OFFSET)
           && !(off < SLICE_AREA + SLAREA_BYTES && off + n > TABLE_AREA);
}

/* the pool becomes project SLOT's: KIND 1 its list (or the legacy one, if it has none), 2 an
 * empty pool (NEW). The image's directory, meta block and slice area are rewritten, the
 * superblock names the new owner, and the loader sends the DSP what the new pool needs (the
 * kit's samples first; a sample already in the DSP's memory costs nothing). -> 0 */
static int apply(int kind, int slot)
{
    int src = -1;
    if (kind == 1) {
        if (slot >= 0 && LINFO[slot].valid && list_read(slot) == 0)
            src = slot;
        else if (LINFO[PL_LEGACY].valid && list_read(PL_LEGACY) == 0)
            src = PL_LEGACY;
    }
    int fl = 0;
    if (src < 0) {
        empty_dir(W_DIR);
        for (int k = 0; k < 128; k++)
            W_SUMS[k] = 0;
    } else {
        fl = LINFO[src].flags;
    }
    /* the switch's intent first: a power cut from here on finishes it at the next power-on
     * (or puts the old pool back, if the OS did not keep the new project) */
    sb_pend = kind;
    sb_pslot = slot;
    sb_tdirsum = csum(W_DIR, DIR_BYTES);
    if (sb_store() != 0)
        return -1;
    u8 *dir = smp_pl_dirp();
    copy(dir, W_DIR, DIR_BYTES);
    smp_dir_ok = 1;
    for (int k = 0; k < POOL_SLOTS; k++) {
        EXPECT[k] = W_SUMS[k];
        copy(EXPECT_E(k), dir + 8 + 16 * (u32)k, 16);
    }
    if ((fl & F_META) && meta_place_ok(dir)) {
        copy(smp_pl_metap(), W_META, META_ROOM);
        u32 n = (le32(dir + META_PTR + 8) + 511u) & ~511u;
        smp_pl_image_write(le32(dir + META_PTR + 4), n, W_META);
    }
    if ((fl & F_AREA) && smp_area_ok()) {
        copy(smp_pl_areap(), W_AREA, SLAREA_BYTES);
        smp_pl_image_write(SLICE_AREA, SLAREA_BYTES, W_AREA);
    }
    u32 hi = dir_extent_end(dir);
    if (hi < smp_hi)
        hi = smp_hi;
    if (smp_pl_dir_commit(hi) != 0)
        return -1;
    /* a NEW project's empty pool is its own at once (the owner's decision 1): a LOAD of it
     * later gives it back, not the legacy pool */
    if (kind == 2 && slot >= 0) {
        empty_dir(W_DIR);
        for (int k = 0; k < 128; k++)
            W_SUMS[k] = 0;
        list_write(slot, 0);
    }
    smp_pl_owner = slot;
    sb_pend = 0;
    sb_pslot = -1;
    sb_dirsum = csum(dir, DIR_BYTES);
    sb_store();
    smp_pl_src = src;
    smp_pl_switches++;
    dirty = 0;
    res_rev++;
    smp_load();
    return 0;
}

/* the owner's list := the pool as it is (the owner's decision 2: at once) */
static int write_owner(void)
{
    if (smp_pl_owner >= 0) {
        int fl = snapshot();
        if (fl < 0 || list_write(smp_pl_owner, fl) != 0)
            return -1;
    }
    sb_dirsum = smp_dir_ok && smp_hi ? csum(smp_pl_dirp(), DIR_BYTES) : 0;
    sb_store();
    dirty = 0;
    return 0;
}

/* from link.c when it has written the image's directory (an edit, a recording kept) */
void smp_pl_changed(void)
{
    if (smp_pl_on)
        dirty = 1;
}

/* -- power-on ------------------------------------------------------------------------------- */

/* link.c's smp_boot, once the library is read and before the pool loads. -> 1 if it has
 * started the load itself (a switch), 0: smp_boot loads the image as it is */
int smp_pl_boot(void)
{
    smp_pl_on = 0;
    smp_pl_state = 0;
    res_n = 0;
    res_rev++;
    expect_clear();
    for (int p = 0; p < PL_N; p++) {
        LINFO[p].valid = 0;
        LINFO[p].seq = 0;
    }
    if (!BLK_READY || BLK_SECTORS < PL_END)
        return 0;                               /* no room for the lists: one pool, as before */
    smp_pl_read_image();                        /* the image's directory and meta, as they are */
    u8 *dir = smp_pl_dirp();
    u32 imgsum = smp_dir_ok ? csum(dir, DIR_BYTES) : 0;
    int act = active();
    int r = sb_load();
    if (r < 0)
        return 0;                               /* the device refused: one pool */
    if (r == 0) {
        /* first power-on with this feature: today's pool is the legacy list, every project
         * shares it until its pool changes (decision 3). Nothing else is written. */
        smp_pl_gen = 1;
        sb_cur = -1;
        sb_seq = 0;
        int fl = snapshot();
        if (fl < 0 || list_write(PL_LEGACY, fl) != 0)
            return 0;
        smp_pl_owner = act;
        sb_pend = 0;
        sb_pslot = -1;
        sb_dirsum = imgsum;
        sb_tdirsum = 0;
        if (sb_store() != 0)
            return 0;
        smp_pl_on = 1;
        smp_pl_boot_case = 1;
        seen_loads = seen_news = 0;
        return 0;
    }
    for (int p = 0; p < PL_N; p++)
        list_read(p);
    smp_pl_on = 1;
    seen_loads = seen_news = 0;
    if (!LINFO[PL_LEGACY].valid) {              /* after a send from the computer: the new pool */
        int fl = snapshot();
        if (fl >= 0)
            list_write(PL_LEGACY, fl);
    }
    /* the image newer than its owner's list (a power cut between the two, or an older build
     * in between that changed the pool): the image is the newest pool there is, and its
     * owner's -- unless it is a switch's new pool, cut before the superblock said so */
    if (smp_dir_ok && imgsum != sb_dirsum && !(sb_pend && sb_tdirsum && imgsum == sb_tdirsum)) {
        smp_pl_boot_case = 6;
        write_owner();
    }
    if (smp_pj_loads || smp_pj_news) {          /* the OS loaded a project already: the poll's */
        smp_pl_boot_case = 2;
        return 0;
    }
    if (!smp_dir_ok) {                          /* the image's directory is unreadable: from the lists */
        smp_pl_boot_case = 5;
        int k = sb_pend && act == sb_pslot && sb_pend == 2 ? 2 : 1;
        return apply(k, act) == 0;
    }
    if (sb_pend) {                              /* a switch cut by power-off */
        int k = sb_pend, s = sb_pslot;
        if (act == s && (k == 1 || k == 2)) {
            smp_pl_boot_case = 3;
            return apply(k, s) == 0;
        }
        if (sb_tdirsum && imgsum == sb_tdirsum && sb_tdirsum != sb_dirsum) {
            /* the image holds the new pool, but the OS kept the old project: its pool back */
            smp_pl_boot_case = 4;
            return apply(1, act) == 0;
        }
        sb_pend = 0;
        sb_pslot = -1;
        sb_store();
    }
    if (act != smp_pl_owner) {
        if (act >= 0 && LINFO[act].valid) {
            smp_pl_boot_case = 7;
            return apply(1, act) == 0;
        }
        smp_pl_boot_case = 8;
        smp_pl_owner = act;
        sb_store();
        return 0;
    }
    if (smp_pl_boot_case != 6)
        smp_pl_boot_case = 9;
    return 0;
}

/* -- every UI pass ---------------------------------------------------------------------------- */

static int last_lstate D_ = 0, fill_due D_ = 0;

static int same(const u8 *a, const u8 *b, u32 n)
{
    for (u32 k = 0; k < n; k++)
        if (a[k] != b[k])
            return 0;
    return 1;
}

/* the list the pool is (the owner's own, or the legacy one it still shares), if it lacks a
 * sum the loader now knows for the same entry -> it, -1 none */
static int fill_list(void)
{
    u8 *dir = smp_pl_dirp();
    int p = -1;
    if (smp_pl_owner >= 0 && LINFO[smp_pl_owner].valid)
        p = smp_pl_owner;
    else if (LINFO[PL_LEGACY].valid && smp_dir_ok && same(dir, LDIR(PL_LEGACY), DIR_BYTES))
        p = PL_LEGACY;
    if (p < 0)
        return -1;
    for (int k = 0; k < POOL_SLOTS; k++) {
        u32 s = smp_pl_slot_sum(k);
        if (s && !LSUM(p)[k] && same(LDIR(p) + 8 + 16 * k, dir + 8 + 16 * k, 16))
            return p;
    }
    return -1;
}

static void quiesce(void)
{
    sw_rec = rec_running();
    sw_blank2 = 0;
    smp_pl_quiesce();                           /* the recorder stopped, the loader's work dropped, K_BLANK */
}

void smp_pl_poll(void)
{
    if (!smp_pl_on)
        return;
    u32 L = smp_pj_loads, N = smp_pj_news, B = smp_pj_begins, E = smp_pj_ends;
    if (L != seen_loads || N != seen_news) {
        seen_loads = L;
        seen_news = N;
        int kind = smp_pj_last == 2 ? 2 : 1;
        int s = kind == 2 ? smp_pj_newslot : smp_pj_slot;
        if (s < -1 || s > 127)
            s = -1;
        if (smp_pl_state != 1 && smp_pl_state != 2)
            quiesce();
        sw_kind = kind;
        sw_slot = s;
        sw_since = smp_periods;
        smp_pl_events++;
        sb_pend = kind;                         /* remembered before anything moves */
        sb_pslot = s;
        sb_tdirsum = 0;
        sb_store();
        smp_pl_state = 2;
    } else if (B != E && smp_pl_state == 0) {
        quiesce();                              /* a LOAD has begun: silence first */
        smp_pl_state = 1;
        end_at = 0;
    }
    if (smp_pl_state == 1) {
        if (B != E) {
            end_at = 0;
            return;
        }
        if (!end_at)
            end_at = smp_periods | 1u;
        if (smp_periods - end_at < 750u)        /* half a second for a NEW that may follow */
            return;
        if (!smp_pl_idle(0))
            return;
        smp_pl_state = 0;                       /* it failed: the pool as it was */
        smp_load();
        return;
    }
    if (smp_pl_state == 2) {
        if (B != E)
            return;
        /* a recording stopped by the switch: its slot blanked again once the DSP has let go */
        if (sw_rec && !sw_blank2 && !rec_running() && (smp_lstate == 0 || smp_lstate == 4)) {
            sw_blank2 = 1;
            smp_pl_quiesce();
        }
        int force = smp_periods - sw_since > 9000u;   /* six seconds: whatever still runs is cut */
        if (!smp_pl_idle(force))
            return;
        if (dirty)                              /* the old project's last changes, into its list */
            write_owner();
        smp_pl_state = 0;
        apply(sw_kind, sw_slot);
        return;
    }
    /* no event: the slot byte moved anyway (SAVE AS, DELETE of the active slot, a project
     * received as SysEx, FORMAT): the pool stays, and is the new slot's */
    int act = active();
    if (act != smp_pl_owner && B == E) {
        smp_pl_owner = act;
        dirty = 1;
        res_rev++;
    }
    if (smp_pl_bad_any() && (smp_lstate == 0 || smp_lstate == 4)) {
        smp_pl_bad_fix();                       /* slots whose frames no longer match: emptied */
        return;
    }
    if (dirty && smp_pl_list_ok()) {
        write_owner();
        return;
    }
    /* a load has finished: the sums it read, into the list the pool came from, where that
     * list did not know them yet (a list written before its slot's frames went through the
     * loader: the legacy list at the migration, a LOAD TO PROJECT's slot) */
    if (smp_lstate == 4 && last_lstate != 4)
        fill_due = 1;
    last_lstate = smp_lstate;
    if (fill_due && smp_pl_list_ok() && smp_lstate == 4) {
        fill_due = 0;
        int p = fill_list();
        if (p == smp_pl_owner && p >= 0)
            write_owner();
        else if (p == PL_LEGACY) {
            int fl = snapshot();
            if (fl >= 0)
                list_write(PL_LEGACY, fl);
        }
    }
}

/* -- a send from the computer replaces every project's pool, as before -------------------- */

void smp_pl_reset(void)                         /* BEGIN or FORGET: every list is void */
{
    if (!smp_pl_on)
        return;
    smp_pl_gen++;
    for (int p = 0; p < PL_N; p++)
        LINFO[p].valid = 0;
    smp_pl_owner = active();
    sb_pend = 0;
    sb_pslot = -1;
    sb_dirsum = 0;
    sb_store();
    res_rev++;
    dirty = 0;
    expect_clear();
}

void smp_pl_after_send(void)                    /* END, FORGET: the new pool is the legacy list */
{
    if (!smp_pl_on)
        return;
    int fl = snapshot();
    if (fl >= 0)
        list_write(PL_LEGACY, fl);
    sb_dirsum = smp_dir_ok && smp_hi ? csum(smp_pl_dirp(), DIR_BYTES) : 0;
    sb_store();
}
