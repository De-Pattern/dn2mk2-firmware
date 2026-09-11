"""Gate C: an image rebuilt with recompressed sections still verifies.

Gate A holds compression constant; this is the other half. The fast case
recompresses the 16 KB bootstrap section, which exercises the whole layout, checksum
and signing path. The MAIN OS case does the same to 3 MB and is marked slow.
"""

import pytest

from dnfw.firmware.build import build, replacement
from dnfw.firmware.load import load
from dnfw.firmware.verify import verify

BOOTSTRAP = 2
MAIN_OS = 3


def _rebuild_with(firmware, section_id, content):
    output = build(firmware, {section_id: replacement(firmware, section_id, content)})
    reloaded = load(output)
    report = verify(reloaded)
    assert report.ok, [c for c in report.checks if not c.ok]
    return output, reloaded


def test_recompressing_a_section_still_verifies(dn2):
    content = dn2.container.find(BOOTSTRAP).unpack()
    output, reloaded = _rebuild_with(dn2, BOOTSTRAP, content)
    assert reloaded.container.find(BOOTSTRAP).unpack() == content
    assert reloaded.key is not None, "signing must survive a rebuild"


def test_a_changed_byte_reaches_the_rebuilt_image(dn2):
    content = bytearray(dn2.container.find(BOOTSTRAP).unpack())
    content[1000] ^= 0xFF
    _, reloaded = _rebuild_with(dn2, BOOTSTRAP, bytes(content))
    assert reloaded.container.find(BOOTSTRAP).unpack() == bytes(content)


def test_unsigned_image_rebuilds_unsigned(dn1):
    content = dn1.container.find(BOOTSTRAP).unpack()
    _, reloaded = _rebuild_with(dn1, BOOTSTRAP, content)
    assert reloaded.key is None


def test_replacing_a_missing_section_is_refused(dn2):
    from dnfw.firmware.build import BuildError

    with pytest.raises(BuildError):
        replacement(dn2, 99, b"nothing")


def test_raw_sections_are_stored_raw_not_compressed(dn2):
    """The updater section does not depack, so a replacement for it must be
    stored verbatim. Compressing it would pass every checksum and brick the
    instrument, which is why the decision is taken from the original section."""
    updater = dn2.container.find(4)
    new = replacement(dn2, 4, updater.stored)
    assert new.stored == updater.stored


@pytest.mark.slow
def test_main_os_rebuild_verifies_and_is_no_larger_than_stock(dn2):
    section = dn2.container.find(MAIN_OS)
    content = section.unpack()
    output, reloaded = _rebuild_with(dn2, MAIN_OS, content)
    assert reloaded.container.find(MAIN_OS).unpack() == content
    # Our packer beats Elektron's on every section we hold; if that ever stops
    # being true the flash budget becomes a question and we want to know.
    assert len(reloaded.container.find(MAIN_OS).stored) <= len(section.stored)
