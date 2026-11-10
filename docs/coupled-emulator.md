# The coupled emulator: what is faithful, what is approximate (v0.48 audit)

`scripts/emu_coupled.py` runs the modified ColdFire image (digikit's ColdFire emulator, the
stock 1.11 snapshot with the build installed) and the modified SHARC image (digikit's SHARC
runner, `sharc_waverider_m5.py`) together, one audio period at a time. This page says, for
each place where the two meet or where time is involved, what the harness does and how
close that is to the unit. A result from it is evidence of category **1** (the actual modified
ColdFire and SHARC code together) only for what the table below calls faithful; anything that
leans on an approximation is said so in the result.

## One period

A period is one DSP block: 32 frames at 48 kHz, 1,500 a second. In each:

1. the ColdFire's UI runs a slice of `UI_SLICE` (1 M) instructions, its PIT/DMA timers on
   digikit's instruction clock;
2. the sequencer's timer ISR (`0x400D987A`, vector 121) is entered as many times as the
   tempo gives (below);
3. the ColdFire's audio ISR (`0x40025E36`) runs to its `rte` (`0x40027BC6`);
4. the frame it built (`0x80005E60`, 2,688 bytes, big-endian) is byte-swapped into the DSP's
   `unpack_call`;
5. the newest ColdFire transmit half with a new sequence number is copied into the DSP's
   receive page (the page the DSP's dispatch is on), the IN samples (`input`) poked into its
   input buffer;
6. the DSP's block runs (8 M instructions at most; it must return to the unpack's return);
7. the DSP's status (its reply page tail) is written to the ColdFire's reply tail
   (`0x80005E40`), and its transmit slots 14..15 to both halves of the ColdFire's receive page.

## Audit

| what | the harness | the unit | verdict |
|---|---|---|---|
| **Audio ISR cadence** | once per period, at the period's boundary (entered by a call with the registers and PC/SR kept, left at its own `rte`) | an interrupt every 0.67 ms, landing anywhere in the UI's code | **faithful in count and order** (one ISR per DSP block; the frame counter `0x4058E8D4` +1 each). **Approximate in placement**: the ISR never lands in the middle of UI code here, so a race between the two (a half-written value the ISR reads) is not exercised. `emu_waverider_menu.py --isr-frame` and the gate's fuzz step cover preemption on the ColdFire alone |
| **UI time against audio time** | 1 M UI instructions a period; the timers count instructions at digikit's 18.72 M a second, so a period is about 53 ms of the OS's own time against 0.67 ms of audio | the OS's 60 Hz timer wheel and the 1.5 kHz audio interrupt on one clock | **approximate**: the UI and its timers run about 80 times faster against the audio than on the unit. Timeouts the UI counts in its own ticks (the panel's knob guards, a key's hold time) are faithful *within the UI*; anything the UI counts in audio frames (`FRAMES`: the value-under-knob window, repeats) is faithful against the audio. A test that depends on the ratio of the two must say so |
| **Sequencer clock** | the timer ISR entered `24 x BPM / 15 / 1500` times a period (the frame's word 108 is BPM x 120; 24 entries a sixteenth, measured in `emu_jump.py`), the fraction carried over | a DMA timer interrupt at that rate, exactly | **faithful in rate** (no drift: the remainder is carried), **approximate in phase**: an entry lands at a period boundary, up to one period (0.67 ms) late, always just before that period's audio ISR. Step order and the steps themselves are the firmware's |
| **ColdFire -> DSP packets** | the newest transmit half with a new sequence number, once a period | the TDM DMA sends both halves in turn, every frame | **faithful when the ColdFire writes at most one new packet a period** (the link's ISR fills one transmit half an ISR; the harness counts `delivered`, so a test can compare it with the ColdFire's own count). If both halves changed within a period the older would be skipped here: a loss the unit would not have. No bit errors, no reordering are modelled |
| **DSP -> ColdFire status and replies** | the status words and slots 14..15 copied after the DSP's block; the ColdFire reads them in the next period | the SPI reply ring and TDM slots, refreshed each frame | **faithful in content, one period of latency**; the unit's own latency is of the same order (the reply of block n is read during block n + 1) but its exact phase is not modelled |
| **Buffer and directory sync** | none forced: the ColdFire's mirror of the pool (`SM.MIRROR`) and the DSP's directory (`SMP_POOL_DDR`) are each written only by their own code and the link | the same | **faithful**, except the setup shortcuts the tests take (below) |
| **The DSP's RAM check (CMD_PROBE)** | finished the moment it starts with the whole-part verdict (`pres` 1), instead of its ~1,000 blocks | the real check | **a shortcut** (`_shortcut_probe`). Everything after it is the two sides' own; `probe()` itself is held to its model by the SHARC runner's link part. A test can turn it off (`shortcut_probe = False`) at the cost of hours |
| **The DSP's time budget** | a block always completes (8 M instruction cap); instructions counted, not cycles | a block must finish in its frame; memory stalls dominate (`docs/timing-model.md`) | **not modelled**: an overrun on the unit is not one here. The meter and the guard's own tests cover load |
| **Inputs** | `input(block)` poked into the DSP's input buffer at its dispatch, as the per-block driver converts them | the codec's samples by DMA | **faithful at the DSP's input buffer**; the codec, its gain and its latency are not modelled |

### The setup shortcuts each coupled test takes

- `emu_coupled_thres.py`: the track's machine byte poked to ONESHOT; the pool's mirror
  emptied; `smp_dir_ok` set; the RECORDER opened by calling `rec_combo`; THRES, SRC, R.STRT
  set by writing their variables. The ARM is a real encoder turn.
- `emu_coupled_recplay.py` (v0.48): the machine through `smp_machine_commit` (the UI's
  commit path, called from the harness); the pool's mirror emptied; `smp_dir_ok` set; the
  RECORDER through FUNC + VOICE when the panel names those keys (else `rec_combo`, recorded in
  its report); SRC and R.LEN written; YES, TRIM/NAME/ASSIGN, STRT's turn, KEYBOARD and the
  note are panel keys and encoders.

### What a coupled result can and cannot claim

It can claim that the ColdFire's code and the DSP's code, as built, carry a command, a
recording, a selection and a render between them correctly in the order the period gives.
It cannot claim anything about the unit's timing margins (an ISR landing mid-update, a
packet lost to a busy period, a DSP block overrunning), the codec, or the panel hardware.
Those stay category 3 until measured on the unit.
