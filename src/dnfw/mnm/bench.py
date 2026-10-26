"""The Monomachine machines in run mode against the Monomachine's own output (its DSP code in
an emulator, golden vectors made outside the repository: `MNM_GOLDEN`, default
../mnm132/research/golden). A golden case: blocks of 16 frames; per block the increment A the
kernel handed the render (56-bit) and the 16 samples; events (block, eight knobs, note,
trigger)."""

from __future__ import annotations

import base64
import json
import math
import os
import pathlib
import struct

from . import core as C
from . import rom
from ..md import core as K
from ..perc.dsl import Mem, Prog, bits, flt

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = pathlib.Path(os.environ.get("MNM_GOLDEN", str(ROOT.parent / "mnm132" / "research" / "golden")))

STATE = 0x00100000                       # the bench's slot words
SCRATCH = 0x00200000
TABLES = 0x00400000
MD_SCRATCH = 0x00080000


def golden(name: str) -> dict:
    g = json.loads((GOLDEN / f"{name}.json").read_text())
    for c in g["cases"]:
        raw = base64.b64decode(c["out"])
        c["out"] = [rom.s24(v) * C.Q23 for v in struct.unpack(f"<{len(raw) // 4}I", raw)]
        c["A"] = [int(x, 16) for x in c["A"]]
    return g


PERC_TABLES = 0x00700000
PERC_SCRATCH = 0x00090000
MD_DELAY = 0x00900000                    # (STATE + 1 MB, the default, is SCRATCH here)


def layout() -> C.Layout:
    from ..perc import machines as PM
    perc = PM.Layout(state=0x000A0000, scratch=PERC_SCRATCH, tables=PERC_TABLES, sin=0,
                     md_state=STATE, md_tables=0x00600000, mnm_scratch=SCRATCH, mnm_tables=TABLES)
    perc.md.delay = MD_DELAY                     # the slots' delay areas (VO-6's pulse ring), apart
    return perc.md.mnm


_TM: dict[int, int] = {}


def table_mem(L: C.Layout) -> dict[int, int]:
    if not _TM:
        for k, v in enumerate(rom.table_words()):     # as table_fill stores them
            _TM[L.tables + 4 * k] = bits(v * C.Q23)
        from . import dpro
        _TM.update(dpro.bench_words(L))           # DPRO's stand-in, as the DSP builds it
        from ..perc import machines as PM
        data, _ = PM.tables_bytes()
        for k in range(0, len(data), 4):
            _TM[PERC_TABLES + k] = struct.unpack_from("<I", data, k)[0]
    return _TM


class Bench:
    def __init__(self, M):
        self.M, self.L = M, layout()
        tm = table_mem(self.L)
        self.mem = Mem(lambda a: tm.get(a, 0))
        self.first = True

    def _prog(self) -> Prog:
        p = Prog("run", mem=self.mem)
        p.i[3] = self.L.md.state
        self.mem.put(self.L.md.C["mdb"], self.L.md.state)
        return p

    def block(self, A: int, F: int, knobs=None, trig=False) -> list[float]:
        """one Monomachine block; the increments exactly the Monomachine's (`exact`)"""
        p = self._prog()
        if knobs is not None:
            self.knobs = knobs
            for k, x in enumerate(knobs):
                p.fconst(0, x / 128.0)
                p.sti(C.P0 + k, 3, 0)
        p.fconst(0, A / 2.0 ** 24)
        C.vws(p, "A", 0)
        for name, v in self.M.exact(A, F, self.knobs).items():
            p.iconst(0, v)
            C.vws(p, name, 0)
        if self.first:
            self.M.init(p, self.L)
            self.first = False
        if trig:
            self.M.trig(p, self.L)
        out = self.L.md.state + 4 * K.OUT0
        p.iconst(0, out)
        p.seti(4, 0)
        self.M.half(p, self.L)
        self.steps = p.steps
        return [flt(self.mem.get(out + 4 * k)) for k in range(16)]


def run_case(M, case: dict) -> tuple[list[float], list[float]]:
    ev = {e[0]: e for e in case["events"]}
    b = Bench(M)
    ours = []
    for k in range(case["nblocks"]):
        if k in ev:
            _, knobs, _note, trig = ev[k]
            ours += b.block(case["A"][k], case["F"][k], knobs, trig)
        else:
            ours += b.block(case["A"][k], case["F"][k])
    return ours, case["out"]


def compare(ours, theirs) -> dict:
    err = [a - b for a, b in zip(ours, theirs)]
    pe = max((abs(e) for e in err), default=0.0)
    sig = math.sqrt(sum(x * x for x in theirs) / max(1, len(theirs)))
    rms = math.sqrt(sum(e * e for e in err) / max(1, len(err)))
    snr = 200.0 if rms == 0 else (20 * math.log10(sig / rms) if sig > 0 else -200.0)
    return {"peak_err": pe, "rms_err": rms, "signal_rms": sig, "snr_db": snr}
