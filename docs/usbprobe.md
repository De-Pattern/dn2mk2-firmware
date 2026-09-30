# usbprobe: read live ColdFire state over USB, without a reflash per question

> derived from irpina/digihealth (sysinfo.s, tools/digiusb.py, tools/winmidi.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

**Status, 2026-09-29: proven on hardware.** It answers on the owner's DN2, and its
reads of the SHARC's reply page located Waverider's DSP stop
(`docs/waverider-dsp-compare.md`, sections 10 and 11; `tools/dn2probe.py stage` and
`irptl`). Published after irpina relicensed digihealth as GPL-2.0-or-later
(irpina/digihealth `72f0183`).

## What it is

A mod (`dnfw mods apply --mod usbprobe`, `src/dnfw/mods/usbprobe.py`) that
makes a Digitone II answer three read-only SysEx commands over USB, and a
Windows client (`tools/dn2probe.py`) that asks them. Nothing on the instrument
changes unless a request arrives, apart from a few counter increments per audio
frame and per context switch.

| command | request args | reply payload |
|---|---|---|
| `HELLO` 0x01 | - | u16 protocol (2 since 2026-09-27; 1 before), u32 audio frames since boot, the build's tag (NUL-terminated) |
| `STATS` 0x02 | - | 80 bytes (layout 2; 60 in layout 1), below |
| `PEEK` 0x03 | u32 addr, u16 len (1..1024) | u32 addr, the bytes |

There is **no write command**. Any other command byte, including every one the
stock Elektron protocols use, draws status 2.

### Framing (irpina's design, unproven on DN2 until the owner's unit answers)

```
request  F0 00 20 3C 7D 00 <pack7: u16 seq, u8 cmd, args> F7
reply    F0 00 20 3C 7D 00 <pack7: u16 seq, u8 cmd|0x80, u8 status, payload> F7
status   0 ok, 1 refused argument, 2 unknown command
```

pack7 is Elektron's MidiRpc packing: groups of up to 7 bytes, each preceded by a
byte whose bit `6-k` is byte `k`'s top bit. Integers are big-endian. Replies go
out on USB only, and only requests that arrived on USB are answered.

### STATS, byte for byte (layout 1)

| off | field | what |
|---|---|---|
| 0 | u16 layout, u16 0 | 1 |
| 4 | `dtcn0` | DMA timer 0's counter (`0xfc07000c`) at the instant of the copy |
| 8 | `frames` | audio frames since boot, the firmware's own `0x4058e8d4` (+1 per ISR) |
| 12 | `samples` | `0x4058e558`, +32 per ISR |
| 16 | `push_wait` | `0x402876f8`: 1500 counted down before the first DSPI push, then 0 |
| 20 | `isr_ticks` | DTCN0 ticks spent in the audio-frame ISR, cumulative |
| 24 | `isr_count` | ISRs timed, cumulative |
| 28 | `isr_max` | longest ISR since the previous STATS (read-and-clear) |
| 32 | `isr_in_idle` | ISR ticks that fell inside an idle interval |
| 36 | `idle_ticks` | ticks the idle task spent parked at its spin, cumulative |
| 40 | `switches` | context switches, cumulative |
| 44 | 4 x u32 | `h = h*31 + word` over: the SHARC's DSPI reply `0x800053a4` (2748 B), the control frame `0x80005e60` (2688 B), SSI0 audio in `0x4e6df100` (4 KB), SSI0 audio out `0x4e6e0100` (4 KB): see the note below |
| **60** | `isr_over` | **layout 2:** audio-frame ISRs longer than one frame (87,708 DTCN0 ticks: 132.00 MHz / 1,505 frames/s), cumulative |
| 64 | `idle_in` | switches into the idle task (TCB `0x424388ac`), cumulative |
| 68 | `idle_out` | switches out of it |
| 72 | `idle_offpc` | ... of them with a resume PC other than the spin `0x400cebe2` |
| 76 | `idle_lastpc` | the last such resume PC |

The counters are copied with interrupts masked, so a reply never tears. The host
differences two replies (`tools/dn2probe.py stats`, `dsp`): CPU is
`1 - (idle - isr_in_idle) / dtcn0`, ISR load `isr_ticks / dtcn0`, the timer rate
`dtcn0 / frames * 1500`.

**Layout 2 (probe protocol 2, 2026-09-27)** appends offsets 60-79 and changes
nothing before them, so a layout-1 decoder still reads the first 60 bytes. A
decoder should read `layout` first and take only the fields its layout has.
The five are copied without masking interrupts (each is one counter the host
differences). Their code and storage are in a second cave (`csrc/usbprobe/ext.S`,
`0x402d0668`, 112 of 592 B), reached by a `jmp` where `isr_out` and
`task_switch` returned and a `jsr` after STATS's hashes, because the first cave
is full (896 of 896 B). To make room, three of timing.S's words (`t_in`,
`i_start`, `i_on`) moved to the scratch RAM (`RAM + 0x8e4..0x8ef`); each is
written before it is read, except that power-on garbage in `i_on` can credit one
bogus idle interval at the first switch out of idle after boot.

**Why layout 2, from the owner's first reading (stock + probe, 2026-09-27).**

- *CPU read 100.0 % playing and stopped.* The idle credit needs a switch out of
  the idle task whose resume PC is the spin. The yield is interrupt source 13
  of INTC0 at level 1 (`0x400012ae`: ICR13 = 1), below the audio ISR's 5, so
  it cannot nest inside an ISR and the PC test is sound on paper. So either
  the idle task is never switched in -- some task never blocks, and the CPU
  truly never idles -- or it is and the test misses it. `idle_in` = 0 says the
  first; `idle_offpc` = `idle_out` the second, with `idle_lastpc` saying where.
- *"audio out 0x4e6e0100 STILL" while a pattern plays* is correct, not a fault:
  that window is the ColdFire -> SHARC stream, and the frame ISR zeroes the
  half it owns every frame (`0x40026080..0x40026090`: `jsr 0x40133ebc` with
  0x800) unless a USB audio input is streaming (the flag `0x80005366`). The
  client now names it "USB audio to the SHARC".
- *The ISR peak ran 74-112 % of a frame on stock*, so a peak alone cannot say
  whether frames are late. `isr_over` counts them. **Own time and time lost to
  nested interrupts cannot be separated with these hooks**: the level-6 and
  level-7 handlers that can preempt the level-5 audio ISR are not hooked, so a
  peak over 100 % is the ISR's wall time, nesting included.

**Protocol 3 (2026-09-30): the idle loop is the prio-1 task, and CPU is right.**
Layout 2 answered the question above: on `wr-m6b-probe` (protocol 2) `idle_in`
stayed 0 for a whole run, so the prio-0 task was never switched in. The
probe's PEEK then read why, with no new build:

- the scheduler's ready table at `0x4664ac9c` holds one list head per
  priority (a TCB's word at +8 points at its slot; higher numbers run first:
  the MIDI task answering the probe is prio 7). Prio 0 (`0x424388ac`) and
  prio 1 (`0x4243c900`) were ready in 60 of 60 reads, so prio 0 can never run;
- prio 1 (entry `0x400cec98`) runs the boot's setup and ends at `bra.s *`
  `0x400cf0e2` (either branch of its last test lands there); its saved PC was
  that spin in 200 of 200 reads.

So `IDLE_TCB`/`IDLE_PC` (`dn2_111.inc`) now name prio 1 and `0x400cf0e2`, the
stock guard moved with them, and `PROTO` is 3. The build differs from
`waverider-m6b-usbprobe` in 14 bytes of MAIN OS (the immediates and the tag).
`dn2stats.reliability` trusts CPU from protocol 3. On the instrument
(`waverider-m6b-usbprobe3`, 2026-09-30):

| state | CPU | audio ISR | idle in/out per s |
|---|---|---|---|
| stopped | 60.5 % | 56.3 % (peak 64 %) | ~264, all from the spin |
| a Waverider pattern playing | 58-61 % | 54 % (peak 63-72 %) | ~260-287 |
| a busy pattern (the owner's) | 59 % | 55 % (**peak 75-83 %**) | ~240 |
| SAVE PROJECT | 100 % for ~1 s, then 77-83 % for ~3 s | 57-61 % (peak 76 %) | switches up to ~1,350/s |

During the save, frames/s held 1500, nothing was late and no ISR ran over a
frame: the save takes all the idle time, the audio keeps its priority. The
ColdFire's load is mostly the audio ISR, which runs every frame whether a
pattern plays or not, so playing barely moves it; the SHARC's load is not in
this figure. What a busy pattern does raise is the ISR's **peak**: the
frames where trigs, locks and LFOs land cost more, and that peak (not the
average) is the headroom to watch -- over 100 % of a frame, audio is late.

### PEEK's allow list: DN2 1.11's own map, not the mk1's

| range | why it is plain memory |
|---|---|
| `0x40000000`-`0x47ffffff` | DDR, 128 MB: ACR0 is written `0x4007e020` at `0x4000055e` (base `0x40`, mask `0x07`); `docs/memory-map.md` |
| `0x80000000`-`0x8000ffff` | the 64 KB on-chip SRAM: the `.data` copy loop at `0x4000047e` bounds it at `0x80008000`, the rest is BSS the firmware uses (`docs/dsp-control-block.md`) |
| `0x4e6df100`-`0x4e6e10ff` | the SSI0 audio windows the eDMA fills and drains (`docs/audio-dma.md`) |

Refused, and tested refused: `0xfc000000` (the MCF5441x peripherals, where a read
can clear a status bit), `0xec000000` (the FPGA register file and the DSPI boot
channel), anything straddling a range's end, length 0 or above 1024.

## The clash check

| id space | who uses it | bytes |
|---|---|---|
| Elektron dump protocol, byte after `00 20 3C` | DNX (`packages/core/src/sysex/devices.ts`, `docs/sysex-format.md`) | Digitone `0x0D`, **Digitone II `0x15`**, device `0x00` |
| Elektron file/RPC protocol | Transfer, DNX | `0x10`, then device ids `0x14` (DN1) / `0x2b` (DN2) inside the body |
| **the DN2's own router table** `0x4029ebc8` (24 slots, stock 1.11) | the firmware | populated slots **`0x00 0x04 0x0D 0x10 0x15 0x17`**; the router drops anything above `0x17` at `0x401216c4` |
| **usbprobe** | this | **`0x7D 0x00`** |

`0x7D` appears nowhere in DNX's source and is above the router's bound, so stock
1.11 drops it (tested: the stock control below) and nothing that talks to the DN2
today can collide with it.

## The ColdFire side: each site, and the evidence it is DN2's own

**No address from irpina's handoff is used.** The handoff and digihealth were
measured on a Digitakt mk1 (irpina has no DN2); their addresses served only as
the *shape* to look for. Every DN2 1.11 site below was found in DN2 1.11's own
disassembly (`out/main111.dis`) and each is guarded byte-for-byte against the
user's stock image by `scripts/gen_usbprobe_code.py` before anything is written.

| DN2 1.11 | what | how it was found |
|---|---|---|
| `0x4012166e` | the SysEx router `(msg, len, source)` | the only instruction sequence in the image that tests `cmpil #240` then `moveq #126` (F0, then 7E set aside), then walks a 4-byte header at `0x40207ae6` = `F0 00 20 3C` and indexes a 24-slot device table bounded at 23. The same routine exists byte-identically in DT mk1 1.53 and DT2 1.16 (`-0x1974`); its only reference is the status-nibble dispatch `0x40120364`, slot 0 = `0xF0` |
| `0x4012169a` | **hook**, `lea 0x40207ae6,%a3`, 6 bytes | the instruction just before the manufacturer compare; a0 = a1 = the message, d1 its length, d2 the source |
| `0x4012092c` | stock MidiRpc: source 2 or 4 is USB | its handler tests `moveq #2` / `moveb #4` against the source argument before it answers; the probe uses the same test |
| `0x401233f2` | the SysEx sender `bool (buf, len, abort*, port)` | 144-byte chunking through `0x401231a4`, gated on the USB-up word `0x446478d0`; in `0x401231a4` port 2 goes to the USB writer only (`0x40004734`), 3 to DIN, 4 both. Three of its four stock callers pass `(buf, len, NULL, 2)` as constants; the fourth is `MidiOutputStream::flush` |
| `0x40025e36` | the audio-frame ISR (vector 191, 1500 Hz) | `docs/fx-master-modulation.md`; saves every register incl. the EMAC's |
| `0x40025e3e` | **hook**, `movel 0xfc045640,%d0` | right after the register save; replayed by `isr_in` |
| `0x40027b82` | **hook**, `addql #1,0x4058e8d4` | the frame count, straight-line to the ISR's only `rte` at `0x40027bc6`; replayed by `isr_out` |
| `0x40000438` | **hook**, `movel #0xffffdfff,%d0` | the context switch: SR `0x2700` at `0x40000410`, outgoing TCB `0x4664acdc`, all registers reloaded at `0x40000452` |
| `0x424388ac`, `0x400cebe2` | the idle task's TCB, and its `bra.s *` | TASK_CREATE `entry=0x400cebb4 prio=0 tcb=0x424388ac` (`docs/emulator.md`); that entry creates the next task and parks at `0x400cebe2` |
| `0x402cf52c` | the cave, 888 of 896 B | `dnfw cave scan`: one of three 896-byte runs that pass both checks |
| `0x46f00000` | 2.25 KB of scratch RAM (request, reply, packed reply) | above BSS end `0x466b74d0`, clear of every region `docs/memory-map.md` and every mod names |

**The RTOS lead, checked** (`irpina's handoff says the mk1 RTOS is the DT2's
build relinked +0x2E4`). A 32-byte signature comparison of DN2 1.11 against DT
mk1 1.53 and DT2 1.16: TASK_CREATE `0x400012c8`, task start `0x40001314` and
`0x40001cf4` match **DT2 1.16 at delta 0** and mk1 at **+0x2E4**, and the
context-switch site `0x40000438` matches both at delta 0 on its first 12 bytes.
So DN2 1.11 carries the DT2's RTOS at the same link addresses. It did not change
any site here (each was already found by its own shape); it corroborates the
context-switch hook.

**Why no once-a-second snapshot.** digihealth builds STATS in the mk1's UI tick.
This build takes no UI hook: STATS copies cumulative counters when asked and the
host differences them, so the probe does no periodic work at all. The cost per
audio frame is two DTCN0 reads and five counter updates; per context switch,
about fifteen instructions.

**Why the counters live in the cave.** The stock image ships the cave as zeros
and the bootloader copies MAIN OS at every power-on, so they start at zero with
no init and no BSS. The cave is in cached DDR like the rest of MAIN OS.

## Compatibility

Byte overlap against every registered mod (`check_compatible`, 2026-09-27):
disjoint from arpmodes, bootscreen, fxmod, lfo4, moddest, songguard,
transients and waverider. It overlaps:

- `lfowaves` (its 3-byte stub at the cave's start) and `arpplocks` (its UI
  cave): real, the cave is theirs too;
- `midiarp`, since layout 2: its code runs from the start of the run
  `0x402d0664`, where `ext.S` now sits. arpplocks' second cave is there too;

usbprobe is not in `dnfw mods matrix`'s list on purpose: it is a diagnostic
mod, not one for everyday builds, and the matrix drives the public compatibility
page and the site. The
four hook sites are used by no other mod, nor by waverider-m5b / m5c.

## How it was checked

| gate | probe only | m5c s7 + m5b s3 + probe |
|---|---|---|
| `scripts/emu_usbprobe.py` (snapshot: stock control + build checks) | 42/42 | 42/42 |
| `scripts/emu_usbprobe.py --reset 450000000` (stock and the build booted from reset, then HELLO / STATS / PEEK / a refused PEEK) | 50/50; stock drew 0 replies to 0x7D; the switch hook ran 7 times during the boot | - |
| `scripts/emu_boot_check.py` from reset, the image's own section 3 | booted, 1 frame (control 1), no fault | booted, 1 frame, no fault |
| `scripts/emu_boot_engine.py` | exit 0 | exit 0, machine type 5 kept through save/load |
| `scripts/check_coldfire.py` (cave, and section 3 against stock) | clean | clean |
| `dnfw inspect` | 21/21 | 21/21 |

`emu_boot_check.py` itself exits 1 on both, by design: 23 of the build's 24
symbols did not run during a boot (only `task_switch` did) and it will not clear
a build on a boot alone. Those routines are the ones `emu_usbprobe.py` runs.
Emulator: digikit-up `9007c2a`.

`emu_usbprobe.py` calls the stock router with a message the way the MIDI input
task would (the emulator models no MIDI hardware) and captures the reply at the
stock sender's entry, then lets the sender run. The stock control proves the
capture works (a direct call is captured) and that stock 1.11 never answers
0x7D. What the emulator cannot show: bytes on a real USB cable, the DTCN0 rate
(the emulator does not model DMA timer 0, so it reads 0 there and the load
figures are absent), and the ISR hooks inside a running engine (they are called
directly with the registers each site hands over).

## Hardware test, in the owner's terms

Nothing below writes to the instrument except the flash itself, which the owner
does. **Close Elektron Transfer and DNX first**: Windows lets one program at a
time open a MIDI port.

### 1. The probe on its own: `00_Resources/02_Builds/usbprobe_DN2_1.11.syx`

1. Flash it the normal way with Transfer, then quit Transfer.
2. With the DN2 on and USB CONFIG set to USB MIDI (or Overbridge), run
   `python tools/dn2probe.py ports`. There must be exactly one in and one out
   port containing "Digitone II"; otherwise pass `--in N --out N`.
3. `python tools/dn2probe.py hello`. Expected:

       usbprobe  (probe protocol 1, 91234 audio frames since boot = 60.8 s)

4. `python tools/dn2probe.py stats 5`, first with nothing playing, then with a
   pattern playing. Expected, one block a second:

       reading (frames 97012)
         audio frames  1500 (1500 expected per second)   context switches 3120
         CPU  41.2 %   audio ISR  18.7 % (peak  25.0 % of a frame)   timer 66.00 MHz
         link: SHARC reply 0x800053a4 moving, control frame 0x80005e60 moving, audio in 0x4e6df100 moving, audio out 0x4e6e0100 moving

   The numbers are illustrative; the timer rate is not known for the DN2 yet
   and the first reading measures it.
5. `python tools/dn2probe.py dsp`, playing and stopped.
6. Power-cycle, repeat `hello`: the frame count starts again from near 0.

**Pass:** `hello` answers with tag `usbprobe`; audio frames read 1450-1550 a
second; the instrument plays, saves and loads exactly as stock; a PEEK outside
the list is refused (`python tools/dn2probe.py peek 0xfc045640 4` prints
"refused"). **Record the four link lines, playing and stopped: they are the
healthy baseline** the Waverider test is compared against. If the SHARC reply
reads "STILL" even on this healthy build, its hash is not a liveness signal
and the Waverider test falls back on PEEKs (below).

**Also a result, not a failure:** `no load figures: DMA timer 0 did not move`
means the OS does not run DTIM0 on the DN2; the liveness lines still hold.

**Fail:** no answer from `hello` (check the port first with `ports`); the
instrument misbehaves in any way; an EXCEPTION screen.

**Recovery:** hold **FUNC** while powering on to reach the **Early Start-up
Menu**, press **TRIG 4** for **OS UPGRADE**, and send stock
`Digitone_II_OS1.11.syx` over MIDI (`docs/flashing.md`; a dedicated
class-compliant USB-MIDI cable for the long transfer).

### 3. The save-while-playing hunt: `00_Resources/02_Builds/fxmod-lfo4fast-songguard-arpmodes-usbprobe_DN2_1.11.syx`

The owner's combination -- fxmod, lfo4-fast, songguard, arpmodes -- with the
probe, and lfo4 built with `LFO4_PROFILE` (`csrc/lfo4/profile.h`,
`scripts/build_lfo4_profile.py`, branch `local/usbprobe-lfo4prof`). lfo4 is
exactly lfo4-fast plus a DTCN0 read either side of `lfo4_on_save`,
`lfo4_on_load`, the `memcpy` / `memset` slow paths and the evaluators' bridge
call, and a counter on every stub entry and every evaluator skip. Those
counters are in lfo4's BSS and `watch` reads them with PEEK, at the addresses in
the build's `symbols.json`.

    python tools/dn2probe.py watch 30 --symbols out/fxmod-lfo4fast-songguard-arpmodes-usbprobe/symbols.json

Start it with a pattern playing, let it run five seconds, press SAVE PROJECT,
and let it run until five seconds after the save ends. Do it with the arp on UP
and no LFO4 set, as the owner's project was; then once more on stock + probe
(`usbprobe_DN2_1.11.syx`, a newer build of it for protocol 2, or the old one:
`watch` shows `-` for layout-2 columns it does not get), which is the control.
One line per 100 ms:

    t(s) frames  ISR%  peak%  over  idle-in  on_save n/us/peak ... cpy/set/skipA/skipB

**What sane numbers look like, so a broken timer is obvious:**

| column | playing, no save | during a save | broken if |
|---|---|---|---|
| frames | 150-151 per line | the same on stock (the owner measured 1,505-1,507/s through a save) | 0, or far from 150 |
| ISR% / peak% | about 51 % / 74-112 % (stock, measured) | 54-56 % average on stock | ISR% 0 while frames move: DTCN0 stopped |
| over | 0 most lines; a few at most | the question: stock against the lfo4 build | -- |
| idle-in | 0 means the idle task never ran (then CPU 100 % is real) | -- | -- |
| on_save n | 0 | about 2,192 over the whole save (one per stored sound), in the first ~0.1 s of it | stays 0 through a save: the converter hook is not reached |
| on_save us/peak | -- | about 0.6 us each by the emulator's count (157 instructions); a peak of a few us | peak of hundreds of us, or ms |
| memcpy / memset n | 0 while nothing has an LFO4 (the stub rules the copy out before calling C) | 0 with no LFO4 set | -- |
| refresh n | 0 with no LFO4 set | 0 | nonzero with no LFO4 set: the idle skip is not engaged |
| cpy/set | tens to hundreds per line | thousands per line during the serialise | 0: the stubs are not in the path |
| skipA | 16 x 150 = 2,400 per line (every track, every frame, no LFO4) | the same | 0: the evaluator skip is not engaged |
| skipB | 0 to a few (evaluator B runs per note event) | -- | -- |

Microseconds use the rate `watch` measures from DTCN0 against the frame count
(132.00 MHz on the owner's unit). A reading of 0 us everywhere with nonzero
counts means DTCN0 did not move, as in the emulator.

**What it will say.** If `over` rises during the save on the lfo4 build and not
on stock, a frame is going late, and the columns beside it say whether lfo4's
own pieces spent the time. If lfo4's pieces stay near zero and `over` still
rises, the time is being lost in stock code that runs slower because of lfo4,
which points at memory and cache effects rather than at any hook.

### 2. Waverider: `00_Resources/02_Builds/waverider-m5c-usbprobe_DN2_1.11.syx`

m5c's section 7 with m5b's section 3, plus the probe; nothing else differs
from those builds.

Before the trig (a Waverider track set up, nothing trigged yet):

    python tools/dn2probe.py hello
    python tools/dn2probe.py dsp
    python tools/dn2probe.py stats 3
    python tools/dn2probe.py peek 0x800053a4 64      the SHARC's DSPI reply, head
    python tools/dn2probe.py peek 0x80005e60 64      the control frame to it, head
    python tools/dn2probe.py peek 0x4e6df100 256     audio coming back from the SHARC

Trig the Waverider track once, wait for the silence, and run the same six again,
twice, a few seconds apart.

How to read it:

- **frames still 1500 a second, SHARC reply STILL where it was moving before,
  audio in STILL or all zeros**: the ColdFire is healthy and the SHARC stopped.
  That is the halt, seen from the ColdFire side.
- **frames still 1500, the reply still moving, audio in zeros**: the SHARC runs
  but its output is silent: a mix/FX-chain fault rather than a halt.
- **frames stop**: the ColdFire's own audio ISR stopped; the fault is not only
  the DSP's.
- **no answer at all**: the ColdFire itself is stuck (the MIDI input task does
  not run).

Keep every output: two PEEKs of the reply a few seconds apart show whether the
SHARC is still writing anything, word by word.

## Files

| file | |
|---|---|
| `csrc/usbprobe/` | the ColdFire code: `timing.S` (ISR and idle timing), `probe.S` (the channel), `data.S` (counters), `ext.S` (STATS layout 2, second cave), `dn2_111.inc` (the sites) |
| `csrc/lfo4/profile.[ch]`, `scripts/build_lfo4_profile.py` | lfo4's pieces timed, for the save-while-playing build (local branch only) |
| `scripts/gen_usbprobe_code.py` | assembles it, guards the sites, writes `src/dnfw/mods/usbprobe_code.json` |
| `src/dnfw/mods/usbprobe.py` | the mod |
| `scripts/build_usbprobe.py` | a build, a section-7 swap, and the gate layout under `out/<name>/` |
| `scripts/emu_usbprobe.py` | the emulator tests |
| `tools/dn2probe.py`, `tools/winmidi.py` | the host |

## Live view: `tools/dn2live.py`

The MIDI page (`scripts/midi_live.py`'s, served unchanged) with a probe panel
at its foot, from one process holding the DN2's USB MIDI in and out:

    powershell -File tools/dn2live_launch.ps1        then http://127.0.0.1:8737
    python tools/dn2live.py [--rate 10] [--no-midi]

It asks HELLO, then STATS with one request in flight at a time (10 Hz; 25 or
50 with the MIDI view off), times each round trip, and shows frames/s against
1500, ISR average and peak, context switches/s, the four link hashes, the
timer rate, a 60 s graph, a late/missed indicator, and marks (**M** or the
Mark button). Every reading and mark goes to `out/dn2live/<stamp>.csv`, and
every event to `<stamp>.jsonl`. With no answer it says "no probe on this
firmware" and the MIDI view goes on.

**What polling costs the instrument.** The probe answers in the MIDI input
task (the router hook), not the audio ISR; interrupts are masked only for the
copy of ten counters. So the ISR figures are not inflated by polling, but each
request adds task switches. "Measure probe cost" polls at 5 then 25 Hz and
fits switches/s against the rate; the panel then shows the probe's share and
the net figure. 10 Hz is the default.

**The decoder** (`tools/dn2stats.py`, `LAYOUTS` and `FIELDS`) reads each reply
with its own layout's table: layout 1's 60 bytes, and layout 2's five appended
words (`isr_over`, `idle_in`, `idle_out`, `idle_offpc`, `idle_lastpc`). A
layout above 2 is read as layout 2 plus raw words with their per-reply
difference, assuming it appends as 2 did. Layout 2 adds a tile and a graph
lane for ISRs over a frame (they also count as late), and an idle-task tile.
**CPU is trusted from protocol 3** (above); on protocols 1 and 2 it is
marked unreliable, and on layout 2 the tile shows the idle counters' verdict. The
fourth hash is labelled "USB audio -> SHARC" and STILL is shown as expected,
not as a fault, on every layout. The ISR's own vs nested time is not shown:
the hooks cannot separate them (above).

**lfo4's timers** (a `build_lfo4_profile.py` build) are not in STATS. With
`--symbols out/<build>/symbols.json` (launcher: `-Symbols`), dn2live PEEKs lfo4's
136-byte profile block after every STATS, as `dn2probe.py watch` does, and
adds a per-piece table (calls/s, us/s, recent and boot peaks) and a graph lane
of us per reply. It is a second request per reading: it halves the rate the
round trip allows and doubles the probe's own cost.

| file | |
|---|---|
| `tools/dn2live.py` | wiring, HTTP and SSE |
| `tools/dn2port.py` | winmm in (callback, buffers re-posted outside it) and out |
| `tools/dn2poll.py` | HELLO/STATS, round trips, states, the cost calibration |
| `tools/dn2stats.py` | the STATS decoder and the readings |
| `tools/dn2log.py` | the CSV and JSONL |
| `tools/dn2live_panel.js`, `.css` | the panel |
| `tools/dn2live_launch.ps1` | kill stale holders, start, open |
| `test/test_dn2live.py` | decoder (incl. replies captured from the probe in the emulator), poller, log, server with a fake port |
