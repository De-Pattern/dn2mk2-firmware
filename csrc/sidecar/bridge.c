/* External-engine capture. No USB, allocation, logging or filesystem work in
 * the frame interrupt. Published queue cells are immutable until consumed.
 * ColdFire has one core: the producer interrupts the MIDI consumer, never vice
 * versa. Volatile aligned indices plus compiler barriers publish whole cells.
 */
#include "wr_gen.h"
#include "bridge.h"
#include "sound.h"
#include "ui.h"

#define D __attribute__((section(".data"), aligned(4)))
#define BARRIER() __asm__ volatile ("" ::: "memory")
#define NOTE(v) (1u + (v))
#define VELOCITY(v) (26u + (v))
#define LEVEL(v) (58u + (v))
#define MACHINE(v) (74u + (v))
#define SLOT(v, s) (84u + 73u * (v) + (s))
#define ON 17u
#define OFF 18u

static ScEvent queue[SC_QUEUE] D;
static ScEvent previous[SC_VOICES] D;
static sc_u8 valid[SC_VOICES] D;
/* Knob/smoothing snapshots are replaceable; note edges are not. Reuse the
 * capture cache as a per-voice mailbox, with a generation protecting a MIDI
 * task read interrupted by the frame producer. Published queue cells stay
 * immutable. Sequence numbers describe exported packets, not replaced states. */
static volatile sc_u32 state_gen[SC_VOICES] D, state_serial D;
static sc_u32 state_seen[SC_VOICES] D, state_cursor D;
static volatile sc_u32 state_done D;
static volatile sc_u32 head D, tail D, fault D, epoch D;
static volatile sc_u32 seen_epoch D;
static sc_u32 was_playing D;
static sc_u16 sequence D;
volatile sc_u32 sc_overflows D, sc_queued D, sc_exported D;
volatile sc_u32 sc_sent D, sc_retries D;
volatile sc_u32 sc_edit_mask D;
static volatile sc_u32 link_enabled D, midi_ready D, holding D;
static sc_u8 held_packet[SC_GENERIC_BYTES] D;
static volatile sc_u32 link_seen D, ack_pending D;
static sc_u32 link_token D, link_track D, link_returns D;
static sc_u8 native_owner[8] D; /* DSP voice + 1; zero means no owner */
static sc_u8 ack_packet[SC_PACKET_BYTES] D;
#define FRAMES (*(volatile sc_u32 *)0x4058E8D4u)
#define USB_UP (*(volatile sc_u32 *)0x446478D0u)
#define MIDI_EVENT ((volatile sc_u32 *)0x445EF3B8u)
#define EVENT_SIGNAL ((void (*)(volatile sc_u32 *))0x4000148Cu)
#define EVENT_WAIT ((void (*)(volatile sc_u32 *))0x4000141Au)
#define VSOUND(v) (*(const volatile sc_u8 *volatile *)(0x800052A8u + 4u * (v)))
/* Extra generic controls use existing SYN words. Their native UI record ranges
 * must be installed separately; this does not expose stock WaveTone ranges. */
static const sc_u8 extra_slots[5] = {25, 26, 27, 28, 29};

/* Events are four-byte aligned and sized. Alias-safe word loops avoid libc
 * while keeping copies in the 1500 Hz interrupt short. */
typedef sc_u32 event_word __attribute__((__may_alias__));
static void copy_event(ScEvent *dst, const ScEvent *src)
{
    event_word *d = (event_word *)dst;
    const event_word *s = (const event_word *)src;
    for (sc_u32 i = 0; i < sizeof *dst / 4; i++) d[i] = s[i];
}

static void clear_event(ScEvent *event)
{
    event_word *d = (event_word *)event;
    for (sc_u32 i = 0; i < sizeof *event / 4; i++) d[i] = 0;
}

static int push(ScEvent *e)
{
    sc_u32 h = head;
    if (h - tail >= SC_QUEUE) {
        sc_overflows++;
        BARRIER();
        fault = 1;
        return 0;
    }
    copy_event(&queue[h % SC_QUEUE], e);
    BARRIER();
    head = h + 1;
    sc_queued++;
    return 1;
}

static void remember(sc_u32 v, const ScEvent *e)
{
    state_gen[v]++;
    BARRIER();
    copy_event(&previous[v], e);
    valid[v] = 1;
    BARRIER();
    state_gen[v]++;
    state_serial++;
}

static int native_part(sc_u32 track)
{
    if (link_track == 16u) return track < 8u ? (int)track : -1;
    return track == link_track ? 0 : -1;
}

static void suppress(volatile sc_u16 *f)
{
    /* Type 21 maps to silent custom slot 5 in the matching DSP image. The raw
     * frame carries the routing word; source controls were captured above.
     * Never write this descriptor to the saved sound or modulated UI state. */
    for (sc_u32 v = 0; v < SC_VOICES; v++) {
        if (f[MACHINE(v)] != SC_TYPE)
            continue;
        int part = valid[v] ? native_part(previous[v].track) : -1;
        int native = !!link_returns; /* retain dry-lane interpretation on fault/expiry */
        int owned = native && link_enabled && !fault && part >= 0 && native_owner[part] == v + 1;
        f[SLOT(v, 25)] = SC_FRAME_TAG | (native ? SC_FRAME_NATIVE : 0) |
                         (owned ? (sc_u16)part : SC_FRAME_IDLE);
        if (owned) continue; /* native filter, AMP, pan and sends stay intact */
        f[ON] &= (sc_u16)~(1u << v);
        f[OFF] |= (sc_u16)(1u << v);
        f[LEVEL(v)] = 0;
        for (sc_u32 s = 86; s <= 88; s++)
            f[SLOT(v, s)] = 0;
    }
    /* The event is initialized by the MIDI task before its first wait. A
     * pending signal is sufficient; don't accumulate signals while it is busy. */
    if (midi_ready && link_enabled &&
        (fault || head != tail || state_serial != state_done || holding || ack_pending || FRAMES - link_seen >= SC_LEASE_FRAMES) &&
        !MIDI_EVENT[0])
        EVENT_SIGNAL(MIDI_EVENT);
}

void sc_capture(volatile sc_u16 *f, const volatile sc_u32 *tracks,
                sc_u32 tick, sc_u32 playing)
{
    if (fault) {
        suppress(f);
        return;
    }
    if (seen_epoch != epoch) {
        for (sc_u32 v = 0; v < SC_VOICES; v++) valid[v] = 0;
        for (sc_u32 p = 0; p < 8; p++) native_owner[p] = 0;
        seen_epoch = epoch;
    }
    if (was_playing && !playing) {
        ScEvent e;
        clear_event(&e);
        e.tick = tick;
        e.flags = SC_RESET;
        if (!push(&e)) { suppress(f); return; }
        for (sc_u32 v = 0; v < SC_VOICES; v++) valid[v] = 0;
        for (sc_u32 p = 0; p < 8; p++) native_owner[p] = 0;
    }
    was_playing = playing;
    for (sc_u32 v = 0; v < SC_VOICES; v++) {
        ScEvent e;
        if (tracks[v] < 16u && (sc_edit_mask & (1u << tracks[v]))) continue;
        int external = f[MACHINE(v)] == SC_TYPE && tracks[v] < 16u &&
            (!link_enabled || tracks[v] == link_track || (link_track == 16u && tracks[v] < 8u));
        int part = native_part(tracks[v]);
        /* A stable obsolete allocation has no effect on the Pi until a note
         * edge reacquires it. Defer its identity and smoothed controls together.
         * Machine/track retirement and every ON/OFF still take the full path. */
        if (external && link_enabled && valid[v] && previous[v].track == tracks[v] &&
            part >= 0 && native_owner[part] && native_owner[part] != v + 1 &&
            !((f[ON] | f[OFF]) & (1u << v))) continue;
        int generic = external ? sc_sound_capture_identity(v, VSOUND(v), e.engine) : -1;
        external = external && generic >= 0;
        int same_engine = 1;
        for (sc_u32 i = 0; external && i < 32; i++)
            if (e.engine[i] != previous[v].engine[i]) same_engine = 0;
        if (valid[v] && (!external || previous[v].track != tracks[v] || !same_engine)) {
            int part = native_part(previous[v].track);
            if (part >= 0 && native_owner[part] == v + 1) native_owner[part] = 0;
            ScEvent old;
            copy_event(&old, &previous[v]);
            old.tick = tick;
            old.flags = SC_KILL;
            if (!push(&old)) break;
            valid[v] = 0;
        }
        if (!external) continue;
        e.sequence = 0; /* every other event field is assigned below/by identity */
        e.reserved = (sc_u8)generic;
        e.tick = tick;
        e.voice = (sc_u8)v;
        e.track = (sc_u8)tracks[v];
        e.flags = SC_STATE;
        if (f[ON] & (1u << v)) e.flags |= SC_ON;
        if (f[OFF] & (1u << v)) e.flags |= SC_OFF;
        e.note = f[NOTE(v)];
        e.velocity = f[VELOCITY(v)];
        e.level = f[LEVEL(v)];
        if (!e.level) e.flags |= SC_KILL;
        if (part >= 0) {
            if ((e.flags & SC_ON) || !native_owner[part]) native_owner[part] = (sc_u8)(v + 1);
            if ((e.flags & SC_KILL) && native_owner[part] == v + 1) native_owner[part] = 0;
        }
        int changed = !valid[v] || e.note != previous[v].note
            || e.velocity != previous[v].velocity || e.level != previous[v].level
            || e.reserved != previous[v].reserved;
        for (sc_u32 p = 0; p < 16; p++) {
            e.params[p] = p < 11u ? f[SLOT(v, sc_slots[p])] :
                generic ? f[SLOT(v, extra_slots[p - 11u])] : 0;
            if (e.params[p] != previous[v].params[p]) changed = 1;
        }
        if (changed || (e.flags & (SC_ON | SC_OFF))) {
            if (e.flags != SC_STATE && !push(&e)) break;
            remember(v, &e);
        }
    }
    suppress(f);
}

int sc_pop(ScEvent *e)
{
    if (fault) {
        /* Producer freezes while fault is set. Discard the damaged timeline,
         * request fresh snapshots and deliver a hard silence before restarting. */
        tail = head;
        epoch++;
        clear_event(e);
        e->flags = SC_RESET;
        e->sequence = sequence++;
        BARRIER();
        fault = 0;
        return 1;
    }
    sc_u32 t = tail;
    if (t != head) {
        BARRIER();
        copy_event(e, &queue[t % SC_QUEUE]);
        BARRIER();
        tail = t + 1;
    } else {
        if (seen_epoch != epoch) return 0;
        sc_u32 serial = state_serial;
        for (sc_u32 i = 0; i < SC_VOICES; i++) {
            sc_u32 v = (state_cursor + i) & (SC_VOICES - 1);
            sc_u32 gen = state_gen[v];
            if (!valid[v] || (gen & 1u) || gen == state_seen[v]) continue;
            /* Native synth edits also smooth every old allocated voice. The Pi
             * accepts STATE only from the current monophonic owner; exporting
             * stale allocations wastes USB critical sections and UI time.
             * Only discard mailboxes: queued ON/OFF/KILL edges stay ordered. */
            int part = native_part(previous[v].track);
            if (link_enabled && part >= 0 && native_owner[part] != v + 1) {
                state_seen[v] = gen;
                continue;
            }
            BARRIER();
            copy_event(e, &previous[v]);
            BARRIER();
            if (gen != state_gen[v] || !valid[v]) continue;
            /* A note captured during this scan goes first, with its own full
             * parameter snapshot. Do not emit a later state ahead of it. */
            if (head != tail || seen_epoch != epoch) return 0;
            state_seen[v] = gen;
            if (e->flags != SC_STATE) continue;
            state_cursor = (v + 1) & (SC_VOICES - 1);
            goto exported;
        }
        state_done = serial;
        return 0;
    }
exported:
    e->sequence = sequence++;
    sc_exported++;
    return 1;
}

void sc_set_link(sc_u32 enabled)
{
    /* Called only by the MIDI task after handshake (or to disconnect). */
    sc_u16 sr;
    __asm__ volatile ("move.w %%sr,%0\n\tmove.w #0x2700,%%sr" : "=d" (sr) :: "memory");
    link_enabled = !!enabled;
    head = tail = holding = sequence = ack_pending = 0;
    link_seen = FRAMES;
    fault = !!enabled; /* first delivered event is RESET, then fresh snapshots */
    epoch++;
    __asm__ volatile ("move.w %0,%%sr" :: "d" (sr) : "memory");
    sc_ui_session(enabled ? link_token : 0);
    sc_catalog_session(enabled ? link_token : 0);
    sc_load_session(enabled ? link_token : 0);
}

int sc_rx(const sc_u8 *p, sc_u32 bytes, sc_u32 source)
{
    if ((source == 2 || source == 4) && link_enabled && FRAMES - link_seen < SC_LEASE_FRAMES &&
        p && bytes >= 6 && (p[4] == 2 || p[4] == 3) && p[5] == 4)
        return bytes >= 17 && p[14] == 2 ? sc_catalog_receive(p, bytes, FRAMES) :
               bytes >= 17 && p[14] == 3 ? sc_load_receive(p, bytes, FRAMES) : sc_ui_receive(p, bytes, FRAMES);
    /* Keep this separate from the sampler protocol. Reserved bytes are zero,
     * the nonce is nonzero and every interior byte is MIDI-safe. USB only. */
    if ((source != 2 && source != 4) || bytes != SC_PACKET_BYTES || !p ||
        p[0] != 0xF0 || p[1] != 0x7D || p[2] != 0x44 || p[3] != 0x32 ||
        p[4] != 1 || p[5] != 2 || p[49] != 0xF7 || p[11] > 16 || p[12] != 1 || p[13] > 1)
        return 0;
    for (sc_u32 i = 6; i < 49; i++)
        if ((p[i] & 0x80u) || (i >= 14 && p[i])) return 0;
    sc_u32 token = ((sc_u32)p[7] << 21) | ((sc_u32)p[8] << 14) |
                   ((sc_u32)p[9] << 7) | p[10];
    if (!token) return 0;
    sc_u32 now = FRAMES;
    int same = link_enabled && now - link_seen < SC_LEASE_FRAMES &&
               token == link_token && p[11] == link_track && p[13] == link_returns;
    if (p[6] == 0) { /* HELLO: a fresh session discards the old timeline. */
        if (!same) {
            link_track = p[11]; link_token = token; link_returns = p[13];
            sc_set_link(1);
        }
    } else if ((p[6] == 2 || p[6] == 3) && same) {
        if (p[6] == 3) { sc_set_link(0); return 1; }
    } else return 0;
    link_seen = now;
    for (sc_u32 i = 0; i < SC_PACKET_BYTES; i++) ack_packet[i] = p[i];
    ack_packet[6] = 1; /* ACK must be published before this session's events. */
    ack_pending = 1;
    return 1;
}

void sc_midi_wait(volatile sc_u32 *event)
{
    midi_ready = 1;
    EVENT_WAIT(event);
}
void sc_ui_wake(void)
{
    if (link_enabled && midi_ready && !MIDI_EVENT[0]) EVENT_SIGNAL(MIDI_EVENT);
}

void sc_midi_poll(void)
{
    if (!link_enabled) return;
    if (!USB_UP || FRAMES - link_seen >= SC_LEASE_FRAMES) {
        sc_set_link(0);
        return;
    }
    if (ack_pending) {
        if (!sc_usb_try(ack_packet, SC_PACKET_BYTES)) { sc_retries++; return; }
        ack_pending = 0;
    }
    /* Runs once per MIDI queue pass, even with sustained incoming traffic.
     * Bound the work, retain an unsent packet, and leave USB pressure to retry
     * on the next wake. A new queue fault invalidates any held old event. */
    for (sc_u32 n = 0; n < 4; n++) {
        if (fault) holding = 0;
        if (!holding) {
            ScEvent event;
            if (!sc_pop(&event)) break;
            holding = sc_encode(&event, held_packet, sizeof held_packet);
            if (!holding) { fault = 1; break; }
        }
        if (!sc_usb_try(held_packet, holding)) { sc_retries++; break; }
        holding = 0;
        sc_sent++;
    }
    if (!holding && !fault) {
        sc_u8 request[52];
        sc_u32 bytes=sc_load_request(link_token,FRAMES,request);
        if(!bytes) bytes=sc_catalog_request(link_token,FRAMES,request);
        if(!bytes) bytes=sc_ui_request(link_token,FRAMES,request);
        if(bytes) sc_usb_try(request,bytes); /* metadata timeout retries; audio retains priority */
    }
}
