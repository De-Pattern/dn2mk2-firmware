import sys, json, pathlib
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
import sharc_waverider_render as m1, sharc_dn2_fixups as fx
from dnfw.waverider import dsp
from dnfw.sampler import stereo as ST
DK = pathlib.Path("../digikit-wt-sharcemu"); dk = m1.Digikit(DK); fx.bind(str(DK / "tools"))
stock = m1.dn2_section7(pathlib.Path("../Digitone_II_OS1.11.syx"))
mod = dsp.section7(stock)
mem = dk.ldr.LoadedMemory.from_stream(mod)
spec = json.load(open("csrc/waverider/sharc/stereo.json")); offs = spec["instruction_offsets"]
walk = dk.walk(mem, ST.CODE_SW, ST.CODE_SW + max(offs) // 2 + 4)
starts = {(sw - ST.CODE_SW) * 2 for sw, *_ in walk}
miss = [o for o in offs if o not in starts]
bad = [f"{sw:#x} {form} {kind}" for sw, _, form, kind in walk if form == "unknown" or kind == "uncertain"]
lines = [l for l in open("csrc/waverider/sharc/stereo.asm").read().splitlines() if l.split("//")[0].strip() and not l.split("//")[0].strip().startswith(".") and not l.split("//")[0].strip().endswith(":")]
print("instructions", len(offs), "missed starts", len(miss), "unknown/uncertain", len(bad))
for o in miss[:20]:
    k = offs.index(o); print(f"  {ST.CODE_SW + o // 2:#x}: {lines[k-1].strip()}  ||  {lines[k].strip()}")
