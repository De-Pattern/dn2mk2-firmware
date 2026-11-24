/* Native MACHINE SEL rows. Virtual values are UI-only: sounds always store
 * SC_TYPE plus a full engine ID. Only an explicit pending load freezes rows. */
#include "wr_gen.h"
#include "ui.h"
#include "sound.h"
#define D __attribute__((section(".data"), aligned(4)))
#define TRACK (*(volatile sc_u8 *)0x42431a6cu)
#define KIT (*(volatile sc_u32 *)0x800052a0u)
#define NOW (*(volatile sc_u32 *)0x4058e8d4u)
#define ROW_TYPE ((sc_u32 (*)(sc_u32))0x4005b162u)
#define BUILD_ROWS ((void (*)(sc_u32))0x4005b2c0u)
#define DIRTY ((void (*)(sc_u32))0x4011c7bau)
#define FOLLOW ((void (*)(sc_u32))0x4005a956u)
#define NEW ((void *(*)(sc_u32))0x40120264u)
#define DELETE ((void (*)(void *))0x40120270u)
#define VIRTUAL 256u
static ScCatalog rows D;
static sc_u32 native_view D, row_track D, row_kit D, row_project D;
static sc_u32 opened D, loading D, failed D, wake_at D, row_generation D;
static sc_u8 selected[32] D;
extern void *wr_screen_obj;
extern sc_u32 smp_pj_loads;
extern void sc_ui_wake(void);
static int ram(sc_u32 p) { return p>=0x40000000u && p<0x48000000u && !(p&3); }
static int equal(const sc_u8 *a,const sc_u8 *b)
{ for(sc_u32 i=0;i<32;i++) if(a[i]!=b[i]) return 0; return 1; }
static sc_u32 top(void)
{
    sc_u32 s=(sc_u32)wr_screen_obj;
    if(!ram(s)) return 0;
    sc_u32 node=*(sc_u32 *)(s+28);
    if(!ram(node)||node==s+20) return 0;
    sc_u32 v=*(sc_u32 *)(node+8);
    return ram(v)&&*(sc_u32 *)v==0x401df9d8u ? v : 0;
}
static const ScCatalogEntry *entry(sc_u32 type)
{ return type>=VIRTUAL && type-VIRTUAL<rows.count ? &rows.entry[type-VIRTUAL] : 0; }
sc_u32 sc_list_current(sc_u32 model,sc_u32 track);
void sc_pick_seen(sc_u32 view) { (void)view; }
int sc_pick_visible(void) { return 0; }
void sc_pick_draw(void *canvas) { (void)canvas; }
const sc_u8 *sc_pick_target(void) { return loading ? selected : 0; }
void sc_pick_close(void) { loading=failed=0; sc_load_cancel(); }

/* Stock getter already allocated this vector. Replace that allocation using
 * the same native heap; native row creation and destruction remain unchanged. */
void sc_list_types(sc_u32 *vec,sc_u32 view)
{
    row_generation++;
    sc_pick_close(); native_view=view; row_track=TRACK; row_kit=KIT; row_project=smp_pj_loads;
    const ScCatalog *c=sc_catalog_view(); rows.count=0;rows.token=c?c->token:0;
    if(!c||!c->count||TRACK>=8||!KIT) return;
    sc_u32 n=(vec[1]-vec[0])/4;
    if(n>64||vec[1]<vec[0]) return;
    sc_u32 *old=(sc_u32 *)vec[0],*out=NEW((n+c->count)*4);
    if(!out) return;
    for(sc_u32 i=0;i<sizeof rows;i++) ((volatile sc_u8 *)&rows)[i]=((const sc_u8 *)c)[i];
    /* Keep a fallback only if the saved engine has no matching catalog row. */
    int fallback=*(sc_u8 *)(KIT+52+1163*TRACK+0xde)==SC_TYPE &&
                 sc_list_current(*(sc_u32 *)(view+132),TRACK)==SC_TYPE;
    sc_u32 used=0;
    for(sc_u32 i=0;i<n;i++) {
        if(old[i]!=SC_TYPE||fallback) out[used++]=old[i];
        if(old[i]==SC_TYPE) { for(sc_u32 k=0;k<rows.count;k++) out[used++]=VIRTUAL+k; }
    }
    vec[0]=(sc_u32)out;vec[1]=(sc_u32)(out+used);vec[2]=(sc_u32)(out+n+c->count);
    if(old) DELETE(old);
    *(sc_u32 *)(view+412)=sc_list_current(*(sc_u32 *)(view+132),TRACK);
}
static int rows_changed(const ScCatalog *c)
{
    if(!c) return rows.count!=0;
    if(c->token!=rows.token || c->count!=rows.count) return 1;
    for(sc_u32 i=0;i<c->count;i++) {
        if(!equal(c->entry[i].id,rows.entry[i].id)) return 1;
        for(sc_u32 k=0;k<11;k++) if(c->entry[i].name[k]!=rows.entry[i].name[k]) return 1;
    }
    return 0;
}
static void refresh_rows(sc_u32 v)
{
    sc_u32 type=ROW_TYPE(v),column=*(sc_u32 *)(v+424);sc_u8 id[32];const ScCatalogEntry *old=entry(type);
    if(old) for(sc_u32 k=0;k<32;k++) id[k]=old->id[k];
    BUILD_ROWS(v);
    sc_u32 current=*(sc_u32 *)(v+412), wanted=old?current:type;
    if(old) for(sc_u32 k=0;k<rows.count;k++) if(equal(id,rows.entry[k].id)){wanted=VIRTUAL+k;break;}
    if(!column) {
        sc_u32 *p=*(sc_u32 **)(v+388),*end=*(sc_u32 **)(v+392),index=0;
        *(sc_u32 *)(v+420)=0;
        for(;p<end;p+=2,index++) if(*(sc_u32 *)(p[0]+4)==wanted){*(sc_u32 *)(v+420)=index;break;}
    }
    FOLLOW(v);DIRTY(v);
}
const char *sc_list_name(sc_u32 type)
{
    const ScCatalogEntry *e=entry(type);
    return e ? e->name : ((const char *(*)(sc_u32))0x400dc332u)(type);
}
const char *sc_list_label(sc_u32 type)
{
    const ScCatalogEntry *e=entry(type);
    if(!e) return 0;
    if(!loading||!equal(e->id,selected)) return e->short_name;
    if(failed) return "FAILED";
    const ScUiView *v=sc_ui_view();int st=sc_load_state();
    if(v&&equal(v->id,selected)&&((st==1&&v->state==1)||(st==5&&v->state==0)))
        return st==5 ? "YES:SWAP" : "YES:USE";
    return st==1||st==2||st<0 ? "LOADING" : "NO LOAD";
}
sc_u32 sc_list_current(sc_u32 model,sc_u32 track)
{
    sc_u32 type=((sc_u32 (*)(sc_u32,sc_u32))0x4003134eu)(model,track);
    if(type!=SC_TYPE||track>=8||!KIT||track!=row_track) return type;
    sc_u8 id[32];int generic=sc_sound_identity((const sc_u8 *)(KIT+52+1163*track),id);
    if(generic<0) return type;
    if(!generic) { const char *p="mega.perkons";for(sc_u32 i=0;i<32;i++){id[i]=*p;if(*p)p++;} }
    for(sc_u32 i=0;i<rows.count;i++) if(equal(id,rows.entry[i].id)) return VIRTUAL+i;
    return type;
}
void sc_pick_poll(void)
{
    sc_u32 v=top();
    if(!v||!KIT) {
        if(opened){opened=0;sc_catalog_open(0);}
        if(loading) sc_pick_close();
        return;
    }
    /* Stock may reuse MACHINE SEL after changing tracks. Its rows must be
     * rebound before handling YES; an old pending load never follows a track. */
    if(v!=native_view||TRACK!=row_track||KIT!=row_kit||smp_pj_loads!=row_project) {
        BUILD_ROWS(v); FOLLOW(v); DIRTY(v);
    }
    if(TRACK>=8) {
        if(opened){opened=0;sc_catalog_open(0);}
        return;
    }
    if(!opened){opened=1;sc_catalog_open(1);sc_ui_wake();}
    sc_catalog_publish();
    const ScCatalog *c=sc_catalog_view();
    /* Rebind complete catalog changes, preserving the highlighted full ID.
     * Availability-only changes must not cancel a pending explicit selection. */
    if(!loading && rows_changed(c)) refresh_rows(v);
    if(loading) {
        const ScCatalogEntry *e=entry(ROW_TYPE(v));
        if(!e||!equal(e->id,selected)) sc_pick_close();
        if(NOW-wake_at>=15){wake_at=NOW;DIRTY(v);}
    }
}
int sc_pick_pop(sc_u8 *it,int function)
{
    /* Encoders and other ordinary input never service the catalog. Polling is
     * owned by the UI loop; only a machine-list YES needs a synchronous check. */
    (void)function;
    if(it[0]) return 0;
    sc_u32 code=((sc_u32)it[4]<<24)|((sc_u32)it[5]<<16)|((sc_u32)it[6]<<8)|it[7];
    if(code!=10&&code!=49) return 0;
    sc_u32 before=row_generation;sc_pick_poll();sc_u32 v=top();
    if(before!=row_generation) return 1; /* never apply YES to a replaced row */
    if(!v||v!=native_view||TRACK>=8||TRACK!=row_track||KIT!=row_kit||smp_pj_loads!=row_project) return 0;
    sc_u32 flags=((sc_u32)it[8]<<24)|((sc_u32)it[9]<<16)|((sc_u32)it[10]<<8)|it[11];
    sc_u32 type=ROW_TYPE(v);const ScCatalogEntry *e=entry(type);
    if(!e) return 0;
    if(!(flags&1)||(flags&24)) return 1;
    if(!loading) {
        if(sc_list_current(*(sc_u32 *)(v+132),TRACK)==type) return 0;
        for(sc_u32 i=0;i<32;i++) selected[i]=e->id[i];
        loading=sc_load_start(TRACK,selected);failed=0;
        sc_ui_want(selected);sc_ui_wake();DIRTY(v);return 1;
    }
    const ScUiView *desc=sc_ui_view();int st=sc_load_state();
    if(!desc||!equal(desc->id,selected)||!((st==1&&desc->state==1)||(st==5&&desc->state==0))) return 1;
    extern sc_u32 smp_machine_commit(sc_u32,sc_u32,sc_u32,sc_u32,sc_u32);
    extern int gr_allowed(sc_u32,sc_u32);
    if(!gr_allowed(TRACK,SC_TYPE)) return 1;
    volatile sc_u8 *sound=(volatile sc_u8 *)(KIT+52+1163*TRACK);
    if(sound[0xde]!=SC_TYPE) {
        extern int sc_select_hold(sc_u32);
        if(!sc_select_hold(TRACK)) return 1;
        smp_machine_commit(*(sc_u32 *)(v+132),TRACK,SC_TYPE,1,1);
    }
    int ok=sound[0xde]==SC_TYPE ? sc_select(TRACK,desc) : 0;
    if(ok==1){*(sc_u32 *)(v+412)=type;sc_pick_close();FOLLOW(v);}
    else failed=1;
    DIRTY(v);return 1;
}
