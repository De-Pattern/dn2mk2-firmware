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
LOGICAL_ID = 9        # was CONTROLLER; see `logical_id`
PHYSICAL_ID = 10      # was NRPN; see `physical_id`
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
    def logical_id(self) -> int | None:
        """The parameter's **logical id**, not a MIDI controller number.

        **[CORRECTED 2026-09-14 — was `controller`, documented as "MIDI
        controller number".]** It cannot be one: **122 of the 285 records that
        carry this field hold a value above 127**, and MIDI controller numbers
        stop at 127. That was checkable from our own table on the day it was
        written and never checked.

        The name comes from an independent account of the ColdFire→SHARC
        parameter transport (`docs/sharc-crosscheck.md`), which reads the same
        field as a logical id: Chorus Depth carries `0x129`, and our table shows
        297 = `0x129` in exactly that record.

        `SLEW` remains the interesting case — it shares `SPH`'s parameter id but
        carries no value here, which is what you would expect when only one of a
        pair of presentations is externally addressable.
        """
        value = self.words[LOGICAL_ID]
        return None if value == UNSET else value

    @property
    def controller(self) -> int | None:
        """Deprecated alias for `logical_id`, kept so older scripts still run."""
        return self.logical_id

    @property
    def physical_id(self) -> int | None:
        """The parameter's **physical control id**.

        **[RENAMED 2026-09-14 — was `nrpn`.]** Weaker evidence than the
        `logical_id` correction above: nothing in our own data disproves "NRPN",
        and the values are all in NRPN's range. The rename follows the same
        outside account, which traces this field through the ColdFire→SPORT→SHARC
        path and reads it as a physical control id — Chorus Depth `0x6E`, which
        is the 110 our table shows.

        Their account also explains the gap at `0x74`: an anonymous, disabled
        record sits between Reverb Send and Chorus Mix, and our table does show
        two records sharing parameter id 31, one of them carrying `0x74`.

        *Evidence level: reported, not verified here.*
        """
        value = self.words[PHYSICAL_ID]
        return None if value == UNSET else value

    @property
    def nrpn(self) -> int | None:
        """Deprecated alias for `physical_id`, kept so older scripts still run."""
        return self.physical_id

    @property
    def addressable(self) -> bool:
        """Whether (group, id) names this record.

        The first records of the DN2 table carry UNSET in both, so something
        reaches them by array index instead. See `docs/lfo-parameters.md`.
        """
        return self.group is not None and self.parameter_id is not None


def size(word_count: int) -> int:
    return word_count * WORD
