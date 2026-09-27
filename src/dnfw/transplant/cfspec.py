"""What a ColdFire transplant is made of: records, formatters, strings, a page.

The SHARC half (`spec`) moves code. The ColdFire half of a machine port moves
almost none: the Digitakt II and the Digitone II share one UI framework (884 of
their C++ classes have identical names, bases and vtable sizes;
`docs/dt2-machine-port.md`, "The ColdFire half"), so the pieces a machine's page
is built from are either **data** (parameter records, name strings, the page's
knob list) or **code the recipient already has** (every value formatter ONESHOT
uses has a twin in DN2 1.11). This module describes those pieces by address,
size and digest; `cfplan` checks them against the two images the user supplies
and composes the recipient's copies in memory.

**Nothing here is a donor byte.** Strings are named by donor address and
length; records by address and SHA-256; formatter twins by both addresses and a
masked comparison made at apply time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The 60-byte parameter record, both images (`docs/modulation-mask.md` has the
# fields; the record starts 8 bytes after where `dnfw.params` counts it from,
# which is why `dnfw params` shows each record's formatter one row early).
RECORD = 60
PAGE, SLOT, MINIMUM, MAXIMUM, DEFAULT, BIPOLAR = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14
CC, NRPN, ORDINAL, MASK = 0x18, 0x1C, 0x20, 0x24
LONG_NAME, PAGE_LABEL, SHORT_NAME, FORMATTER, SUFFIX = 0x28, 0x2C, 0x30, 0x34, 0x38
POINTERS = (LONG_NAME, PAGE_LABEL, SHORT_NAME, FORMATTER, SUFFIX)
UNSET = 0xFFFFFFFF


@dataclass(frozen=True)
class ImageGuard:
    """One MAIN OS a spec was measured on. Anything else is refused."""

    device: str
    product: int
    version: str
    section3_sha256: str    # of the unpacked MAIN OS


@dataclass(frozen=True)
class RecordRun:
    """Consecutive donor parameter records that move together."""

    name: str
    donor: int              # the first record's address (its page-id word)
    count: int
    sha256: str             # of count * RECORD donor bytes
    donor_entry: int        # the first record's entry number (index + 1) in the donor
    shorts_sha256: str      # of the donor's short names, NUL-joined: a second check
    labels: tuple[str, ...] # our names for the records (the manual's), for reports


@dataclass(frozen=True)
class FormatterTwin:
    """A donor value formatter and the recipient function that does the same.

    `length` bytes from each address must be equal once the operands at
    `operands` are set aside; each of those is checked on its own terms: a
    string operand must name the same text in both images, a branch must land on
    another twin, and a call must land on the same address in both.
    """

    name: str
    donor: int
    recipient: int
    length: int
    operands: tuple[tuple[int, str], ...] = ()   # (offset, 'str32' | 'code32' | 'rel16')


@dataclass(frozen=True)
class Fixed:
    """A pointer both images hold, with no copy needed (the empty suffix string)."""

    name: str
    donor: int
    recipient: int
    text: str


@dataclass(frozen=True)
class PageFact:
    """A page descriptor as the donor's static initializer builds it.

    The descriptor lives in BSS and exists only at run time; its content is the
    immediates of an unrolled initializer, so the spec records the initializer's
    span and digest (the guard) and the values it writes (the facts).
    """

    name: str
    init_start: int
    init_length: int
    sha256: str
    title: int              # donor string address, descriptor +0
    subtitle: int           # donor string address, descriptor +4
    names_sha256: str       # of the two strings, NUL-joined
    entries: tuple[int, ...]  # the eight knob entries, donor entry numbers (0 = none)
    tag: int


@dataclass(frozen=True)
class NameRow:
    """The donor's machine name row (long, short), for MACHINE SEL."""

    donor_row: int
    names_sha256: str       # of the long and short name, NUL-joined


@dataclass(frozen=True)
class CfSpec:
    name: str
    donor: ImageGuard
    recipient_version: str
    records: RecordRun
    formatters: tuple[FormatterTwin, ...]
    record_formatters: tuple[str, ...]      # per record: the FormatterTwin.name it uses
    fixed: tuple[Fixed, ...]
    page: PageFact
    machine_name: NameRow
    notes: tuple[str, ...] = field(default=())

    def formatter(self, name: str) -> FormatterTwin:
        for f in self.formatters:
            if f.name == name:
                return f
        raise KeyError(name)
