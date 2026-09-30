"""Watches: named spans of the instrument's memory, their fields, and what a PEEK of them says.

One job: turn a watch spec into the PEEKs that read it, and those PEEKs' bytes
into named values. `dn2poll` sends the PEEKs (one in flight, after each STATS);
the page shows the values live and `dn2log` writes them.

A spec is one of:

    frame:T          track T (1..16, as the instrument numbers them) in the frame the
                     ColdFire sends the SHARC, 0x80005e60: the trig note, level and
                     machine header words, and the track slot's parameters 25..40
                     (TUN1 25, WAV1 26, TBL1 27, TUN2 31), at `dnfw.waverider.frame`'s
                     offsets. The frame is big-endian 16-bit words at those offsets.
    ADDR+LEN[:FMT]   LEN bytes at ADDR as FMT words (u8, u16, s16, u32; u16 by default),
                     e.g. 0x800068e4+32 or 0x46700000+16:u32. Only what PEEK allows.

A value is the word as read. A frame parameter also shows `coarse.fine`
(`word / 256`), and TUN1/TUN2 their semitones (`word / 256 - 64`, as the
instrument sends them: `0x4000` at 0, `0x4c00` at +12, read on the instrument
2026-09-30).

Pure: no port, no clock.
"""
from __future__ import annotations

import pathlib
import struct
import sys
from dataclasses import dataclass, field

import dn2probe

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from dnfw.waverider import frame as wrframe  # noqa: E402

FRAME_ADDR = 0x80005E60
MAX_WATCHES = 8
SPAN_GAP = 256                 # fields further apart are read by separate PEEKs (a round trip costs more than bytes)
FORMATS = {"u8": ">B", "u16": ">H", "s16": ">h", "u32": ">I"}

# the slot parameters a frame watch shows, and the names we know for them
FRAME_PARAMS = range(25, 41)
PARAM_NAMES = {25: "TUN1", 26: "WAV1", 27: "TBL1", 31: "TUN2"}
TUNE_PARAMS = (25, 31)
FRAME_HEADER = (("NOTE", wrframe.NOTE), ("LEVEL", wrframe.LEVEL), ("MACHINE", wrframe.MACHINE))


@dataclass(frozen=True)
class Field:
    name: str
    addr: int
    fmt: str = "u16"
    kind: str = "raw"          # 'raw', 'param' (coarse.fine) or 'tune' (semitones)

    @property
    def size(self) -> int:
        return struct.calcsize(FORMATS[self.fmt])

    def value(self, word: int) -> dict:
        v = {"name": self.name, "addr": self.addr, "word": word,
             "hex": "0x%0*x" % (self.size * 2, word & ((1 << (8 * self.size)) - 1))}
        if self.kind in ("param", "tune"):
            v["coarse_fine"] = round(word / 256, 3)
        if self.kind == "tune":
            v["semitones"] = round(word / 256 - 64, 3)
        return v


@dataclass(frozen=True)
class Watch:
    name: str
    fields: tuple[Field, ...]
    spans: tuple[tuple[int, int], ...] = field(default=())

    def decode(self, reads: dict[int, bytes]) -> list[dict]:
        """{span start: bytes} -> one value per field."""
        out = []
        for f in self.fields:
            lo, n = next(s for s in self.spans if s[0] <= f.addr and f.addr + f.size <= s[0] + s[1])
            data = reads[lo]
            if len(data) != n:
                raise ValueError("PEEK of 0x%08x came back %d bytes, not %d" % (lo, len(data), n))
            (word,) = struct.unpack_from(FORMATS[f.fmt], data, f.addr - lo)
            out.append(f.value(word))
        return out


def spans_of(fields) -> tuple[tuple[int, int], ...]:
    """The fewest PEEKs (each at most PEEK_MAX, no gap over SPAN_GAP) that read FIELDS."""
    out: list[list[int]] = []
    for f in sorted(fields, key=lambda f: f.addr):
        end = f.addr + f.size
        if out and f.addr - (out[-1][0] + out[-1][1]) <= SPAN_GAP and end - out[-1][0] <= dn2probe.PEEK_MAX:
            out[-1][1] = max(out[-1][1], end - out[-1][0])
        else:
            out.append([f.addr, f.size])
    for lo, n in out:
        if not dn2probe.peek_allowed(lo, n):
            raise ValueError("0x%08x +%d is outside what PEEK allows" % (lo, n))
    return tuple((lo, n) for lo, n in out)


def frame_watch(track: int) -> Watch:
    """Track TRACK (1..16) of the ColdFire -> SHARC frame."""
    if not 1 <= track <= wrframe.TRACKS:
        raise ValueError("frame track is 1..16, as the instrument numbers them")
    t = track - 1
    fields = [Field(name, FRAME_ADDR + wrframe.header_offset(at, t)) for name, at in FRAME_HEADER]
    for p in FRAME_PARAMS:
        fields.append(Field(PARAM_NAMES.get(p, "p%d" % p), FRAME_ADDR + wrframe.slot_offset(t, p),
                            kind="tune" if p in TUNE_PARAMS else "param"))
    return Watch("frame:%d" % track, tuple(fields), spans_of(fields))


def raw_watch(spec: str) -> Watch:
    """ADDR+LEN[:FMT] -> LEN bytes at ADDR as FMT words."""
    where, _, fmt = spec.partition(":")
    fmt = fmt or "u16"
    if fmt not in FORMATS:
        raise ValueError("format is one of %s" % ", ".join(FORMATS))
    addr_s, plus, len_s = where.partition("+")
    if not plus:
        raise ValueError("a raw watch is ADDR+LEN[:FMT], e.g. 0x800068e4+32")
    addr, length = int(addr_s, 0), int(len_s, 0)
    size = struct.calcsize(FORMATS[fmt])
    if length <= 0 or length % size or addr % min(size, 2):
        raise ValueError("LEN must be a positive multiple of the word size, and ADDR aligned")
    fields = [Field("+%d" % k, addr + k, fmt) for k in range(0, length, size)]
    return Watch(spec, tuple(fields), spans_of(fields))


def parse(spec: str) -> Watch:
    spec = spec.strip()
    if spec.startswith("frame:"):
        try:
            track = int(spec[6:])
        except ValueError:
            raise ValueError("frame watch is frame:T, T 1..16") from None
        return frame_watch(track)
    return raw_watch(spec)


def changed(prev: list[dict] | None, cur: list[dict]) -> list[str]:
    """The names of the fields whose word differs from the last reading."""
    if prev is None:
        return []
    return [c["name"] for p, c in zip(prev, cur) if p["word"] != c["word"]]


def summary(values: list[dict]) -> str:
    """One line for the log: name=hex, with semitones for a tune field."""
    bits = []
    for v in values:
        s = "%s=%s" % (v["name"], v["hex"])
        if "semitones" in v:
            s += "(%+g st)" % v["semitones"]
        bits.append(s)
    return " ".join(bits)
