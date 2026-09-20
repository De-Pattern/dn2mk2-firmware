"""Maintenance mode under the emulator: what it starts, and what the service task answers.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_service_mode.py [--limit 150000000] [--cmd "#HELLO" ...]

A cold boot of stock 1.11 from reset. The boot-flags word `0x40287520` gets bit
`0x20` just before the OS tests it (`0x400cf086`) -- in the emulator a memory
write, on the instrument the bootstrap's job. Then it records:

- whether the service task (`0x400cd48e`) is created and runs;
- the USB mode chosen (`0x40006c52`'s argument: 4 means the CDC-ACM
  `PID 0xFFFF` device, 2/5/6 the normal ones);
- every reply, text (`0x400054b4`, printf-style) and binary (`0x400cd204`).

Commands are fed the way the USB byte receiver would: each time the task
reaches the queue receive (`0x400cd4e0`), the next line is written to spare RAM
and **posted to the queue itself** -- the pointer into the ring buffer at the
read index, and the count raised -- so the firmware's own receive
(`0x40001928`) returns it. Nothing is redirected; the queue and the dispatcher
run for real. Only the byte-level framing is skipped, and that is read in the
code (`docs/service-commands.md`, "1.11: the whole path").

Only read-only commands are in the default list. Write commands are refused.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu import dspboot  # noqa: E402
from unicorn import UC_HOOK_CODE  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_PC  # noqa: E402

SYX = ("/mnt/d/01_Code/Z_Personal/dn2_firmware/00_Resources/00_Firmware/"
       "Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx")
MAIN = "/root/dn2-sections-111/section_3_MAIN_OS.bin"
FLAGS, FLAG_TEST = 0x40287520, 0x400CF086
TASK, USB_MODE = 0x400CD48E, 0x40006C52
INIT_TASK = 0x400CEC98          # the priority-1 task whose body tests the flag
RECEIVE, AFTER_RECEIVE = 0x400CD4E0, 0x400CD4EC
QUEUE = 0x4038AE9C               # the command queue the task waits on
REPLY, REPLY_BIN = 0x400054B4, 0x400CD204
LINE_AT = 0x467D0000                     # spare RAM above BSS for the fed lines
READ_ONLY = ["#HELLO", "#STATUS", "#READ SYNC_1", "#READ_SERIAL", "#READ_TESTED",
             "#TEST_STATUS", "#MMC_GET_HEALTH"]
WRITES = re.compile(r"^#(WRITE|MMC_RECONFIGURE|FULL_UPGRADE|UPGRADE|REBOOT|RESET)")


def cstr(uc, va, n=200):
    return bytes(uc.mem_read(va, n)).split(b"\0")[0].decode("latin-1")


def printf(uc, sp):
    """Format a printf-style reply from the stack: fmt at sp+4, args after."""
    fmt = cstr(uc, struct.unpack(">I", uc.mem_read(sp + 4, 4))[0])
    args, k = [], 8
    for spec in re.findall(r"%[-0-9.]*([dsxcu])", fmt):
        v = struct.unpack(">I", uc.mem_read(sp + k, 4))[0]
        k += 4
        args.append(cstr(uc, v, 64) if spec == "s" else v)
    py = re.sub(r"%([-0-9.]*)([dsxcu])", lambda m: "%" + m.group(1) + ("d" if m.group(2) == "u" else m.group(2)), fmt)
    try:
        return py % tuple(args)
    except (TypeError, ValueError):
        return f"{fmt!r} {args}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=150_000_000)
    p.add_argument("--cmd", action="append", help="a command line to feed (default: a read-only set)")
    args = p.parse_args()
    cmds = args.cmd or READ_ONLY
    bad = [c for c in cmds if WRITES.match(c)]
    if bad:
        raise SystemExit(f"refusing write or reboot commands: {bad}")

    log = {"task_runs": 0, "usb_modes": [], "fed": [], "replies": [], "binary": []}
    queue = list(cmds)
    holder = {}

    def pre_start(m):
        uc, st = m.uc, holder["st"]

        def on(addr, fn):
            uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: fn(uc), begin=addr, end=addr)

        def set_flag(uc):
            v = struct.unpack(">I", uc.mem_read(FLAGS, 4))[0]
            uc.mem_write(FLAGS, struct.pack(">I", v | 0x20))
            log["flags_before"] = v
        on(FLAG_TEST, set_flag)

        def init_task(uc):
            log.setdefault("init_task_at", st["n"])
        on(INIT_TASK, init_task)

        def task(uc):
            log["task_runs"] += 1
            log.setdefault("task_first", st["n"])
        on(TASK, task)

        def usb(uc):
            sp = uc.reg_read(UC_M68K_REG_A7)
            log["usb_modes"].append(struct.unpack(">I", uc.mem_read(sp + 4, 4))[0])
        on(USB_MODE, usb)

        def receive(uc):
            if not queue:
                return                       # nothing left: let it block as normal
            line = queue.pop(0)
            uc.mem_write(LINE_AT, line.encode() + b"\0")
            uc.reg_write(UC_M68K_REG_D0, LINE_AT)
            uc.reg_write(UC_M68K_REG_PC, AFTER_RECEIVE)
            log["fed"].append((st["n"], line))
        on(RECEIVE, receive)

        def reply(uc):
            log["replies"].append((st["n"], printf(uc, uc.reg_read(UC_M68K_REG_A7))))
        on(REPLY, reply)

        def reply_bin(uc):
            sp = uc.reg_read(UC_M68K_REG_A7)
            buf, n = struct.unpack(">II", uc.mem_read(sp + 4, 8))
            log["binary"].append((st["n"], buf, n, bytes(uc.mem_read(buf, min(n, 16))).hex()))
        on(REPLY_BIN, reply_bin)

    m, st, stop = dspboot.run(SYX, open(MAIN, "rb").read(), limit=args.limit,
                              machine_out=holder, pre_start=pre_start)

    print(f"flags word before: {log.get('flags_before', 'never tested'):#x}" if "flags_before" in log
          else "flags word: the test at 0x400cf086 was never reached")
    print(f"init task (0x400cec98) first ran at: {log.get('init_task_at')}")
    print(f"USB mode(s) selected: {log['usb_modes']}")
    print(f"service task ran: {log['task_runs']} time(s), first at {log.get('task_first')}")
    print(f"fed {len(log['fed'])} of {len(cmds)} command(s)")
    for n, line in log["fed"]:
        print(f"  [{n:,}] > {line}")
    for n, text in log["replies"]:
        print(f"  [{n:,}] < {text.rstrip()!r}")
    for n, buf, size, head in log["binary"]:
        print(f"  [{n:,}] < binary {size} B at {buf:#x}: {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
