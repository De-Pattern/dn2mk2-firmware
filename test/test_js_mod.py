"""The browser transients mod, checked against the Python one.

`test_js_codec.py` covers the codec and `test_js_firmware.py` the container and
transport. This covers the part a user actually asks for: the bank is found,
read, written back, and one slot changes without disturbing the other 33.

The check `docs/mods.md` calls the factory round-trip is the strongest one
available offline. The Python tool writes the bank back and gets a
**byte-identical section 7**; the browser cannot match that, because store-only
packing encodes differently, so the standard here is that the *unpacked*
section comes back byte-identical — the same statement about the bank, and a
weaker one only about the compressor.

A wrong bank offset, entry size, count, endianness or sample width would each
corrupt bytes, and the boot-stream walk that turns a load address into a file
offset is exercised on the way.

One check here cannot be done inside the harness: **do both implementations
find the same 34 entries?** Locating the bank is the one thing they do from the
same measured constants, which makes it the one place a shared misreading of
those constants could hide, and no amount of self-checking on either side would
show it.

`audio.decode` is not tested. It needs Web Audio and delegates decoding,
resampling and channel layout to the browser; `audio.fit`, which is where every
judgement call lives, is pure and is tested — the split exists for that reason.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_mod_check.mjs"


@pytest.fixture(scope="session")
def node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.skip("node is not on PATH; the browser mod cannot be checked")
    return found


@pytest.fixture(scope="session")
def js_mod(node, dn2_raw, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("js_mod")
    syx = tmp / "image.syx"
    syx.write_bytes(dn2_raw)
    bank = tmp / "bank.bin"

    done = subprocess.run(
        [node, str(HARNESS), "--syx", str(syx), "--bank-out", str(bank)],
        capture_output=True, text=True, cwd=ROOT)
    report = json.loads(done.stdout) if done.stdout else {"checks": []}
    return done.returncode, report, bank


def test_every_mod_check_passes(js_mod):
    code, report, _ = js_mod
    failed = [c for c in report["checks"] if not c["ok"]]
    assert not failed, failed
    assert code == 0


def test_factory_round_trip(js_mod):
    """Named on its own so a failure says which property broke."""
    _, report, _ = js_mod
    check = next(c for c in report["checks"] if "round-trip" in c["check"])
    assert check["ok"], check


def test_one_slot_changes_and_only_one(js_mod):
    """A round-trip alone cannot catch a mod that writes nothing at all.

    Both halves matter: that the slot asked for changed, and that the other 33
    did not. A mod passing only the first could be overwriting the whole bank.
    """
    _, report, _ = js_mod
    changed = next(c for c in report["checks"] if "changes slot 17" in c["check"])
    others = next(c for c in report["checks"] if "other 33" in c["check"])
    assert changed["ok"] and others["ok"], (changed, others)


def test_both_implementations_find_the_same_bank(js_mod, dn2):
    """The cross-check neither side can make alone.

    Python and JS each locate the bank by walking the boot stream for the block
    covering `0x8045c380`, from constants measured once and copied into both.
    If those constants were misread, both would be wrong in the same way and
    every self-check on both sides would still pass. This is the only test that
    would notice — and it compares the *content*, not the offset, so it also
    covers the walk, the entry size and the count.
    """
    from dnfw.mods import transients

    _, _, bank = js_mod
    if not bank.exists():
        pytest.skip("the harness did not write a bank; an earlier check failed")

    js_bank = bank.read_bytes()
    python_bank = b"".join(transients.extract(dn2))

    assert len(js_bank) == len(python_bank) == transients.COUNT * transients.ENTRY_BYTES
    assert js_bank == python_bank


def test_the_count_is_an_integer(js_mod):
    """34, not 34.04.

    The region is 326,784 bytes and an entry is 9,600, so the division does not
    come out whole. Python's `//` floors it; JS's `/` does not, and a fractional
    COUNT reads as 34 wherever it is used as a length but as **35** in a
    `slot >= COUNT` bounds check — letting a write land past the end of the
    bank, in the float32 table that bounds it.

    This is asserted rather than trusted because the port looked correct and
    was not.
    """
    _, report, _ = js_mod
    check = next(c for c in report["checks"] if c["check"].startswith("bank is"))
    assert check["ok"], check
    assert "34 entries" in check["check"], check
