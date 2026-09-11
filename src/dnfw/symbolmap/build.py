"""Merging curated symbols with the image's own RTTI, checked against a section.

One subject: producing the name set for a section of a given image. Rendering
it, and emitting a Ghidra script, are other modules' jobs.

The check is the point. A curated symbol carries `expect`, the bytes at its
address; here that is compared against what the section actually holds, and a
mismatch is reported rather than applied. That is how a map written for one OS
build is safely re-pointed at another: the names that still match are kept, the
ones that drifted are flagged for a human, and nothing is mislabelled silently.
"""

from dataclasses import dataclass

from ..container import ele3
from ..firmware.model import Firmware
from ..image import symbols as rtti
from ..image.coldfire import LoadedImage
from .record import Symbol


@dataclass(frozen=True)
class Placed:
    """A curated symbol resolved against an image: does its guard still hold?

    No firmware bytes are kept -- only whether the guard digest matched -- so a
    report of this is safe to print and to commit."""

    symbol: Symbol
    ok: bool


@dataclass(frozen=True)
class Names:
    """Everything to label in one section."""

    section: int
    base: int
    curated: tuple[Placed, ...]
    derived: tuple[rtti.Symbol, ...]  # RTTI type names and mangled symbols

    @property
    def curated_ok(self) -> tuple[Placed, ...]:
        return tuple(p for p in self.curated if p.ok)

    @property
    def drift(self) -> tuple[Placed, ...]:
        return tuple(p for p in self.curated if not p.ok)


def merge(firmware: Firmware, curated: list[Symbol], section_id: int) -> Names:
    """Resolve `curated` against `firmware`'s section and add its RTTI names.

    Only curated symbols whose build and version match the image are considered
    -- a name found in 1.10E is not asserted about 1.11, whose addresses moved.
    """
    section = firmware.container.find(section_id)
    if section is None:
        raise ValueError(f"image has no section id={section_id}")
    content = section.unpack()
    if content is None:
        raise ValueError(f"section id={section_id} is stored raw, not code")

    build, version = firmware.container.build, firmware.container.version
    base = _base(curated, section_id, section.dest)

    placed = []
    for symbol in curated:
        if symbol.section != section_id or symbol.build != build or symbol.version != version:
            continue
        placed.append(Placed(symbol=symbol, ok=symbol.matches(content)))

    # RTTI addresses are computed relative to the image's base, so load at the
    # run base the curated symbols use -- for MAIN OS that is the dest and
    # nothing changes; for the bootstrap it keeps every address in one space.
    derived = rtti.find(LoadedImage(dest=base, content=content))
    return Names(section=section_id, base=base, curated=tuple(placed), derived=tuple(derived))


def _base(curated: list[Symbol], section_id: int, dest: int) -> int:
    """The run base for the section: the curated symbols' base if they agree,
    else the ELE3 dest. RTTI addresses are relative to `dest`, so a section with
    no curated symbols is labelled at its dest, which is correct for MAIN OS."""
    bases = {s.base for s in curated if s.section == section_id}
    if len(bases) > 1:
        raise ValueError(f"section {section_id}: curated symbols disagree on the run base {bases}")
    return bases.pop() if bases else dest


def name(section_id: int) -> str:
    return ele3.name(section_id)
