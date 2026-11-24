#include "wr_gen.h"
#include "sound.h"

static sc_u16 word(const volatile sc_u8 *s, sc_u32 slot)
{
    s += 20 + 2 * slot;
    return ((sc_u16)s[0] << 8) | s[1];
}
static void put(volatile sc_u8 *s, sc_u32 slot, sc_u16 value)
{
    s += 20 + 2 * slot;
    s[0] = (sc_u8)(value >> 8); s[1] = (sc_u8)value;
}
static sc_u32 id_slot(sc_u32 i) { return i ? 49 + i : 31; }

/* CRC-15/CAN over schema then all 32 canonical ID bytes. The stored word stays
 * inside the converter's proven 15-bit domain. This is corruption detection,
 * not authentication or an alternative to the full persistent ID. */
static sc_u16 checksum(const sc_u8 *id)
{
    sc_u16 crc = 0;
    for (sc_u32 i = 0; i < 33; i++) {
        crc ^= (sc_u16)(i ? id[i - 1] : 1) << 7;
        for (sc_u32 bit = 0; bit < 8; bit++)
            crc = (sc_u16)(((crc << 1) ^ ((crc & 0x4000) ? 0x4599 : 0)) & 0x7fff);
    }
    return crc;
}

int sc_sound_identity(const volatile sc_u8 *s, sc_u8 *id)
{
    if (!s || !id || s[0xde] != SC_TYPE) return -1;
    sc_u16 a = word(s, 33), b = word(s, 34);
    sc_u8 tmp[32];
    if (a != 0x5343 && b != 0x4932) {
        static const sc_u8 legacy[32] = "mega.perkons";
        for (sc_u32 i = 0; i < 32; i++) id[i] = legacy[i];
        return 0;
    }
    if (a != 0x5343 || b != 0x4932 || word(s, 37) != 1) return -1;
    for (sc_u32 i = 0; i < 16; i++) {
        sc_u16 w = word(s, id_slot(i));
        tmp[2 * i] = (sc_u8)(w >> 8); tmp[2 * i + 1] = (sc_u8)w;
    }
    if (!sc_id_ok(tmp) || checksum(tmp) != word(s, 39)) return -1;
    for (sc_u32 i = 0; i < 32; i++) id[i] = tmp[i];
    return 1;
}

int sc_sound_capture_identity(sc_u32 voice, const volatile sc_u8 *s, sc_u8 *id)
{
    static struct {
        sc_u16 words[20];
        sc_u8 id[32], seen, valid;
    } cache[16] __attribute__((section(".data"), aligned(4)));
    if (voice >= 16 || !s || !id || s[0xde] != SC_TYPE) return -1;
    if (word(s, 33) != 0x5343 && word(s, 34) != 0x4932)
        return sc_sound_identity(s, id);
    static const sc_u8 slots[20] = {31, 50, 51, 52, 53, 54, 55, 56, 57, 58,
                                    59, 60, 61, 62, 63, 64, 33, 34, 37, 39};
    int changed = !cache[voice].seen;
    for (sc_u32 i = 0; i < 20; i++) {
        sc_u16 w = word(s, slots[i]);
        if (cache[voice].words[i] != w) changed = 1;
        cache[voice].words[i] = w;
    }
    if (changed) {
        cache[voice].valid = sc_sound_identity(s, cache[voice].id) == 1;
        cache[voice].seen = 1;
    }
    if (!cache[voice].valid) return -1;
    for (sc_u32 i = 0; i < 32; i++) id[i] = cache[voice].id[i];
    return 1;
}

int sc_sound_store(volatile sc_u8 *s, const sc_u8 *id)
{
    if (!s || s[0xde] != SC_TYPE || !sc_id_ok(id)) return 0;
    sc_u8 tmp[32];
    for (sc_u32 i = 0; i < 32; i++) tmp[i] = id[i];
    sc_u16 crc = checksum(tmp), sr;
    __asm__ volatile ("move.w %%sr,%0\n\tmove.w #0x2700,%%sr" : "=d" (sr) :: "memory");
    for (sc_u32 i = 0; i < 16; i++)
        put(s, id_slot(i), ((sc_u16)tmp[2 * i] << 8) | tmp[2 * i + 1]);
    put(s, 37, 1); put(s, 39, crc);
    put(s, 33, 0x5343); put(s, 34, 0x4932);
    __asm__ volatile ("move.w %0,%%sr" :: "d" (sr) : "memory");
    return 1;
}
