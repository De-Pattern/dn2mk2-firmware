"""Send a READ-ONLY SysEx request to a connected instrument and show the reply.

## Safety, which is the whole design of this file

**The worst known outcome on this protocol, first:** `0x54` (open reader) sent
with an **unterminated body** -- a raw u32 id with no NUL -- **froze a Digitone 1
three times**, recoverable only by a power cycle, which takes the unsaved active
project with it. Reported by the DNX session from its own record. Every
NUL-terminated body has been answered normally. Nothing in this file sends
`0x54` at all, and if it ever does, the terminator is not optional.

`docs/service-commands.md` lists commands that write persistent state --
`#WRITE_SERIAL`, `#WRITE_TESTED`, `#MMC_RECONFIGURE`, `#FULL_UPGRADE` -- and
`docs/midi-rpc.md` lists RPCs that can destroy a +Drive: `FsRawWriteFile*`,
`FsRawDeleteFile`, `DataClear`, and the `OsUpgrade*` trio. A wiped +Drive is
**not recoverable** from anything this project holds.

So this tool cannot send them. Not "should not" -- **cannot**: every outgoing
message must come from `READ_ONLY`, a table in this file, and anything else
raises before a byte reaches the port. Adding a write here would be a
deliberate act, not an accident, which is the point.

It also never opens an output port until the user has named one, and it prints
exactly what it is about to send first.

## The first message, and why it is that one

`F0 7E 7F 06 01 F7` is the **MIDI Universal Device Inquiry**, defined by the MIDI
spec rather than by Elektron. Every compliant device answers it with its
manufacturer, family, model and version, and nothing else happens. It is the
cheapest possible end-to-end proof that the cable, the port, the framing and the
reply path all work -- which is what `docs/midi-rpc.md` says to establish before
anything device-specific is attempted.

No dependency is used: `python-rtmidi` and `pygame` have no wheels for the
Python here, so this talks to `winmm` directly through `ctypes`.

    python scripts/midi_probe.py --list
    python scripts/midi_probe.py --out 1 --in 1 --send inquiry
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

winmm = ctypes.WinDLL("winmm")

# Only these may ever be sent. Each is read-only by definition of its own spec.
READ_ONLY = {
    "inquiry": (
        bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]),
        "MIDI Universal Device Inquiry -- identity request, MIDI standard, "
        "no device state is read or written",
    ),
}


# ---------------------------------------------------------------------------
# Elektron SysEx, as implemented by dagargo/elektroid (GPLv3) and read from its
# src/connectors/elektron.c rather than guessed. Reuse before writing --
# docs/references.md.
#
#   raw   = F0 00 20 3C 10 00 <encode87(body)> F7
#   body  = <seq:2 BE> 00 00 <opcode> [payload]
#   reply carries the request opcode | 0x80
#
# ONLY read-only opcodes appear below. The write side of this protocol --
# 0x11/0x12/0x20/0x21 (create/delete/rename), 0x40-0x45 (file writers),
# 0x5a-0x5d (data move/copy/clear/swap) and 0x50 (OS upgrade) -- is
# deliberately absent, because DataClear and the FsRaw writers can destroy a
# +Drive and nothing this project holds can restore one.
# ---------------------------------------------------------------------------
ELEKTRON_HEADER = bytes([0xF0, 0x00, 0x20, 0x3C, 0x10, 0x00])

# 0x03 and 0x04 were here as "device_uid" on elektroid's naming. The DNX
# session reports both are UNIDENTIFIED -- Transfer merely polls with them --
# so they are removed. A name in someone else's source is not evidence about
# what a command does to a device.
ELEKTRON_READ_ONLY = {
    "ping":             (0x01, b"", "liveness only"),
    "software_version": (0x02, b"", "reports the running OS version"),
    "storage_info":     (0x05, b"", "reports storage sizes and free space"),
}


def encode87(src: bytes) -> bytes:
    """Elektron's 8-in-7 packing: one MSB byte then seven cleared bytes."""
    out = bytearray()
    for j in range(0, len(src), 7):
        group = src[j:j + 7]
        accum = 0
        for k in range(7):
            accum <<= 1
            if k < len(group) and group[k] & 0x80:
                accum |= 1
        out.append(accum)
        out.extend(b & 0x7F for b in group)
    return bytes(out)


def decode87(src: bytes) -> bytes:
    """Inverse of encode87."""
    out = bytearray()
    i = 0
    while i < len(src):
        accum = src[i]
        chunk = src[i + 1:i + 8]
        for k, b in enumerate(chunk):
            out.append(b | (0x80 if accum & (1 << (6 - k)) else 0))
        i += 8
    return bytes(out)


def elektron_message(name: str, seq: int = 0) -> bytes:
    if name not in ELEKTRON_READ_ONLY:
        raise SystemExit(f"{name!r} is not in the read-only allowlist")
    opcode, payload, _ = ELEKTRON_READ_ONLY[name]
    body = bytes([(seq >> 8) & 0x7F, seq & 0xFF, 0, 0, opcode]) + payload
    return ELEKTRON_HEADER + encode87(body) + bytes([0xF7])


def elektron_reply(raw: bytes):
    """-> (opcode, body) for an Elektron SysEx reply, or None."""
    if len(raw) < 12 or raw[:6] != ELEKTRON_HEADER:
        return None
    body = decode87(raw[6:-1] if raw[-1] == 0xF7 else raw[6:])
    if len(body) < 5:
        return None
    return body[4], body[5:]


CALLBACK_FUNCTION = 0x00030000
# The mmsystem callback messages, in order. Getting LONGDATA wrong is silent:
# short messages keep arriving, so the input looks healthy while every SysEx
# reply is thrown away. This file had 0x3C5 -- which is MIM_ERROR -- and two
# "the device did not answer" results were recorded before that was found.
MIM_OPEN = 0x3C1
MIM_CLOSE = 0x3C2
MIM_DATA = 0x3C3
MIM_LONGDATA = 0x3C4
MIM_ERROR = 0x3C5
MIM_LONGERROR = 0x3C6
MHDR_DONE = 0x00000001


class MIDIHDR(ctypes.Structure):
    # lpData is c_void_p, NOT c_char_p. ctypes auto-converts a c_char_p FIELD
    # to a NUL-terminated Python bytes on attribute access, so reading it back
    # yields the buffer truncated at its first zero -- and passing that to
    # string_at then reads from a nonsense address. The first decode of a real
    # reply came back as 54 bytes of noise because of exactly this.
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wt.DWORD),
        ("dwBytesRecorded", wt.DWORD),
        ("dwUser", ctypes.c_void_p),
        ("dwFlags", wt.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_void_p),
        ("dwOffset", wt.DWORD),
        ("dwReserved", ctypes.c_void_p * 8),
    ]


class MIDIINCAPS(ctypes.Structure):
    _fields_ = [("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverVersion", wt.UINT),
                ("szPname", wt.WCHAR * 32), ("dwSupport", wt.DWORD)]


class MIDIOUTCAPS(ctypes.Structure):
    _fields_ = [("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverVersion", wt.UINT),
                ("szPname", wt.WCHAR * 32), ("wTechnology", wt.WORD),
                ("wVoices", wt.WORD), ("wNotes", wt.WORD),
                ("wChannelMask", wt.WORD), ("dwSupport", wt.DWORD)]


def list_ports():
    n_in = winmm.midiInGetNumDevs()
    n_out = winmm.midiOutGetNumDevs()
    ins, outs = [], []
    for i in range(n_in):
        c = MIDIINCAPS()
        winmm.midiInGetDevCapsW(i, ctypes.byref(c), ctypes.sizeof(c))
        ins.append(c.szPname)
    for i in range(n_out):
        c = MIDIOUTCAPS()
        winmm.midiOutGetDevCapsW(i, ctypes.byref(c), ctypes.sizeof(c))
        outs.append(c.szPname)
    return ins, outs


PROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.UINT, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p)


class InPort:
    """A MIDI input with several pre-posted SysEx buffers.

    Windows forbids calling any multimedia function from inside a MIDI
    callback; doing so deadlocks. The first version of this file called
    `midiInAddBuffer` from `on_msg`, which was harmless only for as long as
    MIM_LONGDATA never fired -- once the constant was corrected the very next
    run hung. So buffers are posted up front and the callback does nothing but
    copy bytes out.
    """

    def __init__(self, in_idx, nbuf=8, bufsize=65536):
        self.msgs = []
        self.shorts = []
        self.h = wt.HANDLE()
        self._bufs = [ctypes.create_string_buffer(bufsize) for _ in range(nbuf)]
        self._hdrs = []

        def on_msg(h, msg, inst, p1, p2):
            if msg == MIM_DATA:
                v = ctypes.cast(p1, ctypes.c_void_p).value or 0
                self.shorts.append(f"{v & 0xFF:02x} {(v >> 8) & 0xFF:02x} "
                                   f"{(v >> 16) & 0xFF:02x}")
            elif msg == MIM_LONGDATA:
                mh = ctypes.cast(p1, ctypes.POINTER(MIDIHDR)).contents
                if mh.dwBytesRecorded:
                    raw = ctypes.string_at(mh.lpData, mh.dwBytesRecorded)
                    self.msgs.append(raw)
                # deliberately NOT re-adding the buffer here -- see docstring

        self._cb = PROC(on_msg)
        rc = winmm.midiInOpen(ctypes.byref(self.h), in_idx, self._cb, None,
                              CALLBACK_FUNCTION)
        if rc:
            raise SystemExit(f"midiInOpen failed: {rc}")
        for b in self._bufs:
            hdr = MIDIHDR()
            hdr.lpData = ctypes.cast(b, ctypes.c_void_p)
            hdr.dwBufferLength = len(b)
            r1 = winmm.midiInPrepareHeader(self.h, ctypes.byref(hdr),
                                           ctypes.sizeof(hdr))
            r2 = winmm.midiInAddBuffer(self.h, ctypes.byref(hdr),
                                       ctypes.sizeof(hdr))
            if r1 or r2:
                raise SystemExit(f"buffer setup failed: prepare={r1} add={r2}")
            self._hdrs.append(hdr)
        rc = winmm.midiInStart(self.h)
        if rc:
            raise SystemExit(f"midiInStart failed: {rc}")

    def close(self):
        winmm.midiInStop(self.h)
        winmm.midiInReset(self.h)
        for hdr in self._hdrs:
            winmm.midiInUnprepareHeader(self.h, ctypes.byref(hdr),
                                        ctypes.sizeof(hdr))
        winmm.midiInClose(self.h)


def send_sysex(out_idx, payload):
    hout = wt.HANDLE()
    rc = winmm.midiOutOpen(ctypes.byref(hout), out_idx, None, None, 0)
    if rc:
        raise SystemExit(f"midiOutOpen failed: {rc}")
    sbuf = ctypes.create_string_buffer(payload, len(payload))
    shdr = MIDIHDR()
    shdr.lpData = ctypes.cast(sbuf, ctypes.c_void_p)
    shdr.dwBufferLength = len(payload)
    shdr.dwBytesRecorded = len(payload)
    r1 = winmm.midiOutPrepareHeader(hout, ctypes.byref(shdr), ctypes.sizeof(shdr))
    r2 = winmm.midiOutLongMsg(hout, ctypes.byref(shdr), ctypes.sizeof(shdr))
    print(f"  winmm out codes: open=0, prepare={r1}, longmsg={r2}")
    if r1 or r2:
        print("  *** non-zero: the message did NOT leave this machine ***")
    time.sleep(0.2)
    winmm.midiOutUnprepareHeader(hout, ctypes.byref(shdr), ctypes.sizeof(shdr))
    winmm.midiOutClose(hout)


def exchange(out_idx, in_idx, payload, wait=2.0, bufsize=65536):
    """Send `payload`, collect SysEx replies for `wait` seconds."""
    port = InPort(in_idx, bufsize=bufsize)
    try:
        send_sysex(out_idx, payload)
        t0 = time.time()
        while time.time() - t0 < wait:
            time.sleep(0.05)
        return list(port.msgs)
    finally:
        port.close()


def listen(in_idx, seconds, bufsize=65536):
    """Receive only -- separates 'the device declined' from 'we cannot hear'."""
    port = InPort(in_idx, bufsize=bufsize)
    try:
        print("  input chain open (all winmm codes 0)")
        t0 = time.time()
        while time.time() - t0 < seconds:
            time.sleep(0.05)
        return ([("short", x) for x in port.shorts]
                + [("sysex", m.hex(" ")) for m in port.msgs])
    finally:
        port.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true")
    p.add_argument("--out", type=int, help="output port index")
    p.add_argument("--in", dest="inp", type=int, help="input port index")
    p.add_argument("--send", choices=sorted(READ_ONLY))
    p.add_argument("--elektron", choices=sorted(ELEKTRON_READ_ONLY),
                   help="send a READ-ONLY Elektron SysEx request")
    p.add_argument("--wait", type=float, default=2.0)
    p.add_argument("--listen", type=float, metavar="SECONDS",
                   help="receive only -- proves the input path works before "
                        "'no reply' is read as an answer")
    args = p.parse_args(argv)

    ins, outs = list_ports()
    if args.listen:
        if args.inp is None:
            raise SystemExit("--listen needs --in")
        print(f"listening on [{args.inp}] {ins[args.inp]} for {args.listen}s. "
              f"Nothing is sent.\nTurn an encoder or press a key on the "
              f"device now.")
        got = listen(args.inp, args.listen)
        if not got:
            print("\nNOTHING received. The input path is not working, so the "
                  "earlier\n'no reply' says nothing about the device.")
        else:
            print(f"\n{len(got)} message(s) received -- the input path works:")
            for kind, data in got[:20]:
                print(f"  {kind:<5} {data}")
        return 0
    if args.elektron:
        if args.out is None or args.inp is None:
            raise SystemExit("--out and --in are required with --elektron")
        opcode, _pl, why = ELEKTRON_READ_ONLY[args.elektron]
        msg = elektron_message(args.elektron)
        print(f"out [{args.out}] {outs[args.out]}   in [{args.inp}] {ins[args.inp]}")
        print(f"\nsending elektron {args.elektron} (opcode 0x{opcode:02x}): "
              f"{msg.hex(' ')}")
        print(f"  ({why}; read-only allowlist)\n")
        got = exchange(args.out, args.inp, msg, args.wait)
        if not got:
            print("no reply within the window.")
            return 0
        for r in got:
            print(f"reply {len(r)} bytes: {r.hex(' ')}")
            parsed = elektron_reply(r)
            if parsed:
                op, body = parsed
                print(f"  opcode 0x{op:02x} (request | 0x80 = "
                      f"0x{opcode | 0x80:02x})")
                print(f"  body   {body.hex(' ')}")
                txt = bytes(c for c in body if 32 <= c < 127)
                if len(txt) >= 3:
                    print(f"  text   {txt.decode('ascii', 'replace')!r}")
        return 0
    if args.list or not args.send:
        print("MIDI IN:")
        for i, n in enumerate(ins):
            print(f"  [{i}] {n}")
        print("MIDI OUT:")
        for i, n in enumerate(outs):
            print(f"  [{i}] {n}")
        if not args.send:
            print("\nNothing sent. Pass --send with one of: "
                  + ", ".join(sorted(READ_ONLY)))
        return 0

    if args.out is None or args.inp is None:
        raise SystemExit("--out and --in are required with --send")

    payload, why = READ_ONLY[args.send]
    print(f"out port [{args.out}] {outs[args.out]}")
    print(f"in  port [{args.inp}] {ins[args.inp]}")
    print(f"\nsending {args.send}: {payload.hex(' ')}")
    print(f"  ({why})\n")

    got = exchange(args.out, args.inp, payload, args.wait)
    if not got:
        print("no reply within the window.")
        return 0
    for r in got:
        print(f"reply {len(r)} bytes: {r.hex(' ')}")
        if r[:2] == b"\xf0\x7e" and len(r) >= 6 and r[3] == 0x06 and r[4] == 0x02:
            man = r[5:8] if r[5] == 0 else r[5:6]
            print(f"  manufacturer : {man.hex(' ')}")
            if len(r) >= 12:
                print(f"  family       : {r[8+len(man)-1:10+len(man)-1].hex(' ')}")
                print(f"  member       : {r[10+len(man)-1:12+len(man)-1].hex(' ')}")
                print(f"  version      : {r[12+len(man)-1:-1].hex(' ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
