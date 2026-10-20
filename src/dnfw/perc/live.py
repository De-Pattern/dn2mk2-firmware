"""PERC as the DSP runs it, in Python: dnfw.perc.program run on a memory of our own, for the
tests, the audition WAVs and the comparison with the owner's C (docs/perc.md).

`Harness` lays out what the DSP's memory would hold for one slot -- the tables, the frame
words, the note, the trigger, the slot's buffer -- and runs `program.voice` on it block by
block. The SHARC runner does the same on the DSP's own memory (scripts/sharc_waverider_m5.py).
"""

from __future__ import annotations

import struct

from . import machines as M
from . import program as P
from .dsl import Mem, bits, f32, flt

BUF = 0x00300000                          # where this harness puts the slot's buffer


def layout(state=None, scratch=None, tables=None, sin=None) -> M.Layout:
    """Where the build puts PERC (dnfw.waverider.dsp), unless told otherwise."""
    from ..waverider import dsp
    state = dsp.PERC_STATE_DM if state is None else state
    scratch = dsp.PERC_SCRATCH_DM if scratch is None else scratch
    tables = dsp.PERC_TABLES_DDR if tables is None else tables
    if sin is None:
        from ..shft import live as SL
        _, at = SL.tables_bytes()
        sin = dsp.SHFT_TABLES_DDR + at["sin"]
    return M.Layout(state=state, scratch=scratch, tables=tables, sin=sin)


def table_words(L: M.Layout) -> dict[int, int]:
    """Every table the program reads, word by word (PERC's own and SHFT's sine)."""
    from ..shft import live as SL
    from ..waverider import dsp
    out = {}
    data, _ = M.tables_bytes()
    for k in range(len(data) // 4):
        out[L.tables + 4 * k] = struct.unpack_from("<I", data, 4 * k)[0]
    sdata, sat = SL.tables_bytes()
    base = L.sin - sat["sin"]
    for k in range(len(sdata) // 4):
        out[base + 4 * k] = struct.unpack_from("<I", sdata, 4 * k)[0]
    return out


def word_of(value: float, top: int, low: int) -> int:
    """A 0..1 control as the frame word its record holds."""
    return (min(top, max(0, round(value * top))) + low) << 8


class Harness:
    def __init__(self, t: int = 0, L: M.Layout | None = None):
        self.t, self.L = t, L or layout()
        self.words = table_words(self.L)
        self.mem = Mem(lambda a: self.words.get(a, 0))
        self.steps = 0

    def set_controls(self, mtype: int, params) -> None:
        """mtype 0..N-1; params: eight 0..1 values."""
        t = self.t
        knob = (mtype * 128 + 127) // M.N            # a knob value that lands on mtype
        while (knob * M.N) >> 7 != mtype:
            knob -= 1
        self._half(M.frame_offset(M.TYPE_REC[1]), knob << 8)
        for (_rid, slot, lo, top), x in zip(M.PARAMS, params):
            self._half(M.frame_offset(slot), word_of(x, top, lo))

    def _half(self, off: int, value: int) -> None:
        a = M.FRAME + off + 146 * self.t
        w = self.mem.get(a & ~3)
        if a & 2:
            w = (w & 0xFFFF) | ((value & 0xFFFF) << 16)
        else:
            w = (w & 0xFFFF0000) | (value & 0xFFFF)
        self.mem.put(a & ~3, w)

    def block(self, note: float = 60.0, trig: bool = False, inp=None) -> list[float]:
        t = self.t
        self.mem.put(P.NOTE_CELLS + 4 * t, bits(note))
        self.mem.put(P.TRIG_WORD, (1 << (16 + t)) if trig else 0)
        self.mem.put(P.BUFFERS + 4 * t, BUF)
        for k in range(32):
            self.mem.put(BUF + 4 * k, bits(0.0))
        p, _ = P.run_voice(self.L, None, t, mem=self.mem)
        self.steps += p.steps
        return [flt(self.mem.get(BUF + 4 * k)) for k in range(32)]

    def render(self, mtype: int, params, seconds: float, note: float = 60.0,
               hits=(0.0,)) -> list[float]:
        self.set_controls(mtype, params)
        n = int(seconds * M.RATE) // 32
        at = {int(h * M.RATE) // 32 for h in hits}
        out = []
        for b in range(n):
            out += self.block(note, b in at)
        return out


def defaults(name: str) -> list[float]:
    """The owner's defaults for a machine (rv_params.c perc_pi), as 0..1."""
    return [x / 127.0 for x in DEFAULTS[name]]


DEFAULTS = {
    "TRX-BD": (40, 64, 64, 40, 50, 10, 0, 20), "TRX-B2": (40, 60, 50, 30, 60, 10, 0, 20),
    "TRX-SD": (50, 50, 40, 40, 80, 64, 40, 10), "TRX-XT": (50, 64, 40, 50, 0, 0, 40, 0),
    "TRX-CP": (64, 64, 64, 40, 50, 40, 60, 64), "TRX-RS": (64, 40, 0, 0, 0, 0, 0, 0),
    "TRX-CB": (64, 60, 64, 20, 64, 20, 0, 0), "TRX-CH": (64, 30, 70, 110, 64, 0, 0, 0),
    "TRX-OH": (64, 80, 70, 110, 64, 0, 0, 0), "TRX-CY": (64, 90, 64, 64, 64, 30, 0, 0),
    "TRX-MA": (10, 30, 0, 0, 40, 64, 80, 64), "TRX-CL": (64, 40, 0, 40, 64, 40, 0, 0),
    "TRX-XC": (60, 50, 30, 40, 0, 0, 40, 0),
    "EFM-BD": (40, 64, 64, 40, 40, 40, 30, 0), "EFM-SD": (60, 50, 80, 50, 50, 60, 40, 20),
    "EFM-XT": (50, 64, 40, 50, 40, 50, 40, 30), "EFM-CP": (70, 50, 64, 40, 100, 90, 60, 40),
    "EFM-RS": (80, 30, 40, 20, 40, 70, 30, 60), "EFM-CB": (70, 60, 40, 20, 50, 70, 60, 0),
    "EFM-HH": (90, 30, 0, 64, 110, 100, 90, 70), "EFM-CY": (80, 90, 80, 40, 110, 95, 100, 0),
    "GND-SN": (64, 64, 0, 40, 0, 0, 0, 0), "GND-NS": (50, 0, 0, 0, 0, 0, 0, 0),
    "GND-IM": (20, 127, 20, 127, 0, 0, 0, 0),
}
