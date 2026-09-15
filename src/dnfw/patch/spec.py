"""What a patch record is, and what makes one valid.

The shape is adapted from `PATCHES` / `patchlib.py` in bryantysinger/octa-bt-pt
(MIT), which patches the same CPU family: declarative records carrying the
bytes they expect to find, so a patch refuses to apply to firmware it was not
written against.

Two deliberate differences. That project guards on a single `STOCK_SHA256` of
the whole image; here a patch names the **device, build and version** it
targets as well, so a patch that does not apply says which of those disagreed
instead of only that a hash did not match. And every patch carries `expect` --
the bytes it is replacing -- which is checked at the target before anything is
written. A hash guard alone cannot catch a patch pointed at the wrong offset
inside the right image.

Only same-length replacement is supported. Anything that changes a section's
length moves every address after it, and nothing here can fix up the code that
refers to them. Growing the firmware is a code-cave problem, which is Phase 2.
"""

from dataclasses import dataclass, field


class PatchError(ValueError):
    """A patch record is malformed, or does not apply to this image."""


@dataclass(frozen=True)
class Patch:
    """One same-length edit to one section of one firmware build.

    Exactly one of `address` or `find` locates the target:

    `address` is a virtual address, resolved against the section's load
    destination -- the natural way to name something found in a disassembler.

    `find` is a byte string that must occur exactly once in the section -- the
    natural way to name a string constant, and stable across rebuilds in a way
    an offset is not.
    """

    id: str
    group: str
    description: str
    device: int  # SysEx product id: 0x0d Digitone, 0x15 Digitone II
    build: str  # container build/model string, e.g. "0050"
    version: str  # container version string, e.g. "1.10E"
    section: int  # ELE3 section id, e.g. 3 for MAIN OS
    expect: bytes  # the bytes being replaced, checked before writing
    replace: bytes  # the bytes to write, same length as `expect`
    address: int | None = None
    find: bytes | None = None
    notes: str = field(default="")

    def __post_init__(self) -> None:
        if (self.address is None) == (self.find is None):
            raise PatchError(f"{self.id}: give exactly one of address or find")
        if len(self.expect) != len(self.replace):
            raise PatchError(
                f"{self.id}: replacement is {len(self.replace)} bytes but expect is "
                f"{len(self.expect)}; only same-length patches are supported"
            )
        if not self.expect:
            raise PatchError(f"{self.id}: expect is empty")
        if self.find is not None and self.find != self.expect:
            raise PatchError(f"{self.id}: when locating by find, expect must be the same bytes")

    @property
    def target(self) -> str:
        return f"0x{self.address:08x}" if self.address is not None else repr(self.find)


def validate(patches: list[Patch]) -> None:
    """Reject duplicate ids across the whole discovered set."""
    seen: dict[str, Patch] = {}
    for patch in patches:
        if patch.id in seen:
            raise PatchError(f"duplicate patch id {patch.id!r}")
        seen[patch.id] = patch
