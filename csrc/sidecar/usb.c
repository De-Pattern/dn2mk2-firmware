/* Stock 1.11 USB admission. MIDI task only; no unbounded resource waits.
 * The stock writer is used ONLY with an empty ring and a prechecked inactive
 * free descriptor. Interrupts stay masked across admission and publication so
 * another producer cannot take that descriptor or change the ring meanwhile.
 * Stock endpoint submission includes a bounded 1000-attempt tripwire loop;
 * this critical section's worst hardware cost still requires measurement.
 */
#include "bridge.h"
#define WORD(a) (*(volatile sc_u32 *)(a))
#define TRY_LOCK ((int (*)(void *))0x40001680u)
#define UNLOCK ((void (*)(void *))0x400016D2u)
#define WRITER ((void (*)(sc_u32, const sc_u8 *))0x40004734u)
#define USB_LOCK ((void *)0x4664ADE4u)

int sc_usb_try(const sc_u8 *packet, sc_u32 bytes)
{
    sc_u16 sr;
    __asm__ volatile ("move.w %%sr,%0" : "=d" (sr));
    if ((sr & 0x0700u) || WORD(0x4664ACDCu) != 0x445E6764u || !packet)
        return 0; /* not ordinary MIDI-task context */
    if ((bytes != SC_PACKET_BYTES && bytes != SC_GENERIC_BYTES && bytes != 52) ||
        packet[0] != 0xF0 || packet[bytes - 1] != 0xF7)
        return 0;
    for (sc_u32 i = 1; i < bytes - 1; i++)
        if (packet[i] & 0x80u) return 0;
    if (!TRY_LOCK(USB_LOCK)) return 0;
    __asm__ volatile ("move.w #0x2700,%%sr" ::: "memory");
    int sent = 0;
    const sc_u32 descriptor = WORD(0x4058E364u);
    if (WORD(0x446478D0u) && WORD(0x4058E220u) == 1u && WORD(0xFC0B01C4u) &&
        !(WORD(0x4664AF0Cu) & (1u << 5)) &&
        WORD(0x4058E224u) == 0 && WORD(0x4058E210u) != 0xF0u &&
        descriptor && !(WORD(descriptor + 4u) & 0x80u)) {
        /* Zero outstanding bytes: no DMA owns any part of this ring. Start at
         * zero so this complete 68/72/132-byte USB MIDI transfer cannot wrap and ask
         * the allocator for a second descriptor. Keep the stock DMA buffer,
         * descriptor preparation, completion callback and byte accounting. */
        WORD(0x4058E228u) = 0;
        WRITER(bytes, packet);
        sent = WORD(0x4058E224u) == 4u * ((bytes + 2u) / 3u);
    }
    __asm__ volatile ("move.w %0,%%sr" :: "d" (sr) : "memory");
    UNLOCK(USB_LOCK);
    return sent;
}
