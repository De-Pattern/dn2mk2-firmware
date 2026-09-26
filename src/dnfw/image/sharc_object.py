"""A SHARC+ object file from selache's `selas` -> the bytes the DSP loads.

`selas` (GPL-3.0, run as a tool in WSL, never linked in: `docs/sharc-selache.md`)
writes an ELF32 relocatable object. This reads it with the standard library
alone, so nothing here depends on selache.

**Byte order.** A PM section in the object holds each 16-bit VISA parcel
big-endian; the boot stream and the DSP's memory hold it little-endian, parcel
by parcel ("LE, MSB word first", `docs/sharc-selache.md`). `load_bytes` swaps
each parcel. The round trip in `scripts/sharc_selache_roundtrip.py` is the
measurement behind it: 9,599 of 11,440 firmware encodings reassembled
byte-identical under exactly this swap.

**Relocations are refused.** Milestone 1's reader is position-independent --
pc-relative branches, no absolute addresses -- so the object must carry no
relocation section; if one appears, the code would need a linker (`seld`) and
an LDF, and placing the raw section anywhere would be wrong.
"""

from __future__ import annotations

import struct

SHT_SYMTAB = 2
SHT_RELA = 4
SHT_REL = 9


class ObjectError(ValueError):
    pass


def sections(data: bytes) -> dict[str, tuple[int, bytes]]:
    """-> {section name: (section type, bytes)} from an ELF32 little-endian object."""
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ObjectError("not an ELF32 little-endian object")
    shoff, = struct.unpack_from("<I", data, 0x20)
    ent, num, stridx = struct.unpack_from("<HHH", data, 0x2E)
    headers = [struct.unpack_from("<10I", data, shoff + i * ent) for i in range(num)]
    names = headers[stridx][4]
    out = {}
    for h in headers:
        name = data[names + h[0]:].split(b"\0", 1)[0].decode()
        out[name] = (h[1], data[h[4]:h[4] + h[5]])
    return out


def code(data: bytes, section: str) -> bytes:
    """-> one PM section's bytes, parcel order as stored in the object (big-endian)."""
    found = sections(data)
    relocs = [n for n, (kind, _) in found.items() if kind in (SHT_REL, SHT_RELA)]
    if relocs:
        raise ObjectError(f"the object has relocations ({', '.join(relocs)}); "
                          "it needs linking, not raw placement")
    if section not in found:
        raise ObjectError(f"no section {section!r}; have {', '.join(n for n in found if n)}")
    body = found[section][1]
    if len(body) % 2:
        raise ObjectError(f"section {section!r} is {len(body)} bytes, not whole 16-bit parcels")
    return body


def load_bytes(parcels_be: bytes) -> bytes:
    """Object parcel order -> memory order: swap each 16-bit parcel."""
    if len(parcels_be) % 2:
        raise ObjectError("not whole 16-bit parcels")
    out = bytearray(parcels_be)
    out[0::2], out[1::2] = parcels_be[1::2], parcels_be[0::2]
    return bytes(out)


def symbols(data: bytes) -> dict[str, int]:
    """-> {symbol name: value} from the object's `.symtab`, named via its linked strtab.

    In a selas object a label's value is its offset in its section in 16-bit
    parcels (PM short words), not bytes.
    """
    shoff, = struct.unpack_from("<I", data, 0x20)
    ent, num, _ = struct.unpack_from("<HHH", data, 0x2E)
    headers = [struct.unpack_from("<10I", data, shoff + i * ent) for i in range(num)]
    out = {}
    for h in headers:
        if h[1] != SHT_SYMTAB:
            continue
        strtab = headers[h[6]]
        names = data[strtab[4]:strtab[4] + strtab[5]]
        for at in range(h[4], h[4] + h[5], 16):
            name_at, value = struct.unpack_from("<II", data, at)
            name = names[name_at:].split(b"\0", 1)[0].decode()
            if name:
                out[name] = value
    return out
