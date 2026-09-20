/* The startup loader: copies the appended DNFW area out before the BSS clear.
 *
 * It replaces the startup calls `jsr data_init ; jsr bss_clear` at 0x4000053e
 * and lives in a small cave (dnfw.patch.loader checks the fit). It runs before
 * `main` and before the caches are enabled (0x4000055a), so the code it copies
 * needs no cache maintenance.
 *
 *  - the area header, and each data chunk, go to DNFW_RUNTIME + their offset:
 *    where the boot screen's whole-area copy has always put them;
 *  - a CODE chunk goes to its own load address, its BSS is zeroed, and its
 *    init entry, if any, is called. That is before the firmware's BSS clear,
 *    so an init may touch only its own memory.
 *
 * With no area appended it is exactly the two stock calls. Assembly, not C:
 * the compiled C was 220 bytes and the largest free clean cave is 138. It saves
 * no registers: the startup code after it only calls `main` (0x40000568).
 */
#include "dn2_111.h"

    .section .text.entry,"ax"
    .globl  dnfw_boot
dnfw_boot:
    jsr     DN2_DATA_INIT
    lea     DNFW_AREA,%a2           | a2: the area, then each directory entry - 12
    move.l  (%a2),%d0
    cmpi.l  #DNFW_MAGIC,%d0
    bne.s   9f
    move.l  8(%a2),%d2              | d2: directory entries left
    move.l  %d2,%d4                 | the header first: offset 0, 12 + 12 * count bytes
    addq.l  #1,%d4
    move.l  %d4,%d1
    add.l   %d4,%d4
    add.l   %d1,%d4
    lsl.l   #2,%d4
    moveq   #0,%d0
    bra.s   2f

1:  lea     12(%a2),%a2             | next entry: id, offset, length
    move.l  4(%a2),%d0
    move.l  8(%a2),%d4
2:  lea     DNFW_AREA,%a0
    adda.l  %d0,%a0                 | src: the chunk in the area
    lea     DNFW_RUNTIME,%a1
    adda.l  %d0,%a1                 | dst: the same offset at run time
    moveq   #0,%d1                  | no bss, no init
    suba.l  %a3,%a3
    move.l  (%a2),%d3               | the header's id is 'DNFW', never 'CODE'
    cmpi.l  #DNFW_CODE,%d3
    bne.s   3f
    movea.l (%a0)+,%a1              | CODE: load address,
    move.l  (%a0)+,%d4              |   image length,
    move.l  (%a0)+,%d1              |   bss length,
    movea.l (%a0)+,%a3              |   init entry

3:  addq.l  #3,%d4                  | copy, longword by longword
    lsr.l   #2,%d4
    beq.s   5f
4:  move.l  (%a0)+,(%a1)+
    subq.l  #1,%d4
    bne.s   4b
5:  lsr.l   #2,%d1                  | zero the bss
    beq.s   7f
6:  clr.l   (%a1)+
    subq.l  #1,%d1
    bne.s   6b
7:  move.l  %a3,%d0
    beq.s   8f
    jsr     (%a3)
8:  subq.l  #1,%d2
    bpl.s   1b

9:  jmp     DN2_BSS_CLEAR
