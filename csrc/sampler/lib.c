/* v0.31: the +Drive's sample LIBRARY (docs/drive-library-plan.md, section 9): every sample
 * you keep, in folders, beside the pool (the samples a project holds, link.c). The pool is
 * what the DSP plays; the library is where samples wait until LOAD TO PROJECT copies one
 * into a pool slot.
 *
 * The region: sector LIB_SECTOR (3.5 GiB) to the device's end, above the pool's image
 * (0x600000 .. below 0x6C8001), far above the stock store (below 0x458000). Every read and
 * write is checked against it before the block driver is called (lib_rd, lib_wr).
 *
 *   LIB_SECTOR + 0          the superblock: 'DN2L', version, capacity, its own check
 *   + 1 .. + 256            the index: LIB_CAP entries of 64 bytes, 8 a sector
 *   + 257 .. + 260          LIB_FOLDERS names of 32 bytes (0 INCOMING, 1 RECORDED)
 *   + 261 ..                the frames: each sample one extent of whole sectors
 *
 * An entry: +0 its first sector (0: free), +4 frames, +8 rate (the pool's float ratio),
 * +12 format (the pool's), +13 folder, +14 flags, +16 a check of its frames (adler-32),
 * +20 its sectors, +24 its name (36), +60 a check of bytes 0..59. An entry whose check
 * fails is free: a sector half written leaves nothing. The frames are written first, the
 * entry last.
 *
 * Nothing here writes anything but its RAM (SMP_MIRROR + 0x100000, inside the mirror's
 * declared 5 MB and used by nothing else) and the region above. */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#if !defined(SMP_MIRROR) || !defined(POOL_BYTES)
#error "the sampler's constants are passed by the build (dnfw.waverider.cpage)"
#endif

#define BLK_READ  ((int (*)(u32, u32, void *))0x4012C59Au)          /* (sector, bytes, buf) -> 0 ok */
#define BLK_WRITE ((int (*)(u32, u32, const void *))0x4012C780u)
#define BLK_READY (*(volatile u32 *)0x4461B68Cu)
#define BLK_SECTORS (*(volatile u32 *)0x4461B6B0u)

#define POOL_STORE_END (0x600000u + 1u + POOL_BYTES / 512u)         /* link.c's image ends here */
#define LIB_SECTOR 0x700000u
#define LIB_MAGIC 0x444E324Cu                                       /* 'DN2L' */
#define LIB_VERSION 1u
#define LIB_CAP 2048
#define LIB_ENTRY 64u
#define LIB_INDEX_SECTORS (LIB_CAP * LIB_ENTRY / 512u)                /* 256 */
#define LIB_FOLDERS 64
#define LIB_FOLDER_BYTES 32u
#define LIB_FOLDER_SECTORS (LIB_FOLDERS * LIB_FOLDER_BYTES / 512u)    /* 4 */
#define LIB_INDEX (LIB_SECTOR + 1u)
#define LIB_FOLDER_AT (LIB_INDEX + LIB_INDEX_SECTORS)
#define LIB_DATA (LIB_FOLDER_AT + LIB_FOLDER_SECTORS)
#define LIB_NAME 36u
_Static_assert(LIB_SECTOR >= POOL_STORE_END, "the library lies above the pool's image");

#define LIB_RAM (SMP_MIRROR + 0x100000u)
#define SB ((u32 *)LIB_RAM)                                         /* one sector */
#define IDX ((u8 *)(LIB_RAM + 0x200u))                              /* LIB_CAP x 64 */
#define FOLD ((u8 *)(LIB_RAM + 0x200u + LIB_CAP * LIB_ENTRY))       /* LIB_FOLDERS x 32 */
#define LSTAGE ((u8 *)(LIB_RAM + 0x24000u))                         /* 64 KB */
#define LCHUNK 0x10000u
_Static_assert(0x200u + LIB_CAP * LIB_ENTRY + LIB_FOLDERS * LIB_FOLDER_BYTES <= 0x24000u, "the index fits before the stage");
_Static_assert(0x100000u + 0x24000u + 0x10000u <= 0x500000u, "inside the mirror's 5 MB");

int smp_lib_state __attribute__((section(".data"))) = 0;   /* 0 not read, 1 none (no superblock), 2 ready, -1 the device refused */
u32 smp_lib_writes __attribute__((section(".data"))) = 0;  /* sectors written, for the gate */

static u32 lget(const u8 *p) { return p[0] | p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
static void lput(u8 *p, u32 v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }

static u32 adler(const u8 *p, u32 n, u32 s)
{
    u32 a = s & 0xFFFFu, b = s >> 16;
    for (u32 k = 0; k < n; k++) {
        a = (a + p[k]) % 65521u;
        b = (b + a) % 65521u;
    }
    return b << 16 | a;
}

/* the region, or nothing */
static int lib_in(u32 sector, u32 bytes)
{
    u32 n = bytes / 512u;
    return BLK_READY && !(bytes & 511u) && bytes && sector >= LIB_SECTOR
           && BLK_SECTORS > LIB_DATA && sector < BLK_SECTORS && n <= BLK_SECTORS - sector;
}

static int lib_rd(u32 sector, u32 bytes, void *buf)
{
    return lib_in(sector, bytes) ? BLK_READ(sector, bytes, buf) : -1;
}

static int lib_wr(u32 sector, u32 bytes, const void *buf)
{
    if (!lib_in(sector, bytes))
        return -1;
    smp_lib_writes += bytes / 512u;
    return BLK_WRITE(sector, bytes, buf);
}

#define E(k) (IDX + LIB_ENTRY * (u32)(k))

static u32 entry_check(const u8 *e) { return adler(e, 60, 1u) ^ 0x4C494245u; }

/* which entries hold a sample, worked out once when the index is read or changes (the
 * browser asks thousands of times a frame: the check itself is far too slow for that) */
static u32 used_bits[LIB_CAP / 32] __attribute__((section(".data")));
static u16 fold_n[LIB_FOLDERS] __attribute__((section(".data")));   /* samples in each folder */

static void used_set(int k)
{
    const u8 *e = E(k);
    u32 b = 1u << (k & 31);
    if (lget(e) >= LIB_DATA && lget(e + 60) == entry_check(e) && e[13] < LIB_FOLDERS)
        used_bits[k >> 5] |= b;
    else
        used_bits[k >> 5] &= ~b;
}

static void used_all(void)
{
    for (int k = 0; k < LIB_CAP / 32; k++)
        used_bits[k] = 0;
    for (int k = 0; k < LIB_CAP; k++)
        used_set(k);
    for (int f = 0; f < LIB_FOLDERS; f++)
        fold_n[f] = 0;
    for (int k = 0; k < LIB_CAP; k++)
        if ((used_bits[k >> 5] >> (k & 31)) & 1u)
            fold_n[E(k)[13]]++;
}

int smp_lib_used(int k)                         /* entry K holds a sample */
{
    if (smp_lib_state != 2 || k < 0 || k >= LIB_CAP)
        return 0;
    return (used_bits[k >> 5] >> (k & 31)) & 1u;
}

static u32 sb_check(void) { return ~SB[0] ^ SB[1] ^ SB[2] ^ 0x5AA5C33Cu; }

static int sb_write(void)
{
    for (int k = 0; k < 128; k++)
        SB[k] = 0;
    SB[0] = LIB_MAGIC;
    SB[1] = LIB_VERSION;
    SB[2] = LIB_CAP;
    SB[3] = sb_check();
    return lib_wr(LIB_SECTOR, 512u, SB);
}

static int index_sector_write(int k)            /* the index sector entry K is in */
{
    u32 s = (u32)k / (512u / LIB_ENTRY);
    return lib_wr(LIB_INDEX + s, 512u, IDX + 512u * s);
}

/* power-on (link.c's smp_boot, once the device is up): the superblock, the index, the
 * folders. No superblock: nothing is written until the first send (lib_format). */
void smp_lib_boot(void)
{
    if (smp_lib_state != 0)
        return;
    if (lib_rd(LIB_SECTOR, 512u, SB) != 0) {
        smp_lib_state = -1;
        return;
    }
    if (SB[0] != LIB_MAGIC || SB[1] != LIB_VERSION || SB[2] != LIB_CAP || SB[3] != sb_check()) {
        smp_lib_state = 1;
        return;
    }
    if (lib_rd(LIB_INDEX, LIB_INDEX_SECTORS * 512u, IDX) != 0
        || lib_rd(LIB_FOLDER_AT, LIB_FOLDER_SECTORS * 512u, FOLD) != 0) {
        smp_lib_state = -1;
        return;
    }
    used_all();
    smp_lib_state = 2;
}

static void folder_set(int f, const char *name)
{
    u8 *d = FOLD + LIB_FOLDER_BYTES * (u32)f;
    u32 k = 0;
    for (; k < LIB_FOLDER_BYTES - 1 && name[k]; k++)
        d[k] = (u8)name[k];
    for (; k < LIB_FOLDER_BYTES; k++)
        d[k] = 0;
}

/* a fresh, empty library: the folders, the index zeroed, then the superblock last */
static int lib_format(void)
{
    if (smp_lib_state != 1)
        return smp_lib_state == 2 ? 0 : -1;
    for (u32 k = 0; k < LIB_CAP * LIB_ENTRY; k++)
        IDX[k] = 0;
    for (u32 k = 0; k < LIB_FOLDERS * LIB_FOLDER_BYTES; k++)
        FOLD[k] = 0;
    folder_set(0, "INCOMING");
    folder_set(1, "RECORDED");
    if (lib_wr(LIB_INDEX, LIB_INDEX_SECTORS * 512u, IDX) != 0
        || lib_wr(LIB_FOLDER_AT, LIB_FOLDER_SECTORS * 512u, FOLD) != 0 || sb_write() != 0)
        return -1;
    used_all();
    smp_lib_state = 2;
    return 0;
}

int smp_lib_count(void)
{
    int n = 0;
    for (int k = 0; k < LIB_CAP; k++)
        n += smp_lib_used(k);
    return n;
}

const char *smp_lib_folder_name(int f)
{
    if (smp_lib_state != 2 || f < 0 || f >= LIB_FOLDERS)
        return "";
    return (const char *)(FOLD + LIB_FOLDER_BYTES * (u32)f);
}

int smp_lib_folder_of(int k) { return smp_lib_used(k) ? E(k)[13] : -1; }
const char *smp_lib_name(int k) { return smp_lib_used(k) ? (const char *)(E(k) + 24) : ""; }
u32 smp_lib_frames(int k) { return smp_lib_used(k) ? lget(E(k) + 4) : 0; }

/* the first free sector run of SECTORS from LIB_DATA among the entries' extents -> its
 * first sector, 0: none */
static u32 lib_room(u32 sectors)
{
    u32 cand = LIB_DATA;
    for (int pass = 0; pass <= LIB_CAP; pass++) {
        int moved = 0;
        for (int k = 0; k < LIB_CAP; k++) {
            if (!smp_lib_used(k))
                continue;
            u32 s = lget(E(k)), z = s + lget(E(k) + 20);
            if (s < cand + sectors && cand < z) {
                cand = z;
                moved = 1;
            }
        }
        if (!moved)
            return cand < BLK_SECTORS && sectors <= BLK_SECTORS - cand ? cand : 0;
    }
    return 0;
}

/* -- a send from the computer: BEGIN, WRITE in order, END ------------------------------- */
static int w_idx __attribute__((section(".data"))) = -1;
static u32 w_start __attribute__((section(".data"))) = 0;
static u32 w_bytes __attribute__((section(".data"))) = 0;   /* the frames' bytes */
static u32 w_at __attribute__((section(".data"))) = 0;      /* how many came, in order */
static u32 w_sum __attribute__((section(".data"))) = 1;
static u32 w_block __attribute__((section(".data"))) = 0xFFFFFFFFu;
static u8 w_entry[64] __attribute__((section(".data")));

static int w_flush(void)
{
    if (w_block == 0xFFFFFFFFu)
        return 0;
    u32 n = w_at - w_block;
    n = (n + 511u) & ~511u;
    int r = n ? lib_wr(w_start + w_block / 512u, n, LSTAGE) : 0;
    w_block = 0xFFFFFFFFu;
    return r;
}

static int folder_find(const u8 *name, int make)       /* -> its index, or -1 */
{
    int empty = -1;
    for (int f = 0; f < LIB_FOLDERS; f++) {
        const u8 *d = FOLD + LIB_FOLDER_BYTES * (u32)f;
        if (!d[0]) {
            if (empty < 0)
                empty = f;
            continue;
        }
        u32 k = 0;
        while (k < LIB_FOLDER_BYTES - 1 && d[k] && d[k] == name[k])
            k++;
        if (k == LIB_FOLDER_BYTES - 1 || (!d[k] && !name[k]))
            return f;
    }
    if (!make || empty < 0 || !name[0])
        return -1;
    folder_set(empty, (const char *)name);
    return lib_wr(LIB_FOLDER_AT, LIB_FOLDER_SECTORS * 512u, FOLD) == 0 ? empty : -1;
}

/* the SysEx commands 16..23 (link.c's smp_rx: RQ, its N bytes; the reply's data from RP + R)
 * -> the reply's length; *ST its status (0 ok) */
static void put32(u8 *p, u32 v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }

u32 smp_lib_rx(u32 cmd, const u8 *rq, u32 n, u8 *rp, u32 r, u8 *st)
{
    if (smp_lib_state == 0)
        smp_lib_boot();
    if (cmd == 16) {                            /* INFO */
        put32(rp + r, (u32)smp_lib_state); r += 4;
        put32(rp + r, LIB_CAP); r += 4;
        put32(rp + r, smp_lib_state == 2 ? (u32)smp_lib_count() : 0); r += 4;
        put32(rp + r, BLK_READY ? BLK_SECTORS : 0); r += 4;
        put32(rp + r, LIB_DATA); r += 4;
        return r;
    }
    if (cmd == 17) {                            /* FOLDER name -> its index (made if new) */
        u8 name[LIB_FOLDER_BYTES];
        for (u32 k = 0; k < LIB_FOLDER_BYTES; k++)
            name[k] = 3 + k < n && k < LIB_FOLDER_BYTES - 1 ? rq[3 + k] : 0;
        int f = lib_format() == 0 ? folder_find(name, 1) : -1;
        if (f < 0)
            *st = 1;
        rp[r++] = (u8)(f < 0 ? 0xFF : f);
        return r;
    }
    if (cmd == 18) {                            /* BEGIN frames, fmt, folder, rate bits, name */
        if (n < 3 + 10 || lib_format() != 0) {
            *st = 1;
            return r;
        }
        u32 frames = lget(rq + 3), fmt = rq[7], folder = rq[8], rate = lget(rq + 9);
        u32 bytes = frames * (fmt ? 2u : 4u);
        int k = 0;
        while (k < LIB_CAP && smp_lib_used(k))
            k++;
        u32 sectors = (bytes + 511u) / 512u;
        u32 at = frames && bytes / (fmt ? 2u : 4u) == frames && k < LIB_CAP && folder < LIB_FOLDERS
                 ? lib_room(sectors) : 0;
        if (!at) {
            *st = 2;                            /* no room, or nothing to keep */
            return r;
        }
        for (u32 b = 0; b < 64; b++)
            w_entry[b] = 0;
        lput(w_entry, at);
        lput(w_entry + 4, frames);
        lput(w_entry + 8, rate);
        w_entry[12] = (u8)fmt;
        w_entry[13] = (u8)folder;
        lput(w_entry + 20, sectors);
        for (u32 c = 0; c < LIB_NAME - 1 && 13 + c < n; c++)
            w_entry[24 + c] = rq[13 + c];
        w_idx = k;
        w_start = at;
        w_bytes = bytes;
        w_at = 0;
        w_sum = 1;
        w_block = 0xFFFFFFFFu;
        put32(rp + r, (u32)k); r += 4;
        put32(rp + r, at); r += 4;
        return r;
    }
    if (cmd == 19) {                            /* WRITE offset, data: in order */
        u32 at = n >= 7 ? lget(rq + 3) : 0xFFFFFFFFu, m = n >= 7 ? n - 7 : 0;
        if (w_idx < 0 || at != w_at || m > w_bytes - w_at) {
            *st = 1;
            put32(rp + r, w_at); r += 4;        /* where it wants the next */
            return r;
        }
        for (u32 j = 0; j < m; j++) {
            u32 a = w_at, b = a & ~(LCHUNK - 1u);
            if (b != w_block) {
                if (w_flush() != 0) {
                    *st = 3;
                    w_idx = -1;
                    return r;
                }
                w_block = b;
                for (u32 z = 0; z < LCHUNK; z++)
                    LSTAGE[z] = 0;
            }
            LSTAGE[a - b] = rq[7 + j];
            w_at = a + 1;
        }
        w_sum = adler(rq + 7, m, w_sum);
        put32(rp + r, w_at); r += 4;
        return r;
    }
    if (cmd == 20) {                            /* END check: the entry, last */
        u32 want = n >= 7 ? lget(rq + 3) : 0;
        if (w_idx < 0 || w_at != w_bytes || w_flush() != 0 || want != w_sum) {
            *st = 1;
            w_idx = -1;
            return r;
        }
        lput(w_entry + 16, w_sum);
        lput(w_entry + 60, entry_check(w_entry));
        for (u32 b = 0; b < 64; b++)
            E(w_idx)[b] = w_entry[b];
        if (index_sector_write(w_idx) != 0) {
            *st = 3;
            for (u32 b = 0; b < 64; b++)
                E(w_idx)[b] = 0;
        }
        used_all();
        put32(rp + r, (u32)w_idx); r += 4;
        w_idx = -1;
        return r;
    }
    if (cmd == 21) {                            /* LIST from K: four entries */
        u32 k = n >= 5 ? (u32)(rq[3] | rq[4] << 8) : 0;
        put32(rp + r, smp_lib_state == 2 ? (u32)smp_lib_count() : 0); r += 4;
        for (int j = 0; j < 4; j++, k++) {
            int used = k < LIB_CAP && smp_lib_used((int)k);
            rp[r++] = (u8)k; rp[r++] = (u8)(k >> 8);
            put32(rp + r, used ? lget(E(k) + 4) : 0); r += 4;
            rp[r++] = used ? E(k)[13] : 0xFF;
            for (u32 c = 0; c < 24; c++)
                rp[r++] = used ? E(k)[24 + c] : 0;
        }
        return r;
    }
    if (cmd == 22) {                            /* DELETE K */
        u32 k = n >= 5 ? (u32)(rq[3] | rq[4] << 8) : 0xFFFFu;
        extern int smp_lib_delete(int k);
        if (smp_lib_delete((int)k) != 0)
            *st = 1;
        return r;
    }
    if (cmd == 23) {                            /* FOLDERS from F: four names */
        u32 f = n >= 4 ? rq[3] : 0;
        for (int j = 0; j < 4; j++, f++)
            for (u32 c = 0; c < 24; c++)
                rp[r++] = f < LIB_FOLDERS && smp_lib_state == 2 ? FOLD[LIB_FOLDER_BYTES * f + c] : 0;
        return r;
    }
    *st = 2;
    return r;
}

int smp_lib_delete(int k)
{
    if (!smp_lib_used(k))
        return -1;
    for (u32 b = 0; b < 64; b++)
        E(k)[b] = 0;
    used_all();
    return index_sector_write(k);
}

int smp_lib_rename(int k, const char *name)
{
    if (!smp_lib_used(k))
        return -1;
    u8 *e = E(k);
    u32 c = 0;
    for (; c < LIB_NAME - 1 && name[c]; c++)
        e[24 + c] = (u8)name[c];
    for (; c < LIB_NAME; c++)
        e[24 + c] = 0;
    lput(e + 60, entry_check(e));
    used_all();
    return index_sector_write(k);
}

/* read N bytes of entry K's frames from byte OFF (512-aligned) into BUF */
int smp_lib_read(int k, u32 off, u32 bytes, void *buf)
{
    if (!smp_lib_used(k) || (off & 511u) || ((off + bytes + 511u) & ~511u) > lget(E(k) + 20) * 512u)
        return -1;
    return lib_rd(lget(E(k)) + off / 512u, (bytes + 511u) & ~511u, buf);
}

u32 smp_lib_rate(int k) { return smp_lib_used(k) ? lget(E(k) + 8) : 0; }
int smp_lib_fmt(int k) { return smp_lib_used(k) ? E(k)[12] : 0; }

u8 *smp_lib_stage(void) { return LSTAGE; }      /* link.c's LOAD TO PROJECT copies through it */
int smp_lib_busy(void) { return w_idx >= 0; }   /* a send from the computer is using it */

void smp_lib_refresh(void) { if (smp_lib_state == 2) used_all(); }   /* the index changed in RAM */

int smp_lib_folder_count(int f)                 /* samples in folder F */
{
    return smp_lib_state == 2 && f >= 0 && f < LIB_FOLDERS ? fold_n[f] : 0;
}
