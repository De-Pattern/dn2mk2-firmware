"""The browser arp modes mod against the CLI, in the test suite.

`js_arpmodes_check.mjs` can be run by hand; this runs it every time. The two
halves are generated from the same `arpmodes_code.json`, so what could still
differ -- and what this catches -- is how they apply it: a slice off by one, a
hex parse that drops a leading zero, a guard skipped on one side, a refusal
worded differently.

Properties:

- stock -> arpmodes in the browser is the CLI's `--mod arpmodes`, MAIN OS and
  the whole `.syx`;
- midiarp -> download -> arpmodes, and lfo4 -> download -> arpmodes, in the
  browser are the CLI's pairs, which is how a user chains two pages;
- the refusals (applied twice, a shorter image, an edited guard) are worded
  the same on both sides.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_arpmodes_check.mjs"
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
    from dnfw.mods import arpmodes

    tmp = tmp_path_factory.mktemp("js_arpmodes")
    syx = tmp / "image.syx"
    syx.write_bytes(read_image(STOCK_111))
    outputs = {}
    for name, mods in [("arpmodes", ["arpmodes"]), ("midiarp-arpmodes", ["midiarp", "arpmodes"]),
                       ("lfo4-arpmodes", ["lfo4", "arpmodes"])]:
        out = tmp / f"{name}.syx"
        args = ["mods", "apply", str(syx), "-o", str(out)]
        for m in mods:
            args += ["--mod", m]
        assert dnfw(args) == 0
        outputs[name] = out

    refusals = tmp / "refusals.json"
    done = subprocess.run(
        [node, str(HARNESS), "--syx", str(syx),
         *[a for name, out in outputs.items() for a in (f"--cli-{name}", str(out))],
         "--refusals-out", str(refusals)],
        capture_output=True, text=True, cwd=ROOT)
    rows = [line.split("  ", 1) for line in done.stdout.splitlines()
            if line.startswith(("OK  ", "FAIL  "))]
    js = json.loads(refusals.read_text()) if refusals.exists() else {}
    firmware = load(syx.read_bytes())
    return {"code": done.returncode, "stderr": done.stderr,
            "rows": [(r[1], r[0] == "OK") for r in rows], "js": js,
            "stock": firmware.container.find(arpmodes.SECTION).unpack(),
            "applied": load(outputs["arpmodes"].read_bytes())}


def test_the_harness_ran_at_all(run):
    """A harness that crashed prints nothing, and zero failures out of zero
    checks reads exactly like a pass."""
    assert run["rows"], f"the harness produced no checks; stderr:\n{run['stderr']}"


def test_every_check_passes(run):
    failed = [name for name, ok in run["rows"] if not ok]
    assert not failed, f"{failed}\nstderr:\n{run['stderr']}"
    assert run["code"] == 0


@pytest.mark.parametrize("prefix", [
    "arpmodes on stock: MAIN OS == CLI", "arpmodes on stock: .syx == CLI",
    "midiarp then arpmodes: MAIN OS == CLI", "midiarp then arpmodes: .syx == CLI",
    "lfo4 then arpmodes: MAIN OS == CLI", "lfo4 then arpmodes: .syx == CLI",
])
def test_the_browser_produces_the_cli_bytes(run, prefix):
    """Named on their own so a failure says which property broke."""
    name, ok = next((r for r in run["rows"] if r[0].startswith(prefix)), (prefix, False))
    assert ok, name


def test_the_refusals_are_worded_the_same(run):
    from dnfw.mods import arpmodes

    stock = run["stock"]
    guarded = bytearray(stock)
    guarded[arpmodes.SPEC["guards"][0]["va"] - arpmodes.BASE] ^= 0xFF
    python = {
        "arpmodes_twice": _refusal(lambda: arpmodes.apply(run["applied"])),
        "arpmodes_on_shorter": _refusal(lambda: arpmodes.apply(_Staged(stock[:-16]))),
        "arpmodes_on_edited_guard": _refusal(lambda: arpmodes.apply(_Staged(bytes(guarded)))),
    }
    assert all(python.values()), python
    assert run["js"] == python
