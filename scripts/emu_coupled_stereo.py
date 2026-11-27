"""Stereo on both processors, against its own two halves (docs/stereo-assessment.md, "Field
reports on v0.54-t1"; the route rewritten 2026-11-27).

One stereo note (format 2, L a 200 Hz saw, R a 330 Hz sine) is played on track 1, ONESHOT, from
the power-on load onwards, as the first note after boot (so on voice 0: the coupled emulator leaves
a track's later voices silent on every build, v0.76's mono ones included, a limit of its own). The
same run is made twice more with a MONO sample in the stereo one's place: its L channel alone
(--pool L), then its R alone (--pool R). Stereo is right when it is exactly those two:

  1. The power-on load: the image reached the DSP over the sample link, every frame's word.
  1b. (--pool stereo) the ColdFire's slot 0 is stereo (format 2).
  2a. Track 1 ONESHOT on slot 0, a stock synth on another track.
  3. (--compare) Every block, track 1's buffer after the voices' sum and the stereo hook
     (sw 0x1c255a): its L half is the L run's, bit for bit; its R half is the R run's, to the
     float rounding of g L + (g R - g L) (relative 1e-6 of the block's peak); both sound
     (the twins' peak > 0.01); R is not L.
  4. (--compare) No NaN or infinity in any track's buffer, in any of the three runs.
  5. No halt, no fault, the DSP's status alive to the end.

A negative control: v0.54-t1's build (with its own layout) must fail 3.

Usage: emu_coupled_stereo.py --build BUILD.syx --pool stereo|L|R --json OUT
       emu_coupled_stereo.py --compare STEREO.json L.json R.json"""

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
import emu_coupled_flex as F                                    # noqa: E402
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
TRACK_BUF = 0x259F68                    # 16 tracks x 64 words: L half, R half
SUM_AFTER = 0x1C255A                    # just after the voices' sum and the stereo hook (stereo.py)
NOTE_ON, NOTE_OFF = 30, 4
N = 3000                                # the stereo sample's frames (62 ms; a short load)


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
    p.add_argument("--pool", choices=("stereo", "L", "R"), default="stereo")
    p.add_argument("--compare", nargs=3, default=None, metavar=("STEREO", "L", "R"))
    a = p.parse_args()
    if a.compare:
        return compare(*a.compare)
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    from unicorn import UC_HOOK_CODE                            # noqa: PLC0415
    from unicorn import m68k_const as K                         # noqa: PLC0415
    from dnfw.sampler import live as SL, machines as SM         # noqa: PLC0415
    from dnfw.waverider import dsp as WD                        # noqa: PLC0415
    c = Coupled(a.build, a.snapshot, a.stock, verbose=False)
    c.watchdog()
    F.install_smoother_model(c)          # digikit's EMAC decays the stock smoother's output to ~3% (emu_coupled_flex)
    rep = {"links": {}, "numbers": {}, "setup": [("the stock smoother 0x400db12a modelled", "emu_coupled_flex")]}
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
    if a.pool == "stereo":
        img = SL.pool_bytes([st, mono], base, [1.0, 1.0], [SM.FMT_I16S, SM.FMT_I16], ["WIDE", "TRI"])
    else:                                                        # the note's one side, a mono sample
        side = [x[0] if a.pool == "L" else x[1] for x in st]
        img = SL.pool_bytes([side, mono], base, [1.0, 1.0], [SM.FMT_I16, SM.FMT_I16], ["SIDE", "TRI"])
    rep["pool"] = a.pool
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
    if a.pool == "stereo":
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
    # the ONESHOT's own controls at the DT2's defaults (machine_commit keeps the synth sound's words;
    # runs 1..3, without the smoother's model either, played REV from STRT's middle, crawling), TUNE
    # +36: the KEYBOARD key plays note 24 (C1), so the sample plays at its own rate
    for slot, w in ((25, 100 << 8), (41, 127 << 8), (26, 0), (45, 120 << 8), (44, 0), (30, 100 << 8)):
        c.poke(kit + 52 + STRIDE * T + 20 + 2 * slot, struct.pack(">H", w))
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

    # 3: the note, held NOTE_ON periods and let go NOTE_OFF more; every block, every track's buffer
    # after the voices' sum and the stereo hook after it (sw 0x1c255a: the sum hook returns there)
    blocks: list = []

    def after_sum(r, cc):
        blocks.append([(cc.M.m2.word(r.state, TRACK_BUF + 4 * i) or 0) & 0xFFFFFFFF for i in range(16 * 64)])
    c.taps[SUM_AFTER] = after_sum
    track(T)
    c.machine.pc = P.press(c.machine.m, c.panel.profile, *key(33))
    held_ok = c.periods(NOTE_ON)
    c.machine.pc = P.release(c.machine.m, c.panel.profile, *key(33))
    c.periods(NOTE_OFF)
    rep["track"] = T
    rep["blocks"] = blocks
    st_ = [c.last_status[k] for k in range(3)] if c.last_status else []
    rep["numbers"]["status"] = [hex(x) for x in st_]
    link("5. the DSP's status alive to the end", bool(st_) and all(x == 0x5A00 for x in st_),
         f"the last statuses {[hex(x) for x in st_]}")
    return finish()


def compare(sj: str, lj: str, rj: str) -> int:
    """links 3 and 4 over the three runs' JSONs"""
    S, L, R = (json.loads(pathlib.Path(x).read_text()) for x in (sj, lj, rj))
    f = lambda w: struct.unpack("<f", struct.pack("<I", w))[0]        # noqa: E731
    bad = []

    def link(name, ok, detail=""):
        print(("  ok    " if ok else "  FAIL  ") + name + (f" -- {detail}" if detail else ""), flush=True)
        if not ok:
            bad.append(name)
    for nm, run in (("stereo", S), ("L", L), ("R", R)):
        link(f"the {nm} run passed its own links", all(v["ok"] for v in run["links"].values()) and not run.get("halt"),
             ", ".join(k for k, v in run["links"].items() if not v["ok"]) or "all ok")
    t = S.get("track", 1)
    n = min(len(S.get("blocks", [])), len(L.get("blocks", [])), len(R.get("blocks", [])))
    l_exact = r_close = sounding = 0
    worst, diff, peaks = 0.0, 0, [0.0, 0.0]
    for b in range(n):
        s, l_, r_ = S["blocks"][b], L["blocks"][b], R["blocks"][b]
        sl, sr = s[64 * t:64 * t + 32], s[64 * t + 32:64 * t + 64]
        ll, rr = l_[64 * t:64 * t + 32], r_[64 * t + 32:64 * t + 64]
        l_exact += sl == ll
        pk = max(abs(f(w)) for w in rr)
        e = max(abs(f(x) - f(y)) for x, y in zip(sr, rr))
        worst = max(worst, e / pk if pk else (0.0 if e == 0 else math.inf))
        r_close += e <= 1e-6 * pk or e == 0
        diff += sl != sr
        peaks = [max(peaks[0], max(abs(f(w)) for w in ll)), max(peaks[1], pk)]
    link("3. track 1's L half is the L run's, bit for bit, every block; its R half the R run's (relative "
         "1e-6); both sound; R is not L",
         n > 20 and l_exact == n and r_close == n and min(peaks) > 0.01 and diff > n // 2,
         f"{n} blocks: L exact {l_exact}, R within rounding {r_close} (worst relative {worst:.2g}); peaks L "
         f"{peaks[0]:.4f} R {peaks[1]:.4f}; blocks where R differs from L {diff}")
    nonfinite = {nm: sum(1 for blk in run.get("blocks", []) for w in blk if (w >> 23) & 0xFF == 0xFF)
                 for nm, run in (("stereo", S), ("L", L), ("R", R))}
    link("4. no NaN or infinity in any track's buffer, in any of the three runs", not any(nonfinite.values()),
         str(nonfinite))
    print(("PASS" if not bad else "FAIL") + (f": the first broken link: {bad[0]}" if bad else
          ": stereo is its two halves on both processors"), flush=True)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
