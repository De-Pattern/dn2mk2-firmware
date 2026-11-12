"""v0.52 FLEX MUTE SRC (owner, 2026-11-12, option B: "the whole time" it is ON), through both processors
(emu_coupled.py).

  direct: track 1 FLEX (smp_machine_commit), its SRC TRK3 (fx_set)
  UI:     [TRK] + [TRIG 2], FUNC + VOICE (FLEX REC), RIGHT (REC SETUP), knob H right four detents
          (MUTE ON), NO; [TRK] + [TRIG 3], KEYBOARD, [TRIG 9] held: a note on track 3, three times:
          MUTE OFF (H left four detents first, then ON again by fx_set for the third), ON, OFF

Links: 1 H turns MUTE ON (the track's sound keeps it: fx_get FX_MUTE; the panel's bn_mute);
2 the mask names track 3 (ms_mask); 3 muted, every voice playing track 3 has the frame's LEVEL and
its three FX sends at 0, and the DSP's record +0x22c (the LEVEL it unpacked) 0; 4 the other voices'
LEVEL as unmuted; 5 the track still plays: its voice's block after the chain (TRACK_BUFFERS, the
TRK source FLEX records, docs/link-research.md B) as loud muted as unmuted (within 3 dB); 6 MUTE
OFF gives LEVEL and the sends back.

Negative control (--break nomute): H is not turned, MUTE stays OFF: fails at 1 (and 3).

Usage: emu_coupled_mute.py --build out/v052.syx [--break nomute] [--json OUT]"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from emu_coupled import CF_FRAME, Coupled                       # noqa: E402
from emu_coupled_flex import install_smoother_model             # noqa: E402

KIT, STRIDE = 0x800052A0, 1163
FLEX = 17
T, S = 1, 2                              # the FLEX track, its SRC's track (TRK3)
SLOT_TRACK = 0x80005308
KB_ON = 0x42431A9C
FX_SRC, FX_MUTE = 0, 6
SENDS = (86, 87, 88)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--stock", default=str(HERE.parent.parent / "Digitone_II_OS1.11.syx"))
    p.add_argument("--snapshot", default=str(HERE.parent.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"))
    p.add_argument("--break", dest="brk", default=None, choices=("nomute",))
    p.add_argument("--json", default=None)
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    c = Coupled(a.build, a.snapshot, a.stock, verbose=True)
    c.watchdog()
    install_smoother_model(c)
    rep = {"links": {}, "numbers": {}, "break": a.brk}
    fail = []

    def link(name, ok, detail=""):
        rep["links"][name] = {"ok": bool(ok), "detail": detail}
        print(("  ok    " if ok else "  FAIL  ") + name + (f" -- {detail}" if detail else ""), flush=True)
        if not ok:
            fail.append(name)
        return ok

    def done():
        rep["halt"], rep["faults"] = c.halt, [str(f) for f in c.faults()[:5]]
        if a.json:
            pathlib.Path(a.json).write_text(json.dumps(rep, indent=1, default=str))
        ok = not fail and not c.halt
        print(("PASS" if ok else "FAIL") + (f": the first broken link: {fail[0]}" if fail else "")
              + (f" (halt: {c.halt})" if c.halt else ""), flush=True)
        return 0 if ok else 1

    key = lambda code: divmod(code - 1, 8)                       # noqa: E731
    P = c.panel.panelin

    def held(code, on, n=3):
        c.machine.pc = (P.press if on else P.release)(c.machine.m, c.panel.profile, *key(code))
        c.periods(n)

    def tap(code):
        held(code, True)
        held(code, False)

    def turn(enc, delta, n):
        for _ in range(n):
            c.machine.pc = P.encoder(c.machine.m, c.panel.profile, enc, delta)
            c.periods(2)

    kit = c.long(KIT)
    snd = kit + 52 + STRIDE * T
    owner = c.call(0x4018A97A)[0]
    c.call(lay["smp_machine_commit"], owner + 0xF4, T, FLEX, 1, 1)
    c.periods(2)
    c.call(lay["fx_set"], T, FX_SRC, 2 + S)
    if not link("0. track 2 is FLEX, its SRC TRK3", c.read(snd + 0xDE, 1)[0] == FLEX
                and c.call(lay["fx_get"], T, FX_SRC)[0] == 2 + S, f"type {c.read(snd + 0xDE, 1)[0]}"):
        return done()

    # MUTE through the panel: track 2, FLEX REC, REC SETUP, knob H
    held(16, True); tap(25 + T); held(16, False)
    c.periods(4)
    held(17, True); held(49, True); held(49, False); held(17, False)
    tap(15)                                                      # RIGHT: REC SETUP
    up = c.call(lay["bn_active"])[0] & 0xFF
    if a.brk != "nomute":
        turn(7, 1, 4)
    m_fx, m_ui = c.call(lay["fx_get"], T, FX_MUTE)[0], c.long(lay["bn_mute"])
    link("1. knob H on FLEX REC SETUP turns MUTE ON (four detents; kept in the track's sound)",
         up and m_fx == 1 and m_ui == 1, f"bn_active {up}, fx_get {m_fx}, bn_mute {m_ui}")
    turn(7, -1, 4)                                               # .. and OFF again, for the first note
    m_off = c.call(lay["fx_get"], T, FX_MUTE)[0]
    tap(12)                                                      # NO: closed
    rep["numbers"]["after_left"] = m_off

    # notes on track 3
    held(16, True); tap(25 + S); held(16, False)
    c.periods(4)
    if not c.read(KB_ON, 1)[0]:
        tap(18)

    def word(fr, off):
        return struct.unpack(">H", fr[off:off + 2])[0]

    def note(mute, n=64):
        if a.brk != "nomute" or not mute:
            c.call(lay["fx_set"], T, FX_MUTE, 1 if mute else 0)
        c.machine.pc = P.press(c.machine.m, c.panel.profile, *key(33))
        got = []
        for _ in range(n):
            if not c.period():
                break
            vt = struct.unpack(">16I", c.read(SLOT_TRACK, 64))
            fr = c.last_frame
            got.append({"mask": c.long(lay["ms_mask"]),
                        "voices": {v: {"track": vt[v], "level": word(fr, 116 + 2 * v),
                                       "sends": [word(fr, 168 + 2 * s + 146 * v) for s in SENDS],
                                       "dsp_level": c.dsp_word(c.M.V.track_record(v) + 0x22C),
                                       "peak": max(abs(x) for x in c.last_bufs[v])} for v in range(16)}})
        c.machine.pc = P.release(c.machine.m, c.panel.profile, *key(33))
        c.periods(30)
        return got

    off1, on, off2 = note(False), note(True), note(False)

    def s_voices(g):
        return [v for v in range(16) if g["voices"][v]["track"] == S]

    def peak(run):
        return max((p["voices"][v]["peak"] for p in run for v in s_voices(p)), default=0.0)
    late = on[-24:]                                              # after the fade (32 frames)
    rep["numbers"]["masks"] = sorted({g["mask"] for g in on})
    link("2. the mask names track 3 (ms_mask)", all(g["mask"] == 1 << S for g in late),
         f"masks {rep['numbers']['masks']}")
    muted = [(g["voices"][v]["level"], g["voices"][v]["sends"], g["voices"][v]["dsp_level"])
             for g in late for v in s_voices(g)]
    rep["numbers"]["muted"] = muted
    bad3 = [m for m in muted if not (m[0] == 0 and not any(m[1]) and m[2] == 0)]
    link("3. muted (after the 32-frame fade): each voice of track 3 has the frame's LEVEL and FX sends at 0, "
         "and the DSP's LEVEL 0", muted and not bad3, f"{len(muted)} readings, not 0: {bad3[:3]}")
    others = [(v, off1[-1]["voices"][v]["level"], on[-1]["voices"][v]["level"]) for v in range(16)
              if on[-1]["voices"][v]["track"] != S and off1[-1]["voices"][v]["track"] == on[-1]["voices"][v]["track"]]
    # (stock's LEVEL drifts a little between the runs, about 2 %, for every voice alike)
    def near(x, y):
        return x > 0 and abs(x - y) <= 0.03 * x
    link("4. the other voices' LEVEL as unmuted (within stock's own 3 % drift; none faded)",
         others and all(near(x, y) for _, x, y in others), f"{others[:4]}")
    p_off, p_on = peak(off1), peak(on)
    db = 20 * math.log10(p_on / p_off) if p_off > 0 and p_on > 0 else None
    rep["numbers"]["peaks"] = {"unmuted": p_off, "muted": p_on, "db": db}
    link("5. track 3 still plays: its block after the chain (the TRK source) as loud muted (within 3 dB)",
         p_off > 0.001 and db is not None and abs(db) <= 3.0, f"peak unmuted {p_off:.4f}, muted {p_on:.4f}")
    back = [(g["voices"][v]["level"], g["voices"][v]["sends"]) for g in off2[-10:] for v in s_voices(g)]
    first = [(g["voices"][v]["level"], g["voices"][v]["sends"]) for g in off1[-10:] for v in s_voices(g)]
    link("6. MUTE OFF: LEVEL and the sends back (as before it was ON, within stock's drift)",
         back and first and near(first[-1][0], back[-1][0]) and back[-1][1] == first[-1][1],
         f"before {first[-1:]}, after {back[-1:]}")
    return done()


if __name__ == "__main__":
    raise SystemExit(main())
