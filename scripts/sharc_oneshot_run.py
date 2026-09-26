"""Run the DT2 ONESHOT render in digikit's SHARC runner: on the DT2 image (the
control) and, transplanted, inside the DN2 image. Helpers for
`scripts/sharc_oneshot_port.py`; no steps or verdicts here.

digikit is a tool (GPL-2.0+), imported from a checkout the caller names
(`sharc_waverider_render.Digikit`); nothing of it is copied.

The render is called the way its donor caller calls it (DT2 `0x1c6afd`):
R4 = the voice record, R8 = the output (32 floats), R12 = the block size (32),
with the I6/I7 frame. Each block is a fresh call on the previous block's state,
so the record's phase, flags and decimator state carry from block to block.
"""

from __future__ import annotations

import hashlib
import pathlib
import struct
import time

import sharc_dn2_fixups as fx

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "oneshot"

STACK = 0x300000
BLOCK = 32
DT2_INIT = 0x1C15E3                   # the DT2 engine init (digikit's finding 06: no arguments)
DT2_RECORD = 0x2412CC                 # DT2 voice record 0 (32 x 0x1d8 from here)
DT2_POOL = 0x19000000                 # the DT2 sample pool (its 400 MiB RAM pool)
DT2_OUT = 0x2F0000                    # a scratch output buffer (the stream loads nothing here)
DT2_RENDER = 0x1C4ECF


def runner_for(dk, memory, start: int, regs=None):
    base = {"I6": STACK, "I7": STACK}
    base.update(regs or {})
    return dk.run.Runner(memory, start, regs=base, explicit_memory_model=True,
                         approx_recips=True, follow_loaded_calls=True, max_call_depth=64)


def poke_bytes(dk, state, address: int, data: bytes) -> None:
    """Write DATA at ADDRESS, whole words where it can, then the tail by halves."""
    n = len(data) // 4 * 4
    for k in range(0, n, 4):
        _poke(dk, state, address + k, struct.unpack_from("<I", data, k)[0], 4)
    for k in range(n, len(data), 2):
        _poke(dk, state, address + k, struct.unpack_from("<H", data + b"\0", k)[0], 2)


def poke_pcm(dk, state, address: int, pcm: list[int]) -> None:
    for i, v in enumerate(pcm):
        _poke(dk, state, address + 2 * i, v & 0xFFFF, 2)


def _poke(dk, state, address: int, value: int, width: int) -> None:
    if not dk.st._dm_write(state, address, width, dk.st.Const(value)):
        raise SystemExit(f"a write to {address:#x} did not take effect")


def peek_bytes(dk, state, address: int, n: int) -> bytes:
    out = bytearray()
    for k in range(0, n, 4):
        v = dk.st._dm_read(state, address + k, 4)
        out += struct.pack("<I", v.value & 0xFFFFFFFF if isinstance(v, dk.st.Const) else 0)
    return bytes(out[:n])


def floats(dk, state, address: int, n: int = BLOCK) -> list[float]:
    raw = peek_bytes(dk, state, address, 4 * n)
    return list(struct.unpack(f"<{n}f", raw))


def float_bits(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


class Render:
    """N blocks of one voice: the render called on a carried state."""

    def __init__(self, dk, base_runner, entry: int, record: int, out: int, fixups=None):
        self.dk, self.runner, self.entry = dk, base_runner, entry
        self.record, self.out, self.fixups = record, out, fixups
        self.blocks, self.records, self.instructions, self.halts = [], [], [], []
        self.wall = 0.0

    def step(self) -> bool:
        r = self.runner.fresh_call(self.entry, regs={"R4": self.record, "R8": self.out,
                                                      "R12": BLOCK, "I6": STACK, "I7": STACK})
        t0 = time.perf_counter()
        if self.fixups is None:
            res = r.run(max_steps=40_000)
            ok = res.halt.reason == "return without followed call"
            n, why = res.instructions, f"{res.halt.reason} at {res.halt.pc_sw:#x}"
        else:
            kind, h, n = fx.run(r, 40_000, self.fixups)
            ok = kind == "halt" and h.reason == "return without followed call"
            why = f"{h.reason} at {h.pc_sw:#x}" if kind == "halt" else kind
        self.wall += time.perf_counter() - t0
        self.halts.append(why)
        if not ok:
            return False
        self.runner = r
        self.blocks.append(floats(self.dk, r.state, self.out))
        self.records.append(peek_bytes(self.dk, r.state, self.record, 0x1D8))
        self.instructions.append(n)
        return True

    def run(self, blocks: int) -> bool:
        for _ in range(blocks):
            if not self.step():
                return False
        return True

    @property
    def samples(self) -> list[float]:
        return [x for b in self.blocks for x in b]


# -- the donor: the DT2 image, as the control ---------------------------------------------------

class Donor:
    """The user's DT2 1.16 section 7 in the runner, from its own engine init."""

    def __init__(self, dk, section7: bytes, cache: bool = True):
        self.dk = dk
        self.section7 = section7
        self.sha = hashlib.sha256(section7).hexdigest()
        self.memory = dk.ldr.LoadedMemory.from_stream(section7)
        self.init, self.init_info = self._init(cache)

    def _init(self, cache: bool):
        OUT.mkdir(parents=True, exist_ok=True)
        snap = OUT / f"dt2_init_{self.sha[:12]}.snap"
        if cache and snap.exists():
            r = self.dk.run.load_snapshot(str(snap), self.memory)
            return r, {"reused": snap.name}
        r = runner_for(self.dk, self.memory, DT2_INIT)
        t0 = time.perf_counter()
        res = r.run(max_steps=3_000_000)
        if res.halt.reason != "return without followed call":
            raise SystemExit(f"DT2 init did not return: {res.halt.reason} at {res.halt.pc_sw:#x}")
        info = {"instructions": res.instructions, "wall_s": round(time.perf_counter() - t0, 1)}
        if cache:
            self.dk.run.save_snapshot(r, str(snap))
            info["saved"] = snap.name
        return r, info

    def render(self, record: bytes, pcm: list[int], pool: int | None = DT2_POOL) -> Render:
        """A render of RECORD (its word 0 re-pointed at POOL, where PCM is placed).
        `pool=None` keeps the record's own pointer -- a null-pointer record then
        exercises the render's "no sample assigned" silence gate."""
        base = self.init.fresh_call(DT2_RENDER)
        rec = record if pool is None else struct.pack("<I", pool) + record[4:]
        if pool is not None:
            poke_pcm(self.dk, base.state, pool, pcm)
        poke_bytes(self.dk, base.state, DT2_RECORD, rec)
        return Render(self.dk, base, DT2_RENDER, DT2_RECORD, DT2_OUT)


# -- the recipient: the DN2 image with the transplant spliced in --------------------------------

DN2_RECORD = 0x296000                 # our 16 DT2-shaped records, 0x1d8 apart (a fill block)
DN2_OUT = 0x288000                    # a scratch output (Milestone 1's reader output span)
DN2_POOL = 0x298100                   # direct-call runs: where the sample is poked


class Recipient:
    """DN2 1.11 section 7 plus the plan's relocated spans (and any EXTRA blocks)."""

    def __init__(self, dk, section7: bytes, plan, extra: bytes = b""):
        from dnfw.image import bootstream  # noqa: PLC0415
        self.dk, self.plan = dk, plan
        blocks = b"".join(bootstream.block(at, payload) for at, payload in plan.blocks())
        self.stream = bootstream.insert_before_final(section7, blocks + extra)
        self.memory = dk.ldr.LoadedMemory.from_stream(self.stream)
        self.sha = hashlib.sha256(self.stream).hexdigest()
        self.entry = plan.spec.span(plan.spec.entry).recipient

    def render(self, record: bytes, pcm: list[int], pool: int | None = DN2_POOL,
               record_at: int = DN2_RECORD, fixups=None) -> Render:
        """The transplanted render called directly, on a bare DN2 state. `pool` is
        the sample pool the record's word 0 points at (`None` keeps the record's
        own pointer -- pass a null-pointer record to exercise the silence gate)."""
        base = runner_for(self.dk, self.memory, self.entry)
        rec = record if pool is None else struct.pack("<I", pool) + record[4:]
        if pool is not None:
            poke_pcm(self.dk, base.state, pool, pcm)
        poke_bytes(self.dk, base.state, record_at, rec)
        return Render(self.dk, base, self.entry, record_at, DN2_OUT, fixups=fixups)
