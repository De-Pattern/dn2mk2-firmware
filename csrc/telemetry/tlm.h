/* Telemetry: get a number out of the running instrument, as MIDI.
 *
 * **One subject.** This sends values. It does not know what they mean, which
 * build asked for them, or what is being debugged. LFO4 is the first caller and
 * must not be the last -- nothing here may mention it.
 *
 * **Why it exists.** Six firmware builds were flashed on 2026-09-23 to read one
 * number each off the LFO4 page, and the page turned out to render only the
 * high byte of what a column returned, so every value -- all of them 0..15 --
 * displayed identically. The readings were void. A display column read by eye
 * is too narrow a channel for debugging a live audio engine; this is the wider
 * one, proposed by the owner.
 *
 * **The value range is 0..127.** MIDI data bytes are seven bits. A wider number
 * is the caller's problem: send it as two or three signals (see `mask_lo`,
 * `mask_mid`, `mask_hi` in the channel map) rather than truncating silently,
 * because a silently truncated value is exactly the failure this replaces.
 *
 * **Cost.** Every call reaches the MIDI transmit path, which runs in the audio
 * engine's timing. `tlm_every()` exists so a caller in a per-frame or per-sample
 * path can emit at a rate that does not perturb what it is measuring. A probe
 * that changes the thing it measures is worse than no probe.
 */
#ifndef TLM_H
#define TLM_H

#include "tlm_channels.h"

typedef unsigned char  u8;
typedef unsigned short u16;
typedef unsigned int   u32;

/* Send one control change on the telemetry channel. `value` is masked to 0..127
 * -- see the note above about why the caller should split wider values. */
void tlm_cc(u8 cc, u8 value);

/* Send `value` as two signals, low seven bits then the next seven. */
void tlm_cc14(u8 cc_lo, u8 cc_hi, u16 value);

/* -> 1 once every `n` calls for this `slot`, 0 otherwise. For rate-limiting a
 * probe in a hot path: `if (tlm_every(0, 256)) tlm_cc(TLM_CC_TRACK, t);` */
int tlm_every(u8 slot, u16 n);

/* Has the transmit path been resolved on this build? A build whose telemetry is
 * silent should be able to say whether it never sent or never could. */
int tlm_available(void);

#endif /* TLM_H */
