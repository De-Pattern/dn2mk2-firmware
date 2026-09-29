"""scripts/sharc_waverider_stages_trace.py S7.bin -- the stage markers of waverider-disc-stages in the runner.

Runs the build as the wtplace check does (post-engine-init, 4 blocks, WaveTone on track
1, trig on block 1) and logs every write to the markers' two reply words
(build_waverider_disc_wtplace.MARK_AT), in order. Passes when both words take the same
values, each block's sequence is the full path (1..19, 10..15 once per sample), and the
last value is 19: what the probe must read on the instrument when nothing stalls."""
import sys, pathlib, tempfile, collections
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
import sharc_waverider_m5 as G
import sharc_waverider_render as m1
import sharc_waverider_m4 as m4
import sharc_dn2_fixups as fx
import build_waverider_disc_wtplace as W

DK = pathlib.Path("D:/01_Code/Z_Personal/digikit-wt-sharcemu")
IMG = pathlib.Path("../../../00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
dk = m1.Digikit(DK); fx.bind(str(DK / "tools")); m4.IMAGE = IMG
stock = m1.dn2_section7(IMG)
sound, machines = m4.init_sound(IMG)
img = pathlib.Path(sys.argv[1]).read_bytes()
snap, mach = G.snapshot_path(dk, stock, pathlib.Path(tempfile.mkdtemp()))

log = {a: [] for a in W.MARK_AT}
import sharc_core.memory as mem
orig = getattr(mem._dm_write, "__wrapped_trace__", mem._dm_write)


def w(state, address, width, value, *a, **k):
    ad = getattr(address, "value", address)
    if ad in log:
        v = getattr(value, "value", value)
        log[ad].append(v if isinstance(v, int) else None)
    return orig(state, address, width, value, *a, **k)


w.__wrapped_trace__ = orig
for m in list(sys.modules.values()):
    if getattr(m, "_dm_write", None) is orig:
        m._dm_write = w

fr = lambda b: G.base_frame(sound, machines, trigger=(b == 1), t0=4, others={1: 1},
                            trigger_others=True).to_bytes()
r = G.run_blocks(G.init_on(snap, mach, G.Image(dk, img)), fr, 4)
assert r["ok"], r.get("halt")
a, b = (log[x] for x in W.MARK_AT)
st = [None if v is None else (v & 0xFFFF if v >> 16 == 0x5752 else ("?", hex(v))) for v in a]
print("writes per page:", len(a), len(b), "; pages agree:", a == b)
runs, cur = [], []
for s in st:
    if s == 1 and cur:
        runs.append(cur); cur = []
    cur.append(s)
runs.append(cur)
want = [1, 2, 3, 4, 5, 6, 7, 8, 9] + [10, 11, 12, 13, 14, 15] * 32 + [16, 18, 19]
for k, run in enumerate(runs):
    c = collections.Counter(run)
    print(f"block {k}: {len(run)} markers, first {run[:10]}, last {run[-4:]}, stage 14 x{c[14]}; full path: {run == want}")
ok = a == b and len(runs) == 4 and all(run == want for run in runs) and st[-1] == 19
print("last value", hex(a[-1]) if a and a[-1] is not None else None)
print("STAGES TRACE", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
