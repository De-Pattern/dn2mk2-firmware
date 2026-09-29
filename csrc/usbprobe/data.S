| derived from irpina/digihealth (sysinfo.s), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project
|
| The probe's counters. They sit at the end of the cave, in bytes the stock
| image ships as zeros, so the bootloader's copy of MAIN OS clears them at every
| power-on and no init is needed -- where digihealth's live in a .bss that
| elekloader's core clears. The request and reply buffers are scratch, rewritten
| before every use, so they live in RAM above the BSS (RAM, set by the build).

        .balign 4
| STATS copies r_acc..n_sw with one movem: keep these six in this order.
r_acc:      .long 0                     | ISR ticks, cumulative
r_cnt:      .long 0                     | ISRs timed, cumulative
r_max:      .long 0                     | the longest ISR since the last STATS
r_idle:     .long 0                     | ISR ticks spent inside idle intervals
i_acc:      .long 0                     | ticks parked in the idle spin, cumulative
n_sw:       .long 0                     | context switches, cumulative
