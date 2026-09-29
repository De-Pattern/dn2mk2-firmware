"""`dnfw mods list` runs over every registered mod.

It crashed once a mod with no single SECTION joined the registry, so every mod
is listed here, and a mod spanning several sections lists them from its extents.
"""

from dnfw.cli.main import main as dnfw
from dnfw.cli.mods import REGISTRY, _sections


def test_list_names_every_mod(capsys):
    assert dnfw(["mods", "list"]) == 0
    out = capsys.readouterr().out
    for mid in REGISTRY:
        assert f"  {mid}\n" in out


def test_multi_section_mod_lists_its_sections():
    class Extent:
        def __init__(self, section):
            self.section = section

    class Spanning:                     # no SECTION: its extents name the sections
        @staticmethod
        def extents():
            return [Extent(7), Extent(3), Extent(7)]

    assert _sections(Spanning) == (3, 7)
