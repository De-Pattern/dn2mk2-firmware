"""tools/patcher/dn2patch.py, the in-browser patcher's Python (dn2mk2's patcher.html).

What it adds to the build is reading the owner's files as Elektron ship them: the
Machinedrum's .syx rebuilt into its flash image, the DT2's section 7 taken from its .syx,
and either inside a .zip."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import pathlib
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MD = ROOT.parent / "md163"


def _mod():
    spec = importlib.util.spec_from_file_location("dn2patch", ROOT / "tools" / "patcher" / "dn2patch.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_md_image_from_the_syx_carries_the_flash_image_chain():
    syx, bin_ = MD / "md_uw_os1.63.syx", MD / "md_uw_os1.63.bin"
    if not (syx.is_file() and bin_.is_file()):
        pytest.skip("the Machinedrum's OS files are not beside the repository")
    img, ref = _mod().md_image(syx.read_bytes()), bin_.read_bytes()
    assert len(img) == len(ref) == 8 << 20
    # every byte the syx carries is the flash image's, and it carries the chain whole
    carried = [i for i in range(0x4000, len(img), 64) if img[i:i + 64] != b"\xff" * 64]
    assert all(img[i:i + 64] == ref[i:i + 64] for i in carried)
    end = 0x4000
    import struct
    for _ in range(3):
        clen, _ck = struct.unpack_from(">II", ref, end)
        end += 8 + clen
    assert img[0x4000:end] == ref[0x4000:end]
    assert img[0xC5458:0xC545B] == b"163"


def test_unzip_takes_the_one_file_or_refuses():
    m = _mod()
    raw = b"\xf0 not a zip \xf7"
    assert m.unzip(raw, (".syx",)) == raw
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "x")
        z.writestr("os.syx", raw)
    assert m.unzip(buf.getvalue(), (".syx",)) == raw
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as z:
        z.writestr("a.syx", raw)
        z.writestr("b.syx", raw)
    with pytest.raises(m.PatchError):
        m.unzip(buf2.getvalue(), (".syx",))


def test_md_image_refuses_other_files():
    m = _mod()
    with pytest.raises(m.PatchError):
        m.md_image(b"\xf0\x00\x20\x3c\x02\x00\x7e\xf7" * 10)


def test_dt2_section7_checks_its_sha():
    m = _mod()
    assert m.DT2_SEC7_SHA == __import__("dnfw.dt2.rom", fromlist=["SHA256"]).SHA256


def test_the_page_saves_only_the_cleared_sha():
    page = (ROOT / "tools" / "web" / "patcher.html").read_text()
    assert "got === b.sha256" in page and "$(\"#save\").disabled = false" in page
    worker = (ROOT / "tools" / "web" / "patcher-worker.js").read_text()
    assert "zipSha" in worker and "pyodide/v0.27.7" in worker
