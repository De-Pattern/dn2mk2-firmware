"""`dnfw mods list` runs over every registered mod.

It crashed once a mod with no single SECTION (oneshot writes MAIN OS and the
DSP stream whole) joined the registry, so every mod is listed here, with the
sections read from its extents where it spans more than one.
"""

from dnfw.cli.main import main as dnfw
from dnfw.cli.mods import REGISTRY


def test_list_names_every_mod(capsys):
    assert dnfw(["mods", "list"]) == 0
    out = capsys.readouterr().out
    for mid in REGISTRY:
        assert f"  {mid}\n" in out


def test_multi_section_mod_lists_its_sections(capsys):
    assert dnfw(["mods", "list"]) == 0
    out = capsys.readouterr().out
    summary, device = out.split("  oneshot\n", 1)[1].splitlines()[:2]
    assert device.strip() == "device 0x15, sections 3, 7"
