"""The stock encoder path, stage by stage (v0.48: STRT/LEN/LOOP's fine resolution is verified
against stock's own fine controls through this path; docs/display-path.md has the history).

A stock 1.11 snapshot (the v0.14 build's edits put back to stock), the FLTR page, then an input
sequence of detents on one encoder, each followed by GAP instructions of the UI running. Every
stage the input passes is hooked and logged with the 120 Hz tick (0x466758b0) and the
instruction count:

  1. feed:      the bytes panelin puts into the panel UART's ring (its produced count)
  2. driver:    0x4011fc2c(encoder index, delta), the per-detent record handler, its entry
                and what it leaves in the accumulator (0x445a0dc4[i]) and pending mask (0x445a0dec)
  3. queue:     queue_send (0x40001896) of an encoder record (type 1): its code and delta
  4. receive:   queue_receive (0x40001928) returning into the main loop (0x4002f184)
  5. setter:    the parameter setter 0x40037b74 (sound, slot, value)
  6. value:     the sound's 16-bit word for the parameter after every step

What it established (v0.48, stock 1.11, every run from the same snapshot identical):
nothing is lost before the parameter's own knob step. Every detent reaches the driver,
the panel task flushes the sum every 4 timer-wheel ticks (PIT2, 60 Hz: 15 records a
second, clamped to +/-30), and each record reaches the page as one encoder event. The
knob step 0x4011336e then holds a per-encoder rest counter (+16 of its state: +1 every
knob-timer tick up to 48, about 1.6 s to fill). While it is above 24 a move is taken
out of it (3 x |delta|, floor 0) instead of moving the value: stock's own guard against
a knob nudged after it has been left alone. So from rest the first records do nothing,
by design. `--rest 0` empties the counter first (the causal check: the same turn then
moves at once); `--no-wheel` stops PIT2 (the negative control: the trace then shows the
detents at the driver and no encoder record queued).

Not known without hardware: how many counts the panel sends for one physical detent
(digikit's panelin sends what it is given; RESO's divisor of 3 suggests more than one),
and the absolute instruction rate (the snapshot's timers run at 18.72 M instructions a
second, a proxy). Everything in this path is timer-driven, so the timing is faithful in
the OS's own time once a detent rate in that time is chosen.

Usage: emu_encoder_trace.py --enc 4 --slot 67 --detents 12 --gap 200000 --json OUT
(slot 67 FREQ, 68 RESO on track 0's sound; enc 4 = E, 5 = F on FLTR page 1)."""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SNAP = str(HERE.parent.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap")
TICK = 0x466758B0
ACC, PENDING, LAST = 0x445A0DC4, 0x445A0DEC, 0x445A0D9C
DRIVER, QSEND, QRECV, SETTER = 0x4011FC2C, 0x40001896, 0x40001928, 0x40037B74
KIT = 0x800052A0
# The page's knob state (0x4011336e's a2, 20 bytes an encoder: +0 timeout, +8 acceleration,
# +12 remainder, +16 rest counter), as the FLTR page of this snapshot places it.
STATE = 0x447BEE94 + 32


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--enc", type=int, default=4)
    p.add_argument("--slot", type=int, default=67)
    p.add_argument("--detents", default="1*12", help="e.g. 1*12 or 1*6,-1*6")
    p.add_argument("--gap", type=int, default=200_000)
    p.add_argument("--tail", type=int, default=5_000_000)
    p.add_argument("--json", default=None)
    p.add_argument("--hook", action="append", default=[], help="ADDR: log its entries and first 4 stack args")
    p.add_argument("--rest", type=int, default=None,
                   help="put this in the knob's rest counter (+16 of its state) before the turn: the causal check")
    p.add_argument("--no-wheel", action="store_true",
                   help="negative control: stop delivering PIT2 (the timer-wheel tick) before the turn, so the "
                        "panel task never flushes; the trace must report the loss at the queue stage")
    p.add_argument("--watch", action="append", default=[], help="ADDR:LEN: log every write into it (pc, address, value)")
    a = p.parse_args()
    from emulib.image import differences
    from emulib.machine import Machine
    from emulib.panel import Panel
    from unicorn import UC_HOOK_CODE
    from unicorn import m68k_const as K
    m = Machine(SNAP)
    stock = open(pathlib.Path(HERE.parent.parent / "sec111/section_3_MAIN_OS.bin"), "rb").read()
    back = [(va, stock[va - 0x40000400:va - 0x40000400 + len(b)])
            for va, b in differences(stock, open(SNAP + ".section_3_MAIN_OS.bin", "rb").read())
            if va + len(b) <= 0x40000400 + len(stock)]
    m.apply(back)
    m.flush()
    uc = m.uc
    panel = Panel(m, png_dir=str(pathlib.Path(a.json or "out/enc").with_suffix("")) + "_png")
    snd = m.long(KIT) + 52
    va = snd + 0x14 + 2 * a.slot
    seqn = {"n": 0}
    log = []

    def now():
        return m.long(TICK)

    def word():
        return struct.unpack(">H", bytes(m.read(va, 2)))[0]

    def args(n):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        return struct.unpack(f">{n}I", bytes(uc.mem_read(sp + 4, 4 * n)))

    def on_driver(uc_, ad, sz, us):
        i, d = args(2)
        log.append(("driver", seqn["n"], now(), i, struct.unpack(">b", struct.pack(">B", d & 0xFF))[0]))

    def on_qsend(uc_, ad, sz, us):
        q, item = args(2)
        try:
            raw = bytes(uc_.mem_read(item, 12))
        except Exception:                                   # noqa: BLE001
            return
        log.append(("queue", seqn["n"], now(), hex(q), raw.hex()))

    def on_setter(uc_, ad, sz, us):
        x = args(4)
        log.append(("setter", seqn["n"], now(), [hex(v) for v in x]))
    hooks = [uc.hook_add(UC_HOOK_CODE, on_driver, begin=DRIVER, end=DRIVER),
             uc.hook_add(UC_HOOK_CODE, on_qsend, begin=QSEND, end=QSEND),
             uc.hook_add(UC_HOOK_CODE, on_setter, begin=SETTER, end=SETTER)]
    for h in a.hook:
        hv = int(h, 0)

        def on_any(uc_, ad, sz, us, hv=hv):
            sp = uc_.reg_read(K.UC_M68K_REG_A7)
            ret = struct.unpack(">I", bytes(uc_.mem_read(sp, 4)))[0]
            log.append((f"hook {hv:#x}", seqn["n"], now(), hex(ret), [hex(v) for v in args(4)]))
        hooks.append(uc.hook_add(UC_HOOK_CODE, on_any, begin=hv, end=hv))
    from unicorn import UC_HOOK_MEM_WRITE
    for w in a.watch:
        wa, wl = (int(x, 0) for x in w.split(":"))

        def on_w(uc_, acc, ad, sz, val, us):
            log.append(("write", seqn["n"], now(), hex(uc_.reg_read(K.UC_M68K_REG_PC)), hex(ad), sz, val))
        hooks.append(uc.hook_add(UC_HOOK_MEM_WRITE, on_w, begin=wa, end=wa + wl - 1))
    panel.settle(5_000_000)
    panel.tap((0, 2))                                       # FLTR
    panel.settle(10_000_000)
    plan = []
    for part in a.detents.split(","):
        d, n = part.split("*")
        plan += [int(d)] * int(n)
    state = STATE + 20 * a.enc
    if a.rest is not None:
        m.uc.mem_write(state + 16, struct.pack(">i", a.rest))
    if a.no_wheel:
        for src in getattr(panel.timers, "sources", (panel.timers,)):
            if hasattr(src, "channels") and 2 in src.channels and type(src).__name__ == "Pits":
                src.channels = tuple(c for c in src.channels if c != 2)
    out = {"input": {"enc": a.enc, "slot": a.slot, "detents": plan, "gap": a.gap, "rest": a.rest,
                     "no_wheel": a.no_wheel},
           "start": {"tick": now(), "value": word(), "acc": m.long(ACC + 4 * a.enc),
                     "pending": m.long(PENDING), "last": m.long(LAST + 4 * a.enc)},
           "steps": []}
    log.clear()
    for k, d in enumerate(plan):
        seqn["n"] = k
        st = panelin_state(panel)
        m.pc = panel.panelin.encoder(m.m, panel.profile, a.enc, d)
        st2 = panelin_state(panel)
        panel.settle(a.gap)
        out["steps"].append({"k": k, "d": d, "tick": now(), "fed": st2["produced"] - st["produced"],
                             "knob": list(struct.unpack(">5i", bytes(m.read(state, 20)))),
                             "consumed": panelin_state(panel)["consumed"] - st["consumed"],
                             "acc": m.long(ACC + 4 * a.enc), "pending": m.long(PENDING), "value": word()})
    seqn["n"] = len(plan)
    panel.settle(a.tail)
    out["end"] = {"tick": now(), "value": word(), "acc": m.long(ACC + 4 * a.enc), "pending": m.long(PENDING)}
    out["log"] = log
    out["counts"] = {s: sum(1 for e in log if e[0] == s) for s in ("driver", "queue", "setter", "write")}
    out["counts"]["queue_enc"] = sum(1 for e in log if e[0] == "queue" and e[4].startswith("01"))
    for h in a.hook:
        out["counts"][f"hook {int(h, 0):#x}"] = sum(1 for e in log if e[0] == f"hook {int(h, 0):#x}")
    for h in hooks:
        uc.hook_del(h)
    print(json.dumps({"start": out["start"], "end": out["end"], "counts": out["counts"],
                      "values": [s["value"] for s in out["steps"]]}), flush=True)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(out, indent=1))
    return 0


def panelin_state(panel):
    return panel.panelin.state(panel.m.m, panel.profile)


if __name__ == "__main__":
    raise SystemExit(main())
