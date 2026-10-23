"""The sample machines as the DSP runs them, in Python (dnfw.sampler.program run on a
memory of our own): the pool, the frame words, the note and the buffer one slot sees."""

from __future__ import annotations

import math
import struct

from ..perc import machines as PM
from ..perc import program as PP
from ..perc.dsl import Mem, bits, flt
from . import machines as SM
from . import program as P

BUF = 0x00300000


def layout() -> P.Layout:
    from ..perc import live as PL
    from ..waverider import dsp
    return P.Layout(state=dsp.SMP_STATE_DM, scratch=dsp.SMP_SCRATCH_DM, pool=dsp.SMP_POOL_DDR,
                    exp2=PL.layout().T["exp2"], tables=dsp.SMP_TABLES_DDR, dec=dsp.SMP_DEC_DM)


def pool_bytes(samples, base: int, rates=None, fmts=None, names=None, slices=None) -> bytes:
    """the directory and the frames of SAMPLES (lists of floats), as the DSP's DDR holds
    them from BASE: magic, count, POOL_SLOTS entries (address, frames, rate, format),
    the names (dnfw.sampler.machines.NAME_BYTES each, for the ColdFire's pages; the DSP
    ignores them), then each sample's frames -- float32 (format 0) or int16 (format 1)
    -- on a 64-byte (cache line) boundary"""
    rates = rates or [1.0] * len(samples)
    fmts = fmts or [0] * len(samples)
    names = names or [""] * len(samples)
    slices = slices or [()] * len(samples)
    head = SM.DATA_OFFSET
    entries, data = [], bytearray()
    for s, r, f, sl in zip(samples, rates, fmts, slices):
        # v0.19: the format word's bits 8..15 count the sample's slices (SLICE), whose
        # table -- start, end, loop in frames -- follows its frames on a word
        assert len(sl) <= SM.MAX_SLICES
        entries.append(struct.pack("<IIfI", base + head + len(data), len(s), r, f | len(sl) << 8))
        if f == 1:
            data += struct.pack(f"<{len(s)}h", *(max(-32768, min(32767, round(x * 32768))) for x in s))
        else:
            data += struct.pack(f"<{len(s)}f", *s)
        if sl:
            data += bytes((-len(data)) % 4)
            for a, b, lp in sl:
                data += struct.pack("<III", a, b, lp)
        data += bytes((-len(data)) % 0x40)
    d = struct.pack("<II", SM.POOL_MAGIC, len(samples)) + b"".join(entries)
    d += bytes(SM.NAMES_OFFSET - len(d))
    d += b"".join(n.encode("ascii", "replace")[:SM.NAME_BYTES - 1].ljust(SM.NAME_BYTES, b"\0") for n in names)
    d += bytes(head - len(d))
    return d + bytes(data)


TEST_RATE = 24000                          # the test sounds' sample rate: half the DSP's
TEST_STEP = TEST_RATE / 48000.0            # so each plays at 0.5 frames a sample


def _noise(seed: int):
    x = seed
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x3FFFFFFF - 1.0


def test_samples() -> list[list[float]]:
    """the pool a build ships until samples can be loaded: four drum sounds made here
    (no one's recordings), at 24 kHz to keep the upgrade file small:
    1 KICK, 2 SNARE, 3 HAT, 4 BEAT (sixteen steps of the three at 12 kHz, for GRID)"""
    r = TEST_RATE
    kick = []
    ph = 0.0
    for k in range(int(0.25 * r)):
        t = k / r
        ph += (45.0 + 110.0 * math.exp(-t * 28.0)) / r
        kick.append(0.9 * math.exp(-t * 9.0) * math.sin(2 * math.pi * ph))
    nz = _noise(7)
    snare = []
    for k in range(int(0.15 * r)):
        t = k / r
        tone = 0.45 * math.exp(-t * 30.0) * math.sin(2 * math.pi * 185.0 * t)
        snare.append(tone + 0.5 * math.exp(-t * 22.0) * next(nz))
    nz = _noise(11)
    hat, prev = [], 0.0
    for k in range(int(0.06 * r)):
        x = next(nz)
        hat.append(0.5 * math.exp(-k / r * 70.0) * (x - prev))      # a crude high pass
        prev = x
    # BEAT at half that rate again (12 kHz): 16 steps of 75 ms (200 BPM sixteenths)
    step = int(0.075 * r) // 2
    beat = [0.0] * (16 * step)
    for j, hit in enumerate("K.H.SHH.K.HKS.HH"):
        src = {"K": kick, "S": snare, "H": hat}.get(hit)
        for k in range(step if src else 0):
            beat[j * step + k] += 0.85 * (src[2 * k] if 2 * k < len(src) else 0.0)
    return [kick, snare, hat, beat]


TEST_NAMES = ("KICK", "SNARE", "HAT", "BEAT")


def test_fmts() -> list[int]:
    """the test sounds are int16 (v0.14: half the bytes of v0.13's float32)"""
    return [SM.FMT_I16] * 4


def test_rates() -> list[float]:
    return [TEST_STEP] * 3 + [TEST_STEP / 2]


class Harness:
    def __init__(self, t: int = 0, samples=None, rates=None, fmts=None, slices=None):
        self.t, self.L = t, layout()
        self.samples = samples if samples is not None else test_samples()
        data = pool_bytes(self.samples, self.L.pool,
                          rates if rates is not None else test_rates(),
                          fmts if fmts is not None else test_fmts(), TEST_NAMES, slices)
        self.words = {self.L.pool + 4 * k: struct.unpack_from("<I", data, 4 * k)[0]
                      for k in range(len(data) // 4)}
        from ..perc import live as PL
        self.words.update(PL.table_words(PL.layout()))
        tb = P.tables_bytes()                   # v0.18: the DT2 reader's coefficients
        self.words.update({self.L.T["poly"] + 4 * k: struct.unpack_from("<I", tb, 4 * k)[0]
                           for k in range(len(tb) // 4)})
        self.mem = Mem(lambda a: self.words.get(a, 0))
        self.steps = 0

    def set(self, rec: int, value: int) -> None:
        """record REC to VALUE (0..top, as the knob shows it)"""
        slot, lo, top = SM.RECORDS[rec]
        a = PM.FRAME + PM.frame_offset(slot) + 146 * self.t
        w = self.mem.get(a & ~3)
        word = (min(top, max(0, value)) + lo) << 8
        w = (w & 0xFFFF) | (word << 16) if a & 2 else (w & 0xFFFF0000) | word
        self.mem.put(a & ~3, w)

    def defaults(self) -> None:
        self.set(SM.TUNE_REC, 60)        # 0 semitones
        self.set(SM.PLAY_REC, 127)       # FWD
        self.set(SM.SAMP_REC, 1)        # slot 1 (0 is OFF)
        self.set(SM.LEV_REC, 100)
        self.set(SM.STRT_REC, 0)
        self.set(SM.LEN_REC, 127)
        self.set(SM.LOOP_REC, 0)
        self.set(SM.SLEN_REC, 0)

    def command(self, cmd: int, src: int = 0, chan: int = 0, thres: float = 0.0, dest: int = 0,
                frames: int = SM.REC_FRAMES) -> None:
        """the ColdFire's next recorder command, as the sample link writes it"""
        a = self.L.pool + SM.CMD_OFFSET
        seq = (self.mem.get(a) + 1) & 0xFFFFFFFF
        for k, w in enumerate((seq, cmd, src, chan, int(thres * 32767), dest << 24 | frames)):
            self.mem.put(a + 4 * k, w)

    def status(self) -> list[int]:
        """the 16 halves of the recorder's status, as the ColdFire reads them"""
        a = SM.REPLY_PAGES[0] + SM.REPLY_TAIL
        out = []
        for k in range(8):
            w = self.mem.get(a + 4 * k)
            out += [w & 0xFFFF, w >> 16]
        return out

    def block(self, mtype: int, note: float = 60.0, trig: bool = False, recorder: bool = False,
              inp=None, trk=None) -> list[float]:
        """one block on track T as MTYPE; RECORDER: run the recorder first (as the DSP
        does), with INP (32 floats, L = R) in the engine's input block"""
        t = self.t
        a = PM.FRAME + 148 + 2 * t                # the frame's type word for the track
        w = self.mem.get(a & ~3)
        self.mem.put(a & ~3, (w & 0xFFFF) | (mtype << 16) if a & 2 else (w & 0xFFFF0000) | mtype)
        self.mem.put(PP.NOTE_CELLS + 4 * t, bits(note))
        self.mem.put(PP.TRIG_WORD, (1 << (16 + t)) if trig else 0)
        self.mem.put(PP.BUFFERS + 4 * t, BUF)
        for k in range(32):
            self.mem.put(BUF + 4 * k, bits(0.0))
        if recorder:
            for k, x in enumerate(inp or [0.0] * 32):
                self.mem.put(SM.IN_BUF + 4 * k, bits(x))
                self.mem.put(SM.IN_BUF + 0x80 + 4 * k, bits(x))
            for tk, (l, r) in (trk or {}).items():
                for k in range(32):
                    self.mem.put(SM.TRK_BUF + SM.TRK_STRIDE * tk + 4 * k, bits(l[k]))
                    self.mem.put(SM.TRK_BUF + SM.TRK_STRIDE * tk + 0x80 + 4 * k, bits(r[k]))
            P.run_recorder(self.L, self.mem)
        p, _ = P.run_voice(self.L, None, t, mtype, mem=self.mem)
        self.steps += p.steps
        return [flt(self.mem.get(BUF + 4 * k)) for k in range(32)]


# -- the fast link (v0.16): what each end puts on the TDM slots ---------------------------------

def rx_units(offset: int, words, seq: int = 0) -> list[int]:
    """the ColdFire's 256 units for WORDS (<= 124) at word OFFSET into the pool"""
    words = list(words)
    assert len(words) <= SM.RX_WORDS
    u = [SM.RX_MAGIC, seq & 0xFFFF, offset & 0xFFFF, offset >> 16]
    for w in words + [0] * (SM.RX_WORDS - len(words)):
        u += [w & 0xFFFF, w >> 16]
    u += [len(words), 0, 0]
    u.append((SM.LINK_SEED + sum(u)) & 0xFFFF)
    assert len(u) == SM.RX_UNITS
    return u


def rx_page(units, high: bool = True) -> dict[int, int]:
    """the DSP's receive page as words {byte offset from slot 8 of frame 0: word}: unit i in
    frame i >> 3, slot 8 + (i & 7); HIGH: the 24 bits arrive left-justified (TAG << 24 |
    v << 8), else right-justified (TAG << 16 | v)"""
    out = {}
    for i, v in enumerate(units):
        w = (SM.TDM_TAG << 24 | v << 8) if high else (SM.TDM_TAG << 16 | v)
        out[64 * (i >> 3) + 4 * (i & 7)] = w
    return out


def tx_decode(word_at) -> list[int] | None:
    """the DSP's packet from its transmit page (WORD_AT(byte offset from slot 14 of frame
    0) -> word), checked: [offset, seq, words...] or None"""
    u = []
    for i in range(SM.TX_UNITS):
        w = word_at(64 * (i >> 1) + 4 * (i & 1))
        if w >> 24 != SM.TDM_TAG:
            return None
        u.append((w >> 8) & 0xFFFF)
    if u[0] != SM.TX_MAGIC or u[63] != (SM.LINK_SEED + sum(u[:63])) & 0xFFFF:
        return None
    n = u[62]
    return [u[2] | u[3] << 16, u[1]] + [u[4 + 2 * k] | u[5 + 2 * k] << 16 for k in range(n)]
