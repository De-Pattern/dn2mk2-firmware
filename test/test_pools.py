"""v0.38, per-project sample pools (csrc/sampler/pools.c, docs/project-pools.md): what can be
checked without the emulator -- the region, the hooks, the gate step. The behaviour itself is
the ship gate's emulator step `per-project pools (ColdFire)` (scripts/emu_pools.py)."""

from __future__ import annotations

import json
import pathlib
import re

from dnfw.sampler import machines as SM

ROOT = pathlib.Path(__file__).resolve().parents[1]
POOLS = (ROOT / "csrc/sampler/pools.c").read_text()


def _define(name: str) -> int:
    return int(re.search(rf"#define {name} (0x[0-9A-Fa-f]+|\d+)u?\b", POOLS).group(1), 0)


def test_the_lists_lie_between_the_pool_image_and_the_library():
    pool_end = 0x600000 + 1 + SM.POOL_BYTES // 512          # link.c's image: its last sector + 1
    sb, lists, span, n = _define("PL_SB"), _define("PL_LISTS"), _define("PL_SPAN"), _define("PL_N")
    end = lists + 2 * n * span
    assert (sb, lists, span, n) == (0x6D0000, 0x6D0100, 256, 129)
    assert pool_end <= sb < lists and end <= 0x700000          # the library's first sector
    assert "_Static_assert(PL_SB >= POOL_STORE_END" in POOLS and "_Static_assert(PL_END <= LIB_SECTOR" in POOLS
    # every read and write is bounded to the region
    assert "sector >= PL_SB && sector < PL_END" in POOLS and "n <= PL_END - sector" in POOLS
    assert POOLS.count("BLK_WRITE(") == 1                     # pl_wr's one call


def test_a_list_is_written_parts_first_header_last():
    body = POOLS[POOLS.index("static int list_write"):POOLS.index("/* -- extents no new sample")]
    parts = [body.index("pl_wr(s + L_SUMS"), body.index("pl_wr(s + L_META"), body.index("pl_wr(s + L_AREA"),
             body.index("pl_wr(s, 512u, h)")]
    assert parts == sorted(parts)
    assert "int c = li->valid ? 1 - li->copy : 0;" in body     # into the older copy


def test_the_four_detours_are_at_their_stock_sites():
    spec = json.loads((ROOT / "src/dnfw/mods/waverider_code.json").read_text())
    edits = {e["va"]: e for e in spec["edits"]}
    want = {0x40042E6E: "4fefffdc48d7043c", 0x40042ED2: "2f052f034ebabc8a",
            0x40042EE6: "10044cd7043c4fef0024", 0x40042AF0: "2eae000c2f0a4ebac06a"}
    lay = spec["layout"]
    for va, stock in want.items():
        e = edits[va]
        assert e["stock"] == stock, hex(va)
        assert e["new"].startswith("4ef9") and len(e["new"]) == len(stock)
        assert set(e["new"][12:]) <= set("4e71")           # the rest nops
    hooks = (ROOT / "csrc/sampler/hooks.S").read_text()
    for back in ("jmp     0x40042E76", "jmp     0x40042EDA", "jmp     0x40042AFA", "jsr     0x4003EB62"):
        assert back in hooks
    for name in ("smp_pl_on", "smp_pl_owner", "smp_pj_loads", "smp_pj_news", "smp_blank_req"):
        assert name in lay


def test_the_gate_runs_the_pools_step():
    gate = (ROOT / "scripts/ship_gate.py").read_text()
    assert '("pools", "per-project pools (ColdFire)")' in gate and "link16:{syms}:pools" in gate
    assert 'later("pools", "per-project pools (ColdFire)"' in gate
    emu = (ROOT / "scripts/emu_pools.py").read_text()
    assert emu.count('facts[') >= 16
