"""The optimal-parse packer (v0.65, docs/packer.md): apopt.c chooses the tokens, aplibpack's
own `_Writer` writes them.

v0.64's image was 291 bytes under the 2 MiB USB limit (`docs/usb-upgrade-limit.md`), packed by
`aplibpack.pack` (greedy, one step of lookahead). The same sections parsed optimally come out
about 87 KB smaller (MAIN OS -72 KB, the DSP program -15 KB), inside the same limits, and the
instrument's own depacker (the bootstrap's 0x80000432, run in the emulator by the gate's
`depack` step) gives back exactly the bytes we packed.

The planner is C because a dynamic program over every byte of a 3.4 MB section is out of reach
in Python (and the in-browser patcher runs this same build under Pyodide). One source,
`apopt.c`, three ways to run it, all giving the same tokens:

    native   compiled here with the system's C compiler, called through ctypes (the build,
             the gate)
    pyodide  `apopt.wasm` (scripts/build_apopt_wasm.py), instantiated through the browser's
             WebAssembly (the patcher)
    node     the same `apopt.wasm` under node (web_bundle's rebuild from the zip alone, which
             runs the build as the browser does, and the tests)

`DNFW_APOPT` picks one; the default is pyodide under Pyodide, else native.
"""

from __future__ import annotations

import array
import hashlib
import os
import pathlib
import subprocess
import sys
import tempfile

from .aplibpack import _Writer

DEPTH = 1024                      # the chain depth: candidates looked at a position
HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE / "apopt.c"
WASM = HERE / "apopt.wasm"
WASM_MAGIC = b"\0asm"


class PackError(RuntimeError):
    pass


def _wasm_bytes() -> bytes:
    b = WASM.read_bytes()
    if b[:4] != WASM_MAGIC:
        raise PackError(f"{WASM} is not a WebAssembly module")
    return b


def _tokens_native(data: bytes, depth: int) -> array.array:
    import ctypes
    src = SOURCE.read_bytes()
    _wasm_bytes()           # opened here too, so web_bundle's audit carries it into the zip
    tag = hashlib.sha256(src).hexdigest()[:16]
    cache = pathlib.Path(os.environ.get("DNFW_APOPT_CACHE", tempfile.gettempdir())) / f"dnfw-apopt-{tag}.so"
    if not cache.is_file():
        cc = os.environ.get("CC", "cc")
        tmp = cache.with_suffix(f".{os.getpid()}.tmp")
        with tempfile.TemporaryDirectory() as td:
            c = pathlib.Path(td) / "apopt.c"
            c.write_bytes(src)
            r = subprocess.run([cc, "-O2", "-shared", "-fPIC", "-fno-strict-aliasing", "-o", str(tmp), str(c)],
                               capture_output=True, text=True)
        if r.returncode:
            raise PackError(f"could not compile apopt.c with {cc}: {r.stderr.strip()}")
        os.replace(tmp, cache)
    lib = ctypes.CDLL(str(cache))
    lib.apopt_need.restype = lib.apopt_tokens.restype = lib.apopt_plan.restype = ctypes.c_uint32
    lib.apopt_need.argtypes = lib.apopt_tokens.argtypes = [ctypes.c_uint32]
    lib.apopt_plan.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    n = len(data)
    region = (ctypes.c_uint8 * lib.apopt_need(n))()
    ctypes.memmove(region, data, n)
    cnt = lib.apopt_plan(region, n, depth)
    off = lib.apopt_tokens(n)
    out = array.array("I")
    out.frombytes(bytes(memoryview(region)[off:off + 8 * cnt]))
    if sys.byteorder != "little":
        out.byteswap()
    return out


_NODE_PROG = r"""
const fs = require("fs");
const [wasmPath, inPath, outPath, depth] = process.argv.slice(2);
const data = fs.readFileSync(inPath);
const inst = new WebAssembly.Instance(new WebAssembly.Module(fs.readFileSync(wasmPath)), {});
const e = inst.exports, n = data.length, base = e.__heap_base.value;
const need = base + e.apopt_need(n), mem = e.memory;
if (need > mem.buffer.byteLength) mem.grow(Math.ceil((need - mem.buffer.byteLength) / 65536));
new Uint8Array(mem.buffer, base, n).set(data);
const cnt = e.apopt_plan(base, n, Number(depth));
fs.writeFileSync(outPath, new Uint8Array(mem.buffer, base + e.apopt_tokens(n), 8 * cnt));
"""


def _tokens_node(data: bytes, depth: int) -> array.array:
    node = os.environ.get("NODE", "node")
    with tempfile.TemporaryDirectory() as td:
        t = pathlib.Path(td)
        (t / "in.bin").write_bytes(data)
        (t / "run.js").write_text(_NODE_PROG)
        wasm = t / "apopt.wasm"
        wasm.write_bytes(_wasm_bytes())
        r = subprocess.run([node, str(t / "run.js"), str(wasm), str(t / "in.bin"), str(t / "out.bin"), str(depth)],
                           capture_output=True, text=True)
        if r.returncode:
            raise PackError(f"apopt.wasm under node failed: {r.stderr.strip()}")
        out = array.array("I")
        out.frombytes((t / "out.bin").read_bytes())
    if sys.byteorder != "little":
        out.byteswap()
    return out


def _tokens_pyodide(data: bytes, depth: int) -> array.array:
    import js                                   # Pyodide's bridge to the browser
    from pyodide.ffi import to_js
    mod = js.WebAssembly.Module.new(to_js(_wasm_bytes()))
    e = js.WebAssembly.Instance.new(mod, js.Object.new()).exports
    n = len(data)
    base = getattr(e, "__heap_base").value
    need = base + e.apopt_need(n)
    mem = e.memory
    if need > mem.buffer.byteLength:
        mem.grow((need - mem.buffer.byteLength + 65535) // 65536)
    js.Uint8Array.new(mem.buffer, base, n).set(to_js(data))
    cnt = e.apopt_plan(base, n, depth)
    raw = js.Uint8Array.new(mem.buffer, base + e.apopt_tokens(n), 8 * cnt).to_py()
    out = array.array("I")
    out.frombytes(bytes(raw))
    return out


def backend() -> str:
    b = os.environ.get("DNFW_APOPT")
    if b:
        if b not in ("native", "node", "pyodide"):
            raise PackError(f"DNFW_APOPT={b!r}: native, node or pyodide")
        return b
    return "pyodide" if sys.platform == "emscripten" else "native"


def tokens(data: bytes, depth: int = DEPTH, how: str | None = None) -> array.array:
    """the parse: (offset, length) pairs, offset 0 a literal"""
    how = how or backend()
    if not data:
        return array.array("I")
    return {"native": _tokens_native, "node": _tokens_node, "pyodide": _tokens_pyodide}[how](data, depth)


def pack(data: bytes, depth: int = DEPTH, how: str | None = None) -> bytes:
    """`data` as an aPLib stream (no section header), from the optimal parse"""
    t = tokens(data, depth, how)
    w = _Writer()
    last = 1
    pos = 0
    n = len(data)
    for k in range(0, len(t), 2):
        off, length = t[k], t[k + 1]
        if off == 0:
            if length != 1:
                raise PackError(f"a literal of length {length} at {pos}")
            w.literal(data[pos])
        else:
            if not (0 < off <= pos and length >= 2 and pos + length <= n):
                raise PackError(f"a match ({off}, {length}) at {pos} that does not fit")
            last = w.match(off, length, last)
        pos += length
    if pos != n:
        raise PackError(f"the parse covers {pos} of {n} bytes")
    w.end()
    return bytes(w.out)
