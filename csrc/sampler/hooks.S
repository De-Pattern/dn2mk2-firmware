| The sample link's two hooks in stock code (csrc/sampler/link.c, docs/sampler.md).
| Each replaces one 6-byte `lea` with a `jsr` here, calls the C, and replays the lea.

        .text
        .globl  smp_rx_hook
        .globl  smp_feed_hook

| The SysEx router 0x4012166e at 0x4012169a (was: lea 0x40207ae6,%a3), once per F0
| message other than F0 7E, in the MIDI input task: a0 = a1 = the message, d1 its
| length, d2 its source; those must survive, and d0, d3, a2 are free (the USB probe's
| hook site, docs/usbprobe.md). smp_rx(msg, len, source) only reads the message.
smp_rx_hook:
        lea     -20(%sp), %sp
        movem.l %d0-%d2/%a0-%a1, (%sp)
        move.l  %d2, -(%sp)
        move.l  %d1, -(%sp)
        move.l  %a0, -(%sp)
        jsr     smp_rx
        lea     12(%sp), %sp
        movem.l (%sp), %d0-%d2/%a0-%a1
        lea     20(%sp), %sp
        lea     0x40207ae6, %a3
        rts

| The frame builder 0x400274ba at 0x400276a2 (was: lea 0x40006c4a,%a2), every frame
| after the frame's last word is written, in the audio-frame ISR. Every register but
| a2 is kept; a2 gets what the lea gave it.
smp_feed_hook:
        lea     -16(%sp), %sp
        movem.l %d0-%d1/%a0-%a1, (%sp)
        jsr     smp_feed
        movem.l (%sp), %d0-%d1/%a0-%a1
        lea     16(%sp), %sp
        lea     0x40006c4a, %a2
        rts
