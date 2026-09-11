"""What a curated symbol is: a name we assigned to an address by analysis.

The firmware carries hundreds of names for free -- GCC left RTTI and mangled
symbols in it (`image.symbols`). Those are derived automatically and never
written down. This module is for the other kind: a function or datum a person
named after reading it, which no amount of scanning would recover -- the receive
handler, the parameter table, the service dispatcher.

The shape follows `patch.spec.Patch` on purpose. A curated symbol names the
**build and version** it was found in, and carries a guard -- the SHA-256 of a
few bytes at its address -- so a symbol pointed at the wrong image, or at an
address that moved between OS releases, is caught rather than silently
mislabelling code. That guard is what lets a map be re-checked against a new
image instead of trusted blind.

**The guard is a hash, not the bytes.** This repository holds no Elektron code,
not even a handful of bytes of it, so a symbol commits `guard` (a digest) and
`guard_len` (how many bytes it covers), and the check recomputes the digest from
the firmware the user supplies. Same idea as the patch model's `STOCK_SHA256`.

Addresses are **run addresses**, the ones a disassembler shows, so `base` is the
address the section is loaded/run at -- which is not always its ELE3 `dest`. The
bootstrap is the case that matters: its section table says `0x02000000`, but it
runs at `0x800003fc` (`docs/bootstrap.md`), and the names were read there.
"""

import hashlib
from dataclasses import dataclass, field

KINDS = ("function", "label", "data")
GUARD_LEN = 16  # bytes at the address the guard digest covers

# Run base per section, where it differs from the ELE3 dest or is worth naming.
MAIN_OS_BASE = 0x40000400
BOOTSTRAP_BASE = 0x800003FC


class SymbolError(ValueError):
    """A symbol record is malformed, or does not match its image."""


@dataclass(frozen=True)
class Symbol:
    """One name assigned to one address in one firmware build."""

    id: str
    name: str
    kind: str  # one of KINDS
    build: str  # container build/model string, e.g. "40050"
    version: str  # container version string, e.g. "1.10E"
    section: int  # ELE3 section id: 2 bootstrap, 3 MAIN OS
    base: int  # run base of the section
    address: int  # run address of the symbol
    guard: str  # SHA-256 hex of `guard_len` bytes at the address
    note: str = field(default="")
    guard_len: int = GUARD_LEN

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise SymbolError(f"{self.id}: kind {self.kind!r} is not one of {KINDS}")
        if len(self.guard) != 64 or not all(c in "0123456789abcdef" for c in self.guard):
            raise SymbolError(f"{self.id}: guard must be a 64-hex-character SHA-256")
        if self.address < self.base:
            raise SymbolError(
                f"{self.id}: address 0x{self.address:08x} is below the section base "
                f"0x{self.base:08x}"
            )

    @property
    def offset(self) -> int:
        """Byte offset into the decoded section content."""
        return self.address - self.base

    def matches(self, content: bytes) -> bool:
        """Whether the bytes at this address in `content` hash to the guard."""
        window = content[self.offset : self.offset + self.guard_len]
        if len(window) != self.guard_len:
            return False
        return hashlib.sha256(window).hexdigest() == self.guard


def validate(symbols: list[Symbol]) -> None:
    """Reject duplicate ids, and two names on one (section, address)."""
    by_id: dict[str, Symbol] = {}
    by_place: dict[tuple[int, int], Symbol] = {}
    for symbol in symbols:
        if symbol.id in by_id:
            raise SymbolError(f"duplicate symbol id {symbol.id!r}")
        by_id[symbol.id] = symbol
        place = (symbol.section, symbol.address)
        if place in by_place and by_place[place].name != symbol.name:
            raise SymbolError(
                f"{symbol.id}: 0x{symbol.address:08x} in section {symbol.section} is already "
                f"named {by_place[place].name!r} by {by_place[place].id!r}"
            )
        by_place[place] = symbol
