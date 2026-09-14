"""The browser codec, checked against the Python one over real firmware.

`site/js/aplib.js` exists so the page can rebuild firmware with nothing
uploaded anywhere. It is a **second implementation of a format whose output
people flash**, which is the kind of code that earns no benefit of the doubt:
a depacker that is subtly wrong produces a plausible image, and the place that
finds out is the instrument.

So it is held to the three checks `docs/mods.md` wrote down before any of it
existed, and every one runs against bytes Elektron actually shipped:

1. **depack agreement** -- the JS depacker reproduces, byte for byte, what the
   Python depacker gets from every compressed section of a real image.
2. **pack self-check** -- JS `packStore` output survives the JS depacker.
3. **cross-check** -- JS `packStore` output survives the *Python* depacker.
   This is the one that matters: two implementations sharing no lineage.

Checks 1 and 2 happen inside `scripts/js_codec_check.mjs`, because they are
JS-side. Check 3 can only happen here, and check 4 below could not be done in
either language alone.

4. **the factory round-trip** -- rebuild a whole image with a store-only
   section 7 and verify it. Not a codec check: it asks whether the *container*
   still adds up when a section changes length, which is the question the
   browser tool's whole plan rests on.

Skips cleanly, loudly, when Node or the corpus is absent. A skipped test says
so; it does not quietly pass.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_codec_check.mjs"


@pytest.fixture(scope="session")
def node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.skip("node is not on PATH; the browser codec cannot be checked")
    return found


def _compressed(firmware):
    """Every section of this image that is actually an aPLib stream.

    Discovered rather than listed: which sections are compressed is a property
    of the image (`container.section`), and hard-coding ids here would quietly
    stop testing a section that a future OS stores differently.
    """
    return [s for s in firmware.container.sections if s.unpack() is not None]


def test_js_depack_matches_python(node, dn2, tmp_path):
    """Checks 1 and 2, over every compressed section of a real image."""
    sections = _compressed(dn2)
    assert sections, "the image has no compressed sections; the fixture is wrong"

    for section in sections:
        stored = tmp_path / f"s{section.id}.stored.bin"
        expect = tmp_path / f"s{section.id}.unpacked.bin"
        stored.write_bytes(section.stored)
        expect.write_bytes(section.unpack())

        done = subprocess.run(
            [node, str(HARNESS), "--stored", str(stored), "--expect", str(expect)],
            capture_output=True, text=True, cwd=ROOT)
        assert done.returncode == 0, (
            f"section {section.id}: {done.stdout}\n{done.stderr}")

        report = json.loads(done.stdout)
        assert all(c["ok"] for c in report["checks"]), report
        assert report["unpacked_bytes"] == len(section.unpack())
        # Store-only costs one control bit per byte and nothing else. Asserting
        # the ratio catches a packer that silently started emitting matches --
        # which would be a *better* packer and an untested one.
        assert report["growth_ratio"] == pytest.approx(1.125, abs=0.001)


def test_python_depacks_the_js_packer(node, dn2, tmp_path):
    """Check 3: the cross-implementation one.

    Both directions have now been closed -- Python's stream reads correctly in
    JS, and JS's stream reads correctly in Python -- and neither implementation
    was consulted while the other ran.
    """
    from dnfw.codec import aplib

    section = max(_compressed(dn2), key=lambda s: len(s.unpack()))
    content = section.unpack()
    stored = tmp_path / "stored.bin"
    expect = tmp_path / "unpacked.bin"
    packed = tmp_path / "js_packed.bin"
    stored.write_bytes(section.stored)
    expect.write_bytes(content)

    done = subprocess.run(
        [node, str(HARNESS), "--stored", str(stored), "--expect", str(expect),
         "--packed-out", str(packed)],
        capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"

    assert aplib.depack(packed.read_bytes()) == content


def test_store_only_section_rebuilds_and_verifies(node, dn2, dn2_raw, tmp_path):
    """Check 4: a whole image whose section 7 was packed by the browser codec.

    Section 7 is the one the transients mod edits, and the only one the browser
    tool will ever repack -- 2, 3 and 8 keep their original stored bytes. So
    this is the exact shape of image the tool will produce.

    Two things are asserted that a checksum cannot tell apart:

    - the section **depacks back to the same content**, so the store-only
      stream is not merely well-formed but carries the right bytes;
    - every integrity field still verifies, which is not free, because the
      section changed length and the trailer and content checksum are taken
      over the result.
    """
    from dnfw.container.section import HEADER, STORED_ALIGN, Section
    from dnfw.firmware.build import build
    from dnfw.firmware.load import load
    from dnfw.firmware.verify import verify

    original = dn2.container.find(7)
    if original is None or original.unpack() is None:
        pytest.skip("this image has no compressed section 7")
    content = original.unpack()

    stored = tmp_path / "stored.bin"
    expect = tmp_path / "unpacked.bin"
    packed = tmp_path / "js_packed.bin"
    stored.write_bytes(original.stored)
    expect.write_bytes(content)
    done = subprocess.run(
        [node, str(HARNESS), "--stored", str(stored), "--expect", str(expect),
         "--packed-out", str(packed)],
        capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"

    stream = packed.read_bytes()
    header = (len(stream).to_bytes(4, "big")
              + (sum(stream) & 0xFFFFFFFF).to_bytes(4, "big"))
    padding = bytes(-(HEADER + len(stream)) % STORED_ALIGN)
    section = Section(id=7, dest=original.dest, stored=header + stream + padding)

    rebuilt = load(build(dn2, {7: section}))
    assert rebuilt.container.find(7).unpack() == content
    report = verify(rebuilt)
    assert report.ok, [c for c in report.checks if not c.ok]


def test_store_only_is_inside_elektrons_limits(node, dn2, tmp_path):
    """A store-only stream contains no matches at all, so it cannot violate
    either bound in `codec.limits` -- there is nothing to violate them with.

    Worth asserting rather than reasoning about: those limits are why images of
    ours once stalled in recovery, and "it has no matches" is a claim about the
    packer that a future packer could quietly stop honouring.
    """
    from dnfw.codec.profile import profile

    section = max(_compressed(dn2), key=lambda s: len(s.unpack()))
    content = section.unpack()
    stored = tmp_path / "stored.bin"
    expect = tmp_path / "unpacked.bin"
    packed = tmp_path / "js_packed.bin"
    stored.write_bytes(section.stored)
    expect.write_bytes(content)
    subprocess.run(
        [node, str(HARNESS), "--stored", str(stored), "--expect", str(expect),
         "--packed-out", str(packed)],
        capture_output=True, text=True, cwd=ROOT, check=True)

    p = profile(packed.read_bytes())
    assert p.matches == 0, "the browser packer emitted a match; it is store-only"
    assert p.literals == len(content)
