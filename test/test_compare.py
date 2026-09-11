"""`firmware.compare`: that it reports change, and only change."""

from dnfw.firmware import compare


def test_identical_bytes_make_no_blocks():
    data = bytes(range(256)) * 10
    assert compare.clusters(data, data) == []


def test_nearby_differences_cluster_and_distant_ones_do_not():
    a = bytearray(20_000)
    b = bytearray(a)
    for i in (100, 110, 120):  # one dense block
        b[i] = 1
    b[15_000] = 1  # far enough away to be its own block
    blocks = compare.clusters(bytes(a), bytes(b), gap=4096)
    assert [(x.start, x.end, x.differing) for x in blocks] == [(100, 121, 3), (15_000, 15_001, 1)]


def test_text_keeps_words_and_drops_code():
    blob = (
        b"\x00OUTBOX 8 CONNECTED\x00"
        b"\x00Out %s Volume=%s\x00"
        b"\x00vector::_M_insert_aux\x00"
        b"\x00DHMx%I\x00"  # relinked code: mixed case, no word
        b"\x00DEK@*-\x00"  # mostly punctuation
    )
    found = compare.text(blob)
    assert {"OUTBOX 8 CONNECTED", "Out %s Volume=%s", "vector::_M_insert_aux"} <= found
    assert "DHMx%I" not in found
    assert "DEK@*-" not in found


def test_an_image_compared_with_itself_is_identical(dn2):
    diffs = compare.sections(dn2, dn2)
    assert diffs and all(d.identical and not d.blocks for d in diffs)
