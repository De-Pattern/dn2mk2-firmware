"""Disassembly via GNU binutils objdump — the reference engine.

This is the only decoder currently trusted for this CPU. Everything else gets
checked against it; see `docs/mainos-image.md` and `image.instruction`.

binutils is not bundled and is not a Python dependency. It is looked for under
the several names it ships as, because the package differs by platform: a
bare-metal cross build installs `m68k-elf-objdump`, while Debian and Ubuntu's
`binutils-m68k-linux-gnu` installs `m68k-linux-gnu-objdump`.

**It is also looked for inside WSL.** On Windows the one-package route to a
ColdFire-capable objdump is `apt install binutils-m68k-linux-gnu` in a WSL
distro, and there is no reason to make the caller care which side of that line
the tool lives on. When it is reached through WSL the temporary file is handed
over as a `/mnt/<drive>/...` path.
"""

import shutil
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .instruction import Instruction

ARCHITECTURE = "m68k:cfv4e"
NAMES = ("m68k-elf-objdump", "m68k-linux-gnu-objdump", "m68k-none-elf-objdump")

# objdump delimits with tabs: "40000400:\t46 fc 27 00 \tmovew #9984,%sr".
# A wrapped encoding is a line with an address and bytes but no third field.
_ADDRESS = re.compile(r"^\s*([0-9a-fA-F]+):$")
_BYTES = re.compile(r"^[0-9a-fA-F]{2}(?: ?[0-9a-fA-F]{2})*$")


class ObjdumpMissing(RuntimeError):
    """No m68k objdump reachable, natively or through WSL."""


@dataclass(frozen=True)
class Tool:
    """How to invoke objdump, and how to name a file to it."""

    argv: tuple[str, ...]
    name: str
    via_wsl: bool

    def describe(self) -> str:
        return f"{self.name} (via WSL)" if self.via_wsl else self.name

    def path_for(self, path: Path) -> str:
        if not self.via_wsl:
            return str(path)
        resolved = path.resolve()
        drive = resolved.drive.rstrip(":").lower()
        rest = str(resolved)[len(resolved.drive) :].replace("\\", "/")
        return f"/mnt/{drive}{rest}"

    def run(self, arguments: list[str]) -> subprocess.CompletedProcess:
        # stdin=DEVNULL matters on Windows: wsl.exe inherits the parent's stdin
        # handle, and under a test runner that captures stdio there is no valid
        # handle to inherit -- which surfaces as "[WinError 6] The handle is
        # invalid" at a point that looks nothing like the cause.
        return subprocess.run(
            [*self.argv, *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
        )


def find_tool() -> Tool | None:
    """The first usable objdump: native if there is one, else through WSL."""
    for name in NAMES:
        found = shutil.which(name)
        if found:
            return Tool(argv=(found,), name=name, via_wsl=False)

    wsl = shutil.which("wsl")
    if wsl is None:
        return None
    for name in NAMES:
        probe = subprocess.run(
            [wsl, "-e", name, "--version"],
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            return Tool(argv=(wsl, "-e", name), name=name, via_wsl=True)
    return None


def require_tool() -> Tool:
    tool = find_tool()
    if tool is None:
        raise ObjdumpMissing(
            "no m68k objdump found, natively or in WSL (tried: " + ", ".join(NAMES) + "). "
            "It is the only decoder confirmed to read ColdFire V4e correctly. On Windows: "
            "`wsl -u root apt-get install -y binutils-m68k-linux-gnu`. "
            "See docs/mainos-image.md for why another disassembler is not a substitute."
        )
    return tool


def supports_coldfire(tool: Tool) -> bool:
    """Whether this build actually decodes ColdFire, tested by decoding some.

    Not read off `objdump -i`: that lists the coarse BFD architecture (`m68k`)
    and says nothing about sub-machines, so a build that reads ColdFire
    perfectly well reports nothing about it. The honest test is to hand it a
    ColdFire-only instruction and see whether it comes back decoded. `71 00` is
    in the MOVEQ opcode space with bit 8 set, which is undefined on every
    68000-series part; on ColdFire it is MVS.
    """
    decoded = disassemble(b"\x71\x00\x4e\x75", 0, tool=tool)
    return bool(decoded) and "mvs" in decoded[0].text.lower()


def disassemble(data: bytes, address: int, tool: Tool | None = None) -> list[Instruction]:
    """Disassemble `data` as ColdFire V4e loaded at `address`."""
    tool = tool or require_tool()
    with tempfile.TemporaryDirectory() as directory:
        blob = Path(directory) / "span.bin"
        blob.write_bytes(data)
        result = tool.run(
            # -z: do not elide runs of identical bytes as "...". Without it a
            # zero run vanishes from the listing and a boundary comparison
            # would report a divergence that is only a display convention.
            ["-D", "-z", "-b", "binary", "-m", ARCHITECTURE,
             f"--adjust-vma={address:#x}", tool.path_for(blob)]
        )
    if result.returncode != 0:
        raise RuntimeError(f"{tool.describe()} failed: {result.stderr.strip()}")
    return parse(result.stdout)


def parse(output: str) -> list[Instruction]:
    """Parse objdump's listing into instructions.

    Continuation lines — objdump wraps a long encoding onto a second line with
    an address but no disassembly — are folded into the instruction above,
    otherwise one long instruction would be reported as two.
    """
    instructions: list[Instruction] = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        match = _ADDRESS.match(fields[0])
        if not match:
            continue
        encoding = fields[1].strip()
        if not _BYTES.match(encoding):
            continue
        address = int(match.group(1), 16)
        data = bytes.fromhex(encoding.replace(" ", ""))
        text = fields[2].strip() if len(fields) > 2 else ""
        if not text and instructions and instructions[-1].end == address:
            previous = instructions[-1]
            instructions[-1] = Instruction(previous.address, previous.data + data, previous.text)
            continue
        instructions.append(Instruction(address, data, text))
    return instructions
