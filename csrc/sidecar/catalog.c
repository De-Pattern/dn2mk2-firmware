/* Compact installed-engine list. MIDI builds one revision; UI publishes it whole.
 * No engine loading or sound changes are caused by opening/browsing the catalog. */
#include "ui.h"
#include "sound.h"
#define D __attribute__((section(".data"), aligned(4)))
#define BARRIER() __asm__ volatile ("" ::: "memory")
static ScCatalog catalogs[2] D;
static volatile sc_u32 opened D, generation D, complete D, active D;
static sc_u32 session D, working D, index D, serial D, pending D, sent D, done D, refreshed D;
static void copy(sc_u8 *d, const sc_u8 *s, sc_u32 n) { while (n--) *d++ = *s++; }
static void zero(sc_u8 *d, sc_u32 n) { while (n--) *d++ = 0; }
static int equal(const sc_u8 *a, const sc_u8 *b, sc_u32 n)
{ while (n--) if (*a++ != *b++) return 0; return 1; }
static sc_u32 get7(const sc_u8 *p, sc_u32 n)
{ sc_u32 v = 0; while (n--) v = (v << 7) | *p++; return v; }
static void put7(sc_u8 *p, sc_u32 v, sc_u32 n)
{ while (n) { p[--n] = (sc_u8)(v & 127); v >>= 7; } }
static int text_ok(const sc_u8 *p, sc_u32 n)
{
    int end = 0;
    while (n--) { sc_u8 c = *p++; if (!c) end = 1; else if (end || c < 32 || c > 126) return 0; }
    return 1;
}
static sc_u16 lock(void)
{
    sc_u16 sr;
    __asm__ volatile ("move.w %%sr,%0\n\tmove.w #0x2700,%%sr" : "=d" (sr) :: "memory");
    return sr;
}
static void unlock(sc_u16 sr) { __asm__ volatile ("move.w %0,%%sr" :: "d" (sr) : "memory"); }
void sc_catalog_open(sc_u32 on)
{
    sc_u16 sr = lock();
    opened = !!on; generation++; complete = 0;
    unlock(sr);
}
int sc_catalog_publish(void)
{
    if (!complete) return 0;
    sc_u16 sr = lock();
    int yes = opened && session && complete && working == generation;
    if (yes) { active ^= 1; BARRIER(); complete = 0; }
    unlock(sr);
    return yes;
}
const ScCatalog *sc_catalog_view(void)
{
    const ScCatalog *c = &catalogs[active];
    return session && c->token == session ? c : 0;
}
void sc_catalog_session(sc_u32 token)
{
    if (token > 0x0fffffffu) token = 0;
    if (session != token) { session = token; pending = complete = done = index = 0; }
}
sc_u32 sc_catalog_request(sc_u32 token, sc_u32 now, sc_u8 *p)
{
    if (!p || token > 0x0fffffffu) return 0;
    sc_catalog_session(token);
    if (working != generation) { working = generation; pending = complete = done = index = 0; }
    if (!session || !opened || complete) return 0;
    if (done) {
        if (now - refreshed < 1500) return 0;
        done = pending = index = 0;
    }
    if (pending && now - sent < 150) return 0;
    if (!pending) { serial = (serial + 1) & 0x0fffffffu; if (!serial) serial = 1; pending = 1; }
    zero(p, 50);
    p[0] = 0xf0; p[1] = 0x7d; p[2] = 0x44; p[3] = 0x32; p[4] = 2; p[5] = 3;
    put7(p + 6, session, 4); put7(p + 10, serial, 4);
    p[14] = 2; p[15] = (sc_u8)index; p[49] = 0xf7;
    if (working != generation || !opened) { pending = 0; return 0; }
    sent = now;
    return 50;
}
int sc_catalog_receive(const sc_u8 *p, sc_u32 n, sc_u32 now)
{
    if (!p || !opened || !pending || !session || working != generation || n != 71 ||
        p[0] != 0xf0 || p[1] != 0x7d || p[2] != 0x44 || p[3] != 0x32 ||
        p[4] != 2 || p[5] != 4 || p[70] != 0xf7 || p[17] > 15 ||
        get7(p + 6, 4) != session || get7(p + 10, 4) != serial ||
        p[14] != 2 || p[15] != index || p[16] || p[22] > 32 || p[23] > 6) return 0;
    for (sc_u32 i = 6; i < 70; i++) if (p[i] & 128) return 0;
    sc_u32 count = p[22];
    if (index < count) {
        if (!sc_id_ok(p + 24) || !text_ok(p + 56, 10) || !text_ok(p + 66, 4)) return 0;
    } else {
        /* Empty catalog is a valid atomic publication. A shrinking mid-scan list
         * returns an empty out-of-range entry; its new revision restarts below. */
        for (sc_u32 i = 23; i < 70; i++) if (p[i]) return 0;
    }
    ScCatalog *c = &catalogs[active ^ 1];
    sc_u32 revision = get7(p + 17, 5);
    if (index && (revision != c->revision || count != c->count)) {
        pending = done = index = 0; return 1;
    }
    if (index && index >= count) return 0;
    for (sc_u32 i = 0; i < index; i++) if (equal(c->entry[i].id, p + 24, 32)) return 0;
    pending = 0;
    if (!index) {
        const ScCatalog *old = sc_catalog_view();
        if (old && old->revision == revision && old->count == count) {
            done = 1; refreshed = now; return 1;
        }
        zero((sc_u8 *)c, sizeof *c); c->revision = revision; c->token = session; c->count = (sc_u8)count;
    }
    if (count) {
        ScCatalogEntry *e = &c->entry[index];
        copy(e->id, p + 24, 32); copy((sc_u8 *)e->name, p + 56, 10);
        copy((sc_u8 *)e->short_name, p + 66, 4); e->state = p[23];
    }
    if (++index >= count) { done = 1; refreshed = now; BARRIER(); complete = 1; }
    return 1;
}
