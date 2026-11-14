"""v0.39: the mod's own version (owner, 2026-11-02): one file, `VERSION` at the repository's
root (e.g. `0.39`), read when a build is composed. Each release bumps that file only.

It is shown on the instrument in two places, both drawn by our code: a small label, `MOD
0.39`, over the start-up animation's last (holding) frame (dnfw.bootanim.label_chunk, the
stamp's ANZL path: s!Rwa²'s frames stay as he drew them), and `MOD v0.39` under the two
stores at the sample browser's top (csrc/sampler/smp_page.c, MOD_VERSION from the C
renderer's header). Elektron's own OS version string is never touched (Transfer and the
updater read it).

A build without the file, or with anything but DIGITS.DIGITS in it, fails. A test build
(owner, 2026-11-14: CLAUDE.md, "Test builds") is DIGITS.DIGITS-tN, e.g. `0.54-t1`.
"""

from __future__ import annotations

import pathlib
import re

FILE = pathlib.Path(__file__).resolve().parents[2] / "VERSION"


class VersionError(ValueError):
    """VERSION is missing or not DIGITS.DIGITS"""


def mod_version() -> str:
    try:
        text = FILE.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as e:
        raise VersionError(f"{FILE}: the mod's version file cannot be read ({e}): the build needs it") from None
    v = text.strip()
    if not re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}(-t[0-9]{1,2})?", v) or text not in (v, v + "\n"):
        raise VersionError(f"{FILE}: {text!r} is not a version like 0.39 or a test build's 0.54-t1 "
                           "(one line, digits, a dot, digits)")
    return v


def c_define() -> str:
    """the C renderer's header line (dnfw.waverider.coldfire.compose)"""
    return f'#define MOD_VERSION "{mod_version()}"\n'
