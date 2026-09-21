/* `lfo4-dest`'s two stubs: the gate the browser opens behind, and its mask.
 *
 * Its own file, for the reason `valuehooks.S` states -- an assembly file is
 * linked whole, so a stub placed beside others is compiled into every build
 * that has no interest in the site it patches.
 *
 * Six sites in the image compare an entry against 78, 88 and 98, and five
 * choose a capability mask from bits 18, 17 and 16. `emu_lfo4_dest.py` opened
 * the browser on all four MOD pages and found that **one** of each runs. These
 * are that one of each.
 */
#include "dn2_111.h"
#include "slots.h"

/* The last of the three compares, and a fourth behind it.
 *
 * The gate is woven through the prologue -- `moveq #78,%d1` is the function's
 * second instruction, before the arguments are loaded -- so the twenty-two
 * bytes are not contiguous and cannot be replaced as one. They do not need to
 * be: 78 and 88 are tested and taken before this point, and what is left is
 * `moveb #98,%d1 ; cmpl %d0,%d1 ; bne`, eight bytes with both exits in them.
 *
 * `%d0` holds the entry. `%d1` is the stock code's scratch and is dead on both
 * exits -- the accept path's first instruction is `movel %d0,%d1`, and the
 * decline path never reads it -- so this stub need preserve neither.
 */
    .globl  lfo4_dest_stub
lfo4_dest_stub:
    cmp.l   #98,%d0
    beq.s   lfo4_dest_yes
    cmp.l   #LFO4_E_DEST,%d0
    beq.s   lfo4_dest_yes
    jmp     DN2_DEST_DECLINE
lfo4_dest_yes:
    jmp     DN2_DEST_ACCEPT

/* The mask cascade, transcribed with a fourth step.
 *
 * The firmware's is thirty-four bytes and every branch converges on
 * `DN2_DEST_MASK_AFTER`, so the whole of it is replaced rather than hooked.
 * The first three steps are its own, instruction for instruction, including
 * the `movew` that writes only the low half of a `%d0` the `movel` above it
 * has already cleared.
 *
 * The fourth is the staircase's own next step: bit 15 of the record's `+44`,
 * which is what `lfo4records.DEST_FLAGS` writes, selecting `0x0200`, which is
 * the mask that admits LFO3's eight records on top of everything LFO3 itself
 * may target. Nothing in the shipping firmware ever passes it.
 *
 * `%d1` holds the flags and is not written here. `%d0` is the answer.
 */
    .globl  lfo4_dest_mask
lfo4_dest_mask:
    move.l  #0x1e00,%d0
    btst    #18,%d1
    bne.s   lfo4_dest_mask_done
    move.w  #0x0e00,%d0
    btst    #17,%d1
    bne.s   lfo4_dest_mask_done
    move.w  #0x0600,%d0
    btst    #16,%d1
    bne.s   lfo4_dest_mask_done
    move.w  #DN2_DEST_MASK4,%d0
    btst    #DN2_DEST_FLAG_BIT,%d1
    bne.s   lfo4_dest_mask_done
    clr.l   %d0
lfo4_dest_mask_done:
    jmp     DN2_DEST_MASK_AFTER
