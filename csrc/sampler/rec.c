/* The recorder's ColdFire end (docs/sampler.md; v0.22: the DT2's SAMPLING screen, global).
 *
 * FUNC + VOICE (the DN2's unison toggle, replaced; VOICE alone still opens its menu)
 * opens the RECORDER over whatever page is up, and closes it again. While it is up its
 * eight knobs are the recorder's, not the track's (smp_ui_pop takes them out of the UI
 * queue before any view sees them):
 *
 *   A SRC     EXT L+R, EXT L, EXT R, MAIN, TRK1..16
 *   D THRES   0..120, the meter's tick
 *   E DEST    the slot the recording goes into (SAMP 1..127); the next empty one
 *   F R.LEN   MAX, or 1..128 sixteenth steps at the tempo
 *   G R.STRT  THRES (when the input reaches THRES) or PLAY (the first note any track plays)
 *   H ARM     a turn arms the recorder (or, armed or recording, stops it)
 *   YES       records at once, or stops; NO closes the screen (a recording goes on)
 *
 * Any page key, [TRK], [PTN], [SONG], [PRESET] or [SETTINGS] closes it and does what it
 * does; PLAY, STOP, the trigs and FUNC pass through and keep it up. FUNC + VOICE brings
 * it back; a recording runs on behind any page, as on the DT2.
 *
 * A recording goes where there is room in the recordings' area (link.c's smp_rec_place:
 * the largest free stretch; the slot's own old recording is freed), into the slot DEST
 * names; when it ends it is saved to the +Drive with the name RECnnn (link.c), and DEST
 * moves on to the next empty slot. The DSP answers in the SPI reply's tail (smp_status):
 * its state, the command it last took, the frames recorded, the block's peak.
 */
#include "wr_gen.h"

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define FRAMES (*(volatile u32 *)0x4058E8D4u)                         /* frames since boot, 1,500 a second */
#define REC_THR_FLOOR 33u                       /* v0.30: THRES 0's level, -60 dB, under any real input */
#define CTL_FRAME ((volatile u16 *)0x80005E60u)
#define TEMPO_WORD 108                                               /* the frame's BPM x 120 (byte 216) */
#define KEY_ORIG ((int (*)(void *, void *))0x40016480u)              /* the parameter page's key handler */
/* the UI queue's receive: the item in d0. Declared as returning an integer: GCC takes a
 * returned pointer from a0, where the stock code leaves nothing of the kind */
#define UI_POP ((u32 (*)(void *))0x40001928u)

#define CMD_ARM 1
#define CMD_NOW 2
#define CMD_STOP 3
#define CMD_MONITOR 4
#define CMD_ARM_PLAY 5

/* UI-queue items (16 bytes): type, then code, flags (keys) or index, delta (knobs) */
#define IT_KEY 0
#define IT_KNOB 1
#define IT_DROP 0xFF                                                 /* past every case: the loop skips it */
#define F_PRESS 0x01
#define F_RELEASE 0x10
enum { K_TRIG = 1, K_MOD = 6, K_PRESET = 7, K_SETTINGS = 8, K_YES = 10, K_UP = 11, K_NO = 12,
       K_LEFT = 13, K_DOWN = 14, K_RIGHT = 15, K_TRK = 16, K_PTN = 23, K_SONG = 24,
       K_FUNC = 17, K_PLAY = 20, K_ENC_A = 41, K_ENC_H = 48 };

extern u32 smp_command(u32 cmd, u32 src, u32 chan, u32 thres, u32 dest_frames);
extern int smp_status(u16 *out);
extern void smp_save_recording(int slot, u32 off, u32 frames);
extern u32 smp_rec_place(int dest, u32 *room);
extern int smp_slot_empty(int k);
extern int smp_list_up(void *view);
extern void smp_list_hold(void);
extern void smp_list_close(void);
extern void smp_list_settle(int v);
extern void *smp_list_view;
extern int smp_lst_orig, smp_overlay_dirty;     /* v0.25: the list, the folder browser */
extern int smp_fb_open, smp_fb_folder, smp_fb_cur;
extern int smp_fb_item(int i, int *slot);
extern int smp_fb_menu, smp_fb_mcur;
extern int smp_fb_index_of(int f);
extern int smp_fb_marked(int k), smp_fb_nactions(int on_folder);     /* v0.29: multi-select */
extern void smp_fb_mark(int k, int on), smp_fb_mark_folder(int folder), smp_fb_unmark_all(void);
extern void smp_fb_delete(int slot, int folder);
extern void smp_discard(int k);
static void rename_start(int slot);
static int lst_func __attribute__((section(".data"))) = 0;
#define UI_TRACK_NOW (*(volatile unsigned char *)0x42431A6Cu)
int smp_set_samp(int track, int value);
int smp_samp_of(int track);
extern u32 smp_frames(int k);
extern int smp_trim(int k, u32 s, u32 e);
extern void smp_discard(int k);
extern void smp_rename(int k, const char *name);
extern const char *smp_name(int k);
extern int smp_saved;
int smp_assign(int track, int slot);                 /* below: 0 done */

/* v0.22: after a recording, the DT2's steps (manual 13.2, 9..11): TRIM, then NAME, then
 * ASSIGN (a [TRIG] key: that track plays it; NO: none). rec_phase 0 is the RECORDER. */
enum { PH_REC, PH_TRIM, PH_NAME, PH_ASSIGN, PH_WORK };   /* v0.25: WORK, NORMALIZING */
int rec_phase __attribute__((section(".data"))) = PH_REC;
int trim_slot __attribute__((section(".data"))) = -1;
u32 trim_n __attribute__((section(".data"))) = 0;           /* its frames, as recorded */
u32 trim_s __attribute__((section(".data"))) = 0;
u32 trim_e __attribute__((section(".data"))) = 0;
char nm_text[8] __attribute__((section(".data")));           /* the name being edited */
int nm_cur __attribute__((section(".data"))) = 0;
int as_done __attribute__((section(".data"))) = -1;          /* the track it went to, for the screen */
static const char NM_SET[] = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_";
/* v0.25: the DT2's character grid, while FUNC is held on FILE NAME (the owner's photo):
 * FUNC + the arrows move through it, and letting FUNC go puts the character at the cursor */
const char nm_grid[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ-_0123456789 ";
#define NM_GRID_W 14
int nm_gsel __attribute__((section(".data"))) = 0;          /* the grid's cell */
static int nm_gpicked __attribute__((section(".data"))) = 0;  /* an arrow moved it this hold */

/* the recorder's settings: the instrument's, not a sound's (none of it is saved) */
int rec_overlay __attribute__((section(".data"))) = 0;      /* the screen is up */
int rec_src __attribute__((section(".data"))) = 0;          /* SMP_REC_SOURCES choices */
int rec_thres __attribute__((section(".data"))) = 0;        /* 0..120 */
int rec_dest __attribute__((section(".data"))) = -1;        /* slot 0..126 (SAMP 1..127); -1 not chosen */
int rec_rlen __attribute__((section(".data"))) = 0;         /* 0 MAX, else steps */
int rec_rstrt __attribute__((section(".data"))) = 0;        /* 0 THRES, 1 PLAY */
u32 rec_room __attribute__((section(".data"))) = 0;         /* bytes free for the next recording */

/* what the DSP last said */
int rec_state __attribute__((section(".data"))) = 0;        /* 0 idle, 1 armed, 2 recording, 3 done */
u32 rec_frames __attribute__((section(".data"))) = 0;
int rec_peak __attribute__((section(".data"))) = 0;         /* 0..32767 */
u32 rec_heard __attribute__((section(".data"))) = 0;        /* FRAMES of the last good status, + 1 */
int rec_link __attribute__((section(".data"))) = 0;         /* the DSP took our last command: 1, -1 no, 0 ? */
int rec_saved_slot __attribute__((section(".data"))) = -1;  /* the last recording's slot, for the screen */

static u32 sent_seq __attribute__((section(".data"))) = 0;
static u32 sent_at __attribute__((section(".data"))) = 0;
static int mon_known __attribute__((section(".data"))) = 0;
static int mon_src __attribute__((section(".data"))) = -1;
static u16 st[16] __attribute__((section(".data")));
static int rec_taken __attribute__((section(".data"))) = -1;   /* the slot the recording goes into */
static u32 rec_off __attribute__((section(".data"))) = 0;      /* .. its place in the area */
static int was_recording __attribute__((section(".data"))) = 0;
static u32 eaten __attribute__((section(".data"))) = 0;        /* keys whose press we took: their release too */

int rec_visible(void)
{
    return rec_overlay;
}

/* the DSP's source and channel for a SRC choice: EXT L+R, L, R; MAIN; TRK1..16 */
static void src_of(int s, u32 *src, u32 *chan)
{
    if (s < 3) { *src = 0; *chan = (u32)s; }
    else if (s == 3) { *src = 1; *chan = 0; }
    else { *src = (u32)(s - 2); *chan = 0; }
}

/* the frames R.LEN asks for: MAX the most the DSP records (66 s), else that many sixteenth
 * steps at the tempo (BPM x 120 in the frame: 48,000 x 60 / 4 x 120 / that = 86,400,000 / it) */
static u32 rec_length(void)
{
    u32 full = 0xFFFFFFu;
    if (rec_rlen <= 0)
        return full;
    u32 bpm120 = CTL_FRAME[TEMPO_WORD];
    if (bpm120 < 1200)
        bpm120 = 14400;
    u32 f = (u32)rec_rlen * (86400000u / bpm120);
    return f > full ? full : f;
}

static int next_empty(int from)
{
    for (int j = 0; j < 127; j++) {
        int k = (from + j) % 127;
        if (smp_slot_empty(k))
            return k;
    }
    return from % 127;
}

static void send(int cmd)
{
    u32 src, chan, thr = (u32)rec_thres * 32767u / 120u;
    if (thr < REC_THR_FLOOR)                    /* v0.30: THRES 0 waits for a sound, not for */
        thr = REC_THR_FLOOR;                    /* silence (a user: it began on nothing) */
    src_of(rec_src, &src, &chan);
    if (rec_dest < 0)
        rec_dest = next_empty(0);
    u32 place = 0;
    if (cmd == CMD_NOW || cmd == CMD_ARM || cmd == CMD_ARM_PLAY) {
        u32 room;
        place = smp_rec_place(rec_dest, &room);
        rec_room = room;
        if (room < 0x10000u)                    /* no room: nothing is recorded */
            return;
        rec_taken = rec_dest;
        rec_off = place;
    }
    sent_seq = smp_command((u32)cmd, src, chan | (place / 512u) << 8, thr,
                           (u32)rec_dest << 24 | rec_length());
    sent_at = FRAMES;
    if (rec_link < 0)
        rec_link = 0;
    mon_src = rec_src;
}

void rec_yes(void)
{
    send(rec_state == 2 ? CMD_STOP : CMD_NOW);
}

/* v0.30: H's turn, as one action a turn (a user: "the knob acceleration is wonky on ARM":
 * every detent toggled it, so a quick turn armed, stopped and armed again). Right arms,
 * left stops; after an action the knob is left alone for 0.4 s. */
static u32 arm_at __attribute__((section(".data"))) = 0;

static void rec_arm_turn(int delta)
{
    u32 now = FRAMES;
    if (arm_at && now - arm_at < 600u)
        return;
    if (delta > 0 && rec_state != 1 && rec_state != 2)
        send(rec_rstrt ? CMD_ARM_PLAY : CMD_ARM);
    else if (delta < 0 && (rec_state == 1 || rec_state == 2))
        send(CMD_STOP);
    else
        return;
    arm_at = now ? now : 1u;
}

/* FUNC + VOICE (coldfire.py's REC_COMBO_SITE, in the main key handler's VOICE case) */
static void preview(int on);
void rec_combo(void)
{
    preview(0);
    rec_overlay = !rec_overlay;
    rec_phase = PH_REC;                         /* a recording mid-TRIM keeps what it is */
    if (rec_overlay) {
        mon_known = 0;
        if (rec_dest < 0 || (!smp_slot_empty(rec_dest) && rec_dest != rec_saved_slot))
            rec_dest = next_empty(rec_dest < 0 ? 0 : rec_dest);
        u32 room;
        smp_rec_place(rec_dest, &room);
        rec_room = room;
    }
}

/* v0.25: the RECORDING screen's waveform, as the DT2 draws it while it records: the
 * peak of each column's stretch, REC_WAVE_W columns of rec_wave_span frames; when the
 * recording passes the last, the columns pair up and each spans twice as long */
#define REC_WAVE_W 120
u8 rec_wave[REC_WAVE_W] __attribute__((section(".data")));
u32 rec_wave_span __attribute__((section(".data"))) = 2400;    /* 50 ms a column to start */
extern int smp_overlay_dirty;

static void rec_wave_reset(void)
{
    for (int j = 0; j < REC_WAVE_W; j++)
        rec_wave[j] = 0;
    rec_wave_span = 2400;
}

static void rec_wave_add(u32 frames, int peak)
{
    while (frames / rec_wave_span >= REC_WAVE_W) {
        for (int j = 0; j < REC_WAVE_W / 2; j++)
            rec_wave[j] = rec_wave[2 * j] > rec_wave[2 * j + 1] ? rec_wave[2 * j] : rec_wave[2 * j + 1];
        for (int j = REC_WAVE_W / 2; j < REC_WAVE_W; j++)
            rec_wave[j] = 0;
        rec_wave_span *= 2u;
    }
    u32 c = frames / rec_wave_span;
    u8 v = (u8)(peak >> 7);
    if (v > rec_wave[c])
        rec_wave[c] = v;
}

/* from the UI loop (page.c's wr_poll), every pass */
static void rpt_poll(void);

void rec_poll(void)
{
    rpt_poll();
    if (smp_status(st)) {
        rec_state = st[0] & 3;
        rec_frames = (u32)st[2] << 6;              /* 64 frames a unit (v0.16) */
        rec_peak = st[3] & 0x7FFF;
        rec_heard = FRAMES + 1u;
        if (sent_seq && st[1] == (u16)sent_seq)
            rec_link = 1;
        /* a recording has ended: it is kept on the +Drive, as the DT2 keeps its
         * recordings, and is there again after a power cycle; DEST moves on */
        if (rec_state == 2) {
            if (!was_recording)
                rec_wave_reset();
            rec_wave_add(rec_frames, rec_peak);
            was_recording = 1;
        }
        else if (was_recording) {
            was_recording = 0;
            if (rec_taken >= 0) {
                smp_save_recording(rec_taken, rec_off, rec_frames);
                rec_saved_slot = rec_taken;
                if (rec_overlay) {                  /* NORMALIZING, then TRIM, as the DT2 */
                    rec_phase = PH_WORK;
                    trim_slot = rec_taken;
                    trim_n = rec_frames;
                    trim_s = 0;
                    trim_e = rec_frames;
                }
                rec_dest = next_empty(rec_taken + 1);
                if (rec_dest == rec_taken)
                    rec_dest = rec_taken;
            }
        }
    }
    if (rec_phase == PH_WORK && smp_saved != 0) {   /* v0.25: saved (and normalised): TRIM */
        u32 n = smp_frames(trim_slot);
        if (n) {
            trim_n = n;
            trim_s = 0;
            trim_e = n;
        }
        rec_phase = PH_TRIM;
        smp_overlay_dirty = 1;
    }
    if (sent_seq && rec_link == 0 && FRAMES - sent_at > 1500u)
        rec_link = -1;                          /* sent, and no echo within a second */
    if (!rec_overlay) {                         /* off the screen: no monitoring is sent */
        mon_known = 0;
        return;
    }
    if (!mon_known || rec_src != mon_src) {
        mon_known = 1;
        if (rec_state != 2)                     /* not while recording: the source stays */
            send(CMD_MONITOR);
        mon_src = rec_src;
    }
}

static int clamp(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

/* a knob on the recorder's screen: INDEX 1..8 (A..H), DELTA detents */
static void knob(int index, int delta)
{
    switch (index) {
    case 1: rec_src = clamp(rec_src + delta, 0, SMP_REC_SOURCES - 1); break;
    case 4: rec_thres = clamp(rec_thres + delta, 0, 120); break;
    case 5: if (rec_state != 2 && rec_state != 1) rec_dest = clamp((rec_dest < 0 ? 0 : rec_dest) + delta, 0, 126);
        break;
    case 6: rec_rlen = clamp(rec_rlen + delta, 0, 128); break;
    case 7: rec_rstrt = delta > 0 ? 1 : 0; break;
    case 8: rec_arm_turn(delta); break;
    default: break;
    }
}

static int closes(u32 code)
{
    return (code >= K_TRIG && code <= K_MOD) || code == K_PRESET || code == K_SETTINGS
           || code == K_TRK || code == K_PTN || code == K_SONG;
}

/* -- v0.22: TRIM, NAME, ASSIGN ------------------------------------------------------------- */

#define K_TRIG1 25                              /* the sixteen [TRIG] keys: 25..40 (digikit's panel map) */

/* the recording to track TRACK: its SAMP, and ONESHOT if it plays no sample (-> 0 done) */
/* the stock calls a knob turn and MACHINE SEL make (found and called in the emulator):
 * the UI's owner (a singleton, built long before), its model, a parameter's set on a track,
 * setValue(set, id, value << 8, track, rec 0, midi 0, announce 1) as the knob path, and
 * MACHINE SEL's commit(model, track, type, 1, 1), which resets the sound to the machine's
 * defaults (so SAMP is set after it) */
#define UI_OWNER   ((u32 (*)(void))0x4018A97Au)
#define PARAM_SET  ((u32 (*)(u32, u32, u32))0x40041A40u)
#define SET_VALUE  ((u32 (*)(u32, u32, u32, u32, u32, u32, u32))0x40037326u)
#define MACHINE_COMMIT ((u32 (*)(u32, u32, u32, u32, u32))0x40031880u)
#define KIT (*(volatile u32 *)0x800052A0u)
#define SOUND_TYPE(t) (*(volatile signed char *)(KIT + 52u + 1163u * (u32)(t) + 0xDEu))
#define ONESHOT 8                               /* dnfw.sampler.machines.TYPE_OF; 8..8 + SMP_N - 1 */

int smp_assign(int track, int slot)
{
    if (track < 0 || track > 15 || slot < 0 || slot > 126 || !KIT)
        return -1;
    u32 owner = UI_OWNER();
    if (!owner)
        return -1;
    int ty = SOUND_TYPE(track);
    if (ty < ONESHOT || ty >= ONESHOT + SMP_N) {    /* not a sample machine: ONESHOT, as the DT2's audio tracks */
        MACHINE_COMMIT(owner + 0xF4u, (u32)track, ONESHOT, 1, 1);
        if (SOUND_TYPE(track) != ONESHOT)
            return -1;                          /* refused (stock's permission): nothing set */
    }
    u32 ps = PARAM_SET(owner, SMP_SAMP_ID, (u32)track);
    if (!ps)
        return -1;
    SET_VALUE(ps, SMP_SAMP_ID, (u32)(slot + 1) << 8, (u32)track, 0, 0, 1);
    return 0;
}

/* v0.25: SAMP on TRACK set to VALUE (0 OFF, k slot k - 1) as the knob sets it, and read */
int smp_set_samp(int track, int value)
{
    if (track < 0 || track > 15 || value < 0 || value > 127 || !KIT)
        return -1;
    int ty = SOUND_TYPE(track);
    if (ty < ONESHOT || ty >= ONESHOT + SMP_N)
        return -1;                              /* not a sample machine: nothing to set */
    u32 owner = UI_OWNER();
    if (!owner)
        return -1;
    u32 ps = PARAM_SET(owner, SMP_SAMP_ID, (u32)track);
    if (!ps)
        return -1;
    SET_VALUE(ps, SMP_SAMP_ID, (u32)value << 8, (u32)track, 0, 0, 1);
    return 0;
}

int smp_samp_of(int track)
{
    if (track < 0 || track > 15 || !KIT)
        return 0;
    return *(volatile u8 *)(KIT + 52u + 1163u * (u32)track + 20u + 2u * 43u);
}

/* a [TRIG] key's track, or -1 */
int smp_trig_track(u32 code)
{
    return code >= K_TRIG1 && code < K_TRIG1 + 16u ? (int)(code - K_TRIG1) : -1;
}

static void name_start(void)
{
    const char *n = smp_name(trim_slot);
    int j = 0;
    for (; j < 7 && n && n[j]; j++)
        nm_text[j] = n[j];
    for (; j < 8; j++)
        nm_text[j] = 0;
    nm_cur = 0;
    rec_phase = PH_NAME;
}

static void name_step(int d)
{
    char ch = nm_text[nm_cur] ? nm_text[nm_cur] : ' ';
    int i = 0, n = (int)sizeof NM_SET - 1;
    while (i < n && NM_SET[i] != ch)
        i++;
    i = ((i + d) % n + n) % n;
    nm_text[nm_cur] = NM_SET[i];
    for (int j = 0; j < nm_cur; j++)            /* no hole before the cursor */
        if (!nm_text[j])
            nm_text[j] = ' ';
}

static int nm_only __attribute__((section(".data"))) = 0;   /* v0.25: the browser's RENAME */

static void rename_start(int slot)
{
    if (slot < 0 || slot > 126 || rec_phase != PH_REC)
        return;
    trim_slot = slot;
    name_start();
    nm_only = 1;
    rec_overlay = 1;
}

static void name_done(void)
{
    char t[8];
    int j, last = -1;
    for (j = 0; j < 7; j++) {
        t[j] = nm_text[j] ? nm_text[j] : ' ';
        if (t[j] != ' ')
            last = j;
    }
    if (last >= 0) {                            /* trailing spaces off; an empty name stays as it was */
        t[last + 1] = 0;
        smp_rename(trim_slot, t);
    }
    as_done = -1;
    rec_phase = PH_ASSIGN;
    if (nm_only) {                              /* the browser's RENAME: done, back to the page */
        nm_only = 0;
        rec_phase = PH_REC;
        rec_overlay = 0;
    }
}

/* v0.25: FUNC as it is held now, kept from every FUNC press and release the UI queue
 * carries (they all pass here, and on to stock). The DN2's own key items' bit 1 is not a
 * FUNC chord: on the instrument a plain YES carries it (the owner's v0.24: YES on TRIM and
 * on a SLICE track did nothing), so nothing here reads it. */
int smp_func_held __attribute__((section(".data"))) = 0;
int rec_pv_on __attribute__((section(".data"))) = 0;      /* a preview playing, while held */
static u32 knob_at __attribute__((section(".data"))) = 0;    /* the last trim knob's FRAMES */
#define CMD_PREVIEW 9
extern int smp_overlay_dirty;

static void preview(int on)
{
    if (on && trim_slot >= 0)
        smp_command(CMD_PREVIEW, (u32)trim_slot, trim_s, trim_e, 0);
    else if (rec_pv_on)
        smp_command(CMD_PREVIEW, (u32)(trim_slot < 0 ? 0 : trim_slot), 0, 0, 0);
    rec_pv_on = on && trim_slot >= 0;
}

/* a TRIM knob: E START, H END. A detent moves a 1000th of the recording, more the faster
 * the knob turns (as a sample machine's start moves), a 10,000th with FUNC held */
static void trim_knob(int index, int delta, int fine)
{
    u32 now = FRAMES, dt = now - knob_at;
    knob_at = now;
    int ad = delta < 0 ? -delta : delta;
    u32 mul = fine ? 1u : dt < 12u ? 12u : dt < 30u ? 5u : dt < 60u ? 2u : 1u;
    u32 step = trim_n / (fine ? 10000u : 1000u) * mul * (u32)ad;
    if (step < 2u)
        step = 2u;
    int sgn = delta < 0 ? -1 : 1;
    if (index == 5) {
        int v = (int)trim_s + sgn * (int)step;
        if (v < 0) v = 0;
        if ((u32)v + 64u > trim_e) v = (int)trim_e - 64;
        trim_s = (u32)(v < 0 ? 0 : v);
    } else if (index == 8) {
        int v = (int)trim_e + sgn * (int)step;
        if ((u32)(v < 0 ? 0 : v) < trim_s + 64u) v = (int)trim_s + 64;
        if ((u32)v > trim_n) v = (int)trim_n;
        trim_e = (u32)v;
    }
    smp_overlay_dirty = 1;                      /* drawn at once, not at the next tick */
}

/* the DT2's FILE NAME keys: a character at the cursor removed (FUNC + NO), a space put in
 * (FUNC + YES) */
static void name_delete(void)
{
    for (int j = nm_cur; j < 6; j++)
        nm_text[j] = nm_text[j + 1];
    nm_text[6] = 0;
}

static void name_insert(void)
{
    for (int j = 6; j > nm_cur; j--)
        nm_text[j] = nm_text[j - 1];
    nm_text[nm_cur] = ' ';
}

/* the name grid: an arrow moves the selection (v0.26: LEFT/RIGHT round its row) */
static void grid_move(u32 code)
{
    int n = (int)sizeof nm_grid - 1;
    if (code == K_LEFT || code == K_RIGHT) {
        int r0 = nm_gsel / NM_GRID_W * NM_GRID_W;
        int w = n - r0 < NM_GRID_W ? n - r0 : NM_GRID_W;
        int col = nm_gsel - r0 + (code == K_RIGHT ? 1 : -1);
        nm_gsel = r0 + (col + w) % w;
    } else {
        int g = nm_gsel + (code == K_UP ? -NM_GRID_W : NM_GRID_W);
        if (g >= 0 && g < n)
            nm_gsel = g;
    }
    nm_gpicked = 1;
}

/* v0.27: LEFT/RIGHT held on FILE NAME repeat (owner: as the DN2's own naming screen), a
 * short wait and then a steady step; rec_poll steps them, the key's release stops them */
#define RPT_WAIT 600u                           /* 0.4 s, in the 1.5 kHz ticks of 0x4058e8d4 */
#define RPT_STEP 120u                           /* then 12.5 a second */
static u32 rpt_code __attribute__((section(".data"))) = 0;
static u32 rpt_next __attribute__((section(".data"))) = 0;
static int rpt_grid __attribute__((section(".data"))) = 0;

static void rpt_start(u32 code)
{
    rpt_code = code;
    rpt_grid = smp_func_held;
    rpt_next = *(volatile u32 *)0x4058E8D4u + RPT_WAIT;
}

/* v0.30: UP/DOWN held in the sample list or the folder browser step on by themselves, as
 * FILE NAME's arrows (owner): 0.4 s, then 12.5 a second, until let go */
static u32 lrpt_code __attribute__((section(".data"))) = 0;
static u32 lrpt_next __attribute__((section(".data"))) = 0;
static void lst_step(u32 code);

static void lrpt_poll(void)
{
    if (!lrpt_code)
        return;
    u32 now = *(volatile u32 *)0x4058E8D4u;
    if ((int)(now - lrpt_next) < 0)
        return;
    lrpt_next = now + RPT_STEP;
    lst_step(lrpt_code);
}

static void rpt_poll(void)
{
    lrpt_poll();
    if (!rpt_code)
        return;
    if (!rec_overlay || rec_phase != PH_NAME || rpt_grid != smp_func_held) {
        rpt_code = 0;
        return;
    }
    u32 now = *(volatile u32 *)0x4058E8D4u;
    if ((int)(now - rpt_next) < 0)
        return;
    rpt_next = now + RPT_STEP;
    if (rpt_grid)
        grid_move(rpt_code);
    else if (rpt_code == K_LEFT && nm_cur > 0)
        nm_cur--;
    else if (rpt_code == K_RIGHT && nm_cur < 6)
        nm_cur++;
    smp_overlay_dirty = 1;
}

static u32 after_pop(u8 *it, u32 code, u32 flags)
{
    if (it[0] == IT_KNOB) {
        int delta = (signed char)it[8];
        if (code >= 1 && code <= 9) {                /* A..H, and LEVEL/DATA (9) */
            if (rec_phase == PH_TRIM)
                trim_knob((int)code, delta, smp_func_held);
            else if (rec_phase == PH_NAME) {
                name_step(delta);
                smp_overlay_dirty = 1;
            }
            it[0] = IT_DROP;
        }
        return (u32)it;
    }
    if (it[0] != IT_KEY)
        return (u32)it;
    int press = (flags & F_PRESS) && !(flags & F_RELEASE);
    if (code == K_FUNC)                         /* FUNC goes on to stock (noted in smp_ui_pop) */
        return (u32)it;
    int ours = code == K_YES || code == K_NO || (code >= K_UP && code <= K_RIGHT)
               || (code >= K_ENC_A && code <= K_ENC_H);
    if (rec_phase == PH_ASSIGN && smp_trig_track(code) >= 0)
        ours = 1;
    if (rec_phase == PH_NAME && code == K_PLAY && smp_func_held)
        ours = 1;                               /* v0.26: FUNC + PLAY clears the name */
    if (rec_phase == PH_WORK)                   /* NORMALIZING: the keys wait */
        ours = ours || code == K_SETTINGS;
    if (!ours) {
        if (press && closes(code) && rec_phase != PH_WORK) {
            preview(0);
            rec_overlay = 0;
            rec_phase = PH_REC;
        }
        return (u32)it;
    }
    if (press && code < 32)
        eaten |= 1u << code;
    it[0] = IT_DROP;
    if (!press)
        return (u32)it;
    smp_overlay_dirty = 1;
    if (rec_phase == PH_TRIM) {
        if (code == K_YES && smp_func_held) {           /* FUNC + YES: heard while held */
            preview(1);
        } else if (code == K_YES) {                     /* YES: saved, START..END */
            preview(0);
            if (trim_s > 0 || trim_e < trim_n)
                smp_trim(trim_slot, trim_s, trim_e);
            name_start();
        } else if (code == K_NO && smp_func_held) {     /* FUNC + NO: the recording is dropped */
            preview(0);
            smp_discard(trim_slot);
            rec_saved_slot = -1;
            rec_dest = trim_slot;
            rec_phase = PH_REC;
        } else if (code == K_LEFT || code == K_RIGHT) {
            trim_knob(code == K_LEFT ? 5 : 8, code == K_LEFT ? -1 : 1, 1);
        }
    } else if (rec_phase == PH_NAME) {
        if (code == K_PLAY) {                   /* v0.26, FUNC + PLAY: the name cleared */
            for (int j = 0; j < 8; j++)
                nm_text[j] = 0;
            nm_cur = 0;
            nm_gsel = 0;
            nm_gpicked = 0;
        } else if (code == K_YES && smp_func_held)
            name_insert();
        else if (code == K_NO && smp_func_held)
            name_delete();
        else if (code == K_YES)
            name_done();
        else if (code == K_NO && nm_only) {    /* the browser's RENAME, left as it was */
            nm_only = 0;
            rec_phase = PH_REC;
            rec_overlay = 0;
        } else if (code == K_NO) {
            as_done = -1;
            rec_phase = PH_ASSIGN;              /* the name it has */
        } else if (smp_func_held && code >= K_UP && code <= K_RIGHT) {  /* the grid */
            grid_move(code);
            if (code == K_LEFT || code == K_RIGHT)
                rpt_start(code);
        } else if (code == K_LEFT && nm_cur > 0) {
            nm_cur--;
            rpt_start(code);
        } else if (code == K_RIGHT && nm_cur < 6) {
            nm_cur++;
            rpt_start(code);
        }
        else if (code == K_UP || code == K_DOWN)
            name_step(code == K_UP ? 1 : -1);
    } else if (rec_phase == PH_ASSIGN) {
        int t = smp_trig_track(code);
        if (t >= 0) {
            if (smp_assign(t, trim_slot) == 0)
                as_done = t;
            rec_phase = PH_REC;
        } else if (code == K_NO || code == K_YES) {
            rec_phase = PH_REC;
        }
    }
    return (u32)it;
}

/* the UI loop's queue receive (coldfire.py's UI_POP_SITE): every item passes here before
 * any view sees it. With the recorder up, its keys and knobs are taken; with the sample
 * list up, UP and DOWN become SAMP's knob (D) a detent, and pushing that knob closes the
 * list. A taken item's type becomes IT_DROP, which the loop passes over. */
u32 smp_ui_pop(void *queue)                   /* -> the item, in d0 as the stock receive returns it */
{
    u8 *it = (u8 *)UI_POP(queue);
    if (!it)
        return (u32)it;
    u32 code = (u32)it[4] << 24 | (u32)it[5] << 16 | (u32)it[6] << 8 | it[7];
    u32 flags = (u32)it[8] << 24 | (u32)it[9] << 16 | (u32)it[10] << 8 | it[11];
    /* v0.25: a key's item: bit 0 while it is down (a press), bit 4 on most keys' release,
     * bit 1 while FUNC is held. FUNC's own release carries neither bit 0 nor bit 4 (the
     * emulator's panel, read through smp_ui_pop): v0.22..v0.24 waited for bit 4 and so
     * kept FUNC "held" for good after its first use -- YES on TRIM, a SLICE track's YES
     * and the list's YES then did nothing (the owner's v0.24 report). Released is "not
     * down", for every key. */
    int down = (flags & F_PRESS) && !(flags & F_RELEASE);
    if (it[0] == IT_KEY && code == K_FUNC) {
        if (rec_overlay && rec_phase == PH_NAME) {
            if (down && !smp_func_held) {       /* the grid opens on the cursor's character */
                char ch = nm_text[nm_cur] ? nm_text[nm_cur] : ' ';
                int g = 0;
                while (nm_grid[g] && nm_grid[g] != ch)
                    g++;
                nm_gsel = nm_grid[g] && ch != ' ' ? g : 0;   /* a blank: from A */
                nm_gpicked = 0;
            } else if (!down && nm_gpicked) {   /* let go: the picked character goes in */
                nm_text[nm_cur] = nm_grid[nm_gsel];
                for (int j = 0; j < nm_cur; j++)
                    if (!nm_text[j])
                        nm_text[j] = ' ';
                nm_gpicked = 0;
                if (nm_cur < 6)                 /* v0.26: and the cursor moves on */
                    nm_cur++;
            }
            smp_overlay_dirty = 1;
        }
        smp_func_held = down;
    }
    if (it[0] == IT_KEY && !down && code == rpt_code)
        rpt_code = 0;                           /* v0.27: the held arrow let go */
    if (it[0] == IT_KEY && !down && code == lrpt_code)
        lrpt_code = 0;                          /* v0.30: and the list's */
    if (rec_pv_on && it[0] == IT_KEY && !down && (code == K_YES || code == K_FUNC))
        preview(0);                             /* FUNC + YES let go: the preview stops */
    if (it[0] == IT_KEY && code < 32 && (eaten >> code & 1)) {
        if (!down) {                            /* the release of a key we took */
            eaten &= ~(1u << code);
            it[0] = IT_DROP;
        }
        return (u32)it;
    }
    if (!rec_overlay) {                          /* v0.23: SLICE's menus (slice.c) */
        extern int slc_pop(u8 *it);
        if (slc_pop(it)) {
            if (it[0] == IT_KEY && (flags & F_PRESS) && !(flags & F_RELEASE) && code < 32)
                eaten |= 1u << code;
            it[0] = IT_DROP;
            return (u32)it;
        }
    }
    if (rec_overlay && rec_phase != PH_REC)
        return after_pop(it, code, flags);
    if (rec_overlay) {
        if (it[0] == IT_KNOB) {
            u32 index = code;
            int delta = (signed char)it[8];
            if (index >= 1 && index <= 8) {
                knob((int)index, delta);
                it[0] = IT_DROP;
            }
            return (u32)it;
        }
        if (it[0] != IT_KEY)
            return (u32)it;
        int press = (flags & F_PRESS) && !(flags & F_RELEASE);
        if (code == K_YES || code == K_NO || (code >= K_UP && code <= K_RIGHT)
            || (code >= K_ENC_A && code <= K_ENC_H)) {
            if (press && code == K_YES)
                rec_yes();
            if (press && code == K_NO)
                rec_overlay = 0;                /* the screen closes; a recording goes on */
            if (press && code < 32)
                eaten |= 1u << code;
            it[0] = IT_DROP;
            return (u32)it;
        }
        if (press && closes(code))
            rec_overlay = 0;                    /* the key does what it does, and the page shows */
        return (u32)it;
    }
    lst_func = smp_func_held;                   /* v0.25: the list's FUNC + YES */
    /* v0.25: the folder browser (smp_page.c): over everything while it is up */
    if (smp_fb_open) {
        smp_overlay_dirty = 1;
        if (it[0] == IT_KNOB) {                 /* any knob: through the items (or the menu) */
            int delta = (signed char)it[8], d = delta > 0 ? 1 : delta < 0 ? -1 : 0;
            if (smp_fb_menu == 1) {
                int ks, kf = smp_fb_item(smp_fb_cur, &ks), last = smp_fb_nactions(ks < 0) - 1;
                (void)kf;
                smp_fb_mcur += d;
                if (smp_fb_mcur < 0) smp_fb_mcur = 0;
                if (smp_fb_mcur > last) smp_fb_mcur = last;
            } else if (!smp_fb_menu)
                smp_fb_cur += d;
            it[0] = IT_DROP;
            return (u32)it;
        }
        if (it[0] != IT_KEY)
            return (u32)it;
        int press = (flags & F_PRESS) && !(flags & F_RELEASE);
        if (code == K_YES || code == K_NO || (code >= K_UP && code <= K_RIGHT)) {
            if (press && code < 32)
                eaten |= 1u << code;
            it[0] = IT_DROP;
            if (!press)
                return (u32)it;
            int slot, f = smp_fb_item(smp_fb_cur, &slot);
            int t = (int)UI_TRACK_NOW;
            int on_folder = slot < 0 && f != -1;
            if (smp_fb_menu == 2) {             /* DELETE asked */
                if (code == K_YES && (slot >= 0 || on_folder))
                    smp_fb_delete(slot, f);     /* v0.29: the marked ones, or this one, or the folder's */
                smp_fb_menu = 0;
            } else if (smp_fb_menu == 1) {      /* SAMPLE ACTION */
                int act = on_folder ? (smp_fb_mcur == 0 ? 3 : 2) : smp_fb_mcur;
                if (code == K_UP && smp_fb_mcur > 0)
                    smp_fb_mcur--;
                else if (code == K_DOWN && smp_fb_mcur < smp_fb_nactions(on_folder) - 1)
                    smp_fb_mcur++;
                else if (code == K_NO || code == K_LEFT)
                    smp_fb_menu = 0;
                else if (code == K_YES && act == 3) {      /* v0.29: SELECT ALL (or CLEAR ALL) */
                    smp_fb_menu = 0;
                    smp_fb_mark_folder(on_folder ? f : smp_fb_folder);
                } else if (code == K_YES && act == 2 && (slot >= 0 || on_folder)) {
                    smp_fb_menu = 2;            /* DELETE: asked first */
                } else if (code == K_YES && slot >= 0) {
                    smp_fb_menu = 0;
                    if (smp_fb_mcur == 0) {     /* LOAD TO TRK */
                        smp_set_samp(t, slot + 1);
                        smp_fb_open = 0;
                        smp_list_settle(slot + 1);
                    } else if (smp_fb_mcur == 1) {   /* RENAME: the NAME screen, alone */
                        smp_fb_open = 0;
                        smp_list_close();
                        rename_start(slot);
                    }
                }
            } else if (code == K_UP || code == K_DOWN) {
                lst_step(code);
                lrpt_code = code;               /* v0.30: held, it goes on */
                lrpt_next = *(volatile u32 *)0x4058E8D4u + RPT_WAIT;
            }
            else if (code == K_YES && smp_func_held && slot >= 0)
                smp_fb_mark(slot, !smp_fb_marked(slot));    /* v0.29: FUNC + YES marks */
            else if (code == K_YES && smp_func_held && on_folder)
                smp_fb_mark_folder(f);
            else if (code == K_RIGHT && (slot >= 0 || on_folder)) {
                smp_fb_menu = 1;                /* v0.29: on a folder too (SELECT ALL, DELETE) */
                smp_fb_mcur = 0;
            } else if (code == K_YES && on_folder) {
                smp_fb_folder = f;              /* into the folder */
                smp_fb_cur = 0;
            } else if (code == K_YES && slot >= 0) {   /* the DT2's quick assign */
                smp_set_samp(t, slot + 1);
                smp_fb_open = 0;
                smp_list_settle(slot + 1);
            } else if (code == K_LEFT) {        /* up a folder; at the top it stays (v0.26) */
                if (smp_fb_folder != -1) {
                    int back = smp_fb_folder;
                    smp_fb_folder = -1;
                    smp_fb_cur = smp_fb_index_of(back);
                }
            } else if (code == K_NO) {          /* v0.26: NO closes it from anywhere, and the */
                smp_fb_open = 0;                /* list under it (SAMP stays as it is) */
                smp_fb_unmark_all();
                smp_fb_folder = -1;
                smp_list_close();
            }
            return (u32)it;
        }
        if (press && closes(code)) {
            smp_fb_open = 0;
            smp_fb_menu = 0;
            smp_fb_unmark_all();
            smp_list_close();
        }
        return (u32)it;
    }
    /* the sample list (smp_page.c): UP / DOWN a slot, YES keeps, NO puts SAMP back, FUNC +
     * YES the browser, SAMP's push keeps; a page key closes it as YES */
    if (it[0] == IT_KEY && smp_list_view && smp_list_up(smp_list_view)) {
        int press = (flags & F_PRESS) && !(flags & F_RELEASE);
        int t = (int)UI_TRACK_NOW;
        if (code == K_UP || code == K_DOWN || code == K_YES || code == K_NO) {
            if (press && code < 32)
                eaten |= 1u << code;
            it[0] = IT_DROP;
            if (!press)
                return (u32)it;
            smp_list_hold();
            if (code == K_UP || code == K_DOWN) {
                lst_step(code);
                lrpt_code = code;               /* v0.30: held, it goes on */
                lrpt_next = *(volatile u32 *)0x4058E8D4u + RPT_WAIT;
            } else if (code == K_YES && lst_func) {
                smp_fb_open = 1;
                smp_fb_unmark_all();
                smp_fb_folder = -1;
                smp_fb_cur = 0;
            } else if (code == K_YES) {
                smp_list_close();
            } else {                            /* NO: as it was */
                smp_set_samp(t, smp_lst_orig);
                smp_list_settle(smp_lst_orig);
            }
            return (u32)it;
        }
        if (press && code == K_ENC_A + 3)
            smp_list_close();
        else if (press && closes(code))
            smp_list_close();
    }
    return (u32)it;
}

/* v0.30: one UP/DOWN step in the folder browser (its items, or the action menu) or the
 * sample list (SAMP); a held arrow's repeat comes here too, and stops when neither is up */
static void lst_step(u32 code)
{
    if (smp_fb_open) {
        smp_overlay_dirty = 1;
        if (smp_fb_menu == 2)                   /* DELETE asked: nothing to move */
            return;
        if (smp_fb_menu == 1) {
            int ks, kf = smp_fb_item(smp_fb_cur, &ks), last = smp_fb_nactions(ks < 0 && kf != -1) - 1;
            if (code == K_UP && smp_fb_mcur > 0)
                smp_fb_mcur--;
            else if (code == K_DOWN && smp_fb_mcur < last)
                smp_fb_mcur++;
            return;
        }
        if (code == K_UP && smp_fb_cur > 0)
            smp_fb_cur--;
        else if (code == K_DOWN)
            smp_fb_cur++;                       /* (held at the last item when drawn) */
        return;
    }
    if (smp_list_view && smp_list_up(smp_list_view)) {
        int t = (int)UI_TRACK_NOW;
        smp_list_hold();
        int v = smp_samp_of(t) + (code == K_DOWN ? 1 : -1);
        if (v >= 0 && v <= 127)
            smp_set_samp(t, v);
        return;
    }
    lrpt_code = 0;                              /* neither up: the repeat ends */
}

/* the parameter page's key handler (its vtable slot at 0x401d49a8 points here): stock's,
 * as it was before v0.15 (the recorder's keys arrive through smp_ui_pop now) */
int smp_key(void *view, void *ev)
{
    return KEY_ORIG(view, ev);
}
