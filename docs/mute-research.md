# Mute on stock DN2 OS 1.11 — notes (2026-10-29)

Grades: [M] measured, [D] derived from disassembly, [I] inferred, [G] guess.

## Mute state on the ColdFire
- 0x80005218 (long, SRAM) = global mute mask, bit t = track t. 0x8000521c = solo mask.
  Both written only by 0x40025a58 (copies struct+36 / +40; callers 0x400405ce, 0x40042a98,
  0x40042da2, 0x40043422). [D]
- Emulator (wt29 build on ui800M-v014; mute logic is stock): MUTE mode + TRIG1 sets
  0x8000521b bit0 (i.e. 0x80005218 = 1); TRIG1 again clears it. Nothing else in
  0x40280000..0x40600000 or 0x80000000..0x8000ffff changes except UI counters/queue/LEDs:
  no voice table, no level, no kill flag (0x4058e54c/e550/e55c stay 0). [M] (memdiff.json, prep.json)
- Prepared mute: FUNC held + TRIG2: 0x80005218 still 0; on FUNC release -> 0x00000002.
  Quick mute FUNC+TRIG3+release -> 0x00000006. No kill flags. [M] (prep.json / prep.log)
- 0x4058e888 (word) = pattern mute mask [I]: set by 0x40025816 (callers 0x4003fb5c,
  0x4004a156) and by the ISR from a pattern-change event (0x400261c2). [D]

## How the ISR (0x40025e36) uses it
- 0x40025ec8: fp-116 = 0x80005218, or ~0x8000521c if any solo. fp-116 is read at ONE place:
  0x400264c2. [D]
- 0x400264a4..0x4002651a: for an event whose +20 == 1 (sequencer trig) on track t=ev+16:
  if bit t of fp-116 or of 0x4058e888 -> record t in fp-142 / fp-138 (the "muted track has
  trigs" LED blink masks, posted as UI message 29 at 0x40027120) and branch to 0x40027bc8
  -> d2=1 -> 0x40026520 (calls 0x400db798 on the event) -> 0x40026560 `tstl d2; bne
  0x40026e50`: NO voice allocation, NO note bit, NO timers. [D]
- So stock mute = the note-on is never generated. A voice already sounding is not touched by
  the mute: it ends by its own note-off (mask 36) when its gate timer runs out. [D + M: no
  state changed on mute]

## The four masks (per DSP SLOT/voice k, not per track; track = frame[0xa5a+2k])
ISR locals: fp-172 note-on, fp-164 amp-off accumulator, fp-160 filter-env trig, fp-168
filter-off accumulator, fp-136 / fp-132 gate-timer expiries, fp-152 LFO-trig (CF only).
- 0x40025f18..: 0x80005220[k] (gate timer, set to note LEN on note-on at 0x40026b04) -= 14400
  each ISR; reaching 0 -> fp-136 bit k + 0x4002b06e(k) (voice freed). 0x80005260[k] (set only
  when trig flag bit9, 0x40026ba8) -> fp-132 bit k. [D]
- note-on 0x40026b0c: fp-172 |= k; fp-164 &= ~k. flag bit10 -> fp-152; bit9 -> fp-160 |= k,
  0x80005348 |= k, fp-168 &= ~k. [D]
- voice steal 0x400267b0 / freed loops 0x40026fb8, 0x40026fe0 (all-voices release when
  0x4058e55c is set, by 0x40025594 at init/reload): fp-164 |= k; and fp-168 |= k if k in 0x80005348. [D]
- Final (0x4002706a..0x400274b4):
    frame+34 = fp-172                                  note on            [D]
    frame+36 = (fp-136 & ~fp-172) | fp-164             note off (amp gate off) [D]
    frame+38 = fp-160                                  filter-env trigger [D]
    frame+40 = (fp-132 & ~fp-160) | fp-168             filter-env gate off [D]
  Stop-all (0x4058e550 == 2, from 0x40027bdc on kit/project load etc.): +36 = 0xffff,
  +40 = 0xffff, +34 = +38 = 0, and the FX block fades (the "mute gate" at 0x40027468). [D]
- trig flag bits 9/10 = filter trig / LFO trig (DN2 TRIG page FLT.T / LFO.T) [G]

## DSP addresses (perc/program.py half(): FRAME=0x25C48C, byte-addressed, LE halfwords)
  +34 note on       = DM 0x25C4AC bits 16-31 (what we read)
  +36 note off      = DM 0x25C4B0 bits 0-15
  +38 filt env trig = DM 0x25C4B0 bits 16-31
  +40 filt env off  = DM 0x25C4B4 bits 0-15                                   [D]

## Runner check (stock DSP, WaveTone init sound on slot 0) [M]
scripts: ../mute_masks.py; log run/masks.log; json run/masks_t1_K16.json.
Mask 34 bit0 on block 1 only; then ONE of 36/38/40 bit0 on block 16 only. Track 0 amp-out RMS:
- none: sustains (0.0478 -> 0.0461 by block 35, the slow sustain drift)
- 36:   identical to none through block 16, then decays from block 17 (0.0468, 0.0463 ... 0.0397
        at 35): the amp envelope enters RELEASE. Mask 36 = note off / gate off.
- 38, 40: bit-identical to none (init sound's filter env has no audible depth): consistent with
        filter-env trigger / filter-env gate-off; not distinguished here.
Note FR.init_frame(trigger=True) sets all four masks at once; the runner tests that "trigger"
a voice therefore always also send note-off+filter-off in the same frame.

## For our voices (2026-10-29)

- Stock mute drops new trigs on the ColdFire; our voices get no note for a muted track either, so a muted track's new trigs are silent on our machines too [D]. A sounding note ends by note-off (mask 36) through the stock AMP chain, which runs after our render on every track, ours included.
- So no change is made for zugada's report (U3) until it is reproduced: which machine, LEN, and whether it is a track mute (MUTE mode / FUNC+TRIG) or something else.
- Runner caveat: FR.init_frame(trigger=True) raises all four masks at once, so a runner 'trigger' is also a note-off and a filter-envelope off in the same frame.
