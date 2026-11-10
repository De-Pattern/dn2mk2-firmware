"""v0.48: STRT, LEN and LOOP's fine records (csrc/sampler/fmt.c smp_fine), swapped in and out.

On the ColdFire emulator with a build installed over the stock 1.11 snapshot (the v0.14
build's edits put back to stock first), the UI running, the panel driven as a person would:

  1. WaveTone active (track 0): the three records and their runtime entries as the
     snapshot has them -- the baseline, every byte.
  2. Track 1 to ONESHOT (MACHINE SEL's commit through smp_machine_commit, as the UI's call), track 0 still
     active: the records unchanged; track 1's LEN at 120.00 (0x7800), STRT and LOOP at 0.
  3. [TRK]+[TRIG 2]: track 1 active. 239/258/257 carry FREQ's (record 36) range-free fine
     words: range 0x7800, LEN's default 0x7800, the flag, FREQ's value type and formatter.
  4. A turn of STRT (encoder E on the SRC page): a value that is not a whole number.
  5. [TRK]+[TRIG 1]: WaveTone active again. Every byte of the records and the entries back
     to the baseline; track 1's STRT unchanged. A turn of WAV1 there: whole steps only.
  6. [TRK]+[TRIG 2]: fine again, track 1's STRT still the same word.
  7. Track 1 to GRID, STRETCH, SLICE, REPITCH, BOUNCE, WERP and back to ONESHOT, then
     WaveTone, each while it is the active track: each machine's mask (ONESHOT 3 fine,
     STRETCH/REPITCH/BOUNCE STRT and LEN, the rest none) and, for every record not fine,
     its baseline bytes but for the names and formatter (wr_names' and smp_formats' own).

Every check prints PASS or FAIL with what it saw; the exit code is the number failed.
Usage: emu_fine_swap.py --build out/v048.syx [--json OUT]"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

SNAP = str(HERE.parent.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap")
KIT, STRIDE = 0x800052A0, 1163
UI_TRACK = 0x42431A6C
REC = lambda i: 0x401F7F94 + 60 * i            # noqa: E731
ENT = lambda i: 0x4243325C + 68 * i            # noqa: E731
IDS = (239, 258, 257)                           # STRT, LEN, LOOP
SLOTS = {239: 26, 258: 45, 257: 44}
FREQ = 36
ONESHOT, WERP, STRETCH, REPITCH, GRID, SLICE, BOUNCE = 8, 9, 10, 11, 12, 13, 17
MASK = {ONESHOT: 7, STRETCH: 3, REPITCH: 3, BOUNCE: 3}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--json", default=None)
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"),
                   help="the build's layout (its smp_machine_commit)")
    a = p.parse_args()
    from emu_encoder_trace import guest
    from emulib.image import differences
    from emulib.machine import Machine
    from emulib.panel import Panel
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    from dnfw.mods import platform
    from dnfw.sampler import machines as SMx
    from unicorn import UC_PROT_ALL, UcError
    m = Machine(a.snapshot)
    stock = open(pathlib.Path(os.environ.get("DT2_SECTIONS", HERE.parent.parent / "sec111")) / "section_3_MAIN_OS.bin", "rb").read()
    m.apply([(va, stock[va - 0x40000400:va - 0x40000400 + len(b)])
             for va, b in differences(stock, open(a.snapshot + ".section_3_MAIN_OS.bin", "rb").read())
             if va + len(b) <= 0x40000400 + len(stock)])
    sec3 = load(read_image(pathlib.Path(a.build))).container.find(3).unpack()
    m.apply(differences(stock, sec3))
    for va, blob in platform.runtime(sec3):
        m.write(va, blob)
    for pg in range(SMx.MIRROR, SMx.MIRROR + 0x500000, 0x100000):
        try:
            m.uc.mem_map(pg, 0x100000, UC_PROT_ALL)
        except UcError:
            pass
    m.flush()
    panel = Panel(m, png_dir=str(pathlib.Path(a.json or "out/fine_swap").with_suffix("")) + "_png")
    names = {}
    for code in range(1, 64):
        n = panel.panelin.control_name(m.m, panel.profile, code)
        if n:
            names[n.upper()] = code
    trk = names.get("TRK") or names.get("TRACK")
    if trk is None:
        print("FAIL: no TRK key in the firmware's button names:", sorted(names))
        return 1
    TRK = divmod(trk - 1, 8)
    TRIG = lambda t: divmod(25 + t - 2, 8)          # noqa: E731  [TRIG t]: codes 25..40 (rec.c K_TRIG1), code = ch*8+bit+1
    results, report = [], {"steps": []}

    def check(name, ok, detail=""):
        results.append((name, bool(ok)))
        print(("PASS " if ok else "FAIL ") + name + (f" -- {detail}" if detail else ""), flush=True)

    def rec_bytes(i):
        return bytes(m.read(REC(i), 60)) + bytes(m.read(ENT(i), 68))

    def words(i):
        r = struct.unpack(">15i", bytes(m.read(REC(i), 60)))
        t = struct.unpack(">4I", bytes(m.read(ENT(i) + 4, 16)))
        return {"range": r[3], "default": r[4], "flag": r[5], "fmt": r[13] & 0xFFFFFFFF, "type": list(t)}

    def snd(t):
        return m.long(KIT) + 52 + STRIDE * t

    def val(t, rid):
        return struct.unpack(">H", bytes(m.read(snd(t) + 0x14 + 2 * SLOTS[rid], 2)))[0]

    def mtype(t):
        return struct.unpack(">b", bytes(m.read(snd(t) + 0xDE, 1)))[0]

    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]

    def commit(t, ty):                               # MACHINE SEL's commit as the UI makes it: through
        owner = guest(m, 0x4018A97A)                 # its call at 0x4005bba0, which the mod points at
        guest(m, lay["smp_machine_commit"], owner + 0xF4, t, ty, 1, 1)   # smp_machine_commit (rec.c)
        panel.settle(5_000_000)

    def select(t):
        m.pc = panel.panelin.press(m.m, panel.profile, *TRK)
        panel.settle(1_000_000)
        panel.tap(TRIG(t + 1), after=1_000_000)
        m.pc = panel.panelin.release(m.m, panel.profile, *TRK)
        panel.settle(5_000_000)

    def turn(enc, n, gap=1_000_000):
        for _ in range(n):
            m.pc = panel.panelin.encoder(m.m, panel.profile, enc, 1)
            panel.settle(gap)
        panel.settle(5_000_000)

    fine = words(FREQ)

    def is_fine(i):
        w = words(i)
        return (w["range"] == 0x7800 and w["default"] == (0x7800 if i == 258 else 0)
                and w["flag"] == fine["flag"] and w["type"] == fine["type"] and w["fmt"] == fine["fmt"])

    panel.settle(5_000_000)
    t0 = mtype(0)
    check("track 0 is not one of ours at the start (WaveTone's records are the baseline)", t0 < 4, f"type {t0}")
    base = {i: rec_bytes(i) for i in IDS}
    report["baseline"] = {i: words(i) for i in IDS}
    report["freq"] = fine

    def unswapped(i, allow_fmt=False):
        now = rec_bytes(i)
        if allow_fmt:                                   # all but the names and formatter (+0x28..+0x37),
            return now[:0x28] + now[0x38:] == base[i][:0x28] + base[i][0x38:]   # wr_names/smp_formats' own
        return now == base[i]

    commit(1, ONESHOT)
    check("2. track 1 on ONESHOT", mtype(1) == ONESHOT, f"type {mtype(1)}")
    check("2. records untouched while WaveTone is active", all(unswapped(i) for i in IDS))
    check("2. a fresh ONESHOT: LEN 120.00, STRT and LOOP 0",
          (val(1, 258), val(1, 239), val(1, 257)) == (0x7800, 0, 0),
          f"LEN {val(1, 258):#06x} STRT {val(1, 239):#06x} LOOP {val(1, 257):#06x}")
    select(1)
    check("3. track 1 active", m.read(UI_TRACK, 1)[0] == 1, f"UI_TRACK {m.read(UI_TRACK, 1)[0]}")
    check("3. STRT, LEN, LOOP fine (FREQ's words)", all(is_fine(i) for i in IDS),
          json.dumps({i: words(i) for i in IDS}))
    panel.tap((0, 1))                                   # SYN: the machine page
    turn(4, 40, 200_000)                            # (past the knob's rest guard: emu_encoder_trace)
    v1 = val(1, 239)
    check("4. STRT moved off zero by a fine amount (not a whole step)", v1 != 0 and v1 % 256 != 0, f"STRT {v1:#06x}")
    select(0)
    check("5. WaveTone active: records and entries back, every byte", all(unswapped(i) for i in IDS),
          json.dumps({i: words(i) for i in IDS}))
    check("5. track 1's STRT unchanged", val(1, 239) == v1, f"{val(1, 239):#06x}")
    def words_of(t):
        return struct.unpack(">101H", bytes(m.read(snd(t) + 0x14, 202)))
    w0 = words_of(0)
    panel.tap((0, 1))                                   # SYN: the machine page
    turn(4, 40, 200_000)                            # (WaveTone's SYN 1, encoder E: record 250)
    w1 = words_of(0)
    moved = [(k, w0[k], w1[k]) for k in range(101) if w0[k] != w1[k]]
    check("5. a WaveTone knob still moves in whole steps (stock)", moved and all(a_ % 256 == 0 and b_ % 256 == 0 for _, a_, b_ in moved),
          str([(k, hex(a_), hex(b_)) for k, a_, b_ in moved]))
    check("5. track 1's STRT still unchanged", val(1, 239) == v1, f"{val(1, 239):#06x}")
    select(1)
    check("6. fine again on track 1", all(is_fine(i) for i in IDS))
    check("6. STRT kept its fine word", val(1, 239) == v1, f"{val(1, 239):#06x}")
    for ty in (GRID, STRETCH, SLICE, REPITCH, BOUNCE, WERP, ONESHOT, t0):
        commit(1, ty)
        mk = MASK.get(ty, 0)
        got = [is_fine(i) for i in IDS]
        want = [bool(mk & (1 << k)) for k in range(3)]
        back = all(unswapped(i, allow_fmt=True) for k, i in enumerate(IDS) if not want[k])
        check(f"7. type {ty}: fine {want}", mtype(1) == ty and got == want and back,
              f"type {mtype(1)} fine {got}, others at baseline {back}; " + json.dumps({i: words(i) for i in IDS}))
        if mk & 2:
            check(f"7. type {ty} fresh: LEN 120.00", val(1, 258) == 0x7800, f"{val(1, 258):#06x}")
    check("7. WaveTone on track 1: every byte back", all(unswapped(i) for i in IDS))
    faults = getattr(m.m, "faults", [])
    check("no faults", not faults, str(faults[:3]))
    failed = [n for n, ok in results if not ok]
    report["results"] = results
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1, default=str))
    print(f"{len(results) - len(failed)}/{len(results)} passed", flush=True)
    return len(failed)


if __name__ == "__main__":
    raise SystemExit(main())
