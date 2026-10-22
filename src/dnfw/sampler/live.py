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
                    exp2=PL.layout().T["exp2"])


def pool_bytes(samples, base: int, rates=None, fmts=None, names=None) -> bytes:
    """the directory and the frames of SAMPLES (lists of floats), as the DSP's DDR holds
    them from BASE: magic, count, POOL_SLOTS entries (address, frames, rate, format),
    the names (dnfw.sampler.machines.NAME_BYTES each, for the ColdFire's pages; the DSP
    ignores them), then each sample's frames -- float32 (format 0) or int16 (format 1)
    -- on a 64-byte (cache line) boundary"""
    rates = rates or [1.0] * len(samples)
    fmts = fmts or [0] * len(samples)
    names = names or [""] * len(samples)
    head = SM.DATA_OFFSET
    entries, data = [], bytearray()
    for s, r, f in zip(samples, rates, fmts):
        entries.append(struct.pack("<IIfI", base + head + len(data), len(s), r, f))
        if f == 1:
            data += struct.pack(f"<{len(s)}h", *(max(-32768, min(32767, round(x * 32768))) for x in s))
        else:
            data += struct.pack(f"<{len(s)}f", *s)
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
    def __init__(self, t: int = 0, samples=None, rates=None, fmts=None):
        self.t, self.L = t, layout()
        self.samples = samples if samples is not None else test_samples()
        data = pool_bytes(self.samples, self.L.pool,
                          rates if rates is not None else test_rates(),
                          fmts if fmts is not None else test_fmts(), TEST_NAMES)
        self.words = {self.L.pool + 4 * k: struct.unpack_from("<I", data, 4 * k)[0]
                      for k in range(len(data) // 4)}
        from ..perc import live as PL
        self.words.update(PL.table_words(PL.layout()))
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

    def block(self, mtype: int, note: float = 60.0, trig: bool = False) -> list[float]:
        t = self.t
        self.mem.put(PP.NOTE_CELLS + 4 * t, bits(note))
        self.mem.put(PP.TRIG_WORD, (1 << (16 + t)) if trig else 0)
        self.mem.put(PP.BUFFERS + 4 * t, BUF)
        for k in range(32):
            self.mem.put(BUF + 4 * k, bits(0.0))
        p, _ = P.run_voice(self.L, None, t, mtype, mem=self.mem)
        self.steps += p.steps
        return [flt(self.mem.get(BUF + 4 * k)) for k in range(32)]
