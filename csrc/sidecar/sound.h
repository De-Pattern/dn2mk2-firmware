#ifndef SIDECAR_SOUND_H
#define SIDECAR_SOUND_H
#include "bridge.h"
/* Saved in existing SYN words, never in the modulated control frame. All
 * access is bytewise: adjacent native sounds have an odd 1163-byte stride.
 * Read returns 1 generic, 0 legacy Perkons, -1 invalid/missing sound. On failure
 * the destination is unchanged. Store validates first and publishes atomically.
 * Caller supplies a complete zero-padded 32-byte manifest ID, not a slot index. */
int sc_sound_identity(const volatile sc_u8 *sound, sc_u8 *id);
/* Capture interrupt only. Compare all saved identity words each frame; repeat
 * CRC/alphabet validation only after those words change. No UI/cache sharing. */
int sc_sound_capture_identity(sc_u32 voice, const volatile sc_u8 *sound, sc_u8 *id);
int sc_sound_store(volatile sc_u8 *sound, const sc_u8 *id);
#endif
