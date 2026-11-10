"""v0.48 (Error Kit, Discord 2026-11-09: "threshold recording only starts when I set Threshold
to 0 ... as soon as I set it to 1 or 10 the rec doesn't start"), on the coupled emulator
(emu_coupled.py): the ColdFire's RECORDER and the DSP's recorder together, nothing standing in.

The input (IN, L and R alike) is a 440 Hz tone at -34 dBFS. The RECORDER is opened on an
ONESHOT track, SRC IN, R.STRT THRES; ARM is knob H's turn, as a person arms it.

  A. THRES 30: its tick on the meter is at -45 dB, under the tone's bar: the take starts
     (the DSP's status says recording) within a few periods of the ARM.
  B. THRES 110: its tick at -5 dB, over the tone: armed, nothing starts; THRES turned down to
     30 while armed: the take starts, without re-arming.

Each run's numbers: the periods to the ARM's echo and to the start, the status words."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from emu_coupled import Coupled                                 # noqa: E402

KIT, SOUND_STRIDE = 0x800052A0, 1163
ONESHOT = 8
AMP = 10 ** (-34 / 20)


def tone(block):
    s = [AMP * math.sin(2 * math.pi * 440 * (32 * block + k) / 48000) for k in range(32)]
    return s, s


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--stock", default=str(HERE.parent.parent / "Digitone_II_OS1.11.syx"))
    p.add_argument("--snapshot", default=str(HERE.parent.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"))
    p.add_argument("--json", default=None)
    p.add_argument("--only", default="AB")
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    report = {"checks": {}, "numbers": {}}

    def setup():
        c = Coupled(a.build, a.snapshot, a.stock, verbose=True)
        from dnfw.sampler import machines as SM                 # noqa: PLC0415
        kit = c.long(KIT)
        c.poke(kit + 52 + SOUND_STRIDE * 0 + 0xDE, bytes([ONESHOT]))
        c.poke(SM.MIRROR + 8, b"\x00" * 16 * SM.POOL_SLOTS)     # every slot empty: room to record
        c.put32(lay["smp_dir_ok"], 1)
        c.input = tone
        c.periods(4)
        c.call(lay["rec_combo"])                                # FUNC + VOICE: the RECORDER
        c.put32(lay["rec_src"], 0)                              # IN
        if "rec_rstrt" in lay:                                  # (v0.47 did not export it: 0 there)
            c.put32(lay["rec_rstrt"], 0)                        # R.STRT THRES
        return c

    def state(c):
        return c.last_status[0] & 3 if c.last_status[0] & 0xFF00 == 0x5A00 else None

    def arm(c):
        c.machine.pc = c.panel.panelin.encoder(c.machine.m, c.panel.profile, 7, 1)   # knob H, right: ARM
        c.panel.settle(10_000_000)                              # the UI takes the turn (as the gate's spin:)

    def run_until(c, want, limit):
        for n in range(limit):
            if not c.period():
                return None
            if state(c) == want:
                return n + 1
        return None

    if "A" in a.only:
        c = setup()
        c.put32(lay["rec_thres"], 30)
        arm(c)
        armed = run_until(c, 1, 30)
        started = run_until(c, 2, 30) if armed else None
        report["numbers"]["A"] = {"armed_after": armed, "started_after": started, "status": c.last_status,
                                  "halt": c.halt, "faults": len(c.faults())}
        print("  A:", report["numbers"]["A"], flush=True)
        report["checks"]["A: THRES 30 (tick -45 dB), a -34 dB tone: armed, then the take starts"] = bool(
            armed and started and started <= 6)
    if "B" in a.only:
        c = setup()
        c.put32(lay["rec_thres"], 110)
        arm(c)
        armed = run_until(c, 1, 30)
        held = None
        if armed:
            held = all(c.period() and state(c) == 1 for _ in range(8))
        c.put32(lay["rec_thres"], 30)                           # turned down while armed
        started = run_until(c, 2, 30) if armed else None
        report["numbers"]["B"] = {"armed_after": armed, "held_at_110": held, "started_after_change": started,
                                  "status": c.last_status, "halt": c.halt, "faults": len(c.faults())}
        print("  B:", report["numbers"]["B"], flush=True)
        report["checks"]["B: THRES 110 (tick -5 dB) holds the -34 dB tone back; THRES 30 while armed: it starts"] = bool(
            armed and held and started and started <= 8)
    ok = all(report["checks"].values()) and bool(report["checks"])
    report["ok"] = ok
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1))
    for k, v in report["checks"].items():
        print(("  ok    " if v else "  FAIL  ") + k, flush=True)
    print(("PASS" if ok else "FAIL") + f": {sum(report['checks'].values())}/{len(report['checks'])} checks", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
