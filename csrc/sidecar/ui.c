/* Two buffers, one active descriptor. No per-engine native tables. The MIDI task
 * builds an entire revision before the UI swaps it in; audio capture is unrelated. */
#include "ui.h"
#include "sound.h"
#define D __attribute__((section(".data"), aligned(4)))
#define BARRIER() __asm__ volatile ("" ::: "memory")
static ScUiView views[2] D;
static sc_u8 wanted[32] D;
static volatile sc_u32 generation D, complete D, active D;
static sc_u32 working D, session D, serial D, pending D, sent D, refreshed D;
static sc_u32 op D, arg D, first D, done D;
static sc_u32 context D, selector D, view_context[2] D, view_selector[2] D;

static void copy(sc_u8 *d, const sc_u8 *s, sc_u32 n) { while (n--) *d++ = *s++; }
static void zero(sc_u8 *d, sc_u32 n) { while (n--) *d++ = 0; }
static int equal(const sc_u8 *a, const sc_u8 *b, sc_u32 n)
{ while (n--) if (*a++ != *b++) return 0; return 1; }
static sc_u32 get7(const sc_u8 *p, sc_u32 n)
{ sc_u32 v = 0; while (n--) v = (v << 7) | *p++; return v; }
static void put7(sc_u8 *p, sc_u32 v, sc_u32 n)
{ while (n) { p[--n] = (sc_u8)(v & 127); v >>= 7; } }
/* Printable, canonical NUL padding; full-width strings need no trailing NUL. */
static int text_ok(const sc_u8 *p, sc_u32 n)
{
    int end = 0;
    while (n--) {
        sc_u8 c = *p++;
        if (!c) end = 1;
        else if (end || c < 32 || c > 126) return 0;
    }
    return 1;
}
static sc_u16 lock(void)
{
    sc_u16 sr;
    __asm__ volatile ("move.w %%sr,%0\n\tmove.w #0x2700,%%sr" : "=d" (sr) :: "memory");
    return sr;
}
static void unlock(sc_u16 sr) { __asm__ volatile ("move.w %0,%%sr" :: "d" (sr) : "memory"); }

int sc_ui_want_context(const sc_u8 *id,sc_u32 track,sc_u32 value)
{
    sc_u32 ctx=track<8?track+1:0;
    if(value>127) return 0;
    /* wanted is written only by this UI task. Unchanged pages need no IRQ mask. */
    if ((id ? equal(wanted, id, 32) : !wanted[0]) && context==ctx && selector==value) return 0;
    if (id && !sc_id_ok(id)) return 0;
    sc_u16 sr = lock();
    int changed = (id ? !equal(wanted, id, 32) : wanted[0] != 0) || context!=ctx || selector!=value;
    if (changed) {
        if (id) copy(wanted, id, 32); else zero(wanted, 32);
        context=ctx;selector=value;
        generation++; complete = 0;
    }
    unlock(sr);
    return changed;
}
int sc_ui_want(const sc_u8 *id) {return sc_ui_want_context(id,16,0);}
int sc_ui_publish(void)
{
    if (!complete) return 0;
    sc_u16 sr = lock();
    int yes = complete && working == generation && session && wanted[0];
    if (yes) { active ^= 1; BARRIER(); complete = 0; }
    unlock(sr);
    return yes;
}
const ScUiView *sc_ui_view(void)
{
    const ScUiView *v = &views[active];
    return session && v->token == session && wanted[0] && equal(v->id, wanted, 32) &&
        view_context[active]==context && view_selector[active]==selector ? v : 0;
}
static void restart(void)
{
    pending = complete = done = op = arg = first = 0;
}
void sc_ui_session(sc_u32 token)
{
    if (token > 0x0fffffffu) token = 0;
    if (session != token) { session = token; restart(); }
}
sc_u32 sc_ui_request(sc_u32 token, sc_u32 now, sc_u8 *p)
{
    if (!p || token > 0x0fffffffu) return 0;
    sc_ui_session(token);
    if (working != generation) {
        working = generation; restart();
    }
    if (!session || !wanted[0] || complete) return 0;
    if (done) {
        if (now - refreshed < 1500) return 0;
        restart();
    }
    if (pending && now - sent < 150) return 0;
    if (!pending) {
        serial = (serial + 1) & 0x0fffffffu;
        if (!serial) serial = 1;
        pending = 1;
    }
    p[0] = 0xf0; p[1] = 0x7d; p[2] = 0x44; p[3] = 0x32; p[4] = context?3:2; p[5] = 3;
    put7(p + 6, session, 4); put7(p + 10, serial, 4);
    p[14] = (sc_u8)op; p[15] = (sc_u8)arg; p[16] = (sc_u8)first;
    if(context) {p[17]=(sc_u8)(context-1);p[18]=(sc_u8)selector;}
    copy(p + (context?19:17), wanted, 32); p[context?51:49] = 0xf7;
    if (working != generation) { restart(); return 0; }
    sent = now;
    return context?52:50;
}
static void next_names(ScUiView *v, sc_u32 now)
{
    while (arg < 16 && !v->knob[arg].count) arg++;
    if (arg == 16) {
        done = 1; refreshed = now; BARRIER(); complete = 1;
    }
}
int sc_ui_receive(const sc_u8 *p, sc_u32 n, sc_u32 now)
{
    if (!p || !pending || !session || working != generation || n < 23 || n > 128 ||
        p[0] != 0xf0 || p[1] != 0x7d || p[2] != 0x44 || p[3] != 0x32 ||
        p[4] != (context?3:2) || p[5] != 4 || p[n - 1] != 0xf7 || p[17] > 15 ||
        get7(p + 6, 4) != session || get7(p + 10, 4) != serial ||
        p[14] != op || p[15] != arg || p[16] != first) return 0;
    for (sc_u32 i = 6; i < n - 1; i++) if (p[i] & 128) return 0;
    ScUiView *v = &views[active ^ 1];
    const sc_u8 *q = p + 22;
    if (!op && !arg) {
        if (n != 56 || q[0] > 6 || q[1] > 7 || q[2] != 16 || q[3] != 5 ||
            !text_ok(q + 4, 10) || !text_ok(q + 14, 4) || !text_ok(q + 18, 13)) return 0;
    } else if (!op) {
        if (n != 119) return 0;
        for (sc_u32 k = 0; k < 4; k++) {
            const sc_u8 *kn = q + 24 * k;
            if (kn[0] != (arg - 1) * 4 + k + 1 || kn[1] > 3 || kn[2] > 7 || kn[3] > 2 ||
                kn[4] > kn[6] || kn[6] > kn[5] || kn[7] > 36 ||
                !text_ok(kn + 8, 12) || !text_ok(kn + 20, 4)) return 0;
        }
    } else {
        if (n < 25 || arg >= 16 || q[0] != v->knob[arg].count || first >= q[0] ||
            q[1] != (q[0] - first < 8 ? q[0] - first : 8) || n != 25 + 8u * q[1]) return 0;
        for (sc_u32 k = 0; k < q[1]; k++)
            if (q[2 + 8 * k + 7] || !text_ok(q + 2 + 8 * k, 8)) return 0;
    }
    sc_u32 revision = get7(p + 17, 5);
    if ((op || arg) && revision != v->revision) { restart(); return 1; }
    pending = 0;
    if (!op && !arg) {
        const ScUiView *current = sc_ui_view();
        if (current && current->revision == revision) {
            done = 1; refreshed = now; return 1;
        }
        zero((sc_u8 *)v, sizeof *v);
        view_context[active^1]=context;view_selector[active^1]=selector;
        v->revision = revision; v->token = session; copy(v->id, wanted, 32);
        v->state = q[0]; v->flags = q[1];
        copy((sc_u8 *)v->name, q + 4, 10);
        copy((sc_u8 *)v->short_name, q + 14, 4);
        copy((sc_u8 *)v->title, q + 18, 13);
        arg = 1;
    } else if (!op) {
        for (sc_u32 k = 0; k < 4; k++) {
            const sc_u8 *kn = q + 24 * k;
            ScUiKnob *d = &v->knob[(arg - 1) * 4 + k];
            d->look = kn[1]; d->kind = kn[2]; d->role = kn[3];
            d->min = kn[4]; d->max = kn[5]; d->def = kn[6]; d->count = kn[7];
            copy((sc_u8 *)d->name, kn + 8, 12); copy((sc_u8 *)d->short_name, kn + 20, 4);
        }
        if (++arg == 5) { op = 1; arg = first = 0; next_names(v, now); }
    } else {
        copy((sc_u8 *)v->knob[arg].names[first], q + 2, 8u * q[1]);
        first += q[1];
        if (first == q[0]) { arg++; first = 0; next_names(v, now); }
    }
    return 1;
}
