/* Telemetry, the implementation. See tlm.h for what this is for.
 *
 * **The transmit seam is deliberately one function.** `tlm_send3` is the only
 * place that knows how a byte leaves the instrument, so locating the firmware's
 * MIDI transmit routine changes this file and nothing else. Everything above it
 * -- masking, splitting, rate limiting -- is testable without it.
 *
 * **Not yet resolved.** `DN2_MIDI_TX` is unset: `MidiOutputStream` appears in
 * the image at 0x4023100e as a mangled-symbol fragment with no pointer to it,
 * so a string search does not reach the routine. The route in is a MIDI machine
 * sending a note, which is a live caller of exactly this path, read from the
 * sequencer side in Ghidra. Until then `tlm_available()` returns 0 and every
 * send is a no-op -- **silent, but honestly silent**, which is the distinction
 * that matters when a probe reports nothing.
 */
#include "tlm.h"

#ifdef DN2_MIDI_TX
extern void dn2_midi_tx(u8 status, u8 d1, u8 d2);
#endif

#define TLM_SLOTS 4
static u16 counter[TLM_SLOTS];

int tlm_available(void)
{
#ifdef DN2_MIDI_TX
    return 1;
#else
    return 0;
#endif
}

static void tlm_send3(u8 status, u8 d1, u8 d2)
{
#ifdef DN2_MIDI_TX
    dn2_midi_tx(status, d1, d2);
#else
    (void)status; (void)d1; (void)d2;
#endif
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
