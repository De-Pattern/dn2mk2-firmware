"""Port a gated 1.11 build to stock 1.12 (docs/os112-port.md).

The build's MAIN OS is stock 1.11 with edits, plus the appended area (data chunks and CODE chunks
that run from RAM). The port:

1. **Edits.** Every byte run where the build's MAIN OS differs from stock 1.11 is moved to its
   1.12 place (`AddrMap.image`); the stock bytes under it must agree in both images (a relinked
   pointer aside), so an edit never lands on code that changed.
2. **Operands.** In every executed range (the edits, and each CODE chunk's code), the 1.11
   addresses an instruction carries as an absolute operand or a 32-bit immediate are found by
   disassembly (objdump, ColdFire V4e) and translated. Nothing outside a decoded instruction is
   touched.
3. **Data.** A CODE chunk's data, and the data chunks, are copied as they are; every 32-bit word in
   them that reads as a 1.11 address that moved is reported (`Report.data_words`), and the port
   refuses unless each is listed in `DATA_OK` (known not to be an address) or `DATA_PTR` (a
   pointer, translated).
4. **The area** goes after 1.12's last byte instead of 1.11's.

Everything translated or refused is in the report, with the instruction or the word, so the port
is reviewable line by line.
"""
from __future__ import annotations

import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .addrmap import BASE, AddrMap

OBJDUMP = "m68k-linux-gnu-objdump"
# a 1.11 address: MAIN OS, or RAM up to the top of stock's heap that our translator can place
LO, HI = 0x40000000, 0x46700000
# our own RAM (the area's chunks, the sample link's mirror, PROJECT RAM banks): never translated
OURS = [(0x46700000, 0x48000000)]


class PortError(RuntimeError):
    pass


@dataclass
class Report:
    edits: list = field(default_factory=list)          # (va11, va12, n)
    operands: list = field(default_factory=list)       # (where, insn, v11, v12)
    data_words: list = field(default_factory=list)     # (where, v11, v12, verdict)
    refused: list = field(default_factory=list)        # (where, why)


def _ours(v: int) -> bool:
    return any(a <= v < b for a, b in OURS)


def disasm(code: bytes, va: int) -> list[tuple[int, bytes, str]]:
    """-> [(va, bytes, text)] of a linear decode"""
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        f.write(code)
        f.flush()
        out = subprocess.run([OBJDUMP, "-D", "-b", "binary", "-m", "m68k:cfv4e",
                              f"--adjust-vma={va:#x}", f.name],
                             capture_output=True, text=True, check=True).stdout
    rows = []
    pat = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{4}\s)+)\s*(.*)$")
    for line in out.splitlines():
        m = pat.match(line)
        if not m:
            continue
        a = int(m.group(1), 16)
        raw = bytes.fromhex(m.group(2).replace(" ", ""))
        rows.append((a, raw, m.group(3).strip()))
    # objdump continues a long instruction's words on the next line(s) with no text
    merged: list[tuple[int, bytes, str]] = []
    for a, raw, text in rows:
        if not text and merged and merged[-1][0] + len(merged[-1][1]) == a:
            pa, praw, ptext = merged[-1]
            merged[-1] = (pa, praw + raw, ptext)
        else:
            merged.append((a, raw, text))
    return merged


def _immediates(text: str) -> set[int]:
    """the values written as immediates (#n) in an instruction's text"""
    out = set()
    for d in re.findall(r"#(-?\d+)\b", text):
        out.add(int(d) & 0xFFFFFFFF)
    for h in re.findall(r"#0x([0-9a-f]+)", text):
        out.add(int(h, 16))
    return out


def _values(text: str) -> set[int]:
    vals = set()
    for h in re.findall(r"0x([0-9a-f]+)", text):
        vals.add(int(h, 16))
    for d in re.findall(r"#(-?\d+)\b", text):
        vals.add(int(d) & 0xFFFFFFFF)
    return vals


def relocate_code(code: bytearray, va: int, m: AddrMap, rep: Report, where: str) -> None:
    """translate, in place, the 1.11 addresses carried by the instructions of `code` (at `va`)"""
    for a, raw, text in disasm(bytes(code), va):
        if text.startswith(".short") or text.startswith("unknown"):
            continue
        imms = _immediates(text)
        for v in _values(text):
            if not (LO <= v < HI) or _ours(v):
                continue
            needle = struct.pack(">I", v)
            k = raw.find(needle, 2)
            if k < 0:
                continue
            if v in imms:
                # an immediate: a number unless there is direct evidence it is an address
                nv, why = m.strict(v)
                if nv is None:
                    rep.data_words.append((f"{where} {a:#x}", v, v, f"immediate left as a number: {text}"))
                    continue
            else:
                nv, why = m.map(v)
            if nv is None:
                rep.refused.append((f"{where} {a:#x}", f"{text}: {v:#x} {why}"))
                continue
            if nv != v:
                o = a - va + k
                assert code[o:o + 4] == needle
                code[o:o + 4] = struct.pack(">I", nv)
                rep.operands.append((f"{where} {a:#x}", text, v, nv))


def data_words(blob: bytes, va: int, m: AddrMap, rep: Report, where: str,
               ok: dict[int, str], ptr: dict[int, str]) -> bytearray:
    out = bytearray(blob)
    for o in range(0, len(blob) - 3, 2):
        v = struct.unpack_from(">I", blob, o)[0]
        if not (LO <= v < HI) or _ours(v):
            continue
        nv, why = m.map(v)
        if nv is None or nv == v:
            continue
        at = va + o
        if at not in ptr and at not in ok:
            kind = _classify(v, nv, m)
            if kind.startswith("pointer"):
                ptr = {**ptr, at: kind}
            else:
                ok = {**ok, at: kind}
        if at in ptr:
            struct.pack_into(">I", out, o, nv)
            rep.data_words.append((f"{where} {at:#x}", v, nv, "pointer: " + ptr[at]))
        elif at in ok:
            rep.data_words.append((f"{where} {at:#x}", v, nv, "not an address: " + ok[at]))
        else:
            rep.data_words.append((f"{where} {at:#x}", v, nv, "UNREVIEWED"))
    return out


def _classify(v: int, nv: int, m: AddrMap) -> str:
    """a data word that reads as a moved 1.11 address: a pointer (to the start of a stock string,
    identical in 1.12) or not an address (text, or anything else, left as it is)"""
    raw = struct.pack(">I", v)
    if all(c == 0 or 0x20 <= c < 0x7F for c in raw):
        return "text"
    if BASE <= v < m.end_a and BASE <= nv < m.end_b:
        o, ob = v - BASE, nv - BASE
        tail = m.a[o:o + 48]
        z = tail.find(0)
        # (a string's tail counts: GCC shares a string's tail with a shorter one, "MIDI")
        if (z >= 3 and all(0x20 <= c < 0x7F for c in tail[:z])
                and m.a[o - 8:o + z + 1] == m.b[ob - 8:ob + z + 1]):
            return f"pointer to the stock string {tail[:z].decode()!r}"
    return "not a stock string: data"


def edit_runs(stock: bytes, build: bytes, gap: int = 8) -> list[tuple[int, int]]:
    """[(offset, length)] where build differs from stock (runs merged across small gaps)"""
    runs = []
    i, n = 0, min(len(stock), len(build))
    while i < n:
        if stock[i] == build[i]:
            i += 1
            continue
        j = i
        last = i
        while j < n and j - last <= gap:
            if stock[j] != build[j]:
                last = j
            j += 1
        runs.append((i, last + 1 - i))
        i = last + 1
    return runs


def port_edits(stock11: bytes, build11: bytes, stock12: bytes, m: AddrMap, rep: Report,
               insn_pad: int = 16) -> bytearray:
    """stock 1.12 MAIN OS with the build's edits moved and their operands translated"""
    out = bytearray(stock12)
    for o, n in edit_runs(stock11, build11):
        # an edit that touches a word stock relinked between 1.11 and 1.12 (a pointer) takes the
        # whole word from the build: a byte it left as stock 1.11's is not stock 1.12's there
        # (v0.73-t1: `jsr 0x46ac022a` over stock's `jsr 0x4011d32a` kept stock's last byte, and
        # 1.12's relinked 0x4011d60a made it `jsr 0x46ac020a`)
        va = BASE + o
        nva, why = m.image(va, span=1)
        if nva is None:
            rep.refused.append((f"edit {va:#x}+{n}", why))
            continue
        nb = nva - BASE
        # the stock bytes under the edit and around it must be the same code in 1.12
        lo, hi = max(0, o - insn_pad), o + n + insn_pad
        if not m.same(lo, nb - (o - lo), hi - lo):
            rep.refused.append((f"edit {va:#x}+{n}", "the stock code under it differs in 1.12"))
            continue
        piece = bytearray(build11[o:o + n])
        # decode from the edit's own start (an edit writes whole instructions: a hook's jmp/jsr,
        # or a replaced instruction), on to a little past it so its last one is whole
        ctx_lo = o & ~1
        ctx = bytearray(build11[ctx_lo:o + n + insn_pad])
        before = bytes(ctx)
        relocate_code(ctx, BASE + ctx_lo, m, rep, "edit")
        for k in range(len(ctx)):
            if ctx[k] != before[k]:
                if not (o <= ctx_lo + k < o + n):
                    continue                  # an operand in stock code: stock 1.12 has its own
                piece[ctx_lo + k - o] = ctx[k]
        out[nb:nb + n] = piece
        # a word stock relinked between 1.11 and 1.12 that the edit covers only in part
        for k in range((o - 3) & ~1, o + n + 3, 2):
            if k + 4 <= o or k >= o + n or k < 0 or (o <= k and k + 4 <= o + n):
                continue
            kb = k + (nb - o)
            if stock11[k:k + 4] == stock12[kb:kb + 4]:
                continue
            bw = struct.unpack_from(">I", build11, k)[0]
            if build11[k:k + 4] == stock11[k:k + 4] or not (_ours(bw) or LO <= bw < HI):
                continue        # untouched, or not an address word (a window across two instructions)
            if _ours(bw):
                w = bw                                                  # ours (a hook's target)
            else:
                w, why = m.map(bw)
                if w is None:
                    rep.refused.append((f"edit {va:#x}+{n}", f"a relinked word it covers: {bw:#x} {why}"))
                    continue
            struct.pack_into(">I", out, kb, w)
        rep.edits.append((va, nva, n))
    return out


# -- the whole build ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[3]
DATA_ONLY = {0x47000000: "the DSP's tables (scripts/ship_gate.py DATA_ONLY)"}
# words in a chunk's data that read as a moved 1.11 address and are known not to be one
DATA_OK: dict[int, str] = {}
# words in a chunk's data that are 1.11 addresses (pointers), translated
DATA_PTR: dict[int, str] = {}


def code_ranges() -> dict[int, list[tuple[int, int]]]:
    """the same recorded code ranges as the gate's ColdFire step (scripts/ship_gate.py)"""
    import json
    lay = json.loads((ROOT / "src/dnfw/mods/waverider_code.json").read_text())["layout"]
    out = {lay["is_wr"]: [(lay["is_wr"], lay["labels"])],
           lay["c_load"]: [(lay["c_load"], lay["c_text_end"])]}
    if "mchunk_code_end" in lay:
        out[lay["slot_shim"]] = [(lay["slot_shim"], lay["name_long_5"])]
    return out


def port_area(blob: bytes, m: AddrMap, rep: Report) -> bytes:
    """the appended area with each chunk's code relocated and its data checked"""
    from ..patch import area
    out = bytearray(blob)
    total, count = struct.unpack_from(">II", blob, 4)
    ranges = code_ranges()
    for i in range(count):
        cid = blob[12 + 12 * i:16 + 12 * i]
        off, n = struct.unpack_from(">II", blob, 16 + 12 * i)
        if cid != area.CODE:
            body = data_words(blob[off:off + n], area.RUNTIME_VA + off, m, rep,
                              cid.decode("latin-1"), DATA_OK, DATA_PTR)
            out[off:off + n] = body
            continue
        load = struct.unpack_from(">I", blob, off)[0]
        img_at, img_n = off + 16, struct.unpack_from(">I", blob, off + 4)[0]
        image = bytearray(blob[img_at:img_at + img_n])
        if load in DATA_ONLY:
            pass                                   # data for the DSP: never a ColdFire address
        else:
            spans = ranges.get(load, [(load, load + img_n)])
            covered = bytearray(img_n)
            for lo, hi in spans:
                seg = bytearray(image[lo - load:hi - load])
                relocate_code(seg, lo, m, rep, f"chunk {load:#x}")
                image[lo - load:hi - load] = seg
                covered[lo - load:hi - load] = b"\x01" * (hi - lo)
            # the rest of the chunk is data: reported, translated only where listed
            k = 0
            while k < img_n:
                if covered[k]:
                    k += 1
                    continue
                j = k
                while j < img_n and not covered[j]:
                    j += 1
                image[k:j] = data_words(bytes(image[k:j]), load + k, m, rep,
                                        f"chunk {load:#x} data", DATA_OK, DATA_PTR)
                k = j
        out[img_at:img_at + img_n] = image
    return bytes(out)


def verify_calls(build11: bytes, main12: bytes, m: AddrMap, n11: int, rep: Report) -> None:
    """every absolute call and jump in the edits must reach, on 1.12, the same code it reached on
    1.11: the target's first bytes in the 1.12 image equal the 1.11 build's (a relinked pointer
    aside). A misplaced or untranslated target fails here, before any emulator runs"""
    n12 = len(m.b)
    for o, n in edit_runs(m.a, build11[:n11]):
        nva, _ = m.image(BASE + o, span=1)
        if nva is None:
            continue
        d = nva - BASE - o
        # each jsr/jmp abs.l whose opcode or operand the edit touches (found by its opcode at an
        # even offset, so a run that starts inside an instruction still finds it)
        for p in range((o - 6) & ~1, o + n, 2):
            if build11[p:p + 2] not in (b"\x4e\xb9", b"\x4e\xf9") or p + 6 <= o:
                continue
            t1 = struct.unpack_from(">I", build11, p + 2)[0]
            t2 = struct.unpack_from(">I", main12, p + 2 + d)[0]
            x = build11[t1 - BASE:t1 - BASE + 6] if BASE <= t1 < BASE + n11 else None
            y = main12[t2 - BASE:t2 - BASE + 6] if BASE <= t2 < BASE + n12 else None
            if x is None and y is None:
                if t1 != t2:
                    rep.refused.append((f"call {BASE + p + d:#x}", f"to our {t2:#x}, was {t1:#x}"))
                continue
            if x is None or y is None or not _same6(x, y):
                rep.refused.append((f"call {BASE + p + d:#x}",
                                    f"reaches {t2:#x}, not the code {t1:#x} reached on 1.11"))


def _same6(x: bytes, y: bytes) -> bool:
    return x[:2] == y[:2] and (x == y or (x[2] >> 4 == 4 and y[2] >> 4 == 4))


def port_main_os(build11: bytes, m: AddrMap, rep: Report) -> bytes:
    from ..mods import platform
    n11 = platform.SPEC["stock_length"]                # 1.11's, whatever DN2_OS says
    at = platform.SPEC["calls_va"] - BASE
    if (len(build11) < n11 or len(m.a) != n11
            or build11[at:at + len(platform.SPEC["hook"]) // 2].hex() != platform.SPEC["hook"]):
        raise PortError("not a DN2 mk2 build on stock 1.11 (no platform loader, or the wrong length)")
    base = build11[:n11]
    new_base = port_edits(m.a, base, m.b, m, rep)
    out = bytes(new_base) + port_area(build11[len(base):], m, rep)
    verify_calls(build11, out, m, n11, rep)
    return out


def assemble(stock12_syx: bytes, main12: bytes, sec7: bytes) -> bytes:
    """stock 1.12 with MAIN OS and the DSP section replaced, every checksum recomputed and the
    result verified (dnfw build, in-process: the browser runs this too)"""
    from ..cli.build import rebuild, replacement
    from ..firmware.load import load
    from ..firmware.verify import verify
    fw = load(stock12_syx)
    out = rebuild(fw, {3: replacement(fw, 3, main12), 7: replacement(fw, 7, sec7)})
    if not verify(load(out)).ok:
        raise PortError("the 1.12 image does not verify")
    return out


def port_syx(build11: Path, out: Path, stock11: Path | None = None, stock12: Path | None = None) -> Report:
    """build11 (.syx, a DN2 mk2 build on stock 1.11) -> out (.syx on stock 1.12), signed; the
    report says every edit, operand and data word. Refuses on any refusal."""
    from ..cli.files import read_image
    from ..firmware.load import load
    from .addrmap import AddrMap, main_os
    stock11 = stock11 or ROOT.parent / "Digitone_II_OS1.11.syx"
    stock12 = stock12 or ROOT.parent / "Digitone_II_OS1.12.syx"
    m = AddrMap(main_os(stock11), main_os(stock12))
    rep = Report()
    secs = {s.id: s for s in load(read_image(build11)).container.sections}
    main12 = port_main_os(secs[3].unpack(), m, rep)
    if rep.refused or any(w[3] == "UNREVIEWED" for w in rep.data_words):
        raise PortError(f"{len(rep.refused)} refused: {rep.refused[:5]}")
    out.write_bytes(assemble(read_image(stock12), main12, secs[7].unpack()))
    return rep


# -- the recipe: the port replayed without a disassembler (the browser) ------------------------
def recipe(build11_main: bytes, m: AddrMap) -> dict:
    """The port of this MAIN OS as data: the byte runs that move (1.11 offset, 1.12 offset,
    length: exactly the bytes the build changed, so never Elektron's), and every 32-bit word the
    port changes (its offset in the 1.12 MAIN OS, the value before, the value after). Offsets and
    addresses only: `replay` rebuilds `port_main_os`'s result from the build and stock 1.12."""
    import hashlib
    from ..mods import platform
    n11 = platform.SPEC["stock_length"]
    rep = Report()
    want = port_main_os(build11_main, m, rep)
    if rep.refused:
        raise PortError(f"refused: {rep.refused[:3]}")
    runs = []
    for o, n in edit_runs(m.a, build11_main[:n11], gap=0):
        nva, _ = m.image(BASE + o, span=1)
        runs.append([o, nva - BASE, n])
    base = _replay_runs(build11_main, m.b, runs, n11)
    words = [[k, struct.unpack_from(">I", base, k)[0], struct.unpack_from(">I", want, k)[0]]
             for k in _changed_words(base, want)]
    return {"build11_main_sha256": hashlib.sha256(build11_main).hexdigest(),
            "stock11_length": n11, "stock12_length": len(m.b),
            "want_sha256": hashlib.sha256(want).hexdigest(), "runs": runs, "words": words}


def _replay_runs(build11_main: bytes, stock12_main: bytes, runs, n11: int) -> bytearray:
    out = bytearray(stock12_main)
    for o11, o12, n in runs:
        out[o12:o12 + n] = build11_main[o11:o11 + n]
    return out + build11_main[n11:]


def _changed_words(a: bytes, b: bytes) -> list[int]:
    """even offsets of 4-byte windows that cover every byte where a and b differ (each window
    starts at the first differing byte's even offset; `replay`'s sha256 check is the proof)"""
    if len(a) != len(b):
        raise PortError("the replayed runs and the port differ in length")
    out, k = [], 0
    while k < len(a):
        if a[k] == b[k]:
            k += 1
            continue
        st = k & ~1
        out.append(st)
        k = st + 4
    return out


def replay(recipe: dict, build11_main: bytes, stock12_main: bytes) -> bytes:
    """the ported MAIN OS from the recipe, the 1.11 build's MAIN OS and stock 1.12's"""
    import hashlib
    if hashlib.sha256(build11_main).hexdigest() != recipe["build11_main_sha256"]:
        raise PortError("this is not the 1.11 build the recipe was made from")
    if len(stock12_main) != recipe["stock12_length"]:
        raise PortError("that is not stock Digitone II OS 1.12's MAIN OS")
    out = _replay_runs(build11_main, stock12_main, recipe["runs"], recipe["stock11_length"])
    for k, old, new in recipe["words"]:
        if struct.unpack_from(">I", out, k)[0] != old:
            raise PortError(f"the word at +{k:#x} is not {old:#x}: not stock 1.12")
        struct.pack_into(">I", out, k, new)
    if hashlib.sha256(out).hexdigest() != recipe["want_sha256"]:
        raise PortError("the replayed port differs from the cleared one")
    return bytes(out)
