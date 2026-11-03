/* v0.39: ERASE MOD DATA (docs/erase-mod-data.md; owner-approved 2026-11-02).
 *
 * Erases exactly the mod's own +Drive regions (docs/memory-map.md's +Drive table) with the
 * eMMC's erase command, the stock block driver's TRIM (0x4012c4b2(sector, count): CMD35
 * start, CMD36 end, CMD38 argument 1), in calls of 2,048 sectors (1 MiB) as stock's FORMAT
 * +DRIVE makes them (0x4012f3cc): the call size proven on every unit. Then reads back every
 * header sector and a sampled set across every range: each must read as erased (all 0x00 or
 * all 0xFF, the card's ERASED_MEM_CONT).
 *
 *   the pool image (link.c)            0x600000 .. 0x6C8000   (header 0x600000)
 *   the per-project lists (pools.c)    0x6D0000 .. 0x6E02FF   (superblocks 0x6D0000/1)
 *   the settings sector (jump.c)       0x6FF000
 *   the library (lib.c)                0x700000 .. the device's last sector
 *
 * Nothing below 0x600000 is ever named: the stock store (below 0x458000) and the factory
 * buffer (0x458000 .. 0x5D7FFF) are below every region, which the static asserts tie to the
 * other files' constants, and every call passes er_guard (the assertion): a range outside
 * the four regions, or past the device, is refused before the driver is called and the
 * erase stops there.
 *
 * Order (power loss at any point boots safely; docs/erase-mod-data.md): every header first
 * -- the pool's, the lists' region (its superblocks and every list's header), the settings,
 * the library's superblock, index and folders -- so after the first few calls each part
 * already reads as empty to its own boot code (each treats a missing or invalid header as
 * empty); then the bulk (the pool's frames, the library's frames).
 *
 * From the first call on, smp_er_lock is set and stays set until power-off: every writer of
 * ours (link.c image_write / header_write, pools.c pl_wr, lib.c lib_wr, jump.c's settings)
 * refuses, so nothing in RAM is written back over the erased regions. The screen then asks
 * for a restart: the mod comes up as on a fresh install.
 *
 * Started from the browser's top (rec.c: +DRIVE, RIGHT, ERASE MOD DATA, two questions) or by
 * link command 28 (link.c); stepped from the UI loop (page.c's wr_poll) about 40 ms a pass.
 *
 * v0.41 (a unit's report: "TRIM ERROR AT 817905", then further on a second try): the stock
 * TRIM returns non-zero only when one of CMD35/36/38 got no answer (its ISR 0x4012b99e sets -1
 * on the controller's command timeout, CTOE, and on nothing else), and a card answers no
 * CMD35 while it is still programming the previous erase. Stock's own wait for that (0x4012c52c:
 * the DAT0 edge interrupt armed BEFORE DAT0 is tested) leaves a stale post when DAT0 rises in
 * between -- likely after a short TRIM of an unmapped range -- and the next TRIM's wait then
 * returns at once with the card still busy. So before every call we read the eSDHC's present
 * state (PRSSTAT, read-only, as 0x4012c544 does) and call only when the card is idle: DAT0 high,
 * no command or data inhibit. A call that still fails is tried again after a pause (ER_TRIES in
 * all), as is a verify read; a failure leaves the place it stopped, and asking again (without a
 * restart) carries on from there. */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define D_ __attribute__((section(".data")))

#if !defined(POOL_BYTES)
#error "the sampler's constants are passed by the build (dnfw.waverider.cpage)"
#endif

#define BLK_READ  ((int (*)(u32, u32, void *))0x4012C59Au)          /* (sector, bytes, buf) -> 0 ok */
#define BLK_TRIM  ((int (*)(u32, u32))0x4012C4B2u)                  /* (sector, count) -> 0 ok: CMD35/36/38(1) */
#define BLK_READY (*(volatile u32 *)0x4461B68Cu)
#define BLK_SECTORS (*(volatile u32 *)0x4461B6B0u)
#define FRAMES_NOW (*(volatile u32 *)0x4058E8D4u)                   /* 1,500 a second */
/* v0.41: the eSDHC's present state (MCF5441x PRSSTAT): bit 24 DAT0's level (low: the card is
 * busy), bit 1 CDIHB, bit 0 CIHB. Only ever read (stock's TRIM tests the same bit 24) */
#define SD_PRSSTAT (*(volatile u32 *)0xFC0CC024u)
#define SD_IDLE(p) (((p) & (1u << 24)) && !((p) & 3u))
/* the EXT_CSD as the driver read it at power-on (docs/drive-storage-research.md: byte-swapped
 * per word; SEC_COUNT, byte 212, at 0x4e6f11d4), for the status only */
#define EXT_CSD 0x4E6F1100u
#define CSD_BYTE(b) (*(volatile u8 *)(EXT_CSD + ((u32)(b) & ~3u) + (3u - ((u32)(b) & 3u))))

/* the regions, as the files that own them define them */
#define STOCK_STORE_END 0x458000u                                   /* the stock store ends below */
#define FACTORY_END 0x5D8000u                                       /* the factory buffer 0x458000..0x5D7FFF */
#define ER_FLOOR 0x600000u                                          /* nothing below is ever named */
#define POOL_SECTOR 0x600000u                                       /* link.c STORE_SECTOR */
#define POOL_STORE_END (0x600000u + 1u + POOL_BYTES / 512u)         /* link.c: its image ends below */
#define PL_SB 0x6D0000u                                             /* pools.c */
#define PL_END (0x6D0100u + 2u * 129u * 256u)
#define SET_SECTOR 0x6FF000u                                        /* jump.c */
#define LIB_SECTOR 0x700000u                                        /* lib.c */
#define LIB_DATA (LIB_SECTOR + 1u + 256u + 4u)                      /* lib.c: superblock, index, folders */
#define ER_CHUNK 2048u                                              /* stock FORMAT's call */
#define ER_TRIES 5u                     /* v0.41: a call (TRIM or a verify read) tried at most 5 times */
#define ER_PAUSE_FR 300u                /* 200 ms between tries (or ER_PAUSE_PASSES passes ... */
#define ER_PAUSE_PASSES 8u              /* ... when the frame counter is not running) */
#define ER_BUSY_FR 15000u               /* the card busy 10 s on end: CARD BUSY (or ... */
#define ER_BUSY_PASSES 250u             /* ... 250 passes when the frame counter is not running) */
#define ER_SPIN 4000u                   /* PRSSTAT reads in one pass before it waits for the next */

_Static_assert(ER_FLOOR >= FACTORY_END && FACTORY_END > STOCK_STORE_END, "nothing stock at or above the floor");
_Static_assert(POOL_SECTOR >= ER_FLOOR, "the pool image lies above the floor");
_Static_assert(POOL_STORE_END == 0x6C8001u, "the pool image ends at 0x6C8000 (docs/memory-map.md)");
_Static_assert(PL_SB >= POOL_STORE_END && PL_END == 0x6E0300u, "the lists: 0x6D0000..0x6E02FF");
_Static_assert(SET_SECTOR >= PL_END && SET_SECTOR < LIB_SECTOR, "the settings sector between the lists and the library");
_Static_assert(LIB_SECTOR > SET_SECTOR && LIB_DATA == 0x700105u, "the library's headers: 0x700000..0x700104");

int smp_er_lock D_ = 0;                 /* set at the first erase call; every writer of ours refuses */
int smp_er_req D_ = 0;                  /* link command 28: start at the next UI pass */
int smp_er_state D_ = 0;                /* 0 idle, 1 erasing, 2 verifying, 3 ERASED, 4 failed */
int smp_er_err D_ = 0;                  /* 1 guard (refused before the driver), 2 TRIM's error, 3 a read
                                         * failed, 4 a sector not erased, 5 the +Drive not up,
                                         * 6 the card stayed busy (v0.41) */
u32 smp_er_sector D_ = 0;               /* the failing sector */
u32 smp_er_value D_ = 0;                /* the driver's return, or the sector's first word */
u32 smp_er_done D_ = 0;                 /* sectors erased (of smp_er_total) */
u32 smp_er_total D_ = 0;
u32 smp_er_trims D_ = 0;                /* TRIM calls made */
u32 smp_er_reads D_ = 0;                /* sectors read back */
u32 smp_er_checks D_ = 0;               /* of smp_er_nchecks */
u32 smp_er_nchecks D_ = 0;
int smp_er_job D_ = 0;
u32 smp_er_retries D_ = 0;              /* v0.41: calls tried again (all of them) */
u32 smp_er_waits D_ = 0;                /* v0.41: passes that found the card busy */
int smp_er_resume D_ = 0;               /* v0.41: 1 or 2 (the state to go back to) after a failure
                                         * a new try may get past: asking again carries on */
static u32 er_tries D_ = 0;             /* this call's failed tries */
static u32 er_hold_fr D_ = 0, er_hold_n D_ = 0;     /* a pause or a busy wait: since (frames), passes */
static int er_hold D_ = 0;              /* 0 none, 1 a pause before a try again, 2 waiting for the card */
static u32 er_pos D_ = 0;               /* the next sector of the job */
static u8 er_buf[512] __attribute__((section(".data"), aligned(16)));

/* job -> [start, end) */
#define ER_JOBS 6
static void er_job(int j, u32 *a, u32 *b)
{
    u32 end = BLK_SECTORS;
    switch (j) {
    case 0: *a = POOL_SECTOR; *b = POOL_SECTOR + 1u; return;       /* the pool image's header */
    case 1: *a = PL_SB; *b = PL_END; return;                        /* the lists (superblocks first) */
    case 2: *a = SET_SECTOR; *b = SET_SECTOR + 1u; return;          /* the settings */
    case 3: *a = LIB_SECTOR; *b = end < LIB_DATA ? end : LIB_DATA; return;   /* the library's headers */
    case 4: *a = POOL_SECTOR + 1u; *b = POOL_STORE_END; return;     /* the pool's frames */
    default: *a = LIB_DATA; *b = end > LIB_DATA ? end : LIB_DATA; return;    /* the library's frames */
    }
}

/* the assertion: [s, s + n) inside exactly one of the four regions, never below ER_FLOOR,
 * never past the device, at most one stock-sized call */
static int er_inside(u32 s, u32 n)
{
    u32 dev = BLK_SECTORS;
    if (!BLK_READY || n == 0 || n > ER_CHUNK || s < ER_FLOOR || s >= dev || n > dev - s)
        return 0;
    if (s >= POOL_SECTOR && s + n <= POOL_STORE_END)
        return 1;
    if (s >= PL_SB && s + n <= PL_END)
        return 1;
    if (s == SET_SECTOR && n == 1u)
        return 1;
    if (s >= LIB_SECTOR)                        /* to the device's end (checked above) */
        return 1;
    return 0;
}

static void er_fail(int err, u32 sector, u32 value)
{
    /* v0.41: a TRIM or read error, or a card that stayed busy, may pass on a new try: asking
     * again carries on from this call (the headers are long gone; nothing of ours writes) */
    smp_er_resume = (err == 2 || err == 3 || err == 6) ? smp_er_state : 0;
    smp_er_err = err;
    smp_er_sector = sector;
    smp_er_value = value;
    smp_er_state = 4;
    er_hold = 0;
    er_tries = 0;
}

/* v0.41: -> 1 when the card may be given a command now. Otherwise this pass ends: a pause
 * after a failed try runs out, or the card's busy line is waited for (CARD BUSY once it has
 * been busy too long, SECTOR the call's) */
static u32 er_since(u32 *n)
{
    u32 fr = FRAMES_NOW - er_hold_fr;
    *n = er_hold_n;
    return fr;
}

static int er_ready(u32 sector)
{
    u32 n, fr;
    if (er_hold == 1) {                         /* the pause before a try again */
        fr = er_since(&n);
        er_hold_n++;
        if (fr < ER_PAUSE_FR && !(fr == 0 && n >= ER_PAUSE_PASSES))
            return 0;
        er_hold = 0;
    }
    for (u32 k = 0; k < ER_SPIN; k++)
        if (SD_IDLE(SD_PRSSTAT)) {
            er_hold = 0;
            return 1;
        }
    smp_er_waits++;
    if (er_hold != 2) {
        er_hold = 2;
        er_hold_fr = FRAMES_NOW;
        er_hold_n = 0;
        return 0;
    }
    fr = er_since(&n);
    er_hold_n++;
    if (fr >= ER_BUSY_FR || (fr == 0 && n >= ER_BUSY_PASSES))
        er_fail(6, sector, SD_PRSSTAT);
    return 0;
}

/* v0.41: a call failed (R its return): -> 1 if it is tried again after a pause, 0 if that was
 * its last try (the caller fails) */
static int er_again(void)
{
    if (++er_tries >= ER_TRIES)
        return 0;
    smp_er_retries++;
    er_hold = 1;
    er_hold_fr = FRAMES_NOW;
    er_hold_n = 0;
    return 1;
}

static int er_trim(u32 s, u32 n)
{
    if (!er_inside(s, n)) {
        er_fail(1, s, n);
        return -1;
    }
    smp_er_trims++;
    int r = BLK_TRIM(s, n);
    if (r != 0) {
        if (!er_again())
            er_fail(2, s, (u32)r);
        return -1;                              /* (tried again on a later pass, or failed) */
    }
    er_tries = 0;
    return 0;
}

/* the verify's list: K -> a sector. Every header sector first (the pool's; the lists'
 * superblocks and each list copy's header; the settings; the library's superblock, index,
 * folders), then 64 a range spread over it, its first and last among them */
#define ER_SPREAD 64u
static u32 er_nhead(void) { return 1u + 2u + 2u * 129u + 1u + (LIB_DATA - LIB_SECTOR); }

static u32 er_check_sector(u32 k)
{
    u32 h = er_nhead();
    if (k == 0)
        return POOL_SECTOR;
    if (k <= 2)
        return PL_SB + (k - 1u);
    if (k < 3u + 258u)
        return 0x6D0100u + 256u * (k - 3u);
    if (k == 3u + 258u)
        return SET_SECTOR;
    if (k < h)
        return LIB_SECTOR + (k - 262u);
    k -= h;
    u32 j = k / ER_SPREAD, i = k % ER_SPREAD, a, b;
    er_job(j == 0 ? 4 : j == 1 ? 1 : 5, &a, &b);    /* the pool's frames, the lists, the library */
    if (b <= a)
        return a;
    u32 span = b - a - 1u;
    /* i of 63 along the range, nudged off the 1 MiB grid by a little (never past its end) */
    u32 at = a + (span / (ER_SPREAD - 1u)) * i + (span % (ER_SPREAD - 1u)) * i / (ER_SPREAD - 1u);   /* (32-bit) */
    u32 nudge = (i * 2654435761u >> 20) & 1023u;
    return (i == 0 || i == ER_SPREAD - 1u || at + nudge >= b) ? at : at + nudge;
}

static int er_erased(const u8 *p)
{
    u8 v = p[0];
    if (v != 0x00 && v != 0xFF)
        return 0;
    for (int k = 1; k < 512; k++)
        if (p[k] != v)
            return 0;
    return 1;
}

extern int smp_overlay_dirty;

int smp_er_start(void)
{
    if (smp_er_state == 1 || smp_er_state == 2 || smp_er_state == 3)
        return -1;                              /* under way, or done: restart first */
    if (smp_er_resume && smp_er_lock && BLK_READY) {
        /* v0.41: asked again after a failure a new try may get past: on from the call that
         * failed (the erase's place and counts kept; it reads every check again from there) */
        smp_er_state = smp_er_resume;
        smp_er_resume = 0;
        smp_er_err = 0;
        er_hold = 0;
        er_tries = 0;
        smp_overlay_dirty = 1;
        return 0;
    }
    smp_er_resume = 0;
    if (!BLK_READY || BLK_SECTORS <= LIB_DATA) {
        er_fail(5, 0, BLK_SECTORS);
        return -1;
    }
    extern void rec_halt(void), smp_lib_preview_stop(void);
    smp_er_lock = 1;                            /* from here on nothing of ours writes */
    rec_halt();                                 /* a recording stops (its take is not kept) */
    smp_lib_preview_stop();
    smp_er_err = 0;
    smp_er_sector = smp_er_value = 0;
    smp_er_done = smp_er_trims = smp_er_reads = smp_er_checks = 0;
    smp_er_retries = smp_er_waits = 0;
    er_hold = 0;
    er_tries = 0;
    smp_er_total = 0;
    for (int j = 0; j < ER_JOBS; j++) {
        u32 a, b;
        er_job(j, &a, &b);
        smp_er_total += b - a;
    }
    smp_er_nchecks = er_nhead() + 3u * ER_SPREAD;
    u32 end;
    smp_er_job = 0;
    er_job(0, &er_pos, &end);
    smp_er_state = 1;
    smp_overlay_dirty = 1;
    return 0;
}

/* from the UI loop (page.c's wr_poll), every pass: about 40 ms of work */
void smp_er_poll(void)
{
    if (smp_er_req) {
        smp_er_req = 0;
        smp_er_start();
    }
    if (smp_er_state != 1 && smp_er_state != 2)
        return;
    u32 t0 = FRAMES_NOW;
    int calls = 0;
    smp_overlay_dirty = 1;                      /* the progress redrawn */
    while (smp_er_state == 1 && (int)(FRAMES_NOW - t0) < 60 && calls < 256) {
        u32 a, b;
        er_job(smp_er_job, &a, &b);
        if (er_pos < a)
            er_pos = a;
        if (er_pos >= b) {
            if (++smp_er_job >= ER_JOBS) {
                smp_er_state = 2;               /* all erased: read back */
                break;
            }
            er_job(smp_er_job, &er_pos, &b);
            continue;
        }
        u32 n = b - er_pos > ER_CHUNK ? ER_CHUNK : b - er_pos;
        if (!er_ready(er_pos))
            return;                             /* v0.41: the card busy, or a pause: next pass */
        if (er_trim(er_pos, n) != 0)
            return;
        er_pos += n;
        smp_er_done += n;
        calls++;
    }
    while (smp_er_state == 2 && (int)(FRAMES_NOW - t0) < 60 && calls < 256) {
        if (smp_er_checks >= smp_er_nchecks) {
            smp_er_state = 3;                   /* ERASED */
            return;
        }
        u32 s = er_check_sector(smp_er_checks);
        if (!er_inside(s, 1u)) {
            er_fail(1, s, 1u);
            return;
        }
        if (!er_ready(s))
            return;                             /* v0.41: as the TRIMs */
        int r = BLK_READ(s, 512u, er_buf);
        smp_er_reads++;
        calls++;
        if (r != 0) {
            if (!er_again())
                er_fail(3, s, (u32)r);
            return;
        }
        er_tries = 0;
        if (!er_erased(er_buf)) {
            er_fail(4, s, (u32)er_buf[0] << 24 | (u32)er_buf[1] << 16 | (u32)er_buf[2] << 8 | er_buf[3]);
            return;
        }
        smp_er_checks++;
    }
}

/* for link command 29 (link.c): the state, then the card's EXT_CSD as read at power-on (if
 * the driver's copy is still the card's: its SEC_COUNT is the device's size) */
static void put(u8 *p, u32 v)
{
    p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v;
}

u32 smp_er_status(u8 *rp, u32 r)
{
    rp[r++] = (u8)smp_er_state;
    rp[r++] = (u8)smp_er_err;
    rp[r++] = (u8)smp_er_job;
    rp[r++] = (u8)smp_er_lock;
    u32 v[8] = {smp_er_done, smp_er_total, smp_er_sector, smp_er_value, smp_er_trims, smp_er_reads,
                smp_er_checks, smp_er_nchecks};
    for (int k = 0; k < 8; k++, r += 4)
        put(rp + r, v[k]);
    u32 cnt = (u32)CSD_BYTE(212) | (u32)CSD_BYTE(213) << 8 | (u32)CSD_BYTE(214) << 16 | (u32)CSD_BYTE(215) << 24;
    int ok = BLK_READY && cnt == BLK_SECTORS;
    rp[r++] = (u8)ok;
    rp[r++] = ok ? CSD_BYTE(231) : 0;          /* SEC_FEATURE_SUPPORT */
    rp[r++] = ok ? CSD_BYTE(181) : 0;          /* ERASED_MEM_CONT */
    rp[r++] = ok ? CSD_BYTE(192) : 0;          /* EXT_CSD_REV */
    put(rp + r, BLK_SECTORS); r += 4;
    put(rp + r, smp_er_retries); r += 4;        /* v0.41: calls tried again, passes the card was */
    put(rp + r, smp_er_waits); r += 4;          /* busy, and whether asking again carries on */
    rp[r++] = (u8)smp_er_resume;
    return r;
}

/* the browser's screen (smp_page.c): 0 none of ours, 1 erasing, 2 verifying, 3 ERASED, 4 failed */
int smp_er_can_resume(void) { return smp_er_resume != 0; }
int smp_er_shown(void) { return smp_er_state; }
u32 smp_er_percent(void)
{
    if (smp_er_state == 2)
        return smp_er_nchecks ? smp_er_checks * 100u / smp_er_nchecks : 0;
    u32 per = (smp_er_total + 99u) / 100u;     /* (32-bit: the total is up to ~2^26 sectors) */
    return per ? smp_er_done / per : 0;
}
