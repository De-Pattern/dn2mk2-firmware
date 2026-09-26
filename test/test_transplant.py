"""dnfw.transplant: the SHARC relocation arithmetic and the ONESHOT plan.

The pure-arithmetic tests always run. The plan tests need the user's DT2 1.16
and DN2 1.11 files and skip cleanly when either is absent (no DT2 bytes are in
this repository).
"""

import pathlib

import pytest

from dnfw.transplant import oneshot_dt2 as O
from dnfw.transplant import sharc as S

ROOT = pathlib.Path(__file__).resolve().parent.parent
FW = ROOT / "00_Resources" / "00_Firmware"
DT2 = FW / "Digitakt_II_OS1.16_dist" / "Digitakt_II_OS1.16.syx"
DN2 = FW / "Digitone_II_OS1.11_dist.zip"
DT2_15C = FW / "Digitakt_II_OS1.15C.syx"


# -- relocation arithmetic (pure) -------------------------------------------------------------

def test_code_and_data_addresses():
    assert S.code_address(0x1C4ECF) == 0x28000000 + 2 * 0x1C4ECF
    assert S.data_address(0x25D940) == 0x28000000 + 0x25D940
    assert S.code_address(0xB80000, "l2") == 0x20000000 + 2 * (0xB80000 - 0x00B80000)


def test_value_bytes_roundtrip():
    value = 0xF150025D940
    assert S.to_value(S.to_bytes(value)) == value
    assert S.get_field(value, "data32") == 0x25D940


def test_retarget_absolute_and_relative():
    # a 17a `I5 = 0x25d940` -> point it at 0x294000
    v = 0xF150025D940
    v2 = S.retarget(v, "data32", 0x1809DB, 0x294000)
    assert S.get_field(v2, "data32") == 0x294000
    # an 8a_rel CALL at sw src to donor target keeps its meaning after moving both
    src, dst = 0x1C5193, 0x1C06BA
    rel = S.retarget(0, "rel24", src, dst)  # build a rel field
    assert S.target_of(rel, "rel24", src) == dst
    moved = S.retarget(rel, "rel24", 0x180AC4, 0x180D00)
    assert S.target_of(moved, "rel24", 0x180AC4) == 0x180D00


def test_spec_shape():
    assert O.SPEC.entry == "render"
    assert sum(sp.size for sp in O.SPEC.spans if sp.kind == "code" and sp.name != "decimator")
    names = {sp.name for sp in O.SPEC.spans}
    assert names == {"render", "divide", "decimator", "coeff", "deccoef"}
    # every site names a span that exists and a target span that exists
    for site in O.SPEC.sites:
        assert O.SPEC.span(site.span).kind == "code"
        assert O.SPEC.span(site.refers_to)


# -- the plan against the two user images (skips without them) --------------------------------

def _need(path: pathlib.Path):
    if not path.exists():
        pytest.skip(f"{path.name} not present; the transplant needs the user's own file")


def _raw(path):
    from dnfw.cli.files import read_image
    return read_image(path)


def test_plan_builds_and_relocates():
    _need(DT2); _need(DN2)
    from dnfw.transplant import plan as P
    plan = P.build(O.SPEC, _raw(DT2), _raw(DN2))
    assert plan.ok, plan.refusals
    assert len(plan.relocations) == len(O.SPEC.sites)
    # every span's donor bytes hashed to the recorded digest (checked inside build)
    report = plan.report()
    assert report["donor_bytes_moved"] == sum(sp.nbytes for sp in O.SPEC.spans)
    # a relative site keeps its target across the move
    call = next(r for r in plan.relocations if r["field"] == "rel24")
    assert call["donor_target"].startswith("sw 0x1c06ba")


def test_plan_refuses_wrong_donor_version():
    _need(DT2_15C); _need(DN2)
    from dnfw.transplant import plan as P
    plan = P.build(O.SPEC, _raw(DT2_15C), _raw(DN2))
    assert not plan.ok
    assert any("1.15C" in r or "section 7" in r for r in plan.refusals)


def test_plan_refuses_wrong_device():
    _need(DT2); _need(DN2)
    from dnfw.transplant import plan as P
    assert not P.build(O.SPEC, _raw(DN2), _raw(DN2)).ok       # DN2 as donor
    assert not P.build(O.SPEC, _raw(DT2), _raw(DT2)).ok       # DT2 as recipient
