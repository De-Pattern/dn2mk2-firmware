"""Per-block DSP frames from a frame the ColdFire's own builder made, for the M5 runner gate.

    python scripts/waverider_cf_frames.py out/waverider-m5/final2/tbl1.frame_be.bin \\
        out/waverider-m5/cf_frames/tbl1 [--blocks 8] [--note 60]

A frame captured in the ColdFire emulator (`emu_waverider_menu.py frame:NAME`) has no
note in it: no key was played there (the ISR entered with a trig key held did not
reach the builder). So the one thing a player adds is added here, and nothing else:

- each 16-bit word byte-swapped into DSP memory order (the layouts agree word for
  word; see `waverider_frame_compare.py`);
- track 0's trig note set to NOTE (header `2 + 2t`, `note << 8`) on every block, and
  its four trigger bits (offsets 34..40) on block 1 only, as a key press does;
- with `--solo` (the default) tracks 1-15 set to MIDI (type 4, no render), so the
  runner's minutes go to the track under test. `--no-solo` keeps them verbatim.

Every other word -- WAV1, TBL1, the filter, the amp, the FX, the unmodelled header
arrays -- is the ColdFire's, verbatim. The files are `NN.bin`, one per block, for
`sharc_waverider_m5.py --frames 'DIR/*.bin'`.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import frame as FR                 # noqa: E402


def to_dsp(be: bytes) -> FR.Frame:
    if len(be) != FR.FRAME_BYTES:
        raise SystemExit(f"a frame is {FR.FRAME_BYTES} bytes, not {len(be)}")
    words = struct.unpack(f">{FR.FRAME_BYTES // 2}H", be)
    return FR.Frame(bytearray(struct.pack(f"<{FR.FRAME_BYTES // 2}H", *words)))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("frame_be", type=pathlib.Path)
    p.add_argument("out", type=pathlib.Path)
    p.add_argument("--blocks", type=int, default=8)
    p.add_argument("--note", type=int, default=60)
    p.add_argument("--no-solo", action="store_true")
    p.add_argument("--level", type=lambda x: int(x, 0), default=None,
                   help="override track 0's header word at 116 (frame.py's LEVEL; the "
                        "ColdFire's capture holds 0x023a there): a labelled deviation")
    p.add_argument("--velocity", type=lambda x: int(x, 0), default=None,
                   help="track 0's velocity word (header 52 + 2t, from 0x8000dd40, clamped "
                        "to 0x7f00 by the ISR's note-on): what a key press writes there")
    p.add_argument("--machine", type=int, default=None,
                   help="override track 0's machine type (e.g. 1, the WaveTone control)")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    base = to_dsp(a.frame_be.read_bytes())
    for b in range(a.blocks):
        f = FR.Frame(bytearray(base.data))
        f.header(FR.NOTE, 0, a.note << 8)
        f.trigger(0, on=(b == 1))
        if a.level is not None:
            f.header(FR.LEVEL, 0, a.level)
        if a.velocity is not None:
            f.put(52, a.velocity)
        if a.machine is not None:
            f.header(FR.MACHINE, 0, a.machine)
        if not a.no_solo:
            for t in range(1, FR.TRACKS):
                f.header(FR.MACHINE, t, 4)
        (a.out / f"{b:02d}.bin").write_bytes(f.to_bytes())
    print(f"wrote {a.blocks} frames to {a.out}: track 0 type {base.get(FR.MACHINE)}, "
          f"WAV1 {base.get(FR.slot_offset(0, 26)):#06x}, TBL1 {base.get(FR.slot_offset(0, 27)):#06x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
