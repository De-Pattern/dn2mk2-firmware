"""Which addresses are called, and from where -- the check that was missing.

This project hooked `0x4004ca80` because a prologue, an epilogue and a
`Sound::updateMirror` string all fell inside it. The firmware was built, signed
and flashed, and nothing happened. The reason was one fact nobody had measured:
**its address appears in the image exactly once, as a vtable slot, and nothing
calls it directly** (`docs/lfo4-slot-plan.md`).

Three further builds were spent before that surfaced, so the measurement is
worth having as a module rather than as a helper copied into a build script.
One subject: derive, from the instruction stream, who calls whom.

**What this answers, and what it does not.** A direct-call scan is evidence of
reachability, never proof of it, and it cuts both ways:

- **zero direct callers** does not mean dead. A virtual override is reached
  through a vtable and this scan cannot see it. It does mean *a cave there
  cannot be assumed to run*, which is the useful half.
- **many direct callers** does not mean reached *on the path you care about*.
  `parameter_value_getter` has two callers and is demonstrably not the display
  path (`docs/version-anchors.md`).

The instrument that settles reachability on the device is `patch/trace.py`.
This module narrows the candidates it is worth spending a flash on.
"""

from __future__ import annotations

import bisect
import struct
from dataclasses import dataclass

from .coldfire import LoadedImage

# Call forms this decoder recognises, all of them direct:
#   4eb9 xxxxxxxx   jsr (xxx).l          absolute long
#   4eba dddd       jsr (d16,pc)         pc-relative word
#   61xx            bsr.b                displacement in the low byte
#   6100 dddd       bsr.w
#   61ff dddddddd   bsr.l
# Indirect calls (`jsr (%a0)`, `jsr (d16,%a0)`) carry no target in the
# instruction and are invisible here by construction -- that is the limit
# stated in the module docstring, not an oversight.
JSR_ABS = 0x4EB9
JSR_PCREL = 0x4EBA
BSR_HI = 0x61


@dataclass(frozen=True)
class Call:
    """One direct call: `site` is the instruction, `target` what it calls."""

    site: int
    target: int


def _decode_call(content: bytes, off: int, base: int) -> int | None:
    """The target of a direct call at `off`, or None if this is not one.

    Reads two to six bytes past `off`; the caller keeps the scan in bounds.
    """
    op = struct.unpack_from(">H", content, off)[0]
    if op == JSR_ABS:
        return struct.unpack_from(">I", content, off + 2)[0]
    if op == JSR_PCREL:
        return base + off + 2 + struct.unpack_from(">h", content, off + 2)[0]
    if (op >> 8) == BSR_HI:
        low = op & 0xFF
        if low == 0x00:
            return base + off + 2 + struct.unpack_from(">h", content, off + 2)[0]
        if low == 0xFF:
            return base + off + 2 + struct.unpack_from(">i", content, off + 2)[0]
        return base + off + 2 + struct.unpack_from(">b", content, off + 1)[0]
    return None


@dataclass(frozen=True)
class CallGraph:
    """Every direct call found in a section, indexed both ways.

    Built by scanning on a 2-byte stride, which reads operand words as though
    they were opcodes and so admits a few false calls. They are harmless for the
    two questions asked of this class -- a spurious extra caller does not turn an
    unreachable address into a reachable one -- and the `entries` list stays
    conservative because a false target rarely lands on a real function.
    """

    base: int
    calls: tuple[Call, ...]
    _targets: dict[int, tuple[int, ...]]
    _entries: tuple[int, ...]

    @property
    def entries(self) -> tuple[int, ...]:
        """Every address something calls directly, ascending -- function starts."""
        return self._entries

    def callers_of(self, target: int) -> tuple[int, ...]:
        """The sites that call `target` directly. Empty means indirect-only."""
        return self._targets.get(target, ())

    def containing(self, address: int) -> int | None:
        """The nearest call target at or below `address`.

        A **guess at** the enclosing function, not a fact. Functions reached only
        through a vtable are not in `entries`, so an address inside one is
        attributed to whichever directly-called function happens to precede it.
        Treat a result as a lead to verify by disassembling from it, never as an
        identification.
        """
        i = bisect.bisect_right(self._entries, address) - 1
        return self._entries[i] if i >= 0 else None

    def is_entry(self, address: int) -> bool:
        return address in self._targets


def build(image: LoadedImage) -> CallGraph:
    """Scan `image` for direct calls and index them."""
    content = image.content
    base = image.dest
    limit = image.end
    calls: list[Call] = []
    for off in range(0, len(content) - 5, 2):
        target = _decode_call(content, off, base)
        if target is None:
            continue
        # A target outside the section, or on an odd address, is a misread
        # operand rather than a call -- m68k instructions are 2-byte aligned.
        if target % 2 or not (base <= target < limit):
            continue
        calls.append(Call(site=base + off, target=target))

    targets: dict[int, list[int]] = {}
    for call in calls:
        targets.setdefault(call.target, []).append(call.site)
    frozen = {t: tuple(sites) for t, sites in targets.items()}
    return CallGraph(
        base=base,
        calls=tuple(calls),
        _targets=frozen,
        _entries=tuple(sorted(frozen)),
    )


def branch_targets_within(image: LoadedImage, start: int, length: int) -> tuple[int, ...]:
    """Addresses strictly inside [start, start+length) that something jumps to.

    The guard a code cave needs and `patch/cave.py` cannot make on its own.
    Splicing a `jmp` over `length` bytes is only safe if no other instruction
    branches into the middle of them -- a loop whose back-edge lands there would
    arrive to find half a jump. `start` itself is excluded: a hook at a function
    entry is *expected* to be a call target, and that is the normal case.

    Covers Bcc/BSR/BRA (0x6x) and JMP/JSR in their absolute and pc-relative
    forms, which is every direct transfer that names its destination.
    """
    content = image.content
    base = image.dest
    interior = range(start + 2, start + length)
    hits: set[int] = set()
    for off in range(0, len(content) - 5, 2):
        op = struct.unpack_from(">H", content, off)[0]
        target = None
        if op in (JSR_ABS, 0x4EF9):  # jsr/jmp (xxx).l
            target = struct.unpack_from(">I", content, off + 2)[0]
        elif op in (JSR_PCREL, 0x4EFA):  # jsr/jmp (d16,pc)
            target = base + off + 2 + struct.unpack_from(">h", content, off + 2)[0]
        elif 0x6000 <= op < 0x7000:  # Bcc.b/.w/.l, BRA, BSR
            low = op & 0xFF
            if low == 0x00:
                target = base + off + 2 + struct.unpack_from(">h", content, off + 2)[0]
            elif low == 0xFF:
                target = base + off + 2 + struct.unpack_from(">i", content, off + 2)[0]
            else:
                target = base + off + 2 + struct.unpack_from(">b", content, off + 1)[0]
        if target is not None and target in interior:
            hits.add(base + off)
    return tuple(sorted(hits))
