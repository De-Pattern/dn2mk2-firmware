"""Comparing two firmware images section by section.

One subject: producing the differences. Rendering them is `cli.diff`'s job.

Comparison is on **decoded** content, never on the stored bytes -- two
compressions of the same code differ everywhere, and that is not a change.
The differing bytes are counted and clustered, because a relink shows as
thousands of scattered one-byte pointer changes while a real rewrite shows as
one dense block, and the two read very differently. When the lengths differ
the shared prefix is compared unshifted: if the growth is at the end, as it was
from 1.10D to 1.10E, that is exactly right, and if something was inserted
mid-way it shows as one block running from the insertion to the end.
"""

import re
from dataclasses import dataclass

from .model import Firmware

CLUSTER_GAP = 4096  # differences closer than this belong to one block
_TEXT = re.compile(rb"(?<![\x20-\x7e])[A-Za-z#_%][\x20-\x7e]{5,}(?=\x00)")


@dataclass(frozen=True)
class Block:
    start: int  # offset into the decoded section
    end: int  # one past the last differing byte
    differing: int


@dataclass(frozen=True)
class SectionDiff:
    id: int
    present: tuple[bool, bool]
    raw: tuple[bool, bool]  # stored raw rather than compressed
    length: tuple[int, int]  # decoded length; stored length for raw sections
    dest: tuple[int, int]
    identical: bool
    blocks: tuple[Block, ...]  # over the shared prefix, unshifted


def content(section) -> tuple[bytes, bool]:
    """Decoded content, and whether the section is stored raw."""
    unpacked = section.unpack()
    return (section.stored, True) if unpacked is None else (unpacked, False)


def sections(a: Firmware, b: Firmware) -> list[SectionDiff]:
    """Every section id present in either image, in `a`'s order then `b`'s."""
    ids = [s.id for s in a.container.sections]
    ids += [s.id for s in b.container.sections if s.id not in ids]
    return [_section(a.container.find(i), b.container.find(i), i) for i in ids]


def _section(sa, sb, section_id: int) -> SectionDiff:
    if sa is None or sb is None:
        one = sa or sb
        data, raw = content(one)
        return SectionDiff(
            id=section_id,
            present=(sa is not None, sb is not None),
            raw=(raw, raw),
            length=(len(data) if sa else 0, len(data) if sb else 0),
            dest=(sa.dest if sa else 0, sb.dest if sb else 0),
            identical=False,
            blocks=(),
        )
    ca, ra = content(sa)
    cb, rb = content(sb)
    shared = min(len(ca), len(cb))
    blocks = clusters(ca[:shared], cb[:shared])
    return SectionDiff(
        id=section_id,
        present=(True, True),
        raw=(ra, rb),
        length=(len(ca), len(cb)),
        dest=(sa.dest, sb.dest),
        identical=ca == cb,
        blocks=tuple(blocks),
    )


def clusters(a: bytes, b: bytes, gap: int = CLUSTER_GAP) -> list[Block]:
    """Differing bytes between equal-length `a` and `b`, grouped into blocks."""
    out: list[Block] = []
    start = last = None
    count = 0
    for i, (x, y) in enumerate(zip(a, b)):
        if x == y:
            continue
        if start is not None and i - last > gap:
            out.append(Block(start, last + 1, count))
            start = None
        if start is None:
            start, count = i, 0
        last = i
        count += 1
    if start is not None:
        out.append(Block(start, last + 1, count))
    return out


def text(data: bytes) -> set[str]:
    """NUL-terminated strings that read as text rather than as code bytes.

    Code is full of short printable runs, and after a relink every one whose
    bytes include an address changes, so a naive string diff is all noise. A
    string is kept only if it contains a word: three or more letters, cased the
    way people case words (UPPER, lower or Capitalised), with a vowel, and no
    more than a quarter of it punctuation. That keeps "OUTBOX 8 CONNECTED" and
    "Out %s Volume=%s" and drops "DHMx%I". It is a filter, not a parser: the
    odd code fragment still gets through, and reads as one.
    """
    out = set()
    for match in _TEXT.finditer(data):
        s = match.group().decode("ascii")
        symbols = sum(not (c.isalnum() or c == " ") for c in s)
        if symbols > 0.25 * len(s):
            continue
        if any(_is_word(w) for w in re.findall(r"[A-Za-z]{3,}", s)):
            out.add(s)
    return out


def _is_word(w: str) -> bool:
    cased = w.isupper() or w.islower() or (w[0].isupper() and w[1:].islower())
    return cased and bool(re.search(r"[aeiouyAEIOUY]", w))
