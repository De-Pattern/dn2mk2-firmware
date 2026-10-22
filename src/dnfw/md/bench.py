"""Running a Machinedrum machine's DSL in run mode against the Machinedrum's own output
(test/test_md.py, scripts/md_compare.py).

The reference is the golden vectors: DSP2's own code for each machine run in a DSP56300
emulator on the owner's firmware (`MD_GOLDEN`, default ../md163/research/emu56k/golden
beside the repo; Elektron's output, so never in this repository). A case is a list of
events (block, eight 14-bit inputs, trigger), the host's words the OS sent at each, and
the 44.1 kHz output, 24-bit, every block.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import struct

from . import core as K
from . import rom
from ..perc.dsl import Mem, Prog, bits

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = pathlib.Path(os.environ.get("MD_GOLDEN", str(ROOT.parent / "md163" / "research" / "emu56k" / "golden")))
STATE = 0x82100000                     # where the build puts slot 0 (dnfw.waverider.dsp.MD_STATE_DDR)
SCRATCH = 0x2DF000
TABLES = 0x82000000                    # dnfw.waverider.dsp.MD_TABLES_DDR


def layout() -> K.Layout:
    return K.Layout(STATE, SCRATCH, TABLES)


def golden_available() -> bool:
    return GOLDEN.is_dir() and rom.available()


def golden(name: str) -> dict:
    return json.loads((GOLDEN / f"{name.replace('-', '')}.json").read_text())


def unpack(s: str) -> list[float]:
    raw = base64.b64decode(s)
    return [x * K.Q23 for x in struct.unpack(f"<{len(raw) // 4}i", raw)]


_TABLE_MEM: dict[int, dict[int, int]] = {}


def table_mem(L: K.Layout) -> dict[int, int]:
    """The tables as the DSP holds them: the ROM's from the firmware, and the sine as the
    DSP's own fill computes it (run once here, through the DSL)."""
    if L.tables not in _TABLE_MEM:
        m: dict[int, int] = {}
        data = K.tables_bytes()
        base = L.T["hostP"]
        for k in range(0, len(data), 4):
            m[base + k] = struct.unpack_from("<I", data, k)[0]
        mem = Mem(lambda a: m.get(a, 0))
        p = Prog("run", mem=mem)
        for _ in range(K.SINE_N // K.SINE_PER_BLOCK):
            K.sine_fill(p, L)
        m.update({a: v for a, v in mem.w.items() if L.T["sine"] <= a < L.T["sine"] + 4 * K.SINE_N})
        _TABLE_MEM[L.tables] = m
    return _TABLE_MEM[L.tables]


class Bench:
    """One slot running machine M in run mode, block by block, at 44.1 kHz."""

    def __init__(self, M):
        self.M, self.L = M, layout()
        tm = table_mem(self.L)
        self.mem = Mem(lambda a: tm.get(a, 0))
        self.first = True

    def _prog(self) -> Prog:
        p = Prog("run", mem=self.mem)
        p.i[3] = self.L.state
        self.mem.put(self.L.C["mdb"], self.L.state)
        return p

    def block(self, inputs=None, trig=False) -> list[float]:
        p = self._prog()
        if inputs is not None:
            for k, x in enumerate(inputs):
                p.iconst(0, x)
                p.sti(K.INP0 + k, 3, 0)
            p.iconst(0, 1 if trig else 0)
            K.vws(p, "trg", 0)
            self.M.host(p, self.L)
        if self.first:
            self.M.init(p, self.L)
            self.first = False
        if trig:
            self.M.trig(p, self.L)
        self.M.render(p, self.L)
        self.steps = p.steps
        return [struct.unpack("<f", struct.pack("<I", self.mem.get(self.L.state + 4 * (K.OUT0 + k))))[0]
                for k in range(32)]


def run_case(M, case: dict) -> tuple[list[float], list[float]]:
    """-> (ours, the Machinedrum's), every sample of the case."""
    ev = {b: (inputs, trig) for b, inputs, trig in case["events"]}
    b = Bench(M)
    ours = []
    for k in range(case["nblocks"]):
        if k in ev:
            ours += b.block(ev[k][0], ev[k][1])
        else:
            ours += b.block()
    return ours, unpack(case["out"])


def compare(ours: list[float], theirs: list[float]) -> dict:
    """The error against the Machinedrum: its peak, its RMS, and the signal-to-error ratio
    (dB) over the case."""
    import math
    err = [a - b for a, b in zip(ours, theirs)]
    pe = max((abs(e) for e in err), default=0.0)
    sig = math.sqrt(sum(x * x for x in theirs) / max(1, len(theirs)))
    rms = math.sqrt(sum(e * e for e in err) / max(1, len(err)))
    snr = 200.0 if rms == 0 else (20 * math.log10(sig / rms) if sig > 0 else -200.0)
    return {"peak_err": pe, "rms_err": rms, "signal_rms": sig, "snr_db": snr}
