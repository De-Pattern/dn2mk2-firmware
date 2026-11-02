/* DIRECT JUMP (docs/jump.md): a pattern cued with PTN + TRIG while the sequencer plays starts
 * at once, from where the playing pattern was (Elektron's rule), instead of at the end of
 * the playing pattern. Off unless the user turns it on: hold PTN and press YES (on) or NO (off);
 * the screen says DIRECT JUMP ON / OFF. The setting is the instrument's, kept in the mod's
 * own settings sector on the +Drive (SET_SECTOR, in our region), not in a project.
 *
 * Stock 1.11's sequencer tick (the timer ISR 0x400d987a) already does everything a pattern
 * change needs; this only moves WHEN it arms and WHERE the new pattern starts:
 *
 *   the cue (0x400fa1da, the PTN view's single-pattern cue, jsr 0x400d93f0)
 *       -> jmp_cue: stock's cue, then jmp_cued() arms if the setting is on and it plays
 *   the tick's "tick 2 of the step" test (0x400da406, moveb 0x42c5a91e,%d1)
 *       -> jmp_tick: armed, on any tick that is not a step boundary, takes the tick-2 path
 *   that path's change-length test (0x400da45a, mvsw 0x42c5aab4,%d1)
 *       -> jmp_arm: armed and the queue's head is another pattern: straight to stock's
 *          arming (0x400da4d2), skipping the "is this the last step" test
 *   the switch, at the next step boundary (0x400da6e6, lea 0x42c5a9c4,%a1)
 *       -> jmp_switch: for our jump, the start step (0x42c5a9c4) from jmp_position(), and
 *          stock's per-track position code reads the new pattern (a5)
 *   that code's end (0x400da8cc, pea 0x401f6b25)
 *       -> jmp_tracks: each track goes on from its own step, wrapped by its new length
 *
 * Chains, songs and MIDI program changes cue through other callers of 0x400d93f0 and never
 * arm, so they keep stock's behaviour; with the setting off nothing here changes what stock
 * does. Everything here is RAM in .data (the chunk has no BSS) and one 512-byte sector. */

typedef unsigned int u32;
typedef unsigned short u16;
typedef short s16;
typedef unsigned char u8;
typedef signed char s8;

#if !defined(POOL_BYTES)
#error "the sampler's constants are passed by the build (dnfw.waverider.cpage)"
#endif

/* -- stock 1.11 ----------------------------------------------------------------------- */
#define PTN_VIEW_KEY ((int (*)(void *, void *))0x400FA6BEu)   /* the PTN view's key handler */
#define KEY_HELD ((int (*)(u32))0x4011F7E4u)                  /* (code) -> 1 while held */
#define EV_PRESSED ((int (*)(void *))0x401160BCu)              /* a fresh press, not a repeat */
#define EV_FUNC ((int (*)(void *))0x401160ACu)                 /* FUNC held with it */
#define STR_NEW ((void (*)(void *, const char *, void *))0x401CE69Eu)   /* std::string(s, alloc) */
#define STR_FREE ((void (*)(void *))0x401CCBEEu)
#define SAY ((void (*)(void *, void *))0x4005628Cu)            /* the PTN screen's message line */
#define K_YES 10u
#define K_NO 12u
#define K_FUNC 17u
#define K_PTN 23u

#define SEQ_PLAYING (*(volatile u32 *)0x42C5A918u)             /* 1 while it plays */
#define SEQ_PATTERN (*(volatile u32 *)0x42C5A9A0u)             /* the playing pattern */
#define SEQ_PREVIOUS (*(volatile u32 *)0x42C5A9A8u)            /* the one before the switch */
#define TRACK_NEXT ((volatile u16 *)0x42C5A9EAu)               /* each track's start step at a switch */
#define TRACK_CUR ((volatile u8 *)0x42C5A984u)                 /* each track's step now playing */
#define SEQ_COUNTER (*(volatile u16 *)0x42C5A91Cu)             /* the master counter, advanced at the boundary */
#define PAT_LENGTH 122196                                      /* s16: the pattern's (master) length */
#define PAT_MODE 122201                                        /* u8: 0 per pattern, else per track */
#define TRK_STRIDE 1701                                        /* the pattern's tracks, from +0 */
#define TRK_LENGTH 1164                                        /* s16: a track's length */

/* -- the +Drive -------------------------------------------------------------------------- */
#define BLK_READ  ((int (*)(u32, u32, void *))0x4012C59Au)          /* (sector, bytes, buf) -> 0 ok */
#define BLK_WRITE ((int (*)(u32, u32, const void *))0x4012C780u)
#define BLK_READY (*(volatile u32 *)0x4461B68Cu)
#define BLK_SECTORS (*(volatile u32 *)0x4461B6B0u)
/* our region (link.c, lib.c): the stock store ends below 0x458000; the pool's image is
 * 0x600000 .. POOL_STORE_END; the library starts at 0x700000. The sector between them is
 * written by nothing else */
#define STOCK_STORE_END 0x458000u
#define POOL_STORE_END (0x600000u + 1u + POOL_BYTES / 512u)
#define LIB_SECTOR 0x700000u
#define SET_SECTOR 0x6FF000u
#define SET_MAGIC 0x444E3253u                                   /* 'DN2S': the mod's settings */
#define SET_VERSION 1u
#define SET_JUMP 1u                                             /* flags bit 0: DIRECT JUMP on */
_Static_assert(SET_SECTOR >= POOL_STORE_END && SET_SECTOR < LIB_SECTOR && SET_SECTOR >= STOCK_STORE_END,
               "the settings sector lies in our region, between the pool's image and the library");

/* the state, exported for the emulator check (scripts/emu_jump.py) */
u8 jmp_on __attribute__((section(".data"))) = 0;          /* the setting */
u8 jmp_armed __attribute__((section(".data"))) = 0;       /* a cue to take on the next tick */
u8 jmp_pending __attribute__((section(".data"))) = 0;     /* armed by us: the switch is ours */
u8 jmp_fix __attribute__((section(".data"))) = 0;         /* the tracks' steps to wrap */
u32 jmp_from __attribute__((section(".data"))) = 0;       /* the pattern playing when armed */
u32 jmp_to __attribute__((section(".data"))) = 0;         /* the pattern armed */
u32 jmp_count __attribute__((section(".data"))) = 0;      /* jumps made */
u32 jmp_last __attribute__((section(".data"))) = 0;       /* the last one's start step */
int jmp_loaded __attribute__((section(".data"))) = 0;     /* the sector read (or found absent) */
u8 jmp_dirty __attribute__((section(".data"))) = 0;       /* to be written */
u32 jmp_reads __attribute__((section(".data"))) = 0;      /* sectors read / written, for the check */
u32 jmp_writes __attribute__((section(".data"))) = 0;
static u32 sector[128] __attribute__((section(".data")));

static int set_ok(void)
{
    return BLK_READY && BLK_SECTORS > SET_SECTOR;
}

static u32 set_check(const u32 *s)
{
    return ~s[0] ^ s[1] ^ s[2];
}

/* from the UI loop (page.c's wr_poll), every pass: the setting read once the device is up,
 * then written whenever it changed */
void jmp_poll(void)
{
    if (!set_ok())
        return;
    if (!jmp_loaded) {
        jmp_loaded = 1;
        if (!jmp_dirty && BLK_READ(SET_SECTOR, 512u, sector) == 0) {
            jmp_reads++;
            if (sector[0] == SET_MAGIC && sector[1] == SET_VERSION && sector[3] == set_check(sector))
                jmp_on = (sector[2] & SET_JUMP) != 0;
        }
    }
    if (jmp_dirty) {
        jmp_dirty = 0;
        for (int k = 0; k < 128; k++)
            sector[k] = 0;
        sector[0] = SET_MAGIC;
        sector[1] = SET_VERSION;
        sector[2] = jmp_on ? SET_JUMP : 0;
        sector[3] = set_check(sector);
        if (BLK_WRITE(SET_SECTOR, 512u, sector) == 0)
            jmp_writes++;
    }
}

static void say(void *view, const char *text)
{
    static u32 s[4] __attribute__((section(".data")));     /* the string object (no memset here) */
    static u32 alloc __attribute__((section(".data")));
    s[0] = s[1] = s[2] = s[3] = 0;
    STR_NEW(s, text, &alloc);
    SAY(*(void **)((u8 *)view + 120), s);
    STR_FREE(s);
}

/* the PTN view's key handler (its vtable slot 0x402008cc points here): PTN held, a fresh
 * YES or NO without FUNC sets DIRECT JUMP on or off (stock: either closes the PTN view);
 * everything else is stock's */
int jmp_key(void *view, void *ev)
{
    u32 code = *(u32 *)((u8 *)ev + 12);
    if ((code == K_YES || code == K_NO) && EV_PRESSED(ev) && !EV_FUNC(ev)
        && KEY_HELD(K_PTN) && !KEY_HELD(K_FUNC)) {
        jmp_on = code == K_YES;
        jmp_dirty = 1;
        say(view, jmp_on ? "DIRECT JUMP ON" : "DIRECT JUMP OFF");
        return 1;
    }
    return PTN_VIEW_KEY(view, ev);
}

/* after stock's cue (jmp_cue in hooks.S): arm if the setting is on and the sequencer plays */
void jmp_cued(void)
{
    if (jmp_on && SEQ_PLAYING == 1) {
        jmp_armed = 1;
    } else {
        jmp_armed = 0;
        jmp_pending = 0;
    }
}

/* at the switch (jmp_switch): -> the new pattern's start step, or -1 when the switch is not
 * the one we armed (then stock's 0 stands). Elektron's DIRECT JUMP rule: the new pattern
 * goes on from where the playing one was. The switch is at a step boundary, after this
 * boundary's step of the playing pattern has been taken, so the step that starts is the one
 * after it: per pattern, the playing pattern's step (each track's, 0x42c5a984) + 1; per
 * track, its master counter (0x42c5a91c, already advanced: 0 after a wrap is its length).
 * Wrapped by the new pattern's length (stock: 1 or less is no wrap, INF). Each track's own
 * start comes after (jmp_wrap_tracks) */
int jmp_position(void)
{
    u32 p = SEQ_PATTERN;
    if (p != jmp_to || SEQ_PREVIOUS != jmp_from || !p || !jmp_from)
        return -1;
    const u8 *pat = (const u8 *)p, *old = (const u8 *)jmp_from;
    u32 next;
    if (old[PAT_MODE] == 0) {
        next = (u32)TRACK_CUR[0] + 1u;
    } else {
        next = SEQ_COUNTER;
        s16 olen = *(const s16 *)(old + PAT_LENGTH);
        if (next == 0 && olen > 1)
            next = (u32)olen;
    }
    s16 len = *(const s16 *)(pat + PAT_LENGTH);
    if (len > 1)
        next %= (u32)len;
    jmp_fix = 1;
    jmp_last = next;
    jmp_count++;
    return (int)next;
}

/* after stock's per-track positions (jmp_tracks): each track goes on from its own step in the
 * playing pattern, the step after it, wrapped by its length in the new one (the pattern's,
 * per pattern; the track's, per track) */
void jmp_wrap_tracks(void)
{
    const u8 *pat = (const u8 *)SEQ_PATTERN;
    if (!pat)
        return;
    int per_track = pat[PAT_MODE] != 0;
    for (int t = 0; t < 16; t++) {
        s16 len = per_track ? *(const s16 *)(pat + TRK_STRIDE * t + TRK_LENGTH)
                            : *(const s16 *)(pat + PAT_LENGTH);
        u32 next = (u32)(u8)(TRACK_CUR[t] + 1u);
        if (len >= 1)
            next %= (u32)(u16)len;
        TRACK_NEXT[t] = (u16)next;
    }
}
