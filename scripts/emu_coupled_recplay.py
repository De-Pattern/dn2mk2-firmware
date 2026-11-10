"""v0.48: a recording and its playback through both processors (emu_coupled.py), with STRT fine.

The chain, each link the real code's, the ColdFire and the DSP block by block:

  1. The RECORDER opened on track 0 (ONESHOT through MACHINE SEL's commit as the UI makes it),
     SRC IN, R.LEN 1 step; YES records (the panel key). The command goes out in the ColdFire's
     packets to the DSP's link (the real TDM pages).
  2. The DSP records IN: a known chirp, 0.25 full scale, from block 0 on.
  3. The take: the DSP's directory entry for the slot (address, frames) and its frames,
     matched against the input (normalised correlation at the best latency).
  4. The ColdFire's flow: SAVING, TRIM, FILE NAME, ASSIGN ([TRIG 1]: track 0 plays the slot),
     every step the panel's.
  5. STRT turned on the SYN page (encoder E, a fine value: fmt.c smp_fine).
  6. A note (KEYBOARD, [TRIG 9] held): the ColdFire's frame builder puts the slot and STRT in
     the frame; the DSP renders track 0.
  7. The rendered audio against the recorded frames from STRT's place: the best lag must be
     within 2 frames of floor(frames x STRT / 120.00) and the correlation above 0.98.

--break NAME breaks one link on purpose (a negative control; the run must FAIL, saying where):
  noqueue    the ColdFire's packets are dropped from the YES on (the command never arrives)
  nodir      the DSP's directory entry for the take is wiped once the take is over
  nosel      the frame's SAMP word for track 0 is 0 (no sample selected)
  wrongslot  the frame's SAMP word points one slot further (the DSP plays another slot)

Usage: emu_coupled_recplay.py --build out/v048.syx [--break NAME] [--json OUT]"""

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

KIT, STRIDE = 0x800052A0, 1163
ONESHOT = 8
SLOT_SAMP, SLOT_STRT = 43, 26
AMP = 0.25


def chirp(block):
    """a linear chirp, 200 Hz .. 4 kHz over a second, then again: no two places alike"""
    out = []
    for k in range(32):
        n = 32 * block + k
        t = (n % 48000) / 48000.0
        out.append(AMP * math.sin(2 * math.pi * (200 * t + 0.5 * 3800 * t * t)))
    return out, out


def best_match(x, y, lags):
    """-> (lag, corr): the lag L in LAGS maximising the normalised correlation of x[i] and y[i + L]"""
    best = (None, -2.0)
    n = len(x)
    ex = math.sqrt(sum(v * v for v in x)) or 1e-30
    for L in lags:
        if L < 0 or L + n > len(y):
            continue
        seg = y[L:L + n]
        ey = math.sqrt(sum(v * v for v in seg)) or 1e-30
        c = sum(a * b for a, b in zip(x, seg)) / (ex * ey)
        if c > best[1]:
            best = (L, c)
    return best


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--stock", default=str(HERE.parent.parent / "Digitone_II_OS1.11.syx"))
    p.add_argument("--snapshot", default=str(HERE.parent.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"))
    p.add_argument("--break", dest="brk", default=None, choices=("noqueue", "nodir", "nosel", "wrongslot"))
    p.add_argument("--strt-counts", type=int, default=24)
    p.add_argument("--json", default=None)
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    from dnfw.sampler import machines as SM                     # noqa: PLC0415
    from dnfw.waverider import dsp as D                         # noqa: PLC0415
    c = Coupled(a.build, a.snapshot, a.stock, verbose=True)
    setup = []
    rep = {"break": a.brk, "steps": {}, "numbers": {}, "setup": setup}
    c.watchdog()
    fail = []

    def step(name, ok, detail=""):
        rep["steps"][name] = {"ok": bool(ok), "detail": detail}
        print(("  ok    " if ok else "  FAIL  ") + name + (f" -- {detail}" if detail else ""), flush=True)
        if not ok:
            fail.append(name)
        return ok

    def done():
        rep["halt"], rep["faults"] = c.halt, len(c.faults())
        rep["ok"] = not fail and not c.halt and not c.faults()
        if a.json:
            pathlib.Path(a.json).write_text(json.dumps(rep, indent=1, default=str))
        if c.halt or c.faults():
            print(f"  FAIL  the run: halt {c.halt}, faults {c.faults()[:3]}")
        print(("PASS" if rep["ok"] else "FAIL") + (f": the first broken link: {fail[0]}" if fail else
              f": {len(rep['steps'])} links, recording to playback"), flush=True)
        return 0 if rep["ok"] else 1

    names = {}
    for code in range(1, 64):
        n = c.panel.panelin.control_name(c.machine.m, c.panel.profile, code)
        if n:
            names[n.upper()] = code
    key = lambda code: divmod(code - 1, 8)                       # noqa: E731
    rep["keys"] = names

    def tap(code, after=2_000_000):
        c.panel.tap(key(code), after=after)

    def hold_tap(held, code):
        c.machine.pc = c.panel.panelin.press(c.machine.m, c.panel.profile, *key(held))
        c.panel.settle(1_000_000)
        tap(code, after=1_000_000)
        c.machine.pc = c.panel.panelin.release(c.machine.m, c.panel.profile, *key(held))
        c.panel.settle(3_000_000)

    kit = c.long(KIT)
    snd = kit + 52 + STRIDE * 0

    def word(slot):
        return struct.unpack(">H", c.read(snd + 0x14 + 2 * slot, 2))[0]

    owner = c.call(0x4018A97A)[0]
    c.call(lay["smp_machine_commit"], owner + 0xF4, 0, ONESHOT, 1, 1)
    setup.append(("track 0 ONESHOT", "direct call of smp_machine_commit (the UI's commit path, not MACHINE SEL's keys)"))
    c.poke(SM.MIRROR + 8, b"\x00" * 16 * SM.POOL_SLOTS)          # an empty pool: room to record
    c.put32(lay["smp_dir_ok"], 1)
    setup.append(("an empty pool, its directory known", "direct: the ColdFire's mirror emptied, smp_dir_ok set"))
    c.input = chirp
    c.periods(4)
    if not step("0. track 0 on ONESHOT", c.read(snd + 0xDE, 1)[0] == ONESHOT, f"type {c.read(snd + 0xDE, 1)[0]}"):
        return done()

    # 1. the RECORDER: FUNC held, the VOICE key (panel code 49, as the gate's recorder step
    # presses it; the firmware's name table calls 49 LEVEL) pressed and let go, FUNC let go.
    # It opens on VOICE's release (measured), so FUNC is held through it
    def held(code, on):
        f = c.panel.panelin.press if on else c.panel.panelin.release
        c.machine.pc = f(c.machine.m, c.panel.profile, *key(code))
        c.periods(3)
    held(17, True); held(49, True); held(49, False); held(17, False)
    setup.append(("the RECORDER opened", "UI: FUNC + VOICE (panel keys, audio periods between)"))
    c.put32(lay["rec_src"], 0)                                   # IN (knob A's value; set, not turned)
    c.put32(lay["rec_rlen"], 1)                                  # R.LEN 1 step (knob G's)
    setup.append(("SRC IN, R.LEN 1 step", "direct: the recorder's variables written"))
    if "rec_rstrt" in lay:
        c.put32(lay["rec_rstrt"], 0)
        setup.append(("R.STRT", "direct"))
    if not step("1. the RECORDER is up", c.long(lay["rec_overlay"]) != 0, f"overlay {c.long(lay['rec_overlay'])}"):
        return done()
    cmds0 = c.long(lay["smp_cmds"])
    if a.brk == "noqueue":
        c.packet_filter = lambda words: None
    tap(names.get("YES", 10), after=1_000_000)
    setup.append(("YES records", "UI: the YES key"))
    rec_at, end_at = None, None
    c.phase = "recording"
    t0 = shown = __import__("time").perf_counter()
    for n in range(400):
        if not c.period():
            break
        now = __import__("time").perf_counter()
        if now - shown >= 60:
            shown = now
            print(f"  [recording] period {n + 1} (at most 400), {(n + 1) / 1.5:.0f} ms of audio, {now - t0:.0f} s, "
                  f"status {c.last_status[:2]}, started {rec_at}", flush=True)
        st = c.last_status[0]
        if st & 0xFF00 == 0x5A00 and st & 3 == 2 and rec_at is None:
            rec_at = n
        if rec_at is not None and st & 0xFF00 == 0x5A00 and st & 3 != 2:
            end_at = n
            break
    rep["numbers"]["record"] = {"cmds": [cmds0, c.long(lay["smp_cmds"])], "started": rec_at, "ended": end_at,
                                "status": c.last_status[:4], "delivered": c.delivered}
    if not step("2. the DSP records (its status: recording, then done)", rec_at is not None and end_at is not None,
                f"started after {rec_at} periods, ended after {end_at}; status {c.last_status[:4]}; "
                f"ColdFire commands {cmds0} -> {c.long(lay['smp_cmds'])}, packets delivered {c.delivered}"):
        return done()
    c.packet_filter = None

    # 3. the take, in the DSP's directory and frames
    slot = c.long(lay["rec_saved_slot"]) if "rec_saved_slot" in lay else None
    c.periods(4)
    dirs = [[c.dsp_word(D.SMP_POOL_DDR + 8 + 16 * k + 4 * j) for j in range(4)] for k in range(SM.POOL_SLOTS)]
    taken = [k for k, e in enumerate(dirs) if e[0] and e[1]]
    if a.brk == "nodir":
        for k in taken:
            for j in range(4):
                c.dsp_poke(D.SMP_POOL_DDR + 8 + 16 * k + 4 * j, 0)
        dirs = [[c.dsp_word(D.SMP_POOL_DDR + 8 + 16 * k + 4 * j) for j in range(4)] for k in range(SM.POOL_SLOTS)]
        taken = [k for k, e in enumerate(dirs) if e[0] and e[1]]
    dest = c.long(lay["rec_dest"])                               # the slot the RECORDER showed (next empty)
    in_area = [j for j in taken if dirs[j][0] >= D.SMP_POOL_DDR + SM.REC_OFFSET]
    if dest not in taken and len(in_area) == 1:                  # (rec_dest moves on to the next empty one)
        dest = in_area[0]
    rep["numbers"]["take"] = {"slots": taken, "entries": {k: dirs[k] for k in taken}, "rec_saved_slot": slot,
                              "rec_dest": dest}
    # the pool's other entries are the DSP's built-in test sounds (in the pool's first MB);
    # the take is the RECORDER's slot, in the recordings' area
    if not step("3a. the DSP's directory holds the take in the RECORDER's slot (address, frames)",
                0 <= dest < SM.POOL_SLOTS and dest in taken and dirs[dest][0] >= D.SMP_POOL_DDR + SM.REC_OFFSET,
                f"rec_dest {dest}; entries with frames {[(k, hex(dirs[k][0]), dirs[k][1]) for k in taken]}"):
        return done()
    k = dest
    addr, frames, rate, fmt = dirs[k]
    bpm120 = struct.unpack(">H", c.read(CF_FRAME + 2 * 108, 2))[0]
    want = 86400000 // bpm120
    step("3b. its length is R.LEN's (1 step at the tempo)", abs(frames - want) <= 64,
         f"{frames} frames; R.LEN 1 step at {bpm120 / 120:.1f} BPM: {want}")

    def frames_at(off, n):
        out = []
        for i in range(off, off + n, 2):
            w = c.dsp_word(addr + 2 * i)                         # int16 frames, two a word
            for h in (w & 0xFFFF, w >> 16):
                out.append(((h ^ 0x8000) - 0x8000) / 32768.0)
        return out[:n]
    rec = frames_at(0, min(frames, 4096))
    src = []
    for b in range(400):
        src += chirp(b)[0]
    lag, corr = best_match(rec[1024:3072], src, range(0, 400 * 32 - 2048))
    rep["numbers"]["take_vs_input"] = {"lag": lag, "corr": corr, "fmt": fmt}
    step("3c. the take's frames are the input (normalised correlation > 0.99)", corr > 0.99,
         f"corr {corr:.4f} at input sample {lag} (format {fmt})")

    # 4. the ColdFire's flow to ASSIGN, the panel's keys
    phases = [c.long(lay["rec_phase"])]
    for _ in range(6):
        if c.long(lay["rec_phase"]) == 1:                        # TRIM: YES on
            break
        c.periods(10)
        phases.append(c.long(lay["rec_phase"]))
    yes = names.get("YES", 10)
    setup.append(("TRIM, FILE NAME, ASSIGN", "UI: YES, YES, [TRIG 1] (panel keys)"))
    tap(yes, after=5_000_000)                                    # TRIM -> FILE NAME
    phases.append(c.long(lay["rec_phase"]))
    tap(yes, after=5_000_000)                                    # FILE NAME -> ASSIGN
    phases.append(c.long(lay["rec_phase"]))
    tap(25, after=10_000_000)                                    # [TRIG 1]: track 0 plays it
    phases.append(c.long(lay["rec_phase"]))
    c.periods(4)
    samp = word(SLOT_SAMP) >> 8
    rep["numbers"]["flow"] = {"phases": phases, "samp": samp}
    if not step("4. SAVING, TRIM, FILE NAME, ASSIGN: track 0's SAMP is the take", samp == k + 1,
                f"phases {phases}, SAMP {samp}, the take's slot {k} (SAMP {k + 1})"):
        return done()

    setup.append(("STRT", "UI: SRC page key, encoder E turned"))
    # 5. STRT, fine, on the SYN page's encoder E
    c.panel.tap((0, 1))
    for _ in range(a.strt_counts):
        c.machine.pc = c.panel.panelin.encoder(c.machine.m, c.panel.profile, 4, 1)
        c.panel.settle(1_000_000)
    c.panel.settle(5_000_000)
    strt = word(SLOT_STRT)
    if not step("5. STRT moved by a fraction", strt > 0 and strt % 256 != 0, f"STRT {strt:#06x} ({strt / 256:.2f})"):
        return done()

    # 6. the note, its frame, the DSP's render
    def fil(fr):
        b = bytearray(fr)
        vt = struct.unpack(">16I", c.read(0x80005308, 64))
        for vv in range(16):
            if vt[vv] != 0:
                continue
            o = 168 + 2 * SLOT_SAMP + 146 * vv
            if a.brk == "nosel":
                b[o:o + 2] = b"\x00\x00"
            elif a.brk == "wrongslot":
                w = struct.unpack(">H", bytes(b[o:o + 2]))[0]
                b[o:o + 2] = struct.pack(">H", (w + 0x100) & 0xFFFF)
        return bytes(b)
    if a.brk in ("nosel", "wrongslot"):
        c.frame_filter = fil
    setup.append(("the note", "UI: KEYBOARD, [TRIG 9] held"))
    kb, trig9 = names.get("KEYBOARD"), 33
    if kb:
        tap(kb)
    c.periods(2)
    c.machine.pc = c.panel.panelin.press(c.machine.m, c.panel.profile, *key(trig9))
    fw = []
    outs = [[] for _ in range(16)]
    voices = set()
    c.phase = "the note"
    for n in range(40):
        if not c.period():
            break
        # the frame's records are per VOICE; the ColdFire's slot -> track table (0x80005308,
        # the DSP's routing, link.c SLOT_TRACK) says which voices play track 0
        vt = struct.unpack(">16I", c.read(0x80005308, 64))
        for v in range(16):
            if vt[v] == 0:
                voices.add(v)
                fw.append((v, struct.unpack(">H", c.read(CF_FRAME + 168 + 2 * SLOT_SAMP + 146 * v, 2))[0]))
        for b in range(16):
            outs[b] += c.last_bufs[b]
    c.machine.pc = c.panel.panelin.release(c.machine.m, c.panel.profile, *key(trig9))
    c.periods(2)
    peaks = [max((abs(x) for x in o), default=0.0) for o in outs]
    bi = max(range(16), key=lambda b: peaks[b])
    out, peak = outs[bi], peaks[bi]
    rep["numbers"]["note"] = {"frame_samp": sorted(set(fw)), "voices_of_track0": sorted(voices),
                              "peaks": [round(x, 4) for x in peaks], "loudest_buffer": bi, "peak": peak,
                              "keyboard_key": kb}
    step("6a. the frame selects the take (its SAMP word, on a voice of track 0's)",
         any(w == (k + 1) << 8 for _, w in fw),
         f"track 0's voices {sorted(voices)}; their SAMP words {sorted(set(fw))}; want {(k + 1) << 8:#x}")
    if not step("6b. the DSP renders track 0", peak > 0.01, f"peak {peak:.4f}"):
        return done()

    # 7. the audio against the take from STRT's place
    lo = frames * strt // 0x7800
    start = next(i for i, x in enumerate(out) if abs(x) > 1e-4)
    seg = out[start + 256:start + 256 + 512]                     # past the first block's fade
    take = frames_at(0, frames)
    lag, corr = best_match(seg, take, range(max(0, lo - 64), min(frames - 512, lo + 1024)))
    expect = lo + 256                                            # the voice's position 256 frames in
    rep["numbers"]["audio"] = {"lo": lo, "start": start, "lag": lag, "corr": corr, "expect": expect}
    step("7. the audio is the take from STRT's place (best lag within 2 frames, corr > 0.98)",
         lag is not None and abs(lag - expect) <= 2 and corr > 0.98,
         f"STRT {strt / 256:.2f} of {frames} frames: lo {lo}; the render 256 frames in matches take frame "
         f"{lag} (want {expect}), corr {corr:.4f}")
    return done()


if __name__ == "__main__":
    raise SystemExit(main())
