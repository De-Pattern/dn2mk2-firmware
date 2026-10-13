"""PING's ColdFire half, as recorded in waverider_code.json (dnfw.ping.coldfire)."""

import json
import pathlib
import struct

from dnfw.ping import coldfire as P
from dnfw.ping import pages as PP

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "src/dnfw/mods/waverider_code.json").read_text())
LAY = SPEC["layout"]
CHUNK = SPEC["ping_chunk"]
CODE = bytes.fromhex(CHUNK["code"])


def _at(va: int, n: int) -> bytes:
    off = va - CHUNK["load"]
    assert 0 <= off and off + n <= len(CODE)
    return CODE[off:off + n]


def _edit(va: int) -> dict:
    hits = [e for e in SPEC["edits"] if e["va"] == va]
    assert len(hits) == 1, f"{va:#x}: {len(hits)} edits"
    return hits[0]


def test_chunk_place():
    assert CHUNK["load"] == P.LOAD == LAY["ping_slot"]
    assert P.LOAD + len(CODE) <= P.END
    # Waverider's page chunk ends before PING's begins
    wr = SPEC["chunk"]
    assert wr["load"] + len(bytes.fromhex(wr["code"])) <= P.LOAD
    assert LAY["ping_code_end"] <= LAY["ping_list"] < LAY["ping_names"] < LAY["ping_end"]


def test_list_has_ping_last():
    n = len(P.LIST_NEW)
    got = struct.unpack(f">{n}i", _at(LAY["ping_list"], 4 * n))
    assert got == (0, 1, 4, 3, 5, 2, 6)
    assert LAY["ping_list_end"] == LAY["ping_list"] + 4 * n
    assert _edit(P.LIST_ALLOC)["new"] == "4878001c"
    assert _edit(P.LIST_CAP)["new"] == "41e8001c"
    assert _edit(P.LIST_BEGIN)["new"] == "4879" + f"{LAY['ping_list']:08x}"
    assert _edit(P.LIST_END)["new"] == "4879" + f"{LAY['ping_list_end']:08x}"


def _cstr(va: int) -> str:
    off = va - CHUNK["load"]
    return CODE[off:CODE.index(b"\0", off)].decode()


def test_names_row_six():
    row = _at(LAY["ping_names"] + 12 * 6, 12)
    lo, sh, third = struct.unpack(">III", row)
    assert (_cstr(lo), _cstr(sh), third) == ("Ping", "PING", 0)
    for bound, base, _op, col in P.NAME_SITES:
        assert _edit(bound)["stock"] == "7205" and _edit(bound)["new"] == "7206"
        assert _edit(base + 2)["new"] == f"{LAY['ping_names'] + col:08x}"


def test_load_keeps_six_and_hooks():
    e = _edit(P.LOAD_BOUND)
    assert (e["stock"], e["new"]) == ("143c0007", "143c0008")
    assert _edit(P.SLOT_SITE)["new"] == "4ef9" + f"{LAY['ping_slot']:08x}"
    assert _edit(P.SLOT_SITE)["stock"] == P.SLOT_STOCK.hex()
    assert _edit(P.OVER_SITE)["new"] == "4eb9" + f"{LAY['ping_over']:08x}"
    assert _edit(P.OVER_SITE)["stock"] == P.OVER_STOCK.hex()


def test_guards_recorded():
    have = {(g["va"], g["bytes"]) for g in SPEC["guards"]}
    for va, want, _ in P.GUARDS:
        assert (va, want) in have


def test_renamed_records_are_filter_records():
    # Multi-Mode's (page 5) or the filter envelope's (page 13), never a machine's
    stock = (ROOT.parent / "sec111/section_3_MAIN_OS.bin")
    if not stock.exists():
        return
    d = stock.read_bytes()
    for rid, _long, short in PP.NAMED:
        page = struct.unpack(">i", d[0x401F7F94 - 0x40000400 + 60 * rid:][:4])[0]
        assert page in (5, 13), (rid, page)
        assert 1 <= len(short) <= 5
