"""What the Machinedrum's firmware holds that the port needs, read from the owner's own
copy of it (OS 1.63, `MD_OS_BIN`, default ../md163/md_uw_os1.63.bin beside the repo). None
of it is in this repository: the firmware is Elektron's (CLAUDE.md), so the build reads
the tables from the file at build time, as it reads the DN2's own firmware.

The file is the flash image (docs/md.md): a chain of UCL NRV2B blocks from 0x4000 -- the
OS (68k, loaded at 0x200000), then DSP2's program (records of 24-bit words, little
endian). P, X and Y share one external memory above 0x100000 on DSP2, so a table is read
by its address alone.
"""

from __future__ import annotations

import functools
import os
import pathlib
import struct

ROOT = pathlib.Path(__file__).resolve().parents[3]
DEFAULT = ROOT.parent / "md163" / "md_uw_os1.63.bin"
CHAIN = 0x4000                       # the first compressed block (the OS)
OS_VMA = 0x200000


class RomError(Exception):
    pass


def path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MD_OS_BIN", str(DEFAULT)))


def available() -> bool:
    return path().is_file()


def nrv2b(src: bytes, ip: int) -> bytes:
    """UCL NRV2B, 8-bit bit buffer (the bootloader's decompressor)."""
    out = bytearray()
    bb = 0

    def bit():
        nonlocal bb, ip
        if bb & 0x7F:
            bb *= 2
        else:
            bb = src[ip] * 2 + 1
            ip += 1
        return (bb >> 8) & 1
    last = 1
    while True:
        while bit():
            out.append(src[ip])
            ip += 1
        m_off = 1
        while True:
            m_off = m_off * 2 + bit()
            if bit():
                break
        if m_off == 2:
            m_off = last
        else:
            m_off = (m_off - 3) * 256 + src[ip]
            ip += 1
            if m_off == 0xFFFFFFFF:
                break
            m_off += 1
            last = m_off
        m_len = bit()
        m_len = m_len * 2 + bit()
        if m_len == 0:
            m_len = 1
            while True:
                m_len = m_len * 2 + bit()
                if bit():
                    break
            m_len += 2
        m_len += m_off > 0xD00
        q = len(out) - m_off
        for k in range(m_len + 1):
            out.append(out[q + k])
        if len(out) > 1 << 24:
            raise RomError("a block decompresses past 16 MB")
    return bytes(out)


@functools.lru_cache(maxsize=1)
def blocks() -> tuple[bytes, ...]:
    """The first three blocks: the OS, DSP2's image, DSP1's image, each checked against
    its stored byte sum."""
    d = path().read_bytes()
    if len(d) != 8 << 20 or d[0xC5458:0xC545B] != b"163":
        raise RomError(f"{path()} is not the Machinedrum UW OS 1.63 flash image")
    out, at = [], CHAIN
    for _ in range(3):
        clen, ck = struct.unpack_from(">II", d, at)
        if sum(d[at + 8:at + 8 + clen]) & 0xFFFFFFFF != ck:
            raise RomError(f"block at {at:#x}: its byte sum does not match")
        out.append(nrv2b(d, at + 8))
        at += 8 + clen
    return tuple(out)


def _w(d: bytes, o: int) -> int:
    return d[o] | d[o + 1] << 8 | d[o + 2] << 16


@functools.lru_cache(maxsize=1)
def dsp2() -> dict[int, int]:
    """DSP2's memory as its image loads it: {address: 24-bit word}, P/X/Y merged."""
    d = blocks()[1]
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
    """N signed 24-bit words of DSP2's memory from ADDR."""
    m = dsp2()
    out = []
    for k in range(n):
        if addr + k not in m:
            raise RomError(f"DSP2 {addr + k:#x} is not in the image")
        v = m[addr + k]
        out.append(v - (1 << 24) if v & 0x800000 else v)
    return out


def os_longs(vma: int, n: int) -> list[int]:
    """N big-endian 32-bit words of the OS from its address VMA."""
    o = vma - OS_VMA
    return list(struct.unpack_from(f">{n}I", blocks()[0], o))


# the host's tables (the scale functions read them) and DSP2's ROM tables
HOST_TABLES = {"P": (0x24BD94, 128), "D": (0x24BF94, 512), "Q": (0x24C794, 512), "R": (0x24D794, 128),
               "A": (0x2462E8, 512)}             # v0.24: A, P-IMA's four 128-long tables
DSP_TABLES = {
    "TRXBD_CLICK1": (0x10050C, 288), "TRXBD_CLICK2": (0x10062C, 288), "X140000": (0x140000, 8448),
    "SNAP100881": (0x100881, 4128), "TRXXT_CLICK1": (0x10190F, 32), "TRXXT_CLICK2": (0x10192F, 32),
    "TRXRS_CLICK": (0x101BA0, 800), "TRXCH_W0": (0x102600, 114), "TRXCH_W1": (0x102700, 102),
    "TRXCH_W2": (0x102780, 86), "TRXCH_W3": (0x102800, 80), "TRXCH_W4": (0x102880, 58),
    "TRXCH_W5": (0x1028C0, 52), "TRXXC_CLICK": (0x102C0F, 32),
}
from .pi_tables import TABLES as _PI_TABLES          # noqa: E402  (v0.24: P-I's)
DSP_TABLES.update(_PI_TABLES)


@functools.lru_cache(maxsize=None)
def host_table(name: str) -> tuple[int, ...]:
    return tuple(os_longs(*HOST_TABLES[name]))


@functools.lru_cache(maxsize=None)
def dsp_table(name: str) -> tuple[int, ...]:
    return tuple(words(*DSP_TABLES[name]))
