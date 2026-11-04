"""v0.39, ERASE MOD DATA under digikit's ColdFire emulator (csrc/sampler/erase.c,
docs/erase-mod-data.md): the gate's check.

    DT2_SECTIONS=../sec111 DT2_MAIN_IMG=../sec111/section_3_MAIN_OS.bin \\
    DNFW_EMU_FLAGS='{"weakptr": false}' ../digikit/.venv/bin/python -u scripts/emu_erase.py \\
        --build out/b --snapshot ../digikit/out/snapshots/dn2-1.11/ui800M-v014.snap \\
        --scenario ui|link|boot --json out/erase-ui.json [--png-dir out/erase]

The +Drive is played by Python, as in the link16 and pools checks: the stock block driver's
three entries (0x4012c59a read, 0x4012c780 write, 0x4012c4b2 TRIM) become `moveq #0,%d0 ;
rts` and a hook does their work first. Every call is logged as the eMMC commands the stock
routine sends for it (CMD18 / CMD25 at the sector; TRIM: CMD35 start, CMD36 start + count
- 1, CMD38 argument 1, the routine's own arithmetic, docs/erase-mod-data.md). The device
is the size of the owner's (Kingston, reconfigured: 48,340,992 sectors) unless a scenario
says otherwise.

Scenarios (each from a fresh machine):

- **ui**: the +Drive filled with data in every mod region, in the stock store, in the
  factory buffer and in the free gaps; the browser opened as a person opens it (the sample
  list, FUNC + YES), then +DRIVE, RIGHT: the menu; YES, NO at the first question; RIGHT,
  YES, YES, NO at the second; LEFT out of the menu: after each, not one command but reads,
  the +Drive byte for byte as it was. Then RIGHT, YES, YES, YES: ERASED. Checked: TRIM
  ranges inside the four regions only, covering each exactly; not one write from the
  first TRIM on (nor after, a setting changed); every byte outside the regions as it was;
  every sector of the regions read back erased; the verify's reads inside the regions; the
  screens; YES closes. The +Drive's state after selected TRIM calls is kept for **boot**.
- **link**: link command 28 (a wrong word refused, nothing done), then "ERASE": ERASED,
  with a card whose erased state reads 0xFF; command 29's reply. Then a card that ignores
  one TRIM (a sector left as it was: NOT ERASED at that sector) and one whose TRIM returns
  an error (TRIM ERROR at its sector), each failing with the exact sector, the screen drawn.
- **link** (v0.41, a unit's "TRIM ERROR AT 817905"): the card's busy line is played too (PRSSTAT
  bit 24, the eSDHC's DAT0 level, read as the stock TRIM reads it). A **flaky card**: some TRIM
  calls return while the card is still programming (stock's DAT0 wait ends early on a stale
  post), and a command sent then gets no answer (CTOE: the call returns -1, nothing erased),
  as does a read; some calls fail once on their own. It must end ERASED, the regions covered
  exactly, no command ever sent while the line says busy. A card that **keeps failing at one
  sector**: ERASE FAILED at that call's sector after 5 tries, and asked again it carries on
  from that call (not from the start) and fails there again. A card that **stays busy**: CARD
  STAYED BUSY, no command sent to it. v0.39's erase fails the first (TRIM ERROR).
- **boot**: a power-on (the mod's boot code, its own RAM fresh) on each kept state: after
  the first TRIM, inside the lists, after every header, inside the pool's frames, inside
  the library's, and after the whole erase -- and on a +Drive the mod never wrote: each
  boots (no fault, its boot done), reads the pool as empty, writes only in its regions;
  the whole erase boots exactly as the never-written +Drive does (the same state, the same
  writes).
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import pathlib
import random
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from emulib.image import differences                           # noqa: E402
from emulib.machine import Machine                             # noqa: E402

BLK_READ, BLK_WRITE, BLK_TRIM = 0x4012C59A, 0x4012C780, 0x4012C4B2
BLK_READY, BLK_SECTORS = 0x4461B68C, 0x4461B6B0
SYSEX_ROUTER, SYSEX_SENDER = 0x4012166E, 0x401233F2
KIT, SOUND_STRIDE = 0x4210C08C, 1163
DEVICE = 48_340_992                     # the Kingston 32 GB part, reconfigured (docs/drive-storage-research.md)
POOL0, POOL_END = 0x600000, 0x6C8001
PL0, PL_END = 0x6D0000, 0x6E0300
SET = 0x6FF000
LIB0, LIB_DATA = 0x700000, 0x700105
STACK_TOP, SENTINEL = 0x46A20000, 0x46A20400
RESULT = SENTINEL + 0x800               # what a stubbed driver entry returns (the hook sets it)
PRSSTAT = 0xFC0CC024                    # the eSDHC's present state: bit 24 DAT0 (v0.41)

failures: list[str] = []
report: dict = {"checks": {}}


def check(name, ok, detail=""):
    report["checks"][name] = {"ok": bool(ok), "detail": detail}
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


def regions(dev):
    return [(POOL0, POOL_END), (PL0, PL_END), (SET, SET + 1), (LIB0, dev)]


def in_regions(s, n, dev):
    return any(a <= s and s + n <= b for a, b in regions(dev))


class Disk:
    """the +Drive: written sectors, and the ranges TRIM erased (read as ERASED)"""

    def __init__(self, dev=DEVICE, erased=0x00):
        self.s: dict[int, bytes] = {}
        self.ks: list[int] = []
        self.dirty = False
        self.trimmed: list[list[int]] = []
        self.dev, self.erased = dev, erased
        self.log: list[tuple] = []           # ("R"|"W"|"T", sector, sectors)
        self.cmds: list[tuple[int, int]] = []    # the eMMC commands, (index, argument)
        self.ignore = None                   # a sector a TRIM leaves as it was (a bad card)
        self.fail_at = None                  # the TRIM call that returns an error
        self.on_trim = None
        # v0.41: the card's busy line (PRSSTAT's DAT0), as PRSSTAT reads and calls see it
        self.busy = 0                        # reads (or calls) the card stays busy for
        self.rng = None                      # a flaky card: early returns, one-off errors
        self.stuck = None                    # a sector whose TRIM always fails
        self.busy_after = None               # the TRIM call after which the card stays busy
        self.while_busy = 0                  # commands sent while the line said busy
        self.prs_reads = 0
        self.busy_seen = 0                   # PRSSTAT reads that found it busy
        self.failed: list[tuple] = []        # ("T"|"R", sector, sectors): calls that returned -1

    def tick(self):
        if self.busy > 0 and self.busy < 1 << 30:
            self.busy -= 1

    def copy(self):
        d = Disk(self.dev, self.erased)
        d.s = dict(self.s)
        d.trimmed = [list(t) for t in self.trimmed]
        d.dirty = True
        return d

    def put(self, sector, data):
        if sector not in self.s:
            self.dirty = True
        self.s[sector] = bytes(data)

    def get(self, sector):
        if sector in self.s:
            return self.s[sector]
        i = bisect.bisect_right([t[0] for t in self.trimmed], sector) - 1
        if i >= 0 and self.trimmed[i][0] <= sector < self.trimmed[i][1]:
            return bytes([self.erased]) * 512
        return bytes(512)

    def trim(self, s, n):
        if self.dirty:
            self.ks = sorted(self.s)
            self.dirty = False
        i = bisect.bisect_left(self.ks, s)
        j = bisect.bisect_left(self.ks, s + n)
        for k in self.ks[i:j]:
            if k != self.ignore:
                del self.s[k]
        self.ks[i:j] = [k for k in self.ks[i:j] if k == self.ignore]
        if self.trimmed and self.trimmed[-1][1] == s:
            self.trimmed[-1][1] = s + n
        else:
            self.trimmed.append([s, s + n])
            self.trimmed.sort()
        if self.ignore is not None and s <= self.ignore < s + n and self.ignore not in self.s:
            pass


def install(a, machine):
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    snap_image = pathlib.Path(a.snapshot + ".section_3_MAIN_OS.bin")
    if snap_image.exists():
        back = [(va, stock[va - 0x40000400:va - 0x40000400 + len(b)]) for va, b in
                differences(stock, snap_image.read_bytes()) if va + len(b) <= 0x40000400 + len(stock)]
        machine.apply(back)
    image = (pathlib.Path(a.build) / "section_3_MAIN_OS.bin").read_bytes()
    machine.apply(differences(stock, image))
    sys.path.insert(0, str(HERE.parent / "src"))
    from dnfw.mods import platform                         # noqa: PLC0415
    for va, blob in platform.runtime(image):
        machine.write(va, blob)
    # the sample link's 5 MB RAM window (SMP_MIRROR) is DDR on the unit; the snapshot maps
    # only the pages stock touched (as emu_slides.py)
    from unicorn import UC_PROT_ALL, UcError
    from dnfw.sampler import machines as SMx                # noqa: PLC0415
    for page in range(SMx.MIRROR, SMx.MIRROR + 0x500000, 0x100000):
        try:
            machine.uc.mem_map(page, 0x100000, UC_PROT_ALL)
        except UcError:
            pass
    machine.flush()


def harness(a, disk, ready=True):
    """-> a machine with the build in, the +Drive played by DISK"""
    from unicorn import UC_HOOK_CODE
    from unicorn import m68k_const as K
    machine = Machine(a.snapshot)
    uc = machine.uc
    install(a, machine)
    state = {"disk": disk, "calls": 0}

    def blk(uc_, address, size, user):
        d = state["disk"]
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        try:
            if address == BLK_TRIM:
                s, n = struct.unpack(">2I", bytes(uc.mem_read(sp + 4, 8)))
                state["calls"] += 1
                if d.busy > 0:                  # v0.41: the card still programming: CMD35 unanswered
                    d.while_busy += 1
                    d.tick()
                    d.cmds.append((35, s))
                    d.failed.append(("T", s, n))
                    uc.mem_write(RESULT, struct.pack(">i", -1))
                    return
                once = d.rng is not None and d.rng.random() < 1 / 60
                if (d.fail_at is not None and state["calls"] == d.fail_at) or once \
                        or (d.stuck is not None and s <= d.stuck < s + n):
                    d.cmds.append((35, s))
                    d.failed.append(("T", s, n))
                    uc.mem_write(RESULT, struct.pack(">i", -1))               # no answer (CTOE)
                    return
                d.log.append(("T", s, n))
                d.cmds += [(35, s), (36, (s + n - 1) & 0xFFFFFFFF), (38, 1)]   # 0x4012c4b2's own
                if d.rng is not None and d.rng.random() < 1 / 20:
                    # returned early: still programming, briefly, or for longer than a pass's look
                    d.busy = d.rng.randrange(1, 8) if d.rng.random() < 0.7 else d.rng.randrange(5000, 9000)
                if d.busy_after is not None and state["calls"] >= d.busy_after:
                    d.busy = 1 << 30
                uc.mem_write(RESULT, bytes(4))
                d.trim(s, n)
                if d.on_trim:
                    d.on_trim(state["calls"], s, n)
                return
            uc.mem_write(RESULT, bytes(4))
            s, nbytes, buf = struct.unpack(">3I", bytes(uc.mem_read(sp + 4, 12)))
            n = nbytes // 512
            if address == BLK_READ and d.busy > 0:
                d.while_busy += 1
                d.tick()
                d.failed.append(("R", s, n))
                uc.mem_write(RESULT, struct.pack(">i", -1))
                return
            if address == BLK_READ:
                d.log.append(("R", s, n))
                d.cmds.append((18, s))
                uc.mem_write(buf, b"".join(d.get(s + k) for k in range(n)))
            else:
                d.log.append(("W", s, n))
                d.cmds.append((25, s))
                data = bytes(uc.mem_read(buf, nbytes))
                for k in range(n):
                    d.put(s + k, data[512 * k:512 * k + 512])
        except Exception as e:                  # noqa: BLE001 -- the report says
            state.setdefault("errors", []).append(repr(e)[:200])
    # each entry becomes move.l RESULT,%d0 ; rts, and the hook does its work (and sets RESULT) first
    machine.write(RESULT, bytes(4))
    for va in (BLK_READ, BLK_WRITE, BLK_TRIM):
        machine.write(va, bytes.fromhex("2039") + struct.pack(">I", RESULT) + bytes.fromhex("4e75"))
        uc.hook_add(UC_HOOK_CODE, blk, begin=va, end=va)
    machine.write(BLK_READY, struct.pack(">I", 1 if ready else 0))
    machine.write(BLK_SECTORS, struct.pack(">I", disk.dev))
    # v0.41: PRSSTAT (0xfc0cc024) as the card's busy line says: DAT0 (bit 24) low while busy,
    # no inhibit (bits 0, 1) -- each read is time passing
    from unicorn import UC_HOOK_MEM_READ

    def prs(uc_, typ, address, size, value, user):
        d = state["disk"]
        d.prs_reads += 1
        busy = d.busy > 0
        d.busy_seen += busy
        d.tick()
        v = struct.unpack(">I", bytes(uc.mem_read(PRSSTAT, 4)))[0] & ~3
        uc.mem_write(PRSSTAT, struct.pack(">I", (v & ~(1 << 24)) if busy else (v | 1 << 24)))
    uc.hook_add(UC_HOOK_MEM_READ, prs, begin=PRSSTAT, end=PRSSTAT + 3)
    machine.flush()
    return machine, state


def fill(disk, rng):
    """mod data in every region; stock data, the factory buffer and the gaps around them"""
    def junk():
        return bytes(rng.randrange(1, 255) for _ in range(512))
    mod = [POOL0, POOL0 + 1, POOL0 + 2, POOL0 + 777, 0x6C8000, PL0, PL0 + 1, PL0 + 2, 0x6D00FF, 0x6D0100, 0x6D0101,
           0x6D0100 + 256 * 7, 0x6D0100 + 256 * 257, 0x6E02FF, SET, LIB0, LIB0 + 1, LIB0 + 256, 0x700104, LIB_DATA,
           LIB_DATA + 1, disk.dev - 2049, disk.dev - 1] + [s for s in (0x800000, 0x1000000) if s < disk.dev]
    mod += [rng.randrange(POOL0, POOL_END) for _ in range(60)] + [rng.randrange(LIB0, disk.dev) for _ in range(60)]
    other = [0x0, 0x800, 0x1000, 0x2000, 0x58000, 0x457FFF, 0x458000, 0x500000, 0x5D7FFF, 0x5D8000, 0x5FFFFF,
             0x6C8001, 0x6CFFFF, 0x6E0300, 0x6FEFFF, 0x6FF001, 0x6FFFFF]
    other += [rng.randrange(0, 0x600000) for _ in range(60)]
    for s in mod + other:
        disk.put(s, junk())
    return sorted(set(mod)), sorted(set(other))


def guest_call(machine, fn, *args, limit=50_000_000):
    """FN called in the paused machine, every register put back (as emu_waverider_menu.py's
    guest_call); the fast stepper's budget lifted for the call. -> d0"""
    from unicorn import m68k_const as K
    uc = machine.uc
    regs = [getattr(K, f"UC_M68K_REG_{r}{i}") for r in "DA" for i in range(8)]
    saved = [uc.reg_read(r) for r in regs]
    saved_pc = uc.reg_read(K.UC_M68K_REG_PC)
    sp = STACK_TOP - 0x100
    machine.write(sp, struct.pack(">I", SENTINEL) + b"".join(struct.pack(">I", x & 0xFFFFFFFF) for x in args))
    machine.write(SENTINEL, bytes.fromhex("4e714e71"))
    uc.reg_write(K.UC_M68K_REG_A7, sp)
    stepper = getattr(machine.m, "_fast_stepper_obj", None)
    if stepper is not None:
        stepper.left = 1 << 40
    try:
        uc.emu_start(fn, SENTINEL, count=limit)
    finally:
        if stepper is not None:
            stepper.left = 0
        d0 = uc.reg_read(K.UC_M68K_REG_D0)
        for r, v in zip(regs, saved):
            uc.reg_write(r, v)
        uc.reg_write(K.UC_M68K_REG_PC, saved_pc)
    return d0


def faults(machine):
    got = list(getattr(machine.m, "faults", []))
    for f in got:
        report.setdefault("fault_records", []).append(repr(f)[:300])
    return got


def browser(machine, panel, lay, SMx):
    """the sample list, then FUNC + YES: the browser on its two stores (the gate's drive
    step's own key sequence, ship_gate.py 6l)"""
    from emulib.panel import YES
    put = lambda va, v: machine.write(va, struct.pack(">I", v))          # noqa: E731
    seen = report.setdefault("lead_in", [])

    def note(what):
        seen.append({"at": what, **{k: struct.unpack(">i", machine.read(lay[k], 4))[0] for k in
                     ("smp_booted", "smp_dir_ok", "smp_lst_open", "smp_fb_open", "smp_fb_store")}})
        print("  lead-in", seen[-1], flush=True)
    panel.settle(2_000_000)
    for t in range(16):
        machine.write(KIT + 52 + SOUND_STRIDE * t + 0xDE, b"\x08")
    for t in range(16):
        machine.write(KIT + 52 + SOUND_STRIDE * t + 0x6A, bytes([2, 0]))
    d = bytearray(0x1000)
    struct.pack_into("<II", d, 0, 0x31504D53, 4)
    struct.pack_into("<IIfI", d, 8, 0x84001000, 48000, 1.0, 1)
    d[0x808:0x80C] = b"KICK"
    machine.write(SMx.MIRROR, bytes(d[:0xC10]))
    put(lay["smp_dir_ok"], 1)
    panel.settle(6_000_000)
    panel.tap((0, 1))                                            # SRC: the track's page
    panel.settle(6_000_000)
    note("SRC")
    put(lay["smp_periods"], 0)
    put(lay["smp_pos_at"], 0)
    panel.settle(12_000_000)
    panel.tap((0, 1))
    panel.settle(6_000_000)
    for t in range(16):
        machine.write(KIT + 52 + SOUND_STRIDE * t + 0x6A, bytes([3, 0]))
    put(lay["smp_overlay_dirty"], 1)
    panel.settle(10_000_000)
    guest_call(machine, lay["smp_quant"], KIT + 52, SMx.RECORDS[SMx.SAMP_REC][0], 2 << 8)   # SAMP turned: the list
    machine.write(KIT + 52 + 0x6A, bytes([2, 0]))
    put(lay["smp_overlay_dirty"], 1)
    panel.settle(10_000_000)
    note("SAMP turned")
    panel.hold((2, 0), 2_000_000)                               # FUNC + YES
    panel.tap(YES)
    panel.let_go((2, 0), 8_000_000)
    note("FUNC + YES")
    panel.screen("erase_lead_in")


def run_ui(a, lay, SMx):
    from emulib.panel import LEFT, NO, RIGHT, UP, YES, Panel
    rng = random.Random(39)
    disk = Disk()
    mod, other = fill(disk, rng)
    machine, st = harness(a, disk, ready=False)                 # (as the drive step's machine)
    panel = Panel(machine, png_dir=a.png_dir or "out/erase")
    i32 = lambda n: struct.unpack(">i", machine.read(lay[n], 4))[0]          # noqa: E731
    f0 = len(faults(machine))
    panel.settle(20_000_000)
    browser(machine, panel, lay, SMx)
    machine.write(BLK_READY, struct.pack(">I", 1))              # the +Drive up from here on
    panel.settle(4_000_000)
    check("the browser opens on its two stores", i32("smp_fb_open") == 1 and i32("smp_fb_store") == -1,
          f"open {i32('smp_fb_open')}, store {i32('smp_fb_store')}")
    if i32("smp_fb_cur") != 0:
        panel.tap(UP, after=4_000_000)                          # +DRIVE
    before = {s: disk.get(s) for s in mod + other}
    mark = len(disk.log)

    def nothing(what):
        new = [x for x in disk.log[mark:] if x[0] != "R"]
        same = all(disk.get(s) == b for s, b in before.items())
        check(f"{what}: nothing erased or written", not new and same and i32("smp_er_lock") == 0
              and i32("smp_er_state") == 0, f"{len(new)} command(s), the +Drive {'as it was' if same else 'CHANGED'}")
    panel.tap(RIGHT, after=6_000_000)
    report["screens"] = {"menu": panel.screen("erase_menu")}
    check("+DRIVE, RIGHT: the ERASE MOD DATA menu", i32("smp_fb_menu") == 3, f"menu {i32('smp_fb_menu')}")
    panel.tap(YES, after=6_000_000)
    report["screens"]["ask1"] = panel.screen("erase_ask1")
    check("YES: the first question", i32("smp_fb_menu") == 4)
    panel.tap(NO, after=6_000_000)
    check("NO at the first question closes it", i32("smp_fb_menu") == 0 and i32("smp_fb_open") == 1)
    nothing("NO at the first question")
    panel.tap(RIGHT, after=4_000_000)
    panel.tap(YES, after=4_000_000)
    panel.tap(YES, after=6_000_000)
    report["screens"]["ask2"] = panel.screen("erase_ask2")
    check("YES, YES: the second question", i32("smp_fb_menu") == 5)
    panel.tap(NO, after=6_000_000)
    check("NO at the second question closes it", i32("smp_fb_menu") == 0)
    nothing("NO at the second question")
    panel.tap(RIGHT, after=4_000_000)
    panel.tap(LEFT, after=4_000_000)
    check("LEFT leaves the menu", i32("smp_fb_menu") == 0)
    nothing("LEFT out of the menu")

    # the erase, with the +Drive kept after selected TRIM calls (the boot scenario's)
    keep = {1: "after the pool's header", 12: "inside the lists", 34: "after the lists",
            36: "after every header", 200: "inside the pool's frames", 2000: "inside the library's frames"}
    kept = {}

    def on_trim(k, s, n):
        if k in keep:
            kept[keep[k]] = disk.copy()
    disk.on_trim = on_trim
    mark = len(disk.log)
    panel.tap(RIGHT, after=4_000_000)
    panel.tap(YES, after=4_000_000)
    panel.tap(YES, after=4_000_000)
    panel.tap(YES, after=4_000_000)
    report["screens"]["erasing"] = panel.screen("erase_running")
    for k in range(400):
        if i32("smp_er_state") in (3, 4) or (k >= 3 and i32("smp_er_state") == 0):
            break
        panel.settle(10_000_000)
    panel.settle(6_000_000)
    report["screens"]["done"] = panel.screen("erase_done")
    stt, err = i32("smp_er_state"), i32("smp_er_err")
    report.update(state=stt, err=err, trims=i32("smp_er_trims"), reads=i32("smp_er_reads"),
                  verified=[i32("smp_er_checks"), i32("smp_er_nchecks")], sector=f"{i32('smp_er_sector') & 0xFFFFFFFF:#x}")
    check("three YES: ERASED", stt == 3 and err == 0, f"state {stt}, err {err}, sector {report['sector']}")
    log = disk.log[mark:]
    trims = [(s, n) for k, s, n in log if k == "T"]
    writes = [(s, n) for k, s, n in log if k == "W"]
    reads = [(s, n) for k, s, n in log if k == "R"]
    first_t = next((i for i, x in enumerate(log) if x[0] == "T"), None)
    report["commands"] = {"trims": len(trims), "writes": len(writes), "reads": len(reads),
                          "cmd35": sum(1 for c, _ in disk.cmds if c == 35), "cmd38": sum(1 for c, _ in disk.cmds if c == 38),
                          "first_trims": [f"{s:#x}+{n}" for s, n in trims[:6]], "last_trim": f"{trims[-1][0]:#x}+{trims[-1][1]}" if trims else None}
    check("every TRIM inside one of the four regions, never below 0x600000, at most 2,048 sectors",
          trims and all(in_regions(s, n, DEVICE) and s >= POOL0 and 1 <= n <= 2048 for s, n in trims),
          f"{len(trims)} TRIM calls")
    cover = sorted(trims)
    merged = []
    for s, n in cover:
        if merged and merged[-1][1] == s:
            merged[-1][1] = s + n
        elif merged and merged[-1][1] > s:
            merged.append(["OVERLAP", s])
        else:
            merged.append([s, s + n])
    want = [[POOL0, POOL_END], [PL0, PL_END], [SET, SET + 1], [LIB0, DEVICE]]
    check("the TRIMs cover exactly the four regions, each sector once",
          merged == want, f"{[[hex(x) if isinstance(x, int) else x for x in m] for m in merged]}")
    order = [s for s, _ in trims[:36]]
    check("headers first: the pool's, the lists' region, the settings, the library's headers, then the frames",
          order[0] == POOL0 and order[1] == PL0 and SET in order[:36] and LIB0 in order[:36]
          and trims[35] == (LIB0, LIB_DATA - LIB0) and trims[36][0] == POOL0 + 1, str([hex(x) for x in order[:3]]))
    check("not one write from the first TRIM on", first_t is not None and not [x for x in log[first_t:] if x[0] == "W"],
          f"{len(writes)} write(s) in all")
    check("the verify's reads inside the regions", reads and all(in_regions(s, n, DEVICE) for s, n in reads),
          f"{len(reads)} read(s)")
    check("every byte outside the regions as it was", all(disk.get(s) == before[s] for s in other),
          f"{len(other)} sectors: the stock store, the factory buffer, the gaps")
    bad = [hex(s) for s in mod if disk.get(s) != bytes(512)]
    check("every written sector of the regions reads erased", not bad, f"{len(mod)} sectors, {bad[:4]}")
    check("the commands: CMD35, CMD36, CMD38(1) for each TRIM",
          report["commands"]["cmd35"] == len(trims) == report["commands"]["cmd38"]
          and all(arg == 1 for c, arg in disk.cmds if c == 38))
    kept["after the whole erase"] = disk.copy()
    # a setting changed now: nothing written (the latch until power-off)
    mark2 = len(disk.log)
    machine.write(lay["jmp_dirty"], b"\x01")
    panel.settle(10_000_000)
    check("after it, a setting changed: not written (nothing of ours writes until a restart)",
          not [x for x in disk.log[mark2:] if x[0] != "R"] and i32("smp_er_lock") == 1)
    panel.tap(YES, after=6_000_000)
    check("YES closes the result", i32("smp_fb_open") == 0)
    check("no fault", len(faults(machine)) == f0, f"{len(faults(machine)) - f0}")
    check("no driver hook error", not st.get("errors"), str(st.get("errors"))[:200])
    return kept


def sysex(machine, uc, K, cmd, payload, seq=7):
    raw = [seq >> 8, seq & 0xFF, cmd] + list(payload)
    out, i = [], 0
    while i < len(raw):
        grp = raw[i:i + 7]
        top = 0
        for k, b in enumerate(grp):
            if b & 0x80:
                top |= 0x40 >> k
        out += [top] + [b & 0x7F for b in grp]
        i += 7
    msg = bytes([0xF0, 0x00, 0x20, 0x3C, 0x7D, 0x01] + out + [0xF7])
    buf = SENTINEL + 0x1000
    sent = []

    def at_sender(uc_, address, size, user):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        b, n, _ab, port = struct.unpack(">4I", bytes(uc.mem_read(sp + 4, 16)))
        sent.append(bytes(uc.mem_read(b, n)))
    from unicorn import UC_HOOK_CODE
    h = uc.hook_add(UC_HOOK_CODE, at_sender, begin=SYSEX_SENDER, end=SYSEX_SENDER)
    machine.write(buf, msg)
    guest_call(machine, SYSEX_ROUTER, buf, len(msg), 2)
    uc.hook_del(h)
    if not sent:
        return None
    body, j = sent[-1][6:-1], 0
    got = []
    while j < len(body):
        top = body[j]
        for k in range(1, 8):
            if j + k >= len(body):
                break
            got.append(body[j + k] | (0x80 if top & (0x40 >> (k - 1)) else 0))
        j += 8
    return got


def covered(trims, dev):
    """v0.41: the TRIMs that went through cover exactly the four regions (a range may be sent
    again only after it failed, so each still once)"""
    merged = []
    for s, n in sorted(trims):
        if merged and merged[-1][1] == s:
            merged[-1][1] = s + n
        elif merged and merged[-1][1] > s:
            return False
        else:
            merged.append([s, s + n])
    return merged == [[a, b] for a, b in regions(dev)]


def run_link(a, lay, SMx):
    from unicorn import m68k_const as K
    from emulib.panel import NO, Panel
    out = {}
    STUCK = LIB_DATA + 2048 * 100 + 5
    for name, dev, erased, ignore, fail_at in (("erased 0xFF", 0x900000, 0xFF, None, None),
                                               ("a sector left as it was", 0x900000, 0x00, LIB0, None),
                                               ("a TRIM error", 0x900000, 0x00, None, 40),
                                               ("a flaky card", 0xA00000, 0x00, None, None),
                                               ("a card failing at one sector", 0x900000, 0x00, None, None),
                                               ("a card that stays busy", 0x900000, 0x00, None, None)):
        rng = random.Random(7)
        disk = Disk(dev, erased)
        mod, other = fill(disk, rng)
        disk.ignore, disk.fail_at = ignore, fail_at
        if name == "a flaky card":
            disk.rng = random.Random(41)
        elif name == "a card failing at one sector":
            disk.stuck = STUCK
        elif name == "a card that stays busy":
            disk.busy_after = 50
        machine, st = harness(a, disk)
        panel = Panel(machine, png_dir=a.png_dir or "out/erase")
        i32 = lambda n: struct.unpack(">i", machine.read(lay[n], 4))[0] if n in lay else 0     # noqa: E731 (v0.41's counters: 0 on v0.39)
        f0 = len(faults(machine))
        panel.settle(20_000_000)
        mark = len(disk.log)
        r = sysex(machine, machine.uc, K, 28, b"ERASX")
        panel.settle(10_000_000)
        if name == "erased 0xFF":
            check("link 28 with a wrong word: refused, nothing done",
                  r is not None and r[2] == 28 | 0x80 and r[3] == 1 and i32("smp_er_state") == 0
                  and not [x for x in disk.log[mark:] if x[0] != "R"], str(r[:4] if r else r))
        r = sysex(machine, machine.uc, K, 28, b"ERASE")
        ok28 = r is not None and r[3] == 0
        machine.write(lay["smp_fb_open"], struct.pack(">I", 1))      # (the browser up: the screen shows it)
        for _ in range(600):
            if i32("smp_er_state") in (3, 4):
                break
            panel.settle(10_000_000)
        panel.settle(6_000_000)
        shot = panel.screen("erase_link_" + name.replace(" ", "_").replace("0x", ""))
        r29 = sysex(machine, machine.uc, K, 29, b"")
        stt, err, sec = i32("smp_er_state"), i32("smp_er_err"), i32("smp_er_sector") & 0xFFFFFFFF
        trims = [(s, n) for k, s, n in disk.log if k == "T"]
        writes = [x for x in disk.log[mark:] if x[0] == "W"]
        out[name] = {"state": stt, "err": err, "sector": hex(sec), "reply29": r29[:24] if r29 else None, "screen": shot}
        safe = all(in_regions(s, n, dev) for s, n in trims) and not writes \
            and all(disk.get(s) == b for s, b in [(s, disk.get(s)) for s in other])
        if name == "erased 0xFF":
            st29 = r29 is not None and r29[4] == 3 and r29[5] == 0
            check("link 28 \"ERASE\": ERASED, on a card whose erased state reads 0xFF; 29 reports it",
                  ok28 and stt == 3 and st29 and safe and all(disk.get(s) == b"\xff" * 512 for s in mod),
                  f"state {stt}, reply {r29[:6] if r29 else None}")
        elif ignore is not None:
            check("a card that leaves a sector: NOT ERASED at that sector, shown",
                  stt == 4 and err == 4 and sec == ignore and safe, f"state {stt}, err {err}, sector {sec:#x}")
        elif name == "a TRIM error":
            # v0.41: a call that fails once is tried again after a pause, and the erase ends ERASED
            check("a TRIM that fails once: tried again, ERASED, the regions covered exactly",
                  stt == 3 and err == 0 and safe and covered(trims, dev) and len(disk.failed) == 1
                  and i32("smp_er_retries") == 1 and all(disk.get(s) == bytes(512) for s in mod),
                  f"state {stt}, err {err}, sector {sec:#x}, {len(disk.failed)} failed call(s), "
                  f"{i32('smp_er_retries')} retried")
        elif name == "a flaky card":
            out[name].update(failed=len(disk.failed), while_busy=disk.while_busy, prs_reads=disk.prs_reads,
                             retries=i32("smp_er_retries"), waits=i32("smp_er_waits"), trims=len(trims))
            check("a flaky card (TRIMs returning while it programs, one-off errors): ERASED, the "
                  "regions covered exactly, every sector erased",
                  stt == 3 and err == 0 and safe and covered(trims, dev)
                  and all(disk.get(s) == bytes(512) for s in mod),
                  f"state {stt}, err {err}, sector {sec:#x}, {len(trims)} TRIMs, {len(disk.failed)} failed, "
                  f"{i32('smp_er_retries')} retried, {i32('smp_er_waits')} busy waits")
            check("a flaky card: no command sent while its busy line was low; the waits and the one-off "
                  "errors both seen",
                  disk.while_busy == 0 and disk.busy_seen > 0 and i32("smp_er_waits") > 0 and i32("smp_er_retries") > 0,
                  f"{disk.while_busy} sent while busy, busy seen {disk.busy_seen} times, {i32('smp_er_waits')} passes "
                  f"waited, {i32('smp_er_retries')} retries")
        elif name == "a card failing at one sector":
            first = next((k for k in range(len(trims)) if trims[k][0] <= STUCK < trims[k][0] + trims[k][1]), None)
            call0 = STUCK - (STUCK - LIB_DATA) % 2048
            tries1 = sum(1 for k, s0, n0 in disk.failed if k == "T" and s0 == call0)
            check("a card failing at one sector: ERASE FAILED (CARD ERASE FAILED) at that call's sector "
                  "after 5 tries, shown; 29 says asking again carries on",
                  stt == 4 and err == 2 and sec == call0 and tries1 == 5 and first is None and safe
                  and r29 is not None and len(r29) >= 53 + 4 and r29[4 + 52] == 1,
                  f"state {stt}, err {err}, sector {sec:#x} (want {call0:#x}), {tries1} tries, "
                  f"resume {r29[4 + 52] if r29 and len(r29) > 56 else None}")
            n_t = len(trims)
            mark_again = len(disk.log)
            r = sysex(machine, machine.uc, K, 28, b"ERASE")
            for _ in range(200):
                panel.settle(10_000_000)
                if i32("smp_er_state") in (3, 4):
                    break
            again = [(s0, n0) for k, s0, n0 in disk.log[mark_again:] if k == "T"]
            tries2 = sum(1 for k, s0, n0 in disk.failed if k == "T" and s0 == call0)
            check("asked again: it carries on at the failing call (no TRIM from the start again), and "
                  "fails there again",
                  r is not None and r[3] == 0 and i32("smp_er_state") == 4 and i32("smp_er_err") == 2
                  and not again and tries2 == 10 and len([x for x in disk.log if x[0] == "T"]) == n_t,
                  f"state {i32('smp_er_state')}, {len(again)} new TRIM(s), {tries2} tries in all")
            panel.screen("erase_link_failing_again")
            panel.tap(NO, after=6_000_000)
            check("a failure seen and closed: it may be asked again (the state idle, the lock kept)",
                  i32("smp_er_state") == 0 and i32("smp_er_lock") == 1 and i32("smp_fb_open") == 0)
        else:
            check("a card that stays busy: CARD STAYED BUSY, no command sent to it while busy",
                  stt == 4 and err == 6 and disk.while_busy == 0 and safe,
                  f"state {stt}, err {err}, sector {sec:#x}, {disk.while_busy} sent while busy, "
                  f"{len(trims)} TRIMs")
        check(f"{name}: no fault", len(faults(machine)) == f0 and not st.get("errors"))
    report["link"] = out


def boot_once(a, lay, disk):
    """a power-on of the mod on DISK: its RAM fresh (the build installed again), its boot run"""
    machine, st = harness(a, disk)
    from emulib.panel import Panel
    panel = Panel(machine, png_dir=a.png_dir or "out/erase")
    i32 = lambda n: struct.unpack(">i", machine.read(lay[n], 4))[0]          # noqa: E731
    f0 = len(faults(machine))
    mark = len(disk.log)
    for _ in range(12):
        panel.settle(5_000_000)
        if i32("smp_booted") == 1:                              # the DSP's RAM check never answers here:
            machine.write(lay["smp_periods"], struct.pack(">I", 1_000_000))     # its four seconds pass
        if i32("smp_booted") == 2:
            break
    panel.settle(20_000_000)
    log = disk.log[mark:]
    res = {"booted": i32("smp_booted"), "dir_ok": i32("smp_dir_ok"), "hi": i32("smp_hi"),
           "lib": i32("smp_lib_state"), "pl_on": i32("smp_pl_on"), "pl_case": i32("smp_pl_boot_case"),
           "jmp_on": machine.read(lay["jmp_on"], 1)[0], "faults": len(faults(machine)) - f0,
           "errors": st.get("errors"),
           "writes": [(s, n, disk.get(s).hex()[:16]) for k, s, n in log if k == "W"],
           "outside": [(k, hex(s), n) for k, s, n in log if not in_regions(s, n, disk.dev) and s >= 0x600000],
           "low_writes": [(k, hex(s), n) for k, s, n in log if k != "R" and s < 0x600000]}
    return res


def run_boot(a, lay, SMx, kept):
    rows = {}
    never = boot_once(a, lay, Disk())
    rows["a +Drive the mod never wrote"] = never
    for name, d in kept.items():
        d.log, d.cmds, d.on_trim = [], [], None
        rows[name] = boot_once(a, lay, d)
    for name, r in rows.items():
        ok = (r["faults"] == 0 and not r["errors"] and r["booted"] == 2 and r["dir_ok"] == 0
              and not r["outside"] and not r["low_writes"])
        check(f"power-on {name}: boots, the pool empty, writes only in its regions", ok,
              f"booted {r['booted']}, dir_ok {r['dir_ok']}, lib {r['lib']}, lists case {r['pl_case']}, "
              f"jump {r['jmp_on']}, {len(r['writes'])} write(s), faults {r['faults']}, outside {r['outside'][:2]}")
    full = rows.get("after the whole erase")
    if full is not None:
        keys = ("booted", "dir_ok", "hi", "lib", "pl_on", "pl_case", "jmp_on", "writes")
        diff = [k for k in keys if full[k] != never[k]]
        check("after the whole erase it boots exactly as on a +Drive the mod never wrote (fresh install)",
              not diff, f"differs in {diff}")
    report["boot"] = {k: {kk: vv for kk, vv in v.items() if kk != "writes"} | {"writes": len(v["writes"])}
                      for k, v in rows.items()}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--scenario", choices=("ui", "link", "boot", "all"), default="all")
    p.add_argument("--json", default=None)
    p.add_argument("--png-dir", default=None)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    a = p.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    sys.path.insert(0, str(HERE.parent / "src"))
    from dnfw.sampler import machines as SMx                    # noqa: PLC0415
    kept = {}
    if a.scenario in ("ui", "boot", "all"):
        kept = run_ui(a, lay, SMx)
        if a.scenario in ("boot", "all"):
            # (the whole erase: the ui run's +Drive at its end is the last kept state's, erased on)
            pass
    if a.scenario in ("link", "all"):
        run_link(a, lay, SMx)
    if a.scenario in ("boot", "all"):
        run_boot(a, lay, SMx, kept)
    report["failures"] = failures
    report["ok"] = not failures
    print(json.dumps({k: v for k, v in report.items() if k not in ("checks",)}, indent=1, default=str)[:4000])
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1, default=str) + "\n")
    print(f"erase ({a.scenario}): {'PASS' if not failures else 'FAIL ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
