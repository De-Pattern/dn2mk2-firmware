"""A small sample bank baked into section 7, behind a directory (our own format).

The shape is Waverider Milestone 4's wavetable directory, for samples:

    DM BANK_DM   +0  magic 'OSB1' (0x3142534f)
                 +4  count
                 +8  entry[0]: pointer (DM byte address), length (samples), rate (Hz)
                 +20 entry[1] ...
    then the samples, int16 little-endian, each entry's pointer 4-byte aligned

The adapter resolves a voice's SAMP through it and never trusts a slot at or
past the count (it plays slot 0). Without the magic it renders nothing.
"""

from __future__ import annotations

import struct

MAGIC = 0x3142534F          # b'OSB1' as a little-endian word
HEADER = 8
ENTRY = 12


def build(base: int, samples: list[list[int]], rate: int = 48000, limit: int | None = None
          ) -> tuple[bytes, list[dict]]:
    """-> (the bank's bytes, to load at DM BASE; one dict per entry)."""
    at = base + HEADER + ENTRY * len(samples)
    at = (at + 3) & ~3
    entries, body = [], b""
    for pcm in samples:
        entries.append({"pointer": at, "length": len(pcm), "rate": rate})
        chunk = struct.pack(f"<{len(pcm)}h", *pcm)
        chunk += b"\0" * (-len(chunk) % 4)
        body += chunk
        at += len(chunk)
    head = struct.pack("<II", MAGIC, len(samples))
    for e in entries:
        head += struct.pack("<III", e["pointer"], e["length"], e["rate"])
    head += b"\0" * ((entries[0]["pointer"] - base) - len(head) if entries else 0)
    data = head + body
    if limit is not None and len(data) > limit:
        raise ValueError(f"the bank is {len(data):,} bytes; the span holds {limit:,}")
    return data, entries
