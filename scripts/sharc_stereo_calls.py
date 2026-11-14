"""stereo: every CALL in the voice chain body under random sounds and every filter type:
site, R4, whether R12 is a voice's block (STAGES, EXTRA_SITES in dnfw.sampler.stereo).
python scripts/sharc_stereo_calls.py SEED SITE,SITE,... (the sites: CALLs in sw 0x1c8ef1..0x1c9d3f)"""
import sys, pathlib, tempfile, struct, random, collections
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
import sharc_waverider_m5 as G, sharc_waverider_render as m1, sharc_waverider_m4 as m4, sharc_dn2_fixups as fx
from dnfw.waverider import dsp, frame as FR
from dnfw.sampler import stereo as ST, machines as SM
DK = pathlib.Path("../digikit-wt-sharcemu"); IMG = pathlib.Path("../Digitone_II_OS1.11.syx")
dk = m1.Digikit(DK); fx.bind(str(DK / "tools")); m4.IMAGE = IMG
stock = m1.dn2_section7(IMG); sound, machines = m4.init_sound(IMG)
m5 = G.Image(dk, dsp.section7(stock))
snap, mach = G.snapshot_path(dk, stock, pathlib.Path(tempfile.mkdtemp()))
init = G.init_on(snap, mach, G.Image(dk, m5.stream), warm=True)
mem = dk.ldr.LoadedMemory.from_stream(stock)
sites = []
for sw, n, form, kind in dk.walk(mem, 0x1c8ef1, 0x1c9d3f):
    import sharc_disasm as D
    insn = D.decode_confident_loaded(mem, sw)
    if "CALL" in insn.type_name.upper() or "CJUMP" in insn.type_name.upper() or insn.type_name.startswith("8a") or insn.type_name.startswith("8b"):
        sites.append(sw)
SITES = [int(x, 16) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None
seen = collections.defaultdict(set)
def hook(site):
    def h(r):
        R4, R8, R12 = (G.m2.word_reg(r, n) for n in ("R4", "R8", "R12"))
        blocks = {G.m2.word(r.state, ST.VOICE_BLOCK + 4 * v): v for v in range(16)}
        v = blocks.get(R12)
        seen[site].add((hex(R4), v, R8 == R12))
    return h
ONE = SM.TYPE_OF["ONESHOT"]
rnd = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
def fb(b):
    w = {i: rnd.randrange(0, 0x80) << 8 for i in [*range(66, 93), *range(95, 100)]}
    f = G.base_frame(sound, machines, t0=ONE, overrides={**w, **G.smp_words()}, trigger=b == 1)
    f.header(FR.FILTER, 0, FR.FILTER_TO_DSP[b % 6])
    return f.to_bytes()
hooks = {s: hook(s) for s in SITES} if SITES else {}
r = G.run_blocks(init, fb, 24, extra_hooks=hooks)
print("ok", r["ok"])
for s in sorted(seen):
    print(hex(s), sorted(seen[s], key=str)[:4], len(seen[s]), "voice0:", [x for x in seen[s] if x[1] == 0][:2])
