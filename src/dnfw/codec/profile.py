"""What an aPLib stream asks of the decompressor: how far back its matches
reach, and how long they run.

Two streams can decode to identical bytes and still differ here, which is the
point. A decompressor with a bounded history accepts one and fails on the
other, and no checksum notices. See `codec.limits` for the bounds Elektron's
own streams stay inside, and why they matter.

The tokens come from `aplib.tokens`, the same reading the depacker uses, so a
profile and a decode cannot disagree about what a stream contains.
"""

from dataclasses import dataclass

from . import limits
from .aplib import tokens


@dataclass(frozen=True)
class Profile:
    output: int  # bytes the stream decodes to
    literals: int
    matches: int
    max_offset: int  # furthest any match reaches back; 0 if there are none
    max_length: int  # most bytes any single match copies
    beyond: int  # matches reaching back `window` bytes or more
    first_beyond: int | None  # output position of the first of those
    window: int

    @property
    def within_limits(self) -> bool:
        """Whether this stream stays inside the bounds Elektron's own do."""
        return self.max_offset < self.window and self.max_length <= limits.MAX_MATCH


def profile(stream: bytes, window: int = limits.WINDOW) -> Profile:
    """Profile one aPLib stream (no section header).

    Raises `aplib.DepackError` if the stream is not valid aPLib, exactly as
    decoding it would.
    """
    produced = literals = matches = max_offset = max_length = beyond = 0
    first_beyond = None

    for offset, value in tokens(stream):
        if offset == 0:
            literals += 1
            produced += 1
            continue
        matches += 1
        if offset > max_offset:
            max_offset = offset
        if value > max_length:
            max_length = value
        if offset >= window:
            beyond += 1
            if first_beyond is None:
                first_beyond = produced
        produced += value

    return Profile(
        output=produced,
        literals=literals,
        matches=matches,
        max_offset=max_offset,
        max_length=max_length,
        beyond=beyond,
        first_beyond=first_beyond,
        window=window,
    )
