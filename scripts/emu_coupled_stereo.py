"""Stereo, the field route on both processors (docs/stereo-assessment.md, "Field reports on
v0.54-t1"): what the gate never ran before v0.54-t1 went out, end to end.

  1. The power-on load (the power cycle): a stereo sample (format 2, L and R different waves) and a
     mono one on the emulated +Drive, as the import page leaves them. The ColdFire's own loader
     sends the image over the sample link to the real DSP; every word must arrive (the loader's
     own edits of the header aside).
  2. Track 1 ONESHOT on the stereo sample, track 2 a stock synth (the snapshot's). KEYBOARD notes
     ([TRIG 9] held): the synth, the stereo sample, the stereo sample again while it sounds (the
     retrigger), the synth again.
  3. After the pan stage (sw 0x1c9b33), track 1's voice's stereo buffer (what the main bus and the
     sends read): its L side is the sample's L, its R side the sample's R (correlation at the best
     lag), both sounding, and not each other (v0.54-t1: a gain ramp with no sound in it).
  4. The synth sounds on its first note (v0.54-t1: an FM Tone track needed 2-3 presses) and keeps
     sounds again after the stereo notes (v0.54-t1 after a power cycle: nothing on any track).
  5. The retrigger: it sounds, and no jump in track 1's stereo buffer, from sample to sample and across
     blocks, larger than the sample's own largest step plus a margin (v0.54-t1: a loud click).
  6. No halt, no fault, the DSP's status alive to the end.

A negative control: v0.54-t1's build (with its own layout) must fail it, at 3 at least.

Usage: emu_coupled_stereo.py --build BUILD.syx [--layout waverider_code.json] [--json OUT]"""

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
from emu_coupled_recplay import best_match                      # noqa: E402
_OSV = __import__("os").environ.get("DN2_OS", "1.11")

KIT, STRIDE = 0x800052A0, 1163
SEQ_PATTERN, TRACK_CUR = A(0x42C5A9A0), A(0x42C5A984)
PAT_LENGTH = 122196
SLOT_TRACK = 0x80005308
ONESHOT = 8
SLOT_SAMP = 43
T = 1                                   # the stereo track (not 0: an idle voice reads track 0)
KB_ON = A(0x42431A9C)                   # KEYBOARD's state (emu_coupled_flex)
BLK_READ, BLK_WRITE = A(0x4012C59A), A(0x4012C780)
BLK_READY, BLK_SECTORS = A(0x4461B68C), A(0x4461B6B0)
STORE_SECTOR = 0x600000
PAN_END = 0x1C9B33                      # the pan stage's end: each voice's stereo buffer written
STEREO_BUF = 0x257EE8                   # a voice's: L 32 floats, R 32 at +0x80, 0x100 a voice
N = 12000                               # the stereo sample's frames (250 ms: longer than a step)


def wave_l(k):                          # a 200 Hz saw, 0.5
    return 0.5 * ((k * 200 % 48000) / 24000.0 - 1.0)


def wave_r(k):                          # a 330 Hz sine, 0.4: not L's
    return 0.4 * math.sin(2 * math.pi * 330 * k / 48000.0)


def adler(b):
    a_, b_ = 1, 0
    for x in b:
        a_ = (a_ + x) & 0xFFFFFFFF
        b_ = (b_ + a_) & 0xFFFFFFFF
    return (b_ << 16 ^ a_) & 0xFFFFFFFF


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--stock", default=str(HERE.parent.parent / f"Digitone_II_OS{_OSV}.syx"))
    p.add_argument("--snapshot", default=str(HERE.parent.parent / f"digikit/out/snapshots/dn2-{_OSV}/ui800M-v014.snap"))
    p.add_argument("--json", default=None)
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    from unicorn import UC_HOOK_CODE                            # noqa: PLC0415
    from unicorn import m68k_const as K                         # noqa: PLC0415
    from dnfw.sampler import live as SL, machines as SM         # noqa: PLC0415
    from dnfw.waverider import dsp as WD                        # noqa: PLC0415
    c = Coupled(a.build, a.snapshot, a.stock, verbose=False)
    c.watchdog()
    rep = {"links": {}, "numbers": {}, "setup": []}
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
              ": the stereo field route on both processors"), flush=True)
        return 0 if ok else 1

    # 1. the +Drive with the image, the stock driver's two entries answered by the hook
    disk: dict[int, bytes] = {}

    def blk(uc, address, size, user):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        sector, n, buf = struct.unpack(">3I", bytes(uc.mem_read(sp + 4, 12)))
        if address == BLK_READ:
            uc.mem_write(buf, b"".join(disk.get(sector + k, bytes(512)) for k in range(n // 512)))
        else:
            d = bytes(uc.mem_read(buf, n))
            for k in range(n // 512):
                disk[sector + k] = d[512 * k:512 * k + 512]
    from unicorn import UC_PROT_ALL, UcError                    # noqa: PLC0415
    for page in range(SM.BANK_RAM & ~0xFFFFF, SM.BANK_RAM + SM.BANK_RAM_BYTES, 0x100000):
        try:                                                     # banks B..D's RAM (link.c, pools.c): real
            c.uc.mem_map(page, 0x100000, UC_PROT_ALL)            # RAM on the unit, unmapped by Coupled
        except UcError:
            pass
    for va in (BLK_READ, BLK_WRITE):
        c.machine.write(va, bytes.fromhex("70004e75"))
        c.uc.hook_add(UC_HOOK_CODE, blk, begin=va, end=va)
    c.machine.write(BLK_READY, struct.pack(">I", 1))
    c.machine.write(BLK_SECTORS, struct.pack(">I", 0x3A00000))
    st = [(wave_l(k), wave_r(k)) for k in range(N)]
    mono = [0.3 * ((k % 50) / 25 - 1) for k in range(700)]
    base = WD.SMP_POOL_DDR
    img = SL.pool_bytes([st, mono], base, [1.0, 1.0], [SM.FMT_I16S, SM.FMT_I16], ["WIDE", "TRI"])
    img = bytearray(img + bytes((-len(img)) % 512))
    hdr = bytes(img[:SM.DATA_OFFSET])
    magic, nb, ck = 0x444E3251, len(img), adler(hdr)
    disk[STORE_SECTOR] = struct.pack(">5I", magic, 2, nb, ck, (~magic ^ nb ^ ck) & 0xFFFFFFFF).ljust(512, b"\0")
    for k in range(len(img) // 512):
        disk[STORE_SECTOR + 1 + k] = bytes(img[512 * k:512 * k + 512])
    rep["setup"].append(("the +Drive: a stereo sample (slot 0, format 2, L a 200 Hz saw, R a 330 Hz sine, "
                         f"{N} frames) and a mono one (slot 1)", f"{len(img)} bytes"))
    periods = 0
    while periods < 2400:
        c.periods(10)
        periods += 10
        if c.long(lay["smp_lstate"]) == 4 or c.halt:
            break
        if periods % 200 == 0:
            print(f"  [load] period {periods}: state {c.long(lay['smp_lstate'])}, walk "
                  f"{c.long(lay['smp_walk'])}/{c.long(lay['smp_walk_total'])}, retries {c.long(lay['smp_retries'])}, "
                  f"{time.perf_counter() - t0:.0f} s", flush=True)
    loaded = c.long(lay["smp_lstate"]) == 4
    wrong = [k for k in range(len(img) // 4) if c.dsp_word(base + 4 * k) != struct.unpack_from("<I", img, 4 * k)[0]]
    frames_lo = struct.unpack_from("<I", img, 8)[0] - base       # slot 0's frames' place
    frames_wrong = [k for k in wrong if 4 * k >= frames_lo]
    rep["numbers"]["load"] = {"periods": periods, "retries": c.long(lay["smp_retries"]),
                              "words_differing": [(4 * k, hex(c.dsp_word(base + 4 * k)),
                                                   hex(struct.unpack_from("<I", img, 4 * k)[0])) for k in wrong[:12]],
                              "frames_differing": len(frames_wrong)}
    if not link("1. the power-on load: the image reached the DSP over the sample link, every frame's word",
                loaded and not frames_wrong, f"state {c.long(lay['smp_lstate'])} after {periods} periods; "
                f"{len(frames_wrong)} frame words differ ({len(wrong)} words in all, the header's own edits aside)"):
        return finish()
    fmt0 = c.call(lay["smp_slot_fmt"], 0)[0]
    link("1b. the ColdFire's slot 0 is stereo (format 2)", fmt0 == SM.FMT_I16S, f"smp_slot_fmt(0) {fmt0}")

    # 2. the tracks: T ONESHOT on slot 0 (not track 0: the voice table reads 0 for an idle voice),
    # a stock synth on another
    kit = c.long(KIT)
    types = [c.read(kit + 52 + STRIDE * t + 0xDE, 1)[0] for t in range(4)]
    rep["numbers"]["types_before"] = types
    owner = c.call(A(0x4018A97A))[0]
    c.call(lay["smp_machine_commit"], owner + 0xF4, T, ONESHOT, 1, 1)
    c.periods(4)
    if "smp_set_samp_word" in lay:
        rc = c.call(lay["smp_set_samp_word"], T, 1 << 8)[0]
    else:                                                        # an older build (the negative control's)
        c.poke(kit + 52 + STRIDE * T + 20 + 2 * SLOT_SAMP, struct.pack(">H", 1 << 8))
        rc = 0
    c.periods(4)
    synth = next((t for t in (2, 3, 0) if types[t] < 5), None)
    rep["setup"].append((f"track {T} ONESHOT on slot 0 (smp_set_samp_word {rc}); track {synth} the snapshot's "
                         f"synth (type {types[synth] if synth is not None else None})", "direct"))
    if not link(f"2a. track {T} is ONESHOT on slot 0, a stock synth on another track",
                c.read(kit + 52 + STRIDE * T + 0xDE, 1)[0] == ONESHOT and rc == 0 and synth is not None,
                f"types {[c.read(kit + 52 + STRIDE * t + 0xDE, 1)[0] for t in range(4)]}, set_samp {rc}"):
        return finish()
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
    if not c.read(KB_ON, 1)[0]:
        tap(18)                                                  # KEYBOARD
    rep["setup"].append(("KEYBOARD on; notes on [TRIG 9]", "UI"))

    # 3..5: notes, every block's stereo buffer of track T's voices and the synth's track buffer
    sb: list = []
    phase = {"now": "synth1"}

    def at_pan(r, cc):
        vt = struct.unpack(">16I", c.read(SLOT_TRACK, 64))
        vs = [v for v in range(16) if vt[v] == T]
        sb.append((phase["now"], {v: (cc.M.m2.floats(r.state, STEREO_BUF + 0x100 * v, 32),
                                      cc.M.m2.floats(r.state, STEREO_BUF + 0x100 * v + 0x80, 32)) for v in vs}))
    c.taps[PAN_END] = at_pan
    log = []

    def run(name, n, press=None):
        phase["now"] = name
        if press is not None:
            c.machine.pc = (P.press if press else P.release)(c.machine.m, c.panel.profile, *key(33))
        for _ in range(n):
            if not c.period():
                break
            syn = max((abs(x) for x in (c.last_bufs[synth] or []) if x == x), default=0.0)
            log.append({"phase": name, "synth": syn, "status": c.last_status[0]})
        print(f"  [{name}] {len(log)} periods, {time.perf_counter() - t0:.0f} s", flush=True)
    track(synth)
    run("synth1", 90, True)
    run("synth1-off", 30, False)
    track(T)
    run("stereo", 150, True)                                     # 100 ms of the 250 ms sample
    run("stereo-off", 4, False)
    run("retrig", 150, True)                                     # again while it still sounds
    run("retrig-off", 30, False)
    track(synth)
    run("synth2", 90, True)
    run("synth2-off", 10, False)
    rep["numbers"]["play_periods"] = len(log)
    # the voice that sounds: its L and R through the stereo note and the retrigger
    st_blocks = [b for ph, b in sb if ph in ("stereo", "stereo-off", "retrig", "retrig-off")]
    voices = sorted({v for blk in st_blocks for v in blk})
    peak = lambda v: max((abs(x) for blk in st_blocks if v in blk for x in blk[v][0] if x == x), default=0.0)   # noqa: E731
    best_v = max(voices, key=peak, default=None)
    ls = [x for blk in st_blocks for x in (blk[best_v][0] if best_v in blk else [0.0] * 32)]
    rs = [x for blk in st_blocks for x in (blk[best_v][1] if best_v in blk else [0.0] * 32)]
    pk_l = max((abs(x) for x in ls if x == x), default=0.0)
    pk_r = max((abs(x) for x in rs if x == x), default=0.0)
    first = next((i for i, x in enumerate(ls) if abs(x) > 1e-3), None)
    want_l = [wave_l(k) for k in range(N)]
    want_r = [wave_r(k) for k in range(N)]
    win = 1024
    seg = (first or 0) + 256
    lags = range(0, 6000)
    lag_l, corr_l = best_match(ls[seg:seg + win], want_l, lags)
    lag_r, corr_r = best_match(rs[seg:seg + win], want_r, lags)
    _, cross = best_match(rs[seg:seg + win], want_l, lags)
    rep["numbers"]["stereo"] = {"voices": voices, "voice": best_v, "blocks": len(st_blocks), "peak_l": pk_l,
                                "peak_r": pk_r, "first_sound": first, "corr_l": corr_l, "lag_l": lag_l,
                                "corr_r": corr_r, "lag_r": lag_r, "r_vs_l_wave": cross}
    link(f"3a. track {T}'s note sounds in its stereo buffer, both sides (what the main bus and the sends read)",
         pk_l > 0.05 and pk_r > 0.05, f"voice {best_v}: peak L {pk_l:.3f}, R {pk_r:.3f}; first sound at sample {first}")
    link("3b. L is the sample's L and R the sample's R (correlation > 0.98 at the best lag), R not L's wave",
         corr_l > 0.98 and corr_r > 0.98 and cross < 0.5 and lag_l is not None and lag_r is not None
         and abs(lag_l - lag_r) <= 2, f"L {corr_l:.4f} at {lag_l}, R {corr_r:.4f} at {lag_r}; R against L's wave {cross:.3f}")
    # 4. the synth: its first note sounds, and again after the stereo notes
    s1 = [e["synth"] for e in log if e["phase"] == "synth1"]
    s2 = [e["synth"] for e in log if e["phase"] == "synth2"]
    s1_first = next((i for i, x in enumerate(s1) if x > 1e-5), None)   # (the snapshot's sound swells in slowly)
    rep["numbers"]["synth"] = {"track": synth, "first_note_first_sound": s1_first, "first_peak": max(s1, default=0),
                               "after_peak": max(s2, default=0)}
    link("4a. the synth track sounds on its first note (within 60 periods)", s1_first is not None and s1_first < 60,
         f"track {synth}: first sound at period {s1_first} of its note")
    link("4b. the synth track sounds again after the stereo notes (audio not gone)", max(s2, default=0) > 1e-5,
         f"its peak on the second note {max(s2, default=0):.4f}")
    # 5. the retrigger: no jump past the sample's own steps, no NaN
    own = max(max(abs(want_l[k + 1] - want_l[k]) for k in range(N - 1)),
              max(abs(want_r[k + 1] - want_r[k]) for k in range(N - 1)))
    jl = max((abs(ls[i + 1] - ls[i]) for i in range(len(ls) - 1) if ls[i] == ls[i] and ls[i + 1] == ls[i + 1]), default=0.0)
    jr = max((abs(rs[i + 1] - rs[i]) for i in range(len(rs) - 1) if rs[i] == rs[i] and rs[i + 1] == rs[i + 1]), default=0.0)
    nan = sum(1 for x in ls + rs if x != x)
    rt = [b for ph, b in sb if ph == "retrig"]
    rt_peak = max((abs(x) for blk in rt for v in blk for x in blk[v][0] + blk[v][1] if x == x), default=0.0)
    rep["numbers"]["jumps"] = {"own_largest": own, "l": jl, "r": jr, "nan": nan, "retrig_peak": rt_peak}
    link("5. the retrigger: it sounds, no click (no jump past the sample's own largest step x 1.5), no NaN",
         rt_peak > 0.05 and jl <= 1.5 * own and jr <= 1.5 * own and nan == 0,
         f"retrigger peak {rt_peak:.3f}; largest jump L {jl:.3f}, R {jr:.3f}; the sample's own {own:.3f}; NaN {nan}")
    alive = [e["status"] for e in log[-10:]]
    link("6. the DSP's status alive to the end", all(s & 0xFF00 == 0x5A00 for s in alive),
         f"the last statuses {[hex(s) for s in alive[-3:]]}")
    return finish()


if __name__ == "__main__":
    sys.exit(main())
