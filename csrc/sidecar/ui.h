#ifndef SIDECAR_UI_H
#define SIDECAR_UI_H
#include "bridge.h"

typedef struct {
    sc_u8 look, kind, role, min, max, def, count, reserved;
    char name[13], short_name[5], names[36][8];
} ScUiKnob;
typedef struct {
    sc_u32 revision, token;
    sc_u8 id[32];
    char name[11], short_name[5], title[14];
    sc_u8 state, flags;
    ScUiKnob knob[16];
} ScUiView;
typedef struct { sc_u8 id[32]; char name[11], short_name[5]; sc_u8 state; } ScCatalogEntry;
typedef struct { sc_u32 revision, token; sc_u8 count; ScCatalogEntry entry[32]; } ScCatalog;
void sc_catalog_open(sc_u32 on);
int sc_catalog_publish(void);
const ScCatalog *sc_catalog_view(void);
void sc_catalog_session(sc_u32 token);
sc_u32 sc_catalog_request(sc_u32 token, sc_u32 now, sc_u8 *packet);
int sc_catalog_receive(const sc_u8 *packet, sc_u32 bytes, sc_u32 now);
/* Explicit load transaction: -1 canceled, -2 awaiting reply, otherwise RMP_PST_*.
 * Cancel stops requests; an already accepted Pi load may finish into its cache. */
int sc_load_start(sc_u32 track, const sc_u8 *id);
void sc_load_cancel(void);
int sc_load_state(void);
void sc_load_session(sc_u32 token);
sc_u32 sc_load_request(sc_u32 token, sc_u32 now, sc_u8 *packet);
int sc_load_receive(const sc_u8 *packet, sc_u32 bytes, sc_u32 now);

/* UI task: choose a complete canonical ID (NULL clears), then publish completed
 * metadata at the beginning of a UI pass. Returned view remains immutable until
 * the next publish on that same UI task. MIDI never writes the published buffer. */
int sc_ui_want(const sc_u8 *id);
int sc_ui_want_context(const sc_u8 *id, sc_u32 track, sc_u32 selector);
int sc_ui_publish(void);
const ScUiView *sc_ui_view(void);
/* MIDI task: one bounded, read-only request at a time. 100 ms retries, one-second
 * metadata refresh; no filesystem/DSP work. A changed token cancels old replies.
 * Returns 50 (legacy) or 52 (track/selector context), zero while waiting.
 * The caller must provide 52 bytes. Failed transport may retry later. */
sc_u32 sc_ui_request(sc_u32 token, sc_u32 now, sc_u8 *packet);
void sc_ui_session(sc_u32 token);
int sc_ui_receive(const sc_u8 *packet, sc_u32 bytes, sc_u32 now);
/* UI task only: follow the selected native sound and install completed metadata. */
sc_u32 sc_ui_follow(void);
int sc_ui_generic(void);
const char *sc_ui_label(sc_u32 knob, int short_name);
const sc_u32 *sc_ui_page(sc_u32 page);
sc_u32 sc_ui_page_count(void);
int sc_select(sc_u32 track, const ScUiView *view);
void sc_select_poll(void);
int sc_select_apply(sc_u32 track, volatile sc_u8 *sound, const sc_u32 *sets, const ScUiView *view);
const ScUiView *sc_ui_sound_view(void);
void sc_pick_seen(sc_u32 view);
int sc_pick_visible(void);
const sc_u8 *sc_pick_target(void);
void sc_pick_close(void);
void sc_pick_poll(void);
int sc_pick_pop(sc_u8 *item, int function);
void sc_pick_draw(void *canvas);
#endif
