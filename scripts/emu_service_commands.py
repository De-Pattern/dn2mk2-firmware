"""Ask the service dispatcher a command under the emulator, and read its reply.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_service_commands.py ["#HELLO" "#STATUS" ...]

`scripts/emu_service_mode.py` proves what maintenance mode *starts* -- USB mode
4 and the service task -- from a cold boot. It cannot ask it anything: the
task is priority 2, and with the emulator's semaphore patch the higher-priority
tasks never sleep, so it runs once and starves. Waiting longer does not help
(900M instructions, checked).

So the dispatcher is called directly, the way `scripts/emu_arp_plocks.py` calls
the p-lock routines: a snapshot is restored, the command queue is built in
spare RAM with the line already posted, and `0x400cd48e` is entered with a
synthetic stack. Its own code runs for real from there -- the same string
comparisons, the same handlers, the same reply function -- and the replies are
captured at `0x400054b4` (text) and `0x400cd204` (binary).

What this does **not** exercise: the USB endpoint, the byte receiver's framing,
and whatever maintenance mode's own startup would have configured. Those are
read in the code (`docs/service-commands.md`) and, for the startup, confirmed
by `emu_service_mode.py`.

**Read-only commands only.** Anything that writes or reboots is refused.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu.longrun import build  # noqa: E402
from unicorn import UC_HOOK_CODE, UC_PROT_ALL, UcError  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A6, UC_M68K_REG_A7  # noqa: E402

SNAP = "/root/dn2-snapshots/Digitone_II_OS1.11/ui1200M.snap"
SYX = ("/mnt/d/01_Code/Z_Personal/dn2_firmware/00_Resources/00_Firmware/"
       "Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx")

TASK = 0x400CD48E                # the service task's entry: the dispatcher
RECEIVE = 0x400CD4E0             # where it takes the next line off the queue
REPLY, REPLY_BIN = 0x400054B4, 0x400CD204
QUEUE = 0x4038AE9C               # the queue object the task waits on

SCRATCH = 0x467D0000             # spare RAM above BSS, as emu_arp_plocks.py uses
STACK = 0x467CF000
READ_ONLY = ["#HELLO", "#STATUS", "#READ SYNC_1", "#READ_SERIAL", "#READ_TESTED",
             "#READ_UI_TESTED", "#TEST_STATUS", "#MMC_GET_HEALTH",
             "#MMC_GET_RECONFIGURED", "#READ_UI_TEST_COMPLETED"]
REFUSE = re.compile(r"^#(WRITE|MMC_RECONFIGURE|FULL_UPGRADE|UPGRADE|REBOOT|RESET|ENTER_TEST|"
                    r"EXIT_TEST|START_UI_TEST|ABORT_UI_TEST|RECEIVE_AUDIO|PLAY|RECORD|STOP)")


def cstr(uc, va, n=240):
    try:
        return bytes(uc.mem_read(va, n)).split(b"\0")[0].decode("latin-1")
    except UcError:
        return f"<unreadable 0x{va:08x}>"


def printf(uc, sp):
    """A printf-style reply: the format at sp+4, its arguments after it."""
    fmt = cstr(uc, struct.unpack(">I", uc.mem_read(sp + 4, 4))[0])
    args, at = [], 8
    for spec in re.findall(r"%[-0-9.]*([dsxcu])", fmt):
        value = struct.unpack(">I", uc.mem_read(sp + at, 4))[0]
        at += 4
        args.append(cstr(uc, value, 64) if spec == "s" else value)
    template = re.sub(r"%([-0-9.]*)([dsxcu])",
                      lambda m: "%" + m.group(1) + ("d" if m.group(2) == "u" else m.group(2)), fmt)
    try:
        return template % tuple(args)
    except (TypeError, ValueError):
        return f"{fmt!r} {args}"


class Service:
    def __init__(self, snapshot):
        self.m, *_ = build(snapshot, syx=SYX, unblock=True, softfloat=True, bitmap=True,
                           dsp=True, weakptr=True, slc=True, deferred_components=("timers",))
        self.uc = self.m.uc
        self.replies = []
        self.at = SCRATCH
        self.ret = STACK + 0x800
        self.uc.hook_add(UC_HOOK_CODE, self._text, begin=REPLY, end=REPLY)
        self.uc.hook_add(UC_HOOK_CODE, self._binary, begin=REPLY_BIN, end=REPLY_BIN)
        self.uc.hook_add(UC_HOOK_CODE, self._receive, begin=RECEIVE, end=RECEIVE)
        self.pending = []

    def alloc(self, n, fill=b""):
        va = (self.at + 15) & ~15
        self.at = va + n
        self.write(va, fill.ljust(n, b"\0"))
        return va

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

    def _text(self, uc, address, size, user):
        self.replies.append(printf(uc, uc.reg_read(UC_M68K_REG_A7)))

    def _binary(self, uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        buf, n = struct.unpack(">II", uc.mem_read(sp + 4, 8))
        self.replies.append(f"<binary {n} B: {bytes(uc.mem_read(buf, min(n, 24))).hex()}...>")

    def _receive(self, uc, address, size, user):
        """The dispatcher is back for the next line: give it one, or stop."""
        if not self.pending:
            uc.emu_stop()
            return
        line = self.pending.pop(0)
        at = self.alloc(len(line) + 2, line.encode() + b"\0")
        ring, index, mask = (struct.unpack(">I", uc.mem_read(QUEUE + off, 4))[0]
                             for off in (0x14, 0x1C, 0x10))
        self.write(ring + 4 * (index & mask), struct.pack(">I", at))
        self.write(QUEUE + 4, struct.pack(">I", 1))

    def prepare_queue(self, depth=16):
        """Build the queue object the way 0x400cea6e does, in spare RAM."""
        ring = self.alloc(4 * depth)
        self.write(QUEUE, bytes(0x20))
        self.write(QUEUE + 0x10, struct.pack(">I", depth - 1))    # mask
        self.write(QUEUE + 0x14, struct.pack(">I", ring))         # the ring of pointers
        self.write(QUEUE + 0x1C, struct.pack(">I", 0))            # read index

    def ask(self, commands, budget=40_000_000):
        self.pending = list(commands)
        self.prepare_queue()
        self.write(STACK, struct.pack(">I", self.ret) + bytes(0x40))
        self.uc.reg_write(UC_M68K_REG_A7, STACK)
        self.uc.reg_write(UC_M68K_REG_A6, 0)
        try:
            self.uc.emu_start(TASK, self.ret, count=budget)
        except UcError as exc:
            self.replies.append(f"<emulation stopped: {exc}>")
        return self.replies


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("commands", nargs="*", default=None)
    p.add_argument("--snapshot", default=SNAP)
    args = p.parse_args()
    commands = args.commands or READ_ONLY
    refused = [c for c in commands if REFUSE.match(c)]
    if refused:
        raise SystemExit(f"refusing commands that write, play or reboot: {refused}")

    service = Service(args.snapshot)
    print(f"asking {len(commands)} command(s), snapshot {args.snapshot}")
    replies = service.ask(commands)
    for line in replies:
        print("  < " + line.rstrip().replace("\r\n", " | "))
    print(f"\n{len(replies)} reply line(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
