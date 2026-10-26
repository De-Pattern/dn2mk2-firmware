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
    from ..sampler import machines as SM
    from ..md import core as MDC
    state = dsp.PERC_STATE_DM if state is None else state
    scratch = dsp.PERC_SCRATCH_DM if scratch is None else scratch
    tables = dsp.PERC_TABLES_DDR if tables is None else tables
    if sin is None:
        from ..shft import live as SL
        _, at = SL.tables_bytes()
        sin = dsp.SHFT_TABLES_DDR + at["sin"]
    return M.Layout(state=state, scratch=scratch, tables=tables, sin=sin,
                    md_state=dsp.MD_STATE_DDR, md_tables=dsp.MD_TABLES_DDR,
                    mnm_scratch=dsp.MNM_SCRATCH_DDR,
                    mnm_tables=dsp.MD_TABLES_DDR + MDC.TABLE_LAYOUT["mnm"][0],
                    md_shipped=dsp.SMP_POOL_DDR + SM.TABLE_AREA,
                    md_ready=dsp.SMP_POOL_DDR + SM.TABLE_READY)


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
    from ..md import bench as MDB                 # the Machinedrum's tables, the sine filled (v0.17)
    out.update(MDB.table_mem(L.md))
    return out


def word_of(value: float, top: int, low: int) -> int:
    """A 0..1 control as the frame word its record holds."""
    return (min(top, max(0, round(value * top))) + low) << 8


def knob_word(knob: int, top: int, low: int) -> int:
    """v0.26: a Monomachine knob (0..127) as the frame word of a PERC record spanning
    0..TOP: the value whose knob, as the DSP and the page read it (v / top x 127, rounded),
    is KNOB, or the nearest (TUN1/TUN2 span 0..120: some knobs have no value)."""
    v = min(range(top + 1), key=lambda v: (abs(int(v / top * 127 + 0.5) - knob), v))
    return (v + low) << 8


class Harness:
    def __init__(self, t: int = 0, L: M.Layout | None = None):
        self.t, self.L = t, L or layout()
        self.words = table_words(self.L)
        self.mem = Mem(lambda a: self.words.get(a, 0))
        self.steps = 0

    def set_controls(self, mtype: int, params, fx=None) -> None:
        """mtype 0..N-1; params: eight 0..1 values; fx: the seven track effects' (0..1,
        default FX_OFF: every effect off, as at the records' defaults)."""
        t = self.t
        from ..md import voice as MDV
        knob = (mtype * 128 + 127) // MDV.N          # a knob value that lands on mtype
        while (knob * MDV.N) >> 7 != mtype:
            knob -= 1
        self._half(M.frame_offset(M.TYPE_REC[1]), knob << 8)
        for (_rid, slot, lo, top), x in zip(M.PARAMS + M.FX_PARAMS, list(params) + list(fx or FX_OFF)):
            self._half(M.frame_offset(slot), word_of(x, top, lo))

    def set_mnm(self, mtype: int, knobs) -> None:
        """v0.26: the track on machine type MTYPE (a Monomachine machine's: the frame's type
        word at 148 + 2 t), its eight knobs 0..127 on PERC's eight records"""
        a = M.FRAME + 148 + 2 * self.t
        w = self.mem.get(a & ~3)
        w = (w & 0xFFFF) | (mtype << 16) if a & 2 else (w & 0xFFFF0000) | mtype
        self.mem.put(a & ~3, w)
        for (_rid, slot, lo, top), x in zip(M.PARAMS, knobs):
            self._half(M.frame_offset(slot), knob_word(x, top, lo))

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
        self.mem.put(self.L.C["mcost"], 0)          # v0.26: as the program sets it each block
        p, _ = P.run_voice(self.L, None, t, mem=self.mem)
        self.steps += p.steps
        return [flt(self.mem.get(BUF + 4 * k)) for k in range(32)]

    def render(self, mtype: int, params, seconds: float, note: float = 60.0,
               hits=(0.0,), fx=None) -> list[float]:
        self.set_controls(mtype, params, fx)
        n = int(seconds * M.RATE) // 32
        at = {int(h * M.RATE) // 32 for h in hits}
        out = []
        for b in range(n):
            out += self.block(note, b in at)
        return out


# AMD AMF EQF EQG FLTF FLTW FLTQ at the WaveTone records' defaults: every effect off
FX_OFF = (0.0, 0.5, 0.5, 0.5, 0.0, 1.0, 0.0)


def defaults(name: str) -> list[float]:
    """The Machinedrum's defaults for a machine (its machine table), as 0..1."""
    from ..md import machines as MD
    return [x / 127.0 for x in MD.DEFAULTS[name]]
