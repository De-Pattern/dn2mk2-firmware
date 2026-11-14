# Machinedrum and Monomachine engines: our own, optimised (queued)

Owner, 2026-11-14 05:56: *"i want to SERIOUSLY trim down the MM and MD engines. we should do that
as its own branch too, lets rewrite EACH of them so they are proprietary, based on the stock
versions that we ported, but in our own code, so they sound the same (as close as possible) but
are EXTREMELY optimized to work as they should without any dropping or stealing outside of the
normal dn2 behavior"* -- after the stereo work and any other pressing updates.

- **Branch:** its own (`mdmm-rewrite`), removable, like stereo.
- **Each machine rewritten in our own code**, from what the ported ones do, sounding as close
  as possible to them (measured: the runner renders both, and the difference is reported per
  machine, not just listened to).
- **The goal is DSP time:** every machine light enough that a full pattern never needs the
  guard to leave voices out or steal them, so voice handling is stock DN2's and nothing more.
- **Start from the costs** in `docs/dsp-cost.md` (SID 8.7 %, DPRO-DDRW 8.3 %, VO-6 7.2 % of a
  frame per voice, the heaviest first), with the load meter on the unit as the final measure.
