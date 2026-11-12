# Stereo sampling: an assessment (2026-11-12)

The owner asked for this before any code (ROADMAP, 2026-11-10): what stereo would take end to end
(resampling MAIN, TRK and IN; playback on every sample machine; importing without folding to mono:
the import tool, the pool and the +Drive formats), what it would cost (DSP time, memory, polyphony,
ColdFire room), what would change, how long it would take, and how sure we could be.

**Short answer:**
- The recording and storing half is straightforward.
- Playing a stereo sample through a DN2 track is the hard half: the DN2's voices and tracks are
  mono until the stock chain pans them, so a stereo sample needs **two voices a note**, panned apart.
- There is a cheaper first step that gives real stereo with two tracks and no change to the stock
  voice handling (Phase 1).

## 1. Why it isn't one switch: how a sample reaches the output today

- **Our sample voice renders one mono block a voice into that voice's buffer** (`TRACK_BUFFERS`).
- **The stock chain then runs on that buffer with the voice's own parameters**, which the ColdFire
  builds per voice in the frame (sixteen 146-byte records; the sound's 101 slots a voice,
  `docs/slides.md`). That chain is
  the filters, the amp envelope, overdrive, pan, and the delay/reverb/chorus sends.
- **The chain pans the mono voice into the stereo mix.**
- **Everything downstream assumes one channel a voice.**

So the stereo image has to be made from **voices**: two voices a note (L and R), each through the
same track's chain, with their pan words set apart. Writing the second channel in past the chain is
the alternative. It would skip that track's filter, amp envelope and FX for half of the signal, so
it doesn't sound right and isn't proposed.

## 2. What each part needs

| part | today | for stereo | difficulty |
|---|---|---|---|
| **Recording IN / MAIN** | one channel: CHAN L+R, L or R | both channels at once, into **two slots** (L and R) or one interleaved slot | moderate: the DSP's recorder writes two streams; the ColdFire places two takes |
| **Recording TRK** | the track's voice, mono | a mono track stays mono (its stereo exists only after pan); TRK stereo only makes sense for a stereo sample track | n/a |
| **FLEX buffers** | 8 mono buffers | stereo takes need 2x memory a buffer, and FLEX playing them is the playback problem below | moderate, after playback |
| **The import tool** (`dn2samples.py`) | folds stereo WAVs to mono | sends L and R as a pair of slots (or keeps them interleaved) | easy |
| **The pool** (DSP DDR, 128 slots, int16 mono) | mono | a "pair" flag in the format word, or interleaved frames and a stereo reader | easy (pair) / moderate (interleaved) |
| **The +Drive library** | int16 mono entries | a pair of entries linked by a flag, or a stereo format | easy-moderate; old libraries stay readable |
| **Playback** | one voice a note | **two voices a note**, L and R, same track, pan words apart, the same pitch, start, trims, slices and envelope, stolen and released together | **hard**: it needs the stock voice allocation to hand a stereo track two voices for each note (a hook in the ColdFire's allocator), on every sample machine (ONESHOT, WERP, STRETCH, REPITCH, GRID, SLICE, FLEX) |

## 3. The cost

- **DSP time:** a stereo note costs two sample voices, about 2.6 % of the frame each
  (`docs/dsp-cost.md`), so about 5.2 % a stereo note. The guard handles the total as it does now.
- **Polyphony:** each stereo note takes two of the 16 voices, so a stereo track halves what's left
  for everything else.
- **Memory:** 2x a sample. The pool (400 MB after the RAM check, 128 MB proven otherwise;
  `docs/sampler.md`) holds about 70 minutes of 48 kHz int16 mono, so about 35 minutes of stereo
  (23 and 11 at 128 MB). The +Drive's image is the pool byte for byte, so the same limit.
  FLEX's 32 MB recordings area holds about 5 1/2 minutes mono, about 2 3/4 stereo.
- **ColdFire room:** the allocator hook and the pairing logic are a few KB of code. That fits; the
  code chunks have room.
- **What changes for everyone:** nothing for mono samples (the default stays mono). Stereo is chosen
  per sample: a stereo import, or CHAN STEREO on the recorder.

## 4. A phased plan

### Phase 1: stereo with two tracks (no change to voice allocation)
- **Import:** a stereo WAV becomes two slots, "NAME L" and "NAME R", adjacent.
- **Recording:** CHAN gets a fourth choice, STEREO, which records IN or MAIN into two slots at once
  (L and R); FLEX's buffers stay mono in Phase 1.
- **Playing:** put L on one track panned hard left and R on another panned hard right, with the same
  trigs (copy the track). A helper could set the pair up: "MAKE STEREO PAIR" on the sample list
  assigns L and R to the active track and the next one and sets their pans.
- **Cost:** easy-moderate, about one release. Low risk: the stock voice handling isn't touched.
- **Downsides:** two tracks a stereo sound, and p-locks have to be copied to both.

### Phase 2: stereo on one track (two voices a note)
- A stereo sample on a track plays as two voices a note, through that track's chain, panned around
  the track's PAN by a WIDTH control.
- This needs a hook in the voice allocator: a stereo track claims two voices for each note, and they
  are stolen together.
- On the DSP: the second voice reads the R slot, the same position and rate as the first.
- **Cost:** hard, about two to three releases, much of it in gate work. Two coupled tests, voice
  stealing under load, every sample machine, and SAVE/LOAD of stereo tracks.
- **Risk:** the allocator is stock code we would hook. A mistake there affects every track, stock
  machines too, which is why it goes after Phase 1.

### Phase 3: stereo FLEX
Stereo buffers (2x memory a buffer) played as Phase 2's pairs.

## 5. How sure we can be

| question | emulator | hardware only |
|---|---|---|
| the recorder writes both channels, the takes equal IN's L and R | yes, coupled | |
| import pairs, pool and +Drive pairs, SAVE/LOAD | yes, ColdFire and unit tests | |
| two voices a note, same position, pans apart in the frame | yes, coupled (the frame's per-voice words) | |
| the allocator hook under load: stealing in pairs, the voice menu's settings | partly (the ColdFire emulator runs the allocator) | the unit's real timing |
| the stereo image as heard, the chain's pan law | no (the stock chain's output mix isn't fully modelled) | yes |
| DSP load with many stereo notes | estimate (the runner's cost step) | the unit's meter |

## 6. Recommendation

1. **Phase 1 first.** It gives real stereo recordings and imports soon, with nothing risky, and the
   L/R pair format is what Phase 2 builds on.
2. **Decide on Phase 2 after using Phase 1 for a while.** It's the bigger job and touches stock voice
   handling.

**Open questions for the owner:**
- A pair of slots, or interleaved stereo? Pairs are simpler and fit Phase 1.
- STEREO on CHAN for IN only, or MAIN too? MAIN stereo is the whole mix, which is useful for
  resampling.
- How should a stereo sample show in the sample list: one entry marked "ST", or its two slots?
