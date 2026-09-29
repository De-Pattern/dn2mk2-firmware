| derived from irpina/digihealth (os153.inc), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project
|
| Digitone II MAIN OS 1.11: the stock routines, sites and data the USB probe
| uses. The shape follows digihealth's os153.inc (irpina's address sheet for
| the Digitakt mk1 1.53); every value below was found again on DN2 1.11, by
| the signature of the mk1 routine it replaces, and is guarded against the
| stock image by scripts/gen_usbprobe_code.py before anything is written.
| docs/usbprobe.md carries the evidence for each one.

        | ---- the SysEx router, and its reply path ---------------------------
        .equ ROUTER,      0x4012166e    | (msg, len, source): F0 7E aside, then F0 00 20 3C
        .equ ROUTER_HOOK, 0x4012169a    | lea 0x40207ae6,%a3 -- 6 bytes, before the compare
        .equ ELK_HDR,     0x40207ae6    | F0 00 20 3C, what the hook's lea loads
        .equ SYSEX_SEND,  0x401233f2    | bool (buf, len, abort*, port); port 2 = USB
        .equ PORT_USB,    2

        | ---- the audio-frame ISR (vector 191, 1500 Hz) ----------------------
        .equ ISR_IN,      0x40025e3e    | movel 0xfc045640,%d0 -- after the register save
        .equ ISR_OUT,     0x40027b82    | addql #1,0x4058e8d4 -- the frame count, before rte
        .equ EDMA50_SADDR, 0xfc045640   | what ISR_IN's displaced instruction reads
        .equ FRAMES,      0x4058e8d4    | audio frames since boot, +1 per ISR
        .equ SAMPLES,     0x4058e558    | +32 per ISR
        .equ PUSH_WAIT,   0x402876f8    | counts 1500 down, then the DSPI push runs every frame

        | ---- the ColdFire <-> SHARC link, plain RAM -------------------------
        .equ DSP_REPLY,   0x800053a4    | the SHARC's DSPI reply, copied in each frame
        .equ DSP_REPLY_N, 2748
        .equ DSP_CTL,     0x80005e60    | the control frame pushed to the SHARC each frame
        .equ DSP_CTL_N,   2688
        .equ AUD_RX,      0x4e6df100    | SSI0/eDMA48, SHARC -> ColdFire, two 2 KB halves
        .equ AUD_TX,      0x4e6e0100    | SSI0/eDMA50, ColdFire -> SHARC, two 2 KB halves
        .equ AUD_N,       4096

        | ---- the scheduler ---------------------------------------------------
        .equ TASK_SWITCH, 0x40000438    | movel #0xffffdfff,%d0 -- a0 = incoming TCB, SR 0x2700
        .equ CUR_TCB,     0x4664acdc    | the running task's TCB
        .equ IDLE_TCB,    0x424388ac    | the prio-0 task (entry 0x400cebb4), parked
        .equ IDLE_PC,     0x400cebe2    | where it spins: bra.b *

        | ---- the clock -------------------------------------------------------
        .equ DTCN0,       0xfc07000c    | DMA timer 0 counter; the OS reads it at ten sites
        .equ TB_HI,       0x424388a0    | the OS's own 64-bit timebase over DTCN0
        .equ TB_LO,       0x424388a4
