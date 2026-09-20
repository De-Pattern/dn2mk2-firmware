/* memcpy's entry (0x40134490) becomes `jmp hello_memcpy_stub ; nop`.
 * The stub passes memcpy's own three arguments to the C routine, then replays
 * the two instructions the jump displaced and continues in memcpy. */
#include "dn2_111.h"

    .text
    .globl  hello_memcpy_stub
hello_memcpy_stub:
    move.l  12(%sp),-(%sp)          | n
    move.l  12(%sp),-(%sp)          | src
    move.l  12(%sp),-(%sp)          | dst
    jsr     hello_on_memcpy
    lea     12(%sp),%sp
    movea.l 4(%sp),%a1              | displaced: movea.l 4(sp),a1
    movea.l 8(%sp),%a0              | displaced: movea.l 8(sp),a0
    jmp     DN2_MEMCPY + 8
