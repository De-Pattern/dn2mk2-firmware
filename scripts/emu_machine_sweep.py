"""Every machine through MACHINE SEL's own list, and every track of ours drawn: the check
v0.44's BOUNCE freeze went through.

    DT2_SYX=.. DT2_SECTIONS=../sec111 DT2_MAIN_IMG=../sec111/section_3_MAIN_OS.bin \\
    DNFW_EMU_FLAGS='{"weakptr": false}' ../digikit/.venv/bin/python -u \\
        scripts/emu_machine_sweep.py --snapshot BOOTED.snap --stock ../sec111/section_3_MAIN_OS.bin \\
        --mod-types 5,...,18 --list 0,2,1,3,5,...,4 [--png-dir DIR] [--json OUT]

**The snapshot is the build's own boot, not ui800M-v014.** MACHINE SEL builds its rows once,
at boot (constructor 0x4005b6de -> row builder 0x4005b2c0), so a snapshot booted on another
build shows that build's list whatever is installed over it: ui800M-v014 shows v0.14's rows, no
SLICE, no BOUNCE, and no emulator step ever picked BOUNCE through the real list. BOOTED.snap is
scripts/emu_machine_boot.py's: `boot400M` with this build installed before the views are built,
our machine types put on the kit's tracks at the UI's first draw, saved at 800M.

**The unit's freeze, made visible.** v0.44 froze the unit with no EXCEPTION screen: on a BOUNCE
track the label lookup (pages.py wr_label) indexed past the Monomachine's label tables and
walked absolute address 0x000000EE as a table. The emulator maps low memory as zero RAM, so
there the walk met a 0 at once and the page drew; the unit has no RAM there, and hung. So here
**any read below 0x40000000 by code that is not stock's** (our chunks, an edited stock site)
fails, with its PC and callers (stock's one boot-time byte read at 0x400cecf2 is stock's); so
does the firmware's EXCEPTION reporter, and a page or menu that does not change the screen.

- **tracks** (`--mod-types`): each track whose machine is one of ours made active ([TRK] +
  [TRIG n]) and its FLTR page (stock cells: every label through wr_label) and SYN page drawn.
- **sweep** (`--list`, coldfire.LIST_NEW): MACHINE SEL on the active track, the cursor walked to
  the top, then each row in order picked with YES (the track's sound+0xDE must become that
  type), NO (the menu must close), FLTR and SYN drawn.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys

HERE = pathlib.Path(os.environ.get("DNFW_SCRIPTS", pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(HERE))

from emulib.machine import Machine                              # noqa: E402
from emulib.panel import DOWN, NO, UP, YES, Panel               # noqa: E402

FUNC, SRC, FLTR = (2, 0), (0, 1), (0, 2)    # codes 17, 2, 3
TRK, TRIG1 = (1, 7), 25                     # [TRK] code 16; [TRIG 1..16] codes 25..40
KIT = 0x800052A0                            # the live kit; sound t at + 52 + 1163 t
SOUND_TYPE = 0xDE
ACTIVE = 0x42431A6C                         # the UI's active track (byte)
REDRAW = 0x4011D32A                         # the UI loop's draw of every view on its screen
REPORTER = 0x4011EA6A                       # the firmware's EXCEPTION reporter
LOW_END = 0x3FFFFFFF                        # below DDR: nothing of ours may read here


class Run:
    def __init__(self, snapshot, stock, png_dir):
        self.m = Machine(snapshot)
        self.uc = self.m.uc
        # a saved snapshot keeps only the regions the emulator mapped itself: the platform
        # loader's RAM copies (our CODE chunks) are not in it, so they go back where the loader
        # put them, as every snapshot harness does (emu_waverider_menu.py); their data and BSS
        # start again from the image
        image = pathlib.Path(snapshot + ".section_3_MAIN_OS.bin").read_bytes()
        if len(image) > len(stock):
            sys.path.insert(0, str(HERE.parent / "src"))
            from dnfw.mods import platform       # noqa: PLC0415
            for va, blob in platform.runtime(image):
                self.m.write(va, blob)
            self.m.flush()
        self.stock = stock
        self.panel = Panel(self.m, png_dir=png_dir)
        self.low, self.faults, self.poke, self.low_steps = [], [], None, {}
        from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ
        from unicorn import m68k_const as K
        self.K = K
        self.uc.hook_add(UC_HOOK_MEM_READ, self._low, begin=0, end=LOW_END)
        self.uc.hook_add(UC_HOOK_CODE, self._reporter, begin=REPORTER, end=REPORTER)
        self.uc.hook_add(UC_HOOK_CODE, self._redraw, begin=REDRAW, end=REDRAW)

    def _low(self, uc, access, address, size, value, user):
        pc = uc.reg_read(self.K.UC_M68K_REG_PC)
        off = pc - 0x40000400
        if 0 <= off < len(self.stock) - 8 and bytes(uc.mem_read(pc, 8)) == self.stock[off:off + 8]:
            return                                  # stock's own (its boot-time byte at 0)
        self.low_steps[self.step] = self.low_steps.get(self.step, 0) + 1
        if len(self.low) < 8:
            sp = uc.reg_read(self.K.UC_M68K_REG_A7)
            words = struct.unpack(">32I", bytes(uc.mem_read(sp, 128)))
            callers = [f"{v:#010x}" for v in words if 0x40000400 <= v < 0x40220000][:6]
            self.low.append({"address": f"{address:#010x}", "pc": f"{pc:#010x}", "callers": callers,
                             "step": self.step})

    def _reporter(self, uc, address, size, user):
        a2 = uc.reg_read(self.K.UC_M68K_REG_A2)
        self.faults.append({"record": bytes(uc.mem_read(a2, 16)).hex(), "step": self.step})

    def _redraw(self, uc, address, size, user):
        if self.poke is None or self.poke.get("done"):
            return
        kit = struct.unpack(">I", bytes(uc.mem_read(KIT, 4)))[0]
        if not 0x40000000 <= kit < 0x50000000:
            return
        for t in range(16):
            uc.mem_write(kit + 52 + 1163 * t + SOUND_TYPE, bytes([self.poke["type"] & 0xFF]))
        self.poke["done"] = True

    step = "start"

    def types(self):
        kit = self.m.long(KIT)
        return [struct.unpack(">b", self.m.read(kit + 52 + 1163 * t + SOUND_TYPE, 1))[0] for t in range(16)]

    def frame(self):
        f = self.panel.capture.frames
        return bytes(f[-1]) if f else b""

    def tap(self, key, after=None):
        n = self.panel.frames()
        self.panel.tap(key) if after is None else self.panel.tap(key, after=after)
        return self.panel.frames() - n

    def machine_sel(self):
        self.panel.hold(FUNC, 3_000_000)
        self.panel.tap(SRC, after=3_000_000)
        self.panel.let_go(FUNC)
        self.panel.settle(10_000_000)


def code_key(code):
    return ((code - 1) // 8, (code - 1) % 8)


def tracks(a, stock, mod_types) -> dict:
    """Each track whose machine is one of ours, made the active track ([TRK] + [TRIG n]) and its
    FLTR and SYN pages drawn: every cell of a stock page (FLTR) asks wr_label, the SYN page is
    ours or stock's by machine."""
    r = Run(a.snapshot, stock, a.png_dir)
    r.step = "settle"
    r.panel.settle(20_000_000)
    rows, ok = [], True
    kinds = r.types()
    for t in range(16):
        if kinds[t] not in mod_types:
            continue
        r.step = f"track {t + 1} (type {kinds[t]})"
        r.panel.hold(TRK, 3_000_000)
        r.panel.tap(code_key(TRIG1 + t), after=3_000_000)
        r.panel.let_go(TRK)
        active = r.m.read(ACTIVE, 1)[0]
        before = r.frame()
        r.tap(FLTR)
        fltr = r.frame()
        r.tap(SRC)
        syn = r.frame()
        r.panel.screen(f"track{t + 1:02d}_type{kinds[t]}_syn")
        row = {"track": t + 1, "type": kinds[t], "active": active == t,
               "fltr_drawn": fltr != before, "syn_drawn": syn != fltr}
        row["ok"] = all(v for k, v in row.items() if k not in ("track", "type"))
        ok = ok and row["ok"]
        rows.append(row)
        print(f"  {'ok  ' if row['ok'] else 'FAIL'}  track {t + 1}, type {kinds[t]}: "
              f"{'active' if row['active'] else 'NOT made active'}; FLTR {'drawn' if row['fltr_drawn'] else 'NOT drawn'}, "
              f"SYN {'drawn' if row['syn_drawn'] else 'NOT drawn'}", flush=True)
    facts = {"every track of ours drawn": ok and bool(rows), "no read below 0x40000000 by our code": not r.low,
             "no EXCEPTION": not r.faults}
    return {"ok": all(facts.values()), "facts": facts, "rows": rows, "low": r.low, "low_steps": r.low_steps,
            "faults": r.faults}


def sweep(a, stock, order) -> dict:
    r = Run(a.snapshot, stock, a.png_dir)
    r.step = "settle"
    r.panel.settle(20_000_000)
    track = r.m.read(ACTIVE, 1)[0]
    picks, ok = [], True
    r.step = "MACHINE SEL"
    r.machine_sel()
    for _ in range(len(order) + 4):           # to the top (dividers are skipped)
        r.panel.tap(UP)
    for i, t in enumerate(order):
        r.step = f"pick {i} (type {t})"
        if i:
            r.machine_sel()
            r.panel.tap(DOWN)
        menu = r.frame()
        r.panel.tap(YES)
        r.panel.settle(10_000_000)
        got = r.types()[track]
        shot = r.panel.screen(f"pick{i:02d}_{t}")
        r.panel.tap(NO)
        closed = r.frame()
        r.tap(FLTR)
        fltr = r.frame()
        r.tap(SRC)
        syn = r.frame()
        row = {"i": i, "want": t, "got": got, "menu_closed": closed != menu,
               "fltr_drawn": fltr != closed, "syn_drawn": syn != fltr, "screen": shot}
        row["ok"] = got == t and row["menu_closed"] and row["fltr_drawn"] and row["syn_drawn"]
        ok = ok and row["ok"]
        picks.append(row)
        print(f"  {'ok  ' if row['ok'] else 'FAIL'}  pick {i:2d}: type {t:2d} -> track {track + 1} has {got}"
              f"{'' if row['menu_closed'] else '; the menu did not close'}"
              f"{'' if row['fltr_drawn'] and row['syn_drawn'] else '; a page did not draw'}", flush=True)
    facts = {"every row picked, in the list's order": ok and len(picks) == len(order),
             "no read below 0x40000000 by our code": not r.low, "no EXCEPTION": not r.faults}
    return {"ok": all(facts.values()), "facts": facts, "track": track, "picks": picks,
            "low": r.low, "low_steps": r.low_steps, "faults": r.faults}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshot", required=True, help="scripts/emu_machine_boot.py's saved machine (the build's own boot)")
    p.add_argument("--stock", required=True, help="stock section_3_MAIN_OS.bin (what counts as stock's code)")
    p.add_argument("--list", default="", help="MACHINE SEL's types in order (coldfire.LIST_NEW); empty: no sweep")
    p.add_argument("--mod-types", default="", help="our machine types: each track holding one is drawn")
    p.add_argument("--png-dir", default="out/machine-sweep")
    p.add_argument("--json", default=None)
    a = p.parse_args()
    stock = pathlib.Path(a.stock).read_bytes()
    result = {"tracks": None, "sweep": None}
    mod = {int(x) for x in a.mod_types.split(",") if x.strip()}
    if mod:
        result["tracks"] = tracks(a, stock, mod)
        tr = result["tracks"]
        print(f"  {'ok  ' if tr['ok'] else 'FAIL'}  our machines' pages, track by track"
              + "".join(f"\n        read of {row['address']} at pc {row['pc']} during {row['step']} "
                        f"(callers {' '.join(row['callers'])})" for row in tr["low"][:2]))
    if a.list:
        result["sweep"] = sweep(a, stock, [int(x) for x in a.list.split(",")])
        s = result["sweep"]
        print(f"  {'ok  ' if s['ok'] else 'FAIL'}  MACHINE SEL sweep, {len(s['picks'])} pick(s)"
              + "".join(f"\n        read of {row['address']} at pc {row['pc']} during {row['step']} "
                        f"(callers {' '.join(row['callers'])})" for row in s["low"][:2])
              + "".join(f"\n        {n} read(s) below 0x40000000 during {k}" for k, n in s["low_steps"].items()))
    good = all(v is None or v["ok"] for v in result.values())
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(result, indent=1))
    print(f"\n  machine sweep: {'PASS' if good else 'FAIL'}")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
