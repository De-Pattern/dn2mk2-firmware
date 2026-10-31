"""v0.34: ask the unit what poisons a voice (docs/timing-model.md), over USB MIDI, read-only.

    python tools/dn2diag.py                      DIAG, then the four scans, in plain words
    python tools/dn2diag.py diag                 the guard's record, the DSP load, the counters
    python tools/dn2diag.py scan ADDR WORDS      non-finite words in any DSP memory range
    python tools/dn2diag.py watch [SECONDS]      the four scans again every two seconds

The scans (each the DSP walking the range, 1,024 words a block, about 2 ms):

    voice 1's P-I delay lines   0x82200000  2048 words     voice 4's   0x82206000
    the 16 voices' L2 state     0x200a0000  4096 words     the PERC state  0x2de180  512

Run it right after a power-on, before any note is played, then after the note that kills
voice 1, then `watch` with nothing playing. A non-finite word before any note says the
memory is poisoned at boot (the fill did not land, or something wrote there); one that
appears while nothing plays says something on the unit writes there; one only after a note
says our own voice made it. Needs a v0.34 build (SysEx commands 24 and 25).
"""

from __future__ import annotations

import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from dn2samples import HELLO, Link  # noqa: E402

DIAG, SCAN = 24, 25
SCANS = (("voice 1's P-I delay lines (DDR)", 0x82200000, 2048),
         ("voice 4's P-I delay lines (DDR)", 0x82206000, 2048),
         ("the 16 voices' Machinedrum state (L2)", 0x200A0000, 4096),
         ("the 16 voices' PERC state (L1)", 0x2DE180, 512))


def u32s(p: bytes) -> list[int]:
    return list(struct.unpack(f">{len(p) // 4}I", p[:len(p) // 4 * 4]))


def diag(link: Link) -> dict:
    d = u32s(link.call(DIAG))
    keys = ("wipes", "info", "where", "mask", "since", "load", "load_peak", "skipped", "periods", "frames",
            "scan_count", "scan_first", "scan_done", "scan_seq")
    return dict(zip(keys, d))


def say_diag(d: dict) -> None:
    print(f"DSP load {d['load']} % (peak {d['load_peak'] / 10:.1f} %), {d['frames']:,} audio frames since power-on")
    if d["wipes"]:
        slot, mtype = d["info"] & 0xFF, d["info"] >> 8
        where = d["where"]
        w = ("its delay lines, word %d" % (where & 0x7FFF)) if where & 0x8000 and where != 0xFFFF else "not its delay lines (its own state, its input or the effects)"
        ago = "" if d["since"] == 0xFFFFFFFF else f", the last {d['since'] / 1500:.1f} s ago"
        print(f"the output guard wiped a voice {d['wipes']} time(s){ago}: last voice {slot + 1}, machine type {mtype}, "
              f"the NaN in {w}; voices ever wiped: {[t + 1 for t in range(16) if d['mask'] >> t & 1]}")
    else:
        print("the output guard has wiped no voice since power-on")
    if d["skipped"]:
        print(f"voices left out for DSP time at some point: {[t + 1 for t in range(16) if d['skipped'] >> t & 1]}")


def scan(link: Link, addr: int, words: int, timeout: float = 5.0) -> tuple[int, int]:
    """-> (non-finite words, the first one's index or -1)"""
    p = link.call(SCAN, struct.pack(">II", addr, words))
    seq = struct.unpack(">H", p[:2])[0]
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = diag(link)
        if d["scan_done"] == (seq & 0xFFFF) and d["scan_seq"] == seq:
            first = -1 if d["scan_first"] == 0xFFFFFFFF else d["scan_first"]
            return d["scan_count"], first
        time.sleep(0.05)
    raise TimeoutError("the scan did not finish (is the DSP's link up?)")


def say_scans(link: Link) -> None:
    for name, addr, words in SCANS:
        n, first = scan(link, addr, words)
        if n:
            print(f"  {name}: {n} non-finite word(s), the first at index {first} (address {addr + 4 * first:#010x})")
        else:
            print(f"  {name}: clean")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    port_name = "Digitone II"
    if "--port" in args:
        k = args.index("--port")
        port_name = args[k + 1]
        del args[k:k + 2]
    import winmidi  # noqa: PLC0415
    port = winmidi.Port(port_name)
    try:
        link = Link(port)
        proto = struct.unpack(">H", link.call(HELLO)[:2])[0]
        if proto < 5:
            raise SystemExit(f"sample link {proto}: a v0.34 build is needed")
        cmd = args[0] if args else "all"
        if cmd == "diag":
            say_diag(diag(link))
        elif cmd == "scan":
            n, first = scan(link, int(args[1], 0), int(args[2], 0))
            print(f"{n} non-finite word(s)" + (f", the first at index {first}" if n else ""))
        elif cmd == "watch":
            end = time.time() + (float(args[1]) if len(args) > 1 else 60.0)
            while time.time() < end:
                print(time.strftime("%H:%M:%S"))
                say_scans(link)
                time.sleep(2.0)
        else:
            say_diag(diag(link))
            print("scans:")
            say_scans(link)
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
