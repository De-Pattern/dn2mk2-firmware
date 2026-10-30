# What each machine costs the DSP (v0.33, measured 2026-10-30)

One voice of each machine sounding, eight blocks after its note, in the SHARC runner
(`scripts/sharc_waverider_m5.py --steps cost`, step 3c), less a run with nothing sounding.
Per block (32 samples): the instructions our code runs, and its memory accesses by where they
land. On the unit an access to L2 costs several instruction times and one to DDR about ten
(complex-ping's measurements, `docs/others-dn2-research.md`); the estimate is instructions +
4 x L2 + 10 x DDR, against the frame's 666,667 cycles. It is an estimate: the unit's meter
(FUNC held on a PERC or Monomachine page) is the measure.

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

## What it says

- **DPRO DDRW is the heaviest machine** by far: about 2,400 DDR accesses a block, its
  wavetables (the Monomachine's tables live in DDR, decoded there by the DSP at power-on).
  DENS and DPRO WAVE read the same tables. **Next**: those tables (31,871 bytes) fit the 32 KB
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
