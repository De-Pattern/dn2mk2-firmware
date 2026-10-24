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
directory, the names, then each sample's frames as 16-bit (dnfw.sampler.live.pool_bytes).
From v0.16 (sample link 3) it writes the pool, a piece a message, straight onto the
instrument's +Drive; the instrument then loads it into the DSP, 64 KB at a time, each
piece checked, and loads it again at every power-on (as the DT2 keeps its samples).
`save` and `--keep` have nothing left to do. Up to 96 MB of yours (the DSP's pool is
128 MB; its last 32 MB are the recorder's four slots, which are kept on the +Drive too).

Before v0.16 the pool went into a 5 MB mirror in RAM, streamed to the DSP over and over,
and was kept on the +Drive only after `save`; this tool still speaks that to those builds.
They go to a region of the +Drive the DN2 itself never uses (above 3 GiB), so your
projects, presets and kits are not touched; `forget` marks the copy empty. A WAV is read as
it is: 8, 16, 24 or 32-bit PCM or 32-bit float, any rate (played at its own pitch on
C4), stereo mixed to mono. Up to 122 slots (SAMP 1..122; 124..127 are the recorder's) and
about 18 minutes of 16-bit mono at 44.1 kHz in all (96 MB; 5 MB before v0.16).

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

from dnfw.sampler import machines as SM  # noqa: E402
from dn2probe import pack7, unpack7          # noqa: E402  (Elektron's 7-bit packing)

HEADER = bytes([0xF0, 0x00, 0x20, 0x3C, 0x7D, 0x01])
HELLO, WRITE, STATUS, CLEAR, SAVE, LOAD, FORGET, BEGIN, END = 1, 2, 3, 4, 5, 6, 7, 8, 9
STATUS_TEXT = {0: "ok", 1: "refused", 2: "unknown command", 3: "the +Drive refused the write"}
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


def read_cues(path):
    """the sample offsets of a WAV's cue points ('cue ' chunk), sorted; [] if none"""
    data = pathlib.Path(path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return []
    at, out = 12, []
    while at + 8 <= len(data):
        cid, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        if cid == b"cue ":
            n = struct.unpack_from("<I", data, at + 8)[0]
            for k in range(n):
                out.append(struct.unpack_from("<I", data, at + 12 + 24 * k + 20)[0])  # dwSampleOffset
        at += 8 + size + (size & 1)
    return sorted(set(out))


def onsets(s, rate, most=64):
    """where the sound's energy jumps (a simple onset finder): frame offsets, the first 0"""
    hop = max(64, int(rate * 0.005))
    env = [sum(x * x for x in s[i:i + hop]) / hop for i in range(0, len(s), hop)]
    gap = max(1, int(0.05 * rate / hop))
    floor = max(env) * 1e-4 if env else 0.0
    out, last = [0], -gap
    for k in range(1, len(env)):
        prev = sum(env[max(0, k - 4):k]) / min(4, k)
        if env[k] > floor and env[k] > 4.0 * (prev + 1e-12) and k - last >= gap:
            if k * hop - out[-1] >= 0.05 * rate:
                out.append(k * hop)
                last = k
    return out[:most]


def slices_from(starts, frames):
    """(start, end, loop) from the slice starts: each to the next start, the last to the end"""
    starts = sorted(set(x for x in starts if 0 <= x < frames))[:64]
    return [(a, b, a) for a, b in zip(starts, starts[1:] + [frames])]


def slicing(mode, path, s, rate):
    """v0.19, SLICE: a WAV's slices -- MODE cue (its cue points, if it has any; the default),
    grid:N (N equal slices), onsets (where the sound's energy jumps), none"""
    if mode == "none":
        return []
    if mode.startswith("grid:"):
        n = max(1, min(64, int(mode[5:])))
        return slices_from([len(s) * k // n for k in range(n)], len(s))
    if mode == "onsets":
        return slices_from(onsets(s, rate), len(s))
    cues = read_cues(path)
    return slices_from(cues, len(s)) if cues else []


def wav_list(items):
    out = []
    for it in items:
        p = pathlib.Path(it)
        if p.is_dir():
            out += sorted(q for q in p.iterdir() if q.suffix.lower() == ".wav")
        else:
            out.append(p)
    return out


def build_pool(paths, slice_mode="cue", big=True):
    """BIG (sample link 4, v0.22 or later): up to 400 MB, around the recordings' area"""
    from dnfw.sampler import live as SL, machines as SM
    from dnfw.waverider import dsp
    if len(paths) > SM.USER_SLOTS:
        raise SystemExit(f"{len(paths)} files: the pool has {SM.USER_SLOTS} slots for yours "
                         "(124..127 are the recorder's)")
    samples, rates, names, cuts = [], [], [], []
    for p in paths:
        s, r = read_wav_any(p)
        if not s:
            raise SystemExit(f"{p}: no frames")
        peak = max(abs(x) for x in s)
        if peak > 1.0:
            s = [x / peak for x in s]
        samples.append(s)
        cuts.append(slicing(slice_mode, p, s, r))
        rates.append(r / DSP_RATE)
        names.append(pathlib.Path(p).stem.upper()[:SM.NAME_BYTES - 1])
    pool = SL.pool_bytes(samples, dsp.SMP_POOL_DDR, rates, [SM.FMT_I16] * len(samples), names, cuts,
                         hole=SM.USER_HOLE if big else None)
    room = SM.POOL_BYTES if big else SM.REC_OFFSET
    if len(pool) > room:
        mb = (len(pool) - (SM.REC_BYTES if len(pool) > SM.REC_END else 0)) / 2 ** 20
        raise SystemExit(f"{mb:.0f} MB of samples: more than the {SM.USER_BYTES / 2 ** 20 if big else 96:.0f} MB "
                         "the pool holds for yours" + ("" if big else " (flash v0.22 or later for 368 MB)"))
    return pool, names, [len(s) / r / DSP_RATE * DSP_RATE for s, r in zip(samples, rates)]


class Link:
    def __init__(self, port):
        self.port = port
        self.seq = 0x300
        self.proto = 0

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
    if link.proto >= 3:
        keys = ("image_bytes", "load_state", "loaded", "retried", "fast_link", "frames", "ram_check")
        p = link.call(STATUS)
        return dict(zip(keys, struct.unpack(f">{min(7, len(p) // 4)}I", p[:4 * min(7, len(p) // 4)])))
    hi, walk, passes, packets, frames = struct.unpack(">5I", link.call(STATUS)[:20])
    return {"high_water": hi, "walk": walk, "passes": passes, "packets": packets, "frames": frames}


LOAD_DONE = 4


def cmd_send3(link, pool, names, chunk):
    """v0.16 (sample link 3): the pool is written to the +Drive in order, then loaded into
    the DSP from there, each 64 KB checked"""
    print(f"{len(names)} sample(s), {len(pool):,} bytes:")
    for k, n in enumerate(names):
        print(f"  SAMP {k + 1:3d}  {n}")
    t0 = time.time()
    link.call(BEGIN, struct.pack(">I", len(pool)), timeout=10.0)
    at, total = 0, len(pool)
    while at < total:
        if SM.USER_HOLE[0] <= at < SM.USER_HOLE[1]:     # v0.22: the recordings' area: not ours
            at = SM.USER_HOLE[1]
            continue
        end = min(at + chunk, total)
        if at < SM.USER_HOLE[0] < end:
            end = SM.USER_HOLE[0]
        piece = pool[at:end]
        try:
            link.call(WRITE, struct.pack(">I", at) + piece, timeout=5.0, tries=2)
        except TimeoutError:
            if chunk <= 32:
                raise
            chunk //= 2
            print(f"\n  (no answer: pieces of {chunk} bytes from here)")
            continue
        at += len(piece)
        print(f"\r  to the +Drive: {100 * at // total:3d} %", end="", flush=True)
    link.call(END, timeout=20.0)
    print(f"\r  to the +Drive: done in {time.time() - t0:.0f} s")
    t1 = time.time()
    while True:
        st = status(link)
        print(f"\r  into the DSP: {100 * min(st['loaded'], total) // max(total, 1):3d} %"
              f"{'' if st['fast_link'] else ' (slow link)'}", end="", flush=True)
        if st["load_state"] == LOAD_DONE:
            break
        if st["load_state"] == 0:
            raise SystemExit("\n  the load stopped: the DSP did not take the samples (see "
                             "docs/sampler.md); they are on the +Drive, `load` tries again")
        time.sleep(1.0)
    print(f"\r  into the DSP: done in {time.time() - t1:.0f} s"
          f"{'' if st['fast_link'] else ' (over the slow link)'}")
    print(f"  the samples are on SAMP 1..{len(names)}, and load at every power-on")


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
    ap.add_argument("--chunk", type=int, default=512)
    ap.add_argument("-o", "--out")
    ap.add_argument("--slices", default="cue",
                    help="send/build: each WAV's slices for the SLICE machine: cue (its cue points, "
                         "if any; the default), grid:N, onsets, none")
    a = ap.parse_args(argv)
    if a.command == "build":
        pool, names, _ = build_pool(wav_list(a.files), a.slices)
        pathlib.Path(a.out or "pool.bin").write_bytes(pool)
        print(f"{len(names)} sample(s), {len(pool):,} bytes -> {a.out or 'pool.bin'}")
        return 0
    if not 16 <= a.chunk <= 512:
        raise SystemExit("--chunk: 16..512 bytes")
    import winmidi                                              # noqa: PLC0415
    port = winmidi.Port(a.port)
    try:
        link = Link(port)
        p = link.call(HELLO)
        proto, room, ddr = struct.unpack(">HII", p[:10])
        link.proto = proto
        ram = None
        if proto >= 4 and len(p) >= 22:
            _hole_end, room, ram = struct.unpack(">III", p[10:22])
            room -= SM.REC_BYTES
        if a.command == "hello":
            print(f"sample link {proto}: room for {room / 2 ** 20:.0f} MB of samples, the pool at DSP 0x{ddr:08x}")
            if ram is not None:
                print("  the DSP's RAM check: " + {0: "not run yet", 1: "passed (all 400 MB load)",
                                                     2: "FAILED: only the first 128 MB load"}.get(ram, str(ram)))
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
        elif proto >= 3:
            pool, names, _ = build_pool(wav_list(a.files), a.slices, big=proto >= 4)
            cmd_send3(link, pool, names, a.chunk)
        else:
            pool, names, _ = build_pool(wav_list(a.files), a.slices)
            if len(pool) > 5 << 20:
                raise SystemExit("this build holds 5 MB: flash v0.16 or later for more")
            cmd_send(link, pool, names, a.chunk)
            if a.keep:
                n = struct.unpack(">I", link.call(SAVE, timeout=20.0)[:4])[0]
                print(f"  saved {n:,} bytes on the +Drive: they load at power-on")
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
