"""v0.76: the FLEX step lag through both processors (Dubmaster, 2026-11-25: a FLEX take played
back 41 ms late at 60 BPM, 25 ms at 90, 18 ms at 120 -- a sequencer tick, a sixth of a step).

The sequencer plays it, as a user's pattern does: a two-step pattern; track 1 is FLEX, recording
the input (SRC IN) with a one-shot recorder trig on step 1 and R.LEN 2 (the whole pattern), and
has a note of its own on step 1. Pass 1 records; pass 2 plays the take on the note. The input is
a known noise, a function of the sample's own number. What a user hears (Dubmaster's lag) is when
an event recorded in pass 1 sounds again against its own next pass: the playback's start less the
take's, less the pattern's length P. Both starts are measured, not inferred: the take's from its
own samples in the DSP's memory (the input it holds, found by correlation), the playback's from the
DSP's voice state (the block its position began). (2026-11-26: the track's audio itself is the
snapshot synth's filter and envelope over the take -- too far from the input to correlate, so it
is only checked to sound.)

  direct: track 1 FLEX (smp_machine_commit), the pattern's length 2, track 1's SRC IN and R.LEN
          (fx_set), the input (the noise)
  UI:     [TRK] + [TRIG 2], GRID RECORD [TRIG 1] (track 1's note; twice when step 1 has one, as
          the snapshot's pattern does, locks and all: taken away, then a plain one);
          FUNC + VOICE (the FLEX REC panel), [TRIG 1] (the one-shot recorder trig), NO; PLAY

Links: 0 track 1 has a plain note on step 1; 1 the take recorded in pass 1 (rt_fired, the DSP's
status recording then done); 2 track 1 sounds in pass 2; 3 the take is the input (correlation >
0.9) and its playback is seen; 4 the lag within 3 ms (144 samples) either side (v0.75: a tick).

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
from dnfw.waverider import dsp as WD                            # noqa: E402
_OSV = __import__("os").environ.get("DN2_OS", "1.11")

SLOT_TRACK = 0x80005308
T = 1                                   # the FLEX track (not 0: an idle voice reads track 0)
ON_TIME = 144                           # samples (3 ms) either side
TEMPO = 0x80005E60 + 2 * 108


def noise(n):
    """the input at sample n: a fixed pseudo-random value of n alone (an LCG of n, then mixed)"""
    v = (n * 2654435761 + 0x9E3779B9) & 0xFFFFFFFF
    v ^= v >> 15
    v = (v * 2246822519) & 0xFFFFFFFF
    v ^= v >> 13
    return 0.4 * ((v & 0xFFFF) / 32768.0 - 1.0)


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
        if c.halt:
            print(f"  FAIL  the run: halt {c.halt}", flush=True)
        if c.faults():                                           # (recorded, as emu_coupled_flex's)
            print(f"  note  faults {c.faults()[:3]}", flush=True)
        ok = not bad and not c.halt
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
    c.call(lay["fx_set"], T, 0, 0)                               # SRC: IN
    c.call(lay["fx_set"], T, 2, 2)                               # R.LEN: two steps
    c.input = lambda b: ([noise(32 * b + k) for k in range(32)],) * 2
    c.periods(4)
    def has_note(t, st):                                         # stock's own test (slice.c's PTRACK_NOTE)
        ptk = c.call(A(0x4003B2EA), c.call(A(0x4003EFA8), c.call(A(0x4018A97A))[0])[0], t)[0]
        return bool(c.call(A(0x4004F0F4), ptk, st)[0] & 0xFF)
    track(T)
    had = has_note(T, 0)
    tap(19)                                                      # GRID RECORD: a fresh note on step 1, no locks.
    if had:                                                      # The snapshot's pattern has one there, with the
        tap(25)                                                  # synth's locks (a FLEX note on it played
    tap(25)                                                      # silence, 2026-11-26): a tap takes it away, the
    tap(19)                                                      # next places a plain one
    c.periods(4)
    if not link("0. track 1 has a fresh note on step 1", has_note(T, 0),
                "UI: GRID RECORD [TRIG 1]" + (" twice (the snapshot's own taken away first)" if had else "")):
        return finish()
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
    a_t, blk, log, sounds, flex = [], [], [], [], []
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
        bt = [0.0] * 32
        for v in range(16):
            buf = c.last_bufs[v] or [0.0] * 32
            if vt[v] == T:
                bt = [x + (y if y == y else 0.0) for x, y in zip(bt, buf)]
        a_t += bt
        blk.append(c.blocks)
        fv = [(v, c.dsp_word(WD.SMP_STATE_DM + 128 * v), c.dsp_word(WD.SMP_STATE_DM + 128 * v + 8),
               c.dsp_word(WD.SMP_STATE_DM + 128 * v + 32), c.dsp_word(WD.SMP_STATE_DM + 128 * v + 36))
              for v in range(16) if vt[v] == T]
        flex.append((c.blocks, fv))
        fr = c.last_frame
        trigw = struct.unpack(">4H", fr[34:42]) if fr else (0, 0, 0, 0)
        if any(trigw) or n % 50 == 0:                            # the FLEX voices' sampler state (words 0..13)
            sounds.append({"n": n, "trig": trigw, "vt": vt[:6],
                           "smp": {v: [c.dsp_word(WD.SMP_STATE_DM + 128 * v + 4 * k) for k in range(14)]
                                   for v in range(16) if vt[v] == T}})
        log.append({"n": n, "step": c.read(F.TRACK_CUR + T, 1)[0], "fired": c.long(lay["rt_fired"]) != fired0,
                    "rec": rec})
        if n % 200 == 0:
            print(f"  [play] period {n}/{n_periods}, {time.perf_counter() - t0:.0f} s", flush=True)
    rep["numbers"]["trigs"] = sounds[:60]
    for e in sounds[:60]:
        print("  trig", e, flush=True)
    fired_at = next((e["n"] for e in log if e["fired"]), None)
    changes = [e["n"] for i, e in enumerate(log) if i and log[i - 1]["step"] != e["step"]]
    rep["numbers"]["play"] = {"fired_at": fired_at, "step_changes": changes[:8], "rec_seen": rec_seen,
                              "rec_done": rec_done}
    link("1. the take recorded in pass 1 (the trig fired, the DSP recorded and finished)",
         rtv == 2 and fired_at is not None and rec_seen and rec_done,
         f"rt_trig {rtv}, fired at period {fired_at}, recording seen {rec_seen}, done {rec_done}; step changes {changes[:6]}")
    # pass 2: from the second time step 1 comes round (two steps after PLAY), one pass long; each
    # period's samples carry its block's number (the input's sample numbers)
    p2 = 2 * step
    xt = a_t[p2:p2 + 2 * step]
    sn = [32 * blk[i // 32] + i % 32 for i in range(p2, min(p2 + 2 * step, len(a_t)))]
    pk_t = max((abs(v) for v in xt), default=0.0)
    if not link("2. track 1 sounds in pass 2", pk_t > 1e-4, f"track {T} peak {pk_t:.5f}"):
        return finish()
    P = 2 * step
    # the playback's start, from the DSP's own state: the first block a voice of track 1 plays the
    # take (on, its base) after pass 1; its position then is the samples it has played
    base = frames = None
    play_start = None
    for k, (b, fv) in enumerate(flex):
        if 32 * k < p2 - step // 2:
            continue
        for v, on, pos, bs, fr in fv:
            if on & 1 and pos and play_start is None:
                play_start, base, frames = 32 * (b + 1) - pos, bs, fr   # block b: samples 32b..32b+31
    # the take's start, from its own samples: the take (int16, two to a DSP word) against the input
    take = []
    if base is not None:
        for k in range(min(frames, 6 * 4096) // 2):
            w = c.dsp_word(base + 4 * k)
            for h in (w & 0xFFFF, w >> 16):
                take.append((h - 65536 if h & 0x8000 else h) / 32768.0)
    first_blk = blk[0] - 1 if blk else 0
    rec_lo = 32 * first_blk                                      # PLAY's block: the take starts after it

    def tcorr(start):                                            # the take against the input from START
        ref = [noise(start + i) for i in range(len(take))]
        ea = math.sqrt(sum(v * v for v in take)) or 1e-30
        eb = math.sqrt(sum(v * v for v in ref)) or 1e-30
        return sum(p_ * q for p_, q in zip(take, ref)) / (ea * eb)
    best = (-2.0, None)
    if take:
        cands = range(rec_lo - 64, rec_lo + 2 * step, 32)
        best = max((tcorr(st), st) for st in cands)
        best = max(((tcorr(st), st) for st in range(best[1] - 32, best[1] + 33)), default=best)
    rec_start = best[1]
    rep["numbers"]["take"] = {"base": base, "frames": frames, "read": len(take), "corr": round(best[0], 4),
                              "rec_start": rec_start, "play_start": play_start, "play_block": first_blk}
    if not link("3. the take is the input (correlation > 0.9 at its start), its playback seen",
                best[0] > 0.9 and play_start is not None,
                f"take corr {best[0]:.4f} from sample {rec_start}; playback from sample {play_start}"):
        return finish()
    lag = play_start - rec_start - P                             # what a user hears: a source event reappears
    tick = step / 6                                              # lag samples after its own next pass
    rep["numbers"]["lag"] = {"samples": lag, "ms": round(lag / 48, 2), "ticks": round(lag / tick, 3),
                             "P": P, "peak": round(pk_t, 5)}
    link(f"4. the take plays on time: play's start less the take's, less the pattern, within {ON_TIME} samples (3 ms)",
         abs(lag) <= ON_TIME, f"lag {lag} samples ({lag / 48:.1f} ms, {lag / tick:.2f} ticks): play from {play_start}, "
         f"take from {rec_start}, pattern {P}")
    return finish()


if __name__ == "__main__":
    sys.exit(main())
