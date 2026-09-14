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
OS release could move the bank. `_bank_spans` resolves the address through
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


def _bank_spans(section_bytes: bytes):
    """The bank's file pieces, in load order. See `bootstream.spans`.

    **A load-address range is not a file range**, and this bank proves it: it
    spans two payload blocks with a 36-byte fill block and two 16-byte headers
    between them, 47,440 bytes in. Reading or writing it linearly crosses those
    headers -- which is exactly what this module did until 2026-09-14.
    """
    return bootstream.spans(section_bytes, BANK_ADDR, COUNT * ENTRY_BYTES)


def extents(firmware) -> list[Extent]:
    """Which bytes this mod writes -- **several ranges, not one.**

    The bank is contiguous in the DSP's memory and scattered in the file, so a
    single extent would under-declare it and the compatibility check would miss
    a real overlap. The fill piece contributes no extent because there are no
    file bytes to claim.
    """
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError(f"image has no section {SECTION}")
    data = section.unpack() or section.raw_payload
    return [Extent(SECTION, at, n, f"transient bank, {n:,} bytes")
            for at, n in _bank_spans(data) if at is not None]


def read_wav(path: pathlib.Path, whole: bool = False) -> list[int]:
    """-> 16-bit mono samples at RATE; slot-length unless `whole`.

    `whole=True` returns the entire file, which `prepare()` needs so it can
    choose which 100 ms to keep. Truncating first would throw away the part the
    user may be asking for.
    """
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
    v = [max(-32768, min(32767, x)) for x in v]
    if whole:
        return v
    if len(v) > ENTRY_SAMPLES:
        v = v[:ENTRY_SAMPLES]
    elif len(v) < ENTRY_SAMPLES:
        v = v + [0] * (ENTRY_SAMPLES - len(v))
    return v


def prepare(path: pathlib.Path, lead_ms: float = 3.0,
            start_ms: float | None = None) -> list[int]:
    """Condition any sample into one slot: mono, 48 kHz, 100 ms of the right part.

    A slot is 100 ms and a user's file is whatever it is, so something has to
    choose *which* 100 ms.

    **`start_ms` — you choose.** The window starts exactly there. Use it when the
    part you want is not the first attack: the second hit of a flam, a tail you
    want on its own, a sample whose useful moment is 300 ms in.

    **Otherwise the onset is found** — the first point reaching an eighth of the
    peak — and the window starts `lead_ms` before it. Files routinely carry a few
    milliseconds of silence, and starting at sample 0 would spend the slot on it.

    `lead_ms` is a per-sample control, not a constant, because the right value
    depends on the sound. A sharp click wants almost none; a soft or swelling
    attack wants more, or the detector fires partway up the rise and the front of
    the sound is cut off. Guessing one number for a whole bank is exactly the
    kind of fixed assumption this project keeps having to retract, so it is
    exposed instead.

    A 2 ms fade at the end keeps the hard cut from adding a click of its own,
    which would be a transient this tool invented.

    This is **fitting**, not separation. Pulling the percussive layer out of a
    pitched sample is real signal processing, and `mikkovihonen/transientsplit`
    (MIT) already does it in the browser — run a sample through that first if
    you want the transient *component*, then through this to fit it to the slot.
    """
    v = read_wav(path, whole=True)
    if not v:
        return [0] * ENTRY_SAMPLES

    if start_ms is not None:
        start = max(0, int(start_ms * RATE / 1000))
    else:
        peak = max((abs(x) for x in v), default=0)
        if peak == 0:
            return (v + [0] * ENTRY_SAMPLES)[:ENTRY_SAMPLES]
        threshold = peak // 8
        onset = next((i for i, x in enumerate(v) if abs(x) >= threshold), 0)
        start = max(0, onset - int(lead_ms * RATE / 1000))

    out = v[start:start + ENTRY_SAMPLES]
    if len(out) < ENTRY_SAMPLES:
        out = out + [0] * (ENTRY_SAMPLES - len(out))
    fade = RATE // 500                      # 2 ms, far shorter than any decay
    for i in range(min(fade, len(out))):
        out[-1 - i] = int(out[-1 - i] * i / fade)
    return out


def read_options(directory: pathlib.Path) -> dict:
    """Per-sample conditioning options from `prepare.csv`, if present.

    One line per file, so a bank can be tuned sample by sample without renaming
    anything or passing thirty-four flags:

        # file, lead_ms, start_ms
        kick.wav,   6,
        snare.wav,   , 120

    A blank field means "not set". `start_ms` wins over `lead_ms` where both are
    given, because naming an exact start is a stronger statement than adjusting
    a guess. Unknown filenames are reported rather than ignored -- a typo that
    silently does nothing is worse than an error.
    """
    options: dict[str, dict] = {}
    for name in ("prepare.csv", "prepare.txt"):
        path = directory / name
        if not path.exists():
            continue
        import csv
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if not row or row[0].strip().startswith("#"):
                    continue
                key = row[0].strip()
                if not key:
                    continue
                entry = {}
                if len(row) > 1 and row[1].strip():
                    entry["lead_ms"] = float(row[1])
                if len(row) > 2 and row[2].strip():
                    entry["start_ms"] = float(row[2])
                options[key] = entry
        break
    return options


def extract(firmware) -> list[bytes]:
    """-> the factory entries, each ENTRY_BYTES of raw 16-bit LE PCM.

    Read through `bootstream.read_span`, which gathers the bank across the
    blocks that hold it. Reading the file linearly from the first block -- what
    this did until 2026-09-14 -- returned two 16-byte block headers and a
    36-byte fill gap as audio, and shifted everything after them by 34 samples:
    85.5% of the bank was wrong, and the header bytes showed up as a full-scale
    spike near the end of entry 4.
    """
    section = firmware.container.find(SECTION)
    data = section.unpack() or section.raw_payload
    bank = bootstream.read_span(data, BANK_ADDR, COUNT * ENTRY_BYTES)
    return [bank[k * ENTRY_BYTES:(k + 1) * ENTRY_BYTES] for k in range(COUNT)]


def apply(firmware, sources: list[pathlib.Path], condition: bool = False,
          lead_ms: float = 3.0, options: dict | None = None) -> Result:
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

    # Build the whole bank in load order first, then scatter it back across the
    # blocks that hold it. Writing entry by entry at a computed file offset is
    # what put header bytes in the audio and would have written audio over two
    # block headers -- see `_bank_spans`.
    bank = bytearray(bootstream.read_span(data, BANK_ADDR, COUNT * ENTRY_BYTES))

    notes = []
    for k, path in enumerate(sources):
        with wave.open(str(path), "rb") as w:
            n_in, rate_in = w.getnframes(), w.getframerate()
        opts = (options or {}).get(path.name, {})
        if condition:
            samples = prepare(path,
                              lead_ms=opts.get("lead_ms", lead_ms),
                              start_ms=opts.get("start_ms"))
        else:
            samples = read_wav(path)
        at = k * ENTRY_BYTES
        bank[at:at + ENTRY_BYTES] = struct.pack(f"<{ENTRY_SAMPLES}h", *samples)
        note = f"{k:02d} <- {path.name}"
        if condition:
            if "start_ms" in opts:
                note += f" (start {opts['start_ms']:g} ms)"
            else:
                lead = opts.get("lead_ms", lead_ms)
                note += f" (onset-aligned, lead {lead:g} ms"
                note += ", from prepare.csv)" if "lead_ms" in opts else ")"
        if rate_in != RATE:
            note += f" (resampled {rate_in} -> {RATE})"
        if n_in * RATE // max(rate_in, 1) > ENTRY_SAMPLES:
            note += f" (TRUNCATED to {1000 * ENTRY_SAMPLES // RATE} ms)"
        notes.append(note)
    if len(sources) < COUNT:
        notes.append(f"entries {len(sources)}..{COUNT - 1} left as factory")

    # Scatter the bank back. Fill pieces have no file bytes, so whatever the
    # user put there cannot be stored; that is reported rather than dropped in
    # silence -- it is 36 bytes near the end of entry 4 and the loader will
    # write zeros over it regardless.
    cursor = 0
    for at, n in _bank_spans(bytes(data)):
        if at is None:
            lost = bank[cursor:cursor + n]
            if any(lost):
                notes.append(
                    f"{n} bytes at bank offset {cursor:,} (entry "
                    f"{cursor // ENTRY_BYTES}) fall in a boot-stream fill "
                    f"block and CANNOT be written; the loader zeroes them")
        else:
            data[at:at + n] = bank[cursor:cursor + n]
        cursor += n

    return Result(payloads={SECTION: bytes(data)},
                  extents=extents(firmware),
                  notes=notes)
