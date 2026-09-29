"""The USB probe in the emulator: every command, the refusals, and a stock control.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_usbprobe.py [--build out/usbprobe]

derived from irpina/digihealth (tools/digiusb.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

irpina's probing notes (shared privately), section 5, says to test the handler by calling
the router directly, and that is what this does: the emulator models no MIDI
hardware, so a message is put where the MIDI input task would have put it and
the stock SysEx router `0x4012166e(msg, len, source)` is entered with it.

**The reply is captured at the stock sender's entry, `0x401233f2(buf, len,
abort, port)`, and the sender then runs**, so the probe's real reply path is
exercised to its return: the capture records what was handed over and the
routine does what it does with no USB host (it returns false). A reply that
reaches the sender is the reply the instrument would send.

Run twice on the same snapshot, and the two are the point:

- **stock** (the control): device byte 0x7D must reach the sender **never**,
  and a direct call of the sender must be captured, so the capture is proven
  to work on the machine where it reports silence;
- **the build**: HELLO, STATS (twice), PEEK inside each allowed range (checked
  byte for byte against memory), PEEK refused outside them and at every
  boundary, an unknown command, and malformed input, which must draw no reply
  at all: DIN instead of USB, a missing F7, a body too short, another
  device byte.

The ISR and context-switch hooks do not run from a snapshot with timers
deferred (the engine does not run here), so their routines are called directly
with the registers each site hands over, and the counters STATS reports are
checked against those calls.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
from emulib.image import differences            # noqa: E402
from emulib.machine import SNAP, Machine        # noqa: E402

import dn2probe as proto                        # noqa: E402  the host's codec, shared

ROOT = "/mnt/d/01_Code/Z_Personal/dn2_firmware"
ROUTER, SENDER = 0x4012166E, 0x401233F2
FRAMES, IDLE_TCB, IDLE_PC, CUR_TCB = 0x4058E8D4, 0x424388AC, 0x400CEBE2, 0x4664ACDC
USB, DIN = 2, 8
PROBE_RAM = 0x46F00000                          # scripts/gen_usbprobe_code.py's RAM


class Rig:
    """A snapshot with one image installed, the router to call and the sender watched."""

    def __init__(self, image=None):
        from unicorn import UC_HOOK_CODE
        from unicorn.m68k_const import UC_M68K_REG_A7

        self.m = Machine(SNAP)
        if image is not None:
            stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
            self.m.apply(differences(stock, image))
            # A combination with lfo4 appends a CODE chunk the loader copies at
            # boot; a snapshot has run past the loader, so do its job, or every
            # memcpy jumps into lfo4 stubs that are not there.
            if len(image) > len(stock):
                from emulib.image import code_chunks
                for chunk in code_chunks(image):
                    self.m.load_code_chunk(chunk)
                self.m.flush()
        self.sent = []

        def at_sender(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            buf, n, abort, port = struct.unpack(">4I", bytes(uc.mem_read(sp + 4, 16)))
            self.sent.append((bytes(uc.mem_read(buf, n)) if 0 < n < 70000 else b"", port, abort))

        self.m.uc.hook_add(UC_HOOK_CODE, at_sender, begin=SENDER, end=SENDER)
        self.msg = self.m.alloc(2048)

    def route(self, sysex: bytes, source=USB):
        """-> the replies the router's call produced (usually zero or one)."""
        before = len(self.sent)
        self.m.write(self.msg, sysex)
        self.m.flush()
        self.m.call(ROUTER, self.msg, len(sysex), source)
        return self.sent[before:]

    def ask(self, sysex, source=USB):
        replies = self.route(sysex, source)
        return [proto.parse(r) for r, _port, _ab in replies], replies


def check(results, ok, what):
    results.append((ok, what))
    print(f"  [{'PASS' if ok else 'FAIL'}] {what}")


def control(results):
    print("\nstock 1.11 (the control)")
    rig = Rig()
    got = rig.route(proto.req_hello(1))
    check(results, got == [], f"HELLO on device 0x7D reaches the sender {len(got)} time(s): expected 0")
    got = rig.route(proto.req_peek(2, 0x80000000, 16))
    check(results, got == [], "PEEK on device 0x7D reaches the sender 0 times")
    buf = rig.m.alloc(8)
    rig.m.write(buf, bytes.fromhex("F07E7F0601F7"))
    rig.m.call(SENDER, buf, 6, 0, USB)
    check(results, len(rig.sent) == 1 and rig.sent[-1][0] == bytes.fromhex("F07E7F0601F7"),
          "positive control: a direct call of the sender is captured, so its silence above is real")


def build(results, image, sym):
    print("\nthe build")
    rig = Rig(image)
    m = rig.m

    # ---- HELLO ---------------------------------------------------------
    (r,), raw = rig.ask(proto.req_hello(0x1234))
    h = proto.decode_hello(r["payload"]) if r else None
    check(results, r is not None and r["seq"] == 0x1234 and r["cmd"] == 0x81 and r["status"] == 0,
          f"HELLO answers: {r and (hex(r['seq']), hex(r['cmd']), r['status'])}")
    check(results, raw[0][1] == USB and raw[0][2] == 0, f"sent to port {raw[0][1]} (USB), no abort flag")
    check(results, h is not None and h["frames"] == m.long(FRAMES),
          f"HELLO frames {h and h['frames']} = the ISR's count {m.long(FRAMES)}; tag {h and h['tag']!r}")

    # ---- the timing hooks, called with what each site hands over --------
    from unicorn.m68k_const import UC_M68K_REG_A0
    f0 = m.long(FRAMES)
    for _ in range(3):
        m.call(sym["isr_in"])
        m.call(sym["isr_out"])
    check(results, m.long(FRAMES) == f0 + 3, "isr_out replays the frame count: +3 over three ISRs")
    tcb = m.long(CUR_TCB)
    m.write(CUR_TCB, struct.pack(">I", 0x11111111))       # a task, then the idle task in
    m.uc.reg_write(UC_M68K_REG_A0, IDLE_TCB)
    m.call(sym["task_switch"], 0, 0x40001000)
    m.write(CUR_TCB, struct.pack(">I", IDLE_TCB))           # idle out, parked at its spin
    m.uc.reg_write(UC_M68K_REG_A0, 0x11111111)
    m.call(sym["task_switch"], 0, IDLE_PC)
    m.write(CUR_TCB, struct.pack(">I", tcb))

    # ---- STATS ----------------------------------------------------------
    (r1,), _ = rig.ask(proto.req_stats(1))
    (r2,), _ = rig.ask(proto.req_stats(2))
    s1, s2 = proto.decode_stats(r1["payload"]), proto.decode_stats(r2["payload"])
    check(results, r1["status"] == 0 and s1["layout"] == 2 and len(r1["payload"]) == proto.STATS2_BYTES,
          f"STATS answers, layout {s1['layout']}, {len(r1['payload'])} B")
    check(results, (s1.get("idle_in"), s1.get("idle_out"), s1.get("idle_offpc")) == (1, 1, 0),
          f"layout 2 counts the idle task: in {s1.get('idle_in')}, out {s1.get('idle_out')}, "
          f"off the spin {s1.get('idle_offpc')}")
    check(results, s1["isr_count"] == 3 and s1["switches"] == 2,
          f"STATS counts the calls above: {s1['isr_count']} ISRs, {s1['switches']} switches")
    check(results, s1["frames"] == m.long(FRAMES), f"STATS frames {s1['frames']} = memory")
    check(results, s2["isr_max"] == 0, f"the ISR peak is per STATS: {s1['isr_max']} then {s2['isr_max']}")
    check(results, s1["hash"] == s2["hash"], "the link hashes are stable while nothing moves")
    m.write(0x800053A4, struct.pack(">I", m.long(0x800053A4) ^ 0x5A5A5A5A))
    (r3,), _ = rig.ask(proto.req_stats(3))
    s3 = proto.decode_stats(r3["payload"])
    check(results, s3["hash"][0] != s2["hash"][0] and s3["hash"][1:] == s2["hash"][1:],
          "one word of the SHARC's reply changed: only its hash moved")

    # ---- layout 2: an ISR over a frame, and an idle switch off the spin ----
    # DTCN0 reads 0 here, so a long ISR is made by the entry timestamp: the
    # exit's `0 - t_in` is then 131,072 ticks, over the 87,708 of one frame.
    t_in = PROBE_RAM + 0x8E4                                # csrc/usbprobe/layout.inc
    m.call(sym["isr_in"])
    m.write(t_in, struct.pack(">I", 0xFFFE0000))
    m.call(sym["isr_out"])
    m.call(sym["isr_in"])
    m.call(sym["isr_out"])                                  # and one of 0 ticks
    m.write(CUR_TCB, struct.pack(">I", IDLE_TCB))
    m.uc.reg_write(UC_M68K_REG_A0, 0x11111111)
    m.call(sym["task_switch"], 0, 0x40012345)               # idle out, somewhere else
    m.write(CUR_TCB, struct.pack(">I", tcb))
    (r4,), _ = rig.ask(proto.req_stats(4))
    s4 = proto.decode_stats(r4["payload"])
    check(results, s4.get("isr_over") == s3.get("isr_over", 0) + 1,
          f"one ISR over a frame, one not: isr_over {s3.get('isr_over')} -> {s4.get('isr_over')}")
    check(results, s4.get("idle_offpc") == 1 and s4.get("idle_lastpc") == 0x40012345,
          f"an idle switch-out off the spin is counted, and its PC kept: "
          f"{s4.get('idle_offpc')}, {s4.get('idle_lastpc', 0):#010x}")

    # ---- PEEK -----------------------------------------------------------
    for addr, n in ((0x80005E60, 64), (0x40000400, 1024), (0x4E6DF100, 32), (0x4E6E0900 + 0x7E0, 32),
                    (0x8000FFF0, 16), (0x47FFFFF0, 16)):
        replies, _ = rig.ask(proto.request(9, proto.PEEK, struct.pack(">IH", addr, n)))
        r = replies[0] if replies else None
        ok = r is not None and r["status"] == 0 and proto.decode_peek(r["payload"])["data"] == m.read(addr, n)
        check(results, ok, f"PEEK 0x{addr:08x} +{n}: the bytes in memory")
    for addr, n in ((0xFC045640, 4), (0xEC094018, 1), (0x47FFFFFE, 4), (0x8000FFFE, 4),
                    (0x7FFFFFFE, 4), (0x4E6DF0FF, 2), (0x4E6E10FF, 2), (0x40000000, 0),
                    (0x40000000, 1025), (0x00000000, 4), (0xFFFFFFFC, 8)):
        replies, _ = rig.ask(proto.request(9, proto.PEEK, struct.pack(">IH", addr, n)))
        r = replies[0] if replies else None
        check(results, r is not None and r["status"] == 1 and r["payload"] == b"",
              f"PEEK 0x{addr:08x} +{n}: refused ({r and r['status']})")
    replies, _ = rig.ask(proto.request(9, proto.PEEK, b"\x80\x00"))
    check(results, replies and replies[0]["status"] == 1, "PEEK with its arguments cut short: refused")

    # ---- unknown and malformed -------------------------------------------
    replies, _ = rig.ask(proto.request(4, 0x44))
    check(results, replies and replies[0]["status"] == 2, "an unknown command: status 2")
    replies, _ = rig.ask(proto.request(4, 0x04, b"\x01\x02"))
    check(results, replies and replies[0]["status"] == 2, "no write command exists: 0x04 is unknown")
    hello = proto.req_hello(5)
    for what, sx, src in (("from DIN, not USB", hello, DIN),
                          ("from DIN port 0x10", hello, 0x10),
                          ("without its F7", hello[:-1] + b"\x00", USB),
                          ("a body of two bytes", proto.HEADER + b"\x00\x00\x05\xF7", USB),
                          ("an empty body", proto.HEADER + b"\xF7", USB),
                          ("device byte 0x7E", hello[:4] + b"\x7E" + hello[5:], USB),
                          ("device 0x7D, sub 0x01", hello[:5] + b"\x01" + hello[6:], USB)):
        got = rig.route(sx, src)
        check(results, got == [], f"malformed, {what}: no reply ({len(got)})")
    # An oversized request is not malformed -- 16 KB of zeros unpacks to seq 0,
    # cmd 0, an unknown command -- but it must not write past the request
    # buffer: unpack7 keeps RQ_MAX bytes and drops the rest.
    canary = bytes(range(0xA0, 0xAC))
    m.write(sym["rq"] + 0x14, canary)
    rig.msg = m.alloc(16384 + 16)
    replies, _ = rig.ask(proto.HEADER + bytes(16384) + b"\xF7")
    check(results, len(replies) == 1 and replies[0]["status"] == 2
          and m.read(sym["rq"] + 0x14, len(canary)) == canary,
          "16 KB of body: one 'unknown command' reply, nothing written past the request buffer")
    (r,), _ = rig.ask(proto.req_hello(6))
    check(results, r is not None and r["status"] == 0, "and it still answers afterwards")


def from_reset(results, image, sym, limit, label, fast=False):
    """Boot `image` from reset (the real bootloader path, digikit's dspboot), then
    ask the router for HELLO, STATS and a PEEK in the machine the boot left.

    This is the round trip a snapshot cannot give: the hooks are in place from
    the first instruction, the context-switch hook runs through the whole boot,
    and the reply path is entered in a machine this image booted."""
    sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from emu_boot_engine import After
    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_A7

    syx = f"{ROOT}/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
    holder, fault, sent, hits = {}, {}, [], {"task_switch": 0}

    def pre_start(mach, count):
        def at_reporter(uc, address, size, user):
            fault.setdefault("at", count())
            uc.emu_stop()

        def at_sender(uc, address, size, user):
            sp = uc.reg_read(UC_M68K_REG_A7)
            buf, n, abort, port = struct.unpack(">4I", bytes(uc.mem_read(sp + 4, 16)))
            sent.append((bytes(uc.mem_read(buf, n)) if 0 < n < 70000 else b"", port, abort))

        def at_switch(uc, address, size, user):
            hits["task_switch"] += 1
        mach.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=0x4011EA6A, end=0x4011EA6A)
        mach.uc.hook_add(UC_HOOK_CODE, at_sender, begin=SENDER, end=SENDER)
        if "task_switch" in sym:
            mach.uc.hook_add(UC_HOOK_CODE, at_switch, begin=sym["task_switch"], end=sym["task_switch"])

    print(f"\n{label}: from reset, {limit:,} instructions{' (fast path)' if fast else ''}")
    try:
        from emulib import fastpath             # the fast path, where it is installed
    except ImportError:
        fastpath = None
    if fast and fastpath is None:
        raise SystemExit("--fast needs scripts/emulib/fastpath.py, which this checkout does not have")
    if fastpath is not None:
        mach, st, stop, _count = fastpath.run(syx, image, limit, pre_start=pre_start, fast=fast)
    else:                                       # digikit's cold boot, as before the fast path
        from emu import dspboot
        box = {}
        mach, st, stop = dspboot.run(syx, image, limit=limit, machine_out=box,
                                     pre_start=lambda m: pre_start(m, lambda: box["st"]["n"]))
    print(f"  ran {st['n']:,}, stop {stop!r}, sender calls during boot {len(sent)}")
    check(results, not fault, f"no EXCEPTION during the boot ({fault or 'none'})")
    after = After(mach.uc)
    msg = after.alloc(256)
    probe = "task_switch" in sym

    def route(sx):
        before = len(sent)
        after.write(msg, sx)
        after.call(ROUTER, msg, len(sx), USB)
        return [proto.parse(r) for r, _p, _a in sent[before:]]

    got = route(proto.req_hello(0x77))
    if not probe:
        check(results, got == [], f"stock from reset: HELLO on 0x7D draws {len(got)} replies, expected 0")
        return
    check(results, hits["task_switch"] > 0, f"the context-switch hook ran {hits['task_switch']:,} times")
    ok = len(got) == 1 and got[0] and got[0]["status"] == 0
    check(results, ok, f"HELLO after a real boot: {got and got[0] and proto.decode_hello(got[0]['payload'])}")
    got = route(proto.req_stats(0x78))
    s = proto.decode_stats(got[0]["payload"]) if got and got[0] else None
    check(results, s is not None and s["switches"] > 0,
          f"STATS after a real boot: {s and {k: s[k] for k in ('frames', 'switches', 'dtcn0', 'idle_ticks')}}")
    got = route(proto.req_peek(0x79, 0x80005E60, 64))
    check(results, len(got) == 1 and got[0]["status"] == 0
          and proto.decode_peek(got[0]["payload"])["data"] == bytes(mach.uc.mem_read(0x80005E60, 64)),
          "PEEK after a real boot: the bytes in memory")
    got = route(proto.req_peek(0x7B, 0x800053A4, 8))
    check(results, len(got) == 1 and got[0]["status"] == 0
          and proto.decode_peek(got[0]["payload"])["data"] == bytes(mach.uc.mem_read(0x800053A4, 8)),
          "PEEK of the SHARC reply's words 0-1 (dn2probe stage) after a real boot: the bytes in memory")
    got = route(proto.request(0x7A, proto.PEEK, struct.pack(">IH", 0xFC045640, 4)))
    check(results, len(got) == 1 and got[0]["status"] == 1, "PEEK of a peripheral register after a real boot: refused")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/usbprobe")
    p.add_argument("--reset", type=int, default=0, metavar="N",
                   help="also boot stock and the build from reset for N instructions and "
                        "round-trip the channel in each (slow: ~4.5 min per 100M)")
    p.add_argument("--fast", action="store_true", default=os.environ.get("DN2_EMU_FAST") == "1",
                   help="the reset boots on the fast path, where scripts/emulib/fastpath.py is installed")
    args = p.parse_args()
    folder = os.path.join(ROOT, args.build)
    image = open(os.path.join(folder, "section_3_MAIN_OS.bin"), "rb").read()
    sym = {k: int(v, 16) for k, v in json.load(open(os.path.join(folder, "symbols.json"))).items()}
    results = []
    control(results)
    build(results, image, sym)
    if args.reset:
        stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
        from_reset(results, stock, {}, args.reset, "stock (the control)", args.fast)
        from_reset(results, image, sym, args.reset, os.path.basename(folder), args.fast)
    bad = [w for ok, w in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks pass" + ("" if not bad else ": DO NOT FLASH"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
