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
NRPN = 9              # the 14-bit NRPN number; see `nrpn`
UNKNOWN_ID = 10       # not the CC, not the NRPN; see `physical_id`
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
    def nrpn(self) -> int | None:
        """The parameter's **14-bit NRPN number**, `MSB * 128 + LSB`.

        **[SETTLED 2026-09-14 against Elektron's own manual.]** Appendix C of the
        Digitone II manual lists CC and NRPN for every addressable parameter.
        Parsing 45 of its rows and looking each `MSB * 128 + LSB` up in this
        column matches **45 of 45**, with the names agreeing too — `Mute`,
        `Trig Note`, `Frequency`, `Base`, `Width`, `Overdrive`.

        The history is worth keeping, because the field was named wrongly twice:

        | when | name | why it was wrong |
        |---|---|---|
        | originally | `controller`, "MIDI controller number" | **122 of 285 records hold a value above 127**, and CC numbers stop at 127 |
        | this morning | `logical_id` | renamed on an outside author's say-so, which was a description rather than an identification |
        | now | **`nrpn`** | 45/45 against the vendor's published table |

        The irony is that the record *next* to this one was called `nrpn` from
        the start. The original author had the right name on the wrong word.

        **The CC is not in this record at all.** Every one of the fifteen words
        was tested against the manual's CC column and none matches, so CC
        assignment lives in a table this project has not found.
        """
        value = self.words[NRPN]
        return None if value == UNSET else value

    @property
    def logical_id(self) -> int | None:
        """Deprecated alias for `nrpn`, kept so today's scripts still run."""
        return self.nrpn

    @property
    def controller(self) -> int | None:
        """Deprecated alias. **Not a MIDI controller number** -- see `nrpn`."""
        return self.nrpn

    @property
    def physical_id(self) -> int | None:
        """An identifier this project has **not** been able to name.

        Its history is three wrong guesses deep and the honest state is "unknown":

        | when | called | status |
        |---|---|---|
        | originally | `nrpn` | **wrong** — the NRPN is the word before this one, 45/45 against the manual |
        | this morning | `physical_id`, "physical control id" | an outside author's description, adopted without evidence |
        | now | `physical_id`, unidentified | **it is not the CC** |

        The CC test was decisive and cheap. Elektron's Appendix C gives a CC for
        every addressable parameter; all fifteen words of the record were
        compared against it across 45 rows and **none matched any of them**.
        Chorus Depth is CC 16 and holds 110 here; Mute is CC 94 and holds 8.

        So CC assignment lives in a table this project has not found, and this
        field is something else. It is left named after the guess that has not
        yet been disproved, which is the weakest reason a name can have.
        """
        value = self.words[UNKNOWN_ID]
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
