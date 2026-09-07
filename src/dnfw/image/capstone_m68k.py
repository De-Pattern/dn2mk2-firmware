"""Disassembly via Capstone's m68k backend — the candidate engine, and one we
already know is wrong here.

Capstone offers modes for the 68000, 010, 020, 030, 040 and 060. **There is no
ColdFire mode**, so instructions ColdFire added are undefined to it. It does
not report that as failure in any way a caller notices: with `skipdata` it
emits a two-byte `.byte` and carries on, and where the real instruction was
longer than two bytes the stream desynchronises and everything after it is
fiction that reads like ordinary code.

Measured on Digitone II 1.10E MAIN OS, `0x40000400`–`0x40098000`, 2026-09-07:
2,055 undecodable instructions out of 195,649, and Capstone assigned **two
bytes to every single one of them**. 2,166 halfwords in that window match
`0111rrr1` — the MOVEQ opcode space with bit 8 set, which is undefined on every
68000-series part and is where ColdFire ISA_B places MVS and MVZ. That
identification is inferred from the encoding and is not confirmed until objdump
says so; what is measured is that Capstone cannot read them.

So this module exists to be **compared against**, not to be believed. It is
what makes Gate F a measurement rather than an assertion. Capstone is an
optional dependency and is imported lazily.
"""

from .instruction import Instruction

MODE_NAMES = ("040", "060", "030", "020", "010", "000")
SKIPPED = (".byte", ".short", "db", "dw")


class CapstoneMissing(RuntimeError):
    """Capstone is not installed."""


def _engine(mode_name: str):
    try:
        import capstone
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise CapstoneMissing("capstone is not installed (pip install capstone)") from error

    mode = getattr(capstone, f"CS_MODE_M68K_{mode_name}", None)
    if mode is None:
        raise ValueError(f"capstone has no m68k mode {mode_name!r}; known: {MODE_NAMES}")
    engine = capstone.Cs(capstone.CS_ARCH_M68K, mode | capstone.CS_MODE_BIG_ENDIAN)
    engine.skipdata = True
    return engine


def disassemble(data: bytes, address: int, mode_name: str = "040") -> list[Instruction]:
    """Disassemble `data` at `address`, closest-available m68k mode."""
    engine = _engine(mode_name)
    return [
        Instruction(insn.address, bytes(insn.bytes), f"{insn.mnemonic} {insn.op_str}".strip())
        for insn in engine.disasm(data, address)
    ]


def undecodable(instructions: list[Instruction]) -> list[Instruction]:
    """The entries Capstone could not decode and skipped over."""
    return [insn for insn in instructions if insn.text.split(" ")[0] in SKIPPED]
