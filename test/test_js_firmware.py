"""The browser firmware stack, checked against the Python one on a real image.

`test_js_codec.py` covers the codec. This covers the four layers above it --
SysEx transport, ELE3 container, integrity, and the order they go in -- which
together are everything the browser tool needs to hand a user a `.syx` they can
flash.

Two checks here are stronger than anything in the codec file:

**The round-trip.** Load a real image and build it straight back with nothing
replaced; the output must be byte-identical to the input. One comparison
exercises SysEx framing, 8-in-7, per-packet checksums, marker counters, the
container layout, the content checksum and the HMAC trailer at once, and any
one of them being wrong shows up as a differing byte. It is `docs/ROADMAP.md`'s
Gate A, in JavaScript.

**The agreement.** Build a store-only image in JS, build the same image in
Python, and compare. Two toolchains sharing no lineage producing the same
bytes is a stronger statement than either one verifying itself, and it is the
check that would catch a shared *assumption* rather than a coding slip -- the
kind of thing that makes both implementations wrong in the same direction.

Skips cleanly, loudly, when Node or the corpus is absent.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_firmware_check.mjs"


@pytest.fixture(scope="session")
def node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.skip("node is not on PATH; the browser stack cannot be checked")
    return found


@pytest.fixture(scope="session")
def js_report(node, dn2_raw, tmp_path_factory):
    """Run the harness once; every test below reads the same report.

    Session-scoped because the run costs a few seconds and re-running it per
    test would say nothing new -- it is deterministic by construction, which is
    the property `test_agrees_with_python` actually asserts.
    """
    tmp = tmp_path_factory.mktemp("js_firmware")
    syx = tmp / "image.syx"
    syx.write_bytes(dn2_raw)
    out = tmp / "js_rebuild.syx"

    done = subprocess.run(
        [node, str(HARNESS), "--syx", str(syx), "--section", "7", "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"
    return json.loads(done.stdout), out


def test_every_stack_check_passes(js_report):
    report, _ = js_report
    failed = [c for c in report["checks"] if not c["ok"]]
    assert not failed, failed


def test_round_trip_is_byte_identical(js_report):
    """Gate A, in JavaScript. Named separately from the blanket check above so
    a failure says which property broke, not merely that something did."""
    report, _ = js_report
    check = next(c for c in report["checks"] if "round-trip" in c["check"])
    assert check["ok"], check


def test_key_is_derived_not_assumed(js_report):
    """A stack that quietly decided the image was unsigned would still produce
    a file, and every checksum in it would pass. The derivation string is the
    only thing that distinguishes that from success."""
    report, _ = js_report
    check = next(c for c in report["checks"] if "signing key" in c["check"])
    assert check["ok"], check
    assert "Multiplier" in check["detail"], check


def test_agrees_with_python(js_report, dn2, tmp_path):
    """The JS-built image and the Python-built image are the same bytes.

    Both are given the same store-only stream, so what is being compared is the
    container layout, the section table rewrite, the trailer placement, the
    content checksum and the whole transport -- independently implemented on
    both sides.
    """
    from dnfw.container.section import HEADER, STORED_ALIGN, Section
    from dnfw.firmware.build import build

    _, js_path = js_report
    js_bytes = js_path.read_bytes()

    original = dn2.container.find(7)
    if original is None or original.unpack() is None:
        pytest.skip("this image has no compressed section 7")

    # Take the stream straight out of the JS image rather than repacking it in
    # Python: the packers are compared in test_js_codec.py, and mixing that in
    # here would make a failure ambiguous between the codec and the container.
    from dnfw.firmware.load import load
    js_section = load(js_bytes).container.find(7)
    stream = js_section.stream
    header = (len(stream).to_bytes(4, "big")
              + (sum(stream) & 0xFFFFFFFF).to_bytes(4, "big"))
    padding = bytes(-(HEADER + len(stream)) % STORED_ALIGN)
    section = Section(id=7, dest=original.dest, stored=header + stream + padding)

    python_bytes = build(dn2, {7: section})
    assert len(js_bytes) == len(python_bytes)
    assert js_bytes == python_bytes
