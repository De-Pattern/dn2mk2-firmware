"""v0.76: the FLEX step lag through both processors (Dubmaster, 2026-11-25: a FLEX take played
back 41 ms late at 60 BPM, 25 ms at 90, 18 ms at 120 -- a sequencer tick, a sixth of a step).

The sequencer plays everything here, as a user's pattern does: a two-step pattern; track 2 (the
snapshot's synth) has a note on step 1; track 1 is FLEX, recording track 2 (SRC TRK3) with a
one-shot recorder trig on step 1 and R.LEN 2 (the whole pattern), and has a note of its own on
step 1. Pass 1 records track 2; pass 2 plays the take on track 1 while track 2 plays its note
again. Played back on time, track 1's audio in pass 2 is track 2's audio in pass 2 (the same note,
recorded a pass earlier): the lag of the best correlation between them is the playback's lateness.

  direct: track 1 FLEX (smp_machine_commit), the pattern's length 2, track 1's SRC and R.LEN
          (fx_set), the input silent
  UI:     [TRK] + [TRIG 3], GRID RECORD [TRIG 1] (track 2's note); [TRK] + [TRIG 2], GRID
          RECORD [TRIG 1] (track 1's note); FUNC + VOICE (the FLEX REC panel), [TRIG 1] (the
          one-shot recorder trig), NO; PLAY

Links: 1 the take recorded in pass 1 (rt_fired, the DSP's status recording then done); 2 both
tracks sound in pass 2; 3 track 1's pass-2 audio matches track 2's (correlation > 0.9 at the best
lag); 4 the best lag is within 3 ms (144 samples) of on time, either side (v0.75: about a tick,
1,000 samples at 120 BPM).

A negative control: v0.75's build must fail at 4 (a tick late).

Usage: emu_coupled_flexlag.py --build BUILD.syx [--layout waverider_code.json] [--json OUT]"""

from __future__ import annotations

import sys as _osport_sys, pathlib as _osport_pl  # noqa: E401
_osport_sys.path.insert(0, str(_osport_pl.Path(__file__).resolve().parents[1] / 'src'))
from dnfw.osport.os import A  # noqa: E402  (docs/os112-port.md)

import argparse
import json
import math
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from emu_coupled import Coupled                                 # noqa: E402
import emu_coupled_flex as F                                    # noqa: E402
_OSV = __import__("os").environ.get("DN2_OS", "1.11")

SLOT_TRACK = 0x80005308
T, S = 1, 2                             # FLEX track, its source (neither 0: an idle voice reads track 0)
ON_TIME = 144                           # samples (3 ms) either side
TEMPO = 0x80005E60 + 2 * 108


def corr_at(x, y, lag):
    """normalised correlation of x[i] and y[i + lag] over the overlap"""
    lo, hi = max(0, -lag), min(len(x), len(y) - lag)
    if hi - lo < 256:
        return -2.0
    a = x[lo:hi]
    b = y[lo + lag:hi + lag]
    ea = math.sqrt(sum(v * v for v in a)) or 1e-30
    eb = math.sqrt(sum(v * v for v in b)) or 1e-30
    return sum(p * q for p, q in zip(a, b)) / (ea * eb)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--stock", default=str(HERE.parent.parent / f"Digitone_II_OS{_OSV}.syx"))
    p.add_argument("--snapshot", default=str(HERE.parent.parent / f"digikit/out/snapshots/dn2-{_OSV}/ui800M-v014.snap"))
    p.add_argument("--json", default=None)
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    c = Coupled(a.build, a.snapshot, a.stock, verbose=False)
    c.watchdog()
    F.install_smoother_model(c)
    rep = {"links": {}, "numbers": {}}
    t0 = time.perf_counter()

    def link(name, ok, detail=""):
        rep["links"][name] = {"ok": bool(ok), "detail": detail}
        print(("  ok    " if ok else "  FAIL  ") + name + (f" -- {detail}" if detail else ""), flush=True)
        return ok

    def finish():
        rep["halt"], rep["faults"] = c.halt, [str(f) for f in c.faults()[:5]]
        rep["seconds"] = round(time.perf_counter() - t0)
        if a.json:
            pathlib.Path(a.json).write_text(json.dumps(rep, indent=1, default=str))
        bad = [k for k, v in rep["links"].items() if not v["ok"]]
        if c.halt or c.faults():
            print(f"  FAIL  the run: halt {c.halt}, faults {c.faults()[:3]}", flush=True)
        ok = not bad and not c.halt and not c.faults()
        print(("PASS" if ok else "FAIL") + (f": the first broken link: {bad[0]}" if bad else
              ": a FLEX take plays back on the step"), flush=True)
        return 0 if ok else 1

    P = c.panel.panelin
    key = lambda code: divmod(code - 1, 8)                       # noqa: E731

    def held(code, on, n=3):
        c.machine.pc = (P.press if on else P.release)(c.machine.m, c.panel.profile, *key(code))
        c.periods(n)

    def tap(code):
        held(code, True)
        held(code, False)

    def track(t):                                                # [TRK] + [TRIG t+1]
        held(16, True)
        tap(24 + t + 1)
        held(16, False)
        c.periods(4)
    owner = c.call(A(0x4018A97A))[0]
    c.call(lay["smp_machine_commit"], owner + 0xF4, T, F.FLEX, 1, 1)
    c.periods(1)
    for _ in range(800):
        if c.long(lay["rt_on"]):
            break
        c.periods(2)
    pat = c.long(F.SEQ_PATTERN)
    c.poke(pat + F.PAT_LENGTH, struct.pack(">H", 2))
    c.call(lay["fx_set"], T, 0, 2 + S)                           # SRC: track S
    c.call(lay["fx_set"], T, 2, 2)                               # R.LEN: two steps
    c.input = lambda b: ([0.0] * 32, [0.0] * 32)
    c.periods(4)
    for t in (S, T):                                             # a note on step 1 (GRID RECORD)
        track(t)
        tap(19)
        tap(25)
        tap(19)
        c.periods(4)
    track(T)
    held(17, True)                                               # FUNC + VOICE: FLEX REC
    held(49, True)
    held(49, False)
    held(17, False)
    tap(25)                                                      # the one-shot recorder trig
    rtv = c.call(lay["rt_trig_get"], pat + F.PAT_LOCK_TABLE, T, 0)[0] & 0xFFFF
    tap(12)                                                      # NO
    bpm120 = struct.unpack(">H", c.read(TEMPO, 2))[0] or 14400
    step = 86400000 // bpm120                                    # samples a step
    rep["numbers"]["setup"] = {"rt_trig": rtv, "bpm": bpm120 / 120, "step_samples": step}
    fired0 = c.long(lay["rt_fired"])
    tap(20)                                                      # PLAY
    a_s, a_t, log, sounds = [], [], [], []
    rec_seen = rec_done = False
    n_periods = (4 * step) // 32 + 40                            # two passes and a margin
    for n in range(n_periods):
        if not c.period():
            break
        st = c.last_status[0]
        rec = st & 0xFF00 == 0x5A00 and st & 3 == 2
        rec_seen |= rec
        rec_done |= rec_seen and not rec
        vt = struct.unpack(">16I", c.read(SLOT_TRACK, 64))
        bs = [0.0] * 32
        bt = [0.0] * 32
        for v in range(16):
            buf = c.last_bufs[v] or [0.0] * 32
            if vt[v] == S:
                bs = [x + (y if y == y else 0.0) for x, y in zip(bs, buf)]
            elif vt[v] == T:
                bt = [x + (y if y == y else 0.0) for x, y in zip(bt, buf)]
        a_s += bs
        a_t += bt
        fr = c.last_frame
        trigw = struct.unpack(">4H", fr[34:42]) if fr else (0, 0, 0, 0)
        loud = {v: round(max(abs(y) for y in c.last_bufs[v] if y == y), 4) for v in range(16)
                if c.last_bufs[v] and max((abs(y) for y in c.last_bufs[v] if y == y), default=0) > 1e-4}
        if any(trigw) or (loud and n % 20 == 0):
            sounds.append({"n": n, "trig": trigw, "loud": loud, "vt": {v: vt[v] for v in loud}})
        log.append({"n": n, "step": c.read(F.TRACK_CUR + S, 1)[0], "fired": c.long(lay["rt_fired"]) != fired0,
                    "rec": rec})
        if n % 200 == 0:
            print(f"  [play] period {n}/{n_periods}, {time.perf_counter() - t0:.0f} s", flush=True)
    rep["numbers"]["sounds"] = sounds[:120]
    print("  sounds:", sounds[:30], flush=True)
    fired_at = next((e["n"] for e in log if e["fired"]), None)
    changes = [e["n"] for i, e in enumerate(log) if i and log[i - 1]["step"] != e["step"]]
    rep["numbers"]["play"] = {"fired_at": fired_at, "step_changes": changes[:8], "rec_seen": rec_seen,
                              "rec_done": rec_done}
    link("1. the take recorded in pass 1 (the trig fired, the DSP recorded and finished)",
         rtv == 2 and fired_at is not None and rec_seen and rec_done,
         f"rt_trig {rtv}, fired at period {fired_at}, recording seen {rec_seen}, done {rec_done}; step changes {changes[:6]}")
    # pass 2: from the second time step 1 comes round (two steps after PLAY), one pass long
    p2 = 2 * step
    xs, xt = a_s[p2:p2 + 2 * step], a_t[p2:p2 + 2 * step]
    pk_s = max((abs(v) for v in xs), default=0.0)
    pk_t = max((abs(v) for v in xt), default=0.0)
    if not link("2. both tracks sound in pass 2", pk_s > 1e-4 and pk_t > 1e-4,
                f"track {S} peak {pk_s:.5f}, track {T} peak {pk_t:.5f}"):
        return finish()
    lim = step // 3
    best = max(((corr_at(xs, xt, L), L) for L in range(-lim, lim + 1, 8)), default=(-2.0, 0))
    best = max(((corr_at(xs, xt, L), L) for L in range(best[1] - 8, best[1] + 9)), default=best)
    tick = step / 6
    rep["numbers"]["lag"] = {"samples": best[1], "ms": round(best[1] / 48, 2), "corr": round(best[0], 4),
                             "ticks": round(best[1] / tick, 3)}
    link("3. track 1's pass-2 audio is track 2's (correlation > 0.9 at the best lag)", best[0] > 0.9,
         f"corr {best[0]:.4f} at lag {best[1]}")
    link(f"4. the take plays on time: the best lag within {ON_TIME} samples (3 ms) either side",
         abs(best[1]) <= ON_TIME, f"lag {best[1]} samples ({best[1] / 48:.1f} ms, {best[1] / tick:.2f} ticks)")
    return finish()


if __name__ == "__main__":
    sys.exit(main())
