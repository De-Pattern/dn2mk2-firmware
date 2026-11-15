# v0.56: DDRW's TIME and BR1/BR2 (owner, 2026-11-15)

> "time in ddrw is not working ... the 2 Br1 and BR2 controls are 99% inaudible"

## Measured (the run model, `dnfw.mnm.bench`, the DSP's own code bit for bit)

Scripts: scratch `ddrw_br.py`, `ddrw_time.py` (golden case "default", MIX 64 / 0).

**BR** (both at once, against BR 0): the difference's level relative to the sound

| BR | 0 | 32 | 64 | 96 | 127 |
|---|---|---|---|---|---|
| bits left (table) | 15 | 12 | 9 | 6 | 3 |
| difference | — | -57 dB | -43 dB | -25 dB | -8 dB |

That is the Monomachine's own curve (P:0x147BE5, an exponential: 192 BR / 2048 octaves), so it
is faithful. The audible part is the top quarter of the knob.

**TIME**: a WAV1 change mid-note (0 -> 40) renders **identically** at TIME 0, 32 and 127. The
fade's rate per half-block is `0x21D10 x g x 0x7FFFFF/(TIME + 1) << 11`, capped at 1. With the
glide word g at 1.0 here, the rate is over 1 up to TIME 32, and about 0.26 at 127: a fade of a
few half-blocks, under 2 ms. TIME does nothing you can hear.

## Plan

- **BR**: remap the knob on the way to the DSP (the ColdFire's frame, DDRW voices only), so the
  DSP's model stays the Monomachine's and its references hold. 0 stays 0 (clean). 1..127 map
  to table 64..127 (9 bits down to 3), so the whole turn is audible.
- **TIME**: the fade's rate becomes `1 / (1 + c TIME^2)` a half-block, so 0 is instant (as now)
  and 127 is about 2 s (c about 0.37), with a musical curve (16: ~30 ms, 64: ~0.5 s). This
  changes the DSP code. Any reference case with TIME > 0 and a wave change mid-note changes
  with it, by design. Those cases get their new expected words from the model, recorded with
  this note, and every other case stays bit for bit.
