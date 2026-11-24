/* Portable Sidecar event codec. No stock OS addresses, generated headers,
 * hardware operations, engine code, allocation or C-structure serialization. */
#include "bridge.h"

int sc_id_ok(const sc_u8 *id)
{
    if (!id || !id[0] || id[0] == '.') return 0;
    int end = 0;
    for (sc_u32 i = 0; i < 32; i++) {
        sc_u8 c = id[i];
        if (!c) { end = 1; continue; }
        if (end || c < 0x21 || c > 0x7e || c == '/' || c == '\\' ||
            (i && c == '.' && id[i - 1] == '.')) return 0;
    }
    return end;
}

static void put16(sc_u8 *out, sc_u16 value)
{
    out[0] = (sc_u8)(value >> 8);
    out[1] = (sc_u8)value;
}

sc_u32 sc_encode(const ScEvent *e, sc_u8 *packet, sc_u32 capacity)
{
    if (!e || !packet || e->reserved > 1 || e->track >= 16 || e->voice >= 16 ||
        !e->flags || (e->flags & ~31u) ||
        ((e->flags & SC_RESET) && e->flags != SC_RESET) ||
        ((e->flags & (SC_ON | SC_OFF)) && !(e->flags & SC_STATE))) return 0;
    sc_u32 generic = e->reserved;
    if (capacity < (generic ? SC_GENERIC_BYTES : SC_PACKET_BYTES)) return 0;
    if (generic) {
        if (e->flags != SC_RESET && !sc_id_ok(e->engine)) return 0;
        if (e->flags == SC_RESET)
            for (sc_u32 i = 0; i < 32; i++) if (e->engine[i]) return 0;
    }
    sc_u8 raw[79];
    sc_u32 raw_bytes = generic ? 79 : 37;
    put16(raw, e->sequence);
    raw[2] = (sc_u8)(e->tick >> 24);
    raw[3] = (sc_u8)(e->tick >> 16);
    raw[4] = (sc_u8)(e->tick >> 8);
    raw[5] = (sc_u8)e->tick;
    raw[6] = e->track; raw[7] = e->voice; raw[8] = e->flags;
    put16(raw + 9, e->note);
    put16(raw + 11, e->velocity);
    put16(raw + 13, e->level);
    for (sc_u32 p = 0; p < (generic ? 16u : 11u); p++) put16(raw + 15 + 2 * p, e->params[p]);
    if (generic) for (sc_u32 i = 0; i < 32; i++) raw[47 + i] = e->engine[i];
    packet[0] = 0xF0; packet[1] = 0x7D; packet[2] = 0x44;
    packet[3] = 0x32; packet[4] = generic ? 2 : 1; packet[5] = 1;
    sc_u32 n = 6;
    for (sc_u32 i = 0; i < raw_bytes;) {
        sc_u32 mask = n++;
        packet[mask] = 0;
        for (sc_u32 bit = 0; bit < 7 && i < raw_bytes; bit++, i++) {
            packet[mask] |= (sc_u8)((raw[i] >> 7) << bit);
            packet[n++] = raw[i] & 0x7F;
        }
    }
    packet[n++] = 0xF7;
    return n;
}
