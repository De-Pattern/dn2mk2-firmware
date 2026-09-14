"""Send a READ-ONLY SysEx request to a connected instrument and show the reply.

## Safety, which is the whole design of this file

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

CALLBACK_FUNCTION = 0x00030000
MIM_DATA = 0x3C3
MIM_LONGDATA = 0x3C5
MHDR_DONE = 0x00000001


class MIDIHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_char_p),
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


def exchange(out_idx, in_idx, payload, wait=2.0, bufsize=65536):
    """Send `payload`, collect SysEx replies for `wait` seconds."""
    received = []

    hin = wt.HANDLE()
    buf = ctypes.create_string_buffer(bufsize)
    hdr = MIDIHDR()
    hdr.lpData = ctypes.cast(buf, ctypes.c_char_p)
    hdr.dwBufferLength = bufsize

    def on_msg(h, msg, inst, p1, p2):
        if msg == MIM_LONGDATA:
            mh = ctypes.cast(p1, ctypes.POINTER(MIDIHDR)).contents
            if mh.dwBytesRecorded:
                received.append(bytes(buf[:mh.dwBytesRecorded]))
            winmm.midiInAddBuffer(hin, ctypes.byref(hdr), ctypes.sizeof(hdr))

    cb = PROC(on_msg)
    rc = winmm.midiInOpen(ctypes.byref(hin), in_idx, cb, None,
                          CALLBACK_FUNCTION)
    if rc:
        raise SystemExit(f"midiInOpen failed: {rc}")
    winmm.midiInPrepareHeader(hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.midiInAddBuffer(hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.midiInStart(hin)

    hout = wt.HANDLE()
    rc = winmm.midiOutOpen(ctypes.byref(hout), out_idx, None, None, 0)
    if rc:
        raise SystemExit(f"midiOutOpen failed: {rc}")

    sbuf = ctypes.create_string_buffer(payload, len(payload))
    shdr = MIDIHDR()
    shdr.lpData = ctypes.cast(sbuf, ctypes.c_char_p)
    shdr.dwBufferLength = len(payload)
    shdr.dwBytesRecorded = len(payload)
    winmm.midiOutPrepareHeader(hout, ctypes.byref(shdr), ctypes.sizeof(shdr))
    winmm.midiOutLongMsg(hout, ctypes.byref(shdr), ctypes.sizeof(shdr))

    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(0.05)

    winmm.midiOutUnprepareHeader(hout, ctypes.byref(shdr), ctypes.sizeof(shdr))
    winmm.midiOutClose(hout)
    winmm.midiInStop(hin)
    winmm.midiInReset(hin)
    winmm.midiInUnprepareHeader(hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.midiInClose(hin)
    return received


def listen(in_idx, seconds, bufsize=65536):
    """Receive only. Captures short messages AND SysEx.

    The point is the control: if the device never answers an inquiry we must
    be able to tell "it declined" from "we cannot hear it". A turned encoder
    produces short messages, so this separates the two.
    """
    got = []
    hin = wt.HANDLE()
    buf = ctypes.create_string_buffer(bufsize)
    hdr = MIDIHDR()
    hdr.lpData = ctypes.cast(buf, ctypes.c_char_p)
    hdr.dwBufferLength = bufsize

    def on_msg(h, msg, inst, p1, p2):
        if msg == MIM_DATA:
            v = ctypes.cast(p1, ctypes.c_void_p).value or 0
            got.append(("short", f"{v & 0xFF:02x} {(v >> 8) & 0xFF:02x} "
                                 f"{(v >> 16) & 0xFF:02x}"))
        elif msg == MIM_LONGDATA:
            mh = ctypes.cast(p1, ctypes.POINTER(MIDIHDR)).contents
            if mh.dwBytesRecorded:
                got.append(("sysex", bytes(buf[:mh.dwBytesRecorded]).hex(" ")))
            winmm.midiInAddBuffer(hin, ctypes.byref(hdr), ctypes.sizeof(hdr))

    cb = PROC(on_msg)
    rc = winmm.midiInOpen(ctypes.byref(hin), in_idx, cb, None, CALLBACK_FUNCTION)
    if rc:
        raise SystemExit(f"midiInOpen failed: {rc}")
    winmm.midiInPrepareHeader(hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.midiInAddBuffer(hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.midiInStart(hin)
    t0 = time.time()
    while time.time() - t0 < seconds:
        time.sleep(0.05)
    winmm.midiInStop(hin)
    winmm.midiInReset(hin)
    winmm.midiInUnprepareHeader(hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.midiInClose(hin)
    return got


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true")
    p.add_argument("--out", type=int, help="output port index")
    p.add_argument("--in", dest="inp", type=int, help="input port index")
    p.add_argument("--send", choices=sorted(READ_ONLY))
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
