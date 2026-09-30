| derived from irpina/digihealth (sysinfo.s), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project
|
| The probe's two measurements, kept as cumulative counters the STATS reply
| reads (the host takes differences, so nothing here is ever reset but the
| peak):
|
| - the audio-frame ISR's own time, entry to exit, in DTCN0 ticks: the
|   ColdFire's per-frame cost, which is where lfo4's evaluators run;
| - the time the idle task spends parked, from the context switch: everything
|   else the CPU does is 1 minus that.
|
| digihealth times the Digitakt mk1's render the same way (si_render_in/out,
| task_switch); what differs is the sites, which are DN2 1.11's own, and
| that there is no once-a-second snapshot task here: STATS copies these under
| masked interrupts when it is asked, which is what keeps the probe free of
| any periodic work (irpina's probing notes (shared privately), section 5, builds the
| snapshot in the UI task instead; this build has no UI hook to spare).
|
| Every counter lives in the probe's data block, in the cave, which the
| bootloader reloads as zeros at every power-on -- so no init is needed.

| At ISR_IN (was: movel 0xfc045640,%d0). The ISR has saved every register;
| d0 is the displaced instruction's destination, so it is free until then.
        .globl  isr_in
isr_in:
        move.l  DTCN0, %d0
        move.l  %d0, t_in
        move.l  EDMA50_SADDR, %d0       | the instruction this replaced
        rts

| At ISR_OUT (was: addql #1,0x4058e8d4). d0 and d1 are dead here: the next
| instruction loads d0, and d1 is written before it is read. The ISR's body
| is straight-line from its entry to ISR_IN and from ISR_OUT to its only rte,
| so every exit here was preceded by an entry above in the same call.
        .globl  isr_out
isr_out:
        addq.l  #1, FRAMES              | the instruction this replaced
        move.l  DTCN0, %d0
        sub.l   t_in, %d0               | ticks this frame took
        add.l   %d0, r_acc
        addq.l  #1, r_cnt
        cmp.l   r_max, %d0
        bls.s   1f
        move.l  %d0, r_max
1:      move.l  CUR_TCB, %d1
        cmpi.l  #IDLE_TCB, %d1
        bne.s   9f
        add.l   %d0, r_idle             | ISR time taken out of an idle interval
9:      jmp     EXT_OUT                 | layout 2: the over-a-frame count (ext.S)

| At TASK_SWITCH (was: movel #0xffffdfff,%d0). Interrupts are masked; a0 is
| the incoming TCB, a1 and d1 are live, and d2-d7/a2-a5 are about to be
| reloaded from the incoming TCB, so they are free. 8(sp) is the outgoing
| task's resume PC, above this routine's return address.
        .globl  task_switch
task_switch:
        addq.l  #1, n_sw                | switches seen: the scheduler is alive
        move.l  DTCN0, %d2
        move.l  CUR_TCB, %d3            | the outgoing task
        cmpi.l  #IDLE_TCB, %d3
        bne.s   1f
        tst.l   i_on
        beq.s   1f
        move.l  8(%sp), %d4
        cmpi.l  #IDLE_PC, %d4           | only time parked in the idle spin
        bne.s   1f
        move.l  %d2, %d4
        sub.l   i_start, %d4
        add.l   %d4, i_acc
1:      clr.l   i_on
        cmpa.l  #IDLE_TCB, %a0
        bne.s   2f
        move.l  %d2, i_start            | idle switched in: open an interval
        moveq   #1, %d0
        move.l  %d0, i_on
2:      move.l  #0xffffdfff, %d0        | the instruction this replaced
        jmp     EXT_SW                  | layout 2: the idle diagnostics (ext.S)
