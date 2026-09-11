"""The curated symbol map: that it loads, guards, merges, and refuses drift.

The guard is a SHA-256 of bytes at the address, never the bytes themselves --
the repository holds no Elektron code -- so these tests carry hashes, not
firmware.
"""

import hashlib
import pathlib

import pytest

from dnfw.symbolmap import build, discover, ghidra
from dnfw.symbolmap.record import BOOTSTRAP_BASE, MAIN_OS_BASE, Symbol, SymbolError, validate

ROOT = pathlib.Path(__file__).resolve().parent.parent
SYMBOLS_DIR = ROOT / "symbols"

BOOTSTRAP = 2
MAIN_OS = 3

ZERO = "0" * 64  # a valid-shaped guard that will not match real bytes
ONES = "f" * 64


def make(**over) -> Symbol:
    args = dict(id="x", name="n", kind="function", build="40050", version="1.10E",
                section=MAIN_OS, base=MAIN_OS_BASE, address=0x40001000, guard=ZERO)
    args.update(over)
    return Symbol(**args)


# --- the records themselves --------------------------------------------------


def test_the_shipped_symbols_load_and_validate():
    symbols = discover.load(SYMBOLS_DIR)
    assert symbols, "symbols/ should carry curated names"
    validate(symbols)
    assert {s.section for s in symbols} == {BOOTSTRAP, MAIN_OS}


def test_a_symbol_needs_a_valid_sha_guard():
    with pytest.raises(SymbolError):
        make(guard="not-a-sha")


def test_kind_is_checked():
    with pytest.raises(SymbolError):
        make(kind="subroutine")


def test_two_names_on_one_address_are_refused():
    with pytest.raises(SymbolError):
        validate([make(id="a", name="one"), make(id="b", name="two")])


def test_shipped_symbols_carry_no_raw_firmware_bytes():
    """The guard must be a hash; a curated file must not embed section bytes."""
    for path in SYMBOLS_DIR.glob("*.py"):
        assert "bytes.fromhex" not in path.read_text(encoding="utf-8"), path.name


# --- merging against a real image --------------------------------------------


@pytest.fixture(scope="module")
def curated():
    return discover.load(SYMBOLS_DIR)


def test_every_bootstrap_guard_matches_the_image(dn2, curated):
    names = build.merge(dn2, curated, BOOTSTRAP)
    assert names.base == BOOTSTRAP_BASE
    assert len(names.curated_ok) == 3
    assert not names.drift, [p.symbol.id for p in names.drift]
    assert {p.symbol.name for p in names.curated_ok} == {
        "recovery_receive_loop", "sysex_packet_handler", "verify_and_flash_container"
    }


def test_main_os_merges_curated_with_rtti(dn2, curated):
    names = build.merge(dn2, curated, MAIN_OS)
    assert names.base == MAIN_OS_BASE
    assert len(names.curated_ok) == 3
    assert not names.drift
    assert len(names.derived) > 400, "MAIN OS carries hundreds of RTTI names"


def test_a_wrong_guard_shows_as_drift(dn2):
    names = build.merge(dn2, [make(id="wrong", guard=ONES)], MAIN_OS)
    assert not names.curated_ok
    assert [p.symbol.id for p in names.drift] == ["wrong"]


def test_names_from_another_build_are_not_asserted(dn2):
    """Filtered by build/version before the guard, so a 1.10E map is silent on
    an image that is not 1.10E rather than claiming a false match."""
    other = make(id="future", build="99999", version="9.99", address=0x401E29D4)
    names = build.merge(dn2, [other], MAIN_OS)
    assert not names.curated_ok and not names.drift


def test_guard_matches_is_a_hash_of_the_named_bytes(dn2, curated):
    """A positive control: the guard really is the digest of the section bytes."""
    section = dn2.container.find(MAIN_OS)
    content = section.unpack()
    table = next(s for s in curated if s.name == "parameter_table")
    window = content[table.offset : table.offset + table.guard_len]
    assert hashlib.sha256(window).hexdigest() == table.guard


# --- the Ghidra script -------------------------------------------------------


def test_ghidra_manifest_lists_the_names(dn2, curated):
    names = build.merge(dn2, curated, BOOTSTRAP)
    text = ghidra.manifest(names)
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    # every record is one tab-separated line: kind, address, name, note
    assert all(len(ln.split("	")) == 4 for ln in lines)
    assert any(ln.startswith("function	0x80003c9c	verify_and_flash_container") for ln in lines)
