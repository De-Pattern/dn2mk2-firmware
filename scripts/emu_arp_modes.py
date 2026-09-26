"""Run the stock arp step for every MODE value, and the three MODE bounds, in the emulator.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \\
        scripts/emu_arp_modes.py [snapshot]

**The question** (docs/arp-hidden-modes.md): the 1.11 image names eight arp
modes, OFF TRUE UP DOWN CYCL SHUF RAND CHRD, and the instrument offers five.
Does the step at `0x4002a0bc` implement the last three?

The sequencer does not play under the emulator (docs/ideas-backlog.md §18), so
the step is called directly, on stock code, with its real arguments. The arp
state is laid out the way the note set (`0x40029cd4`) leaves it after its reset
(`0x40029f3a`): four held notes in the track's bitmap (`0x40598728`), the same
notes linked in press order in its list (`0x40598828`, head `0x4059c868`,
tail `0x4059c828`), and the state record `0x405984a8 + 40*track` pointing at a
sound whose MODE (`+351`), RNG (`+353`), LEN (`+355`), mask (`+356`) and
offsets (`+358`) are set here.

Then the three places that bound MODE are called, each with an out-of-range
value and an in-range control:

- `setMode` (`0x4004bea4`), the arp menu's edit;
- the FUNC+ARP toggle (`0x4004bf32`), which restores the parked MODE (`+374`);
- the stored-sound LOAD converter (`0x400dd1ea`), after a SAVE (`0x400dd6a6`)
  of a live sound carrying the value.

Read-only against the firmware: scratch buffers and the arp state of track 1.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu.longrun import build  # noqa: E402
from unicorn import UC_PROT_ALL, UcError  # noqa: E402
from unicorn.m68k_const import (UC_M68K_REG_A6, UC_M68K_REG_A7,  # noqa: E402
                                UC_M68K_REG_D0, UC_M68K_REG_SR)

SNAP = "/root/dn2-snapshots/Digitone_II_OS1.11/grid-rec.snap"
SYX = ("/mnt/d/01_Code/Z_Personal/dn2_firmware/00_Resources/00_Firmware/"
       "Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx")

STEP = 0x4002A0BC                         # (track, arp id) -> note, -1 rest, -2 stale
SET_MODE, TOGGLE = 0x4004BEA4, 0x4004BF32
LOAD, SAVE = 0x400DD1EA, 0x400DD6A6       # (live, stored), (stored, live, flag)
BITMAPS, LISTS = 0x40598728, 0x40598828   # 4 longs / 128 x 8 B per track
HEAD, TAIL = 0x4059C868, 0x4059C828
STATE, STATE_STRIDE = 0x405984A8, 40
MODE, RNG, LEN, MASK, OFFSETS, PARKED = 351, 353, 355, 356, 358, 374
STORED_MODE = 331                         # SAVE 0x400dd8aa: stored +331 <- live +351
SOUND, STORED = 1163, 359
NAMES = ["OFF", "TRUE", "UP", "DOWN", "CYCL", "SHUF", "RAND", "CHRD"]
NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

STACK, SCRATCH = 0x467CF000, 0x467D0000
HOOK = 0x4002A13C                         # arpmodes' dispatch hook: jmp its cave
GEN, RECORDS, RAM_BYTES = 0x467A0000, 0x467A0010, 2320   # arpmodes' generator and records
TICK = 0x466758B0
HELD, HELD_BITS, HELD_ANY = 0x446478C8, 600, 616       # the held-trig object (arpplocks)
TRACK = 0
PRESSED = [64, 60, 67, 71]                # E4 C4 G4 B4, in press order: TRUE shows it
STEPS = 24

failures = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def name(n):
    return "rest" if n < 0 else f"{NOTE[n % 12]}{n // 12 - 1}"


class Emu:
    def __init__(self, snapshot, ranges=()):
        self.m, *_ = build(snapshot, syx=SYX, unblock=True, softfloat=True, bitmap=True, dsp=True,
                           weakptr=True, slc=True, deferred_components=("timers",))
        self.uc = self.m.uc
        self.ret = STACK + 0x800
        self.at = SCRATCH
        self.labels = {}
        for path in ranges:
            for r in json.load(open(path))["ranges"]:
                self.write(int(r["va"], 16), bytes.fromhex(r["hex"]))
            try:
                self.labels.update({k: int(v, 16) for k, v in json.load(open(path + ".at")).items()})
            except FileNotFoundError:
                pass

    def write(self, va, data):
        try:
            self.uc.mem_write(va, data)
        except UcError:
            for page in range(va & ~0xFFFFF, va + len(data) + 0x100000, 0x100000):
                try:
                    self.uc.mem_map(page, 0x100000, UC_PROT_ALL)
                except UcError:
                    pass
            self.uc.mem_write(va, data)

    def read(self, va, n):
        return bytes(self.uc.mem_read(va, n))

    def put32(self, va, v):
        self.write(va, struct.pack(">I", v & 0xFFFFFFFF))

    def alloc(self, n):
        va = (self.at + 15) & ~15
        self.at = va + n
        self.write(va, bytes(n))
        return va

    def call(self, fn, *args):
        """Enter `fn` as a jsr would, interrupts masked (a call interrupted returns a lie)."""
        frame = struct.pack(">I", self.ret) + b"".join(struct.pack(">I", a & 0xFFFFFFFF) for a in args)
        self.write(STACK, frame)
        self.uc.reg_write(UC_M68K_REG_A7, STACK)
        self.uc.reg_write(UC_M68K_REG_A6, 0)
        sr = self.uc.reg_read(UC_M68K_REG_SR)
        self.uc.reg_write(UC_M68K_REG_SR, (sr & ~0x0700) | 0x2700)
        try:
            self.uc.emu_start(fn, self.ret, count=5_000_000)
            d0 = self.uc.reg_read(UC_M68K_REG_D0)
            return d0 - (1 << 32) if d0 & 0x80000000 else d0
        finally:
            self.uc.reg_write(UC_M68K_REG_SR, sr)

    def model(self, sound):
        """An object whose vt[40] returns `sound` and vt[16] (notify) returns."""
        code = self.alloc(16)
        self.write(code, b"\x20\x3c" + struct.pack(">I", sound) + b"\x4e\x75" + b"\x4e\x75")
        vt = self.alloc(64)
        self.put32(vt + 40, code)
        self.put32(vt + 16, code + 8)
        obj = self.alloc(16)
        self.put32(obj, vt)
        return obj


def hold(e, sound, notes, arp_id=1):
    """Lay out the held-note set and a reset arp state, as the note set leaves them."""
    bits = [0, 0, 0, 0]
    for n in notes:
        bits[n >> 5] |= 1 << (n & 31)
    e.write(BITMAPS + 16 * TRACK, struct.pack(">4I", *bits))
    lists = LISTS + 1024 * TRACK
    e.write(lists, bytes(1024))
    prev = 0
    for n in notes:
        entry = lists + 8 * n
        e.put32(entry, prev)                 # +0 previous
        if prev:
            e.put32(prev + 4, entry)         # +4 next
        prev = entry
    e.put32(HEAD + 4 * TRACK, lists + 8 * notes[0])
    e.put32(TAIL + 4 * TRACK, prev)
    st = STATE + STATE_STRIDE * TRACK
    e.write(st, struct.pack(">10i", -1, 0, 1, -1, -1, 0, arp_id, 0, sound, 0))
    return arp_id


def seed(e, state=0x1234ABCD, tick=None):
    """arpmodes' generator to `state`, every SHUF record blank; the tick if given."""
    e.write(GEN, struct.pack(">I", state) + bytes(RAM_BYTES - 4))
    if tick is not None:
        e.put32(TICK, tick)


def run_mode(e, mode, rng=1, length=15, mask=0xFFFF, offsets=None, notes=PRESSED, steps=STEPS,
             state=0x1234ABCD):
    seed(e, state)
    sound = e.alloc(SOUND + 16)
    s = bytearray(SOUND)
    s[MODE] = mode & 0xFF
    s[RNG] = rng
    s[LEN] = length
    s[MASK:MASK + 2] = struct.pack(">H", mask)
    for i, v in enumerate(offsets or []):
        s[OFFSETS + i] = v & 0xFF
    e.write(sound, bytes(s))
    arp_id = hold(e, sound, notes)
    return [e.call(STEP, TRACK, arp_id) for _ in range(steps)]


def show(label, seq):
    print(f"  {label:<14s} " + " ".join(f"{name(n):>4s}" for n in seq))


C4, E4, G4, B4 = 60, 64, 67, 71
UP = [C4, E4, G4, B4, C4 + 12, E4 + 12, G4 + 12, B4 + 12]
RANGE = sorted(UP)                        # the four held notes over RNG 1: two octaves
OFFS = [0, 7, -5, 12, 0, 7, -5, 12]
MUTED = 0xFFFF & ~((1 << 2) | (1 << 6))   # arp steps 3 and 7 muted


def controls(e, seqs):
    """The modes both images share, and must play alike."""
    check("OFF rests every step", all(n == -1 for n in seqs[0]))
    check("TRUE plays press order, then the next octave",
          seqs[1][:8] == [E4, C4, G4, B4, E4 + 12, C4 + 12, G4 + 12, B4 + 12])
    check("UP (control) climbs C E G B, then an octave up", seqs[2] == (UP * 8)[:len(seqs[2])])
    check("DOWN falls B G E C", seqs[3][:4] == [B4, G4, E4, C4])
    cycl = seqs[4]
    check("CYCL (control) goes up then down without repeating the turn",
          cycl[:6] == [C4, E4, G4, B4, G4, E4])
    check("CHRD (7) is note for note CYCL", seqs[7] == cycl)
    neg = run_mode(e, -1, steps=len(cycl))
    check("a negative MODE is CYCL too (the dispatch's default)", neg == cycl)


def bounds(e, menu, toggle, load):
    print("\n  the menu edit: setMode(model, v)")
    for v, want in menu:
        sound = e.alloc(SOUND + 16)
        e.write(sound + MODE, bytes([2]))
        e.call(SET_MODE, e.model(sound), v)
        got = e.read(sound + MODE, 1)[0]
        check(f"setMode({v}) writes {want}", got == want, f"wrote {got}")

    print("\n  FUNC+ARP: MODE 0, parked value p at +374 -> restores")
    for p, want in toggle:
        sound = e.alloc(SOUND + 16)
        e.write(sound + MODE, bytes([0]))
        e.write(sound + PARKED, bytes([p]))
        e.call(TOGGLE, e.model(sound))
        got = e.read(sound + MODE, 1)[0]
        check(f"toggle with parked {p} restores {want}", got == want, f"restored {got}")

    print("\n  SAVE then LOAD a sound with MODE v")
    base = struct.unpack(">I", e.read(0x800052A0, 4))[0]
    real = e.read(base + 52, SOUND) if base else bytes(SOUND)
    for v, want in load:
        live = e.alloc(SOUND + 16)
        s = bytearray(real)
        s[MODE] = v
        e.write(live, bytes(s))
        stored = e.alloc(STORED + 16)
        e.call(SAVE, stored, live, 0)
        on_disk = e.read(stored + STORED_MODE, 1)[0]
        back = e.alloc(SOUND + 16)
        e.call(LOAD, back, stored)
        got = e.read(back + MODE, 1)[0]
        check(f"MODE {v}: saved as {on_disk}, loaded as {got}", on_disk == v and got == want,
              f"want saved {v}, loaded {want}")


def stock(e):
    seqs = {}
    for mode in range(8):
        seqs[mode] = run_mode(e, mode)
        show(f"{mode} {NAMES[mode]}", seqs[mode])
    print()
    controls(e, seqs)
    cycl = seqs[4]
    for mode in (5, 6):
        check(f"{NAMES[mode]} ({mode}) is note for note CYCL", seqs[mode] == cycl,
              "same sequence" if seqs[mode] == cycl else "differs")

    print("\n  twice, each from a fresh state: is SHUF / RAND the same every time?")
    for mode in (5, 6):
        again = run_mode(e, mode)
        check(f"{NAMES[mode]} repeats itself exactly (no randomness)", again == seqs[mode])

    print("\n  CHRD with offsets (+0 +7 -5 +12) and steps 3, 7 muted, LEN 8, RNG 0:")
    chrd = run_mode(e, 7, rng=0, length=7, mask=MUTED, offsets=OFFS, steps=16)
    cyc2 = run_mode(e, 4, rng=0, length=7, mask=MUTED, offsets=OFFS, steps=16)
    show("7 CHRD", chrd)
    show("4 CYCL", cyc2)
    check("CHRD one note per step, same as CYCL, with offsets and mutes", chrd == cyc2)
    check("a muted step rests", chrd[2] == -1 and chrd[6] == -1)

    bounds(e, menu=((3, 3), (4, 4), (5, 4), (6, 4), (7, 4), (-1, 0)),
           toggle=((3, 3), (4, 4), (6, 4), (0, 1)),
           load=((2, 2), (4, 4), (5, 0), (6, 0), (7, 0)))


def permutations(seq, n):
    """-> [each run of n], and whether every one is the whole range once."""
    runs = [seq[i:i + n] for i in range(0, len(seq), n)]
    return runs, all(sorted(r) == sorted(runs[0]) and len(set(r)) == n for r in runs)


def played(seq, offsets, length):
    """The notes a run chose, in order: rests dropped, each step's offset taken off."""
    return [n - offsets[k % length] for k, n in enumerate(seq) if n >= 0]


def mod(e):
    seqs = {}
    steps = 64
    for mode in range(8):
        seqs[mode] = run_mode(e, mode, steps=steps)
        show(f"{mode} {NAMES[mode]}", seqs[mode][:24])
    print()
    controls(e, seqs)
    fixed = [seqs[m] for m in (1, 2, 3, 4)]

    print("\n  SHUF: held C4 E4 G4 B4, RNG 1 -- a range of 8, three cycles and then 64 steps")
    shuf = seqs[5]
    runs, whole = permutations(shuf[:24], 8)
    for k, r in enumerate(runs):
        show(f"  cycle {k + 1}", r)
    check("SHUF: each of 3 cycles plays the whole range once", whole and sorted(runs[0]) == RANGE)
    check("SHUF: the three orders differ", len({tuple(r) for r in runs}) == 3)
    runs8, whole8 = permutations(shuf, 8)
    check("SHUF: all 8 cycles of 64 steps are permutations of the range", whole8)
    joins = [(a[-1], b[0]) for a, b in zip(runs8, runs8[1:])]
    check("SHUF: no cycle starts on the note the one before ended on",
          all(x != y for x, y in joins), f"{sum(x == y for x, y in joins)} repeat(s)")
    check("SHUF is none of TRUE, UP, DOWN, CYCL", all(shuf != f for f in fixed))

    print("\n  RAND: 64 steps")
    rand = seqs[6]
    show("  RAND", rand[:32])
    show("", rand[32:])
    check("RAND stays within the range", set(rand) <= set(RANGE),
          f"outside: {sorted(set(rand) - set(RANGE))}")
    check("RAND is none of TRUE, UP, DOWN, CYCL, SHUF", all(rand != f for f in fixed + [shuf]))
    _, rand_whole = permutations(rand, 8)
    counts = {n: rand.count(n) for n in RANGE}
    repeats = sum(a == b for a, b in zip(rand, rand[1:]))
    print(f"    each note's count: {' '.join(f'{name(n)}:{c}' for n, c in counts.items())};"
          f" {repeats} immediate repeat(s)")
    check("RAND reaches every note of the range in 64 steps", all(counts.values()))
    check("RAND is not a shuffle (its runs of 8 are not all permutations)", not rand_whole)

    print("\n  the generator: repeatable from a state, moved by the tick")
    for mode in (5, 6):
        a = run_mode(e, mode, steps=16, state=0x0BADF00D)
        b = run_mode(e, mode, steps=16, state=0x0BADF00D)
        check(f"{NAMES[mode]}: the same state and tick replay the same notes", a == b)
        tick = struct.unpack(">I", e.read(TICK, 4))[0]
        e.put32(TICK, tick + 1234)
        c = run_mode(e, mode, steps=16, state=0x0BADF00D)
        e.put32(TICK, tick)
        check(f"{NAMES[mode]}: another millisecond, another sequence", c != a)
        z = run_mode(e, mode, steps=16, state=0)
        check(f"{NAMES[mode]}: a zero state still draws within the range", set(z) <= set(RANGE))

    print("\n  edges")
    for mode in (5, 6):
        one = run_mode(e, mode, rng=0, notes=[62], steps=8)
        check(f"{NAMES[mode]}: one note, RNG 0, plays it every step", one == [62] * 8, str(one))
    big = run_mode(e, 5, rng=7, steps=96)
    runs32, whole32 = permutations(big, 32)
    check("SHUF: RNG 7 (32 notes) cycles through all 32, three times",
          whole32 and sorted(runs32[0]) == sorted(n + 12 * o for n in PRESSED for o in range(8)))

    print("\n  mutes, offsets and LEN: offsets +0 +7 -5 +12, steps 3 and 7 muted, LEN 8, RNG 0")
    for mode in (4, 5, 6):                  # CYCL, the stock mode, is the control
        a = run_mode(e, mode, rng=0, length=7, mask=MUTED, offsets=OFFS, steps=16, state=0x5EED)
        b = run_mode(e, mode, rng=0, steps=12, state=0x5EED)
        show(f"{mode} {NAMES[mode]} mutes", a)
        show(f"{mode} {NAMES[mode]} plain", b)
        check(f"{NAMES[mode]}: a muted step rests", all(a[k] == -1 for k in (2, 6, 10, 14)))
        check(f"{NAMES[mode]}: a muted step does not advance, and each step adds its offset",
              played(a, OFFS, 8) == b, f"{played(a, OFFS, 8)} vs {b}")

    bounds(e, menu=((3, 3), (4, 4), (5, 5), (6, 6), (7, 6), (-1, 0)),
           toggle=((3, 3), (4, 4), (5, 5), (6, 6), (7, 6), (0, 1)),
           load=((2, 2), (4, 4), (5, 5), (6, 6), (7, 0)))


def plocks(e, modded):
    """arpplocks' MODE lock, recorded as the menu records it with every step held.

    The menu hands the setter the sound's value plus the knob's delta, and
    arpplocks adds that delta to the lock, so a turn of one detent is the
    sound's MODE (2) + 1 each time, and the lock climbs one per detent.
    """
    ceiling = 6 if modded else 4
    obj = struct.unpack(">I", e.read(HELD, 4))[0]
    if not obj:
        check("arpplocks: the snapshot has a held-trig object", False)
        return
    print("\n  arpplocks: MODE locked from the menu, every step held, sound MODE 2 "
          f"({'with' if modded else 'without'} arpmodes)")
    e.write(obj + HELD_BITS, b"\xff" * 16)
    e.write(obj + HELD_ANY, b"\x01")
    sound = e.alloc(SOUND + 16)
    e.write(sound + MODE, bytes([2]))
    model = e.model(sound)
    for label, turn, detents, want in (
            ("up", +1, 6, [min(2 + k, ceiling) for k in range(1, 7)]),
            ("down", -1, 8, [max(ceiling - k, 0) for k in range(1, 9)])):
        seen = []
        for _ in range(detents):
            e.call(e.labels["ui_mode"], model, 2 + turn)
            seen.append(e.call(e.labels["disp_mode"], model, 0))
        print(f"    {label:>4}: {' '.join(NAMES[v] if 0 <= v < 8 else str(v) for v in seen)}")
        check(f"arpplocks: turning {label}, the MODE lock stops at "
              f"{NAMES[ceiling] if turn > 0 else 'OFF'}", seen == want, f"want {want}")
    check("arpplocks: the sound's own MODE stays 2", e.read(sound + MODE, 1)[0] == 2)
    e.write(obj + HELD_BITS, bytes(16))
    e.write(obj + HELD_ANY, b"\x00")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("snapshot", nargs="?", default=SNAP)
    p.add_argument("--ranges", action="append", default=[],
                   help="a build's changed runs (out/mkranges.py format); repeatable")
    args = p.parse_args()
    e = Emu(args.snapshot, args.ranges)
    modded = e.read(HOOK, 2) == b"\x4e\xf9"
    print(f"image: {'arpmodes' if modded else 'stock'}"
          f"{' + arpplocks' if 'ui_mode' in e.labels else ''};  held, in press order: "
          f"{' '.join(name(n) for n in PRESSED)};  RNG 1 (two octaves), LEN 16, all steps on, "
          "offsets 0\n")
    (mod if modded else stock)(e)
    if "ui_mode" in e.labels:
        plocks(e, modded)

    print(f"\n{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
