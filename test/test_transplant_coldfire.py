"""dnfw.transplant.cfplan / oneshot_cf and dnfw.oneshot.coldfire: the ColdFire half.

The pure tests always run. Everything that reads the donor needs the user's DT2
1.16 file and skips cleanly without it (no DT2 bytes are in this repository).
"""

import json
import pathlib
import struct

import pytest

from dnfw.oneshot import coldfire as OC
from dnfw.transplant import cfspec as C
from dnfw.transplant import oneshot_cf as S

ROOT = pathlib.Path(__file__).resolve().parent.parent
FW = ROOT / "00_Resources" / "00_Firmware"
DT2 = FW / "Digitakt_II_OS1.16_dist" / "Digitakt_II_OS1.16.syx"
DN2 = FW / "Digitone_II_OS1.11_dist.zip"
CODE = ROOT / "src" / "dnfw" / "mods" / "oneshot_code.json"


# -- pure ----------------------------------------------------------------------------------------

def test_cow_rep_is_a_leaked_static_string():
    rep = OC.cow_rep("SAMPLE")
    length, cap, refs = struct.unpack_from(">IIi", rep)
    assert (length, cap, refs) == (6, 6, -1)
    assert rep[12:19] == b"SAMPLE\0" and len(rep) % 4 == 0


def test_layout_fits_the_chunk():
    lay = OC.Layout.fixed()
    assert OC.CHUNK_VA <= lay.strings < lay.names < lay.attributes < lay.machine_list
    assert lay.machine_list < lay.slot_map < lay.descriptor < lay.reps < OC.SHIMS_VA
    assert OC.SHIMS_VA < OC.CHUNK_VA + OC.CHUNK_BYTES
    assert OC.CHUNK_VA > 0x466B74D0            # above BSS


def test_spec_names_eight_records_and_a_formatter_each():
    assert S.RECORDS.count == 8 == len(S.RECORD_FORMATTERS) == len(OC.DEAD_ENTRIES)
    names = {f.name for f in S.TWINS}
    assert set(S.RECORD_FORMATTERS) <= names
    assert S.PAGE.entries == (202, 203, 0, 205, 206, 207, 208, 209)
    # nothing in the spec is a donor byte: only ints, short names, and hex digests
    assert all(len(f.operands) <= 4 for f in S.TWINS)


def test_committed_shims_match_the_layout():
    spec = json.loads(CODE.read_text())
    assert spec["new_type"] == OC.NEW_TYPE and spec["shims_va"] == OC.SHIMS_VA
    labels = spec["labels"]
    assert set(labels) == set(OC.SHIM_LABELS)
    assert all(OC.SHIMS_VA <= v < OC.SHIMS_VA + len(spec["shims"]) // 2 for v in labels.values())
    assert len(bytes.fromhex(spec["group"])) == len(OC.GROUP_STOCK)


def test_committed_shims_are_a_fresh_assembly():
    from dnfw.patch.assemble import assemble, available
    if not available():
        pytest.skip("no m68k assembler")
    built = OC.assemble_shims(assemble)
    spec = json.loads(CODE.read_text())
    assert built["code"].hex() == spec["shims"] and built["group"].hex() == spec["group"]
    assert built["labels"] == spec["labels"]


# -- with the user's two images ------------------------------------------------------------------

@pytest.fixture(scope="module")
def images():
    if not DT2.exists() or not DN2.exists():
        pytest.skip("needs the user's DT2 1.16 and DN2 1.11 images in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    dt2_raw, dn2_raw = read_image(DT2), read_image(DN2)
    return (load(dt2_raw).container.find(3).unpack(), load(dn2_raw).container.find(3).unpack(),
            dt2_raw, dn2_raw)


def test_plan_checks_every_piece(images):
    from dnfw.transplant import cfplan
    donor, recip, _, _ = images
    plan = cfplan.build(S.SPEC, donor, recip)
    assert plan.ok, plan.refusals
    assert len([c for c in plan.checks if c.startswith("formatter")]) == len(S.TWINS)
    keys = dict(plan.strings())
    assert {"machine.long", "machine.short", "page.title", "page.subtitle"} <= set(keys)
    assert len(keys) == 3 * S.RECORDS.count + 4


def test_plan_refuses_the_wrong_donor_and_a_changed_record(images):
    from dnfw.transplant import cfplan
    donor, recip, _, _ = images
    assert not cfplan.build(S.SPEC, recip, recip).ok               # DN2 as the donor
    tampered = bytearray(donor)
    at = S.RECORDS.donor - 0x40000400 + C.MAXIMUM
    tampered[at] ^= 1
    plan = cfplan.build(S.SPEC, bytes(tampered), recip)
    assert not plan.ok and "hashes to" in plan.refusals[0]          # the whole-section guard


def test_report_carries_no_donor_string(images):
    from dnfw.transplant import cfplan
    donor, recip, _, _ = images
    plan = cfplan.build(S.SPEC, donor, recip)
    text = json.dumps(plan.report())
    for key, value in plan.strings():
        if len(value) > 3 and value not in S.RECORDS.labels:   # our labels are the manual's names
            assert value not in text, key


def test_compose_puts_the_records_in_the_dead_entries(images):
    from dnfw.transplant import cfplan
    from dnfw.mods import oneshot as MOD
    donor, recip, _, _ = images
    plan = cfplan.build(S.SPEC, donor, recip)
    out = OC.compose(recip, plan, MOD.shims())
    content = out["content"]
    for k, e in enumerate(OC.DEAD_ENTRIES):
        va = OC.record_va(e) - 0x40000400
        rec = content[va:va + C.RECORD]
        page, slot = struct.unpack_from(">II", rec)
        assert page == OC.RECORD_PAGE and 25 <= slot <= 34
        fmt = struct.unpack_from(">I", rec, C.FORMATTER)[0]
        assert fmt == S.SPEC.formatter(S.RECORD_FORMATTERS[k]).recipient
    assert out["layout"]["page_entries"] == [1, 2, 0, 4, 5, 11, 12, 13]
    assert out["layout"]["slot_map"] == {25: 1, 26: 2, 27: 3, 28: 4, 31: 5, 32: 11, 33: 12, 34: 13}
    # everything outside the edits, the loader and the appended area is stock
    edited = set()
    for e in out["edits"]:
        edited.update(range(e.va - 0x40000400, e.va - 0x40000400 + len(e.new)))
    loader_bytes = {i for i in range(len(recip)) if content[i] != recip[i]} - edited
    assert len(loader_bytes) < 200          # the loader in its cave and its startup call


def test_mod_builds_a_verifying_image(images, tmp_path):
    from dnfw.firmware.build import build as rebuild, replacement
    from dnfw.firmware.load import load
    from dnfw.firmware.verify import verify
    from dnfw.mods import oneshot as MOD
    from dnfw.oneshot import samples as SM
    _, _, dt2_raw, dn2_raw = images
    out = MOD.compose(dn2_raw, dt2_raw, SM.chirp())
    fw = load(dn2_raw)
    image = rebuild(fw, {sid: replacement(fw, sid, out[sid]) for sid in (MOD.MAIN_OS, MOD.DSP_STREAM)})
    assert verify(load(image)).ok
