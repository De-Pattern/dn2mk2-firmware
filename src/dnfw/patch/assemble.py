"""Assemble ColdFire source into raw bytes with the real GNU toolchain.

For anything past a few instructions, a hand-encoder is the wrong tool -- the
lesson of emuyia/ems-octakit (read for architecture only; see
`docs/references.md`), which assembles hand-written `.S` with `m68k-*-as` and a
linker script rather than emitting bytes by hand. We already depend on
`m68k-linux-gnu-*` for Gate F, so the assembler and objcopy from the same
binutils are reached the same way -- natively if present, else through WSL.

`patch/coldfire.py` stays the no-toolchain path and the way to build a one-line
hook branch; this module is for a real payload. One subject: turn assembly text
into the bytes it assembles to.

The bytes come back position-correct for a payload that names external targets
**absolutely** (`jmp 0x400dxxxx`, `.long 0x80000000`) and branches **within
itself** by label -- which is what a cave stub does. Pass `base` only when the
stub must resolve its *own* labels to absolute cave addresses; then the object
is linked at that address before the bytes are extracted.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# ColdFire V4e. 54455 is a V4e part `as` accepts; the encoding it emits is the
# core ISA, identical to what the DN2's CPU runs. objdump validates it (Gate F).
CPU = "54455"
AS_NAMES = ("m68k-linux-gnu-as", "m68k-elf-as", "m68k-none-elf-as")
LD_NAMES = ("m68k-linux-gnu-ld", "m68k-elf-ld", "m68k-none-elf-ld")
OBJCOPY_NAMES = ("m68k-linux-gnu-objcopy", "m68k-elf-objcopy", "m68k-none-elf-objcopy")


class AssemblerMissing(RuntimeError):
    """No m68k binutils reachable, natively or through WSL."""


class AssemblyError(ValueError):
    """The assembler or linker rejected the source."""


@dataclass(frozen=True)
class Toolchain:
    """How to invoke as/ld/objcopy, and how to name a file to them."""

    as_argv: tuple[str, ...]
    ld_argv: tuple[str, ...]
    objcopy_argv: tuple[str, ...]
    via_wsl: bool

    def path_for(self, path: Path) -> str:
        if not self.via_wsl:
            return str(path)
        resolved = path.resolve()
        drive = resolved.drive.rstrip(":").lower()
        rest = str(resolved)[len(resolved.drive) :].replace("\\", "/")
        return f"/mnt/{drive}{rest}"

    def run(self, argv: tuple[str, ...], arguments: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*argv, *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
        )


def _find_native(names: tuple[str, ...]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def find_toolchain() -> Toolchain | None:
    """The first usable binutils trio: native if present, else through WSL."""
    native = {kind: _find_native(names) for kind, names in
              (("as", AS_NAMES), ("ld", LD_NAMES), ("objcopy", OBJCOPY_NAMES))}
    if all(native.values()):
        return Toolchain(
            as_argv=(native["as"],),
            ld_argv=(native["ld"],),
            objcopy_argv=(native["objcopy"],),
            via_wsl=False,
        )

    wsl = shutil.which("wsl")
    if wsl is None:
        return None

    def wsl_name(names: tuple[str, ...]) -> str | None:
        for name in names:
            probe = subprocess.run(
                [wsl, "-e", name, "--version"],
                capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
            )
            if probe.returncode == 0:
                return name
        return None

    picked = {kind: wsl_name(names) for kind, names in
              (("as", AS_NAMES), ("ld", LD_NAMES), ("objcopy", OBJCOPY_NAMES))}
    if all(picked.values()):
        return Toolchain(
            as_argv=(wsl, "-e", picked["as"]),
            ld_argv=(wsl, "-e", picked["ld"]),
            objcopy_argv=(wsl, "-e", picked["objcopy"]),
            via_wsl=True,
        )
    return None


def require_toolchain() -> Toolchain:
    tool = find_toolchain()
    if tool is None:
        raise AssemblerMissing(
            "no m68k binutils (as/ld/objcopy) found, natively or in WSL. On Windows: "
            "`wsl -u root apt-get install -y binutils-m68k-linux-gnu`. "
            "Until then use patch/coldfire.py's encoder for small stubs."
        )
    return tool


def assemble(source: str, *, base: int | None = None, cpu: str = CPU,
             toolchain: Toolchain | None = None) -> bytes:
    """Assemble GNU m68k `source` and return the raw `.text` bytes.

    `base` links the object at that virtual address before extraction, so the
    stub's own labels resolve absolutely; leave it None for a stub that only
    references external targets absolutely and branches within itself.
    """
    tool = toolchain or require_toolchain()
    with tempfile.TemporaryDirectory(prefix="dnfw_asm_") as tmp:
        d = Path(tmp)
        src = d / "stub.s"
        obj = d / "stub.o"
        binout = d / "stub.bin"
        # A leading .text keeps everything in one allocatable section, so
        # objcopy -O binary emits exactly the instruction stream in order.
        src.write_text(".text\n" + source + "\n", encoding="ascii")

        r = tool.run(tool.as_argv, [f"-mcpu={cpu}", tool.path_for(src), "-o", tool.path_for(obj)])
        if r.returncode:
            raise AssemblyError(_clean(r.stderr) or "assembler failed")

        extract_from = obj
        if base is not None:
            linked = d / "stub.elf"
            r = tool.run(tool.ld_argv, [
                f"-Ttext=0x{base:08x}", "-e", "0", "--no-warn-rwx-segments",
                tool.path_for(obj), "-o", tool.path_for(linked),
            ])
            # ld warns about a missing/zero entry; that is expected for a raw
            # stub and not a failure. Only a non-zero exit is fatal.
            if r.returncode:
                raise AssemblyError(_clean(r.stderr) or "linker failed")
            extract_from = linked

        r = tool.run(tool.objcopy_argv, [
            "-O", "binary", "-j", ".text", tool.path_for(extract_from), tool.path_for(binout),
        ])
        if r.returncode:
            raise AssemblyError(_clean(r.stderr) or "objcopy failed")
        return binout.read_bytes()


def available() -> bool:
    """Whether a toolchain can be found -- for tests to skip when it cannot."""
    return find_toolchain() is not None


def _clean(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Drop the "Assembler messages:" banner; keep the actual diagnostics.
    return "; ".join(ln for ln in lines if not ln.endswith("messages:"))
