"""Replace the Digitone II's FM drum transient bank with your own samples.

## What was measured, and what was not

The bank was located in the **SHARC image** (container section 7, an ADI boot
stream) by a detector calibrated against Elektron's own `TRANSIENT 01-08.wav`
from the Syntakt OS 1.41 Twinshot pack — `docs/pcm-hunt.md` §14. The numbers
below are measurements, not choices:

| | | how |
|---|---|---|
| region | DDR `0x8045b000`–`0x804ac000` | bounded by float32 tables either side, not by a threshold |
| format | 16-bit mono, little-endian | byte-plane and step-correlation match real transients |
| rate | 48 kHz | the period is exactly 100.0 ms at 48 k and an awkward 108.8 ms at 44.1 k |
| entry | 4,800 samples | envelope autocorrelation, with 2x and 3x harmonics also ranking |
| phase | 2,496 samples into the region | attack-at-start vs decay-at-end scores 14.27 against 1.46 for the next candidate |

**Confirmed on hardware, 2026-09-14.** An image with marker samples at five
known slots was flashed to a Digitone II and every marker played back from
`TRAN` — so these bytes are the FM drum transients, and the count is 34.
`docs/pcm-hunt.md` §16.

**What stays conditional:** none of this is documented by Elektron, so another
OS release could move the bank. `_payload_offset` resolves the address through
the boot stream every time it runs and refuses an image whose layout it does not
recognise, rather than trusting the constants above.

This mod replaces **whole entries in place** and touches nothing else — no
lengths change, no index is rewritten, and every byte outside the entries it
writes is left exactly as it was.

## How a replacement is prepared

Each input becomes exactly 4,800 samples of 16-bit mono at 48 kHz:

- other sample rates are linearly resampled;
- stereo is mixed to mono;
- longer inputs are **truncated** and shorter ones **zero-padded**, because a
  transient is a fixed slot in a packed bank and there is nowhere for a longer
  one to go.

Truncation is reported rather than done silently.
"""

import pathlib
import struct
import wave

from . import Extent, ModError, Result
from ..image import bootstream

ID = "transients"
NAME = "FM drum transients"
SUMMARY = "Replace the factory FM drum transient bank with your own samples."
DEVICE = 0x15                      # Digitone II, dump-protocol product id
SECTION = 7                        # the SHARC image

# Measured -- see the module docstring. Load addresses, not file offsets.
REGION_START = 0x8045B000
REGION_END = 0x804AC000
PHASE_SAMPLES = 2496
ENTRY_SAMPLES = 4800
RATE = 48000

BYTES_PER_SAMPLE = 2
ENTRY_BYTES = ENTRY_SAMPLES * BYTES_PER_SAMPLE
BANK_ADDR = REGION_START + PHASE_SAMPLES * BYTES_PER_SAMPLE
COUNT = (REGION_END - BANK_ADDR) // ENTRY_BYTES


def _payload_offset(section_bytes: bytes, address: int) -> int:
    """Load address -> offset inside section 7's unpacked payload.

    The boot stream scatters its payloads across L1, L2 and DDR, so an offset
    into the section is not an address (`dnfw.image.bootstream`). Writing to
    the wrong one would corrupt an unrelated region, so the block that actually
    covers the address is found rather than assumed.
    """
    walk = bootstream.walk(section_bytes)
    for block in walk.blocks:
        if not block.has_payload:
            continue
        if block.target <= address < block.target + block.count:
            return block.payload_at + (address - block.target)
    raise ModError(
        f"0x{address:08x} is not inside any boot-stream block carrying data; "
        f"this image's layout is not the one this mod was measured against")


def extents(firmware) -> list[Extent]:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError(f"image has no section {SECTION}")
    data = section.unpack() or section.raw_payload
    start = _payload_offset(data, BANK_ADDR)
    return [Extent(SECTION, start, COUNT * ENTRY_BYTES,
                   f"{COUNT} transient entries of {ENTRY_SAMPLES} samples")]


def read_wav(path: pathlib.Path) -> list[int]:
    """-> exactly ENTRY_SAMPLES signed 16-bit samples at RATE, mono."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ModError(f"{path.name}: {w.getsampwidth() * 8}-bit; "
                           f"only 16-bit WAV is supported")
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    v = list(struct.unpack_from(f"<{n * ch}h", raw, 0))
    if ch > 1:
        v = [sum(v[i:i + ch]) // ch for i in range(0, len(v), ch)]
    if rate != RATE:
        # Linear resample. Good enough for a 100 ms percussive hit, and far
        # better than refusing the file; anything fancier belongs in the
        # user's editor, where they can hear it.
        out, step = [], rate / RATE
        for i in range(int(len(v) / step)):
            x = i * step
            k = int(x)
            f = x - k
            a = v[k] if k < len(v) else 0
            b = v[k + 1] if k + 1 < len(v) else a
            out.append(int(a + (b - a) * f))
        v = out
    if len(v) > ENTRY_SAMPLES:
        v = v[:ENTRY_SAMPLES]
    elif len(v) < ENTRY_SAMPLES:
        v = v + [0] * (ENTRY_SAMPLES - len(v))
    return [max(-32768, min(32767, x)) for x in v]


def prepare(path: pathlib.Path, lead_ms: int = 3) -> list[int]:
    """Condition any sample into one slot: mono, 48 kHz, onset-aligned, 100 ms.

    A transient slot is 100 ms and a user's file is whatever it is, so something
    has to choose *which* 100 ms. Starting at sample 0 is wrong for most
    recordings: files routinely carry a few milliseconds of silence, and that
    silence would eat the attack, which is the one part of a transient that
    matters.

    So the onset is found -- the first point reaching a fraction of the peak --
    and the slot starts `lead_ms` before it, keeping the attack's leading edge
    rather than clipping into it. A short fade at the end prevents the hard cut
    from adding a click of its own, which would be a transient this tool
    invented.

    This is deliberately NOT transient/tonal separation. Pulling the percussive
    layer out of a pitched sample is a real DSP problem, and
    `mikkovihonen/transientsplit` (MIT) already solves it in the browser -- run
    a sample through that first if you want the transient *component*, then
    through this to fit it to the slot.
    """
    v = read_wav(path)                      # mono, 48 kHz, already slot-length
    peak = max((abs(x) for x in v), default=0)
    if peak == 0:
        return v
    threshold = peak // 8
    onset = next((i for i, x in enumerate(v) if abs(x) >= threshold), 0)
    lead = lead_ms * RATE // 1000
    start = max(0, onset - lead)
    out = v[start:] + [0] * start
    fade = RATE // 500                      # 2 ms, far shorter than any decay
    for i in range(min(fade, len(out))):
        out[-1 - i] = int(out[-1 - i] * i / fade)
    return out


def extract(firmware) -> list[bytes]:
    """-> the factory entries, each ENTRY_BYTES of raw 16-bit LE PCM."""
    section = firmware.container.find(SECTION)
    data = section.unpack() or section.raw_payload
    start = _payload_offset(data, BANK_ADDR)
    return [data[start + k * ENTRY_BYTES: start + (k + 1) * ENTRY_BYTES]
            for k in range(COUNT)]


def apply(firmware, sources: list[pathlib.Path], condition: bool = False) -> Result:
    """Replace entries in order with `sources`; a short list leaves the rest.

    `condition=True` runs each input through `prepare()` -- onset alignment and
    an end fade. It is OFF by default on purpose: conditioning changes samples,
    and with it off, extracting the factory bank and writing it straight back
    produces a byte-identical image. That round-trip is the strongest check this
    mod has, and a default that silently altered samples would destroy it.
    """
    if not sources:
        raise ModError("no input samples given")
    if len(sources) > COUNT:
        raise ModError(f"{len(sources)} samples given but the bank holds "
                       f"{COUNT}; remove {len(sources) - COUNT}")

    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError(f"image has no section {SECTION}")
    data = bytearray(section.unpack() or section.raw_payload)
    start = _payload_offset(bytes(data), BANK_ADDR)

    notes = []
    for k, path in enumerate(sources):
        with wave.open(str(path), "rb") as w:
            n_in, rate_in = w.getnframes(), w.getframerate()
        samples = prepare(path) if condition else read_wav(path)
        at = start + k * ENTRY_BYTES
        data[at:at + ENTRY_BYTES] = struct.pack(f"<{ENTRY_SAMPLES}h", *samples)
        note = f"{k:02d} <- {path.name}"
        if condition:
            note += " (onset-aligned)"
        if rate_in != RATE:
            note += f" (resampled {rate_in} -> {RATE})"
        if n_in * RATE // max(rate_in, 1) > ENTRY_SAMPLES:
            note += f" (TRUNCATED to {1000 * ENTRY_SAMPLES // RATE} ms)"
        notes.append(note)
    if len(sources) < COUNT:
        notes.append(f"entries {len(sources)}..{COUNT - 1} left as factory")

    return Result(payloads={SECTION: bytes(data)},
                  extents=[Extent(SECTION, start, COUNT * ENTRY_BYTES,
                                  "transient bank")],
                  notes=notes)
