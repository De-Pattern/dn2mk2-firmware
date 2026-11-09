"""FASCIA's DSP program beside live.py: the run mode (dnfw.fascia.program) on a memory that holds
what the DSP would (the frame's words, the note cell, the trig, the tables), block for block,
against live.Voice on the same panel, note and velocity (test_fascia_program, the runner's
`fascia` part, scripts/fascia_dsp_compare.py).

The DSP's inputs are the frame's words, so the panel live.py gets is what the DSP reads from
them: a choice's knob after the record's 0..100 or 0..120 (machines.knob(word_of(k))), the
velocity as the frame carries it (7 bits << 8) over 127 (live.u).
"""

from __future__ import annotations

import struct

import numpy as np

from ..perc.dsl import Mem, f32, bits, flt
from . import live as LV
from . import machines as FM
from . import model as MD
from . import program as P

TRIG = P.TRIG_WORD
BUF0 = 0x00300000                        # the runner-free fake buffers: 16 x 32 floats
VOICE_SLOT = 0


def panel_words(panel: dict) -> dict[str, int]:
    """the panel (0..127 knobs, defaults filled) as the frame words the DSP reads"""
    full = {**FM.DEFAULTS, **{k: int(v) for k, v in panel.items() if k in FM.DEFAULTS}}
    return {c: FM.word_of(c, min(max(full[c], 0), 127)) for c in FM.CONTROLS}


def panel_seen(panel: dict) -> dict[str, int]:
    """what the DSP's knobs are for that panel (machines.knob of the words)"""
    return {c: FM.knob(c, w) for c, w in panel_words(panel).items()}


def vel_word(vel: float) -> int:
    return int(round(min(max(vel, 0.0), 1.0) * 127)) << 8


def note_word(note: float) -> int:
    """the frame's note word (header 2 + 2t), as the ColdFire sends it: note << 8 | fine"""
    return int(round(float(note) * 256)) & 0xFFFF


def note_seen(note: float) -> float:
    """the note the program reads (the word / 256): what live.Voice.note_on is given"""
    return note_word(note) / 256.0


def vel_seen(vel: float) -> np.float32:
    return LV.u(vel_word(vel) >> 8)


class Frame:
    """a block's frame image (the words the program reads), as a word dictionary"""

    def __init__(self):
        self.w: dict[int, int] = {}

    def half(self, off: int, v: int) -> None:
        a = P.FRAME + off
        word = a & ~3
        cur = self.w.get(word, 0)
        if a & 2:
            cur = (cur & 0xFFFF) | ((v & 0xFFFF) << 16)
        else:
            cur = (cur & 0xFFFF0000) | (v & 0xFFFF)
        self.w[word] = cur

    def slot(self, t: int, panel_w: dict[str, int], vel: float, note: float, trig: bool, mtype: int = FM.TYPE):
        for c, word in panel_w.items():
            self.half(168 + 2 * FM.SLOTS[c][1] + 146 * t, word)
        self.half(P.VEL_OFFSET + 2 * t, vel_word(vel))
        self.half(148 + 2 * t, mtype)
        self.half(P.NOTE_OFFSET + 2 * t, note_word(note))
        tw = self.w.get(TRIG, 0)
        if trig:
            tw |= 1 << (16 + t)
        self.w[TRIG] = tw


def table_mem(L: P.Layout) -> dict[int, int]:
    out = {}
    data = P.tables_bytes()
    for k in range(len(data) // 4):
        out[L.tables + 4 * k] = struct.unpack_from("<I", data, 4 * k)[0]
    for k, x in enumerate(LV.SIN_T):
        out[L.sin + 4 * k] = bits(float(x))
    return out


class Dsp:
    """the run mode's voices on one memory, block by block"""

    def __init__(self, L: P.Layout | None = None, fill=None):
        self.L = L or P.layout()
        base = table_mem(self.L)
        for t in range(16):
            base[P.BUFFERS + 4 * t] = BUF0 + 128 * t
        self.base = base
        self.fill = fill                          # garbage: a function addr -> word for unwritten state
        self.mem = Mem(self._read)
        self.steps = 0

    def _read(self, a: int) -> int:
        if a in self.frame:
            return self.frame[a]
        if a in self.base:
            return self.base[a]
        if self.fill is not None:
            return self.fill(a)
        return 0

    def block(self, frame: Frame, slots) -> dict[int, np.ndarray]:
        """run the model for SLOTS (in that order) on FRAME; -> slot -> its 32 samples"""
        self.frame = frame.w
        for a in list(frame.w):                  # this block's frame overrides what was written
            self.mem.w.pop(a, None)
        out = {}
        for t in slots:
            p, _ = P.run_voice(self.L, self._read, t, self.mem)
            self.steps = p.steps
            buf = BUF0 + 128 * t
            out[t] = np.array([flt(self.mem.get(buf + 4 * k)) for k in range(P.BLOCK)], np.float32)
        return out


def events_blocks(events, seconds: float):
    """events (start s, note, vel[, overrides]) -> {block: [(note, vel, over)]} on block starts"""
    out = {}
    for ev in events:
        t0, note, vel = ev[:3]
        over = ev[3] if len(ev) > 3 else {}
        out.setdefault(int(t0 * LV.RATE) // LV.BLOCK, []).append((note, vel, over))
    return out


def compare_voice(panel: dict, events, blocks: int, slot: int = 0, controls=None, dsp: Dsp | None = None):
    """one slot playing EVENTS (each a note on that slot) for BLOCKS blocks, the DSP model and
    live.Voice(seed=slot+1) side by side. CONTROLS: block -> panel (p-locks, LFOs), else PANEL.
    -> (dsp output, live output, first mismatching block or None)"""
    dsp = dsp or Dsp()
    v = LV.Voice(seed=slot + 1)
    evb = events_blocks(events, blocks * LV.BLOCK / LV.RATE)
    a, b = [], []
    first = None
    for k in range(blocks):
        pk = controls(k) if controls else panel
        trig = k in evb
        note, vel = (evb[k][-1][0], evb[k][-1][1]) if trig else (60.0, 1.0)
        f = Frame()
        f.slot(slot, panel_words(pk), vel, note, trig)
        got = dsp.block(f, [slot])[slot]
        if trig:
            v.note_on(note_seen(note), vel_seen(vel))
        want = v.block(panel_seen(pk))
        a.append(got)
        b.append(want)
        if first is None and not np.array_equal(got.view(np.uint32), want.view(np.uint32)):
            first = k
    return np.concatenate(a), np.concatenate(b), first
