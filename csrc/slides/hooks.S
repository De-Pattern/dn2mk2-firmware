| Parameter slides' hooks in stock code (csrc/slides/slide.c, docs/slides.md). Each site
| (dnfw.slides) is a jmp or jsr here; the *_stock entries replay the bytes a hook replaced
| (as .word, byte for byte) and go on into the stock routine.

        .text

| 0x40026bac, in the frame ISR's per-voice note block (was: movea.l %d2,%a4 ; move.l
| 64(%a0),%d0, 6 bytes; now jsr here): d2 the voice, d3 the track. sl_pre(voice, track);
| every register as it came, then the two instructions replayed (the move sets the flags
| the ISR's beq.s tests next; nothing after it touches them).
        .globl  sl_pre_hook
sl_pre_hook:
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        move.l  %d3, -(%sp)
        move.l  %d2, -(%sp)
        jsr     sl_pre
        addq.l  #8, %sp
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        movea.l %d2, %a4
        move.l  64(%a0), %d0
        rts

| 0x4002717e (was: jsr 0x400db12a, the smoother; now jsr sl_smooth, its argument on the
| stack as before): see slide.c. The smoother leaves d1/a0/a1 as scratch; d0 its base.

| 0x400db092, the lock applier (was: lea -44(%sp),%sp ; move.l 48(%sp),%d0; now jmp sl_apply)
        .globl  sl_apply_stock
sl_apply_stock:
        .word   0x4fef, 0xffd4, 0x202f, 0x0030
        jmp     0x400db09a

| 0x400d85e8, the lock-list builder (was: lea -24(%sp),%sp ; moveq #101,%d0)
        .globl  sl_build_stock
sl_build_stock:
        .word   0x4fef, 0xffe8, 0x7065
        jmp     0x400d85ee

| 0x4003d14e, clear a step's locks (was: lea -40(%sp),%sp ; movem.l %d2-%d7/%a2-%a5,(%sp))
        .globl  sl_clear_stock
sl_clear_stock:
        .word   0x4fef, 0xffd8, 0x48d7, 0x3cfc
        jmp     0x4003d156

| 0x400de51e, a pattern's lock table loaded (was: lea -32(%sp),%sp ; movem.l %d2-%d5/%a2-%a5,(%sp))
        .globl  sl_load_stock
sl_load_stock:
        .word   0x4fef, 0xffe0, 0x48d7, 0x3c3c
        jmp     0x400de526

| 0x400de718, a pattern's lock table saved (was: lea -28(%sp),%sp ; movem.l %d2-%d4/%a2-%a5,(%sp))
        .globl  sl_save_stock
sl_save_stock:
        .word   0x4fef, 0xffe4, 0x48d7, 0x3c1c
        jmp     0x400de720

| ---- v0.40: copy and paste carry SLD/SLEN (docs/slides.md) --------------------------------
| The shapes are the arp p-locks' (scripts/build_arp_plocks.py, each path driven under the
| emulator there): the same stock sites, our records in place of theirs.

| Copying steps inside a pattern: shift (FUNC + LEFT/RIGHT, 0x40051158) and page autocopy on
| lengthening (0x40050cce) match records by track; the tag cleared, our records travel with
| their steps. Replaces `mvs.b rec+1, %d0 ; cmp.l 60(%a2), %d0` (8 bytes: jsr, nop); the flags
| are the compare's, as stock's.
        .globl  sl_copy_cmp1
sl_copy_cmp1:
        mvs.b   1(%a3,%d1.l), %d0
        bclr    #5, %d0
        cmp.l   60(%a2), %d0
        rts
        .globl  sl_copy_cmp2
sl_copy_cmp2:
        mvs.b   1(%a5,%a0.l), %d0
        bclr    #5, %d0
        cmp.l   60(%a2), %d0
        rts

| paste_core(record, values, table, first step, count, destination track) -> d0: the record's
| track byte (mvs.b), or -2 when it was one of ours of the clipboard's track, written onto the
| destination (sl_paste, slide.c). The clipboard is the paste routine's -16(%fp); its track at
| +96668. Keeps d1-d7 / a0-a6.
sl_paste_core:
        lea     -12(%sp), %sp
        movem.l %d1/%a0-%a1, (%sp)
        movea.l -16(%fp), %a0
        move.l  #96668, %d1
        move.l  (%a0,%d1.l), -(%sp)             | the clipboard's track
        move.l  40(%sp), -(%sp)                 | destination track
        move.l  40(%sp), -(%sp)                 | count
        move.l  40(%sp), -(%sp)                 | first step
        move.l  40(%sp), -(%sp)                 | table
        move.l  40(%sp), -(%sp)                 | values
        move.l  40(%sp), -(%sp)                 | record
        jsr     sl_paste
        lea     28(%sp), %sp
        movem.l (%sp), %d1/%a0-%a1
        lea     12(%sp), %sp
        rts

| Track pastes 0x4005389c / 0x40052948 (its UNDO): a3 + a0 the record and its 128 values, d2
| the table, 60(%a2) the track; the result in d5 / d4 (was: mvs.b 1(%a3,%a0.l),%d5|%d4 ;
| move.l #96668,%d1: 10 bytes, jsr and two nops). d0 kept: the stock loop reads it after.
        .globl  sl_paste_c, sl_paste_d
sl_paste_d:
        move.l  %d0, -(%sp)
        bsr.s   sl_track_paste
        move.l  %d0, %d4
        bra.s   1f
sl_paste_c:
        move.l  %d0, -(%sp)
        bsr.s   sl_track_paste
        move.l  %d0, %d5
1:      move.l  (%sp)+, %d0
        move.l  #96668, %d1
        rts
sl_track_paste:
        move.l  60(%a2), -(%sp)
        pea     128
        clr.l   -(%sp)
        move.l  %d2, -(%sp)
        pea     (%a3,%a0.l)
        pea     (%a3,%a0.l)
        bsr     sl_paste_core
        lea     24(%sp), %sp
        rts

| Page pastes 0x40052634 (its UNDO) / 0x40053246: a1 + d0 the record, the page's values at
| -20(%fp) + d0 / d6 + d0, a3 the table, d3 the page's first step; the result in d7 / d5 (was:
| mvs.b 1(%a1,%d0.l),%d7|%d5 ; move.l #96668,%d1).
        .globl  sl_paste_a, sl_paste_b
sl_paste_a:
        move.l  -20(%fp), %d1
        bsr.s   sl_page_paste
        move.l  %d1, %d7
        move.l  #96668, %d1
        rts
sl_paste_b:
        move.l  %d6, %d1
        bsr.s   sl_page_paste
        move.l  %d1, %d5
        move.l  #96668, %d1
        rts
sl_page_paste:                                  | d1 the values' base -> d1 the result
        move.l  %d0, -(%sp)
        move.l  60(%a2), -(%sp)
        pea     16
        move.l  %d3, -(%sp)
        move.l  %a3, -(%sp)
        add.l   %d0, %d1
        move.l  %d1, -(%sp)
        pea     (%a1,%d0.l)
        bsr     sl_paste_core
        lea     24(%sp), %sp
        move.l  %d0, %d1
        move.l  (%sp)+, %d0
        rts

| Trig copy 0x40053f48 (the source step's stock locks gathered, before its clipboard entry is
| appended; was: move.l (%a2),-(%sp) ; move.l 60(%a3),-(%sp)): sl_tcopy(entry, context, step),
| the entry's number from the clipboard's vector at -92(%fp) (72 bytes an entry), a3 the
| track's context, (a2) the step. Then the two pushes, under the return address.
        .globl  sl_copy_hook
sl_copy_hook:
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        movea.l -92(%fp), %a0
        move.l  8(%a0), %d0
        sub.l   4(%a0), %d0
        move.l  (%a2), -(%sp)
        move.l  %a3, -(%sp)
        move.l  %d0, -(%sp)
        jsr     sl_tcopy
        lea     12(%sp), %sp
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        move.l  (%sp), -(%sp)                   | R R
        move.l  (%a2), 4(%sp)                   | R step
        move.l  (%sp), -(%sp)                   | R R step
        move.l  60(%a3), 4(%sp)                 | R track step (the flags: the last push's, as stock)
        rts

| Trig paste 0x40055440 (the destination step cleared, its stock locks written; was: mvz.b
| 4(%a3),%d0 ; lea 0x40054690,%a4): sl_tpaste(entry, context, step), the entry's number from
| a3's place in the clipboard's vector, a2 the track's context, (a3) the destination step.
        .globl  sl_paste_hook
sl_paste_hook:
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        movea.l -92(%fp), %a0
        move.l  %a3, %d0
        sub.l   4(%a0), %d0
        move.l  (%a3), -(%sp)
        move.l  %a2, -(%sp)
        move.l  %d0, -(%sp)
        jsr     sl_tpaste
        lea     12(%sp), %sp
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        mvz.b   4(%a3), %d0
        lea     0x40054690, %a4
        rts
