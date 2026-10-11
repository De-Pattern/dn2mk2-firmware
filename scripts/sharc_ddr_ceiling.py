"""How high in the SHARC's DDR does the stock engine reach at run time?

    python scripts/sharc_ddr_ceiling.py --image STOCK_1.11 --digikit DIGIKIT_SHARCEMU
        [--blocks 8]

W5 wants room for many wavetables. The boot stream loads 5.4 MB into DDR, to
0x8052fbe0, but the engine's init writes beyond that (its first table, a sine, is at
0x8052fbe0 itself, `sharc_waverider_voice.SINE_TABLE`). So "past the image" is not
free by itself. This runs the DN2 1.11 engine init from scratch and then the slot
dispatch for each stock machine type, with a recorder on every DM read and write, and
reports the DDR extent anything touched. Tables are only ever placed above that,
with a margin, and the margin is a decision recorded with the build, not here.

A ceiling measured in the runner is evidence, not proof: code paths the runner does
not reach (FX, a different voice count) could reach further. The instrument is the
second check (`docs/w5-tables.md`).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_render as m1                      # noqa: E402
import sharc_waverider_voice as voice                     # noqa: E402
import sharc_dn2_fixups as fx                             # noqa: E402
from dnfw.waverider import testtable                      # noqa: E402

DDR = (0x80000000, 0xA0000000)
IMAGE_END = 0x8052FBE0


class Recorder:
    def __init__(self):
        self.lo = {"r": None, "w": None}
        self.hi = {"r": None, "w": None}
        self.above = {"r": 0, "w": 0}
        self.pages: dict[int, int] = {}
        self.far: dict[str, int] = {}          # "pc:address" for writes far above the image
        self.state = None

    def note(self, address, width, kind):
        a = getattr(address, "value", address)
        if not isinstance(a, int) or not (DDR[0] <= a < DDR[1]):
            return
        end = a + max(width, 1)
        if self.lo[kind] is None or a < self.lo[kind]:
            self.lo[kind] = a
        if self.hi[kind] is None or end > self.hi[kind]:
            self.hi[kind] = end
        if a >= IMAGE_END + 0x10000 and kind == "w" and len(self.far) < 200:
            pc = getattr(self.state, "pc_sw", None) if self.state is not None else None
            self.far[f"{pc:#x}" if pc is not None else "?"] = a
        if a >= IMAGE_END:
            self.above[kind] += 1
            page = a & ~0xFFFF
            self.pages[page] = self.pages.get(page, 0) + 1


def install(rec: Recorder) -> None:
    import sharc_core.memory as mem
    orig_r, orig_w = mem._dm_read, mem._dm_write

    def r(state, address, width, *a, **k):
        rec.state = state
        rec.note(address, width, "r")
        return orig_r(state, address, width, *a, **k)

    def w(state, address, width, value):
        rec.state = state
        rec.note(address, width, "w")
        return orig_w(state, address, width, value)

    for m in list(sys.modules.values()):
        for name, new, old in (("_dm_read", r, orig_r), ("_dm_write", w, orig_w)):
            if getattr(m, name, None) is old:
                setattr(m, name, new)


def snapshot(rec: Recorder) -> dict:
    h = lambda v: None if v is None else f"{v:#010x}"            # noqa: E731
    return {"read": [h(rec.lo["r"]), h(rec.hi["r"])], "write": [h(rec.lo["w"]), h(rec.hi["w"])],
            "accesses_above_image_end": dict(rec.above),
            "pages_above_image_end": {f"{p:#010x}": n for p, n in sorted(rec.pages.items())},
            "far_writes_by_pc": {k: f"{v:#010x}" for k, v in rec.far.items()}}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                       ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--blocks", type=int, default=8)
    p.add_argument("--out", type=pathlib.Path, default=ROOT / "out/w5/ddr_ceiling.json")
    a = p.parse_args()

    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    stream = m1.dn2_section7(a.image)
    with tempfile.TemporaryDirectory() as tmp:
        code, _, _ = m1.reader_code(False, pathlib.Path(tmp))
    mach = voice.Machine(dk, stream, code, testtable.table())
    rec = Recorder()
    install(rec)

    report: dict = {"image_end": f"{IMAGE_END:#010x}"}
    t0 = time.perf_counter()
    snap = ROOT / f"out/w5/init_{mach.sha[:12]}.snap"
    if snap.exists():
        r = fx.sr.load_snapshot(str(snap), mach.memory)
        res, ok = ("cached", None, 0), True
    else:
        r = mach.runner(voice.INIT)
        res = fx.run(r, 60_000_000, mach.fixups(True))
        ok = res[0] == "halt" and res[1].reason == "return without followed call"
        if ok:
            snap.parent.mkdir(parents=True, exist_ok=True)
            fx.sr.save_snapshot(r, str(snap))
    report["init"] = {"ok": ok, "instructions": res[2], "wall_s": round(time.perf_counter() - t0, 1),
                      **snapshot(rec)}
    print("init:", json.dumps(report["init"], indent=1))
    if not ok:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(report, indent=1))
        return 1

    # every stock machine type on track 0, the rest MIDI, a few blocks each
    for mtype, name in ((0, "FM Tone"), (1, "WaveTone"), (2, "FM Drum"), (3, "Swarmer")):
        machines = {0: mtype, **{t: voice.MIDI for t in range(1, voice.V.N_TRACKS)}}
        out = voice.render_blocks(mach, r, a.blocks, machines, arm=(mtype == 1))
        report[name] = {"ok": out.get("ok", True), **snapshot(rec)}
        print(name, json.dumps(report[name]))
    # all sixteen voices on stock synth machines at once
    mix = {t: t % 4 for t in range(voice.V.N_TRACKS)}
    voice.render_blocks(mach, r, a.blocks, mix)
    report["all_sixteen"] = snapshot(rec)
    print("all sixteen:", json.dumps(report["all_sixteen"]))

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=1) + "\n")
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
