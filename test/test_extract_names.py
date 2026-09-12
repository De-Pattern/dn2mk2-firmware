"""`dnfw extract` must produce a legal filename for every section.

`ele3.name` returns `?` for a section id we have not identified, which is the
right thing to show and an illegal filename on Windows. DN2 1.11 ships an
unnamed section 8, and extracting it failed outright until this was fixed --
so this is the normal case for new firmware, not an edge one.
"""

import pytest

from dnfw.cli.extract import _filename
from dnfw.container import ele3

ILLEGAL = set('<>:"/\\|?*')


@pytest.mark.parametrize(
    "label, expected",
    [
        ("?", "unnamed"),
        ("MAIN OS", "MAIN_OS"),
        ("blob", "blob"),
        ("meta", "meta"),
        ("", "unnamed"),
        ("a/b", "a_b"),
        ("*", "unnamed"),
    ],
)
def test_filename_is_legal_and_stable(label, expected):
    assert _filename(label) == expected


def test_every_known_section_name_survives():
    """A rename must not silently change the files a rebuild diffs against."""
    for section_id in list(ele3.NAMES) + [8, 99]:
        name = _filename(ele3.name(section_id))
        assert name, f"section {section_id} produced an empty filename"
        assert not (set(name) & ILLEGAL), f"section {section_id} -> {name!r}"
        assert name == name.strip(), f"section {section_id} -> {name!r}"
