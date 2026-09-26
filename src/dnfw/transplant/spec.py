"""What a transplant is made of: guarded images, spans, relocation sites.

A transplant moves code (and the tables it reads) from a **donor** firmware
the user supplies into a **recipient** firmware the user supplies, at apply
time. The repository holds only the description below -- addresses, sizes,
SHA-256 digests, the value each relocation site must hold, and where each
span lands -- never the donor's bytes (`docs/dt2-machine-port.md`, "Which
bytes are whose").
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Guard:
    """The one image a spec was measured on. Anything else is refused."""

    device: str
    product: int            # the ELE3 container's product code
    version: str            # the container's version string
    section7_sha256: str    # of the unpacked section 7 (the SHARC boot stream)


@dataclass(frozen=True)
class Span:
    """A contiguous run of donor memory that moves as one piece.

    Code spans are counted in 16-bit parcels at short-word addresses; data
    spans in bytes at DM byte addresses. `window` says how the donor's boot
    stream loads a code span (`sharc.code_address`); the recipient always
    receives it through the short-word alias.
    """

    name: str
    kind: str               # "code" | "data"
    donor: int              # donor sw (code) or DM byte address (data)
    size: int               # parcels (code) or bytes (data)
    sha256: str             # of the donor bytes, as loaded
    recipient: int          # recipient sw (code) or DM byte address (data)
    what: str
    window: str = "l1"

    @property
    def nbytes(self) -> int:
        return 2 * self.size if self.kind == "code" else self.size

    def contains(self, address: int) -> bool:
        return self.donor <= address < self.donor + self.size

    def moved(self, address: int) -> int:
        """Where a donor address inside this span lands in the recipient."""
        if not self.contains(address):
            raise ValueError(f"{address:#x} is not inside span {self.name}")
        return self.recipient + (address - self.donor)


@dataclass(frozen=True)
class Site:
    """One absolute (or span-crossing relative) reference inside a moved span."""

    span: str               # the span the instruction is in
    sw: int                 # the instruction's donor short-word address
    form: str               # digikit's decoder name for it (for the record)
    field: str              # `sharc.FIELDS` key
    donor_target: int       # the address it holds in the donor
    refers_to: str          # the span that address is inside
    what: str


@dataclass(frozen=True)
class Reserved:
    """Recipient RAM the adapter uses and the boot stream must not load."""

    name: str
    dm: int
    size: int
    fill: bool = False      # True: a zero-fill block at boot (the loader clears it)


@dataclass(frozen=True)
class Spec:
    name: str
    donor: Guard
    recipient: Guard
    spans: tuple[Span, ...]
    sites: tuple[Site, ...]
    entry: str              # the span whose first parcel is the routine's entry
    notes: tuple[str, ...] = field(default=())

    def span(self, name: str) -> Span:
        for s in self.spans:
            if s.name == name:
                return s
        raise KeyError(name)
