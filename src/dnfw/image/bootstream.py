"""Parse an Analog Devices boot stream (`.ldr`) into its blocks.

Section 7 of a Digitone II update — the one `elektron-firmware-tool` calls
`blob` — is the SHARC program in this format, which is why a scan for a raw
48-bit instruction stream found nothing there for months (`docs/sharc-image.md`).

A boot stream is a chain of 16-byte headers, each followed by its payload:

    0  block code      top byte 0xAD, the header signature
    1  target address  where the payload is loaded
    2  byte count      payload length
    3  argument

**The signature alone is not evidence.** `0xAD` appears 1,833 times in this
section by chance. What identifies the format is that the chain *walks*: step
over the payload the header's own count declares and the next header is there,
and its target address continues the previous block's. `walk()` reports both, so
a caller can judge a stream rather than trust a magic byte.

This parses the container. It does not decode SHARC instructions, and nothing in
this package does.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SIGNATURE = 0xAD
HEADER = 16

# Flags live in bits 8..15 of the block code. These values were derived by
# walking -- the only assignment under which the chain consumes section 7
# exactly, 95 blocks over all 836,956 bytes with nothing left over -- and they
# then turn out to match ADI's documented boot-stream flags, which is the
# corroboration rather than the source.
FLAG_FILL = 0x01      # BFLAG_FILL:   zero the target range; no payload in the stream
FLAG_IGNORE = 0x08    # BFLAG_IGNORE: skip the payload
FLAG_INDIRECT = 0x10  # BFLAG_INDIRECT
FLAG_FIRST = 0x40     # BFLAG_FIRST:  first block of a stream
FLAG_FINAL = 0x80     # BFLAG_FINAL:  last block; `target` is the entry point

FLAG_NAMES = (
    (FLAG_FILL, "fill"),
    (FLAG_IGNORE, "ignore"),
    (FLAG_INDIRECT, "indirect"),
    (FLAG_FIRST, "first"),
    (FLAG_FINAL, "final"),
)


@dataclass(frozen=True)
class Block:
    """One boot-stream block header, and where it sat in the stream."""

    offset: int
    code: int
    target: int
    count: int
    argument: int

    @property
    def flags(self) -> int:
        return (self.code >> 8) & 0xFF

    @property
    def flag_names(self) -> tuple[str, ...]:
        return tuple(name for bit, name in FLAG_NAMES if self.flags & bit)

    @property
    def has_payload(self) -> bool:
        """Whether `count` bytes follow the header in the stream.

        A fill block declares a target range to zero and carries nothing, so it
        advances the load address without advancing the file -- which is exactly
        why a walk that ignores the distinction desynchronises immediately.
        """
        return not (self.flags & (FLAG_FILL | FLAG_IGNORE)) and self.count > 0

    @property
    def payload_at(self) -> int:
        return self.offset + HEADER

    @property
    def end(self) -> int:
        """Offset of the next header, if this block is well formed."""
        return self.offset + HEADER + (self.count if self.has_payload else 0)


@dataclass(frozen=True)
class Walk:
    """The result of walking a stream: the blocks, and how well they agreed."""

    blocks: tuple[Block, ...]
    stopped_at: int
    reason: str
    data_len: int = 0

    @property
    def transitions(self) -> int:
        """How many block-to-block target comparisons were possible."""
        return max(len([b for b in self.blocks if b.count]) - 1, 0)

    @property
    def contiguous(self) -> int:
        """How many of those had `target == previous target + previous count`.

        This is the number that matters. Chance produces a signature byte; it
        does not produce consecutive load addresses that each continue the last.
        """
        agreed, previous = 0, None
        for block in self.blocks:
            if not block.count:
                continue
            if previous is not None and block.target == previous:
                agreed += 1
            previous = block.target + block.count
        return agreed

    @property
    def complete(self) -> bool:
        """The walk consumed the whole stream and ended on a final block.

        This is the strongest single signal there is. A wrong rule for which
        blocks carry payload desynchronises and either runs off the end or stops
        early; landing *exactly* on the last byte, on a block flagged final,
        after 95 steps, does not happen by accident.
        """
        return bool(self.blocks) and self.data_len > 0 \
            and self.stopped_at == self.data_len and self.final is not None

    @property
    def convincing(self) -> bool:
        """Whether to believe this is a boot stream rather than coincidence.

        Either the walk accounts for the entire section, or every target
        continues the last. **Perfect contiguity alone is the wrong test for a
        whole image**: a real one loads several memories -- section 7 fills L1,
        L2 and DDR -- so it jumps between regions by design, 16 times here. It
        was this rule, not the data, that called the true 95-block walk
        unconvincing while blessing six-block fragments of it.
        """
        if len(self.blocks) < 3 or self.transitions <= 0:
            return False
        return self.complete or self.contiguous == self.transitions

    @property
    def payload_bytes(self) -> int:
        return sum(b.count for b in self.blocks if b.has_payload)

    @property
    def final(self) -> Block | None:
        """The block marked final, if the walk reached one."""
        for block in self.blocks:
            if block.flags & FLAG_FINAL:
                return block
        return None

    @property
    def entry_point(self) -> int | None:
        """The final block's target -- where the loaded program starts."""
        final = self.final
        return None if final is None else final.target

    def regions(self) -> list[tuple[int, int]]:
        """Contiguous load spans, merged -- which memories the image fills."""
        spans = sorted((b.target, b.target + b.count) for b in self.blocks if b.count)
        merged: list[tuple[int, int]] = []
        for lo, hi in spans:
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        return merged

    @property
    def target_range(self) -> tuple[int, int] | None:
        loaded = [b for b in self.blocks if b.count]
        if not loaded:
            return None
        return (min(b.target for b in loaded),
                max(b.target + b.count for b in loaded))


def header_at(data: bytes, offset: int) -> Block | None:
    """The block header at `offset`, or None if there is not a signed one there."""
    if offset < 0 or offset + HEADER > len(data):
        return None
    code, target, count, argument = struct.unpack_from("<IIII", data, offset)
    if (code >> 24) != SIGNATURE:
        return None
    return Block(offset=offset, code=code, target=target, count=count, argument=argument)


def walk(data: bytes, start: int = 0, max_blocks: int = 100_000) -> Walk:
    """Follow the block chain from `start` for as far as it holds."""
    blocks: list[Block] = []
    at = start
    while len(blocks) < max_blocks:
        block = header_at(data, at)
        if block is None:
            reason = ("end of data" if at + HEADER > len(data)
                      else f"no 0x{SIGNATURE:02x} signature at 0x{at:06x}")
            return Walk(tuple(blocks), at, reason, len(data))
        # Only a block that actually carries bytes has to fit in the stream. A
        # fill block declares a range to zero and can be far larger than the
        # file -- section 7 ends with a 4.5 MB fill into DDR, and a blunter
        # guard than this rejected it and truncated the walk at 88 of 95 blocks.
        if block.has_payload and block.end > len(data):
            return Walk(tuple(blocks), at,
                        f"payload at 0x{at:06x} runs past the end of the section",
                        len(data))
        blocks.append(block)
        at = block.end
    return Walk(tuple(blocks), at, "block limit reached", len(data))


def load_regions(data: bytes, start: int = 0) -> list[tuple[int, bytes]]:
    """Play the stream back into the memory it describes: [(address, bytes)].

    This is what makes the image *readable*. Offsets into the section are not
    addresses -- the payloads are scattered across L1, L2 and DDR -- so nothing
    can be cross-referenced until the blocks are laid out where they load. Fill
    blocks contribute zeros, which is what the loader writes.

    Adjacent and overlapping spans are merged, so a later block overwrites an
    earlier one exactly as it would on the device.
    """
    result = walk(data, start)
    pieces: list[tuple[int, bytes]] = []
    for block in result.blocks:
        if block.has_payload:
            pieces.append((block.target, data[block.payload_at:block.payload_at + block.count]))
        elif block.flags & FLAG_FILL and block.count:
            pieces.append((block.target, bytes(block.count)))
    if not pieces:
        return []

    pieces.sort(key=lambda p: p[0])
    merged: list[tuple[int, bytearray]] = []
    for address, payload in pieces:
        if merged and address <= merged[-1][0] + len(merged[-1][1]):
            base, buffer = merged[-1]
            offset = address - base
            need = offset + len(payload)
            if need > len(buffer):
                buffer.extend(bytes(need - len(buffer)))
            buffer[offset:offset + len(payload)] = payload
        else:
            merged.append((address, bytearray(payload)))
    return [(address, bytes(buffer)) for address, buffer in merged]


def find_streams(data: bytes, min_blocks: int = 3) -> list[Walk]:
    """Every convincing chain in `data`, outermost first, without overlaps.

    A stream need not start at offset 0 -- a section can hold several, and the
    Digitone II's section 7 does. Candidates are tried at every signed header
    and kept only if `Walk.convincing`.
    """
    found: list[Walk] = []
    claimed: list[tuple[int, int]] = []
    candidates = [i for i in range(0, max(len(data) - HEADER, 0), 4)
                  if data[i + 3] == SIGNATURE]
    walks = [walk(data, at) for at in candidates]
    walks.sort(key=lambda w: len(w.blocks), reverse=True)
    for result in walks:
        if len(result.blocks) < min_blocks or not result.convincing:
            continue
        begin = result.blocks[0].offset
        if any(lo <= begin < hi for lo, hi in claimed):
            continue
        claimed.append((begin, result.stopped_at))
        found.append(result)
    return sorted(found, key=lambda w: w.blocks[0].offset)


class SpanError(ValueError):
    """A load-address range is not wholly backed by payload in this stream."""


def spans(data: bytes, address: int, length: int) -> list[tuple[int | None, int]]:
    """Map a load-address range to the file pieces that hold it.

    -> [(file_offset, piece_length), ...] in load order, covering exactly
    `length` bytes from `address`. A piece whose offset is **None** is a *fill*
    block: the loader writes zeros there and **the file contains no bytes for
    it at all**, so it can be read but never written.

    **This exists because a load-address range is not a file range.** The boot
    stream interleaves 16-byte headers with payload, so a region contiguous in
    the DSP's memory can be several disjoint pieces in the file, and anything
    that reads or writes it linearly will cross a header.

    Measured, not hypothetical. The FM drum transient bank at `0x8045c380`
    spans two payload blocks with a **36-byte fill block and two headers**
    between them, 47,440 bytes in. Until 2026-09-14 `mods.transients` read and
    wrote straight through that:

    - 85.5% of the bank it reported was shifted by 34 samples and carried the
      header bytes as audio -- the visible spike in entry 4;
    - a caller replacing every entry would have **overwritten two block
      headers**, leaving a boot stream the DSP cannot load.

    See `docs/pcm-hunt.md`.

    Raises SpanError if any byte is not covered by a block at all. That is the
    important half: a gap means the caller's model of the image is wrong, and
    guessing an offset there corrupts a region nobody was looking at.
    """
    pieces: list[tuple[int | None, int]] = []
    blocks = sorted((b for b in walk(data).blocks if b.count),
                    key=lambda b: b.target)
    at, remaining = address, length
    progressed = True
    while remaining > 0 and progressed:
        progressed = False
        for block in blocks:
            if not (block.target <= at < block.target + block.count):
                continue
            take = min(remaining, block.target + block.count - at)
            pieces.append(
                (block.payload_at + (at - block.target) if block.has_payload
                 else None, take))
            at += take
            remaining -= take
            progressed = True
            break
    if remaining > 0:
        raise SpanError(
            f"0x{at:08x} is not inside any boot-stream block "
            f"({remaining:,} of {length:,} bytes unmapped); this image's "
            f"layout is not the one this was measured against")
    return pieces


def read_span(data: bytes, address: int, length: int) -> bytes:
    """The bytes loaded at `address`, gathered across blocks.

    Fill blocks contribute zeros, which is what the loader writes.
    """
    out = bytearray()
    for at, n in spans(data, address, length):
        out += bytes(n) if at is None else data[at:at + n]
    return bytes(out)


def writable(data: bytes, address: int, length: int) -> list[tuple[int, int]]:
    """`spans`, but refusing any fill block.

    A separate function rather than a flag, because the failure is worth a
    different sentence: reading a fill region is fine and gives zeros, while
    writing one is impossible -- there is nowhere to put the bytes -- and a
    caller that cannot be told so would silently drop them.
    """
    pieces = spans(data, address, length)
    at = address
    for offset, n in pieces:
        if offset is None:
            raise SpanError(
                f"0x{at:08x}..0x{at + n:08x} ({n} bytes) is a fill block: the "
                f"loader writes zeros there and the file holds no bytes for "
                f"it, so it cannot be written")
        at += n
    return [(offset, n) for offset, n in pieces]


def write_span(data: bytearray, address: int, payload: bytes) -> None:
    """Write `payload` to `address`, scattered back across blocks, in place."""
    cursor = 0
    for at, n in writable(bytes(data), address, len(payload)):
        data[at:at + n] = payload[cursor:cursor + n]
        cursor += n
