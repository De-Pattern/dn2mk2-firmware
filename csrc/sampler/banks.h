/* v0.65 PROJECT RAM banks (docs/banks.md), the ColdFire's side: what every sampler file shares.
 *
 * A GLOBAL SLOT g is bank * POOL_SLOTS + slot: bank g >> 7 (0 A .. 3 D), slot g & 127. Bank A's
 * g is the slot number every file used before v0.65 (0..127), so bank A reads as it always did.
 * SAMP's word carries the bank in its low byte (BANK_TAG); its high byte is the slot + 1 as
 * before (0 OFF; FLEX buffers' codes 129.. are bank A's).
 *
 * Bank A's directory page is the mirror's DIR (link.c); banks B..D's are copies in BANK_RAM, each
 * the whole page as it lies in the pool at BANK_AREA: the directory page (bank A's format, magic
 * BANK_MAGIC) at + 0, its meta block at + BANK_META, its slice area at + BANK_SLICES. */
#ifndef SMP_BANKS_H
#define SMP_BANKS_H

#if !defined(BANK_AREA) || !defined(BANK_PAGE) || !defined(BANK_RAM) || !defined(BANK_N)
#error "the banks' constants are passed by the build (dnfw.waverider.cpage)"
#endif

#define SMP_ALL ((int)(BANK_N * POOL_SLOTS))                 /* global slots */
#define G_BANK(g) ((u32)(g) >> 7)
#define G_SLOT(g) ((u32)(g) & 127u)
#define G_OF(b, s) ((int)((u32)(b) * POOL_SLOTS + (u32)(s)))
#define BANK_TAG(b) ((u32)(b) << 6)                          /* 0x00, 0x40, 0x80, 0xC0 */
#define BPAGE(b) ((unsigned char *)(BANK_RAM + ((u32)(b) - 1u) * BANK_PAGE))   /* b 1..3 */
#define BPAGE_OFF(b) (BANK_AREA + ((u32)(b) - 1u) * BANK_PAGE)                /* in the pool */
/* the per-slot RAM of banks B..D's slots (g >= POOL_SLOTS), after the three pages */
#define BOVERVIEW(g) ((unsigned char *)(BANK_RAM + 3u * BANK_PAGE + 100u * ((u32)(g) - POOL_SLOTS)))
#define BSLICECOL(g) ((unsigned char *)(BANK_RAM + 3u * BANK_PAGE + 0xA000u + 64u * ((u32)(g) - POOL_SLOTS)))
#define BSSUM(g) ((unsigned char *)(BANK_RAM + 3u * BANK_PAGE + 0x10000u + 20u * ((u32)(g) - POOL_SLOTS)))
_Static_assert(3u * 100u * POOL_SLOTS <= 0xA000u && 3u * 64u * POOL_SLOTS <= 0x6000u
               && 3u * BANK_PAGE + 0x10000u + 3u * 20u * POOL_SLOTS <= 0x80000u, "banks' RAM fits BANK_RAM_BYTES");
_Static_assert(BANK_AREA + 3u * BANK_PAGE == TABLE_AREA, "the pages lie just below the tables");

int smp_bank_live(int b);                       /* link.c: bank B in use (A always, with a pool) */
int smp_bank_count(int b);                      /* link.c: its page's count */

/* a SAMP word's bank, as the DSP reads it (dnfw.sampler.machines.bank_of) */
static inline int smp_word_bank(u32 w)
{
    u32 b = ((w & 0xFFu) + 0x20u) >> 6;
    return (int)(b > 3u ? 3u : b);
}

/* the global slot a SAMP word plays (its high byte 1..127 in its bank), -1 OFF or a FLEX code */
static inline int smp_word_g(u32 w)
{
    u32 v = (w >> 8) & 0xFFu;
    if (v < 1u || v > 127u)
        return -1;
    return G_OF(smp_word_bank(w), v - 1u);
}

/* the list's rows (the DT2's: one run through the banks): 0 OFF, then each bank's 127 slots,
 * then the eight FLEX buffers */
#define ROW_BANK0 1
#define ROW_FLEX (1 + 4 * 127)                              /* 509 */
#define ROWS_ALL (ROW_FLEX + 8)
#define G_WORD(g) ((u32)(G_SLOT(g) + 1u) << 8 | BANK_TAG(G_BANK(g)))   /* a global slot's SAMP word */
#define G_ROW(g) (ROW_BANK0 + 127 * (int)G_BANK(g) + (int)G_SLOT(g))   /* a global slot's row */

#endif
