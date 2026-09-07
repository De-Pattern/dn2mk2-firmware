"""Reading the disassembly `ghidra/ExportDisassembly.java` writes.

Ghidra is not driven from Python here. It runs headless, writes a listing, and
this parses it -- which keeps the comparison honest in a way that calling into
Ghidra would not: the file is exactly what Ghidra said, and it can be kept,
diffed and re-read after the fact.

One line per instruction, tab separated:

    40001000\t2f0a\tmove.l A2,-(SP)

An instruction Ghidra could not decode is written with the text
`; undecodable` and two bytes, which is what the export script advances by --
the same assumption Capstone makes, recorded rather than hidden.
"""

from pathlib import Path

from .instruction import Instruction

UNDECODABLE = "; undecodable"


def parse(text: str) -> list[Instruction]:
    instructions: list[Instruction] = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        try:
            address = int(fields[0], 16)
            data = bytes.fromhex(fields[1])
        except ValueError:
            continue
        instructions.append(Instruction(address, data, fields[2].strip()))
    return instructions


def load(path: Path) -> list[Instruction]:
    return parse(path.read_text(encoding="utf-8", errors="replace"))


def undecodable(instructions: list[Instruction]) -> list[Instruction]:
    return [insn for insn in instructions if insn.text == UNDECODABLE]
