"""Send your own samples to a Digitone II running the sampler build (v0.14 and later), over USB.

    python tools/dn2samples.py hello                    is the sample link answering
    python tools/dn2samples.py send A.wav B.wav ...     the WAVs into slots 1, 2, ... (SAMP 1..)
    python tools/dn2samples.py send FOLDER              every .wav in a folder, by name
    python tools/dn2samples.py status                   how far the DSP has been sent
    python tools/dn2samples.py clear                    stop sending (the DSP keeps what it has)
    python tools/dn2samples.py save                     keep what was sent on the +Drive (v0.15)
    python tools/dn2samples.py load                     the +Drive's copy back (as at power-on)
    python tools/dn2samples.py forget                   the +Drive's copy no longer loads
    python tools/dn2samples.py build A.wav ... -o pool.bin   the pool as it would be sent (no device)

    options: --port "Digitone II" (a substring of the port name), --chunk 256 (bytes a message)

What happens (docs/sampler.md): this tool lays the samples out as the DSP's pool -- a
directory, the names, then each sample's frames as 16-bit (dnfw.sampler.live.pool_bytes)
-- and writes it, a piece a message, into the instrument's RAM (its mirror of the pool).
The instrument then streams the mirror to the DSP, 36 KB a second, over and over, so a
slot sounds once the stream has passed it. `status` tells you when: a pass is complete.

The samples last until power-off unless you `save` them (v0.15): `send --keep` saves
them on the +Drive when the send is done, and the instrument loads them at power-on.
They go to a region of the +Drive the DN2 itself never uses (above 3 GiB), so your
projects, presets and kits are not touched; `forget` marks the copy empty. A WAV is read as
it is: 8, 16, 24 or 32-bit PCM or 32-bit float, any rate (played at its own pitch on
C4), stereo mixed to mono. Up to 122 slots (SAMP 1..122; 124..127 are the recorder's) and about 2.5 minutes of 16-bit mono at 44.1
kHz in all (the mirror is 5 MB).

    request  F0 00 20 3C 7D 01 <pack7: u16 seq, u8 cmd, payload> F7
    reply    F0 00 20 3C 7D 01 <pack7: u16 seq, u8 cmd | 0x80, u8 status, payload> F7

Windows only for the device (winmidi.py); `build` runs anywhere. Close Elektron Transfer
first: Windows lets one program at a time open a MIDI port.
"""
import argparse
import pathlib
import struct
import sys
import time
import wave

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from dn2probe import pack7, unpack7          # noqa: E402  (Elektron's 7-bit packing)

HEADER = bytes([0xF0, 0x00, 0x20, 0x3C, 0x7D, 0x01])
HELLO, WRITE, STATUS, CLEAR, SAVE, LOAD, FORGET = 1, 2, 3, 4, 5, 6, 7
STATUS_TEXT = {0: "ok", 1: "refused", 2: "unknown command"}
DSP_RATE = 48000
LINK_BYTES_PER_S = 24 * 1500


def request(seq, cmd, payload=b""):
    return HEADER + pack7(struct.pack(">HB", seq & 0xFFFF, cmd) + payload) + b"\xF7"


def parse(sx):
    sx = bytes(sx)
    if not sx.startswith(HEADER) or not sx.endswith(b"\xF7"):
        return None
    msg = unpack7(sx[len(HEADER):-1])
    if len(msg) < 4:
        return None
    seq, cmd, status = struct.unpack(">HBB", msg[:4])
    return {"seq": seq, "cmd": cmd, "status": status, "payload": msg[4:]}


def read_wav(path):
    """-> (mono floats in -1..1, sample rate)"""
    with wave.open(str(path), "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
        fmt_tag = getattr(w, "_comptype", "NONE")
    if width == 1:
        vals = [(b - 128) / 128.0 for b in raw]
    elif width == 2:
        vals = [x / 32768.0 for x in struct.unpack(f"<{len(raw) // 2}h", raw)]
    elif width == 3:
        vals = [int.from_bytes(raw[i:i + 3], "little", signed=True) / 8388608.0
                for i in range(0, len(raw), 3)]
    elif width == 4:
        ints = struct.unpack(f"<{len(raw) // 4}i", raw)
        vals = [x / 2147483648.0 for x in ints]
    else:
        raise ValueError(f"{path}: {width * 8}-bit samples are not read here")
    if ch > 1:
        vals = [sum(vals[i:i + ch]) / ch for i in range(0, len(vals), ch)]
    return vals, rate


def read_wav_any(path):
    try:
        return read_wav(path)
    except wave.Error:
        return read_float_wav(path)


def read_float_wav(path):
    """32-bit float WAVs (format 3), which the wave module refuses"""
    data = pathlib.Path(path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a WAV file")
    at, fmt, body = 12, None, None
    while at + 8 <= len(data):
        cid, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        if cid == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", data, at + 8)
        elif cid == b"data":
            body = data[at + 8:at + 8 + size]
        at += 8 + size + (size & 1)
    if not fmt or body is None or fmt[0] != 3 or fmt[5] != 32:
        raise ValueError(f"{path}: not PCM or 32-bit float")
    ch, rate = fmt[1], fmt[2]
    vals = list(struct.unpack(f"<{len(body) // 4}f", body))
    if ch > 1:
        vals = [sum(vals[i:i + ch]) / ch for i in range(0, len(vals), ch)]
    return vals, rate


def wav_list(items):
    out = []
    for it in items:
        p = pathlib.Path(it)
        if p.is_dir():
            out += sorted(q for q in p.iterdir() if q.suffix.lower() == ".wav")
        else:
            out.append(p)
    return out


def build_pool(paths):
    from dnfw.sampler import live as SL, machines as SM
    from dnfw.waverider import dsp
    if len(paths) > SM.USER_SLOTS:
        raise SystemExit(f"{len(paths)} files: the pool has {SM.USER_SLOTS} slots for yours "
                         "(124..127 are the recorder's)")
    samples, rates, names = [], [], []
    for p in paths:
        s, r = read_wav_any(p)
        if not s:
            raise SystemExit(f"{p}: no frames")
        peak = max(abs(x) for x in s)
        if peak > 1.0:
            s = [x / peak for x in s]
        samples.append(s)
        rates.append(r / DSP_RATE)
        names.append(pathlib.Path(p).stem.upper()[:SM.NAME_BYTES - 1])
    pool = SL.pool_bytes(samples, dsp.SMP_POOL_DDR, rates, [SM.FMT_I16] * len(samples), names)
    if len(pool) > SM.MIRROR_BYTES:
        raise SystemExit(f"{len(pool):,} bytes: more than the {SM.MIRROR_BYTES:,} the instrument holds")
    return pool, names, [len(s) / r / DSP_RATE * DSP_RATE for s, r in zip(samples, rates)]


class Link:
    def __init__(self, port):
        self.port = port
        self.seq = 0x300

    def call(self, cmd, payload=b"", timeout=2.0, tries=3):
        for attempt in range(tries):
            try:
                return self._call(cmd, payload, timeout)
            except TimeoutError:
                if attempt == tries - 1:
                    raise

    def _call(self, cmd, payload, timeout):
        self.seq = (self.seq + 1) & 0xFFFF or 1
        seq = self.seq
        self.port.send(request(seq, cmd, payload))
        found = []

        def answered(msgs):
            for m in msgs[len(found):]:
                r = parse(m)
                found.append(r if r and r["seq"] == seq and r["cmd"] == cmd | 0x80 else None)
            return any(found)
        self.port.receive(timeout, until=answered)
        for r in found:
            if r:
                if r["status"]:
                    raise ValueError(f"command {cmd}: {STATUS_TEXT.get(r['status'], r['status'])}")
                return r["payload"]
        raise TimeoutError("no answer: is a sampler build (v0.14 or later) running, on this port, "
                           "with USB CONFIG set to USB MIDI or Overbridge?")


def status(link):
    hi, walk, passes, packets, frames = struct.unpack(">5I", link.call(STATUS)[:20])
    return {"high_water": hi, "walk": walk, "passes": passes, "packets": packets, "frames": frames}


def cmd_send(link, pool, names, chunk):
    print(f"{len(names)} sample(s), {len(pool):,} bytes:")
    for k, n in enumerate(names):
        print(f"  SAMP {k + 1:3d}  {n}")
    t0 = time.time()
    # the frames first, the directory (offset 0) last: no slot points at a sample
    # before the sample is there
    from dnfw.sampler import machines as SM
    # pieces of CHUNK bytes; a piece that draws no answer is sent again in halves (the
    # instrument's SysEx input may take less than CHUNK), down to 32 bytes
    spans = [(SM.DATA_OFFSET, len(pool)), (0, min(SM.DATA_OFFSET, len(pool)))]
    total, done = len(pool), 0
    for lo, hi in spans:
        at = lo
        while at < hi:
            piece = pool[at:min(at + chunk, hi)]
            try:
                link.call(WRITE, struct.pack(">I", at) + piece, tries=2)
            except TimeoutError:
                if chunk <= 32:
                    raise
                chunk //= 2
                print(f"\n  (no answer: pieces of {chunk} bytes from here)")
                continue
            at += len(piece)
            done += len(piece)
            print(f"\r  to the instrument: {100 * done // total:3d} %", end="", flush=True)
    print(f"\r  to the instrument: done in {time.time() - t0:.0f} s")
    st = status(link)
    first = st["passes"]
    secs = len(pool) / LINK_BYTES_PER_S
    print(f"  to the DSP: about {secs:.0f} s a pass; waiting for one whole pass ...")
    while status(link)["passes"] < first + 2:
        time.sleep(1.0)
    print("  done: the samples are on SAMP 1.."
          f"{len(names)} (they stay until power-off; the instrument keeps refreshing them)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("hello", "send", "status", "clear", "build", "save", "load", "forget"))
    ap.add_argument("--keep", action="store_true", help="send: then save on the +Drive")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--port", default="Digitone II")
    ap.add_argument("--chunk", type=int, default=256)
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    if a.command == "build":
        pool, names, _ = build_pool(wav_list(a.files))
        pathlib.Path(a.out or "pool.bin").write_bytes(pool)
        print(f"{len(names)} sample(s), {len(pool):,} bytes -> {a.out or 'pool.bin'}")
        return 0
    if not 16 <= a.chunk <= 512:
        raise SystemExit("--chunk: 16..512 bytes")
    import winmidi                                              # noqa: PLC0415
    port = winmidi.Port(a.port)
    try:
        link = Link(port)
        if a.command == "hello":
            p = link.call(HELLO)
            proto, mirror, ddr = struct.unpack(">HII", p[:10])
            print(f"sample link {proto}: mirror {mirror:,} bytes, the pool at DSP 0x{ddr:08x}")
        elif a.command == "status":
            print(status(link))
        elif a.command == "save":
            n = struct.unpack(">I", link.call(SAVE, timeout=20.0)[:4])[0]
            print(f"saved {n:,} bytes on the +Drive: they load at power-on")
        elif a.command == "load":
            n = struct.unpack(">I", link.call(LOAD, timeout=20.0)[:4])[0]
            print(f"loaded {n:,} bytes from the +Drive")
        elif a.command == "forget":
            link.call(FORGET, timeout=10.0)
            print("the +Drive's copy is forgotten: nothing loads at power-on")
        elif a.command == "clear":
            link.call(CLEAR)
            print("cleared: the instrument stops sending; the DSP keeps what it has")
        else:
            pool, names, _ = build_pool(wav_list(a.files))
            cmd_send(link, pool, names, a.chunk)
            if a.keep:
                n = struct.unpack(">I", link.call(SAVE, timeout=20.0)[:4])[0]
                print(f"  saved {n:,} bytes on the +Drive: they load at power-on")
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
