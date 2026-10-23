"""The Digitakt II's DSP image (section 7 of the owner's DT2 OS 1.16/1.17 file), read at
build time for the two tables its sample reader uses (docs/sampler.md, v0.18).

The image is Elektron's, so neither it nor anything copied out of it is in this
repository: the build reads the owner's copy (`DT2_SECTION7`, default
`../dt2s117/section_7_BLOB.bin` beside the repository), checks its sha256, and takes
  - the polyphase interpolator's coefficients: 256 phases x 6 taps, Q31, at DM 0x25d940;
  - the 2:1 decimator's four all-pass coefficients, float32, at DM 0x26ef88.
"""

from __future__ import annotations

import functools
import hashlib
import os
import pathlib
import struct

SHA256 = "0f514a12a2255f5c081e292c47f1f29462003177658da4bbae0a22fd737fffa2"
POLY_DM, POLY_ROWS, POLY_TAPS = 0x25D940, 256, 6
DECIM_DM = 0x26EF88
LOAD_ALIAS = 0x28000000                      # DM byte address -> load address (as the DN2's)


def path() -> pathlib.Path:
    root = pathlib.Path(__file__).resolve().parents[3]
    return pathlib.Path(os.environ.get("DT2_SECTION7", str(root.parent / "dt2s117" / "section_7_BLOB.bin")))


def available() -> bool:
    return path().is_file()


@functools.lru_cache(maxsize=1)
def image() -> bytes:
    data = path().read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise ValueError(f"{path()} is not DT2 1.16/1.17's section 7 (sha256 {digest[:12]}...)")
    return data


def _span(dm: int, n: int) -> bytes:
    from ..image import bootstream
    return bootstream.read_span(image(), LOAD_ALIAS + dm, n)


def polyphase() -> list[list[float]]:
    """256 rows of 6 taps, each the Q31 word / 2^31 (the DSP holds them as float32)."""
    raw = struct.unpack(f"<{POLY_ROWS * POLY_TAPS}i", _span(POLY_DM, 4 * POLY_ROWS * POLY_TAPS))
    return [[x / 2.0 ** 31 for x in raw[POLY_TAPS * r:POLY_TAPS * r + POLY_TAPS]] for r in range(POLY_ROWS)]


def decimator() -> tuple[float, float, float, float]:
    return struct.unpack("<4f", _span(DECIM_DM, 16))


COMB_GAIN_DM = 0x26B338                      # v0.20: COMB's feedback curve, 128 float32


def comb_gain() -> tuple[float, ...]:
    return struct.unpack("<128f", _span(COMB_GAIN_DM, 512))
