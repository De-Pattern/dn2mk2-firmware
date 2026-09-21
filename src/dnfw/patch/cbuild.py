"""Compile C (and GNU assembly) for the DN2's ColdFire, linked at a fixed address.

The new logic of a large mod -- LFO4's extension table, its save / load mapping,
its page -- is written in C (`docs/lfo4-build-plan.md` §8) and only the patch-site
stubs stay assembly. This module turns those sources into the bytes that will
sit at one address at run time, plus the symbol addresses the in-image hooks
need. One subject: sources in, linked bytes and symbols out.

The code calls firmware routines by address (`csrc/include/dn2_111.h`) and is
called by hooks, so it must share the firmware's calling convention. It does:
the firmware was built by GCC for ColdFire, and `m68k-linux-gnu-gcc` keeps the
same one -- arguments on the stack, result in `d0`, `d0`/`d1`/`a0`/`a1` scratch,
`d2`-`d7`/`a2`-`a6` preserved.

Freestanding: no libc, no startup files, no builtins turned into library calls.
`libgcc` is linked for the few helpers the compiler may still emit. Data and
BSS follow the code; BSS is not in the bytes, and `Linked.bss` says how much the
loader must zero after them.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .assemble import AssemblerMissing, AssemblyError, Toolchain, _clean, _find_native

CPU = "5475"                          # ColdFire V4e, the DN2's core
GCC_NAMES = ("m68k-linux-gnu-gcc", "m68k-elf-gcc", "m68k-none-elf-gcc")
NM_NAMES = ("m68k-linux-gnu-nm", "m68k-elf-nm", "m68k-none-elf-nm")
OBJCOPY_NAMES = ("m68k-linux-gnu-objcopy", "m68k-elf-objcopy", "m68k-none-elf-objcopy")
OBJDUMP_NAMES = ("m68k-linux-gnu-objdump", "m68k-elf-objdump", "m68k-none-elf-objdump")

# A scaled index of 8 is a 68020 addressing mode that the ColdFire V4e does
# not implement -- and nothing in this toolchain objects to it: GCC emits it
# for any 8-byte-strided array indexed by a variable, gas assembles it, and
# the emulator's generic m68k core runs it. Only the instrument refuses,
# with an address error (`lfo4-bridge`, 2026-09-20: V03 M0 P468004FC). So
# every build is disassembled and checked here, where it cannot be skipped.
SCALE8 = re.compile(r":[lw]:8\)")

CFLAGS = (
    f"-mcpu={CPU}", "-Os", "-std=gnu11", "-ffreestanding", "-fno-builtin", "-nostdlib",
    "-fno-pic", "-fno-common", "-fno-tree-loop-distribute-patterns",
    "-ffunction-sections", "-fdata-sections", "-fomit-frame-pointer",
    "-fno-asynchronous-unwind-tables", "-Wall", "-Wextra", "-Werror",
)

LINKER_SCRIPT = """\
SECTIONS
{{
  . = 0x{base:08x};
  .text : {{ KEEP(*(.text.entry)) *(.text .text.*) }}
  .rodata : ALIGN(4) {{ *(.rodata .rodata.*) }}
  .data : ALIGN(4) {{ *(.data .data.*) }}
  . = ALIGN(4);
  __image_end = .;
  .bss (NOLOAD) : ALIGN(4) {{ __bss_start = .; *(.bss .bss.*) . = ALIGN(4); __bss_end = .; }}
  /DISCARD/ : {{ *(.comment) *(.note*) *(.eh_frame*) *(.gnu*) }}
}}
"""


class CompilerMissing(AssemblerMissing):
    """No m68k GCC reachable, natively or through WSL."""


@dataclass(frozen=True)
class CToolchain:
    gcc: tuple[str, ...]
    nm: tuple[str, ...]
    objcopy: tuple[str, ...]
    via_wsl: bool
    objdump: tuple[str, ...] = ()

    def path_for(self, path: Path) -> str:
        return Toolchain((), (), (), self.via_wsl).path_for(path)

    def run(self, argv: tuple[str, ...], arguments: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run([*argv, *arguments], capture_output=True, text=True,
                              errors="replace", stdin=subprocess.DEVNULL)


@dataclass(frozen=True)
class Linked:
    """What a build produced: `image` loads at `base`, then `bss` zero bytes.

    `kinds` is `nm`'s own letter per symbol -- `t`/`T` for code, `b`/`d`/`r`
    for data. It exists because the boot gate reports which of a build's
    routines never ran, and a counter listed beside them as "NOT EXERCISED" is
    noise in the one place this project cannot afford any: `lfo4-table`'s gate
    named 24 symbols, and 15 of them were variables.
    """

    base: int
    image: bytes
    bss: int
    symbols: dict[str, int]
    kinds: dict[str, str] = field(default_factory=dict)

    def routines(self) -> dict[str, int]:
        """-> only the symbols that are code, and so can be said to have run."""
        return {n: a for n, a in self.symbols.items() if self.kinds.get(n, "").lower() == "t"}

    def __getitem__(self, name: str) -> int:
        return self.symbols[name]

    @property
    def end(self) -> int:
        return self.base + len(self.image) + self.bss


def find_toolchain() -> CToolchain | None:
    # objdump is wanted, not required: it drives the ColdFire check, and a
    # missing checker must not stop a build that would otherwise work.
    native = [_find_native(n) for n in (GCC_NAMES, NM_NAMES, OBJCOPY_NAMES)]
    if all(native):
        dump = _find_native(OBJDUMP_NAMES)
        return CToolchain((native[0],), (native[1],), (native[2],), via_wsl=False,
                          objdump=(dump,) if dump else ())
    wsl = shutil.which("wsl")
    if wsl is None:
        return None

    def in_wsl(names):
        for name in names:
            probe = subprocess.run([wsl, "-e", name, "--version"], capture_output=True,
                                   text=True, errors="replace", stdin=subprocess.DEVNULL)
            if probe.returncode == 0:
                return name
        return None

    picked = [in_wsl(n) for n in (GCC_NAMES, NM_NAMES, OBJCOPY_NAMES)]
    if all(picked):
        dump = in_wsl(OBJDUMP_NAMES)
        return CToolchain(*((wsl, "-e", p) for p in picked), via_wsl=True,
                          objdump=(wsl, "-e", dump) if dump else ())
    return None


def _refuse_unrunnable(tool: CToolchain, elf: Path) -> None:
    """Raise if the link contains an instruction the ColdFire cannot execute.

    The check reads the disassembly, not the bytes, so it sees what the CPU
    would decode rather than a pattern that happens to sit inside data.
    """
    if not tool.objdump:
        return
    r = tool.run(tool.objdump, ["-d", "-m", "m68k:cfv4e", tool.path_for(elf)])
    if r.returncode:
        return                     # a check that cannot run must not fail a build
    bad = [ln.strip() for ln in r.stdout.splitlines() if SCALE8.search(ln)]
    if bad:
        raise AssemblyError(
            "this build contains %d instruction(s) the ColdFire V4e cannot "
            "execute -- a scaled index of 8, which is a 68020 mode:\n    %s\n"
            "Split the 8-byte-strided array into parallel arrays, or index it "
            "through an explicit pointer (csrc/lfo4/carry.c has the worked case)."
            % (len(bad), ("\n    ").join(bad[:8])))


def require_toolchain() -> CToolchain:
    tool = find_toolchain()
    if tool is None:
        raise CompilerMissing(
            "no m68k GCC found, natively or in WSL. On Windows: "
            "`wsl -u root apt-get install -y gcc-m68k-linux-gnu`.")
    return tool


def available() -> bool:
    return find_toolchain() is not None


def build(sources: list[Path], *, base: int, entries: list[str] = (),
          include: list[Path] = (), defines: dict[str, int | str] | None = None,
          toolchain: CToolchain | None = None) -> Linked:
    """Compile and link `sources` (.c and .S) to run at `base`.

    `entries` are the symbols something outside the code reaches -- hooks, an
    init. Unreferenced sections are dropped, so anything not reachable from
    them (or from a `.text.entry` section) is not in the image.
    """
    if base % 4:
        raise ValueError(f"base 0x{base:08x} is not longword-aligned")
    tool = toolchain or require_toolchain()
    flags = list(CFLAGS)
    flags += [f"-I{tool.path_for(Path(p))}" for p in include]
    flags += [f"-D{k}={v}" for k, v in (defines or {}).items()]
    with tempfile.TemporaryDirectory(prefix="dnfw_cc_") as tmp:
        d = Path(tmp)
        objects = []
        for i, src in enumerate(sources):
            obj = d / f"{i}_{Path(src).stem}.o"
            r = tool.run(tool.gcc, [*flags, "-c", tool.path_for(Path(src)), "-o", tool.path_for(obj)])
            if r.returncode:
                raise AssemblyError(f"{Path(src).name}: {_clean(r.stderr) or 'compile failed'}")
            objects.append(tool.path_for(obj))

        script = d / "link.ld"
        script.write_text(LINKER_SCRIPT.format(base=base), newline="\n")
        elf = d / "out.elf"
        r = tool.run(tool.gcc, [f"-mcpu={CPU}", "-nostdlib", "-static", "-Wl,--no-warn-rwx-segments",
                                "-Wl,--gc-sections", *(f"-Wl,--undefined={e}" for e in entries),
                                "-T", tool.path_for(script), *objects,
                                "-lgcc", "-o", tool.path_for(elf)])
        if r.returncode:
            raise AssemblyError(_clean(r.stderr) or "link failed")

        binout = d / "out.bin"
        r = tool.run(tool.objcopy, ["-O", "binary", "-R", ".bss", tool.path_for(elf), tool.path_for(binout)])
        if r.returncode:
            raise AssemblyError(_clean(r.stderr) or "objcopy failed")

        _refuse_unrunnable(tool, elf)

        r = tool.run(tool.nm, ["--defined-only", tool.path_for(elf)])
        if r.returncode:
            raise AssemblyError(_clean(r.stderr) or "nm failed")
        symbols, kinds = {}, {}
        for line in r.stdout.splitlines():
            m = re.match(r"([0-9a-fA-F]+) (\w) (\S+)$", line.strip())
            if m:
                symbols[m.group(3)] = int(m.group(1), 16)
                kinds[m.group(3)] = m.group(2)

        image = binout.read_bytes() if binout.exists() else b""
        want = symbols["__image_end"] - base
        if len(image) > want:
            raise AssemblyError(f"image is {len(image)} B, past __image_end ({want} B)")
        image += bytes(want - len(image))
        missing = [e for e in entries if e not in symbols]
        if missing:
            raise AssemblyError(f"entries not defined: {', '.join(missing)}")
        return Linked(base, image, symbols["__bss_end"] - symbols["__bss_start"],
                      symbols, kinds)
