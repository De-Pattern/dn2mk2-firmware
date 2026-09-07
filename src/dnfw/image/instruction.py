"""One disassembled instruction, and what it means for two disassemblers to
agree about a span.

Agreement is judged on **boundaries and bytes, not on text.** Two engines
spell the same instruction differently — `bra.b $40001602` against
`bras 0x40001602` — and arguing about syntax would bury the thing that
actually matters. What matters is whether they cut the byte stream in the same
places, because a disagreement there means one of them has desynchronised and
everything it prints after that point is fiction.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Instruction:
    address: int
    data: bytes
    text: str

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def end(self) -> int:
        return self.address + self.size


@dataclass(frozen=True)
class Divergence:
    address: int
    reference: Instruction | None
    candidate: Instruction | None

    def describe(self, reference_name: str, candidate_name: str) -> str:
        def show(insn: Instruction | None) -> str:
            if insn is None:
                return "(nothing at this address)"
            return f"{insn.data.hex(' '):<14} {insn.text}"

        return (
            f"0x{self.address:08x}\n"
            f"    {reference_name:<9} {show(self.reference)}\n"
            f"    {candidate_name:<9} {show(self.candidate)}"
        )


@dataclass(frozen=True)
class Agreement:
    """How far a candidate engine tracked the reference over one span."""

    compared: int
    matched: int
    divergences: tuple[Divergence, ...]
    first_divergence: int | None

    @property
    def ok(self) -> bool:
        return not self.divergences

    @property
    def ratio(self) -> float:
        return self.matched / self.compared if self.compared else 0.0


def compare(reference: list[Instruction], candidate: list[Instruction]) -> Agreement:
    """Compare two disassemblies of the same span.

    An instruction matches when the candidate has one starting at the same
    address with the same length. The candidate is allowed to name it
    differently; it is not allowed to disagree about where it ends.
    """
    by_address = {insn.address: insn for insn in candidate}

    matched = 0
    divergences: list[Divergence] = []
    for insn in reference:
        theirs = by_address.get(insn.address)
        if theirs is not None and theirs.size == insn.size:
            matched += 1
        else:
            divergences.append(Divergence(insn.address, insn, theirs))

    first = divergences[0].address if divergences else None
    return Agreement(len(reference), matched, tuple(divergences), first)
