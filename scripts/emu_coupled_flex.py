"""v0.49 FLEX through both processors (emu_coupled.py): a one-shot recorder trig on step 1, the
DSP's take into the FLEX buffer, and a note on the FLEX track playing it (docs/flex-design.md).

Category 1: the modified ColdFire and SHARC code together. Setup marked direct is written by the
harness; everything else is the panel's keys and the firmware's own paths (the sequencer's timer
ISR at the tempo, rt_frame in the audio ISR, the link, the DSP's recorder and voices).

  direct: track 1 FLEX (smp_machine_commit, the UI's commit path), an empty pool known to the
          ColdFire, the pattern 4 steps, R.LEN 1 step (its sound slot 40), SRC IN (slot 38: 0)
  UI:     [TRK] + [TRIG 2] (track 1), FUNC + VOICE (the FLEX REC panel), [TRIG 1] (a one-shot
          recorder trig on step 1: v0.49's default), NO (closed), PLAY; then KEYBOARD and
          [TRIG 9] held (a note) once the take is in
  IN:     a chirp at 0.25 full scale from block 0

Links, each reported: 0 FLEX on track 1; 1a the panel up; 1b the one-shot in the lock store (2);
2 the step fired it (rt_fired); 3 the DSP recorded (status recording, then done); 4a the buffer
directory's entry for buffer 1 (address, frames); 4b the take is the input (correlation); 4c the
one-shot spent (3); 5 the frame selects the buffer on track 1's voice (SAMP 129); 6 the DSP renders
it (the voice's buffer read right after the voices render, before the stock chain); 7 the render
is the take (correlation). Negative controls (--break): notrig (no [TRIG 1]: link 1b and 2 fail),
nosamp (track 1's voices' SAMP zeroed in the frame: link 5 and 6 fail), wrongbuf (the SAMP word
one buffer on: link 5 and 7 fail).

Usage: emu_coupled_flex.py --build out/v049.syx [--break notrig|nosamp|wrongbuf] [--json OUT]"""

from __future__ import annotations

import argparse
import json
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
FLEX = 17
T = 1                                    # the FLEX track (not 0: the voice table reads 0 for an idle voice)
SLOT_RLEN, SLOT_SAMP, SLOT_SRC = 40, 43, 38
SLOT_TRACK = 0x80005308
KB_ON = 0x42431A9C                       # KEYBOARD's state (1 on; measured on stock, 2026-11-10)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--stock", default=str(HERE.parent.parent / "Digitone_II_OS1.11.syx"))
    p.add_argument("--snapshot", default=str(HERE.parent.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"))
    p.add_argument("--break", dest="brk", default=None, choices=("notrig", "nosamp", "wrongbuf"))
    p.add_argument("--json", default=None)
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    from dnfw.sampler import machines as SM                     # noqa: PLC0415
    from dnfw.waverider import dsp as D                         # noqa: PLC0415
    c = Coupled(a.build, a.snapshot, a.stock, verbose=True)
    c.watchdog()
    rep = {"setup": [], "links": {}, "numbers": {}, "break": a.brk}

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

    def held(code, on, n=3):
        c.machine.pc = (P.press if on else P.release)(c.machine.m, c.panel.profile, *key(code))
        c.periods(n)

    def tap(code):
        held(code, True)
        held(code, False)
    kit = c.long(KIT)
    snd = kit + 52 + STRIDE * T
    owner = c.call(0x4018A97A)[0]
    c.call(lay["smp_machine_commit"], owner + 0xF4, T, FLEX, 1, 1)
    rep["setup"].append(("track 1 FLEX", "direct: smp_machine_commit (the UI's commit path)"))
    c.poke(SM.MIRROR + 8, b"\x00" * 16 * SM.POOL_SLOTS)
    c.put32(lay["smp_dir_ok"], 1)
    rep["setup"].append(("an empty pool, known", "direct"))
    pat = c.long(SEQ_PATTERN)
    c.poke(pat + PAT_LENGTH, struct.pack(">H", 4))
    c.poke(snd + 0x14 + 2 * SLOT_RLEN, struct.pack(">H", 1 << 8))
    c.poke(snd + 0x14 + 2 * SLOT_SRC, struct.pack(">H", 0))
    rep["setup"].append(("pattern 4 steps, R.LEN 1, SRC IN", "direct: written"))
    c.input = chirp
    c.periods(4, label="settle")
    if not link("0. track 1 is FLEX", c.read(snd + 0xDE, 1)[0] == FLEX, f"type {c.read(snd + 0xDE, 1)[0]}"):
        return finish()
    held(16, True)
    tap(24 + T + 1)                                              # [TRK] + [TRIG 2]: track 1
    held(16, False)
    c.periods(4)
    rep["setup"].append(("track 1 active", "UI: [TRK] + [TRIG 2]"))
    held(17, True); held(49, True); held(49, False); held(17, False)
    rep["setup"].append(("the FLEX REC panel", "UI: FUNC + VOICE"))
    link("1a. the FLEX REC panel is up", c.call(lay["bn_active"])[0] & 0xFF, f"bn_active {c.call(lay['bn_active'])[0]}")
    if a.brk != "notrig":
        tap(25)                                                  # [TRIG 1]
        rep["setup"].append(("a one-shot recorder trig on step 1", "UI: [TRIG 1]"))
    table = pat + PAT_LOCK_TABLE
    tv = c.call(lay["rt_trig_get"], table, T, 0)[0] & 0xFFFF
    link("1b. [TRIG 1] put a one-shot recorder trig on step 1 (the lock store: 2)", tv == 2, f"rt_trig_get {tv}")
    tap(12)                                                      # NO: the panel closed
    fired0 = c.long(lay["rt_fired"])
    tap(20)                                                      # PLAY
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
            print(f"  [take] period {n + 1}/320, {(n + 1) / 1.5:.0f} ms of audio, {now - t0:.0f} s, step "
                  f"{c.read(TRACK_CUR + T, 1)[0]}, fired {fired_at}, recording {rec_at}, status {c.last_status[:2]}", flush=True)
        if fired_at is None and n > 120:
            break
    rep["numbers"]["fire"] = {"fired_at": fired_at, "rt_fired": c.long(lay["rt_fired"]), "rec_at": rec_at,
                              "end_at": end_at, "status": c.last_status[:4], "refused": c.long(lay["rt_refused"]),
                              "why": c.long(lay["rt_why"])}
    if not link("2. the step fired the trig (rt_fired)", fired_at is not None,
                f"after {fired_at} periods; refused {c.long(lay['rt_refused'])} (why {c.long(lay['rt_why'])})"):
        return finish()
    if not link("3. the DSP recorded (status recording, then done)", rec_at is not None and end_at is not None,
                f"recording from period {rec_at} to {end_at}; status {c.last_status[:4]}"):
        return finish()
    c.periods(4)
    ents = [[c.dsp_word(D.SMP_POOL_DDR + SM.BUF_DIR + 12 * k + 4 * j) for j in range(3)] for k in range(SM.BUF_HALVES)]
    e0 = ents[0]
    rep["numbers"]["buffers"] = {"entries": {k: e for k, e in enumerate(ents) if e[0] or e[1]}}
    if not link("4a. buffer 1's directory entry holds the take (address, frames)", e0[0] and e0[1],
                f"entry {e0}; others {[(k, e) for k, e in enumerate(ents) if k and (e[0] or e[1])]}"):
        return finish()
    addr, frames = e0[0], e0[1]

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
    rep["numbers"]["take_vs_input"] = {"frames": frames, "lag": lag, "corr": corr}
    link("4b. the take is the input", corr > 0.99, f"{frames} frames, corr {corr:.4f} at input sample {lag}")
    tv = c.call(lay["rt_trig_get"], table, T, 0)[0] & 0xFFFF
    link("4c. the one-shot is spent (3)", tv == 3, f"rt_trig_get {tv}")

    # the note: KEYBOARD on (a tap toggles it), [TRIG 9] held; the voice's buffer read right
    # after our voices render (ping.asm's entry), before the stock chain clears it
    mid = {}

    def at_mid(r, cc):
        mid["bufs"] = [cc.M.m2.floats(r.state, cc.M.m2.word(r.state, cc.M.V.TRACK_BUFFERS + 4 * v), 32) for v in range(16)]
    c.taps[c.M.dsp.PING_SW] = at_mid
    if a.brk in ("nosamp", "wrongbuf"):
        def fil(fr):
            b = bytearray(fr)
            vt = struct.unpack(">16I", c.read(SLOT_TRACK, 64))
            for v in range(16):
                if vt[v] != T:
                    continue
                o = 168 + 2 * SLOT_SAMP + 146 * v
                w = struct.unpack(">H", bytes(b[o:o + 2]))[0]
                b[o:o + 2] = struct.pack(">H", 0 if a.brk == "nosamp" else (w + 0x200) & 0xFFFF)
            return bytes(b)
        c.frame_filter = fil
    if not c.read(KB_ON, 1)[0]:
        tap(18)
    rep["setup"].append(("a note", "UI: KEYBOARD, [TRIG 9] held"))
    rep["numbers"]["keyboard"] = c.read(KB_ON, 1)[0]
    c.machine.pc = P.press(c.machine.m, c.panel.profile, *key(33))
    fw, outs = [], []
    c.phase = "the note"
    for n in range(60):
        if not c.period():
            break
        vt = struct.unpack(">16I", c.read(SLOT_TRACK, 64))
        vs = [v for v in range(16) if vt[v] == T]
        for v in vs:
            fw.append(struct.unpack(">H", c.read(CF_FRAME + 168 + 2 * SLOT_SAMP + 146 * v, 2))[0])
        if vs and "bufs" in mid:
            outs.append(mid["bufs"][vs[0]])
    c.machine.pc = P.release(c.machine.m, c.panel.profile, *key(33))
    c.periods(2)
    out = [x for blk in outs for x in blk]
    peak = max((abs(x) for x in out), default=0.0)
    want = SM.BUF_SAMP0 << 8
    rep["numbers"]["note"] = {"frame_samp": sorted(set(fw)), "peak": peak, "want_samp": want}
    link("5. the frame selects buffer 1 on track 1's voice (SAMP 129)", want in fw,
         f"SAMP words {sorted(hex(x) for x in set(fw))}, want {want:#x}")
    link("6. the DSP renders the FLEX voice", peak > 0.001, f"peak {peak:.4f} over {len(outs)} blocks")
    if peak > 0.001:
        start = next(i for i, x in enumerate(out) if abs(x) > 1e-4)
        seg = out[start + 256:start + 768]
        lag, corr = best_match(seg, take, range(0, max(1, frames - 512)))
        rep["numbers"]["audio"] = {"lag": lag, "corr": corr}
        link("7. the render is the take", corr is not None and corr > 0.95, f"corr {corr:.4f} at take frame {lag}")
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
