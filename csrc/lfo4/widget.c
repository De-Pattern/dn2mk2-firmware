/* Why LFO4's page drew eight plain dials, and the ten rows that fix it.
 *
 * The page itself was right from the first build: `[MOD]` reached it, the
 * header read `MOD (4/4)`, and all eight labels were there in the sound
 * `ParameterSet` order -- `SPD MULT FADE DEST` over `WAVE SPH MODE DEP`. What
 * was missing was everything *inside* the dials. LFO3's page shows `512` in a
 * box for MULT, `SYN PD2` for DEST, a square glyph for WAVE; LFO4's showed
 * eight identical empty circles.
 *
 * `scripts/emu_lfo4_widget.py` hooked the companion-table accessor while each
 * MOD page drew:
 *
 *     [MOD] x3: entries [10, 95, 96, 97, 98, 99, 101, 102, 103]
 *     [MOD] x4: entries [10, 321, 322, 323, 324, 325, 327, 328, 329]
 *               96 of them answered 0x4243325c -- entry 0, the fallback
 *
 * **The page asked the right questions.** The accessor's bound is 321 and
 * clamps anything above to entry 0, so every LFO4 parameter was handed the
 * fallback row and drew the fallback's widget.
 *
 * That table cannot be relocated -- its initialiser is unrolled and writes 902
 * absolute addresses, so there is no base to repoint -- so the accessor is
 * diverted for LFO4's ten entries and answers from here.
 *
 * **The rows are LFO3's, copied whole**, for the same reason the page record
 * is: the fields are pointers to objects the UI built at startup, and this
 * code has never had to learn their layout. It copies at first use rather than
 * at init, because at init the firmware has not filled them yet.
 *
 * One subject: ten rows and which entry owns each. It does not know what a
 * widget is.
 */
#include "slots.h"

#define ROWS    (LFO4_ENTRYN - LFO4_ENTRY0)
#define BYTES   (ROWS * DN2_COMPANION_STRIDE)

u8 lfo4_companion_rows[BYTES];
u32 lfo4_companion_built, lfo4_companion_hits, lfo4_companion_declined;

/* -> the row for `entry`, or 0 for an entry the firmware owns.
 *
 * Zero is the signal to let the stock accessor have it, so the divert is
 * decided here and not in the assembly: an entry this build does not own is a
 * value the firmware has always answered for and must keep answering for.
 */
u32 lfo4_companion(u32 entry)
{
    const u8 *lfo3;
    u32 k;

    if (entry < LFO4_ENTRY0 || entry >= LFO4_ENTRYN) {
        lfo4_companion_declined++;
        return 0;
    }
    if (!lfo4_companion_built) {
        lfo3 = (const u8 *)(DN2_COMPANION + DN2_COMPANION_STRIDE * LFO3_ENTRY0);
        for (k = 0; k < BYTES; k++)
            lfo4_companion_rows[k] = lfo3[k];
        lfo4_companion_built = 1;
    }
    lfo4_companion_hits++;
    return (u32)lfo4_companion_rows + DN2_COMPANION_STRIDE * (entry - LFO4_ENTRY0);
}
