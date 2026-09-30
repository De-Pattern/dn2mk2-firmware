# SHARC load: the stock cycle count, and benchmarking the synths

## The count is already in the stock reply

The SHARC's per-frame handler (sw `0x1c9d6b`) ends by storing its own EMUCLK cycle count in word 0 of the reply ring. It swaps the halves, so a big-endian reader gets the count in order (`docs/waverider-dsp-compare.md`; `docs/for-digikit-coldfire-sharc-link.md` §7 and §8). **[D]**

The ColdFire receives the reply at `0x800053a4` every frame, so a big-endian u32 there is the number of cycles that frame took. It needs no DSP change, only a usbprobe build to read it:

    python tools/dn2sharc_load.py silent            the baseline, with nothing sounding
    python tools/dn2sharc_load.py waverider-1       then one held note per synth

Each run PEEKs word 0 N times (100 by default) and prints the median, the 5th and 95th percentiles and the extremes. It also prints the difference from the latest `silent` row, then appends the row to `out/sharc-load.csv`. On the probe page, the watch `0x800053a4+4:u32` shows the count live.

## First readings, 2026-09-30

Taken on `waverider-m6b-usbprobe`, 20 readings each, from the reply captures (not yet with the tool). **[V]**

| state | cycles per frame | over silent |
|---|---|---|
| silent | 415,900-416,500 | -- |
| the owner's busy pattern | 418,600-420,400 | about +3,500 |
| one Waverider note held | 423,800-424,900 | about **+8,000** |

- **Most of the SHARC's work is fixed:** about 416,000 cycles a frame with nothing sounding.
- **As a share of a frame:** the core runs at 1 GHz (*The clock*, below), so a frame at 1,500 frames/s has 666,667 cycles. Silent is **62.4 %**, the busy pattern **62.9 %**, one Waverider note **63.6 %**. That leaves about 36 % of the SHARC free.
- ~~**Waverider is too expensive.**~~ **Withdrawn the same day:** the benchmark below found that word 0 misreads around a Waverider track, and that in the emulator Waverider is the lightest engine. What this bullet said, kept for the record: one Waverider voice costs more than the whole busy pattern added. As the owner put it, one synth playing one wave cannot cost more DSP than a whole pattern of stock synths. So the loop is to be optimised, measured with this count: one held note against silence, on the instrument, before and after each change (`docs/ideas-backlog.md` §28).
- **To make that a fair comparison,** each synth is to be benchmarked the same way: the same track, note and sustain, with no overdrive or FX, one run per engine.

## The benchmark, 2026-09-30, and why word 0 did not settle it

On the instrument (`waverider-m6b-usbprobe3`), in a fresh project, with overdrive and sends at 0 and the compressor off, the owner ran track 1 through each engine on a pattern (one trig, 16 steps long). Each row below is 150 PEEKs of word 0, in the order taken. **[V]** for the numbers; see below for what they measure.

| order | state | median cycles |
|---|---|---|
| 1 | silent, fresh project | 413,746 |
| 2 | FM Tone playing | 414,207 |
| 3-4 | FM Drum playing / stopped | 398,668 / 372,067 |
| 5-6 | WaveTone playing / stopped | 377,700 / 379,037 |
| 7-8 | Swarmer playing / stopped | 378,963 / 375,055 |
| 9-10 | Waverider playing / stopped | 313,936 / 259,812 |
| 11-12 | FM Tone stopped (twice) | 260,128 / 259,725 |
| 13 | FM Tone playing | 347,323 |
| 14 | all tracks muted, stopped | 413,585 |
| 15 | unmuted, stopped (twice, 20 s apart) | 413,759 / 413,800 |
| 16 | MIDI on all 16 tracks (twice, 60 s apart) | 413,406 / 413,952 |
| 17 | track 1 Waverider, never played | 413,774 |
| 18-19 | Waverider playing, then stopped | 327,683 / **259,667, held** |
| 20 | FM Tone playing, sends up | 413,868 |
| 21-23 | Waverider playing / stopping / stopped, sends up | 308,417 / 308,179 / 308,283 |
| 24 | FM Tone playing, sends up | 404,954 |
| 25 | Waverider playing, more FX and the filter | **271,204** |

What these rows show:

- **The floor is about 413,700.** It holds with no synth anywhere (MIDI on every track), steady over a minute. Muting does not change it.
- **Once a Waverider note has played, word 0 falls 90,000-154,000 below that floor,** and stays low after the note stops. Switching machine or toggling mutes lifts it again, but not every time.
- **Adding FX and a filter lowered it further** (row 25).
- **The owner heard every effect throughout.** No work audibly went missing.

**So word 0 is not the SHARC's total load around a Waverider track.** Adding work cannot read as less work. The reply's word 0 is the span between two EMUCLK reads in the command handler (sw `0x1c9d89` -> `0x1c9e47`). Between them, the handler reads a command word and dispatches through the table `0x268a68` (`jump (m13,i8)` at `0x1c9dbf`). Whether that span includes waiting (for the link, or the next frame), and so shifts with timing, is **[O]**: the linear decode desyncs right after the dispatch. The register the span keeps its start in, R14, is saved and restored by `machine5_live.asm`, which has a single exit.

## The engines in the emulator: instructions per block

digikit's SHARC runner, the DN2 1.11 engine-init snapshot, runs sw `0x1c2712` (frame unpack and machine dispatch). Track 0 is on each machine and tracks 1-15 are MIDI, three blocks each, with the last block shown. These are instructions executed, not cycles: a relative measure. **[E]**

| track 0 | parameters (owner) | no note | note | idle over MIDI |
|---|---|---|---|---|
| MIDI | -- | 152,780 | 153,502 | -- |
| **Waverider** | 3 | 154,605 | 155,327 | **+1,825** |
| WaveTone | 23 | 160,957 | 162,359 | +8,177 |
| FM Drum | 30 | 161,549 | 162,451 | +8,769 |
| Swarmer | 7 | 161,747 | 162,493 | +8,967 |
| FM Tone | 30 | 163,893 | 164,635 | +11,113 |

- **The stock image** gives every one of types 0-4 exactly 238 fewer instructions: that is our entry check. Our build leaves the stock engines untouched.
- **Every stock engine does nearly all its work whether or not a note plays;** a note adds 700-1,400. The owner's guess, that the engines keep their machinery computed at all times, holds.
- **The parameter count does not set the cost.** Swarmer, with 7 parameters, costs as much as FM Drum with 30.
- **Waverider** skips that standing work, and its note adds about 720, about 22 per sample: the reader's loop.

**The two measures disagree in size.** Changing the machine moves this routine by at most 11,000 of 153,000 instructions, while word 0 moved by 150,000 cycles on the instrument. So word 0's swings are not this routine's work.

**Next:** a load figure that covers the whole frame. Either our own EMUCLK stamps at the per-block routine's entry and exit, written to reply bytes 4-0x15 (a Waverider build; the ColdFire reads none of those bytes), or the handler run whole in the emulator, to see what the dispatched command does between the two reads.

## The whole load, from the idle task (2026-09-30, awaiting the instrument)

The SHARC runs FreeRTOS. **[D]**
- `vTaskStartScheduler` (sw `0xb887db`, in L2 code that loads at `0x20000000`, i.e. sw `0xb80000`) creates the idle task with `r8 = "IDLE"` (`0x2d0760`) and `r4 = 0xb88aa6`.
- `prvIdleTask` has no idle hook and no `IDLE` instruction. It spins:

  ```
  b88aab  call prvCheckTasksWaitingTermination
  b88ab2  if more than one task is ready at the idle priority: yield (IRPTL bit 31)
  b88abb  jump (pc,-0x10)   -> b88aab
  ```

So its time is the SHARC's spare time, and the build measures it (`csrc/waverider/sharc/idle_load.asm`, `dnfw.waverider.dsp` patch 4):
- **The patch.** The back edge at sw `0xb88abb` becomes `JUMP 0x16f500`, in L1 block 1's free tail, between the directory and table 0.
- **Each pass.** The stub reads EMUCLK, and adds the cycles since the previous pass to a running total when they are fewer than 4,096. A longer gap means the idle task was preempted by real work.
- **What it publishes.** The total, halves swapped like word 0, goes to reply word 1 of both reply pages (`0x2c49d4`, `0x2c59d4`); the ColdFire reads it at `0x800053a8`. The stub uses R8-R10 only, saved in its own area at `0x2de100`, and jumps back to `0xb88aab`.
- **The host side.** `tools/dn2sharc_load.py LABEL --idle` takes the total and the ColdFire's frame count from STATS, twice a second apart, and computes load = 1 - d(idle) / (d(frames) x 666,667). The probe page's **Watch SHARC** shows the total as SHARC_IDLE.
- **What it can miss.** An interrupt shorter than 4,096 cycles that lands inside the idle loop is counted as idle. That reads the load slightly low.

**Checked in digikit's runner** (`scripts/sharc_idle_load_check.py`, 7 of 7, on the engine-init snapshot):
- the patched loop goes round;
- every pass is counted;
- R8-R10 are intact at every return;
- with a fed clock, the total is exactly the sum of the short steps, across a counter wrap;
- both reply pages hold it.

The Waverider gate on the instrument's captured frames still passes 6 of 6. The build is `waverider-m6c-idle-usbprobe_DN2_1.11.syx`; its section 3 is `usbprobe3`'s but for the HELLO tag.

## The idle measure on the instrument, and the stock control (2026-09-30)

`dn2sharc_load.py --idle`, 6 one-second intervals each. It is steady to 0.1-0.3 % within a state. **[V]**

| state | `waverider-m6c-idle-usbprobe` | `stock-idle-usbprobe` (no Waverider code) |
|---|---|---|
| first reading, MIDI on all tracks | 41.6 % (Waverider had played with FX) | **64.5 %** (fresh project) |
| FM Tone playing | 56.7 % (54.6-58.0) | 64.7 % (with FX and envelope); 63.5 % (cleared) |
| FM Tone stopped | 64.7 % | 62.9 % |
| MIDI on all tracks, again | 64.7 % | **62.9 %** |
| Waverider played, then stopped | 60.4 % | -- |

- **Stock is flat:** 63-65 % whatever plays. The engine runs its full machinery every frame.
- **Only the Waverider build drops,** to 41.6 %, after a Waverider note. It stays down across machine changes until something resets it. The drop is about 23 points, 154,000 cycles a frame: the same step reply word 0 showed.
- **So Waverider's code stops about 23 % of work that stock always does.**
- **It is inaudible on the instrument:** the owner heard every effect in the low state.
- **What stops is [O].** One candidate fits both facts: the per-track audio records in the reply (`+0x1c..+0xa9c`, 28 channels of 24-bit, the stream Overbridge carries), which the instrument's own outputs never play. Next: read those records with the probe in the low state on a Waverider build.

## Ruled out: a skipped render pass, and the Overbridge stream (2026-09-30)

**The Overbridge stream.** In the low state, with Overbridge enabled and its app open, its input meters showed Main, track 1 (FM Tone) and track 2 (Waverider) all carrying audio. The reply's `+0x1c..+0xa9c` records stayed empty whether or not Overbridge was enabled and streaming, so they are not that stream (the per-track-audio reading in section 8 of the digikit note is withdrawn). **[V]**

**A second pass of the per-block routine.** `block_count.asm` (the build `waverider-m6d-count-usbprobe`) counts every pass of the machine dispatch into reply word 2:

| state | SHARC load | blocks per frame |
|---|---|---|
| high: FM Tone on track 1, no Waverider yet | 63.0 % | 1.00 |
| low: after Waverider played on track 2 | 45.8 % | 1.00 |

The routine runs once a frame in both states, so the missing ~17-23 points are not a pass that stops. **[V]**

**What is left:** either each pass does less in the low state, or the work is outside the per-block routine. Next: reproduce the latch in digikit's runner, running MIDI, then a Waverider trig, then stop, then FM Tone frame by frame, and compare what each block executes.

## The clock: 1 GHz, from the init program

The SHARC boot stream carries two programs: a small init program entered at sw `0x120230`, then the main one (digikit `docs/sharc/SPEC-FINDINGS.md`). The init program is block 1, which loads at bw `0x282403f0` (sw `0x1201f8`, 10,312 bytes). It sets the clocks. Read with selmap (`js216/selache`) and digikit's `sharcimm.py`. **[D]**

- **CLKIN.** The first instruction, `r8=0x1312d00`, hands 20,000,000 to the power driver's init (`0x120b65`), which stores it in the device record. That is the 20 MHz crystal Y4 (`docs/hardware.md`).
- **The settings record.** `0x120532` builds it on the stack and passes it to `0x120c98`: CLKIN, a flag half-word `0x0100`, then **`0x06a10464`** and **`0x00000310`**.
- **The unpacking.** `0x120a06` builds the registers from those two words and compares them with the live ones. It reaches CGU0 through the base table at `0x242c88`, which is why the registers never appear as constants in the code:
  - CGU_CTL is `MSEL << 8 | DF`, masked with `0x7f01`. MSEL is word 1 bits 0-6 = **100**; DF is bit 7 = **0**.
  - CGU_DIV fields:

    | field | bits of word 1 | value |
    |---|---|---|
    | CSEL | 9-13 | **2** |
    | SYSSEL | 14-18 | 4 |
    | S0SEL | 19-21 | 4 |
    | S1SEL | 22-24 | 2 |
    | DSEL | 25-29 | 3 |
    | OSEL | word 2, bits 0-6 | 16 |

So PLLCLK = 20 MHz x 100 = 2 GHz, and **CCLK = PLLCLK / CSEL = 1 GHz**. The rest are:

| clock | from | frequency |
|---|---|---|
| SYSCLK | / 4 | 500 MHz |
| SCLK0 | SYSCLK / 4 | 125 MHz |
| SCLK1 | SYSCLK / 2 | 250 MHz |
| DCLK | / 3 | 667 MHz (DDR3-1333) |
| OCLK | / 16 | 125 MHz |

Three independent points agree:
- the dividers are ADI's standard 1 GHz setup for this family;
- the DDR clock comes out at a standard DDR3 speed;
- the part is marked `ADSP-21569KBCZ10`, the 1 GHz speed grade (`docs/hardware.md`).

**[D]**, not measured: nothing here has timed the core against a known interval. In the whole section, the CGU bases appear only in this init block's table. So the main program is not seen reprogramming the PLL, but a call through that table from the main program has not been ruled out.

## Open
- **What the count covers.** This is the handler's own count. Whether it includes all voice rendering (the engine task at `0x1c9fe7` loops on the handler) or leaves some DSP work out has not been read.
