"""DPRO-DENS and DPRO-DDRW's common ground (docs/mnm.md): three leaf subroutines and the tables.

Both read a Digibank wave (2048 24-bit words: nine mip levels, 1024 >> L samples at
2048 - 2^(11-L)) at twice the rate (32 samples a block) and bring it to 16 with the kernel's
2:1 allpass decimator (P:0x458). Per oscillator and block (the kernel's P:0x408/0x3EC and
P:0x421, and the machines' own level code):

- `start` (leaf): from the increment b (top-level samples a 2x step, 24 fraction bits, an
  unsigned int) and the phase u (top-level samples, 22 fraction bits: the Monomachine's
  phase >> 2, which keeps it exact: the phase moves 32 b a block), the level (shift
  = clamp(floor(log2 b) - 23, 0, 8), its mask and offset in the wave), the start sample
  i0 = floor(pos - hf) - 1 (mod the level's size) and frac0, the level's increment, and the
  top-1/16-octave crossfade weight wx = clamp(16 (mantissa(b) - 0.9375), 0, 1);
- the machine builds 37 samples from i0 into BUF;
- `interp` (leaf): 32 samples at frac0 + k inc from BUF through the kernel's 5-tap,
  32-phase filter with linear interpolation between phases (x/y:0x334.. of the kernel's
  internal memory: `rom.interp_coefs`), clamped, times `g`, into `out` (added to it if `m`);
- `dec2` (leaf): 32 samples at MIX -> 16 at I4 through nine first-order allpass stages,
  y_j = x_{j-1} + c (x_j - y_{j-1}), on the even samples (c1, c4, c1', then a delay: c = 0)
  and the odd ones (c2, c3, c2', a delay, c5), out_j = (even_j + odd_j) / 2: the kernel's
  P:0x458..0x4A7. State: two words a stage (the last input, the last output), 18.

The 56300's truncations (each stage's limited store, lim of the slope sum) are float here.
"""

from __future__ import annotations

from . import core as C
from . import rom
from ..md import core as K
from ..perc.dsl import Prog, bits

NBUF = 37                                     # samples built a level (the kernel's n2 + 1)
DEC_WORDS = 18


def q23(p: Prog, d: int, r: int) -> None:
    """Fd = the 24-bit word in Rr as a Q23 fraction. Clobbers R12."""
    p.lsh(d, r, 8)
    p.iconst(12, -31)
    p.float_(d, d, 12)


def addr(p: Prog, d: int, a: int, b: int) -> None:
    """Rd = Ra + Rb (integer; any registers). Clobbers R12 unless a is R8..R15."""
    if 8 <= a <= 15:
        p.iop(d, a, "+", b)
    else:
        p.ipass(12, a)
        p.iop(d, 12, "+", b)


# -- start --------------------------------------------------------------------------------
def _start(p: Prog, L: C.Layout) -> None:
    W = L.W
    p.ld(1, W["bs"])
    p.lsh(1, 1, -8)
    p.iconst(12, 0)
    p.float_(2, 1, 12)
    p.lsh(3, 2, -23)                            # the biased exponent of bs >> 8
    p.iconst(12, -142)
    p.iop(3, 12, "+", 3)
    p.iconst(12, 0)
    p.iop(3, 3, "MAX", 12)
    p.iconst(12, 8)
    p.iop(3, 3, "MIN", 12)
    p.st(W["sh"], 3)                            # shift
    p.iconst(12, 0)
    p.iop(4, 12, "-", 3)                        # -shift
    p.iconst(5, 1024)
    p.float_(6, 5, 4)
    p.trunc(5, 6)                               # size
    p.iconst(12, -1)
    p.iop(6, 12, "+", 5)
    p.st(W["msk"], 6)
    p.ipass(12, 5)
    p.iop(7, 12, "+", 5)
    p.iconst(12, 2048)
    p.iop(7, 12, "-", 7)
    p.st(W["boff"], 7)                          # 2048 - 2 size
    p.ld(1, W["b"])
    p.lsh(2, 1, -1)
    p.iconst(12, -23)
    p.iop(8, 12, "+", 4)
    p.float_(2, 2, 8)
    p.st(W["il"], 2)                            # b / 2^(24 + shift)
    p.lsh(1, 1, -8)
    p.iconst(12, 0)
    p.float_(2, 1, 12)
    p.iconst(12, 0x7FFFFF)
    p.iop(2, 2, "AND", 12)
    p.iconst(12, 0x3F000000)
    p.iop(2, 2, "OR", 12)                       # the mantissa, 0.5..1
    p.fconst(12, -0.9375)
    p.fop(2, 2, "+", 12)
    p.fconst(12, 16.0)
    p.fop(2, 2, "*", 12)
    p.fconst(12, 0.0)
    p.fop(2, 2, "MAX", 12)
    C.sat(p, 2)
    p.st(W["wx"], 2)
    # the start: pos = u >> shift (22 + shift fraction bits), less hf
    p.ld(1, W["u"])
    p.lsh(2, 1, -22)
    p.iconst(12, 0x3FFFFF)
    p.iop(3, 1, "AND", 12)
    p.float_(5, 2, 4)
    p.trunc(6, 5)                               # its whole part
    p.iconst(12, 0)
    p.float_(7, 6, 12)
    p.fop(5, 5, "-", 7)
    p.iconst(12, -22)
    p.iop(8, 12, "+", 4)
    p.float_(7, 3, 8)
    p.fop(5, 5, "+", 7)                         # its fraction
    p.ld(7, W["hf"])
    p.fop(5, 5, "-", 7)

    def borrow():
        p.fconst(12, 1.0)
        p.fop(5, 5, "+", 12)
        p.iconst(12, -1)
        p.iop(6, 12, "+", 6)
    p.ifz(5, "LT", borrow, kind="f")
    p.st(W["fr"], 5)
    p.iconst(12, -1)
    p.iop(6, 12, "+", 6)
    p.ld(7, W["msk"])
    p.iop(6, 6, "AND", 7)
    p.st(W["i0"], 6)


def start(p: Prog, L: C.Layout) -> None:
    """W b, bs, u, hf -> sh, msk, boff, il, wx, fr, i0. Clobbers R1-R8, R12, I12."""
    p.call("dp_start", lambda: _start(p, L))


# -- interp -------------------------------------------------------------------------------
def _interp(p: Prog, L: C.Layout) -> None:
    W = L.W
    p.ld(1, W["fr"])
    p.st(W["P"], 1)

    def one():
        p.ld(1, W["P"])
        p.trunc(2, 1)                           # the buffer index
        p.iconst(12, 0)
        p.float_(3, 2, 12)
        p.fop(3, 1, "-", 3)
        p.fconst(12, 0.5)
        p.fop(3, 3, "+", 12)
        p.fconst(12, 1.0)
        p.if_(3, "GE", 12, lambda: p.fop(3, 3, "-", 12))
        p.fconst(12, 32.0)
        p.fop(3, 3, "*", 12)
        p.trunc(4, 3)                           # the phase, 0..31
        p.iconst(12, 0)
        p.float_(5, 4, 12)
        p.fop(6, 3, "-", 5)                     # the residual
        p.lsh(2, 2, 2)
        p.iconst(12, L.BUF)
        p.iop(2, 12, "+", 2)
        p.seti(1, 2)
        p.lsh(5, 4, 5)
        p.lsh(7, 4, 3)
        p.ipass(12, 5)
        p.iop(5, 12, "+", 7)                    # 40 words a phase
        p.iconst(12, L.DT["interp"])
        p.iop(5, 12, "+", 5)
        p.seti(2, 5)
        p.fconst(7, 0.0)

        def tap():
            p.ldpost(8, 1)
            p.ldpost(9, 2)
            p.ldpost(10, 2)
            p.fop(10, 10, "*", 6)
            p.fop(9, 9, "+", 10)
            p.fop(9, 9, "*", 8)
            p.fop(7, 7, "+", 9)
        p.loop(W["t"], 5, tap)
        C.sat(p, 7)
        p.ld(10, W["g"])
        p.fop(7, 7, "*", 10)
        p.ld(8, W["out"])
        p.seti(5, 8)
        p.ld(10, W["m"])
        p.ifz(10, "NE", lambda: (p.ldi(9, 0, 5), p.fop(7, 7, "+", 9)))
        p.stpost(5, 7)
        p.iconst(12, 4)
        p.iop(8, 8, "+", 12)
        p.st(W["out"], 8)
        p.ld(1, W["P"])
        p.ld(2, W["il"])
        p.fop(1, 1, "+", 2)
        p.st(W["P"], 1)
    p.loop(W["k"], 32, one)


def interp(p: Prog, L: C.Layout) -> None:
    """32 samples from BUF at W fr + k il -> W out (int address, walked), x W g (float), added
    to what is there if W m (int) != 0. Clobbers R0-R12, I1, I2, I5, I12."""
    p.call("dp_interp", lambda: _interp(p, L))


# -- dec2 ---------------------------------------------------------------------------------
def _dec2(p: Prog, L: C.Layout) -> None:
    W = L.W
    p.iconst(12, L.DT["dec2"])
    p.seti(1, 12)

    def stage():
        p.ldpost(3, 1)                          # c
        p.iconst(5, L.MIX)                      # stages 0..3 the even samples, 4..8 the odd
        p.ld(0, W["st"])
        p.iconst(12, 5)
        p.if_(0, "LE", 12, lambda: p.iconst(5, L.MIX + 4), kind="i")
        p.ldi(1, 0, 2)
        p.ldi(2, 1, 2)

        def one():
            p.seti(5, 5)
            p.ldi(4, 0, 5)
            C.sat(p, 4)
            p.fop(6, 4, "-", 2)
            p.fop(6, 6, "*", 3)
            p.fop(2, 1, "+", 6)
            C.sat(p, 2)                         # the 56300 stores (and feeds back) it limited
            p.fpass(1, 4)
            p.sti(0, 5, 2)
            p.iconst(13, 8)
            p.iop(5, 13, "+", 5)
        p.loop(W["j"], 16, one)
        p.stpost(2, 1)
        p.stpost(2, 2)
    p.loop(W["st"], 9, stage)
    p.iconst(12, L.MIX)
    p.seti(5, 12)

    def out():
        p.ldpost(1, 5)
        p.ldpost(2, 5)
        p.fop(1, 1, "+", 2)
        p.fconst(12, 0.5)
        p.fop(1, 1, "*", 12)
        C.sat(p, 1)
        p.stpost(4, 1)
    p.loop(W["j"], 16, out)


def dec2(p: Prog, L: C.Layout) -> None:
    """MIX (32) -> 16 at I4 (walked); I2 the 18 state words. Clobbers R0-R13, I1, I2, I5, I12."""
    p.call("dp_dec2", lambda: _dec2(p, L))


def state_ptr(p: Prog, L: C.Layout, i: int, k: int) -> None:
    """Ii = the slot's state word k. Clobbers R12-R14."""
    p.ld(14, L.md.C["mdb"])
    p.iconst(13, 4 * (K.S0 + k))
    p.iop(13, 13, "+", 14)
    p.seti(i, 13)


def zero(p: Prog, L: C.Layout, k: int, n: int) -> None:
    """the slot's state words k..k+n-1 = 0. Clobbers R0-R1, R12-R14, I1."""
    state_ptr(p, L, 1, k)
    p.iconst(1, 0)
    p.loop(L.W["j"], n, lambda: p.stpost(1, 1))


def unsigned(p: Prog, d: int, f: int) -> None:
    """Rd = the float Ff (0 .. 2^32) as an unsigned 32-bit int (TRUNC saturates at 2^31).
    Clobbers R12, R13, Ff."""
    p.fconst(12, 2.0 ** 31)
    p.fop(f, f, "-", 12)
    p.trunc(d, f)
    p.iconst(13, 1 << 31)
    p.iop(d, 13, "+", d)


# -- the Digibank stand-in, built by the DSP ------------------------------------------------
BUILD_PER_BLOCK = 12                          # outputs a call (about 2,000 instructions)


def _build_one(p: Prog, L: C.Layout) -> None:
    """One output of the build: wave w (0..31), pass l, sample j (L.DG). Pass 0: level 0
    (1024) = the ROM wave (512) zero-stuffed through the halfband x 2; pass l = 1..9: the
    halfband of level l-1 (N = 1024 >> (l-1) samples, circular), whose even samples are level
    l (l <= 8) and whose samples are level l-1's crossfade partner, two bytes in the low bytes
    of level l-2's words 2j, 2j+1 (l >= 2). Each level word: the 16-bit sample << 8."""
    G, W = L.DG, L.W
    p.ld(1, G["l"])
    p.iconst(12, -1)
    p.iop(2, 12, "+", 1)
    p.iconst(12, 0)
    p.iop(2, 2, "MAX", 12)
    p.iconst(12, 0)
    p.iop(2, 12, "-", 2)
    p.iconst(3, 1024)
    p.float_(3, 3, 2)
    p.trunc(3, 3)                               # N
    p.st(W["n2"], 3)
    p.iconst(12, -1)
    p.iop(4, 12, "+", 3)
    p.st(W["msk"], 4)
    p.ld(5, G["w"])
    p.lsh(6, 5, 13)
    p.iconst(12, L.DIGI)
    p.iop(6, 12, "+", 6)
    p.st(W["cb"], 6)                            # the wave's words
    p.lsh(7, 3, 1)
    p.iconst(12, 2048)
    p.iop(7, 12, "-", 7)
    p.lsh(7, 7, 2)
    addr(p, 7, 7, 6)
    p.st(W["fb"], 7)                            # level l-1's words (pass l >= 1)
    p.lsh(5, 5, 11)
    p.iconst(12, L.tables)
    p.iop(5, 12, "+", 5)
    p.st(W["wb"], 5)                            # the ROM wave's samples (pass 0)
    p.ld(1, G["j"])
    p.iconst(12, -3)
    p.iop(1, 12, "+", 1)
    p.st(W["i0"], 1)
    p.iconst(12, L.DT["hb"])
    p.seti(2, 12)
    p.fconst(9, 0.0)
    p.st(W["fr"], 9)

    def tap():
        p.ld(1, W["i0"])
        p.ld(2, W["msk"])
        p.iop(2, 1, "AND", 2)                   # k
        p.iconst(12, 1)
        p.iop(1, 12, "+", 1)
        p.st(W["i0"], 1)
        p.ld(3, G["l"])

        def src():                              # the ROM wave, zero-stuffed
            p.fconst(4, 0.0)
            p.iconst(12, 1)
            p.iop(5, 2, "AND", 12)

            def even():
                p.lsh(5, 2, 1)                  # (k >> 1) x 4
                p.ld(6, W["wb"])
                addr(p, 5, 5, 6)
                p.seti(1, 5)
                p.ldi(4, 0, 1)
                p.fop(4, 4, "+", 4)
            p.ifz(5, "EQ", even)

        def lev():
            p.lsh(5, 2, 2)
            p.ld(6, W["fb"])
            addr(p, 5, 5, 6)
            p.seti(1, 5)
            p.ldi(4, 0, 1)
            p.iconst(12, 0xFFFF00)
            p.iop(4, 4, "AND", 12)
            q23(p, 4, 4)
        p.ifz(3, "EQ", src, lev)
        p.ldpost(5, 2)
        p.fop(4, 4, "*", 5)
        p.ld(9, W["fr"])
        p.fop(9, 9, "+", 4)
        p.st(W["fr"], 9)
    p.loop(W["t"], 7, tap)
    p.ld(9, W["fr"])
    p.fconst(12, 32768.0)
    p.fop(9, 9, "*", 12)
    p.fconst(12, 32767.0)
    p.fop(9, 9, "MIN", 12)
    p.fconst(12, -32768.0)
    p.fop(9, 9, "MAX", 12)
    p.trunc(9, 9)                               # the 16-bit sample
    p.iconst(12, 0xFFFF)
    p.iop(8, 9, "AND", 12)
    p.lsh(8, 8, 8)                              # as a level word
    p.ld(1, G["l"])
    p.ld(2, G["j"])
    p.ld(3, W["n2"])

    def main0():                                # level 0, word j
        p.lsh(4, 2, 2)
        p.ld(5, W["cb"])
        addr(p, 4, 4, 5)
        p.seti(1, 4)
        p.sti(0, 1, 8)

    def mainl():                                # level l, word j / 2, j even, l <= 8
        p.iconst(12, 1)
        p.iop(4, 2, "AND", 12)
        p.iconst(12, 9)

        def go():
            p.lsh(4, 2, 1)                      # (j / 2) x 4
            p.iconst(12, 2048)
            p.iop(5, 12, "-", 3)                # level l's offset: 2048 - N
            p.lsh(5, 5, 2)
            addr(p, 4, 4, 5)
            p.ld(5, W["cb"])
            addr(p, 4, 4, 5)
            p.seti(1, 4)
            p.sti(0, 1, 8)
        p.ifz(4, "EQ", lambda: p.if_(1, "LT", 12, go, kind="i"))

        def partner():                          # level l-2: words 2j, 2j+1, offset 2048 - 4N
            p.lsh(4, 2, 3)
            p.lsh(5, 3, 2)
            p.iconst(12, 2048)
            p.iop(5, 12, "-", 5)
            p.lsh(5, 5, 2)
            addr(p, 4, 4, 5)
            p.ld(5, W["cb"])
            addr(p, 4, 4, 5)
            p.seti(1, 4)
            p.iconst(12, -0x100)
            p.ldi(5, 0, 1)
            p.iop(5, 5, "AND", 12)
            p.lsh(6, 9, -8)
            p.iconst(12, 0xFF)
            p.iop(6, 6, "AND", 12)
            p.iop(5, 5, "OR", 6)
            p.sti(0, 1, 5)
            p.iconst(12, -0x100)
            p.ldi(5, 1, 1)
            p.iop(5, 5, "AND", 12)
            p.iconst(12, 0xFF)
            p.iop(6, 9, "AND", 12)
            p.iop(5, 5, "OR", 6)
            p.sti(1, 1, 5)
        p.iconst(12, 2)
        p.if_(1, "GE", 12, partner, kind="i")
    p.ifz(1, "EQ", main0, mainl)
    # j, l, w move on
    p.ld(2, G["j"])
    p.iconst(12, 1)
    p.iop(2, 12, "+", 2)
    p.ld(3, W["n2"])

    def wrap():
        p.iconst(2, 0)
        p.ld(1, G["l"])
        p.iconst(12, 1)
        p.iop(1, 12, "+", 1)
        p.iconst(12, 10)

        def nextwave():
            p.iconst(1, 0)
            p.ld(4, G["w"])
            p.iconst(12, 1)
            p.iop(4, 12, "+", 4)
            p.st(G["w"], 4)
        p.if_(1, "GE", 12, nextwave, kind="i")
        p.st(G["l"], 1)
    p.if_(2, "GE", 3, wrap, kind="i")
    p.st(G["j"], 2)


def build(p: Prog, L: C.Layout) -> None:
    """The Digibank stand-in, BUILD_PER_BLOCK outputs a call, once the tables are filled
    (dnfw.md.core.table_fill: C['fill'] = Z_N) and until L.DG w = 32 (then DENS and DDRW
    play). Clobbers R0-R13, I1, I2."""
    W = L.W

    def go():
        def one():
            p.ld(1, L.DG["w"])
            p.iconst(12, 32)
            p.if_(1, "LT", 12, lambda: _build_one(p, L), kind="i")
        p.loop(W["osc"], BUILD_PER_BLOCK, one)
    p.ld(1, L.md.C["fill"])
    p.iconst(12, K.Z_N)
    p.if_(1, "GE", 12, go, kind="i")


def ready(p: Prog, L: C.Layout, then) -> None:
    """then() once the stand-in is built; else 16 zeros at I4 (DENS/DDRW are silent till then)"""
    def zeros():
        p.fconst(1, 0.0)
        p.loop(L.W["j"], 16, lambda: p.stpost(4, 1))
    p.ld(1, L.DG["w"])
    p.iconst(12, 32)
    p.if_(1, "GE", 12, then, zeros, kind="i")


_REF = None


def digibank_reference(L: C.Layout | None = None) -> tuple[int, ...]:
    """The stand-in as the DSP builds it: `build` run in run mode until done (this is its
    definition; the golden runs and the bench load these words). 32 x 2048 24-bit words."""
    global _REF
    if _REF is None:
        import hashlib, os, pathlib, struct, tempfile
        from . import bench
        L = L or bench.layout()
        key = hashlib.sha256(pathlib.Path(__file__).read_bytes()
                             + repr(rom.table_words()).encode()).hexdigest()[:16]
        f = pathlib.Path(tempfile.gettempdir()) / f"dnfw_mnm_digibank_{key}.bin"
        if f.exists():
            _REF = struct.unpack(f"<{C.DIGI_WORDS}I", f.read_bytes())
            return _REF
        from ..perc.dsl import Mem
        tm = {}
        for k, v in enumerate(rom.table_words()):
            tm[L.tables + 4 * k] = bits(v * C.Q23)
        tm[L.md.C["fill"]] = K.Z_N
        mem = Mem(lambda a: tm.get(a, 0))
        p = Prog("run", mem=mem)
        while mem.get(L.DG["w"]) < 32:
            build(p, L)
        _REF = tuple(mem.get(L.DIGI + 4 * k) & 0xFFFFFF for k in range(C.DIGI_WORDS))
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(struct.pack(f"<{C.DIGI_WORDS}I", *_REF))
        os.replace(tmp, f)
    return _REF


def bench_words(L: C.Layout) -> dict[int, int]:
    """the bench's memory past the shipped tables: the stand-in, built (and its done word)"""
    out = {L.DIGI + 4 * k: v for k, v in enumerate(digibank_reference(L))}
    out[L.DG["w"]] = 32
    return out
