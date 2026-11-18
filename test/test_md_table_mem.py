"""dnfw.md.bench.table_mem: the Machinedrum tables as the DSP holds them, built once per layout.

The bench (layout(): the tables in place, no ready word) and PERC's live harness (dnfw.perc.live:
the same tables address, the shipped part in the sample pool, a ready word) both ask for them. Kept
by the tables address alone, whichever came first served the other: after a test that built a
harness, the bench's machines read a table area without its shipped part and played silence
(test_md failed every case of EFM, GND and P-I when test_perc_live.py ran before it)."""

import pytest

from dnfw.md import bench as B
from dnfw.md import rom


def _need_rom():
    if not rom.available():
        pytest.fail("needs the Machinedrum's firmware: MD_OS_BIN (docs/md.md)")


def test_each_layout_gets_its_own_tables_whatever_was_built_first():
    _need_rom()
    from dnfw.perc import live as PL
    bench_L, harness_L = B.layout(), PL.layout().md
    assert bench_L.tables == harness_L.tables         # the case: one address, two layouts
    saved = dict(B._TABLE_MEM)
    try:
        B._TABLE_MEM.clear()
        bench_alone = dict(B.table_mem(bench_L))
        B._TABLE_MEM.clear()
        harness_alone = dict(B.table_mem(harness_L))
        assert bench_alone != harness_alone
        B._TABLE_MEM.clear()
        B.table_mem(harness_L)                         # the harness first, as test_perc_live leaves it
        assert B.table_mem(bench_L) == bench_alone
        assert B.table_mem(harness_L) == harness_alone
    finally:
        B._TABLE_MEM.clear()
        B._TABLE_MEM.update(saved)
