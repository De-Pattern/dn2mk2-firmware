| derived from irpina/digihealth (sysinfo.s), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project
|
| STATS layout 2: what the first cave had no room for, in a second one.
|
| The owner's first readings (stock + probe, 2026-09-27) raised two questions
| layout 1 cannot answer, and the save-while-playing hunt needs a third:
|
| - CPU read 100.0 % playing and stopped. Either the idle task never runs --
|   some task never blocks, and the CPU really is never idle -- or it runs
|   and the idle credit misses it (its TCB, or the resume PC the credit
|   requires). `idle_in` counts switches into the idle task, `idle_out` the
|   switches out of it, `idle_offpc` those whose resume PC is not the spin,
|   and `idle_lastpc` is the last such PC. idle_in = 0 means the first
|   reading; idle_offpc = idle_out the second.
| - The ISR's peak per STATS interval ran 74-112 % of a frame on stock, so
|   one peak says little. `isr_over` counts every ISR longer than one frame
|   period, cumulative: the host differences it per interval.
|
| Each is reached by a `jmp` from where the first cave returned (isr_out's
| and task_switch's `rts`) or a `jsr` from STATS, so every register contract
| there holds: see timing.S. The counters are in this cave, which the stock
| image ships as zeros, so they start at zero at every power-on.
#include "dn2_111.inc"

| One audio frame at the instrument's own rates, measured by this probe on
| 2026-09-27: DTCN0 at 132.00 MHz, 1,505 frames a second.
        .equ ISR_OVER_TICKS, 87708

        .text
        .globl  ext_out
| From isr_out. d0 = this ISR's ticks; d0 and d1 are dead after.
ext_out:
        cmp.l   #ISR_OVER_TICKS, %d0
        bls.s   1f
        addq.l  #1, isr_over
1:      rts

        .globl  ext_sw
| From task_switch, after it reloaded d0 with the replayed constant. Interrupts
| are masked; a0 is the incoming TCB and must survive, as must d0 and d1;
| d2-d7 are about to be reloaded, so d2 is free. 8(sp) is still the outgoing
| task's resume PC, and CUR_TCB still the outgoing task.
ext_sw:
        move.l  CUR_TCB, %d2
        cmpi.l  #IDLE_TCB, %d2
        bne.s   2f
        addq.l  #1, idle_out
        move.l  8(%sp), %d2
        cmpi.l  #IDLE_PC, %d2
        beq.s   2f
        addq.l  #1, idle_offpc
        move.l  %d2, idle_lastpc
2:      cmpa.l  #IDLE_TCB, %a0
        bne.s   3f
        addq.l  #1, idle_in
3:      rts

        .globl  ext_stats
| From STATS, after the four hashes: a1 is where the next field goes, and is
| left after the last one. Appended fields only: layout 1's 60 bytes are
| untouched. Not copied under masked interrupts: each is one counter a host
| differences, so a count one frame out is the most a tear can cost.
ext_stats:
        lea     isr_over, %a0
        moveq   #5, %d0
1:      move.l  (%a0)+, (%a1)+
        subq.l  #1, %d0
        bne.s   1b
        rts

        .balign 4
| ext_stats copies these five, in this order.
isr_over:    .long 0                    | ISRs longer than ISR_OVER_TICKS
idle_in:     .long 0                    | switches into the idle task
idle_out:    .long 0                    | switches out of it
idle_offpc:  .long 0                    | ... whose resume PC was not IDLE_PC
idle_lastpc: .long 0                    | the last such PC
        .globl  ext_end
ext_end:
