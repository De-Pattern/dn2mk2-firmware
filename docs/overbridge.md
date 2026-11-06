# Overbridge with the mod (v0.41)

The owner asked (2026-11-05, ROADMAP 1b) whether Overbridge is supported on the mod, after
Pablo Se7en's report that Overbridge did not detect his DN2.

## What is known

- **Pablo's report was the Overbridge suite's version, not the mod.** The plugin said the OS
  version was incompatible and asked to update the suite: Overbridge 2.26.10 is the first to
  support Digitone II OS 1.11. ptkrm confirmed v0.39 + Overbridge 2.26.10 + Windows 11 + Live
  12 works (Discord, 2026-11-05).
- **The mod never touches** the USB descriptors or Elektron's OS version string
  (`dnfw/safety.py`, `modversion.py`): to the computer it is a Digitone II on OS 1.11.
- **Overbridge's channels and the mod's link are apart** (`docs/link-research.md`): Overbridge
  moves SHARC TDM slots 0..13 (main, tracks 1..16, FX returns, the input) and the reply
  records; the mod's sample link uses TX slots 8..15 (which mode 6 leaves alone on frames
  without USB data) and RX slots 14..15.
- **A tempo-follow report (Pablo, 2026-11-06)**: with Overbridge's plugin the Digitone
  follows the DAW's tempo even with CLOCK RECEIVE off. That is Overbridge's own sync, set in
  the plugin, not MIDI clock and not the mod.

## What the gate proves (step `overbridge`, `scripts/gate_overbridge.py`)

No byte the build changes lies in an instruction Overbridge's audio path can run. From the
mode-6 packet builder (`0x40003118`), the USB-to-TX input (`0x40003376`), the USB writer
(`0x40004734`), the USB mode's getter (`0x40006c4a`) and the audio interrupt up to the
link's hook, the stock code is followed through every branch and call (1,907 instructions
on v0.41): none is patched. The audio interrupt's only patch is the link's documented hook
at `0x40026098`, where every transmit-fill mode has already run. A negative control, rooted
at a site the build does patch (the lock applier), must find it, so the detector is shown
to work every run. Indirect calls (38, through function pointers) are not followed; they are
listed in the step's record.

## What only the unit can confirm (the owner's checklist)

1. **Detection.** Overbridge 2.26.10 or later. SETTINGS > SYSTEM > USB CONFIG: OVERBRIDGE.
   Overbridge Engine shows the Digitone II, online.
2. **Streams.** In the DAW, the plugin (or the Overbridge audio device): main, a few tracks,
   the input. Put a sample machine, a Waverider, a Machinedrum and a Monomachine machine on
   tracks; each track's channel carries its track.
3. **The plugin with our machines.** Open the plugin's sound page on a track with one of our
   machines: it should show the track (parameter names may be generic); nothing crashes.
4. **The sample link while streaming.** With Overbridge streaming: load a sample to the
   project (+DRIVE, LOAD TO PROJECT), record a take, play a REC buffer. Audio keeps streaming,
   and the take and the sample are right.
5. **DSP load.** Hold FUNC on a busy pattern (the load meter) with and without Overbridge
   streaming: report both numbers.
6. **The +DRIVE preview** is not heard through Overbridge (paQ, v0.35): expected, as the
   preview is added to the analog main after the mix Overbridge takes. Note if that matters.

If the plugin refuses a kit with our machines, use Overbridge's audio device in the DAW
without the plugin. If Overbridge itself fails, that is found before anything else ships.
