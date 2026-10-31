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
              "FMT_I16", "MAX_SLICES", "REC_OFFSET", "REC_END", "POOL_BYTES", "REC_BYTES", "HOLE_BYTES", "SLICE_AREA", "TABLE_AREA",
              "META_PTR", "META_PTR_MAGIC", "META_MAGIC", "META_FOLDERS", "META_FOLDER_BYTES", "META_SLOT_BYTES",
              "META_NAME_BYTES", "META_BYTES"):
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


def _drive_writes(image: bytearray, writes, block=0x10000):
    """link.c's WRITE into the +Drive's image: each 64 KB block is staged from zeros when a
    write first reaches it, and only up to the last byte written (on 512) goes to the drive."""
    blk, stage, fill = None, None, 0

    def flush():
        if blk is None or not fill:
            return
        n = (fill + 511) & ~511
        if len(image) < blk + n:
            image.extend(bytes(blk + n - len(image)))
        image[blk:blk + n] = stage[:n]
    for at, data in writes:
        for j, byte in enumerate(data):
            a = at + j
            b = a & ~(block - 1)
            if b != blk:
                flush()
                blk, stage, fill = b, bytearray(block), 0
            stage[a - b] = byte
            fill = max(fill, a - b + 1)
    flush()


def test_add_keeps_what_is_on_the_instrument_byte_for_byte():
    """v0.24 tool, Add: the instrument's image after a Replace (slots 1, 2 and 4, one with
    slices), then an Add into slots 3 and 7 and over slot 2, through the link's own block
    rule: the kept samples' entries and bytes are untouched, the new ones are where their
    entries say, and the directory is the whole of it."""
    js = r"""
      const mk = (n, f, rate, name, sl) => ({frames: Float32Array.from({length: n}, (_, i) => f(i)), rate, name, slices: sl});
      const A = mk(70000, i => Math.sin(i / 7) * 0.5, 44100, "A", []);
      const B = mk(3000, i => (i % 50) / 50 - 0.5, 48000, "B", [[0, 1500, 0], [1500, 3000, 1500]]);
      const D = mk(40001, i => 0.25, 22050, "D", []);
      const first = DN2.poolBytes([A, B, null, D]);
      const dirOf = p => Array.from(p.subarray(0, DN2.C.DATA_OFFSET));
      const kept = [0, 1, 3].map(k => ({k, entry: first.subarray(8 + 16 * k, 24 + 16 * k), name: ["A", "B", "", "D"][k]}));
      const E = mk(5000, i => -0.3, 48000, "E", []), F = mk(123, i => 0.9, 48000, "F", [[0, 60, 0]]), G = mk(777, i => 0.1, 32000, "G", []);
      const pl = DN2.addPlan(kept, first.length, [{k: 2, ...E}, {k: 6, ...F}, {k: 1, ...G}]);
      const items = {E: Array.from(DN2.itemData(E)), F: Array.from(DN2.itemData(F)), G: Array.from(DN2.itemData(G))};
      console.log(JSON.stringify({first: Array.from(first), dir: dirOf(pl.dir), at: pl.at, data: Array.from(pl.data), end: pl.end, items}));
    """
    r = _node(js)
    first = bytearray(r["first"])
    image = bytearray(first)
    _drive_writes(image, [(0, bytes(r["dir"])), (r["at"], bytes(r["data"]))])
    assert r["at"] % 0x10000 == 0 and r["at"] >= len(first) and r["end"] == r["at"] + len(r["data"])
    base, D0 = dsp.SMP_POOL_DDR, SM.DATA_OFFSET

    def entry(img, k):
        return struct.unpack_from("<IIfI", img, 8 + 16 * k)
    assert struct.unpack_from("<II", image, 0) == (SM.POOL_MAGIC, 7)
    # A (slot 1) and D (slot 4): entries and every byte of their data as the first send left them
    for k in (0, 3):
        e = entry(image, k)
        assert e == entry(first, k)
        n = (e[1] * 2 + 0x3F) & ~0x3F
        assert image[e[0] - base:e[0] - base + n] == first[e[0] - base:e[0] - base + n]
    # E, F, G where their entries point; slot 2 is G now (B's bytes stay, unused)
    for k, name in ((2, "E"), (6, "F"), (1, "G")):
        e = entry(image, k)
        data = bytes(r["items"][name])
        assert e[0] - base >= r["at"] and image[e[0] - base:e[0] - base + len(data)] == data
        assert image[SM.NAMES_OFFSET + SM.NAME_BYTES * k:SM.NAMES_OFFSET + SM.NAME_BYTES * k + 1] == name.encode()
    assert entry(image, 6)[3] == SM.FMT_I16 | (1 << 8)
    for k in (4, 5):
        assert entry(image, k) == (0, 0, 0.0, 0)
    assert image[SM.NAMES_OFFSET:SM.NAMES_OFFSET + 1] == b"A" and D0 == 0x1000


def test_pick_leaves_the_slots_between_empty():
    r = _node("const s={frames:Float32Array.from([0.5,-0.5]),rate:48000,name:'X',slices:[]};"
              "const p=DN2.poolBytes([null,null,s]);console.log(JSON.stringify(Array.from(p.subarray(0,64))))")
    got = bytes(r)
    assert struct.unpack_from("<II", got, 0) == (SM.POOL_MAGIC, 3)
    assert got[8:40] == bytes(32)
    assert struct.unpack_from("<II", got, 40) == (dsp.SMP_POOL_DDR + SM.DATA_OFFSET, 2)


def test_the_long_names_and_folders_block():
    """v0.25: the meta block (long names, folders) after the image, the directory pointing
    at it, as link.c's meta_read takes it: 512-aligned, past the image, folders in order."""
    js = r"""
      const s = n => ({frames: Float32Array.from({length: n}, () => 0.1), rate: 48000, name: "X", slices: []});
      const pool = DN2.poolBytes([s(1000), null, s(333)]);
      const meta = DN2.metaBytes([{long: "shs_haunt_tape_56_drum_lo", folder: "drum_loops"}, null,
                                  {long: "Break (v2)", folder: "breaks"}]);
      const img = DN2.attachMeta(pool, meta);
      console.log(JSON.stringify({pool: pool.length, img: Array.from(img), meta: meta.length,
                                  short: [DN2.short("shs_haunt_tape_56_drum_lo"), DN2.short("Break (v2)")]}))"""
    r = _node(js)
    img = bytes(r["img"])
    magic, at, n = struct.unpack_from("<III", img, SM.META_PTR)
    assert magic == SM.META_PTR_MAGIC and at % 512 == 0 and at >= r["pool"] and n == r["meta"] >= SM.META_BYTES
    m = img[at:at + n]
    assert struct.unpack_from("<III", m, 0) == (SM.META_MAGIC, 1, 2)
    fo = 12
    assert m[fo:fo + 10] == b"drum_loops" and m[fo + 32:fo + 38] == b"breaks"
    rec = 12 + SM.META_FOLDERS * SM.META_FOLDER_BYTES
    assert m[rec] == 0 and m[rec + 4:rec + 29] == b"shs_haunt_tape_56_drum_lo"
    assert m[rec + SM.META_SLOT_BYTES] == 0xFF
    assert m[rec + 2 * SM.META_SLOT_BYTES] == 1 and m[rec + 2 * SM.META_SLOT_BYTES + 4:rec + 2 * SM.META_SLOT_BYTES + 14] == b"Break (v2)"
    assert all(m[rec + SM.META_SLOT_BYTES * k] == 0xFF for k in range(3, 128))
    assert r["short"] == ["SHS_HAU", "BREAK V"]          # link.c makes the same of the long names


def test_the_library_send_is_what_lib_c_reads():
    # v0.31 (link 5): BEGIN <u32 frames, u8 fmt, u8 folder, f32 rate, name>, little-endian;
    # the int16 data and adler (seed 1) as dn2samples.lib_send's; a LIST reply parsed
    import dn2samples as D
    r = _node("""
      const fr = new Float32Array(100).map((_, i) => Math.sin(i / 5) * 0.5);
      const data = DN2.libSample({ frames: fr });
      const lst = new Uint8Array(4 + 4 * 31); lst[0] = 1;
      lst[4] = 7; lst[6] = 100; lst[10] = 2; lst.set([75, 73, 67, 75], 11);
      console.log(JSON.stringify({ begin: DN2.libBegin(100, 3, 44100, "kick 1"), data: [...data],
                                   adler: DN2.adler(data), list: DN2.libList(lst) }));
    """)
    b = bytes(r["begin"])
    frames, fmt, folder, rate = struct.unpack_from("<IBBf", b)
    assert (frames, fmt, folder) == (100, SM.FMT_I16, 3) and abs(rate - 44100 / 48000) < 1e-6
    assert b[10:] == b"KICK 1"
    import math
    want = struct.pack("<100h", *(max(-32768, min(32767, round(math.sin(i / 5) * 0.5 * 32768))) for i in range(100)))
    assert len(r["data"]) == 200
    assert max(abs(x - y) for x, y in zip(struct.unpack("<100h", bytes(r["data"])), struct.unpack("<100h", want))) <= 1
    assert r["adler"] == D.lib_adler(bytes(r["data"]))
    assert r["list"]["count"] == 1 and r["list"]["rows"][0] == {"k": 7, "frames": 100, "folder": 2, "name": "KICK"}


def _ext80(rate: float) -> bytes:
    import math
    m, e = math.frexp(rate)                      # rate = m * 2**e, 0.5 <= m < 1
    return struct.pack(">HQ", 16383 + e - 1, int(m * 2 ** 64))


@pytest.mark.parametrize("comp", ["NONE", "sowt", "fl32"])
def test_an_aiff_reads_as_the_same_wav(comp):
    """2026-10-31: AIFF and AIFF-C (big-endian, sowt, float) give the WAV's frames, rate and cues"""
    n, rate = 300, 44100
    ch = [[int(9000 * ((i * 37 + c * 11) % 200 - 100) / 100) for i in range(n)] for c in (0, 1)]
    inter = [ch[c][i] for i in range(n) for c in (0, 1)]
    wav_data = struct.pack(f"<{2 * n}h", *inter)
    wav = (b"RIFF" + struct.pack("<I", 36 + len(wav_data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2, rate, rate * 4, 4, 16)
           + b"data" + struct.pack("<I", len(wav_data)) + wav_data)
    if comp == "fl32":
        snd, bits = struct.pack(f">{2 * n}f", *[v / 32768 for v in inter]), 32
    else:
        snd, bits = struct.pack(("<" if comp == "sowt" else ">") + f"{2 * n}h", *inter), 16
    comm = struct.pack(">hIh", 2, n, bits) + _ext80(rate) + (b"" if comp == "NONE" else comp.encode() + b"\x00\x00")
    mark = struct.pack(">HhI", 2, 1, 50) + b"\x01a" + struct.pack(">hI", 2, 120) + b"\x00\x00"
    chunks = [(b"COMM", comm), (b"MARK", mark), (b"SSND", struct.pack(">II", 0, 0) + snd)]
    body = (b"AIFC" if comp != "NONE" else b"AIFF") + b"".join(t + struct.pack(">I", len(c)) + c + b"\x00" * (len(c) & 1) for t, c in chunks)
    aiff = b"FORM" + struct.pack(">I", len(body)) + body
    r = _node(f"""const buf = b => Uint8Array.from(Buffer.from(b, "base64")).buffer;
      const a = DN2.readAiff(buf("{__import__('base64').b64encode(aiff).decode()}")), w = DN2.readWav(buf("{__import__('base64').b64encode(wav).decode()}"));
      console.log(JSON.stringify({{a: Array.from(a.frames), w: Array.from(w.frames), ar: a.rate, wr: w.rate, cues: a.cues}}))""")
    assert r["ar"] == r["wr"] == rate
    assert r["cues"] == [50, 120]
    assert len(r["a"]) == n and max(abs(x - y) for x, y in zip(r["a"], r["w"])) < 1e-6
