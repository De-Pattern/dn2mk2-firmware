| derived from irpina/digihealth (sysinfo.s), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project
|
| Where the probe's scratch buffers go. RAM and TAG_BYTES come from the build
| (scripts/gen_usbprobe_code.py, -D): RAM is above the BSS end 0x466b74d0, clear
| of every region docs/memory-map.md lists as claimed. The buffers are
| rewritten before every use, so power-on garbage in them is harmless.

        .equ rq,  RAM                   | a request, unpacked (RQ_MAX + 4)
        .equ rp,  RAM + 0x20            | a reply before packing: 4 + 4 + PEEK_MAX
        .equ tx,  RAM + 0x440           | a reply as sent: 6 + 1180 + 1
        .equ RAM_END, RAM + 0x900
| Two timestamps, moved out of the cave for layout 2's room: each is written
| before it is read, so power-on garbage in them is harmless.
        .equ t_in,    RAM + 0x8E4             | DTCN0 at the ISR's entry
        .equ i_start, RAM + 0x8E8             | DTCN0 when the idle task was switched in
| And the flag that an idle interval is open. Power-on garbage here can credit
| one bogus interval, at the first switch out of idle after boot, and never
| again: the next switch in writes it.
        .equ i_on,    RAM + 0x8EC
