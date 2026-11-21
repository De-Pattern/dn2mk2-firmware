"""v0.69: the voice/load guardrail's table (src/dnfw/sampler/guardrail.py -> csrc/sampler/guard_tab.h)"""
from dnfw.sampler import guardrail as GR
from dnfw.waverider import coldfire


def test_header_is_current():
    assert GR.HEADER.read_text() == GR.header()


def test_every_mod_machine_weighs_and_stock_does_not():
    assert set(GR.PER_VOICE) == set(coldfire.NEW_TYPES)
    for t in range(5):
        assert GR.weight(t) == 0


def test_limit_inside_what_is_free():
    assert 0 < GR.LIMIT <= GR.FREE
