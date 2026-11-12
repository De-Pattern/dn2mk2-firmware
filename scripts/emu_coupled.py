"""The coupled emulator (v0.48, for FLEX; docs/flex-design.md): the ColdFire and the DSP run
together, block by block, as the unit runs them.

Each audio period:
  1. the ColdFire's UI runs a slice (Panel.settle), then its audio ISR (0x40025e36 to its rte),
     which builds the DSP's frame (0x80005e60, 16-bit big-endian) and writes the fast link's
     transmit page (slots 8..15, TDM_TX's half);
  2. the DSP runs one block of its per-block routine (sw 0x1c2712, sharc_waverider_m5's
     runner) on that frame; at its dispatch the ColdFire's packet is put in the DSP's receive
     page (the page TDM_PAGE names, word for word: the two pages share their layout,
     docs/link-research.md); after the sample machines its transmit page (slots 14..15) is read;
  3. the DSP's reply (its status tail, SM.REPLY_PAGES[0] + REPLY_TAIL) goes to the ColdFire's
     SPI reply tail (0x80005e40), and its transmit slots to both halves of the ColdFire's TDM
     receive page, as the ISR finds them next period.

Before this, each side was tested against a stand-in for the other (emu_waverider_menu's
link16 DSP, the runner's poked frames), which is how BOUNCE passed every check and played
nothing on the unit. Here nothing stands in: the frame, every packet and every status word are
the other side's own.

As a library: Coupled(build_syx, snapshot, ...) then .period(), .periods(n), .tap(code),
.press/.release, .poke/.long, .track_out(t) (each track's buffer at the dispatch's end, the
last block), .smp_out(t) (a sample voice's own output)."""

from __future__ import annotations

import os
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
from emulib import bounded                                      # noqa: E402

ISR, ISR_RTE = 0x40025E36, 0x40027BC6
CF_FRAME = 0x80005E60                   # the frame as the ColdFire builds it (16-bit BE)
CF_REPLY_TAIL = 0x80005E40              # the SPI reply's tail: the DSP's status, 16 BE halfwords
CF_TDM_TX, CF_TDM_RX = 0x4E6E0100, 0x4E6DF100
STACK_TOP, SENTINEL = 0x46A20000, 0x46A20400
SEQ_ISR, SEQ_VECTOR = 0x400D987A, 121   # the sequencer's timer ISR (emu_jump.py, emu_waverider_menu.py)
SEQ_ENTRIES_A_STEP = 24                 # 4 entries a tick, 6 ticks a sixteenth (measured, emu_jump.py)
UI_SLICE = 1_000_000                    # ColdFire instructions a period between ISRs (the UI loop's pass needs about this here)
# v0.48, the timing-faithful mode (docs/coupled-emulator.md): on the unit the audio ISR takes
# 56 % of the ColdFire's time with the sequencer stopped (docs/coldfire-tasks.md, the USB
# probe's protocol 3), so a frame is the ISR's own cost / 0.56, measured here in the same units
# the UI's slice and the timers count (the fast stepper's blocks x per_block)
ISR_SHARE_STOPPED = 0.56
AUDIO_HZ = 1500
TICK = 0x466758B0                       # the panel task's 60 Hz tick (the timer wheel's, every PIT2)
IDLE_SPIN = 0x400CF0E2                  # the idle task's bra.s * (docs/coldfire-tasks.md)


def _bits(x: float) -> int:
    return struct.unpack("<I", struct.pack("<f", x))[0]


class _FrameClock:
    """an event source for digikit's spin: its deadline is where the UI's share of the frame
    ends, so the deadline stepping stops the UI there (faithful mode only); it raises nothing"""
    def __init__(self):
        self.ui_end = None

    def step(self, done, remaining=None):
        if self.ui_end is None:
            return None
        return max(1, int(self.ui_end - done + 0.999))

    def service(self, done):
        pass


class Coupled:
    def __init__(self, build_syx: str, snapshot: str, stock_syx: str, digikit_sharc: str | None = None,
                 png_dir: str | None = None, verbose: bool = False, dsp: bool = True):
        self.verbose = verbose
        t0 = time.perf_counter()
        self._load_images(build_syx, stock_syx)
        self._cf_setup(snapshot, png_dir)
        # dsp=False: the ColdFire alone (the ISR, the sequencer, the frame it builds, the UI),
        # no DSP block: its status and replies stay as they were (category 2, not 1)
        self.dsp = dsp
        if dsp:
            self._dsp_setup(digikit_sharc)
        self.blocks = 0
        self.last_seq = {0: None, 1: None}
        self.delivered = 0
        self.dsp_packets = 0
        self.halt = None
        self.taps: dict = {}
        self.input = None                       # block -> ([32 floats L], [32 floats R]): the inputs
        # negative controls only (a test breaking one link on purpose, to show it is caught):
        # frame_filter(bytes) -> bytes, the frame as the DSP gets it (big-endian, as built);
        # packet_filter(words) -> words or None, the ColdFire's packet before delivery
        self.frame_filter = None
        self.packet_filter = None
        # the scheduling: "fast" (UI_SLICE a period: the UI about 80 x the audio's pace) or
        # "faithful" (set_timing: a frame's worth of instructions shared as on the unit)
        self.timing = "fast"
        self.frame_units = None
        self.isr_units = []
        self.ui_units = 0.0
        self._clock = _FrameClock()
        self._frame_t0 = None
        self.last_call_units = 0.0
        # progress (periods(..., label=)) and the watchdog
        self.phase = "setup"
        self.period_wall = []
        self._last_done = time.perf_counter()
        self.shortcut_probe = True
        self.seq_acc = 0.0                      # the sequencer's timer, kept in step with the frames
        self.probes_shortcut = 0
        from dnfw.sampler import live as SL     # noqa: PLC0415
        self.SL_C = SL.layout().C
        if verbose:
            print(f"  coupled: ready in {time.perf_counter() - t0:.0f} s", flush=True)

    # -- images ----------------------------------------------------------------------------
    def _load_images(self, build_syx, stock_syx):
        from dnfw.cli.files import read_image                  # noqa: PLC0415
        from dnfw.firmware.load import load                    # noqa: PLC0415
        built = load(read_image(pathlib.Path(build_syx)))
        stock = load(read_image(pathlib.Path(stock_syx)))
        self.sec3 = built.container.find(3).unpack()
        self.sec7 = built.container.find(7).unpack()
        self.stock3 = stock.container.find(3).unpack()
        self.stock7 = stock.container.find(7).unpack()
        self.stock_syx = stock_syx

    # -- the ColdFire ----------------------------------------------------------------------
    def _cf_setup(self, snapshot, png_dir):
        from emulib.image import differences                   # noqa: PLC0415
        from emulib.machine import Machine                     # noqa: PLC0415
        from unicorn import UC_PROT_ALL, UcError                # noqa: PLC0415
        from unicorn import m68k_const as K                    # noqa: PLC0415
        from dnfw.mods import platform                         # noqa: PLC0415
        from dnfw.sampler import machines as SM                # noqa: PLC0415
        self.K, self.SM = K, SM
        m = Machine(snapshot)
        self.machine, self.uc = m, m.uc
        snap_image = pathlib.Path(snapshot + ".section_3_MAIN_OS.bin")
        stock = self.stock3
        if snap_image.exists():
            back = [(va, stock[va - 0x40000400:va - 0x40000400 + len(b)]) for va, b in
                    differences(stock, snap_image.read_bytes()) if va + len(b) <= 0x40000400 + len(stock)]
            m.apply(back)
        m.apply(differences(stock, self.sec3))
        for va, blob in platform.runtime(self.sec3):
            m.write(va, blob)
        for page in range(SM.MIRROR, SM.MIRROR + SM.MIRROR_BYTES, 0x100000):
            try:
                self.uc.mem_map(page, 0x100000, UC_PROT_ALL)
            except UcError:
                pass
        m.flush()
        self.regs = [getattr(K, f"UC_M68K_REG_{r}{i}") for r in "DA" for i in range(8)]
        from emulib.panel import Panel                         # noqa: PLC0415
        self.panel = Panel(m, png_dir=png_dir or "out/coupled")
        self.faults0 = len(getattr(m.m, "faults", []))

    def call(self, fn, *args, until=None, limit=50_000_000):
        """FN(ARGS) on the ColdFire, its registers kept -> (d0, the pc it stopped at)"""
        uc, K, m = self.uc, self.K, self.machine
        saved = [uc.reg_read(r) for r in self.regs]
        pc0, sr0 = uc.reg_read(K.UC_M68K_REG_PC), uc.reg_read(K.UC_M68K_REG_SR)   # the UI's, put back
        sp = STACK_TOP - 0x200
        m.write(sp, struct.pack(">I", SENTINEL) + b"".join(struct.pack(">I", x & 0xFFFFFFFF) for x in args))
        m.write(SENTINEL, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        stepper = getattr(m.m, "_fast_stepper_obj", None)
        blocks = bounded.run(uc, m.m, fn, until if until is not None else SENTINEL, limit)
        if stepper is not None:
            self.last_call_units = blocks * stepper.per_block
        d0 = uc.reg_read(K.UC_M68K_REG_D0)
        pc = uc.reg_read(K.UC_M68K_REG_PC)
        for r, v in zip(self.regs, saved):
            uc.reg_write(r, v)
        uc.reg_write(K.UC_M68K_REG_PC, pc0)
        uc.reg_write(K.UC_M68K_REG_SR, sr0)
        m.pc = pc0
        return d0, pc

    def long(self, va) -> int:
        return self.machine.long(va)

    def read(self, va, n) -> bytes:
        return bytes(self.machine.read(va, n))

    def poke(self, va, data: bytes):
        self.machine.write(va, data)

    def put32(self, va, v):
        self.machine.write(va, struct.pack(">I", v & 0xFFFFFFFF))

    # -- the DSP ---------------------------------------------------------------------------
    def _dsp_setup(self, digikit_sharc):
        import sharc_waverider_m5 as M                         # noqa: PLC0415
        self.M = M
        dk_path = pathlib.Path(digikit_sharc or os.environ.get("DNFW_DIGIKIT_SHARC",
                                                                str(ROOT.parent / "digikit-wt-sharcemu")))
        dk = M.m1.Digikit(dk_path)
        M.fx.bind(str(dk_path / "tools"))
        M.m4.IMAGE = pathlib.Path(self.stock_syx)
        img = M.Image(dk, self.sec7)
        import tempfile                                         # noqa: PLC0415
        M.OUT.mkdir(parents=True, exist_ok=True)
        self._tmp = tempfile.TemporaryDirectory(dir=M.OUT)
        snap, m2mach = M.snapshot_path(dk, self.stock7, pathlib.Path(self._tmp.name))
        self.dsp_state = M.init_on(snap, m2mach, img, warm=True)
        self.dsp_i7 = M.m2.word_reg(self.dsp_state, "I7")    # v0.51: every block called with it (m4.unpack_call)
        self.dsp_instructions = 0

    def dsp_word(self, a) -> int:
        return (self.M.m2.word(self.dsp_state.state, a) or 0) & 0xFFFFFFFF

    def dsp_floats(self, a, n):
        return self.M.m2.floats(self.dsp_state.state, a, n)

    def dsp_poke(self, a, w):
        self.M.m2.poke(self.dsp_state.state, a, w)

    # -- the link --------------------------------------------------------------------------
    def _cf_packet(self):
        """the newest ColdFire transmit half holding a packet not yet delivered -> its 0x800
        bytes as words, or None (stock's zeros go over then)"""
        SM = self.SM
        best = None
        for half in (0, 1):
            raw = self.read(CF_TDM_TX + (half << 11), 0x800)
            x = struct.unpack_from(">I", raw, 4 * 8)[0]
            if x >> 16 != SM.TDM_TAG or x & 0xFFFF != SM.RX_MAGIC:
                continue
            seq = struct.unpack_from(">I", raw, 4 * 9)[0] & 0xFFFF
            if seq == self.last_seq[half]:
                continue
            self.last_seq[half] = seq
            best = struct.unpack(">512I", raw)
        return best

    def period(self, ui=UI_SLICE):
        """one audio period: the UI's slice, the ColdFire's ISR, the DSP's block, the replies"""
        if self.halt:
            return False
        t_start = time.perf_counter()
        timers = self.panel.timers
        if self.timing == "faithful":
            # the UI runs to the frame's end less the ISR's last cost, stopped exactly there by
            # the frame clock (the timers' deadline stepping would otherwise run on to the next
            # PIT deadline, a whole timer period: measured, 23 x the frame)
            last = self.isr_units[-1] if self.isr_units else self.frame_units * ISR_SHARE_STOPPED
            if self._frame_t0 is None or timers.now > self._frame_t0 + self.frame_units:
                self._frame_t0 = timers.now
            self._clock.ui_end = self._frame_t0 + self.frame_units - last
            ui = max(1, int(self._clock.ui_end - timers.now))
        if ui:
            self.ui_units += self.panel.settle(ui)
        self._seq_tick()
        _, pc = self.call(ISR, until=ISR_RTE)
        self.isr_units.append(self.last_call_units)
        if self.timing == "faithful":
            timers.now += self.last_call_units       # the ISR's time is the frame's too
            self._frame_t0 += self.frame_units
        if len(self.isr_units) > 4096:
            del self.isr_units[:2048]
        if pc != ISR_RTE:
            self.halt = f"the ColdFire's ISR stopped at {pc:#x}"
            return False
        frame_be = self.read(CF_FRAME, 2688)
        if self.frame_filter is not None:
            frame_be = self.frame_filter(frame_be)
        self.last_frame = frame_be
        if not self.dsp:
            self._cf_packet()
            self.blocks += 1
            now = time.perf_counter()
            self.period_wall.append(now - t_start)
            self._last_done = now
            return True
        frame = self.M.swap16(frame_be)
        packet = self._cf_packet()
        if packet is not None and self.packet_filter is not None:
            packet = self.packet_filter(packet)
        M, SM = self.M, self.SM
        tap = {}

        def at_dispatch(r):
            pg = (M.m2.word(r.state, SM.TDM_PAGE) or 0) & 1
            tap["pg"] = pg
            rx = SM.TDM_RX + (pg << 11)
            for frm in range(32):
                for k in range(8):
                    w = packet[16 * frm + 8 + k] if packet is not None else 0
                    M.m2.poke(r.state, rx + 64 * frm + 32 + 4 * k, w)
            tap["bufs"] = [M.m2.word(r.state, M.V.TRACK_BUFFERS + 4 * t) for t in range(16)]
            if self.input is not None:          # the inputs (L, R), as the per-block driver converts them
                left, right = self.input(self.blocks)
                for k in range(32):
                    M.m2.poke(r.state, SM.IN_BUF + 4 * k, _bits(left[k]))
                    M.m2.poke(r.state, SM.IN_BUF + 0x80 + 4 * k, _bits(right[k]))

        def after_smp(r):
            tx = SM.TDM_TX + (tap.get("pg", 0) << 11)
            tap["tx"] = [(M.m2.word(r.state, tx + 64 * frm + 56 + 4 * k) or 0) & 0xFFFFFFFF
                         for frm in range(32) for k in range(2)]
        hooks = {M.m3.DISPATCH: at_dispatch, M.dsp.PING_SW: after_smp}
        for k, fn in self.taps.items():
            hooks[k] = (lambda f0, f1: lambda r: (f0(r), f1(r, self)))(hooks[k], fn) if k in hooks \
                else (lambda f1: lambda r: f1(r, self))(fn)
        f = M.fixups(hooks)
        r = M.m4.unpack_call(self.dsp_state, frame, i7=self.dsp_i7)
        res = M.fx.run(r, 8_000_000, f)
        if not (res[0] == "halt" and res[1].pc_sw == M.m4.UNPACK_RETURN):
            self.halt = (f"the DSP's block {self.blocks}: {res[1].reason} at {res[1].pc_sw:#x}"
                         if res[0] == "halt" else f"the DSP's block {self.blocks}: {res[0]} at {res[1]:#x}")
            return False
        self.dsp_instructions += res[2]
        self.dsp_state = r
        self.last_bufs = [M.m2.floats(r.state, tap["bufs"][t], 32) for t in range(16)]
        if packet is not None:
            self.delivered += 1
        # the DSP's status -> the ColdFire's reply tail (both of the DSP's pages hold the same)
        h = []
        for k in range(8):
            w = self.dsp_word(SM.REPLY_PAGES[0] + SM.REPLY_TAIL + 4 * k)
            h += [w & 0xFFFF, w >> 16]
        self.poke(CF_REPLY_TAIL, struct.pack(">16H", *h))
        self.last_status = h
        # its transmit slots -> both halves of the ColdFire's receive page
        tx = tap.get("tx", [0] * 64)
        if any(tx):
            self.dsp_packets += 1
        for half in (0, 1):
            for i, w in enumerate(tx):
                frm, k = i >> 1, i & 1
                self.poke(CF_TDM_RX + (half << 11) + 4 * (16 * frm + 14 + k), struct.pack(">I", w))
        self._shortcut_probe()
        self.blocks += 1
        now = time.perf_counter()
        self.period_wall.append(now - t_start)
        self._last_done = now
        return True

    def _seq_tick(self):
        """The sequencer's timer ISR (it never fires on its own here: the timers are deferred),
        entered as the interrupt would be, at the rate the tempo gives: the frame's word 108 is
        BPM x 120, a sixteenth SEQ_ENTRIES_A_STEP entries, 1,500 periods a second"""
        bpm = struct.unpack(">H", self.read(CF_FRAME + 2 * 108, 2))[0] / 120.0
        if bpm <= 0:
            return
        self.seq_acc += SEQ_ENTRIES_A_STEP * (bpm / 15.0) / 1500.0
        uc, K, m = self.uc, self.K, self.machine
        while self.seq_acc >= 1.0:
            self.seq_acc -= 1.0
            saved = [uc.reg_read(r) for r in self.regs]
            pc0, sr0 = uc.reg_read(K.UC_M68K_REG_PC), uc.reg_read(K.UC_M68K_REG_SR)
            sp = STACK_TOP - 0x100
            m.write(sp, struct.pack(">HHI", 0x4000 | (SEQ_VECTOR << 2), 0x2000, SENTINEL))
            m.write(SENTINEL, bytes.fromhex("4e714e71"))
            uc.reg_write(K.UC_M68K_REG_A7, sp)
            bounded.run(uc, m.m, SEQ_ISR, SENTINEL, 3_000_000)
            for r, v in zip(self.regs, saved):
                uc.reg_write(r, v)
            uc.reg_write(K.UC_M68K_REG_PC, pc0)
            uc.reg_write(K.UC_M68K_REG_SR, sr0)
            m.pc = pc0

    def _shortcut_probe(self):
        """The one shortcut: the DSP's power-on RAM check (CMD_PROBE, sampler program.probe:
        PROBE_STEP words a block over 4 x 256 KB, about 1,000 blocks: hours here) is finished
        the moment it starts, with the verdict a whole part gives (pres 1), as if its blocks had
        run. Everything after it is the two sides' own. (probe() itself is held to its model
        by the SHARC runner's link part.)"""
        if self.shortcut_probe and self.dsp_word(self.SL_C["pres"]) == 3:
            self.dsp_poke(self.SL_C["pph"], 0)
            self.dsp_poke(self.SL_C["pres"], 1)
            self.probes_shortcut += 1

    def periods(self, n, ui=UI_SLICE, each=None, label=None, every=60.0):
        """N periods. With LABEL, a progress line at least every EVERY seconds of wall time:
        the phase, periods done of N, the audio time they make, the wall time, the measured
        throughput and the time left at it."""
        if label:
            self.phase = label
        t0, shown = time.perf_counter(), time.perf_counter()
        for k in range(n):
            if not self.period(ui):
                return False
            if each is not None:
                each(self)
            now = time.perf_counter()
            if label and (now - shown >= every or k == n - 1):
                shown = now
                rate = (k + 1) / (now - t0)
                print(f"  [{label}] {k + 1}/{n} periods, {(k + 1) / AUDIO_HZ * 1000:.1f} ms of audio "
                      f"(block {self.blocks}), {now - t0:.0f} s, {1 / rate:.1f} s a period, "
                      f"about {(n - k - 1) / rate / 60:.1f} min left ({self.timing})", flush=True)
        return True

    def set_timing(self, mode, calibrate=24):
        """"fast" or "faithful". Faithful: a frame is ISR_SHARE_STOPPED of the ISR's cost measured
        over CALIBRATE periods now (call it with the sequencer stopped and nothing recording,
        once; the frame stays fixed after, as the unit's clock does), the UI gets what the ISR
        leaves of it, and every timer counts that frame rate's instructions a second."""
        if mode == "faithful" and self.frame_units is None:
            self.timing = "fast"
            self.periods(calibrate, label="calibrating the frame")
            w = sorted(self.isr_units[-calibrate:])
            self.frame_units = w[len(w) // 2] / ISR_SHARE_STOPPED
        self.timing = mode
        if mode == "faithful":
            self._frame_t0 = None
            if self._clock not in self.panel.events:
                self.panel.events = tuple(self.panel.events) + (self._clock,)
        else:
            self.panel.events = tuple(e for e in self.panel.events if e is not self._clock)
        ips = (self.frame_units * AUDIO_HZ) if mode == "faithful" else None
        for src in getattr(self.panel.timers, "sources", (self.panel.timers,)):
            if not hasattr(src, "ips"):
                continue
            if not hasattr(src, "_ips_fast"):
                src._ips_fast = src.ips
            src.ips = ips if ips else src._ips_fast
        return self.frame_units

    def timing_report(self, n=AUDIO_HZ // 2):
        """N periods measured: the clocks against the audio (the 60 Hz tick, the frame counter,
        the timers' interrupts) and the UI's share that the idle task spent spinning"""
        from unicorn import UC_HOOK_CODE                     # noqa: PLC0415
        spins = {"n": 0}

        def on_spin(uc_, ad, sz, us):
            spins["n"] += 1
        h = self.uc.hook_add(UC_HOOK_CODE, on_spin, begin=IDLE_SPIN, end=IDLE_SPIN)
        t0, f0 = self.long(TICK), self.long(0x4058E8D4)
        fired0 = dict(self.panel.timers.fired)
        ui0, isr0 = self.ui_units, len(self.isr_units)
        self.periods(n, label=f"timing report ({self.timing})")
        self.uc.hook_del(h)
        per = getattr(getattr(self.machine.m, "_fast_stepper_obj", None), "per_block", 1.0)
        fired = {k: v - fired0.get(k, 0) for k, v in dict(self.panel.timers.fired).items()}
        isr = self.isr_units[isr0:]
        ui = self.ui_units - ui0
        out = {"mode": self.timing, "periods": n, "audio_s": n / AUDIO_HZ,
               "tick_60hz": self.long(TICK) - t0, "tick_want": round(60 * n / AUDIO_HZ, 1),
               "frames": self.long(0x4058E8D4) - f0, "timers_fired": fired,
               "isr_units_median": sorted(isr)[len(isr) // 2] if isr else None,
               "ui_units_a_period": ui / n, "frame_units": self.frame_units,
               "idle_spin_share_of_ui": (spins["n"] * per / ui) if ui else None}
        return out

    def watchdog(self, quiet=600.0):
        """A thread that says so when no period has completed for QUIET seconds (and after
        every further QUIET): the phase, the last block. It stops nothing."""
        import threading                                       # noqa: PLC0415

        def run():
            while True:
                time.sleep(30)
                idle = time.perf_counter() - self._last_done
                if idle >= quiet:
                    print(f"  WATCHDOG: no period completed for {idle:.0f} s (phase '{self.phase}', "
                          f"last block {self.blocks}, halt {self.halt})", flush=True)
                    self._last_done = time.perf_counter()
        threading.Thread(target=run, daemon=True).start()

    # -- the panel -------------------------------------------------------------------------
    def press(self, code):
        self.panel.panelin.press(self.machine, code) if hasattr(self.panel.panelin, "press") else None

    def faults(self):
        return getattr(self.machine.m, "faults", [])[self.faults0:]


def main() -> int:
    """a smoke run: N periods, the link's numbers"""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True, help="the build's .syx")
    p.add_argument("--stock", default=str(ROOT.parent / "Digitone_II_OS1.11.syx"))
    p.add_argument("--snapshot", default=str(ROOT.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"))
    p.add_argument("--periods", type=int, default=40)
    a = p.parse_args()
    c = Coupled(a.build, a.snapshot, a.stock, verbose=True)
    t0 = time.perf_counter()
    ok = c.periods(a.periods)
    print(f"  {c.blocks} periods in {time.perf_counter() - t0:.0f} s; halt: {c.halt}; packets to the DSP "
          f"{c.delivered}, from it {c.dsp_packets}; status {[hex(x) for x in c.last_status[:4]]}; "
          f"DSP instructions {c.dsp_instructions}; faults {len(c.faults())}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
