"""Move the shipping build's stock addresses from Digitone II OS 1.11 to OS 1.12.

    python scripts/port_os112.py STOCK_1.11(.zip|.syx) STOCK_1.12(.zip|.syx) [--write] [--json OUT]

Without --write it changes nothing and prints what it would do (docs/os112-port.md).

How it decides, all measured from the two stock images, nothing remembered:

1. **Align MAIN OS.** Every 12-byte run unique in both images anchors a delta (1.12 offset
   minus 1.11 offset); anchors grow over equal bytes. 1.12 is 1.11 relinked: long regions
   each moved by one constant (0, +0x164, +0x2e0, +0x410, +0x4b8, +0x540, ...).
2. **BSS.** The start-up code's own bounds give it: 1.11 clears 0x402fc000..0x466b74d0,
   1.12 0x402fd000..0x466b84d0, so every BSS address moves +0x1000. Checked here against the
   stock operands: every BSS operand of aligned 1.11 code must reappear +0x1000 in 1.12.
3. **Each literal** `0x4XXXXXXX` in the files below is a stock address when it falls in
   MAIN OS or BSS. A code address moves by its region's delta only if 12 bytes there are the
   same code in 1.12 (equal, or differing only in absolute operands that themselves
   translate); otherwise the script refuses (a hand port). A BSS literal moves +0x1000,
   unless its four bytes are letters or digits (a tag such as 'DNFW').
   Inside a hex string (stock bytes in Python), only a long after an opcode word whose
   operand is absolute long is an address.
4. Lines that name an OS version (1.10, 1.11, 1.12) are history and are left alone.

Firmware is never written here: this edits source text. The edits' stock-bytes checks,
re-run by scripts/gen_*_code.py against 1.12, are what prove each placement.
"""

from __future__ import annotations

import bisect
import json
import pathlib
import re
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

BASE = 0x40000400
K = 12
BSS_111 = (0x402FC000, 0x466B74D0)
BSS_SHIFT = 0x1000

FILES = [
    "src/dnfw/waverider/coldfire.py", "src/dnfw/waverider/cpage.py", "src/dnfw/waverider/pages.py",
    "src/dnfw/slides.py",
    "src/dnfw/sampler/machines.py", "src/dnfw/patch/area.py", "src/dnfw/patch/loader.py",
    "src/dnfw/mods/waverider.py", "src/dnfw/mods/platform.py", "src/dnfw/mods/bootscreen.py",
    "scripts/gen_waverider_code.py", "scripts/gen_platform_code.py", "scripts/gen_bootscreen_code.py",
    "csrc/include/dn2_111.h", "csrc/runtime/loader.S",
]
C_DIRS = ["waverider", "sampler", "jump", "slides"]

# C literals may carry a suffix (0x42431a6cu, 0x4011c674UL): 148 of them in csrc/ (2026-11-07)
LIT = re.compile(r"0([xX])(4[0-6][0-9a-fA-F]{6})(?=[uUlL]*\b)")
HEXSTR = re.compile(r"([\"'])([0-9a-fA-F]{12,})\1")
VERSION = re.compile(r"\b1\.1[0-2]")


def section3(path: str) -> bytes:
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(pathlib.Path(path))).container.find(3).unpack()


class Map:
    def __init__(self, a: bytes, b: bytes):
        self.a, self.b = a, b
        self.runs = self._align()
        self.starts = [r[0] for r in self.runs]
        self.long = [r for r in self.runs if r[1] - r[0] >= 64]
        self.lstarts = [r[0] for r in self.long]

    def _align(self) -> list[tuple[int, int, int]]:
        a, b = self.a, self.b

        def uniq(data):
            pos, dup = {}, set()
            for i in range(len(data) - K + 1):
                k = data[i:i + K]
                if k in pos:
                    dup.add(k)
                else:
                    pos[k] = i
            for k in dup:
                del pos[k]
            return pos
        ia, ib = uniq(a), uniq(b)
        d_at: list[int | None] = [None] * len(a)
        for k, i in ia.items():
            j = ib.get(k)
            if j is not None:
                for t in range(i, i + K):
                    d_at[t] = j - i
        for step, rng in ((1, range(1, len(a))), (-1, range(len(a) - 2, -1, -1))):
            for i in rng:
                if d_at[i] is None:
                    p = d_at[i - step]
                    if p is not None and 0 <= i + p < len(b) and a[i] == b[i + p]:
                        d_at[i] = p
        runs, s = [], 0
        for i in range(1, len(a) + 1):
            if i == len(a) or d_at[i] != d_at[s]:
                if d_at[s] is not None:
                    runs.append((BASE + s, BASE + i, d_at[s]))
                s = i
        return runs

    def regions(self) -> list[tuple[int, int, int]]:
        out: list[list[int]] = []
        for s, e, d in self.long:
            if out and out[-1][2] == d:
                out[-1][1] = e
            else:
                out.append([s, e, d])
        return [tuple(r) for r in out if r[1] - r[0] >= 1024]

    def _code_delta(self, va: int) -> list[int]:
        i = bisect.bisect_right(self.starts, va) - 1
        # only long runs: a short one can be an accidental match with a wrong delta
        # (0x401ac2de, a vtable entry, sat in an 8+ byte run of +0x56; its region is +0x2e0)
        if i >= 0 and self.runs[i][0] <= va < self.runs[i][1] and self.runs[i][1] - self.runs[i][0] >= 64:
            return [self.runs[i][2]]
        j = bisect.bisect_right(self.lstarts, va) - 1
        return list(dict.fromkeys(r[2] for r in self.long[max(j, 0):j + 2]))

    def word(self, w: int) -> int | None:
        """translation of one absolute operand, no verification"""
        if BSS_111[0] <= w < BSS_111[1]:
            return w + BSS_SHIFT
        if BASE <= w < BSS_111[0]:
            ds = self._code_delta(w)
            return w + ds[0] if ds else None
        return w

    def same(self, va: int, vb: int, n: int = 12) -> bool:
        i, j = va - BASE, vb - BASE
        if i < 0 or j < 0 or i + n > len(self.a) or j + n > len(self.b):
            return False
        x, y = self.a[i:i + n], self.b[j:j + n]
        if x == y:
            return True
        covered = set()
        for k in range(n):
            if x[k] == y[k] or k in covered:
                continue
            for s in range(k - 3, k + 1):
                if i + s < 0 or i + s + 4 > len(self.a):
                    continue
                w1 = struct.unpack_from(">I", self.a, i + s)[0]
                w2 = struct.unpack_from(">I", self.b, j + s)[0]
                if w1 != w2 and self.word(w1) == w2:
                    covered.update(range(s, s + 4))
                    break
            if k not in covered:
                return False
        return True

    def code(self, va: int) -> int | None:
        """1.12 address of 1.11 code/rodata address va, or None if not proven"""
        for d in self._code_delta(va):
            if self.same(va, va + d):
                return va + d
        return None


def classify(m: Map, w: int) -> tuple[str, int | None]:
    if BASE <= w < BSS_111[0]:
        t = m.code(w)
        return ("same" if t == w else "moved", t) if t is not None else ("REFUSED", None)
    if BSS_111[0] <= w < BSS_111[1]:
        raw = struct.pack(">I", w)
        if all(c < 0x80 and chr(c).isalnum() for c in raw):         # 'DNFW', 'CODE': a tag, not an address
            return "ascii", w
        return "bss", w + BSS_SHIFT
    return "other", w


def abs_long_opcode(op: int) -> bool:
    if op & 0x3F == 0x39:                                  # source EA = abs.l
        return True
    return op >> 12 in (1, 2, 3) and (op >> 6) & 0x3F == 0x0F   # move dest = abs.l


def check_bss(m: Map) -> list[str]:
    """every BSS operand in aligned 1.11 code reappears +0x1000 in 1.12"""
    bad = []
    for s, e, d in m.regions():
        for i in range((s - BASE + 1) & ~1, e - BASE - 4, 2):     # code is word aligned
            w = struct.unpack_from(">I", m.a, i)[0]
            if (i + d) % 2 == 0 and BSS_111[0] <= w < BSS_111[1] and abs_long_opcode(struct.unpack_from(">H", m.a, i - 2)[0]):
                v = struct.unpack_from(">I", m.b, i + d)[0]
                # an unchanged long is an instruction pair read out of step, not an operand
                if v not in (w, w + BSS_SHIFT):
                    bad.append(f"{BASE + i:#010x}: {w:#010x} -> {v:#010x}")
    return bad


def files() -> list[str]:
    out = list(FILES)
    for d in C_DIRS:
        out += sorted(str(p.relative_to(ROOT)) for p in (ROOT / "csrc" / d).iterdir()
                      if p.suffix in (".c", ".h", ".S"))
    return out


def port_line(m: Map, line: str, is_py: bool, report: list) -> str:
    if VERSION.search(line):
        if LIT.search(line):
            report.append(("history", None, None))
        return line

    def lit(mo):
        w = int(mo.group(2), 16)
        cls, t = classify(m, w)
        report.append((cls, w, t))
        if cls in ("moved", "bss") and t != w:
            digits = f"{t:08x}"
            return "0" + mo.group(1) + (digits.upper() if mo.group(2).isupper() else digits)
        return mo.group(0)
    line = LIT.sub(lit, line)
    if not is_py:
        return line

    def hexs(mo):
        s = bytearray.fromhex(mo.group(2)) if len(mo.group(2)) % 2 == 0 else None
        if s is None:
            return mo.group(0)
        changed = False
        for k in range(2, len(s) - 3, 2):
            if not abs_long_opcode(struct.unpack_from(">H", s, k - 2)[0]):
                continue
            w = struct.unpack_from(">I", s, k)[0]
            cls, t = classify(m, w)
            if cls in ("other", "ascii"):
                continue
            report.append(("hex-" + cls, w, t))
            if t is not None and t != w:
                struct.pack_into(">I", s, k, t)
                changed = True
        if not changed:
            return mo.group(0)
        h = s.hex()
        return mo.group(1) + (h.upper() if mo.group(2).isupper() else h) + mo.group(1)
    return HEXSTR.sub(hexs, line)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    out_json = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    if out_json in args:
        args.remove(out_json)
    # --only FILE[,FILE...]: port just these (a test that names stock addresses; never re-run
    # over files already ported: their 1.12 addresses would be read as 1.11)
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    if only and ",".join(only) in args:
        args.remove(",".join(only))
    if len(args) != 2:
        raise SystemExit(__doc__)
    a, b = section3(args[0]), section3(args[1])
    m = Map(a, b)
    print("MAIN OS 1.11 %d B, 1.12 %d B; regions (>= 1 KB):" % (len(a), len(b)))
    for s, e, d in m.regions():
        print(f"  {s:#010x}..{e:#010x}  {d:+#x}")
    bad = check_bss(m)
    print(f"BSS operands not moved +0x1000: {len(bad)}")
    for x in bad[:20]:
        print("  ", x)
    refused, summary, detail, pending = [], {}, {}, {}
    for rel in only or files():
        path = ROOT / rel
        text = path.read_text()
        report: list = []
        rows = []
        new_lines = []
        for n, line in enumerate(text.split("\n"), 1):
            before = len(report)
            new_lines.append(port_line(m, line, rel.endswith(".py"), report))
            for cls, w, t in report[before:]:
                rows.append({"line": n, "class": cls, "va": w, "va112": t})
                if cls.endswith("REFUSED"):
                    refused.append(f"{rel}:{n} {w:#010x}")
        new = "\n".join(new_lines)
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["class"]] = counts.get(r["class"], 0) + 1
        if rows:
            summary[rel] = counts
            detail[rel] = rows
        if new != text:
            pending[path] = new
    if write and not refused and not bad:  # all or nothing: every file is checked first
        for path, new in pending.items():
            path.write_text(new)
    for rel, c in summary.items():
        print(f"  {rel}: {c}")
    total: dict[str, int] = {}
    for c in summary.values():
        for k, v in c.items():
            total[k] = total.get(k, 0) + v
    print("total:", total)
    if out_json:
        pathlib.Path(out_json).write_text(json.dumps(detail, indent=0))
    if refused or bad:
        print(f"REFUSED: {len(refused)} literal(s) not proven; nothing written" if refused else "")
        for r in refused:
            print("  ", r)
        return 1
    print("written" if write else "dry run: nothing written (--write to apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
