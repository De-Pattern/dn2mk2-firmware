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
- **A percentage needs the core clock,** which is not yet read (see *Open*). At 1,500 frames/s, a frame has 533,000 cycles at 800 MHz and 667,000 at 1 GHz, the ADSP-21569's range (`docs/hardware.md`). That puts silent at 62-78 %.
- **Waverider is too expensive.** One Waverider voice costs more than the whole busy pattern added. As the owner put it, one synth playing one wave cannot cost more DSP than a whole pattern of stock synths. So the loop is to be optimised, measured with this count: one held note against silence, on the instrument, before and after each change (`docs/ideas-backlog.md` §28).
- **To make that a fair comparison,** each synth is to be benchmarked the same way: the same track, note and sustain, with no overdrive or FX, one run per engine.

## Open

- **The core clock.** The boot stream's init block (the one loading at `0x28242c3c`) holds a table naming CGU0 `0x3108d000` and CGU1 `0x3108e000`, each with a pointer to its settings. The settings are zero in the image, so the MSEL and CSEL values are written by code, not read from data. Not traced yet.
- **What the count covers.** This is the handler's own count. Whether it includes all voice rendering (the engine task at `0x1c9fe7` loops on the handler) or leaves some DSP work out has not been read.
