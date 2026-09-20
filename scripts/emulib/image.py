"""What a build produced, read without needing the emulator or dnfw.

These run under digikit's venv, which has neither `dnfw` nor a way to unpack a
`.syx`, so every build script writes the patched section and its symbols beside
it and these read those. One subject: turning a build's output into the things
a harness has to put into a machine.
"""

from __future__ import annotations

import json
import pathlib
import struct

BASE = 0x40000400                 # where MAIN OS loads
AREA_VA = 0x4030B980              # the end of stock 1.11, where the DNFW area starts


def load_build(directory: str | pathlib.Path):
    """-> (the patched section, {symbol: address}) a build wrote."""
    d = pathlib.Path(directory)
    image = (d / "section_3_MAIN_OS.bin").read_bytes()
    symbols = {k: int(v, 16) for k, v in json.loads((d / "symbols.json").read_text()).items()}
    return image, symbols


def differences(stock: bytes, built: bytes):
    """-> [(virtual address, bytes)] for every run the build changed.

    A build that appends the `DNFW` area is longer than stock; the tail is
    simply another run, since nothing in stock occupies it.
    """
    if len(built) < len(stock):
        raise SystemExit(f"built section is shorter than stock: {len(built):,} < {len(stock):,}")
    runs, start = [], None
    for i in range(len(stock) + 1):
        same = i == len(stock) or stock[i] == built[i]
        if not same and start is None:
            start = i
        elif same and start is not None:
            runs.append((BASE + start, built[start:i]))
            start = None
    if len(built) > len(stock):
        runs.append((BASE + len(stock), built[len(stock):]))
    return runs


def code_chunk(image: bytes):
    """-> (load, image length, bss, init, bytes) of the appended `CODE` chunk.

    This is what the startup loader reads. A harness that restores a snapshot
    has already run past the loader, so it must do this itself.
    """
    a = AREA_VA - BASE
    count = struct.unpack_from(">I", image, a + 8)[0]
    off = next(struct.unpack_from(">I", image, a + 16 + 12 * i)[0]
               for i in range(count) if image[a + 12 + 12 * i:a + 16 + 12 * i] == b"CODE")
    load, length, bss, init = struct.unpack_from(">4I", image, a + off)
    return load, length, bss, init, image[a + off + 16:a + off + 16 + length]


def sites(directory: str | pathlib.Path):
    """-> [(what, address, patched bytes, stock bytes)] the build recorded.

    Not a second list to keep in step with the build's: the build writes
    `sites.json` as it patches, so a harness installs exactly what it installed.
    """
    rows = json.loads((pathlib.Path(directory) / "sites.json").read_text())
    return [(s["what"], int(s["va"], 16), bytes.fromhex(s["bytes"]), bytes.fromhex(s["stock"]))
            for s in rows]
