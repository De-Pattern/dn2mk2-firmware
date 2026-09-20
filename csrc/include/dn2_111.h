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
