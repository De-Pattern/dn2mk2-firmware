"""Turn "does this function run?" into something you can read off the screen.

`docs/flashing.md`, 2026-09-13: a cave hooked into the boot path wrote
`CAVE RAN!!!` over the SETTINGS menu string in RAM, and the device showed it.
That makes `patch/cave.py` an **instrument** rather than only a patcher -- any
function, when it executes, can be made to leave a mark a human can see.

This module spends that on the question that cost this project four flashes:
**which functions are actually on the path?** Static analysis could not answer
it. `image/functions.py` narrows the field but cannot close it, because a
vtable call is invisible in the instruction stream and a function with callers
may still not be on the path you care about (`parameter_value_getter` has two
callers and does not draw parameters).

## The board

One visible string in the image is the display surface. Ship it as a row of
idle characters instead of its stock text, then give each candidate function a
**column** and a **mark**:

    SETTINGS shows  .M..G..U...
                     |  |  |
                     |  |  `- column 7's function ran
                     |  `---- column 4's function ran
                     `------- column 1's function ran

Eleven columns in `PERSONALIZE`, so **eleven reachability answers per flash**,
against one answer per flash for the builds that produced them by guessing.
And the marks accumulate while the instrument is used: change a parameter, come
back into SETTINGS, and the row shows what that action touched.

The idle row is a **plain data edit shipped in the image** -- the same class of
edit as Gate E, already proven on this device -- so nothing has to run for the
board to appear. A blank row is therefore a real result (no probe ran), not an
ambiguous one.

## Why a probe may be spliced anywhere

A hook at an arbitrary site must leave the machine exactly as it found it, and
"exactly" includes the condition codes. A probe that clobbered CCR between a
`cmp` and its `beq` would silently change what the firmware decides, which is a
far worse failure than not running at all -- it would look like a result.

    lea     %sp@(-8),%sp        ; claim stack *before* writing to it, so an
    movem.l %d0/%a0,%sp@        ; interrupt cannot land on the saved registers
    move.w  %ccr,%d0            ; MOVEM and LEA do not touch CCR; this does not either
    lea     BOARD,%a0
    move.b  #MARK,%a0@(COLUMN)  ; the only instruction here that writes CCR
    move.w  %d0,%ccr            ; put it back
    movem.l %sp@,%d0/%a0
    lea     %sp@(8),%sp         ; stock displaced bytes replay with %sp restored

32 bytes, verified against objdump. `%sp` is restored before `patch/cave.py`
replays the displaced instructions, so a displaced `movea.l %sp@(4),%a0` -- an
ordinary way for a ColdFire prologue to read its first argument -- still reads
the argument and not our saved registers.

ColdFire has no MOVEM predecrement or postincrement mode, which is why the
stack moves by `lea` rather than `movem.l %d0/%a0,%sp@-`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..image.coldfire import LoadedImage
from ..image.functions import branch_targets_within
from .assemble import assemble
from .cave import Cave, CaveError, CaveHook

IDLE = ord(".")
# One probe's cave holds 32 bytes of payload, the displaced stock, and a 6-byte
# jump home. 64 leaves room for a hook that has to displace 10 or 12 bytes to
# land on an instruction boundary, and keeps the arithmetic in `lay_out` trivial.
SLOT = 64


class TraceError(ValueError):
    """A trace board or probe is malformed, or does not fit this image."""


@dataclass(frozen=True)
class Board:
    """The visible string a trace writes into.

    `address` is where the string starts and `width` how many characters of it
    are ours to use. The string must be one the instrument actually displays and
    whose stock text is not needed while tracing -- on the DN2 that is
    `PERSONALIZE` in SETTINGS, eleven characters, proven visible.
    """

    address: int
    width: int

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise TraceError("a board needs at least one column")

    @property
    def idle(self) -> bytes:
        """What ships in the image: a row of idle characters, NUL-terminated."""
        return bytes([IDLE]) * self.width + b"\x00"


@dataclass(frozen=True)
class Probe:
    """One function under observation.

    `site` is where the hook is spliced -- normally a function's entry, because
    an entry is straight-line, is already a call target, and answers "was this
    function reached" rather than "was this one instruction reached".

    `mark` is the character it writes into `column` when it executes. Give each
    probe a mark that recalls what it tests; the legend printed by the build is
    what you read the screen against.
    """

    id: str
    site: int
    mark: str
    column: int
    note: str = ""

    def __post_init__(self) -> None:
        if len(self.mark) != 1 or not self.mark.isprintable():
            raise TraceError(f"{self.id}: mark must be one printable character, got {self.mark!r}")
        if self.mark == chr(IDLE):
            raise TraceError(f"{self.id}: mark {self.mark!r} is the idle character -- invisible")
        if self.column < 0:
            raise TraceError(f"{self.id}: column must be non-negative")


def payload(board: Board, probe: Probe) -> bytes:
    """Assemble the stamp for one probe. See the module docstring for the shape."""
    if probe.column >= board.width:
        raise TraceError(
            f"{probe.id}: column {probe.column} is outside the board's {board.width}"
        )
    source = "\n".join([
        f"| trace {probe.id}: stamp {probe.mark!r} in column {probe.column}",
        "    lea     %sp@(-8),%sp",
        "    movem.l %d0/%a0,%sp@",
        "    move.w  %ccr,%d0",
        f"    lea     {board.address},%a0",
        f"    move.b  #{ord(probe.mark)},%a0@({probe.column})",
        "    move.w  %d0,%ccr",
        "    movem.l %sp@,%d0/%a0",
        "    lea     %sp@(8),%sp",
    ])
    return assemble(source + "\n")


def check_site(image: LoadedImage, probe: Probe, stock: bytes) -> None:
    """Refuse a site where splicing a jump would corrupt the firmware.

    `patch/cave.py` checks that the stock bytes match and that they hold no
    PC-relative branch. One hazard is left, and only a whole-image scan finds
    it: **something branching into the middle of the bytes we replace**. A loop
    whose back-edge lands two bytes into our `jmp` would arrive at an operand
    word and execute whatever it decodes as.

    The entry byte itself is excluded -- a hook at a function entry is meant to
    be a call target.
    """
    hits = branch_targets_within(image, probe.site, len(stock))
    if hits:
        listed = ", ".join(f"0x{h:08x}" for h in hits[:4])
        more = f" (+{len(hits) - 4} more)" if len(hits) > 4 else ""
        raise TraceError(
            f"{probe.id}: something branches into the middle of the {len(stock)} bytes at "
            f"0x{probe.site:08x} -- from {listed}{more}. Splicing a jump here would land "
            f"that branch on an operand word. Pick another site."
        )


def lay_out(start: int, count: int, *, slot: int = SLOT) -> tuple[Cave, ...]:
    """Carve `count` equal caves out of one free run beginning at `start`.

    Kept separate from the probes so the caller chooses the run -- which run is
    safe is `docs/memory-map.md`'s call, not this module's.
    """
    if start % 2:
        raise TraceError(f"cave run 0x{start:08x} is odd; m68k code is 2-byte aligned")
    return tuple(Cave(address=start + i * slot, capacity=slot) for i in range(count))


def hooks(image: LoadedImage, board: Board, probes: tuple[Probe, ...],
          caves: tuple[Cave, ...], stocks: dict[str, bytes]) -> tuple[CaveHook, ...]:
    """One `CaveHook` per probe, every guard checked before any is returned.

    `stocks` maps a probe id to the whole-instruction bytes at its site, which
    the caller obtains from `dnfw cave probe` or `cave.displaced_stock` -- this
    module does not disassemble, so that it has one subject.
    """
    if len(caves) < len(probes):
        raise TraceError(f"{len(probes)} probes but only {len(caves)} caves")
    seen: dict[int, str] = {}
    built: list[CaveHook] = []
    for probe, cave in zip(probes, caves):
        if probe.column in seen:
            raise TraceError(
                f"{probe.id} and {seen[probe.column]} both write column {probe.column}"
            )
        seen[probe.column] = probe.id
        stock = stocks.get(probe.id)
        if stock is None:
            raise TraceError(f"{probe.id}: no stock bytes supplied for 0x{probe.site:08x}")
        check_site(image, probe, stock)
        built.append(CaveHook(
            id=probe.id,
            site=probe.site,
            stock=stock,
            payload=payload(board, probe),
            cave=cave,
        ))
    return tuple(built)


def legend(probes: tuple[Probe, ...], width: int) -> str:
    """The row of marks to read the screen against, plus what each one means."""
    row = [chr(IDLE)] * width
    for probe in probes:
        row[probe.column] = probe.mark
    lines = ["".join(row), ""]
    for probe in sorted(probes, key=lambda p: p.column):
        note = f"  -- {probe.note}" if probe.note else ""
        lines.append(f"  col {probe.column:>2}  {probe.mark}  0x{probe.site:08x}  {probe.id}{note}")
    return "\n".join(lines)


def find_board(content: bytes, base: int, text: bytes) -> Board:
    """Locate the board by its stock text, requiring it to be unique.

    By string search and never by address: an offset stops being true the moment
    anything earlier in the image changes, and a board that matched twice would
    write marks somewhere unseen.
    """
    if not text.endswith(b"\x00"):
        raise TraceError("give the board's stock text with its NUL, so the length is exact")
    hits = [i for i in range(len(content) - len(text) + 1)
            if content[i:i + len(text)] == text]
    if len(hits) != 1:
        raise TraceError(f"{text!r} occurs {len(hits)} times in the image, expected exactly 1")
    return Board(address=base + hits[0], width=len(text) - 1)
