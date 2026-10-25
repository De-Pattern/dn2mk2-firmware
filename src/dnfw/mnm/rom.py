"""What the Monomachine's firmware holds that the port needs, read from the owner's own copy
of it (SFX-6/60 OS 1.32B, `MNM_OS`, default ../mnm132/mnm_os1.32b.syx beside the repo). None
of it is in this repository: the firmware is Elektron's (CLAUDE.md), so the build reads the
tables from the file at build time, as it reads the Machinedrum's (dnfw.md.rom).

The .syx carries the flash from 0x4000 (the Machinedrum's format, device byte 3): a chain
of UCL NRV2B blocks -- the OS (ColdFire, at 0x200000), the two DSPs' kernels, and the
external memory image the kernels share (records of 24-bit words; P, X and Y are one
memory above 0x100000), where the machines' code and tables are.
"""

from __future__ import annotations

import functools
import hashlib
import os
import pathlib
import struct

from ..md.rom import nrv2b

ROOT = pathlib.Path(__file__).resolve().parents[3]
DEFAULT = ROOT.parent / "mnm132" / "mnm_os1.32b.syx"
SHA256 = "fe13c09f661cdba5fe57813240fa1574de1ee0a3ddd7047fc39d0318cba1a710"
CHAIN = 0x4000
FLASH = 1 << 20


class RomError(Exception):
    pass


def path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MNM_OS", str(DEFAULT)))


def available() -> bool:
    return path().is_file()


def flash(data: bytes) -> bytes:
    """The flash the .syx carries (0xFF where it carries nothing)."""
    img = bytearray(b"\xff" * FLASH)
    i = n = 0
    while True:
        a = data.find(b"\xf0", i)
        if a < 0:
            break
        b = data.find(b"\xf7", a)
        if b < 0:
            break
        m = data[a:b + 1]
        i = b + 1
        if m[1:6] != b"\x00\x20\x3c\x03\x00" or m[6] != 0x7E or len(m) < 18:
            continue
        addr = 0
        for k in range(9, 15):
            addr = (addr << 4) | (m[k] & 0x0F)
        body = m[15:-1]
        for k in range(0, len(body) - len(body) % 3, 3):
            v = (body[k] << 14) | (body[k + 1] << 7) | body[k + 2]
            o = addr + 2 * (k // 3)
            if o + 2 > FLASH:
                raise RomError("the Monomachine file has an address past its flash")
            img[o] = v >> 8
            img[o + 1] = v & 0xFF
        n += 1
    if n < 8000:
        raise RomError("that is not the Monomachine OS 1.32B file")
    return bytes(img)


@functools.lru_cache(maxsize=1)
def blocks() -> tuple[bytes, ...]:
    """The OS, DSP A's and DSP B's kernels and the external image, each checked against its
    stored byte sum."""
    raw = path().read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise RomError(f"{path()} is not the Monomachine OS 1.32B .syx (sha256 {SHA256[:12]}...)")
    d = flash(raw)
    out, at = [], CHAIN
    for _ in range(4):
        clen, ck = struct.unpack_from(">II", d, at)
        if sum(d[at + 8:at + 8 + clen]) & 0xFFFFFFFF != ck:
            raise RomError(f"block at {at:#x}: its byte sum does not match")
        out.append(nrv2b(d, at + 8))
        at += 8 + clen
    return tuple(out)


def _w(d: bytes, o: int) -> int:
    return d[o] | d[o + 1] << 8 | d[o + 2] << 16


@functools.lru_cache(maxsize=1)
def ext() -> dict[int, int]:
    """The external memory as the image loads it: {address: 24-bit word}."""
    d = blocks()[3]
    mem: dict[int, int] = {}
    o = 6 if d[0] == 3 else 0
    if d[o] == 4:
        o += 6
    while o < len(d):
        t = _w(d, o)
        if t > 2:
            break
        a, n = _w(d, o + 3), _w(d, o + 6)
        for k in range(n):
            mem[a + k] = _w(d, o + 9 + 3 * k)
        o += 9 + 3 * n
    return mem


def words(addr: int, n: int) -> list[int]:
    """N 24-bit words (unsigned) of the external memory from ADDR."""
    m = ext()
    out = []
    for k in range(n):
        if addr + k not in m:
            raise RomError(f"{addr + k:#x} is not in the image")
        out.append(m[addr + k])
    return out


WAVES = (0x101D7B, 33 * 256)                  # DPRO-WAVE's 33 waves, two 12-bit samples a word
COMB = (0x140800, 4096)                       # SID's combined waveforms, 8 bits << 16


def s24(v: int) -> int:
    v &= 0xFFFFFF
    return v - (1 << 24) if v & 0x800000 else v


@functools.lru_cache(maxsize=1)
def wave_samples() -> tuple[int, ...]:
    """The waves as the render reads them, 512 samples a wave, each a signed 24-bit word:
    a word's high sample is the word itself, its low sample the low 12 bits << 12."""
    out = []
    for w in words(*WAVES):
        out += [s24(w), s24(w << 12)]
    return tuple(out)
