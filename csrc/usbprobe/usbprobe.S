| derived from irpina/digihealth (sysinfo.s), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project
|
| The USB probe, as one translation unit: it is linked into a single code cave
| in MAIN OS, and the four hooks jsr into it (scripts/gen_usbprobe_code.py).
| timing.S keeps the counters, probe.S answers the SysEx channel, data.S is the
| counters' storage at the cave's end.
#include "dn2_111.inc"
#include "layout.inc"

        .text
        .globl  usbprobe_start
usbprobe_start:
#include "timing.S"
#include "probe.S"
#include "data.S"
        .globl  usbprobe_end
usbprobe_end:
