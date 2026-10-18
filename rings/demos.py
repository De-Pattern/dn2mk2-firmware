"""Render the RESONATOR audition WAVs (docs/rings.md): python rings/demos.py"""

import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rings_model", HERE / "model.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
OUT = HERE / "demos"
OUT.mkdir(exist_ok=True)


def steps(bpm, notes, every=0.25, start=0.05, **over):
    beat = 60.0 / bpm
    return [(start + k * every * beat, n, dict(over)) for k, n in enumerate(notes) if n is not None]


def chords(times, chords_, **over):
    return [(t, n, dict(over)) for t, ch in zip(times, chords_) for n in ch]


def demo(name, events, seconds, **kw):
    M.write_wav(str(OUT / f"{name}.wav"), M.sequence(events, seconds, **kw))
    print(f"  {name}.wav")


MEL = [72, None, 79, 76, None, 84, 79, None, 72, 74, None, 79, 76, 72, None, 67]


def main():
    demo("01_marimba_bar", steps(110, MEL * 2), 5.5, structure=0.5, brightness=0.45,
         damping=0.5, position=0.25)
    demo("02_bells_chords", chords([0.05, 1.6, 3.2], [(60, 67, 76), (57, 64, 72), (62, 69, 77, 81)]),
         6.5, structure=0.92, brightness=0.6, damping=0.75, position=0.2)
    demo("03_string_pluck", steps(100, [48, 55, 60, 63, 67, 63, 60, 55] * 2, every=0.5), 5.2,
         model="STRING", structure=0.1, brightness=0.6, damping=0.6, position=0.15)
    demo("04_glass_noise", steps(90, [84, None, 91, None, 88, None, 96, None]), 3.6,
         structure=0.75, brightness=0.9, damping=0.6, position=0.1, exc="NOISE")
    ev = [(0.05 + 0.6 * k, 60, {"structure": k / 7}) for k in range(8)]
    demo("05_structure_harmonic_to_bell", ev, 6.0, brightness=0.55, damping=0.45, position=0.3)
    ev = [(0.05 + 0.7 * k, 64, {"damping": k / 6}) for k in range(7)]
    demo("06_damping_short_to_long", ev, 7.0, structure=0.6, brightness=0.5, position=0.3)
    demo("07_four_voice_chords", chords([0.05, 1.2, 2.4, 3.6], [(48, 55, 64, 71), (45, 52, 60, 67),
                                                               (41, 48, 57, 64), (43, 50, 59, 62)]),
         6.5, structure=0.3, brightness=0.5, damping=0.7, position=0.35)
    demo("08_plate_drums", steps(120, [40, None, 40, 47, None, 40, 43, None] * 2), 5.0,
         structure=0.8, brightness=0.4, damping=0.52, position=0.4)


if __name__ == "__main__":
    main()
