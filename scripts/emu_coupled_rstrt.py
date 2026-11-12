"""v0.50 (impbox, 2026-11-10: "R.LEN 64 with R.STRT on PLAY: the take does not stop after 64
steps"): the RECORDER armed on R.STRT PLAY with an R.LEN, through both processors (emu_coupled.py).

  direct: track 0 ONESHOT (smp_machine_commit), an empty pool known to the ColdFire, the
          RECORDER's SRC IN, R.LEN 1 step, R.STRT PLAY (rec_src, rec_rlen, rec_rstrt)
  UI:     FUNC + VOICE (the RECORDER), knob H turned right (ARM, rec_arm_turn), PLAY
  DSP:    a note on track 0 from block NOTE_AT on (TRIG_WORD's bit, as a playing trig sets it):
          R.STRT PLAY starts the take on the first note any track plays
  IN:     a chirp at 0.25 full scale

Measured 2026-11-12 on v0.50's first build: R.LEN 1 at 81 BPM ended at 8,896 frames (8,888 asked:
the block it ends in), and did not start again: impbox's report did not reproduce at R.LEN 1.

Links: 1 the RECORDER up, 2 armed (status 1), 3 the take starts on a note (status 2), 4 it
ends (status 3 or 0) and its frames are R.LEN's (one step at the frame's tempo, within one
block), 5 it does not start again: 120 periods after its end, still not recording.

Usage: emu_coupled_rstrt.py --build out/v050.syx [--rlen N] [--json OUT]"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from emu_coupled import Coupled                                   # noqa: E402
from emu_coupled_recplay import chirp                            # noqa: E402

KIT, STRIDE, ONESHOT = 0x800052A0, 1163, 8
CTL_FRAME, TEMPO_WORD = 0x80005E60, 108
NOTE_AT = 40                                                      # periods after ARM


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--stock", default=str(HERE.parent.parent / "Digitone_II_OS1.11.syx"))
    p.add_argument("--snapshot", default=str(HERE.parent.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"))
    p.add_argument("--rlen", type=int, default=1)
    p.add_argument("--no-play", action="store_true", help="arm and note without pressing PLAY")
    p.add_argument("--json", default=None)
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    from dnfw.perc import program as PP                          # noqa: PLC0415
    from dnfw.sampler import machines as SM                     # noqa: PLC0415
    c = Coupled(a.build, a.snapshot, a.stock, verbose=True)
    rep = {"links": {}, "numbers": {}, "rlen": a.rlen}
    c.watchdog()
    fail = []

    def link(name, ok, detail=""):
        rep["links"][name] = {"ok": bool(ok), "detail": detail}
        print(("  ok    " if ok else "  FAIL  ") + name + (f" -- {detail}" if detail else ""), flush=True)
        if not ok:
            fail.append(name)
        return ok

    def done():
        rep["halt"] = c.halt
        if a.json:
            pathlib.Path(a.json).write_text(json.dumps(rep, indent=1, default=str))
        ok = not fail and not c.halt
        print(("PASS" if ok else "FAIL") + (f": the first broken link: {fail[0]}" if fail else "")
              + (f" (halt: {c.halt})" if c.halt else ""), flush=True)
        return 0 if ok else 1

    key = lambda code: divmod(code - 1, 8)                       # noqa: E731

    def held(code, on):
        f = c.panel.panelin.press if on else c.panel.panelin.release
        c.machine.pc = f(c.machine.m, c.panel.profile, *key(code))
        c.periods(3)

    owner = c.call(0x4018A97A)[0]
    c.call(lay["smp_machine_commit"], owner + 0xF4, 0, ONESHOT, 1, 1)
    c.poke(SM.MIRROR + 8, b"\x00" * 16 * SM.POOL_SLOTS)
    c.put32(lay["smp_dir_ok"], 1)
    c.input = chirp
    c.periods(4)
    held(17, True); held(49, True); held(49, False); held(17, False)
    c.put32(lay["rec_src"], 0)
    c.put32(lay["rec_rlen"], a.rlen)
    c.put32(lay["rec_rstrt"], 1)
    if not link("1. the RECORDER is up", c.long(lay["rec_overlay"]) != 0, f"overlay {c.long(lay['rec_overlay'])}"):
        return done()

    note = {"on": False}

    def at_dispatch(r, cc):
        if note["on"]:
            w = cc.M.m2.word(r.state, PP.TRIG_WORD) or 0
            cc.M.m2.poke(r.state, PP.TRIG_WORD, w | 1 << 16)
    c.taps[c.M.m3.DISPATCH] = at_dispatch

    c.machine.pc = c.panel.panelin.encoder(c.machine.m, c.panel.profile, 7, 1)     # H right: ARM
    c.periods(6)
    st = c.last_status[0]
    if not link("2. armed (status 1)", st & 0xFF00 == 0x5A00 and st & 3 == 1, f"status {c.last_status[:4]}"):
        return done()
    if not a.no_play:
        c.panel.tap(key(20), after=1_000_000)                     # PLAY
    bpm120 = int.from_bytes(c.read(CTL_FRAME + 2 * TEMPO_WORD, 2), "big") or 14400
    want = a.rlen * (86400000 // bpm120)
    rep["numbers"]["tempo"] = {"bpm120": bpm120, "want_frames": want}
    started = ended = None
    restarted = None
    seen = []
    t0 = shown = time.perf_counter()
    limit = NOTE_AT + want // 32 + 200
    for n in range(limit):
        if n == NOTE_AT:
            note["on"] = True
        if not c.period():
            break
        st = c.last_status
        s = st[0] & 3 if st[0] & 0xFF00 == 0x5A00 else -1
        seen.append(s)
        if started is None and s == 2:
            started = n
        elif started is not None and ended is None and s != 2:
            ended = n
            rep["numbers"]["frames_at_end"] = st[2] << 6
        elif ended is not None and restarted is None and s in (1, 2):
            restarted = n
        if ended is not None and n - ended >= 120:
            break
        now = time.perf_counter()
        if now - shown >= 60:
            shown = now
            print(f"  [rstrt] period {n + 1}/{limit}, {now - t0:.0f} s, status {st[:4]}, started {started}, "
                  f"ended {ended}", flush=True)
    rep["numbers"]["periods"] = {"started": started, "ended": ended, "restarted": restarted,
                                 "statuses": "".join(str(x) if x >= 0 else "." for x in seen)}
    # (the snapshot's pattern plays a note as soon as PLAY starts it: the take starts on that,
    # before ours at NOTE_AT; measured 2026-11-12, period 1)
    if not link("3. the take starts on a note after PLAY", started is not None,
                f"recording from period {started} (ours at {NOTE_AT})"):
        return done()
    got = rep["numbers"].get("frames_at_end")
    if not link("4. it ends at R.LEN", ended is not None and got is not None and abs(got - want) <= 64,
                f"ended after {ended} periods, {got} frames recorded; R.LEN {a.rlen} = {want} frames at "
                f"{bpm120 / 120:.1f} BPM"):
        return done()
    link("5. it does not start again", restarted is None, f"recording again at period {restarted}")
    return done()


if __name__ == "__main__":
    raise SystemExit(main())
