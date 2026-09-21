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
