/* The sample link on the ColdFire (v0.14, docs/sampler.md): your samples into the DSP's
 * pool.
 *
 *   computer --USB SysEx--> smp_rx --> the mirror (ColdFire RAM) --smp_feed, a packet a
 *   frame--> the DSP (dnfw.sampler.program.mailbox) --> the pool (DSP DDR)
 *
 * The mirror is the pool as the DSP holds it, byte for byte: the host
 * (tools/dn2samples.py) builds it (dnfw.sampler.live.pool_bytes) and writes it here in
 * pieces. The feeder walks it from 0 to its high-water mark again and again, one 24-byte
 * packet a frame (1,500 a second, 36 KB/s), so a frame the DSP misses is put right on the
 * next pass. A write moves the walk back to it, so what was just sent goes out first.
 *
 * SysEx: F0 00 20 3C 7D 01 <pack7 body> F7, over USB only. Device 0x7D is above the
 * router's bound (stock drops it) and sub-id 01 is ours (the read-only probe is 00).
 *   request  <u16 seq, u8 cmd, args>        reply  <u16 seq, u8 cmd|0x80, u8 status, data>
 *   1 HELLO   -> u16 proto, u32 mirror bytes, u32 pool's DSP address
 *   2 WRITE   u32 offset, data (to the end)  -> status 1 if it would leave the mirror
 *   3 STATUS  -> u32 high-water, u32 walk, u32 passes, u32 packets, u32 frames
 *   4 CLEAR   -> the walk stops (high-water 0); the DSP keeps what it has
 *   5 SAVE    -> the mirror to the +Drive (v0.15): u32 bytes written; status 1 if none
 *   6 LOAD    -> the +Drive's copy into the mirror: u32 bytes; status 1 if none or bad
 *   7 FORGET  -> the +Drive's copy is marked empty (its header sector zeroed)
 *
 * The +Drive copy (v0.15) is a region of the eMMC the DN2 never uses: the stock storage
 * code reads and writes nothing above 2,224 MiB (docs/drive-storage-research.md); ours
 * starts at sector 0x600000 (3 GiB), one header sector and then the mirror's bytes. Read
 * and written through the stock block driver (0x4012c59a / 0x4012c780, under its own
 * mutex), and only inside that region. At power-on the UI loop's first passes load it
 * (smp_boot, from wr_poll), so your samples come back without the computer.
 *
 * Nothing here writes anything but the mirror, its own counters and the frame's sixteen
 * words; no peripheral, no flash. The mirror is RAM above BSS, declared by the mod.
 */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define SYSEX_SEND ((int (*)(const u8 *, u32, void *, u32))0x401233F2u)  /* (buf, len, abort*, port) */
#define PORT_USB 2
#define CTL_FRAME ((volatile u16 *)0x80005E60u)                          /* the frame pushed each tick */
#define FRAMES (*(volatile u32 *)0x4058E8D4u)

#ifndef SMP_MIRROR
#define SMP_MIRROR 0x46B00000u
#define SMP_MIRROR_BYTES 0x00500000u
#define SMP_POOL_DDR 0x84000000u
#define LINK_OFFSET 2650
#define LINK_MAGIC 0x5A31
#define LINK_SEED 0x1D0F
#define POOL_MAGIC 0x31504D53u
#define NAMES_OFFSET 2056
#define NAME_BYTES 8
#define DATA_OFFSET 0x1000
#define POOL_SLOTS 128
#endif

#define PROTO 2
#define BLK_READ  ((int (*)(u32, u32, void *))0x4012C59Au)          /* (sector, bytes, buf) -> 0 ok */
#define BLK_WRITE ((int (*)(u32, u32, const void *))0x4012C780u)
#define BLK_READY (*(volatile u32 *)0x4461B68Cu)                    /* the device is up */
#define BLK_SECTORS (*(volatile u32 *)0x4461B6B0u)                  /* its size, sectors */
#ifndef STORE_SECTOR
#define STORE_SECTOR 0x600000u
#endif
#ifndef STORE_FLOOR
#define STORE_FLOOR 0x458000u                                       /* the stock store's end */
#endif
#define STORE_SECTORS (1u + SMP_MIRROR_BYTES / 512u)
#define STORE_MAGIC 0x444E3250u                                     /* 'DN2P' */
#define RQ_MAX 600
#define TX_MAX 160

static u8 *const mirror = (u8 *)SMP_MIRROR;

u32 smp_hi __attribute__((section(".data"))) = 0;       /* bytes of the mirror in use */
u32 smp_walk __attribute__((section(".data"))) = 0;     /* the next byte to send */
static u32 smp_passes __attribute__((section(".data"))) = 0;
static u32 smp_packets __attribute__((section(".data"))) = 0;
static u8 rq[RQ_MAX] __attribute__((section(".data")));
static u8 rp[48] __attribute__((section(".data")));
static u8 tx[TX_MAX] __attribute__((section(".data")));
static u32 store_hdr[128] __attribute__((section(".data"), aligned(16)));   /* one sector */
int smp_booted __attribute__((section(".data"))) = 0;

static u32 checksum(const u8 *p, u32 n)
{
    u32 a = 1, b = 0;
    for (u32 k = 0; k < n; k++) {
        a += p[k];
        b += a;
    }
    return b << 16 ^ a;
}

/* the region is ours and inside the device, or nothing is touched */
static int store_ok(void)
{
    return BLK_READY && BLK_SECTORS >= STORE_SECTOR + STORE_SECTORS
           && STORE_SECTOR >= STORE_FLOOR;                            /* above the stock store */
}

static u32 smp_save(void)
{
    u32 hi = smp_hi;
    if (hi < 8 || hi > SMP_MIRROR_BYTES || !store_ok())
        return 0;
    u32 bytes = (hi + 511u) & ~511u;
    if (BLK_WRITE(STORE_SECTOR + 1u, bytes, mirror) != 0)
        return 0;
    for (int k = 0; k < 128; k++)
        store_hdr[k] = 0;
    store_hdr[0] = STORE_MAGIC;
    store_hdr[1] = 1;
    store_hdr[2] = hi;
    store_hdr[3] = checksum(mirror, hi);
    store_hdr[4] = ~store_hdr[0] ^ store_hdr[2] ^ store_hdr[3];
    if (BLK_WRITE(STORE_SECTOR, 512u, store_hdr) != 0)
        return 0;
    return hi;
}

static u32 smp_load(void)
{
    if (!store_ok() || BLK_READ(STORE_SECTOR, 512u, store_hdr) != 0)
        return 0;
    u32 hi = store_hdr[2];
    if (store_hdr[0] != STORE_MAGIC || store_hdr[1] != 1 || hi < 8 || hi > SMP_MIRROR_BYTES
        || store_hdr[4] != (~store_hdr[0] ^ store_hdr[2] ^ store_hdr[3]))
        return 0;
    smp_hi = 0;                                 /* the feeder rests while the mirror changes */
    if (BLK_READ(STORE_SECTOR + 1u, (hi + 511u) & ~511u, mirror) != 0)
        return 0;
    if (checksum(mirror, hi) != store_hdr[3])
        return 0;
    smp_walk = 0;
    smp_hi = hi;
    return hi;
}

static int smp_forget(void)
{
    if (!store_ok())
        return 0;
    for (int k = 0; k < 128; k++)
        store_hdr[k] = 0;
    return BLK_WRITE(STORE_SECTOR, 512u, store_hdr) == 0;
}

/* from the UI loop (page.c's wr_poll), every pass until it has run once with the device
 * up: the +Drive's copy, if there is one, into the mirror */
void smp_boot(void)
{
    if (smp_booted || !BLK_READY)
        return;
    smp_booted = 1;
    if (smp_hi == 0)
        smp_load();
}

/* the frame builder has just built the frame: our packet over its words 2650..2681 */
void smp_feed(void)
{
    u32 hi = smp_hi, o = smp_walk;
    if (hi < 4 || hi > SMP_MIRROR_BYTES)
        return;                                 /* nothing to send: stock's words stay */
    if (o >= hi) {
        o = 0;
        smp_passes++;
    }
    volatile u16 *mb = CTL_FRAME + LINK_OFFSET / 2;
    u16 h[16];
    u32 w = o >> 2;
    h[0] = LINK_MAGIC;
    h[1] = (u16)w;
    h[2] = (u16)(w >> 16);
    const u8 *s = mirror + o;
    for (int j = 0; j < 6; j++) {               /* the pool's little-endian words */
        h[3 + 2 * j] = (u16)(s[4 * j] | s[4 * j + 1] << 8);
        h[4 + 2 * j] = (u16)(s[4 * j + 2] | s[4 * j + 3] << 8);
    }
    u32 sum = LINK_SEED;
    for (int k = 0; k < 15; k++)
        sum += h[k];
    h[15] = (u16)sum;
    for (int k = 0; k < 16; k++)
        mb[k] = h[k];
    smp_walk = o + 24;
    smp_packets++;
}

static u32 unpack7(const u8 *src, u32 n, u8 *dst, u32 room)
{
    u32 out = 0;
    while (n) {
        u8 top = *src++;
        n--;
        for (int k = 0; k < 7 && n; k++) {
            u8 b = *src++ & 0x7F;
            n--;
            if (top & (0x40 >> k))
                b |= 0x80;
            if (out < room)
                dst[out++] = b;
        }
    }
    return out;
}

static u32 pack7(const u8 *src, u32 n, u8 *dst)
{
    u32 out = 0;
    while (n) {
        u8 *head = dst + out++;
        u8 top = 0;
        for (int k = 0; k < 7 && n; k++, n--) {
            u8 b = *src++;
            if (b & 0x80)
                top |= 0x40 >> k;
            dst[out++] = b & 0x7F;
        }
        *head = top;
    }
    return out;
}

static void put32(u8 *p, u32 v)
{
    p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v;
}

static u32 get32(const u8 *p)
{
    return (u32)p[0] << 24 | (u32)p[1] << 16 | (u32)p[2] << 8 | p[3];
}

static const u8 hdr[6] = {0xF0, 0x00, 0x20, 0x3C, 0x7D, 0x01};

/* from the SysEx router (pages' smp_rx_hook): MSG F0..F7, LEN bytes, from SOURCE.
 * Anything not ours, or not from USB, is left to the router as it was. */
void smp_rx(const u8 *msg, u32 len, u32 source)
{
    if (source != 2 && source != 4)
        return;
    if (len < 10 || len > 7 + (RQ_MAX * 8) / 7)
        return;
    for (int k = 0; k < 6; k++)
        if (msg[k] != hdr[k])
            return;
    if (msg[len - 1] != 0xF7)
        return;
    u32 n = unpack7(msg + 6, len - 7, rq, RQ_MAX);
    if (n < 3)
        return;
    u8 cmd = rq[2];
    u32 r = 4;
    rp[0] = rq[0];
    rp[1] = rq[1];
    rp[2] = cmd | 0x80;
    rp[3] = 0;
    if (cmd == 1) {                             /* HELLO */
        rp[r++] = 0; rp[r++] = PROTO;
        put32(rp + r, SMP_MIRROR_BYTES); r += 4;
        put32(rp + r, SMP_POOL_DDR); r += 4;
    } else if (cmd == 2) {                      /* WRITE */
        u32 at = n >= 7 ? get32(rq + 3) : 0, k = n >= 7 ? n - 7 : 0;
        if (n < 7 || at > SMP_MIRROR_BYTES || k > SMP_MIRROR_BYTES - at) {
            rp[3] = 1;
        } else {
            for (u32 j = 0; j < k; j++)
                mirror[at + j] = rq[7 + j];
            if (at + k > smp_hi)
                smp_hi = (at + k + 3) & ~3u;
            if ((at & ~3u) < smp_walk)
                smp_walk = at & ~3u;
            put32(rp + r, smp_hi); r += 4;
        }
    } else if (cmd == 3) {                      /* STATUS */
        put32(rp + r, smp_hi); r += 4;
        put32(rp + r, smp_walk); r += 4;
        put32(rp + r, smp_passes); r += 4;
        put32(rp + r, smp_packets); r += 4;
        put32(rp + r, FRAMES); r += 4;
    } else if (cmd == 4) {                      /* CLEAR */
        smp_hi = 0;
        smp_walk = 0;
    } else if (cmd == 5 || cmd == 6) {          /* SAVE, LOAD */
        u32 n6 = cmd == 5 ? smp_save() : smp_load();
        if (!n6)
            rp[3] = 1;
        put32(rp + r, n6); r += 4;
    } else if (cmd == 7) {                      /* FORGET */
        if (!smp_forget())
            rp[3] = 1;
    } else {
        rp[3] = 2;
    }
    for (int k = 0; k < 6; k++)
        tx[k] = hdr[k];
    u32 m = 6 + pack7(rp, r, tx + 6);
    tx[m++] = 0xF7;
    SYSEX_SEND(tx, m, 0, PORT_USB);
}

/* for the pages: the mirror's pool, when one has been sent and is whole */
int smp_count(void)
{
    if (smp_hi < DATA_OFFSET)
        return -1;
    const u8 *d = mirror;
    u32 magic = d[0] | d[1] << 8 | (u32)d[2] << 16 | (u32)d[3] << 24;
    u32 count = d[4] | d[5] << 8 | (u32)d[6] << 16 | (u32)d[7] << 24;
    if (magic != POOL_MAGIC || count > POOL_SLOTS)
        return -1;
    return (int)count;
}

const char *smp_name(int k)
{
    return (const char *)(mirror + NAMES_OFFSET + NAME_BYTES * k);
}

/* for the page's waveform: slot K's bytes in the mirror (offset, frames, format), when the
 * mirror holds a whole pool and the slot's frames lie inside it */
int smp_entry(int k, u32 *off, u32 *frames, u32 *fmt)
{
    int n = smp_count();
    if (n < 0 || k < 0 || k >= n)
        return 0;
    const u8 *e = mirror + 8 + 16 * k;
    u32 addr = e[0] | e[1] << 8 | (u32)e[2] << 16 | (u32)e[3] << 24;
    u32 fr = e[4] | e[5] << 8 | (u32)e[6] << 16 | (u32)e[7] << 24;
    u32 f = e[12];
    u32 o = addr - SMP_POOL_DDR, bytes = fr * (f ? 2u : 4u);
    if (addr < SMP_POOL_DDR || o > smp_hi || bytes > smp_hi - o)
        return 0;
    *off = o;
    *frames = fr;
    *fmt = f;
    return 1;
}

/* the sample at frame I of the slot just looked up, -32768..32767 */
int smp_frame(u32 off, u32 fmt, u32 i)
{
    const u8 *s = mirror + off;
    if (fmt) {
        int v = s[2 * i] | s[2 * i + 1] << 8;
        return v >= 32768 ? v - 65536 : v;
    }
    /* float32 (the tool sends int16; this is for completeness): the top bits as a
     * rough magnitude, no FPU needed */
    u32 b = s[4 * i] | s[4 * i + 1] << 8 | (u32)s[4 * i + 2] << 16 | (u32)s[4 * i + 3] << 24;
    int e = (int)((b >> 23) & 0xFF) - 127;                  /* |x| ~ 2^e */
    int m = e >= 0 ? 32767 : e < -15 ? 0 : 32768 >> -e;
    return (b >> 31) ? -m : m;
}
