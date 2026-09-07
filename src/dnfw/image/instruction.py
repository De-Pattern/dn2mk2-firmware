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


# objdump marks bytes it will not decode with a data directive. A divergence
# there is the two engines disagreeing about whether something is an
# instruction at all -- usually alignment padding between functions -- which is
# a different and much smaller problem than misreading real code.
DATA_DIRECTIVES = (".short", ".byte", ".word", ".long")


@dataclass(frozen=True)
class Agreement:
    """How far a candidate engine tracked the reference over one span."""

    compared: int
    matched: int
    divergences: tuple[Divergence, ...]
    first_divergence: int | None
    longest_run: int

    @property
    def ok(self) -> bool:
        return not self.divergences

    @property
    def ratio(self) -> float:
        return self.matched / self.compared if self.compared else 0.0

    @property
    def clusters(self) -> tuple[tuple[Divergence, ...], ...]:
        """Divergences grouped into consecutive runs.

        Attribution matters more than counting. When a candidate misreads one
        instruction it usually gets the next one wrong too, and calling that
        two independent failures both inflates the number and hides what
        actually went wrong. A cluster is one failure; what it *starts* on is
        what it means.
        """
        groups: list[list[Divergence]] = []
        previous_end: int | None = None
        for divergence in self.divergences:
            reference = divergence.reference
            if previous_end is not None and reference is not None and reference.address == previous_end:
                groups[-1].append(divergence)
            else:
                groups.append([divergence])
            previous_end = reference.end if reference is not None else None
        return tuple(tuple(group) for group in groups)

    @property
    def on_data(self) -> tuple[tuple[Divergence, ...], ...]:
        """Clusters that begin on bytes the reference declined to decode.

        Almost always alignment padding between functions: the two engines
        disagree about whether something is an instruction at all, which is a
        far smaller problem than misreading code.
        """
        return tuple(c for c in self.clusters if _starts_on_data(c))

    @property
    def on_code(self) -> tuple[tuple[Divergence, ...], ...]:
        """Clusters that begin on a real instruction.

        This is the number that decides whether a decoder is usable.
        """
        return tuple(c for c in self.clusters if not _starts_on_data(c))


def _starts_on_data(cluster: tuple[Divergence, ...]) -> bool:
    first = cluster[0].reference
    return first is not None and first.text.startswith(DATA_DIRECTIVES)


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
    return Agreement(len(reference), matched, tuple(divergences), first, _longest_run(reference, by_address))


def _longest_run(reference: list[Instruction], by_address: dict) -> int:
    """The most consecutive reference instructions the candidate got wrong.

    This separates a decoder that stumbles and recovers from one that has
    genuinely lost the stream. A short maximum run means the candidate
    resynchronises; a long one means everything after it is fiction.
    """
    longest = run = 0
    for insn in reference:
        theirs = by_address.get(insn.address)
        if theirs is not None and theirs.size == insn.size:
            run = 0
        else:
            run += 1
            longest = max(longest, run)
    return longest
