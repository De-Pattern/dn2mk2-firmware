"""Stereo slots past 0 on the SHARC runner: three ONESHOT tracks, one voice each (a chord, as
step_smp_chords), the first two voices marked stereo (slots 0 and 1) in test mode (DUP: R's block is L's as rendered), against
the mono run. Every voice's block after the amp must equal the mono run's, and R's block each
slot's L (v0.76-t1 on both processors: the second stereo voice, and a mono voice beside it, silent).

    python3 scripts/sharc_stereo_slots.py [BLOCKS]"""

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
N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
AMP = ST.STAGES[-1]
fl = lambda w: struct.unpack("<f", struct.pack("<I", w or 0))[0]   # noqa: E731


def run(stereo: dict | None):
    seen, rec = {}, []

    cur, last = {}, []

    def amp(r):                                   # at each amp call: the previous voice's amp
        if last:                                  # has returned, its block is its output
            st_, b_ = last.pop()
            cur[(st_ - AMP[2]) // AMP[3]] = [G.m2.word(r.state, b_ + 4 * i) for i in range(32)]
        seen[G.m2.word_reg(r, "R4")] = G.m2.word_reg(r, "R12")
        last.append((G.m2.word_reg(r, "R4"), G.m2.word_reg(r, "R12")))

    def perc(r):
        if stereo:
            G.m2.poke(r.state, ST.ANY, len(stereo))
            for s, v in stereo.items():
                for k, a in enumerate(ST.voice_laddr(v)):
                    G.m2.poke(r.state, ST.laddr(s, k), a)
                G.m2.poke(r.state, ST.VOICE + 4 * s, v)
                G.m2.poke(r.state, ST.DUP + 4 * s, 1)
        if last:
            st_, b_ = last.pop()
            cur[(st_ - AMP[2]) // AMP[3]] = [G.m2.word(r.state, b_ + 4 * i) for i in range(32)]
        blocks = dict(cur)
        cur.clear()
        rbs = [[G.m2.word(r.state, ST.RBLK + 128 * s + 4 * i) for i in range(32)] for s in range(ST.SLOTS)]
        rec.append((blocks, rbs, G.m2.word(r.state, ST.ODD)))

    words = G.smp_words({SM.TUNE_REC: 67})

    def fb(b):                                    # tracks 0..2 ONESHOT, one voice each (as
        f = G.base_frame(sound, machines, t0=ONE, overrides=words, trigger=b == 1,   # step_smp_chords)
                         others={t: ONE for t in (1, 2)}, trigger_others=True)
        for t in range(3):
            for slot, w in words.items():
                f.param(t, slot, w)
            f.header(G.FR.NOTE, t, (0x3C00, 0x4000, 0x4300)[t])
            f.header(G.FR.LEVEL, t, f.get(G.FR.header_offset(G.FR.LEVEL, 0)))
        return f.to_bytes()
    r = G.run_blocks(init, fb, N, extra_hooks={dsp.PERC_SW: perc, AMP[1]: amp})
    print("  smp out peaks per track:", [{t: round(max(map(abs, v["out"]), default=0), 4) for t, v in blk.items()}
                                          for blk in r.get("smp", [])][:5],
          "voice tracks:", [G.m2.word(r["state"].state, ST.VOICE_TRACK + 4 * v) for v in range(4)] if "state" in r else None,
          flush=True)
    return r, rec


def peak(ws):
    return max((abs(fl(w)) for w in ws), default=0.0)


r0, mono = run(None)
# the perc hook reads the previous block's amp outputs: block b's record holds block b-1's
loud = sorted({v for blk, *_ in mono for v, ws in blk.items() if peak(ws) > 0})
print("mono: ok", r0["ok"], "voices sounding:", loud, flush=True)
if len(loud) < 2:
    print("FAIL: fewer than two voices sound in the mono run")
    sys.exit(1)
pair = {0: loud[0], 1: loud[1]}
r1, st = run(pair)
print("stereo slots", pair, ": ok", r1["ok"], r1.get("halt"))
bad = 0
for b, ((blk, rbs, odd), (blk0, *_)) in enumerate(zip(st, mono)):
    diff = [v for v in range(16) if blk.get(v) != blk0.get(v)]
    rl = {s: rbs[s] == blk.get(v, rbs[s]) for s, v in pair.items()}
    print(f"block {b}: voices differing from mono {diff}; R == L per slot {rl}; odd {odd}; "
          + "; ".join(f"v{v} {peak(blk0.get(v, [])):.4f}->{peak(blk.get(v, [])):.4f}" for v in loud))
    bad += bool(diff) or not all(rl.values())
print("PASS" if not bad and r1["ok"] else "FAIL")
