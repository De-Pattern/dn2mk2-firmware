| derived from irpina/digihealth (sysinfo.s), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project
|
| The read-only USB SysEx channel: F0 00 20 3C 7D 00 <pack7 body> F7.
|
|   request  <pack7: u16 seq, u8 cmd, args>
|   reply    <pack7: u16 seq, u8 cmd|0x80, u8 status, payload>
|   status   0 ok, 1 refused argument, 2 unknown command
|
| The protocol, pack7/unpack7 and the router hook are digihealth's (and
| irpina's probing notes (shared privately), section 5); the DN2 1.11 sites are in
| dn2_111.inc. Where this diverges from sysinfo.s, and why:
|
| - STATS is built when it is asked for, not once a second by a UI hook, so
|   the probe does no periodic work at all. Its counters are cumulative and the
|   host differences two replies; only the ISR peak is read-and-clear.
| - STATS carries DSP liveness, which the mk1 has no need of: the ColdFire's
|   audio-frame count, and a hash of each buffer the SHARC link moves (the
|   SHARC's DSPI reply, the control frame pushed to it, and both SSI0 audio
|   windows). A halted SHARC shows as a reply hash that stops changing.
| - PEEK's allow list adds the two SSI0 audio windows, which are plain DDR
|   the eDMA writes, and nothing else: never the 0xfc000000 peripherals or the
|   0xec000000 FPGA/DSPI window, where a read can have a side effect.
| - HELLO carries the build's tag, so the host can say which image answers.
|
| There is no write command, and none can be added by a request: the
| dispatcher only knows the three below.

        .equ PROTO,       3                | 2: STATS layout 2 appends ext.S's fields
                                           | 3: idle is the prio-1 task: CPU is right
        .equ C_HELLO,     1
        .equ C_STATS,     2
        .equ C_PEEK,      3
        .equ PEEK_MAX,    1024
        .equ NRANGES,     3
        .equ RQ_MAX,      16
        .equ STATS_LAYOUT, 2

| At ROUTER_HOOK (was: lea 0x40207ae6,%a3), once per F0 message other than
| F0 7E, in the MIDI input task. a0 = a1 = the message, F0..F7; d1 = its
| length; d2 = where it came from (2 or 4 USB, 8 or 0x10 DIN, the stock
| MidiRpc test at 0x4012092c). a0, a1, d1, d2 must survive; d0, d3, a2 are
| free. The router goes on to drop device 0x7D itself (0x401216c4: only
| 0x00-0x17 route), so a stock-shaped reply path is untouched.
        .globl  probe_rx
probe_rx:
        lea     -16(%sp), %sp
        movem.l %d1-%d2/%a0-%a1, (%sp)
        moveq   #8, %d0
        cmp.l   %d0, %d1
        blt.s   9f                      | header + one byte + F7 at least
        moveq   #PORT_USB, %d0          | USB only
        cmp.l   %d0, %d2
        beq.s   1f
        moveq   #4, %d0
        cmp.l   %d0, %d2
        bne.s   9f
1:      lea     probe_hdr, %a2          | F0 00 20 3C 7D 00
        moveq   #6, %d3
2:      move.b  (%a0)+, %d0
        cmp.b   (%a2)+, %d0
        bne.s   9f
        subq.l  #1, %d3
        bne.s   2b
        move.l  %d1, %d0                | a0 = the body; d0 = its length
        subq.l  #7, %d0
        moveq   #-9, %d3                | the last byte is F7?
        cmp.b   0(%a0,%d0.l), %d3
        bne.s   9f
        bsr.w   diag_rx
9:      movem.l (%sp), %d1-%d2/%a0-%a1
        lea     16(%sp), %sp
        lea     ELK_HDR, %a3            | the instruction this replaced
        rts

| diag_rx(a0 body, d0 its length): unpack, answer, send. A body too short
| to carry seq and cmd is ignored: no reply.
diag_rx:
        lea     -32(%sp), %sp
        movem.l %d2-%d7/%a2-%a3, (%sp)
        lea     rq, %a3                 | the request; seq at +1 puts PEEK's u32 aligned
        lea     1(%a3), %a1
        moveq   #RQ_MAX, %d1
        bsr.w   unpack7
        move.l  %d0, %d5                | request bytes
        moveq   #3, %d1
        cmp.l   %d1, %d5
        blt.w   99f
        lea     rp, %a2
        move.b  1(%a3), (%a2)           | seq, a byte at a time: rq+1 is odd
        move.b  2(%a3), 1(%a2)
        moveq   #0, %d2
        move.b  3(%a3), %d2             | cmd
        move.l  %d2, %d0
        bset    #7, %d0
        move.b  %d0, 2(%a2)
        clr.b   3(%a2)                  | status: ok
        lea     4(%a2), %a1             | the payload
        subq.l  #C_HELLO, %d2
        beq.s   10f
        subq.l  #C_STATS - C_HELLO, %d2
        beq.s   20f
        subq.l  #C_PEEK - C_STATS, %d2
        beq.s   30f
        moveq   #2, %d0                 | unknown command
        move.b  %d0, 3(%a2)
        bra.w   80f

10:     moveq   #PROTO, %d0             | HELLO: u16 proto, u32 frames, the tag
        move.w  %d0, (%a1)+
        move.l  FRAMES, (%a1)+
        lea     probe_tag, %a0
11:     move.b  (%a0)+, %d0
        move.b  %d0, (%a1)+
        bne.s   11b
        bra.w   80f

20:     move.l  #(STATS_LAYOUT << 16), (%a1)+   | STATS: u16 layout, u16 0
        move.w  %sr, %d7                | one consistent instant
        move.w  #0x2700, %sr
        move.l  DTCN0, (%a1)+
        move.l  FRAMES, (%a1)+
        move.l  SAMPLES, (%a1)+
        move.l  PUSH_WAIT, (%a1)+
        lea     r_acc, %a0              | r_acc r_cnt r_max r_idle i_acc n_sw
        movem.l (%a0), %d0-%d5
        clr.l   8(%a0)                  | the peak is per STATS
        move.w  %d7, %sr
        movem.l %d0-%d5, (%a1)
        lea     24(%a1), %a1
        lea     hash_list, %a3          | then the link's buffers, hashed
        moveq   #4, %d6
23:     movea.l (%a3)+, %a0
        move.l  (%a3)+, %d0
        bsr.w   hash
        move.l  %d0, (%a1)+
        subq.l  #1, %d6
        bne.s   23b
        jsr     EXT_STATS               | layout 2's fields, at the end
        bra.s   80f

30:     moveq   #9, %d1                 | PEEK: seq, cmd, u32 addr, u16 len
        cmp.l   %d1, %d5
        blt.s   39f
        move.l  4(%a3), %d3             | address
        moveq   #0, %d4
        move.w  8(%a3), %d4             | length
        beq.s   39f
        cmpi.l  #PEEK_MAX, %d4
        bhi.s   39f
        lea     peek_ranges, %a0        | inside one range, its end included
        moveq   #NRANGES, %d2
31:     move.l  %d3, %d1
        sub.l   (%a0), %d1              | the offset into this range
        bcs.s   32f                     | below it
        add.l   %d4, %d1                | where the read ends
        move.l  4(%a0), %d0
        sub.l   (%a0), %d0              | the range's size
        cmp.l   %d0, %d1
        bls.s   33f
32:     addq.l  #8, %a0
        subq.l  #1, %d2
        bne.s   31b
        bra.s   39f
33:     move.l  %d3, (%a1)+
        movea.l %d3, %a0
34:     move.b  (%a0)+, %d0
        move.b  %d0, (%a1)+
        subq.l  #1, %d4
        bne.s   34b
        bra.s   80f
39:     moveq   #1, %d0                 | refused
        move.b  %d0, 3(%a2)

80:     move.l  %a1, %d0                | send: the reply ends at a1
        sub.l   %a2, %d0
        movea.l %a2, %a0
        lea     tx+6, %a1
        bsr.w   pack7
        lea     tx, %a0
        move.l  probe_hdr, %d1          | F0 00 20 3C
        move.l  %d1, (%a0)
        move.w  probe_hdr+4, %d1        | 7D 00
        move.w  %d1, 4(%a0)
        addq.l  #6, %d0
        moveq   #-9, %d1                | F7
        move.b  %d1, 0(%a0,%d0.l)
        addq.l  #1, %d0
        pea     2.w                     | port: USB (PORT_USB)
        clr.l   -(%sp)                  | no abort flag
        move.l  %d0, -(%sp)
        pea     tx
        jsr     SYSEX_SEND
        lea     16(%sp), %sp
99:     movem.l (%sp), %d2-%d7/%a2-%a3
        lea     32(%sp), %sp
        rts

| hash(a0 longword-aligned buffer, d0 longwords) -> d0 = h*31 + w over it.
| A change detector, not a checksum anyone relies on. Uses d1.
hash:
        move.l  %d2, -(%sp)
        moveq   #0, %d1
1:      move.l  %d1, %d2
        lsl.l   #5, %d2
        sub.l   %d1, %d2
        add.l   (%a0)+, %d2
        move.l  %d2, %d1
        subq.l  #1, %d0
        bne.s   1b
        move.l  %d1, %d0
        move.l  (%sp)+, %d2
        rts

| unpack7(a0 src, d0 len, a1 dst, d1 room) -> d0 bytes out. MidiRpc's
| packing: each group of up to 7 bytes follows a byte whose bit 6-k is byte
| k's bit 7.
unpack7:
        lea     -16(%sp), %sp
        movem.l %d2-%d5, (%sp)
        move.l  %d0, %d2                | bytes left
        moveq   #0, %d3                 | bytes out
1:      tst.l   %d2
        beq.s   9f
        moveq   #0, %d4
        move.b  (%a0)+, %d4             | the group's top bits
        subq.l  #1, %d2
        moveq   #7, %d0
2:      tst.l   %d2
        beq.s   9f
        add.l   %d4, %d4                | this byte's top bit to bit 7
        move.b  (%a0)+, %d5
        subq.l  #1, %d2
        bclr    #7, %d5
        btst    #7, %d4
        beq.s   3f
        bset    #7, %d5
3:      cmp.l   %d1, %d3
        bcc.s   4f                      | no room: drop it
        move.b  %d5, (%a1)+
        addq.l  #1, %d3
4:      subq.l  #1, %d0
        bne.s   2b
        bra.s   1b
9:      move.l  %d3, %d0
        movem.l (%sp), %d2-%d5
        lea     16(%sp), %sp
        rts

| pack7(a0 src, d0 len, a1 dst) -> d0 bytes out.
pack7:
        lea     -16(%sp), %sp
        movem.l %d2-%d4/%a2, (%sp)
        move.l  %a1, %d4                | where the output starts
1:      tst.l   %d0
        beq.s   9f
        movea.l %a1, %a2                | the group's header byte
        addq.l  #1, %a1
        moveq   #0, %d2                 | header
        moveq   #0x40, %d3              | its bit for this byte
2:      move.b  (%a0)+, %d1
        btst    #7, %d1
        beq.s   3f
        or.l    %d3, %d2
3:      bclr    #7, %d1
        move.b  %d1, (%a1)+
        subq.l  #1, %d0
        beq.s   4f
        lsr.l   #1, %d3
        bne.s   2b
4:      move.b  %d2, (%a2)
        bra.s   1b
9:      move.l  %a1, %d0
        sub.l   %d4, %d0
        movem.l (%sp), %d2-%d4/%a2
        lea     16(%sp), %sp
        rts

| ---- constants -------------------------------------------------------------
        .balign 4
peek_ranges:
        .long   0x40000000, 0x48000000  | DDR, 128 MB (ACR0 at 0x4000055e)
        .long   0x80000000, 0x80010000  | the 64 KB on-chip SRAM
        .long   AUD_RX, AUD_TX + AUD_N  | the SSI0 audio windows, RX then TX
hash_list:
        .long   DSP_REPLY, DSP_REPLY_N / 4
        .long   DSP_CTL, DSP_CTL_N / 4
        .long   AUD_RX, AUD_N / 4
        .long   AUD_TX, AUD_N / 4
probe_hdr:
        .byte   0xF0, 0x00, 0x20, 0x3C, 0x7D, 0x00
        .balign 4
        .globl  probe_tag
probe_tag:                              | the build's tag, NUL-terminated;
        .skip   TAG_BYTES               | filled in at apply time
