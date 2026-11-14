"""stereo: each wrapped stage's footprint around R4 during its L call, over step_stereo's runs
(every filter type, moving sounds): SIZES in dnfw.sampler.stereo."""
import sys, pathlib, tempfile, struct
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
import sharc_waverider_m5 as G, sharc_waverider_render as m1, sharc_waverider_m4 as m4, sharc_dn2_fixups as fx
from dnfw.waverider import dsp
DK = pathlib.Path("../digikit-wt-sharcemu"); IMG = pathlib.Path("../Digitone_II_OS1.11.syx")
dk = m1.Digikit(DK); fx.bind(str(DK / "tools")); m4.IMAGE = IMG
stock = m1.dn2_section7(IMG); sound, machines = m4.init_sound(IMG)
m5 = G.Image(dk, dsp.section7(stock))
snap, mach = G.snapshot_path(dk, stock, pathlib.Path(tempfile.mkdtemp()))
init = G.init_on(snap, mach, G.Image(dk, m5.stream), warm=True)

import json
from dnfw.sampler import stereo as ST
import sharc_resolve_jumps as RJ
offs = json.load(open("csrc/waverider/sharc/stereo.json"))["instruction_offsets"]
lab = RJ.labels(open("csrc/waverider/sharc/stereo.asm").read())
at = lambda n: ST.CODE_SW + offs[lab[n]] // 2
import sharc_core.memory as _mem
_ow, _or = _mem._dm_write, _mem._dm_read
W = {"on": None, "w": {}, "r": {}}
def _w(state, address, width, value, *a, **k):
    if W["on"]: W["w"].setdefault(W["on"], set()).add(getattr(address, "value", address))
    return _ow(state, address, width, value, *a, **k)
def _r(state, address, width, *a, **k):
    if W["on"]: W["r"].setdefault(W["on"], set()).add(getattr(address, "value", address))
    return _or(state, address, width, *a, **k)
for _m in list(sys.modules.values()):
    if getattr(_m, "_dm_write", None) is _ow: _m._dm_write = _w
    if getattr(_m, "_dm_read", None) is _or: _m._dm_read = _r

FOOT={}
CUR={"k":None,"r4":None}
def _w2(state, address, width, value, *a, **k):
    _note(address); return _ow(state, address, width, value, *a, **k)
def _r2(state, address, width, *a, **k):
    _note(address); return _or(state, address, width, *a, **k)
def _note(address):
    if CUR["k"] is None: return
    ad=getattr(address,"value",address)
    if isinstance(ad,int):
        o=ad-CUR["r4"]
        if -0x400 <= o < 0x800:
            lo,hi=FOOT.get(CUR["k"],(o,o)); FOOT[CUR["k"]]=(min(lo,o),max(hi,o))
for _m in list(sys.modules.values()):
    if getattr(_m, "_dm_write", None) is _w: _m._dm_write = _w2
    if getattr(_m, "_dm_read", None) is _r: _m._dm_read = _r2
def on(r):
    CUR["k"]=G.m2.word(r.state, ST.CURK) or 0; CUR["r4"]=G.m2.word_reg(r,"R4")
def off(r): CUR["k"]=None
orig=G.run_blocks
def rb(init, fb, blocks, extra_hooks=None):
    hh=dict(extra_hooks or {})
    for K in range(len(ST.STAGES)):
        hh[ST.STAGES[K][1]]=lambda r: on(r) if CUR.get("arm") else None
        hh[at(f"wr_st_cl{K}")]=lambda r: CUR.__setitem__("arm",1)
        hh[at(f"wr_st_cl{K}_b")]=lambda r: (off(r), CUR.__setitem__("arm",0))
    return orig(init, fb, blocks, extra_hooks=hh)
G.run_blocks=rb
r = G.step_stereo(init, sound, machines, blocks=6)
for k in sorted(FOOT): print(k, hex(ST.STAGES[k][1]), "stride", hex(ST.STAGES[k][3]), "footprint", [hex(x) for x in FOOT[k]])
