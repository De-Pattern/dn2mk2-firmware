"""Firmware mods: what one is, and how two of them are known not to collide.

A **mod** is a named, reversible change to one or more sections of a firmware
image, expressed as bytes written at declared offsets. It is deliberately a
smaller idea than `dnfw.patch`, which models a single same-length edit with
`expect` guards: a mod may rewrite hundreds of kilobytes (a sample bank), and
carries its own notion of what the user supplies.

## Why extents are declared rather than discovered

The point of this package is that a user can eventually apply **several** mods
to one image. Two mods are safe together when the bytes they write do not
overlap, so every mod must be able to say what it will touch *before* it
touches it. `extents()` is that promise, and `check_compatible()` is what turns
a set of mods into a yes or no.

This is not a guarantee of musical or behavioural compatibility -- two mods can
write disjoint bytes and still fight over the same feature. It is the weakest
useful guarantee, and it is checkable, which is why it is the one enforced.

## What a mod must not do

**Change any section's length.** Every address after a resized section moves,
and nothing in this repository fixes up the code that refers to them
(`dnfw.patch.spec` says the same about patches). A mod that needs more room is
a code-cave or new-section problem — `docs/ideas-backlog.md` §1a and §6.

**Touch the "Multiplier" key material** (`docs/ele3-format.md` §5).

Integrity is not a mod's business: `dnfw build` recomputes the section byte-sum,
the content checksum and the HMAC-SHA256 trailer, and re-verifies the result
before writing. A mod produces section payloads; the build path makes them into
a firmware the device accepts.
"""

from dataclasses import dataclass


class ModError(ValueError):
    """A mod cannot apply to this image, or its inputs are wrong."""


@dataclass(frozen=True)
class Extent:
    """A byte range a mod writes, inside one section's *unpacked* payload."""

    section: int
    start: int
    length: int
    what: str = ""

    @property
    def end(self) -> int:
        return self.start + self.length

    def overlaps(self, other: "Extent") -> bool:
        return (self.section == other.section
                and self.start < other.end and other.start < self.end)

    def __str__(self) -> str:
        return (f"section {self.section} "
                f"[0x{self.start:08x}..0x{self.end:08x}) "
                f"{self.length:,} B{' — ' + self.what if self.what else ''}")


@dataclass(frozen=True)
class Result:
    """What a mod produced: replacement payloads, and what it wrote."""

    payloads: dict[int, bytes]        # section id -> whole new payload
    extents: list[Extent]
    notes: list[str]


def check_compatible(named_extents) -> list[str]:
    """-> a list of conflict descriptions; empty means the set is compatible.

    `named_extents` is [(mod_id, [Extent, ...]), ...]. Every pair is compared,
    because "A is fine with B" and "B is fine with C" says nothing about A and
    C. The comparison is byte-range overlap only -- see the module docstring
    for what that does and does not promise.
    """
    conflicts = []
    items = list(named_extents)
    for i, (a_id, a_ext) in enumerate(items):
        for b_id, b_ext in items[i + 1:]:
            for a in a_ext:
                for b in b_ext:
                    if a.overlaps(b):
                        lo = max(a.start, b.start)
                        hi = min(a.end, b.end)
                        conflicts.append(
                            f"{a_id} and {b_id} both write section {a.section} "
                            f"0x{lo:08x}..0x{hi:08x} ({hi - lo:,} bytes)")
    return conflicts
