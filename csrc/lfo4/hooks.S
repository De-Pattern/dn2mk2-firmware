/* The two patch sites: `memcpy` and `memset` at their entries.
 *
 * Eight bytes of each becomes `jmp <stub> ; nop`, so each stub passes the
 * routine's own three arguments to C, replays the two instructions the jump
 * displaced, and continues at entry + 8. Neither stub saves a register: the C
 * it calls follows the same convention the firmware's callers expect, so
 * d0/d1/a0/a1 are already the caller's to lose, and both displaced pairs write
 * their registers *after* the call.
 *
 * The displaced pairs, read out of stock 1.11:
 *   memcpy  0x40134490  moveal 4(%sp),%a1 ; moveal 8(%sp),%a0
 *   memset  0x401344d8  moveal 8(%sp),%a0 ; mvzb 11(%sp),%d0
 * `scripts/build_lfo4_ext.py` checks both against the image before patching,
 * and checks that this file assembles back to exactly those bytes.
 */
#include "dn2_111.h"

    .text

    .globl  lfo4_memcpy_stub
lfo4_memcpy_stub:
    move.l  12(%sp),-(%sp)          | n
    move.l  12(%sp),-(%sp)          | src
    move.l  12(%sp),-(%sp)          | dst
    jsr     lfo4_on_memcpy
    lea     12(%sp),%sp
    .globl  lfo4_memcpy_displaced
lfo4_memcpy_displaced:
    movea.l 4(%sp),%a1
    movea.l 8(%sp),%a0
    jmp     DN2_MEMCPY + 8

    .globl  lfo4_memset_stub
lfo4_memset_stub:
    move.l  12(%sp),-(%sp)          | n
    move.l  12(%sp),-(%sp)          | fill
    move.l  12(%sp),-(%sp)          | dst
    jsr     lfo4_on_memset
    lea     12(%sp),%sp
    .globl  lfo4_memset_displaced
lfo4_memset_displaced:
    movea.l 8(%sp),%a0
    mvz.b   11(%sp),%d0
    jmp     DN2_MEMSET + 8

/* The other two sites are inside code that never expected a call, so unlike the
 * `memcpy` / `memset` stubs these must preserve what the compiler calls
 * scratch: at both, d0, d1, a0 and a1 are live across the site. ColdFire's
 * MOVEM has no predecrement or postincrement mode, hence the `lea` either side.
 *
 * Each sits just past its converter's value loop, where the live sound and the
 * stored sound are both still in a2/a3 -- in opposite roles, which is why the
 * two stubs push their arguments in opposite orders.
 *
 *   load   0x400dd282  mvs.b 28(%a2),%d0 ; moveq #6,%d2          a2 live, a3 stored
 *   save   0x400dd724  mvs.b 54(%a2),%d0 ; move.l (%a0,%d0*4),%d0  a2 stored, a3 live
 */

    .globl  lfo4_load_stub
lfo4_load_stub:
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    move.l  %a3,-(%sp)              | stored
    move.l  %a2,-(%sp)              | live
    jsr     lfo4_on_load
    addq.l  #8,%sp
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    .globl  lfo4_load_displaced
lfo4_load_displaced:
    mvs.b   %a2@(28),%d0
    moveq   #6,%d2
    jmp     DN2_LOAD_SITE + 6

    .globl  lfo4_save_stub
lfo4_save_stub:
    lea     -16(%sp),%sp
    movem.l %d0-%d1/%a0-%a1,(%sp)
    move.l  %a3,-(%sp)              | live
    move.l  %a2,-(%sp)              | stored
    jsr     lfo4_on_save
    addq.l  #8,%sp
    movem.l (%sp),%d0-%d1/%a0-%a1
    lea     16(%sp),%sp
    .globl  lfo4_save_displaced
lfo4_save_displaced:
    mvs.b   %a2@(54),%d0
    move.l  %a0@(0,%d0:l:4),%d0
    jmp     DN2_SAVE_SITE + 8
