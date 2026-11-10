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

ISR, ISR_RTE = 0x40025E36, 0x40027BC6
CF_FRAME = 0x80005E60                   # the frame as the ColdFire builds it (16-bit BE)
CF_REPLY_TAIL = 0x80005E40              # the SPI reply's tail: the DSP's status, 16 BE halfwords
CF_TDM_TX, CF_TDM_RX = 0x4E6E0100, 0x4E6DF100
STACK_TOP, SENTINEL = 0x46A20000, 0x46A20400
UI_SLICE = 175_000                      # ColdFire instructions a period between ISRs (about the unit's)


class Coupled:
    def __init__(self, build_syx: str, snapshot: str, stock_syx: str, digikit_sharc: str | None = None,
                 png_dir: str | None = None, verbose: bool = False):
        self.verbose = verbose
        t0 = time.perf_counter()
        self._load_images(build_syx, stock_syx)
        self._cf_setup(snapshot, png_dir)
        self._dsp_setup(digikit_sharc)
        self.blocks = 0
        self.last_seq = {0: None, 1: None}
        self.delivered = 0
        self.dsp_packets = 0
        self.halt = None
        self.taps: dict = {}
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
        sp = STACK_TOP - 0x200
        m.write(sp, struct.pack(">I", SENTINEL) + b"".join(struct.pack(">I", x & 0xFFFFFFFF) for x in args))
        m.write(SENTINEL, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        stepper = getattr(m.m, "_fast_stepper_obj", None)
        if stepper is not None:
            stepper.left = 1 << 40
        try:
            uc.emu_start(fn, until if until is not None else SENTINEL, count=limit)
        finally:
            if stepper is not None:
                stepper.left = 0
        d0 = uc.reg_read(K.UC_M68K_REG_D0)
        pc = uc.reg_read(K.UC_M68K_REG_PC)
        for r, v in zip(self.regs, saved):
            uc.reg_write(r, v)
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
        self.panel.settle(ui)
        _, pc = self.call(ISR, until=ISR_RTE)
        if pc != ISR_RTE:
            self.halt = f"the ColdFire's ISR stopped at {pc:#x}"
            return False
        frame_be = self.read(CF_FRAME, 2688)
        frame = self.M.swap16(frame_be)
        packet = self._cf_packet()
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

        def after_smp(r):
            tx = SM.TDM_TX + (tap.get("pg", 0) << 11)
            tap["tx"] = [(M.m2.word(r.state, tx + 64 * frm + 56 + 4 * k) or 0) & 0xFFFFFFFF
                         for frm in range(32) for k in range(2)]
        hooks = {M.m3.DISPATCH: at_dispatch, M.dsp.PING_SW: after_smp}
        for k, fn in self.taps.items():
            hooks[k] = (lambda f0, f1: lambda r: (f0(r), f1(r, self)))(hooks[k], fn) if k in hooks \
                else (lambda f1: lambda r: f1(r, self))(fn)
        f = M.fixups(hooks)
        r = M.m4.unpack_call(self.dsp_state, frame)
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
        self.blocks += 1
        return True

    def periods(self, n, ui=UI_SLICE, each=None):
        for _ in range(n):
            if not self.period(ui):
                return False
            if each is not None:
                each(self)
        return True

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
