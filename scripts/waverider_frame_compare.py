"""The ColdFire's own frame beside `dnfw.waverider.frame`'s model of it, field by field.

    python scripts/waverider_frame_compare.py out/waverider-m5/screens/after \\
        [--json out/waverider-m5/frame_compare.json]

Milestone 4's open item: every frame the SHARC gates ran was built by
`dnfw.waverider.frame` from the parameter table's defaults; none came from the
ColdFire's builder (`0x400274ba`). `scripts/emu_waverider_menu.py`'s `frame:NAME`
step runs that builder in the ColdFire emulator and keeps three files beside each
other -- `NAME.frame_be.bin` (the 2,688-byte frame at `0x80005e60`),
`NAME.sounds_be.bin` (the sixteen sound objects it was built from) and
`NAME.mirror_be.bin`. This reads them and asks, for every field `frame.py` models:

- is the ColdFire's word at `frame.py`'s offset the value the sound holds?
  (machine type `sound+0xDE`, filter type `sound+0xDF`, and the sound's value
  array `sound+0x14 + 2 * index` for every parameter index the slots carry);
- and which words of the frame `frame.py` does **not** model, with what the
  ColdFire put there.

A slot value that differs from the sound's is not automatically a disagreement:
the builder copies the *modulated* per-track values, so a parameter an LFO is
moving differs by the modulation. Those are listed, not failed, and the run says
how many there were.

The ColdFire writes big-endian 16-bit words at the same offsets the DSP reads
little-endian ones (`--frame-be` in `sharc_waverider_m5.py` swaps each word).
The layouts agree word for word -- the header arrays sit at `2 + 2t` ... `180 + 2t`
on both sides -- which is the evidence that no wider swap happens on the wire;
the wire itself is not measured.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import frame as FR                 # noqa: E402

SOUND_BYTES, VALUES = 1163, 0x14
MACHINE_TYPE, FILTER_TYPE = 0xDE, 0xDF


def be16(b: bytes, off: int) -> int:
    return struct.unpack_from(">H", b, off)[0]


def compare(frame: bytes, sounds: bytes, tracks=range(FR.TRACKS)) -> dict:
    modelled: set[int] = set()
    rows, header = [], []
    for t in tracks:
        s = sounds[t * SOUND_BYTES:(t + 1) * SOUND_BYTES]
        for name, array, want in (("machine type", FR.MACHINE, s[MACHINE_TYPE]),
                                  ("filter type", FR.FILTER, s[FILTER_TYPE])):
            off = FR.header_offset(array, t)
            modelled.add(off)
            header.append({"track": t, "field": name, "offset": off, "coldfire": be16(frame, off),
                           "sound": want, "agree": be16(frame, off) == want})
        for first, last, _ in FR.SLOT_BLOCKS:
            for idx in range(first, last + 1):
                off = FR.slot_offset(t, idx)
                modelled.add(off)
                cf = be16(frame, off)
                sv = struct.unpack_from(">H", s, VALUES + 2 * idx)[0]
                rows.append({"track": t, "index": idx, "offset": off, "coldfire": cf, "sound": sv,
                             "agree": cf == sv})
    for t in tracks:
        for array in (FR.NOTE, FR.LEVEL):
            modelled.add(FR.header_offset(array, t))
    modelled.update(FR.TRIG_MASKS)
    unmodelled = [{"offset": o, "coldfire": be16(frame, o)}
                  for o in range(0, FR.FRAME_BYTES, 2) if o not in modelled and be16(frame, o)]
    differ = [r for r in rows if not r["agree"]]
    return {"header": header, "header_agree": all(h["agree"] for h in header),
            "slot_words": len(rows), "slot_words_agree": len(rows) - len(differ),
            "slot_words_differ": differ,
            "unmodelled_nonzero": unmodelled,
            "unmodelled_nonzero_count": len(unmodelled)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("stem", help="the path before .frame_be.bin / .sounds_be.bin")
    p.add_argument("--json", default=None)
    p.add_argument("--tracks", default="0", help="comma list, or 'all'")
    a = p.parse_args()
    frame = pathlib.Path(a.stem + ".frame_be.bin").read_bytes()
    sounds = pathlib.Path(a.stem + ".sounds_be.bin").read_bytes()
    tracks = range(FR.TRACKS) if a.tracks == "all" else [int(x) for x in a.tracks.split(",")]
    r = compare(frame, sounds, tracks)
    for h in r["header"]:
        print(f"  track {h['track']:2d} {h['field']:12s} @{h['offset']:4d}: ColdFire {h['coldfire']}, "
              f"sound {h['sound']}  {'agree' if h['agree'] else 'DIFFER'}")
    print(f"  slot words: {r['slot_words_agree']} of {r['slot_words']} equal the sound's value array")
    for d in r["slot_words_differ"][:24]:
        print(f"    track {d['track']} index {d['index']} @{d['offset']}: ColdFire {d['coldfire']:#06x}, "
              f"sound {d['sound']:#06x}")
    print(f"  words frame.py does not model that the ColdFire filled: {r['unmodelled_nonzero_count']}")
    for u in r["unmodelled_nonzero"][:40]:
        print(f"    @{u['offset']:4d}: {u['coldfire']:#06x}")
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(r, indent=1) + "\n")
    return 0 if r["header_agree"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
