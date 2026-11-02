| DIRECT JUMP's hooks in stock 1.11 (csrc/jump/jump.c, docs/jump.md). Each replaces one
| 6-byte instruction; the cue's is a jsr, the four in the sequencer tick ISR (0x400d987a)
| are jmp detours that replay the instruction and jump back. In the ISR every register
| is live, so the shims touch only the one the replayed instruction writes, or save what
| the C may clobber (d0, d1, a0, a1).

        .text

| The PTN view's single-pattern cue 0x400fa11e at 0x400fa1da (was: jsr 0x400d93f0, its
| arguments list and count on the stack). Stock's cue first, as before; then jmp_cued()
| arms when the setting is on and the sequencer plays. The caller reads no register the
| call leaves (it pops its arguments and goes on with a2 and d3).
        .globl  jmp_cue
jmp_cue:
        move.l  8(%sp), -(%sp)                  | the count
        move.l  8(%sp), -(%sp)                  | the list
        jsr     0x400d93f0
        addq.l  #8, %sp
        jsr     jmp_cued
        rts

| The tick's step test at 0x400da406 (was: move.b 0x42c5a91e,%d1, then 0x400da40c compares
| d1 with 2: the tick of the step where stock looks at the queue). Armed, on a tick that is
| not a step boundary (d1 0: stock's step advance and switch run there) and with no stop
| pending (0x42c5a9e9), d1 reads 2 and the queue's path runs now.
        .globl  jmp_tick
jmp_tick:
        move.b  0x42c5a91e, %d1
        tst.b   jmp_armed
        beq.s   1f
        tst.b   %d1
        beq.s   1f
        tst.b   0x42c5a9e9
        bne.s   1f
        moveq   #2, %d1
1:      jmp     0x400da40c

| The queue's path at 0x400da45a (was: mvs.w 0x42c5aab4,%d1; d0 the queue's head pattern).
| Armed: disarmed here; if the head is another pattern, straight to stock's arming at
| 0x400da4d2 (the switch at the next step boundary), skipping the change-length test that
| arms only on the last step. d1 is free on both ways (0x400da460 and 0x400da4d2 set it).
        .globl  jmp_arm
jmp_arm:
        tst.b   jmp_armed
        beq.s   9f
        clr.b   jmp_armed
        tst.l   %d0
        beq.s   9f
        move.l  0x42c5a9a0, %d1
        cmp.l   %d1, %d0
        beq.s   9f
        move.l  %d1, jmp_from
        move.l  %d0, jmp_to
        moveq   #1, %d1
        move.b  %d1, jmp_pending
        jmp     0x400da4d2
9:      mvs.w   0x42c5aab4, %d1
        jmp     0x400da460

| The switch at 0x400da6e6 (was: lea 0x42c5a9c4,%a1, before 0x42c5a9bc = the new pattern's
| start step). Ours: jmp_position() gives the start step (or -1: not the switch we armed),
| and stock's per-track positions that follow read the new pattern through a5 (stock's a5
| is still the pattern that was playing; a5 is read only by that code before 0x400da904
| sets it again).
        .globl  jmp_switch
jmp_switch:
        tst.b   jmp_pending
        beq.s   9f
        clr.b   jmp_pending
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        jsr     jmp_position
        tst.l   %d0
        bmi.s   8f
        move.l  %d0, 0x42c5a9c4
        movea.l 0x42c5a9a0, %a5
8:      movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
9:      lea     0x42c5a9c4, %a1
        jmp     0x400da6ec

| The end of stock's per-track positions at 0x400da8cc (was: pea 0x401f6b25): after our
| jump, each track's start step wrapped by its length (jmp_wrap_tracks).
        .globl  jmp_tracks
jmp_tracks:
        tst.b   jmp_fix
        beq.s   9f
        clr.b   jmp_fix
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        jsr     jmp_wrap_tracks
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
9:      pea     0x401f6b25
        jmp     0x400da8d2
