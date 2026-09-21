/* `lfo4-slew`'s one stub: the gate that decides whether `RND` shows `SLEW`.
 *
 * Its own file, for the reason `valuehooks.S` states -- an assembly file is
 * linked whole, so a stub placed beside others is compiled into every build
 * that has no interest in the site it patches.
 *
 * `DN2_SLEW_GATE` is twenty-two bytes for three compares and three branches,
 * and this stub replaces all of it rather than replaying any: the site is a
 * decision with two exits and the stub owns both.
 *
 *   81, 91, 101   LFO1's, LFO2's and LFO3's `SPH`: exactly what stock accepted
 *   LFO4_E_SPH    327, the fourth, which is the whole change
 *   anything else DN2_SLEW_DECLINE, and the entry is handed back untouched
 *
 * `%d2` holds the entry at the site and is live on both exits -- the decline
 * path's first instruction is `movel %d2,%d0`. Nothing else is: `%d0` and
 * `%d1` were the stock code's own scratch here, and both exits overwrite them
 * before reading them.
 */
#include "dn2_111.h"
#include "slots.h"

    .globl  lfo4_slew_stub
lfo4_slew_stub:
    cmp.l   #81,%d2
    beq.s   lfo4_slew_yes
    cmp.l   #91,%d2
    beq.s   lfo4_slew_yes
    cmp.l   #101,%d2
    beq.s   lfo4_slew_yes
    cmp.l   #LFO4_E_SPH,%d2
    beq.s   lfo4_slew_yes
    jmp     DN2_SLEW_DECLINE
lfo4_slew_yes:
    jmp     DN2_SLEW_ACCEPT
