"""v0.47's BOUNCE through both processors (emu_coupled.py): a genuine recorder trig, its take,
and the track's playback, on the published v0.47 build (BOUNCE is out of v0.48).

Category 1 for what it shows: v0.47's ColdFire and SHARC code together. Setup marked direct
below is written by the harness; everything else is the panel's keys and the firmware's own
paths (the sequencer's timer ISR at the tempo, rt_frame in the audio ISR, the link, the DSP).

  direct: track 0 BOUNCE (v0.47's smp_machine_commit), an empty pool known to the ColdFire,
          the pattern 4 steps, R.LEN 1 step (its sound slot 40), Q.PLAY OFF (heard at once)
  UI:     FUNC + VOICE (the BOUNCE REC panel), [TRIG 1] (a recorder trig on step 1), NO
          (the panel closed), PLAY, then KEYBOARD and [TRIG 9] held (a note) once the take is
          heard
  IN:     a chirp at 0.25 full scale from block 0

Reported at each link: the trig in the lock store (rt_trig_get), rt_fired and the step, the
DSP's status (recording), the buffer directory (address, frames, steps), the take against
the input (correlation), rt_play's switch, the frame's SAMP word for track 0 (129 + 2 b + h
expected) and type word, the DSP's render of track 0 (peak, correlation with the take).
Whatever the outcome, it is reported; nothing is forced.

Usage: emu_coupled_bounce47.py [--build ../v047-wt/out/v047.syx] [--json OUT]"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from emu_coupled import CF_FRAME, Coupled                       # noqa: E402
from emu_coupled_recplay import best_match, chirp              # noqa: E402

KIT, STRIDE = 0x800052A0, 1163
SEQ_PATTERN, TRACK_CUR = 0x42C5A9A0, 0x42C5A984
PAT_LENGTH, PAT_LOCK_TABLE = 122196, 97872
BOUNCE = 17
SLOT_RLEN, SLOT_SAMP, SLOT_BUF = 40, 43, 35


def main() -> int:
    v47 = HERE.parent.parent / "v047-wt"
    p = argparse.ArgumentParser()
    p.add_argument("--build", default=str(v47 / "out/v047.syx"))
    p.add_argument("--layout", default=str(v47 / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--stock", default=str(HERE.parent.parent / "Digitone_II_OS1.11.syx"))
    p.add_argument("--snapshot", default=str(HERE.parent.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"))
    p.add_argument("--json", default=None)
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    from dnfw.sampler import machines as SM                     # noqa: PLC0415
    from dnfw.waverider import dsp as D                         # noqa: PLC0415
    c = Coupled(a.build, a.snapshot, a.stock, verbose=True)
    c.watchdog()
    rep = {"setup": [], "links": {}, "numbers": {}}

    def link(name, ok, detail=""):
        rep["links"][name] = {"ok": bool(ok), "detail": detail}
        print(("  ok    " if ok else "  FAIL  ") + name + (f" -- {detail}" if detail else ""), flush=True)
        return ok

    def finish():
        rep["halt"], rep["faults"] = c.halt, [str(f) for f in c.faults()[:5]]
        if a.json:
            pathlib.Path(a.json).write_text(json.dumps(rep, indent=1, default=str))
        bad = [k for k, v in rep["links"].items() if not v["ok"]]
        print(("PASS" if not bad and not c.halt else "FAIL") + (f": the first broken link: {bad[0]}" if bad else
              "") + (f" (halt: {c.halt})" if c.halt else ""), flush=True)
        return 1 if bad or c.halt else 0

    key = lambda code: divmod(code - 1, 8)                       # noqa: E731
    P = c.panel.panelin

    def held(code, on):
        c.machine.pc = (P.press if on else P.release)(c.machine.m, c.panel.profile, *key(code))
        c.periods(3)
    kit = c.long(KIT)
    snd = kit + 52
    owner = c.call(0x4018A97A)[0]
    c.call(lay["smp_machine_commit"], owner + 0xF4, 0, BOUNCE, 1, 1)
    rep["setup"].append(("track 0 BOUNCE", "direct: smp_machine_commit called (MACHINE SEL hides BOUNCE in v0.47)"))
    c.poke(SM.MIRROR + 8, b"\x00" * 16 * SM.POOL_SLOTS)
    c.put32(lay["smp_dir_ok"], 1)
    rep["setup"].append(("an empty pool, known", "direct"))
    pat = c.long(SEQ_PATTERN)
    c.poke(pat + PAT_LENGTH, struct.pack(">H", 4))
    c.poke(snd + 0x14 + 2 * SLOT_RLEN, struct.pack(">H", 1 << 8))
    c.put32(lay["rt_qplay"], 0)
    rep["setup"].append(("pattern 4 steps, R.LEN 1, Q.PLAY OFF", "direct: written"))
    c.input = chirp
    c.periods(4, label="settle")
    if not link("0. track 0 is BOUNCE", c.read(snd + 0xDE, 1)[0] == BOUNCE, f"type {c.read(snd + 0xDE, 1)[0]}"):
        return finish()
    held(17, True); held(49, True); held(49, False); held(17, False)
    rep["setup"].append(("the BOUNCE REC panel", "UI: FUNC + VOICE"))
    link("1a. the BOUNCE REC panel is up", c.call(lay["bn_active"])[0] & 0xFF, f"bn_active {c.call(lay['bn_active'])[0]}")
    held(25, True); held(25, False)                              # [TRIG 1]
    table = pat + PAT_LOCK_TABLE
    tv = c.call(lay["rt_trig_get"], table, 0, 0)[0] & 0xFFFF if "rt_trig_get" in lay else None
    rep["setup"].append(("a recorder trig on step 1", "UI: [TRIG 1] on the panel"))
    link("1b. [TRIG 1] put a recorder trig on step 1 (the lock store)", tv == 1, f"rt_trig_get {tv}")
    held(12, True); held(12, False)                              # NO: the panel closed
    fired0 = c.long(lay["rt_fired"])
    held(20, True); held(20, False)                              # PLAY
    rep["setup"].append(("PLAY", "UI"))
    rec_at = end_at = fired_at = None
    t0 = shown = time.perf_counter()
    c.phase = "playing: waiting for the take"
    for n in range(320):
        if not c.period():
            break
        if fired_at is None and c.long(lay["rt_fired"]) != fired0:
            fired_at = n
        st = c.last_status[0]
        if rec_at is None and st & 0xFF00 == 0x5A00 and st & 3 == 2:
            rec_at = n
        if rec_at is not None and end_at is None and not (st & 0xFF00 == 0x5A00 and st & 3 == 2):
            end_at = n
            break
        now = time.perf_counter()
        if now - shown >= 60:
            shown = now
            print(f"  [take] period {n + 1}/320, {(n + 1) / 1.5:.0f} ms, {now - t0:.0f} s, step {c.read(TRACK_CUR, 1)[0]}, "
                  f"fired {fired_at}, recording {rec_at}, status {c.last_status[:2]}", flush=True)
    rep["numbers"]["fire"] = {"fired_at": fired_at, "rt_fired": c.long(lay["rt_fired"]), "rec_at": rec_at,
                              "end_at": end_at, "status": c.last_status[:4], "step": c.read(TRACK_CUR, 1)[0]}
    link("2. the step fired the trig (rt_fired)", fired_at is not None, f"after {fired_at} periods")
    if not link("3. the DSP recorded (status recording, then done)", rec_at is not None and end_at is not None,
                f"recording from period {rec_at} to {end_at}; status {c.last_status[:4]}"):
        return finish()
    c.periods(4)
    ents = [[c.dsp_word(D.SMP_POOL_DDR + SM.BUF_DIR + 12 * k + 4 * j) for j in range(3)] for k in range(16)]
    used = [k for k, e in enumerate(ents) if e[0] and e[1]]
    rep["numbers"]["buffers"] = {"entries": {k: ents[k] for k in used}, "rt_play": list(c.read(lay["rt_play"], 2))}
    if not link("4a. the buffer directory holds a take", len(used) >= 1, f"entries {[(k, ents[k]) for k in used]}"):
        return finish()
    k = used[0]
    addr, frames = ents[k][0], ents[k][1]

    def frames_at(off, n):
        out = []
        for i in range(off, off + n, 2):
            w = c.dsp_word(addr + 2 * i)
            for h in (w & 0xFFFF, w >> 16):
                out.append(((h ^ 0x8000) - 0x8000) / 32768.0)
        return out[:n]
    take = frames_at(0, frames)
    src = []
    for b in range(600):
        src += chirp(b)[0]
    lag, corr = best_match(take[1024:3072], src, range(0, 600 * 32 - 2048))
    rep["numbers"]["take_vs_input"] = {"half": k, "frames": frames, "lag": lag, "corr": corr}
    link("4b. the take is the input", corr > 0.99, f"half {k}: {frames} frames, corr {corr:.4f} at input sample {lag}")
    held(18, True); held(18, False)                              # KEYBOARD
    c.machine.pc = P.press(c.machine.m, c.panel.profile, *key(33))
    rep["setup"].append(("a note", "UI: KEYBOARD, [TRIG 9] held"))
    fw, ty = [], []
    outs = [[] for _ in range(16)]
    c.phase = "the note"
    for n in range(40):
        if not c.period():
            break
        vt = struct.unpack(">16I", c.read(0x80005308, 64))     # voice -> track (the frame is per voice)
        for v in range(16):
            if vt[v] == 0:
                fw.append(struct.unpack(">H", c.read(CF_FRAME + 168 + 2 * SLOT_SAMP + 146 * v, 2))[0])
        ty.append(struct.unpack(">H", c.read(CF_FRAME + 148, 2))[0])
        for b in range(16):
            outs[b] += c.last_bufs[b]
    c.machine.pc = P.release(c.machine.m, c.panel.profile, *key(33))
    c.periods(2)
    peaks = [max((abs(x) for x in o), default=0.0) for o in outs]
    bi = max(range(16), key=lambda b: peaks[b])
    out, peak = outs[bi], peaks[bi]
    rep["numbers"]["peaks"] = [round(x, 4) for x in peaks]
    want = (129 + k) << 8
    rep["numbers"]["note"] = {"frame_samp": sorted(set(fw)), "frame_type": sorted(set(ty)), "peak": peak,
                              "want_samp": want, "rt_play": list(c.read(lay["rt_play"], 2)),
                              "rt_bounce_samp": c.call(lay["rt_bounce_samp"], 0)[0]}
    link("5. the frame selects the take (SAMP 129 + 2 b + h)", want in fw,
         f"frame SAMP words {sorted(hex(x) for x in set(fw))}, want {want:#x}; type words {sorted(hex(x) for x in set(ty))}")
    link("6. the DSP renders track 0", peak > 0.01, f"peak {peak:.4f}")
    if peak > 0.01:
        start = next(i for i, x in enumerate(out) if abs(x) > 1e-4)
        seg = out[start + 256:start + 768]
        lag, corr = best_match(seg, take, range(0, max(1, frames - 512)))
        rep["numbers"]["audio"] = {"lag": lag, "corr": corr}
        link("7. the render is the take", corr > 0.95, f"corr {corr:.4f} at take frame {lag}")
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
