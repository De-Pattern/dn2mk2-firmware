"""scripts/sharc_entry_state_diff.py OURS_S7.bin -- the core state on entry to the WaveTone render call, stock vs ours.

Runs stock section 7 and OURS_S7 the same way (post-engine-init, 4 blocks, WaveTone on
track 1, trig on block 1) and snapshots, at the callee's first instruction of the
render call at sw 0x1c9611 (stock: 0x1c6d4a; ours: the adapter), every universal
register except the R/F data registers, the loop stack, the PC-stack depth and the
status stack. Prints what differs.

The DN2's DSP stops on silicon on the first call of our reader but not in the
runner (docs/for-digikit-waverider-dsp-stop.md). A mode bit, a circular-buffer
length, a live hardware loop or a stack depth that differs at entry is state the
silicon may act on where the runner does not."""
import os, sys, pathlib, tempfile
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
import sharc_waverider_m5 as G
import sharc_waverider_render as m1
import sharc_waverider_m4 as m4
import sharc_dn2_fixups as fx

# the runner: a digikit work/sharc-emulator checkout (DIGIKIT_SHARC picks another)
DK = pathlib.Path(os.environ.get("DIGIKIT_SHARC", "D:/01_Code/Z_Personal/digikit-wt-sharcemu"))
IMG = pathlib.Path("../../../00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
STOCK_ENTRY, OUR_ENTRY = 0x1C6D4A, 0x180200
dk = m1.Digikit(DK); fx.bind(str(DK / "tools")); m4.IMAGE = IMG
from sharc_core.encoding import UREG_NAMES  # noqa: E402  (after the runner's path is bound)
stock = m1.dn2_section7(IMG)
sound, machines = m4.init_sound(IMG)
ours = pathlib.Path(sys.argv[1]).read_bytes()
snap, mach = G.snapshot_path(dk, stock, pathlib.Path(tempfile.mkdtemp()))
SKIP = {n for n in UREG_NAMES if n and n[0] in "RF" and n[1:].isdigit()} | {"EMUCLK", "EMUCLK2", "PC"}


def snapshot(r):
    st = r.state
    regs = {n: str(st.uregs.get(k)) for k, n in enumerate(UREG_NAMES) if n and n not in SKIP}
    regs["(loops)"] = str([(getattr(l, "end", None), getattr(l, "count", None)) for l in st.loops])
    regs["(pc stack depth)"] = str(len(st.call_stack))
    regs["(status stack depth)"] = str(len(st.status_stack))
    return regs


def run(image, entry):
    got = []
    fr = lambda b: G.base_frame(sound, machines, trigger=(b == 1), t0=4, others={1: 1},
                                trigger_others=True).to_bytes()
    r = G.run_blocks(G.init_on(snap, mach, G.Image(dk, image)), fr, 4,
                     extra_hooks={entry: lambda rr: got.append(snapshot(rr))})
    assert r["ok"], r.get("halt")
    return got


s, o = run(stock, STOCK_ENTRY), run(ours, OUR_ENTRY)
print(f"entries: stock {len(s)}, ours {len(o)}")
for k in range(min(len(s), len(o))):
    diff = {n: (s[k][n], o[k][n]) for n in s[k] if s[k][n] != o[k].get(n)}
    print(f"-- call {k}: {len(diff)} differing")
    for n, (a, b) in sorted(diff.items()):
        print(f"   {n:22s} stock {a:40.40s} ours {b:.40s}")
if s:
    print("-- stock state at entry, call 0 (the non-default part):")
    for n, v in sorted(s[0].items()):
        if v not in ("Const(0)", "Const(value=0)", "None", "0"):
            print(f"   {n:22s} {v:.60s}")
