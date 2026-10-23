/* The sample link on the ColdFire (v0.16, docs/sampler.md): your samples on the +Drive,
 * loaded into the DSP's pool; the DSP's recordings saved back to the +Drive.
 *
 *   computer --USB SysEx--> smp_rx --> the +Drive's pool image (eMMC, 64 KB at a time)
 *   +Drive --smp_poll, 64 KB a chunk--> the TDM link (smp_tdm, a 124-word packet a period)
 *        or, if that does not verify, the frame's spare words (smp_feed, 6 words a frame)
 *        --> the pool (DSP DDR)
 *   DSP --SEND, the TDM link back (smp_tdm)--> 64 KB at a time --> the +Drive
 *
 * The +Drive keeps an IMAGE of the pool as the DSP holds it, byte for byte: directory,
 * names, then each sound's frames (dnfw.sampler.live.pool_bytes), and since v0.16 the
 * recorder's slots too. Ours is a region of the eMMC the DN2 never uses: the stock
 * storage code reads and writes nothing above 2,224 MiB (docs/drive-storage-research.md);
 * ours starts at sector 0x600000 (3 GiB): a header sector, then the image. Read and
 * written through the stock block driver (0x4012c59a / 0x4012c780, under its own mutex),
 * and only inside that region and inside the device.
 *
 * Loading: at power-on (and after a send), the image's directory decides what is read:
 * each slot's frames, then the directory last, so no slot points at frames not yet there.
 * Every chunk is checked: the DSP adds up the words it now holds (VERIFY) and the sums
 * must be the ColdFire's own. A chunk that does not check out is sent again; twice wrong
 * on the TDM link and the link is set aside for the frame's words (slow, but always there).
 *
 * The TDM link (docs/link-research.md): ColdFire -> DSP in slots 8..15, which stock never
 * fills with data and the DSP never reads; DSP -> ColdFire in slots 14..15, which neither
 * side's stock code touches. Each slot carries a 16-bit unit under the tag byte 0xA5
 * (dnfw.sampler.machines), so either justification of the 24 bits on the wire decodes.
 *
 * SysEx: F0 00 20 3C 7D 01 <pack7 body> F7, over USB only.
 *   request  <u16 seq, u8 cmd, args>        reply  <u16 seq, u8 cmd|0x80, u8 status, data>
 *   1 HELLO   -> u16 proto (3), u32 image bytes the +Drive can hold, u32 pool's DSP address
 *   2 WRITE   u32 offset, data -> into the image being sent (after BEGIN, in order)
 *   3 STATUS  -> u32 image bytes, u32 load state, u32 bytes loaded, u32 chunks retried,
 *                u32 fast link (1 on, 0 set aside), u32 frames
 *   4 CLEAR   -> nothing (kept for the old tool)
 *   5 SAVE    -> nothing to do: the image is the +Drive's (u32 its bytes)
 *   6 LOAD    -> load the +Drive's image into the DSP again
 *   7 FORGET  -> the +Drive's image is marked empty (its header sector zeroed)
 *   8 BEGIN   u32 bytes -> a new image follows (the old one is marked empty first)
 *   9 END     -> the image is complete: its header is written, and it is loaded
 *
 * Nothing here writes anything but its own RAM, the eMMC region above, the frame's spare
 * words and the TDM slots above.
 */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define SYSEX_SEND ((int (*)(const u8 *, u32, void *, u32))0x401233F2u)  /* (buf, len, abort*, port) */
#define PORT_USB 2
#define CTL_FRAME ((volatile u16 *)0x80005E60u)                          /* the frame pushed each tick */
#define FRAMES (*(volatile u32 *)0x4058E8D4u)

/* dnfw.sampler.machines' constants come from the build (cpage.py's defines): SMP_MIRROR,
 * SMP_POOL_DDR, POOL_BYTES, the link's and the pool's, the recorder's, the commands', the
 * TDM link's */
#if !defined(POOL_BYTES) || !defined(REC_OFFSET) || !defined(TX_WORDS) || !defined(SMP_MIRROR)
#error "the sampler's constants are passed by the build (dnfw.waverider.cpage)"
#endif
#define REC_DIR_START (8u + 16u * 123u)          /* the recorder's entries: REC_FIRST.. */
#define REC_DIR_END (8u + 16u * 127u)            /* .. REC_FIRST + REC_SLOTS */
_Static_assert(REC_DIR_START == 8u + 16u * REC_FIRST && REC_DIR_END == 8u + 16u * (REC_FIRST + REC_SLOTS),
               "the recorder's directory entries");
_Static_assert(SMP_MIRROR_BYTES >= 0x10000u + 3u * 0x10000u, "the stages fit in our RAM");

#define REPLY_TAIL ((volatile u16 *)0x80005E40u)                    /* 0x800053a4 + 0xa9c: the DSP's status */
#define TDM_TX(h) ((volatile u32 *)(0x4E6E0100u + ((u32)(h) << 11)))
#define TDM_RX(h) ((volatile u32 *)(0x4E6DF100u + ((u32)(h) << 11)))

#define PROTO 3
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
#define STORE_SECTORS (1u + POOL_BYTES / 512u)
#define STORE_MAGIC_V1 0x444E3250u                                  /* 'DN2P' (v0.13..v0.15) */
#define STORE_MAGIC 0x444E3251u                                     /* 'DN2Q' (v0.16) */
#define RQ_MAX 600
#define TX_MAX 160

#define CHUNK 0x10000u                          /* 64 KB */
#define CHUNK_WORDS (CHUNK / 4u)
#define DIR_BYTES DATA_OFFSET                   /* the directory page: directory and names */
_Static_assert(CMD_OFFSET % 4u == 0 && CMD_OFFSET >= 8u + 16u * POOL_SLOTS + NAME_BYTES * POOL_SLOTS,
               "the command block lies after the directory and the names");
#define OVERVIEW_W 100

/* our RAM (the mirror's 5 MB, laid out anew in v0.16) */
#define DIR ((u8 *)SMP_MIRROR)                                      /* the image's directory page */
#define OVERVIEW ((u8 *)(SMP_MIRROR + 0x1000u))                     /* 128 x 100 column peaks */
#define SLICE_MAX 64                                                /* v0.19, SLICE: a slot's slices */
#define SLICECOL ((u8 *)(SMP_MIRROR + 0x5000u))                     /* 128 x 64 slice starts, columns */
_Static_assert(0x1000u + POOL_SLOTS * OVERVIEW_W <= 0x5000u && 0x5000u + POOL_SLOTS * SLICE_MAX <= 0x10000u,
               "the overview and the slice columns fit below the stages");
#define STAGE(k) ((u8 *)(SMP_MIRROR + 0x10000u + (u32)(k) * CHUNK))   /* 0: loading, 1: saving, 2: upload */

static u8 rq[RQ_MAX] __attribute__((section(".data")));
static u8 rp[48] __attribute__((section(".data")));
static u8 tx[TX_MAX] __attribute__((section(".data")));
static u32 hdr[128] __attribute__((section(".data"), aligned(16)));   /* one sector */
int smp_booted __attribute__((section(".data"))) = 0;
u32 smp_cmds __attribute__((section(".data"))) = 0;                /* commands sent */
u32 smp_hi __attribute__((section(".data"))) = 0;                  /* the image's bytes (0: none) */
u32 smp_walk __attribute__((section(".data"))) = 0;                /* bytes loaded into the DSP */
static int dir_ok __attribute__((section(".data"))) = 0;          /* DIR holds a whole directory */

static u32 checksum(const u8 *p, u32 n)
{
    u32 a = 1, b = 0;
    for (u32 k = 0; k < n; k++) {
        a += p[k];
        b += a;
    }
    return b << 16 ^ a;
}

static u32 le32(const u8 *p)
{
    return p[0] | p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24;
}

static void put_le32(u8 *p, u32 v)
{
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}

/* -- commands to the DSP: a queue, each sent for a few frames ------------------------------ */

#define CMDQ 8
#define CMD_REPEAT 8u
static volatile u32 cmdq[CMDQ][6] __attribute__((section(".data")));
static volatile u32 cmd_head __attribute__((section(".data"))) = 0;   /* written by the UI */
static volatile u32 cmd_tail __attribute__((section(".data"))) = 0;   /* by the frame ISR */
static volatile u32 cmd_left __attribute__((section(".data"))) = 0;
static u32 cmd_seq __attribute__((section(".data"))) = 0;

/* the DSP's next command (dnfw.sampler.program.recorder); -> its sequence number, which
 * the DSP acts on once. A full queue drops the oldest. */
u32 smp_command(u32 cmd, u32 src, u32 chan, u32 thres, u32 dest_frames)
{
    u32 h = cmd_head;
    if (h - cmd_tail >= CMDQ)
        cmd_tail = h - CMDQ + 1;
    volatile u32 *c = cmdq[h % CMDQ];
    c[0] = ++cmd_seq;
    c[1] = cmd;
    c[2] = src;
    c[3] = chan;
    c[4] = thres;
    c[5] = dest_frames;
    smp_cmds++;
    cmd_head = h + 1;
    return cmd_seq;
}

/* the DSP's status from the SPI reply's tail, if it checks out: 16 halves */
int smp_status(u16 *out)
{
    u32 sum = LINK_SEED;
    for (int k = 0; k < 16; k++)
        out[k] = REPLY_TAIL[k];
    for (int k = 0; k < 15; k++)
        sum += out[k];
    return (out[0] & 0xFF00u) == STATUS_MAGIC && (u16)sum == out[15];
}

/* -- what is being sent to the DSP: a job of pool words, from a stage ------------------------ */

static const u8 *volatile job_data __attribute__((section(".data"))) = 0;
static volatile u32 job_base __attribute__((section(".data"))) = 0;   /* its first word's offset */
static volatile u32 job_n __attribute__((section(".data"))) = 0;      /* its words */
static volatile u32 job_fast_next __attribute__((section(".data"))) = 0;
static volatile u32 job_slow_next __attribute__((section(".data"))) = 0;
static volatile int fast_on __attribute__((section(".data"))) = 1;   /* the TDM link, until it fails */
static volatile u32 rx_seq __attribute__((section(".data"))) = 0;
u32 smp_tdm_sent __attribute__((section(".data"))) = 0;
u32 smp_tdm_heard __attribute__((section(".data"))) = 0;

static void send(u32 o, const u32 *words)
{
    volatile u16 *mb = CTL_FRAME + LINK_OFFSET / 2;
    u16 h[16];
    u32 w = o >> 2;
    h[0] = LINK_MAGIC;
    h[1] = (u16)w;
    h[2] = (u16)(w >> 16);
    for (int j = 0; j < 6; j++) {
        h[3 + 2 * j] = (u16)words[j];
        h[4 + 2 * j] = (u16)(words[j] >> 16);
    }
    u32 sum = LINK_SEED;
    for (int k = 0; k < 15; k++)
        sum += h[k];
    h[15] = (u16)sum;
    for (int k = 0; k < 16; k++)
        mb[k] = h[k];
}

/* from the frame builder (hooks.S), every frame: a command, or six words of a slow job */
void smp_feed(void)
{
    if (cmd_tail != cmd_head) {
        u32 c[6];
        for (int j = 0; j < 6; j++)
            c[j] = cmdq[cmd_tail % CMDQ][j];
        send(CMD_OFFSET, c);
        if (++cmd_left >= CMD_REPEAT) {
            cmd_left = 0;
            cmd_tail++;
        }
        return;
    }
    if (fast_on || !job_data || job_slow_next >= job_n)
        return;                                 /* nothing for the frame: stock's words stay */
    u32 c[6], k = job_slow_next, n = job_n - k;
    if (n > 6) {
        k = k > job_n - 6 ? job_n - 6 : k;      /* (a job's last packet ends at its end) */
        n = 6;
    } else if (job_n >= 6) {
        k = job_n - 6;
        n = 6;
    }
    for (u32 j = 0; j < 6; j++)
        c[j] = j < n ? le32(job_data + 4u * (k + j)) : 0;
    send((job_base + k) * 4u, c);
    job_slow_next = k + 6;
}

/* from the audio ISR (hooks.S, smp_tdm_hook), every period, after stock has filled its
 * half H of the transmit window: our packet into slots 8..15; and the DSP's, if any, out
 * of slots 14..15 of the receive window */
static volatile u8 *rx_dest __attribute__((section(".data"))) = 0; /* where SEND's words go */
static volatile u32 rx_base __attribute__((section(".data"))) = 0;   /* their first word's offset */
static volatile u32 rx_n __attribute__((section(".data"))) = 0;
static volatile u32 rx_have[CHUNK_WORDS / TX_WORDS / 32 + 1] __attribute__((section(".data")));

static volatile u32 periods __attribute__((section(".data"))) = 0;   /* smp_tdm's calls */

void smp_tdm(u32 h)
{
    periods++;
    if (fast_on && job_data && job_fast_next < job_n) {
        volatile u32 *t = TDM_TX(h);
        u32 k = job_fast_next, n = job_n - k, off = job_base + k;
        if (n > RX_WORDS)
            n = RX_WORDS;
        u32 sum = LINK_SEED, u;
        static u32 seq __attribute__((section(".data"))) = 0;
#define UNIT(i, v) do { u = (v) & 0xFFFFu; t[16 * ((i) >> 3) + 8 + ((i) & 7)] = TDM_TAG << 16 | u; sum += u; } while (0)
        UNIT(0, RX_MAGIC);
        UNIT(1, seq);
        UNIT(2, off);
        UNIT(3, off >> 16);
        for (u32 j = 0; j < RX_WORDS; j++) {
            u32 w = j < n ? le32(job_data + 4u * (k + j)) : 0;
            UNIT(4 + 2 * j, w);
            UNIT(5 + 2 * j, w >> 16);
        }
        UNIT(252, n);
        UNIT(253, 0);
        UNIT(254, 0);
        t[16 * 31 + 8 + 7] = TDM_TAG << 16 | (sum & 0xFFFFu);
#undef UNIT
        seq++;
        job_fast_next = k + n;
        smp_tdm_sent++;
    }
    /* the DSP's packet: 64 units in slots 14..15, frame by frame */
    volatile u32 *r = TDM_RX(h);
    u16 v[64];
    u32 sum = LINK_SEED, w0 = r[14], sh;
    /* the justification, from the magic: right (TAG << 16 | v, as stock's slots arrive)
     * or left (TAG << 24 | v << 8); then every unit is read the same way */
    if (((w0 >> 16) & 0xFF) == TDM_TAG && (u16)w0 == TX_MAGIC)
        sh = 0;
    else if ((w0 >> 24) == TDM_TAG && (u16)(w0 >> 8) == TX_MAGIC)
        sh = 8;
    else
        return;
    for (int i = 0; i < 64; i++) {
        u32 w = r[16 * (i >> 1) + 14 + (i & 1)] >> sh;
        if (((w >> 16) & 0xFF) != TDM_TAG)
            return;
        v[i] = (u16)w;
        if (i < 63)
            sum += v[i];
    }
    if (v[0] != TX_MAGIC || (u16)sum != v[63])
        return;
    smp_tdm_heard++;
    rx_seq = v[1];
    u32 off = v[2] | (u32)v[3] << 16, n = v[62];
    if (!rx_dest || n > TX_WORDS || off < rx_base || off + n > rx_base + rx_n)
        return;
    volatile u8 *d = rx_dest + (off - rx_base) * 4u;
    for (u32 j = 0; j < n; j++) {
        u32 w = v[4 + 2 * j] | (u32)v[5 + 2 * j] << 16;
        d[4 * j] = w; d[4 * j + 1] = w >> 8; d[4 * j + 2] = w >> 16; d[4 * j + 3] = w >> 24;
    }
    u32 p = (off - rx_base) / TX_WORDS;         /* SEND's packets start at multiples of 29 */
    rx_have[p >> 5] |= 1u << (p & 31);
}

/* -- the +Drive's image ------------------------------------------------------------------- */

/* the region is ours and inside the device, or nothing is touched */
static int store_ok(void)
{
    return BLK_READY && BLK_SECTORS >= STORE_SECTOR + STORE_SECTORS
           && STORE_SECTOR >= STORE_FLOOR;                            /* above the stock store */
}

static int image_read(u32 off, u32 bytes, void *buf)              /* OFF, BYTES: 512-aligned */
{
    if (!store_ok() || off + bytes > POOL_BYTES || (off | bytes) & 511u)
        return -1;
    return BLK_READ(STORE_SECTOR + 1u + off / 512u, bytes, buf);
}

static int image_write(u32 off, u32 bytes, const void *buf)
{
    if (!store_ok() || off + bytes > POOL_BYTES || (off | bytes) & 511u)
        return -1;
    return BLK_WRITE(STORE_SECTOR + 1u + off / 512u, bytes, buf);
}

static int header_write(u32 bytes)              /* 0 marks the image empty */
{
    if (!store_ok())
        return -1;
    for (int k = 0; k < 128; k++)
        hdr[k] = 0;
    if (bytes) {
        hdr[0] = STORE_MAGIC;
        hdr[1] = 2;
        hdr[2] = bytes;
        hdr[3] = checksum(DIR, DIR_BYTES);
        hdr[4] = ~hdr[0] ^ hdr[2] ^ hdr[3];
    }
    return BLK_WRITE(STORE_SECTOR, 512u, hdr);
}

/* -> the image's bytes if the header is ours and the directory page checks out (it is
 * then in DIR), else 0. v0.13..v0.15's images ('DN2P') are the same layout. */
static u32 header_read(void)
{
    if (!store_ok() || BLK_READ(STORE_SECTOR, 512u, hdr) != 0)
        return 0;
    u32 bytes = hdr[2];
    if ((hdr[0] != STORE_MAGIC && hdr[0] != STORE_MAGIC_V1) || bytes < DIR_BYTES
        || bytes > POOL_BYTES || hdr[4] != (~hdr[0] ^ hdr[2] ^ hdr[3]))
        return 0;
    if (image_read(0, DIR_BYTES, DIR) != 0 || le32(DIR) != POOL_MAGIC)
        return 0;
    if (hdr[0] == STORE_MAGIC && checksum(DIR, DIR_BYTES) != hdr[3])
        return 0;
    return bytes;
}

/* -- the pages' view of the pool ------------------------------------------------------------ */

int smp_count(void)
{
    if (!dir_ok)
        return 0;                               /* v0.17: no image, no samples (no test sounds) */
    u32 count = le32(DIR + 4);
    return count > POOL_SLOTS ? -1 : (int)count;
}

const char *smp_name(int k)
{
    return (const char *)(DIR + NAMES_OFFSET + NAME_BYTES * k);
}

/* slot K's waveform, OVERVIEW_W column peaks 0..255, or 0 if none has been seen */
const u8 *smp_overview(int k)
{
    if (k < 0 || k >= POOL_SLOTS)
        return 0;
    const u8 *o = OVERVIEW + OVERVIEW_W * k;
    for (int j = 0; j < OVERVIEW_W; j++)
        if (o[j])
            return o;
    return 0;
}

/* v0.19, SLICE: a slot's slices (its entry's byte 13) and where its table lies in the pool
 * (after its frames, on a word: dnfw.sampler.live.pool_bytes) */
static u32 slice_table(const u8 *e, u32 *n)
{
    u32 addr = le32(e), fr = le32(e + 4), fmt = e[12];
    *n = e[13] > SLICE_MAX ? SLICE_MAX : e[13];
    return ((addr - SMP_POOL_DDR) + fr * (fmt ? 2u : 4u) + 3u) & ~3u;
}

/* the slices' starts as overview columns, for the page; 0xFF where none */
const u8 *smp_slices(int k, int *n)
{
    if (k < 0 || k >= POOL_SLOTS || !dir_ok)
        return 0;
    u32 ns;
    slice_table(DIR + 8 + 16 * k, &ns);
    *n = (int)ns;
    return ns ? SLICECOL + SLICE_MAX * k : 0;
}

static void slices_add(u32 off, u32 bytes, const u8 *buf)
{
    if (!dir_ok)
        return;
    for (int k = 0; k < POOL_SLOTS; k++) {
        const u8 *e = DIR + 8 + 16 * k;
        u32 ns, fr = le32(e + 4);
        if (le32(e) < SMP_POOL_DDR || fr < 2)
            continue;
        u32 t = slice_table(e, &ns);
        for (u32 j = 0; j < ns; j++) {
            u32 at = t + 12u * j;                           /* slice j's start */
            if (at < off || at + 4u > off + bytes)
                continue;
            u32 s = le32(buf + (at - off));
            SLICECOL[SLICE_MAX * k + j] = (u8)(s >= fr ? OVERVIEW_W - 1 : s / (fr / (OVERVIEW_W - 1) + 1u));
        }
    }
}

/* the overview of the slots whose frames lie in [OFF, OFF + BYTES) of the pool, from BUF */
static void overview_add(u32 off, u32 bytes, const u8 *buf)
{
    if (!dir_ok)
        return;
    for (int k = 0; k < POOL_SLOTS; k++) {
        const u8 *e = DIR + 8 + 16 * k;
        u32 addr = le32(e), fr = le32(e + 4), fmt = e[12];
        if (addr < SMP_POOL_DDR || fr < 2 || fmt != 1)
            continue;
        u32 lo = addr - SMP_POOL_DDR, hi = lo + fr * 2u;
        if (hi <= off || lo >= off + bytes)
            continue;
        u8 *o = OVERVIEW + OVERVIEW_W * k;
        u32 a = lo > off ? lo : off, b = hi < off + bytes ? hi : off + bytes;
        for (u32 x = a & ~1u; x + 1 < b; x += 32) {            /* every 16th frame will do */
            if (x < lo)
                continue;
            u32 i = (x - lo) / 2u;
            int s = (short)(buf[x - off] | buf[x - off + 1] << 8);
            if (s < 0) s = -s;
            u32 col = (i >> 6) * OVERVIEW_W / ((fr >> 6) + 1);     /* 32-bit: no libgcc */
            u8 pk = (u8)(s >> 7);
            if (col < OVERVIEW_W && pk > o[col])
                o[col] = pk;
        }
    }
}

/* -- loading the image into the DSP -------------------------------------------------------- */

enum { L_IDLE, L_READ, L_SEND, L_VERIFY, L_DONE };
int smp_lstate __attribute__((section(".data"))) = L_IDLE;
static u32 l_slot __attribute__((section(".data"))) = 0;        /* the range being loaded */
static u32 l_off __attribute__((section(".data"))) = 0;         /* in it, bytes */
static u32 l_end __attribute__((section(".data"))) = 0;
static u32 l_chunk_off __attribute__((section(".data"))) = 0;   /* the chunk in the stage */
static u32 l_chunk_bytes __attribute__((section(".data"))) = 0;
static u32 l_vseq __attribute__((section(".data"))) = 0;
static u32 l_since __attribute__((section(".data"))) = 0;
static u32 l_tries __attribute__((section(".data"))) = 0;
u32 smp_retries __attribute__((section(".data"))) = 0;
static u16 st[16] __attribute__((section(".data")));

/* the next range to load: first the directory page with every entry empty (the names and
 * the count, so the page can name the slots, and nothing points at frames not yet there);
 * then each used slot's frames, the recorder's included, and at once that slot's entry,
 * so a slot plays as soon as it is in; last the whole directory page again. -> 0 when done */
enum { K_BLANK, K_FRAMES, K_ENTRY, K_FULL };
static int l_kind __attribute__((section(".data"))) = K_BLANK;
static int l_entry __attribute__((section(".data"))) = -1;       /* the entry due next */

static int next_range(void)
{
    if (l_slot == 0 && l_kind == K_BLANK && l_end == 0) {
        l_off = 0;
        l_end = CMD_OFFSET;                     /* up to the command block: the DSP's */
        return 1;
    }
    if (l_entry >= 0) {
        l_kind = K_ENTRY;
        l_off = 8u + 16u * (u32)l_entry;
        l_end = l_off + 16u;
        l_entry = -1;
        return 1;
    }
    while (l_slot < POOL_SLOTS) {
        u32 k = l_slot++;
        const u8 *e = DIR + 8 + 16 * k;
        u32 addr = le32(e), fr = le32(e + 4), fmt = e[12];
        if (addr < SMP_POOL_DDR + DATA_OFFSET || fr == 0)
            continue;
        u32 lo = addr - SMP_POOL_DDR, bytes = fr * (fmt ? 2u : 4u);
        u32 ns, tbl = slice_table(e, &ns);                  /* v0.19: and its slices, if any */
        if (ns)
            bytes = tbl - lo + 12u * ns;
        if (lo >= POOL_BYTES || bytes > POOL_BYTES - lo)
            continue;
        l_kind = K_FRAMES;
        l_off = lo & ~511u;
        l_end = (lo + bytes + 511u) & ~511u;
        if (l_end > POOL_BYTES)
            l_end = POOL_BYTES;
        l_entry = (int)k;
        return 1;
    }
    if (l_slot == POOL_SLOTS) {                 /* last: the whole directory page */
        l_slot++;
        l_kind = K_FULL;
        l_off = 0;
        l_end = CMD_OFFSET;
        return 1;
    }
    return 0;
}

static void job_start(const u8 *data, u32 off, u32 bytes)
{
    job_data = 0;
    job_base = off / 4u;
    job_n = bytes / 4u;
    job_fast_next = 0;
    job_slow_next = 0;
    job_data = data;
}

static int job_sent(void)
{
    return fast_on ? job_fast_next >= job_n : job_slow_next >= job_n;
}

/* the two sums VERIFY makes (dnfw.sampler.program.verify_step) of the pool's words as they
 * are in memory (little-endian), over BUF */
static void sums(const u8 *buf, u32 words, u32 *a, u32 *b)
{
    u32 x = 0, y = 0;
    for (u32 k = 0; k < words; k++) {
        x += le32(buf + 4 * k);
        y += x;
    }
    *a = x;
    *b = y;
}

void smp_load(void)                             /* load (again) whatever the image holds */
{
    smp_hi = header_read();
    dir_ok = smp_hi != 0;
    if (!dir_ok) {
        smp_lstate = L_IDLE;
        return;
    }
    for (u32 k = 0; k < POOL_SLOTS * OVERVIEW_W; k++)
        OVERVIEW[k] = 0;
    for (u32 k = 0; k < POOL_SLOTS * SLICE_MAX; k++)
        SLICECOL[k] = 0;
    smp_walk = 0;
    l_slot = 0;
    l_kind = K_BLANK;
    l_entry = -1;
    l_end = 0;
    smp_lstate = next_range() ? L_READ : L_DONE;
}

static void load_poll(void)
{
    if (smp_lstate == L_READ) {
        u32 n = l_end - l_off;
        if (n > CHUNK)
            n = CHUNK;
        if (l_kind == K_FRAMES) {
            if (image_read(l_off, n, STAGE(0)) != 0) {
                smp_lstate = L_IDLE;                            /* the +Drive refused: stop */
                return;
            }
            overview_add(l_off, n, STAGE(0));
            slices_add(l_off, n, STAGE(0));
        } else {                                            /* the directory page's: from DIR */
            for (u32 k = 0; k < n; k++)
                STAGE(0)[k] = DIR[l_off + k];
            if (l_kind == K_BLANK)
                for (u32 k = 8; k < 8u + 16u * POOL_SLOTS; k++)
                    STAGE(0)[k] = 0;
        }
        l_chunk_off = l_off;
        l_chunk_bytes = n;
        l_tries = 0;
        job_start(STAGE(0), l_off, n);
        l_since = 0;
        smp_lstate = L_SEND;
    } else if (smp_lstate == L_SEND) {
        if (!job_sent())
            return;
        if (!l_since) {                         /* a few periods for the last packets to land */
            l_since = periods | 1;
            return;
        }
        if (periods - l_since < 6u)
            return;
        l_vseq = smp_command(CMD_VERIFY, l_chunk_off / 4u, l_chunk_bytes / 4u, 0, 0) & 0xFFFFu;
        l_since = periods;
        smp_lstate = L_VERIFY;
    } else if (smp_lstate == L_VERIFY) {
        int ok = smp_status(st);
        if (ok && st[14] == l_vseq) {
            u32 a, b;
            sums(STAGE(0), l_chunk_bytes / 4u, &a, &b);
            if ((st[10] | (u32)st[11] << 16) == a && (st[12] | (u32)st[13] << 16) == b) {
                if (l_kind == K_FRAMES)
                    smp_walk += l_chunk_bytes;
                l_off += l_chunk_bytes;
                smp_lstate = l_off < l_end || next_range() ? L_READ : L_DONE;
                return;
            }
        } else if (periods - l_since < 1500u) {
            return;                                         /* a second for the DSP to answer */
        }
        smp_retries++;                                      /* wrong, or no answer: again */
        if (++l_tries >= 2 && fast_on)
            fast_on = 0;                                    /* the TDM link is set aside */
        if (l_tries > 6) {
            smp_lstate = L_IDLE;                                /* nothing gets through: stop */
            return;
        }
        job_start(STAGE(0), l_chunk_off, l_chunk_bytes);
        l_since = 0;
        smp_lstate = L_SEND;
    }
}

/* -- saving the recorder's slots to the image ------------------------------------------------ */

extern int rec_state;
extern u32 rec_frames;
extern int rec_dest_taken;                      /* the slot the last recording went into */
int smp_saved __attribute__((section(".data"))) = 0;      /* 1 saved, -1 failed, 0 neither */
static int sstate __attribute__((section(".data"))) = 0;
static u32 s_slot __attribute__((section(".data"))) = 0;
static u32 s_off __attribute__((section(".data"))) = 0;  /* bytes, in the pool */
static u32 s_end __attribute__((section(".data"))) = 0;
static u32 s_n __attribute__((section(".data"))) = 0;    /* this window's words */
static u32 s_since __attribute__((section(".data"))) = 0;
static u32 s_tries __attribute__((section(".data"))) = 0;
static u32 s_frames __attribute__((section(".data"))) = 0;

/* from rec.c when a recording is done: SLOT 0..3, FRAMES recorded */
void smp_save_recording(int slot, u32 frames)
{
    if (!store_ok() || frames == 0 || sstate)
        return;
    s_slot = (u32)slot & 3u;
    s_frames = frames;
    s_off = REC_OFFSET + (s_slot << REC_SLOT_SHIFT);
    s_end = s_off + ((frames * 2u + 511u) & ~511u);
    smp_saved = 0;
    sstate = 1;
}

static void save_window(void)
{
    u32 n = s_end - s_off;
    if (n > CHUNK)
        n = CHUNK;
    s_n = n / 4u;
    for (u32 k = 0; k < sizeof rx_have / sizeof rx_have[0]; k++)
        rx_have[k] = 0;
    rx_dest = 0;
    rx_base = s_off / 4u;
    rx_n = s_n;
    rx_dest = STAGE(1);
    smp_command(CMD_SEND, s_off / 4u, s_n, 0, 0);
    s_since = periods;
    s_tries = 0;
    sstate = 2;
}

static int window_whole(void)
{
    u32 packets = (s_n + TX_WORDS - 1) / TX_WORDS;
    for (u32 p = 0; p < packets; p++)
        if (!(rx_have[p >> 5] & 1u << (p & 31)))
            return 0;
    return 1;
}

static void save_poll(void)
{
    if (sstate == 1) {
        save_window();
    } else if (sstate == 2) {
        if (window_whole()) {
            rx_dest = 0;
            if (image_write(s_off, s_n * 4u, STAGE(1)) != 0) {
                sstate = 0;
                smp_saved = -1;
                return;
            }
            overview_add(s_off, s_n * 4u, STAGE(1));
            s_off += s_n * 4u;
            if (s_off < s_end) {
                save_window();
                return;
            }
            /* the slot's directory entry, into the image's directory page */
            u8 *e = DIR + 8 + 16 * (REC_FIRST + s_slot);
            put_le32(e, SMP_POOL_DDR + REC_OFFSET + (s_slot << REC_SLOT_SHIFT));
            put_le32(e + 4, s_frames);
            put_le32(e + 8, 0x3F800000u);                    /* rate 1.0 */
            put_le32(e + 12, 1);                             /* int16 */
            u32 bytes = smp_hi > s_end ? smp_hi : s_end;
            if (!dir_ok) {                                   /* no image yet: an empty pool */
                for (u32 k = 0; k < DIR_BYTES; k++)
                    if (k < 8 + 16 * REC_FIRST || k >= REC_DIR_END)
                        DIR[k] = 0;
                put_le32(DIR, POOL_MAGIC);
                dir_ok = 1;
            }
            if (image_write(0, DIR_BYTES, DIR) != 0 || header_write(bytes) != 0) {
                sstate = 0;
                smp_saved = -1;
                return;
            }
            smp_hi = bytes;
            sstate = 0;
            smp_saved = 1;
        } else if (periods - s_since > 3000u) {               /* two seconds: ask again */
            if (++s_tries > 3) {
                rx_dest = 0;
                sstate = 0;
                smp_saved = -1;                              /* the link back is not there */
                return;
            }
            smp_command(CMD_SEND, s_off / 4u, s_n, 0, 0);
            s_since = periods;
        }
    }
}

/* from the UI loop (page.c's wr_poll), every pass */
void smp_boot(void)
{
    if (!smp_booted && BLK_READY) {
        smp_booted = 1;
        smp_load();
    }
    load_poll();
    save_poll();
}

/* -- USB ------------------------------------------------------------------------------------ */

static u32 up_bytes __attribute__((section(".data"))) = 0;       /* BEGIN's size; 0: none */
static u32 up_block __attribute__((section(".data"))) = 0xFFFFFFFFu;   /* STAGE(2)'s offset */
static u32 up_fill __attribute__((section(".data"))) = 0;

static int up_flush(void)
{
    if (up_block == 0xFFFFFFFFu)
        return 0;
    u32 n = up_fill;
    if (n == 0)
        return 0;
    n = (n + 511u) & ~511u;
    if (up_block == 0) {                        /* the directory page: yours, but the */
        for (u32 k = 0; k < DIR_BYTES; k++)     /* recorder's entries stay the +Drive's */
            if (k < REC_DIR_START || k >= REC_DIR_END)
                DIR[k] = STAGE(2)[k];
            else
                STAGE(2)[k] = DIR[k];
    }
    int r = image_write(up_block, n, STAGE(2));
    up_block = 0xFFFFFFFFu;
    up_fill = 0;
    return r;
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

static const u8 sx_hdr[6] = {0xF0, 0x00, 0x20, 0x3C, 0x7D, 0x01};

/* from the SysEx router (hooks.S, smp_rx_hook): MSG F0..F7, LEN bytes, from SOURCE.
 * Anything not ours, or not from USB, is left to the router as it was. */
void smp_rx(const u8 *msg, u32 len, u32 source)
{
    if (source != 2 && source != 4)
        return;
    if (len < 10 || len > 7 + (RQ_MAX * 8) / 7)
        return;
    for (int k = 0; k < 6; k++)
        if (msg[k] != sx_hdr[k])
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
        put32(rp + r, REC_OFFSET); r += 4;      /* the image's room for yours */
        put32(rp + r, SMP_POOL_DDR); r += 4;
    } else if (cmd == 2) {                      /* WRITE, in order, after BEGIN */
        u32 at = n >= 7 ? get32(rq + 3) : 0, k = n >= 7 ? n - 7 : 0;
        if (!up_bytes || n < 7 || at > up_bytes || k > up_bytes - at || at + k > REC_OFFSET) {
            rp[3] = 1;
        } else {
            for (u32 j = 0; j < k; j++) {
                u32 a = at + j, b = a & ~(CHUNK - 1u);
                if (b != up_block) {
                    if (up_flush() != 0) {
                        rp[3] = 3;
                        break;
                    }
                    up_block = b;
                    for (u32 z = 0; z < CHUNK; z++)
                        STAGE(2)[z] = 0;
                }
                STAGE(2)[a - b] = rq[7 + j];
                if (a - b + 1 > up_fill)
                    up_fill = a - b + 1;
            }
            put32(rp + r, at + k); r += 4;
        }
    } else if (cmd == 3) {                      /* STATUS */
        put32(rp + r, smp_hi); r += 4;
        put32(rp + r, (u32)smp_lstate); r += 4;
        put32(rp + r, smp_walk); r += 4;
        put32(rp + r, smp_retries); r += 4;
        put32(rp + r, (u32)fast_on); r += 4;
        put32(rp + r, FRAMES); r += 4;
    } else if (cmd == 4 || cmd == 5) {          /* CLEAR, SAVE: nothing to do */
        put32(rp + r, smp_hi); r += 4;
    } else if (cmd == 6) {                      /* LOAD */
        smp_load();
        if (!smp_hi)
            rp[3] = 1;
        put32(rp + r, smp_hi); r += 4;
    } else if (cmd == 7) {                      /* FORGET */
        if (header_write(0) != 0)
            rp[3] = 1;
        smp_hi = 0;
    } else if (cmd == 8) {                      /* BEGIN */
        u32 bytes = n >= 7 ? get32(rq + 3) : 0;
        if (bytes < DIR_BYTES || bytes > REC_OFFSET || header_write(0) != 0) {
            rp[3] = 1;
        } else {
            smp_lstate = L_IDLE;                    /* no load runs while the image changes */
            job_data = 0;
            if (!dir_ok)                        /* no recordings kept yet */
                for (u32 k = REC_DIR_START; k < REC_DIR_END; k++)
                    DIR[k] = 0;
            dir_ok = 0;
            up_bytes = bytes;
            up_block = 0xFFFFFFFFu;
            up_fill = 0;
        }
    } else if (cmd == 9) {                      /* END */
        u32 bytes = up_bytes;
        for (u32 k = REC_FIRST; k < REC_FIRST + REC_SLOTS; k++) {   /* and the recordings' */
            const u8 *e = DIR + 8 + 16 * k;
            u32 a = le32(e), f = le32(e + 4);
            if (a >= SMP_POOL_DDR + REC_OFFSET && a - SMP_POOL_DDR + f * 2u > bytes)
                bytes = a - SMP_POOL_DDR + f * 2u;
        }
        bytes = (bytes + 511u) & ~511u;
        if (bytes > POOL_BYTES)
            bytes = POOL_BYTES;
        if (!up_bytes || up_flush() != 0 || le32(DIR) != POOL_MAGIC
            || header_write(bytes) != 0) {
            rp[3] = 1;
        } else {
            smp_load();
        }
        up_bytes = 0;
        put32(rp + r, smp_hi); r += 4;
    } else {
        rp[3] = 2;
    }
    for (int k = 0; k < 6; k++)
        tx[k] = sx_hdr[k];
    u32 m = 6 + pack7(rp, r, tx + 6);
    tx[m++] = 0xF7;
    SYSEX_SEND(tx, m, 0, PORT_USB);
}
