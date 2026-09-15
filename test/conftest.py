"""Fixtures over the firmware corpus.

The corpus is not in this repository and never will be, so every test that
needs a real image skips cleanly when it is absent. A skipped corpus test says
so; it does not quietly pass.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

FIRMWARE = ROOT / "00_Resources" / "00_Firmware"

# Filename, and the facts each image should report. Written down rather than
# derived so a change in the tooling that silently alters them fails a test.
IMAGES = {
    "dn1": ("Digitone_and_Digitone_Keys_OS1.42A_dist.zip", 0x0D, "0097", "1.42A", False),
    "dn2": ("Digitone_II_OS1.10E_dist.zip", 0x15, "0050", "1.10E", True),
}


def _raw(key: str) -> bytes:
    from dnfw.cli.files import read_image

    name = IMAGES[key][0]
    path = FIRMWARE / name
    if not path.exists():
        pytest.skip(f"corpus image {name} not present under {FIRMWARE}")
    return read_image(path)


@pytest.fixture(scope="session")
def dn1_raw() -> bytes:
    return _raw("dn1")


@pytest.fixture(scope="session")
def dn2_raw() -> bytes:
    return _raw("dn2")


@pytest.fixture(scope="session")
def dn2(dn2_raw):
    from dnfw.firmware.load import load

    return load(dn2_raw)


@pytest.fixture(scope="session")
def dn1(dn1_raw):
    from dnfw.firmware.load import load

    return load(dn1_raw)
