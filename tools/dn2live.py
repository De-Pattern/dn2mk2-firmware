"""The live MIDI page, plus the USB probe's telemetry, from one process holding the DN2's port.

derived from irpina/digihealth (tools/digiusb.py, tools/winmidi.py), GPL-2.0-or-later, used here under GPL-3.0 within this AGPL-3.0-or-later project

    python tools/dn2live.py                       then open http://127.0.0.1:8737
    python tools/dn2live.py --rate 10 --port "Digitone II"
    python tools/dn2live.py --in 1 --out 2 --http 8737
    python tools/dn2live.py --symbols out/fxmod-lfo4fast-songguard-arpmodes-usbprobe/symbols.json
                                                  a profiling build: lfo4's timers too
    powershell -File tools/dn2live_launch.ps1     kill a stale one, start, open the page

It is `scripts/midi_live.py` (whose parser, bus and signal map are imported,
not copied, and whose page is served with a probe panel added at its foot)
holding the **output** as well as the input, so it can ask the probe for STATS.
The probe's replies are taken out of the MIDI stream before it reaches the page;
every other message, SysEx included, is shown as midi_live shows it.

Modules, one job each: `dn2port` the winmm port, `dn2poll` the conversation
with the probe, `dn2stats` the readings, `dn2log` the run's files, this file
the wiring and the HTTP/SSE server; the panel is `dn2live_panel.js` / `.css`.

**The MIDI view can be switched off** (the page's MIDI view button, or
`--no-midi`): non-probe messages are then dropped at the pump, neither sent nor
logged, and the poll rate may go past 10 Hz to 25 or 50. The rate the port
actually sustains is measured per request and shown beside the asked one.

**Read-only on the instrument.** The only bytes sent are the probe's HELLO and
STATS, and the probe has no command that writes. Stock firmware drops them
(device byte 0x7D is above its router's table) and the page says "no probe on
this firmware" while the MIDI view goes on working.

It talks to the probe (`dnfw mods apply --mod usbprobe`), which is derived
from irpina/digihealth (GPL-2.0-or-later).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import queue
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

import dn2log  # noqa: E402
import dn2poll  # noqa: E402

PANEL_JS = HERE / "dn2live_panel.js"
PANEL_CSS = HERE / "dn2live_panel.css"
LOG_DIR = ROOT / "out" / "dn2live"
BACKLOG_S = 70                 # what a tab opened late is handed: a bit over the graph's 60 s
MIDI_ON_MAX_HZ = 10


def _midi_live():
    """scripts/midi_live.py: its parser, bus, signal map and page (imported lazily:
    it loads winmm at import, through midi_probe)."""
    import midi_live
    return midi_live


def short_raw(v: int) -> str:
    """A packed winmm short message -> midi_live.parse's input."""
    return f"{v & 0xFF:02x} {(v >> 8) & 0xFF:02x} {(v >> 16) & 0xFF:02x}"


def sysex_event(raw: bytes, t: float) -> dict:
    head = raw[:16].hex(" ") + (" .. f7" if len(raw) > 16 else "")
    return {"t": t, "kind": "sysex", "raw": head, "len": len(raw)}


class Holder:
    """The open port behind a swappable handle: a flash re-enumerates the instrument
    and leaves the old handle looking fine while it hears nothing (midi_live.Holder)."""

    def __init__(self, opener):
        self.opener = opener
        self.lock = threading.Lock()
        self.port, self.names = opener()

    def send(self, data: bytes) -> None:
        port = self.port
        if port is None:
            raise OSError("no port open")
        port.send(data)

    def reopen(self) -> str:
        with self.lock:
            old, self.port = self.port, None
            try:
                if old is not None:
                    old.close()
            except Exception:                 # noqa: BLE001 -- a dead handle may refuse
                pass
            try:
                self.port, self.names = self.opener()
            except OSError as exc:
                return f"reopen failed: {exc}"
            return f"reopened in {self.names[0]!r}, out {self.names[1]!r}"

    def close(self) -> None:
        with self.lock:
            if self.port is not None:
                self.port.close()
                self.port = None


class Live:
    """The running state: port, poller, bus, log, and the MIDI view switch."""

    def __init__(self, opener, rate_hz: float = dn2poll.DEFAULT_HZ, midi_on: bool = True,
                 log_dir: pathlib.Path = LOG_DIR, started: float | None = None,
                 lfo4: tuple | None = None):
        ml = _midi_live()
        self.ml = ml
        self.started = time.time() if started is None else started
        self.bus = ml.Bus()
        self.log = dn2log.RunLog(log_dir)
        self.backlog: deque = deque()
        self.marks: list[dict] = []
        self.last_status: dict = {}
        self.last_cost: dict | None = None
        self.midi_on = midi_on
        self.stop = threading.Event()
        self.holder = Holder(opener)
        if midi_on:
            rate_hz = min(rate_hz, MIDI_ON_MAX_HZ)
        self.poller = dn2poll.Poller(self.holder.send, self.publish, rate_hz=rate_hz, t0=self.started,
                                     lfo4=lfo4)

    # ---- events ---------------------------------------------------------------

    def publish(self, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "probe-status":
            self.last_status = ev
        elif kind == "probe-cost":
            self.last_cost = ev
        elif kind == "mark":
            self.marks.append(ev)
        if kind in ("probe", "mark", "probe-cost", "probe-lfo4"):
            self.backlog.append(ev)
            cut = ev["t"] - BACKLOG_S
            while self.backlog and self.backlog[0]["t"] < cut:
                self.backlog.popleft()
        self.log.write(ev)
        self.bus.publish(ev)

    def mark(self, label: str) -> dict:
        ev = {"type": "mark", "t": round(time.time() - self.started, 3),
              "label": (label or "mark").strip()[:80]}
        self.publish(ev)
        return ev

    def state(self) -> dict:
        return {"type": "state", "status": self.last_status, "midi_on": self.midi_on,
                "cost": self.last_cost, "log": str(self.log.csv_path),
                "jsonl": str(self.log.jsonl_path), "names": list(self.holder.names),
                "midi_on_max_hz": MIDI_ON_MAX_HZ, "rates": list(dn2poll.RATES),
                "lfo4": bool(self.poller.lfo4),
                "now": round(time.time() - self.started, 3)}

    def set_midi(self, on: bool) -> dict:
        self.midi_on = on
        if on and self.poller.rate_hz > MIDI_ON_MAX_HZ:
            self.poller.set_rate(MIDI_ON_MAX_HZ)
        st = self.state()
        self.bus.publish(st)
        return st

    def set_rate(self, hz: float) -> tuple[float, str]:
        note = ""
        if self.midi_on and hz > MIDI_ON_MAX_HZ:
            hz, note = MIDI_ON_MAX_HZ, f"capped at {MIDI_ON_MAX_HZ} Hz while the MIDI view is on"
        return self.poller.set_rate(hz), note

    # ---- threads ---------------------------------------------------------------

    def pump(self) -> None:
        """Port -> poller (the probe's replies) and bus (everything else, if the view is on)."""
        while not self.stop.is_set():
            port = self.holder.port
            if port is None:
                time.sleep(0.05)
                continue
            try:
                port.service()
            except Exception:                 # noqa: BLE001 -- a handle closed under us
                time.sleep(0.05)
                continue
            while port.shorts:
                t, v = port.shorts.pop(0)
                if not self.midi_on:
                    continue
                ev = self.ml.parse(short_raw(v), round(t - self.started, 3))
                if ev:
                    self.publish(ev)
            while port.sysex:
                t, raw = port.sysex.pop(0)
                if self.poller.on_sysex(raw, t):
                    continue
                if self.midi_on:
                    self.publish(sysex_event(raw, round(t - self.started, 3)))
            time.sleep(0.001)

    def start(self) -> None:
        threading.Thread(target=self.pump, daemon=True, name="pump").start()
        threading.Thread(target=self.poller.run, args=(self.stop,), daemon=True, name="poll").start()

    def close(self) -> None:
        self.stop.set()
        time.sleep(0.05)
        self.holder.close()
        self.log.close()


def page(ml) -> bytes:
    """midi_live's page with the probe panel at its foot. The public page is not
    edited: the panel is added here, as it is served."""
    html = ml.PAGE.read_text(encoding="utf-8")
    html = html.replace("<title>Live MIDI — Digitone II</title>",
                        "<title>DN2 Live — MIDI and probe</title>", 1)
    html = html.replace("</head>", '<link rel="stylesheet" href="/panel.css">\n</head>', 1)
    html = html.replace("</body>", '<script src="/panel.js"></script>\n</body>', 1)
    return html.encode("utf-8")


def handler(live: Live):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            pass

        def do_POST(self):
            return self.do_GET()

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(u.query).items()}
            p = u.path
            if p == "/events":
                return self.stream()
            if p == "/map":
                return self.send_json(live.ml.channel_map())
            if p == "/state":
                return self.send_json(live.state())
            if p == "/reopen":
                msg = live.holder.reopen()
                live.poller.restart()
                print(f"  {msg}")
                return self.send_json({"ok": msg.startswith("reopened"), "message": msg})
            if p == "/mark":
                return self.send_json(live.mark(q.get("label", "mark")))
            if p == "/rate":
                try:
                    hz, note = live.set_rate(float(q.get("hz", dn2poll.DEFAULT_HZ)))
                except ValueError:
                    return self.send_json({"ok": False, "message": "hz must be a number"})
                return self.send_json({"ok": True, "rate_hz": hz, "message": note})
            if p == "/midi":
                return self.send_json(live.set_midi(q.get("on", "1") not in ("0", "off", "false")))
            if p == "/calibrate":
                live.poller.calibrate()
                return self.send_json({"ok": True, "message": "calibrating: 5 Hz, then 25 Hz, 5 s each"})
            if p == "/panel.js":
                return self.send_file(PANEL_JS, "text/javascript; charset=utf-8")
            if p == "/panel.css":
                return self.send_file(PANEL_CSS, "text/css; charset=utf-8")
            return self.send_body(page(live.ml), "text/html; charset=utf-8")

        def send_body(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def send_file(self, path: pathlib.Path, ctype: str):
            return self.send_body(path.read_bytes(), ctype)

        def send_json(self, obj):
            return self.send_body(json.dumps(obj).encode(), "application/json")

        def write_event(self, ev: dict):
            kind = ev.get("type")
            head = f"event: {kind}\n".encode() if kind else b""
            self.wfile.write(head + b"data: " + json.dumps(ev, separators=(",", ":")).encode() + b"\n\n")

        def stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = live.bus.subscribe()
            try:
                self.wfile.write(b": open\n\n")
                self.write_event(live.state())
                self.write_event({"type": "backlog", "events": list(live.backlog)})
                self.wfile.flush()
                last_beat = time.time()
                while not live.stop.is_set():
                    try:
                        ev = q.get(timeout=1.0)
                        self.write_event(ev)
                        while True:                 # drain what is queued, then flush once
                            try:
                                self.write_event(q.get_nowait())
                            except queue.Empty:
                                break
                        self.wfile.flush()
                    except queue.Empty:
                        pass
                    if time.time() - last_beat > 1.0:
                        self.wfile.write(b": beat\n\n")
                        self.wfile.flush()
                        last_beat = time.time()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                live.bus.drop(q)

    return H


def real_opener(name: str, i: int | None, o: int | None):
    import dn2port

    def opener():
        ii, oo, nin, nout = dn2port.pick(name, i, o)
        return dn2port.Dn2Port(ii, oo), (f"[{ii}] {nin}", f"[{oo}] {nout}")
    return opener


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="the MIDI ports Windows sees")
    p.add_argument("--port", default="Digitone II", help="a substring of the MIDI port name")
    p.add_argument("--in", dest="i", type=int, help="MIDI in index (see --list)")
    p.add_argument("--out", dest="o", type=int, help="MIDI out index")
    p.add_argument("--http", type=int, default=8737, help="the page's port on 127.0.0.1")
    p.add_argument("--rate", type=float, default=dn2poll.DEFAULT_HZ,
                   help="STATS requests a second (10; 25 or 50 with --no-midi)")
    p.add_argument("--no-midi", action="store_true", help="start with the MIDI view off")
    p.add_argument("--symbols", help="a profiling build's symbols.json: read lfo4's timers by PEEK too")
    args = p.parse_args(argv)
    lfo4 = None
    if args.symbols:
        import dn2probe
        lfo4 = dn2probe.lfo4_layout(args.symbols)
        if lfo4 is None:
            print(f"  {args.symbols} has no lfo4_prof symbols: not a profiling build")
            return 1

    import winmidi
    if args.list:
        ins, outs = winmidi.ports()
        for label, names in (("MIDI IN", ins), ("MIDI OUT", outs)):
            print(f"{label}:")
            for k, n in enumerate(names):
                print(f"  [{k}] {n}")
        return 0
    try:
        live = Live(real_opener(args.port, args.i, args.o), rate_hz=args.rate,
                    midi_on=not args.no_midi, lfo4=lfo4)
    except OSError as exc:
        print(f"  {exc}")
        print("  Close Elektron Transfer, DNX and midi_live first: Windows lets one program")
        print("  at a time open a MIDI port. --list shows them; --in/--out pick by index.")
        return 1
    live.start()
    server = ThreadingHTTPServer(("127.0.0.1", args.http), handler(live))
    server.daemon_threads = True
    print(f"  MIDI in  {live.holder.names[0]}")
    print(f"  MIDI out {live.holder.names[1]}   (probe HELLO/STATS only; read-only)")
    print(f"  log      {live.log.csv_path}")
    if lfo4:
        print(f"  lfo4     PEEK 0x{lfo4[0]:08x} +{lfo4[1]} after every STATS")
    print(f"  open     http://127.0.0.1:{args.http}")
    print("  ctrl-c to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        live.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
