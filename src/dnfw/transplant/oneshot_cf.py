"""The Digitakt II 1.16 ONESHOT page, for the Digitone II 1.11 ColdFire.

Measured in `docs/dt2-machine-port.md`, "The ColdFire half". What the DT2 draws
for a ONESHOT track's SRC page is three things, and all three move as data:

- **eight parameter records** (DT2 entries 202..209: TUNE, PLAY, CFADE, SAMP,
  STRT, LEN, LOOP, LEV; the page shows seven -- CFADE is a record with no knob);
- **their value formatters**, every one of which the DN2 already has, byte for
  byte outside its string and call operands (`TWINS`, checked at apply time);
- **the page descriptor**, `{title, subtitle, eight entries, 10}` -- the same
  44-byte shape as the DN2's own SYN page descriptors -- which the DT2 builds
  in BSS from the immediates of an unrolled initializer (`PAGE`).

What does **not** move is `SourcePageView`, the DT2's SRC page class: its draw,
tick and key handlers read the DT2 sample pool and the DSP's play-position
feedback and open `SampleListView` (the sample browser). The DN2 draws the
records with its own `MultiSourcePageView`, the class the DT2's is a sibling of.

**Nothing below is a donor byte**: addresses, lengths, SHA-256 digests (the
strings are checked by digest too, never held), the numbers the initializer
writes, and our own labels for the records -- the manual's parameter names.
"""

from __future__ import annotations

from .cfspec import CfSpec, Fixed, FormatterTwin, ImageGuard, NameRow, PageFact, RecordRun

DONOR = ImageGuard(device="Digitakt II", product=43, version="1.16",
                   section3_sha256="57bb4dfa8df07d846adc72fdb4fb0d3cd3c5680c524bf498338460207e008e7d")
RECIPIENT_VERSION = "1.11"
RECIPIENT_SECTION3_SHA256 = "57b06a7960b7c3dc9803bde6b31896b89a2fbdcc404a932ff503f3856d4d7a61"

RECORDS = RecordRun(
    name="ONESHOT page records", donor=0x402120E4, count=8,
    sha256="1cadc1171d854a79bc8a6afb2043215dbc8b1014f9474c0b32ba1d55cbc368c8",
    donor_entry=202,
    shorts_sha256="83aa40d455794ee029c388dd1a549d46039880ab2e460af0ba8bdb238f4444dd",
    labels=("TUNE", "PLAY", "CFADE", "SAMP", "STRT", "LEN", "LOOP", "LEV"))

# Every formatter the eight records use, with its DN2 twin. `operands` are the
# only bytes that may differ: string pointers (the text must match), and the
# decimal formatter's call to abs() (the callee must match, 12 bytes).
TWINS = (
    FormatterTwin("int", 0x400E1424, 0x400E2ECC, 30, ((10, "str32"),)),
    FormatterTwin("decimal", 0x400E144E, 0x400E2EF6, 114,
                  ((26, "call32:12"), (66, "str32"), (76, "str32"), (88, "str32"))),
    FormatterTwin("bipolar", 0x400E1618, 0x400E30C0, 12),
    FormatterTwin("play", 0x400E16CA, 0x400E3172, 94,
                  ((26, "str32"), (48, "str32"), (56, "str32"), (64, "str32"))),
    FormatterTwin("raw", 0x400E1728, 0x400E31D0, 26, ((6, "str32"),)),
    FormatterTwin("loop", 0x400E21A6, 0x400E3C4E, 46, ((14, "str32"),)),
)
RECORD_FORMATTERS = ("bipolar", "play", "int", "raw", "decimal", "decimal", "loop", "int")

FIXED = (Fixed("the empty unit suffix", 0x4023F364, 0x40218572, ""),)

# Descriptor 0 of the DT2's machine page array (BSS 0x4293b960, read through
# 0x400c8840(type)), written by the initializer at 0x401c47ca.
PAGE = PageFact(
    name="ONESHOT SRC page", init_start=0x401C47CA, init_length=0xDE,
    sha256="85b4d90cb9fc909af45d9c1219b8010b5310000a2c6f6edf06c9d46e7a7dd1f7",
    title=0x4023F5BF, subtitle=0x4022988E,
    names_sha256="691b159a595eb16fb60ebeab5387e87a1bbf3bad19e345bbc85fc76fab4434a4",
    entries=(202, 203, 0, 205, 206, 207, 208, 209), tag=10)

MACHINE_NAME = NameRow(donor_row=0x4020EB68,
                       names_sha256="779efd0d758f75a997537d70d6a7f30bc048d784a8c1141ff7e1c9c4d43b6d27")

SPEC = CfSpec(
    name="dt2-1.16-oneshot-page -> dn2-1.11",
    donor=DONOR, recipient_version=RECIPIENT_VERSION,
    records=RECORDS, formatters=TWINS, record_formatters=RECORD_FORMATTERS,
    fixed=FIXED, page=PAGE, machine_name=MACHINE_NAME,
    notes=(
        "The records keep the donor's value slots (TUNE 25, PLAY 26, CFADE 27, SAMP 28, "
        "STRT 31, LEN 32, LOOP 33, LEV 34): the DN2 frame carries machine slots 25..65 "
        "verbatim, so each lands at frame slot offset 2 * (slot - 25).",
        "CC and NRPN are cleared (the donor's numbers are the DT2's MIDI map); the ordinal is "
        "a fresh unused value; the page id is the recipient's choice.",
    ),
)
