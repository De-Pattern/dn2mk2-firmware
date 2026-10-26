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


# -- DPRO-DENS / DPRO-DDRW (v0.26) ----------------------------------------------------------
PCH = (0x101AFB, 128)                         # DENS: PCH ratio, knob -> r x 0x200000
WID = (0x101BFB, 128), (0x101CFB, 128)        # DDRW: WID detune down / up (0x400000 unison)
EXP = (0x140000, 2048)                        # the kernels' exp table


@functools.lru_cache(maxsize=1)
def kernel_xy() -> tuple[dict[int, int], dict[int, int]]:
    """DSP A's kernel image (block 1): its internal X and Y memory records."""
    d = blocks()[1]
    X: dict[int, int] = {}
    Y: dict[int, int] = {}
    o = 6 if d[0] == 3 else 0
    if d[o] == 4:
        o += 6
    while o < len(d):
        t = _w(d, o)
        if t > 2:
            break
        a, n = _w(d, o + 3), _w(d, o + 6)
        if t:
            sp = X if t == 1 else Y
            for k in range(n):
                sp[a + k] = _w(d, o + 9 + 3 * k)
        o += 9 + 3 * n
    return X, Y


@functools.lru_cache(maxsize=1)
def interp_words() -> tuple[int, ...]:
    """The DDRW/DENS interpolator (kernel P:0x421): 32 phases x 5 taps as (B_i, 2 A_i) pairs,
    signed Q23 words: B from x/y:0x334.. (stride 0x20), A the slope set (the residual's product
    is MPYSU: 2 A). The kernel's internal X/Y memory (block 1)."""
    X, Y = kernel_xy()
    out = []
    for ph in range(32):
        c = 0x334 + ph
        B = (Y[c + 0x20], X[c + 0x60], Y[c + 0x80], Y[c + 0xC0], Y[c + 0xE0])
        A = (Y[c], Y[c + 0x40], Y[c + 0x60], Y[c + 0xA0], X[c + 0xC0])
        for b, a in zip(B, A):
            out += [s24(b), 2 * s24(a)]
    return tuple(out)


DEC2 = (0x1583E8, 0x4092FF, 0x66E24C, 0, 0x05DA6B, 0x2A8F65, 0x54E3CE, 0, 0x778898)
"""the kernel's 2:1 allpass decimator (P:0x458): nine stages' c, even samples' four, odd's five"""
HALFBAND = (-0x40000, 0, 0x240000, 0x400000, 0x240000, 0, -0x40000)
"""the Digibank stand-in's halfband (taps -3..3: -1/32, 0, 9/32, 1/2), dnfw.mnm.dpro.build"""


def dpro_words() -> tuple[int, ...]:
    """DPRO-DENS / DPRO-DDRW's tables, signed words (the DSP holds each as FLOAT w BY -23), in
    the order dnfw.mnm.core.DP_TABLES lays them out: the interpolator (320), the decimator's
    c (9), the stand-in's halfband (7), PCH (128: r x 2^21 = 1.0), WID down / up less 0x400000
    (2 x 128), the bit reduction (X48, X49: 2 x 128). TIME (0x7FFFFF/(k+1)) is computed."""
    out = list(interp_words()) + [s24(c) for c in DEC2] + list(HALFBAND)
    out += [s24(v) for v in words(*PCH)]
    out += [s24(v) - 0x400000 for t in WID for v in words(*t)]
    out += list(br_table())
    return tuple(out)


@functools.lru_cache(maxsize=1)
def br_table() -> tuple[int, ...]:
    """DDRW's bit reduction (P:0x147BE5) for BR 0..127: (X48, X49) pairs, the words the
    reducer reads: e = 192 BR (1/2048 octave), n = e >> 11, f = e & 0x7FF; X48 = a1 of
    (exp[f] >> 13) << n, X49 = a1 of exp[0x7FF - f] >> 8 >> n (accumulators, a1 = >> 24)."""
    ex = words(*EXP)
    out = []
    for k in range(128):
        e = 192 * k
        n, f = e >> 11, e & 0x7FF
        a = (s24(ex[f]) << 24) >> 13 << n
        b = (s24(ex[(0x7FF - f) & 0x7FF] if f else ex[0x7FF]) << 24) >> 8 >> n
        out += [(a >> 24) & 0xFFFFFF, (b >> 24) & 0xFFFFFF]
    return tuple(out)


@functools.lru_cache(maxsize=1)
def table_words() -> tuple[int, ...]:
    """Every table the machines read, in the order dnfw.mnm.core.Layout addresses them
    (signed words; the DSP holds each as FLOAT w BY -23): DPRO-WAVE's samples, then
    SID's combined waveforms >> 16 (each render scales them back), then DPRO-DENS/DDRW's
    (dpro_words; their Digibank stand-in the DSP builds itself, dnfw.mnm.dpro.build), then
    VO-6's (vo6_words)."""
    return wave_samples() + comb8() + dpro_words() + vo6_words()


WAVE_WORDS = 33 * 512                         # the samples' words at the tables' start


def packed_words() -> tuple[int, ...]:
    """table_words() as zpack carries them: DPRO-WAVE's samples as (hi, lo) pairs, one per
    ROM word w (lo = its low 12 bits, signed; hi = (w - lo) >> 12), which the DSP's fill
    turns back into (w, lo << 12) (dnfw.md.core.table_fill: hi x 4096 + lo, lo x 4096, exact
    in float); then the rest as they are. Half the bits of the words themselves."""
    out = []
    for w in words(*WAVES):
        lo = s24(w << 12) >> 12
        out += [(s24(w) - lo) >> 12, lo]
    return tuple(out) + table_words()[WAVE_WORDS:]


def comb8() -> tuple[int, ...]:
    """SID's combined waveforms as the tables hold them: each word >> 16 (8 bits << 16)."""
    return tuple(s24(w) >> 16 for w in words(*COMB))


# -- VO-6 (v0.26, dnfw.mnm.vo6) -------------------------------------------------------------
VO_C1 = (0x1001D1, 4 * 0x620)                 # the four resonators' input gains (j = F 0x620 >> 23)
VO_COS = (0x141B23, 0x614)                    # cos(2 pi f / 44100) on F's index (i = F 0x614 >> 23)
VO_BLIT = (0x131, 0x333 - 0x131 + 1)          # the pulse's shape: DSP A's kernel, internal Y
VO_LOG = (0x1445C6, 256)                      # the AGC's log2 mantissas
# the trig's consonant set-ups (P:0x146577.. through x:0x101A51 + k), one row a consonant: x32,
# y32 = x1?, x33, y33, x34, x35, x36 (c, + x1?), y36, x37 (0: c; 1: c0 + kk CVOL / 128), x40 (c,
# + x1?), V-SW?, B's y39 (the 56300's immediates; x1 the CLEN term)
VO_TRIG = (
    (0x76E3, 0, 0xDC, 0x4A4E, 0xBE3, 2, 0, 0, 0xEDC6, 0, 0, 0, 0, 0, 0, 0),
    (0x2E709E, 0, 0, 0x17384F, 0x76E3, 1, 0, 0, 0x2526E, 0, 0, 0, 0x7C, 0, 1, 1),
    (0x2E709E, 0, 0x18, 0x420C4, 0xEDC6, 1, 2, 0, 0x2526E, 1, 0x147AE, 0x8F5C3, 0, 0, 1, 0),
    (0xEDC6, 1, 0x37, 0x12937, 0x76E3, 1, 0xC0, 1, 0xEDC6, 1, 0xCCCCD, 0x733333, 0, 0, 1, 0),
    (0x2E709E, 0, 0x18, 0x420C4, 0xEDC6, 1, 0x1B, 0, 0x2526E, 1, 0x66666, 0x266666, 0, 0, 1, 0),
    (0xEDC6, 1, 0x37, 0, 0x2E709E, 1, 0x8F, 1, 0x18C4A, 1, 0x147AE, 0xA3D71, 0, 0, 1, 0),
    (0xEDC6, 1, 0xD, 0, 0x76E3, 2, 0x89, 0, 0x2526E, 0, 0, 0, 0x113, 1, 1, 0),
    (0x2E709E, 0, 0x37, 0, 0xEDC6, 1, 0x39, 0, 0xEDC6, 1, 0x147AE, 0x400000, 0, 0, 1, 0),
    (0xEDC6, 1, 0x89, 0, 0x153AD, 2, 0x89, 0, 0x2526E, 0, 0, 0, 0xEA, 1, 1, 0),
    (0xEDC6, 1, 0x89, 0, 0x153AD, 2, 0x89, 0, 0x2526E, 0, 0, 0, 0xEA, 1, 1, 0),
    (0xEDC6, 1, 0x89, 0, 0x153AD, 2, 0x89, 0, 0x2526E, 0, 0, 0, 0xEA, 1, 1, 0),
    (0x949B9, 0, 0xD, 0x3B717, 0x4755, 1, 0x1B, 0, 0x2526E, 1, 0x66666, 0x266666, 0, 0, 1, 0),
    (0xEDC6, 1, 0xD, 0, 0x76E3, 2, 0x52, 0, 0x18C4A, 0, 0, 0, 0xC0, 1, 1, 0),
    (0x2526E, 1, 0x89, 0, 0x153AD, 2, 0x37, 0, 0x2526E, 0, 0, 0, 0xB3, 1, 1, 0),
    (0xEDC6, 1, 0x37, 0x12937, 0x76E3, 1, 0xC0, 1, 0xEDC6, 1, 0xA3D7, 0x66666, 0, 0, 1, 0),
    (0x18C4A, 1, 0x6E, 0, 0xEDC6, 1, 0xC0, 1, 0x2526E, 1, 0x147AE, 0xAE148, 0, 0, 1, 0),
    (0x2E709E, 0, 0x52, 0x13D08, 0x2F8E, 1, 0x55, 0, 0xA9D6, 1, 0x147AE, 0x333333, 0, 0, 1, 0),
    (0xEDC6, 1, 0x37, 0x12937, 0x76E3, 1, 0xC0, 1, 0xEDC6, 1, 0xCCCCD, 0x666666, 0, 0, 1, 0),
    (0x2E709E, 1, 0x18, 0x10831, 0x5F1C, 1, 0x39, 1, 0x17F81, 1, 0x147AE, 0xAE148, 0, 0, 1, 0),
    (0xEDC6, 1, 0x37, 0, 0xEDC6, 2, 0x37, 0, 0x18C4A, 0, 0x19999A, 0, 0x7C, 1, 1, 0),
    (0xEDC6, 1, 0x37, 0x12937, 0x76E3, 1, 0xC0, 1, 0xEDC6, 1, 0xA3D7, 0x66666, 0, 0, 1, 0),
)
VO_TRIG_W = 16


def vo6_clen() -> tuple[int, ...]:
    """CLEN 0..127 -> x1 = lim(0x562 x ((CLEN^2)^2)), each square a 24-bit MPY (the trig's)"""
    def mpy_a1(x, y):
        return min((s24(x) * s24(y)) << 1 >> 24, 0x7FFFFF)
    out = []
    for k in range(128):
        x0 = mpy_a1(k << 16, k << 16)
        x0 = mpy_a1(x0, x0)
        out.append(mpy_a1(0x562, x0))
    return tuple(out)


def vo6_log() -> tuple[int, ...]:
    """the AGC's log2 mantissa words L as the gain uses them: L / 2^14, rounded half to even
    (the render's RND, exact: what L contributes to the rounded exponent)"""
    out = []
    for L in words(*VO_LOG):
        q, r = divmod(L, 1 << 14)
        if r > 1 << 13 or (r == 1 << 13 and q & 1):
            q += 1
        out.append(q)
    return tuple(out)


@functools.lru_cache(maxsize=1)
def vo6_words() -> tuple[int, ...]:
    """VO-6's tables in dnfw.mnm.core.VO_TABLES's order (signed 24-bit words): the gains, the
    cosines, the pulse shape, the log mantissas, CLEN's terms, the consonants' set-ups and
    renderers"""
    _, Y = kernel_xy()
    out = [s24(v) for v in words(*VO_C1)] + [s24(v) for v in words(*VO_COS)]
    out += [s24(Y.get(VO_BLIT[0] + k, 0)) for k in range(VO_BLIT[1])]
    out += list(vo6_log()) + list(vo6_clen())
    out += [row[f] for f in range(VO_TRIG_W) for row in VO_TRIG]     # field-major: zpack packs it
    c = vo6_cons()
    out += [c[VO_CONS_W * k + f] for f in range(VO_CONS_W) for k in range(21)]
    return tuple(out)


# the consonants' renderers (P:0x146B3D.. through x:0x101A66 + k), as data: up to four offset
# ops, each O[mask] = MPY(lim(C - V[v]), W) and then O[mask2] = MPY(that, g2), W by mode (0:
# V[w]; 1: the constant w; 2: -MPY(V[w], c); 3: MPY(V[w], V[c])), V = (0, F0..F3, y35, y31,
# x55); the source (0: the noise / 8; 1: a biquad on it; 2: a biquad on the excitation, then
# the crossfade to xk; 3: Z's mix, the biquad, the crossfade; 4: RR's trill and scaling), its
# five coefficients, and when y40 ends the consonant (1: x35 > 3; 2: x31 > 4; 3: x31 == 5)
_T = lambda v, c, m1, m2=0, g2=0: (v, c, 0, 6, 0, m1, m2, g2)              # MPY(lim(c - V), y31)
VO_CONS = (
    ((), 0, 0, (0,) * 5, 0),
    (((5, 0x7FFFF8, 2, 1, 0xCCCCD, 1, 0, 0), (5, 0x7FFFF8, 2, 2, 0xCCCCD, 2, 0, 0)), 0, 0, (0,) * 5, 1),
    ((_T(2, 0x6AF0DD, 32, 2, 0x400000),), 1, 0, (0xB57FC, 0x16AFF7, 0xB57FC, 0xDF712C, 0xDEEC2), 0),
    ((_T(1, 0x423899, 17), _T(2, 0x5747BC, 34)), 1, 0, (0x44345, 0, 0xFBBCBB, 0x108B19, 0x377976), 0),
    (((5, 0x7FFFF8, 1, 0x511C4C, 0, 4, 0, 0),), 1, 0, (0xF879, 0x1F0F3, 0xF879, 0x98261C, 0x2BBBCA), 1),
    (((5, 0x7FFFF8, 1, 0x41CF5, 0, 15, 0, 0), _T(0, 0x41CF5, 240)), 1, 0,
     (0x30E9A, 0x61D34, 0x30E9A, 0xAD3392, 0x1F06D6), 1),
    ((_T(1, 0x40543D, 1), _T(2, 0x607E5B, 2), _T(3, 0x652EBA, 4)), 0, 0, (0,) * 5, 0),
    (((5, 0x7FFFF8, 1, 0x41CF5, 0, 4, 0, 0), (6, 0x7FFFF8, 1, 0x41CF5, 0, 64, 0, 0)), 1, 0,
     (0x6A9D, 0xD53A, 0x6A9D, 0x8F6951, 0x324122), 1),
    ((_T(1, 0x3C0D29, 1), _T(2, 0x5C2239, 2)), 2, 0x800000,
     (0x3DCC43, 0x896360, 0x3DCC43, 0x896360, 0x3B9885), 0),
    ((_T(0, -0x1B2583, 1),), 2, 0x7FFFF8, (0x3BBCBB, 0x89BC72, 0x3BBCBB, 0x89BC72, 0x377976), 0),
    ((_T(1, 0x3C0D29, 1), _T(2, 0x5C2239, 2)), 2, 0x7FFFF8,
     (0x37F898, 0x91F8F7, 0x37F898, 0x91F8F7, 0x2FF130), 0),
    (((5, 0x7FFFF8, 2, 1, 0x266666, 16, 1, 0x400000), (5, 0x7FFFF8, 2, 2, 0x266666, 32, 2, 0x400000)),
     1, 0, (0x4B6F, 0x96DD, 0x4B6F, 0x8CDB9B, 0x345220), 2),
    ((_T(0, -0x3C0D29, 1), _T(3, 0x5AA728, 4)), 0, 0, (0,) * 5, 0),
    (((0, -0x3C0D29, 3, 7, 6, 1, 0, 0), _T(3, 0x5AA728, 4)), 4, 0, (0,) * 5, 3),
    ((_T(2, 0x6D68A3, 32, 2, 0x400000),), 1, 0, (0x26729D, 0xB31AC6, 0x26729D, 0xBDBFC1, 0x178A36), 0),
    ((_T(1, 0x40543D, 17), _T(2, 0x607E5B, 34), _T(3, 0x652EBA, 64)), 1, 0,
     (0x1DA8C4, 0, 0xE2573C, 0xDABCB2, 0x4AE79), 0),
    ((_T(2, 0x6262B7, 34),), 1, 0, (0x4774A, 0x8EE95, 0x4774A, 0xB7E897, 0x19F492), 0),
    ((_T(2, 0x66D3E8, 32, 2, 0x7EB852),), 1, 0, (0x56916, 0xF52DD4, 0x56916, 0x41ABC5, 0x17501D), 0),
    ((_T(1, 0x40543D, 17), _T(2, 0x607E5B, 34), _T(3, 0x652EBA, 64)), 1, 0,
     (0x1DA8C4, 0, 0xE2573C, 0xDABCB2, 0x4AE79), 0),
    ((_T(1, 0x423899, 1), _T(2, 0x5747BC, 2)), 1, 0, (0x24AB6, 0xFB6A94, 0x24AB6, 0x597817, 0x22A2F0), 0),
    ((_T(1, 0x40543D, 1), _T(2, 0x607E5B, 2)), 3, 0x7FFFF8,
     (0x3CDB1F, 0x8649C2, 0x3CDB1F, 0x867152, 0x39DDCF), 0),
)
VO_OPS, VO_CONS_W = 4, 4 * 8 + 8


def vo6_cons() -> list[int]:
    """VO_CONS as rows: per consonant 4 ops x 8, then kind, xk, c0..c4, y40 (vo6_words stores them
    field-major: word f of consonant k at 21 f + k)"""
    out = []
    for ops, kind, xk, co, y40 in VO_CONS:
        for k in range(VO_OPS):
            out += list(ops[k]) if k < len(ops) else [0] * 8
        out += [kind, -xk] + [s24(c) for c in co] + [y40]          # xk: what the crossfade adds
    return out
