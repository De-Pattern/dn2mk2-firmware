"""Render the CZ audition WAVs (docs/cz.md): python cz/demos.py"""

import importlib.util
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cz_model", HERE / "model.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
OUT = HERE / "demos"
OUT.mkdir(exist_ok=True)


def env(*pairs, pad=(99, 0)):
    p = list(pairs) + [pad] * (8 - len(pairs))
    return p[:8]


def demo(name, events, seconds, patch):
    M.write_wav(str(OUT / f"{name}.wav"), M.sequence(events, seconds, patch))
    print(f"  {name}.wav")


def line(waves, dcw, dcw_sus, dca, dca_sus, **kw):
    return {"waves": waves, "dcw": dcw, "dcw_sus": dcw_sus, "dcw_end": len([x for x in dcw if x != (99, 0)]),
            "dca": dca, "dca_sus": dca_sus, "dca_end": len([x for x in dca if x != (99, 0)]), **kw}


def main():
    # 1. every wave, DCW swept 0 -> 99 over each note (sine -> full shape)
    ev, t = [], 0.05
    sweep = line("SAW", env((40, 99), (99, 99)), 1, env((99, 99), (60, 0)), 0)
    pieces = []
    for w in M.WAVES:
        p = {"line1": {**sweep, "waves": w}}
        pieces.append(M.sequence([(0.02, 48, 1.4)], 1.7, p))
    M.write_wav(str(OUT / "01_eight_waves_dcw_sweep.wav"), np.concatenate(pieces))
    print("  01_eight_waves_dcw_sweep.wav  (SAW SQUARE PULSE DOUBLE SAWPULSE RES1 RES2 RES3)")
    # 2. resonant bass: RES1, DCW snapping down, punchy DCA
    bass = {"line1": line("RES1", env((99, 85), (62, 20), (50, 0)), 1,
                          env((99, 99), (70, 70), (55, 0)), 1)}
    seq = [36, 36, 48, 36, 39, 36, 43, 41] * 2
    demo("02_resonant_bass", [(0.05 + 0.18 * k, n, 0.12) for k, n in enumerate(seq)], 3.6, bass)
    # 3. brass: SAW, DCW opening with the attack and settling
    brass = {"line1": line("SAW", env((70, 90), (60, 60), (45, 0)), 1,
                           env((75, 99), (55, 85), (55, 0)), 1),
             "select": "1+1'", "detune_c": 9}
    demo("03_brass", [(0.05, 60, 0.6), (0.05, 64, 0.6), (0.05, 67, 0.6),
                      (0.9, 62, 0.6), (0.9, 65, 0.6), (0.9, 69, 0.6), (1.75, 60, 1.2), (1.75, 64, 1.2),
                      (1.75, 67, 1.2), (1.75, 72, 1.2)], 4.0, brass)
    # 4. strings: SAW pair, slow DCA, 1+1' detuned
    strings = {"line1": line(("SAW", "SAW"), env((30, 50), (99, 50), (35, 0)), 1,
                             env((35, 99), (99, 99), (40, 0)), 1),
               "select": "1+1'", "detune_c": 12}
    demo("04_strings", [(0.05, n, 2.2) for n in (55, 62, 67, 71)] + [(2.6, n, 2.0) for n in (53, 60, 65, 69)],
         6.5, strings)
    # 5. bell: RES2 + ring, decaying DCW
    bell = {"line1": line("RES2", env((99, 70), (45, 10)), 1, env((99, 99), (38, 0)), 1),
            "line2": line("SAW", env((99, 40), (40, 0)), 1, env((99, 99), (35, 0)), 1),
            "select": "1+2'", "octave2": 1, "detune_c": 7, "ring": True}
    demo("05_ring_bell", [(0.05 + 0.6 * k, n, 0.3) for k, n in enumerate([72, 79, 76, 84, 72, 67])], 5.0, bell)
    # 6. square organ and pulse lead
    organ = {"line1": line("SQUARE", env((99, 55), (99, 55)), 1, env((99, 99), (99, 99), (70, 0)), 1)}
    demo("06_square_organ", [(0.05 + 0.4 * k, n, 0.35) for k, n in enumerate([60, 64, 67, 72, 67, 64, 60, 55])],
         3.8, organ)
    lead = {"line1": line("PULSE", env((80, 70), (55, 40)), 1, env((90, 99), (99, 90), (60, 0)), 1),
            "select": "1+1'", "detune_c": 6}
    demo("07_pulse_lead", [(0.05 + 0.3 * k, n, 0.25) for k, n in enumerate([72, 74, 76, 79, 76, 74, 72, 67, 69, 72])],
         3.8, lead)


if __name__ == "__main__":
    main()
