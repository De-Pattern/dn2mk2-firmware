"""Waverider Milestone 6: what the stock unpack does with WaveTone's TUN1.

    python scripts/sharc_waverider_m6_tune.py [--digikit ../digikit-wt-sharcemu]

TUN1 is WaveTone's parameter index 25 (`dnfw params`: "Osc1 Tune", group 1,
range 0x7c00, default 0x4000). The frame carries it at byte 218 + 146t, the word
before WAV1 (220) and TBL1 (222), at the sound's own value (read on the instrument
through the USB probe; this script's frames are built by `dnfw.waverider.frame`, so
it measures the unpack's scale, not what the ColdFire sends). Waverider reads WAV1
and TBL1 from the frame copy itself (the unpack writes nothing for a type-5
track), so to follow TUN1 as WaveTone does it needs WaveTone's own scale.

This measures that scale rather than assuming it. Track 0 is WaveTone (DSP
machine type 1) on the init sound, and only TUN1's frame word changes. Each run
calls the firmware's own unpack (`sw 0x1c2712`, stopped before the dispatch),
then diffs track 0's record and WaveTone's per-track machine state against the
run at TUN1's default. Every word that moves is printed, as an integer and as a
float, for each TUN1 value, so the relation (semitones, octaves, a ratio) can be
read off the numbers.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import struct
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_render as m1                            # noqa: E402
import sharc_waverider_voice as m2                             # noqa: E402
import sharc_waverider_m3 as m3                                # noqa: E402
import sharc_waverider_m4 as m4                                # noqa: E402
import sharc_dn2_fixups as fx                                  # noqa: E402
from dnfw.waverider import frame as FR                         # noqa: E402
from dnfw.waverider import voice as V                          # noqa: E402

WAVETONE = 1                       # DSP machine type (voice.MACHINES)
TUN1 = 25
# sound values: coarse << 8 | fine. The frame carries half (frame.py, M5 note).
SOUND_VALUES = [0x4000, 0x0000, 0x0400, 0x3400, 0x3c00, 0x4080, 0x4100, 0x4400, 0x4c00, 0x7c00]


def words(state, base: int, n: int) -> list[int]:
    return [m2.word(state, base + 4 * k) or 0 for k in range(n)]


def f32(v: int) -> float:
    return struct.unpack(">f", struct.pack(">I", v & 0xFFFFFFFF))[0]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=m4.IMAGE)
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                       ROOT.parent / "digikit-wt-sharcemu")))
    a = p.parse_args(argv)
    m4.IMAGE = a.image
    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    stream = m1.dn2_section7(a.image)
    sound, machines = m4.init_sound(a.image)
    m4.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=m4.OUT) as tmp:
        work = pathlib.Path(tmp)
        reader, _, _ = m1.reader_code(False, work)
        m5, _, _ = m3.load_json(m3.MACHINE5, m3.MACHINE5_SRC, False, work)
        m5d, _, _ = m4.load_code(m4.MACHINE5D, m4.MACHINE5D_SRC, False, work, m4.MACHINE5D_SW)
        mach = m4.M4Machine(dk, stream, reader, m5, m5d, work)
        init = m4.load_init(dk, mach, stream, reader)

        rec0 = V.track_record(0)
        state_off, state_len = V.MACHINE_STATE[WAVETONE]
        regions = {"record": (rec0, V.TRACK_STRIDE // 4)}
        wt = machines.get(1, {})

        def run(value: int):
            f = FR.init_frame(sound, WAVETONE, track0={**wt, TUN1: value})
            r = m4.run_unpack_only(init, f.to_bytes())
            return {k: words(r.state, b, n) for k, (b, n) in regions.items()}

        base = run(0x4000)
        print(f"TUN1 frame word at byte {FR.slot_offset(0, TUN1)}; WaveTone state +{state_off:#x}")
        for value in SOUND_VALUES:
            got = run(value)
            moved = [(k, i, got[k][i]) for k in got for i in range(len(got[k])) if got[k][i] != base[k][i]]
            coarse, fine = value >> 8, value & 0xFF
            print(f"\nTUN1 sound 0x{value:04x} (coarse {coarse}, fine {fine}; "
                  f"{coarse - 64 + fine / 256:+.4f} semitones if centred on 64):")
            for k, i, v in moved or []:
                print(f"   {k} +0x{4 * i:03x}: 0x{v:08x}  int {v}  float {f32(v):.6f}"
                      f"   (default 0x{base[k][i]:08x} float {f32(base[k][i]):.6f})")
            if not moved:
                print("   nothing in the record moved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
