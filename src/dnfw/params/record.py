"""One parameter record: the fixed-width struct that describes a single knob.

Layout and evidence are in `docs/lfo-parameters.md`. The short version: a
record is a run of big-endian words whose **last three** are pointers to
`[long name][page label][short name]`, and whose first is a handler function
pointer. The Digitone II uses 15 words, the Digitone 1 uses 13.

Only the fields that have been identified are exposed. The unidentified words
are deliberately reachable through `words` rather than given speculative names,
because a wrong name is worse than no name for the next reader.
"""

from dataclasses import dataclass

WORD = 4
UNSET = 0xFFFFFFFF

DN2_WORDS = 15
DN1_WORDS = 13

# Word indices, counted from the start of the record.
HANDLER = 0
GROUP = 2
PARAMETER_ID = 3
RANGE = 5
DEFAULT = 6
CONTROLLER = 9
NRPN = 10
# The three name pointers are the last three words, whatever the record size.
NAMES_FROM_END = 3


@dataclass(frozen=True)
class Record:
    """A parameter record, decoded."""

    address: int
    words: tuple[int, ...]
    long_name: str | None
    page: str | None
    short_name: str | None

    @property
    def handler(self) -> int:
        return self.words[HANDLER]

    @property
    def group(self) -> int | None:
        """The page group, or None when the record carries no group at all."""
        value = self.words[GROUP]
        return None if value == UNSET else value

    @property
    def parameter_id(self) -> int | None:
        value = self.words[PARAMETER_ID]
        return None if value == UNSET else value

    @property
    def value_range(self) -> int:
        return self.words[RANGE]

    @property
    def default(self) -> int:
        return self.words[DEFAULT]

    @property
    def controller(self) -> int | None:
        """MIDI controller number, or None when the parameter has none.

        `SLEW` is the interesting case: it shares `SPH`'s parameter id but
        carries no controller, which is what you would expect when only one of
        a pair of presentations is externally addressable.
        """
        value = self.words[CONTROLLER]
        return None if value == UNSET else value

    @property
    def nrpn(self) -> int | None:
        value = self.words[NRPN]
        return None if value == UNSET else value

    @property
    def addressable(self) -> bool:
        """Whether (group, id) names this record.

        The first records of the DN2 table carry UNSET in both, so something
        reaches them by array index instead. See `docs/lfo-parameters.md`.
        """
        return self.group is not None and self.parameter_id is not None


def size(word_count: int) -> int:
    return word_count * WORD
