"""Finding and walking parameter tables in a loaded section.

A table is a run of records at a fixed stride. It is located by shape rather
than by address, because an address found once is a fact about one firmware
version and a shape is a fact about the format.

**Pointer arrays have to be excluded, and they are the whole difficulty.** An
ordinary array of string pointers satisfies "three plausible string pointers at
the end of a record" at *every* 4-byte offset, so it reports as a table
starting almost anywhere. A genuine record table satisfies it at one offset
only. `find` uses exactly that to tell them apart, which is why searching a
3 MB image returns two tables and not eighty.
"""

from dataclasses import dataclass

from ..image.coldfire import LoadedImage
from .record import NAMES_FROM_END, WORD, Record, size

MIN_RECORDS = 8
PRINTABLE = range(0x20, 0x7F)
MAX_NAME = 64


@dataclass(frozen=True)
class Table:
    """A run of parameter records."""

    address: int
    word_count: int
    records: tuple[Record, ...]

    @property
    def stride(self) -> int:
        return size(self.word_count)

    @property
    def end(self) -> int:
        return self.address + self.stride * len(self.records)

    def pages(self) -> list[str]:
        """Page labels in table order, consecutive duplicates collapsed."""
        out: list[str] = []
        for record in self.records:
            if record.page and (not out or out[-1] != record.page):
                out.append(record.page)
        return out


def string_at(image: LoadedImage, address: int) -> str | None:
    """A NUL-terminated printable string, or None if these bytes are not one.

    The empty string is a valid answer: several records carry an empty page
    label, and rejecting those was what made an earlier walk stop 74 records
    short of the true start of the DN2 table.
    """
    if not image.contains(address, 1):
        return None
    start = image.offset_of(address)
    end = image.content.find(b"\x00", start, start + MAX_NAME)
    if end < 0:
        return None
    text = image.content[start:end]
    if any(byte not in PRINTABLE for byte in text):
        return None
    return text.decode("ascii")


def read(image: LoadedImage, address: int, word_count: int) -> Record | None:
    """Decode one record, or None if these bytes are not shaped like one."""
    stride = size(word_count)
    if not image.contains(address, stride):
        return None
    raw = image.read(address, stride)
    words = tuple(
        int.from_bytes(raw[i * WORD : (i + 1) * WORD], "big") for i in range(word_count)
    )
    if not image.contains(words[0], 1):  # the handler pointer
        return None
    names = [string_at(image, word) for word in words[-NAMES_FROM_END:]]
    if any(name is None for name in names):
        return None
    return Record(
        address=address,
        words=words,
        long_name=names[0],
        page=names[1],
        short_name=names[2],
    )


def walk(image: LoadedImage, address: int, word_count: int) -> Table:
    """Read records from `address` until the shape stops holding."""
    records = []
    stride = size(word_count)
    while (record := read(image, address, word_count)) is not None:
        records.append(record)
        address += stride
    start = records[0].address if records else address
    return Table(address=start, word_count=word_count, records=tuple(records))


def containing(image: LoadedImage, address: int, word_count: int) -> Table:
    """The whole table that `address` sits in, walking both ways from it.

    Use this with a record you already trust — a known LFO block, say — rather
    than searching, when you want the full extent around a known point.
    """
    stride = size(word_count)
    start = address
    while read(image, start - stride, word_count) is not None:
        start -= stride
    return walk(image, start, word_count)


def find(image: LoadedImage, word_count: int, minimum: int = MIN_RECORDS) -> list[Table]:
    """Every table of at least `minimum` records, artefacts excluded.

    Two kinds of false positive have to go, and they are different problems:

    - **Pointer arrays**, excluded by the test in this module's docstring: if a
      run of comparable length also starts 4 bytes later, these are pointers.
    - **Misaligned sub-runs of a real table.** Reading a record's short-name
      pointer as the next record's long-name pointer also satisfies the shape,
      so a genuine table reports again at several offsets inside itself. Those
      are dropped by containment: a run lying wholly inside a longer one is an
      artefact of the longer one.
    """
    stride = size(word_count)
    seen: set[int] = set()
    candidates: list[Table] = []

    for offset in range(0, len(image.content) - stride, WORD):
        address = image.address_of(offset)
        if address in seen or read(image, address, word_count) is None:
            continue
        table = walk(image, address, word_count)
        seen.update(record.address for record in table.records)
        if len(table.records) < minimum:
            continue
        shifted = walk(image, address + WORD, word_count)
        if len(shifted.records) >= len(table.records) // 2:
            continue  # a pointer array: it matches at every offset
        candidates.append(table)

    ordered = sorted(candidates, key=lambda t: -len(t.records))
    kept: list[Table] = []
    for table in ordered:
        if any(k.address <= table.address and table.end <= k.end for k in kept):
            continue
        kept.append(table)
    return kept
