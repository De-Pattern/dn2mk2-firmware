/* Explicit picker load request. Loading a package never changes the DN2 sound;
 * the picker commits after READY, or explicitly swaps at full capacity, with
 * complete matching metadata in either case. */
#include "ui.h"
#include "sound.h"
#define D __attribute__((section(".data"), aligned(4)))
static sc_u8 wanted[32] D;
static volatile sc_u32 enabled D, generation D;
static sc_u32 track D, session D, working D, serial D, pending D, attempted D, sent D;
static int state D = -2;
static sc_u32 get7(const sc_u8 *p, sc_u32 n)
{ sc_u32 v = 0; while (n--) v = (v << 7) | *p++; return v; }
static void put7(sc_u8 *p, sc_u32 v, sc_u32 n)
{ while (n) { p[--n] = (sc_u8)(v & 127); v >>= 7; } }
int sc_load_start(sc_u32 part, const sc_u8 *id)
{
    if (part >= 16 || !sc_id_ok(id)) return 0;
    sc_u16 sr;
    __asm__ volatile ("move.w %%sr,%0\n\tmove.w #0x2700,%%sr" : "=d" (sr) :: "memory");
    for (sc_u32 i = 0; i < 32; i++) wanted[i] = id[i];
    track = part; generation++; state = -2; enabled = 1;
    __asm__ volatile ("move.w %0,%%sr" :: "d" (sr) : "memory");
    return 1;
}
void sc_load_cancel(void) { enabled = 0; }
int sc_load_state(void) { return !enabled ? -1 : !session || working != generation ? -2 : state; }
void sc_load_session(sc_u32 token)
{
    if (token > 0x0fffffffu) token = 0;
    if (session != token) { session = token; pending = attempted = 0; state = -2; }
}
sc_u32 sc_load_request(sc_u32 token, sc_u32 now, sc_u8 *p)
{
    if (!p || token > 0x0fffffffu) return 0;
    sc_load_session(token);
    if (working != generation) { working = generation; pending = attempted = 0; state = -2; }
    if (!session || !enabled || (state >= 0 && state != 2) || (attempted && now - sent < 150)) return 0;
    if (!pending) { serial = (serial + 1) & 0x0fffffffu; if (!serial) serial = 1; pending = 1; }
    p[0] = 0xf0; p[1] = 0x7d; p[2] = 0x44; p[3] = 0x32; p[4] = 2; p[5] = 3;
    put7(p + 6, session, 4); put7(p + 10, serial, 4);
    p[14] = 3; p[15] = (sc_u8)track; p[16] = 0;
    for (sc_u32 i = 0; i < 32; i++) p[17 + i] = wanted[i];
    p[49] = 0xf7;
    if (!enabled || working != generation) { pending = 0; return 0; }
    attempted = 1; sent = now;
    return 50;
}
int sc_load_receive(const sc_u8 *p, sc_u32 n, sc_u32 now)
{
    if (!p || !enabled || !pending || !session || working != generation || n != 24 ||
        p[0] != 0xf0 || p[1] != 0x7d || p[2] != 0x44 || p[3] != 0x32 ||
        p[4] != 2 || p[5] != 4 || p[23] != 0xf7 ||
        get7(p + 6, 4) != session || get7(p + 10, 4) != serial ||
        p[14] != 3 || p[15] != track || p[16] || p[22] > 6) return 0;
    for (sc_u32 i = 6; i < 23; i++) if ((p[i] & 128) || (i >= 17 && i <= 21 && p[i])) return 0;
    state = p[22]; pending = 0; sent = now;
    return 1;
}
