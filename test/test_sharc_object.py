"""A selas object -> the bytes the SHARC loads (`dnfw.image.sharc_object`).

Built on a synthetic ELF32 object, so no selache is needed to run it.
"""

import struct

import pytest

from dnfw.image import sharc_object


def _elf(sections):
    """A minimal ELF32 LE object: [(name, type, body, link)] after a null section."""
    names = b"\0" + b"".join(n.encode() + b"\0" for n, _, _, _ in sections) + b".shstrtab\0"
    bodies, at = b"", 0x34
    headers = [(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)]
    name_at = 1
    for n, kind, body, link in sections:
        headers.append((name_at, kind, 0, 0, at + len(bodies), len(body), link, 0, 1, 16 if kind == 2 else 0))
        name_at += len(n) + 1
        bodies += body
    headers.append((name_at, 3, 0, 0, at + len(bodies), len(names), 0, 0, 1, 0))
    bodies += names
    shoff = at + len(bodies)
    ident = b"\x7fELF\x01\x01\x01" + bytes(9)
    head = ident + struct.pack("<HHIIIIIHHHHHH", 1, 0x85, 1, 0, 0, shoff, 0, 0x34, 0, 0,
                               40, len(headers), len(headers) - 1)
    return head + bodies + b"".join(struct.pack("<10I", *h) for h in headers)


def test_sharc_object_code_symbols_and_parcel_swap():
    strtab = b"\0f.\0"
    symtab = bytes(16) + struct.pack("<IIIBBH", 1, 3, 0, 0x12, 0, 1)
    obj = _elf([("seg_pmco", 1, bytes.fromhex("12345678"), 0),
                ("strtab", 3, strtab, 0), ("symtab", 2, symtab, 2)])
    assert sharc_object.code(obj, "seg_pmco") == bytes.fromhex("12345678")
    assert sharc_object.load_bytes(bytes.fromhex("12345678")) == bytes.fromhex("34127856")
    assert sharc_object.symbols(obj) == {"f.": 3}


def test_sharc_object_refuses_relocations():
    obj = _elf([("seg_pmco", 1, b"\0\0", 0), (".rela.seg_pmco", 4, b"", 0)])
    with pytest.raises(sharc_object.ObjectError):
        sharc_object.code(obj, "seg_pmco")
