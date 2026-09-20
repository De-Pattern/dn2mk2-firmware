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
