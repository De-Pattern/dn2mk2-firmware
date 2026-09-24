"""Serve the instrument's live MIDI as a page you can watch while you tweak.

    python scripts/midi_live.py                 # then open http://127.0.0.1:8737
    python scripts/midi_live.py --in 0 --port 8737

**Why local and not an artifact.** A published page cannot reach a MIDI port on
this machine, so a hosted page can only ever show a capture after the fact. The
point of telemetry is to change something on the instrument and watch the value
move, so the page is served from here, by the same process that holds the port.

**Why this exists at all.** Six firmware builds were flashed on 2026-09-23 to
read one number each off the LFO4 page, and the page turned out to render only
the high byte of what a column returned -- so every value, all of them 0..15,
displayed identically. This is the wider channel that replaces it.

**No dependency.** `winmm` through `ctypes` for MIDI (see `scripts/midi_probe.py`,
whose `InPort` is imported rather than copied) and the standard library's
`http.server` for the page. Events reach the browser over Server-Sent Events,
which is one HTTP response held open -- no websocket library, no build step.

**Read-only.** No output port is ever opened. Nothing here can send a byte to
the instrument.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from midi_probe import InPort, list_ports  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PAGE = HERE / "midi_live_page.html"
MAP = ROOT / "src" / "dnfw" / "telemetry" / "channels.json"

SYSTEM = {0xF8: "clock", 0xFA: "start", 0xFB: "continue", 0xFC: "stop",
          0xFE: "active-sense", 0xFF: "reset"}
KIND = {0x80: "note-off", 0x90: "note-on", 0xA0: "aftertouch",
        0xB0: "cc", 0xC0: "program", 0xD0: "pressure", 0xE0: "bend"}


def channel_map() -> dict:
    spec = json.loads(MAP.read_text(encoding="utf-8"))
    return {"channel": spec["channel"],
            "names": {str(s["cc"]): s["name"] for s in spec["signals"]}}


def parse(raw: str, t: float) -> dict | None:
    """One short MIDI message -> the event the page renders, or None to drop.

    The clock is dropped here rather than in the page: at 120 BPM it is 24
    messages per quarter-note, about 96% of the traffic, and shipping it to the
    browser would bury everything else for no benefit. `start`, `stop` and
    `continue` are kept -- they say what the sequencer is doing.
    """
    b = [int(x, 16) for x in raw.split()]
    if not b:
        return None
    if b[0] == 0xF8 or b[0] == 0xFE:
        return None
    if b[0] >= 0xF8:
        return {"t": t, "kind": SYSTEM.get(b[0], f"system {b[0]:#04x}"),
                "raw": " ".join(f"{v:02x}" for v in b[:1])}
    status, chan = b[0] & 0xF0, (b[0] & 0x0F) + 1
    d1 = b[1] if len(b) > 1 else 0
    d2 = b[2] if len(b) > 2 else 0
    return {"t": t, "kind": KIND.get(status, f"{status:#04x}"), "ch": chan,
            "d1": d1, "d2": d2,
            "raw": " ".join(f"{v:02x}" for v in (b[0], d1, d2))}


class Bus:
    """Fan one MIDI stream out to however many browser tabs are open."""

    def __init__(self) -> None:
        self.subs: list[queue.Queue] = []
        self.lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self.lock:
            self.subs.append(q)
        return q

    def drop(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def publish(self, ev: dict) -> None:
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass          # a tab that cannot keep up loses events, not the port


class Holder:
    """The open port, behind a handle that can be swapped.

    **A flash re-enumerates the instrument**, and Windows leaves the old
    `midiInOpen` handle looking valid while it silently delivers nothing. That
    cost two wrong diagnoses in ten minutes -- the page looked healthy and was
    deaf. So the port lives here and `reopen()` replaces it without restarting
    the server or losing the browser's connection.
    """

    def __init__(self, in_idx: int) -> None:
        self.in_idx = in_idx
        self.port = InPort(in_idx)
        self.lock = threading.Lock()

    def reopen(self) -> str:
        with self.lock:
            try:
                self.port.close()
            except Exception:                 # noqa: BLE001 -- a dead handle may refuse
                pass
            ins, _ = list_ports()
            if self.in_idx >= len(ins):
                return f"no input {self.in_idx}; there are {len(ins)}"
            self.port = InPort(self.in_idx)
            return f"reopened [{self.in_idx}] {ins[self.in_idx]}"


def pump(holder: "Holder", bus: Bus, started: float) -> None:
    """Move messages off the callback's list and onto the bus.

    The callback itself must stay trivial -- `midi_probe.InPort` documents why:
    calling a multimedia function from inside it deadlocks Windows.
    """
    while True:
        port = holder.port
        while port.shorts:
            ev = parse(port.shorts.pop(0), round(time.time() - started, 3))
            if ev:
                bus.publish(ev)
        time.sleep(0.004)


def handler(bus: Bus, started: float, holder: "Holder"):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):        # the page is the output, not the log
            pass

        def do_GET(self):
            if self.path.startswith("/events"):
                return self.stream()
            if self.path.startswith("/map"):
                return self.send_json(channel_map())
            if self.path.startswith("/reopen"):
                msg = holder.reopen()
                print(f"  {msg}")
                return self.send_json({"ok": "reopened" in msg, "message": msg})
            return self.send_page()

        def send_page(self):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = bus.subscribe()
            try:
                self.wfile.write(b": open\n\n")
                self.wfile.flush()
                last_beat = time.time()
                while True:
                    try:
                        ev = q.get(timeout=1.0)
                        self.wfile.write(b"data: " + json.dumps(ev).encode() + b"\n\n")
                        self.wfile.flush()
                    except queue.Empty:
                        # a comment keeps the connection alive and, more usefully,
                        # lets the page tell "quiet" from "disconnected"
                        if time.time() - last_beat > 1.0:
                            self.wfile.write(b": beat\n\n")
                            self.wfile.flush()
                            last_beat = time.time()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                bus.drop(q)

    return H


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--list", action="store_true")
    p.add_argument("--in", dest="in_idx", type=int, default=0)
    p.add_argument("--port", type=int, default=8737)
    args = p.parse_args()

    if args.list:
        ins, outs = list_ports()
        for label, names in (("MIDI IN", ins), ("MIDI OUT", outs)):
            print(f"{label}:")
            for i, n in enumerate(names):
                print(f"  [{i}] {n}")
        return 0

    ins, _ = list_ports()
    if not ins:
        print("  No MIDI inputs. The instrument is not connected, or another")
        print("  application (Overbridge, Transfer) holds the port exclusively.")
        return 1
    if args.in_idx >= len(ins):
        print(f"  No input {args.in_idx}; there are {len(ins)}.")
        return 1

    started = time.time()
    bus = Bus()
    holder = Holder(args.in_idx)
    threading.Thread(target=pump, args=(holder, bus, started), daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 handler(bus, started, holder))
    print(f"  listening to [{args.in_idx}] {ins[args.in_idx]}")
    print(f"  open  http://127.0.0.1:{args.port}")
    print("  ctrl-c to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        holder.port.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
