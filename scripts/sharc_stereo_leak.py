"""Stereo: what a stereo voice's wrappers leave for the voices after it (SHARC runner).

v0.76-t1 on both processors (2026-11-26, a per-voice diagnosis): with a stereo voice in slot 0,
every other voice's block left its sampler sounding and reached the amp silent (zero), a mono
voice's with NaN. The runner's other stereo checks sound only voice 0, so a voice after it was
never heard. Here: one ONESHOT note on track 0 (voice 0), mono and then marked stereo (slot 0,
DUP: R's block is L's as rendered, so every word must be stock's). At every stage call site, for
each voice AFTER the stereo one, every universal register as the body makes the call must be the
same in both runs; and each voice's block after the amp. A register the wrappers do not keep
(they keep R0..R15, I0, I1, I3, I4, ASTAT) and the body carries from voice to voice shows here.

    python3 scripts/sharc_stereo_leak.py [BLOCKS]"""

import struct
import sys
import tempfile
import pathlib

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
import sharc_waverider_m5 as G            # noqa: E402
import sharc_waverider_render as m1       # noqa: E402
import sharc_waverider_m4 as m4           # noqa: E402
import sharc_dn2_fixups as fx             # noqa: E402
from dnfw.waverider import dsp            # noqa: E402
from dnfw.sampler import machines as SM, stereo as ST   # noqa: E402

DK = pathlib.Path("../digikit-wt-sharcemu")
IMG = pathlib.Path("../Digitone_II_OS1.11.syx")
dk = m1.Digikit(DK)
fx.bind(str(DK / "tools"))
m4.IMAGE = IMG
stock = m1.dn2_section7(IMG)
sound, machines = m4.init_sound(IMG)
m5 = G.Image(dk, dsp.section7(stock))
snap, mach = G.snapshot_path(dk, stock, pathlib.Path(tempfile.mkdtemp()))
init = G.init_on(snap, mach, m5)
ONE = SM.TYPE_OF["ONESHOT"]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 4
NSLOT = int(sys.argv[2]) if len(sys.argv) > 2 else 1     # slots in use: voices 0..NSLOT-1
DUPV = int(sys.argv[3]) if len(sys.argv) > 3 else 1
V0 = NSLOT - 1
MEM_LO, MEM_HI = 0x240000, 0x260000
REGS = [n for n in fx.UREG_CODES if n[:1] in "RIMBL" and n[1:].isdigit()] + \
       [n for n in ("MODE1", "MODE2", "ASTATX", "ASTATY", "USTAT1", "USTAT2", "PX1", "PX2", "LCNTR", "CURLCNTR") if n in fx.UREG_CODES]


def run(stereo: bool):
    calls = []                                    # (block, stage, voice, {reg: value})
    mems = {}
    amps = {}
    blk = [0]

    def perc(r):
        blk[0] += 1
        if stereo:
            G.m2.poke(r.state, ST.ANY, NSLOT)
            for sl in range(NSLOT):
                for k, a in enumerate(ST.voice_laddr(sl)):
                    G.m2.poke(r.state, ST.laddr(sl, k), a)
                G.m2.poke(r.state, ST.VOICE + 4 * sl, sl)
                G.m2.poke(r.state, ST.DUP + 4 * sl, DUPV)

    def at_site(k):
        site, _t, base, stride = ST.STAGES[k]

        def h(r):
            v = (G.m2.word_reg(r, "R4") - base) // stride
            calls.append((blk[0], k, v, {n: G.m2.word_reg(r, n) for n in REGS}))
            if v == V0 + 1:                       # after the stereo voice's call of this stage
                mems[(blk[0], k)] = {a: G.m2.word(r.state, a) for a in range(MEM_LO, MEM_HI, 4)}
            if k == len(ST.STAGES) - 1 and v > 0:  # the amp: the voice before's block is its output
                pv = v - 1
                b = amps.get(("ptr", pv))
                if b:
                    amps[(blk[0], pv)] = [G.m2.word(r.state, b + 4 * i) for i in range(32)]
            if k == len(ST.STAGES) - 1:
                amps[("ptr", v)] = G.m2.word_reg(r, "R12")
        return h

    def fb(b):
        return G.base_frame(sound, machines, t0=ONE, overrides=G.smp_words({SM.TUNE_REC: 67}),
                            trigger=b == 1).to_bytes()
    hooks = {dsp.PERC_SW: perc}
    for k in range(len(ST.STAGES)):
        hooks[ST.STAGES[k][0]] = at_site(k)
    r = G.run_blocks(init, fb, N, extra_hooks=hooks)
    return r, calls, amps, mems


r0, c0, a0, m0 = run(False)
r1, c1, a1, m1 = run(True)
print("ok", r0["ok"], r1["ok"], "calls", len(c0), len(c1), flush=True)
fl = lambda w: struct.unpack("<f", struct.pack("<I", w or 0))[0]   # noqa: E731
seen = 0
for (b, k, v, regs), (b1, k1, v1, regs1) in zip(c0, c1):
    if (b, k, v) != (b1, k1, v1):
        print("the calls' order differs at", (b, k, v), (b1, k1, v1))
        break
    if v <= V0:
        continue
    diff = {n: (hex(regs[n]), hex(regs1[n])) for n in REGS if regs[n] != regs1[n]}
    if diff and seen < 25:
        print(f"block {b} stage {k} ({ST.STAGES[k][0]:#x}) voice {v}: differ {diff}")
        seen += 1
print("register differences (voices after the stereo one):", sum(1 for x, y in zip(c0, c1)
      if x[2] > V0 and x[3] != y[3]))
for key in sorted(k for k in a0 if k[0] != "ptr"):
    if a0[key] != a1.get(key):
        b, v = key
        print(f"block {b} voice {v} after the amp: mono peak {max(abs(fl(w)) for w in a0[key]):.4g}, "
              f"stereo peak {max((abs(fl(w)) for w in a1.get(key, [])), default=-1):.4g}")

for key in sorted(m0):
    d = [(hex(a), hex(m0[key][a] or 0), hex(m1[key].get(a) or 0)) for a in m0[key] if m0[key][a] != m1[key].get(a)]
    print(f"block {key[0]} at stage {key[1]}'s call for voice {V0 + 1}: {len(d)} words differ", d[:12])
