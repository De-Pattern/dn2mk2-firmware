"""v0.40: the +Drive library's folders inside folders, as csrc/sampler/lib.c reads and makes them.

The folder table is 64 records of 32 bytes (sectors LIB + 257 .. 260). Until v0.40 a record was
a name of up to 31 characters and zeros, byte 31 always 0. v0.40 keeps a folder's parent in
that byte: 0 for a top-level folder (so every older library is all top-level folders, read as
it was), 0x80 | the parent's index for a folder inside a folder, whose name is then at most 30
characters (byte 30 is 0). An older build reads such a record as its own name, at the top.

`tree` is lib.c's `folder_tree`: whatever the records hold (a parent dropped by an older build,
a sector torn by a power cut, a loop), the result is a tree DEPTH deep at most in which every
folder appears. `levels` is how a path becomes folders (lib.c's link 17, the import page).
The emulator checks (scripts/emu_lib_nest.py) hold the firmware's answers to this model.

v0.43: 128 folders (64..127 in their own sectors, lib.c LIB_HI_AT); a parent 64..127 is tagged
0xC0 | (parent - 64) (an older build reads it as a top-level folder).
"""

from __future__ import annotations

FOLDERS = 128                                   # v0.43 (64 before)
LO = 64                                         # those in the library's headers
RECORD = 32
DEPTH = 6                                       # lib.c LIB_DEPTH: a top-level folder is depth 1
TOP_NAME = RECORD - 1                           # 31 characters at the top
NESTED_NAME = RECORD - 2                        # 30 inside a folder


def record(name: str, parent: int | None = None) -> bytes:
    """a folder record as lib.c's folder_set_in writes it"""
    b = name.encode("ascii", "replace")[:NESTED_NAME if parent is not None else TOP_NAME]
    r = bytearray(RECORD)
    r[:len(b)] = b
    if parent is not None and b:
        r[RECORD - 1] = 0x80 | parent if parent < LO else 0xC0 | (parent - LO)
    return bytes(r)


def tree(table: bytes) -> list[int]:
    """each folder's parent as the browser takes it (-1: the top), from the 64 records"""
    rec = [bytearray(table[RECORD * f:RECORD * f + RECORD].ljust(RECORD, b"\0")) for f in range(FOLDERS)]
    for r in rec:                               # a tag after 31 letters: no tag (a torn record)
        if r[RECORD - 1] and r[RECORD - 2]:
            r[RECORD - 1] = 0
    named = [r[0] != 0 for r in rec]
    par = []
    for f, r in enumerate(rec):
        t = r[RECORD - 1]
        p = (t & 0x3F) + (LO if (t & 0xC0) == 0xC0 else 0)
        par.append(p if (t & 0x80) and named[f] and p != f and named[p] and not r[RECORD - 2] else -1)
    for f in range(FOLDERS):                    # a loop or too deep: from here, the top
        p, d = par[f], 1
        while p >= 0 and d <= DEPTH:
            p, d = par[p], d + 1
        if p >= 0 or d > DEPTH:
            par[f] = -1
    return par


def names(table: bytes) -> list[str]:
    """each record's name (what any build shows: it always ends inside the record)"""
    out = []
    for f in range(FOLDERS):
        r = table[RECORD * f:RECORD * f + RECORD]
        out.append(r[:TOP_NAME].split(b"\0")[0].decode("ascii", "replace"))
    return out


def depth(par: list[int], f: int) -> int:
    d = 1
    while par[f] >= 0:
        f, d = par[f], d + 1
    return d


def path(table: bytes, f: int) -> str:
    par, nm = tree(table), names(table)
    out = []
    while f >= 0:
        out.append(nm[f])
        f = par[f]
    return "/".join(reversed(out))


def levels(p: str, *, limit: int = DEPTH) -> list[str]:
    """a path as link 17 makes it (lib.c folder_path): '/' between levels, the spaces next to
    a '/' and empty levels dropped (a name with no '/' kept as it came), each level cut to 31
    characters, then to its record (31 at the top, 30 inside a folder); past LIMIT, nothing"""
    parts = p.split("/")
    out = []
    for i, x in enumerate(parts):
        if i > 0:
            x = x.lstrip(" ")
        x = x[:TOP_NAME]
        if i < len(parts) - 1:
            x = x.rstrip(" ")
        if x:
            out.append(x if not out else x[:NESTED_NAME])
    return out[:limit]
