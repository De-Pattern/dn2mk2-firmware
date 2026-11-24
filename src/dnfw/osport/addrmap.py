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


def _same_region(a: int, b: int) -> bool:
    for lo, hi in ((0x40000000, 0x48000000), (0x80000000, 0x80020000)):
        if lo <= a < hi:
            return lo <= b < hi
    return False


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
        if off < self.segs[0][0] and self.a[:self.segs[0][0]] == self.b[:self.segs[0][0]]:
            return va, "before the first matched run, and the same bytes in both"
        s = self.seg_of(off)
        if s is None:
            return None, "in code that changed in 1.12 (no matching run around it)"
        nb = off + s[2]
        if not self.same(off, nb, span):
            return None, f"in a matched run (shift {s[2]:+d}) but its own {span} bytes differ"
        return BASE + nb, f"matched run, shift {s[2]:+d}"

    def same(self, oa: int, ob: int, span: int) -> bool:
        """the two images' bytes agree over [oa, oa+span) / [ob, ob+span), a relinked absolute
        pointer (a 32-bit word into MAIN OS or RAM, 0x40000000..0x4fffffff, in both) excepted"""
        lo = (oa - 4) & ~1
        mask = set()
        for i in range(lo, oa + span, 2):
            j = ob + (i - oa)
            if i < 0 or j < 0:
                continue
            wa, wb = self.a[i:i + 4], self.b[j:j + 4]
            if len(wa) == len(wb) == 4 and wa != wb and wa[0] >> 4 == 4 and wb[0] >> 4 == 4:
                mask.update(range(i, i + 4))
        return all(self.a[oa + k] == self.b[ob + k] for k in range(span) if oa + k not in mask)

    # -- outside the image (RAM) ---------------------------------------------------------
    @functools.cached_property
    def _refs(self) -> dict[int, list[int]]:
        """every 32-bit word of 1.11 at an even offset whose value lies past the image (RAM), with
        the shift its 1.12 counterpart shows, where both sit in a matched run with equal opcode
        words before them: {value: [shift, ...]}"""
        out: dict[int, list[int]] = collections.defaultdict(list)
        a, b = self.a, self.b
        for i in range(4, len(a) - 3, 2):
            v = (a[i] << 24) | (a[i + 1] << 16) | (a[i + 2] << 8) | a[i + 3]
            if v < self.end_a or v >= 0x90000000:
                continue
            s = self.seg_of(i)
            if s is None:
                continue
            j = i + s[2]
            if a[i - 4:i] != b[j - 4:j]:
                continue
            out[v].append(struct.unpack(">I", b[j:j + 4])[0] - v)
        return out

    @functools.lru_cache(maxsize=None)
    def ram(self, va: int, near: int = 0x100):
        """-> (1.12 va, why) or (None, why). The references to [va - near, va] in 1.11 code (a
        base the code adds to counts); failing those, every reference within 16 KB either side.
        The shift is the one at least 95 % of them show (a few immediates that only look like
        addresses vote too)."""
        refs = self._refs
        for lo, hi, what in ((va - near, va + 1, "reference(s)"),
                             (va - 0x4000, va + 0x4000, "reference(s) within 16 KB")):
            votes: collections.Counter = collections.Counter()
            for base in range(lo, hi):
                for d in refs.get(base, ()):
                    if _same_region(va, va + d):          # a vote off the end of RAM is a constant
                        votes[d] += 1
            if not votes:
                continue
            (d, n), = votes.most_common(1)
            tot = sum(votes.values())
            if n >= 0.95 * tot:
                return va + d, f"{n} of {tot} {what} agree, shift {d:+d}"
            return None, f"{what} disagree: {votes.most_common(4)}"
        return None, "no reference in 1.11 code"

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
