"""The shared appended area past the end of MAIN OS: its byte layout.

A mod that ships more than a cave holds appends it after MAIN OS's last byte
(`0x4030b980` on 1.11), where nothing addresses it; a startup hook copies it
out before the BSS clear. The boot screen proved the route on hardware
(2026-09-17). So that several mods share one hook, the area is a directory of
chunks -- the layout `scripts/gen_bootscreen_code.py` documents, unchanged:

    +0   'DNFW'
    +4   u32 total length, header included
    +8   u32 chunk count
    +12  per chunk: 4-byte id, u32 offset from the area's start, u32 length
         then the chunks, each padded to four bytes

Data chunks (`BOOT`, `ANIM`, ...) run from `RUNTIME_VA` + their offset, exactly
where the boot screen's whole-area copy has always put them. A `CODE` chunk
instead carries linked code for an address of its own:

    +0   u32 load address        -- where the image runs; longword-aligned
    +4   u32 image length
    +8   u32 bss length          -- zeroed after the image
    +12  u32 init entry, or 0    -- called once, after the firmware's BSS clear
    +16  the image

One subject: building and reading that layout. Who copies it is the loader's
business (`csrc/runtime/loader.c`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"DNFW"
CODE = b"CODE"
AREA_VA = 0x4030B980            # the end of stock 1.11 MAIN OS
RUNTIME_VA = 0x46710000         # where data chunks run, above BSS


class AreaError(ValueError):
    """A malformed area or chunk."""


@dataclass(frozen=True)
class CodeChunk:
    load: int
    image: bytes
    bss: int = 0
    init: int = 0

    def pack(self) -> bytes:
        if self.load % 4:
            raise AreaError(f"code load address 0x{self.load:08x} is not longword-aligned")
        if self.init and not self.load <= self.init < self.load + len(self.image):
            raise AreaError(f"init 0x{self.init:08x} is outside the image")
        image = self.image + bytes(-len(self.image) % 4)
        return struct.pack(">4I", self.load, len(image), self.bss + (-self.bss % 4), self.init) + image

    @classmethod
    def unpack(cls, data: bytes) -> "CodeChunk":
        load, n, bss, init = struct.unpack_from(">4I", data)
        return cls(load, data[16:16 + n], bss, init)


def build(chunks: list[tuple[bytes, bytes]]) -> bytes:
    """[(id, data)] -> the area. Order is kept; each chunk is padded to four bytes."""
    head = 12 + 12 * len(chunks)
    directory, body, offset = b"", b"", head
    for cid, data in chunks:
        if len(cid) != 4:
            raise AreaError(f"chunk id {cid!r} is not four bytes")
        pad = bytes(-len(data) % 4)
        directory += cid + struct.pack(">II", offset, len(data))
        body += data + pad
        offset += len(data) + len(pad)
    return MAGIC + struct.pack(">II", head + len(body), len(chunks)) + directory + body


def parse(blob: bytes) -> list[tuple[bytes, bytes]]:
    """The area -> [(id, data)]."""
    if blob[:4] != MAGIC:
        raise AreaError("no DNFW area here")
    total, count = struct.unpack_from(">II", blob, 4)
    if total > len(blob):
        raise AreaError(f"area claims {total} B, only {len(blob)} present")
    out = []
    for i in range(count):
        cid = blob[12 + 12 * i:16 + 12 * i]
        off, n = struct.unpack_from(">II", blob, 16 + 12 * i)
        if off + n > total:
            raise AreaError(f"chunk {cid!r} runs past the area")
        out.append((cid, blob[off:off + n]))
    return out


def runtime_address(blob: bytes, cid: bytes) -> int:
    """Where a data chunk runs: RUNTIME_VA plus its offset in the area."""
    count = struct.unpack_from(">I", blob, 8)[0]
    for i in range(count):
        if blob[12 + 12 * i:16 + 12 * i] == cid:
            return RUNTIME_VA + struct.unpack_from(">I", blob, 16 + 12 * i)[0]
    raise AreaError(f"no {cid!r} chunk")
