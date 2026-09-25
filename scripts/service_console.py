"""Ask a Digitone in maintenance mode a read-only question, over its USB console.

    python scripts/service_console.py --list
    python scripts/service_console.py                 # the default read-only set
    python scripts/service_console.py "#STATUS"

`docs/service-commands.md` reads the whole path in the firmware and
`scripts/emu_service_commands.py` exercises the dispatcher under the emulator.
This is the same conversation with a real instrument.

**Two transports, because of a descriptor bug in the instrument.** In
maintenance mode it enumerates as VID 0x1935 / PID 0xFFFF and its configuration
is a textbook CDC-ACM -- control interface 0 (class 02/02/01), data interface 1
(class 0a) with bulk OUT 0x02 and bulk IN 0x82. But its **interface association
descriptor declares the function as class 02/01/01**, one subclass off, and
Windows builds the driver match from the IAD: it asks for a Direct Line Control
Model driver, which does not exist, and reports "no compatible drivers" (code
28). Forcing the in-box USB Serial driver onto it produces a COM port whose
writes time out, because the data interface never gets set up. Both DN1 1.43 and
DN2 1.11 carry the same descriptor.

So: `usb` talks to the two bulk endpoints directly (needs WinUSB or libusbK
bound to the device, e.g. with Zadig), and `serial` uses a COM port where the
host did manage to bind CDC -- Linux binds by interface class and does.

**It will only send commands on the allow list below.** Not a deny list: a
command this project has not read is refused, including `#MMCDUMP`, whose
handler is still unread. (`#MRAM_DUMP` was read on 2026-09-25 and added; see
`ALLOWED`.) Anything that writes, plays,
records, reboots or reconfigures is not here and is not reachable by argument --
`--force` does not exist. Adding one is a deliberate edit to this file, which is
the point.

The instrument is in a service state while this runs. Nothing here changes its
storage, its calibration or its firmware.
"""

from __future__ import annotations

import argparse
import time

VID, PID = 0x1935, 0xFFFF
DATA_INTERFACE, EP_OUT, EP_IN = 1, 0x02, 0x82

# Read-only, and each one read in the firmware (docs/service-commands.md).
ALLOWED = [
    "#HELLO",                    # HOW DO YOU DO?
    "#STATUS",                   # sections: START, OS, PLATFORM, PRODUCT, FLASH
    "#READ_SERIAL",
    "#READ_TESTED", "#READ_UI_TESTED", "#READ_AUDIO_TESTED", "#READ_UI_TEST_COMPLETED",
    "#TEST_STATUS",
    "#DUMP_UI_CALIBRATION",
    "#MMC_GET_RECONFIGURED", "#MMC_GET_HEALTH",           # the second is DN2 only
    # **Read 2026-09-25 before it was added** (handler at 0x400cdfb8): it sends
    # a 5-byte header -- '!' then a big-endian u32 length, 0x00c4b114 --
    # through the console's transmit ring (0x400053d4), then streams the RAM
    # buffer at 0x405cd85c (a 0x110-byte header followed by the serialised
    # project image) in 512-byte chunks (0x400cd204). It reads memory and
    # writes nothing. That buffer is the working state the firmware flushes to
    # flash, which is why it is worth having. DN2 only. Use --out.
    "#MRAM_DUMP",
    # Digitone 1 only, from its own command table:
    "#READ_ADC", "#READ_ADC_REF", "#READ_JACK_STATUS",
    "#READ_WHEEL_CALIBRATED", "#READ_WHEEL_CALIBRATION",
]
DEFAULT = ["#HELLO", "#STATUS", "#READ_SERIAL", "#READ_TESTED", "#READ_UI_TESTED",
           "#READ_UI_TEST_COMPLETED", "#TEST_STATUS", "#MMC_GET_RECONFIGURED"]


def allowed(line: str) -> bool:
    return bool(line.split()) and line.split()[0].upper() in ALLOWED


class UsbLink:
    """The two bulk endpoints, with no CDC layer in between."""

    def __init__(self):
        import libusb_package
        import usb.util

        self.util = usb.util
        self.device = libusb_package.find(idVendor=VID, idProduct=PID)
        if self.device is None:
            raise LookupError("no instrument in maintenance mode (VID 0x1935 / PID 0xffff)")
        self.util.claim_interface(self.device, DATA_INTERFACE)
        # Claiming again after a release can leave a pipe halted, and the symptom
        # is a console that accepts writes and answers nothing (2026-09-20: a
        # second session on a DN1 went silent from its first command, and a
        # USB-level reset did not recover it). Clearing both pipes costs nothing.
        for endpoint in (EP_OUT, EP_IN):
            try:
                self.device.clear_halt(endpoint)
            except Exception:
                pass
        self.drain()

    def drain(self) -> bytes:
        """Anything left over from a previous session, so a reply is this one's."""
        import usb.core

        out = b""
        while True:
            try:
                out += bytes(self.device.read(EP_IN, 512, timeout=200))
            except usb.core.USBTimeoutError:
                return out
            except Exception:
                return out

    def send(self, line: str) -> None:
        self.device.write(EP_OUT, line.encode() + b"\n", timeout=2000)

    def receive(self, settle: float) -> bytes:
        import usb.core

        out, quiet = b"", time.time() + 2.0
        while time.time() < quiet:
            try:
                chunk = bytes(self.device.read(EP_IN, 512, timeout=int(settle * 1000)))
            except usb.core.USBTimeoutError:
                if out:
                    break
                continue
            out += chunk
            quiet = time.time() + settle
        return out

    def read_exact(self, n: int, progress=None) -> bytes:
        """Exactly `n` bytes, or what arrived before 5 s of silence."""
        import usb.core

        out = bytearray()
        quiet = 0
        while len(out) < n:
            try:
                out += bytes(self.device.read(EP_IN, 16384, timeout=1000))
                quiet = 0
                if progress:
                    progress(len(out))
            except usb.core.USBTimeoutError:
                quiet += 1
                if quiet >= 5:
                    break
        return bytes(out[:n]) if len(out) >= n else bytes(out)

    def close(self):
        self.util.release_interface(self.device, DATA_INTERFACE)
        self.util.dispose_resources(self.device)


class SerialLink:
    """A COM port, where the host bound CDC to it."""

    def __init__(self, port=None):
        import serial
        from serial.tools import list_ports

        if port is None:
            found = [p.device for p in list_ports.comports() if p.vid == VID and p.pid == PID]
            if not found:
                raise LookupError("no COM port with VID 0x1935 / PID 0xffff")
            port = found[0]
        self.port = port
        self.link = serial.Serial(port, 115200, timeout=1.0, write_timeout=2.0)

    def send(self, line: str) -> None:
        self.link.write(line.encode() + b"\n")
        self.link.flush()

    def receive(self, settle: float) -> bytes:
        out, quiet = b"", time.time() + 2.0
        while time.time() < quiet:
            chunk = self.link.read(512)
            if chunk:
                out += chunk
                quiet = time.time() + settle
            elif out:
                break
        return out

    def read_exact(self, n: int, progress=None) -> bytes:
        out = bytearray()
        quiet = 0
        while len(out) < n:
            chunk = self.link.read(min(16384, n - len(out)))
            if chunk:
                out += chunk
                quiet = 0
                if progress:
                    progress(len(out))
            else:
                quiet += 1
                if quiet >= 5:
                    break
        return bytes(out)

    def close(self):
        self.link.close()


def connect(transport: str, port=None):
    if transport in ("usb", "auto"):
        try:
            return UsbLink()
        except Exception as exc:
            if transport == "usb":
                raise SystemExit(f"cannot claim the bulk interface: {exc}\n"
                                 "Bind WinUSB (or libusbK) to the device first -- Windows' own CDC "
                                 "match fails on this instrument's IAD; see this file's header.")
            print(f"  (usb: {exc}; falling back to a COM port)")
    return SerialLink(port)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("commands", nargs="*", help=f"default: {' '.join(DEFAULT)}")
    p.add_argument("--transport", choices=("auto", "usb", "serial"), default="auto")
    p.add_argument("--port", help="COM port, for the serial transport")
    p.add_argument("--settle", type=float, default=0.6, help="quiet time that ends a reply")
    p.add_argument("--list", action="store_true", help="what the host can see")
    p.add_argument("--out", help="file for #MRAM_DUMP's binary stream (required with it)")
    args = p.parse_args()

    if args.list:
        import libusb_package
        from serial.tools import list_ports

        device = libusb_package.find(idVendor=VID, idProduct=PID)
        print(f"  usb    {'found, bus %d address %d' % (device.bus, device.address) if device else 'not found'}")
        ports = [(p.device, p.description) for p in list_ports.comports() if p.vid == VID and p.pid == PID]
        print("  serial " + (", ".join(f"{d} ({t})" for d, t in ports) if ports else "no port"))
        return 0 if device or ports else 1

    commands = args.commands or DEFAULT
    refused = [c for c in commands if not allowed(c)]
    if refused:
        raise SystemExit(f"not on the read-only allow list, refusing: {refused}\n"
                         f"allowed: {' '.join(ALLOWED)}")

    link = connect(args.transport, args.port)
    print(f"{type(link).__name__}: asking {len(commands)} read-only command(s)\n")
    try:
        for line in commands:
            if line.split()[0].upper() == "#MRAM_DUMP":
                if not args.out:
                    raise SystemExit("#MRAM_DUMP streams ~12.9 MB of binary: give --out FILE")
                link.send(line)
                head = link.read_exact(5)
                if len(head) < 5 or head[:1] != b"!":
                    print(f"  > {line}\n  < unexpected header {head.hex()} -- nothing saved\n")
                    continue
                size = int.from_bytes(head[1:5], "big")
                print(f"  > {line}\n  < header ok, {size:,} bytes follow")
                last = [0]

                def show(n, size=size, last=last):
                    if n - last[0] >= 1 << 20 or n >= size:
                        last[0] = n
                        print(f"    {n:,} / {size:,}")

                body = link.read_exact(size, progress=show)
                import pathlib
                pathlib.Path(args.out).write_bytes(body)
                state = "complete" if len(body) == size else f"SHORT by {size - len(body):,}"
                print(f"  wrote {args.out}: {len(body):,} bytes, {state}\n")
                continue
            link.send(line)
            reply = link.receive(args.settle).decode("latin-1")
            print(f"  > {line}")
            for text in reply.replace("\r\n", "\n").rstrip().splitlines():
                print(f"  < {text}")
            if not reply.strip():
                print("  < (no reply)")
            print()
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
