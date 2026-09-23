"""The browser FX modulation mod against the Python one, in the test suite.

`js_fxmod_check.mjs` exists so the parity check can be run by hand; this runs it
every time, because a parity check nobody runs is a claim, not a check. The two
halves are generated from the same `fxmod_code.json`, so what could still differ
— and what this catches — is a difference in how they *apply* it: an off-by-one
in a slice, a hex parse that drops a leading zero, a guard skipped on one side.

The harness also asserts the group-name longword reads `CHR` afterwards and
that Reverb's and Delay's are untouched, which is the one edit byte equality
alone does not carry the meaning of.
"""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_fxmod_check.mjs"
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the browser mod cannot be checked")
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")

    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    from dnfw.mods import fxmod

    tmp = tmp_path_factory.mktemp("js_fxmod")
    syx = tmp / "image.syx"
    syx.write_bytes(read_image(STOCK_111))
    content = tmp / "py_content.bin"
    content.write_bytes(fxmod.apply(load(read_image(STOCK_111))).payloads[fxmod.SECTION])

    done = subprocess.run(
        [node, str(HARNESS), "--syx", str(syx), "--py-content", str(content)],
        capture_output=True, text=True, cwd=ROOT)
    rows = [line.split("  ", 1) for line in done.stdout.splitlines()
            if line.startswith(("OK  ", "FAIL  "))]
    return done.returncode, done.stderr, [(r[1], r[0] == "OK") for r in rows]


def test_the_harness_ran_at_all(report):
    """A harness that crashed prints nothing, and zero failures out of zero
    checks reads exactly like a pass."""
    _, stderr, rows = report
    assert rows, f"the harness produced no checks; stderr:\n{stderr}"


def test_every_check_passes(report):
    code, stderr, rows = report
    failed = [name for name, ok in rows if not ok]
    assert not failed, f"{failed}\nstderr:\n{stderr}"
    assert code == 0


def test_the_browser_produces_the_python_bytes(report):
    """Named on its own so a failure says which property broke."""
    _, _, rows = report
    name, ok = next((r for r in rows if r[0].startswith("MAIN OS ==")), (None, False))
    assert ok, name
