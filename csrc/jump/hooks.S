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
| d1 with 2: the tick of the step where stock looks at the queue; d5 and d6 are written there
| before they are read, so they are free here). A cue to take (jmp_armed):
| - something already armed (0x42c5aaac): ours (jmp_pending), or stock's own change at the
|   pattern's end (the cue made on its last step, after its tick 2): the switch at the next
|   boundary takes the newest cue (stock's cue routine replaces the list), so it is made
|   ours there (jmp_pending, jmp_from), and goes on from where the pattern was.
| - ticks 0, 1, 2: stock's. Tick 2 runs the queue's path, and jmp_arm arms the cue there.
|   v0.40: never on tick 1 (v0.39 did): stock's tick 2 runs that path again and clears the
|   arming first (0x400da41c), so a cue taken on tick 1 waited for the pattern's end.
| - ticks past 2, no stop pending (0x42c5a9e9): d1 reads 2 and the queue's path runs now
|   (jmp_forced: past tick 2, stock's own run of that path ends at 0x400da902).
        .globl  jmp_tick
jmp_tick:
        tst.b   jmp_armed
        beq.s   1f
        tst.l   0x42c5aaac
        beq.s   2f
        tst.b   jmp_pending
        bne.s   1f
        move.l  0x42c5a9a0, %d5
        move.l  %d5, jmp_from
        moveq   #1, %d5
        move.b  %d5, jmp_pending
        bra.s   1f
2:      mvs.b   0x42c5a91e, %d5
        moveq   #2, %d6
        cmp.l   %d6, %d5
        ble.s   1f
        tst.b   0x42c5a9e9
        bne.s   1f
        moveq   #1, %d6
        move.b  %d6, jmp_forced
        moveq   #2, %d1
        jmp     0x400da40c
1:      move.b  0x42c5a91e, %d1
        jmp     0x400da40c

| The queue's path at 0x400da45a (was: mvs.w 0x42c5aab4,%d1; d0 the queue's head pattern).
| Armed: disarmed here; if the head is another pattern, straight to stock's arming at
| 0x400da4d2 (the switch at the next step boundary), skipping the change-length test that
| arms only on the last step. Not another pattern: on a forced tick (past 2) the tick ends as
| stock's own does there (0x400da902; nothing was armed, jmp_tick saw 0x42c5aaac clear), so
| stock's last-step test and its program change are not run twice; on tick 2, stock's path.
| d1 is free on every way (0x400da460, 0x400da4d2 and 0x400da902 set it or do not read it).
        .globl  jmp_arm
jmp_arm:
        tst.b   jmp_armed
        beq.s   9f
        clr.b   jmp_armed
        tst.l   %d0
        beq.s   8f
        move.l  0x42c5a9a0, %d1
        cmp.l   %d1, %d0
        beq.s   8f
        clr.b   jmp_forced
        move.l  %d1, jmp_from
        move.l  %d0, jmp_to
        moveq   #1, %d1
        move.b  %d1, jmp_pending
        jmp     0x400da4d2
8:      tst.b   jmp_forced
        beq.s   9f
        clr.b   jmp_forced
        jmp     0x400da902
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
