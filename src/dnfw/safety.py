"""The preflight: what a build must be before it may be written, let alone flashed.

`verify` asks whether an image is *well formed*: checksums, padding, signature.
This asks whether it is *safe for this project to hand to an instrument*, which
is a narrower thing, decided by what can and cannot be undone.

What can always be undone is MAIN OS (section 3) and the DSP program
(section 7): if either is wrong, the instrument still reaches the Early
Start-up Menu, and recovery re-flashes stock over DIN MIDI. That works because
recovery is run by the **bootstrap**, section 2, which is the one part of the
image that must never change: a damaged bootstrap takes the recovery route
with it (`docs/bootstrap.md`, `docs/flashing.md`). The updater (4), the build
metadata (5) and the Outbox 8 firmware (8) have no reason to change either.

So, as rules:

1. The input is stock Digitone II OS 1.11, by the hash of every section.
2. The build has exactly stock's sections, in stock's order, with stock's
   product, version and build string (a different version string could make
   the device decide its bootstrap needs upgrading).
3. Every section other than 3 and 7 is byte-identical to stock.
4. The DSP program fits the buffers MAIN OS uploads it through: stored size at
   most 1 MiB, unpacked size at most 1 MiB less the one-byte header the uploader
   writes first (read from `0x400cf34c`; see SHARC_MAX_UNPACKED).
5. The build verifies: checksums, padding, Elektron's limits, the HMAC.

Nothing here reads an instrument or sends anything. It is a gate on bytes.
"""

from __future__ import annotations

import dataclasses
import hashlib

from .firmware.load import load
from .firmware.verify import verify

PRODUCT = 52                 # Digitone II
VERSION = "1.11"
BUILD = "0059"

# sha256 of each section's stored payload in Elektron's Digitone II OS 1.11
# (file sha256 2af43e65e3d8390b41c9f66222620f8cce027d73ed87db00c80b440f628472e0).
# Hashes only: no Elektron bytes are in this repository.
STOCK_111 = {
    5: "becc493e90833ee87cde7a942db1faad859b2cf3c662eb225e1070f199125fab",
    2: "669d8c50e9dd028662538016817d841dfac74cf68b2662e7de41b3927bc3275e",
    3: "69296d74cf0ab17f57a88e47244f4d4e654aefec71e322830d8cd866ec3ed6b2",
    4: "e0020c6b65357c2175d1939952924a010ab943364eade497d80b4c8afa65def4",
    7: "5ff93df8747bdf9eb28acf50391fb484d6aa6782bfe969b2b3807a8412645660",
    8: "764f169834ac9ebcdbc1fd883e9f941be1eb43c2d57e4ff02e04685550838b06",
}
ORDER = (5, 2, 3, 4, 7, 8)

MAY_CHANGE = {3: "MAIN OS", 7: "DSP program"}
NEVER = {2: "bootstrap: runs recovery; a damaged one can brick the instrument",
         4: "updater", 5: "build metadata", 8: "Outbox 8 firmware"}

SHARC_BUFFER = 1 << 20       # MAIN OS mallocs 1 MiB to push section 7 to the SHARC
# The uploader (0x400cf34c) checks the *stored* length against 1 MiB (0x400cf5ac), then
# depacks into a second 1 MiB buffer after a one-byte 0x03 header (0x400cf5ce) and only
# then compares length + 1 with 1 MiB (0x400cf5e4). The depack has already written by
# then, so an image over the limit overruns the heap before the check can refuse it.
SHARC_MAX_UNPACKED = SHARC_BUFFER - 1


@dataclasses.dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def stock_checks(stock) -> list[Check]:
    """Rule 1: the input is the stock 1.11 file, section by section."""
    c = stock.container
    out = [Check("input is Digitone II OS 1.11",
                 c.product == PRODUCT and c.version == VERSION and c.build == BUILD,
                 f"product {c.product}, version {c.version}, build {c.build}")]
    ids = tuple(s.id for s in c.sections)
    out.append(Check("input has stock 1.11's sections", ids == ORDER, f"{ids}"))
    for s in c.sections:
        want = STOCK_111.get(s.id)
        out.append(Check(f"input section {s.id} is stock 1.11's",
                         want is not None and _sha(s.raw_payload) == want,
                         _sha(s.raw_payload)[:16]))
    return out


def build_checks(stock, built_bytes: bytes) -> list[Check]:
    """Rules 2-5, comparing a build with the stock image it was made from."""
    built = load(built_bytes)
    b, s = built.container, stock.container
    out = [Check("build keeps product, version and build string",
                 (b.product, b.version, b.build) == (s.product, s.version, s.build),
                 f"{b.product} {b.version} {b.build}")]
    ids = tuple(x.id for x in b.sections)
    out.append(Check("build has stock's sections, in stock's order",
                     ids == tuple(x.id for x in s.sections), f"{ids}"))
    stock_by_id = {x.id: x for x in s.sections}
    for x in b.sections:
        if x.id in MAY_CHANGE:
            continue
        same = x.id in stock_by_id and x.raw_payload == stock_by_id[x.id].raw_payload
        out.append(Check(f"section {x.id} untouched ({NEVER.get(x.id, '?')})", same,
                         "" if same else "DIFFERS FROM STOCK"))
    dsp = b.find(7)
    if dsp is not None:
        n = len(dsp.unpack())
        stored = len(dsp.raw_payload)
        out.append(Check("DSP program fits the 1 MiB upload buffer",
                         n <= SHARC_MAX_UNPACKED and stored <= SHARC_BUFFER,
                         f"{n:,} unpacked of {SHARC_MAX_UNPACKED:,}; {stored:,} stored of {SHARC_BUFFER:,}"))
    report = verify(built)
    bad = [c.name for c in report.checks if not c.ok]
    out.append(Check("integrity and signature", not bad,
                     f"{len(report.checks) - len(bad)}/{len(report.checks)}"
                     + (f"; failed: {', '.join(bad)}" if bad else "")))
    out.append(Check("signed", built.key is not None, ""))
    return out


def preflight(stock, built_bytes: bytes) -> list[Check]:
    return stock_checks(stock) + build_checks(stock, built_bytes)


def report(checks: list[Check]) -> tuple[bool, str]:
    lines = [f"  [{'ok ' if c.ok else 'BAD'}] {c.name}" + (f"  ({c.detail})" if c.detail else "")
             for c in checks]
    ok = all(c.ok for c in checks)
    return ok, "\n".join(lines)
