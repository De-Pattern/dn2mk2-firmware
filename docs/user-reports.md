# User reports (YouTube thread, GitHub issues)

Source: comments on "DIGITONE 2 mk2 FIRMWARE MOD: MD|DT2|MNM" (De-Patterning), read
2026-10-28. Reporters were on v0.26 or MNM-1 unless noted.

## Bugs

| # | report (who) | status |
|---|---|---|
| U1 | MD machines: sometimes no sound on any pattern until a power cycle (zugada_); v0.26 "very unstable, no sound for more than a few minutes" (mistahairplane) | the frame overrun: v0.27's guard. Confirm on v0.27 |
| U2 | Sample (DT2) machines: choosing a sample while the pattern plays freezes the unit; a power cycle clears it. "Most of the crashes are on the Digitakt machines" (zugada_) | **open**: not reproduced yet. v0.27 changed when the list opens; check the load path while playing |
| U3 | A trig can't be pre-muted (trig mute), especially on the custom machines (zugada_) | **open**: our PERC/sample voices may not honour the trig-mute flag |
| U4 | SYN + YES (randomize) on a Machinedrum machine crashes sometimes (zugada_) | **open**: randomized values out of our ranges (TYPE?) |
| U5 | After switching a track from an MD machine to a stock DN2 machine, the MD machine is still heard in the background (zugada_) | **open**: the model silences a track that leaves PERC; check the hardware path |
| U6 | Delete all samples / folders sent by the import tool (zugada_) | multi-select delete, planned |

## Requests

- Stereo sampling from the inputs (bearsshuffle)
- Samples streamed from the +Drive, using its free ~19 GB (paQ75, DrLaemmerbein)
- Polyphonic samples per track (paQ75): not planned for now
- A build with only the Machinedrum and Monomachine machines (douleursolitude)
- "Ensemble machines need work" (ModernDevotion): which machine is unclear; asked for plain-English detail
- A Discord (taktonmusic)
