/* BOUNCE: recorder trigs, the eight buffers, QREC and QPLAY (v0.44; docs/rectrig.md). The
 * ColdFire's side; the DSP's recorder records a take into a buffer half and keeps its entry in
 * the buffer directory (dnfw.sampler.program, SM.BUF_DIR), and a STRETCH voice on SAMP
 * BUF_SLOT0 + 1 + 2 b + h plays half h of buffer b, fitted to the take's steps at the tempo.
 *
 * v0.41's REC trigs were p-locks that fired from a voice's lock list, so a step with no note
 * never recorded, silently, and two knobs were called ARM (the owner, NiKo, depaffect: "none
 * of this is working"). Now:
 *
 * - A recorder trig is a value on a step in the lock store's third record (slide.c: SL_RAM_REC,
 *   stored id 202, so it is saved, copied, pasted and undone with the pattern): 1 a recorder
 *   trig, 2 a one-shot (armed), 3 a one-shot that has fired (spent; YES YES on the BOUNCE
 *   RECORDER arms them again). Placed from the RECORDER page of a BOUNCE track with the
 *   [TRIG] keys (rec.c), the Octatrack's way; never a p-lock on a knob.
 * - It fires from the sequencer's own step: rt_frame (the audio interrupt, every frame)
 *   watches each BOUNCE track's step (TRACK_CUR, as Direct Jump and the slides read it) and,
 *   when it changes, reads that step's value from the playing pattern's lock table (inside
 *   the pattern object at PAT_LOCK_TABLE: the model's table getter returns *(model + 16),
 *   which the emulator showed is PATTERN + 97,872; the gate's harness checks it) and starts
 *   the take: whether or not the step has a note.
 * - Each BOUNCE track records into, and plays, the buffer its BUF control names (1..8; a
 *   p-lock can move it): "2+1" is two BOUNCE tracks on one buffer. A buffer is two halves: a
 *   take records into the half not playing, and the track hears the new half at the first
 *   QPLAY boundary after the take ends (QPLAY OFF: as it starts).
 * - The RECORDER page of a BOUNCE track always says what is happening (rt_status: no trigs,
 *   trigs placed, recording, waiting, playing, a refusal and why, one-shots spent).
 *
 * A take is RAM only (never normalised, never on the +Drive) until FUNC + YES saves the playing
 * one into the next empty pool slot (rec.c: the slot takes the half's frames as they lie, the
 * buffer's next take goes elsewhere). Takes are gone at a project change or a power cycle.
 *
 * QREC: the RECORDER's manual RECORD NOW (YES), with the sequencer playing, waits for the next
 * QREC boundary (rec.c builds the command, rt_frame sends it). Boundaries are on the master
 * position (track 1's step per pattern, the master counter per track): every N steps, or the
 * pattern's first step (PLEN). */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;

#define D __attribute__((section(".data")))

#define FRAMES (*(volatile u32 *)0x4058E8D4u)           /* frames since boot, 1,500 a second */
#define CTL_FRAME ((volatile u16 *)0x80005E60u)
#define TEMPO_WORD 108                                   /* the frame's BPM x 120 */
/* a track's sound in the kit (the frame is per voice, and a track's voice moves): its type
 * byte and its parameter words, slot s at sound + 20 + 2 s as the knobs write them (slice.c
 * SOUND_VALUE, smp_page.c SAMP_FSLOT; 0xDE, the type, is slot 101's place). v0.50 (impbox:
 * "BUF can't be set .. no effect"): v0.44..v0.49 read sound + 48, slot s + 14: BUF was slot
 * 49's word, whatever the knob said */
#define KIT_POINTER (*(u8 *volatile *)0x800052A0u)
#define SOUND_STRIDE 1163u
#define SOUND_BASE 52u
#define SOUND_TYPE 0xDEu
#define SOUND_PARAMS 20u
#define SLOT_BUF 35                                      /* BUF (record 244): 0..7 */
#define SLOT_SRC 38                                      /* SRC (record 252): 0 IN, 1 MAIN, 2.. TRK */
#define SLOT_RLEN 40                                     /* R.LEN (record 253): 0 MAX, 1..127 steps */
#define SLOT_CHAN 46                                     /* CHAN (record 259): 0 L+R, 1 L, 2 R */
#define SEQ_PLAYING (*(volatile u32 *)0x42C5A918u)       /* 1 while it plays (jump.c) */
#define SEQ_PATTERN (*(volatile u32 *)0x42C5A9A0u)       /* the playing pattern */
#define TRACK_CUR ((volatile u8 *)0x42C5A984u)           /* each track's step now playing */
#define SEQ_COUNTER (*(volatile u16 *)0x42C5A91Cu)       /* the master counter */
#define PAT_LENGTH 122196                                /* s16: the pattern's (master) length */
#define PAT_MODE 122201                                  /* u8: 0 per pattern, else per track */
#define PAT_LOCK_TABLE 97872                             /* the pattern's lock table (slide.c's records) */

#define CMD_NOW 2
#define REC_FRAMES_MAX (66u * 48000u)                    /* the DSP's longest take (the DT2's) */
#define REC_BYTES (TABLE_AREA - REC_OFFSET)
#define THR_FLOOR 33u                                    /* (NOW ignores it) */

#define RT_NONE 0xFFFFu                                  /* a step with no recorder trig */
#define RT_TRIG 1u
#define RT_ONESHOT 2u
#define RT_SPENT 3u

extern int rec_state;
extern int smp_dir_ok;
extern u32 smp_rec_place(int dest, u32 *room);
extern volatile u32 smp_blank_req;
extern u32 sl_lock_get(const u8 *table, u32 t, u32 step, u32 k);
extern int sl_lock_set(u8 *table, u32 t, u32 step, u32 k, u32 value);

#define HALF_SLOT(b, h) (BUF_SLOT0 + 2 * (b) + (h))      /* the DSP's slot index of a half */
#define HALF_IX(b, h) (2 * (b) + (h))                    /* .. its index below */

int rt_on D = 0;                        /* the directory is read: buffers usable */
u8 rt_play[BUF_N] D;                    /* the half each buffer plays */
u32 rt_rplace[BUF_HALVES] D;            /* each half's take: its place in the area */
u32 rt_rbytes[BUF_HALVES] D;            /* .. and bytes, 0 none */
u16 rt_rsteps[BUF_HALVES] D;            /* .. its length in steps */
u8 rt_pend[BUF_N] D;                    /* a take waiting for its QPLAY boundary */
u32 rt_pfrom[BUF_N] D, rt_plen[BUF_N] D;    /* .. the master steps seen when it began, its steps */
u32 rt_pt0[BUF_N] D, rt_pfr[BUF_N] D;   /* .. FRAMES when it began, its length in FRAMES */
int rt_cur D = -1;                      /* the buffer the recorder records into, -1 none */
u32 rt_cur_end D;                       /* .. FRAMES when its take is over */
int rt_manual D = 0;                    /* rec.c: a manual take armed, recording or waiting */
u8 rt_last_step[16] D;                  /* each track's step the last frame saw (0xFF: none) */
u8 rt_used[BUF_N] D;                    /* a BOUNCE track points at the buffer (rt_poll) */

/* QREC, QPLAY: OFF, 1, 2, 4, 8, 16, 32, 64 steps, the pattern's length (PLEN) */
#define NQ 9
static const u16 QSTEPS[NQ] = {0, 1, 2, 4, 8, 16, 32, 64, 0xFFFF};
int rt_qrec D = 0;                      /* OFF */
int rt_qplay D = NQ - 1;                /* (v0.49: unused; Q.PLAY is gone) */
int rt_arm D = 1;                       /* v0.49 FLEX: the recorder trigs fire (ARM ON) */

/* the master position, and the steps seen since PLAY (the audio interrupt counts them) */
int rt_pos D = -1;
u32 rt_steps D = 0;

/* where each buffer's next take goes (rt_poll, the UI; smp_rec_place keeps it free) */
u32 rt_nx_place[BUF_N] D, rt_nx_room[BUF_N] D, rt_nx_need[BUF_N] D;
static u32 nx_at D = 0;
static u32 blank_seen D = 0;
int rt_dirty D = 1;

/* the commands for the link (link.c smp_tdm): a recorder trig's (from the audio interrupt),
 * and a QREC take's (rec.c builds it, rt_frame releases it at its boundary). Each: the words,
 * then its generation; the reader copies and checks the generation again */
volatile u32 rt_w[6] D;
volatile u32 rt_gen D = 0;
volatile u32 q_w[6] D;
volatile u32 q_gen D = 0;               /* rec.c: a new QREC take waiting */
volatile u32 q_cancel D = 0;            /* rec.c: = q_gen, it was cancelled */
volatile u32 q_fire D = 0;              /* rt_frame: the generation to send now */
static u32 rt_n D = 0;

/* for the checks (scripts/emu_rectrig.py) and the status line */
u32 rt_fired D, rt_refused D, rt_swaps D, rt_qfired D, rt_why D;
u32 rt_why_at D;                        /* when the last trig was refused (the RECORDER says why) */
u8 rt_why_trk D = 0xFF;                 /* .. on which track */
u32 rt_fired_at D;                      /* when the last trig fired (the line flashes REC) */
u8 rt_fired_trk D = 0xFF;

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

static const u8 *sound_of(u32 t)                /* track t's sound in the kit, 0 without a kit */
{
    const u8 *kit = KIT_POINTER;
    return kit && t < 16 ? kit + SOUND_BASE + SOUND_STRIDE * t : 0;
}

static u32 ctl(u32 t, u32 slot)                 /* a track's control, as its sound holds it */
{
    const u8 *snd = sound_of(t);
    return snd ? (u32)(*(const u16 *)(snd + SOUND_PARAMS + 2u * slot)) >> 8 : 0;
}

/* v0.51 (impbox: "the flex record settings also need to be saved with the project or pattern";
 * owner: per track): FLEX REC's SRC, CHAN, R.LEN, GAIN, Q.REC and ARM live in the FLEX track's own
 * sound, as BUF does, so they are saved with the kit, follow the pattern, and each FLEX track has
 * its own. The words are the recorder's records' slots (dnfw.sampler.machines RECORDS: SRC 38,
 * R.LEN 40, CHAN 46, ARM 27, Q.REC on DEST's 37, GAIN on THRES's 32), none of them FLEX's page's or
 * read by the DSP for a FLEX voice; the value is the word's high byte (GAIN as GAIN + 25). A
 * sound written so carries FX_MARK in SRC's low byte: an older FLEX track (v0.49, v0.50), whose
 * words hold the shared records' defaults, reads the v0.50 defaults until it is first set. */
#define FX_MARK 0xF1u
static const u8 FX_SLOT[FX_N] = {38, 46, 40, 32, 37, 27};
static const short FX_LO[FX_N] = {0, 0, 0, -24, 0, 0};
static const short FX_TOP[FX_N] = {SMP_REC_SOURCES - 1, 2, 128, 38, 8, 1};
static const short FX_DEF[FX_N] = {0, 0, 0, 0, 0, 1};       /* IN, L+R, MAX, 0 dB, OFF, ON */
int fx_valid(u32 t)
{
    const u8 *snd = sound_of(t);
    return snd && (*(const u16 *)(snd + SOUND_PARAMS + 2u * FX_SLOT[FX_SRC]) & 0xFFu) == FX_MARK;
}
int fx_get(u32 t, int k)                        /* the setting K (FX_*) of FLEX track T */
{
    if ((u32)k >= FX_N)
        return 0;
    if (!fx_valid(t))
        return FX_DEF[k];
    int v = (int)ctl(t, FX_SLOT[k]) + (k == FX_GAIN ? -25 : 0);
    return v < FX_LO[k] ? FX_LO[k] : v > FX_TOP[k] ? FX_TOP[k] : v;
}
void fx_set(u32 t, int k, int v)                /* the UI's (rec.c): the word, the mark with it */
{
    const u8 *snd = sound_of(t);
    if (!snd || (u32)k >= FX_N)
        return;
    volatile u16 *w = (volatile u16 *)(snd + SOUND_PARAMS);
    if (!fx_valid(t)) {                          /* first set: every setting at its default, marked */
        for (int j = 0; j < FX_N; j++)
            w[FX_SLOT[j]] = (u16)((u32)(FX_DEF[j] + (j == FX_GAIN ? 25 : 0)) << 8);
        w[FX_SLOT[FX_SRC]] = (u16)(w[FX_SLOT[FX_SRC]] | FX_MARK);
    }
    v = v < FX_LO[k] ? FX_LO[k] : v > FX_TOP[k] ? FX_TOP[k] : v;
    u16 low = k == FX_SRC ? FX_MARK : 0;
    w[FX_SLOT[k]] = (u16)((u32)(v + (k == FX_GAIN ? 25 : 0)) << 8 | low);
}

int rt_is_bounce(u32 t)                         /* v0.49: FLEX (type 17, BOUNCE's) on track t */
{
    const u8 *snd = sound_of(t);
    return snd && snd[SOUND_TYPE] == BOUNCE_TYPE;
}

/* v0.49: BUF over the knob's whole travel, BUF 1..8 an eighth of it each (BOUNCE's read 0..7 of a
 * 0..100 control: its default and most of the knob were BUF 8). fmt.c draws it the same way */
#define REC_W(id) ((const int *)(0x401F7F94u + 60u * (id)))
u32 rt_buf_value(u32 v)                         /* the control's value (0..its top) -> 0..BUF_N-1 */
{
    int top = REC_W(SMP_BUF_ID)[3] >> 8, lo = REC_W(SMP_BUF_ID)[2] >> 8;
    int span = top - lo + 1, x = (int)v - lo;
    if (span < BUF_N)
        span = BUF_N;
    if (x < 0)
        x = 0;
    u32 b = (u32)(x * BUF_N / span);
    return b >= BUF_N ? BUF_N - 1 : b;
}

u32 rt_buf_of(u32 t)                            /* the buffer a FLEX track names, 0..BUF_N-1 */
{
    return rt_buf_value(ctl(t, SLOT_BUF));
}

/* v0.49: R.LEN, SRC and CHAN are the FLEX REC panel's (rec.c rec_rlen, rec_src, rec_chan: what it
 * shows and its knobs turn). v0.44..v0.47 read three sound slots the panel never wrote, so a
 * BOUNCE take ignored its panel */
extern int rec_rlen, rec_src, rec_chan;
static u32 rlen_of(u32 t)                       /* R.LEN steps (0 MAX: the pattern's length) */
{
    int r = fx_get(t, FX_RLEN);                 /* v0.51: the track's own (fx_get) */
    u32 n = r > 0 ? (u32)r : 0u;
    return n > 0 && n <= 128 ? n : (u32)master_len();
}

/* does [PLACE, PLACE + BYTES) cross a live half region other than IX's own? */
static int clash(int ix, u32 place, u32 bytes)
{
    for (int i = 0; i < BUF_HALVES; i++) {
        if (i == ix || !rt_rbytes[i])
            continue;
        u32 a = rt_rplace[i], z = a + rt_rbytes[i];
        if (place < z && a < place + bytes)
            return 1;
    }
    return 0;
}

static void refuse(u32 track, u32 why)
{
    rt_refused++;
    rt_why = why;
    rt_why_at = FRAMES | 1u;
    rt_why_trk = (u8)track;
}

/* a recorder trig on TRACK's STEP, into buffer B: the audio interrupt (rt_frame) */
u32 rt_last_key D;                      /* the last trig's track << 8 | step (the checks) */
static u32 rt_last_bytes D = 0;         /* v0.51: the last take's bytes and steps (rt_clear) */
static u16 rt_last_steps D = 0;
int rt_trig(u32 track, u32 step, u32 b)         /* -> 1: the take started */
{
    u32 now = FRAMES;
    rt_last_key = track << 8 | step;
    if (b >= BUF_N)
        return 0;
    if (!rt_on || rt_manual) {                  /* no directory yet, or a manual take's turn */
        refuse(track, !rt_on ? 1 : 2);
        return 0;
    }
    /* v0.49 FLEX: one buffer, recorded where it plays (half 0); a take already running is
     * never cut by a trig: refused (BUSY), unless it is this buffer's own, ending now (a trig
     * every pass with R.LEN the pattern's length meets its last take's end) */
    if (rt_cur >= 0 && (int)(now - rt_cur_end) < 0
        && !(rt_cur == (int)b && (int)(rt_cur_end - now) <= 6)) {
        refuse(track, 4);
        return 0;
    }
    int half = 0;
    int ix = HALF_IX(b, half), slot = HALF_SLOT(b, half);
    u32 place = rt_nx_place[b], room = rt_nx_room[b];
    u32 steps = rlen_of(track);
    u32 frames = steps * frames_a_step();
    if (frames > REC_FRAMES_MAX)
        frames = REC_FRAMES_MAX;
    /* never longer than the room planned for it (rt_poll: rt_nx_need, kept clear of every
     * other take and plan): a tempo slowed, or R.LEN raised, since the last plan (it is made
     * again every 150 ms) gives a take a little short, never one over the next */
    u32 cap = rt_nx_need[b] < room ? rt_nx_need[b] : room;
    if (frames > cap / 2u)
        frames = (cap / 2u) & ~31u;
    if (frames < 4800u || clash(ix, place, frames * 2u)) {   /* under a tenth of a second, or no room */
        refuse(track, 3);
        return 0;
    }
    u32 src = (u32)fx_get(track, FX_SRC), chan = (u32)fx_get(track, FX_CHAN);   /* v0.51: the track's own */
    u32 seq = 0x80008000u | (++rt_n & 0x7FFFu);  /* low half's bit 15: a buffer take (rec.c) */
    rt_w[0] = seq;
    rt_w[1] = CMD_NOW;
    rt_w[2] = src > 17 ? 0 : src;
    u32 gain = (u32)(fx_get(track, FX_GAIN) + 25) << 24;   /* v0.50: GAIN (rec.c rec_gain_bits); v0.51 the track's */
    rt_w[3] = (chan > 2 ? 2 : chan) | (place / 512u) << 8 | gain;
    rt_w[4] = THR_FLOOR | (steps & 0x7FFFu) << 16;   /* the take's steps: the DSP keeps them */
    rt_w[5] = (u32)slot << 24 | frames;
    rt_gen++;
    rt_rplace[ix] = place;
    rt_rbytes[ix] = frames * 2u;
    rt_rsteps[ix] = (u16)steps;
    rt_last_bytes = frames * 2u;
    rt_last_steps = (u16)steps;
    rt_cur = (int)b;
    rt_cur_end = now + frames / 32u + 3u;
    rt_nx_room[b] = 0;                          /* used: rt_poll finds the next */
    rt_dirty = 1;
    rt_fired++;
    rt_fired_at = now | 1u;
    rt_fired_trk = (u8)track;
    rt_play[b] = 0;                             /* v0.49: heard as it records (no Q.PLAY) */
    rt_pend[b] = 0;
    return 1;
}

/* v0.51 (owner; Error Kit: "how do I delete a buffer?"): buffer B emptied (rec.c, CLEAR BUF n?
 * answered YES): its takes forgotten, so its FLEX tracks play nothing (rt_bounce_samp: SAMP OFF,
 * as after a project change) and the allocator may use its place again. A take saved from it
 * (FUNC + YES) is a pool slot's and stays. -> 0, refused, while it records (the DSP is writing
 * it). rt_trig runs in the audio interrupt, which never stops partway for this task: if one
 * started a take of B between the check and the clearing, its take is put back */
int rt_clear(u32 b)
{
    if (b >= BUF_N)
        return 0;
    if (rt_cur == (int)b && (int)(FRAMES - rt_cur_end) < 0)
        return 0;
    u32 g = rt_gen;
    for (int h = 0; h < 2; h++) {
        rt_rbytes[HALF_IX(b, h)] = 0;
        rt_rsteps[HALF_IX(b, h)] = 0;
    }
    rt_play[b] = 0;
    rt_pend[b] = 0;
    if (rt_gen != g && rt_cur == (int)b) {      /* a trig of B fired as it was cleared: its take stands */
        rt_rbytes[HALF_IX(b, 0)] = rt_last_bytes;
        rt_rsteps[HALF_IX(b, 0)] = rt_last_steps;
    }
    rt_dirty = 1;
    return 1;
}

/* a manual take starts (rec.c, or a QREC take at its boundary): the recorder is its, so a
 * buffer take still running ends here; one waiting for QPLAY, cut short, is dropped (the
 * buffer plays what it played); one heard live (QPLAY OFF) keeps what it got */
void rt_cut(void)                               /* v0.49: the buffer keeps what its take got */
{
    rt_cur = -1;
}

/* v0.49 FLEX: a manual take into the track's buffer (YES on the FLEX REC panel, rec.c): asked for
 * from the UI, started by rt_frame (the audio interrupt, as the trigs: one writer of rt_w), at
 * once, or with Q.REC set and the sequencer playing at the next boundary. ARM OFF: the track's
 * recorder trigs do not fire (a finished bounce kept); YES still records */
volatile u32 rt_req D = 0;              /* the track + 1 asked for, 0 none */
void rt_flex_req(u32 t)
{
    rt_req = t < 16 ? t + 1u : 0u;
}
static int req_q(void)                         /* v0.51: Q.REC of the track a FLEX take is asked for */
{
    return rt_req ? fx_get(rt_req - 1u, FX_QREC) : 0;
}
int rt_req_waiting(void)
{
    return rt_req != 0 && QSTEPS[req_q()] != 0 && SEQ_PLAYING;
}
static void req_fire(void)
{
    u32 t = rt_req - 1u;
    rt_req = 0;
    if (t < 16 && rt_is_bounce(t))
        rt_trig(t, 0, rt_buf_of(t));
}

/* the playing pattern's lock table (the records slide.c keeps) */
static u8 *pat_table(void)
{
    u8 *p = (u8 *)SEQ_PATTERN;
    return p ? p + PAT_LOCK_TABLE : 0;
}

/* every frame (link.c smp_mod_apply, the audio interrupt): the recorder trigs of each BOUNCE
 * track at its new step, the master steps, the QPLAY switches and the QREC start that fall
 * on this step's boundary */
void rt_frame(void)
{
    if (rt_req && SEQ_PLAYING && QSTEPS[req_q()] == 0)   /* v0.49: Q.REC OFF: at once */
        req_fire();
    if (!SEQ_PLAYING) {
        rt_pos = -1;
        for (int t = 0; t < 16; t++)
            rt_last_step[t] = 0xFF;             /* PLAY: the first step fires */
        if (q_gen != q_cancel && q_gen != q_fire) {   /* no clock to wait for: at once */
            rt_cut();
            q_fire = q_gen;
            rt_qfired++;
        }
        if (rt_req)                             /* v0.49: a FLEX take asked for: at once */
            req_fire();
        return;
    }
    u8 *table = pat_table();
    for (u32 t = 0; t < 16; t++) {
        u8 cur = TRACK_CUR[t];
        if (cur == rt_last_step[t])
            continue;
        rt_last_step[t] = cur;
        if (!table || cur > 127 || !rt_is_bounce(t) || !fx_get(t, FX_ARM))   /* v0.51: the track's ARM */
            continue;
        u32 v = sl_lock_get(table, t, cur, 2);
        if (v == RT_TRIG || v == RT_ONESHOT) {
            int took = rt_trig(t, cur, rt_buf_of(t));
            if (v == RT_ONESHOT && took)        /* recorded once: spent until YES YES (a refusal keeps it armed) */
                sl_lock_set(table, t, cur, 2, RT_SPENT);
        }
    }
    int p = master_pos();
    if (p < 0 || p == rt_pos)
        return;
    if (rt_pos < 0)
        rt_steps = 0;                           /* PLAY: counted from here */
    rt_pos = p;
    rt_steps++;
    if (q_gen != q_cancel && q_gen != q_fire && on_boundary(rt_qrec, p)) {
        rt_cut();
        q_fire = q_gen;
        rt_qfired++;
    }
    if (rt_req && on_boundary(req_q(), p))      /* v0.49: a FLEX take at its Q.REC boundary */
        req_fire();
}

/* the SAMP a BOUNCE voice on track T hears (link.c smp_mod_apply): its buffer's playing half
 * (BUF_SLOT0 + 1 + ..), or 0 (OFF) with nothing recorded */
u32 rt_bounce_samp(u32 t)
{
    u32 b = rt_buf_of(t);
    if (!rt_on || !rt_rbytes[HALF_IX(b, rt_play[b])])
        return 0;
    return (u32)HALF_SLOT(b, rt_play[b]) + 1u;
}

/* a region the allocator must keep clear (link.c smp_rec_place, for a take into DEST): the
 * live buffer takes, and the places the next buffer takes will use; -> 1 inside one, and
 * *NEXT lowered to the next region's start past S */
int rt_regions(int dest, u32 s, u32 *next)
{
    int inside = 0;
    for (int i = 0; i < BUF_HALVES; i++) {
        if (BUF_SLOT0 + i == dest || !rt_rbytes[i])
            continue;
        u32 a = rt_rplace[i], z = a + rt_rbytes[i];
        if (a <= s && s < z)
            inside = 1;
        if (a >= s && a < *next)
            *next = a & ~511u;
    }
    for (int b = 0; b < BUF_N; b++) {
        if (!rt_on || !rt_nx_need[b] || HALF_SLOT(b, 0) == dest)
            continue;
        u32 a = rt_nx_place[b], z = a + rt_nx_need[b];
        if (a <= s && s < z)
            inside = 1;
        if (a >= s && a < *next)
            *next = a & ~511u;
    }
    return inside;
}

/* the UI loop (rec.c rec_poll): whether the buffers are on, which are in use, and each one's
 * next place */
void rt_poll(void)
{
    extern void bn_led_poll(void);
    bn_led_poll();                              /* v0.45: the trig LEDs follow the panel (rec.c) */
    if (smp_blank_req != blank_seen) {          /* another project: every take is gone */
        blank_seen = smp_blank_req;
        for (int i = 0; i < BUF_HALVES; i++)
            rt_rbytes[i] = 0;
        for (int b = 0; b < BUF_N; b++)
            rt_play[b] = rt_pend[b] = 0;
        rt_cur = -1;
        rt_dirty = 1;
    }
    /* v0.49: the buffers are usable once the directory is read, or once start-up is over with
     * no pool image on the +Drive (nothing sent to it yet: the pool is empty, so there is nothing
     * in the recordings' area to keep clear but this session's own takes, which the allocator
     * knows). v0.44..v0.47 waited for a directory that a unit with no image never has: every
     * BOUNCE take was refused there (NO +DRIVE POOL) */
    extern int smp_booted;
    extern u32 smp_hi;
    int on = smp_dir_ok != 0 || (smp_booted == 2 && smp_hi == 0);
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
    u32 need[BUF_N];
    for (int b = 0; b < BUF_N; b++) {
        rt_used[b] = 0;
        need[b] = 0;
    }
    for (u32 t = 0; t < 16; t++) {              /* the buffers BOUNCE tracks point at, and the
                                                 * longest take asked of each */
        if (!rt_is_bounce(t))
            continue;
        u32 b = rt_buf_of(t), n = rlen_of(t) * frames_a_step();
        rt_used[b] = 1;
        if (n > need[b])
            need[b] = n;
    }
    for (int b = 0; b < BUF_N; b++) {
        rt_nx_need[b] = 0;                      /* (its own reservation does not count) */
        if (!rt_used[b]) {
            rt_nx_room[b] = 0;
            continue;
        }
        u32 n = need[b] > REC_FRAMES_MAX ? REC_FRAMES_MAX : need[b];
        n = (n * 2u + 511u) & ~511u;
        u32 room;
        u32 place = smp_rec_place(HALF_SLOT(b, 0), &room);   /* v0.49: where it plays (one buffer) */
        rt_nx_place[b] = place;
        rt_nx_room[b] = room;
        rt_nx_need[b] = room < n ? room : n;    /* kept clear for it */
    }
}

/* the RECORDER's Q.REC and Q.PLAY (rec.c): four detents a choice */
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
    int *q = index == 5 ? &rt_qrec : index == 7 ? &rt_arm : 0;   /* v0.49: no Q.PLAY; 7 FLEX's ARM */
    int top = index == 7 ? 1 : NQ - 1;
    if (!q || !n)
        return;
    *q += n;
    if (*q < 0) *q = 0;
    if (*q > top) *q = top;
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
 * *TENTHS its take's length in tenths of a second, *STEPS its steps */
int rt_state(int b, int *tenths, int *steps)
{
    if (b < 0 || b >= BUF_N) {
        *tenths = *steps = 0;
        return 0;
    }
    int playing = HALF_IX(b, 0);               /* v0.49: one buffer */
    int ix = -1, st = 0;
    if (rt_cur == b && (int)(FRAMES - rt_cur_end) < 0) {
        ix = playing;
        st = 1;
    } else if (rt_rbytes[playing]) {
        ix = playing;
        st = 3;
    }
    *tenths = ix >= 0 ? (int)(rt_rbytes[ix] / 9600u) : 0;
    *steps = ix >= 0 ? rt_rsteps[ix] : 0;
    return st;
}

const char *rt_qname(int q)
{
    static const char *const N[NQ] = {"OFF", "1", "2", "4", "8", "16", "32", "64", "PLEN"};
    return N[q < 0 ? 0 : q >= NQ ? NQ - 1 : q];
}

/* -- the recorder trigs of a track, for the UI (rec.c: the [TRIG] keys on a BOUNCE track's
 * RECORDER page; smp_page.c: the grid and the status line). TABLE is the UI's pattern's
 * lock table (slide.c sl_ui_table_now) */
u32 rt_trig_get(const u8 *table, u32 t, u32 step)
{
    u32 v = sl_lock_get(table, t, step, 2);
    return v == RT_TRIG || v == RT_ONESHOT || v == RT_SPENT ? v : RT_NONE;
}

/* [TRIG]: none -> a recorder trig -> none; FUNC + [TRIG]: none -> a one-shot (armed) -> none;
 * either key on the other kind makes it that kind. -> the value now */
u32 rt_trig_toggle(u8 *table, u32 t, u32 step, int oneshot)
{
    u32 v = rt_trig_get(table, t, step);
    u32 want = oneshot ? RT_ONESHOT : RT_TRIG;
    u32 nv = (v == want || (oneshot && v == RT_SPENT)) ? RT_NONE : want;
    if (!sl_lock_set(table, t, step, 2, nv))
        return v;                               /* no record free: unchanged */
    return nv;
}

/* YES YES: every spent one-shot of the track armed again; -> how many */
u32 rt_rearm(u8 *table, u32 t)
{
    u32 n = 0;
    for (u32 s = 0; s < 128; s++)
        if (sl_lock_get(table, t, s, 2) == RT_SPENT && sl_lock_set(table, t, s, 2, RT_ONESHOT))
            n++;
    return n;
}

/* the track's recorder trigs: *TRIGS, *ONESHOTS (armed), *SPENT; -> all three together */
u32 rt_count(const u8 *table, u32 t, u32 *trigs, u32 *oneshots, u32 *spent)
{
    u32 a = 0, b = 0, c = 0;
    for (u32 s = 0; s < 128; s++) {
        u32 v = sl_lock_get(table, t, s, 2);
        if (v == RT_TRIG) a++;
        else if (v == RT_ONESHOT) b++;
        else if (v == RT_SPENT) c++;
    }
    *trigs = a;
    *oneshots = b;
    *spent = c;
    return a + b + c;
}

/* v0.44: a take saved into a pool slot (rec.c, FUNC + YES): the playing half's frames become
 * the slot's; the buffer goes on playing them until its next take, which goes elsewhere
 * (the allocator keeps clear of the slot's frames as of any sample's). -> the half's place
 * (bytes into the area) and *BYTES, or 0 with nothing to save */
u32 rt_take_handover(u32 t, u32 *bytes, u32 *steps)
{
    u32 b = rt_buf_of(t);
    int ix = HALF_IX(b, rt_play[b]);
    if (!rt_on || !rt_rbytes[ix] || (rt_cur == (int)b && (int)(FRAMES - rt_cur_end) < 0)) {
        *bytes = 0;
        *steps = 0;
        return 0;
    }
    *bytes = rt_rbytes[ix];
    *steps = rt_rsteps[ix];
    return rt_rplace[ix];
}
