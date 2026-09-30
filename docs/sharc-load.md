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
- **Waverider is too expensive.** One Waverider voice costs more than the whole busy pattern added. As the owner put it, one synth playing one wave cannot cost more DSP than a whole pattern of stock synths. So the loop is to be optimised, measured with this count: one held note against silence, on the instrument, before and after each change (`docs/ideas-backlog.md` §28).
- **To make that a fair comparison,** each synth is to be benchmarked the same way: the same track, note and sustain, with no overdrive or FX, one run per engine.

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
