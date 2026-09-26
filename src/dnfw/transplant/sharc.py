"""SHARC+ instruction fields a relocation rewrites, in section-7 memory order.

A section-7 boot stream stores program memory as 16-bit parcels, each
little-endian, the first parcel of an instruction at the lowest address. A
48-bit instruction at short-word address `sw` is therefore the six bytes at
loader address `SW_ALIAS + 2 * sw`, and its value is `p0 << 32 | p1 << 16 | p2`.

Only the fields a relocation needs are modelled here, and each one was read
off digikit's decoder (`tools/sharc_disasm.py`, run as a tool) for the very
instructions the transplant moves (`docs/dt2-machine-port.md`, "The
experiment, run"):

| field    | forms                        | bits of the 48-bit value            |
|----------|------------------------------|-------------------------------------|
| `data32` | 17a `ureg = data32`, 16a `DM(Ii, Mm) = data32` | 31..0             |
| `addr32` | 14a `ureg = DM(addr32)`      | 31..0                               |
| `addr24` | 25a direct `CALL/JUMP addr24`| 23..0                               |
| `rel24`  | 8a relative `CALL/JUMP (pc, rel24)` | 23..0, signed, from the instruction's own sw |

This module decodes nothing else and never guesses a form: the caller names
the site, its form and the value it must already hold.
"""

from __future__ import annotations

SW_ALIAS = 0x28000000         # loader byte address of short-word 0 (and DM byte 0)
# Code executed at short-word 0xb80000.. is L2 SRAM: the boot stream loads it
# through the L2 byte window instead (digikit's `sharcldr`, L2_SW_BASE, whose
# bytes we checked against the stream: the DT2 decimator at sw 0xb80000 is only
# present there).
L2_SW_BASE = 0x00B80000
L2_BYTE_BASE = 0x20000000
INSTRUCTION_BYTES = 6         # every relocated site is a 48-bit instruction

FIELDS = {
    "data32": (0, 32, False),
    "addr32": (0, 32, False),
    "addr24": (0, 24, False),
    "rel24": (0, 24, True),
}


def code_address(sw: int, window: str = "l1") -> int:
    """Loader byte address of the parcel at short-word address `sw`: through the
    short-word alias (`l1`), or the L2 byte window (`l2`, sw >= 0xb80000)."""
    if window == "l1":
        return SW_ALIAS + 2 * sw
    if window == "l2":
        if sw < L2_SW_BASE:
            raise ValueError(f"sw {sw:#x} is below the L2 window at {L2_SW_BASE:#x}")
        return L2_BYTE_BASE + 2 * (sw - L2_SW_BASE)
    raise ValueError(f"unknown code window {window!r}")


def data_address(dm: int) -> int:
    """Loader byte address of DM byte address `dm` (the form the firmware writes)."""
    return SW_ALIAS + dm


def to_value(memory_bytes: bytes) -> int:
    """Six memory-order bytes -> the 48-bit instruction value."""
    if len(memory_bytes) != INSTRUCTION_BYTES:
        raise ValueError(f"a 48-bit instruction is {INSTRUCTION_BYTES} bytes, not {len(memory_bytes)}")
    p = [int.from_bytes(memory_bytes[k:k + 2], "little") for k in (0, 2, 4)]
    return p[0] << 32 | p[1] << 16 | p[2]


def to_bytes(value: int) -> bytes:
    """The 48-bit instruction value -> six memory-order bytes."""
    if not 0 <= value < 1 << 48:
        raise ValueError("not a 48-bit value")
    return b"".join(((value >> s) & 0xFFFF).to_bytes(2, "little") for s in (32, 16, 0))


def get_field(value: int, field: str) -> int:
    lo, width, signed = FIELDS[field]
    raw = (value >> lo) & ((1 << width) - 1)
    if signed and raw & (1 << (width - 1)):
        raw -= 1 << width
    return raw


def set_field(value: int, field: str, new: int) -> int:
    lo, width, signed = FIELDS[field]
    if signed:
        if not -(1 << (width - 1)) <= new < 1 << (width - 1):
            raise ValueError(f"{new} does not fit a signed {width}-bit field")
        new &= (1 << width) - 1
    elif not 0 <= new < 1 << width:
        raise ValueError(f"{new:#x} does not fit an unsigned {width}-bit field")
    mask = ((1 << width) - 1) << lo
    return (value & ~mask) | (new << lo)


def target_of(value: int, field: str, sw: int) -> int:
    """The address a site refers to: the field itself, or pc + rel for `rel24`."""
    v = get_field(value, field)
    return sw + v if field == "rel24" else v


def retarget(value: int, field: str, sw: int, new_target: int) -> int:
    """The instruction at `sw`, rewritten to refer to `new_target`."""
    return set_field(value, field, new_target - sw if field == "rel24" else new_target)
