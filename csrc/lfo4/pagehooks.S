/* Step 4b's two page sites, kept apart from `hooks.S` because they are not
 * shared. Every build since step 1 assembles `hooks.S`, and a stub there that
 * calls into `page.c` would make every one of them need that file linked --
 * which is how `lfo4-table` stopped building the moment these were written
 * beside the others.
 *
 * Both are entry stubs: they jump in, replay exactly the instructions the jump
 * displaced, and go back -- the same shape as the four in `hooks.S`, and for
 * the same reason.
 */
#include "dn2_111.h"
/* `id -> record`. The site is that routine's **first** instruction, so the
 * stub is the whole function and owns every scratch register it did: d0 is
 * the result, d1 was its own, and it touched nothing else.
 *
 * LFO4's page id has no record in the firmware's table, so the stub answers
 * for it and lets every other id through to the arithmetic. The answer is 0
 * until the first mode header is drawn and the record is built, and until
 * then the id falls through to the fallback record -- which is what an
 * unknown id has always returned. */
    .globl  lfo4_page_stub
lfo4_page_stub:
    move.l  %sp@(4),%d0
    cmp.l   #LFO4_PAGE,%d0
    bne.s   lfo4_page_stock
    jsr     lfo4_page_for
    tst.l   %d0
    beq.s   lfo4_page_stock         | not built yet
    rts
lfo4_page_stock:
    .globl  lfo4_page_displaced
lfo4_page_displaced:
    moveq   #36,%d1
    move.l  %sp@(4),%d0
    jmp     DN2_PAGE_AFTER

/* The mode-header renderer, entered with the mode object still on the stack.
 * `lfo4_pages` decides whether this is the MOD mode and, once, gives it a
 * fourth page. %a2 and %a3 are callee-saved, so they survive the call and the
 * replayed loads stand. */
    .globl  lfo4_mode_stub
lfo4_mode_stub:
    .globl  lfo4_mode_displaced
lfo4_mode_displaced:
    movea.l %sp@(16),%a2
    movea.l %a0,%a3
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    move.l  %a2,-(%sp)
    jsr     lfo4_pages
    addq.l  #4,%sp
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    jmp     DN2_MODE_AFTER
