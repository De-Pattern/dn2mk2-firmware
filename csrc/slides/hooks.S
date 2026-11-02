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
