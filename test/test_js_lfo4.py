"""The browser LFO4 mod against the Python one, in the test suite.

`js_lfo4_check.mjs` can be run by hand; this runs it every time. The two halves
are generated from the same `lfo4_code.json`, but the relocated parameter table
is **not** in that data: both rebuild it from the image, so the table port
(`paramtable.records`, `lfo4records.build`, `free_unique_ids`, the five field
rewrites) is what byte equality checks here, alongside the edits and the blob.

Three properties:

- stock -> lfo4 in the browser is `lfo4.compose` on stock;
- fxmod -> download -> lfo4 in the browser is the CLI's `--mod fxmod --mod lfo4`,
  which is the order-only pair the browser has to get right by chaining;
- moddest -> lfo4 in the browser is the Python's, so its opened masks are carried;
- the refusals are worded the same on both sides, including fxmod's refusal of
  an lfo4 image (applied after it, fxmod would open records in a table nothing
  reads any more).
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_lfo4_check.mjs"
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


class _Section:
    def __init__(self, content):
        self._content = content

    def unpack(self):
        return self._content


class _Container:
    def __init__(self, content):
        self._section = _Section(content)

    def find(self, _section_id):
        return self._section


class _Staged:
    """Just enough of a firmware for a mod that reads section 3."""

    def __init__(self, content):
        self.container = _Container(content)


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
        pytest.skip("node is not on PATH; the browser mod cannot be checked")
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")

    from dnfw.cli.files import read_image
    from dnfw.cli.main import main as dnfw
    from dnfw.firmware.load import load
    from dnfw.mods import lfo4, moddest

    tmp = tmp_path_factory.mktemp("js_lfo4")
    syx = tmp / "image.syx"
    syx.write_bytes(read_image(STOCK_111))
    stock = load(syx.read_bytes()).container.find(lfo4.SECTION).unpack()
    (tmp / "lfo4.bin").write_bytes(lfo4.compose(stock))
    opened = moddest.apply(load(syx.read_bytes())).payloads[lfo4.SECTION]
    (tmp / "moddest_lfo4.bin").write_bytes(lfo4.compose(opened))

    pair = tmp / "fx_lfo4.syx"
    assert dnfw(["mods", "apply", str(syx), "--mod", "fxmod", "--mod", "lfo4", "-o", str(pair)]) == 0
    (tmp / "fx_lfo4.bin").write_bytes(load(pair.read_bytes()).container.find(lfo4.SECTION).unpack())

    refusals = tmp / "refusals.json"
    done = subprocess.run(
        [node, str(HARNESS), "--syx", str(syx), "--py-lfo4", str(tmp / "lfo4.bin"),
         "--py-fx-lfo4", str(tmp / "fx_lfo4.bin"),
         "--py-moddest-lfo4", str(tmp / "moddest_lfo4.bin"), "--refusals-out", str(refusals)],
        capture_output=True, text=True, cwd=ROOT)
    rows = [line.split("  ", 1) for line in done.stdout.splitlines()
            if line.startswith(("OK  ", "FAIL  "))]
    js = json.loads(refusals.read_text()) if refusals.exists() else {}
    return {"code": done.returncode, "stderr": done.stderr,
            "rows": [(r[1], r[0] == "OK") for r in rows], "js": js,
            "firmware": load(syx.read_bytes()), "stock": stock}


def test_the_harness_ran_at_all(run):
    """A harness that crashed prints nothing, and zero failures out of zero
    checks reads exactly like a pass."""
    assert run["rows"], f"the harness produced no checks; stderr:\n{run['stderr']}"


def test_every_check_passes(run):
    failed = [name for name, ok in run["rows"] if not ok]
    assert not failed, f"{failed}\nstderr:\n{run['stderr']}"
    assert run["code"] == 0


@pytest.mark.parametrize("prefix", ["lfo4 on stock: MAIN OS ==", "fxmod then lfo4: MAIN OS ==",
                                    "moddest then lfo4: MAIN OS =="])
def test_the_browser_produces_the_python_bytes(run, prefix):
    """Named on their own so a failure says which property broke."""
    name, ok = next((r for r in run["rows"] if r[0].startswith(prefix)), (prefix, False))
    assert ok, name


def test_the_refusals_are_worded_the_same(run):
    from dnfw.mods import fxmod, lfo4, lfowaves, moddest

    stock = run["stock"]
    edited = bytearray(stock)
    edited[lfo4.SPEC["edits"][0]["va"] - lfo4.BASE] ^= 0xFF
    after = _Staged(lfo4.compose(stock))
    python = {
        "lfo4_after_lfowaves": _refusal(lambda: lfo4.compose(
            lfowaves.apply(run["firmware"]).payloads[lfo4.SECTION])),
        "lfo4_on_longer": _refusal(lambda: lfo4.compose(stock + bytes(16))),
        "lfo4_on_edited": _refusal(lambda: lfo4.compose(bytes(edited))),
        "fxmod_after_lfo4": _refusal(lambda: fxmod.apply(after)),
        "moddest_after_lfo4": _refusal(lambda: moddest.apply(after)),
    }
    assert all(python.values()), python
    assert run["js"] == python


def test_fxmod_refuses_after_lfo4_and_says_the_order(run):
    """Applied after lfo4, fxmod's ten record masks would land on the stock
    table, which nothing reads once lfo4 has moved it. It refuses instead."""
    from dnfw.mods import fxmod, lfo4

    why = _refusal(lambda: fxmod.apply(_Staged(lfo4.compose(run["stock"]))))
    assert why and "apply fxmod first, then lfo4" in why
