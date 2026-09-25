"""What a WAV wavetable input is, and gathering them from a file or a folder.

**One subject: describing inputs, not decoding them.** Decoding is
`dnfw.wavetable.parse_wav` (reused by `reduce.from_wav`); this reads only the
RIFF headers, so a folder of third-party tables can be checked against what
the pipeline assumes *before* anything is baked.

**What the pipeline assumes about an input**, stated once, here:

  * RIFF/WAVE; PCM 8/16/24/32-bit or IEEE float 32/64-bit (`WAVE_FORMAT_EXTENSIBLE`
    is followed to its real tag);
  * any channel count -- **only the first channel is used**;
  * any sample rate -- **ignored**: a wavetable is a list of cycles, not audio;
  * frame length from a Serum-style `clm ` chunk (`<!>2048 ...`) if present,
    otherwise **2048** when the sample count divides by it, otherwise **the
    whole file is one frame** -- the last case is almost always a table of
    another frame length (256, 512, 1024 ...) and is flagged as a warning;
  * any number of frames -- brought to **16** by linear interpolation along the
    table (so 64 frames are sampled, not averaged, and 2 are blended);
  * each frame brought to **512** points by a box average -- a frame shorter
    than 512 points is therefore *held*, each point repeated, not interpolated --
    and the whole table scaled to a peak of 32767 (relative frame levels kept).

**Licence.** Tables that are not ours (Elektron's factory set, the Make Noise
pack, anything third-party) may be scanned and baked here **for local testing
only**; none of them goes into a build this project ships.
"""

from __future__ import annotations

import pathlib
import struct

from ..wavetable import DEFAULT_FRAME

TARGET_FRAMES = 16          # `reduce.FRAMES`; not imported, because `reduce` imports this

TAGS = {1: "PCM", 3: "float"}


def clm_frame(body: bytes) -> int | None:
    """A `clm ` chunk -> its frame length: the digits right after `<!>`.

    **Not `dnfw.wavetable`'s reading**, which keeps every digit in the five
    characters after `<!>` -- right for Serum's `<!>2048 ...`, wrong for a
    shorter frame: `<!>256 00000000` reads as 2560. The LFO path (and its
    parity twin `site/js/wavetable.js`) is left alone here because it ships;
    this module reads only the leading run of digits.
    """
    text = body.decode("latin1")
    if not text.startswith("<!>"):
        return None
    digits = ""
    for ch in text[3:]:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits else None


def info(data: bytes) -> dict:
    """-> the header facts of one WAV, and what the pipeline will do with it."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return {"ok": False, "error": "not a RIFF/WAVE file"}
    out: dict = {"ok": True, "clm": None, "warnings": []}
    at, fmt, nbytes = 12, None, None
    while at + 8 <= len(data):
        cid, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        body = data[at + 8:at + 8 + size]
        if cid == b"fmt " and len(body) >= 16:
            tag, channels, rate, _, _, bits = struct.unpack_from("<HHIIHH", body)
            if tag == 0xFFFE and len(body) >= 26:
                tag = struct.unpack_from("<H", body, 24)[0]
            fmt = (tag, channels, rate, bits)
        elif cid == b"clm ":
            out["clm"] = clm_frame(body)
        elif cid == b"data":
            nbytes = len(body)
        at += 8 + size + (size & 1)
    if fmt is None or nbytes is None:
        return {"ok": False, "error": "no fmt or no data chunk"}
    tag, channels, rate, bits = fmt
    samples = nbytes // max(1, (bits // 8) * channels)
    if out["clm"]:
        frame, origin = out["clm"], "clm chunk"
    elif samples % DEFAULT_FRAME == 0:
        frame, origin = DEFAULT_FRAME, "default 2048"
    else:
        frame, origin = samples, "whole file"
        out["warnings"].append(f"{samples} samples do not divide by 2048 and there is no "
                               f"clm chunk: read as ONE frame -- check the real frame length")
    out.update(encoding=f"{TAGS.get(tag, f'tag {tag}')} {bits}-bit", channels=channels,
               rate=rate, samples=samples, frame=frame, origin=origin,
               frames=samples // frame if frame else 0)
    if (tag, bits) not in ((1, 8), (1, 16), (1, 24), (1, 32), (3, 32), (3, 64)):
        out["ok"] = False
        out["error"] = f"unsupported encoding {out['encoding']}"
    if frame and frame < 512:
        out["warnings"].append(f"{frame}-point frames are held, not interpolated, up to 512")
    if channels > 1:
        out["warnings"].append(f"{channels} channels: only the first is used")
    if out["frames"] and out["frames"] != TARGET_FRAMES:
        how = "sampled down" if out["frames"] > TARGET_FRAMES else "interpolated up"
        out["warnings"].append(f"{out['frames']} frames {how} to {TARGET_FRAMES}")
    return out


def collect(path: pathlib.Path) -> list[pathlib.Path]:
    """A WAV file, or every `.wav` under a folder (recursively, sorted)."""
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".wav")
    return [path]
