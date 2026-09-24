"""The emitter and the decoder must not drift apart.

Both are generated from `src/dnfw/telemetry/channels.json`. If the header is
edited by hand, or the map changes without regenerating, this fails -- which is
the point. A decoder that disagrees with an emitter reports wrong numbers and
says nothing about it, and that failure cost a day on 2026-09-23.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.telemetry import gen  # noqa: E402


def test_header_matches_the_map():
    """The checked-in header is exactly what the generator produces."""
    spec = gen.load()
    assert gen.HEADER.read_text(encoding="utf-8") == gen.header_text(spec), (
        "csrc/telemetry/tlm_channels.h is stale -- run "
        "`python -m dnfw.telemetry.gen`")


def test_decoder_reads_the_same_map():
    """The host decoder names the signals the header defines."""
    import midi_watch

    spec = gen.load()
    assert midi_watch.TLM_CHANNEL == spec["channel"]
    for s in spec["signals"]:
        assert midi_watch.TLM_CC[s["cc"]] == s["name"]


def test_decoder_only_names_signals_on_the_telemetry_channel():
    """A CC 20 from a MIDI track is not telemetry and must not be labelled as
    one -- the instrument sends its own CCs and they would read as findings."""
    import midi_watch

    assert "track" in midi_watch.decode("bf 14 07")        # ch16, ours
    assert "track" not in midi_watch.decode("b0 14 07")    # ch1, the device's


def test_values_are_seven_bit():
    """Anything wider must be split by the caller, not truncated in silence."""
    spec = gen.load()
    for s in spec["signals"]:
        assert s["width"] == 7, f"{s['name']} claims {s['width']} bits; MIDI has 7"
