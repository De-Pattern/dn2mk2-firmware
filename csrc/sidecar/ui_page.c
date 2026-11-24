/* Native SYN descriptors use the same sixteen records for every external engine.
 * Missing metadata changes labels only: never reset a sound's saved controls. */
#include "wr_gen.h"
#include "ui.h"
#include "sound.h"
#define D __attribute__((section(".data"), aligned(4)))
static sc_u32 stamp D, mode D, wake_at D;
static sc_u32 descriptors[2][11] D;
static const ScUiView *seen D;
static char labels[16][18] D; /* native name pointers never refer to a reusable MIDI staging buffer */
/* Native page headings are old-ABI std::strings. The characters must have a
 * length/capacity/refcount header; -1 makes native copies clone the static text.
 * Plain char buffers let the native UI share, mutate and eventually free them. */
typedef struct { sc_u32 length, capacity, refs; char text[14]; } ScPageString;
static ScPageString titles[2] D;
static ScPageString captions[2] D;
static sc_u8 sound_id[32] D;
static const char *const fallback[16] = {
    "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8",
    "P9", "P10", "P11", "P12", "P13", "P14", "P15", "P16"
};
extern void sc_ui_wake(void);
static int named(const sc_u8 *id,const char *name)
{if(!id)return 0;for(sc_u32 i=0;i<32;i++){if(id[i]!=(sc_u8)name[i])return 0;if(!name[i])return 1;}return 0;}
static sc_u32 raw_value(const volatile sc_u8 *sound,sc_u32 p)
{
    sc_u32 slot=*(volatile sc_u32 *)(0x401f7f94u+60u*sc_all_ids[p]+4);
    return sound[20+2*slot]; /* integer part, independent of modulation/locks */
}
sc_u32 sc_ui_follow(void)
{
    sc_select_poll();
    const volatile sc_u8 *kit = *(const volatile sc_u8 *volatile *)0x800052a0u;
    sc_u32 track = *(volatile sc_u8 *)0x42431a6cu;
    const volatile sc_u8 *sound = kit && track < 16 ? kit + 52 + 1163 * track : 0;
    sc_u8 id[32];
    int generic = sound && sound[0xde] == SC_TYPE ? sc_sound_identity(sound, id) : 0;
    sc_u32 next = generic > 0 ? 1 : generic < 0 ? 2 : 0;
    for (sc_u32 i = 0; i < 32; i++) sound_id[i] = generic > 0 ? id[i] : 0;
    const sc_u8 *target = sc_pick_target();
    const sc_u8 *want=target?target:generic>0?id:0;
    int md=named(want,"sidecar.builtin.md"), preset=named(want,"sidecar.builtin.juno")||named(want,"sidecar.builtin.fm");
    sc_u32 selector=0;
    if((md||preset) && generic>0 && (!target||named(id,(const char*)target))) selector=raw_value(sound,md?8:0);
    if(sc_ui_want_context(want,md||preset?track:16,selector)) stamp++;
    if (mode != next) { mode = next; stamp++; }
    sc_ui_publish();
    const ScUiView *v = sc_ui_sound_view();
    if (v != seen) { seen = v; stamp++; }
    sc_u32 now = *(volatile sc_u32 *)0x4058e8d4u;
    if (mode == 1 && now - wake_at >= 15) { wake_at = now; sc_ui_wake(); }
    return stamp;
}
int sc_ui_generic(void) { return mode != 0; }
const ScUiView *sc_ui_sound_view(void)
{
    const ScUiView *v = sc_ui_view();
    if (!v || mode != 1) return 0;
    for (sc_u32 i = 0; i < 32; i++) if (v->id[i] != sound_id[i]) return 0;
    return v;
}
const char *sc_ui_label(sc_u32 knob, int short_name)
{
    if (knob >= 16) return "-";
    const ScUiView *v = sc_ui_sound_view();
    if (!v) return fallback[knob];
    const char *s = short_name ? v->knob[knob].short_name : v->knob[knob].name;
    if (!s[0]) return "-";
    char *d = labels[knob] + (short_name ? 13 : 0);
    for (sc_u32 i = 0; i < (short_name ? 5u : 13u); i++) d[i] = s[i];
    return d;
}
static sc_u32 page_count(const ScUiView *v)
{
    if(!v) return 2; /* legacy Perkons or metadata still arriving */
    for(sc_u32 k=8;k<16;k++)
        if(v->knob[k].name[0] || v->knob[k].short_name[0]) return 2;
    return 1;
}
static const char *heading(ScPageString *out,const char *text)
{
    sc_u32 n=0;
    for(;n<13 && text[n];n++) out->text[n]=text[n];
    out->text[n]=0;
    out->length=n;out->capacity=13;out->refs=0xffffffffu;
    return out->text;
}
sc_u32 sc_ui_page_count(void)
{
    sc_ui_follow();
    return page_count(sc_ui_sound_view());
}
const sc_u32 *sc_ui_page(sc_u32 page)
{
    if (page >= 2) return 0;
    sc_ui_follow();
    if (!mode) return 0; /* the assembler retains the legacy Perkons descriptors */
    const ScUiView *v = sc_ui_sound_view();
    if(page >= page_count(v)) page=0; /* stale page index after changing machines */
    sc_u32 *d = descriptors[page];
    const char *title = page ? (v && v->title[0] ? v->title : "PARAMETERS") :
                              (mode == 2 ? "INVALID" : v ? v->name : "SIDECAR");
    d[0] = (sc_u32)heading(&titles[page],title);
    const char *caption=!v ? "WAITING" : v->state != 1 ? "UNAVAILABLE" :
                    (v->flags&4) && (named(v->id,"sidecar.builtin.juno")||named(v->id,"sidecar.builtin.fm")) ? v->title : "";
    d[1]=(sc_u32)heading(&captions[page],caption);
    for (sc_u32 k = 0; k < 8; k++) {
        sc_u32 p = page * 8 + k;
        d[2 + k] = v && !v->knob[p].name[0] && !v->knob[p].short_name[0] ? 0 : sc_all_ids[p];
    }
    d[10] = 10; /* the existing custom SYN page tag */
    return d;
}
