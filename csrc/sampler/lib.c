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
 *                           v0.40: byte 31 0 (a top-level folder, every folder written before
 *                           v0.40) or 0x80 | its parent's index (a folder inside a folder; its
 *                           name then at most 30 characters, byte 30 0). See folder_tree.
 *   + 261 ..                the frames: each sample one extent of whole sectors
 *
 * v0.43 (Wolljamin: "failed: command 30: refused", the 64 folders full): folders 64..127 live
 * below the library, between Direct Jump's settings and LIB_SECTOR (nothing else uses those
 * sectors: erase.c, pools.c), as the first 64 do: LIB_HI_AT a header ('DN2F', version, its
 * check), then four sectors of 16 records. A header that does not check (every library before
 * v0.43) is no folders there: the first folder made past 63 writes the records, then the
 * header. A record's tag (byte 31) names a parent 0..63 as 0x80 | parent (v0.40), 64..127 as
 * 0xC0 | (parent - 64) (an older build reads that as a top-level folder: nothing is lost).
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
#define LIB_SECTOR_C 0x700000u
#define LIB_MAGIC 0x444E324Cu                                       /* 'DN2L' */
#define LIB_VERSION 1u
/* v0.45 (spacem0nkey: "maxed out the amount despite having 18gb of memory left"): 16,384
 * entries. The first 2,048 stay where every build keeps them (LIB_INDEX); 2,048..16,383 are
 * the extension, LIB_X_AT: a header ('DN2X', version, capacity, its check) and then 1,792
 * sectors of entries, below the library between the per-project lists (pools.c, to
 * 0x6E02FF) and Direct Jump's settings (0x6FF000), sectors nothing else uses (pools.c,
 * erase.c). Like v0.43's folders past 64, it is made the first time an entry past 2,047 is
 * written: the entries first, the header last, so a power cut leaves the first 2,048 as they
 * were and none past them. The superblock is untouched (version 1, capacity 2,048): an older
 * build reads the library's first 2,048 entries as always and never sees the rest. */
#define LIB_CAP 16384
#define LIB_CAP_LO 2048                                             /* on the +Drive at LIB_INDEX */
#define LIB_ENTRY 64u
#define LIB_INDEX_SECTORS (LIB_CAP_LO * LIB_ENTRY / 512u)             /* 256 */
#define LIB_X_AT 0x6F0000u
#define LIB_X_IDX (LIB_X_AT + 1u)
#define LIB_X_SECTORS ((LIB_CAP - LIB_CAP_LO) * LIB_ENTRY / 512u)    /* 1,792 */
#define LIB_X_MAGIC 0x444E3258u                                     /* 'DN2X' */
_Static_assert(LIB_X_AT >= 0x6E0300u && LIB_X_IDX + LIB_X_SECTORS <= 0x6FF000u,
               "the extension: between the per-project lists and the settings sector");
#define LIB_FOLDERS 128                                             /* v0.43 (64 before; smp_page.c's SMP_LIB_FOLDERS) */
#define LIB_FOLDERS_LO 64                                           /* in the library's headers */
#define LIB_FOLDER_BYTES 32u
#define LIB_FOLDER_SECTORS (LIB_FOLDERS_LO * LIB_FOLDER_BYTES / 512u)   /* 4 */
#define LIB_HI_AT 0x6FF800u                                         /* v0.43: folders 64..127's header */
#define LIB_HI_REC (LIB_HI_AT + 1u)                                 /*   and their four sectors */
#define LIB_HI_SECTORS ((LIB_FOLDERS - LIB_FOLDERS_LO) * LIB_FOLDER_BYTES / 512u)
#define LIB_HI_MAGIC 0x444E3246u                                    /* 'DN2F' */
_Static_assert(LIB_HI_AT > 0x6FF000u && LIB_HI_REC + LIB_HI_SECTORS <= LIB_SECTOR_C, "between the settings sector and the library");
#define LIB_INDEX (LIB_SECTOR + 1u)
#define LIB_FOLDER_AT (LIB_INDEX + LIB_INDEX_SECTORS)
#define LIB_DATA (LIB_FOLDER_AT + LIB_FOLDER_SECTORS)
#define LIB_NAME 36u
/* v0.40: folders inside folders (takton's TRANCE STARTER PACK/KICKS/..: the import page sent
 * each path as one flat name, cut at 31). A top-level folder is depth 1; LIB_DEPTH deep at most */
#define LIB_DEPTH 6
#define FTAG(f) (FOLD[LIB_FOLDER_BYTES * (u32)(f) + LIB_FOLDER_BYTES - 1u])
#define FNAMED(f) (FOLD[LIB_FOLDER_BYTES * (u32)(f)] != 0)
_Static_assert(LIB_SECTOR >= POOL_STORE_END, "the library lies above the pool's image");

#define LIB_RAM (SMP_MIRROR + 0x100000u)
#define SB ((u32 *)LIB_RAM)                                         /* one sector */
#define IDX ((u8 *)(LIB_RAM + 0x200u))                              /* LIB_CAP_LO x 64 */
#define FOLD ((u8 *)(LIB_RAM + 0x200u + LIB_CAP_LO * LIB_ENTRY))    /* LIB_FOLDERS x 32 */
/* v0.45: entries 2,048..16,383 (896 KB), and the extents' scratch for lib_room (128 KB), in
 * the mirror's free part above the per-project pools' SSUM (link.c, to + 0x22CA14) */
#define IDXH ((u8 *)(SMP_MIRROR + 0x300000u))
#define EXT ((u32 *)(SMP_MIRROR + 0x3E8000u))
_Static_assert(0x300000u + (LIB_CAP - LIB_CAP_LO) * LIB_ENTRY <= 0x3E0000u
               && 0x3E8000u + LIB_CAP * 8u <= SMP_MIRROR_BYTES, "the extension's RAM inside the mirror");
#define LSTAGE ((u8 *)(LIB_RAM + 0x24000u))                         /* 64 KB */
#define LCHUNK 0x10000u
_Static_assert(0x200u + LIB_CAP_LO * LIB_ENTRY + LIB_FOLDERS * LIB_FOLDER_BYTES <= 0x24000u, "the index fits before the stage");
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
    if (BLK_READY && !(bytes & 511u) && bytes && BLK_SECTORS > LIB_DATA && sector >= LIB_HI_AT
        && sector + n <= LIB_HI_REC + LIB_HI_SECTORS)
        return 1;                               /* v0.43: folders 64..127 */
    if (BLK_READY && !(bytes & 511u) && bytes && BLK_SECTORS > LIB_DATA && sector >= LIB_X_AT
        && sector + n <= LIB_X_IDX + LIB_X_SECTORS)
        return 1;                               /* v0.45: entries 2,048..16,383 */
    return BLK_READY && !(bytes & 511u) && bytes && sector >= LIB_SECTOR
           && BLK_SECTORS > LIB_DATA && sector < BLK_SECTORS && n <= BLK_SECTORS - sector;
}

static int lib_rd(u32 sector, u32 bytes, void *buf)
{
    return lib_in(sector, bytes) ? BLK_READ(sector, bytes, buf) : -1;
}

extern int smp_er_lock;                         /* v0.39: ERASE MOD DATA (erase.c) */
static int lib_wr(u32 sector, u32 bytes, const void *buf)
{
    if (smp_er_lock || !lib_in(sector, bytes))
        return -1;
    smp_lib_writes += bytes / 512u;
    return BLK_WRITE(sector, bytes, buf);
}

#define E(k) ((u32)(k) < LIB_CAP_LO ? IDX + LIB_ENTRY * (u32)(k) : IDXH + LIB_ENTRY * ((u32)(k) - LIB_CAP_LO))

static u32 entry_check(const u8 *e) { return adler(e, 60, 1u) ^ 0x4C494245u; }

/* which entries hold a sample, worked out once when the index is read or changes (the
 * browser asks thousands of times a frame: the check itself is far too slow for that) */
static u32 used_bits[LIB_CAP / 32] __attribute__((section(".data")));
static u16 fold_n[LIB_FOLDERS] __attribute__((section(".data")));   /* samples in each folder */
/* v0.40: each folder's parent as the browser takes it (-1: the top), and its depth (1: top) */
signed char smp_lib_fpar[LIB_FOLDERS] __attribute__((section(".data")));
static u8 fold_dep[LIB_FOLDERS] __attribute__((section(".data")));

/* v0.40: the tree, worked out from the folder records whenever they or the index change.
 * Whatever the records hold (a parent dropped by an older build, a sector torn by a power
 * cut, a loop), the result is a tree LIB_DEPTH deep at most and every folder is in it: a
 * folder whose parent is not a named folder, or whose line of parents does not reach the
 * top within LIB_DEPTH, is taken as a top-level folder. Nothing is written: a record is only
 * read differently, so no sample is ever lost or hidden. */
static void folder_tree(void)
{
    for (int f = 0; f < LIB_FOLDERS; f++)       /* a byte 31 (a tag) after 31 letters: no tag (a */
        if (FTAG(f) && FOLD[LIB_FOLDER_BYTES * (u32)f + LIB_FOLDER_BYTES - 2u])    /* torn record) */
            FTAG(f) = 0;                        /* so every name ends inside its record */
    for (int f = 0; f < LIB_FOLDERS; f++) {
        u32 t = FTAG(f), p = (t & 0x3Fu) + ((t & 0xC0u) == 0xC0u ? 64u : 0u);   /* v0.43: 0xC0 | p - 64 */
        smp_lib_fpar[f] = (signed char)((t & 0x80u) && FNAMED(f) && p != (u32)f && FNAMED(p)
                                        && !FOLD[LIB_FOLDER_BYTES * (u32)f + LIB_FOLDER_BYTES - 2u] ? (int)p : -1);
    }
    for (int f = 0; f < LIB_FOLDERS; f++) {
        int p = smp_lib_fpar[f], d = 1;
        while (p >= 0 && d <= LIB_DEPTH) {
            p = smp_lib_fpar[p];
            d++;
        }
        if (p >= 0 || d > LIB_DEPTH)            /* a loop, or too deep: from here, the top */
            smp_lib_fpar[f] = -1;
    }
    for (int f = 0; f < LIB_FOLDERS; f++) {
        int p = smp_lib_fpar[f], d = 1;
        while (p >= 0 && d <= LIB_DEPTH) {
            p = smp_lib_fpar[p];
            d++;
        }
        fold_dep[f] = (u8)d;
    }
}

static void used_set(int k)
{
    const u8 *e = E(k);
    u32 b = 1u << (k & 31);
    if (lget(e) >= LIB_DATA && lget(e + 60) == entry_check(e) && e[13] < LIB_FOLDERS)
        used_bits[k >> 5] |= b;
    else
        used_bits[k >> 5] &= ~b;
}

u32 smp_lib_rev __attribute__((section(".data"))) = 0;   /* v0.33: bumped whenever the index may have changed */

static void used_all(void)
{
    smp_lib_rev++;
    for (int k = 0; k < LIB_CAP / 32; k++)
        used_bits[k] = 0;
    for (int k = 0; k < LIB_CAP; k++)
        used_set(k);
    for (int f = 0; f < LIB_FOLDERS; f++)
        fold_n[f] = 0;
    for (int k = 0; k < LIB_CAP; k++)
        if ((used_bits[k >> 5] >> (k & 31)) & 1u)
            fold_n[E(k)[13]]++;
    folder_tree();
}

int smp_lib_used(int k)                         /* entry K holds a sample */
{
    if (smp_lib_state != 2 || k < 0 || k >= LIB_CAP)
        return 0;
    return (used_bits[k >> 5] >> (k & 31)) & 1u;
}

/* v0.43: folders 64..127 (LIB_HI_AT): their header, read at boot; none there until it checks */
static u32 hi_sec[128] __attribute__((section(".data"), aligned(16)));
int smp_lib_hi __attribute__((section(".data"))) = 0;        /* 1: the header checks (records read) */
static u32 hi_check(void) { return ~hi_sec[0] ^ hi_sec[1] ^ hi_sec[2] ^ 0x3CC35AA5u; }

static void hi_read(void)
{
    u8 *hi = FOLD + LIB_FOLDERS_LO * LIB_FOLDER_BYTES;
    smp_lib_hi = 0;
    for (u32 k = 0; k < (LIB_FOLDERS - LIB_FOLDERS_LO) * LIB_FOLDER_BYTES; k++)
        hi[k] = 0;
    if (lib_rd(LIB_HI_AT, 512u, hi_sec) != 0 || hi_sec[0] != LIB_HI_MAGIC || hi_sec[1] != 1u
        || hi_sec[2] != LIB_FOLDERS || hi_sec[3] != hi_check())
        return;                                 /* none there (a library before v0.43) */
    if (lib_rd(LIB_HI_REC, LIB_HI_SECTORS * 512u, hi) != 0) {
        for (u32 k = 0; k < (LIB_FOLDERS - LIB_FOLDERS_LO) * LIB_FOLDER_BYTES; k++)
            hi[k] = 0;
        return;
    }
    smp_lib_hi = 1;
}

/* the records (all four sectors, as they are in RAM), then the header that makes them count */
static int hi_format(void)
{
    if (lib_wr(LIB_HI_REC, LIB_HI_SECTORS * 512u, FOLD + LIB_FOLDERS_LO * LIB_FOLDER_BYTES) != 0)
        return -1;
    for (int k = 0; k < 128; k++)
        hi_sec[k] = 0;
    hi_sec[0] = LIB_HI_MAGIC;
    hi_sec[1] = 1u;
    hi_sec[2] = LIB_FOLDERS;
    hi_sec[3] = hi_check();
    if (lib_wr(LIB_HI_AT, 512u, hi_sec) != 0)
        return -1;
    smp_lib_hi = 1;
    return 0;
}

static u32 sb_check(void) { return ~SB[0] ^ SB[1] ^ SB[2] ^ 0x5AA5C33Cu; }

static int sb_write(void)
{
    for (int k = 0; k < 128; k++)
        SB[k] = 0;
    SB[0] = LIB_MAGIC;
    SB[1] = LIB_VERSION;
    SB[2] = LIB_CAP_LO;                         /* v0.45: the superblock's capacity stays 2,048 (the extension's header says 16,384) */
    SB[3] = sb_check();
    return lib_wr(LIB_SECTOR, 512u, SB);
}

/* v0.45: the extension (entries 2,048..16,383) -- its header, read at boot; none there until it checks */
static u32 x_sec[128] __attribute__((section(".data"), aligned(16)));
int smp_lib_x __attribute__((section(".data"))) = 0;         /* 1: the header checks (entries read) */
static u32 x_check(void) { return ~x_sec[0] ^ x_sec[1] ^ x_sec[2] ^ 0xA55AC33Cu; }

static void x_read(void)
{
    smp_lib_x = 0;
    for (u32 k = 0; k < (LIB_CAP - LIB_CAP_LO) * LIB_ENTRY; k++)
        IDXH[k] = 0;
    if (lib_rd(LIB_X_AT, 512u, x_sec) != 0 || x_sec[0] != LIB_X_MAGIC || x_sec[1] != 1u
        || x_sec[2] != LIB_CAP || x_sec[3] != x_check())
        return;                                 /* none there (a library before v0.45) */
    for (u32 s = 0; s < LIB_X_SECTORS; s += 64u)
        if (lib_rd(LIB_X_IDX + s, 64u * 512u, IDXH + 512u * s) != 0) {
            for (u32 k = 0; k < (LIB_CAP - LIB_CAP_LO) * LIB_ENTRY; k++)
                IDXH[k] = 0;
            return;
        }
    smp_lib_x = 1;
}

/* every extension sector as it is in RAM (all free but what is being written now), then the
 * header that makes them count */
static int x_format(void)
{
    for (u32 s = 0; s < LIB_X_SECTORS; s += 64u)
        if (lib_wr(LIB_X_IDX + s, 64u * 512u, IDXH + 512u * s) != 0)
            return -1;
    for (int k = 0; k < 128; k++)
        x_sec[k] = 0;
    x_sec[0] = LIB_X_MAGIC;
    x_sec[1] = 1u;
    x_sec[2] = LIB_CAP;
    x_sec[3] = x_check();
    if (lib_wr(LIB_X_AT, 512u, x_sec) != 0)
        return -1;
    smp_lib_x = 1;
    return 0;
}

static int index_sector_write(int k)            /* the index sector entry K is in */
{
    if ((u32)k < LIB_CAP_LO) {
        u32 s = (u32)k / (512u / LIB_ENTRY);
        return lib_wr(LIB_INDEX + s, 512u, IDX + 512u * s);
    }
    if (!smp_lib_x)                             /* v0.45: the first entry past 2,047 */
        return x_format();
    u32 s = ((u32)k - LIB_CAP_LO) / (512u / LIB_ENTRY);
    return lib_wr(LIB_X_IDX + s, 512u, IDXH + 512u * s);
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
    if (SB[0] != LIB_MAGIC || SB[1] != LIB_VERSION || SB[2] != LIB_CAP_LO || SB[3] != sb_check()) {
        smp_lib_state = 1;
        return;
    }
    if (lib_rd(LIB_INDEX, LIB_INDEX_SECTORS * 512u, IDX) != 0
        || lib_rd(LIB_FOLDER_AT, LIB_FOLDER_SECTORS * 512u, FOLD) != 0) {
        smp_lib_state = -1;
        return;
    }
    hi_read();
    x_read();
    used_all();
    smp_lib_state = 2;
}

/* folder F's record: NAME, at the top (PARENT -1: 31 characters at most, byte 31 0, as
 * every build before v0.40 wrote) or inside PARENT (30 at most, byte 31 its tag) */
static void folder_set_in(int f, const char *name, int parent)
{
    u8 *d = FOLD + LIB_FOLDER_BYTES * (u32)f;
    u32 k = 0, max = parent >= 0 ? LIB_FOLDER_BYTES - 2u : LIB_FOLDER_BYTES - 1u;
    for (; k < max && name[k]; k++)
        d[k] = (u8)name[k];
    for (; k < LIB_FOLDER_BYTES; k++)
        d[k] = 0;
    if (parent >= 0 && name[0])                 /* v0.43: a parent past 63, 0xC0 | (it - 64) */
        d[LIB_FOLDER_BYTES - 1] = (u8)(parent < LIB_FOLDERS_LO ? 0x80u | (u32)parent : 0xC0u | ((u32)parent - LIB_FOLDERS_LO));
}

static void folder_set(int f, const char *name) { folder_set_in(f, name, -1); }

/* v0.40: one folder record's sector (16 records a sector): a change to a folder writes the
 * one sector it is in, never the other three (before: all four, 2 KB, at each change) */
static int folder_write(int f)
{
    u32 s = (u32)f / (512u / LIB_FOLDER_BYTES);
    if (f < LIB_FOLDERS_LO)
        return lib_wr(LIB_FOLDER_AT + s, 512u, FOLD + 512u * s);
    if (!smp_lib_hi)                            /* v0.43: the first folder past 63: all four, the header */
        return hi_format();
    return lib_wr(LIB_HI_REC + (s - LIB_FOLDER_SECTORS), 512u, FOLD + 512u * s);
}

/* a fresh, empty library: the folders, the index zeroed, then the superblock last */
static int lib_format(void)
{
    if (smp_lib_state != 1)
        return smp_lib_state == 2 ? 0 : -1;
    for (u32 k = 0; k < LIB_CAP_LO * LIB_ENTRY; k++)
        IDX[k] = 0;
    for (u32 k = 0; k < (LIB_CAP - LIB_CAP_LO) * LIB_ENTRY; k++)
        IDXH[k] = 0;                            /* (the extension: made with its first entry) */
    for (u32 k = 0; k < LIB_FOLDERS * LIB_FOLDER_BYTES; k++)
        FOLD[k] = 0;
    folder_set(0, "INCOMING");
    folder_set(1, "RECORDED");
    for (int k = 0; k < 128; k++)
        x_sec[k] = 0;                           /* v0.45: an older library's extension, if any, no longer counts */
    smp_lib_x = 0;
    if (lib_wr(LIB_INDEX, LIB_INDEX_SECTORS * 512u, IDX) != 0
        || lib_wr(LIB_FOLDER_AT, LIB_FOLDER_SECTORS * 512u, FOLD) != 0 || hi_format() != 0
        || lib_wr(LIB_X_AT, 512u, x_sec) != 0 || sb_write() != 0)
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
 * first sector, 0: none. v0.45: the extents sorted by their start (a shell sort in the
 * mirror's scratch), then one pass: 16,384 entries in a few hundred thousand steps (v0.31..
 * v0.44 moved a candidate past overlapping extents pass after pass: up to n^2, too slow at
 * 16,384) */
static u32 lib_room(u32 sectors)
{
    u32 n = 0;
    for (int k = 0; k < LIB_CAP; k++)
        if (smp_lib_used(k)) {
            EXT[2 * n] = lget(E(k));
            EXT[2 * n + 1] = lget(E(k)) + lget(E(k) + 20);
            n++;
        }
    for (u32 gap = n / 2; gap > 0; gap = gap == 2 ? 1 : gap * 5 / 11) {
        for (u32 i = gap; i < n; i++) {
            u32 a = EXT[2 * i], z = EXT[2 * i + 1], j = i;
            while (j >= gap && EXT[2 * (j - gap)] > a) {
                EXT[2 * j] = EXT[2 * (j - gap)];
                EXT[2 * j + 1] = EXT[2 * (j - gap) + 1];
                j -= gap;
            }
            EXT[2 * j] = a;
            EXT[2 * j + 1] = z;
        }
    }
    u32 cand = LIB_DATA;
    for (u32 i = 0; i < n; i++) {
        if (EXT[2 * i] >= cand + sectors)
            break;                              /* the run before this extent is free */
        if (EXT[2 * i + 1] > cand)
            cand = EXT[2 * i + 1];
    }
    return cand < BLK_SECTORS && sectors <= BLK_SECTORS - cand ? cand : 0;
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

/* v0.40: the folder NAME inside PARENT (-1: the top), made if MAKE and new -> its index, or -1.
 * A top-level name compares as before (31 characters); one inside a folder is cut to 30. A
 * new folder goes into the first empty record; any folder whose record still names that
 * record as its parent (left by an older build's DELETE: shown at the top) is written as a
 * top-level folder first, so it never turns up inside the new one. Each write is the one
 * sector a record is in: a power cut leaves the folder made or not, never half. */
static int folder_find_in(int parent, const u8 *name, int make)
{
    int empty = -1;
    u32 max = parent >= 0 ? LIB_FOLDER_BYTES - 2u : LIB_FOLDER_BYTES - 1u;
    if (parent >= LIB_FOLDERS || (parent >= 0 && !FNAMED(parent)))
        return -1;
    for (int f = 0; f < LIB_FOLDERS; f++) {
        const u8 *d = FOLD + LIB_FOLDER_BYTES * (u32)f;
        if (!d[0]) {
            if (empty < 0)
                empty = f;
            continue;
        }
        if (smp_lib_fpar[f] != parent)
            continue;
        u32 k = 0;                              /* (a record's name ends by its byte 31: folder_tree) */
        while (k < max && d[k] && d[k] == name[k])
            k++;
        if (!d[k] && (k == max || !name[k]))    /* (NAME past MAX: cut there, as it is made) */
            return f;
    }
    if (!make || empty < 0 || !name[0] || (parent >= 0 && fold_dep[parent] >= LIB_DEPTH))
        return -1;
    for (int g = 0; g < LIB_FOLDERS; g++)
        if (g != empty && FNAMED(g) && (FTAG(g) & 0xC0u) == 0x80u && (FTAG(g) & 0x3Fu) == (u32)empty) {
            FTAG(g) = 0;
            if (folder_write(g) != 0)
                return -1;
        }
    folder_set_in(empty, (const char *)name, parent);
    int r = folder_write(empty);
    folder_tree();
    if (r != 0)
        return -1;
    smp_lib_rev++;
    return empty;
}

/* v0.40: link 17's name is a path, "TRANCE STARTER PACK/KICKS/808": each level found or
 * made inside the one before ('/' between levels; empty levels skipped). Past LIB_DEPTH the
 * rest of the path is not made: the deepest folder is the answer (its samples go there).
 * A name with no '/' is the top-level folder it always was. -> the last level's index, -1 */
static int folder_path(const u8 *path, u32 n, int *capped)
{
    int at = -1;
    u32 k = 0;
    *capped = 0;
    while (k < n && path[k]) {
        u8 part[LIB_FOLDER_BYTES];
        u32 j = 0;
        while (k < n && path[k] && path[k] != '/') {
            if (j < LIB_FOLDER_BYTES - 1u)
                part[j++] = path[k];
            k++;
        }
        int sep = k < n && path[k] == '/';
        while (sep && j > 0 && part[j - 1] == ' ')  /* "PACK / KICKS": "PACK", then "KICKS" (a */
            j--;                                /* name with no '/' is kept as it came) */
        for (u32 z = j; z < LIB_FOLDER_BYTES; z++)
            part[z] = 0;
        if (sep) {
            k++;
            while (k < n && path[k] == ' ')
                k++;
        }
        if (!j)
            continue;
        if (at >= 0 && fold_dep[at] >= LIB_DEPTH) {
            *capped = 1;
            break;
        }
        int f = folder_find_in(at, part, 1);
        if (f < 0)
            return -1;
        at = f;
    }
    return at;
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
        put32(rp + r, LIB_FOLDERS); r += 4;     /* v0.43: the folders it holds (64 before) */
        return r;
    }
    if (cmd == 17) {                            /* FOLDER name -> its index (made if new); */
        int capped;                             /* v0.40: a path, each level inside the last */
        int f = lib_format() == 0 && n > 3 ? folder_path(rq + 3, n - 3 > 200u ? 200u : n - 3, &capped) : -1;
        if (f < 0)
            *st = 1;
        rp[r++] = (u8)(f < 0 ? 0xFF : f);
        return r;
    }
    if (cmd == 30) {                            /* v0.40: FOLDER IN parent (0xFF: the top), name */
        u8 name[LIB_FOLDER_BYTES];              /*   -> its index, flags (1 made, 2 the parent at */
        int parent = n >= 4 && rq[3] != 0xFFu ? rq[3] : -1;     /* LIB_DEPTH: the parent given) */
        for (u32 k = 0; k < LIB_FOLDER_BYTES; k++)
            name[k] = 4 + k < n && k < LIB_FOLDER_BYTES - 1 ? rq[4 + k] : 0;
        int f = -1, fl = 0;
        if (n >= 5 && lib_format() == 0 && parent < LIB_FOLDERS && (parent < 0 || FNAMED(parent))) {
            if (parent >= 0 && fold_dep[parent] >= LIB_DEPTH) {
                f = parent;
                fl = 2;
            } else {
                int was = folder_find_in(parent, name, 0);
                f = was >= 0 ? was : folder_find_in(parent, name, 1);
                fl = was < 0 && f >= 0;
            }
        }
        if (f < 0)
            *st = 1;
        rp[r++] = (u8)(f < 0 ? 0xFF : f);
        rp[r++] = (u8)fl;
        return r;
    }
    if (cmd == 31) {                            /* v0.40: TREE -> LIB_DEPTH, then each folder's */
        rp[r++] = LIB_DEPTH;                    /*   parent as the browser takes it (0xFF the top) */
        /* v0.43: 64 folders a reply from folder rq[3] (the reply holds 132 bytes; 0 without it,
         * as v0.40..v0.42 answered), so the page asks again at 64 when INFO says 128 */
        int from = n >= 4 ? (int)rq[3] : 0;
        for (int f = from; f < from + 64; f++)
            rp[r++] = f < LIB_FOLDERS && smp_lib_state == 2 && smp_lib_fpar[f] >= 0 ? (u8)smp_lib_fpar[f] : 0xFFu;
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
    if (cmd == 26) {                            /* v0.35: DROP FOLDER F (empty, not 0 or 1) */
        u32 f = n >= 4 ? rq[3] : 0xFFu;
        extern int smp_lib_folder_drop(int f);
        if (f >= LIB_FOLDERS || smp_lib_folder_drop((int)f) != 0)
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

/* v0.33: MOVE SELECTED / MOVE HERE (as the DT2's 13.6.5): entry K into folder F */
int smp_lib_move(int k, int f)
{
    if (!smp_lib_used(k) || f < 0 || f >= LIB_FOLDERS || !FOLD[LIB_FOLDER_BYTES * (u32)f])
        return -1;
    u8 *e = E(k);
    if (e[13] == (u8)f)
        return 0;
    e[13] = (u8)f;
    lput(e + 60, entry_check(e));
    used_all();
    return index_sector_write(k);
}

/* v0.33: CREATE FOLDER: NAME's folder (made if new) -> its index, -1 none (full, or the
 * +Drive refused) */
int smp_lib_folder_make_in(int parent, const char *name)    /* v0.40: inside PARENT (-1 the top) */
{
    u8 nm[LIB_FOLDER_BYTES];
    for (u32 k = 0; k < LIB_FOLDER_BYTES; k++)
        nm[k] = 0;
    for (u32 k = 0; k < LIB_FOLDER_BYTES - 1 && name[k]; k++)
        nm[k] = (u8)name[k];
    return lib_format() == 0 ? folder_find_in(parent, nm, 1) : -1;
}

int smp_lib_folder_make(const char *name) { return smp_lib_folder_make_in(-1, name); }

/* v0.33: DELETE on an empty folder takes the folder away (the 64 are not used up by NEW
 * FOLDER's); INCOMING (0) and RECORDED (1) stay */
int smp_lib_folder_drop(int f)
{
    if (smp_lib_state != 2 || f < 2 || f >= LIB_FOLDERS || fold_n[f] > 0 || !FOLD[LIB_FOLDER_BYTES * (u32)f])
        return -1;
    for (int g = 0; g < LIB_FOLDERS; g++)       /* v0.40: nor while a folder is inside it */
        if (smp_lib_fpar[g] == f)
            return -1;
    folder_set(f, "");
    used_all();
    return folder_write(f);
}

/* v0.40: the tree, for the browser (smp_page.c) */
int smp_lib_folder_parent(int f) { return smp_lib_state == 2 && f >= 0 && f < LIB_FOLDERS ? smp_lib_fpar[f] : -1; }
int smp_lib_folder_depth(int f) { return smp_lib_state == 2 && f >= 0 && f < LIB_FOLDERS ? fold_dep[f] : 0; }
int smp_lib_folder_under(int g, int f)          /* G is F or inside it, any depth */
{
    if (smp_lib_state != 2 || f < 0 || f >= LIB_FOLDERS)
        return 0;
    for (int d = 0; g >= 0 && g < LIB_FOLDERS && d <= LIB_DEPTH; d++, g = smp_lib_fpar[g])
        if (g == f)
            return 1;
    return 0;
}
int smp_lib_folder_room(int f)                  /* a folder can be made inside F (-1: the top) */
{
    return f < 0 || (smp_lib_state == 2 && f < LIB_FOLDERS && FNAMED(f) && fold_dep[f] < LIB_DEPTH);
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
/* v0.39: the adler-32 of entry K's frames (its +16, checked at END): what it is, wherever it lies */
u32 smp_lib_sum(int k) { return smp_lib_used(k) ? lget(E(k) + 16) : 0; }
int smp_lib_fmt(int k) { return smp_lib_used(k) ? E(k)[12] : 0; }

u8 *smp_lib_stage(void) { return LSTAGE; }      /* link.c's LOAD TO PROJECT copies through it */
int smp_lib_busy(void) { return w_idx >= 0; }   /* a send from the computer is using it */

void smp_lib_refresh(void) { if (smp_lib_state == 2) used_all(); }   /* the index changed in RAM */

int smp_lib_folder_count(int f)                 /* samples in folder F */
{
    return smp_lib_state == 2 && f >= 0 && f < LIB_FOLDERS ? fold_n[f] : 0;
}
