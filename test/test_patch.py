"""Patch records: their guards, and that a declared patch actually applies."""

import pathlib

import pytest

from dnfw.patch import discover
from dnfw.patch.apply import apply, applies_to, locate
from dnfw.patch.spec import Patch, PatchError
from dnfw.image.coldfire import LoadedImage

PATCHES = pathlib.Path(__file__).resolve().parent.parent / "patches"


def _patch(**overrides) -> Patch:
    fields = dict(
        id="test",
        group="test",
        description="test",
        device=0x15,
        build="0050",
        version="1.10E",
        section=3,
        expect=b"AAAA",
        replace=b"BBBB",
        address=0x40000400,
    )
    fields.update(overrides)
    return Patch(**fields)


def test_replacement_must_be_the_same_length():
    with pytest.raises(PatchError, match="same-length"):
        _patch(replace=b"BB")


def test_exactly_one_of_address_or_find():
    with pytest.raises(PatchError, match="exactly one"):
        _patch(find=b"AAAA")
    with pytest.raises(PatchError, match="exactly one"):
        _patch(address=None)


def test_find_must_match_expect():
    with pytest.raises(PatchError, match="same bytes"):
        _patch(address=None, find=b"ZZZZ")


def test_duplicate_ids_are_refused():
    from dnfw.patch.spec import validate

    with pytest.raises(PatchError, match="duplicate"):
        validate([_patch(), _patch()])


def test_locate_refuses_a_wrong_expectation():
    image = LoadedImage(dest=0x40000400, content=b"....AAAA....")
    with pytest.raises(PatchError, match="expected"):
        locate(_patch(address=0x40000400), image)


def test_locate_refuses_an_ambiguous_find():
    image = LoadedImage(dest=0x40000400, content=b"AAAA__AAAA")
    with pytest.raises(PatchError, match="matched 2 times"):
        locate(_patch(address=None, find=b"AAAA", expect=b"AAAA"), image)


def test_locate_finds_a_unique_string():
    image = LoadedImage(dest=0x40000400, content=b"__AAAA__")
    assert locate(_patch(address=None, find=b"AAAA", expect=b"AAAA"), image) == 2


def test_declared_patches_load():
    patches = discover.load(PATCHES)
    assert patches, "patches/ should declare at least the Gate E proof patch"
    assert len({p.id for p in patches}) == len(patches)


def test_declared_patches_apply_to_the_image_they_name(dn2):
    for patch in discover.load(PATCHES):
        if patch.device != dn2.envelope.device:
            continue
        assert applies_to(patch, dn2) is None
        contents, applied = apply([patch], dn2)
        assert len(applied) == 1
        assert contents[patch.section].count(patch.replace) == 1


def test_a_patch_for_another_device_is_refused(dn1):
    for patch in discover.load(PATCHES):
        if patch.device == dn1.envelope.device:
            continue
        assert applies_to(patch, dn1) is not None
        with pytest.raises(PatchError, match="does not apply"):
            apply([patch], dn1)
