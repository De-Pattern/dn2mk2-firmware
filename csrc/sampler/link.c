/* The sample link on the ColdFire (v0.16, docs/sampler.md): your samples on the +Drive,
 * loaded into the DSP's pool; the DSP's recordings saved back to the +Drive.
 *
 *   computer --USB SysEx--> smp_rx --> the +Drive's pool image (eMMC, 64 KB at a time)
 *   +Drive --smp_poll, 64 KB a chunk--> the TDM link (smp_tdm, a 124-word packet a period)
 *        --> the pool (DSP DDR); the recorder's commands the same way, into the command block
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
 * must be the ColdFire's own. A chunk that does not check out is sent again; seven times
 * wrong and loading stops (STATUS reports the link down). v0.20: nothing goes by the
 * frame's words any more: the words at 2650.. that v0.14..v0.19 used are the DSP's
 * per-track routing (docs/link-research.md, "Who sets the two tables"), and writing
 * packets there is what made the stock voices buzz after a sample track was used.
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
 *  24 DIAG    -> v0.34: u32 guard wipes, u32 slot | type << 8, u32 where, u32 slots mask,
 *                u32 periods since the last wipe, u32 load %, u32 load peak (permille),
 *                u32 slots ever skipped for time, u32 periods, u32 frames, then the last
 *                SCAN's: u32 non-finite words, u32 the first one's index (0xFFFFFFFF none),
 *                u32 done (its sequence, low 16, when the range is scanned), u32 its sequence
 *  25 SCAN    u32 DSP byte address, u32 words -> u16 seq: the DSP counts the non-finite
 *                words there, VERIFY_CHUNK a block (docs/timing-model.md)
 *  26 DROP    u8 folder -> v0.35: an empty library folder (not INCOMING or RECORDED) removed;
 *                status 1 if it is not empty or not there (lib.c, with 16..23)
 *  27 ENTRY   u8 slot -> v0.35: its 16-byte pool entry (base, frames, rate, format word, little
 *                endian), its 8-byte short name, u32 the pool's DSP address
 *
 * Nothing here writes anything but its own RAM, the eMMC region above and the TDM slots
 * above. It never writes the frame (CTL_FRAME): test_sources checks the C for it.
 */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#include "banks.h"                              /* v0.65: global slots, banks B..D's pages */

#define SYSEX_SEND ((int (*)(const u8 *, u32, void *, u32))0x401233F2u)  /* (buf, len, abort*, port) */
#define PORT_USB 2
#define FRAMES (*(volatile u32 *)0x4058E8D4u)

/* dnfw.sampler.machines' constants come from the build (cpage.py's defines): SMP_MIRROR,
 * SMP_POOL_DDR, POOL_BYTES, the link's and the pool's, the recorder's, the commands', the
 * TDM link's */
#if !defined(POOL_BYTES) || !defined(REC_OFFSET) || !defined(REC_END) || !defined(TX_WORDS) || !defined(SMP_MIRROR)
#error "the sampler's constants are passed by the build (dnfw.waverider.cpage)"
#endif
/* v0.22: recordings go into [REC_OFFSET, REC_END) of the pool (96..128 MB), wherever there
 * is room, and into any slot (rec.c's DEST): a directory entry whose frames lie there is a
 * recording, kept on the +Drive and kept when the host tool sends a new image. Yours are
 * below it and above it, to POOL_BYTES (400 MB): the host tool skips the recordings' area. */
#define REC_BYTES (BANK_AREA - REC_OFFSET)        /* v0.23: the slice area follows; v0.26: the tables first; v0.65: banks B..D's pages */
/* v0.65: K is a global slot (banks.h): bank A's are DIR's, as before */
#define ENTRY(k) (page_of(G_BANK(k)) + 8u + 16u * G_SLOT(k))
#define NAME(k) (page_of(G_BANK(k)) + NAMES_OFFSET + NAME_BYTES * G_SLOT(k))
_Static_assert(SMP_MIRROR_BYTES >= 0x10000u + 3u * 0x10000u, "the stages fit in our RAM");

#define REPLY_TAIL ((volatile u16 *)0x80005E40u)                    /* 0x800053a4 + 0xa9c: the DSP's status */
#define TDM_TX(h) ((volatile u32 *)(0x4E6E0100u + ((u32)(h) << 11)))
#define TDM_RX(h) ((volatile u32 *)(0x4E6DF100u + ((u32)(h) << 11)))

#define PROTO 7                                 /* v0.40: FOLDER IN (30), TREE (31): folders in folders; v0.35: DROP (26); v0.31: the library (16..23); v0.22: 400 MB, the recordings' area a hole */
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
#define BANKS_MAGIC 0x314B4E42u                                     /* 'BNK1' (v0.65): words 5..9 of the header */
#define RQ_MAX 600
#define TX_MAX 160

#define CHUNK 0x10000u                          /* 64 KB */
#define CHUNK_WORDS (CHUNK / 4u)
#define DIR_BYTES DATA_OFFSET                   /* the directory page: directory and names */
_Static_assert(CMD_OFFSET % 4u == 0 && CMD_OFFSET >= 8u + 16u * POOL_SLOTS + NAME_BYTES * POOL_SLOTS,
               "the command block lies after the directory and the names");
#define OVERVIEW_W 100
/* v0.39: the library sample each slot was loaded from (dnfw.sampler.machines LIBID_OFFSET) */
#define LIBID(k) (page_of(G_BANK(k)) + LIBID_OFFSET + 4u * G_SLOT(k))
_Static_assert(LIBID_OFFSET >= META_PTR + 12u && LIBID_OFFSET % 4u == 0 && LIBID_OFFSET + 4u * REC_FIRST <= CMD_OFFSET,
               "the slots' library identities lie between the meta pointer and the command block");

/* our RAM (the mirror's 5 MB, laid out anew in v0.16) */
#define DIR ((u8 *)SMP_MIRROR)                                      /* the image's directory page */
#define OVERVIEW ((u8 *)(SMP_MIRROR + 0x1000u))                     /* 128 x 100 column peaks */
#define SLICE_MAX 64                                                /* v0.19, SLICE: a slot's slices */
#define SLICECOL ((u8 *)(SMP_MIRROR + 0x5000u))                     /* 128 x 64 slice starts, columns */
_Static_assert(0x1000u + POOL_SLOTS * OVERVIEW_W <= 0x5000u && 0x5000u + POOL_SLOTS * SLICE_MAX <= 0x10000u,
               "the overview and the slice columns fit below the stages");
#define STAGE(k) ((u8 *)(SMP_MIRROR + 0x10000u + (u32)(k) * CHUNK))   /* 0: loading, 1: saving, 2: upload, 3: analysis */
/* v0.23: the slice area's copy (SLICE_TABLE_BYTES a slot), the analysis' envelope and its
 * fine waveform */
#define SLICE_TB 768u
#define SLAREA_BYTES (POOL_SLOTS * SLICE_TB)
#define SLAREA ((u8 *)(SMP_MIRROR + 0x50000u))
#define ENV_MAX 16384u
#define ENV ((u32 *)(SMP_MIRROR + 0x68000u))
#define HIRES_W 1024u
#define HIRES ((u8 *)(SMP_MIRROR + 0x78000u))
_Static_assert(0x50000u + SLAREA_BYTES <= 0x68000u && 0x68000u + 4u * ENV_MAX <= 0x78000u
               && 0x78000u + HIRES_W <= SMP_MIRROR_BYTES, "the slice editor's RAM fits");
_Static_assert(SLICE_AREA + SLAREA_BYTES <= REC_END && SLICE_AREA % 512u == 0, "the slice area");

/* v0.65 banks: a page's RAM (A: DIR; B..D: BANK_RAM's copies) and its offset in the pool; a global
 * slot's overview, slice columns, slice table (its RAM copy and its pool offset) */
static u8 *page_of(u32 b) { return b ? BPAGE(b) : DIR; }
static u32 page_off(u32 b) { return b ? BPAGE_OFF(b) : 0u; }
#define OVW(k) ((u32)(k) < POOL_SLOTS ? OVERVIEW + OVERVIEW_W * (u32)(k) : BOVERVIEW(k))
#define SCOL(k) ((u32)(k) < POOL_SLOTS ? SLICECOL + SLICE_MAX * (u32)(k) : BSLICECOL(k))
#define SLTB(k) ((G_BANK(k) ? BPAGE(G_BANK(k)) + BANK_SLICES : SLAREA) + SLICE_TB * G_SLOT(k))
#define SLOFF(k) ((G_BANK(k) ? BPAGE_OFF(G_BANK(k)) + BANK_SLICES : SLICE_AREA) + SLICE_TB * G_SLOT(k))
_Static_assert(BANK_SLICES + SLAREA_BYTES <= BANK_PAGE && BANK_META + 0x2000u <= BANK_SLICES, "a bank's page");
/* banks B..D in use: not while an old recording lies where their pages go (smp_bank_blocked) */
int smp_bank_blocked __attribute__((section(".data"))) = 0;
extern int smp_dir_ok;
int smp_bank_live(int b)
{
    if (b == 0)
        return 1;
    if (b < 0 || b >= BANK_N || smp_bank_blocked || !smp_dir_ok)
        return 0;
    /* nor while another project's list names frames there (an older firmware's recording):
     * the pages are never written over them (pools.c's reserved extents) */
    extern u32 smp_pl_clash(u32 lo, u32 hi);
    if (smp_pl_clash(BANK_AREA, TABLE_AREA))
        return 0;
    const u8 *p = BPAGE(b);
    return ((u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24) == BANK_MAGIC;
}
/* the RAM a pool offset's bytes come from, for the pages and the slice areas: 0 none */
static u8 *ram_of(u32 off)
{
    if (off < DIR_BYTES)
        return DIR + off;
    if (off >= SLICE_AREA && off < SLICE_AREA + SLAREA_BYTES)
        return SLAREA + (off - SLICE_AREA);
    if (off >= BANK_AREA && off < BANK_AREA + 3u * BANK_PAGE)
        return BPAGE(1u + (off - BANK_AREA) / BANK_PAGE) + (off - BANK_AREA) % BANK_PAGE;
    return 0;
}

static u8 rq[RQ_MAX] __attribute__((section(".data")));
/* v0.40: the longest reply, LIST's four entries, is 132 bytes (4 + 4 + 4 x 31): rp was 96 and
 * LIST ran on into rq (read before, so harmless, but never meant). Packed, 132 fits TX_MAX */
static u8 rp[132] __attribute__((section(".data")));
_Static_assert(6u + 132u + (132u + 6u) / 7u + 1u <= TX_MAX, "the longest reply packs into tx");
static u8 tx[TX_MAX] __attribute__((section(".data")));
static u32 hdr[128] __attribute__((section(".data"), aligned(16)));   /* one sector */
int smp_booted __attribute__((section(".data"))) = 0;
u32 smp_cmds __attribute__((section(".data"))) = 0;                /* commands sent */
u32 smp_hi __attribute__((section(".data"))) = 0;                  /* the image's bytes (0: none) */
u32 smp_walk __attribute__((section(".data"))) = 0;                /* bytes loaded into the DSP */
int smp_dir_ok __attribute__((section(".data"))) = 0;            /* DIR holds a whole directory */
#define dir_ok smp_dir_ok
/* v0.22: the DSP's RAM check this power-on (dnfw.sampler.machines.CMD_PROBE): until it has
 * passed, nothing loads past RAM_PROVEN (what ran on the instrument before v0.22) */
int smp_ram __attribute__((section(".data"))) = 0;               /* 0 not yet, 1 passed, 2 failed or no answer */
static u32 ram_top __attribute__((section(".data"))) = RAM_PROVEN;
static u32 ram_seq __attribute__((section(".data"))) = 0;
static u32 ram_since __attribute__((section(".data"))) = 0;
static int rec_keep __attribute__((section(".data"))) = 0;        /* a send merges DIR's recordings (v0.22) */

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
#ifndef CMD_WORDS
#define CMD_WORDS 6u
#endif
#define CMD_REPEAT 8u
static volatile u32 cmdq[CMDQ][6] __attribute__((section(".data")));
static volatile u32 cmd_head __attribute__((section(".data"))) = 0;   /* written by the UI */
static volatile u32 cmd_tail __attribute__((section(".data"))) = 0;   /* by the audio ISR */
static volatile u32 cmd_left __attribute__((section(".data"))) = 0;
static u32 cmd_seq __attribute__((section(".data"))) = 0;

/* the DSP's next command (dnfw.sampler.program.recorder); -> its sequence number, which
 * the DSP acts on once. A full queue drops the oldest. */
static void span_drop(u32 lo, u32 hi);
/* v0.41: the UI's sequence numbers keep bit 15 of their low half clear: a buffer take's
 * (rectrig.c) has it set, and the DSP echoes the low half (rec.c tells them apart by it) */
static u32 next_seq(void)
{
    ++cmd_seq;
    if (cmd_seq & 0x8000u)
        cmd_seq += 0x8000u;
    return cmd_seq;
}

/* v0.41 (QREC, rectrig.c): a command's words with its sequence number, not queued: the
 * audio interrupt sends it at its boundary (smp_tdm) -> the sequence number */
u32 smp_command_words(u32 *w, u32 cmd, u32 src, u32 chan, u32 thres, u32 dest_frames)
{
    if (cmd == 1 || cmd == 2 || cmd == 5)
        span_drop(REC_OFFSET, REC_END);
    w[0] = next_seq();
    w[1] = cmd;
    w[2] = src;
    w[3] = chan;
    w[4] = thres;
    w[5] = dest_frames;
    smp_cmds++;
    return w[0];
}

u32 smp_command(u32 cmd, u32 src, u32 chan, u32 thres, u32 dest_frames)
{
    if (cmd == 1 || cmd == 2 || cmd == 5)       /* v0.38: ARM, NOW, ARM_PLAY: the DSP writes there */
        span_drop(REC_OFFSET, REC_END);
    u32 h = cmd_head;
    if (h - cmd_tail >= CMDQ)
        cmd_tail = h - CMDQ + 1;
    volatile u32 *c = cmdq[h % CMDQ];
    c[0] = next_seq();
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
static volatile int fast_on __attribute__((section(".data"))) = 1;   /* the TDM link: 0 once a load gave up */
static volatile u32 rx_seq __attribute__((section(".data"))) = 0;
u32 smp_tdm_sent __attribute__((section(".data"))) = 0;
u32 smp_tdm_heard __attribute__((section(".data"))) = 0;

/* from the audio ISR (hooks.S, smp_tdm_hook), every period, after stock has filled its
 * half H of the transmit window: our packet into slots 8..15; and the DSP's, if any, out
 * of slots 14..15 of the receive window */
static volatile u8 *rx_dest __attribute__((section(".data"))) = 0; /* where SEND's words go */
static volatile u32 rx_base __attribute__((section(".data"))) = 0;   /* their first word's offset */
static volatile u32 rx_n __attribute__((section(".data"))) = 0;
static volatile u32 rx_have[CHUNK_WORDS / TX_WORDS / 32 + 1] __attribute__((section(".data")));

volatile u32 smp_periods __attribute__((section(".data"))) = 0;   /* smp_tdm's calls */
#define periods smp_periods
/* v0.25: each track's play position as the DSP last sent it (POS_NONE: none; else its
 * fraction of the sample x POS_ONE), and when (periods) */
volatile u16 smp_pos[16] __attribute__((section(".data"))) = {0};
volatile u32 smp_pos_at __attribute__((section(".data"))) = 0;
/* v0.40: when each voice's note began (periods): its position appeared, or jumped (a new
 * note on the same voice), as the DSP's packets show it */
volatile u32 smp_pos_born[16] __attribute__((section(".data"))) = {0};
#define POS_JUMP (POS_ONE / 8u)                 /* more than any packet's advance: a new note */

void smp_pos_in(const volatile u16 *p)          /* the 16 voices' positions of a DSP packet */
{
    for (int t = 0; t < 16; t++) {
        u32 nv = p[t], ov = smp_pos[t];
        if (nv != POS_NONE && (ov == POS_NONE || (nv > ov ? nv - ov : ov - nv) > POS_JUMP))
            smp_pos_born[t] = periods;
        smp_pos[t] = (u16)nv;
    }
    smp_pos_at = periods;
}
/* v0.30: when the DSP's frame guard last left each slot silent (periods, 0 never): the
 * PERC and Monomachine pages show CPU, in place of the tempo, while any is recent (a user: VO-6 went silent after a
 * second -- this tells a DSP-time skip from anything else) */
volatile u32 smp_skip_at[16] __attribute__((section(".data"))) = {0};

int smp_skipped(int t)                          /* skipped within the last half second */
{
    if (t < 0 || t > 15 || !smp_skip_at[t])
        return 0;
    return (int)(periods - smp_skip_at[t]) < 750;   /* v0.40 review: signed (the stamp is | 1) */
}

/* v0.32: the DSP's load, the peak of the last half second, from the idle packets (unit 18,
 * permille; dnfw.perc.guard.meter); -1 while none came in the last second */
volatile u32 smp_load_peak __attribute__((section(".data"))) = 0;
volatile u32 smp_load_at __attribute__((section(".data"))) = 0;
volatile u32 smp_load_seen __attribute__((section(".data"))) = 0;

/* v0.34: the DSP's output guard's record (dnfw.perc.guard BLOWN_*; docs/timing-model.md):
 * from the idle packets' units 19..22. A voice that went non-finite was wiped; this says
 * which, its machine, and where its memory first held a non-finite word, so the unit itself
 * can say what poisons a voice (the owner's O13: P-I machines dead on the same voices) */
volatile u32 smp_blown_count __attribute__((section(".data"))) = 0;   /* the DSP's count (16-bit) */
volatile u32 smp_blown_info __attribute__((section(".data"))) = 0;    /* slot | type << 8 */
volatile u32 smp_blown_where __attribute__((section(".data"))) = 0xFFFF;
volatile u32 smp_blown_mask __attribute__((section(".data"))) = 0;    /* slots, cumulative this power-on */
volatile u32 smp_blown_at __attribute__((section(".data"))) = 0;      /* periods | 1 when the count last moved */
static u32 scan_seq __attribute__((section(".data"))) = 0;           /* the last SCAN's sequence (SysEx 25) */

int smp_blown_recent(void)                      /* the last two seconds */
{
    return smp_blown_at && (int)(periods - smp_blown_at) < 3000;   /* v0.40 review: signed */
}

int smp_dsp_load(void)
{
    if (!smp_load_seen || (int)(periods - smp_load_seen) > 1500)  /* v0.40 review: signed */
        return -1;
    return (int)((smp_load_peak + 5u) / 10u);      /* percent */
}

int smp_skipped_any(void)                       /* any voice, within the last half second */
{
    for (int t = 0; t < 16; t++)
        if (smp_skipped(t))
            return 1;
    return 0;
}

/* track T's playhead as a fraction x POS_ONE, or -1: none (nothing playing, or no news from
 * the DSP for a while) */
/* v0.30: the DSP sends a position per VOICE (its slot's state), not per track; with the
 * DN2's voice allocation track t's notes play on any voice (docs/link-research.md: the
 * ColdFire's slot -> track table 0x80005308, which the frame builder sends as the DSP's
 * routing). v0.25..v0.29 drew voice t's position for track t: right only while voice t
 * played track t (the owner: the playing-slice marker lagged the sound). Now the voices
 * the table gives to track t, the newest note's; none there: voice t's, as before.
 * v0.40 (owner: "the slice machine's on-screen indicators are a little slow to catch up"):
 * v0.30..v0.39 took the voice whose position was LOWEST as the newest note's: on SLICE, a
 * slice later in the sample played after an earlier one (still sounding on its voice, its
 * release) was not shown until the earlier one ended. Now the voice whose note began last
 * (smp_pos_born), the lowest position only between notes begun in the same period. */
#define SLOT_TRACK ((volatile u32 *)0x80005308u)
int smp_playhead(int t)
{
    if (t < 0 || t > 15 || periods - smp_pos_at > 64u)
        return -1;
    u32 best = POS_NONE, age = 0;
    for (int v = 0; v < 16; v++) {
        u32 tr = SLOT_TRACK[v], pos = smp_pos[v], a = periods - smp_pos_born[v];
        if (tr != (u32)t || pos == POS_NONE)
            continue;
        if (best == POS_NONE || a < age || (a == age && pos < best)) {
            best = pos;
            age = a;
        }
    }
    if (best == POS_NONE)
        best = smp_pos[t];
    return best == POS_NONE ? -1 : (int)best;
}

/* v0.38 (pools.c): a project LOAD or NEW in the OS's task bumps smp_blank_req (hooks.S);
 * the next packets, ahead of any job, empty the DSP's 128 directory entries, so from the
 * moment the OS starts on another project no sample track plays the old pool's samples.
 * Not checked (pools.c's K_BLANK, checked, follows); the job in flight is sent again. */
volatile u32 smp_blank_req __attribute__((section(".data"))) = 0;
static u32 blank_seen __attribute__((section(".data"))) = 0;
static u32 blank_left __attribute__((section(".data"))) = 0;
#define ENTRY_WORDS (4u * POOL_SLOTS)
#define BLANK_PACKETS ((ENTRY_WORDS + RX_WORDS - 1u) / RX_WORDS)
u32 smp_blank_sent __attribute__((section(".data"))) = 0;

/* v0.41 (rectrig.c): a REC trig's command, and a QREC take's at its boundary, each sent as a
 * queued one is (CMD_REPEAT packets), ahead of the queue but never in the middle of a queued
 * command's repeats (the DSP would take that one again after: a STOP would end the take) */
extern volatile u32 rt_w[6], rt_gen, q_w[6], q_fire;
static u32 rt_seen __attribute__((section(".data"))) = 0;
static u32 q_seen __attribute__((section(".data"))) = 0;
static u32 rt_left __attribute__((section(".data"))) = 0;
static u32 rt_cw[CMD_WORDS] __attribute__((section(".data")));
u32 smp_rt_sent __attribute__((section(".data"))) = 0;     /* (for the checks) */

static int rt_take(volatile u32 *w, volatile u32 *gen, u32 *seen)
{
    u32 g = *gen;
    if (g == *seen)
        return 0;
    for (int j = 0; j < CMD_WORDS; j++)
        rt_cw[j] = w[j];
    if (*gen != g)
        return 0;                               /* rewritten as it was read: the next period */
    *seen = g;
    rt_left = CMD_REPEAT;
    return 1;
}

void smp_tdm(u32 h)
{
    periods++;
    u32 cw[CMD_WORDS];
    if (smp_blank_req != blank_seen) {
        blank_seen = smp_blank_req;
        blank_left = BLANK_PACKETS;
        job_fast_next = job_n;                  /* (its check fails: the loader sends it again) */
    }
    if (!rt_left && !cmd_left && !rt_take(rt_w, &rt_gen, &rt_seen))
        rt_take(q_w, &q_fire, &q_seen);
    int is_rt = rt_left != 0;
    int is_cmd = is_rt || cmd_tail != cmd_head;
    int is_blank = !is_cmd && blank_left;
    if (is_rt)
        for (int j = 0; j < CMD_WORDS; j++)
            cw[j] = rt_cw[j];
    else if (is_cmd)                            /* a command first: the command block's words */
        for (int j = 0; j < CMD_WORDS; j++)
            cw[j] = cmdq[cmd_tail % CMDQ][j];
    if (is_cmd || is_blank || (job_data && job_fast_next < job_n)) {
        volatile u32 *t = TDM_TX(h);
        u32 k = job_fast_next, n = job_n - k, off = job_base + k;
        if (is_cmd) {
            k = 0;
            n = CMD_WORDS;
            off = CMD_OFFSET / 4u;
        } else if (is_blank) {
            u32 at = (BLANK_PACKETS - blank_left) * RX_WORDS;
            k = 0;
            off = 2u + at;                      /* the entries: bytes 8 .. 8 + 16 x 128 */
            n = ENTRY_WORDS - at < RX_WORDS ? ENTRY_WORDS - at : RX_WORDS;
        } else if (n > RX_WORDS) {
            n = RX_WORDS;
        }
        u32 sum = LINK_SEED, u;
        static u32 seq __attribute__((section(".data"))) = 0;
#define UNIT(i, v) do { u = (v) & 0xFFFFu; t[16 * ((i) >> 3) + 8 + ((i) & 7)] = TDM_TAG << 16 | u; sum += u; } while (0)
        UNIT(0, RX_MAGIC);
        UNIT(1, seq);
        UNIT(2, off);
        UNIT(3, off >> 16);
        for (u32 j = 0; j < RX_WORDS; j++) {
            u32 w = j >= n || is_blank ? 0 : is_cmd ? cw[j] : le32(job_data + 4u * (k + j));
            UNIT(4 + 2 * j, w);
            UNIT(5 + 2 * j, w >> 16);
        }
        UNIT(252, n);
        UNIT(253, 0);
        UNIT(254, 0);
        t[16 * 31 + 8 + 7] = TDM_TAG << 16 | (sum & 0xFFFFu);
#undef UNIT
        seq++;
        if (is_blank) {
            blank_left--;
            smp_blank_sent++;
        } else if (!is_cmd)
            job_fast_next = k + n;
        else if (is_rt) {
            if (--rt_left == 0)
                smp_rt_sent++;
        } else if (++cmd_left >= CMD_REPEAT) {    /* sent a few times: one may be lost */
            cmd_left = 0;
            cmd_tail++;
        }
        smp_tdm_sent++;
    }
    /* the DSP's packet: 64 units in slots 14..15, frame by frame */
    volatile u32 *r = TDM_RX(h);
    u16 v[64];
    u32 sum = LINK_SEED, w0 = r[14], sh;
    /* the justification, from the magic: right (TAG << 16 | v, as stock's slots arrive)
     * or left (TAG << 24 | v << 8); then every unit is read the same way */
    if (((w0 >> 16) & 0xFF) == TDM_TAG && ((u16)w0 == TX_MAGIC || (u16)w0 == POS_MAGIC))
        sh = 0;
    else if ((w0 >> 24) == TDM_TAG && ((u16)(w0 >> 8) == TX_MAGIC || (u16)(w0 >> 8) == POS_MAGIC))
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
    if ((u16)sum != v[63])
        return;
    if (v[0] == POS_MAGIC) {                    /* v0.25: idle, the voices' play positions */
        smp_pos_in(v + 1);
        for (int t = 0; t < 16; t++)            /* v0.30: the slots the DSP's guard skipped */
            if (v[17] >> t & 1u)
                smp_skip_at[t] = periods | 1u;
        if (v[18] <= 1000u && v[18] != 0) {     /* v0.32: the DSP's load (permille), its peak */
            if (v[18] >= smp_load_peak || periods - smp_load_at > 750u) {   /* over half a second */
                smp_load_peak = v[18];
                smp_load_at = periods;
            }
            smp_load_seen = periods | 1u;
        }
        smp_blown_mask |= v[19];                /* v0.34: the output guard's record */
        if (v[22] != smp_blown_count) {
            smp_blown_count = v[22];
            smp_blown_info = v[20];
            smp_blown_where = v[21];
            smp_blown_at = periods | 1u;
        }
        return;
    }
    if (v[0] != TX_MAGIC)
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

static void span_drop(u32 lo, u32 hi);
extern int smp_er_lock;                         /* v0.39: ERASE MOD DATA under way or done (erase.c) */
static int image_write(u32 off, u32 bytes, const void *buf)
{
    if (smp_er_lock || !store_ok() || off + bytes > POOL_BYTES || (off | bytes) & 511u)
        return -1;
    span_drop(off, off + bytes);                /* v0.38: the DSP's copy there is the old one */
    return BLK_WRITE(STORE_SECTOR + 1u + off / 512u, bytes, buf);
}

static int header_write(u32 bytes)              /* 0 marks the image empty */
{
    if (smp_er_lock || !store_ok())
        return -1;
    for (int k = 0; k < 128; k++)
        hdr[k] = 0;
    if (bytes) {
        hdr[0] = STORE_MAGIC;
        hdr[1] = 2;
        hdr[2] = bytes;
        hdr[3] = checksum(DIR, DIR_BYTES);
        hdr[4] = ~hdr[0] ^ hdr[2] ^ hdr[3];
        if (!smp_bank_blocked) {                /* v0.65: banks B..D's directory pages (older */
            hdr[5] = BANKS_MAGIC;               /* firmware reads none of this) */
            for (u32 b = 1; b < BANK_N; b++)    /* (a bank with nothing in it: 0, not written) */
                hdr[5 + b] = smp_bank_live((int)b) && le32(BPAGE(b) + 4) ? checksum(BPAGE(b), DIR_BYTES) : 0u;
            hdr[9] = hdr[5] ^ hdr[6] ^ hdr[7] ^ hdr[8] ^ 0x5A5A5A5Au;
        }
    }
    return BLK_WRITE(STORE_SECTOR, 512u, hdr);
}

/* v0.65: bank B..D's page, empty: its magic, count 0, its meta block's head, every slot in no folder */
static void bank_blank(u32 b)
{
    u8 *p = BPAGE(b);
    for (u32 j = 0; j < BANK_PAGE; j++)
        p[j] = 0;
    put_le32(p, BANK_MAGIC);
    put_le32(p + BANK_META, META_MAGIC);
    put_le32(p + BANK_META + 4, 1u);
    for (u32 s = 0; s < POOL_SLOTS; s++)
        p[BANK_META + 12u + META_FOLDERS * META_FOLDER_BYTES + META_SLOT_BYTES * s] = 0xFF;
}

static int is_recording(u32 k);
static u32 bimg_sum[BANK_N] __attribute__((section(".data")));   /* each page's sum as the image holds it (0: not known) */
#define PAGE_USED (BANK_SLICES + SLAREA_BYTES)
/* v0.65: the pages as the image's header names them (after DIR checked out): each whole page read
 * from the image, its directory part checked against the header; an older image's, or one that
 * does not check out, empty. Banks B..D stay off while one of bank A's recordings (an older
 * firmware's, made before the pages took that room) lies where they go */
static void banks_read(void)
{
    smp_bank_blocked = 0;
    for (u32 k = 0; k < POOL_SLOTS; k++) {
        if (!is_recording(k))
            continue;
        u32 a = le32(DIR + 8u + 16u * k) - SMP_POOL_DDR, z = a + le32(DIR + 12u + 16u * k) * 2u;
        if (a < TABLE_AREA && z > BANK_AREA)
            smp_bank_blocked = 1;
    }
    int hok = hdr[5] == BANKS_MAGIC && hdr[9] == (hdr[5] ^ hdr[6] ^ hdr[7] ^ hdr[8] ^ 0x5A5A5A5Au);
    for (u32 b = 1; b < BANK_N; b++) {
        int ok = 0;
        if (!smp_bank_blocked && hok && hdr[5 + b]) {
            ok = 1;
            for (u32 o = 0; o < BANK_PAGE && ok; o += CHUNK)
                ok = image_read(BPAGE_OFF(b) + o, BANK_PAGE - o < CHUNK ? BANK_PAGE - o : CHUNK, BPAGE(b) + o) == 0;
            ok = ok && le32(BPAGE(b)) == BANK_MAGIC && checksum(BPAGE(b), DIR_BYTES) == hdr[5 + b]
                 && le32(BPAGE(b) + 4) <= POOL_SLOTS;
        }
        bimg_sum[b] = ok ? checksum(BPAGE(b), PAGE_USED) : 0u;
        if (!ok)
            bank_blank(b);
        u8 *m = BPAGE(b) + BANK_META;           /* every string ends inside its field */
        for (u32 s = 0; s < POOL_SLOTS; s++)
            m[12u + META_FOLDERS * META_FOLDER_BYTES + META_SLOT_BYTES * s + META_SLOT_BYTES - 1u] = 0;
        if (le32(m) != META_MAGIC)
            put_le32(m, META_MAGIC);
    }
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
    smp_dir_ok = 1;                             /* (banks_read's own reads go by it) */
    banks_read();
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
    if (k < 0 || k >= SMP_ALL)
        return "";
    return (const char *)NAME(k);
}

/* v0.65: global slot K is one a page holds (bank A's any; B..D's 0..126 of a live bank) */
static int g_ok(int k)
{
    return k >= 0 && k < SMP_ALL && (k < POOL_SLOTS || (G_SLOT(k) < 127u && smp_bank_live((int)G_BANK(k))));
}

int smp_bank_count(int b)                       /* v0.65: a bank's page's count */
{
    return smp_bank_live(b) ? (b ? (int)le32(BPAGE(b) + 4) : smp_count()) : 0;
}

/* slot K's waveform, OVERVIEW_W column peaks 0..255, or 0 if none has been seen */
const u8 *smp_overview(int k)
{
    if (!g_ok(k))
        return 0;
    const u8 *o = OVW(k);
    for (int j = 0; j < OVERVIEW_W; j++)
        if (o[j])
            return o;
    return 0;
}

/* v0.19, SLICE: global slot K's slices (its entry's byte 13) and where its table lies in the
 * pool (after its frames, on a word: dnfw.sampler.live.pool_bytes) */
static u32 slice_table(int k, u32 *n)
{
    const u8 *e = ENTRY(k);
    u32 addr = le32(e), fr = le32(e + 4), fmt = e[12];
    *n = e[13] > SLICE_MAX ? SLICE_MAX : e[13];
    if (e[14] & 1)                              /* v0.23: made on the instrument: the slice area's */
        return SLOFF(k);                        /* (v0.65: its bank's) */
    return ((addr - SMP_POOL_DDR) + fr * (fmt ? 2u : 4u) + 3u) & ~3u;
}

/* the slices' starts as overview columns, for the page; 0xFF where none */
const u8 *smp_slices(int k, int *n)
{
    if (!g_ok(k) || !dir_ok)
        return 0;
    u32 ns;
    slice_table(k, &ns);
    *n = (int)ns;
    return ns ? SCOL(k) : 0;
}

static void slices_add(u32 off, u32 bytes, const u8 *buf)
{
    if (!dir_ok)
        return;
    for (int k = 0; k < SMP_ALL; k++) {
        if (!g_ok(k))
            continue;
        const u8 *e = ENTRY(k);
        u32 ns, fr = le32(e + 4);
        if (le32(e) < SMP_POOL_DDR || fr < 2)
            continue;
        u32 t = slice_table(k, &ns);
        for (u32 j = 0; j < ns; j++) {
            u32 at = t + 12u * j;                           /* slice j's start */
            if (at < off || at + 4u > off + bytes)
                continue;
            u32 s = le32(buf + (at - off));
            SCOL(k)[j] = (u8)(s >= fr ? OVERVIEW_W - 1 : s / (fr / (OVERVIEW_W - 1) + 1u));
        }
    }
}

static void overview_clear(int k)
{
    u8 *o = OVW(k);
    for (u32 j = 0; j < OVERVIEW_W; j++)
        o[j] = 0;
}

/* the overview of the slots whose frames lie in [OFF, OFF + BYTES) of the pool, from BUF */
static void overview_add(u32 off, u32 bytes, const u8 *buf)
{
    if (!dir_ok)
        return;
    for (int k = 0; k < SMP_ALL; k++) {
        if (!g_ok(k))
            continue;
        const u8 *e = ENTRY(k);
        u32 addr = le32(e), fr = le32(e + 4), fmt = e[12];
        if (addr < SMP_POOL_DDR || fr < 2 || fmt != 1)
            continue;
        u32 lo = addr - SMP_POOL_DDR, hi = lo + fr * 2u;
        if (hi <= off || lo >= off + bytes)
            continue;
        u8 *o = OVW(k);
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
enum { K_BLANK, K_FRAMES, K_ENTRY, K_FULL, K_AREA, K_TABLES, K_READY, K_PREVIEW, K_HEAD };
/* v0.38 (the testers' "new samples are silent until a restart"): the DSP plays a slot below
 * REC_FIRST only if it is below the directory's count (word 1; dnfw.sampler.program.start),
 * and only the whole page (BLANK, FULL: a power-on or a project's load) carried the count.
 * A slot added live (LOAD TO PROJECT, a recording, a send's slot) past the count the DSP
 * last had stayed silent until the next power-on. Since v0.33 a recording goes into the
 * first empty slot, mostly the one at the count. K_HEAD: the page's first 8 bytes (the
 * magic and the count, at least smp_head_min), sent after every live entry and when a
 * recording starts. */
int smp_head_due __attribute__((section(".data"))) = 0;
u32 smp_head_min __attribute__((section(".data"))) = 0;     /* a recording's slot + 1 */
u32 smp_heads __attribute__((section(".data"))) = 0;        /* heads that checked out (the gate) */
static int area_push __attribute__((section(".data"))) = -1;    /* one slot's table to the DSP */
static int l_area_read __attribute__((section(".data"))) = 0;   /* K_AREA from the +Drive (else from the copy) */
int smp_area_ok(void);
static int l_kind __attribute__((section(".data"))) = K_BLANK;
static int l_entry __attribute__((section(".data"))) = -1;       /* the entry due next (a global slot) */
/* v0.65: the pages whose blank (power-on, a switch), whole (the load's end) copy, count (a live
 * entry) or slice area is still to go to the DSP: bit b, bank b */
static u32 l_blank_m __attribute__((section(".data"))) = 0;
static u32 l_full_m __attribute__((section(".data"))) = 0;
static u32 head_m __attribute__((section(".data"))) = 0;
static u32 area_m __attribute__((section(".data"))) = 0;
static u32 live_pages(void)
{
    u32 m = 0;
    for (int b = 0; b < BANK_N; b++)
        if (smp_bank_live(b))
            m |= 1u << b;
    return m;
}
static u32 low_bit(u32 m)
{
    u32 b = 0;
    while (!(m & 1u << b))
        b++;
    return b;
}

/* v0.26: the tables (TABLE_LOAD: magic, length, data), sent before anything else at
 * power-on, the +Drive's image or not; READY's magic once every chunk checked out */
#define TBL ((const u8 *)TABLE_LOAD)
int smp_tables __attribute__((section(".data"))) = 0;   /* 0 not yet, 1 sending, 2 sent, -1 none */
static u32 tbl_bytes(void)
{
    if (le32(TBL) != TABLE_MAGIC)
        return 0;
    u32 n = (le32(TBL + 4) + 511u) & ~511u;
    return n && n <= TABLE_ROOM - 512u ? n : 0;
}


/* v0.31: the order the slots load in (the owner: the pool is slow to load at power-on):
 * first the samples the kit's sample tracks are set to (SAMP, as the page reads it), so the
 * pattern plays while the rest comes in; then every other slot, in order. A slot plays as
 * soon as it is in (its entry follows its frames), whatever the order. No kit yet: in order. */
u16 smp_l_order[SMP_ALL] __attribute__((section(".data")));   /* v0.65: global slots */
static int l_order_ok __attribute__((section(".data"))) = 0;
u32 smp_walk_total __attribute__((section(".data"))) = 0;   /* the frames' bytes due this load */
#define L_KIT (*(volatile u32 *)0x800052A0u)
#define L_TYPE(t) (*(volatile signed char *)(L_KIT + 52u + 1163u * (u32)(t) + 0xDEu))
extern int smp_samp_of(int track);

static void load_order(void)
{
    u8 taken[SMP_ALL];
    int n = 0;
    for (int k = 0; k < SMP_ALL; k++)
        taken[k] = 0;
    extern u32 smp_samp_word(int track);
    if (L_KIT)
        for (int t = 0; t < 16; t++) {
            int ty = L_TYPE(t), g = smp_word_g(smp_samp_word(t));   /* v0.65: its bank's slot */
            if (ty < 8 || ty > 13 || g < 0 || taken[g])
                continue;
            taken[g] = 1;
            smp_l_order[n++] = (u16)g;
        }
    for (int k = 0; k < SMP_ALL; k++)
        if (!taken[k])
            smp_l_order[n++] = (u16)k;
    l_order_ok = 1;
}

/* -- v0.38: what the DSP's memory holds, and each slot's sum (pools.c) ---------------------
 * A SPAN is a stretch of the pool (a slot's frames, sector-rounded, as slot_range reads
 * them) that the loader sent this power-on and the DSP checked: the DSP holds the image's
 * bytes there. A switch to a project whose slot is the same span sends only its entry. A
 * span is dropped when anything else is written there: the image (image_write), the DSP by
 * another kind of range (tables, the preview, the slice area's copy), or a recording (the
 * recordings' area, at ARM/NOW). Its SUM is the loader's of those bytes (checksum's, run on
 * across the chunks); pools.c keeps each slot's in its list and asks for it again when the
 * list is loaded (smp_pl_expect): frames that no longer match are not given to the DSP. */
#define SPAN_MAX 256u
#define SPAN_BYTES 176u
#define SPAN(i) ((u8 *)(SMP_MIRROR + 0x220000u + SPAN_BYTES * (u32)(i)))   /* lo, hi, sum, 100 + 64 columns */
#define SSUM(k) ((u32)(k) < POOL_SLOTS ? (u8 *)(SMP_MIRROR + 0x22C000u + 20u * (u32)(k)) : BSSUM(k))   /* a slot's sum, and its entry */
_Static_assert(0x220000u + SPAN_MAX * SPAN_BYTES <= 0x22C000u && 0x22C000u + 20u * POOL_SLOTS <= SMP_MIRROR_BYTES,
               "the spans and the sums fit");
_Static_assert(12u + OVERVIEW_W + SLICE_MAX <= SPAN_BYTES, "a span holds its columns");
static u32 span_n __attribute__((section(".data"))) = 0;
static u32 span_next __attribute__((section(".data"))) = 0;
static u32 l_sa __attribute__((section(".data"))) = 1, l_sb __attribute__((section(".data"))) = 0;
static u32 l_span_lo __attribute__((section(".data"))) = 0;
static u32 pl_bad[SMP_ALL / 32] __attribute__((section(".data"))) = {0};   /* slots whose frames did not match (v0.65: global) */
u32 smp_pl_skipped __attribute__((section(".data"))) = 0;   /* slots a switch did not need to send */
u32 smp_pl_mismatch __attribute__((section(".data"))) = 0;  /* slots whose sum did not match */
extern u32 smp_pl_expect(int k, const u8 *e);
extern int smp_pl_busy(void);
extern void smp_pl_changed(void);
extern u32 smp_pl_clash(u32 lo, u32 hi);
extern u32 smp_pl_next(u32 at);
extern int smp_pl_res_count(void);
extern u32 smp_pl_res_end(int i);
int smp_slot_empty(int k);

static void span_drop(u32 lo, u32 hi)
{
    for (u32 i = 0; i < span_n; i++) {
        u32 a = le32(SPAN(i)), b = le32(SPAN(i) + 4);
        if (a < hi && lo < b)
            put_le32(SPAN(i) + 4, a);           /* empty: never matches again */
    }
}

static int span_find(u32 lo, u32 hi)
{
    for (u32 i = 0; i < span_n; i++)
        if (le32(SPAN(i)) == lo && le32(SPAN(i) + 4) == hi && hi > lo)
            return (int)i;
    return -1;
}

static void span_add(u32 lo, u32 hi, u32 sum, int k)
{
    int i = span_find(lo, hi);
    if (i < 0) {
        for (u32 j = 0; j < span_n && i < 0; j++)       /* a dropped one's place */
            if (le32(SPAN(j)) == le32(SPAN(j) + 4))
                i = (int)j;
        if (i < 0 && span_n < SPAN_MAX)
            i = (int)span_n++;
        if (i < 0)
            i = (int)(span_next++ % SPAN_MAX);
    }
    u8 *sp = SPAN(i);
    put_le32(sp, lo);
    put_le32(sp + 4, hi);
    put_le32(sp + 8, sum);
    for (u32 j = 0; j < OVERVIEW_W; j++)
        sp[12 + j] = OVW(k)[j];
    for (u32 j = 0; j < SLICE_MAX; j++)
        sp[12 + OVERVIEW_W + j] = SCOL(k)[j];
}

static void ssum_set(int k, u32 sum)
{
    u8 *x = SSUM(k);
    put_le32(x, sum);
    for (int j = 0; j < 16; j++)
        x[4 + j] = ENTRY(k)[j];
}

/* slot K's sum, if the loader has read its frames for the entry it has now; 0: not known */
u32 smp_pl_slot_sum(int k)
{
    if (!g_ok(k) || !dir_ok || smp_slot_empty(k))
        return 0;
    const u8 *x = SSUM(k);
    for (int j = 0; j < 16; j++)
        if (x[4 + j] != ENTRY(k)[j])
            return 0;
    return le32(x);
}

static int bad(u32 k) { return k < (u32)SMP_ALL && (pl_bad[k >> 5] >> (k & 31) & 1u); }

/* a slot's frames all read and checked: its sum; against what its list recorded */
static void slot_done(void)
{
    int k = l_entry;
    u32 s = l_sb << 16 ^ l_sa;
    if (!s)
        s = 1;
    u32 want = smp_pl_expect(k, ENTRY(k));
    if (want && want != s) {
        pl_bad[(u32)k >> 5] |= 1u << (k & 31);  /* not given to the DSP: silent, never wrong */
        smp_pl_mismatch++;
        l_entry = -1;
        return;
    }
    ssum_set(k, s);
    span_add(l_span_lo, l_end, s, k);
}

/* slot K's frames as the next range (then its entry) -> 0: nothing to load */
static int slot_range(u32 k)
{
    if (!g_ok((int)k))
        return 0;
    const u8 *e = ENTRY(k);
    u32 addr = le32(e), fr = le32(e + 4), fmt = e[12];
    if (addr < SMP_POOL_DDR + DATA_OFFSET || fr == 0)
        return 0;
    u32 lo = addr - SMP_POOL_DDR, bytes = fr * (fmt ? 2u : 4u);
    u32 ns, tbl = slice_table((int)k, &ns);             /* v0.19: and its slices, if any */
    if (ns && !(e[14] & 1))
        bytes = tbl - lo + 12u * ns;
    if (e[14] & 1)
        area_m |= 1u << G_BANK(k);                      /* (v0.65: its bank's slice area) */
    if (lo >= ram_top || bytes > ram_top - lo)             /* v0.22: past the RAM proven */
        return 0;
    if (lo < TABLE_AREA + TABLE_ROOM && lo + bytes > TABLE_AREA)
        return 0;                                           /* v0.26: over the tables (an old recording) */
    l_kind = K_FRAMES;
    l_off = lo & ~511u;
    l_end = (lo + bytes + 511u) & ~511u;
    if (l_end > ram_top)
        l_end = ram_top;
    l_entry = (int)k;
    l_sa = 1;                                   /* v0.38: the slot's sum, from its first chunk */
    l_sb = 0;
    l_span_lo = l_off;
    int i = span_find(l_off, l_end);
    if (i >= 0) {                               /* the DSP holds these bytes already */
        u32 sum = le32(SPAN(i) + 8), want = smp_pl_expect((int)k, e);
        if (!want || want == sum) {
            for (u32 j = 0; j < OVERVIEW_W; j++)
                OVW(k)[j] = SPAN(i)[12 + j];
            for (u32 j = 0; j < SLICE_MAX; j++)
                SCOL(k)[j] = SPAN(i)[12 + OVERVIEW_W + j];
            ssum_set((int)k, sum);
            smp_walk += l_end - l_off;
            smp_pl_skipped++;
            l_kind = K_ENTRY;                   /* only the entry */
            l_off = page_off(G_BANK(k)) + 8u + 16u * G_SLOT(k);
            l_end = l_off + 16u;
            l_entry = -1;
        }
    }
    return 1;
}

static int next_range(void)
{
    if (smp_tables == 1 && l_kind != K_TABLES && l_kind != K_READY) {
        l_kind = K_TABLES;
        l_off = TABLE_AREA;
        l_end = TABLE_AREA + tbl_bytes();
        return 1;
    }
    if (smp_tables == 1 && l_kind == K_TABLES) {
        l_kind = K_READY;
        l_off = TABLE_READY;
        l_end = TABLE_READY + 512u;
        return 1;
    }
    if (smp_tables == 1) {                      /* READY checked out */
        smp_tables = 2;
        l_kind = K_BLANK;
        l_end = 0;
        if (!dir_ok)
            return 0;
    }
    if (smp_head_due && dir_ok && l_slot > (u32)SMP_ALL) {   /* v0.38: the magic and the count */
        smp_head_due = 0;
        head_m |= 1u;
    }
    if (head_m && dir_ok && l_slot > (u32)SMP_ALL) {   /* v0.65: a page's (bank A's first) */
        u32 b = low_bit(head_m);
        head_m &= ~(1u << b);
        if (smp_bank_live((int)b)) {
            l_kind = K_HEAD;
            l_off = page_off(b);
            l_end = l_off + 8u;
            return 1;
        }
    }
    while (l_blank_m) {                         /* v0.65: each live page, up to the command */
        u32 b = low_bit(l_blank_m);             /* block (the DSP's), its entries empty */
        l_blank_m &= ~(1u << b);
        if (smp_bank_live((int)b)) {
            l_kind = K_BLANK;
            l_off = page_off(b);
            l_end = l_off + CMD_OFFSET;
            return 1;
        }
    }
    if (area_push >= 0) {                       /* v0.23: one slot's slice table */
        l_kind = K_AREA;
        l_area_read = 0;
        l_off = SLOFF(area_push);
        l_end = l_off + SLICE_TB;
        area_push = -1;
        return 1;
    }
    if (l_entry >= 0) {
        l_kind = K_ENTRY;
        l_off = page_off(G_BANK(l_entry)) + 8u + 16u * G_SLOT(l_entry);
        l_end = l_off + 16u;
        l_entry = -1;
        return 1;
    }
    if (l_slot == 0 && !l_order_ok)
        load_order();
    while (l_slot < (u32)SMP_ALL)
        if (slot_range(smp_l_order[l_slot++]))
            return 1;
    while (l_slot == (u32)SMP_ALL && area_m) {  /* v0.23: the slice areas, before the pages */
        u32 b = low_bit(area_m);
        area_m &= ~(1u << b);
        if (b == 0 && smp_area_ok()) {          /* bank A's from the +Drive */
            l_kind = K_AREA;
            l_area_read = 1;
            l_off = SLICE_AREA;
            l_end = SLICE_AREA + SLAREA_BYTES;
            return 1;
        }
        if (b && smp_bank_live((int)b)) {       /* v0.65: B..D's from their pages' copies */
            l_kind = K_AREA;
            l_area_read = 0;
            l_off = BPAGE_OFF(b) + BANK_SLICES;
            l_end = l_off + SLAREA_BYTES;
            return 1;
        }
    }
    if (l_slot == (u32)SMP_ALL) {               /* last: the whole directory pages */
        l_slot++;
        l_full_m = live_pages();
    }
    while (l_full_m) {
        u32 b = low_bit(l_full_m);
        l_full_m &= ~(1u << b);
        if (smp_bank_live((int)b)) {
            l_kind = K_FULL;
            l_off = page_off(b);
            l_end = l_off + CMD_OFFSET;
            return 1;
        }
    }
    return 0;
}

static void job_start(const u8 *data, u32 off, u32 bytes)
{
    job_data = 0;
    job_base = off / 4u;
    job_n = bytes / 4u;
    job_fast_next = 0;
    job_data = data;
}

static int job_sent(void)
{
    return job_fast_next >= job_n;
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

static int is_recording(u32 k);
int smp_is_recording(int k)                     /* v0.25: the browser's "recorded" folder */
{
    return k >= 0 && k < POOL_SLOTS && is_recording((u32)k);
}

/* -- v0.25: the long names and folders (the import tool's; dnfw.sampler.machines META_*) -- */
#define META ((u8 *)(SMP_MIRROR + 0x80000u))
#define META_ROOM 0x2000u
_Static_assert(META_BYTES <= META_ROOM && 0x80000u + META_ROOM <= SMP_MIRROR_BYTES, "the meta block fits");
_Static_assert(META_PTR + 12u <= CMD_OFFSET, "the meta pointer lies before the command block");
int smp_meta_ok __attribute__((section(".data"))) = 0;
#define meta_ok smp_meta_ok

static void meta_read(void)
{
    meta_ok = 0;
    if (!dir_ok || le32(DIR + META_PTR) != META_PTR_MAGIC)
        return;
    u32 off = le32(DIR + META_PTR + 4), n = le32(DIR + META_PTR + 8);
    if (n < META_BYTES || n > META_ROOM || (off & 511u) || off < DATA_OFFSET || off + n > smp_hi
        || (off < REC_END && off + n > REC_OFFSET))
        return;
    n = (n + 511u) & ~511u;
    if (n > META_ROOM || image_read(off, n, META) != 0 || le32(META) != META_MAGIC)
        return;
    META[12 + META_FOLDERS * META_FOLDER_BYTES - 1] = 0;
    for (u32 f = 0; f < META_FOLDERS; f++)          /* every string ends inside its field */
        META[12 + META_FOLDER_BYTES * f + META_FOLDER_BYTES - 1] = 0;
    for (u32 k = 0; k < POOL_SLOTS; k++)
        META[12 + META_FOLDERS * META_FOLDER_BYTES + META_SLOT_BYTES * k + META_SLOT_BYTES - 1] = 0;
    meta_ok = 1;
}

static const u8 *meta_slot(int k)              /* v0.65: a bank's own meta block (its page's) */
{
    const u8 *m = G_BANK(k) ? BPAGE(G_BANK(k)) + BANK_META : META;
    return m + 12 + META_FOLDERS * META_FOLDER_BYTES + META_SLOT_BYTES * G_SLOT(k);
}
static int meta_has(int k)                      /* its meta block is there */
{
    return G_BANK(k) ? g_ok(k) : meta_ok;
}

/* slot K's long name (the tool's), if it has one and the instrument's own short name is
 * still what the tool made of it (its stem: upper case, A-Z 0-9 space _ # -, seven at most:
 * a rename on the instrument wins); else its short name */
const char *smp_long_name(int k)
{
    if (!g_ok(k))
        return "";
    const char *sh = smp_name(k);
    if (!meta_has(k))
        return sh;
    const char *ln = (const char *)meta_slot(k) + 4;
    if (!ln[0])
        return sh;
    char st[8];
    int n = 0;
    for (int j = 0; ln[j] && n < 7; j++) {
        char c = ln[j];
        if (c >= 'a' && c <= 'z')
            c = (char)(c - 32);
        if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == ' ' || c == '_' || c == '#' || c == '-')
            st[n++] = c;
    }
    st[n] = 0;
    for (int j = 0; j < 8; j++) {
        if (st[j] != sh[j])
            return sh;
        if (!st[j])
            break;
    }
    return ln;
}

int smp_folder_count(void)
{
    return meta_ok ? (int)(le32(META + 8) > META_FOLDERS ? META_FOLDERS : le32(META + 8)) : 0;
}

const char *smp_folder_name(int f)
{
    if (f < 0 || f >= smp_folder_count())
        return "";
    return (const char *)META + 12 + META_FOLDER_BYTES * (u32)f;
}

int smp_folder_of(int k)                        /* -1: in no folder */
{
    if (!g_ok(k) || !meta_has(k))
        return -1;
    int f = meta_slot(k)[0];                    /* (v0.65: banks B..D's name bank A's folders) */
    return f < smp_folder_count() ? f : -1;
}

void smp_load(void)                             /* load (again) whatever the image holds */
{
    smp_hi = header_read();
    dir_ok = smp_hi != 0;
    meta_read();
    if (smp_tables == 0)                        /* v0.26: the tables, once, first */
        smp_tables = tbl_bytes() ? 1 : -1;
    if (!dir_ok && smp_tables != 1) {
        smp_lstate = L_IDLE;
        return;
    }
    for (int k = 0; k < SMP_ALL; k++) {         /* v0.65: every bank's */
        for (u32 j = 0; j < OVERVIEW_W; j++)
            OVW(k)[j] = 0;
        for (u32 j = 0; j < SLICE_MAX; j++)
            SCOL(k)[j] = 0;
    }
    smp_walk = 0;
    smp_walk_total = 0;                         /* v0.31: the frames due, for LOADING n% */
    for (int k = 0; k < SMP_ALL; k++) {
        if (!g_ok(k))
            continue;
        const u8 *e = ENTRY(k);
        u32 addr = le32(e), fr = le32(e + 4);
        if (addr >= SMP_POOL_DDR + DATA_OFFSET && fr)
            smp_walk_total += fr * (e[12] ? 2u : 4u);
    }
    l_order_ok = 0;
    fast_on = 1;
    smp_head_min = 0;                           /* v0.38: the whole page carries DIR's count */
    smp_head_due = 0;
    head_m = 0;
    area_m = 0;
    for (u32 k = 0; k < SMP_ALL / 32; k++)      /* v0.38: this load finds its own */
        pl_bad[k] = 0;
    l_slot = 0;
    l_kind = K_BLANK;
    l_entry = -1;
    l_end = 0;
    l_blank_m = dir_ok ? live_pages() : 0u;     /* v0.65: each page blank first */
    l_full_m = 0;
    smp_lstate = next_range() ? L_READ : L_DONE;
}

/* v0.33: +DRIVE's preview (FUNC + YES on a library sample, as the DT2's: its first ten
 * seconds through the main mix while held). The sample is not in the pool, so its first
 * PREVIEW_BYTES go from the +Drive to a stretch of the DSP's pool no slot uses (pool_room),
 * through the loader's checked path, and never to the +Drive's image; the DSP plays them
 * from there (CMD_PREVIEW at PREVIEW_AT) once the first PV_START bytes are in. */
#define PREVIEW_AT 0xFFFFu                  /* dnfw.sampler.program.PREVIEW_AT, PREVIEW_BYTES */
#define PREVIEW_BYTES (10u * 48000u * 2u)
#define PV_START 0x20000u
static int pv_k __attribute__((section(".data"))) = -1;     /* the library entry, -1 none */
static u32 pv_off __attribute__((section(".data"))) = 0;
static u32 pv_bytes __attribute__((section(".data"))) = 0;
int smp_pv_state __attribute__((section(".data"))) = 0;  /* 0 none, 1 asked, 2 loading, 3 playing */

static void load_poll(void)
{
    if (smp_lstate == L_READ) {
        u32 n = l_end - l_off;
        if (n > CHUNK)
            n = CHUNK;
        if (l_kind == K_TABLES || l_kind == K_READY || l_kind == K_PREVIEW || (l_kind == K_AREA && !l_area_read))
            span_drop(l_off, l_off + n);                    /* v0.38: not the image's bytes */
        if (l_kind == K_AREA) {                             /* v0.23: from the copy */
            u8 *ram = ram_of(l_off);                        /* (v0.65: bank A's or a page's) */
            if (!ram) {
                smp_lstate = L_IDLE;
                return;
            }
            if (l_area_read) {
                if (image_read(l_off, n, STAGE(0)) != 0) {
                    smp_lstate = L_IDLE;
                    return;
                }
                for (u32 k = 0; k < n; k++)
                    ram[k] = STAGE(0)[k];
            } else {
                for (u32 k = 0; k < n; k++)
                    STAGE(0)[k] = ram[k];
            }
            slices_add(l_off, n, STAGE(0));
        } else if (l_kind == K_TABLES) {                    /* v0.26: from the ColdFire's RAM */
            for (u32 k = 0; k < n; k++)
                STAGE(0)[k] = TBL[8 + (l_off - TABLE_AREA) + k];
        } else if (l_kind == K_READY) {
            for (u32 k = 0; k < n; k++)
                STAGE(0)[k] = 0;
            put_le32(STAGE(0), TABLE_MAGIC);
        } else if (l_kind == K_PREVIEW) {                   /* v0.33: +DRIVE's preview, from the library */
            extern int smp_lib_read(int k, u32 off, u32 bytes, void *buf);
            if (pv_k < 0 || smp_lib_read(pv_k, l_off - pv_off, n, STAGE(0)) != 0) {
                pv_k = -1;
                smp_lstate = L_IDLE;
                return;
            }
        } else if (l_kind == K_FRAMES) {
            if (image_read(l_off, n, STAGE(0)) != 0) {
                smp_lstate = L_IDLE;                            /* the +Drive refused: stop */
                return;
            }
            overview_add(l_off, n, STAGE(0));
            slices_add(l_off, n, STAGE(0));
        } else {                                            /* a directory page's: from its RAM */
            u8 *ram = ram_of(l_off);                        /* (v0.65: bank A's DIR, or B..D's) */
            u32 pb = l_off < BANK_AREA ? 0u : 1u + (l_off - BANK_AREA) / BANK_PAGE, base = page_off(pb);
            if (!ram || l_off + n > base + DIR_BYTES) {
                smp_lstate = L_IDLE;
                return;
            }
            for (u32 k = 0; k < n; k++)
                STAGE(0)[k] = ram[k];
            if (l_off == 0 && n >= 8u && le32(DIR + 4) < smp_head_min && smp_head_min <= POOL_SLOTS)
                put_le32(STAGE(0) + 4, smp_head_min);       /* v0.38: a recording's slot is counted */
            if (l_kind == K_BLANK)
                for (u32 k = base + 8u; k < base + 8u + 16u * POOL_SLOTS; k++)
                    if (k >= l_off && k < l_off + n)
                        STAGE(0)[k - l_off] = 0;
            for (u32 s = 0; s < POOL_SLOTS; s++) {          /* v0.38: frames that did not match */
                u32 at = base + 8u + 16u * s;
                if (bad(pb * POOL_SLOTS + s) && at >= l_off && at + 16u <= l_off + n)
                    for (u32 j = 0; j < 16; j++)
                        STAGE(0)[at + j - l_off] = 0;
            }
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
                if (l_kind == K_FRAMES && l_entry >= 0) {   /* v0.38: the slot's sum runs on */
                    for (u32 j = 0; j < l_chunk_bytes; j++) {
                        l_sa += STAGE(0)[j];
                        l_sb += l_sa;
                    }
                }
                l_off += l_chunk_bytes;
                if (l_kind == K_FRAMES && l_entry >= 0 && l_off >= l_end)
                    slot_done();
                if (l_kind == K_ENTRY && l_slot > (u32)SMP_ALL && l_off >= l_end)   /* v0.38: a live entry: */
                    head_m |= 1u << (l_off - 16u < BANK_AREA ? 0u : 1u + (l_off - 16u - BANK_AREA) / BANK_PAGE);   /* its page's count next */
                if (l_kind == K_HEAD && l_off >= l_end)
                    smp_heads++;
                smp_lstate = l_off < l_end || next_range() ? L_READ : L_DONE;
                return;
            }
        } else if (periods - l_since < 1500u) {
            return;                                         /* a second for the DSP to answer */
        }
        smp_retries++;                                      /* wrong, or no answer: again */
        if (++l_tries > 6) {
            fast_on = 0;                                    /* nothing gets through: stop */
            if (l_kind == K_PREVIEW)
                pv_k = -1;                                  /* v0.33: and no preview of half of it */
            smp_lstate = L_IDLE;
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
static u32 s_peak __attribute__((section(".data"))) = 0;      /* v0.25: for the normalising */
/* v0.63 (the owner: saving a FLEX buffer normalised it, and the slot shares the frames the
 * buffer is still playing, so the playing take jumped to full scale): set by rec.c's bn_save
 * before smp_save_recording, the save keeps its frames as they lie -- saved, never normalised.
 * The RECORDER's own saves still normalise (v0.41). s_keep is the save's copy */
u32 smp_save_keep __attribute__((section(".data"))) = 0;
static u32 s_keep __attribute__((section(".data"))) = 0;
static u32 s_place __attribute__((section(".data"))) = 0;

/* v0.33: where the recorder's save is (the recorder's NORMALIZING waits on it): a value that
 * changes while it moves, 0 when none runs */
u32 smp_save_mark(void)
{
    /* v0.41 (the owner: NORMALIZING sat for minutes, then the RECORDER came back; the take
     * was fine): v0.33..v0.40's mark held only the save's own place, which stands still while
     * the normalised take goes back to the DSP (state 4: the loader's read, send and check, a
     * long take's for a while), and while state 3 waits for the loader to be free (a page's
     * samples loading, a preview, LOAD TO PROJECT). v0.40 normalises every take, so every take
     * took that road, and the 20-second watchdog in rec.c gave up on a save that was moving.
     * The loader's place is in the mark now: only a save in which nothing moves for 20 s ends it */
    if (!sstate)
        return 0u;
    return (s_off ^ (u32)sstate << 28 ^ s_tries << 24
            ^ (sstate >= 3 ? l_off * 2654435761u ^ (u32)smp_lstate << 20 : 0u)) | 1u;
}

static int is_recording(u32 k)                  /* slot K's frames lie in the recordings' area */
{
    const u8 *e = ENTRY(k);
    u32 a = le32(e), f = le32(e + 4);
    return dir_ok && a >= SMP_POOL_DDR + REC_OFFSET && a < SMP_POOL_DDR + REC_END && f;
}

/* slot K holds nothing (SAMP K + 1) */
int smp_slot_empty(int k)
{
    if (k < 0 || k >= SMP_ALL)
        return 0;
    if (!dir_ok || !g_ok(k))
        return 1;
    const u8 *e = ENTRY(k);
    return le32(e) < SMP_POOL_DDR + DATA_OFFSET || le32(e + 4) == 0;
}

/* v0.23: the slice area is free (no recording of v0.22's reaches into it) */
int smp_area_ok(void)
{
    for (u32 k = 0; k < POOL_SLOTS; k++) {
        if (!is_recording(k))
            continue;
        u32 a = le32(ENTRY(k)) - SMP_POOL_DDR, b = a + le32(ENTRY(k) + 4) * 2u;
        if (b > SLICE_AREA && a < SLICE_AREA + SLAREA_BYTES)
            return 0;
    }
    return 1;
}

/* where a recording into slot DEST may go: the largest stretch of the recordings' area
 * that no other slot's recording uses (DEST's own old one is free: the recording replaces
 * it). -> its start, bytes into the area, a multiple of 512; *ROOM its length */
u32 smp_rec_place(int dest, u32 *room)
{
    u32 best = 0, best_len = 0;
    /* v0.38: and every other project's recordings (pools.c): their ends are candidates too,
     * and nothing starts inside one or runs into one */
    int nres = smp_pl_res_count();
    extern u32 rt_rplace[BUF_HALVES], rt_rbytes[BUF_HALVES], rt_nx_place[BUF_N], rt_nx_need[BUF_N];   /* v0.44: 16 halves, 8 next places */
    for (int c = -1; c < POOL_SLOTS + nres + BUF_HALVES + BUF_N; c++) {    /* each candidate start: 0, or a recording's end */
        u32 s = 0;
        if (c >= POOL_SLOTS + nres) {           /* v0.41: a buffer take's end, or a next place's */
            int i = c - POOL_SLOTS - nres;
            u32 a = i < BUF_HALVES ? rt_rplace[i] : rt_nx_place[i - BUF_HALVES];
            u32 z = a + (i < BUF_HALVES ? rt_rbytes[i] : rt_nx_need[i - BUF_HALVES]);
            if (z == a || (i < BUF_HALVES && BUF_SLOT0 + i == dest))
                continue;
            s = (z + 511u) & ~511u;
        } else if (c >= POOL_SLOTS) {
            u32 z = smp_pl_res_end(c - POOL_SLOTS);
            if (z <= REC_OFFSET || z >= REC_OFFSET + REC_BYTES)
                continue;
            s = (z - REC_OFFSET + 511u) & ~511u;
        } else if (c >= 0) {
            if (c == dest || !is_recording((u32)c))
                continue;
            const u8 *e = ENTRY(c);
            s = (le32(e) - SMP_POOL_DDR - REC_OFFSET + le32(e + 4) * 2u + 511u) & ~511u;
        }
        if (s >= REC_BYTES)
            continue;
        u32 next = REC_BYTES;
        int inside = 0;
        for (int k = 0; k < POOL_SLOTS; k++) {
            if (k == dest || !is_recording((u32)k))
                continue;
            const u8 *e = ENTRY(k);
            u32 a = le32(e) - SMP_POOL_DDR - REC_OFFSET, b = a + le32(e + 4) * 2u;
            if (a <= s && s < b)
                inside = 1;
            if (a >= s && a < next)
                next = a & ~511u;
        }
        if (smp_pl_clash(REC_OFFSET + s, REC_OFFSET + s + 1u))
            inside = 1;
        extern int rt_regions(int dest, u32 s, u32 *next);   /* v0.41: the buffers' takes, and their next places */
        if (rt_regions(dest, s, &next))
            inside = 1;
        u32 nx = smp_pl_next(REC_OFFSET + s);
        if (nx != 0xFFFFFFFFu && nx - REC_OFFSET < next)
            next = (nx - REC_OFFSET) & ~511u;
        if (!inside && next > s && next - s > best_len) {
            best = s;
            best_len = next - s;
        }
    }
    *room = best_len;
    return best;
}

/* from rec.c when a recording is done: into slot SLOT, its frames at OFF bytes into the
 * recordings' area, FRAMES of them */
void smp_save_recording(int slot, u32 off, u32 frames)
{
    if (!store_ok() || frames == 0 || sstate || slot < 0 || slot >= POOL_SLOTS - 1 || off >= REC_BYTES)
        return;
    if (frames > (REC_BYTES - off) / 2u)
        frames = (REC_BYTES - off) / 2u;
    s_slot = (u32)slot;
    s_place = off;
    s_frames = frames;
    s_off = REC_OFFSET + off;
    s_end = s_off + ((frames * 2u + 511u) & ~511u);
    /* v0.22: the slot's entry first (as the DSP already has it), so the frames read back
     * draw the slot's own waveform (overview_add), and none of an older one's is left */
    if (!dir_ok) {                                   /* no image yet: an empty pool */
        for (u32 k = 0; k < DIR_BYTES; k++)
            DIR[k] = 0;
        put_le32(DIR, POOL_MAGIC);
        dir_ok = 1;
    }
    u8 *e = ENTRY(slot);
    if (slot < REC_FIRST)
        put_le32(LIBID(slot), 0);                /* v0.39: a recording: no library sample's */
    put_le32(e, SMP_POOL_DDR + REC_OFFSET + off);
    put_le32(e + 4, frames);
    put_le32(e + 8, 0x3F800000u);                    /* rate 1.0 */
    put_le32(e + 12, 1);                             /* int16 */
    overview_clear(slot);
    smp_saved = 0;
    s_peak = 0;
    s_keep = smp_save_keep;
    smp_save_keep = 0;
    sstate = 1;
}

/* v0.25: the largest |frame| of the recording in the window BUF (bytes [OFF, OFF + BYTES) of
 * the pool), for the normalising after the save */
static void peak_add(u32 off, u32 bytes, const u8 *buf)
{
    u32 lo = REC_OFFSET + s_place, hi = lo + s_frames * 2u;
    u32 a = lo > off ? lo : off, b = hi < off + bytes ? hi : off + bytes;
    for (u32 x = a & ~1u; x + 1 < b; x += 2) {
        int v = (short)(buf[x - off] | buf[x - off + 1] << 8);
        if (v < 0) v = -v;
        if ((u32)v > s_peak) s_peak = (u32)v;
    }
}

/* v0.25: the recording brought to full scale, as the DT2 normalises one (its peak to
 * NORM_PEAK), in the +Drive's copy, a chunk a pass; then the loader's own path (read,
 * sent, checked) gives the DSP the same frames */
/* v0.30: to -6 dB, and by at most +24 dB (a user, and the owner: "incredibly loud" -- full
 * scale sat far above the DN2's own machines, and a quiet take's noise came up with it).
 * v0.41 (the owner: a resampled take came out ~6 dB under what was played, "just record and
 * normalize like the DT2 does"): to full scale, the take's peak to 32,767, as the DT2, the
 * Octatrack and the Digitakt do right after a recording -- ANY take that is not all zero,
 * however quiet (the owner: recording silence and normalising it gives a noise source to
 * ping filters and FX with, as on those). No gain cap and no floor; a take of exact zeros
 * stays zero, one already at full scale is untouched. The one guardrail: never clip. The
 * gain is (32,767 << 16) / peak, floored, so the peak lands on 32,767 at most (a peak of 1:
 * x32,767; v * gi stays within int16 since |v| <= peak) */
#define NORM_PEAK 32767u
static void norm_chunk(void)
{
    u32 lo = REC_OFFSET + s_place, hi = lo + s_frames * 2u;
    u32 n = s_end - s_off;
    if (n > CHUNK)
        n = CHUNK;
    u8 *b = STAGE(1);
    if (image_read(s_off, n, b) != 0) {
        sstate = 0;
        smp_saved = -1;
        return;
    }
    u32 g = (NORM_PEAK << 16) / s_peak;               /* the gain, 16 fractional bits */
    int gi = (int)(g >> 16), gf = (int)(g & 0xFFFFu);
    u32 a = lo > s_off ? lo : s_off, e = hi < s_off + n ? hi : s_off + n;
    for (u32 x = a & ~1u; x + 1 < e; x += 2) {
        int v = (short)(b[x - s_off] | b[x - s_off + 1] << 8);
        int w = v * gi + ((v * gf) >> 16);
        if (w > 32767) w = 32767;
        if (w < -32768) w = -32768;
        b[x - s_off] = (u8)w;
        b[x - s_off + 1] = (u8)((u32)w >> 8);
    }
    if (image_write(s_off, n, b) != 0) {
        sstate = 0;
        smp_saved = -1;
        return;
    }
    s_off += n;
}

int smp_norm_state(void)                        /* 1 normalising, 0 not */
{
    return sstate >= 3;
}

int smp_work_pct(void)                          /* how far the save, or the normalising, is */
{
    u32 lo = (REC_OFFSET + s_place) & ~511u, span = s_end > lo ? s_end - lo : 1u, at;
    if (sstate == 4)
        at = l_off > lo ? l_off - lo : 0u;
    else if (sstate >= 1)
        at = s_off > lo ? s_off - lo : 0u;
    else
        return 100;
    if (sstate == 3 || sstate == 4)             /* the normalising: the +Drive, then the DSP */
        return (int)((sstate == 3 ? 0u : 50u) + (at >> 8) * 50u / ((span >> 8) + 1u));
    return (int)((at >> 8) * 100u / ((span >> 8) + 1u));
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
    if (sstate == 3) {                          /* v0.25: normalising the +Drive's copy */
        if (s_off < s_end) {
            norm_chunk();
            return;
        }
        if (smp_lstate != L_DONE && smp_lstate != L_IDLE)
            return;
        u32 lo = (REC_OFFSET + s_place) & ~511u;   /* then the DSP's, as the loader loads */
        overview_clear((int)s_slot);
        l_kind = K_FRAMES;
        l_off = lo;
        l_end = s_end;
        l_entry = -1;
        l_slot = (u32)SMP_ALL + 1u;
        area_push = -1;
        fast_on = 1;
        smp_lstate = L_READ;
        sstate = 4;
        return;
    }
    if (sstate == 4) {
        if (smp_lstate == L_DONE || smp_lstate == L_IDLE) {
            sstate = 0;
            smp_saved = smp_lstate == L_DONE ? 1 : -1;
        }
        return;
    }
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
            peak_add(s_off, s_n * 4u, STAGE(1));
            s_off += s_n * 4u;
            if (s_off < s_end) {
                save_window();
                return;
            }
            /* the slot's directory entry and name, into the image's directory page */
            u8 *e = ENTRY(s_slot);
            put_le32(e, SMP_POOL_DDR + REC_OFFSET + s_place);
            put_le32(e + 4, s_frames);
            put_le32(e + 8, 0x3F800000u);                    /* rate 1.0 */
            put_le32(e + 12, 1);                             /* int16 */
            u8 *nm = NAME(s_slot);                           /* REC + the slot, as SAMP shows it */
            u32 sn = s_slot + 1;
            nm[0] = 'R'; nm[1] = 'E'; nm[2] = 'C';
            nm[3] = (u8)('0' + sn / 100); nm[4] = (u8)('0' + sn / 10 % 10); nm[5] = (u8)('0' + sn % 10);
            nm[6] = 0; nm[7] = 0;
            if (le32(DIR + 4) < s_slot + 1)                  /* the count covers it */
                put_le32(DIR + 4, s_slot + 1);
            u32 bytes = smp_hi > s_end ? smp_hi : s_end;
            if (image_write(0, DIR_BYTES, DIR) != 0 || header_write(bytes) != 0) {
                sstate = 0;
                smp_saved = -1;
                return;
            }
            smp_hi = bytes;
            smp_pl_changed();                                /* v0.38: into the project's list */
            smp_head_due = 1;                                /* v0.38: and the count to the DSP */
            if (!s_keep && s_peak > 0u && s_peak < NORM_PEAK) {     /* not all zero, under full scale: normalised (v0.41); a FLEX save never (v0.63) */
                s_off = (REC_OFFSET + s_place) & ~511u;
                sstate = 3;
                return;
            }
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

/* -- v0.22: after a recording, the DT2's TRIM and NAME (rec.c) -------------------------------- */

static int dir_due __attribute__((section(".data"))) = 0;       /* DIR to the +Drive when idle (v0.65: bit b, bank b's page) */
#define DUE(k) (1 << G_BANK(k))
static int push_slot __attribute__((section(".data"))) = -1;    /* an entry the DSP must take */
/* v0.29: and the ones behind it (a multi-select DELETE changes many at once; each goes to
 * the DSP in turn, as one does) */
static u32 push_more[SMP_ALL / 32] __attribute__((section(".data"))) = {0};   /* (v0.65: global slots) */

static void push_entry(int k)
{
    if (push_slot < 0 || push_slot == k)
        push_slot = k;
    else if (k >= 0 && k < SMP_ALL)
        push_more[k >> 5] |= 1u << (k & 31);
}
static int area_slot_due __attribute__((section(".data"))) = -1; /* v0.23: a slot's slice table to the +Drive and the DSP */

void smp_push_slot(int k)                       /* v0.44: a slot's entry to the DSP (a BOUNCE take saved) */
{
    push_entry(k);
}

/* slot K's frames: 0 if none */
u32 smp_frames(int k)
{
    if (!g_ok(k) || smp_slot_empty(k))
        return 0;
    return le32(ENTRY(k) + 4);
}

/* slot K keeps frames [S, E) of what it holds: its entry moves (on an even frame, so the
 * address stays on a word), its waveform is redrawn from the columns it keeps */
int smp_trim(int k, u32 s, u32 e)
{
    u32 n = smp_frames(k);
    s &= ~1u;
    if (!n || e > n || s + 64u > e)
        return -1;
    u8 *en = ENTRY(k);
    put_le32(en, le32(en) + 2u * s);
    put_le32(en + 4, e - s);
    u8 *o = OVW(k), t[OVERVIEW_W];
    for (u32 j = 0; j < OVERVIEW_W; j++) {
        u32 f = s + (e - s) / OVERVIEW_W * j;
        u32 c = (f >> 6) * OVERVIEW_W / ((n >> 6) + 1);
        t[j] = o[c < OVERVIEW_W ? c : OVERVIEW_W - 1];
    }
    for (u32 j = 0; j < OVERVIEW_W; j++)
        o[j] = t[j];
    dir_due |= DUE(k);
    push_entry(k);
    return 0;
}

/* slot K forgets its sound (FUNC + NO on TRIM): an empty slot again, its room free */
void smp_discard(int k)
{
    if (!g_ok(k) || G_SLOT(k) >= POOL_SLOTS - 1 || !dir_ok)
        return;
    u8 *en = ENTRY(k);
    for (int j = 0; j < 16; j++)
        en[j] = 0;
    u8 *nm = NAME(k);
    for (int j = 0; j < NAME_BYTES; j++)
        nm[j] = 0;
    if (G_SLOT(k) < REC_FIRST || G_BANK(k))
        put_le32(LIBID(k), 0);                   /* v0.39: no library sample's any more */
    overview_clear(k);
    dir_due |= DUE(k);
    push_entry(k);
}

/* slot K's name (NAME_BYTES - 1 characters at most) */
void smp_rename(int k, const char *name)
{
    if (!g_ok(k) || !dir_ok)
        return;
    u8 *nm = NAME(k);
    int j = 0;
    for (; j < NAME_BYTES - 1 && name[j]; j++)
        nm[j] = (u8)name[j];
    for (; j < NAME_BYTES; j++)
        nm[j] = 0;
    dir_due |= DUE(k);
}

/* v0.46: a name from the naming screen (up to 35 characters): the short name its stem (upper
 * case, A-Z 0-9 space _ # -, seven at most: as LOAD TO PROJECT makes one), and, where the
 * pool keeps long names, the whole of it, so smp_long_name shows it and the +DRIVE browser
 * matches it to its library copy (smp_lib_slot_of) */
static void stem7(const char *ln, char *st);
static int meta_due __attribute__((section(".data"))) = 0;    /* META to the +Drive when idle (v0.65: bit b, bank b's) */
void smp_name_set(int k, const char *name)
{
    if (!g_ok(k) || !dir_ok || !name[0])
        return;
    char st[8];
    stem7(name, st);
    smp_rename(k, st[0] ? st : name);
    if (meta_has(k)) {
        u8 *m = (u8 *)meta_slot(k);
        u32 j = 0;
        for (; j < META_NAME_BYTES - 1 && name[j]; j++)
            m[4 + j] = (u8)name[j];
        for (; j < META_NAME_BYTES; j++)
            m[4 + j] = 0;
        meta_due |= DUE(k);
    }
}

/* -- v0.23: the slice editor's side (slice.c) ------------------------------------------------ */

static int an_state __attribute__((section(".data"))) = 0;      /* 0 idle, 1 running, 2 done, -1 failed */
static int an_slot __attribute__((section(".data"))) = -1;
#define D_ __attribute__((section(".data")))
static u32 an_lo D_ = 0, an_hi D_ = 0, an_at D_ = 0;           /* bytes into the image */
static u32 an_hop D_ = 64, an_n D_ = 0, an_acc D_ = 0, an_cnt D_ = 0;   /* frames a step; steps */
static int an_tries D_ = 0;                                      /* v0.40: the chunk's refused reads */
#define AN_TRIES 8

/* slot K's frames and whether its frames are int16 (all that dn2samples and the recorder make) */
u32 smp_slot_frames(int k, int *i16)
{
    u32 n = smp_frames(k);
    if (i16)
        *i16 = n && ENTRY(k)[12] == 1;
    return n;
}

/* v0.62 (impbox): the slice editor's deep zoom and its zero-crossing snap read a few frames of
 * the sample itself from the +Drive: frames [F0, F0 + N) of slot K (int16 only, N at most
 * FINE_MAX), at once, only while nothing else of ours reads or writes. -> the first frame's
 * bytes (little-endian int16), 0 if not now or not possible */
#define FINE_MAX 8192u
#define FINE ((u8 *)(SMP_MIRROR + 0x79000u))
_Static_assert(0x78000u + HIRES_W <= 0x79000u && 0x79000u + 2u * FINE_MAX + 512u <= 0x80000u,
               "the editor's frames lie between the fine waveform and the meta block");
u32 smp_fine_reads __attribute__((section(".data"))) = 0;
const u8 *smp_frames_read(int k, u32 f0, u32 n)
{
    int i16;
    u32 fr = smp_slot_frames(k, &i16);
    if (!fr || !i16 || !n || n > FINE_MAX || f0 >= fr || n > fr - f0 || !store_ok()
        || sstate || an_state == 1 || (smp_lstate != L_DONE && smp_lstate != L_IDLE) || is_recording(k))
        return 0;
    u32 lo = le32(ENTRY(k)) - SMP_POOL_DDR + 2u * f0;
    u32 a = lo & ~511u, b = (lo + 2u * n + 511u) & ~511u;
    if (b - a > 2u * FINE_MAX + 512u || image_read(a, b - a, FINE) != 0)
        return 0;
    smp_fine_reads++;
    return FINE + (lo - a);
}

/* read slot K's frames from the +Drive, a chunk a UI pass: the fine waveform (HIRES_W
 * column peaks 0..255) and the energy envelope the transient finder reads */
int smp_analyse(int k)
{
    int i16;
    u32 n = smp_slot_frames(k, &i16);
    if (!n || !i16 || an_state == 1 || !store_ok())
        return -1;
    an_slot = k;
    an_lo = le32(ENTRY(k)) - SMP_POOL_DDR;
    an_hi = an_lo + 2u * n;
    an_at = an_lo & ~511u;
    an_hop = n / ENV_MAX + 1u;
    if (an_hop < 64u)
        an_hop = 64u;
    an_n = 0;
    an_acc = 0;
    an_cnt = 0;
    an_tries = 0;
    for (u32 j = 0; j < HIRES_W; j++)
        HIRES[j] = 0;
    an_state = 1;
    return 0;
}

/* v0.40 (a user: EDIT SLICE POINTS and CREATE SLICE GRID "sometimes return CANNOT READ IT;
 * repeatedly selecting eventually works"): the slice menus' start of the read. smp_analyse
 * refuses while any read runs, and the recorder's TRIM starts one on every saved take (rec.c),
 * 64 KB a UI pass: a long take's ran on for seconds after the recorder closed, and every
 * slice menu opened meanwhile said CANNOT READ IT. Here the menu's read comes first: another
 * slot's is dropped (TRIM falls back to its overview), the same slot's is kept. And it waits,
 * not fails, while the slot cannot be read yet: a pool switch under way, the +Drive not up,
 * the slot's take still being saved or normalised (its frames on the +Drive not yet final),
 * LOAD TO PROJECT still copying into it. -> 0 started (or running for K), 1 not now, -1 never
 * (no int16 sample there, no store) */
static int lp_into(int k);
int smp_analyse_ui(int k)
{
    if (smp_pl_busy() || !BLK_READY)
        return 1;
    if (!g_ok(k))
        return -1;
    if ((sstate && s_slot == (u32)k) || lp_into(k))
        return 1;
    int i16;
    if (!smp_slot_frames(k, &i16) || !i16 || !store_ok())
        return -1;
    if (an_state == 1 && an_slot == k)
        return 0;
    if (an_state == 1)
        an_state = 0;
    return smp_analyse(k) == 0 ? 0 : -1;
}

int smp_analysis(int *pct)
{
    if (pct)
        *pct = an_state == 1 && an_hi > an_lo ? (int)((an_at - (an_lo & ~511u)) / ((an_hi - an_lo) / 100u + 1u)) : 100;
    return an_state;
}

int smp_analysis_slot(void) { return an_slot; }   /* v0.33: whose the analysis is */
void smp_analyse_cancel(void) { if (an_state == 1) an_state = 0; }   /* v0.33: NO left it */

const u8 *smp_hires(void)
{
    return HIRES;
}

static void analyse_poll(void)
{
    if (an_state != 1)
        return;
    u32 n = an_hi - an_at;
    if (n > CHUNK)
        n = CHUNK;
    n = (n + 511u) & ~511u;
    if (image_read(an_at, n, STAGE(3)) != 0) {
        if (++an_tries < AN_TRIES)              /* v0.40: a refused read is tried again, the */
            return;                             /* next passes; AN_TRIES refusals in a row: failed */
        an_state = -1;
        return;
    }
    an_tries = 0;
    u32 frames = (an_hi - an_lo) / 2u;
    for (u32 x = an_at; x < an_at + n; x += 2) {
        if (x < an_lo || x + 1 >= an_hi)
            continue;
        u32 i = (x - an_lo) / 2u;
        int v = (short)(STAGE(3)[x - an_at] | STAGE(3)[x - an_at + 1] << 8);
        int a = v < 0 ? -v : v;
        u32 col = (i >> 6) * HIRES_W / ((frames >> 6) + 1u);
        u8 pk = (u8)(a >> 7);
        if (col < HIRES_W && pk > HIRES[col])
            HIRES[col] = pk;
        u32 q = (u32)(a >> 6);
        an_acc += q * q;
        if (++an_cnt == an_hop) {
            if (an_n < ENV_MAX)
                ENV[an_n++] = an_acc / an_hop;
            an_acc = 0;
            an_cnt = 0;
        }
    }
    an_at += n;
    if (an_at >= an_hi)
        an_state = 2;
}

/* the transients of the analysed slot, as the host tool finds them (dn2samples.onsets):
 * where the energy jumps fourfold over the last four steps, 50 ms apart at least. -> how
 * many starts (the first 0), at most MOST */
int smp_onsets(u32 *out, int most)
{
    if (an_state != 2 || most < 1)
        return 0;
    u32 top = 0;
    for (u32 k = 0; k < an_n; k++)
        if (ENV[k] > top)
            top = ENV[k];
    u32 floor = top / 10000u, gap = 2400u / an_hop;
    if (gap < 1u)
        gap = 1u;
    int c = 0;
    out[c++] = 0;
    u32 last = 0;
    for (u32 k = 1; k < an_n && c < most; k++) {
        u32 lo = k > 4u ? k - 4u : 0u, sum = 0;
        for (u32 j = lo; j < k; j++)
            sum += ENV[j] / 4u;
        u32 prev = sum * 4u / (k - lo);
        if (ENV[k] > floor && ENV[k] / 4u > prev && k - last >= gap
            && k * an_hop - out[c - 1] >= 2400u) {
            out[c++] = k * an_hop;
            last = k;
        }
    }
    return c;
}

/* slot K's slices into T (start, end, loop each): -> how many. From the slice area's copy
 * or, made by the host tool, read from the +Drive */
int smp_slices_get(int k, u32 *t)
{
    if (!g_ok(k) || !dir_ok)
        return 0;
    const u8 *e = ENTRY(k);
    u32 ns, at = slice_table(k, &ns);
    if (!ns)
        return 0;
    const u8 *src;
    if (e[14] & 1) {
        src = SLTB(k);
    } else {
        u32 a0 = at & ~511u, nb = ((at + 12u * ns + 511u) & ~511u) - a0;
        if (nb > CHUNK || image_read(a0, nb, STAGE(3)) != 0)
            return 0;
        src = STAGE(3) + (at - a0);
    }
    for (u32 j = 0; j < 3u * ns; j++)
        t[j] = le32(src + 4u * j);
    return (int)ns;
}

/* slot K's slices from T (N of them, sorted by start): kept in the slice area, on the
 * +Drive and in the DSP (the table first, then the entry that points at it) */
int smp_slices_set(int k, const u32 *t, int n)
{
    if (!g_ok(k) || G_SLOT(k) >= POOL_SLOTS - 1 || !dir_ok || n < 0 || n > SLICE_MAX
        || (!G_BANK(k) && !smp_area_ok()) || !smp_frames(k))
        return -1;
    u32 fr = smp_frames(k);
    u8 *tb = SLTB(k);
    for (u32 j = 0; j < SLICE_TB; j++)
        tb[j] = 0;
    for (int j = 0; j < 3 * n; j++)
        put_le32(tb + 4 * j, t[j] > fr ? fr : t[j]);
    u8 *e = ENTRY(k);
    e[13] = (u8)n;
    e[14] = (u8)(n ? e[14] | 1u : e[14] & ~1u);
    for (int j = 0; j < SLICE_MAX; j++)
        SCOL(k)[j] = 0;
    for (int j = 0; j < n; j++) {
        u32 st = t[3 * j];
        SCOL(k)[j] = (u8)(st >= fr ? OVERVIEW_W - 1 : st / (fr / (OVERVIEW_W - 1) + 1u));
    }
    area_slot_due = k;                          /* to the +Drive, then the DSP */
    dir_due |= DUE(k);
    push_entry(k);
    return 0;
}

/* the directory to the +Drive, and a changed entry to the DSP, once nothing else runs */
static void edits_poll(void)
{
    if (sstate || (smp_lstate != L_DONE && smp_lstate != L_IDLE))
        return;
    if (dir_due) {
        u32 bytes = smp_hi;
        for (u32 k = 0; k < POOL_SLOTS; k++) {          /* the image runs to its last recording */
            if (!is_recording(k))
                continue;
            u32 a = le32(ENTRY(k)) - SMP_POOL_DDR + le32(ENTRY(k) + 4) * 2u;
            if (a > bytes)
                bytes = a;
        }
        bytes = (bytes + 511u) & ~511u;
        if (bytes < DIR_BYTES)
            bytes = DIR_BYTES;
        /* v0.65: every page that changed first (banks B..D's whole directory page), then the
         * header that checks them all */
        int ok = !(dir_due & 1) || image_write(0, DIR_BYTES, DIR) == 0;
        for (u32 b = 1; b < BANK_N && ok; b++)
            if (dir_due & (1 << b) && smp_bank_live((int)b)) {
                bimg_sum[b] = 0;                        /* (the image's copy: not the whole known) */
                ok = image_write(BPAGE_OFF(b), DIR_BYTES, BPAGE(b)) == 0;
                if (bytes < TABLE_AREA)
                    bytes = TABLE_AREA;                 /* the image runs past the pages */
            }
        dir_due = 0;
        if (ok && header_write(bytes) == 0) {
            smp_hi = bytes;
            smp_pl_changed();                       /* v0.38: into the project's list, at once */
        }
        return;
    }
    if (meta_due & 1 && meta_ok && le32(DIR + META_PTR) == META_PTR_MAGIC) {   /* v0.46: the long names */
        meta_due &= ~1;
        u32 mo = le32(DIR + META_PTR + 4), mn = (le32(DIR + META_PTR + 8) + 511u) & ~511u;
        image_write(mo, mn, META);
        return;
    }
    meta_due &= ~1;
    if (meta_due) {                                 /* v0.65: a bank's, in its page */
        u32 b = low_bit((u32)meta_due);
        meta_due &= ~(1 << b);
        if (smp_bank_live((int)b)) {
            bimg_sum[b] = 0;
            image_write(BPAGE_OFF(b) + BANK_META, BANK_SLICES - BANK_META, BPAGE(b) + BANK_META);
        }
        return;
    }
    if (area_slot_due >= 0) {                       /* v0.23: the slot's table's sectors */
        u32 so = SLOFF(area_slot_due);
        u32 a0 = so & ~511u;
        u32 a1 = (so + SLICE_TB + 511u) & ~511u;
        u8 *ram = ram_of(a0);
        if (G_BANK(area_slot_due))
            bimg_sum[G_BANK(area_slot_due)] = 0;
        if (ram)
            image_write(a0, a1 - a0, ram);
        u32 top = G_BANK(area_slot_due) ? TABLE_AREA : SLICE_AREA + SLAREA_BYTES;
        if (smp_hi < top && header_write(top) == 0)
            smp_hi = top;
        if (!smp_pl_busy())
            area_push = area_slot_due;              /* the table goes before the entry */
        area_slot_due = -1;
        smp_pl_changed();                           /* v0.38: the list takes the table too */
    }
    if (smp_pl_busy())                              /* v0.38: a switch: nothing of the old pool */
        return;                                     /*   goes to the DSP */
    if (push_slot < 0)                              /* v0.29: the next one waiting */
        for (int k = 0; k < SMP_ALL; k++)
            if (push_more[k >> 5] & (1u << (k & 31))) {
                push_more[k >> 5] &= ~(1u << (k & 31));
                push_slot = k;
                break;
            }
    if (push_slot >= 0 && fast_on) {                /* the loader's own path: sent, checked */
        l_entry = push_slot;
        push_slot = -1;
        l_slot = (u32)SMP_ALL + 1u;
        smp_lstate = next_range() ? L_READ : L_DONE;
    } else if (smp_head_due && fast_on && dir_ok) { /* v0.38: the count, on its own (a recording began) */
        l_entry = -1;
        l_slot = (u32)SMP_ALL + 1u;
        smp_lstate = next_range() ? L_READ : L_DONE;
    }
}

/* v0.38: a recording into slot K has begun (rec.c): the DSP plays it as it records only if
 * its count covers K, so the count goes to the DSP now (the directory itself takes the slot
 * when the recording is saved) */
void smp_count_cover(int k)
{
    if (k < 0 || k >= REC_FIRST)
        return;                                     /* the DSP's own slots need no count */
    if ((u32)k + 1u > smp_head_min)
        smp_head_min = (u32)k + 1u;
    smp_head_due = 1;
}

/* -- v0.31: LOAD TO PROJECT: a library sample (lib.c) into the first empty pool slot ----------
 * Queued from the browser; one at a time, one 64 KB chunk a pass while the loader and the
 * saver are idle: room in the pool's own areas (first fit among the slots' extents and the
 * meta block), the frames copied +Drive to +Drive, the slot's entry and name, the directory
 * saved, then that slot sent to the DSP by the loader's own checked path. */
extern int smp_lib_used(int k);
extern u32 smp_lib_frames(int k);
extern int smp_lib_fmt(int k);
extern u32 smp_lib_rate(int k);
extern const char *smp_lib_name(int k);
extern int smp_lib_read(int k, u32 off, u32 bytes, void *buf);
extern u8 *smp_lib_stage(void);
extern int smp_lib_busy(void);
#define LPQ 16
static short lp_q[LPQ] __attribute__((section(".data")));
static u32 lp_head __attribute__((section(".data"))) = 0, lp_tail __attribute__((section(".data"))) = 0;
static int lp_k __attribute__((section(".data"))) = -1;      /* the library entry being copied */
static int lp_slot __attribute__((section(".data"))) = -1;
static int lp_into(int k) { return lp_k >= 0 && lp_slot == k; }   /* v0.40: LOAD TO PROJECT copying into K */
static u32 lp_off __attribute__((section(".data"))) = 0, lp_bytes __attribute__((section(".data"))) = 0;
static u32 lp_at __attribute__((section(".data"))) = 0;
int smp_lp_done __attribute__((section(".data"))) = 0;       /* loaded since the browser asked */
int smp_lp_full __attribute__((section(".data"))) = 0;       /* refused: no slot or no room */
int smp_lp_bank __attribute__((section(".data"))) = 0;       /* v0.65: the bank LOAD TO PROJECT fills first */
static int one_due __attribute__((section(".data"))) = -1;    /* a slot for the DSP, when idle */

u32 smp_lp_queued __attribute__((section(".data"))) = 0;    /* ever queued (the gate reads it) */

int smp_lib_load(int k)                          /* -> 0 queued */
{
    if (!smp_lib_used(k) || lp_head - lp_tail >= LPQ)
        return -1;
    lp_q[lp_head++ % LPQ] = (short)k;
    smp_lp_queued++;
    return 0;
}

int smp_lib_pending(void) { return (int)(lp_head - lp_tail) + (lp_k >= 0); }

/* the pool slot holding library entry K (same frames, same short name), or -1 */
static void stem7(const char *ln, char *st)
{
    int n = 0;
    for (int j = 0; ln[j] && n < 7; j++) {
        char c = ln[j];
        if (c >= 'a' && c <= 'z')
            c = (char)(c - 32);
        if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == ' ' || c == '_' || c == '#' || c == '-')
            st[n++] = c;
    }
    st[n] = 0;
}

/* v0.39: the identity LOAD TO PROJECT gives a slot: the library sample's frames' adler-32
 * (lib.c's +16: the same audio wherever it lies, and a deleted entry's hole refilled reads
 * as another) mixed with the slot's own pool address (a slot whose frames were replaced
 * since no longer matches); never 0, which is none */
extern u32 smp_lib_sum(int k);
static u32 lib_id(u32 sum, u32 addr)
{
    u32 id = sum ^ (addr * 0x9E3779B1u);
    return id ? id : 1u;
}

int smp_lib_slot_of(int k)
{
    if (!dir_ok || !smp_lib_used(k))
        return -1;
    char st[8];
    const char *ln = smp_lib_name(k);
    stem7(ln, st);
    u32 fr = smp_lib_frames(k), rate = smp_lib_rate(k), fmt = (u32)smp_lib_fmt(k), sum = smp_lib_sum(k);
    for (int s = 0; s < SMP_ALL; s++) {         /* v0.65: every bank's (A's below the recorder's) */
        if (s < POOL_SLOTS ? s >= REC_FIRST : !g_ok(s))
            continue;
        const u8 *e = ENTRY(s);
        if (smp_slot_empty(s) || le32(e + 4) != fr || le32(e + 8) != rate || le32(e + 12) != fmt)
            continue;
        /* v0.39: only the slot LOAD TO PROJECT filled from this very sample. v0.38 went by the
         * frames and the names alone, and a pack's samples of one length (one tempo's loops,
         * padded one-shots) whose names are one for their 35 characters, or for their stem's
         * seven where the pool has no long names, all read as the first loaded: shown in its
         * slot, previewed as it, never loaded themselves (the owner, v0.38). A slot with no
         * identity (an older pool's, a recording, the host tools') matches nothing: such a
         * sample previews from the +Drive and loads into a slot of its own, never as another */
        if (le32(LIBID(s)) != lib_id(sum, le32(e)))
            continue;
        const char *nm = smp_name(s);
        int j = 0;
        while (j < 8 && st[j] == nm[j] && st[j])
            j++;
        if (j == 8 || st[j] != nm[j])
            continue;
        /* v0.35: the slot's long name too, where it has one (LOAD TO PROJ writes it): two
         * library samples of one length whose names differ past their seventh character
         * (a pack's "808 KICK A" and "808 KICK B") read as one, so the second never loaded
         * (Pablo, v0.33: "some of them don't update") */
        if (meta_has(s)) {
            const u8 *m = (const u8 *)meta_slot(s);
            if (m[0] == 0xFF && m[4]) {
                u32 i = 0;
                while (i < META_NAME_BYTES - 1 && m[4 + i] && m[4 + i] == (u8)ln[i])
                    i++;
                if (!(i == META_NAME_BYTES - 1 || (!m[4 + i] && !ln[i])))
                    continue;
            }
        }
        return s;
    }
    return -1;
}

static int clashes(u32 a, u32 z, u32 lo, u32 hi) { return a < hi && lo < z; }

/* BYTES (512-rounded) of room in the pool's areas -> its offset, or 0 */
static u32 pool_room(u32 bytes)
{
    static const u32 seg[2][2] = {{DATA_OFFSET, REC_OFFSET}, {REC_END, POOL_BYTES}};
    for (int g = 0; g < 2; g++) {
        u32 cand = seg[g][0], top = seg[g][1] < ram_top ? seg[g][1] : ram_top;
        int passes = SMP_ALL + 2 + smp_pl_res_count();        /* (each pass moves CAND on, or ends) */
        for (int pass = 0; pass <= passes; pass++) {
            int moved = 0;
            if (cand + bytes > top)
                break;
            u32 z = smp_pl_clash(cand, cand + bytes);       /* v0.38: another project's extents */
            if (z) {
                cand = z;
                moved = 1;
                continue;
            }
            for (u32 s = 0; s < (u32)SMP_ALL; s++) {           /* v0.65: every bank's */
                if (!g_ok((int)s))
                    continue;
                const u8 *e = ENTRY(s);
                u32 addr = le32(e), fr = le32(e + 4);
                if (addr < SMP_POOL_DDR + DATA_OFFSET || !fr)
                    continue;
                u32 lo = addr - SMP_POOL_DDR, n = fr * (e[12] ? 2u : 4u), ns, tbl = slice_table((int)s, &ns);
                if (ns && !(e[14] & 1))
                    n = tbl - lo + 12u * ns;
                u32 hi = (lo + n + 511u) & ~511u;
                if (clashes(cand, cand + bytes, lo & ~511u, hi)) {
                    cand = hi;
                    moved = 1;
                }
            }
            if (le32(DIR + META_PTR) == META_PTR_MAGIC) {
                u32 mo = le32(DIR + META_PTR + 4), mn = (le32(DIR + META_PTR + 8) + 511u) & ~511u;
                if (clashes(cand, cand + bytes, mo, mo + mn)) {
                    cand = mo + mn;
                    moved = 1;
                }
            }
            if (clashes(cand, cand + bytes, TABLE_AREA, SLICE_AREA + SLAREA_BYTES)) {
                cand = SLICE_AREA + SLAREA_BYTES;
                moved = 1;
            }
            if (!moved)
                return cand + bytes <= top ? cand : 0;
        }
    }
    return 0;
}

int smp_lib_preview(int k)                       /* -> 0: asked; -1: not now */
{
    extern int smp_lib_used(int k), smp_lib_fmt(int k);
    extern u32 smp_lib_frames(int k);
    if (!smp_lib_used(k) || !smp_lib_fmt(k) || smp_tables == 1 || !dir_ok || smp_pl_busy())
        return -1;                              /* int16 only (the DSP's preview reads int16) */
    u32 b = smp_lib_frames(k) * 2u;
    if (b > PREVIEW_BYTES)
        b = PREVIEW_BYTES;
    b = (b + 511u) & ~511u;
    u32 off = pool_room(b);
    if (!off || off > POOL_BYTES - PREVIEW_BYTES)
        return -1;                              /* (the DSP holds a preview below that: the review) */
    pv_k = k;
    pv_off = off;
    pv_bytes = b;
    smp_pv_state = 1;
    return 0;
}

void smp_lib_preview_stop(void)
{
    if (smp_pv_state == 3)
        smp_command(CMD_PREVIEW, PREVIEW_AT, 0, 0, 0);
    if (smp_pv_state == 2 && l_kind == K_PREVIEW)
        l_end = l_off;                          /* the chunk in flight is the last */
    smp_pv_state = 0;
    pv_k = -1;
}

static void pv_poll(void)
{
    if (smp_pv_state == 2 && pv_k < 0)
        smp_pv_state = 0;                           /* the +Drive refused it */
    if (smp_pv_state == 2 && (l_kind != K_PREVIEW || smp_lstate == L_DONE || smp_lstate == L_IDLE
                          || l_off - pv_off >= (pv_bytes < PV_START ? pv_bytes : PV_START))) {
        smp_command(CMD_PREVIEW, PREVIEW_AT, pv_off, (pv_bytes / 2u), 0);
        smp_pv_state = 3;
    }
}

static void lp_poll(void)
{
    pv_poll();
    if (smp_pl_busy())                                   /* v0.38: a switch */
        return;
    if (sstate || (smp_lstate != L_DONE && smp_lstate != L_IDLE) || smp_lib_busy())
        return;
    if (smp_pv_state == 1) {                             /* v0.33: +DRIVE's preview */
        if (smp_tables == 1 || pv_k < 0) {
            smp_pv_state = 0;
            return;
        }
        l_kind = K_PREVIEW;
        l_off = pv_off;
        l_end = pv_off + pv_bytes;
        l_slot = (u32)SMP_ALL + 1u;
        l_entry = -1;
        smp_pv_state = 2;
        smp_lstate = L_READ;
        return;
    }
    if (one_due >= 0) {                              /* the copied slot to the DSP */
        if (slot_range((u32)one_due)) {
            l_slot = (u32)SMP_ALL + 1u;
            smp_lstate = L_READ;
        }
        one_due = -1;
        return;
    }
    if (lp_k < 0) {
        if (lp_head == lp_tail)
            return;
        int k = lp_q[lp_tail++ % LPQ];
        if (!smp_lib_used(k) || smp_lib_slot_of(k) >= 0)
            return;                                  /* gone, or already in the pool */
        if (!dir_ok) {                               /* no pool yet: an empty directory */
            for (u32 b = 0; b < DIR_BYTES; b++)
                DIR[b] = 0;
            put_le32(DIR, POOL_MAGIC);
            dir_ok = 1;
            smp_hi = DIR_BYTES;
        }
        /* v0.65: the first empty slot of the list's bank, then of the banks after it (and A's
         * before it), bank A's below the recorder's, B..D's 0..126 */
        int s = -1;
        for (int i = 0; i < BANK_N && s < 0; i++) {
            int b = (smp_lp_bank + i) % BANK_N;
            if (!smp_bank_live(b))
                continue;
            for (int j = 0; j < (b ? 127 : REC_FIRST) && s < 0; j++)
                if (smp_slot_empty(G_OF(b, j)))
                    s = G_OF(b, j);
        }
        u32 bytes = (smp_lib_frames(k) * (smp_lib_fmt(k) ? 2u : 4u) + 511u) & ~511u;
        u32 off = s >= 0 ? pool_room(bytes) : 0;
        if (!off) {
            smp_lp_full = 1;
            return;
        }
        lp_k = k;
        lp_slot = s;
        lp_off = off;
        lp_bytes = bytes;
        lp_at = 0;
        return;
    }
    u32 n = lp_bytes - lp_at;
    if (n > CHUNK)
        n = CHUNK;
    u8 *buf = smp_lib_stage();
    if (smp_lib_read(lp_k, lp_at, n, buf) != 0 || image_write(lp_off + lp_at, n, buf) != 0) {
        lp_k = -1;                                   /* the +Drive refused: this one stops */
        return;
    }
    lp_at += n;
    if (lp_at < lp_bytes)
        return;
    u8 *e = ENTRY(lp_slot);                          /* done: the entry, the name */
    put_le32(e, SMP_POOL_DDR + lp_off);
    put_le32(e + 4, smp_lib_frames(lp_k));
    put_le32(e + 8, smp_lib_rate(lp_k));
    put_le32(e + 12, (u32)smp_lib_fmt(lp_k));
    put_le32(LIBID(lp_slot), lib_id(smp_lib_sum(lp_k), SMP_POOL_DDR + lp_off));   /* v0.39: which sample */
    char st[8];
    stem7(smp_lib_name(lp_k), st);
    smp_rename(lp_slot, st);
    u8 *pg = page_of(G_BANK(lp_slot));               /* its page's count covers it */
    if (le32(pg + 4) < G_SLOT(lp_slot) + 1u)
        put_le32(pg + 4, G_SLOT(lp_slot) + 1u);
    if (G_BANK(lp_slot)) {                           /* v0.65: a bank's meta, in its page */
        u8 *m = (u8 *)meta_slot(lp_slot);
        const char *ln = smp_lib_name(lp_k);
        m[0] = 0xFF;
        u32 j = 0;
        for (; j < META_NAME_BYTES - 1 && ln[j]; j++)
            m[4 + j] = (u8)ln[j];
        for (; j < META_NAME_BYTES; j++)
            m[4 + j] = 0;
        meta_due |= DUE(lp_slot);
    } else if (meta_ok) {                            /* its long name; in no folder */
        u8 *m = (u8 *)meta_slot(lp_slot);
        const char *ln = smp_lib_name(lp_k);
        m[0] = 0xFF;
        u32 j = 0;
        for (; j < META_NAME_BYTES - 1 && ln[j]; j++)
            m[4 + j] = (u8)ln[j];
        for (; j < META_NAME_BYTES; j++)
            m[4 + j] = 0;
        u32 mo = le32(DIR + META_PTR + 4), mn = (le32(DIR + META_PTR + 8) + 511u) & ~511u;
        image_write(mo, mn, META);
    }
    if (smp_hi < lp_off + lp_bytes)
        smp_hi = lp_off + lp_bytes;
    overview_clear(lp_slot);
    dir_due |= DUE(lp_slot);                         /* saved when idle (edits_poll) */
    one_due = lp_slot;
    smp_lp_done++;
    lp_k = -1;
}

/* -- v0.46: a recording into +DRIVE > RECORDED, as the DT2 keeps every sampled take -----------
 * Queued when a recording is named (rec.c: the FILE NAME's YES or NO, as it goes on to ASSIGN).
 * The recording's own save is untouched: it is in the pool first, as it always was, so nothing
 * here can lose it. Then, one chunk a pass while the loader, the saver, a switch, a send and
 * LOAD TO PROJECT are all idle and the directory is saved: its frames are read back from the
 * pool and written into free library sectors by lib.c's send path, and the library entry goes
 * in last (one sector), in RECORDED, under the recording's name. Only then is the slot marked
 * as that library sample (LIBID, as LOAD TO PROJECT marks it), so the +DRIVE browser shows it
 * loaded. A power cut anywhere leaves the library without it or with all of it, and the pool as
 * it was. The library full, or no +Drive library: the recording stays in the pool only (the
 * owner's fallback), and the recorder's line says so. The slot changed meanwhile (dropped,
 * trimmed, another recording): the copy stops, and nothing names what it wrote */
extern int smp_lib_put_begin(u32 frames, int fmt, u32 rate, const char *name);
extern int smp_lib_put(const u8 *p, u32 m);
extern int smp_lib_put_end(void);
extern void smp_lib_put_abort(void);
#define RSQ 8
#define LIB_NAME_MAX 35                             /* lib.c's LIB_NAME - 1 */
static signed char rs_q[RSQ] __attribute__((section(".data")));
static char rs_nm[RSQ][LIB_NAME_MAX + 1] __attribute__((section(".data")));   /* the name it goes in under */
static u32 rs_head __attribute__((section(".data"))) = 0, rs_tail __attribute__((section(".data"))) = 0;
static int rs_slot __attribute__((section(".data"))) = -1;    /* the recording being copied */
static u32 rs_addr __attribute__((section(".data"))) = 0, rs_frames __attribute__((section(".data"))) = 0;
static u32 rs_bytes __attribute__((section(".data"))) = 0, rs_at __attribute__((section(".data"))) = 0;
u32 smp_rs_done __attribute__((section(".data"))) = 0;        /* recordings put into RECORDED (the gate reads it) */
int smp_rs_last __attribute__((section(".data"))) = 0;        /* 1 on the +Drive, 2 the library full, 3 not now (no library) */

void smp_rec_store_named(int k, const char *name)   /* rec.c: recording K is named NAME */
{
    if (k < 0 || k >= REC_FIRST || rs_head - rs_tail >= RSQ)
        return;
    char *d = rs_nm[rs_head % RSQ];
    u32 j = 0;
    for (; j < LIB_NAME_MAX && name && name[j]; j++)
        d[j] = name[j];
    d[j] = 0;
    rs_q[rs_head++ % RSQ] = (signed char)k;
}

static void rs_poll(void)
{
    if (smp_pl_busy() || sstate || dir_due || lp_k >= 0 || lp_head != lp_tail
        || (smp_lstate != L_DONE && smp_lstate != L_IDLE) || smp_pv_state == 1 || smp_pv_state == 2 || smp_er_lock)
        return;
    if (rs_slot < 0) {
        if (rs_head == rs_tail)
            return;
        extern int smp_lib_busy(void);
        if (smp_lib_busy())
            return;                                  /* a send from the computer: after it */
        int k = rs_q[rs_tail % RSQ];
        if (!dir_ok || !store_ok() || smp_slot_empty(k) || le32(LIBID(k)) != 0) {
            rs_tail++;                               /* gone, or already a library sample's */
            return;
        }
        const u8 *e = ENTRY(k);
        u32 addr = le32(e), frames = le32(e + 4), fmt = le32(e + 12);
        u32 bytes = frames * (fmt ? 2u : 4u);
        if (addr < SMP_POOL_DDR || addr - SMP_POOL_DDR + bytes > POOL_BYTES || !frames || fmt > 1u) {
            rs_tail++;
            return;
        }
        const char *name = rs_nm[rs_tail % RSQ];        /* as named on the naming screen */
        int r = smp_lib_put_begin(frames, (int)fmt, le32(e + 8), name[0] ? name : smp_name(k));
        if (r == 4)
            return;                                  /* the computer started a send: later */
        rs_tail++;
        if (r) {
            smp_rs_last = r == 2 ? 2 : 3;
            return;
        }
        rs_slot = k;
        rs_addr = addr;
        rs_frames = frames;
        rs_bytes = bytes;
        rs_at = 0;
        return;
    }
    const u8 *e = ENTRY(rs_slot);
    if (smp_slot_empty(rs_slot) || le32(e) != rs_addr || le32(e + 4) != rs_frames) {
        smp_lib_put_abort();                         /* the slot changed: stop */
        rs_slot = -1;
        return;
    }
    u32 n = rs_bytes - rs_at;
    if (n > 0xF000u)
        n = 0xF000u;
    u32 src = rs_addr - SMP_POOL_DDR + rs_at;        /* (a trimmed take starts on any even frame) */
    u32 lo = src & ~511u, hi = (src + n + 511u) & ~511u;
    if (hi > POOL_BYTES || image_read(lo, hi - lo, STAGE(0)) != 0 || smp_lib_put(STAGE(0) + (src - lo), n) != 0) {
        smp_lib_put_abort();
        rs_slot = -1;
        smp_rs_last = 3;
        return;
    }
    rs_at += n;
    if (rs_at < rs_bytes)
        return;
    extern u32 smp_lib_sum(int k);
    int lk = smp_lib_put_end();
    if (lk >= 0) {
        put_le32(LIBID(rs_slot), lib_id(smp_lib_sum(lk), rs_addr));   /* the slot: that sample */
        dir_due |= 1;
        smp_rs_done++;
        smp_rs_last = 1;
    } else {
        smp_rs_last = 3;
    }
    rs_slot = -1;
}

/* from the UI loop (page.c's wr_poll), every pass */
void smp_boot(void)
{
    if (!smp_booted && BLK_READY) {
        /* v0.22: first the DSP's RAM check (about 0.7 s); then the image loads, past
         * RAM_PROVEN only if the check passed */
        smp_booted = 1;
        span_n = 0;                                     /* v0.38: the DSP holds nothing yet */
        for (int k = 0; k < SMP_ALL; k++)              /* (v0.65: every bank's) */
            put_le32(SSUM(k), 0);
        smp_ram = 0;                                    /* this power-on's verdict, not an older one */
        ram_top = RAM_PROVEN;
        ram_seq = smp_command(CMD_PROBE, 0, 0, 0, 0);
        ram_since = periods;                            /* the audio periods, 1,500 a second */
    }
    if (smp_booted == 1) {
        u16 h[16];
        if (smp_status(h) && h[1] == (u16)ram_seq && (h[4] == 1 || h[4] == 2))
            smp_ram = h[4];
        else if (periods - ram_since > 6000u)           /* four seconds and no verdict */
            smp_ram = 2;
        if (!smp_ram)
            return;
        ram_top = smp_ram == 1 ? POOL_BYTES : RAM_PROVEN;
        smp_booted = 2;
        extern void smp_lib_boot(void);
        smp_lib_boot();                                 /* v0.31: the library's index (lib.c) */
        extern int smp_pl_boot(void);
        if (!smp_pl_boot())                             /* v0.38: the project's own pool (pools.c) */
            smp_load();
    }
    extern void smp_pl_poll(void);
    smp_pl_poll();                                      /* v0.38: a LOAD, a NEW, a slot changed */
    {                                                   /* v0.41: a buffer take writes the recordings' area */
        extern volatile u32 rt_gen;
        static u32 rt_span_seen __attribute__((section(".data"))) = 0;
        if (rt_gen != rt_span_seen) {
            rt_span_seen = rt_gen;
            span_drop(REC_OFFSET, REC_END);
        }
    }
    load_poll();
    save_poll();
    edits_poll();
    lp_poll();                                          /* v0.31: LOAD TO PROJECT */
    rs_poll();                                          /* v0.46: a recording into +DRIVE > RECORDED */
    analyse_poll();
}

/* -- v0.38: what pools.c (per-project pools) needs of the pool here ---------------------------- */

u8 *smp_pl_dirp(void) { return DIR; }
u8 *smp_pl_metap(void) { return META; }
u8 *smp_pl_areap(void) { return SLAREA; }
int smp_pl_image_read(u32 off, u32 bytes, void *buf) { return image_read(off, bytes, buf); }
int smp_pl_image_write(u32 off, u32 bytes, const void *buf) { return image_write(off, bytes, buf); }

/* v0.65: banks B..D's pages for pools.c: B's RAM (dir + meta + slice area), an empty one, and the
 * whole of each written into the image (before the header that checks them: smp_pl_dir_commit) */
u8 *smp_pl_bankp(int b) { return b >= 1 && b < BANK_N ? BPAGE(b) : 0; }
void smp_pl_bank_blank(int b) { if (b >= 1 && b < BANK_N) bank_blank((u32)b); }
int smp_pl_banks_write(void)
{
    if (smp_bank_blocked)
        return 0;
    for (u32 b = 1; b < BANK_N; b++) {
        if (!le32(BPAGE(b) + 4))
            continue;                           /* nothing in it: the header says so (word 0) */
        u32 s = checksum(BPAGE(b), PAGE_USED);
        if (s == bimg_sum[b])
            continue;                           /* the image holds it already */
        for (u32 o = 0; o < PAGE_USED; o += CHUNK) {
            u32 n = PAGE_USED - o < CHUNK ? PAGE_USED - o : CHUNK;
            if (image_write(BPAGE_OFF(b) + o, n, BPAGE(b) + o) != 0) {
                bimg_sum[b] = 0;
                return -1;
            }
        }
        bimg_sum[b] = s;
    }
    return 0;
}

void smp_pl_read_image(void)                    /* the image's directory and meta block, as they are */
{
    smp_hi = header_read();
    dir_ok = smp_hi != 0;
    meta_read();
}

int smp_pl_dir_commit(u32 bytes)                /* DIR as the image's directory page, and its header */
{
    if (image_write(0, DIR_BYTES, DIR) != 0 || header_write(bytes) != 0)
        return -1;
    smp_hi = bytes;
    return 0;
}

/* a switch begins: the recorder stopped (its take kept in the old pool), LOAD TO PROJECT's
 * queue and the preview dropped, the loader's work dropped, and the DSP's directory sent
 * with every entry empty (checked) */
void smp_pl_quiesce(void)
{
    extern void rec_halt(void);
    rec_halt();
    smp_lib_preview_stop();
    lp_head = lp_tail;
    lp_k = -1;
    one_due = -1;
    if (an_state == 1)
        an_state = 0;
    push_slot = -1;
    for (int k = 0; k < SMP_ALL / 32; k++)
        push_more[k] = 0;
    area_push = -1;
    if (smp_tables == 1)                        /* power-on's tables: no sample is in yet */
        return;
    job_data = 0;
    smp_lstate = L_IDLE;
    if (!dir_ok)
        return;
    l_slot = (u32)SMP_ALL + 1u;                 /* the pages blank, then nothing else */
    l_entry = -1;
    area_m = 0;
    head_m = 0;
    l_full_m = 0;
    l_blank_m = live_pages();                   /* (v0.65: banks B..D's too) */
    fast_on = 1;
    smp_lstate = next_range() ? L_READ : L_DONE;
}

/* nothing of the old pool is still moving -> 1. FORCE (six seconds): a recording's save
 * that cannot finish (the link back down) is cut */
int smp_pl_idle(int force)
{
    extern int rec_busy(void);
    int quiet = smp_tables != 1 && (smp_lstate == L_DONE || smp_lstate == L_IDLE) && !sstate
                && !dir_due && area_slot_due < 0 && lp_k < 0;
    if (quiet && (force || !rec_busy()))
        return 1;
    if (!force)
        return 0;
    if (sstate) {
        rx_dest = 0;
        sstate = 0;
        smp_saved = -1;
    }
    if (smp_tables != 1 && smp_lstate != L_DONE && smp_lstate != L_IDLE) {
        job_data = 0;
        smp_lstate = L_IDLE;
    }
    return 0;                                   /* edits_poll writes what is due, then it is */
}

int smp_pl_list_ok(void)                        /* the pool's state whole on the +Drive and in RAM */
{
    return !dir_due && area_slot_due < 0 && !sstate;
}

int smp_pl_bad_any(void)
{
    u32 a = 0;
    for (int k = 0; k < SMP_ALL / 32; k++)
        a |= pl_bad[k];
    return a != 0;
}

/* the slots whose frames did not match their list: emptied (their names kept), and
 * the directory written so the list says so */
void smp_pl_bad_fix(void)
{
    for (u32 k = 0; k < (u32)SMP_ALL; k++) {
        if (!bad(k))
            continue;
        u8 *en = ENTRY(k);
        for (int j = 0; j < 16; j++)
            en[j] = 0;
        overview_clear((int)k);
        dir_due |= DUE(k);
    }
    for (u32 k = 0; k < SMP_ALL / 32; k++)
        pl_bad[k] = 0;
    dir_due |= 1;
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
    if (up_block == 0) {                        /* the directory page: yours, and the */
        u8 *nd = STAGE(2);                      /* recordings kept (v0.22: in any slot) */
        u32 count = le32(nd + 4);
        for (u32 k = 0; k < POOL_SLOTS - 1 && rec_keep; k++) {
            if (!is_recording(k))
                continue;
            u32 j = k;                          /* its own slot, if the new image leaves it */
            if (le32(nd + 8 + 16 * j + 4) != 0) {           /* empty; else the first empty */
                for (j = 0; j < POOL_SLOTS - 1 && le32(nd + 8 + 16 * j + 4) != 0; j++)
                    ;
                if (j >= POOL_SLOTS - 1)
                    continue;                   /* no room: it is not kept */
            }
            for (u32 b = 0; b < 16; b++)
                nd[8 + 16 * j + b] = ENTRY(k)[b];
            for (u32 b = 0; b < NAME_BYTES; b++)
                nd[NAMES_OFFSET + NAME_BYTES * j + b] = NAME(k)[b];
            if (count < j + 1)
                count = j + 1;
        }
        put_le32(nd + 4, count);
        for (u32 k = 0; k < DIR_BYTES; k++)
            DIR[k] = nd[k];
        rec_keep = 0;
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
        put32(rp + r, REC_OFFSET); r += 4;      /* the image's room for yours below the hole */
        put32(rp + r, SMP_POOL_DDR); r += 4;
        put32(rp + r, REC_END); r += 4;         /* v0.22 (link 4): yours again from here */
        put32(rp + r, POOL_BYTES); r += 4;      /*   to here */
        put32(rp + r, (u32)smp_ram); r += 4;    /*   the RAM check: 1 passed (all loads) */
    } else if (cmd == 2) {                      /* WRITE, in order, after BEGIN */
        u32 at = n >= 7 ? get32(rq + 3) : 0, k = n >= 7 ? n - 7 : 0;
        if (!up_bytes || n < 7 || at > up_bytes || k > up_bytes - at || at + k > POOL_BYTES
            || (at < REC_END && at + k > REC_OFFSET)) {        /* v0.22: never the recordings' */
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
        put32(rp + r, (u32)smp_ram); r += 4;    /* v0.22 */
    } else if (cmd == 4 || cmd == 5) {          /* CLEAR, SAVE: nothing to do */
        put32(rp + r, smp_hi); r += 4;
    } else if (cmd == 6) {                      /* LOAD */
        if (smp_pl_busy())                      /* v0.38: not during a project switch */
            rp[3] = 1;
        else
            smp_load();
        if (!smp_hi)
            rp[3] = 1;
        put32(rp + r, smp_hi); r += 4;
    } else if (cmd == 7) {                      /* FORGET */
        extern void smp_pl_reset(void), smp_pl_after_send(void);
        if (smp_pl_busy()) {
            rp[3] = 1;
        } else {
            smp_pl_reset();                     /* v0.38: every project's pool goes with it */
            if (header_write(0) != 0)
                rp[3] = 1;
            smp_hi = 0;
            smp_pl_after_send();
        }
    } else if (cmd == 8) {                      /* BEGIN */
        u32 bytes = n >= 7 ? get32(rq + 3) : 0;
        extern void smp_pl_reset(void);
        if (bytes < DIR_BYTES || bytes > POOL_BYTES || smp_pl_busy()) {
            rp[3] = 1;
        } else if (smp_pl_reset(), header_write(0) != 0) {   /* v0.38: a whole new pool, every project's */
            rp[3] = 1;
        } else {
            smp_lstate = L_IDLE;                    /* no load runs while the image changes */
            job_data = 0;
            rec_keep = dir_ok;                  /* DIR holds the old image's directory: */
            up_bytes = bytes;                   /* its recordings are merged into the new */
            up_block = 0xFFFFFFFFu;
            up_fill = 0;
        }
    } else if (cmd == 9) {                      /* END */
        u32 bytes = up_bytes;
        if (up_flush() != 0)
            up_bytes = 0;                       /* -> refused below */
        if (up_bytes && le32(DIR) == POOL_MAGIC)
            dir_ok = 1;                         /* DIR is the new directory, recordings merged */
        for (u32 k = 0; k < POOL_SLOTS; k++) {  /* the image runs to its last recording too */
            if (!is_recording(k))
                continue;
            const u8 *e = ENTRY(k);
            u32 a = le32(e), f = le32(e + 4);
            if (a - SMP_POOL_DDR + f * 2u > bytes)
                bytes = a - SMP_POOL_DDR + f * 2u;
        }
        bytes = (bytes + 511u) & ~511u;
        if (bytes > POOL_BYTES)
            bytes = POOL_BYTES;
        if (!up_bytes || le32(DIR) != POOL_MAGIC || image_write(0, DIR_BYTES, DIR) != 0
            || header_write(bytes) != 0) {
            rp[3] = 1;
        } else {
            smp_load();
            extern void smp_pl_after_send(void);
            smp_pl_after_send();                /* v0.38: the legacy list: every project shares it */
        }
        up_bytes = 0;
        put32(rp + r, smp_hi); r += 4;
    } else if (cmd == 10) {                     /* DIR (v0.22, link 4): five slots from K */
        u32 k = n >= 4 ? rq[3] : 0;
        put32(rp + r, dir_ok ? (u32)smp_count() : 0); r += 4;
        for (u32 j = 0; j < 5; j++, k++) {
            u32 off = 0, fr = 0;
            if (dir_ok && k < POOL_SLOTS && !smp_slot_empty((int)k)) {
                off = le32(ENTRY(k)) - SMP_POOL_DDR;
                fr = le32(ENTRY(k) + 4);
            }
            put32(rp + r, off); r += 4;
            put32(rp + r, fr); r += 4;
            for (u32 c = 0; c < 8; c++)
                rp[r++] = dir_ok && k < POOL_SLOTS && fr ? NAME(k)[c] : 0;
        }
    } else if (cmd == 27) {                     /* v0.35: ENTRY K -> the slot's 16-byte entry as the DSP reads it, */
        u32 k = n >= 4 ? rq[3] : 0xFFu;          /*   its 8-byte name, u32 the pool's DSP address (for dn2diag's */
        for (u32 c = 0; c < 16; c++)            /*   own entry check: a slot that previews but will not play, M5) */
            rp[r++] = dir_ok && k < POOL_SLOTS ? ENTRY(k)[c] : 0;
        for (u32 c = 0; c < 8; c++)
            rp[r++] = dir_ok && k < POOL_SLOTS ? NAME(k)[c] : 0;
        put32(rp + r, SMP_POOL_DDR); r += 4;
    } else if ((cmd >= 16 && cmd <= 23) || cmd == 26 || cmd == 30 || cmd == 31) {   /* v0.31 (link 5): the +Drive's library (lib.c); v0.40 30, 31 */
        extern u32 smp_lib_rx(u32 cmd, const u8 *rq, u32 n, u8 *rp, u32 r, u8 *st);
        r = smp_lib_rx(cmd, rq, n, rp, r, &rp[3]);
    } else if (cmd == 28) {                     /* v0.39: ERASE MOD DATA, "ERASE" -> started at the */
        static const u8 word[5] = {'E', 'R', 'A', 'S', 'E'};     /* next UI pass (erase.c); the */
        int ok = n >= 8;                        /* page asks twice first */
        for (int k = 0; ok && k < 5; k++)
            ok = rq[3 + k] == word[k];
        extern int smp_er_req, smp_er_state;
        if (!ok || smp_er_state == 1 || smp_er_state == 2 || smp_er_state == 3)
            rp[3] = 1;
        else
            smp_er_req = 1;
    } else if (cmd == 29) {                     /* v0.39: ERASE STATUS (erase.c's smp_er_status) */
        extern u32 smp_er_status(u8 *rp, u32 r);
        r = smp_er_status(rp, r);
    } else if (cmd == 24) {                     /* v0.34: DIAG -> the DSP's guard record and load */
        put32(rp + r, smp_blown_count); r += 4;
        put32(rp + r, smp_blown_info); r += 4;
        put32(rp + r, smp_blown_where); r += 4;
        put32(rp + r, smp_blown_mask); r += 4;
        put32(rp + r, smp_blown_at ? ((int)(periods - smp_blown_at) < 0 ? 0u : periods - smp_blown_at) : 0xFFFFFFFFu); r += 4;
        put32(rp + r, (u32)smp_dsp_load()); r += 4;
        put32(rp + r, smp_load_peak); r += 4;
        u32 sk = 0;
        for (int t = 0; t < 16; t++)
            if (smp_skip_at[t])
                sk |= 1u << t;
        put32(rp + r, sk); r += 4;
        put32(rp + r, periods); r += 4;
        put32(rp + r, FRAMES); r += 4;
        /* and the last SCAN's result (VERIFY's status halves: count, first index, done seq) */
        u16 h[16];
        int ok = smp_status(h);
        put32(rp + r, ok ? ((u32)h[11] << 16 | h[10]) : 0xFFFFFFFFu); r += 4;
        put32(rp + r, ok ? ((u32)h[13] << 16 | h[12]) : 0xFFFFFFFFu); r += 4;
        put32(rp + r, ok ? h[14] : 0); r += 4;
        put32(rp + r, scan_seq); r += 4;
    } else if (cmd == 25) {                     /* v0.34: SCAN u32 address, u32 words -> u16 seq */
        if (n < 11) {
            rp[3] = 1;
        } else {
            scan_seq = smp_command(CMD_SCAN, get32(rq + 3), get32(rq + 7), 0, 0);
            rp[r++] = scan_seq >> 8; rp[r++] = scan_seq;
        }
    } else {
        rp[3] = 2;
    }
    for (int k = 0; k < 6; k++)
        tx[k] = sx_hdr[k];
    u32 m = 6 + pack7(rp, r, tx + 6);
    tx[m++] = 0xF7;
    SYSEX_SEND(tx, m, 0, PORT_USB);
}

/* -- v0.25: an LFO (or any modulation) on SAMP steps through the loaded samples ----------
 *
 * The ColdFire applies modulation each tick into the per-voice parameter mirror the frame
 * is built from (0x400db22c(mirror); docs/engine-state.md): mirror block b's parameter s
 * at the mirror base (MIRROR_CELL) + 34 + 202 b + 2 s, the sound on voice b at 0x800052A8 + 4 b. SAMP
 * modulated over the 128 slots mostly landed on empty ones, so a note played nothing.
 * Here, after the stock apply, a sample machine's modulated SAMP is moved by the same
 * number of steps through the slots that hold something, from the one SAMP is set to
 * (wrapping round them), as the DT2's project slots, which hold only loaded samples. An
 * unmodulated SAMP, and every other parameter and machine, are left as stock wrote them.
 *
 * v0.40 (a user on v0.39: "the p-locked trig doesn't play the sample you lock it to ... it
 * changes when you move the default track SAMP value, so the p-lock seems relative"): what
 * the voice is set to is its TARGET cell (the smoother's source, 0x80003af0, the same
 * layout as the mirror; docs/slides.md), which holds the sound's value or the trig's p-lock
 * (stock's lock applier 0x400db092 writes it, and jumps the smoother there). v0.25..v0.39
 * took the sound's own SAMP (and SLCE) instead, so a lock was a "modulation" of lock - SAMP,
 * scaled by mod_scale to n/128 of it over the n loaded samples and counted from the track's
 * SAMP: about one sample per 5 or 6 lock values with 20-odd loaded, moving with the track's
 * SAMP. Now the modulation is what the stock apply added on top of the target, and it steps
 * from the target: a locked trig plays its slot (or slice) exactly. */
#define MOD_APPLY ((void (*)(void *))0x400DB22Cu)
#define MIRROR_CELL(b, s) ((volatile u16 *)(0x800068E4u + 34u + 202u * (u32)(b) + 2u * (u32)(s)))
#define TARGET_CELL(b, s) ((volatile u16 *)(0x80003AF0u + 34u + 202u * (u32)(b) + 2u * (u32)(s)))
#define VOICE_SOUND(b) (*(u8 *volatile *)(0x800052A8u + 4u * (u32)(b)))
#define SAMP_SLOT 43                            /* SAMP's frame slot (sound + 20 + 2 x 43) */
#define FLEX_BUF_SLOT 35                        /* v0.53: FLEX's BUF (record 244; rectrig.c SLOT_BUF) */
/* the only cell written, block 0's lowest of them, lies past the frame (CTL_FRAME, 2,748
 * bytes: test_sources): the mirror is not the frame, and nothing here touches the frame */
_Static_assert(0x800068E4u + 34u + 2u * SAMP_SLOT >= 0x80005E60u + 2748u, "SAMP's mirror cells lie past the frame");
#define SOUND_TYPE 0xDE

/* v0.29: the modulation's reach follows its depth (the owner: depth did not move it as it
 * should). The stock apply moves SAMP by up to 127 slot steps at full depth; over a pool of
 * N loaded samples that wrapped round them many times, so any depth past a few sounded the
 * same. Now the offset is scaled: full depth reaches N loaded samples either way, half
 * depth N / 2, and it stops at the first and last loaded sample (as the DT2's slots stop at
 * their ends) rather than wrapping. SLICE (a SLICE track's SLCE on a slice, not NOTE)
 * likewise: full depth reaches the sample's slice count, held between its first and last
 * slice -- never past them, and never down onto NOTE. */
static int mod_scale(int k, int n)              /* a stock offset (+-127) -> +-n, rounded */
{
    int x = k * n;
    return (x >= 0 ? x + 64 : x - 64) / 128;
}

#define SLCE_SLOT 44                            /* SLCE's frame slot (sound + 20 + 2 x 44) */
#define SLICE_TYPE 13

/* v0.45 (the owner, v0.44: scrolling SAMP past the loaded samples, trigs played the last
 * loaded one): the frame's smoother (0x400db12a, before this) glides every parameter toward
 * the sound's, SAMP and SLCE too, so for a while after SAMP moves, the heard value differs
 * from the set one -- which this code took for modulation and moved onto the loaded slots,
 * at the end of the list clamped to the last one, every frame. A slot number (and a slice)
 * never glides: before the modulation is added, a sample voice's SAMP and SLCE are set to
 * the sound's (or the lock's) value, in the mirror and in the smoother's state, so what the
 * stock apply adds on top is the modulation alone. */
#define SMOOTH_STATE(b, s) ((volatile u32 *)(0x8000DE60u + 4u * (101u * (u32)(b) + 17u + (u32)(s))))

static u32 snap_slots(void)                     /* v0.77: returns the sample and FLEX voices */
{
    u32 vm = 0;
    for (u32 b = 0; b < 16; b++) {
        u8 *snd = VOICE_SOUND(b);
        if (!snd)
            continue;
        if (snd[SOUND_TYPE] == BOUNCE_TYPE)
            vm |= 1u << b;
        if (snd[SOUND_TYPE] < 8 || snd[SOUND_TYPE] > 13)
            continue;
        vm |= 1u << b;
        u16 s = *TARGET_CELL(b, SAMP_SLOT);
        *MIRROR_CELL(b, SAMP_SLOT) = s;
        *SMOOTH_STATE(b, SAMP_SLOT) = (u32)s << 16;
        if (snd[SOUND_TYPE] == SLICE_TYPE) {
            u16 c = *TARGET_CELL(b, SLCE_SLOT);
            *MIRROR_CELL(b, SLCE_SLOT) = c;
            *SMOOTH_STATE(b, SLCE_SLOT) = (u32)c << 16;
        }
    }
    return vm;
}

/* v0.65 (hooks.S smp_lfo_hook, after the LFOs): a sample voice's SAMP keeps its bank -- the LFOs
 * add a raw offset to the whole word, low byte too, which would move a slot of bank A's into B */
void smp_lfo_fix(void)
{
    for (u32 b = 0; b < 16; b++) {
        u8 *snd = VOICE_SOUND(b);
        if (!snd || snd[SOUND_TYPE] < 8 || snd[SOUND_TYPE] > 13)
            continue;
        volatile u16 *cell = MIRROR_CELL(b, SAMP_SLOT);
        u16 t = *TARGET_CELL(b, SAMP_SLOT);
        if ((t >> 8) > 127u)
            continue;                           /* a FLEX buffer: smp_mod_apply's own */
        *cell = (u16)((*cell & 0xFF00u) | (t & 0xFFu));
    }
}

void smp_mod_apply(void *mirror)
{
    u32 vm = snap_slots();
    MOD_APPLY(mirror);
    extern void pf_apply(void);
    pf_apply();                                 /* v0.69: PERFORM's offsets on top (perf.c) */
    extern void rt_frame(void);
    rt_frame();                                 /* v0.41: QPLAY switches and QREC starts on their step */
    /* v0.49 FLEX: each FLEX voice hears its buffer (or OFF), with or without a pool directory.
     * v0.44..v0.48 did this after the return below, so with no pool image (a unit nothing was
     * sent to) a BOUNCE voice never got its buffer: SAMP 0, silence (emu_coupled_flex) */
    u32 smpm = 0;                               /* v0.77: the sample machines' voices, for the pass below */
    for (u32 b = 0; b < 16; b++) {
        if (!(vm >> b & 1u))                    /* v0.77: only the voices snap_slots found (one scan
                                                 * a frame, not two; the modulation, PERFORM and
                                                 * rt_frame between allocate no voice) */
            continue;
        u8 *snd = VOICE_SOUND(b);
        if (!snd)
            continue;
        if (snd[SOUND_TYPE] >= 8 && snd[SOUND_TYPE] <= 13) {
            smpm |= 1u << b;
            /* v0.55: a sample machine on a FLEX buffer (its SAMP the buffer's code, the sound's
             * or a lock's) hears the buffer's playing half, or OFF while it is empty */
            extern int rt_samp_buf(u32 samp);
            extern u32 rt_buf_samp(u32 buf);
            int fb = rt_samp_buf((u32)(*TARGET_CELL(b, SAMP_SLOT) >> 8));
            if (fb >= 0) {
                volatile u16 *cell = MIRROR_CELL(b, SAMP_SLOT);
                u32 want = rt_buf_samp((u32)fb);
                if ((u32)(*cell >> 8) != want)
                    *cell = (u16)(want << 8);
            }
            continue;
        }
        if (snd[SOUND_TYPE] != BOUNCE_TYPE)
            continue;
        /* v0.53 (NiKo: a BUF lock on a playback trig was ignored): the voice plays the buffer its
         * own BUF names (the voice's target, the step's lock applied), not the track's; FLEX REC
         * still records into the track's BUF (rt_buf_of) */
        extern u32 rt_buf_samp(u32 buf), rt_buf_value(u32 v);
        u32 ot = SLOT_TRACK[b];                 /* the voice's track */
        volatile u16 *cell = MIRROR_CELL(b, SAMP_SLOT);
        u32 want = ot < 16 ? rt_buf_samp(rt_buf_value((u32)(*TARGET_CELL(b, FLEX_BUF_SLOT) >> 8))) : 0;
        if ((u32)(*cell >> 8) != want)
            *cell = (u16)(want << 8);
    }
    if (!dir_ok || !smpm)                       /* v0.77: no sample machine playing: nothing below */
        return;
    /* v0.33: the loaded slots, listed once a frame and only if a voice needs them (this runs
     * in the audio interrupt, 1,500 times a second: v0.25..v0.32 walked the 128 slots twice
     * for every modulated voice, up to 4,096 checks a frame with SAMP modulated on 16) */
    /* v0.65: per bank, the target's (its word's low byte); the bank stays on the remapped value */
    u8 loaded[POOL_SLOTS];
    int nl = -1, lbank = -1;
    for (u32 b = 0; b < 16; b++) {
        if (!(smpm >> b & 1u))
            continue;
        u8 *snd = VOICE_SOUND(b);
        if (!snd)
            continue;
        if (snd[SOUND_TYPE] < 8 || snd[SOUND_TYPE] > 13)
            continue;                           /* not a sample machine */
        u32 tw = *TARGET_CELL(b, SAMP_SLOT);
        u32 set = tw >> 8;                      /* the sound's or the lock's: 0 OFF, k: slot k - 1 */
        if (set > POOL_SLOTS)
            continue;                           /* v0.55: a FLEX buffer (above) */
        int bank = smp_word_bank(tw);
        volatile u16 *cell = MIRROR_CELL(b, SAMP_SLOT);
        int heard = *cell >> 8;
        int k = heard - (int)set;
        if (k != 0 && set != 0 && set <= POOL_SLOTS) {
            if (nl < 0 || lbank != bank) {
                nl = 0;
                lbank = bank;
                for (int j = 0; j < (bank ? 127 : POOL_SLOTS); j++)
                    if (!smp_slot_empty(G_OF(bank, j)))
                        loaded[nl++] = (u8)j;
            }
            int n = nl, at = -1, exact = 0;     /* the loaded slots; the last at or below SAMP's */
            for (int i = 0; i < nl && loaded[i] <= (int)set - 1; i++) {
                at = i;
                exact = loaded[i] == (int)set - 1;
            }
            if (n > 0) {
                int off = mod_scale(k, n);
                /* SAMP on an empty slot sits between two loaded ones: a step up is the one
                 * above, a step down the one below */
                int base = exact ? at : (off > 0 ? at : at + 1);
                int idx = base + off;
                if (idx < 0) idx = 0;
                if (idx > n - 1) idx = n - 1;
                *cell = (u16)((loaded[idx] + 1) << 8 | BANK_TAG(bank));   /* the idx-th loaded slot, in its bank */
            }
        }
        if (snd[SOUND_TYPE] != SLICE_TYPE)
            continue;
        u32 sset = *TARGET_CELL(b, SLCE_SLOT) >> 8;  /* the sound's or the lock's: slice (value >> 1), 0 NOTE */
        volatile u16 *scell = MIRROR_CELL(b, SLCE_SLOT);
        int sk = (int)(*scell >> 8) - (int)sset;
        int slot = smp_word_g(*cell);           /* the sample it plays, after the above (v0.65: global) */
        int ns = 0;
        if (sk == 0 || (sset >> 1) == 0 || slot < 0 || !smp_slices(slot, &ns) || ns < 1)
            continue;
        int sl = (int)(sset >> 1) + mod_scale(sk, ns);
        if (sl < 1) sl = 1;
        if (sl > ns) sl = ns;
        *scell = (u16)((u32)(2 * sl) << 8);
    }
}
