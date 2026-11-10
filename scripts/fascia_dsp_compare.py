"""FASCIA's DSP program beside live.py on the whole audition (docs/fascia.md), and its WAVs.

    PYTHONPATH=src python3 scripts/fascia_dsp_compare.py [OUTDIR] [--seconds S] [--only NAME...]
        [--runner OUT/waverider/m5_report_TAG.json]

Each patch of scripts/fascia_audition.py, every note on its own slot (slot k, seed k + 1, as
live.render_notes gives each note its own voice), the notes starting on their block (the DSP's
quantum): the program's run mode (dnfw.fascia.program, the model the SHARC runner holds the
assembled code to, block for block) beside live.Voice. Prints, per patch, the blocks whose words
differ and the largest |dsp - live| of the mix; writes OUTDIR/NAME.wav (the DSP's mix) and
OUTDIR/NAME_live.wav. Exit 0 when every patch is bit-exact.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.fascia import bench as B      # noqa: E402
from dnfw.fascia import live as LV       # noqa: E402

import fascia_audition as A              # noqa: E402


def write(path: Path, x: np.ndarray) -> None:
    pk = float(np.max(np.abs(x))) or 1.0
    y = np.asarray(x, np.float64) / max(pk, 1.0) * 0.98
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(LV.RATE))
        w.writeframes((y * 32767).astype("<i2").tobytes())


def render(panel: dict, events, seconds: float):
    """-> (dsp mix, live mix, blocks with any slot differing)"""
    blocks = int(seconds * LV.RATE) // LV.BLOCK
    dsp = B.Dsp()
    evs = [(int(t0 * LV.RATE) // LV.BLOCK, k, note, vel) for k, (t0, note, vel, *_r) in enumerate(events)]
    assert len(evs) <= 16
    voices = {k: LV.Voice(seed=k + 1) for _b, k, _n, _v in evs}
    mix_d = np.zeros(blocks * LV.BLOCK, np.float32)
    mix_l = np.zeros(blocks * LV.BLOCK, np.float32)
    bad = 0
    for b in range(blocks):
        f = B.Frame()
        slots = []
        for b0, k, note, vel in evs:
            if b >= b0:
                f.slot(k, B.panel_words(panel), vel, note, b == b0)
                slots.append(k)
        out = dsp.block(f, slots)
        diff = False
        for b0, k, note, vel in evs:
            if b < b0:
                continue
            if b == b0:
                voices[k].note_on(B.note_seen(note), B.vel_seen(vel))
            want = voices[k].block(B.panel_seen(panel))
            got = out[k]
            diff = diff or not np.array_equal(got.view(np.uint32), want.view(np.uint32))
            mix_d[b * LV.BLOCK:(b + 1) * LV.BLOCK] += got
            mix_l[b * LV.BLOCK:(b + 1) * LV.BLOCK] += want
        bad += diff
    return mix_d, mix_l, bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", default=str(ROOT / "out" / "fascia-dsp"))
    ap.add_argument("--seconds", type=float, default=0.0, help="each patch's length (0: the audition's)")
    ap.add_argument("--only", nargs="*", default=())
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, (panel, evs, secs, trem) in A.PATCHES.items():
        if a.only and not any(o in name for o in a.only):
            continue
        t = time.time()
        d, l, bad = render(panel, evs, a.seconds or secs)
        dmax = float(np.max(np.abs(d.astype(np.float64) - l.astype(np.float64))))
        write(out / f"{name}.wav", d)
        write(out / f"{name}_live.wav", l)
        ok = ok and bad == 0
        print(f"{name}: {len(d) / LV.RATE:.2f} s, {len(evs)} notes, blocks differing {bad}, "
              f"max |dsp - live| {dmax:.3g}, peak {float(np.max(np.abs(d))):.3f} ({time.time() - t:.0f} s)", flush=True)
    print("ALL BIT-EXACT" if ok else "DIFFERENCES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
