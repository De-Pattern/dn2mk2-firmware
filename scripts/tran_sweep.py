"""Map `TRAN`'s 125 positions onto the transient bank's 34 entries, by machine.

## What this measures, and why it can

The instrument must be running a **probe build**
(`scripts/make_probe_transients.py`): a pure tone in every even slot, silence in
every odd one, each tone a different frequency. Then for a given `TRAN` value,
the energy in tone *k*'s frequency bin **is** the weight the engine gives slot
2k. Sweeping `TRAN` and reading those bins gives the mapping directly, and the
*width* of each peak gives the interpolation.

That is the owner's design and it is the reason this works at all: with
ordinary transients in the bank, blending makes every landmark a smear and
every reading an opinion about where the middle of a fade was. A tone against
silence turns the question into "where is this maximal", which survives
blending instead of fighting it.

## What it sends, and what it does not

Two kinds of MIDI message, both ordinary performance data:

- **NRPN** to set `TRAN` — MSB 1, LSB 99. Confirmed twice over: Elektron's
  Appendix C gives SYN page 4 knob C as NRPN 1/99, and our own parameter table
  holds 227 for that record, which is 1x128 + 99.
- **note on / note off** to trigger the drum.

**No SysEx.** This module has no code that can emit an `F0` message at all,
which is the same discipline `scripts/midi_probe.py` uses: an incapability
rather than an intention. Nothing here writes to storage, a slot, or a project.

## The control that makes a null result readable

A sweep that reports the same spectrum at every `TRAN` value has two very
different explanations: the mapping is flat, or **the parameter never moved**.
The second is far more likely -- a wrong NRPN encoding, the wrong MIDI channel,
or `RECEIVE CC/NRPN` switched off in SETTINGS.

So `--check` runs first and separately: capture at `TRAN` 0 and at `TRAN` 124
and require the spectra to *differ*. If they do not, the sweep is not run,
because every number it produced would be a fact about the harness.
"""

import argparse
import ctypes
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

TRAN_NRPN_MSB = 1        # Appendix C: SYN page 4, data entry knob C
TRAN_NRPN_LSB = 99
TLEV_NRPN_LSB = 100      # SYN page 4, knob D -- transient level
TRAN_MAX = 124           # the record's range field: 0x7c00 -> 124

CC_NRPN_MSB, CC_NRPN_LSB = 99, 98
CC_DATA_MSB, CC_DATA_LSB = 6, 38

BASE_HZ, STEP_HZ = 650, 300      # must match make_probe_transients.py

# Half-width of the band read for each probe tone.
#
# **Was STEP_HZ/2 = 150 Hz, which was far too wide.** That number was chosen to
# keep neighbouring probe tones from leaking into each other -- and never
# checked against the voice the tones are measured *through*. The FM body sits
# near 278 Hz and its harmonics fall at 834, 1112, 1668, 1946, 2224, 2502 Hz,
# every one of them within 150 Hz of a probe tone. The low bins were measuring
# the synth, not the bank.
#
# 55 Hz keeps the tones apart with room to spare -- they are 300 Hz apart and
# the FFT resolves about 11 Hz over the analysis window -- while excluding the
# harmonics that sit 70-140 Hz off. It cannot help where a harmonic lands
# almost exactly on a tone (3050 Hz against 3058), but those slots were never
# the problem.
BIN_HZ = 55


class MidiOut:
    """The narrowest possible MIDI sender: three-byte channel messages only.

    `winmm`'s `midiOutShortMsg` cannot carry SysEx by construction -- a SysEx
    needs `midiOutLongMsg` and a prepared buffer, neither of which this class
    has. That is the point: the guarantee is structural.
    """

    def __init__(self, index: int):
        self._w = ctypes.WinDLL("winmm")
        self._h = ctypes.c_void_p()
        rc = self._w.midiOutOpen(ctypes.byref(self._h), index, 0, 0, 0)
        if rc:
            raise SystemExit(f"midiOutOpen({index}) failed with {rc}")

    def _short(self, status: int, d1: int, d2: int) -> None:
        self._w.midiOutShortMsg(self._h, status | (d1 << 8) | (d2 << 16))

    def cc(self, channel: int, number: int, value: int) -> None:
        self._short(0xB0 | ((channel - 1) & 0x0F), number & 0x7F, value & 0x7F)

    def note(self, channel: int, pitch: int, velocity: int) -> None:
        self._short(0x90 | ((channel - 1) & 0x0F), pitch & 0x7F, velocity & 0x7F)

    def nrpn(self, channel: int, msb: int, lsb: int, value: int) -> None:
        """Select an NRPN and set it. The value goes in the **data-entry MSB**.

        **Not 14-bit.** Sending `MSB = value >> 7` with `LSB = value & 0x7F` is
        the textbook encoding and it is wrong here: `TRAN` spans 0..124, so the
        MSB is always 0 and the parameter never leaves its first position. On
        the instrument that reads as "it keeps repeating the same transient",
        which is exactly what the owner heard the moment this loop started going
        through here instead of setting CC 6 directly.

        The working runs sent CC 6 alone from the start; the regression arrived
        when that loop was tidied into this method. Measured, not reasoned: with
        CC 6 carrying the value, the sweep walks the bank.
        """
        self.cc(channel, CC_NRPN_MSB, msb)
        self.cc(channel, CC_NRPN_LSB, lsb)
        self.cc(channel, CC_DATA_MSB, value & 0x7F)

    def close(self) -> None:
        self._w.midiOutClose(self._h)


def tone_bins(count: int):
    """-> [(slot, hz)] for the probe build's tones."""
    return [(2 * k, BASE_HZ + STEP_HZ * k) for k in range(count)]


class Capture:
    """One audio stream held open for the whole sweep.

    **Not `sd.rec` per trig.** That opens and closes the device on every
    measurement, and after a few dozen cycles the WASAPI stream stops coming
    back -- the sweep freezes mid-run with no error, which looks from the
    instrument like "it stuck and the transients stopped changing". Seen twice.

    Holding one stream open also drops the per-trig latency, so a 125-point
    sweep takes appreciably less of the owner's time.
    """

    def __init__(self, device: int, rate: int):
        import sounddevice as sd
        self._sd = sd
        self._rate = rate
        self._stream = sd.InputStream(samplerate=rate, channels=2,
                                      device=device, blocksize=0)
        self._stream.start()

    def read(self, seconds: float):
        import numpy as np
        self._stream.read(self._stream.read_available)   # drop anything stale
        frames = int(self._rate * seconds)
        data, overflowed = self._stream.read(frames)
        return np.asarray(data)

    def close(self):
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass


def spectrum(audio, rate: int, bins, window_ms=90.0, floor=0.02):
    """-> {slot: amplitude in that tone's bin}, measured at the **onset**.

    **Not the loudest window.** The first version measured wherever the note was
    loudest, which on an FM drum is the *body* -- a ~280 Hz tone lasting far
    longer than the transient. Every reading came back "280 Hz" and the probe
    bins were picking up its harmonics and leakage, so the numbers described the
    synth voice rather than the sample being selected.

    The transient is 100 ms and it is at the **start**. This finds the first
    sample above the noise floor and reads the window from there.
    """
    import numpy as np
    mono = audio.mean(axis=1)
    loud = np.abs(mono) > floor
    onset = int(np.argmax(loud)) if loud.any() else 0
    seg = mono[onset:onset + int(rate * window_ms / 1000)]
    if len(seg) < 256:
        return {slot: 0.0 for slot, _ in bins}
    mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freqs = np.fft.rfftfreq(len(seg), 1 / rate)
    out = {}
    for slot, hz in bins:
        sel = (freqs > hz - BIN_HZ) & (freqs < hz + BIN_HZ)
        out[slot] = float(mag[sel].max()) if sel.any() else 0.0
    return out


def top_peaks(audio, rate: int, n=4, window_ms=90.0, floor=0.02):
    """The loudest few frequencies at the onset -- for seeing what is actually
    there, rather than only how much lands in bins we chose in advance."""
    import numpy as np
    mono = audio.mean(axis=1)
    loud = np.abs(mono) > floor
    onset = int(np.argmax(loud)) if loud.any() else 0
    seg = mono[onset:onset + int(rate * window_ms / 1000)]
    if len(seg) < 256:
        return []
    mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freqs = np.fft.rfftfreq(len(seg), 1 / rate)
    order = np.argsort(mag)[::-1]
    picked = []
    for i in order:
        if all(abs(freqs[i] - f) > BIN_HZ for f, _ in picked):
            picked.append((float(freqs[i]), float(mag[i])))
        if len(picked) >= n:
            break
    return picked


def measure(midi, cap, args, tran, bins):
    midi.nrpn(args.channel, TRAN_NRPN_MSB, TRAN_NRPN_LSB, tran)
    time.sleep(args.settle)
    midi.note(args.channel, args.note, 100)
    audio = cap.read(args.hold)
    midi.note(args.channel, args.note, 0)
    return spectrum(audio, args.rate, bins)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--midi-out", type=int, required=True)
    p.add_argument("--device", type=int, required=True, help="audio input index")
    p.add_argument("--channel", type=int, default=1, help="MIDI channel of the FM DRUM track")
    p.add_argument("--note", type=int, default=60)
    p.add_argument("--rate", type=int, default=48000)
    p.add_argument("--hold", type=float, default=0.35, help="seconds of audio per trig")
    p.add_argument("--settle", type=float, default=0.08)
    p.add_argument("--step", type=int, default=1, help="TRAN increment")
    p.add_argument("--from", dest="lo", type=int, default=0)
    p.add_argument("--to", dest="hi", type=int, default=TRAN_MAX)
    p.add_argument("--rest", type=float, default=0.15,
                   help="pause after each trig, so a reverb or delay tail "
                        "cannot ring into the next measurement -- that "
                        "contaminated the first sweep and shifted every "
                        "reading toward the previous slot")
    p.add_argument("--tones", type=int, default=17)
    p.add_argument("--tlev", type=int, default=None,
                   help="set transient level once before sweeping (0-127)")
    p.add_argument("--check", action="store_true",
                   help="only run the control: does TRAN change anything at all")
    p.add_argument("--csv", type=pathlib.Path)
    args = p.parse_args(argv)

    bins = tone_bins(args.tones)
    midi = MidiOut(args.midi_out)
    cap = Capture(args.device, args.rate)
    if args.tlev is not None:
        # The FM DRUM body cannot be silenced, so the transient is pushed up
        # instead: the measurement wants the bank as loud as the voice allows
        # relative to everything else.
        midi.nrpn(args.channel, TRAN_NRPN_MSB, TLEV_NRPN_LSB, args.tlev)
        time.sleep(0.1)
    try:
        low = measure(midi, cap, args, 0, bins)
        high = measure(midi, cap, args, TRAN_MAX, bins)
        loudest_low = max(low, key=low.get)
        loudest_high = max(high, key=high.get)
        moved = loudest_low != loudest_high
        print(f"control: TRAN 0   loudest tone -> slot {loudest_low}")
        print(f"         TRAN {TRAN_MAX} loudest tone -> slot {loudest_high}")
        print(f"         the parameter {'MOVED' if moved else 'DID NOT MOVE'}")
        if not moved:
            print()
            print("Not sweeping. Every number a sweep produced would be a fact")
            print("about this harness rather than about the instrument. Check:")
            print("  - SETTINGS > MIDI CONFIG > RECEIVE CC/NRPN is on")
            print("  - --channel matches the FM DRUM track's MIDI channel")
            print("  - the probe build is actually loaded (tones, not drums)")
            return 1
        if args.check:
            return 0

        print()
        rows = []
        # Printed per step and flushed: a sweep of 125 points takes a minute
        # and a silent minute is indistinguishable from a hang. The first
        # version printed nothing until the end and looked stuck.
        for tran in range(args.lo, args.hi + 1, args.step):
            e = measure(midi, cap, args, tran, bins)
            time.sleep(args.rest)
            top = max(e, key=e.get)
            total = sum(e.values()) or 1.0
            rows.append((tran, top, e))
            share = 100 * e[top] / total
            bar = "#" * int(share / 3)
            print(f"  TRAN {tran:3d}  slot {top:2d}  {share:5.1f}%  {bar}", flush=True)

        if args.csv:
            import csv
            with args.csv.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["tran", "loudest_slot"] + [f"slot{s}" for s, _ in bins])
                for tran, top, e in rows:
                    w.writerow([tran, top] + [f"{e[s]:.6g}" for s, _ in bins])
            print(f"\nwrote {args.csv}")
    finally:
        midi.close()
        cap.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
