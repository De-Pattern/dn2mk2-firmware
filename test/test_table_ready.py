"""The tables' READY carries this build's checksum.

The DSP decodes the shipped tables once a boot, from the moment the ready word in the pool's DDR holds TABLE_MAGIC.
Nothing clears that word, so a restart that keeps DDR (the restart after a flash: assumed, not verified on the unit)
showed the new DSP the build before's word, and it decoded the build before's table bytes at once. With READY's
second word, the checksum of what this build ships, another build's word never matches and the decode waits."""
import pytest

from dnfw.md import core as K
from dnfw.perc import live as PL
from dnfw.perc.dsl import Mem, Prog
from dnfw.sampler import machines as SM


def test_the_checksum_is_link_c_s():
    # link.c checksum(): a = 1 + the bytes, b = the running sum of a; b << 16 ^ a, 32 bits
    assert SM.table_sum(b"") == 1
    assert SM.table_sum(b"\x01\x02") == ((2 + 4) << 16) ^ 4
    big = bytes(range(256)) * 400
    a, b = 1, 0
    for x in big:
        a, b = (a + x) & 0xFFFFFFFF, (b + a + x) & 0xFFFFFFFF
    assert SM.table_sum(big) == ((b << 16) ^ a) & 0xFFFFFFFF


def test_the_sum_word_is_inside_ready_s_packet():
    assert SM.TABLE_SUM_AT % 4 == 0 and SM.TABLE_READY + SM.TABLE_SUM_AT + 4 <= SM.SLICE_AREA


def _fill_after_one_block(ready_words: dict[int, int]) -> int:
    L = PL.layout().md                 # the instrument's: its ready word at the pool's TABLE_READY
    data = K.tables_bytes()
    m = {L.T[K.SHIPPED] + k: int.from_bytes(data[k:k + 4], "little") for k in range(0, len(data), 4)}
    m.update({L.ready + off: w for off, w in ready_words.items()})
    p = Prog("run", mem=Mem(lambda a: m.get(a, 0)))
    K.table_fill(p, L)
    return p.mem.get(L.C["fill"]) or 0


@pytest.mark.parametrize("words, decodes", [
    ({0: SM.TABLE_MAGIC, SM.TABLE_SUM_AT: None}, True),          # this build's READY
    ({0: SM.TABLE_MAGIC, SM.TABLE_SUM_AT: 0}, False),            # a READY from before the sum (a build before)
    ({0: SM.TABLE_MAGIC, SM.TABLE_SUM_AT: 0x12345678}, False),   # another build's tables
    ({}, False),                                                 # a cold DDR: nothing yet
])
def test_the_decode_waits_for_this_build_s_ready(words, decodes):
    words = {off: (K.table_sum() if w is None else w) for off, w in words.items()}
    assert (_fill_after_one_block(words) > 0) == decodes
