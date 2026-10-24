"""tools/web/index.html (v0.22): the browser import tool's core, run under node, builds
the same image and the same SysEx as tools/dn2samples.py and dnfw.sampler.live."""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import struct
import subprocess
import sys

import pytest

from dnfw.sampler import live as SL
from dnfw.sampler import machines as SM
from dnfw.waverider import dsp

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def _core() -> str:
    html = (ROOT / "tools/web/index.html").read_text()
    return re.search(r'<script id="core">(.*?)</script>', html, re.S).group(1)


def _node(js: str):
    if not shutil.which("node"):
        pytest.skip("no node")
    out = subprocess.run(["node", "-e", _core() + "\n" + js], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_constants_are_the_builds():
    c = _node("console.log(JSON.stringify(DN2.C))")
    for k in ("POOL_MAGIC", "POOL_SLOTS", "USER_SLOTS", "NAMES_OFFSET", "NAME_BYTES", "DATA_OFFSET",
              "FMT_I16", "MAX_SLICES", "REC_OFFSET", "REC_END", "POOL_BYTES", "REC_BYTES", "HOLE_BYTES", "SLICE_AREA"):
        assert c[k] == getattr(SM, k), k
    assert c["POOL_DDR"] == dsp.SMP_POOL_DDR


def test_the_image_is_pool_bytes_byte_for_byte():
    sounds = [[0.5 * ((k * 7 % 100) / 50 - 1) for k in range(3001)],
              [1.6 * ((k % 40) / 20 - 1) for k in range(777)],          # over 1: normalised
              [0.25] * 64]
    rates = [44100, 48000, 22050]
    slices = [[], [[0, 300, 0], [300, 777, 300]], []]
    names = ["KICK", "LOOPY", "TONE"]
    js = (f"const S={json.dumps(sounds)};const R={json.dumps(rates)};const L={json.dumps(slices)};"
          f"const N={json.dumps(names)};"
          "const items=S.map((s,k)=>({frames:Float32Array.from(s),rate:R[k],name:N[k],slices:L[k]}));"
          # a hole just past the first sound, so the second jumps it
          "const p=DN2.poolBytes(items,[0x1000+6100,0x3000]);console.log(JSON.stringify(Array.from(p)))")
    got = bytes(_node(js))
    peak = [max(abs(x) for x in s) for s in sounds]
    norm = [[x / p for x in s] if p > 1 else s for s, p in zip(sounds, peak)]
    f32 = [[struct.unpack("<f", struct.pack("<f", x))[0] for x in s] for s in norm]
    want = SL.pool_bytes(f32, dsp.SMP_POOL_DDR, [r / 48000 for r in rates], [SM.FMT_I16] * 3, names,
                         [tuple(map(tuple, s)) for s in slices], hole=(0x1000 + 6100, 0x3000))
    assert got == want


def test_the_sysex_is_dn2samples():
    import dn2samples as D
    got = _node("console.log(JSON.stringify([Array.from(DN2.request(0x301,1)),"
                "Array.from(DN2.request(0x302,2,[...DN2.be32(4096),1,2,250,255])),"
                "DN2.parse(DN2.request(0x303,10,[5]))]))")
    assert bytes(got[0]) == D.request(0x301, D.HELLO)
    assert bytes(got[1]) == D.request(0x302, D.WRITE, struct.pack(">I", 4096) + bytes([1, 2, 250, 255]))
    assert got[2]["seq"] == 0x303 and got[2]["cmd"] == 10
