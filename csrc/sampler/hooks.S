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

| The parameter setter 0x40037b74 at 0x40037be6 (was: movea.l %d0,%a0 ; move.w
| %d3,0x14(%a0,%d2.l*2)), where a turn's value is written into the sound: d0 the sound,
| d2 the slot, d3 the value (values[] at sound + 0x14; objdump prints the 0x14 as "14"). smp_quant (fmt.c) may move the value to the next
| choice of a sample machine's control; d3 leaves as what was written, a0 as d0, every
| other register as it came (the setter goes on to pass d0 and d3 along).
        .globl  smp_quant_hook
smp_quant_hook:
        lea     -12(%sp), %sp
        movem.l %d0-%d1/%a1, (%sp)
        move.l  %d3, -(%sp)
        move.l  %d2, -(%sp)
        move.l  %d0, -(%sp)
        jsr     smp_quant
        lea     12(%sp), %sp
        move.l  %d0, %d3
        movem.l (%sp), %d0-%d1/%a1
        lea     12(%sp), %sp
        movea.l %d0, %a0
        move.w  %d3, 0x14(%a0,%d2.l*2)
        rts

| The SSI audio ISR 0x40025e36 at 0x40026098 (was: move.l %fp,%d2 ; addi.l #-72,%d2, 8
| bytes; now jsr here and a nop), v0.16: every mode's transmit fill has ended there
| (docs/link-research.md 6c), so smp_tdm(h) writes our packet into slots 8..15 of the
| transmit half h = %fp@(-56) and reads the DSP's from slots 14..15 of the receive half.
| Every register lives on in the ISR, so every one C may touch is kept; d2 leaves as the
| two replayed instructions leave it (the ISR pushes it next).
        .globl  smp_tdm_hook
smp_tdm_hook:
        lea     -20(%sp), %sp
        movem.l %d0-%d2/%a0-%a1, (%sp)
        move.l  -56(%fp), -(%sp)
        jsr     smp_tdm
        addq.l  #4, %sp
        movem.l (%sp), %d0-%d2/%a0-%a1
        lea     20(%sp), %sp
        move.l  %fp, %d2
        addi.l  #-72, %d2
        rts
