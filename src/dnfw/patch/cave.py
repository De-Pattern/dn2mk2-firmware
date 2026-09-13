"""Add code to the firmware without moving anything: a code-cave detour.

`patch/spec.py` only replaces bytes in place, because changing a section's
length would move every address after it. When Phase 2 needs *new* code -- a
fourth LFO in the modulation tick, a raised parameter-table bound -- the way
that does not relocate the image is a **detour**: overwrite a handful of stock
bytes at a hook site with a `jmp` into unused space (a "cave"), run the new
code there, replay the stock instructions the jmp displaced, and jump back.

The model is octabam's and midisc's (both MIT, ColdFire, `docs/references.md`):
a hook address, the **stock bytes asserted** at it, and the displaced
instructions replayed in the cave. Two guards make it safe to apply:

- the stock bytes at the hook must match, or the image is the wrong build and
  nothing is written (the `patch/spec.py` discipline, here for a cave);
- the cave must lie in space that is actually free. `docs/memory-map.md` is
  strict about this on the DN2: the only safe caves are the **unreferenced
  padding runs** in the constants region (~0x4026e000..0x402e2000). The bytes
  copied to SDRAM at boot (0x402e2000..0x40300000, the .data/BSS initializer)
  read as free but are not, and live code obviously is not. The applier
  refuses a cave that is not currently all-zero, and the caller is responsible
  for the region being one the memory map blesses.

Displaced bytes are replayed verbatim, which is only correct if they are
position-independent. PC-relative branches (Bcc/BSR) are not, and moving them
silently retargets them. `plan()` scans the displaced bytes for those opcodes
and refuses unless the caller passes `allow_pcrel=True` -- a coarse net (it is
not a full disassembler), so the honest rule remains: pick hook sites whose
displaced instructions are straight-line moves and arithmetic.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..image.coldfire import LoadedImage
from .coldfire import jmp_abs

NOP = b"\x4e\x71"  # ColdFire nop; pads a hook site out to an instruction boundary
HOOK_BRANCH_LEN = 6  # jmp (addr).l


class CaveError(ValueError):
    """A cave patch is malformed, or does not apply to this image."""


@dataclass(frozen=True)
class Cave:
    """A region of the image reserved for new code.

    `address` is a virtual address; `capacity` is how many bytes may be written
    there. Both must fall inside a run the memory map marks free -- this class
    does not know which runs those are, only that the bytes it is given are
    currently zero (checked at apply time).
    """

    address: int
    capacity: int

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise CaveError("cave capacity must be positive")


@dataclass(frozen=True)
class CaveHook:
    """A detour spliced at `site`.

    `stock` is the exact bytes expected at `site` -- whole instructions, at
    least a `jmp`'s worth (6 bytes), on a 2-byte boundary. They are asserted
    before anything is written and replayed in the cave after `payload` runs.

    `payload` is the new code, already assembled (via `patch/assemble.py` or the
    `patch/coldfire.py` encoder). It runs first, then the displaced `stock`,
    then a jump back to just after the hook.
    """

    id: str
    site: int
    stock: bytes
    payload: bytes
    cave: Cave
    allow_pcrel: bool = False

    def __post_init__(self) -> None:
        if len(self.stock) < HOOK_BRANCH_LEN:
            raise CaveError(
                f"{self.id}: stock is {len(self.stock)} bytes; a hook needs at least "
                f"{HOOK_BRANCH_LEN} (a jmp) so whole instructions are displaced"
            )
        if len(self.stock) % 2:
            raise CaveError(f"{self.id}: stock length must be even (2-byte instruction boundary)")


@dataclass(frozen=True)
class Write:
    """One contiguous edit to the decompressed section."""

    offset: int
    old: bytes
    new: bytes

    @property
    def address_note(self) -> str:
        return f"offset 0x{self.offset:x} ({len(self.new)} bytes)"


@dataclass(frozen=True)
class CavePlan:
    """What a cave hook resolves to: the exact edits, computed but not applied."""

    hook: CaveHook
    cave_bytes: bytes  # payload + displaced stock + jmp back
    writes: tuple[Write, Write]  # (cave region, hook site)

    @property
    def return_address(self) -> int:
        return self.hook.site + len(self.hook.stock)


# ColdFire PC-relative branch opcodes, high byte. Bcc.b/.w share 0x6x; BSR is
# 0x61. Detecting these in the displaced stream is a coarse safety net, not a
# decoder -- an operand byte can coincide with one of these values -- so it errs
# toward refusing, and the real rule is to choose straight-line hook sites.
_PCREL_HI = set(range(0x60, 0x70))


def _looks_pcrel(stock: bytes) -> bool:
    return any((stock[i] in _PCREL_HI) for i in range(0, len(stock), 2))


def plan(image: LoadedImage, hook: CaveHook) -> CavePlan:
    """Resolve `hook` against `image` into concrete edits, or raise.

    Nothing is written; the returned plan carries the byte edits so a caller can
    inspect or diff them before committing. Every guard is checked here.
    """
    # 1. The hook site must hold exactly the stock bytes we expect.
    if not image.contains(hook.site, len(hook.stock)):
        raise CaveError(
            f"{hook.id}: hook 0x{hook.site:08x}+{len(hook.stock)} is outside "
            f"0x{image.dest:08x}..0x{image.end:08x}"
        )
    site_off = image.offset_of(hook.site)
    found = image.content[site_off : site_off + len(hook.stock)]
    if found != hook.stock:
        raise CaveError(
            f"{hook.id}: at 0x{hook.site:08x} expected {hook.stock.hex(' ')} "
            f"but found {found.hex(' ')} -- wrong build or wrong address"
        )

    # 2. The displaced bytes are replayed; refuse if they look position-dependent.
    if _looks_pcrel(hook.stock) and not hook.allow_pcrel:
        raise CaveError(
            f"{hook.id}: displaced stock {hook.stock.hex(' ')} may contain a PC-relative "
            "branch, which breaks when replayed in the cave. Pick a straight-line hook "
            "site, or pass allow_pcrel=True if you have verified it is safe."
        )

    # 3. Build the cave body: payload, then the displaced stock, then jump back.
    cave_body = bytes(hook.payload) + bytes(hook.stock) + jmp_abs(hook.site + len(hook.stock))
    if len(cave_body) > hook.cave.capacity:
        raise CaveError(
            f"{hook.id}: cave body is {len(cave_body)} bytes but cave at "
            f"0x{hook.cave.address:08x} holds {hook.cave.capacity}"
        )

    # 4. The cave must be inside the section and currently free (all zero).
    if not image.contains(hook.cave.address, len(cave_body)):
        raise CaveError(
            f"{hook.id}: cave 0x{hook.cave.address:08x}+{len(cave_body)} is outside "
            f"0x{image.dest:08x}..0x{image.end:08x}"
        )
    cave_off = image.offset_of(hook.cave.address)
    existing = image.content[cave_off : cave_off + len(cave_body)]
    if any(existing):
        first = next(i for i, b in enumerate(existing) if b)
        raise CaveError(
            f"{hook.id}: cave at 0x{hook.cave.address + first:08x} is not free "
            f"(0x{existing[first]:02x}) -- refusing to overwrite. See docs/memory-map.md "
            "for which runs are safe."
        )

    # 5. The hook edit: jmp into the cave, then nop-pad to the instruction boundary.
    branch = jmp_abs(hook.cave.address)
    pad = (len(hook.stock) - HOOK_BRANCH_LEN) // 2
    hook_bytes = branch + NOP * pad

    return CavePlan(
        hook=hook,
        cave_bytes=cave_body,
        writes=(
            Write(offset=cave_off, old=bytes(existing), new=cave_body),
            Write(offset=site_off, old=bytes(hook.stock), new=hook_bytes),
        ),
    )


def apply(image: LoadedImage, hook: CaveHook) -> bytes:
    """Return new section content with `hook`'s detour spliced in.

    Applies to a copy, so a failed guard leaves the input untouched.
    """
    resolved = plan(image, hook)
    edited = bytearray(image.content)
    for write in resolved.writes:
        edited[write.offset : write.offset + len(write.new)] = write.new
    return bytes(edited)


# --- authoring aids: finding a cave, and sizing a hook --------------------

@dataclass(frozen=True)
class FreeRun:
    """A run of zero bytes -- a candidate cave, before the safety judgement."""

    address: int
    size: int


def find_free_runs(image: LoadedImage, start: int, end: int, min_size: int) -> list[FreeRun]:
    """Runs of `min_size`+ zero bytes in [start, end).

    A zero run is only a *candidate* cave. Whether it is safe is the memory
    map's call (`docs/memory-map.md`): the padding in the constants region is
    safe; the .data/BSS initializer at 0x402e2000+ is all zero here too but is
    copied to SDRAM at boot, so it is not. This finds runs; it does not bless
    them. Default the range to the blessed region and it will not mislead.
    """
    if start < image.dest or end > image.end or start >= end:
        raise CaveError(
            f"range 0x{start:08x}..0x{end:08x} is outside "
            f"0x{image.dest:08x}..0x{image.end:08x}"
        )
    runs: list[FreeRun] = []
    content = image.content
    i = image.offset_of(start)
    stop = image.offset_of(end - 1) + 1
    while i < stop:
        if content[i]:
            i += 1
            continue
        j = i
        while j < stop and content[j] == 0:
            j += 1
        if j - i >= min_size:
            runs.append(FreeRun(address=image.address_of(i), size=j - i))
        i = j
    return runs


@dataclass(frozen=True)
class Suspect:
    """A group of free runs that repeat at a fixed stride — almost certainly an array."""

    stride: int
    runs: tuple[FreeRun, ...]

    @property
    def start(self) -> int:
        return self.runs[0].address

    @property
    def end(self) -> int:
        return self.runs[-1].address + self.runs[-1].size

    def describe(self) -> str:
        return (f"{len(self.runs)} runs of ~{self.runs[0].size} bytes at a {self.stride:#x} "
                f"stride, 0x{self.start:08x}..0x{self.end:08x}")


def suspect_arrays(runs: list[FreeRun], *, min_members: int = 3,
                   tolerance: float = 0.125) -> list[Suspect]:
    """Free runs that repeat at a fixed stride, which padding does not do.

    **Why this exists.** On 2026-09-13 caves were placed at `0x40287ef6`, offered
    by `find_free_runs` because the bytes are zero. They are not padding. Sixteen
    runs of 1,035 zeros sit there at a `0x40c` stride, each followed by a single
    `0xff` — an **array of 1,036-byte records, shipped zeroed and written at
    runtime**, sixteen being this machine's track and voice count. The firmware
    overwrote the caves while the keyboard was played and the device took an
    address error (`docs/flashing.md`).

    A compiler pads to an alignment boundary; it does not emit a dozen equal
    gaps at a constant pitch. **Regular spacing is positive evidence that a run
    belongs to a structure**, and it is the one signal that would have caught
    this without running anything.

    This does not prove a group is live, and an irregular run is not thereby
    safe — the only proof of safety is watching the firmware run and seeing the
    bytes stay untouched. It refuses the mistake we actually made.

    **`tolerance` is not a fudge factor, it is the whole difference between
    catching this and not.** An exact-stride rule flags `0x4028830e` onward and
    **misses `0x40287ef6`** — the run the caves were actually put in — because
    that record is twelve bytes longer than its fifteen siblings, so its gap is
    `0x418` against their `0x40c`, 2.9% out. A record array with a slightly
    different first entry is completely ordinary, and a guard that fails on its
    own motivating case is not a guard. Gaps within ±12.5% count as one stride.
    """
    ordered = sorted(runs, key=lambda r: r.address)
    found: list[Suspect] = []
    i = 0
    while i < len(ordered) - 1:
        stride = ordered[i + 1].address - ordered[i].address
        group = [ordered[i], ordered[i + 1]]
        j = i + 1
        while j < len(ordered) - 1:
            gap = ordered[j + 1].address - ordered[j].address
            if abs(gap - stride) > stride * tolerance:
                break
            group.append(ordered[j + 1])
            # Track the running mean so a long group is not dragged off by its
            # first gap; the members still have to agree with each other.
            stride = (ordered[j + 1].address - ordered[i].address) // (len(group) - 1)
            j += 1
        if len(group) >= min_members:
            found.append(Suspect(stride=stride, runs=tuple(group)))
            i = j
        else:
            i += 1
    return found


# Instructions that load an absolute long address. Requiring one of these in
# front of the constant is what separates a reference from a coincidence: a bare
# 32-bit-window scan over a 3 MB image finds ~175 values that merely *look* like
# addresses in a 0x74000-byte region, which is about one per free run — enough
# to condemn everything and mean nothing.
_LEA_ABS = {0x41F9 | (n << 9) for n in range(8)}       # lea 0x........,%aN
_MOVEL_IMM = {0x203C | (n << 9) for n in range(8)}     # move.l #0x........,%dN
_PEA_ABS = {0x4879}                                    # pea 0x........
_ADDRESS_LOADS = _LEA_ABS | _MOVEL_IMM | _PEA_ABS


def qualified_references(image: LoadedImage, lo: int, hi: int) -> dict[int, tuple[int, ...]]:
    """Addresses in [lo, hi) that the code actually *loads*, and from where.

    Complements `suspect_arrays`, and neither is sufficient alone — this is the
    lesson of `0x40287ef6` (`docs/code-caves.md`):

    * the array's **base** carries 9 qualified references, because the code
      holds it in a register;
    * its **other fifteen records carry none**, because they are reached by
      `base + i * 1036`. A reference check alone would call them free.

    So: references catch a base, stride catches the members, and a run needs to
    pass both. Even then neither proves the bytes are unused at runtime — a
    region reached by a computed pointer with no constant anywhere would pass
    both checks. They rule out what can be ruled out statically.
    """
    if lo >= hi:
        raise CaveError(f"empty range 0x{lo:08x}..0x{hi:08x}")
    content = image.content
    base = image.dest
    found: dict[int, list[int]] = {}
    for off in range(0, len(content) - 5, 2):
        if struct.unpack_from(">H", content, off)[0] not in _ADDRESS_LOADS:
            continue
        value = struct.unpack_from(">I", content, off + 2)[0]
        if lo <= value < hi:
            found.setdefault(value, []).append(base + off)
    return {value: tuple(sites) for value, sites in found.items()}


def references_into(run: FreeRun, references: dict[int, tuple[int, ...]]) -> tuple[int, ...]:
    """Every site that loads an address inside `run`."""
    sites: list[int] = []
    for value, at in references.items():
        if run.address <= value < run.address + run.size:
            sites.extend(at)
    return tuple(sorted(sites))


def displaced_stock(instruction_bytes: list[bytes], min_len: int = HOOK_BRANCH_LEN) -> bytes:
    """The whole-instruction stock a hook must displace to fit a `min_len` branch.

    Given the byte strings of consecutive decoded instructions at the hook site,
    return the concatenation of as many whole instructions as it takes to reach
    at least `min_len` bytes -- so the detour never splits an instruction.
    """
    out = bytearray()
    for data in instruction_bytes:
        out += data
        if len(out) >= min_len:
            return bytes(out)
    raise CaveError(
        f"only {len(out)} bytes of whole instructions available, need {min_len} for a hook"
    )
