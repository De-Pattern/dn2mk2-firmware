"""DIRECT JUMP's scenarios on the coupled emulator: emu_jump.py's own run() (the patterns, the cues, the checks and the
trace digest), with the ColdFire run as emu_coupled.py runs it (each audio period the UI's slice, then the audio ISR;
the sequencer's ISR at the tempo's rate between them).

Why (2026-11-14, the 1.12 gate's blind spots): emu_jump.py runs the UI only in short windows (200 K instructions every 8
sequencer entries) and never runs the audio ISR. On 1.12 the sequencer takes two nodes every eight entries from a
64-node pool that only the audio ISR hands back, so every run hung at entry 256. Running the audio ISR inside emu_jump
was not enough: on 1.12 the switch to A04 (rapid) and, from v0.53, A01's loop (odd) start work that waits on the TDM
side, which emu_jump does not have, and no key reached stock's cue after it (on 1.11 too, once the audio ISR ran).
On the coupled emulator, from the same snapshot, the same work completes and every cue arms.

What stays emu_jump's: everything run() does, and its JSON line `emu_jump SCENARIO: {...}`. The +Drive is served as
there and stock's fault reporter hooked as there. --stock is the control as there: nothing installed (the coupled
emulator built from the stock image itself). What the coupled emulator brings: the UI and the audio ISR run every
period. As in emu_jump, the sequencer does not advance while the panel is handled (a key down, let go, or a settle):
its entries are counted from the cue, and one `isr()` is one sequencer entry, the periods up to and including the one
that entered it.

    emu_jump_coupled.py --build BUILD.syx --stock-image STOCK.syx --snapshot SNAP --scenario S [--variant V] [--stock]
                        [--json OUT] [--png-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import struct
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import emu_jump as J                                    # noqa: E402
from emu_coupled import UI_SLICE, Coupled               # noqa: E402
from emulib.panel import SETTLE, TAP                    # noqa: E402

ENTRIES_A_PERIOD_MAX = 1                                # at most one sequencer entry a period below 937 BPM
# TIME_BALANCE: here the panel's time is audio time (the audio ISR runs every period), and the trace digest hashes a
# counter it moves (emu_jump.SEQ_NODES + 0xb1; nothing of the sequencer's own state differs: measured on 1.12,
# stock off against pc, rows 1 and 2). emu_jump's panel time is the UI's alone. So every run spends the same time:
# PTN_YES, run()'s PTN + YES (PTN 3 M, YES 2 + 3 M, let go 3 M, then 5 M), in the runs that skip it; CUE_KEYS, a cue
# from the keys, before a cue made by a call (pc)
PTN_YES, CUE_KEYS = 16_000_000, 10_000_000
SEQ_WAIT_MOST = 3000                                    # periods (2 s) without an entry: the sequencer stopped (an entry is due every ~12 at 81 BPM)


class Paced(Coupled):
    """the coupled emulator whose sequencer can be held (no entry, no time for it) while the panel is handled"""

    seq_hold = False

    def _seq_tick(self):
        if not self.seq_hold:
            super()._seq_tick()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", required=True, help="the build (.syx)")
    p.add_argument("--stock-image", required=True, help="stock (.syx)")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--scenario", required=True, choices=("off", "on", "ref", "pc", "persist", "rapid"))
    p.add_argument("--variant", default="pp", choices=("pp", "pt", "odd"))
    p.add_argument("--stock", action="store_true", help="install nothing: the control")
    p.add_argument("--json")
    p.add_argument("--png-dir")
    a = p.parse_args()

    c = Paced(a.stock_image if a.stock else a.build, a.snapshot, a.stock_image, png_dir=a.png_dir, dsp=False)
    m, uc = c.machine, c.uc
    from unicorn import UC_HOOK_CODE
    from unicorn import m68k_const as K
    syms = {}
    if not a.stock:
        lay = json.loads((HERE.parent / "src/dnfw/mods/waverider_code.json").read_text())["layout"]
        syms = {k: v for k, v in lay.items() if k.startswith("jmp_")}

    # the +Drive, served as emu_jump.py serves it
    disk: dict[int, bytes] = {}
    io = {"reads": [], "writes": []}

    def blk(uc_, address, size, user):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        sector, n, buf = struct.unpack(">3I", bytes(uc.mem_read(sp + 4, 12)))
        if address == J.BLK_READ:
            io["reads"].append(sector)
            uc.mem_write(buf, b"".join(disk.get(sector + k, bytes(512)) for k in range(n // 512)))
        else:
            io["writes"].append(sector)
            data = bytes(uc.mem_read(buf, n))
            for k in range(n // 512):
                disk[sector + k] = data[512 * k:512 * k + 512]
    for va in (J.BLK_READ, J.BLK_WRITE):
        m.write(va, bytes.fromhex("70004e75"))          # moveq #0,%d0 ; rts: the hook does the work
        uc.hook_add(UC_HOOK_CODE, blk, begin=va, end=va)
    m.write(J.BLK_READY, struct.pack(">I", 1))
    m.write(J.BLK_SECTORS, struct.pack(">I", 0x3A00000))
    m.flush()

    faults: list[str] = []
    uc.hook_add(UC_HOOK_CODE, lambda u, ad, sz, us: faults.append(f"{u.reg_read(K.UC_M68K_REG_PC):#x}"),
                begin=J.FAULT_REPORTER, end=J.FAULT_REPORTER)
    entries = [0]
    uc.hook_add(UC_HOOK_CODE, lambda u, ad, sz, us: entries.__setitem__(0, entries[0] + 1),
                begin=J.SEQ_ISR, end=J.SEQ_ISR)

    def periods(n):
        if not c.periods(n):
            raise SystemExit(f"emu_jump {a.scenario}: {json.dumps({'ok': False, 'halt': c.halt, 'faults': faults})}")

    def u8(va): return c.read(va, 1)[0]
    def u16(va): return struct.unpack(">H", c.read(va, 2))[0]
    def u32(va): return c.long(va)

    def sym(name, n=1):
        return int.from_bytes(c.read(syms[name], n), "big") if name in syms else None

    def isr():
        """one sequencer entry: the periods up to and including the one that entered it"""
        e0, waited = entries[0], 0
        while entries[0] == e0:
            periods(1)
            waited += 1
            if waited > SEQ_WAIT_MOST:
                raise SystemExit(f"emu_jump {a.scenario}: {json.dumps({'ok': False, 'why': f'no sequencer entry in {waited} periods', 'faults': faults})}")
        if entries[0] - e0 > ENTRIES_A_PERIOD_MAX:
            raise SystemExit(f"{entries[0] - e0} sequencer entries in one period")

    def guest(fn, *args):
        """FN(ARGS) on the ColdFire (pc: the sequencer's cue routine), its registers kept, after the 10 M a cue from
        the keys takes here (PTN held 3, TRIG 2 + 2, let go 3: run()'s cue_a02), so the two cues cost the same audio
        time and the trace digests stay comparable (see TIME_BALANCE)"""
        Keys.run(CUE_KEYS)
        c.call(fn, *args)

    class Keys:
        """emu_jump's Panel calls, in periods: the UI and the audio ISR run, the sequencer is held"""

        @staticmethod
        def run(instructions):                  # (whole periods of UI_SLICE: 3 M is 3 periods, as each key above)
            c.seq_hold = True
            try:
                periods(max(1, math.ceil(instructions / UI_SLICE)))
            finally:
                c.seq_hold = False

        def hold(self, key, instructions=SETTLE):
            m.pc = c.panel.panelin.press(m.m, c.panel.profile, *key)
            self.run(instructions)

        def let_go(self, key, after=SETTLE):
            m.pc = c.panel.panelin.release(m.m, c.panel.profile, *key)
            self.run(after)

        def tap(self, key, after=SETTLE):
            self.hold(key, TAP)
            self.let_go(key, after)

        def settle(self, instructions=SETTLE):
            self.run(instructions)
            return instructions

        def screen(self, name):
            return c.panel.screen(name)

    panel = Keys()
    panel.settle(20_000_000)                    # as emu_jump: the UI settles before the scenario
    if a.scenario not in ("on", "persist", "pc", "rapid"):
        panel.settle(PTN_YES)                   # the time the others spend on PTN + YES (TIME_BALANCE)
    E = types.SimpleNamespace(m=m, panel=panel, isr=isr, guest=guest, u8=u8, u16=u16, u32=u32, sym=sym, syms=syms,
                              disk=disk, io=io, faults=faults,
                              ui_share=lambda k: None)   # (the UI runs every period here, not in emu_jump's windows)
    return J.run(a, E)


if __name__ == "__main__":
    raise SystemExit(main())
