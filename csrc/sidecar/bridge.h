#ifndef SIDECAR_BRIDGE_H
#define SIDECAR_BRIDGE_H

typedef unsigned int sc_u32;
typedef unsigned short sc_u16;
typedef unsigned char sc_u8;

enum { SC_STATE = 1, SC_ON = 2, SC_OFF = 4, SC_KILL = 8, SC_RESET = 16 };
enum { SC_QUEUE = 32, SC_VOICES = 16 };

/* In-memory record only. The USB codec must serialize fields explicitly. */
typedef struct {
    sc_u32 tick;
    sc_u16 sequence, note, velocity, level;
    sc_u16 params[16];
    sc_u8 voice, track, flags, reserved;
    sc_u8 engine[32]; /* full stable ID; reserved=1 for saved generic sounds */
} ScEvent;

/* Single producer: the completed native frame interrupt. */
void sc_capture(volatile sc_u16 *frame, const volatile sc_u32 *tracks,
                sc_u32 tick, sc_u32 playing);
/* Single consumer: MIDI task. 0 empty; 1 an event (including overflow RESET). */
int sc_pop(ScEvent *event);
/* Legacy v1 or generic v2. Capacity/validation failure writes nothing. */
enum { SC_PACKET_BYTES = 50, SC_GENERIC_BYTES = 98 };
enum { SC_LEASE_FRAMES = 3000 }; /* two seconds at the stock 1500 Hz frame rate */
int sc_id_ok(const sc_u8 *id); /* canonical full ID, 32 bytes, NUL padded */
sc_u32 sc_encode(const ScEvent *event, sc_u8 *packet, sc_u32 capacity);
/* MIDI task only. Complete 50/98-byte packet, 1 submitted / 0 retry; never waits
 * for a mutex, ring space or a free descriptor. Not called from capture. */
int sc_usb_try(const sc_u8 *packet, sc_u32 bytes);
void sc_set_link(sc_u32 enabled);
/* Versioned USB session request; no USB send here. Returns 1 only if accepted. */
int sc_rx(const sc_u8 *packet, sc_u32 bytes, sc_u32 source);
void sc_midi_wait(volatile sc_u32 *event);
void sc_midi_poll(void);

extern volatile sc_u32 sc_overflows, sc_queued, sc_exported;
extern volatile sc_u32 sc_sent, sc_retries;
/* UI sound-selection transaction; only its track pauses export. */
extern volatile sc_u32 sc_edit_mask;
#endif
