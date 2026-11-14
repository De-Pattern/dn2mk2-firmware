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

def run(stereo_v, dup=1):
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
            G.m2.poke(r.state, ST.DUP, dup)
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
    def tbuf(r):
        TB.append([G.m2.word(r.state, ST.TRACK_BUF + 4 * i) for i in range(16 * 64)])
    TB = []
    PRE_TB, MID_TB = [], []
    hooks = {dsp.PERC_SW: perc, AMP[1]: amp, ST.SUM_POST_SITE + 3: tbuf,
             0x1C2515: lambda r: PRE_TB.append([G.m2.word(r.state, ST.TRACK_BUF + 4 * i) for i in range(16 * 64)]),
             ST.SUM_POST_SITE: lambda r: MID_TB.append([G.m2.word(r.state, ST.TRACK_BUF + 4 * i) for i in range(16 * 64)])}
    DBG[stereo_v, dup] = (PRE_TB, MID_TB)
    MEMS = []
    def memsnap(r):
        if not MEMS:
            MEMS.append({a: G.m2.word(r.state, a) for a in range(0x240000, 0x2A0000, 4)})
    hooks[ST.SUM_POST_SITE + 3] = (lambda r, f=tbuf: (f(r), memsnap(r)))
    def lr(r):
        if stereo_v is not None and dup:
            lb = G.m2.word(r.state, ST.VOICE_BLOCK + 4 * stereo_v)
            L = [G.m2.word(r.state, lb + 4 * i) for i in range(32)]
            R = [G.m2.word(r.state, ST.RBLK + 4 * i) for i in range(32)]
            LRD.append([(i, hex(L[i]), hex(R[i])) for i in range(32) if L[i] != R[i]])
            if AT6:
                L6, R6 = AT6[-1]
                CHG.append(("L changed" if L6 != L else "L same", "R changed" if R6 != R else "R same"))
            PTR.append((hex(lb), hex(seen.get(AMP[2] + stereo_v * AMP[3], 0))))
    def lr2(r):
        WATCH["on"] = None
        lr(r)
    hooks[ST.SUM_POST_SITE] = lr2
    DBG[stereo_v, dup, "mem"] = MEMS
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
                if k == 6:
                    AT6.append((L, R))
                    WATCH["on"] = (lb, lb + 128)
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
    return r, rec, TB

STG = []
DBG = {}
LRD = []
WATCH = {"on": None, "pcs": {}}
import sharc_core.memory as _mem
_ow = _mem._dm_write
def _w(state, address, width, value, *a, **k):
    on = WATCH["on"]
    ad = getattr(address, "value", address)
    if on and isinstance(ad, int) and on[0] <= ad < on[1]:
        pc = getattr(state, "pc_sw", None)
        WATCH["pcs"][pc] = WATCH["pcs"].get(pc, 0) + 1
    return _ow(state, address, width, value, *a, **k)
for _m in list(sys.modules.values()):
    if getattr(_m, "_dm_write", None) is _ow:
        _m._dm_write = _w
AT6 = []
CHG = []
PTR = []
r0, mono, tb0 = run(None)
loud = [v for v in range(16) if any(any(w & 0x7FFFFFFF for w in blk.get(v, [])) for blk, *_ in mono)]
print("ok", r0["ok"], "voices sounding:", loud)
V = loud[0] if loud else 0
r1, st, tb1 = run(V)
r2, st2, tb2 = run(V, dup=0)
print("ok", r1["ok"], r1.get("halt"))
for b, ((lb, rb, odd, gf), (lb0, *_)) in enumerate(zip(st, mono)):
    L = lb.get(V, []); L0 = lb0.get(V, [])
    others = all(lb.get(v) == lb0.get(v) for v in range(16))
    peak = max((abs(struct.unpack('<f', struct.pack('<I', w))[0]) for w in L), default=0)
    f = lambda ws: [round(struct.unpack('<f', struct.pack('<I', w or 0))[0], 6) for w in ws[:6]]
    if b in (1, 3, 7): print("   L", f(L), "\n   R", f(rb))
    print(f"block {b}: R == L {rb == L}  L == mono run {L == L0}  every voice as mono {others}  peak {peak:.4f}  odd {odd} gain {gf}")

print("stage checks:", len(STG), "all R == L:", all(x[1] for x in STG), "stages seen:", sorted({x[0] for x in STG}))

print("track buffers after the sum, R == L (dup): every block identical to the mono run:", tb1 == tb0, len(tb0), "blocks")
lh = all(a[i] == b[i] for a, b in zip(tb2, tb0) for t in range(16) for i in range(t * 64, t * 64 + 32))
rh = [sum(1 for t in range(16) for i in range(t * 64 + 32, t * 64 + 64) if a[i] != b[i]) for a, b in zip(tb2, tb0)]
print("R silent (no dup): L halves as mono:", lh, " R-half words differing per block:", rh)
for b, (a, c) in enumerate(zip(tb1, tb0)):
    d = [(i, a[i], c[i]) for i in range(len(a)) if a[i] != c[i]]
    if d:
        f = lambda w: struct.unpack('<f', struct.pack('<I', w or 0))[0]
        print(f"block {b}: {len(d)} words differ, e.g.", [(i, f(x), f(y)) for i, x, y in d[:4]])

(p0, m0), (p1, m1) = DBG[None, 1], DBG[V, 1]
print("before the sum: dup run == mono run:", p0 == p1, "| after stock's sum (before our post): ==", m0 == m1, "| counts", len(p0), len(p1), len(m0), len(m1))

ma, mb = DBG[None, 1, "mem"][0], DBG[V, 1, "mem"][0]
dif = sorted(a for a in ma if ma[a] != mb[a])
print("block 0, DM 0x240000..0x2a0000 words differing:", len(dif), [hex(a) for a in dif[:40]])

print("at the sum hook, L vs R block differences per block:", LRD[:3])

print("the table's block vs the amp's R12, per block:", PTR[:3])

print("from the amp's return to the sum:", CHG[:3])

print("writes to L's block between the amp and the sum, by pc:", {hex(k) if k else k: v for k, v in WATCH["pcs"].items()})
