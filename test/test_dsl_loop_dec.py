"""dnfw.perc.dsl loop_r: with ONE the counter itself, the count steps down by `Rc = Rc - 1;`
(dec) and no register is set to 1; with any other ONE, as before (ONE = 1, Rc = Rc - ONE)."""

from __future__ import annotations

from dnfw.perc.dsl import Mem, Prog


def _count(one: int) -> tuple[int, list[str]]:
    runs = []
    r = Prog("run", mem=Mem(lambda a: 0))
    r.iconst(9, 0)
    r.loop_r(0, 5, lambda: (runs.append(1), r.iconst(9, 7)), one=one)
    e = Prog("emit")
    e.loop_r(0, 5, lambda: e.iconst(9, 7), one=one)
    return len(runs), [t.strip() for t in e.text().splitlines()]


def test_one_the_counter_steps_by_dec():
    n, code = _count(0)
    assert n == 5
    assert "R0 = R0 - 1;" in code
    assert not any(t.startswith("R0 = 1") or t == "R0 = R0 - R0;" for t in code)


def test_another_one_is_as_before():
    n, code = _count(12)
    assert n == 5
    assert any(t.startswith("R12 = 1") or t.startswith("R12 = 0x1") for t in code)
    assert "R0 = R0 - R12;" in code
