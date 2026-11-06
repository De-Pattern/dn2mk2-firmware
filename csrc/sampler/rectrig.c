/* REC trigs, the two REC buffers, QREC and QPLAY (v0.41; docs/rectrig.md). The ColdFire only:
 * the DSP's recorder, its slots and its commands are v0.40's, unchanged.
 *
 * A REC trig is a lock on a step (slide.c: SL_RAM_REC, stored id 202, set from the RECORDER
 * overlay with a step held: knob H, OFF / REC 1 / REC 2). When the step plays (the lock
 * applier, slide.c sl_apply, in the sequencer's timer interrupt) rt_trig() builds a NOW for
 * the recorder: SRC and CHAN as the RECORDER has them, R.LEN steps at the tempo (MAX: the
 * pattern's length), into its buffer. The command goes to the DSP through a slot of its own
 * in the link's packets (link.c smp_tdm, the audio interrupt), ahead of the UI's queue, so
 * the take starts about a millisecond after its step.
 *
 * The buffers are the DSP's four recorder slots (it plays them whatever the pool's count,
 * and records into slots up to 126): REC 1 plays as SAMP 124 and REC 2 as SAMP 125, each
 * double-buffered over two of them (HALF): a take records into the half that is not
 * playing, and the track switches to it (smp_mod_apply, rt_map: the SAMP a voice hears)
 * at the first QPLAY boundary after the take has ended, so a loop never plays a half-
 * recorded take; QPLAY OFF switches as the take starts (heard live). A voice reads SAMP at
 * its note, so a note playing the old take finishes on it.
 *
 * A buffer's take is RAM only: never saved to the +Drive nor normalised (a take a bar would
 * otherwise spend seconds on each), never in the ColdFire's directory, and gone at a project
 * change (pools.c blanks the DSP's entries) or a power cycle, as the Octatrack's buffers.
 *
 * Guards: a manual take (armed, recording, or waiting for QREC) is never cut by a REC trig;
 * a project with a saved sample in SAMP 124..127 (v0.32's DEST, or an old recording) has no
 * buffers (rt_on 0: those slots play what they hold, untouched); a take never runs past the
 * room the allocator found (link.c smp_rec_place, which also keeps every live buffer region
 * and the next takes' places out of anyone's way).
 *
 * QREC: the RECORDER's manual RECORD NOW (YES), with the sequencer playing, waits for the
 * next QREC boundary (rec.c builds the command, rt_frame sends it). Boundaries are on the
 * master position (track 1's step per pattern, the master counter per track), as the
 * Octatrack quantises to the pattern: every N steps, or the pattern's first step (PLEN). */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define D __attribute__((section(".data")))

#define FRAMES (*(volatile u32 *)0x4058E8D4u)           /* frames since boot, 1,500 a second */
#define CTL_FRAME ((volatile u16 *)0x80005E60u)
#define TEMPO_WORD 108                                   /* the frame's BPM x 120 */
#define SEQ_PLAYING (*(volatile u32 *)0x42C5A918u)       /* 1 while it plays (jump.c) */
#define SEQ_PATTERN (*(volatile u32 *)0x42C5A9A0u)       /* the playing pattern */
#define TRACK_CUR ((volatile u8 *)0x42C5A984u)           /* each track's step now playing */
#define SEQ_COUNTER (*(volatile u16 *)0x42C5A91Cu)       /* the master counter */
#define PAT_LENGTH 122196                                /* s16: the pattern's (master) length */
#define PAT_MODE 122201                                  /* u8: 0 per pattern, else per track */

#define CMD_NOW 2
#define REC_FRAMES_MAX (66u * 48000u)                    /* the DSP's longest take (the DT2's) */
#define REC_BYTES (TABLE_AREA - REC_OFFSET)
#define THR_FLOOR 33u                                    /* (NOW ignores it) */

extern int rec_src, rec_chan, rec_rlen, rec_state;
extern int smp_dir_ok;
extern int smp_slot_empty(int k);
extern u32 smp_rec_place(int dest, u32 *room);
extern volatile u32 smp_blank_req;

/* the buffers' slots: [buffer][half]; SAMP 124 and 125 are REC 1 and REC 2 */
static const u8 HALF[2][2] = {{REC_FIRST, REC_FIRST + 2}, {REC_FIRST + 1, REC_FIRST + 3}};
#define LOGICAL(b) (REC_FIRST + (b))                     /* the slot SAMP names: 123, 124 */

int rt_on D = 0;                        /* buffers usable: SAMP 124..127 hold nothing saved */
u8 rt_play[2] D = {0, 0};               /* the half each buffer plays */
u32 rt_rplace[4] D;                     /* each recorder slot's take: its place in the area */
u32 rt_rbytes[4] D;                     /* .. and bytes, 0 none */
u8 rt_pend[2] D;                        /* a take waiting for its QPLAY boundary */
u32 rt_pfrom[2] D, rt_plen[2] D;        /* .. the master steps seen when it began, its steps */
u32 rt_pt0[2] D, rt_pfr[2] D;           /* .. FRAMES when it began, its length in FRAMES */
int rt_cur D = -1;                      /* the buffer the recorder records into, -1 none */
u32 rt_cur_end D;                       /* .. FRAMES when its take is over */
int rt_manual D = 0;                    /* rec.c: a manual take armed, recording or waiting */

/* QREC, QPLAY: OFF, 1, 2, 4, 8, 16, 32, 64 steps, the pattern's length (PLEN) */
#define NQ 9
static const u16 QSTEPS[NQ] = {0, 1, 2, 4, 8, 16, 32, 64, 0xFFFF};
int rt_qrec D = 0;                      /* OFF */
int rt_qplay D = NQ - 1;                /* PLEN: a new take is heard from the pattern's top */

/* the master position, and the steps seen since PLAY (the audio interrupt counts them) */
int rt_pos D = -1;
u32 rt_steps D = 0;

/* where each buffer's next take goes (rt_poll, the UI; smp_rec_place keeps it free) */
u32 rt_nx_place[2] D, rt_nx_room[2] D, rt_nx_need[2] D;
static u32 nx_at D = 0;
static u32 blank_seen D = 0;
int rt_dirty D = 1;

/* the commands for the link (link.c smp_tdm): a REC trig's (from the timer interrupt), and a
 * QREC take's (rec.c builds it, rt_frame releases it at its boundary). Each: the words, then
 * its generation; the reader copies and checks the generation again */
volatile u32 rt_w[6] D;
volatile u32 rt_gen D = 0;
volatile u32 q_w[6] D;
volatile u32 q_gen D = 0;               /* rec.c: a new QREC take waiting */
volatile u32 q_cancel D = 0;            /* rec.c: = q_gen, it was cancelled */
volatile u32 q_fire D = 0;              /* rt_frame: the generation to send now */
static u32 rt_n D = 0;

/* for the checks (scripts/emu_rectrig.py) */
u32 rt_fired D, rt_refused D, rt_swaps D, rt_qfired D, rt_why D;
static u32 last_frame D = 0xFFFFFFFFu, last_key D = 0xFFFFFFFFu;

static int master_len(void)
{
    const u8 *p = (const u8 *)SEQ_PATTERN;
    int n = p ? *(const s16 *)(p + PAT_LENGTH) : 0;
    return n > 1 && n <= 1024 ? n : 16;                /* (INF: a bar) */
}

static int master_pos(void)
{
    const u8 *p = (const u8 *)SEQ_PATTERN;
    if (!p)
        return -1;
    if (p[PAT_MODE] == 0)
        return TRACK_CUR[0];
    int n = *(const s16 *)(p + PAT_LENGTH);
    u32 c = SEQ_COUNTER;
    return n > 1 ? (int)(c % (u32)n) : (int)c;
}

static int on_boundary(int q, int pos)          /* QSTEPS index Q */
{
    u32 n = QSTEPS[q < 0 ? 0 : q >= NQ ? NQ - 1 : q];
    if (n == 0)
        return 1;
    if (n == 0xFFFF)
        return pos == 0;
    return (u32)pos % n == 0;
}

static u32 frames_a_step(void)                  /* at 48 kHz: 48,000 x 60 / 4 / BPM */
{
    u32 bpm120 = CTL_FRAME[TEMPO_WORD];
    if (bpm120 < 1200)
        bpm120 = 14400;
    return 86400000u / bpm120;
}

static void swap(int b)
{
    rt_play[b] ^= 1;
    rt_pend[b] = 0;
    rt_swaps++;
}

/* does [PLACE, PLACE + BYTES) cross a live buffer region other than SLOT's own? */
static int clash(int slot, u32 place, u32 bytes)
{
    for (int i = 0; i < 4; i++) {
        if (REC_FIRST + i == slot || !rt_rbytes[i])
            continue;
        u32 a = rt_rplace[i], z = a + rt_rbytes[i];
        if (place < z && a < place + bytes)
            return 1;
    }
    return 0;
}

/* a REC trig on TRACK's STEP for buffer BUF (1, 2): the timer interrupt (slide.c sl_apply) */
void rt_trig(u32 track, u32 step, u32 buf)
{
    u32 key = track << 8 | step, now = FRAMES;
    if (now == last_frame && key == last_key)
        return;                                 /* the trig's other voices */
    last_frame = now;
    last_key = key;
    int b = (int)buf - 1;
    if (b < 0 || b > 1)
        return;
    if (!rt_on || rt_manual) {                  /* no buffers here, or a manual take's turn */
        rt_refused++;
        rt_why = !rt_on ? 1 : 2;
        return;
    }
    int half = rt_play[b] ^ 1;
    if (rt_pend[b])                             /* its last take still waits: it is replaced */
        half = rt_play[b] ^ 1;
    int slot = HALF[b][half];
    u32 place = rt_nx_place[b], room = rt_nx_room[b];
    u32 steps = rec_rlen > 0 ? (u32)rec_rlen : (u32)master_len();
    u32 frames = steps * frames_a_step();
    if (frames > REC_FRAMES_MAX)
        frames = REC_FRAMES_MAX;
    /* never longer than the room planned for it (rt_poll: rt_nx_need, kept clear of every
     * other take and plan): a tempo slowed, or R.LEN raised, since the last plan (it is made
     * again every 150 ms) gives a take a little short, never one over the next */
    u32 cap = rt_nx_need[b] < room ? rt_nx_need[b] : room;
    if (frames > cap / 2u)
        frames = (cap / 2u) & ~31u;
    if (frames < 4800u || clash(slot, place, frames * 2u)) {   /* under a tenth of a second, or no room */
        rt_refused++;
        rt_why = 3;
        return;
    }
    /* one recorder: a take of the other buffer still running is cut here, and keeps playing
     * what it played (its waiting take, cut short, is dropped) */
    if (rt_cur >= 0 && rt_cur != b && (int)(now - rt_cur_end) < 0) {
        rt_pend[rt_cur] = 0;
        rt_rbytes[HALF[rt_cur][rt_play[rt_cur] ^ 1] - REC_FIRST] = 0;
    }
    u32 seq = 0x80008000u | (++rt_n & 0x7FFFu);  /* low half's bit 15: a buffer take (rec.c) */
    rt_w[0] = seq;
    rt_w[1] = CMD_NOW;
    rt_w[2] = (u32)(rec_src < 0 ? 0 : rec_src);
    rt_w[3] = (u32)(rec_chan < 0 ? 0 : rec_chan > 2 ? 2 : rec_chan) | (place / 512u) << 8;
    rt_w[4] = THR_FLOOR;
    rt_w[5] = (u32)slot << 24 | frames;
    rt_gen++;
    rt_rplace[slot - REC_FIRST] = place;
    rt_rbytes[slot - REC_FIRST] = frames * 2u;
    rt_cur = b;
    rt_cur_end = now + frames / 32u + 3u;
    rt_nx_room[b] = 0;                          /* used: rt_poll finds the next */
    rt_dirty = 1;
    rt_fired++;
    if (QSTEPS[rt_qplay] == 0 || !SEQ_PLAYING) {
        rt_play[b] = (u8)half;                  /* QPLAY OFF: heard as it records */
        rt_pend[b] = 0;
        rt_swaps++;
    } else {
        /* the master steps since PLAY at this step: this step counted already, or (the
         * audio interrupt has not seen it yet) about to be */
        int p = master_pos();
        rt_pfrom[b] = rt_steps + (p != rt_pos ? 1u : 0u);
        rt_plen[b] = steps;
        rt_pt0[b] = now;
        rt_pfr[b] = frames / 32u + 3u;
        rt_pend[b] = 1;
    }
}

/* a manual take starts (rec.c, or a QREC take at its boundary): the recorder is its, so a
 * buffer take still running ends here; one waiting for QPLAY, cut short, is dropped (the
 * buffer plays what it played); one heard live (QPLAY OFF) keeps what it got */
void rt_cut(void)
{
    if (rt_cur < 0 || (int)(FRAMES - rt_cur_end) >= 0) {
        rt_cur = -1;
        return;
    }
    int b = rt_cur;
    if (rt_pend[b]) {
        rt_pend[b] = 0;
        rt_rbytes[HALF[b][rt_play[b] ^ 1] - REC_FIRST] = 0;
    }
    rt_cur = -1;
    rt_dirty = 1;
}

/* every frame (link.c smp_mod_apply, the audio interrupt): the master steps, the QPLAY
 * switches and the QREC start that fall on this step's boundary */
void rt_frame(void)
{
    if (!SEQ_PLAYING) {
        rt_pos = -1;
        for (int b = 0; b < 2; b++)             /* stopped: a waiting take is heard once it is over */
            if (rt_pend[b] && FRAMES - rt_pt0[b] >= rt_pfr[b])
                swap(b);
        if (q_gen != q_cancel && q_gen != q_fire) {   /* no clock to wait for: at once */
            rt_cut();
            q_fire = q_gen;
            rt_qfired++;
        }
        return;
    }
    int p = master_pos();
    if (p < 0 || p == rt_pos)
        return;
    if (rt_pos < 0)
        rt_steps = 0;                           /* PLAY: counted from here */
    rt_pos = p;
    rt_steps++;
    for (int b = 0; b < 2; b++)
        if (rt_pend[b] && rt_steps - rt_pfrom[b] >= rt_plen[b] && on_boundary(rt_qplay, p))
            swap(b);
    if (q_gen != q_cancel && q_gen != q_fire && on_boundary(rt_qrec, p)) {
        rt_cut();
        q_fire = q_gen;
        rt_qfired++;
    }
}

/* SAMP as a voice hears it (smp_mod_apply): REC 1 and REC 2 to the half they play; the
 * other two recorder slots play nothing while the buffers are on */
u32 rt_map(u32 v)                               /* SAMP's value: 0 OFF, k slot k - 1 */
{
    if (!rt_on || v < REC_FIRST + 1u || v > REC_FIRST + 4u)
        return v;
    u32 k = v - 1u;
    if (k == LOGICAL(0))
        return HALF[0][rt_play[0]] + 1u;
    if (k == LOGICAL(1))
        return HALF[1][rt_play[1]] + 1u;
    return 0;
}

/* a region the allocator must keep clear (link.c smp_rec_place, for a take into DEST): the
 * live buffer takes, and the places the next buffer takes will use; -> 1 inside one, and
 * *NEXT lowered to the next region's start past S */
int rt_regions(int dest, u32 s, u32 *next)
{
    int inside = 0;
    for (int i = 0; i < 4; i++) {
        if (REC_FIRST + i == dest || !rt_rbytes[i])
            continue;
        u32 a = rt_rplace[i], z = a + rt_rbytes[i];
        if (a <= s && s < z)
            inside = 1;
        if (a >= s && a < *next)
            *next = a & ~511u;
    }
    for (int b = 0; b < 2; b++) {
        if (!rt_on || !rt_nx_need[b] || HALF[b][rt_play[b] ^ 1] == dest)
            continue;
        u32 a = rt_nx_place[b], z = a + rt_nx_need[b];
        if (a <= s && s < z)
            inside = 1;
        if (a >= s && a < *next)
            *next = a & ~511u;
    }
    return inside;
}

/* the UI loop (rec.c rec_poll): whether the buffers are on, and each one's next place */
void rt_poll(void)
{
    if (smp_blank_req != blank_seen) {          /* another project: the DSP's entries emptied */
        blank_seen = smp_blank_req;
        for (int i = 0; i < 4; i++)
            rt_rbytes[i] = 0;
        rt_play[0] = rt_play[1] = 0;
        rt_pend[0] = rt_pend[1] = 0;
        rt_cur = -1;
        rt_dirty = 1;
    }
    int on = smp_dir_ok != 0;
    for (int i = 0; i < 4 && on; i++)
        if (!smp_slot_empty(REC_FIRST + i))
            on = 0;                             /* a saved sample in SAMP 124..127: theirs */
    if (on != rt_on) {
        rt_on = on;
        rt_dirty = 1;
    }
    if (rt_cur >= 0 && (int)(FRAMES - rt_cur_end) >= 0)
        rt_cur = -1;
    u32 now = FRAMES;
    if (!rt_on || (!rt_dirty && now - nx_at < 150u))
        return;
    nx_at = now;
    rt_dirty = 0;
    u32 steps = rec_rlen > 0 ? (u32)rec_rlen : (u32)master_len();
    u32 need = steps * frames_a_step();
    if (need > REC_FRAMES_MAX)
        need = REC_FRAMES_MAX;
    need = need * 2u + 511u;
    need &= ~511u;
    for (int b = 0; b < 2; b++) {
        rt_nx_need[b] = 0;                      /* (its own reservation does not count) */
        u32 room;
        u32 place = smp_rec_place(HALF[b][rt_play[b] ^ 1], &room);
        rt_nx_place[b] = place;
        rt_nx_room[b] = room;
        rt_nx_need[b] = room < need ? room : need;   /* kept clear for it */
    }
}

/* the RECORDER's REC TRIGS view: E QREC, F QPLAY, four detents a choice (rec.c) */
static int qk_acc D = 0, qk_idx D = 0;
static u32 qk_at D = 0;
void rt_knob(int index, int delta)
{
    u32 now = FRAMES;
    if (qk_idx != index || now - qk_at > 3000u || (qk_acc > 0 && delta < 0) || (qk_acc < 0 && delta > 0))
        qk_acc = 0;
    qk_idx = index;
    qk_at = now;
    qk_acc += delta;
    int n = qk_acc / 4;
    qk_acc -= n * 4;
    int *q = index == 5 ? &rt_qrec : index == 6 ? &rt_qplay : 0;
    if (!q || !n)
        return;
    *q += n;
    if (*q < 0) *q = 0;
    if (*q > NQ - 1) *q = NQ - 1;
}

int rt_q_waiting(void)                          /* a QREC take not started yet */
{
    return q_gen != q_cancel && q_gen != q_fire;
}

void rt_q_set(const u32 *w)                     /* rec.c: a manual NOW for the next QREC boundary */
{
    for (int j = 0; j < 6; j++)
        q_w[j] = w[j];
    q_gen++;
}

void rt_q_cancel(void)
{
    q_cancel = q_gen;
}

int rt_quantised(void)                          /* QREC set and the sequencer playing */
{
    return QSTEPS[rt_qrec] != 0 && SEQ_PLAYING;
}

/* a buffer's state for the view: 0 empty, 1 recording, 2 a take waiting, 3 playing a take;
 * *SECS its take's length in tenths of a second */
int rt_state(int b, int *tenths)
{
    int playing = HALF[b][rt_play[b]] - REC_FIRST, idle = HALF[b][rt_play[b] ^ 1] - REC_FIRST;
    *tenths = 0;
    if (rt_cur == b && (int)(FRAMES - rt_cur_end) < 0) {
        *tenths = (int)(rt_rbytes[rt_pend[b] ? idle : playing] / 9600u);
        return 1;
    }
    if (rt_pend[b]) {
        *tenths = (int)(rt_rbytes[idle] / 9600u);
        return 2;
    }
    if (rt_rbytes[playing]) {
        *tenths = (int)(rt_rbytes[playing] / 9600u);
        return 3;
    }
    return 0;
}

const char *rt_qname(int q)
{
    static const char *const N[NQ] = {"OFF", "1", "2", "4", "8", "16", "32", "64", "PLEN"};
    return N[q < 0 ? 0 : q >= NQ ? NQ - 1 : q];
}
