/* Telemetry, the implementation. See tlm.h for what this is for.
 *
 * **The transmit seam is deliberately one function.** `tlm_send3` is the only
 * place that knows how a byte leaves the instrument, so locating the firmware's
 * MIDI transmit routine changes this file and nothing else. Everything above it
 * -- masking, splitting, rate limiting -- is testable without it.
 *
 * **Resolved 2026-09-24.** `MidiOutputStream`'s vtable sits at `0x40207c98`;
 * its `put(byte)` appends to a buffer at `this+20` and tail-calls `flush`, and
 * `flush` calls `0x401233f2(buffer, count, port, flags)`. The three callers
 * outside the class push `port` and `flags` as constants, so this needs no
 * stream instance and no object at all -- three bytes on our own stack and one
 * call.
 *
 * **Untested on hardware.** It faults or it does not; nothing here has sent a
 * byte to a real instrument yet.
 */
#include "tlm.h"

#include "dn2_111.h"

/* `tx(buffer, count, port, flags)` -- see DN2_MIDI_TX in dn2_111.h. */
typedef int (*midi_tx_fn)(const u8 *buf, u32 count, u32 port, u32 flags);

#define TLM_SLOTS 4
static u16 counter[TLM_SLOTS];

int tlm_available(void)
{
    return DN2_MIDI_TX != 0;
}

static void tlm_send3(u8 status, u8 d1, u8 d2)
{
    u8 msg[3];

    msg[0] = status;
    msg[1] = d1;
    msg[2] = d2;
    ((midi_tx_fn)DN2_MIDI_TX)(msg, 3u, DN2_MIDI_PORT, DN2_MIDI_FLAGS);
}

void tlm_cc(u8 cc, u8 value)
{
    tlm_send3((u8)(0xB0u | ((TLM_CHANNEL - 1) & 0x0Fu)),
              (u8)(cc & 0x7Fu), (u8)(value & 0x7Fu));
}

void tlm_cc14(u8 cc_lo, u8 cc_hi, u16 value)
{
    tlm_cc(cc_lo, (u8)(value & 0x7Fu));
    tlm_cc(cc_hi, (u8)((value >> 7) & 0x7Fu));
}

int tlm_every(u8 slot, u16 n)
{
    if (slot >= TLM_SLOTS || n == 0)
        return 0;
    if (++counter[slot] < n)
        return 0;
    counter[slot] = 0;
    return 1;
}
