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
    def __init__(self, snapshot):
        self.m, *_ = build(snapshot, syx=SYX, unblock=True, softfloat=True, bitmap=True, dsp=True,
                           weakptr=True, slc=True, deferred_components=("timers",))
        self.uc = self.m.uc
        self.ret = STACK + 0x800
        self.at = SCRATCH

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


def run_mode(e, mode, rng=1, length=15, mask=0xFFFF, offsets=None, notes=PRESSED, steps=STEPS):
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


def main(snapshot=SNAP):
    e = Emu(snapshot)
    print(f"held, in press order: {' '.join(name(n) for n in PRESSED)};  "
          f"RNG 1 (two octaves), LEN 16, all steps on, offsets 0\n")

    seqs = {}
    for mode in range(8):
        seqs[mode] = run_mode(e, mode)
        show(f"{mode} {NAMES[mode]}", seqs[mode])
    print()

    c4, e4, g4, b4 = 60, 64, 67, 71
    up = [c4, e4, g4, b4, c4 + 12, e4 + 12, g4 + 12, b4 + 12] * 3
    check("OFF rests every step", all(n == -1 for n in seqs[0]))
    check("TRUE plays press order, then the next octave",
          seqs[1][:8] == [e4, c4, g4, b4, e4 + 12, c4 + 12, g4 + 12, b4 + 12])
    check("UP (control) climbs C E G B, then an octave up", seqs[2] == up[:STEPS])
    check("DOWN falls B G E C", seqs[3][:4] == [b4, g4, e4, c4])
    cycl = seqs[4]
    check("CYCL (control) goes up then down without repeating the turn",
          cycl[:6] == [c4, e4, g4, b4, g4, e4])
    for mode in (5, 6, 7):
        check(f"{NAMES[mode]} ({mode}) is note for note CYCL", seqs[mode] == cycl,
              "same sequence" if seqs[mode] == cycl else "differs")
    neg = run_mode(e, -1)
    check("a negative MODE is CYCL too (the dispatch's default)", neg == cycl)

    print("\n  twice, each from a fresh state: is SHUF / RAND the same every time?")
    for mode in (5, 6):
        again = run_mode(e, mode)
        check(f"{NAMES[mode]} repeats itself exactly (no randomness)", again == seqs[mode])

    print("\n  CHRD with offsets (+0 +7 -5 +12) and steps 3, 7 muted, LEN 8, RNG 0:")
    offs = [0, 7, -5, 12, 0, 7, -5, 12]
    mask = 0xFFFF & ~((1 << 2) | (1 << 6))
    chrd = run_mode(e, 7, rng=0, length=7, mask=mask, offsets=offs, steps=16)
    cyc2 = run_mode(e, 4, rng=0, length=7, mask=mask, offsets=offs, steps=16)
    show("7 CHRD", chrd)
    show("4 CYCL", cyc2)
    check("CHRD one note per step, same as CYCL, with offsets and mutes", chrd == cyc2)
    check("a muted step rests", chrd[2] == -1 and chrd[6] == -1)

    print("\n  the menu edit: setMode(model, v)")
    for v, want in ((3, 3), (4, 4), (5, 4), (6, 4), (7, 4), (-1, 0)):
        sound = e.alloc(SOUND + 16)
        e.write(sound + MODE, bytes([2]))
        e.call(SET_MODE, e.model(sound), v)
        got = e.read(sound + MODE, 1)[0]
        check(f"setMode({v}) writes {want}", got == want, f"wrote {got}")

    print("\n  FUNC+ARP: MODE 0, parked value p at +374 -> restores")
    for p, want in ((3, 3), (4, 4), (6, 4), (0, 1)):
        sound = e.alloc(SOUND + 16)
        e.write(sound + MODE, bytes([0]))
        e.write(sound + PARKED, bytes([p]))
        e.call(TOGGLE, e.model(sound))
        got = e.read(sound + MODE, 1)[0]
        check(f"toggle with parked {p} restores {want}", got == want, f"restored {got}")

    print("\n  SAVE then LOAD a sound with MODE v (stock converters)")
    base = struct.unpack(">I", e.read(0x800052A0, 4))[0]
    real = e.read(base + 52, SOUND) if base else bytes(SOUND)
    for v, want in ((2, 2), (4, 4), (5, 0), (6, 0), (7, 0)):
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

    print(f"\n{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
