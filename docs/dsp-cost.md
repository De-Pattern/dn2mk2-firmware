# What each machine costs the DSP (v0.39 source, measured 2026-11-03; v0.33 table below it)

One voice of each machine sounding, eight blocks after its note, in the SHARC runner
(`scripts/sharc_waverider_m5.py --steps cost`, step 3c), less a run with nothing sounding.
Per block (32 samples): the instructions our code runs, and its memory accesses by where they
land. On the unit an access to L2 costs several instruction times and one to DDR about ten
(complex-ping's measurements, `docs/others-dn2-research.md`); the estimate is instructions +
4 x L2 + 10 x DDR, against the frame's 666,667 cycles. It is an estimate: the unit's meter
(FUNC held on a PERC or Monomachine page) is the measure.

| machine | instructions | L2 accesses | DDR accesses | estimate | of the frame |
|---|---|---|---|---|---|
| SID 6581 | 29,507 | 7,046 | 0 | 57,691 | 8.7 % |
| DPRO-DDRW | 25,876 | 6,839 | 217 | 55,402 | 8.3 % |
| VO-6 | 30,838 | 3,845 | 171 | 47,928 | 7.2 % |
| PI-SD | 15,033 | 110 | 1,803 | 33,503 | 5.0 % |
| PI-RS | 14,766 | 108 | 1,779 | 32,988 | 4.9 % |
| TRX-CY | 20,646 | 2,434 | 144 | 31,822 | 4.8 % |
| EFM-CY | 20,224 | 2,246 | 188 | 31,088 | 4.7 % |
| DPRO-DENS | 14,259 | 3,681 | 162 | 30,603 | 4.6 % |
| DPRO-WAVE | 13,179 | 2,728 | 187 | 25,961 | 3.9 % |
| TRX-MA | 15,091 | 2,347 | 0 | 24,479 | 3.7 % |
| PI-MT | 13,924 | 497 | 783 | 23,742 | 3.6 % |
| TRX-CP | 15,175 | 1,985 | 0 | 23,115 | 3.5 % |
| TRX-S2 | 15,426 | 1,629 | 37 | 22,312 | 3.3 % |
| PI-BD | 11,755 | 478 | 729 | 20,957 | 3.1 % |
| EFM-CB | 13,004 | 1,757 | 92 | 20,952 | 3.1 % |
| PI-ML | 14,060 | 1,073 | 68 | 19,032 | 2.9 % |
| EFM-RS | 11,372 | 1,660 | 92 | 18,932 | 2.8 % |
| TRX-OH | 11,691 | 1,268 | 141 | 18,173 | 2.7 % |
| TRX-CH | 11,685 | 1,268 | 141 | 18,167 | 2.7 % |
| WERP | 5,320 | 0 | 1,253 | 17,850 | 2.7 % |
| REPITCH | 5,211 | 0 | 1,253 | 17,741 | 2.7 % |
| ONESHOT | 5,001 | 0 | 1,253 | 17,531 | 2.6 % |
| SLICE | 4,948 | 0 | 1,254 | 17,488 | 2.6 % |
| GRID | 4,913 | 0 | 1,253 | 17,443 | 2.6 % |
| PI-CC | 8,575 | 136 | 807 | 17,189 | 2.6 % |
| PI-RC | 8,337 | 126 | 787 | 16,711 | 2.5 % |
| EFM-CP | 10,376 | 1,300 | 44 | 16,016 | 2.4 % |
| PI-HH | 7,382 | 134 | 783 | 15,748 | 2.4 % |
| EFM-SD | 9,402 | 1,439 | 44 | 15,598 | 2.3 % |
| EFM-XT | 9,943 | 1,220 | 44 | 15,263 | 2.3 % |
| EFM-HH | 8,617 | 1,149 | 68 | 13,893 | 2.1 % |
| EFM-BD | 8,775 | 1,025 | 44 | 13,315 | 2.0 % |
| PI-MA | 7,366 | 529 | 0 | 9,482 | 1.4 % |
| TRX-CB | 5,404 | 791 | 21 | 8,778 | 1.3 % |
| TRX-SD | 3,558 | 265 | 70 | 5,318 | 0.8 % |
| TRX-CL | 2,707 | 489 | 23 | 4,893 | 0.7 % |
| TRX-RS | 3,729 | 159 | 47 | 4,835 | 0.7 % |
| TRX-B2 | 3,194 | 133 | 20 | 3,926 | 0.6 % |
| TRX-BD | 902 | 108 | 36 | 1,694 | 0.3 % |
| GND-SN | 875 | 145 | 20 | 1,655 | 0.2 % |
| STRETCH | 1,650 | 0 | 0 | 1,650 | 0.2 % |
| GND-NS | 753 | 188 | 0 | 1,505 | 0.2 % |
| TRX-XT | 879 | 67 | 16 | 1,307 | 0.2 % |
| TRX-XC | 886 | 66 | 12 | 1,270 | 0.2 % |
| GND-IM | 491 | 86 | 0 | 835 | 0.1 % |

(Negative counts are under the empty run's and shown as 0; the sample machines' L2 count is
under it too, STRETCH's whole row. The empty run: 15,152 instructions, 943 L2, 420 DDR. Run:
`python3 scripts/sharc_waverider_m5.py --image ../Digitone_II_OS1.11.syx --steps cost --tag before`,
6,693 s; report `out/waverider/m5_report_before.json`.)

## The Monomachine machines since v0.33

| machine | v0.33 estimate | now | DDR accesses v0.33 -> now | what changed |
|---|---|---|---|---|
| DPRO-DDRW | 108,076 (16.2 %) | 55,402 (8.3 %) | 2,380 -> 217 | v0.36 its 976 table words in L2; v0.37 level B skipped where its weight is 0 |
| DPRO-DENS | 33,569 (5.0 %) | 30,603 (4.6 %) | 657 -> 162 | v0.36 the same tables in L2 |
| DPRO-WAVE | 25,961 (3.9 %) | 25,961 (3.9 %) | 187 -> 187 | nothing |
| SID 6581 | 57,661 (8.6 %) | 57,691 (8.7 %) | 0 -> 0 | nothing (rounding of the empty run) |
| VO-6 | 47,928 (7.2 %) | 47,928 (7.2 %) | 171 -> 171 | nothing |

## What it says (2026-11-03, the v0.40 L2 item)

- **The DPRO machines' DDR reads are no longer their cost.** What is left in DDR is the
  wave samples themselves: DDRW 217 accesses a block (2,170 of its 55,402, 3.9 %), DENS 162
  (5.3 %), DPRO WAVE 187 (7.2 %). Moved to L2 (4 instead of 10 each) they would save at most
  1,302 / 972 / 1,122 cycles a voice-block, 0.2 % of the frame each: no voice more on any of them.
  Their cost now is instructions and L2 (DDRW: 25,876 + 4 x 6,839, its render scratch in L2).
- **The tables do not fit the room anyway.** The v0.33 note below said the Monomachine tables are
  31,871 *bytes*; they are 31,871 *words* (`rom.table_words()`: WAVE's samples 16,896, SID's
  combined waves 4,096, DPRO's 976, VO-6's 9,903), 124.5 KB. What DDRW and DENS read is the
  Digibank stand-in the DSP builds at power-on, 32 x 2,048 words, 256 KB; DPRO WAVE reads its
  16,896 samples (66 KB). The proven L2 room left is 0x200A9200..0x200B0000, 28,160 bytes
  (0x200A8000..0x200A9000 holds the v0.36 DPRO tables, 0x200A9000..0x200A9200 the v0.37 MAIN
  tap). The Digibank's top mip levels (L >= 4, 124 words a wave, 16 KB) would fit, but a
  note uses them only above about 690 Hz (the cost run's C4 reads level 2); levels >= 3 need
  32,256 bytes. So no change was made for v0.40.
- **Where the next saving is**: the L2 accesses (DDRW 6,839, SID 7,046, DENS 3,681 a block:
  the render scratch and the voice slots, L2 since v0.32) and the instructions. L1 room, not L2,
  would cut those.
- **P-I's delay lines** (PI-SD, PI-RS: about 1,800 DDR accesses a block) are 128 KB: they
  do not fit L2. Shorter lines for the machines that need little would.
- **The sample machines** read their samples from DDR (1,250 accesses: the reader's taps);
  that is where samples live, and it is the DT2's own cost.

## v0.33's table (2026-10-30)

| machine | instructions | L2 accesses | DDR accesses | estimate | of the frame |
|---|---|---|---|---|---|
| DPRO-DDRW | 44,128 | 10,037 | 2,380 | 108,076 | 16.2 % |
| SID 6581 | 29,507 | 7,046 | 0 | 57,661 | 8.6 % |
| VO-6 | 30,838 | 3,845 | 171 | 47,928 | 7.2 % |
| DPRO-DENS | 14,259 | 3,185 | 657 | 33,569 | 5.0 % |
| PI-SD | 15,033 | 109 | 1,803 | 33,499 | 5.0 % |
| PI-RS | 14,766 | 108 | 1,779 | 32,988 | 4.9 % |
| TRX-CY | 20,645 | 2,434 | 144 | 31,821 | 4.8 % |
| EFM-CY | 20,224 | 2,245 | 188 | 31,084 | 4.7 % |
| DPRO-WAVE | 13,179 | 2,728 | 187 | 25,961 | 3.9 % |
| TRX-MA | 15,091 | 2,347 | 0 | 24,449 | 3.7 % |
| PI-MT | 13,924 | 497 | 783 | 23,742 | 3.6 % |
| TRX-CP | 15,175 | 1,985 | 0 | 23,085 | 3.5 % |
| TRX-S2 | 15,426 | 1,629 | 37 | 22,312 | 3.3 % |
| PI-BD | 11,755 | 478 | 729 | 20,957 | 3.1 % |
| EFM-CB | 13,004 | 1,757 | 92 | 20,952 | 3.1 % |
| PI-ML | 14,060 | 1,073 | 68 | 19,032 | 2.9 % |
| EFM-RS | 11,372 | 1,660 | 92 | 18,932 | 2.8 % |
| TRX-OH | 11,691 | 1,268 | 141 | 18,173 | 2.7 % |
| TRX-CH | 11,685 | 1,268 | 141 | 18,167 | 2.7 % |
| WERP | 5,841 | 0 | 1,317 | 17,647 | 2.6 % |
| REPITCH | 5,732 | 0 | 1,317 | 17,538 | 2.6 % |
| ONESHOT | 5,522 | 0 | 1,317 | 17,328 | 2.6 % |
| SLICE | 5,469 | 0 | 1,318 | 17,285 | 2.6 % |
| GRID | 5,434 | 0 | 1,317 | 17,240 | 2.6 % |
| PI-CC | 8,575 | 136 | 807 | 17,189 | 2.6 % |
| PI-RC | 8,337 | 126 | 787 | 16,711 | 2.5 % |
| EFM-CP | 10,376 | 1,300 | 44 | 16,016 | 2.4 % |
| PI-HH | 7,382 | 134 | 783 | 15,748 | 2.4 % |
| EFM-SD | 9,402 | 1,439 | 44 | 15,598 | 2.3 % |
| EFM-XT | 9,943 | 1,220 | 44 | 15,263 | 2.3 % |
| EFM-HH | 8,617 | 1,149 | 68 | 13,893 | 2.1 % |
| EFM-BD | 8,775 | 1,025 | 44 | 13,315 | 2.0 % |
| PI-MA | 7,366 | 529 | 0 | 9,442 | 1.4 % |
| TRX-CB | 5,404 | 790 | 21 | 8,774 | 1.3 % |
| TRX-SD | 3,558 | 264 | 70 | 5,314 | 0.8 % |
| TRX-CL | 2,706 | 489 | 23 | 4,892 | 0.7 % |
| TRX-RS | 3,728 | 159 | 47 | 4,834 | 0.7 % |
| TRX-B2 | 3,194 | 133 | 20 | 3,926 | 0.6 % |
| TRX-BD | 902 | 108 | 36 | 1,694 | 0.3 % |
| GND-SN | 875 | 145 | 20 | 1,655 | 0.2 % |
| GND-NS | 753 | 188 | 0 | 1,465 | 0.2 % |
| TRX-XT | 879 | 67 | 16 | 1,307 | 0.2 % |
| TRX-XC | 885 | 66 | 12 | 1,269 | 0.2 % |
| GND-IM | 491 | 86 | 0 | 795 | 0.1 % |
| STRETCH | 2,171 | 0 | 0 | 517 | 0.1 % |

(Negative counts are under the empty run's and shown as 0. STRETCH's single voice here
plays little of its sample at this tempo, so it reads almost nothing.)

## What it said (v0.33)

- **DPRO DDRW is the heaviest machine** by far: about 2,400 DDR accesses a block, its
  wavetables (the Monomachine's tables live in DDR, decoded there by the DSP at power-on).
  DENS and DPRO WAVE read the same tables. **Next**: those tables (31,871 bytes -- words, in fact: see above) fit the 32 KB
  of proven L2 left above the Monomachine scratch (0x200A8000..0x200B0000). Moving them means
  copying them there once decoded, and the Monomachine voices reading from there: a change to
  the voices' generated code and the decoder, with its own checks, kept out of v0.33 so this
  release stays the stability one.
- **P-I's delay lines** (PI-SD, PI-RS: about 1,800 DDR accesses a block) are 128 KB: they
  do not fit L2. Shorter lines for the machines that need little would.
- **SID** is L2-heavy (7,000 accesses): its state, now in L2 (v0.32). It was DDR before.
- **The sample machines** read their samples from DDR (1,300 accesses: the reader's taps);
  that is where samples live, and it is the DT2's own cost.
- The rest of the Machinedrum machines are light: TRX-BD, GND and the TRX-XT/XC family cost
  under 0.3 % of the frame each.

## The worst cases (step 3s, v0.33)

With the clock made to move (three cycles an instruction): sixteen P-I voices with every
control moving each block, sixteen VO-6 and DENS voices likewise, and one track retriggered
every block beside fifteen sounding voices. In every block our voices were done by 0.56,
0.42 and 0.58 of the frame, the guard leaving 189, 73 and 131 voice-blocks out, every buffer
finite. Before any of it the voices' state was also filled with NaN and with random words
(step 3g): every machine came through, finite.
