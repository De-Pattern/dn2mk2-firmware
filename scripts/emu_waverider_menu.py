"""Waverider in the ColdFire emulator: MACHINE SEL offers it, choosing it sets type 5,
and the frame the ColdFire builds carries it.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \\
        scripts/emu_waverider_menu.py --build out/waverider-m5 \\
        --snapshot /root/wr-m5/wr-ui800M.snap [--steps "..."] [--json OUT]

**The snapshot matters.** The MACHINE SEL view builds its rows once, at about
67 M instructions after `boot400M` (its constructor `0x4005b6de` calls the SYN
row builder `0x4005b2c0`), so `ui1200M` -- booted from the stock image -- holds
stock rows whatever is installed over it. `wr-ui800M` is `boot400M` with this
build installed before that moment and run on to the SYN page by digikit's
`guirun --patch-ranges ... --save-at 800M` (docs, Milestone 5). The build's
changed runs are installed again here, which is a no-op on that snapshot and
keeps the harness honest about what it ran.

The panel is driven as a person would drive it (`emulib.panel`): FUNC held, SRC
tapped, DOWN, YES. Watched while it runs:

- every call of the accessors the build bounds or reroutes, with its type
  argument, so a type 5 reaching one that was *not* rerouted shows up;
- the machine setter's write of `sound+0xDE` (`0x4004cc94`): which sound, which
  type;
- the frame: the audio ISR does not run in this emulator, so `frame:NAME` enters
  it directly (`0x40025e36`, as `emu_mirror_base.py` does), checks that the
  frame builder's loop ran (`0x400275a2`), and keeps the 2,688-byte frame from
  `0x80005e60` -- big-endian 16-bit words at the offsets `dnfw.waverider.frame`
  uses.

Steps (comma-separated): `func-src` (open MACHINE SEL), `up`, `down`, `left`,
`right`, `yes`, `no`, `png:NAME`, `wait:MILLIONS`, `turn:ENC:DELTA` (push and
turn -- what moves a value here, parameters included), `spin:ENC:DELTA` (a
plain turn: shows the value, moves nothing in this emulator, stock included),
`tap:CODE`, `press:CODE` / `release:CODE` (hold a key: TRIG 1-16 are 25-40 and
play the track), `sync:T` (the track's mirror through `0x4002549c`), `sync`
(every track through the kit-load sync `0x40025af4`), `frame:NAME` (the ISR, and
the frame it built, with the mirror and the sixteen sounds beside it),
`blocks:NAME:MILLIONS[:ENC:DELTA]` (every instruction address run), `mem:VA:N`,
`poke:VA:HEX` (write bytes: a value the audio tick would have left, say),
`types` (every track's `sound+0xDE`), `call:VA[:ARG...]` (enter a routine that
does not run here; ARG is a number, `kit`, `soundT`, `long@VA`, or `argN@VA[-OFF]`
-- the Nth argument of the last entry to an `--args-at VA`, less OFF -- and d0 is
reported).

`--watch-types` logs every write to any track's `sound+0xDE` with the step, PC
and the code addresses on the stack: the persistence check. The selection test
(fix/waverider-select, `docs/machine-list.md`):

    --watch-types --args-at 0x40031880 --steps "func-src,wait:20,up,up,yes,wait:20,
      down,down,down,down,yes,wait:20,png:after_yes,types,no,wait:20,func-src,
      wait:20,png:reopen,no,wait:10,call:0x4003134e:arg1@0x40031880:0,
      call:0x40041acc:arg1@0x40031880-0xf4:0:1,types,
      call:0x40041acc:arg1@0x40031880-0xf4:0:1,types,sync,sync:0,frame:f,types"
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from emulib.image import differences                           # noqa: E402
from emulib.machine import SNAP, Machine                       # noqa: E402
from emulib.panel import DOWN, LEFT, NO, RIGHT, UP, YES, Panel  # noqa: E402

FUNC, SRC = (2, 0), (0, 1)             # codes 17 and 2 (code = channel * 8 + bit + 1)
KEYS = {"up": UP, "down": DOWN, "left": LEFT, "right": RIGHT, "yes": YES, "no": NO}

# the accessors the build touches, and where each keeps its type argument on entry
WATCH = {
    0x400DC02A: ("param_set_slot_to_id(slot, type, filter)", 8),
    0x400DC19A: ("permission(type, track)", 4),
    0x400DC15C: ("attribute byte(type)", 4),
    0x400DC176: ("all-tracks(type)", 4),
    0x400DC332: ("long name(type)", 4),
    0x400DC358: ("short name(type)", 4),
    0x400DC37E: ("name column 3(type)", 4),
    0x40059274: ("MACHINE SEL group(type)", 4),
    0x400394BE: ("the machine's parameter list(out, type)", 4),
    0x4004CC08: ("machine setter(sound, type, flag)", 8),
    0x40031880: ("MACHINE SEL commit(model, track, type)", 12),
    0x4004C30C: ("machine change: reset its parameters(sound, 1, old type, 0)", 12),
    0x400C24D2: ("SYN page count(type)", 4),
    0x400C24EE: ("SYN page descriptor(type, page)", 4),
    0x400C248E: ("per-machine descriptor 0x42432b24(type)", 4),
}
SETTER_WRITE = 0x4004CC94               # moveb %d2,%a0@(222)
# every `mvs.b %aN@(222),%dM` in the image (objdump of MAIN OS): site -> N
TYPE_READS = {0x400254B4: 2, 0x40031BD2: 0, 0x40031C1C: 0, 0x40036478: 0, 0x40036738: 0,
              0x40036C24: 0, 0x4004B816: 0, 0x4004CC82: 0, 0x4004DE0E: 3, 0x400A801C: 0,
              0x400B1668: 0}
GETTER_RTS = 0x4003647C                 # rts of the machine-type getter 0x40036462
TRACK_GETTER_EXIT = 0x4004B81E          # getMachineType(track) 0x4004b7f2: the common exit
ISR = 0x40025E36                        # the audio frame handler: modulation, frame, send
SYSEX_ROUTER, SYSEX_SENDER = 0x4012166E, 0x401233F2    # docs/usbprobe.md
FRAME_BUILT = 0x400275A2                # the builder's sixteen passes are done
FRAME = 0x80005E60
FRAME_BYTES = 2688
FRAME_MACHINE = 148                     # + 2t
MIRROR, MIRROR_BYTES = 0x800068E4, 202  # the modulated per-track values the builder copies
KIT_POINTER, KIT_SYNC =0x800052A0, 0x40025AF4   # the live kit; its sixteen-track sync
TRACK_SYNC, SOUND_STRIDE = 0x4002549C, 1163      # (sound, track) -> the mirror; kit + 52 + 1163 t
MIRROR_TYPE, MIRROR_STRIDE =0x80003AF0 + 3468, 153   # the builder's per-track type byte
STACK_TOP, SENTINEL = 0x46A20000, 0x46A20400   # above BSS (0x466b74d0); Machine.write maps it
GET_SHORT_NAME = 0x400372DA             # getShortName(this, id): record + 0x30
SET_PIXEL = 0x40113B90                  # Bitmap::setPixel(bitmap, x, y, on), docs/display-path.md
PARAM_TABLE, PARAM_RECORDS, PARAM_BYTES = 0x401F7F94, 321, 60


BLK_READ, BLK_WRITE = 0x4012C59A, 0x4012C780
BLK_READY, BLK_SECTORS = 0x4461B68C, 0x4461B6B0
STORE_SECTOR = 0x600000
REPLY_TAIL = 0x80005E40
ROUTE_OFFSET = 0xA5A                     # the frame's per-track routing words (docs/link-research.md)
TDM_TX, TDM_RX = 0x4E6E0100, 0x4E6DF100


def link16(machine, uc, K, guest_call, syms, scenario, SL, SM, WD):
    """the scenario's run: -> what was checked (see the link16: step)"""
    import random
    from unicorn import UC_HOOK_CODE
    # the +Drive, fresh for each scenario; the hooks once per machine
    shared = link16.__dict__.setdefault("shared", {})
    disk: dict[int, bytes] = {}
    io = {"reads": 0, "writes": 0}
    shared["disk"], shared["io"] = disk, io

    def blk(uc_, address, size, user):
        try:
            blk_(address, shared["disk"], shared["io"])
        except Exception as e:                  # noqa: BLE001 -- kept for the report
            shared["io"].setdefault("errors", []).append(repr(e)[:200])

    def blk_(address, disk, io):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        sector, n, buf = struct.unpack(">3I", bytes(uc.mem_read(sp + 4, 12)))
        if address == BLK_READ:
            io["reads"] += 1
            data = b"".join(disk.get(sector + k, bytes(512)) for k in range(n // 512))
            uc.mem_write(buf, data)
        else:
            io["writes"] += 1
            data = bytes(uc.mem_read(buf, n))
            for k in range(n // 512):
                disk[sector + k] = data[512 * k:512 * k + 512]
    # the stock driver does not run here: each entry becomes moveq #0,%d0 ; rts, and the
    # hook does its work first
    if not shared.get("hooked"):
        shared["hooked"] = True
        for va in (BLK_READ, BLK_WRITE):
            machine.write(va, bytes.fromhex("70004e75"))
            uc.hook_add(UC_HOOK_CODE, blk, begin=va, end=va)
    machine.write(BLK_READY, struct.pack(">I", 1))
    machine.write(BLK_SECTORS, struct.pack(">I", 0x3A00000))   # 29 GiB

    def long(name):
        return struct.unpack(">I", machine.read(syms[name], 4))[0]

    def call(name, *args):
        return guest_call(syms[name], *args, limit=50_000_000)

    def returned_d0():
        return guest_call.returned["d0"]

    # the DSP: its pool as words, the commands it took, the status it answers with
    pool: dict[int, int] = {}
    dsp = {"seq": None, "state": 0, "vdone": 0, "vsum": 0, "vsum2": 0, "send": None,
           "sseq": 0, "fast": 0, "slow": 0, "dropped": 0, "cmds": [], "sent_back": 0,
           "ram": 0, "ram_answer": 2 if scenario == "lowram" else 1}
    rng = random.Random(16)

    def status_out():
        h = [SM.STATUS_MAGIC | dsp["state"], (dsp["seq"] or 0) & 0xFFFF, 0, 0, dsp["ram"], 0, 0, 0, 0, 0,
             dsp["vsum"] & 0xFFFF, dsp["vsum"] >> 16, dsp["vsum2"] & 0xFFFF, dsp["vsum2"] >> 16,
             dsp["vdone"] & 0xFFFF]
        h.append((SM.LINK_SEED + sum(h)) & 0xFFFF)
        machine.write(REPLY_TAIL, struct.pack(">16H", *h))

    def command(words):
        """a command, as the DSP's recorder takes it from the command block (v0.20: by TDM)"""
        seq, cmd, a0, a1 = words[:4]
        if seq == dsp["seq"]:
            return
        dsp["seq"] = seq
        dsp["cmds"].append(cmd)
        if cmd == SM.CMD_VERIFY:
            x = y = 0
            for k in range(a0, a0 + a1):
                x = (x + pool.get(k, 0)) & 0xFFFFFFFF
                y = (y + x) & 0xFFFFFFFF
            dsp.update(vsum=x, vsum2=y, vdone=seq)
        elif cmd == SM.CMD_SEND:
            dsp["send"] = [a0, a0 + a1]
        elif cmd == SM.CMD_PROBE:               # v0.22: the RAM check's verdict, at once
            dsp["ram"] = dsp["ram_answer"]
        status_out()

    # v0.20: the frame's words 2650..2681 are the DSP's per-track routing; ours never
    # writes them. Each period they must be what stock's builder put there: the snapshot's
    # own, as the first period finds them
    route = {}

    def routing():
        h = struct.unpack(">16H", machine.read(0x80005E60 + ROUTE_OFFSET, 32))
        route.setdefault("stock", h)
        if h != route["stock"]:
            route["changed"] = route.get("changed", 0) + 1

    last = {}

    def tdm_in():
        for half in (0, 1):
            base = TDM_TX + (half << 11)
            raw = machine.read(base, 0x800)
            units = []
            for i in range(SM.RX_UNITS):
                x = struct.unpack_from(">I", raw, 4 * (16 * (i >> 3) + 8 + (i & 7)))[0]
                if x >> 16 != SM.TDM_TAG:
                    break
                units.append(x & 0xFFFF)
            if len(units) != SM.RX_UNITS or units[0] != SM.RX_MAGIC:
                continue
            if units[255] != (SM.LINK_SEED + sum(units[:255])) & 0xFFFF:
                raise AssertionError("a TDM packet with a bad check")
            # what the DSP decodes is what live.rx_units builds: the same units
            off, n = units[2] | units[3] << 16, units[252]
            words = [units[4 + 2 * j] | units[5 + 2 * j] << 16 for j in range(n)]
            assert SL.rx_units(off, words, units[1]) == units
            machine.write(base + 32, bytes(0x800 - 32))   # stock's memset, as each period
            if last.get(half) == units[1]:
                continue
            last[half] = units[1]
            drop = (scenario == "dead") or (scenario == "fast" and dsp["fast"] == 20 and not dsp["dropped"])
            dsp["fast"] += 1
            if drop:
                dsp["dropped"] += 1
                continue
            if 4 * off == SM.CMD_OFFSET:            # a command: exactly the block's words
                assert n == SM.CMD_WORDS, n
                dsp["cmd_packets"] = dsp.get("cmd_packets", 0) + 1
                command(words)
                continue
            assert 4 * (off + n) <= SM.CMD_OFFSET or 4 * off >= SM.CMD_OFFSET + 4 * SM.CMD_WORDS
            for j, x in enumerate(words):
                pool[off + j] = x

    def tdm_out():
        # the DSP's SEND: TX_WORDS a block, left-justified as the DSP writes them (the
        # ColdFire's receive slots carry them right-justified: both are tried, by turns)
        if not dsp["send"]:
            for half in (0, 1):
                for i in range(64):
                    machine.write(TDM_RX + (half << 11) + 4 * (16 * (i >> 1) + 14 + (i & 1)), bytes(4))
            return
        a, b = dsp["send"]
        n = min(SM.TX_WORDS, b - a)
        words = [pool.get(a + j, 0) for j in range(n)] + [0] * (SM.TX_WORDS - n)
        u = [SM.TX_MAGIC, dsp["sseq"] & 0xFFFF, a & 0xFFFF, a >> 16]
        for x in words:
            u += [x & 0xFFFF, x >> 16]
        u += [n]
        u.append((SM.LINK_SEED + sum(u)) & 0xFFFF)
        assert len(u) == SM.TX_UNITS
        left = dsp["sseq"] & 1
        for half in (0, 1):
            for i, v in enumerate(u):
                w = (SM.TDM_TAG << 24 | v << 8) if left else (SM.TDM_TAG << 16 | v)
                machine.write(TDM_RX + (half << 11) + 4 * (16 * (i >> 1) + 14 + (i & 1)),
                              struct.pack(">I", w))
        dsp["sseq"] += 1
        dsp["sent_back"] += 1
        dsp["send"][0] += n
        if dsp["send"][0] >= b:
            dsp["send"] = None

    def period():
        tdm_out()
        guest_call(ISR)
        routing()
        tdm_in()
        status_out()        # the ISR copies the SPI reply over the tail each frame: ours again

    log = []
    out = {"scenario": scenario}
    base = WD.SMP_POOL_DDR
    # v0.22: each scenario from power-on: the RAM check first, then the image
    machine.write(syms["smp_booted"], bytes(4))
    if scenario in ("high", "lowram"):
        # an image whose second sound lies past the proven 128 MB (at 130 MB, after the
        # recordings' area): loaded when the RAM check passes (high), left out when it
        # fails (lowram), the first sound loaded either way
        snd = [[0.5 * ((k % 100) / 50 - 1) for k in range(3000)],
               [0.25 * ((k % 40) / 20 - 1) for k in range(2000)]]
        img = SL.pool_bytes(snd, base, [1.0, 1.0], [SM.FMT_I16] * 2, ["LOW", "HIGH"],
                            hole=(SM.DATA_OFFSET + 6400, (130 << 20)))
        hi_addr = struct.unpack_from("<I", img, 8 + 16)[0] - base
        assert hi_addr == 130 << 20, hex(hi_addr)
        img = bytearray(img + bytes((-len(img)) % 512))
        hdr_dir = bytes(img[:SM.DATA_OFFSET])

        def adler2(b):
            a_, b_ = 1, 0
            for x in b:
                a_ = (a_ + x) & 0xFFFFFFFF
                b_ = (b_ + a_) & 0xFFFFFFFF
            return (b_ << 16 ^ a_) & 0xFFFFFFFF
        magic, nbytes, ck = 0x444E3251, len(img), adler2(hdr_dir)
        disk[STORE_SECTOR] = struct.pack(">5I", magic, 2, nbytes, ck,
                                         (~magic ^ nbytes ^ ck) & 0xFFFFFFFF).ljust(512, b"\0")
        for k in range(len(img) // 512):
            chunk = bytes(img[512 * k:512 * k + 512])
            if any(chunk):
                disk[STORE_SECTOR + 1 + k] = chunk
        periods = 0
        while periods < 8000:
            period()
            call("smp_boot")
            periods += 1
            if all(pool.get(k // 4) == struct.unpack_from("<I", img, k)[0] for k in range(0, SM.CMD_OFFSET, 4)):
                break

        def has(lo, n):
            return all(pool.get((lo + k) // 4) == struct.unpack_from("<I", img, lo + k)[0]
                       for k in range(0, n, 4))
        low_in = has(struct.unpack_from("<I", img, 8)[0] - base, 6000)
        high_in = has(hi_addr, 4000)
        high_any = any(hi_addr // 4 <= k < (hi_addr + 4000) // 4 for k in pool)
        out.update(periods=periods, low_loaded=low_in, high_loaded=high_in, high_touched=high_any,
                   probes=dsp["cmds"].count(SM.CMD_PROBE), ram=dsp["ram"],
                   probe_first=bool(dsp["cmds"]) and dsp["cmds"][0] == SM.CMD_PROBE,
                   routing_changed=route.get("changed", 0))
        want_high = scenario == "high"
        # (a probe sent while the snapshot warmed up may arrive too: one or more, all first)
        out["ok"] = (periods < 8000 and low_in and out["probe_first"] and out["probes"] >= 1
                     and (high_in if want_high else not high_any) and not route.get("changed"))
    elif scenario in ("fast", "dead"):
        # an image on the +Drive: two sounds, one longer than a 64 KB chunk (fast) or both
        # short (dead: every TDM packet lost), and a recording kept in slot 125
        n_long = 40000 if scenario == "fast" else 900
        snd = [[0.6 * ((k * 37 % 200) / 100 - 1) for k in range(n_long)],
               [0.3 * ((k % 50) / 25 - 1) for k in range(700)]]
        img = SL.pool_bytes(snd, base, [1.0, 0.5], [SM.FMT_I16] * 2, ["SAW", "TRI"])
        img = bytearray(img + bytes((-len(img)) % 512))
        rec = bytes(rng.randrange(256) for _ in range(2 * 1000))
        rec_off = SM.REC_OFFSET + (1 << SM.REC_SLOT_SHIFT)
        struct.pack_into("<IIfI", img, 8 + 16 * (SM.REC_FIRST + 1), base + rec_off, 1000, 1.0, 1)
        import zlib  # noqa: F401
        hdr_dir = bytes(img[:SM.DATA_OFFSET])

        def adler(b):
            a_, b_ = 1, 0
            for x in b:
                a_ = (a_ + x) & 0xFFFFFFFF
                b_ = (b_ + a_) & 0xFFFFFFFF
            return (b_ << 16 ^ a_) & 0xFFFFFFFF
        magic, nbytes, ck = 0x444E3251, rec_off + len(rec), adler(hdr_dir)
        hdr = struct.pack(">5I", magic, 2, nbytes, ck, (~magic ^ nbytes ^ ck) & 0xFFFFFFFF)
        disk[STORE_SECTOR] = hdr.ljust(512, b"\0")
        for k in range(len(img) // 512):
            disk[STORE_SECTOR + 1 + k] = bytes(img[512 * k:512 * k + 512])
        recp = rec + bytes((-len(rec)) % 512)
        for k in range(len(recp) // 512):
            disk[STORE_SECTOR + 1 + rec_off // 512 + k] = recp[512 * k:512 * k + 512]
        retries0 = long("smp_retries")       # (the machine runs the scenarios in turn: its count goes on)
        status_out()
        periods = 0
        limit = int(os.environ.get("LINK16_LIMIT", 4000 if scenario == "fast" else 30000))
        while periods < limit:
            period()
            call("smp_boot")
            periods += 1
            if periods % 25 == 0:
                log.append([periods, long("smp_walk"), long("smp_retries"), long("smp_lstate"),
                            long("smp_tdm_sent"), len(dsp["cmds"]), io["reads"]])
            if (scenario == "dead" and periods > 100 and long("smp_lstate") == 0
                    and long("smp_booted") == 2):     # (v0.22: after the RAM check's four seconds)
                break                           # the loader gave up
            # done: the directory page (the last range) is in
            if all(pool.get(k // 4) == struct.unpack_from("<I", img, k)[0] for k in range(0, SM.CMD_OFFSET, 4)):
                break
        want = {}
        for k in range(0, len(img), 4):
            want[k // 4] = struct.unpack_from("<I", img, k)[0]
        for k in range(0, len(recp), 4):
            want[(rec_off + k) // 4] = struct.unpack_from("<I", recp, k)[0]
        # what the directory points at must all be there: frames of used slots + dir
        wrong = [k for k, v in want.items() if k * 4 < SM.CMD_OFFSET and pool.get(k) != v]
        frames_wrong = 0
        for slot in list(range(2)) + [SM.REC_FIRST + 1]:
            addr, fr, _r, fmt = struct.unpack_from("<IIfI", img, 8 + 16 * slot)
            lo = addr - base
            for k in range(lo // 4, (lo + fr * 2 + 3) // 4):
                if pool.get(k) != want.get(k, 0):
                    frames_wrong += 1
        out.update(periods=periods, dir_wrong=len(wrong), frames_wrong=frames_wrong,
                   walk=long("smp_walk"), retries=long("smp_retries"),
                   tdm_sent=long("smp_tdm_sent"), fast=dsp["fast"], dropped=dsp["dropped"],
                   cmd_packets=dsp.get("cmd_packets", 0), verifies=dsp["cmds"].count(SM.CMD_VERIFY),
                   hi=long("smp_hi"), disk_reads=io["reads"], disk_writes=io["writes"],
                   disk_errors=io.get("errors", [])[:3], routing_changed=route.get("changed", 0),
                   lstate=long("smp_lstate"))
        if scenario == "fast":
            out["ok"] = (not wrong and not frames_wrong and periods < limit and out["cmd_packets"] > 0
                         and not route.get("changed"))
        else:
            # nothing gets through: the loader tries each chunk seven times and stops, and
            # the frame stays stock's
            out["ok"] = (periods < limit and out["lstate"] == 0 and out["retries"] - retries0 == 7
                         and not dsp["cmds"] and not route.get("changed"))
        if scenario == "fast":                  # v0.22: the RAM check came first
            out["ok"] = out["ok"] and dsp["cmds"][0] == SM.CMD_PROBE
    elif scenario == "slices":
        # v0.23: SLICE's editor's side: a 3 s int16 sample with four hits on the +Drive,
        # loaded; read back (smp_analyse, a chunk a pass: its transients found where the
        # hits are); a slice table set (smp_slices_set): the slice area's sectors written
        # on the +Drive, the DSP given the table before the entry that points at it (bit
        # 16, the count), and the table read back the same (smp_slices_get)
        n = 144000
        hits = [0, 36000, 72000, 108000]
        snd = [0.0] * n
        for h in hits:
            for k in range(6000):
                snd[h + k] = 0.8 * ((k * 37 % 50) / 25 - 1) * (1 - k / 6000)
        img = SL.pool_bytes([snd], base, [1.0], [SM.FMT_I16], ["HITS"])
        img = bytearray(img + bytes((-len(img)) % 512))
        hdr_dir = bytes(img[:SM.DATA_OFFSET])

        def adler3(b):
            a_, b_ = 1, 0
            for x in b:
                a_ = (a_ + x) & 0xFFFFFFFF
                b_ = (b_ + a_) & 0xFFFFFFFF
            return (b_ << 16 ^ a_) & 0xFFFFFFFF
        magic, nbytes, ck = 0x444E3251, len(img), adler3(hdr_dir)
        disk[STORE_SECTOR] = struct.pack(">5I", magic, 2, nbytes, ck,
                                         (~magic ^ nbytes ^ ck) & 0xFFFFFFFF).ljust(512, b"\0")
        for k in range(len(img) // 512):
            disk[STORE_SECTOR + 1 + k] = bytes(img[512 * k:512 * k + 512])
        periods = 0
        while periods < 3000:
            period()
            call("smp_boot")
            periods += 1
            if long("smp_lstate") == 4:
                break
        loaded = long("smp_lstate") == 4
        call("smp_analyse", 0)
        for _ in range(400):
            call("smp_boot")
            call("smp_analysis", 0)
            if returned_d0() == 2:
                break
        an = returned_d0()
        buf = STACK_TOP - 0x2000
        call("smp_onsets", buf, 16)
        nos = returned_d0()
        ons = list(struct.unpack(f">{nos}I", machine.read(buf, 4 * nos))) if 0 < nos <= 16 else []
        table = [0, 30000, 0, 36000, 70000, 40000, 72000, 140000, 72000]
        machine.write(buf, struct.pack(">9I", *table))
        call("smp_slices_set", 0, buf, 3)
        set_rc = returned_d0()
        sent_at = len(dsp["cmds"])
        order = []
        area = SM.SLICE_AREA // 4
        for _ in range(3000):
            period()
            call("smp_boot")
            got_area = all(pool.get(area + j) == table[j] for j in range(9))
            e = pool.get((8 + 12) // 4, 0)
            if got_area and "area" not in order:
                order.append("area")
            if (e >> 16) & 1 and "entry" not in order:
                order.append("entry")
            if len(order) == 2 and long("smp_lstate") == 4:
                break
        machine.write(buf, bytes(4 * 9))
        call("smp_slices_get", 0, buf)
        back_n = returned_d0()
        back = list(struct.unpack(">9I", machine.read(buf, 36)))
        sec = SM.SLICE_AREA // 512
        on_disk = disk.get(STORE_SECTOR + 1 + sec, bytes(512))[:36]
        out.update(loaded=loaded, analysis=an, onsets=ons, set=set_rc, order=order, back_n=back_n,
                   back=back, disk_table=list(struct.unpack("<9I", on_disk)),
                   entry_word=hex(pool.get((8 + 12) // 4, 0)), routing_changed=route.get("changed", 0))
        near = all(any(abs(o - h) <= 400 for o in ons) for h in hits)
        out["ok"] = (loaded and an == 2 and near and len(ons) == 4 and set_rc == 0
                     and order == ["area", "entry"] and back_n == 3 and back == table
                     and out["disk_table"] == table and not route.get("changed"))
    elif scenario == "save":
        # a recording of 3,000 frames on the DSP, 16 MB into the recordings' area, for slot
        # 40 (SAMP 41; v0.22: any slot, any place); no image on the +Drive yet
        place = 16 << 20
        slot = 40
        rec_off = SM.REC_OFFSET + place
        recw = [rng.randrange(1 << 32) for _ in range(1500)]
        for k, x in enumerate(recw):
            pool[rec_off // 4 + k] = x
        status_out()
        for _ in range(200):                    # v0.22: past the boot's RAM check first
            period()
            call("smp_boot")
            if long("smp_booted") == 2:
                break
        call("smp_save_recording", slot, place, 3000)
        periods = 0
        while periods < 3000:
            period()
            call("smp_boot")
            periods += 1
            if long("smp_saved"):
                break
        got = b"".join(disk.get(STORE_SECTOR + 1 + rec_off // 512 + k, bytes(512)) for k in range(12))
        exp = struct.pack("<1500I", *recw)
        exp += bytes(len(got) - len(exp))
        d = b"".join(disk.get(STORE_SECTOR + 1 + k, bytes(512)) for k in range(8))
        entry = struct.unpack_from("<IIfI", d, 8 + 16 * slot)
        name = d[SM.NAMES_OFFSET + SM.NAME_BYTES * slot:SM.NAMES_OFFSET + SM.NAME_BYTES * slot + 6]
        count = struct.unpack_from("<I", d, 4)[0]
        hdr = disk.get(STORE_SECTOR, bytes(512))
        out.update(periods=periods, saved=struct.unpack(">i", machine.read(syms["smp_saved"], 4))[0],
                   frames_equal=got == exp, entry=[hex(entry[0]), entry[1], entry[2], entry[3]],
                   dir_magic=hex(struct.unpack_from("<I", d, 0)[0]),
                   header=hdr[:12].hex(), sent_back=dsp["sent_back"],
                   heard=long("smp_tdm_heard"), disk_writes=io["writes"],
                   routing_changed=route.get("changed", 0), name=name.decode("latin-1"), count=count)
        out["ok"] = (out["saved"] == 1 and got == exp and entry[0] == base + rec_off
                     and entry[1] == 3000 and entry[3] == 1 and hdr[:4] == b"DN2Q"
                     and name == b"REC041" and count >= slot + 1
                     and not route.get("changed"))
    out["log"] = log[-8:]
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/waverider-m5")
    p.add_argument("--root", default=str(HERE.parent))
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--warmup", type=int, default=20_000_000)
    p.add_argument("--steps", default="func-src,wait:20,png:menu,down,down,png:cursor,"
                   "yes,wait:30,png:syn,frame:after")
    p.add_argument("--png-dir", default=None)
    p.add_argument("--json", default=None)
    p.add_argument("--stock", action="store_true", help="install nothing: the control")
    p.add_argument("--regs-at", action="append", default=[], help="record registers at VA")
    p.add_argument("--item-log", action="store_true", help="log every UI-queue item the main loop pops")
    p.add_argument("--access", action="append", default=[], metavar="VA:N",
                   help="record every read and write of N bytes at VA, by PC")
    p.add_argument("--count", action="append", default=[], metavar="VA",
                   help="count the entries to VA (after reset-trace, if one is given)")
    p.add_argument("--stack-at", action="append", default=[], metavar="VA",
                   help="at every entry to VA, the code addresses on the stack: who calls it")
    p.add_argument("--regs-last", type=int, default=0, metavar="N",
                   help="keep the last N register rows at each --regs-at VA, not the first 6")
    p.add_argument("--args-at", action="append", default=[],
                   help="keep the long arguments of the last entry to VA (for call: argN@VA)")
    p.add_argument("--label-log", action="store_true",
                   help="log every getShortName call (caller, this, id, this+0xDE) and every read of a "
                        "record's short-name field (+0x30), with the reading code: where the SYN page's labels come from")
    p.add_argument("--pixel-callers", default=None, metavar="X0,Y0,X1,Y1",
                   help="for every setPixel inside the box, the code addresses on the stack: who draws it")
    p.add_argument("--panel-writers", default=None, metavar="X0,Y0,X1,Y1",
                   help="every write to the two panel buffers (0x44622bc8, 0x44622fc8; 16 B a row) "
                        "inside the pixel box, with the code addresses on the stack")
    p.add_argument("--watch-types", action="store_true",
                   help="log every write to a track's machine type byte (sound+0xDE)")
    a = p.parse_args()

    root = pathlib.Path(a.root)
    build = root / a.build
    png_dir = pathlib.Path(a.png_dir) if a.png_dir else build / ("screens-stock" if a.stock else "screens")
    machine = Machine(a.snapshot)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    if not a.stock:
        image = (build / "section_3_MAIN_OS.bin").read_bytes()
        runs = differences(stock, image)
        n = machine.apply(runs)
        print(f"  installed {len(runs)} run(s), {n} bytes, from {build}")
        # A snapshot has booted already, so the platform loader never runs here: put
        # its run-time copies (the area's data window and each CODE chunk) where the
        # loader would have, or a build on the platform jumps into empty RAM.
        if len(image) > len(stock):
            sys.path.insert(0, str(HERE.parent / "src"))
            from dnfw.mods import platform       # noqa: PLC0415
            for va, blob in platform.runtime(image):
                machine.write(va, blob)
                print(f"  placed {len(blob)} bytes at {va:#010x} (the platform loader's copy)")
    else:
        print("  stock: nothing installed (the control)")

    from unicorn import UC_HOOK_CODE
    from unicorn import m68k_const as K

    uc = machine.uc
    calls: dict[str, dict] = {}
    writes, frames, shots, mems, calls_made = [], {}, {}, {}, []
    built, counted = {"n": 0}, {"n": 0}

    def arg(off):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        return struct.unpack(">i", bytes(uc.mem_read(sp + off, 4)))[0]

    for va, (name, off) in WATCH.items():
        def hit(uc_, address, size, user, name=name, off=off):
            t = arg(off)
            ret = arg(0) & 0xFFFFFFFF
            row = calls.setdefault(name, {"n": 0, "types": {}, "type5_callers": []})
            row["n"] += 1
            row["types"][str(t)] = row["types"].get(str(t), 0) + 1
            if t == 5 and len(row["type5_callers"]) < 12 and f"{ret:#010x}" not in row["type5_callers"]:
                row["type5_callers"].append(f"{ret:#010x}")
        uc.hook_add(UC_HOOK_CODE, hit, begin=va, end=va)

    # every static read of a sound's machine type byte (`mvsb %aN@(222)`), with the
    # value it read: a site that reads 5 and was not rerouted is a candidate for
    # WaveTone-only behaviour that Waverider does not get
    type_reads: dict[str, dict] = {}
    for va, reg in TYPE_READS.items():
        def read(uc_, address, size, user, reg=reg):
            base = uc.reg_read(getattr(K, f"UC_M68K_REG_A{reg}"))
            v = struct.unpack(">b", bytes(uc.mem_read(base + 222, 1)))[0]
            row = type_reads.setdefault(f"{address:#010x}", {"n": 0, "values": {}})
            row["n"] += 1
            row["values"][str(v)] = row["values"].get(str(v), 0) + 1
        uc.hook_add(UC_HOOK_CODE, read, begin=va, end=va)

    getter5: dict[str, int] = {}

    def getter_rts(uc_, address, size, user):
        # the vtable getter 0x40036462 returns sound+0xDE: who asked, when it is 5
        if struct.unpack(">b", struct.pack(">B", uc.reg_read(K.UC_M68K_REG_D0) & 0xFF))[0] == 5:
            ret = f"{arg(0) & 0xFFFFFFFF:#010x}"
            getter5[ret] = getter5.get(ret, 0) + 1
    uc.hook_add(UC_HOOK_CODE, getter_rts, begin=GETTER_RTS, end=GETTER_RTS)

    labels: dict[str, dict] = {"calls": {}, "field_reads": {}}
    if a.label_log:
        from unicorn import UC_HOOK_MEM_READ

        def short_name(uc_, address, size, user):
            this, rid = arg(4) & 0xFFFFFFFF, arg(8)
            ret = arg(0) & 0xFFFFFFFF
            try:
                t = struct.unpack(">b", bytes(uc.mem_read(this + 0xDE, 1)))[0]
            except Exception:                   # noqa: BLE001 -- this may not be a sound
                t = None
            key = f"{ret:#010x} id {rid}"
            row = labels["calls"].setdefault(key, {"n": 0, "this": f"{this:#010x}", "this_DE": t})
            row["n"] += 1

        uc.hook_add(UC_HOOK_CODE, short_name, begin=GET_SHORT_NAME, end=GET_SHORT_NAME)

        def field_read(uc_, access, address, size, value, user):
            off = (address - PARAM_TABLE) % PARAM_BYTES
            if 0x30 <= off < 0x34:
                pc = uc.reg_read(K.UC_M68K_REG_PC)
                rid = (address - PARAM_TABLE) // PARAM_BYTES
                row = labels["field_reads"].setdefault(f"{pc:#010x}", {"n": 0, "ids": []})
                row["n"] += 1
                if rid not in row["ids"] and len(row["ids"]) < 24:
                    row["ids"].append(rid)

        uc.hook_add(UC_HOOK_MEM_READ, field_read, begin=PARAM_TABLE,
                    end=PARAM_TABLE + PARAM_RECORDS * PARAM_BYTES - 1)

    # every read and write of a range, by the PC that made it (and the code on the stack)
    access: dict[str, int] = {}
    for spec in a.access:
        from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
        va, n = (int(v, 0) for v in spec.split(":"))

        def touched(uc_, kind, address, size, value, user, va=va):
            pc = uc.reg_read(K.UC_M68K_REG_PC)
            sp = uc.reg_read(K.UC_M68K_REG_A7)
            stack = struct.unpack(">24I", bytes(uc.mem_read(sp, 96)))
            chain = " ".join(f"{v:08x}" for v in stack if 0x40000400 <= v < 0x40220000)[:44]
            what = "w" if kind == UC_MEM_WRITE else "r"
            key = f"{what} +{address - va:#x} pc {pc:#010x} <- {chain}"
            access[key] = access.get(key, 0) + 1

        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, touched, begin=va, end=va + n - 1)

    counts: dict[str, int] = {}
    frames_at_reset = [0]
    for va in a.count:
        def counted(uc_, address, size, user):
            key = f"{address:#010x}"
            counts[key] = counts.get(key, 0) + 1
        uc.hook_add(UC_HOOK_CODE, counted, begin=int(va, 0), end=int(va, 0))

    pixels: dict[str, int] = {}
    if a.pixel_callers:
        x0, y0, x1, y1 = (int(v) for v in a.pixel_callers.split(","))

        def pixel(uc_, address, size, user):
            x, y = arg(8), arg(12)
            if x0 <= x <= x1 and y0 <= y <= y1:
                sp = uc.reg_read(K.UC_M68K_REG_A7)
                stack = struct.unpack(">64I", bytes(uc.mem_read(sp, 256)))
                chain = " ".join(f"{v:08x}" for v in stack if 0x40000400 <= v < 0x40310000 or 0x4670C000 <= v < 0x4670D000)
                key = chain.split(" ")[:6]
                pixels[" ".join(key)] = pixels.get(" ".join(key), 0) + 1
        uc.hook_add(UC_HOOK_CODE, pixel, begin=SET_PIXEL, end=SET_PIXEL)

    panel_writers: dict[str, int] = {}
    if a.panel_writers:
        px0, py0, px1, py1 = (int(v) for v in a.panel_writers.split(","))

        def panel_write(pc, address, value, size):
            for base in (0x44622BC8, 0x44622FC8):
                off = address - base
                if 0 <= off < 1024:
                    y, bx = off // 16, off % 16
                    if py0 <= y <= py1 and px0 // 8 <= bx <= px1 // 8:
                        sp = uc.reg_read(K.UC_M68K_REG_A7)
                        stack = struct.unpack(">64I", bytes(uc.mem_read(sp, 256)))
                        chain = [f"{pc:08x}"] + [f"{v:08x}" for v in stack if 0x40000400 <= v < 0x40310000][:7]
                        panel_writers[" ".join(chain)] = panel_writers.get(" ".join(chain), 0) + 1
        machine.watch_writes(0x44622BC8, 0x44622FC8 + 1024, panel_write)

    # who calls VA: the code addresses on the stack at its entry, deepest first
    stacks: dict[str, int] = {}
    for va in a.stack_at:
        def stacked(uc_, address, size, user):
            sp = uc.reg_read(K.UC_M68K_REG_A7)
            words = struct.unpack(">256I", bytes(uc.mem_read(sp, 1024)))
            chain = " ".join(f"{v:08x}" for v in words if 0x40000400 <= v < 0x40310000)
            key = f"{address:#010x}: " + " ".join(chain.split(" ")[:12])
            stacks[key] = stacks.get(key, 0) + 1
        uc.hook_add(UC_HOOK_CODE, stacked, begin=int(va, 0), end=int(va, 0))

    # v0.22: every UI-queue item the main loop pops (type, code, flags, time), after the
    # pop at 0x4002f17e: how keys and encoders arrive (the recorder's input filter)
    items: list = []
    if a.item_log:
        def popped(uc_, address, size, user):
            item = uc.reg_read(K.UC_M68K_REG_D0)
            try:
                items.append(bytes(uc.mem_read(item, 16)).hex())
            except Exception:                   # noqa: BLE001
                items.append(f"unreadable {item:#x}")
        uc.hook_add(UC_HOOK_CODE, popped, begin=0x4002F184, end=0x4002F184)

    regs_at: dict[str, list] = {}
    for va in a.regs_at:
        def at(uc_, address, size, user):
            rows = regs_at.setdefault(f"{address:#010x}", [])
            if len(rows) < 6 or a.regs_last:
                rows.append({f"{r}{i}": f"{uc.reg_read(getattr(K, f'UC_M68K_REG_{r}{i}')):#010x}"
                             for r in "DA" for i in range(8)})
                del rows[:-max(6, a.regs_last)]
        uc.hook_add(UC_HOOK_CODE, at, begin=int(va, 0), end=int(va, 0))

    # the long arguments of the last entry to each --args-at VA, for `call:` to reuse
    # (`argN@VA`): MACHINE SEL's model object, say, which no fixed address holds
    entry_args: dict[int, tuple] = {}
    for va in a.args_at:
        def took(uc_, address, size, user):
            entry_args[address] = tuple(arg(4 * n) & 0xFFFFFFFF for n in range(1, 6))
        uc.hook_add(UC_HOOK_CODE, took, begin=int(va, 0), end=int(va, 0))

    track_getter5: dict[str, int] = {}

    def track_getter_exit(uc_, address, size, user):
        # getMachineType(track) 0x4004b7f2's exit: d0 the type, a2 saved at sp@0,
        # the caller's return address at sp@4
        if struct.unpack(">b", struct.pack(">B", uc.reg_read(K.UC_M68K_REG_D0) & 0xFF))[0] == 5:
            ret = f"{arg(4) & 0xFFFFFFFF:#010x}"
            track_getter5[ret] = track_getter5.get(ret, 0) + 1
    uc.hook_add(UC_HOOK_CODE, track_getter_exit, begin=TRACK_GETTER_EXIT, end=TRACK_GETTER_EXIT)

    def setter(uc_, address, size, user):
        a0 = uc.reg_read(K.UC_M68K_REG_A0)
        writes.append({"sound": f"{a0:#010x}", "type": uc.reg_read(K.UC_M68K_REG_D2) & 0xFF})
    uc.hook_add(UC_HOOK_CODE, setter, begin=SETTER_WRITE, end=SETTER_WRITE)

    # every write to any track's machine type byte `sound+0xDE` in the live kit,
    # whoever makes it: the setter, a bulk copy, a message handler. The step it
    # happened in and the code addresses on the stack say who asked.
    type_writes = []
    step_now = {"name": "warmup"}
    type_lo = machine.long(KIT_POINTER) + 52 + 0xDE
    type_hi = type_lo + SOUND_STRIDE * 15

    def type_write(pc, address, value, size):
        for t in range(16):
            at = type_lo + SOUND_STRIDE * t
            if address <= at < address + size and len(type_writes) < 256:
                v = (value >> (8 * (address + size - 1 - at))) & 0xFF
                sp = uc.reg_read(K.UC_M68K_REG_A7)
                stack = struct.unpack(">24I", bytes(uc.mem_read(sp, 96)))
                type_writes.append({"step": step_now["name"], "pc": f"{pc:#010x}", "track": t,
                                    "value": v - 256 if v > 127 else v, "size": size,
                                    "stack": [f"{x:#010x}" for x in stack
                                              if 0x40000400 <= x < 0x40310000][:8]})
    if a.watch_types:
        machine.watch_writes(type_lo - 3, type_hi, type_write)

    mirror_writes = []

    def mirror(pc, address, value, size):
        if (address - MIRROR_TYPE) % MIRROR_STRIDE == 0 and len(mirror_writes) < 64:
            mirror_writes.append({"pc": f"{pc:#010x}", "track": (address - MIRROR_TYPE) // MIRROR_STRIDE,
                                  "value": value, "size": size})
    machine.watch_writes(MIRROR_TYPE, MIRROR_TYPE + MIRROR_STRIDE * 15, mirror)

    def builder_done(uc_, address, size, user):
        built["n"] += 1
    uc.hook_add(UC_HOOK_CODE, builder_done, begin=FRAME_BUILT, end=FRAME_BUILT)

    def count(uc_, address, size, user):
        counted["n"] += 1

    returned = {"d0": 0}

    def guest_call(fn, *args, limit=5_000_000):
        """Call FN in the paused machine and put every register back, as digikit's
        machinepatch.call_dispatch does. SR is never read: the patched Unicorn
        clobbers the condition codes on that read. -> instructions run."""
        regs = [getattr(K, f"UC_M68K_REG_{r}{i}") for r in "DA" for i in range(8)]
        saved = [uc.reg_read(r) for r in regs]
        saved_pc = uc.reg_read(K.UC_M68K_REG_PC)
        sp = STACK_TOP - 0x100
        machine.write(sp, struct.pack(">I", SENTINEL) + b"".join(struct.pack(">I", x) for x in args))
        machine.write(SENTINEL, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        counted["n"] = 0
        h = uc.hook_add(UC_HOOK_CODE, count)
        # `panel.settle` runs digikit's fast stepper, whose permanent block hook
        # stops the machine once its step budget is spent (longrun._FastStepper).
        # Left at zero, it stops a call at its first block with nothing run --
        # which is how three earlier calls here "returned" having done nothing.
        stepper = getattr(machine.m, "_fast_stepper_obj", None)
        if stepper is not None:
            stepper.left = 1 << 40
        try:
            uc.emu_start(fn, SENTINEL, count=limit)
        finally:
            if stepper is not None:
                stepper.left = 0
            uc.hook_del(h)
            returned["d0"] = uc.reg_read(K.UC_M68K_REG_D0)
            for r, v in zip(regs, saved):
                uc.reg_write(r, v)
            uc.reg_write(K.UC_M68K_REG_PC, saved_pc)
        return counted["n"]

    guest_call.returned = returned
    panel = Panel(machine, png_dir=str(png_dir))
    panel.settle(a.warmup)
    for step in [s.strip() for s in a.steps.split(",") if s.strip()]:
        step_now["name"] = step
        if step == "func-src":
            panel.hold(FUNC, 3_000_000)
            panel.tap(SRC, after=3_000_000)
            panel.let_go(FUNC)
        elif step in KEYS:
            panel.tap(KEYS[step])
        elif step.startswith("png:"):
            shots[step[4:]] = panel.screen(step[4:])
        elif step.startswith("wait:"):
            panel.settle(int(float(step[5:]) * 1_000_000))
        elif step.startswith("turn:"):
            _, enc, delta = step.split(":")
            panel.push_and_turn(int(enc), int(delta))
        elif step.startswith("spin:"):
            _, enc, delta = step.split(":")
            machine.pc = panel.panelin.encoder(machine.m, panel.profile, int(enc), int(delta))
            panel.settle(10_000_000)
        elif step.startswith("press:") or step.startswith("release:"):
            kind, code = step.split(":")
            key = ((int(code) - 1) // 8, (int(code) - 1) % 8)
            (panel.hold if kind == "press" else panel.let_go)(key, 2_000_000)
        elif step.startswith("tap:"):
            code = int(step[4:])
            panel.tap(((code - 1) // 8, (code - 1) % 8))
        elif step.startswith("blocks:"):
            # every instruction address executed while the machine runs MILLIONS
            # (after an optional encoder turn, so the page redraws): two of these,
            # taken with the track on WaveTone and on Waverider, diff to the code
            # that treats the two differently (emu_lfo4_modal.py's method). A code
            # hook, not a block hook: the fast stepper chains translated blocks.
            parts = step.split(":")
            name, millions = parts[1], parts[2]
            seen = set()

            def blk(uc_, address, size, user):
                seen.add(address)
            h = uc.hook_add(UC_HOOK_CODE, blk)
            if len(parts) == 5 and parts[3] == "tap":     # blocks:NAME:M:tap:CODE -- a key, e.g. the page key
                code = int(parts[4])
                panel.tap(((code - 1) // 8, (code - 1) % 8))
            elif len(parts) == 5:
                machine.pc = panel.panelin.encoder(machine.m, panel.profile, int(parts[3]), int(parts[4]))
            panel.settle(int(float(millions) * 1_000_000))
            uc.hook_del(h)
            png_dir.mkdir(parents=True, exist_ok=True)
            (png_dir / f"{name}.blocks.txt").write_text("\n".join(f"{x:08x}" for x in sorted(seen)))
            print(f"  blocks {name}: {len(seen)} distinct")
        elif step.startswith("call:"):
            # call:VA[:ARG...] -- a routine that does not run here, entered directly.
            # ARG: a number, `kit` (the live kit), `soundT` (track T's sound), or
            # `long@VA` (the long stored at VA).
            parts = step.split(":")
            args = []
            for x in parts[2:]:
                if x == "kit":
                    args.append(machine.long(KIT_POINTER))
                elif x.startswith("sound"):
                    args.append(machine.long(KIT_POINTER) + 52 + SOUND_STRIDE * int(x[5:]))
                elif x.startswith("long@"):
                    args.append(machine.long(int(x[5:], 0)))
                elif x.startswith("arg") and "@" in x:
                    # argN@VA, or argN@VA-OFF: an object that argument points into
                    n, va = x[3:].split("@")
                    va, _, off = va.partition("-")
                    args.append((entry_args[int(va, 0)][int(n) - 1] - int(off or "0", 0)) & 0xFFFFFFFF)
                else:
                    args.append(int(x, 0) & 0xFFFFFFFF)
            ran = guest_call(int(parts[1], 0), *args)
            d0 = returned["d0"]
            calls_made.append({"fn": parts[1], "args": [f"{v:#x}" for v in args], "ran": ran,
                               "d0": d0 - (1 << 32) if d0 & 0x80000000 else d0})
            print(f"  call {parts[1]}({', '.join(f'{v:#x}' for v in args)}): {ran:,} instructions, "
                  f"d0 = {calls_made[-1]['d0']}")
        elif step == "reset-trace":
            # forget what the pixel and panel traces saw so far: trace one screen state only
            pixels.clear()
            panel_writers.clear()
            access.clear()
            counts.clear()
            frames_at_reset[0] = panel.frames()
        elif step == "types":
            # every track's machine type byte, as the sound holds it
            kit = machine.long(KIT_POINTER)
            got = [struct.unpack(">b", machine.read(kit + 52 + SOUND_STRIDE * t + 0xDE, 1))[0]
                   for t in range(16)]
            mems[f"types@{len(mems)}"] = got
            print(f"  types {got}")
        elif step.startswith("sysex:"):
            # v0.14, the sample link: each message in FILE (hex, one a line) through the
            # stock SysEx router (msg, len, source 2 = USB), as the MIDI input task would;
            # what reaches the stock sender is kept (FILE.replies.json)
            path = pathlib.Path(step[6:])
            msgs = [bytes.fromhex(x) for x in path.read_text().split()]
            buf = SENTINEL + 0x1000
            sent = []

            def at_sender(uc_, address, size, user):
                sp = uc.reg_read(K.UC_M68K_REG_A7)
                b, n, _ab, port = struct.unpack(">4I", bytes(uc.mem_read(sp + 4, 16)))
                sent.append((bytes(uc.mem_read(b, n)).hex() if 0 < n < 4096 else "", port))
            hs = uc.hook_add(UC_HOOK_CODE, at_sender, begin=SYSEX_SENDER, end=SYSEX_SENDER)
            total = 0
            for msg in msgs:
                machine.write(buf, msg)
                total += guest_call(SYSEX_ROUTER, buf, len(msg), 2)
            uc.hook_del(hs)
            (path.parent / (path.name + ".replies.json")).write_text(json.dumps(sent))
            print(f"  sysex: {len(msgs)} message(s), {len(sent)} repl(ies), {total:,} instructions")
        elif step.startswith("isr:"):
            # the ISR N times; the frame's words 2650..2681 (the sample link's packet,
            # big-endian 16-bit) after each, to png_dir/NAME.link.json
            _, n, name = step.split(":")
            got = []
            for _k in range(int(n)):
                guest_call(ISR)
                fr = machine.read(FRAME + 2650, 32)
                got.append([struct.unpack_from(">H", fr, 2 * k)[0] for k in range(16)])
            png_dir.mkdir(parents=True, exist_ok=True)
            (png_dir / f"{name}.link.json").write_text(json.dumps(got))
            print(f"  isr x{n}: {sum(1 for g in got if g[0] == 0x5A31)} packet(s)")
        elif step.startswith("link16:"):
            # v0.16, the sample link end to end on the ColdFire (csrc/sampler/link.c), with
            # the +Drive and the DSP played by Python: link16:SYMS.json:SCENARIO, SCENARIO
            # fast (one TDM packet dropped once), dead (every TDM packet dropped: the loader
            # stops; v0.20, the frame's words are never used), save (a recording read back over
            # TDM and written). Every period: the frame's routing words stay stock's
            _, syms_path, scenario = step.split(":")
            syms = json.loads(pathlib.Path(syms_path).read_text())
            sys.path.insert(0, str(HERE.parent / "src"))
            from dnfw.sampler import live as SL, machines as SM      # noqa: PLC0415
            from dnfw.waverider import dsp as WD                       # noqa: PLC0415
            result = link16(machine, uc, K, guest_call, syms, scenario, SL, SM, WD)
            png_dir.mkdir(parents=True, exist_ok=True)
            (png_dir / f"link16_{scenario}.json").write_text(json.dumps(result, indent=1))
            print(f"  link16 {scenario}: {json.dumps({k: v for k, v in result.items() if k != 'log'})}")
        elif step.startswith("poke:"):
            _, va, data = step.split(":")
            machine.write(int(va, 0), bytes.fromhex(data))
            print(f"  poke {va} = {data}")
        elif step.startswith("mem:"):
            _, va, n = step.split(":")
            # a second read of the same address keeps the first: key it by its order
            key = va if va not in mems else f"{va}@{len(mems)}"
            mems[key] = machine.read(int(va, 0), int(n, 0)).hex()
        elif step.startswith("sync:"):
            # One track, through the routine the ISR's note path calls when a
            # triggered track's sound has changed (0x40026bbc / 0x40026bfe).
            track = int(step[5:])
            sound = machine.long(KIT_POINTER) + 52 + SOUND_STRIDE * track
            ran = guest_call(TRACK_SYNC, sound, track)
            print(f"  track sync {TRACK_SYNC:#010x}({sound:#010x}, {track}): {ran:,} instructions")
        elif step == "sync":
            # The mirror the frame builder reads (`0x80003af0 + 153t`, a copy of
            # sound+0xDE onwards) is refreshed by `0x4002549c(sound, track)`: from
            # the ISR when a track's note triggers with a changed sound, and for
            # all sixteen tracks by `0x40025af4(kit)` when a kit loads. No note
            # plays in this emulator, so the kit-load sync is entered -- the
            # firmware's own copy, not a poke.
            kit = machine.long(KIT_POINTER)
            ran = guest_call(KIT_SYNC, kit)
            print(f"  kit sync {KIT_SYNC:#010x}({kit:#010x}): {ran:,} instructions")
        elif step.startswith("frame:"):
            name = step[6:]
            before = built["n"]
            ran = guest_call(ISR)
            frame = machine.read(FRAME, FRAME_BYTES)
            png_dir.mkdir(parents=True, exist_ok=True)
            out = png_dir / f"{name}.frame_be.bin"
            out.write_bytes(frame)
            # what the builder read, kept beside what it wrote: the modulated
            # per-track mirror (202 B a track) and each track's sound object
            (png_dir / f"{name}.mirror_be.bin").write_bytes(machine.read(MIRROR, 16 * MIRROR_BYTES))
            kit = machine.long(KIT_POINTER)
            (png_dir / f"{name}.sounds_be.bin").write_bytes(
                b"".join(machine.read(kit + 52 + SOUND_STRIDE * t, SOUND_STRIDE) for t in range(16)))
            words = [struct.unpack_from(">H", frame, FRAME_MACHINE + 2 * t)[0] for t in range(16)]
            frames[name] = {"file": str(out), "builder_ran": built["n"] - before,
                            "isr_instructions": ran, "machine_words": words}
            print(f"  frame {name}: the builder ran {built['n'] - before} time(s) in {ran:,} "
                  f"instructions; machine words {words}")
        else:
            raise SystemExit(f"unknown step {step!r}")
        print(f"  {step}")

    result = {"build": str(build), "snapshot": a.snapshot, "stock": a.stock, "screens": shots,
              "calls": calls, "type_reads": type_reads, "getter_type5_callers": getter5,
              "track_getter_type5_callers": track_getter5, "regs_at": regs_at, "stacks": stacks,
              "setter_writes": writes,
              "mirror_type_writes": mirror_writes, "type_writes": type_writes,
              "direct_calls": calls_made,
              "frames": frames, "memory": mems, "labels": labels, "pixel_callers": pixels, "access": access, "counts": counts,
              "screen_frames": panel.frames() - frames_at_reset[0],
              "panel_writers": panel_writers, "items": items}
    print(json.dumps(result, indent=1))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(result, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
