import sys, pathlib, tempfile, struct
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
import sharc_waverider_m5 as G
import sharc_waverider_render as m1
import sharc_waverider_m4 as m4
import sharc_dn2_fixups as fx
from dnfw.waverider import dsp
from dnfw.sampler import machines as SM, stereo as ST
DK = pathlib.Path("../digikit-wt-sharcemu")
IMG = pathlib.Path("../Digitone_II_OS1.11.syx")
dk = m1.Digikit(DK); fx.bind(str(DK / "tools")); m4.IMAGE = IMG
stock = m1.dn2_section7(IMG)
sound, machines = m4.init_sound(IMG)
m5 = G.Image(dk, dsp.section7(stock))
snap, mach = G.snapshot_path(dk, stock, pathlib.Path(tempfile.mkdtemp()))
init = G.init_on(snap, mach, m5)
ONE = SM.TYPE_OF["ONESHOT"]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
AMP = ST.STAGES[-1]

def run(stereo_v):
    seen = {}          # amp state -> block
    rec = []
    def amp(r):
        seen[G.m2.word_reg(r, "R4")] = G.m2.word_reg(r, "R12")
    def perc(r):
        if stereo_v is not None:
            G.m2.poke(r.state, ST.ANY, 1)
            for k, a in enumerate(ST.voice_laddr(stereo_v)):
                G.m2.poke(r.state, ST.laddr(0, k), a)
            G.m2.poke(r.state, ST.VOICE, stereo_v)
            G.m2.poke(r.state, ST.DUP, 1)
        blocks = {}
        for v in range(16):
            b = seen.get(AMP[2] + v * AMP[3])
            if b:
                blocks[v] = [G.m2.word(r.state, b + 4 * i) for i in range(32)]
        rb = [G.m2.word(r.state, ST.RBLK + 4 * i) for i in range(32)]
        rec.append((blocks, rb, G.m2.word(r.state, ST.ODD), G.m2.word(r.state, ST.GFLAG)))
    fb = lambda b: G.base_frame(sound, machines, t0=ONE, overrides=G.smp_words({SM.TUNE_REC: 67}), trigger=b == 1).to_bytes()
    import json, collections
    trail = collections.deque(maxlen=40)
    hooks = {dsp.PERC_SW: perc, AMP[1]: amp}
    if stereo_v is not None:
        offs = json.load(open("csrc/waverider/sharc/stereo.json"))["instruction_offsets"]
        for o in offs:
            hooks.setdefault(ST.CODE_SW + o // 2, lambda r, a=ST.CODE_SW + o // 2: trail.append(a))
    if stereo_v is not None:
        import sharc_resolve_jumps as RJ
        lab = RJ.labels(open("csrc/waverider/sharc/stereo.asm").read())
        def after(k):
            def h(r):
                lb = G.m2.word(r.state, ST.SAVE_IN + 4 * 12)
                L = [G.m2.word(r.state, lb + 4 * i) for i in range(32)]
                R = [G.m2.word(r.state, ST.RBLK + 4 * i) for i in range(32)]
                if any(w & 0x7FFFFFFF for w in L):
                    fl = lambda w: struct.unpack('<f', struct.pack('<I', w or 0))[0]
                    ratio = next((fl(b) / fl(a) for a, b in zip(L, R) if a & 0x7FFFFFFF), None)
                    STG.append((k, L == R, ratio))
            return h
        for k in range(len(ST.STAGES)):
            hooks[ST.CODE_SW + offs[lab[f"wr_st_r{k}"]] // 2] = after(k)
    r = G.run_blocks(init, fb, N, extra_hooks=hooks)
    if not r["ok"]:
        print("last:", [hex(a) for a in trail])
    return r, rec

STG = []
r0, mono = run(None)
loud = [v for v in range(16) if any(any(w & 0x7FFFFFFF for w in blk.get(v, [])) for blk, *_ in mono)]
print("ok", r0["ok"], "voices sounding:", loud)
V = loud[0] if loud else 0
r1, st = run(V)
print("ok", r1["ok"], r1.get("halt"))
for b, ((lb, rb, odd, gf), (lb0, *_)) in enumerate(zip(st, mono)):
    L = lb.get(V, []); L0 = lb0.get(V, [])
    others = all(lb.get(v) == lb0.get(v) for v in range(16))
    peak = max((abs(struct.unpack('<f', struct.pack('<I', w))[0]) for w in L), default=0)
    f = lambda ws: [round(struct.unpack('<f', struct.pack('<I', w or 0))[0], 6) for w in ws[:6]]
    if b in (1, 3, 7): print("   L", f(L), "\n   R", f(rb))
    print(f"block {b}: R == L {rb == L}  L == mono run {L == L0}  every voice as mono {others}  peak {peak:.4f}  odd {odd} gain {gf}")

print("stage checks:", len(STG), "all R == L:", all(x[1] for x in STG), "stages seen:", sorted({x[0] for x in STG}))
