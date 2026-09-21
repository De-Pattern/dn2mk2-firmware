/* Digitone II OS 1.11: firmware addresses the C code calls or reads.
 *
 * Every entry is checked against the stock image by the build that uses it;
 * the routines follow GCC's ColdFire convention (arguments on the stack,
 * result in d0), which is also what this compiler emits.
 */
#ifndef DN2_111_H
#define DN2_111_H

#ifndef __ASSEMBLER__
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#endif

/* Startup: the .data initialiser and the BSS clear the startup hook wraps. */
#define DN2_DATA_INIT  0x4000045C
#define DN2_BSS_CLEAR  0x400004B2

/* The appended area, and where its data chunks run (dnfw.patch.area). */
#define DNFW_AREA      0x4030B980
#define DNFW_RUNTIME   0x46710000
#define DNFW_MAGIC     0x444E4657      /* 'DNFW' */
#define DNFW_CODE      0x434F4445      /* 'CODE' */

/* The stored <-> live sound converters (`docs/lfo4-build-plan.md` §4), and the
 * two sites just past their value loops, where both pointers are still live.
 * Deserialize takes (live, stored); serialize takes (stored, live, flag). */
#define DN2_SOUND_LOAD 0x400DD1EA
#define DN2_SOUND_SAVE 0x400DD6A6
#define DN2_LOAD_SITE  0x400DD282      /* mvs.b 28(a2),d0 ; moveq #6,d2 -- 6 bytes */
#define DN2_SAVE_SITE  0x400DD724      /* mvs.b 54(a2),d0 ; move.l (a0,d0.l*4),d0 -- 8 */

/* The parameter setter, and the bound that makes room for LFO4's slots.
 * 0x40037bd0 is `moveq #100,d0 ; cmp.l d2,d0 ; blt.s skip` -- six bytes, the
 * width of a `jmp <abs.l>` exactly -- guarding `values[d2] = d3` at
 * 0x40037be8. Above 100 stock firmware writes nothing at all, which is what
 * makes it a safe divert (`docs/lfo4-build-plan.md` §"Why that bound is the
 * opening"). */
#define DN2_SET_BOUND  0x40037BD0      /* the six bytes replaced */
#define DN2_SET_WRITE  0x40037BD6      /* on to the firmware's own write */
#define DN2_SET_SKIP   0x40037C48      /* the epilogue the bound branches to */

/* Step 4b, the page. Two sites, both in UI code that runs every frame.
 *
 * `DN2_PAGE_RECORD` is `id -> 0x42432c00 + 44 * id`, and it rejects anything
 * above 36 -- so a fourth MOD page's record cannot come from that table and
 * has to be answered before the arithmetic. The six bytes replaced are two
 * whole instructions the stub replays (`moveq #36,%d1 ; movel %sp@(4),%d0`).
 *
 * `DN2_MODE_HEADER` is the mode-header renderer, which reads the page vector
 * at the mode object's `+124` and the current index at `+144`. The stub is
 * entered after `%a2` would have been loaded and replays that load and the
 * one after it. */
#define DN2_PAGE_RECORD  0x400C2474    /* the six bytes replaced */
#define DN2_PAGE_AFTER   0x400C247A    /* cmpl %d0,%d1, where the stock code resumes */
#define DN2_MODE_HEADER  0x40063F5C    /* moveal %sp@(16),%a2 ; moveal %a0,%a3 */
#define DN2_MODE_AFTER   0x40063F62

/* The page id a fourth MOD page takes: one past the table's last, which only
 * the stub above ever answers for. */
#define LFO4_PAGE        37
/* The first of the ten parameter records appended to the relocated table --
 * an entry, so index + 1 (`dnfw.patch.paramtable`). */
#define LFO4_ENTRY0      321

/* Step 4c, the read side, and it is the setter's own shape.
 *
 * `0x4003717c` is `moveq #100,%d0 ; cmpl %d2,%d0 ; blts <zero>` -- six bytes,
 * the width of a `jmp <abs.l>`, guarding `mvs.w %a0@(20,%d2:l:2),%d0` at
 * `0x40037194`. Above 100 the firmware returns 0 and touches nothing, exactly
 * as its write path writes nothing, so the divert cannot corrupt a value the
 * firmware owns.
 *
 * Found by running: of the 119 instructions in the image that address the
 * value array's shape, **two** execute while a MOD page draws, and the other
 * clamps its index to 0..15 (`scripts/emu_value_reads.py`). */
#define DN2_GET_BOUND  0x4003717C      /* the six bytes replaced */
#define DN2_GET_READ   0x40037182      /* on to the firmware's own read */
#define DN2_GET_ZERO   0x4003719A      /* clr.l %d0, then the epilogue */
#define DN2_GET_RETURN 0x4003719C      /* the epilogue, with the answer in d0 */

/* Step 4d: the companion table, and why LFO4's page drew plain dials.
 *
 * `0x400c2418` is `entry -> 0x4243325c + 68 * entry`, bounded at 321 and
 * clamping anything above to entry 0. Drawing LFO4's page asks it for entries
 * 321-329 -- the right ones, the page's own eight -- and every one of the 96
 * lookups answered `0x4243325c`, the fallback (`scripts/emu_lfo4_widget.py`).
 * So each parameter got the fallback's widget: a dial with no value, no `512`
 * in a box, no waveform glyph, where LFO3's page has all three.
 *
 * The table cannot move -- its initialiser is unrolled and writes 902 absolute
 * addresses -- so the accessor is diverted for LFO4's entries instead, to ten
 * rows this build owns. Ten bytes are replaced and both instructions replayed.
 */
#define DN2_COMPANION        0x4243325C   /* the table itself, 321 x 68 */
#define DN2_COMPANION_STRIDE 68
#define DN2_COMPANION_BOUND  0x400C2418   /* the ten bytes replaced */
#define DN2_COMPANION_AFTER  0x400C2422   /* scs %d1, where the stock code resumes */

/* LFO3's ten entries, the ones LFO4's are copied from. Entry = index + 1, and
 * LFO3's records are indices 94..103. */
#define LFO3_ENTRY0      95
#define LFO4_ENTRYN      (LFO4_ENTRY0 + 10)

/* Step 4e: the waveform preview, which is re-coded per LFO.
 *
 * `0x4010e1f4` onward is three near-identical blocks selected by an LFO index
 * in `%d0` -- 0, 1, 2 -- each calling `0x4006538e` five times with its own
 * LFO's **entry numbers written as literals**:
 *
 *     index 0:  79, 81, 82, 75, 83      WAVE, SPH, MODE, SPD, DEP
 *     index 1:  89, 91, 92, 85, 93
 *     index 2:  99, 101, 102, 95, 103
 *
 * Anything else falls to `0x4010e2f0` and draws no preview -- which is why
 * LFO4's `SPH` came out a plain dial where LFO1-3 have the phase braces around
 * the waveform. **The dispatch already computes 3 for LFO4**
 * (`scripts/emu_lfo4_wave.py`); there is simply no block for it.
 *
 * So a fourth block is added, transcribing the firmware's own with five
 * constants changed, and the fallback's first eight bytes become a jump to it.
 */
#define DN2_WAVE_FALLBACK 0x4010E2F0   /* the eight bytes replaced */
#define DN2_WAVE_CALL     0x4006597A   /* what the fallback does, replayed */
#define DN2_WAVE_AFTER    0x4010E2F8
#define DN2_WAVE_TAIL     0x4010E2C6   /* the common tail all three blocks reach */
#define DN2_WIDGET_GET    0x4006538E   /* (page, entry, buffer) -> the drawn value */
#define DN2_WAVE_INDEX    3            /* what the dispatch hands LFO4 */

/* LFO4's five, in the order the blocks call for them. */
#define LFO4_E_WAVE  (LFO4_ENTRY0 + 4)
#define LFO4_E_SPH   (LFO4_ENTRY0 + 6)
#define LFO4_E_MODE  (LFO4_ENTRY0 + 7)
#define LFO4_E_SPD   (LFO4_ENTRY0 + 0)
#define LFO4_E_DEP   (LFO4_ENTRY0 + 8)

/* The parameter table as it sits in the image, for reading a record's own
 * default at init. `lfo4-table` relocates this table, but the image's copy is
 * still there and still correct -- and it is the one guaranteed to be loaded
 * when `lfo4_init` runs, which the relocated chunk is not. */
#define DN2_PARAM_TABLE   0x401F7FC8
#define DN2_PARAM_STRIDE  60
#define DN2_PARAM_DEFAULT 24           /* the record's default value */
#define LFO3_RECORD0      94           /* LFO3's group of ten starts here */

/* libc as the firmware has it. */
#define DN2_MEMCPY     0x40134490
#define DN2_MEMSET     0x401344D8

#ifndef __ASSEMBLER__
static inline void *dn2_memset(void *dst, int c, u32 n)
{
    return ((void *(*)(void *, int, u32))DN2_MEMSET)(dst, c, n);
}

static inline void *dn2_memcpy(void *dst, const void *src, u32 n)
{
    return ((void *(*)(void *, const void *, u32))DN2_MEMCPY)(dst, src, n);
}
#endif /* __ASSEMBLER__ */

#endif
