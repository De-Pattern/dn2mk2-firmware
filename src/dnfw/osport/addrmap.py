"""1.11 -> 1.12 address translation for MAIN OS (ColdFire), with evidence.

Two images, decoded MAIN OS of each. In the image: unique 16-byte k-mers matched across the two
give the shift of every run of unchanged code (`segments`). Outside the image (RAM: .bss and the
heap): every 1.11 instruction word that holds the address as an absolute operand, moved by its
own segment's shift, gives a candidate read from 1.12; agreement of all of them is the answer.
"""
from __future__ import annotations

import bisect
import collections
import functools
import pathlib
import struct

BASE = 0x40000400
K = 16


def _kmers(d: bytes, step: int) -> dict[bytes, int]:
    c: collections.Counter = collections.Counter()
    pos: dict[bytes, int] = {}
    for i in range(0, len(d) - K, step):
        k = d[i:i + K]
        if k.count(0) > 8 or len(set(k)) < 6:
            continue
        c[k] += 1
        pos[k] = i
    return {k: pos[k] for k, n in c.items() if n == 1}


class AddrMap:
    def __init__(self, a: bytes, b: bytes, min_run: int = 256):
        self.a, self.b = a, b
        B = _kmers(b, 1)
        A = _kmers(a, 2)
        pts = sorted((ia, B[k] - ia) for k, ia in A.items() if k in B)
        segs: list[list[int]] = []
        for ia, d in pts:
            if segs and segs[-1][2] == d:
                segs[-1][1] = ia + K
            else:
                segs.append([ia, ia + K, d])
        self.segs = [tuple(s) for s in segs if s[1] - s[0] >= min_run]
        self._starts = [s[0] for s in self.segs]
        self.end_a, self.end_b = BASE + len(a), BASE + len(b)

    # -- in the image --------------------------------------------------------------------
    def seg_of(self, off: int):
        i = bisect.bisect_right(self._starts, off) - 1
        if i >= 0 and self.segs[i][0] <= off < self.segs[i][1]:
            return self.segs[i]
        return None

    def image(self, va: int, span: int = 8):
        """-> (1.12 va, why) or (None, why) for an address in 1.11's MAIN OS"""
        off = va - BASE
        s = self.seg_of(off)
        if s is None:
            return None, "in code that changed in 1.12 (no matching run around it)"
        nb = off + s[2]
        if self.a[off:off + span] != self.b[nb:nb + span]:
            return None, f"in a matched run (shift {s[2]:+d}) but its own {span} bytes differ"
        return BASE + nb, f"matched run, shift {s[2]:+d}"

    # -- outside the image (RAM) ---------------------------------------------------------
    @functools.lru_cache(maxsize=None)
    def ram(self, va: int, near: int = 0x100):
        """-> (1.12 va, why) or (None, why). Uses every reference to [va - near, va] in 1.11
        code as an absolute long operand (a base the code adds to also counts)."""
        votes: collections.Counter = collections.Counter()
        for base in range(va, va - near - 1, -2):
            pat = struct.pack(">I", base)
            i = self.a.find(pat)
            while i != -1:
                s = self.seg_of(i)
                if s is not None:
                    j = i + s[2]
                    if self.a[i - 4:i] == self.b[j - 4:j]:        # the opcode words agree
                        nv = struct.unpack(">I", self.b[j:j + 4])[0]
                        votes[nv - base] += 1
                i = self.a.find(pat, i + 2)
            if votes:
                break
        if not votes:
            return None, "no reference in 1.11 code"
        (d, n), *rest = votes.most_common()
        if rest and rest[0][1] * 4 > n:
            return None, f"references disagree: {votes.most_common(4)}"
        return va + d, f"{n} reference(s) agree, shift {d:+d}" + (f" (base {hex(base)})" if base != va else "")

    def map(self, va: int):
        if BASE <= va < self.end_a:
            return self.image(va)
        if va >= self.end_a:
            return self.ram(va)
        return None, "below MAIN OS"


def main_os(image: pathlib.Path) -> bytes:
    """decoded MAIN OS (section 3) of a .syx"""
    from ..cli.files import read_image
    from ..firmware.load import load
    fw = load(read_image(image))
    return next(s for s in fw.container.sections if s.id == 3).unpack()


ROOT = pathlib.Path(__file__).resolve().parents[3]


@functools.lru_cache(maxsize=1)
def default() -> AddrMap:
    """1.11 -> 1.12 from the stock images beside the repository"""
    return AddrMap(main_os(ROOT.parent / "Digitone_II_OS1.11.syx"),
                   main_os(ROOT.parent / "Digitone_II_OS1.12.syx"))
