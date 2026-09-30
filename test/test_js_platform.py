"""The browser platform against the Python one, in the test suite.

`js_platform_check.mjs` chains lfowaves, bootscreen and lfo4 the way the site
does (each page's download loaded into the next) and compares every MAIN OS
with the Python's; the refusals must be worded the same on both sides.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_platform_check.mjs"
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


def _refusal(fn):
    from dnfw.mods import ModError
    try:
        fn()
    except ModError as exc:
        return str(exc)
    return None


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the browser mods cannot be checked")
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")

    from dnfw.cli.files import read_image
    from dnfw.cli.mods import _staged
    from dnfw.firmware.load import load
    from dnfw.mods import bootscreen, lfo4, lfowaves

    tmp = tmp_path_factory.mktemp("js_platform")
    syx = tmp / "image.syx"
    syx.write_bytes(read_image(STOCK_111))
    firmware = load(syx.read_bytes())
    mark = [bootscreen.image_from_pixels({(x, x >> 1) for x in range(128)})]
    run = {"lfowaves": lfowaves.apply, "bootscreen": lambda f: bootscreen.apply(f, mark),
           "lfo4": lfo4.apply}

    def chain(order):
        payloads = {}
        for mid in order:
            payloads.update(run[mid](_staged(firmware, payloads)).payloads)
        return payloads[3]

    cases = {"lfowaves.bin": ["lfowaves"], "bootscreen.bin": ["bootscreen"],
             "waves_boot.bin": ["lfowaves", "bootscreen"],
             "trio.bin": ["lfowaves", "bootscreen", "lfo4"]}
    for name, order in cases.items():
        (tmp / name).write_bytes(chain(order))

    with_lfo4 = _staged(firmware, {3: chain(["lfo4"])})
    with_boot = _staged(firmware, {3: chain(["bootscreen"])})
    python = {"lfowaves_after_lfo4": _refusal(lambda: lfowaves.apply(with_lfo4)),
              "bootscreen_twice": _refusal(lambda: bootscreen.apply(with_boot, mark))}

    refusals = tmp / "refusals.json"
    done = subprocess.run([node, str(HARNESS), "--syx", str(syx), "--py-dir", str(tmp),
                           "--refusals-out", str(refusals)],
                          capture_output=True, text=True, cwd=ROOT)
    rows = [line.split("  ", 1) for line in done.stdout.splitlines()
            if line.startswith(("OK  ", "FAIL  "))]
    return {"code": done.returncode, "stderr": done.stderr, "python": python,
            "rows": [(r[1], r[0] == "OK") for r in rows],
            "js": json.loads(refusals.read_text()) if refusals.exists() else {}}


def test_the_harness_ran_at_all(run):
    assert run["rows"], run["stderr"]


def test_every_check_passes(run):
    failed = [name for name, ok in run["rows"] if not ok]
    assert not failed, f"{failed}\nstderr:\n{run['stderr']}"
    assert run["code"] == 0


def test_the_refusals_are_worded_the_same(run):
    assert all(run["python"].values()), run["python"]
    assert run["js"] == run["python"]
