"""DSP-side mono return router, packaged in the native-return prototype.

Runs at the existing pre-filter insertion point. A negotiated configuration
must be published by the control bridge before this program can be enabled.
Layout addresses are supplied by the caller; this module reserves no live RAM.
The eight USB float planes and the native voice-pointer table are from the
stock 1.11 link/voice analysis. Their live block phase remains to be verified.
"""
from dataclasses import dataclass

from ..perc.dsl import Prog
from ..waverider.voice import TRACK_BUFFERS

BLOCK = 32
LANES = 8
VOICES = 16
USB_PLANES = 0x268638
MAGIC = 0x53435231
FRAME_TAG = 0x5300
FRAME_NATIVE = 0x80
FRAME_IDLE = 15
FRAME = 0x25C48C  # stock frame copy, shared by the existing custom machines


def _frame_half(p, dest, offset, index):
    # Read an aligned word and select its little-endian half. Keeping this
    # lightweight avoids importing any embedded engine's private ROM tables.
    p.iconst(12, FRAME + offset)
    p.iop(0, 12, "+", index)
    p.iconst(12, 2)
    p.iop(1, 12, "AND", 0)
    p.iconst(12, -4)
    p.iop(0, 12, "AND", 0)
    p.seti(1, 0)
    p.ldi(dest, 0, 1)
    p.ifz(1, "NE", lambda: p.lsh(dest, dest, -16))
    p.iconst(12, 0xFFFF)
    p.iop(dest, 12, "AND", dest)


@dataclass(frozen=True)
class Config:
    """40 bytes: enable magic, owned-voice mask, eight signed owner indices.

    Each lane owns one native voice (0..15), or -1 while idle. The mask must
    include all external voice slots that need clearing, including old owners.
    An invalid/unowned owner receives no audio. Duplicate owners are silenced.
    All eight USB lanes are consumed while enabled, even without any owner.
    Updates and rendering must not run concurrently.
    """
    base: int

    def __post_init__(self):
        if self.base < 0 or self.base % 4 or self.base + 40 > 0x100000000:
            raise ValueError("configuration must be an aligned 40-byte span")

    @property
    def enabled(self): return self.base

    @property
    def owned(self): return self.base + 4

    def owner(self, lane):
        if not 0 <= lane < LANES:
            raise ValueError("lane outside 0..7")
        return self.base + 8 + lane * 4


def route(p: Prog, cfg: Config) -> None:
    """Emit/run the bounded copy. M6=1; caller saves clobbered R/I registers.

    Integer copies preserve the source float bits. The source is the stock
    Q31-to-float USB conversion, not arbitrary plugin memory. No resampling,
    allocation, extra audio block, envelope, pan or gain is introduced here.
    """
    def enabled():
        p.ld(13, cfg.owned)
        p.iconst(15, 0)

        def voice():
            # Only external voice slots may be touched. Native voices keep their
            # oscillator output and are processed normally by the stock chain.
            p.lsh(0, 13, 31)

            def external():
                p.iconst(8, 0)  # number of USB lanes assigned to this voice
                for lane in range(LANES):
                    p.ld(0, cfg.owner(lane))

                    def match(lane=lane):
                        p.iconst(12, 1)
                        p.iop(8, 8, "+", 12)
                        p.iconst(9, USB_PLANES + BLOCK * 4 * lane)
                    p.if_(0, "EQ", 15, match, kind="i")

                p.lsh(0, 15, 2)
                p.iconst(12, TRACK_BUFFERS)
                p.iop(0, 12, "+", 0)
                p.seti(2, 0)
                p.ldi(0, 0, 2)
                p.seti(2, 0)
                p.iconst(12, 1)

                def copy():
                    p.seti(1, 9)
                    def sample():
                        p.ldpost(2, 1)
                        p.stpost(2, 2)
                    p.loop_r(14, BLOCK, sample)

                def silence():
                    p.iconst(2, 0)
                    p.loop_r(14, BLOCK, lambda: p.stpost(2, 2))
                p.if_(8, "EQ", 12, copy, silence, kind="i")

            p.ifz(0, "NE", external)
            p.lsh(13, 13, -1)
            p.iconst(12, 1)
            p.iop(15, 15, "+", 12)
        p.loop_r(11, VOICES, voice)

        # Remove the original main/FX bypass paths after copying. Leaving an
        # idle lane intact would leak buffered audio past the native envelope.
        p.iconst(9, USB_PLANES)
        p.seti(1, 9)
        p.iconst(2, 0)
        p.loop_r(14, BLOCK * LANES, lambda: p.stpost(1, 2))

    p.ld(0, cfg.enabled)
    p.iconst(12, MAGIC)
    p.if_(0, "EQ", 12, enabled, kind="i")


def assembly(cfg: Config) -> str:
    p = Prog(prefix="sc_return")
    p.raw(".SECTION/PM seg_pmco;")
    p.place("wr_sidecar_return")
    route(p, cfg)
    p.e("RTS;")
    return "\n".join(p.lines) + "\n"


def publish_frame(p: Prog, cfg: Config) -> None:
    """Publish owners from the already-unpacked native parameter frame.

    The CF bridge captures source parameters first, then replaces the external
    machine's unused slot 25 in this transient DSP frame with TAG|mode|lane.
    Saved sounds and the controls sent to the Pi are never changed. Type 21
    must map to the existing silent custom-machine slot in the DSP lookup.
    lane 15 marks an old/unowned allocated voice; 0..7 identifies its Pi part.
    With no external machines, retain the negotiated mode but clear all owners.
    A malformed/mixed descriptor consumes all USB lanes without routing audio.
    This executes once per block, before route(), with no concurrent publisher.
    """
    half = _frame_half
    from .machines import TYPE
    p.iconst(13, 0)  # current external-voice mask, never clear a reused internal voice
    p.iconst(14, 0)  # observed modes: legacy=1, native=2, malformed=4
    p.iconst(0, -1)
    for lane in range(LANES): p.st(cfg.owner(lane), 0)
    for v in range(VOICES):
        p.iconst(10, 2 * v)
        half(p, 2, 148, 10)
        p.iconst(12, TYPE)

        def external(v=v):
            p.iconst(12, 1 << v)
            p.iop(13, 13, "OR", 12)
            p.iconst(10, 146 * v)
            half(p, 2, 218, 10)
            p.iconst(12, 0xFF70)
            p.iop(3, 12, "AND", 2)
            p.iconst(12, FRAME_TAG)

            def invalid():
                p.iconst(12, 4)
                p.iop(14, 14, "OR", 12)

            def valid():
                p.iconst(12, FRAME_NATIVE)
                p.iop(3, 12, "AND", 2)
                def native():
                    p.iconst(12, 2)
                    p.iop(14, 14, "OR", 12)
                    p.iconst(12, 15)
                    p.iop(2, 12, "AND", 2)
                    p.iconst(12, LANES)
                    def assign():
                        p.lsh(2, 2, 2)
                        p.iconst(12, cfg.owner(0))
                        p.iop(2, 12, "+", 2)
                        p.seti(2, 2)
                        p.ldi(3, 0, 2)
                        p.iconst(12, -1)
                        p.if_(3, "EQ", 12, lambda: p.iconst(0, v),
                              lambda: p.iconst(0, -2), kind="i")
                        p.sti(0, 2, 0)  # duplicate lane fails closed
                    def idle():
                        p.iconst(12, FRAME_IDLE)
                        p.if_(2, "NE", 12, invalid, kind="i")
                    p.if_(2, "LT", 12, assign, idle, kind="i")
                def legacy():
                    p.iconst(12, 1)
                    p.iop(14, 14, "OR", 12)
                p.ifz(3, "NE", native, legacy)
            p.if_(3, "EQ", 12, valid, invalid, kind="i")
        p.if_(2, "EQ", 12, external, kind="i")
    p.st(cfg.owned, 13)
    def observed():
        p.iconst(12, 1)
        def legacy():
            p.iconst(0, 0)
            p.st(cfg.enabled, 0)
        def native_or_invalid():
            p.iconst(0, MAGIC)
            p.st(cfg.enabled, 0)
            p.iconst(12, 2)
            def invalid():
                p.iconst(0, -1)
                for lane in range(LANES): p.st(cfg.owner(lane), 0)
            p.if_(14, "NE", 12, invalid, kind="i")
        p.if_(14, "EQ", 12, legacy, native_or_invalid, kind="i")
    p.ifz(14, "NE", observed)


def frame_assembly(cfg: Config) -> str:
    p = Prog(prefix="sc_frame_return")
    p.raw(".SECTION/PM seg_pmco;")
    p.place("wr_sidecar_frame_return")
    publish_frame(p, cfg)
    route(p, cfg)
    p.e("RTS;")
    return "\n".join(p.lines) + "\n"
