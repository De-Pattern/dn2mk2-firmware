"""v0.48: STRT's fine record swapped while the sequencer plays over parameter locks
(emu_coupled.py with dsp=False: the modified ColdFire alone, its sequencer ISR at the tempo,
its audio ISR building the frame the DSP would get; category 2, no DSP).

Set up through the panel (the UI's own paths) unless marked direct:
  - track 1 (A) ONESHOT (direct: smp_machine_commit, the UI's commit path), track 2 (B) WaveTone;
    the pattern's length 4 steps (direct: written in the pattern);
  - GRID RECORDING (RECORD), a trig on step 1 of each track ([TRIG 1]), a lock on step 1:
    [TRIG 1] held and encoder E turned (track 0: STRT on SRC, a fine value; track 1: SRC's E,
    WaveTone's record 250, whole steps); the base value turned too (no step held);
  - PLAY; while it plays the active track goes 0 -> 1 -> 0 -> 1 ([TRK] + [TRIG n]), so the
    records 239/258/257 are swapped in and out under the sequencer.

Checked every period, from the per-voice mirror the frame is built from (the voices the
slot -> track table gives each track): each track's value word for the locked slot is its lock on step 1 and its own base on the others, to the bit, whatever track
is active; at the end the kit's values are what they were; no faults.

Usage: emu_fine_seq.py --build out/v048.syx [--json OUT]"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from emu_coupled import CF_FRAME, Coupled                       # noqa: E402

KIT, STRIDE = 0x800052A0, 1163
SEQ_PATTERN, TRACK_CUR, SEQ_PLAYING = 0x42C5A9A0, 0x42C5A984, 0x42C5A918
PAT_LENGTH = 122196
UI_TRACK = 0x42431A6C
ONESHOT = 8
A, B = 1, 2                     # the two tracks (not 0: the slot -> track table reads 0 for an idle voice)
SLOT_TRACK = 0x80005308         # the ColdFire's voice -> track table (link.c), what the frame's records follow
K_RECORD, K_PLAY, K_STOP, K_TRK, K_TRIG1 = 19, 20, 21, 16, 25


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    p.add_argument("--stock", default=str(HERE.parent.parent / "Digitone_II_OS1.11.syx"))
    p.add_argument("--snapshot", default=str(HERE.parent.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"))
    p.add_argument("--periods", type=int, default=1600)
    p.add_argument("--json", default=None)
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    c = Coupled(a.build, a.snapshot, a.stock, verbose=True, dsp=False)
    c.watchdog()
    rep, results, setup = {"setup": []}, [], []
    rep["setup"] = setup

    def check(name, ok, detail=""):
        results.append((name, bool(ok)))
        print(("PASS " if ok else "FAIL ") + name + (f" -- {detail}" if detail else ""), flush=True)

    key = lambda code: divmod(code - 1, 8)                       # noqa: E731
    P = c.panel.panelin

    def press(code):
        c.machine.pc = P.press(c.machine.m, c.panel.profile, *key(code))
        c.periods(2)

    def release(code):
        c.machine.pc = P.release(c.machine.m, c.panel.profile, *key(code))
        c.periods(2)

    def tap(code):
        press(code)
        release(code)

    def turn(enc, n, gap=200_000):
        for _ in range(n):
            c.machine.pc = P.encoder(c.machine.m, c.panel.profile, enc, 1)
            c.panel.settle(gap)
        c.periods(4)

    kit = c.long(KIT)
    snd = lambda t: kit + 52 + STRIDE * t                        # noqa: E731

    def val(t, slot):
        return struct.unpack(">H", c.read(snd(t) + 0x14 + 2 * slot, 2))[0]

    def fword(v, slot):
        """voice V's value for SLOT in the per-voice mirror the frame is built from (0x800068E4,
        101 words a voice after 17: emu_slides.py's OUT). The frame's own words are this after
        the ISR's smoothing (a glide toward it every frame), so they are not compared to the bit"""
        return struct.unpack(">H", c.read(0x800068E4 + 2 * (17 + 101 * v + slot), 2))[0]

    owner = c.call(0x4018A97A)[0]
    c.call(lay["smp_machine_commit"], owner + 0xF4, A, ONESHOT, 1, 1)
    setup.append(("track A ONESHOT", "direct: smp_machine_commit called"))
    pat = c.long(SEQ_PATTERN)
    c.poke(pat + PAT_LENGTH, struct.pack(">H", 4))
    setup.append(("pattern length 4", "direct: the pattern's length word"))
    c.periods(4, label="settle")
    check("track A ONESHOT, track B WaveTone", c.read(snd(A) + 0xDE, 1)[0] == ONESHOT and c.read(snd(B) + 0xDE, 1)[0] < 4,
          f"types {c.read(snd(A) + 0xDE, 1)[0]}, {c.read(snd(B) + 0xDE, 1)[0]}")

    def select(t):
        press(K_TRK)
        tap(K_TRIG1 + t)
        release(K_TRK)
        c.periods(4)

    slots = {A: 26, B: None}
    for t in (A, B):
        select(t)
        c.panel.tap((0, 1))                                      # SRC
        c.periods(2)
        before = [val(t, s) for s in range(101)]
        turn(4, 40)                                              # the base value
        after = [val(t, s) for s in range(101)]
        moved = [s for s in range(101) if before[s] != after[s]]
        if t == B:
            slots[B] = moved[0] if moved else None
        tap(K_RECORD)
        tap(K_TRIG1)                                             # a trig on step 1
        press(K_TRIG1)
        turn(4, 30)                                              # its lock: E turned, step 1 held
        release(K_TRIG1)
        tap(K_RECORD)
        setup.append((f"track {t}: base value, a trig and a lock on step 1", "UI: SRC, encoder E, RECORD, [TRIG 1] held + E"))
    s0, s1 = slots[A], slots[B]
    check("track B's encoder E moved a WaveTone slot", s1 is not None, f"slot {s1}")
    if s1 is None:
        return 1
    base = {A: val(A, s0), B: val(B, s1)}
    rep["base"] = base
    check("track A's STRT base is fine (a fraction)", base[A] % 256 != 0, f"{base[A]:#06x}")
    tap(K_PLAY)
    setup.append(("PLAY", "UI: the PLAY key"))
    seen = {A: {}, B: {}}
    switches = {a.periods // 5: B, 2 * a.periods // 5: A, 3 * a.periods // 5: B}
    for n in range(a.periods):
        if n in switches:
            select(switches[n])
        if not c.period():
            break
        vt = struct.unpack(">16I", c.read(SLOT_TRACK, 64))
        for t, sl in ((A, s0), (B, s1)):
            step = c.read(TRACK_CUR + t, 1)[0]
            for v in range(16):
                if vt[v] == t:
                    seen[t].setdefault(step, set()).add(fword(v, sl))
        if n % 300 == 0:
            print(f"  [playing] {n}/{a.periods} periods, active {c.read(UI_TRACK, 1)[0]}, steps "
                  f"{c.read(TRACK_CUR + A, 1)[0]}/{c.read(TRACK_CUR + B, 1)[0]}, seen {json.dumps({t: {k: sorted(hex(x) for x in v) for k, v in seen[t].items()} for t in seen})}", flush=True)
    tap(K_STOP)
    rep["seen"] = {t: {k: sorted(v) for k, v in seen[t].items()} for t in seen}
    for t in (A, B):
        locked = seen[t].get(0, set())
        others = set().union(*[v for k, v in seen[t].items() if k != 0]) if len(seen[t]) > 1 else set()
        check(f"track {t}: the other steps play its base {base[t]:#06x} only", others == {base[t]},
              f"{sorted(hex(x) for x in others)}")
        check(f"track {t}: step 1 plays one locked value, not the base", len(locked) == 1 and base[t] not in locked,
              f"{sorted(hex(x) for x in locked)}")
    lock0 = next(iter(seen[A].get(0, {0})))
    check("track A's STRT lock is kept to the bit (fine, not rounded to a whole step)", lock0 % 256 != 0, f"{lock0:#06x}")
    check("4 steps played on each track", all(len(seen[t]) == 4 for t in (A, B)), str({t: sorted(seen[t]) for t in seen}))
    check("the kit's base values unchanged at the end", val(A, s0) == base[A] and val(B, s1) == base[B],
          f"{val(A, s0):#06x}, {val(B, s1):#06x}")
    check("no faults, no halt", not c.faults() and not c.halt, f"{c.faults()[:3]} {c.halt}")
    failed = [n for n, ok in results if not ok]
    rep["results"] = results
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(rep, indent=1, default=str))
    print(("PASS" if not failed else "FAIL") + f": {len(results) - len(failed)}/{len(results)}", flush=True)
    return len(failed)


if __name__ == "__main__":
    raise SystemExit(main())
