"""The ELE3 container: a header, a section table, and the sections themselves.

Field offsets ported from `format.h` in mischa85/elektron-firmware-tool, MIT.
All fields are big-endian.

    0x00  magic "ELE3"
    0x07  build/model string
    0x13  version string
    0x1C  u32 section count
    0x20  section table, 16 bytes per entry: id, offset, stored length, dest

Sections are laid out on 16-byte boundaries, in ascending offset order, after
the header and table. Everything past the last section belongs to the trailer,
which is `integrity.digest`'s business, not this module's.
"""

from dataclasses import dataclass

from .section import Section

MAGIC = b"ELE3"
BUILD_OFFSET = 0x07
VERSION_OFFSET = 0x13
COUNT_OFFSET = 0x1C
TABLE_OFFSET = 0x20
ENTRY_SIZE = 16
MAX_SECTIONS = 64
ALIGN = 16

# Labels, not ground truth: Elektron document none of these. Id 2 was "DSP"
# until its content was read -- it is ColdFire code carrying the Early Start-up
# Menu's own strings ("READY TO RECEIVE", "RECEIVING...", "LENGTH ERROR",
# "CRC CHECK", "STARTUP MENU") and the HMAC key string. It is the recovery
# receiver. Upstream elektron-firmware-tool renamed it "bootstrap" on
# 2026-09-08 from the same evidence; the name follows theirs.
NAMES = {
    1: "FPGA",
    2: "bootstrap",
    3: "MAIN OS",
    4: "updater",
    5: "meta",
    6: "boot",
    7: "blob",
}


def name(section_id: int) -> str:
    return NAMES.get(section_id, "?")


@dataclass(frozen=True)
class Container:
    """A parsed ELE3 container.

    `head` is every byte before the first section -- magic, strings, count and
    table -- kept verbatim so a rebuild reproduces the parts we do not touch
    and only rewrites the table entries it must.
    """

    head: bytes
    first_offset: int
    sections: tuple[Section, ...]
    offsets: tuple[int, ...]  # original container offset of each section
    declared_size: int

    @property
    def build(self) -> str:
        return _text(self.head, BUILD_OFFSET, VERSION_OFFSET)

    @property
    def version(self) -> str:
        return _text(self.head, VERSION_OFFSET, COUNT_OFFSET)

    def find(self, section_id: int) -> Section | None:
        for section in self.sections:
            if section.id == section_id:
                return section
        return None


def parse(data: bytes, declared_size: int) -> Container:
    """Parse a container. `data` starts at the ELE3 magic; `declared_size` is
    the length from the transport preamble."""
    if data[:4] != MAGIC:
        raise ValueError("not an ELE3 container")
    count = int.from_bytes(data[COUNT_OFFSET : COUNT_OFFSET + 4], "big")
    if not 0 < count <= MAX_SECTIONS:
        raise ValueError(f"implausible section count {count}")

    sections, offsets = [], []
    for i in range(count):
        entry = data[TABLE_OFFSET + i * ENTRY_SIZE : TABLE_OFFSET + (i + 1) * ENTRY_SIZE]
        sid, offset, length, dest = (
            int.from_bytes(entry[k : k + 4], "big") for k in (0, 4, 8, 12)
        )
        sections.append(Section(id=sid, dest=dest, stored=data[offset : offset + length]))
        offsets.append(offset)

    first = min(offsets)
    return Container(
        head=data[:first],
        first_offset=first,
        sections=tuple(sections),
        offsets=tuple(offsets),
        declared_size=declared_size,
    )


def assemble(container: Container, replacements: dict[int, Section]) -> bytes:
    """Lay the container out again, returning the bytes up to the end of the
    last section. The caller adds the trailer.

    Sections keep their original relative order; each starts on a 16-byte
    boundary; the table is rewritten with the new offsets and lengths.
    """
    head = bytearray(container.head)
    body = bytearray(head)
    position = container.first_offset

    for index in sorted(range(len(container.sections)), key=lambda i: container.offsets[i]):
        section = container.sections[index]
        section = replacements.get(section.id, section)

        aligned = (position + ALIGN - 1) & ~(ALIGN - 1)
        body.extend(bytes(aligned - len(body)))
        position = aligned

        body.extend(section.stored)
        entry = TABLE_OFFSET + index * ENTRY_SIZE
        body[entry + 4 : entry + 8] = position.to_bytes(4, "big")
        body[entry + 8 : entry + 12] = len(section.stored).to_bytes(4, "big")
        position += len(section.stored)

    return bytes(body)


def _text(head: bytes, start: int, end: int) -> str:
    """Read one of the header's fixed-width strings.

    They are space- and NUL-padded and sometimes carry a leading non-printable
    byte, so leading junk is skipped and the run of printable characters is
    taken -- the same shape as `header_fields` in the C tool.
    """
    field = head[start:end]
    i = 0
    while i < len(field) and not (field[i : i + 1].isalnum() or field[i : i + 1] == b"."):
        i += 1
    out = []
    while i < len(field) and (field[i : i + 1].isalnum() or field[i : i + 1] == b"."):
        out.append(field[i])
        i += 1
    return bytes(out).decode("ascii", "replace")
