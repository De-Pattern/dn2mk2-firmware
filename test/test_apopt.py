"""v0.65: the optimal-parse packer (codec.aplibopt, docs/packer.md).

What has to hold for it to replace aplibpack.pack in the build:
- every stream depacks to its input (our depacker here; the gate's `depack` step runs the
  instrument's own on the build's sections);
- no match reaches past the window or copies more than 2,048 bytes (codec.limits);
- never larger than aplibpack.pack's stream for the same input;
- the native library and apopt.wasm (the in-browser patcher's) give the very same tokens, so
  the browser builds the cleared file byte for byte;
- apopt.wasm is the build of the committed apopt.c;
- a parse that does not fit its input is refused, not written.
"""

import array
import pathlib
import random
import shutil
import subprocess
import sys

import pytest

from dnfw.codec import aplibopt, aplibpack, limits
from dnfw.codec.aplib import depack
from dnfw.codec.profile import profile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _random(size: int, seed: int) -> bytes:
    r = random.Random(seed)
    return bytes(r.randrange(256) for _ in range(size))


def _far(seed: int) -> bytes:
    """a block, 200 KB of noise, the block again (a far match), and short repeats near and far"""
    r = random.Random(seed)
    block = bytes(r.randrange(256) for _ in range(5000))
    out = bytearray(block) + _random(200_000, seed + 1) + block
    for _ in range(3000):
        k = r.randrange(len(out) - 40)
        out += out[k:k + r.randrange(2, 40)] + bytes([r.randrange(256)])
    return bytes(out)


CASES = {
    "one": b"A",
    "two": b"AB",
    "zeros": bytes(5000),
    "long_run": b"\xa5" * 70000,
    "repeating": b"the quick brown fox " * 300,
    "alternating": b"\x00\xff" * 20000,
    "noise": _random(20000, 1),
    "far": _far(7),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_round_trip_within_limits_and_never_larger(name):
    data = CASES[name]
    s = aplibopt.pack(data, how="native")
    assert depack(s) == data
    p = profile(s)
    assert p.within_limits and p.max_offset <= limits.PACK_MAX_OFFSET and p.max_length <= limits.MAX_MATCH
    assert len(s) <= len(aplibpack.pack(data))


def test_the_far_case_does_reach_past_the_far_threshold():
    """the length bonus and the 3-byte minimum past offset 3,328 are exercised, not just allowed"""
    t = aplibopt.tokens(CASES["far"], how="native")
    assert any(t[k] > 3328 for k in range(0, len(t), 2))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name", sorted(CASES))
def test_native_and_wasm_give_the_same_tokens(name):
    data = CASES[name]
    assert aplibopt.tokens(data, how="native") == aplibopt.tokens(data, how="node")


def test_apopt_wasm_is_built_from_apopt_c():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_apopt_wasm.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_parse_that_does_not_fit_is_refused(monkeypatch):
    data = b"abcabcabc"
    good = aplibopt.tokens(data, how="native")
    assert aplibopt.pack(data, how="native")
    bad = array.array("I", [0, 1, 5, 2, 0, 1])          # a match reaching before the start
    monkeypatch.setattr(aplibopt, "tokens", lambda *a, **k: bad)
    with pytest.raises(aplibopt.PackError):
        aplibopt.pack(data)
    short = array.array("I", list(good)[:-2])           # a parse that stops early
    monkeypatch.setattr(aplibopt, "tokens", lambda *a, **k: short)
    with pytest.raises(aplibopt.PackError):
        aplibopt.pack(data)


def test_the_build_depacks_what_it_packs(monkeypatch):
    """container.section.compress refuses a stream that does not depack to its content"""
    from dnfw.container import section
    monkeypatch.setattr(section.aplibopt, "pack", lambda c: aplibpack.pack(c[:-1]))
    with pytest.raises(ValueError):
        section.compress(3, 0x40000400, b"0123456789" * 100)


def test_stock_sections_pack_smaller_than_elektrons(dn2):
    for s in dn2.sections if hasattr(dn2, "sections") else dn2.container.sections:
        content = s.unpack()
        if not content:
            continue
        ours = aplibopt.pack(content, how="native")
        assert depack(ours) == content
        assert len(ours) + 8 <= len(s.stored), f"section {s.id}"
