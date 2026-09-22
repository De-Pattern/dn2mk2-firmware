/* The fourth MOD page: a page record that does not exist, and a vector of three.
 *
 * Two runtime structures stand between the ten parameter records and a page
 * the instrument will show, and neither can be written at build time:
 *
 * - **the page-record table** at `0x42432c00`, ids 0..36, 44 bytes each, built
 *   by the UI at startup. `0x400c2474` turns an id into a record with
 *   `base + 44 * id` after rejecting anything above 36;
 * - **the mode's page vector**, three longwords holding the ids `4 5 6`, at the
 *   mode object's `+124`/`+128`. The header the screen draws is derived from
 *   it -- `MOD (3/3)` is `(end - begin) / 4` and the 1-based `+144` -- so
 *   **nothing has to be taught that there are four pages; a fourth entry is
 *   the whole change** (`docs/lfo4-build-plan.md`).
 *
 * The vector's three entries are exactly their own allocation: the sixteen
 * bytes after them are an allocator word and live pointers, so a fourth cannot
 * be appended in place. The array is rehoused here instead, and the record is
 * built here too, from LFO3's -- which is the only way to get one, since the
 * fields that matter are pointers to string objects the UI made at startup and
 * this code has never had to learn their layout. It copies LFO3's name object
 * and changes one character.
 *
 * The swap happens the first time a mode header is drawn with `4 5 6` in it.
 * **That is one frame too late** when a project opens on the MOD page: three
 * page dots are drawn until `[MOD]` is pressed once, reported from the
 * instrument on 2026-09-22 and visible in the boot gate, which listed
 * `lfo4_pages` as never exercised in a boot to a drawn frame. `pagelist.c`
 * builds the vector with four ids at startup instead; this stays as the route
 * for any build that does not patch that site, and declines once the vector
 * already holds four.
 *
 * **The one thing this does that it cannot prove.** The vector's `begin` is
 * replaced with an array this build owns, so a destructor that frees it would
 * be freeing memory the firmware's allocator never handed out. UI mode objects
 * are built once and kept -- the snapshot's has a stable address across
 * sessions -- but "never destroyed" is an observation, not a guarantee, and
 * switching modes hard in the emulator is how it is checked.
 */
#include "ext.h"

#define PAGE_TABLE   0x42432C00u
#define PAGE_STRIDE  44u
#define PAGE_WORDS   (PAGE_STRIDE / 4u)
#define LFO3_PAGE    6u
#define VEC_BEGIN    124u
#define VEC_END      128u
#define VEC_CAP      132u

#define NAME_BYTES   32u          /* LFO3's name object, copied whole */
#define NAME_DIGIT   3u           /* "LFO3" -> "LFO4" */
#define ENTRIES      8u

/* The page record's eight entries are positions 0,1,2,3,4,6,7,8 of the group
 * of ten: the two alternates -- SLEW, which shares SPH's slot, and the second
 * MULT -- are reached from state rather than named on the page. */
static const u8 POSITION[ENTRIES] = {0, 1, 2, 3, 4, 6, 7, 8};

u32 lfo4_page_record[PAGE_WORDS];
u32 lfo4_page_ids[4];
u8 lfo4_page_name[NAME_BYTES];
u32 lfo4_pages_swapped;

static u32 *page(u32 id)
{
    return (u32 *)(PAGE_TABLE + PAGE_STRIDE * id);
}

static void build(void);

/* -> the record for a page id the firmware has none for, or 0 if the UI has
 * not built its own table yet. The accessor stub asks; this is the only
 * reader that may be early, and it answers 0 by falling the id through to the
 * fallback record, which is what an unknown id always returned.
 *
 * **It builds on demand rather than waiting to be told.** It used to be told,
 * by `lfo4_pages`, which runs off the mode-header renderer -- so when the page
 * list is instead made four at startup (`pagelist.c`) nothing calls that, and
 * the record has to be built the first time someone asks for it.
 */
u32 lfo4_page_for(void)
{
    if (!lfo4_page_record[0]) {
        if (!page(LFO3_PAGE)[0])
            return 0;                 /* the UI's page table is not filled yet */
        build();
    }
    return (u32)lfo4_page_record;
}

static void build(void)
{
    const u32 *lfo3 = page(LFO3_PAGE);
    const u8 *name = (const u8 *)lfo3[0];
    u32 k;

    for (k = 0; k < NAME_BYTES; k++)
        lfo4_page_name[k] = name[k];
    lfo4_page_name[NAME_DIGIT] = '4';

    for (k = 0; k < PAGE_WORDS; k++)
        lfo4_page_record[k] = lfo3[k];
    lfo4_page_record[0] = (u32)lfo4_page_name;
    /* `+4` is the **mode** name, the `MOD` the header draws, and it is the
     * same string for every page in the mode -- so LFO3's own is reused
     * rather than copied. */
    for (k = 0; k < ENTRIES; k++)
        lfo4_page_record[2 + k] = LFO4_ENTRY0 + POSITION[k];
}

/* Called from the top of the mode-header renderer with the mode object. */
void lfo4_pages(u32 object)
{
    u32 *begin = *(u32 **)(object + VEC_BEGIN);
    u32 *end = *(u32 **)(object + VEC_END);

    if (!begin || end != begin + 3)
        return;                       /* not a three-page mode, or already ours */
    if (begin[0] != 4u || begin[1] != 5u || begin[2] != 6u)
        return;                       /* three pages, but not the MOD pages */

    build();
    lfo4_page_ids[0] = begin[0];
    lfo4_page_ids[1] = begin[1];
    lfo4_page_ids[2] = begin[2];
    lfo4_page_ids[3] = LFO4_PAGE;
    *(u32 **)(object + VEC_BEGIN) = lfo4_page_ids;
    *(u32 **)(object + VEC_END) = lfo4_page_ids + 4;
    *(u32 **)(object + VEC_CAP) = lfo4_page_ids + 4;
    lfo4_pages_swapped++;
}
