| Per-pass MIDI queue hook: replay the displaced A5 load and preserve the queue
| count in D0, every other caller-saved register and the original stack layout.
        .text
        .globl sc_midi_poll_hook
sc_midi_poll_hook:
        lea -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        jsr sc_midi_poll
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea 16(%sp), %sp
        lea 0x40001876, %a5
        rts
