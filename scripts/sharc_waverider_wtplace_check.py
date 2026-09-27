"""scripts/sharc_waverider_wtplace_check.py S7.bin -- waverider-disc-wtplace in the runner (from post-engine-init, 4 blocks, trig on block 1):
a) track 1 WaveTone (+ track 0 MIDI): wtplace's track-1 machine tap == constpitch's
   type-5 track-0 tap, bit for bit (same reader, same constants, phase from 0);
b) tracks != 1 bit-identical to stock (machine tap and end-of-dispatch buffers);
c) strict memory map: violations with the PC in our code; every block returns;
d) no WaveTone track (tracks 1-4 FM Tone/FM Drum/Swarmer/MIDI): all 16 buffers bit-identical to stock."""
import sys, pathlib, tempfile, struct, collections
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
import sharc_waverider_m5 as G
import sharc_waverider_render as m1
import sharc_waverider_m4 as m4
import sharc_dn2_fixups as fx
import sharc_strict_memory as SM

DK = pathlib.Path("D:/01_Code/Z_Personal/digikit-wt-sharcemu")
IMG = pathlib.Path("../../../00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
CP = pathlib.Path("../../../00_Resources/02_Builds/waverider-disc-m5c-constpitch_DN2_1.11.syx")
WTP = pathlib.Path(sys.argv[1])
EXPECT = sys.argv[2] if len(sys.argv) > 2 else "saw"   # "saw": our reader; "stock": passthru
dk = m1.Digikit(DK); fx.bind(str(DK / "tools")); m4.IMAGE = IMG
stock = m1.dn2_section7(IMG)
sound, machines = m4.init_sound(IMG)
fw = m1.load(m1.read_image(CP)); sec = fw.container.find(7); cp = sec.unpack() or sec.raw_payload
wtp = WTP.read_bytes()
work = pathlib.Path(tempfile.mkdtemp())
snap, mach = G.snapshot_path(dk, stock, work)
imgs = {"stock": G.Image(dk, stock), "cp": G.Image(dk, cp), "wtp": G.Image(dk, wtp)}
BLOCKS = 4


def run(name, strict=False, **kw):
    fr = lambda b: G.base_frame(sound, machines, trigger=(b == 1), **kw).to_bytes()
    if strict:
        SM.install(dk, {"stock": stock, "cp": cp, "wtp": wtp}[name]); SM.reset()
    r = G.run_blocks(G.init_on(snap, mach, imgs[name]), fr, BLOCKS)
    assert r["ok"], (name, r.get("halt"))
    return r


def bits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def tap(r, t):
    return [x for blk in r["machine"] for x in blk[t]]


ok = True
w = run("wtp", strict=True, t0=4, others={1: 1}, trigger_others=True)
OURS = [(0x137BFA, 0x138000), (0x160000, 0x178000), (0x180000, 0x190000)]   # block 0 top, block 1, block 2 (sw)
ours = [v for v in SM.violations if v["pc"] is not None and any(a <= v["pc"] < b for a, b in OURS)]
print("c strict: violations with the PC in our code:", len(ours), [(v["kind"], hex(v["pc"]), hex(v["address"])) for v in ours[:10]])
print("  all kinds:", collections.Counter(v["kind"] for v in SM.violations))
ok &= not ours
if EXPECT == "saw":
    c = run("cp", t0=5)
    a, b = tap(w, 1), tap(c, 0)
    mism = sum(bits(x) != bits(y) for x, y in zip(a, b))
    print(f"a track-1 tap vs constpitch track-0 tap: {mism} mismatches of {len(a)}; "
          f"peak {max(abs(x) for x in a):.4f}; first {a[:4]}")
    ok &= mism == 0 and len(a) == BLOCKS * 32 and max(abs(x) for x in a) > 0.5
s = run("stock", t0=4, others={1: 1}, trigger_others=True)
skip = {1} if EXPECT == "saw" else set()
m_same = all([blk[t] for t in range(16) if t not in skip] == [sblk[t] for t in range(16) if t not in skip]
             for blk, sblk in zip(w["machine"], s["machine"]))
e_same = [[x for t, x in enumerate(blk) if t not in skip] for blk in w["buffer_bits"]] == \
         [[x for t, x in enumerate(blk) if t not in skip] for blk in s["buffer_bits"]]
print(f"b tracks {'!= 1' if skip else 'all 16'} vs stock: machine tap identical", m_same, "; end-of-dispatch buffers identical", e_same)
print("  stock WaveTone track-1 tap peak:", max(abs(x) for x in tap(s, 1)))
ok &= m_same and e_same
others = {1: 0, 2: 2, 3: 3, 4: 4}
d_w, d_s = run("wtp", t0=0, others=others, trigger_others=True), run("stock", t0=0, others=others, trigger_others=True)
same16 = d_w["buffer_bits"] == d_s["buffer_bits"]
print("d no WaveTone track: all 16 buffers bit-identical to stock:", same16)
ok &= same16
print(f"WTPLACE CHECK ({EXPECT})", "PASS" if ok else "FAIL")
