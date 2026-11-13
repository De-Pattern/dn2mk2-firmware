"""Stereo study (docs/stereo-assessment.md): where in the per-track chain (sw 0x1c8ef1) the
mono track buffer becomes the per-track stereo buffer 0x257ee8 + 0x100 t.

    python scripts/sharc_stereo_probe.py [--blocks N]

On M4's voice run (type 5, init sound, one trigger), on the traced block: every call out of
0x1c8ef1's body that changes track 0's mono buffer (ChainTracer), and every instruction
that changes a word of track 0's stereo buffer (L 32 at +0, R 32 at +0x80), by pc, with
the call it sits in. Nothing is patched; this only reads.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import sharc_waverider_m4 as m4          # noqa: E402

STEREO = 0x257EE8
WATCH = (0x257EE8, 0x258F68, 0x259F68)     # per-track stereo; routing A (post-chain); B (raw panned)
SENDS = (0x25AF68, 0x25B268, 0x25B568)     # the FX sends 0x1c1738 writes (docs/link-research.md)
CHAIN = 0x1C8EF1


class StereoTracer(m4.ChainTracer):
    def __init__(self):
        super().__init__()
        self.writes = collections.OrderedDict()   # pc -> [count, first call index, words]
        self.snap = None

    n_all = 0
    n_chain = 0

    def pre(self, runner, insn):
        if self.active:
            self.n_all += 1
            pc = runner.state.pc_sw
            if self.BODY[0] <= pc < self.BODY[1] or self.open is not None:
                self.n_chain += 1               # the chain's body and the calls it makes
            st = runner.state
            now = [m4.m2.word(st, base + 4 * k) for base in WATCH for k in (0, 5, 32, 37)]
            if self.snap is not None and now != self.snap and self.last_pc is not None:
                which = tuple(i // 4 for i, (x, y) in enumerate(zip(now, self.snap)) if x != y)
                e = self.writes.setdefault((self.last_pc, which), [0, len(self.calls), self.open and self.open["target"]])
                e[0] += 1
            self.snap = now
            self.last_pc = runner.state.pc_sw
        return super().pre(runner, insn)

    last_pc = None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--blocks", type=int, default=4)
    p.add_argument("--level", type=lambda x: int(x, 0), default=None, help="frame header LEVEL for track 0")
    p.add_argument("--slot", action="append", default=[], help="IDX=VALUE on track 0's slots (e.g. 86=0x7f00)")
    p.add_argument("--zero-level", action="store_true", help="record +0x22c = 0 at the chain's entry (MUTE SRC's idea)")
    a = p.parse_args()
    dk = m4.m1.Digikit(pathlib.Path(m4.os.environ.get("DNFW_DIGIKIT_SHARC",
                                                      m4.ROOT.parent / "digikit-wt-sharcemu")))
    m4.fx.bind(str(dk.path / "tools") if hasattr(dk, "path") else str(m4.ROOT.parent / "digikit-wt-sharcemu" / "tools"))
    stream = m4.m1.dn2_section7(m4.IMAGE)
    m4.SOUND, _machines = m4.init_sound(m4.IMAGE)
    m4.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=m4.OUT) as tmp:
        work = pathlib.Path(tmp)
        reader, _, _ = m4.m1.reader_code(False, work)
        m5, _, _ = m4.m3.load_json(m4.m3.MACHINE5, m4.m3.MACHINE5_SRC, False, work)
        m5d, _, _ = m4.load_code(m4.MACHINE5D, m4.MACHINE5D_SRC, False, work, m4.MACHINE5D_SW)
        mach = m4.M4Machine(dk, stream, reader, m5, m5d, work)
        init = m4.load_init(dk, mach, stream, reader)
        positions = m4.render.sweep(len(m4.testtable.table()), max(a.blocks, 2))
        prep = m4.voice_prep(a.freq if hasattr(a, "freq") else 375.0, positions)
        tr = StereoTracer()
        ov = {int(k): int(v, 0) for k, v in (x.split("=") for x in a.slot)}

        def frame(b):
            f = bytearray(m4.make_frame(m4.SOUND, 5, trig=(b == 1), overrides=ov))
            if a.level is not None:
                off = m4.FR.header_offset(m4.FR.LEVEL, 0)
                f[off:off + 2] = a.level.to_bytes(2, "little")
            return bytes(f)
        if a.zero_level:
            zero = lambda r: m4.m2.poke(r.state, m4.V.track_record(0) + 0x22C, 0)   # noqa: E731
            tr.hooks[CHAIN] = zero
            base_fix = m4.fixups
            m4.fixups = lambda hooks=None: base_fix({**(hooks or {}), CHAIN: zero})
        on = m4.run_blocks(init, a.blocks, frame, type5=prep, tracer=tr, trace_block=a.blocks - 1)
        print("ok", on["ok"], on.get("halt"))
        print(f"cost: traced block {tr.n_all:,} instructions; track 0's chain (body and its calls) "
              f"{tr.n_chain:,} ({100 * tr.n_chain / max(tr.n_all, 1):.1f}%)")
        print("calls out of 0x1c8ef1 that touch track 0's mono buffer:")
        for i, c in enumerate(tr.calls):
            print(f"  {i:2d} {c['from']} -> {c['target']}  R4 {c['R4']}  peak {c['peak_in']:.4f} -> {c['peak_out']:.4f}")
        print("writers of track 0's stereo buffer (pc: changes, after call #, inside call to):")
        for (pc, which), (n, ci, tgt) in tr.writes.items():
            print(f"  {pc:#x} buf {[hex(WATCH[w]) for w in sorted(set(which))]}: {n}  after #{ci}  in {tgt}")
        st = on["state"].state
        def peak(base, n=64):
            return max(abs(m4.V.bits_f32(m4.m2.word(st, base + 4 * k) or 0) or 0) for k in range(n))
        print("  record +0x22c:", hex(m4.m2.word(st, m4.V.track_record(0) + 0x22C) or 0))
        for base in WATCH + SENDS:
            print(f"  peak {base:#x}: {peak(base):.5f}")
        for base in WATCH:
            print(f"  {base:#x} L {[round(m4.V.bits_f32(m4.m2.word(st, base + 4*k) or 0), 4) for k in range(0, 32, 8)]}"
                  f" R {[round(m4.V.bits_f32(m4.m2.word(st, base + 0x80 + 4*k) or 0), 4) for k in range(0, 32, 8)]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
