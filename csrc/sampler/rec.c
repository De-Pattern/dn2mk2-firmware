/* The recorder's ColdFire end (docs/sampler.md, v0.15): the RECORDER page (SYN page 3 of a
 * sample machine, drawn by smp_page.c's smp_rec_draw), its YES key, ARM, and the
 * commands it sends the DSP (link.c's smp_command; dnfw.sampler.program.recorder).
 *
 * Nothing about the recorder is saved with a sound. Its settings sit on the page's records
 * (SRC, CHAN, THRES, DEST, R.LEN, R.STRT), but the DSP only ever acts on a command, and a
 * command is only sent while the page is on the screen:
 *   - YES records at once (or stops a recording), as the DT2's RECORD NOW;
 *   - turning ARM arms the recorder (R.STRT THRES: at the threshold; PLAY: at the first
 *     note any track plays) or, armed or recording, stops it. ARM's switch shows what the
 *     DSP is doing, not the record's value, so a sound saved with ARM on arms nothing.
 *   - SRC and CHAN are sent as they change, so the meter shows the source.
 * A recording, once it ends, is saved to the +Drive (link.c's smp_save_recording, v0.16).
 * The DSP answers in the SPI reply's tail (link.c's smp_status): its state, the command it
 * last took, the frames recorded, the block's peak.
 */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define FRAMES (*(volatile u32 *)0x4058E8D4u)                         /* frames since boot, 1,500 a second */
#define CTL_FRAME ((volatile u16 *)0x80005E60u)
#define TEMPO_WORD 108                                               /* the frame's BPM x 120 (byte 216) */
#define KEY_ORIG ((int (*)(void *, void *))0x40016480u)              /* the parameter page's key handler */
#define KEY_CODE ((int (*)(void *))0x40116018u)
#define KEY_PRESSED ((int (*)(void *))0x401160BCu)
#define KEY_YES 10
#define VISIBLE 750u                                                 /* frames: half a second */

#define CMD_ARM 1
#define CMD_NOW 2
#define CMD_STOP 3
#define CMD_MONITOR 4
#define CMD_ARM_PLAY 5

extern void smp_command(u32 cmd, u32 src, u32 chan, u32 thres, u32 dest_frames);
extern int smp_status(u16 *out);
extern void smp_save_recording(int slot, u32 frames);

/* what the page last drew (smp_rec_draw fills these each time it draws) */
void *rec_view __attribute__((section(".data"))) = 0;
u32 rec_seen __attribute__((section(".data"))) = 0;          /* FRAMES then, + 1 (0: never) */
int rec_src __attribute__((section(".data"))) = 0;           /* 0 IN, 1 MAIN, 2 + t */
int rec_chan __attribute__((section(".data"))) = 0;
int rec_thres __attribute__((section(".data"))) = 0;         /* 0..120 */
int rec_dest __attribute__((section(".data"))) = 0;          /* 0..3: SAMP 124..127 */
int rec_rlen __attribute__((section(".data"))) = 0;          /* 0 MAX, else steps */
int rec_rstrt __attribute__((section(".data"))) = 0;         /* 0 THRES, 1 PLAY */
int rec_arm __attribute__((section(".data"))) = 0;           /* the ARM record's value */

/* what the DSP last said */
int rec_state __attribute__((section(".data"))) = 0;         /* 0 idle, 1 armed, 2 recording, 3 done */
u32 rec_frames __attribute__((section(".data"))) = 0;
int rec_peak __attribute__((section(".data"))) = 0;          /* 0..32767 */
u32 rec_heard __attribute__((section(".data"))) = 0;         /* FRAMES of the last good status, + 1 */

static int arm_known __attribute__((section(".data"))) = 0;
static int arm_last __attribute__((section(".data"))) = 0;
static int mon_known __attribute__((section(".data"))) = 0;
static int mon_src __attribute__((section(".data"))) = 0;
static int mon_chan __attribute__((section(".data"))) = 0;
static u16 st[16] __attribute__((section(".data")));
static int rec_taken __attribute__((section(".data"))) = 0;   /* the slot a recording goes into */
static int was_recording __attribute__((section(".data"))) = 0;

int rec_visible(void)
{
    return rec_seen && FRAMES + 1u - rec_seen < VISIBLE;
}

/* the frames R.LEN asks for: MAX the slot's whole length, else that many sixteenth steps
 * at the tempo (BPM x 120 in the frame: 48,000 x 60 / 4 x 120 / that = 86,400,000 / it) */
static u32 rec_length(void)
{
    u32 full = 1u << 20;
    if (rec_rlen <= 0)
        return full;
    u32 bpm120 = CTL_FRAME[TEMPO_WORD];
    if (bpm120 < 1200)
        bpm120 = 14400;
    u32 f = (u32)rec_rlen * (86400000u / bpm120);
    return f > full ? full : f;
}

static void send(int cmd)
{
    u32 thr = (u32)rec_thres * 32767u / 120u;
    smp_command((u32)cmd, (u32)rec_src, (u32)rec_chan, thr, (u32)rec_dest << 24 | rec_length());
    if (cmd == CMD_NOW || cmd == CMD_ARM || cmd == CMD_ARM_PLAY)
        rec_taken = rec_dest;
    if (cmd != CMD_MONITOR) {
        mon_src = rec_src;
        mon_chan = rec_chan;
    }
}

/* YES on the page: RECORD NOW, or stop a recording */
void rec_yes(void)
{
    send(rec_state == 2 ? CMD_STOP : CMD_NOW);
}

/* from the UI loop (page.c's wr_poll), every pass */
void rec_poll(void)
{
    if (smp_status(st)) {
        rec_state = st[0] & 3;
        rec_frames = (u32)st[2] << 6;              /* 64 frames a unit (v0.16) */
        rec_peak = st[3] & 0x7FFF;
        rec_heard = FRAMES + 1u;
        /* a recording has ended (v0.16): it is kept on the +Drive, as the DT2 keeps its
         * recordings, and is there again after a power cycle */
        if (rec_state == 2)
            was_recording = 1;
        else if (was_recording) {
            was_recording = 0;
            smp_save_recording(rec_taken, rec_frames);
        }
    }
    if (!rec_visible()) {                       /* off the page: nothing is sent */
        arm_known = mon_known = 0;
        return;
    }
    if (!mon_known || rec_src != mon_src || rec_chan != mon_chan) {
        mon_known = 1;
        mon_src = rec_src;
        mon_chan = rec_chan;
        if (rec_state != 2)                     /* not while recording: the source stays */
            send(CMD_MONITOR);
    }
    if (!arm_known) {                           /* what ARM was when the page came up */
        arm_known = 1;
        arm_last = rec_arm;
    } else if (rec_arm != arm_last) {           /* turned: a toggle */
        arm_last = rec_arm;
        if (rec_state == 1 || rec_state == 2)
            send(CMD_STOP);
        else
            send(rec_rstrt ? CMD_ARM_PLAY : CMD_ARM);
    }
}

/* the parameter page's key handler (its vtable slot at 0x401d49a8 points here): YES on the
 * RECORDER page is ours; everything else, and every other page, is stock's */
int smp_key(void *view, void *ev)
{
    if (view == rec_view && rec_visible() && KEY_CODE(ev) == KEY_YES) {
        if (KEY_PRESSED(ev) & 0xFF)
            rec_yes();
        return 1;
    }
    return KEY_ORIG(view, ev);
}
