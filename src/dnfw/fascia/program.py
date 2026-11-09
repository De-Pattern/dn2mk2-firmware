"""FASCIA's DSP program (machine type 18): `dnfw.fascia.live` on the SHARC, in PERC's
two-backend DSL (dnfw.perc.dsl): the same calls are the assembly text and, run in Python, its
exact model. The SHARC runner holds the assembled code to the run mode, and the run mode is
held to `live.py` bit for bit (test_fascia_program; the runner's `fascia` part holds the
assembled code to live.py directly).

**Where it runs.** A separate chained L2 program (fascia.asm, `wr_fsc`): smp.asm's tail jumps
here, and this jumps on to the shared tail at PING_SW (0x170280), which restores the registers
PERC saved. It walks the slots in PERC's voice order (the newest note first, perc.program
ORDER), and renders every slot whose frame type word is 18 under the frame guard
(perc.guard.around): a voice that does not fit in the frame's time is left out that block
(its buffer zeroed, its state kept) and, the second time in one note, stolen.

**The voice** is live.Voice, statement for statement: every float operation is the one
live.py makes, in its order (a sum over modes in mode order, from -0.0, which is exactly
numpy's add.accumulate). Integer arithmetic (the controls, expand, the counters, the
xorshift) is exact. The controls are read every block from the frame (the panel's 24 knobs,
`dnfw.fascia.machines`), the note from the note cell, the velocity from the frame's header
word 52 + 2t (the ColdFire's 0x8000dd40[t], the trig's velocity << 8: the frame builder's
`movew %a0@,%a3@(50)` at 0x40027510). A trig arms the voice (live.note_on), a sounding one
fades first (the steal), and the IDLE rule rests it.

**Memory.** Each slot's voice (VOICE_WORDS) in L2 at STATE + STRIDE t; the block's working
arrays and coefficients in L1 scratch (transient: written before read in every block, so the
voices share them); the tables in DDR (TABLE_*, `tables_bytes`, committed in tables.json so
the build needs no numpy). Every word of the state is written at the strike before it is
read; garbage (power-on memory) in the state is answered by the validity tests on the 'on',
'pending' and 'fading' words (exactly 1 or not), clamped loop counts and table indexes, and the
fault test (live: a non-finite or runaway state rests the voice).

**Subroutines.** Leaves (Prog.call: exp2, sinp, cosp, recip, rsqrt, tanh, the sine table,
frac, the xorshifts) take F15 and clobber only R12-R15, I1 and I12, so the expression
compiler's temporaries (R0-R11) live across them. Routines (`Rt`) may call leaves and other
routines (never themselves): each has its own return-address word in scratch.
"""

from __future__ import annotations

import json
import math
import pathlib
import struct

from ..perc.dsl import Prog, Mem, f32, bits, flt, s32, NOT, imm
from . import machines as FM

TABLES_JSON = pathlib.Path(__file__).with_name("tables.json")

# -- the panel -> its frame slots ----------------------------------------------------------
CONTROLS = FM.CONTROLS
TYPE = FM.TYPE
VEL_OFFSET = 52                                  # the frame's header word 52 + 2t: velocity << 8
NOTE_OFFSET = 2                                  # the frame's header word 2 + 2t: the trig's note << 8 | fine
NOTE_CELLS = 0x254B14
TRIG_WORD = 0x25C4AC
BUFFERS = 0x254A60
FRAME = 0x25C48C

# the model's names (dnfw.fascia.model, mirrored in machines; held equal by test_fascia_program)
TYPES = FM.TYPES                                 # STRIKE BLOW BOW DUST PULSE TZFM
BODIES = FM.BODIES                               # MEMB .. STRING, OFF
KINDS = BODIES[:-1]
CLICKS = ("SNAP", "TICK", "NOISE", "THUMP")
XMODS = ("EXCITE", "BEND", "CHOKE", "TRADE")
OFF = len(KINDS)                                 # BODB's OFF: 9
MODES, TWINS, NMAX = 16, 8, 24
BLOCK = 32
RATE = 48000.0
VARY_INTERNAL = 40                               # model.INTERNAL: VARY and FDBK are fixed
NEG0 = 0x80000000                                # -0.0: a sum's start (x + -0 = x for every x)


# -- layouts: named words -------------------------------------------------------------------
class St:
    """a record of words: name -> word offset (sub-records nest)"""

    def __init__(self):
        self.off: dict[str, int] = {}
        self.n = 0

    def w(self, *names, n: int = 1) -> "St":
        for name in names:
            assert name not in self.off, name
            self.off[name] = self.n
            self.n += n
        return self

    def sub(self, name: str, rec: "St") -> "St":
        self.off[name] = self.n
        self.n += rec.n
        return self

    def __getitem__(self, k):
        return self.off[k]


MODE = St().w("L", "aj", "offs", "mult", "y", "d", "drift", "s2", "sw", "og")
MW = MODE.n
BODY = St().w("kind", "n", "split", "spatial", "bias", "dsig", "peak", "level", "nfull", "ogok",
              "ogokp", "pad1")
BODY_MODES = BODY.n
BODY.n += NMAX * MW
TZR = ("mph", "cph", "ei", "eo", "ci", "fm", "d6", "ki", "ko")
GEN = St().w("kind", "s", "k", "pn", "pinv", "en", "ph", "pe", "ep", "burst", *TZR, "ca", "sm0", "sm1",
             "sm2", "sm3", "kn", "cn", "pd", "kd", "ga", "inc0", "dinc", "kep", "vel",
             "c_dec", "c_side", "c_utz", "c_udust", "c_DUST", "c_ubend", "f0", "tg")
EXC = St().w("kind", "driven", "done", "t", "n_end", "atk", "lag", "latok",
             "l_dec", "l_side", "l_utz", "l_udust", "l_DUST", "l_ubend", "l_f0",
             "am", "cS", "fm", "fm2", "a0", "b00", "b01", "b02", "a1", "b10", "b11", "b12",
             "oq", "hold", "sph", "grit", "breath", "np", "vel")
EXC.sub("G", GEN).sub("LG", GEN)
CLK = St().w("kind", "k", "len", "level", "n", "ninv", "gain", "inc", "ke", "kp", "pe", "prev", "ph", "e")
SHF = St().w("in1", "in2", "ph", "iprev").w("ay1", "ay2", "by1", "by2", n=4)
SVF1 = ("ic1", "ic2", "a1", "a2", "a3")
FORM = St().w("v", "w0", "wet", "wetok", "kk").w("s0", "s1", n=len(("ic1", "ic2", "a1", "a2", "a3")))
WBAND = St().w("aic1", "aic2", "aa1", "aa2", "aa3", "cic1", "cic2", "ca1", "ca2", "ca3", "e", "es", "use", "wk")
WAT = St().w("ss", "sw", "g", "gok", "amt", "amtok", "kf0", "kamt", "kok",
             "l1ic1", "l1ic2", "l1a1", "l1a2", "l1a3", "l2ic1", "l2ic2", "l2a1", "l2a2", "l2a3")
WAT.w("bands", n=6 * WBAND.n)
POST = ("ring", "shift", "form", "watr", "fold", "char", "vca")
VOICE = St().w("on", "pending", "fading", "pnote", "pvel", "note", "vel", "blocks", "rng",
               "cenv", "lenv", "menv", "venv", "rattle", "dc_x", "dc_y", "lim", "ring_ph", "morph",
               "ppok", "pp_l2", "pp_ge", "bratio", "ka", "kb", "clk", "sh_on", "fo_on", "wa_on",
               "seed", "magic")
VOICE.w("lv", n=7).w("par", n=7).w("parok", n=7).w("obp", n=BLOCK)
VOICE.sub("A", BODY).sub("B", BODY).sub("EA", EXC).sub("EB", EXC).sub("CK", CLK) \
    .sub("SH", SHF).sub("FO", FORM).sub("WA", WAT)
VOICE_WORDS = VOICE.n
STRIDE = 0xF80                                   # 3,968 bytes a slot: 4096 - 128 (shifts, no multiply)
assert 4 * VOICE_WORDS <= STRIDE, VOICE_WORDS

# the block's scratch (L1, transient): arrays of 32, the modes' coefficients, the words
ARRAYS = ("X", "Z", "W", "XB", "RJ", "E", "OA", "BZ", "Y", "P1", "OB", "P0", "D0", "D1")
TMODE = ("m", "k", "b", "phi", "ogp")
TW = len(TMODE)
SC_WORDS = (
    # the slot, its pointers, the routines' return words
    "t", "k146", "vbase", "idx", "tmp0", "tmp1", "tmp2", "tmp3", "tmp4", "tmp5", "tmp6",
    "cnt0", "cnt1", "cnt2", "cnt3", "trig",
    # the panel (24) and the engine (32)
    *[f"P_{c}" for c in CONTROLS],
    "Q_TYPA", "Q_TYPB", "Q_HARD", "Q_DUST", "Q_TZFM", "Q_BEND", "Q_MIX", "Q_DEC", "Q_BODA", "Q_BODB",
    "Q_TUNE", "Q_GEOM", "Q_MATL", "Q_POS", "Q_COUP", "Q_DAMP", "Q_MORPH", "Q_FORM", "Q_SHIFT",
    "Q_RING", "Q_SIDE", "Q_FOLD", "Q_LPG", "Q_CHAR", "Q_ATK", "Q_CLIK", "Q_CTYP", "Q_XMOD",
    "Q_BUZZ", "Q_WATR",
    # block_controls
    "c_hard", "c_uhard", "c_tilt", "c_geom_e", "c_inv_t60", "c_matl", "c_pos", "c_bend", "c_ubend",
    "c_chirp", "c_lpg", "c_ulpg", "c_coup", "c_xmod", "c_buzz", "c_morph", "c_ga", "c_gb", "c_dec",
    "c_udust", "c_utz", "c_side", "c_uring", "c_uwatr", "c_ufold", "c_uchar",
    # the block
    "f0", "l2f0", "hasx", "excdone", "ch", "bend", "loss", "back", "retune", "mexp", "ramp",
    "fcount", "drv", "hasxb", "bzon", "invtb", "bb", "first", "kv", "lv0", "lv1", "pon",
    "p0", "pmove", "jj", "g", "sel", "best", "bests", "nn", "x1", "y1", "pk", "ended",
    "S", "Wsum", "gn", "mt", "a1", "a2", "omt", "lpos", "ltilt", "lf0",
    "linv", "ramp_og", "tanh_x", "tanh_n", "gauss_a", "fa", "fb",
    "vv", "ws", "w0", "w1", "dw", "jj1", "sk", "pcur", "svr", "sx", "sv1", "sv2", "sfc", "skk", "fa_s", "fa_g", "fb_s", "fb_g", "dmax", "ymax", "q0", "q1", "q2", "q3", "q4", "q5", "q6", "q7",
    "q8", "q9", "u0", "u1", "u2",
    # routines' return words (Rt)
    )


# the scratch words most used (counted in fascia.asm, 2026-11-08), first: within -64..63 words of
# I5 (the scratch's base + 64 words) a word is DM(k, I5) in a 32-bit instruction, else 48
HOT_WORDS = ('cnt3', 'tmp0', 'u1', 'idx', 'u0', 'u2', 'tmp3', 'tmp1', 'vbase', 'w1', 'tmp2', 'tmp4', 'cnt0', 'cnt2', 'bests', 'tmp5', 'jj', 'pcur', 'pon', 'pmove', 'sfc', 'cnt1', 'w0', 'tmp6', 'pk', 'lv0', 'f0', 'q5', 'svr', 'q0', 'q3', 'dmax', 'ymax', 'q4', 'lv1', 'p0', 'q1', 'y1', 'q8', 'q9', 'skk', 'q6', 't', 'best', 'ended', 'q2', 'c_coup', 'ws', 'omt', 'fa', 'x1', 'q7', 'ramp', 'lf0', 'lpos', 'fb', 'c_hard', 'dw', 'g', 'vv', 'c_inv_t60', 'hasx', 'c_xmod', 'c_udust', 'first', 'sx', 'Q_DUST', 'l2f0', 'fcount', 'Wsum', 'nn', 'Q_HARD', 'linv', 'c_pos', 'c_ga', 'c_gb', 'c_geom_e', 'mexp', 'hasxb', 'bzon', 'c_dec', 'sv1', 'Q_LPG', 'Q_ATK', 'Q_CLIK', 'Q_RING', 'Q_FORM', 'Q_WATR', 'Q_FOLD', 'ltilt', 'back', 'retune', 'ramp_og', 'drv', 'c_buzz', 'invtb', 'bb', 'c_ubend', 'c_utz', 'c_side', 'mt', 'a1', 'a2', 'S', 'fa_g', 'fb_g', 'gauss_a', 'Q_BEND', 'Q_SHIFT', 'Q_TZFM', 'Q_CTYP', 'Q_XMOD', 'Q_COUP', 'Q_CHAR', 'c_tilt', 'ch')
# the constants most loaded (48-bit immediates), in the window too: filled at FASCIA's entry (and by
# run_voice for the model); JBASE, TBASE: the jloop's I4 base and the modes' coefficients
POOL = (1065353216, 'JBASE', 1056964608, 2147483647, 1006699012, 'TBASE', 1132462080, 1073741824, 934200126, 3086754069, 1048576000, 1082130432)
WIN = 64                                   # words: I5 = scratch + 4 WIN; I4 (a jloop) = the arrays + 4 (j + WIN)


def _sc_order() -> list[str]:
    pool = [f"k{i}" for i in range(len(POOL))]
    hot = [w for w in HOT_WORDS if w in SC_WORDS][:2 * WIN - len(pool)]
    return hot + pool + [w for w in SC_WORDS if w not in hot and w not in pool]


class Layout:
    """where the build puts FASCIA (dnfw.waverider.dsp provides the addresses)"""

    def __init__(self, state: int, scratch: int, tables: int, sin: int, order: int, order_i: int,
                 cost: int, strikes: int, stolen: int, state2: int | None = None):
        """STATE: slots 0..7 (STRIDE each), STATE2: slots 8..15 (default: after them)"""
        self.state, self.scratch, self.tables, self.sin = state, scratch, tables, sin
        self.state2 = state + 8 * STRIDE if state2 is None else state2
        self.order, self.order_i, self.cost, self.strikes, self.stolen = order, order_i, cost, strikes, stolen
        self.rets = stolen + 0x40                # the routines' return words (32), after the steals
        at = scratch
        self.C = {}
        for name in _sc_order():                 # the words, the most used first (HOT_WORDS)
            self.C[name] = at
            at += 4
        self.arrays = at
        self.A = {}
        for name in ARRAYS:                      # the arrays, the most used first
            self.A[name] = at
            at += 4 * BLOCK
        self.T = at                              # NMAX x TW words: m k b phi ogp
        at += 4 * NMAX * TW
        self.scratch_end = at
        self.base5 = scratch + 4 * WIN           # I5 in a voice
        sym = {"JBASE": self.arrays + 4 * WIN, "TBASE": self.T}
        self.pool = {self.C[f"k{i}"]: (sym[k] if isinstance(k, str) else k) & 0xFFFFFFFF
                     for i, k in enumerate(POOL)}
        self.TB = {name: tables + 4 * off for name, (off, _n) in TABLE_AT.items()}


# -- tables (DDR) ---------------------------------------------------------------------------
TABLE_SPEC = (("LOG2R", 9 * MODES), ("JSV", MODES), ("KIND", 9 * len(("spatial", "split", "beat", "bias", "bratio"))),
              ("A2", 4), ("B2", 4), ("VOW", 10), ("TG", 6), ("WK", 6), ("SLOT", 24))
TABLE_AT = {}
_o = 0
for _n, _k in TABLE_SPEC:
    TABLE_AT[_n] = (_o, _k)
    _o += _k
TABLE_WORDS = _o
KIND_FIELDS = ("spatial", "split", "beat", "bias", "bratio")


def table_values() -> dict[str, list[float]]:
    """every table, as live.py computes it (float32): numpy here, never in the build"""
    import numpy as np
    from . import live as LV
    from . import model as MD
    F = np.float32
    out = {}
    out["LOG2R"] = [float(x) for k in KINDS for x in LV.LOG2R[k]]
    vary = LV.u(VARY_INTERNAL) * F(3.2)
    js = np.array([math.sqrt(3.0) * 0.0012 * (1.0 + 0.15 * k) for k in range(MODES)], F) * F(vary)
    out["JSV"] = [float(x) for x in js]
    kt = []
    for k in KINDS:
        split = MD.SPLIT[k]
        kt += [float(F(MD.SPATIAL[k])), float(F(split)), float(F(MD.BEAT_MAX[k])), float(F(MD.RING_BIAS[k])),
               float(F(MD.B_RATIO.get(k, 1.0)))]
    out["KIND"] = kt
    A2, B2 = LV._shift_coeffs()
    out["A2"], out["B2"] = [float(x) for x in A2], [float(x) for x in B2]
    out["VOW"] = [float(x) for row in LV.VOWELS for x in row]
    out["TG"] = [float(LV.TG[t]) for t in TYPES]
    out["WK"] = [float(F(k / 7.0)) for k in LV.WATER_USE]
    # the panel's frame words (offset 168 + 2 slot) and their tops, ints
    out["SLOT"] = [(FRAME + 168 + 2 * FM.SLOTS[c][1]) | FM.SLOTS[c][3] << 24 for c in CONTROLS]   # address | top << 24
    return out


def tables_bytes() -> bytes:
    """the DDR tables, from the committed tables.json (no numpy: the build reads this)"""
    spec = json.loads(TABLES_JSON.read_text(encoding="utf-8"))
    words = []
    for name, n in TABLE_SPEC:
        vals = spec[name]
        assert len(vals) == n, name
        words += [int(v, 16) for v in vals]
    return struct.pack(f"<{len(words)}I", *words)


def write_tables_json() -> dict:
    vals = table_values()
    spec = {"note": "generated by scripts/gen_fascia_asm.py from dnfw.fascia.live; do not edit"}
    for name, n in TABLE_SPEC:
        assert len(vals[name]) == n, name
        spec[name] = [f"{v & 0xFFFFFFFF:08x}" if isinstance(v, int) else f"{bits(f32(v)):08x}"
                      for v in vals[name]]
    TABLES_JSON.write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8", newline="\n")
    return spec


# -- the live.py constants, float32 ----------------------------------------------------------
def _consts() -> dict:
    """live.py's constants (numpy at generation and in run mode; the values are float32)"""
    import numpy as np
    from . import live as LV
    from . import model as MD
    F = np.float32
    c = {
        "INV127": LV.INV127, "INVR": LV.INVR, "LOG2E": LV.LOG2E, "C_DECAY": LV.C_DECAY,
        "F_HI": LV.F_HI, "F_LO": LV.F_LO, "H_SCALE": LV.H_SCALE, "OUT": LV.OUT, "IDLE": LV.IDLE,
        "FLOOR": F(LV.FLOOR), "SQ15": LV._SQ15, "TANH_TOP": LV.TANH_TOP, "K_RAMP": LV.K_RAMP,
        "K_PE": LV.K_PE, "BOW_LO": LV.BOW_LO, "BOW_HI": LV.BOW_HI, "LIM_TH": LV.LIM_TH,
        "LIM_KR": LV.LIM_KR, "DC_A": LV.DC_A, "K_CHIRP": LV.K_CHIRP, "SQ2": LV.SQ2,
        "LOG2_440": F(LV.LOG2_440), "FADE_STEP": LV.FADE_STEP,
        "KA1": LV.Water.KA1, "KR1": LV.Water.KR1, "KA2": LV.Water.KA2, "KR2": LV.Water.KR2,
        "GMAX": LV.Water.GMAX,
        "PI2": F(math.pi / 2), "L400": F(math.log2(400.0)), "I003": F(1.0 / 0.03),
        "L0125": F(math.log2(0.0125)), "L30": F(math.log2(30.0)),
        "BLOW_A": F(-2.0 * math.pi / math.log(2.0) / RATE), "I2PI": F(1.0 / (2.0 * math.pi)),
        "KH_BOW": F(math.exp(-1.0 / (0.08 * RATE))), "KH_BLOW": F(math.exp(-1.0 / (0.06 * RATE))),
        "KP_THUMP": F(math.exp(-1.0 / (0.008 * RATE))), "W_SPAN": F(math.log2(9000.0 / 2.2)),
        "SQH": F(math.sqrt(0.5)), "OUT4": F(4.0 / MD.OUT), "I15": F(1.0 / 1.5),
        "FOLDK": F(1.0 / (2 * math.pi)), "HANN": F(LV.HANN_VAR),
    }
    vary = LV.u(VARY_INTERNAL) * F(3.2)
    c["CAJ"] = F(F(0.10) * F(vary)) * LV.LOG2E
    c["DSIG"] = F(math.sqrt(3.0) * 1.5e-5) * F(vary)
    for k in range(7):
        c[f"WK{k}"] = F(k / 7.0)
    for k, (n, lo, hi) in {"DEC": (0, 0.004, 2.0), "ATK": (0, 0.0002, 0.5), "DDUST": (0, 5.0, 3000.0),
                           "BDUST": (0, 20.0, 4000.0)}.items():
        c[f"EM_{k}"] = (F(lo), F(math.log2(hi / lo)))
    c["ONEP1"] = F(-1 * (1.0 / math.log(2.0)) / RATE)            # onepole_inv(x, 1)
    c["ONEPB"] = F(-BLOCK * (1.0 / math.log(2.0)) / RATE)        # onepole_inv(x, BLOCK)
    c["EXP2_C"], c["SIN_C"], c["COS_C"] = LV.EXP2_C, LV.SIN_C, LV.COS_C
    c["EXPM1_C"], c["TANH_N"], c["TANH_D"] = LV.EXPM1_C, LV.TANH_N, LV.TANH_D
    c["SIN_TOP"] = LV._TOP
    for k, q in (("FORM", 8.0), ("LP", math.sqrt(0.5)), ("AN", 3.0), ("CAR", 14.0)):
        c[f"KK_{k}"] = F(1.0) * LV.recip(F(q))          # live.SVF.set's kk for a scalar q
    return c


_C = None


def K_() -> dict:
    global _C
    if _C is None:
        _C = _consts()
    return _C


def kf(name) -> float:
    return float(K_()[name])


# -- expressions --------------------------------------------------------------------------
class E:
    def __add__(self, o):
        return Op("+", self, w(o))

    def __radd__(self, o):
        return Op("+", w(o), self)

    def __sub__(self, o):
        return Op("-", self, w(o))

    def __rsub__(self, o):
        return Op("-", w(o), self)

    def __mul__(self, o):
        return Op("*", self, w(o))

    def __rmul__(self, o):
        return Op("*", w(o), self)

    def __neg__(self):
        return Op("*", self, Kc(-1.0))

    def depth(self) -> int:
        return 1


class Kc(E):
    def __init__(self, v):
        self.v = f32(float(v))


class Mv(E):
    """a memory word: ('a', byte address) or ('i', I register, word offset)"""

    def __init__(self, kind, a, off=0, isint=False):
        self.kind, self.a, self.off, self.isint = kind, a, off, isint


class Op(E):
    def __init__(self, op, a, b):
        self.op, self.a, self.b = op, a, b
        self._d = None

    def depth(self) -> int:
        if self._d is None:
            da, db = self.a.depth(), self.b.depth()
            self._d = max(da, db + 1) if da >= db else max(db, da + 1)
        return self._d


class Fn(E):
    def __init__(self, name, a):
        self.name, self.a = name, w(a)

    def depth(self) -> int:
        return self.a.depth()


class Un(E):
    """abs (the sign bit cleared), a float of an int register expression, etc."""

    def __init__(self, kind, a):
        self.kind, self.a = kind, w(a)

    def depth(self) -> int:
        return self.a.depth() + 1


def w(x) -> E:
    return x if isinstance(x, E) else Kc(x)


def _calls(e: E) -> bool:
    if isinstance(e, Fn):
        return True
    if isinstance(e, Op):
        return _calls(e.a) or _calls(e.b)
    if isinstance(e, Un):
        return _calls(e.a)
    return False


def mn(a, b) -> E:
    return Op("MIN", w(a), w(b))


def mx(a, b) -> E:
    return Op("MAX", w(a), w(b))


def ab(a) -> E:
    return Un("abs", a)


def fi(a) -> E:
    """an integer word as a float (FLOAT R BY 0)"""
    return Un("float", a)


class FProg(Prog):
    """PERC's Prog with two size forms (v0.45, the DSP's 1 MiB upload buffer): a constant 0 is
    `Rd = Rd - Rd`, and while `scr` is set (inside a voice, I5 = the scratch's base) a scratch
    word is DM(k, I5), pre-modified, instead of an absolute address"""

    scr: tuple[int, int, int] | None = None
    scr_on = False

    pool: dict[int, int] = {}                 # value -> its word's address (Layout.pool)

    def _const(self, d: int, v: int, note: str) -> None:
        if self.scr_on and v in self.pool and self.known.get(d) != v:
            self.ldi(d, (self.pool[v] - self.scr[2]) // 4, 5, note or "the pool")
            if not self.run:
                self.known[d] = v
            return
        if v == 0:
            if self.run:
                self.steps += 1
                self.r[d] = 0
                return
            if self.known.get(d) == 0:
                return
            self.e(f"R{d} = R{d} - R{d};", note or "0")
            self.known[d] = 0
            return
        super()._const(d, v, note)

    def _rel(self, addr: int):
        """scr = (from, to, I5's value): a word in from..to is DM((addr - I5) / 4, I5)"""
        if self.scr_on and self.scr and self.scr[0] <= (addr & 0xFFFFFFFF) < self.scr[1]:
            return ((addr & 0xFFFFFFFF) - self.scr[2]) // 4
        return None

    def ld(self, d: int, addr: int, note: str = "") -> None:
        k = self._rel(addr)
        if k is None:
            return super().ld(d, addr, note)
        self.ldi(d, k, 5, note)

    def st(self, addr: int, s: int, note: str = "") -> None:
        k = self._rel(addr)
        if k is None:
            return super().st(addr, s, note)
        self.sti(k, 5, s, note)


class Gen:
    """the code generator: a Prog, the layout, and the routines"""

    def __init__(self, p: Prog, L: Layout):
        self.p, self.L = p, L
        self.rts: dict[str, object] = {}
        self.rt_ret: dict[str, int] = {}
        self.rt_done: set[str] = set()

    # -- memory words ---------------------------------------------------------------------
    def c(self, name) -> Mv:
        return Mv("a", self.L.C[name])

    def ci(self, name) -> Mv:
        return Mv("a", self.L.C[name], isint=True)

    def a(self, arr, j) -> Mv:
        return Mv("a", self.L.A[arr] + 4 * j)

    def v(self, name, base=2, rec=VOICE, at=0) -> Mv:
        return Mv("i", base, at + rec[name])

    # -- evaluation -------------------------------------------------------------------------
    def ld(self, d: int, m: Mv) -> None:
        p = self.p
        if not p.run and p.lines:
            # a load of the word just stored from the same register: it holds it already
            # (emit only: the run mode loads it, which changes nothing)
            if m.kind == "a":
                k = p._rel(m.a) if isinstance(p, FProg) else None
                st = f"DM({imm(m.a)}) = R{d};" if k is None else f"DM({k}, I5) = R{d};"
            else:
                st = f"DM({m.off}, I{m.a}) = R{d};"
            if p.lines[-1].strip().startswith(st):
                return
        if m.kind == "a":
            p.ld(d, m.a)
        else:
            p.ldi(d, m.off, m.a)

    def st(self, m: Mv, s: int) -> None:
        if m.kind == "a":
            self.p.st(m.a, s)
        else:
            self.p.sti(m.off, m.a, s)

    def ev(self, e: E, r: int = 0) -> int:
        """the value of E in Fr (R0..R11 are the stack, r and up are free)"""
        p = self.p
        assert r <= 11, "expression too deep"
        if isinstance(e, Kc):
            p.fconst(r, e.v)
        elif isinstance(e, Mv):
            self.ld(r, e)
        elif isinstance(e, Op):
            a, b = e.a, e.b
            if _calls(b) and not _calls(a):
                # the side with a call first, at the lower register (a leaf at r = 0 needs no
                # moves): the order of two side-effect-free operands changes nothing
                self.ev(b, r)
                self.ev(a, r + 1)
                p.fop(r, r + 1, e.op, r)
            elif isinstance(b, (Kc, Mv)):
                self.ev(a, r)
                self.ev(b, r + 1)
                p.fop(r, r, e.op, r + 1)
            elif isinstance(a, (Kc, Mv)) or b.depth() > a.depth():
                self.ev(b, r)
                self.ev(a, r + 1)
                p.fop(r, r + 1, e.op, r)
            else:
                self.ev(a, r)
                self.ev(b, r + 1)
                p.fop(r, r, e.op, r + 1)
        elif isinstance(e, Fn):
            if e.name[1:] not in ("bi", "u01", "gauss"):     # the generators take nothing
                self.ev(e.a, r)
            if e.name == "sqrt":
                self._sqrt(r)
            else:
                self.call_at(e.name, r)
        elif isinstance(e, Un):
            self.ev(e.a, r)
            if e.kind == "abs":
                p.iconst(r + 1, 0x7FFFFFFF)
                p.iop(r, r, "AND", r + 1)
            elif e.kind == "float":
                p.iconst(12, 0)
                p.float_(r, r, 12)
            else:
                raise ValueError(e.kind)
        else:
            raise TypeError(e)
        return r

    def call_at(self, name: str, r: int) -> None:
        """Fr = leaf NAME(Fr): the leaves take and give F0, so at r > 0 F0 is kept in F(r+1)"""
        p = self.p
        if r == 0:
            LEAF[name](self)
            return
        assert r + 1 <= 11
        p.fpass(r + 1, 0)
        p.fpass(0, r)
        LEAF[name](self)
        p.fpass(r, 0)
        p.fpass(0, r + 1)

    def _sqrt(self, r: int) -> None:
        """live.sqrt: x > 0: x rsqrt(max(x, 1e-30)), else 0"""
        p = self.p
        p.fconst(r + 1, 0.0)

        def pos():
            p.fconst(r + 1, 1e-30)
            p.fop(r + 1, r, "MAX", r + 1)
            self.call_at("rsqrt", r + 1)
            p.fop(r, r, "*", r + 1)
        p.if_(r, "GT", r + 1, pos, lambda: p.fconst(r, 0.0))

    def set(self, m: Mv, e) -> None:
        r = self.ev(w(e), 0)
        self.st(m, r)

    def iset(self, m: Mv, v: int) -> None:
        self.p.iconst(0, v)
        self.st(m, 0)

    def fz(self, m: Mv) -> None:
        self.p.fconst(0, 0.0)
        self.st(m, 0)

    def cmp(self, a, cond: str, b, then, else_=None) -> None:
        """if (a COND b) [floats]"""
        self.ev(w(a), 0)
        self.ev(w(b), 1)
        if then is None:
            cond, then, else_ = NOT[cond], else_, None
        self.p.if_(0, cond, 1, then, else_)

    def icmp(self, m: Mv, cond: str, v: int, then, else_=None) -> None:
        """if (int word COND v)"""
        self.ld(0, m)
        if then is None:
            cond, then, else_ = NOT[cond], else_, None
        if v == 0:
            self.p.ifz(0, cond, then, else_)
            return
        self.p.iconst(1, v)
        self.p.if_(0, cond, 1, then, else_, kind="i")

    def iflag(self, m: Mv, then, else_=None) -> None:
        """if (word != 0): the flags are 0 or 1 (the life words are made so first)"""
        self.ld(0, m)
        if then is None:
            self.p.ifz(0, "EQ", else_)
        else:
            self.p.ifz(0, "NE", then, else_)

    # -- routines ---------------------------------------------------------------------------
    def rt(self, name: str, body) -> None:
        """call routine NAME (its own return word; may call leaves and other routines)"""
        p = self.p
        if p.run:
            body()
            return
        if name not in self.rts:
            self.rts[name] = body
            assert len(self.rt_ret) < 32
            self.rt_ret[name] = self.L.rets + 4 * len(self.rt_ret)
        ret = p.label("rret")
        p.known.clear()
        p.lines.append("      I12 = 0x0;".ljust(40) + f"// return address - 1: {ret}. - 1")
        p.jump("", f"wr_{p.prefix}_rt_{name}")
        p.place(ret)

    def emit_rts(self) -> None:
        p = self.p
        while True:
            todo = [n for n in self.rts if n not in self.rt_done]
            if not todo:
                break
            for name in todo:
                self.rt_done.add(name)
                p.place(f"wr_{p.prefix}_rt_{name}")
                # the return address, kept from the leaves' (which use I12) in its own word
                p.e(f"DM({imm(self.rt_ret[name])}) = I12;")
                self.rts[name]()
                p.e(f"I12 = DM({imm(self.rt_ret[name])});")
                p.e("JUMP (M14, I12);")


# -- leaves: F0 in, F0 out (F15 inside); clobber R12-R15, I1, I12 only ----------------------
def _leaf(p: Prog, name: str, body) -> None:
    """call leaf NAME: `I12 = return - 1; JUMP`; the leaf moves F0 to F15, runs BODY, gives F15
    back in F0 and returns by JUMP (M14, I12) (Prog.emit_subs)"""
    def full():
        p.fpass(15, 0)
        body()
        p.fpass(0, 15)
    if p.run:
        p.in_sub = True
        full()
        p.in_sub = False
        return
    p.subs.setdefault(name, full)
    ret = p.label("ret")
    p.known.clear()
    p.lines.append("      I12 = 0x0;".ljust(40) + f"// return address - 1: {ret}. - 1")
    p.jump("", f"wr_{p.prefix}_sub_{name}")
    p.place(ret)
def _horner(p: Prog, acc: int, x: int, cs, k: int = 12) -> None:
    """acc = poly(x), Horner from the highest coefficient (live: p = c[-1]; p = p x + c)"""
    p.fconst(acc, cs[-1])
    for c in cs[-2::-1]:
        p.fop(acc, acc, "*", x)
        p.fconst(k, c)
        p.fop(acc, acc, "+", k)


def _exp2(g: Gen) -> None:
    p = g.p

    def body():
        p.fconst(12, -100.0)
        p.fop(15, 15, "MAX", 12)
        p.fconst(12, 100.0)
        p.fop(15, 15, "MIN", 12)
        _floor(p, 13, 14)                       # R13 = floor (int), F14 = it as a float
        p.fop(15, 15, "-", 14)                  # f
        _horner(p, 14, 15, K_()["EXP2_C"])
        p.iconst(12, 1)
        p.float_(15, 12, 13)                    # 2^i
        p.fop(15, 14, "*", 15)
    _leaf(p, "exp2", body)


def _floor(p: Prog, ri: int, fr: int) -> None:
    """Ri = floor(F15) as an integer, Ffr = it as a float (TRUNC, and one less below zero).
    Uses R12."""
    p.trunc(ri, 15)
    p.iconst(12, 0)
    p.float_(fr, ri, 12)

    def down():
        p.fconst(12, 1.0)
        p.fop(fr, fr, "-", 12)
        p.iconst(12, 1)
        p.iop(ri, ri, "-", 12)
    p.if_(15, "LT", fr, down)


def _sinp(g: Gen) -> None:
    p = g.p

    def body():
        p.fop(14, 15, "*", 15)
        _horner(p, 13, 14, K_()["SIN_C"])
        p.fop(15, 13, "*", 15)
    _leaf(p, "sinp", body)


def _cosp(g: Gen) -> None:
    p = g.p

    def body():
        p.fop(14, 15, "*", 15)
        _horner(p, 15, 14, K_()["COS_C"])
    _leaf(p, "cosp", body)


def _expm1(g: Gen) -> None:
    p = g.p

    def body():
        _horner(p, 14, 15, K_()["EXPM1_C"])
        p.fop(15, 14, "*", 15)
    _leaf(p, "expm1", body)


def _recip_body(p: Prog, x: int, r: int, t: int) -> None:
    """Fr = 1/Fx: the seed 0x7ef311c7 - bits, r = r (2 - x r) three times. Uses R12."""
    p.iconst(12, 0x7EF311C7)
    p.iop(r, 12, "-", x)
    for _ in range(3):
        p.fop(t, x, "*", r)
        p.fconst(12, 2.0)
        p.fop(t, 12, "-", t)
        p.fop(r, r, "*", t)


def _recip(g: Gen) -> None:
    p = g.p

    def body():
        _recip_body(p, 15, 14, 13)
        p.fpass(15, 14)
    _leaf(p, "recip", body)


def _rsqrt(g: Gen) -> None:
    p = g.p

    def body():
        p.lsh(14, 15, -1)
        p.iconst(12, 0x5F3759DF)
        p.iop(14, 12, "-", 14)
        p.fconst(12, 0.5)
        p.fop(13, 15, "*", 12)                  # hx
        for _ in range(3):
            p.fop(15, 14, "*", 14)
            p.fop(15, 15, "*", 13)
            p.fconst(12, 1.5)
            p.fop(15, 12, "-", 15)
            p.fop(14, 14, "*", 15)
        p.fpass(15, 14)
    _leaf(p, "rsqrt", body)


def _tanh(g: Gen) -> None:
    p, C = g.p, g.L.C

    def body():
        top = kf("TANH_TOP")
        p.fconst(12, -top)
        p.fop(15, 15, "MAX", 12)
        p.fconst(12, top)
        p.fop(15, 15, "MIN", 12)
        p.st(C["tanh_x"], 15)
        p.fop(14, 15, "*", 15)                  # x2
        _horner(p, 13, 14, K_()["TANH_N"])
        p.ld(15, C["tanh_x"])
        p.fop(13, 15, "*", 13)                  # x n
        p.st(C["tanh_n"], 13)
        _horner(p, 15, 14, K_()["TANH_D"])      # d (F15)
        _recip_body(p, 15, 14, 13)              # F14 = 1/d
        p.ld(15, C["tanh_n"])
        p.fop(15, 15, "*", 14)
    _leaf(p, "tanh", body)


def _tab(g: Gen) -> None:
    """the sine table at index F15 (clamped to 0..TOP), linear"""
    p, L = g.p, g.L

    def body():
        p.fconst(12, 0.0)
        p.fop(15, 15, "MAX", 12)
        p.fconst(12, kf("SIN_TOP"))
        p.fop(15, 15, "MIN", 12)
        p.trunc(14, 15)
        p.iconst(12, 0)
        p.iop(14, 14, "MAX", 12)
        p.iconst(12, int(kf("SIN_TOP")))
        p.iop(14, 14, "MIN", 12)
        p.iconst(12, 0)
        p.float_(13, 14, 12)
        p.fop(15, 15, "-", 13)                  # f
        p.lsh(14, 14, 2)
        p.iconst(12, L.sin)
        p.iop(14, 12, "+", 14)
        p.seti(1, 14)
        p.ldi(13, 0, 1)                         # a
        p.ldi(12, 1, 1)                         # b
        p.fop(12, 12, "-", 13)
        p.fop(12, 15, "*", 12)
        p.fop(15, 13, "+", 12)
    _leaf(p, "tab", body)


def _fl(g: Gen) -> None:
    """live._fl: |x| < FLOOR -> +0, else x"""
    p = g.p

    def body():
        p.iconst(14, 0x7FFFFFFF)
        p.iop(13, 15, "AND", 14)
        p.fconst(14, kf("FLOOR"))

        def zero():
            p.fconst(15, 0.0)
        p.if_(13, "LT", 14, zero)
    _leaf(p, "fl", body)


def _frac(g: Gen) -> None:
    p = g.p

    def body():
        _floor(p, 13, 14)
        p.fop(15, 15, "-", 14)
    _leaf(p, "frac", body)


def _xs_body(p: Prog, ireg: int, off: int) -> None:
    """R15 = the next xorshift32 of the word DM(off, Ireg) (13, 17, 5), stored back.
    Uses R13, R14."""
    p.ldi(15, off, ireg)
    for sh in (13, -17, 5):
        p.lsh(14, 15, sh)
        p.iop(13, 15, "AND", 14)
        p.iop(15, 15, "OR", 14)
        p.iop(15, 15, "-", 13)
    p.sti(off, ireg, 15)


def _xs_leaf(name: str, ireg: int, off: int, kind: str):
    def leaf(g: Gen) -> None:
        p, C = g.p, g.L.C

        def bi():
            _xs_body(p, ireg, off)
            p.iconst(12, -31)
            p.float_(15, 15, 12)

        def body():
            if kind == "bi":
                bi()
            elif kind == "u01":
                _xs_body(p, ireg, off)
                p.lsh(15, 15, -8)
                p.iconst(12, -24)
                p.float_(15, 15, 12)
            else:                               # gauss: (bi + bi) sqrt 1.5
                bi()
                p.st(C["gauss_a"], 15)
                bi()
                p.ld(14, C["gauss_a"])
                p.fop(15, 14, "+", 15)
                p.fconst(12, kf("SQ15"))
                p.fop(15, 15, "*", 12)
        _leaf(p, name, body)
    return leaf


LEAF = {"exp2": _exp2, "sinp": _sinp, "cosp": _cosp, "expm1": _expm1, "recip": _recip,
        "rsqrt": _rsqrt, "tanh": _tanh, "tab": _tab, "frac": _frac, "fl": _fl,
        "vbi": _xs_leaf("vbi", 2, VOICE["rng"], "bi"), "vu01": _xs_leaf("vu01", 2, VOICE["rng"], "u01"),
        "vgauss": _xs_leaf("vgauss", 2, VOICE["rng"], "gauss"),
        "gbi": _xs_leaf("gbi", 0, GEN["s"], "bi"), "gu01": _xs_leaf("gu01", 0, GEN["s"], "u01"),
        "ggauss": _xs_leaf("ggauss", 0, GEN["s"], "gauss")}


def exp2(x) -> E:
    return Fn("exp2", x)


def sinp(x) -> E:
    return Fn("sinp", x)


def cosp(x) -> E:
    return Fn("cosp", x)


def expm1(x) -> E:
    return Fn("expm1", x)


def recip(x) -> E:
    return Fn("recip", x)


def rsqrt(x) -> E:
    return Fn("rsqrt", x)


def sqrt(x) -> E:
    return Fn("sqrt", x)


def tanh(x) -> E:
    return Fn("tanh", x)


def frac(x) -> E:
    return Fn("frac", x)


def sin_t(ph) -> E:
    return Fn("tab", w(ph) * 256.0)


def cos_t(ph) -> E:
    return Fn("tab", w(ph) * 256.0 + 64.0)


def rnd(name: str) -> E:
    """a draw from a generator (the argument is unused): vbi, vu01, vgauss, gbi, gu01, ggauss"""
    return Fn(name, Kc(0.0))


def u_of(m: Mv) -> E:
    """live.u: an int word 0..127 as float x 1/127 (the words here are already clamped)"""
    return fi(m) * kf("INV127")


def expmap_e(m: Mv, key: str) -> E:
    lo, l2 = K_()[f"EM_{key}"]
    return Kc(lo) * exp2(u_of(m) * Kc(l2))


def onepole(inv, blocks: bool = False) -> E:
    """live.onepole_inv(inv) (one sample) or (inv, BLOCK)"""
    return exp2(Kc(kf("ONEPB" if blocks else "ONEP1")) * w(inv))


def fl_(e) -> E:
    """live._fl: |x| < FLOOR -> 0 (a conditional, so a statement: see Gen.flush_word)"""
    raise NotImplementedError


# == the voice ==============================================================================
from ..perc import program as PP                # noqa: E402  (t146, half: the frame's words)


class FP(Gen):
    """FASCIA's voice program (one slot's block), on Gen's compiler"""

    # -- small statements -------------------------------------------------------------------
    def flushw(self, m: Mv) -> None:
        """live._fl on a word: |x| < FLOOR (float32) -> +0 (the leaf fl)"""
        self.set(m, Fn("fl", m))

    def sloop(self, cnt: str, n: int, body) -> None:
        """for n times (n > 0): the count in scratch word CNT; BODY may use every register"""
        self.p.loop(self.L.C[cnt], n, body)

    def ivloop(self, cnt: str, body) -> None:
        """while the scratch word CNT (set by the caller, > 0) counts down to 0"""
        p, C = self.p, self.L.C
        if p.run:
            while True:
                body()
                p.ld(0, C[cnt])
                p.iconst(12, 1)
                p.iop(0, 0, "-", 12)
                p.st(C[cnt], 0)
                if p.r[0] == 0:
                    return
        top = p.label("vloop")
        p.place(top)
        body()
        p.ld(0, C[cnt])
        p.iconst(12, 1)
        p.iop(0, 0, "-", 12)
        p.st(C[cnt], 0)
        p.jump("NE", top)

    def ptr(self, ireg: int, word: str) -> None:
        self.p.ld(12, self.L.C[word])
        self.p.seti(ireg, 12)

    def bump(self, word: str, nbytes: int) -> None:
        p, C = self.p, self.L.C
        p.ld(13, C[word])
        p.iconst(12, nbytes)
        p.iop(13, 12, "+", 13)
        p.st(C[word], 13)

    def mloop(self, n_word: str, body, trans: bool = True) -> None:
        """for each of the body's modes (I0 = the body): I3 = its record, I4 = its coefficients
        (scratch), C['idx'] = its index. The count from the body's n, clamped to 1..24."""
        p, C, L = self.p, self.L.C, self.L
        p.ldi(0, BODY["n"], 0)
        p.iconst(1, 1)
        p.iop(0, 0, "MAX", 1)
        p.iconst(1, NMAX)
        p.iop(0, 0, "MIN", 1)
        p.st(C[n_word], 0)
        self._mstart()
        p.iconst(0, 0)
        p.st(C["idx"], 0)

        def it():
            self.ptr(3, "u0")
            self.ptr(4, "u1")
            body()
            self.bump("u0", 4 * MW)
            self.bump("u1", 4 * TW)
            p.ld(0, C["idx"])
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(C["idx"], 0)
        self.ivloop(n_word, it)

    def _mstart(self) -> None:
        """u0 = I0's modes (from the body pointer word 'u2'), u1 = the coefficients"""
        p, C = self.p, self.L.C
        p.ld(13, C["u2"])
        p.iconst(12, 4 * BODY_MODES)
        p.iop(13, 12, "+", 13)
        p.st(C["u0"], 13)
        p.iconst(13, self.L.T)
        p.st(C["u1"], 13)

    def set_body(self, which: str) -> None:
        """I0 = body A or B (and the pointer word u2)"""
        p, C = self.p, self.L.C
        p.ld(13, C["vbase"])
        p.iconst(12, 4 * VOICE[which])
        p.iop(13, 12, "+", 13)
        p.st(C["u2"], 13)
        p.seti(0, 13)

    def md(self, f) -> Mv:
        return Mv("i", 3, MODE[f])

    def tm(self, f) -> Mv:
        return Mv("i", 4, TMODE.index(f))

    def bd(self, f) -> Mv:
        return Mv("i", 0, BODY[f])

    def vb(self, which, f) -> Mv:
        """a body's header word through I2"""
        return Mv("i", 2, VOICE[which] + BODY[f])

    def V(self, f) -> Mv:
        return Mv("i", 2, VOICE[f])

    def tabv(self, d: int, table: str, idx_reg: int) -> None:
        """Rd = TABLE[R idx_reg] (an int index, already in range). Uses R12, R13, I1."""
        p = self.p
        p.lsh(12, idx_reg, 2)
        p.iconst(13, self.L.TB[table])
        p.iop(12, 13, "+", 12)
        p.seti(1, 12)
        p.ldi(d, 0, 1)

    def ktab(self, d: int, kind_word: Mv, field: str) -> None:
        """Rd = the KIND table's FIELD for the body kind in KIND_WORD (clamped 0..8)"""
        p = self.p
        self.ld(d, kind_word)
        p.iconst(12, 0)
        p.iop(d, d, "MAX", 12)
        p.iconst(12, len(KINDS) - 1)
        p.iop(d, d, "MIN", 12)
        assert len(KIND_FIELDS) == 5
        p.lsh(13, d, 2)
        p.iop(d, 13, "+", d)                    # kind x 5
        p.iconst(12, KIND_FIELDS.index(field))
        p.iop(d, 12, "+", d)
        self.tabv(d, "KIND", d)

    # -- the frame --------------------------------------------------------------------------
    def read_frame(self) -> None:
        """the panel's 24 knobs (P_*), the trig, the note and the velocity"""
        p, C = self.p, self.L.C
        p.ld(9, C["t"])
        PP.t146(p, 10, 9)
        p.st(C["k146"], 10)
        assert all(FM.SLOTS[c][2] == 0 for c in CONTROLS)
        assert [SC_WORDS.index(f"P_{c}") for c in CONTROLS] == list(range(SC_WORDS.index("P_TYPA"), SC_WORDS.index("P_TYPA") + 24))
        p.iconst(0, 0)
        p.st(C["idx"], 0)

        def one():
            p.ld(0, C["idx"])
            self.tabv(4, "SLOT", 0)                 # the frame word's address | top << 24
            p.lsh(5, 4, -24)                        # top
            p.st(C["q0"], 5)
            p.iconst(12, 0xFFFFFF)
            p.iop(4, 4, "AND", 12)
            p.ld(8, C["k146"])
            p.iop(4, 8, "+", 4)
            p.iconst(12, 2)
            p.iop(1, 4, "AND", 12)
            p.iconst(12, -4)
            p.iop(4, 4, "AND", 12)
            p.seti(1, 4)
            p.ldi(4, 0, 1)
            p.ifz(1, "NE", lambda: p.lsh(4, 4, -16))
            p.iconst(12, 0xFFFF)
            p.iop(4, 4, "AND", 12)
            p.lsh(4, 4, -8)
            p.iconst(12, 0)
            p.iop(4, 4, "MAX", 12)
            p.ld(5, C["q0"])                        # top
            p.iop(4, 4, "MIN", 5)

            def knob():                             # machines.knob: (v 254 + top) // (2 top)
                p.iconst(12, 0)
                p.float_(4, 4, 12)
                p.iconst(12, 100)

                def c100():
                    p.fconst(6, 254.0 / 200)
                p.fconst(6, 254.0 / 240)
                p.if_(5, "EQ", 12, c100, kind="i")
                p.fop(4, 4, "*", 6)
                p.fconst(6, 0.502)
                p.fop(4, 4, "+", 6)
                p.trunc(4, 4)
            p.iconst(12, 127)
            p.if_(5, "NE", 12, knob, kind="i")
            # P_[idx] = R4
            p.ld(0, C["idx"])
            p.lsh(0, 0, 2)
            p.iconst(12, C["P_TYPA"])
            p.iop(0, 12, "+", 0)
            p.seti(1, 0)
            p.sti(0, 1, 4)
            p.ld(0, C["idx"])
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(C["idx"], 0)
        self.sloop("cnt0", 24, one)
        assert {FM.SLOTS[c][3] for c in CONTROLS} == {100, 120, 127}

    def read_note(self) -> None:
        """the trig, the note and the velocity"""
        p, C = self.p, self.L.C
        # the trig bit
        p.ld(0, TRIG_WORD)
        p.lsh(0, 0, -16)
        p.iconst(1, 1)
        p.ld(9, C["t"])
        PP._shift_by(p, 1, 9)
        p.iop(0, 0, "AND", 1)
        p.st(C["trig"], 0)
        # the velocity: header word 52 + 2t, >> 8, 0..127, x 1/127 (live.u)
        p.ld(9, C["t"])
        p.iop(10, 9, "+", 9)
        PP.half(p, 4, VEL_OFFSET, 10)
        p.lsh(4, 4, -8)
        p.iconst(12, 127)
        p.iop(4, 4, "MIN", 12)
        p.iconst(12, 0)
        p.float_(4, 4, 12)
        p.fconst(5, kf("INV127"))
        p.fop(4, 4, "*", 5)
        p.st(C["vv"], 4)
        # the note: the frame's header word 2 + 2t (note << 8 | fine), / 256. Not the note
        # cell (engine +0x1387c + 4t, what PERC and smp read): the stock unpack writes that
        # after this code runs, so on a trig with a new note it still holds the note before
        # (the runner, a steal 60 -> 67: the cell says 60 on the trig's block, 67 the next)
        p.ld(9, C["t"])
        p.iop(10, 9, "+", 9)
        PP.half(p, 8, NOTE_OFFSET, 10)
        p.iconst(12, -8)
        p.float_(8, 8, 12)
        p.st(C["nn"], 8)

    def expand(self) -> None:
        """live.expand, in integers: P_* -> Q_*"""
        p, C = self.p, self.L.C

        def cp(src, dst=None):
            p.ld(0, C[f"P_{src}"])
            p.st(C[f"Q_{dst or src}"], 0)
        for k in ("TYPA", "TYPB", "DUST", "BEND", "MIX", "DEC", "BODA", "BODB", "TUNE", "GEOM",
                  "MATL", "POS", "DAMP", "MORPH", "SHIFT", "BUZZ", "LPG", "HARD", "TZFM"):
            cp(k)
        # ATK = (32 - h) 4 if h < 32
        p.ld(0, C["P_HARD"])
        p.iconst(1, 32)
        p.iop(2, 1, "-", 0)
        p.lsh(2, 2, 2)
        p.iconst(3, 0)
        p.if_(0, "LT", 1, lambda: p.st(C["Q_ATK"], 2), lambda: p.st(C["Q_ATK"], 3), kind="i")
        # SIDE = 16 + (3 TZFM) // 4
        p.ld(8, C["P_TZFM"])
        p.iop(0, 8, "+", 8)
        p.iop(0, 8, "+", 0)
        p.lsh(0, 0, -2)
        p.iconst(12, 16)
        p.iop(0, 12, "+", 0)
        p.st(C["Q_SIDE"], 0)
        # CLIK: four zones
        p.iconst(0, 0)
        p.st(C["Q_CTYP"], 0)
        p.st(C["Q_CLIK"], 0)
        p.ld(0, C["P_CLIK"])

        def clik():
            p.ld(0, C["P_CLIK"])
            p.iconst(12, -1)
            p.iop(0, 12, "+", 0)
            p.lsh(8, 0, 2)                      # R8 = 4 (c - 1)
            p.iconst(9, 16)                     # CTYP = (2 z + 1) 16
            for thr in (127, 254, 381):
                p.iconst(1, thr)

                def up():
                    p.iconst(12, -127)
                    p.iop(8, 12, "+", 8)
                    p.iconst(12, 32)
                    p.iop(9, 12, "+", 9)
                # compare against the ORIGINAL 4 (c - 1): R0 still holds c - 1
                p.lsh(2, 0, 2)
                p.if_(2, "GE", 1, up, kind="i")
            p.st(C["Q_CTYP"], 9)
            p.iconst(12, 0)
            p.iop(8, 8, "MAX", 12)
            p.iconst(12, 127)
            p.iop(8, 8, "MIN", 12)
            p.iconst(12, 0)
            p.float_(8, 8, 12)
            p.fconst(1, 95.0 / 127.0)
            p.fop(8, 8, "*", 1)
            p.fconst(1, 0.002)
            p.fop(8, 8, "+", 1)
            p.trunc(8, 8)
            p.iconst(12, 32)
            p.iop(8, 12, "+", 8)
            p.st(C["Q_CLIK"], 8)
        p.iconst(1, 0)
        p.if_(0, "GT", 1, clik, kind="i")
        # XMOD: the panel's five (RING the fifth)
        p.ld(0, C["P_XMOD"])
        p.lsh(8, 0, 2)
        p.iop(0, 8, "+", 0)                     # 5 v
        p.lsh(0, 0, -7)
        p.iconst(12, 4)
        p.iop(0, 0, "MIN", 12)
        p.ld(2, C["P_COUP"])
        p.iconst(3, 0)

        def ring():
            p.iconst(1, 16)
            p.st(C["Q_XMOD"], 1)
            p.st(C["Q_COUP"], 3)
            p.st(C["Q_RING"], 2)

        def other():
            p.lsh(0, 0, 5)
            p.iconst(12, 16)
            p.iop(0, 12, "+", 0)
            p.st(C["Q_XMOD"], 0)
            p.st(C["Q_COUP"], 2)
            p.st(C["Q_RING"], 3)
        p.iconst(1, 4)
        p.if_(0, "EQ", 1, ring, other, kind="i")
        # SKIN: FORM under 64, WATR over
        p.ld(0, C["P_SKIN"])
        p.iconst(1, 64)
        p.iconst(3, 0)
        p.st(C["Q_FORM"], 3)
        p.st(C["Q_WATR"], 3)

        def form():
            p.iop(2, 1, "-", 0)
            p.lsh(2, 2, 1)
            p.iconst(12, 127)
            p.iop(2, 2, "MIN", 12)
            p.st(C["Q_FORM"], 2)

        def watr():
            p.iop(2, 0, "-", 1)
            p.lsh(2, 2, 1)
            p.iconst(12, 127)
            p.iop(2, 2, "MIN", 12)
            p.st(C["Q_WATR"], 2)
        p.if_(0, "LT", 1, form, kind="i")
        p.if_(0, "GT", 1, watr, kind="i")
        # DRIVE: CHAR to the middle, FOLD on top
        p.ld(0, C["P_DRIVE"])
        p.lsh(2, 0, 1)
        p.iconst(12, 127)
        p.iop(2, 2, "MIN", 12)
        p.st(C["Q_CHAR"], 2)
        p.st(C["Q_FOLD"], 3)

        def fold():
            p.iop(2, 0, "-", 1)
            p.lsh(2, 2, 1)
            p.st(C["Q_FOLD"], 2)
        p.if_(0, "GT", 1, fold, kind="i")

    def ichoice(self, d: int, word: str, n: int) -> None:
        """Rd = min((v n) >> 7, n - 1) for the int word (0..127)"""
        p, C = self.p, self.L.C
        p.ld(d, C[word])
        p.iconst(13, 0)
        for b in range(4):
            if n >> b & 1:
                p.lsh(14, d, b)
                p.iop(13, 13, "+", 14)
        p.lsh(d, 13, -7)
        p.iconst(12, n - 1)
        p.iop(d, d, "MIN", 12)

    def block_controls(self) -> None:
        """live.block_controls(q, vel) into c_* (vel: the voice's)"""
        C = self.L.C
        c, ci, V = self.c, self.ci, self.V
        U = {k: u_of(ci(f"Q_{k}")) for k in ("HARD", "DAMP", "MIX", "SIDE", "GEOM", "MATL", "POS", "BEND",
                                             "LPG", "COUP", "BUZZ", "MORPH", "DUST", "TZFM")}
        vel = V("vel")
        self.set(c("c_hard"), U["HARD"] * (Kc(0.5) + Kc(0.5) * vel))
        self.set(c("c_uhard"), U["HARD"])
        self.set(c("c_tilt"), Kc(1.2) * (Kc(1.0) - c("c_hard")))
        self.set(c("c_geom_e"), Kc(0.6) + Kc(0.8) * U["GEOM"])
        # -u(127 - DAMP): the int 127 - DAMP, as live's u
        p = self.p
        p.ld(0, C["Q_DAMP"])
        p.iconst(1, 127)
        p.iop(0, 1, "-", 0)
        p.st(C["q0"], 0)
        self.set(c("c_inv_t60"), Kc(kf("I003")) * exp2(-(u_of(ci("q0"))) * Kc(kf("L400"))))
        self.set(c("c_matl"), U["MATL"])
        self.set(c("c_pos"), Kc(0.02) + Kc(0.48) * U["POS"])
        self.set(c("c_bend"), (U["BEND"] * Kc(7.0)) * (Kc(0.4) + Kc(0.6) * vel))
        self.set(c("c_ubend"), U["BEND"])
        self.set(c("c_chirp"), (U["HARD"] * vel) * Kc(0.6))
        self.set(c("c_lpg"), U["LPG"] * Kc(6.0))
        self.set(c("c_ulpg"), U["LPG"])
        self.set(c("c_coup"), U["COUP"])
        self.ichoice(0, "Q_XMOD", 4)
        p.st(C["c_xmod"], 0)
        self.set(c("c_buzz"), U["BUZZ"])
        self.set(c("c_morph"), U["MORPH"] * Kc(1.4))
        self.set(c("tmp0"), U["MIX"] * Kc(kf("PI2")))
        self.set(c("c_ga"), mx(cosp(c("tmp0")), 0.0))
        self.set(c("c_gb"), sinp(c("tmp0")))
        self.set(c("c_dec"), expmap_e(ci("Q_DEC"), "DEC"))
        self.set(c("c_udust"), U["DUST"])
        self.set(c("c_utz"), U["TZFM"])
        self.set(c("tmp0"), U["SIDE"])
        self.set(c("c_side"), Kc(0.5) + Kc(6.5) * (c("tmp0") * sqrt(c("tmp0"))))
        self.set(c("c_uring"), u_of(ci("Q_RING")))
        self.set(c("c_uwatr"), u_of(ci("Q_WATR")))
        self.set(c("c_ufold"), u_of(ci("Q_FOLD")))
        self.set(c("c_uchar"), u_of(ci("Q_CHAR")))

    def f0_of(self) -> None:
        """f0, l2f0 from the voice's note and TUNE"""
        c = self.c
        self.set(c("tmp0"), self.V("note") + (fi(self.ci("Q_TUNE")) - Kc(64.0)) * Kc(0.375))
        self.set(c("tmp1"), (c("tmp0") - Kc(69.0)) * Kc(1.0 / 12.0))
        self.set(c("f0"), Kc(440.0) * exp2(c("tmp1")))
        self.set(c("l2f0"), c("tmp1") + Kc(kf("LOG2_440")))

    # -- a slot's block ---------------------------------------------------------------------
    def voice(self, t: int | None = None) -> None:
        p, C, L = self.p, self.L.C, self.L
        if p.run:
            p.iconst(9, t)
            p.st(C["t"], 9)
        self.read_note()
        V = self.V
        # the life words: exactly 1, or 0 (garbage is off)
        for f in ("on", "pending", "fading"):
            self.ld(0, V(f))
            p.iconst(1, 1)
            p.if_(0, "NE", 1, lambda f=f: (p.iconst(0, 0), self.st(V(f), 0)), kind="i")
        # a trig: live.note_on (the note and velocity now; a sounding voice fades first)

        def note_on():
            p.ld(0, C["nn"])
            self.st(V("pnote"), 0)
            p.ld(0, C["vv"])
            self.st(V("pvel"), 0)
            self.iset(V("pending"), 1)
            self.ld(0, V("on"))
            self.st(V("fading"), 0)
        p.ld(0, C["trig"])
        p.ifz(0, "NE", note_on)
        # the panel, only for a voice that will run this block (sounding or armed): an idle
        # voice reads nothing more and writes its silence
        self.ld(0, V("on"))
        self.ld(1, V("pending"))
        p.iop(0, 0, "OR", 1)
        p.ifz(0, "NE", lambda: (self.read_frame(), self.expand()))
        self.ld(0, V("fading"))
        self.ld(1, V("on"))
        p.iop(0, 0, "AND", 1)

        def fade():
            self.rt("run", lambda: self.run_block())
            self.iset(V("fading"), 0)
            self.iset(V("on"), 0)
            self.out(fade=True)

        def normal():
            self.icmp(V("pending"), "EQ", 1, self.strike)
            self.iflag(V("on"), lambda: (self.rt("run", lambda: self.run_block()), self.out()), self.zeros)
        p.ifz(0, "NE", fade, normal)

    def out(self, fade: bool = False) -> None:
        """the slot's buffer = Z (x (1 - ramp) when fading)"""
        p, C, L = self.p, self.L.C, self.L
        # (post-modified: I1, I2, I4 only; I0, I3, I5 never: their L may be circular on the unit)
        self._buf(4)
        p.iconst(0, L.A["Z"])
        p.seti(1, 0)
        p.iconst(0, L.A["RJ"])
        p.seti(2, 0)

        def s():
            p.ldpost(5, 1)
            if fade:
                p.ldpost(6, 2)
                p.fconst(7, 1.0)
                p.fop(6, 7, "-", 6)
                p.fop(5, 5, "*", 6)
            p.stpost(4, 5)
        p.loop_r(10, BLOCK, s, one=11)
        self.ptr(2, "vbase")

    def zeros(self) -> None:
        p = self.p
        self._buf(4)
        p.fconst(5, 0.0)
        p.loop_r(10, BLOCK, lambda: p.stpost(4, 5), one=11)

    def _buf(self, ireg: int) -> None:
        p, C = self.p, self.L.C
        p.ld(9, C["t"])
        p.lsh(12, 9, 2)
        p.iconst(11, BUFFERS)
        p.iop(12, 11, "+", 12)
        p.seti(1, 12)
        p.ldi(0, 0, 1)
        p.seti(ireg, 0, "the slot's buffer")

    # -- the strike (live.Voice._strike) ----------------------------------------------------
    def xs_seed(self, m: Mv, seed_reg: int) -> None:
        """M = XS(seed).s: 0x2545f491 + (seed << 16) + seed (seed < 0x10000), or 1 if 0,
        then three steps. SEED_REG holds the seed; uses R12-R15."""
        p = self.p
        p.lsh(14, seed_reg, 16)
        p.iconst(15, 0x2545F491)
        p.iop(15, 15, "+", 14)
        p.iop(15, 15, "+", seed_reg)
        p.ifz(15, "EQ", lambda: p.iconst(15, 1))
        self.st(m, 15)
        for _ in range(3):
            p.ldi(15, m.off, m.a)
            for sh in (13, -17, 5):
                p.lsh(14, 15, sh)
                p.iop(13, 15, "AND", 14)
                p.iop(15, 15, "OR", 14)
                p.iop(15, 15, "-", 13)
            p.sti(m.off, m.a, 15)

    def strike(self) -> None:
        p, C = self.p, self.L.C
        V, c, ci = self.V, self.c, self.ci
        # the note (non-finite: 0) and the velocity (0..1, NaN: 1)
        self.ld(0, V("pnote"))
        p.lsh(12, 0, -23)
        p.iconst(13, 0xFF)
        p.iop(12, 12, "AND", 13)
        p.if_(12, "EQ", 13, lambda: p.iconst(0, 0), kind="i")
        self.st(V("note"), 0)
        self.ld(0, V("pvel"))
        p.lsh(12, 0, -23)
        p.iconst(13, 0xFF)
        p.iop(12, 12, "AND", 13)
        p.if_(12, "EQ", 13, lambda: p.fconst(0, 1.0), kind="i")
        p.fconst(1, 0.0)
        p.fop(0, 0, "MAX", 1)
        p.fconst(1, 1.0)
        p.fop(0, 0, "MIN", 1)
        self.st(V("vel"), 0)
        self.iset(V("pending"), 0)
        # the voice's generator: seed t + 1 (live: Voice(seed))
        p.ld(8, C["t"])
        p.iconst(12, 1)
        p.iop(8, 12, "+", 8)
        self.st(V("seed"), 8)
        self.xs_seed(V("rng"), 8)
        self.rt("bctl", lambda: self.block_controls())
        self.rt("f0", lambda: self.f0_of())
        # the bodies
        self.ichoice(0, "Q_BODA", len(KINDS))
        self.st(V("ka"), 0)
        self.ichoice(0, "Q_BODB", len(BODIES))
        self.st(V("kb"), 0)
        self.set(c("linv"), c("c_inv_t60"))
        self.set(c("ltilt"), c("c_tilt"))
        self.set(c("lf0"), c("f0"))
        self.set(c("lpos"), c("c_pos"))
        self.ld(0, V("ka"))
        p.st(C["q1"], 0)
        self.set_body("A")
        self.rt("body_init", lambda: self.body_init())
        p.fconst(0, 1.0)
        self.st(V("bratio"), 0)

        def b_on():
            self.ktab(0, V("kb"), "bratio")
            self.st(V("bratio"), 0)
            self.set(c("lf0"), c("f0") * V("bratio"))
            self.set(c("lpos"), c("c_pos") * Kc(0.73))
            self.ld(0, V("kb"))
            p.st(C["q1"], 0)
            self.set_body("B")
            self.rt("body_init", lambda: self.body_init())
        self.icmp(V("kb"), "NE", OFF, b_on)
        # the exciters (BOW's phase is a draw of the voice's generator, after the bodies')
        for which, typ, s in (("EA", "Q_TYPA", 1), ("EB", "Q_TYPB", 2)):
            self.ichoice(0, typ, len(TYPES))
            p.st(C["q1"], 0)
            self.ld(8, V("seed"))
            p.lsh(8, 8, 2)
            p.iconst(12, s)
            p.iop(8, 12, "+", 8)
            p.st(C["q2"], 8)
            self.set_exc(which)
            self.rt("exc_init", lambda: self.exc_init())
        # the click
        self.iset(V("clk"), 0)

        def clk_on():
            self.iset(V("clk"), 1)
            self.ichoice(0, "Q_CTYP", len(CLICKS))
            p.st(C["q1"], 0)
            self.rt("clk_init", lambda: self.clk_init())
        self.icmp(ci("Q_CLIK"), "GT", 0, clk_on)
        # the voice's own words
        for f, x in (("cenv", 1.0), ("lenv", 1.0), ("menv", 1.0), ("venv", 1.0), ("rattle", 0.0),
                     ("dc_x", 0.0), ("dc_y", 0.0), ("lim", 0.0), ("ring_ph", 0.0), ("morph", 0.0),
                     ("pp_l2", 0.0), ("pp_ge", 0.0)):
            p.fconst(0, x)
            self.st(V(f), 0)
        for f in ("ppok", "sh_on", "fo_on", "wa_on", "fading", "blocks"):
            self.iset(V(f), 0)
        # lv, par, parok and ob_prev: contiguous, zeros (I1 post-modified)
        assert VOICE["par"] == VOICE["lv"] + 7 and VOICE["parok"] == VOICE["par"] + 7 \
            and VOICE["obp"] == VOICE["parok"] + 7
        p.ld(13, C["vbase"])
        p.iconst(12, 4 * VOICE["lv"])
        p.iop(13, 12, "+", 13)
        p.seti(1, 13)
        p.iconst(5, 0)
        p.loop_r(10, 21 + BLOCK, lambda: p.stpost(1, 5), one=11)
        self.iset(V("on"), 1)

    def set_exc(self, which: str) -> None:
        """I3 = exciter EA or EB, its pointer in u2"""
        p, C = self.p, self.L.C
        p.ld(13, C["vbase"])
        p.iconst(12, 4 * VOICE[which])
        p.iop(13, 12, "+", 13)
        p.st(C["u2"], 13)
        p.seti(3, 13)

    def set_gen(self, which: str) -> None:
        """I0 = the exciter's (u2) generator G or LG"""
        p, C = self.p, self.L.C
        p.ld(13, C["u2"])
        p.iconst(12, 4 * EXC[which])
        p.iop(13, 12, "+", 13)
        p.seti(0, 13)

    # -- a body at the strike (live.Body.__init__ and twin_select) ---------------------------
    def body_init(self) -> None:
        """I0 = the body; q1 = its kind; lf0, lgeom, linv, c_matl, lpos, ltilt: the strike's"""
        p, C = self.p, self.L.C
        c, bd, md, tm = self.c, self.bd, self.md, self.tm
        p.ld(0, C["q1"])
        p.iconst(1, 0)
        p.iop(0, 0, "MAX", 1)
        p.iconst(1, len(KINDS) - 1)
        p.iop(0, 0, "MIN", 1)
        self.st(bd("kind"), 0)
        for f in ("spatial", "split", "bias"):
            self.ktab(0, bd("kind"), f)
            self.st(bd(f), 0)
        # split bodies: 16 primaries + 8 twins, nfull 32; else 16, 16
        self.iset(bd("n"), MODES)
        p.fconst(0, float(MODES))
        self.st(bd("nfull"), 0)
        self.cmp(bd("split"), "NE", 0.0, lambda: (self.iset(bd("n"), MODES + TWINS), self.set(bd("nfull"), Kc(2.0 * MODES))))
        p.fconst(0, kf("DSIG"))
        self.st(bd("dsig"), 0)
        p.fconst(0, 1e-9)
        self.st(bd("peak"), 0)
        p.fconst(0, 1.0)
        self.st(bd("level"), 0)
        self.iset(bd("ogok"), 0)
        self.iset(self.ci("q3"), 0)
        self.icmp(bd("kind"), "EQ", KINDS.index("CHIME"), lambda: self.iset(self.ci("q3"), 1))
        # every mode's state zero (all 24 records, a word at a time: I1 post-modified)
        p.ld(13, C["u2"])
        p.iconst(12, 4 * BODY_MODES)
        p.iop(13, 12, "+", 13)
        p.seti(1, 13)
        p.iconst(5, 0)
        p.loop_r(10, NMAX * MW, lambda: p.stpost(1, 5), one=11)

        def per16(body):
            """for the 16 primaries: I3, I4, idx (C['q4'] = kind x 16 + idx)"""
            self._mstart()
            p.iconst(0, 0)
            p.st(C["idx"], 0)

            def it():
                self.ptr(3, "u0")
                self.ptr(4, "u1")
                self.ld(0, bd("kind"))
                p.lsh(0, 0, 4)
                p.ld(1, C["idx"])
                p.iop(0, 0, "OR", 1)
                p.st(C["q4"], 0)
                body()
                self.bump("u0", 4 * MW)
                self.bump("u1", 4 * TW)
                p.ld(0, C["idx"])
                p.iconst(12, 1)
                p.iop(0, 12, "+", 0)
                p.st(C["idx"], 0)
            self.sloop("cnt1", MODES, it)

        # eps: a bi each, x js, the first x 0.2; Lj = L0 + (eps (1 - eps/2)) log2e
        def eps():
            self.set(c("tmp0"), rnd("vbi"))
            p.ld(0, C["idx"])
            self.tabv(0, "JSV", 0)
            p.st(C["tmp1"], 0)
            self.set(c("tmp0"), c("tmp0") * c("tmp1"))
            self.icmp(self.ci("idx"), "EQ", 0, lambda: self.set(c("tmp0"), c("tmp0") * Kc(0.2)))
            p.ld(0, C["q4"])
            self.tabv(0, "LOG2R", 0)
            p.st(C["tmp1"], 0)
            self.set(md("L"), c("tmp1") + (c("tmp0") * (Kc(1.0) - Kc(0.5) * c("tmp0"))) * Kc(kf("LOG2E")))
        per16(eps)

        # aj = exp2(g2 (0.1 vary log2e)); a chime's lowest three weighted
        def aj():
            self.set(c("tmp0"), rnd("vgauss"))
            self.set(md("aj"), exp2(c("tmp0") * Kc(kf("CAJ"))))

            def chime():
                for i, wgt in enumerate((0.08, 0.18, 0.45)):
                    self.icmp(self.ci("idx"), "EQ", i, lambda wgt=wgt: self.set(md("aj"), md("aj") * Kc(wgt)))
            self.iflag(self.ci("q3"), chime)
            p.fconst(0, 1.0)
            self.st(md("mult"), 0)
        per16(aj)

        def split():
            # the twins' offsets and levels: beat = min(((f0 ratio) split) (0.6 + 0.8 r1), BEAT_MAX)
            self.ktab(0, bd("kind"), "beat")
            p.st(C["q5"], 0)

            def offs():
                self.set(c("tmp0"), rnd("vu01"))
                p.ld(0, C["q4"])
                self.tabv(0, "LOG2R", 0)
                p.st(C["tmp1"], 0)
                self.set(c("tmp1"), exp2(c("tmp1")))                             # live.RATIO
                self.set(c("tmp2"), mn(((c("lf0") * c("tmp1")) * bd("split")) * (Kc(0.6) + Kc(0.8) * c("tmp0")),
                                       c("q5")))
                self.set(md("offs"), mx(c("tmp2"), 0.15))
            per16(offs)

            def ajt():
                self.set(c("tmp0"), rnd("vu01"))
                self.set(tm("m"), md("aj") * (Kc(0.5) + Kc(0.5) * c("tmp0")))       # ajt
            per16(ajt)
            # twin_select: the scores (tm k), then TWINS passes (taken: tm b = 1.0)
            self.ev(mn(mx(c("c_matl") + bd("bias"), 0.0), 1.0), 0)
            p.st(C["mt"], 0)
            self.set(c("omt"), Kc(1.0) - c("mt"))
            self.set(c("a1"), Kc(4.0) * (c("omt") * c("omt")) + Kc(0.015))
            self.set(c("a2"), Kc(2.0) * ((c("omt") * c("omt")) * c("omt")) + Kc(0.002))

            def score():
                lr = c("q6")
                self.set(lr, c("c_geom_e") * md("L"))
                self.set(c("q7"), exp2(lr))                                       # ratio
                self.set(c("q8"), mn(mx(c("q7") * c("lf0"), kf("F_LO")), kf("F_HI")))   # f
                self.set(c("q8"), c("q8") * Kc(0.001))                             # fk
                self.set(c("q9"), mn(c("linv") * ((c("q8") * c("a2") + c("a1")) * c("q8") + Kc(1.0)), 1000.0))
                self.sp_of(c("q8"), lr, c("q7"))
                self.set(c("q8"), ab(sin_t(frac(c("q8") * (c("lpos") * Kc(0.5))))))
                self.set(tm("k"), ((c("q8") * exp2(lr * (Kc(-0.7) * c("ltilt")))) * (md("aj") + tm("m")))
                         * rsqrt(c("q9")))
                # alive: ratio f0 inside F_LO..F_HI, else -1
                self.set(c("tmp0"), c("q7") * c("lf0"))
                self.cmp(c("tmp0"), "LT", kf("F_HI"), lambda: self.cmp(c("tmp0"), "GT", kf("F_LO"), None,
                                                                         lambda: self.set(tm("k"), -1.0)),
                         lambda: self.set(tm("k"), -1.0))
                self.fz(tm("b"))
            per16(score)

            def one_pass():
                p.iconst(0, -1)
                p.st(C["best"], 0)

                def look():
                    def cand():
                        p.ld(0, C["idx"])
                        p.st(C["best"], 0)
                        self.ld(0, tm("k"))
                        p.st(C["bests"], 0)

                    def untaken():
                        self.icmp(self.ci("best"), "LT", 0, cand,
                                  lambda: self.cmp(tm("k"), "GT", c("bests"), cand))
                    self.cmp(tm("b"), "EQ", 0.0, untaken)
                per16(look)
                # take it: I4 = T + best x TW words
                p.ld(0, C["best"])
                p.lsh(2, 0, 2)
                p.ipass(8, 2)
                p.lsh(2, 0, 4)
                p.iop(2, 8, "+", 2)                 # best x 20 (TW = 5 words)
                p.iconst(12, self.L.T)
                p.iop(2, 12, "+", 2)
                p.seti(4, 2)
                p.fconst(0, 1.0)
                self.st(tm("b"), 0)
            assert TW == 5
            self.sloop("cnt2", TWINS, one_pass)
            # the layout: twins after the primaries, in mode order; a primary whose twin is
            # not kept folds it in (aj + ajt, mult 2); offs only on the twins
            p.ld(13, C["u2"])
            p.iconst(12, 4 * (BODY_MODES + MODES * MW))
            p.iop(13, 12, "+", 13)
            p.st(C["q5"], 13)                       # the next twin's record

            def lay():
                def kept():
                    p.ld(12, C["q5"])
                    p.seti(1, 12)
                    for f in ("L", "offs"):
                        self.ld(0, md(f))
                        p.sti(MODE[f], 1, 0)
                    self.ld(0, tm("m"))
                    p.sti(MODE["aj"], 1, 0)
                    p.fconst(0, 1.0)
                    p.sti(MODE["mult"], 1, 0)
                    self.bump("q5", 4 * MW)

                def folded():
                    self.set(md("aj"), md("aj") + tm("m"))
                    p.fconst(0, 2.0)
                    self.st(md("mult"), 0)
                self.cmp(tm("b"), "EQ", 1.0, kept, folded)
                self.fz(md("offs"))
            per16(lay)
        self.cmp(bd("split"), "NE", 0.0, split)

    def sp_of(self, dst: Mv, lr: Mv, ratio: Mv) -> None:
        """the spatial frequency: the ratio itself (spatial 1) or exp2(lr spatial)"""
        self.cmp(self.bd("spatial"), "EQ", 1.0, lambda: self.set(dst, ratio),
                 lambda: self.set(dst, exp2(lr * self.bd("spatial"))))

    # -- exciters at the strike (live.Exciter.__init__, Gen.__init__) -------------------------
    def ex(self, f) -> Mv:
        return Mv("i", 3, EXC[f])

    def gn(self, f) -> Mv:
        return Mv("i", 0, GEN[f])

    def exc_init(self) -> None:
        """I3 = the exciter (u2); q1 = its type, q2 = its generators' seed"""
        p, C = self.p, self.L.C
        c, ex, V = self.c, self.ex, self.V
        p.ld(0, C["q1"])
        p.iconst(1, 0)
        p.iop(0, 0, "MAX", 1)
        p.iconst(1, len(TYPES) - 1)
        p.iop(0, 0, "MIN", 1)
        self.st(ex("kind"), 0)
        p.iconst(2, 0)
        for k in (TYPES.index("BOW"), TYPES.index("BLOW")):
            p.iconst(1, k)
            p.if_(0, "EQ", 1, lambda: p.iconst(2, 1), kind="i")
        self.st(ex("driven"), 2)
        for f in ("done", "t", "latok", "lag"):
            self.iset(ex(f), 0)
        self.iset(ex("n_end"), 1)
        self.ld(0, V("vel"))
        self.st(ex("vel"), 0)
        self.fz(ex("atk"))
        # (ATK is the one engine control that can be 128: expand's (32 - HARD) 4; live.u clamps it)
        lo, l2 = K_()["EM_ATK"]
        self.icmp(self.ci("Q_ATK"), "GT", 0, lambda: self.set(ex("atk"), Kc(lo) * exp2(
            (mn(fi(self.ci("Q_ATK")), 127.0) * kf("INV127")) * Kc(l2))))

        def impulsive():
            self.set_gen("G")
            self.rt("gen_init", lambda: self.gen_init())

            def atk():
                self.set(c("tmp0"), ex("atk") * Kc(RATE))
                p.ld(0, C["tmp0"])
                p.trunc(0, 0)
                p.iconst(1, 2)
                p.iop(0, 0, "MAX", 1)
                self.st(ex("am"), 0)
                p.st(C["q5"], 0)
                p.iconst(12, -1)
                p.iop(1, 12, "+", 0)
                p.st(C["q6"], 1)                   # m - 1
                p.ipass(8, 0)
                p.iop(1, 8, "+", 0)
                p.iconst(12, -1)
                p.iop(1, 12, "+", 1)
                p.st(C["q7"], 1)                   # 2 m - 1
                m, m1, m2 = fi(self.ci("q5")), fi(self.ci("q6")), fi(self.ci("q7"))
                self.set(ex("cS"), Kc(6.0) * recip((m1 * m) * m2))
                self.set(ex("fm"), m)
                self.set(ex("fm2"), m * m)
                for f in ("b00", "b01", "b02", "b10", "b11", "b12"):
                    self.fz(ex(f))
                self.iset(ex("a0"), 0)
                p.ld(0, C["q5"])
                self.st(ex("a1"), 0)
                self.set_gen("LG")
                self.rt("gen_init", lambda: self.gen_init())
                self.iset(ex("lag"), 1)
            self.cmp(ex("atk"), "GT", 0.0, atk)
        self.iflag(ex("driven"), None, impulsive)
        p.fconst(0, 1.0)
        self.st(ex("oq"), 0)
        self.st(ex("hold"), 0)
        self.fz(ex("grit"))
        self.fz(ex("breath"))
        self.fz(ex("sph"))
        self.icmp(ex("kind"), "EQ", TYPES.index("BOW"),
                  lambda: (self.set(c("tmp0"), rnd("vu01")),
                           self.set(ex("sph"), (c("tmp0") * Kc(6.0)) * Kc(kf("I2PI")))))

    def gen_init(self) -> None:
        """I0 = the generator; I3 its exciter (kind, vel); q2 = the seed"""
        p, C = self.p, self.L.C
        c, gn, ex = self.c, self.gn, self.ex
        self.ld(0, ex("kind"))
        self.st(gn("kind"), 0)
        self.ld(0, ex("vel"))
        self.st(gn("vel"), 0)
        p.ld(8, C["q2"])
        self.xs_seed(gn("s"), 8)
        self.iset(gn("k"), 0)
        self.set(c("tmp0"), u_of(self.ci("Q_HARD")) * (Kc(0.5) + Kc(0.5) * gn("vel")))
        self.set(c("tmp1"), Kc(4.0e-3) * exp2(c("tmp0") * Kc(kf("L0125"))))      # width
        self.ev(c("tmp1") * Kc(RATE), 0)
        p.trunc(0, 0)
        p.iconst(1, 2)
        p.iop(0, 0, "MAX", 1)
        self.st(gn("pn"), 0)
        self.set(gn("pinv"), recip(fi(gn("pn"))))
        p.fconst(0, 1.0)
        for f in ("en", "pe", "ep", "ei", "eo"):
            self.st(gn(f), 0)
        for f in ("ph", "mph", "cph", "sm0", "sm1", "sm2", "sm3", "ca", "kn", "cn", "pd", "kd", "ga",
                  "inc0", "dinc", "kep", "ci", "fm", "d6", "ki", "ko"):
            self.fz(gn(f))
        # the TZFM burst on any other exciter when TZFM > 0
        self.iset(gn("burst"), 0)
        self.icmp(self.ci("Q_TZFM"), "GT", 0,
                  lambda: self.icmp(gn("kind"), "NE", TYPES.index("TZFM"), lambda: self.iset(gn("burst"), 1)))

        def dust():
            # dn = max(trunc(max(width, 1e-4) R), 2); the grain's four one-poles
            self.ev(mx(c("tmp1"), 1e-4) * Kc(RATE), 0)
            p.trunc(0, 0)
            p.iconst(1, 2)
            p.iop(0, 0, "MAX", 1)
            p.st(C["q5"], 0)
            dn = fi(self.ci("q5"))
            self.set(c("tmp2"), Kc(kf("HANN")) * (dn * dn))
            self.set(c("tmp2"), c("tmp2") * Kc(0.25))                         # s
            self.set(gn("ca"), Kc(1.0))

            def pos():
                self.set(c("tmp3"), Kc(1.0) + Kc(2.0) * c("tmp2"))
                self.set(c("tmp3"), (Kc(2.0) * c("tmp2")) * recip(c("tmp3") + sqrt(Kc(1.0) + Kc(4.0) * c("tmp2"))))
                self.set(gn("ca"), Kc(1.0) - c("tmp3"))
            self.cmp(c("tmp2"), "LE", 0.0, None, pos)
        self.icmp(gn("kind"), "EQ", TYPES.index("DUST"), dust)

    def clk_init(self) -> None:
        """the click (live.Click.__init__): q1 = its kind; hard = c_hard; the voice's vel"""
        p, C = self.p, self.L.C
        c, V = self.c, self.V
        ck = lambda f: Mv("i", 2, VOICE["CK"] + CLK[f])
        p.ld(0, C["q1"])
        self.st(ck("kind"), 0)
        self.set(ck("level"), (u_of(self.ci("Q_CLIK")) * V("vel")) * Kc(0.5))
        self.set(c("tmp0"), Kc(1.0) - c("c_hard"))                               # h1
        self.iset(ck("k"), 0)
        self.fz(ck("ph"))
        self.fz(ck("prev"))
        p.fconst(0, 1.0)
        self.st(ck("e"), 0)
        self.st(ck("pe"), 0)
        for f in ("n", "ninv", "gain", "inc", "ke", "kp"):
            self.fz(ck(f))

        def snap():
            self.ev((Kc(0.00015) + Kc(0.0006) * c("tmp0")) * Kc(RATE), 0)
            p.trunc(0, 0)
            p.iconst(1, 3)
            p.iop(0, 0, "MAX", 1)
            self.st(ck("n"), 0)
            p.iconst(12, 1)
            p.iop(1, 12, "+", 0)
            self.st(ck("len"), 1)
            self.set(ck("ninv"), recip(fi(ck("n"))))
            self.set(ck("gain"), fi(ck("n")) * Kc(0.35))

        def tick():
            self.iset(ck("len"), int(0.004 * RATE))
            self.set(ck("inc"), (Kc(2500.0) + Kc(3000.0) * c("c_hard")) * Kc(kf("INVR")))
            self.set(ck("ke"), onepole(recip(Kc(0.0004) + Kc(0.0008) * c("tmp0"))))

        def noise():
            self.iset(ck("len"), int(0.012 * RATE))
            self.set(ck("ke"), onepole(recip(Kc(0.0008) + Kc(0.003) * c("tmp0"))))

        def thump():
            self.iset(ck("len"), int(0.06 * RATE))
            self.set(ck("ke"), onepole(recip(Kc(0.012) + Kc(0.01) * c("tmp0"))))
            p.fconst(0, kf("KP_THUMP"))
            self.st(ck("kp"), 0)
        self.icmp(ck("kind"), "EQ", 0, snap, lambda: self.icmp(ck("kind"), "EQ", 1, tick,
                  lambda: self.icmp(ck("kind"), "EQ", 2, noise, thump)))

    # -- an exciter's block (live.Exciter.gen_block) ----------------------------------------
    def exc_block(self) -> None:
        """I3 = the exciter (u2); fa/fb: the addresses of its press and drive arrays. Writes
        E (impulsive: the excitation, zeros past its end) or its press, drive and np."""
        p, C, L = self.p, self.L.C, self.L
        c, ex = self.c, self.ex
        # E = +0 (live's np.zeros)
        p.iconst(0, L.A["E"])
        p.seti(1, 0)
        p.fconst(5, 0.0)
        p.loop_r(10, BLOCK, lambda: p.stpost(1, 5), one=11)
        # the controls: latched at the strike under ATK (impulsive), else the block's
        names = ("dec", "side", "utz", "udust", "ubend")

        def use_block():
            for n in names:
                p.ld(0, C[f"c_{n}"])
                p.st(C[f"q{names.index(n)}"], 0)
            p.ld(0, C["Q_DUST"])
            p.st(C["q5"], 0)
            p.ld(0, C["f0"])
            p.st(C["q6"], 0)

        def use_latch():
            def latch():
                for n in names:
                    p.ld(0, C[f"c_{n}"])
                    self.st(ex(f"l_{n}"), 0)
                p.ld(0, C["Q_DUST"])
                self.st(ex("l_DUST"), 0)
                p.ld(0, C["f0"])
                self.st(ex("l_f0"), 0)
                self.iset(ex("latok"), 1)
            self.iflag(ex("latok"), None, latch)
            for n in names:
                self.ld(0, ex(f"l_{n}"))
                p.st(C[f"q{names.index(n)}"], 0)
            self.ld(0, ex("l_DUST"))
            p.st(C["q5"], 0)
            self.ld(0, ex("l_f0"))
            p.st(C["q6"], 0)
        self.cmp(ex("atk"), "GT", 0.0, lambda: self.iflag(ex("driven"), use_block, use_latch), use_block)
        # n_end = trunc((dec 4 + 0.01 + atk) R)
        self.ev(((c("q0") * Kc(4.0) + Kc(0.01)) + ex("atk")) * Kc(RATE), 0)
        p.trunc(0, 0)
        self.st(ex("n_end"), 0)
        self.iset(ex("np"), 0)

        def ended():
            self.iset(ex("done"), 1)
            self.iset(ex("np"), 0)
            self._t_on()

        def go():
            self.iflag(ex("driven"), self.driven, self.impulsive)
            self._t_on()
            self.ld(0, ex("t"))
            self.ld(1, ex("n_end"))
            p.if_(0, "GE", 1, lambda: self.iset(ex("done"), 1), kind="i")
        # done, or k0 >= n_end
        self.ld(0, ex("t"))
        self.ld(1, ex("n_end"))
        p.if_(0, "GE", 1, ended, lambda: self.iflag(ex("done"), ended, go), kind="i")

    def _t_on(self) -> None:
        p = self.p
        self.ld(8, self.ex("t"))
        p.iconst(12, BLOCK)
        p.iop(8, 12, "+", 8)
        self.st(self.ex("t"), 8)

    def gen_ctl(self, which: str) -> None:
        """copy the block's (or latched) controls q0..q6 into the generator WHICH"""
        p, C = self.p, self.L.C
        self.set_gen(which)
        for k, f in enumerate(("c_dec", "c_side", "c_utz", "c_udust", "c_ubend", "c_DUST", "f0")):
            p.ld(0, C[f"q{k}"])
            self.st(self.gn(f), 0)

    def impulsive(self) -> None:
        """the generator a sample at a time, and under ATK the window (two staggered sums)"""
        p, C, L = self.p, self.L.C, self.L
        c, ex = self.c, self.ex
        self.gen_ctl("G")
        self.iflag(ex("lag"), lambda: self.gen_ctl("LG"))
        p.iconst(0, 0)
        p.st(C["jj"], 0)
        p.iconst(0, 1)
        p.st(C["fcount"], 0)                   # 1: go on

        def sample():
            def run():
                # k = t + j
                self.ld(8, ex("t"))
                p.ld(1, C["jj"])
                p.iop(8, 8, "+", 1)
                p.st(C["cnt2"], 8)
                self.ld(1, ex("n_end"))

                def stop():
                    self.iset(ex("done"), 1)
                    self.iset(self.ci("fcount"), 0)

                def one():
                    self.set_gen("G")
                    self.rt("gen", lambda: self.gen_sample())
                    p.ld(0, C["jj"])
                    p.lsh(0, 0, 2)
                    p.iconst(12, L.A["E"])
                    p.iop(0, 12, "+", 0)
                    p.st(C["tmp6"], 0)

                    def plain():
                        p.ld(0, C["g"])
                        p.ld(12, C["tmp6"])
                        p.seti(1, 12)
                        p.sti(0, 1, 0)

                    def window():
                        p.ld(0, C["g"])
                        p.st(C["x1"], 0)                  # x
                        self.fz(c("y1"))                  # xo
                        self.ld(1, ex("am"))
                        p.ld(0, C["cnt2"])

                        def lagged():
                            self.set_gen("LG")
                            self.rt("gen", lambda: self.gen_sample())
                            p.ld(0, C["g"])
                            p.st(C["y1"], 0)
                        p.if_(0, "GE", 1, lagged, kind="i")
                        self.fz(c("pk"))                  # y
                        for a in ("0", "1"):
                            self.window(a)
                        self.set(c("tmp0"), c("pk") * ex("cS"))
                        p.ld(0, C["tmp0"])
                        p.ld(12, C["tmp6"])
                        p.seti(1, 12)
                        p.sti(0, 1, 0)
                    self.iflag(ex("lag"), window, plain)
                p.if_(8, "GE", 1, stop, one, kind="i")
            self.iflag(self.ci("fcount"), run)
            p.ld(0, C["jj"])
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(C["jj"], 0)
        self.sloop("cnt1", BLOCK, sample)

    def window(self, a: str) -> None:
        """one of ATK's two sums at sample k (cnt2): x (x1) in, x_{k-m} (y1) out; y (pk)"""
        p, C = self.p, self.L.C
        c, ex = self.c, self.ex
        A0, B0, B1, B2 = f"a{a}", f"b{a}0", f"b{a}1", f"b{a}2"

        def restart():
            p.ld(0, C["cnt2"])
            self.st(ex(A0), 0)
            for f in (B0, B1, B2):
                self.fz(ex(f))
        # k == a0 + 2m: start afresh
        self.ld(8, ex(A0))
        self.ld(1, ex("am"))
        p.iop(8, 8, "+", 1)
        p.iop(8, 8, "+", 1)
        p.ld(0, C["cnt2"])
        p.if_(0, "EQ", 8, restart, kind="i")

        def live_():
            self.set(ex(B2), (ex(B2) + Kc(2.0) * ex(B1)) + ex(B0))
            self.set(ex(B1), ex(B1) + ex(B0))
            self.set(ex(B0), ex(B0) + c("x1"))
            # k - m >= a0: x_{k-m} was this window's
            p.ld(0, C["cnt2"])
            self.ld(1, ex("am"))
            p.iop(0, 0, "-", 1)
            self.ld(1, ex(A0))

            def out():
                self.set(ex(B0), ex(B0) - c("y1"))
                self.set(ex(B1), ex(B1) - c("y1") * ex("fm"))
                self.set(ex(B2), ex(B2) - c("y1") * ex("fm2"))
            p.if_(0, "GE", 1, out, kind="i")
            # whole: a0 == 0 or k >= a0 + m
            self.ld(8, ex(A0))
            self.ld(1, ex("am"))
            p.iop(1, 8, "+", 1)
            p.ld(0, C["cnt2"])
            take = lambda: (self.ld(0, ex(B2)), p.st(C["pk"], 0))
            p.if_(0, "GE", 1, take, lambda: self.icmp(ex(A0), "EQ", 0, take), kind="i")
        self.ld(1, ex(A0))
        p.ld(0, C["cnt2"])
        p.if_(0, "GE", 1, live_, kind="i")

    def gen_sample(self) -> None:
        """live.Gen.__call__: I0 = the generator; -> C['g'] (x vel)"""
        p, C = self.p, self.L.C
        c, gn = self.c, self.gn
        # its setup every 32 samples of its own count
        self.ld(0, gn("k"))
        p.iconst(1, BLOCK - 1)
        p.iop(0, 0, "AND", 1)
        p.ifz(0, "EQ", lambda: self.rt("gsetup", lambda: self.gen_setup()))
        self.fz(c("ws"))                       # pulse
        self.fz(c("w0"))                       # rest
        kind = gn("kind")

        def strike():
            self.ld(0, gn("k"))
            self.ld(1, gn("pn"))
            p.if_(0, "LT", 1, lambda: self.set(c("ws"), (Kc(1.0) - cos_t(fi(gn("k")) * gn("pinv"))) * gn("pinv")),
                  kind="i")

            def contact():
                self.set(c("w1"), rnd("ggauss"))
                self.set(c("w0"), (c("w1") * gn("en")) * gn("cn"))
                self.set(gn("en"), gn("en") * gn("kn"))
                self.flushw(gn("en"))
            self.cmp(gn("cn"), "NE", 0.0, contact)

        def dust():
            self.fz(c("w1"))                   # ev
            self.set(c("w0"), rnd("gu01"))
            self.cmp(c("w0"), "LT", gn("pd") * gn("en"),
                     lambda: (self.set(c("w1"), rnd("gbi")), self.set(c("w1"), c("w1") * gn("ga"))))
            self.set(gn("en"), gn("en") * gn("kd"))
            self.flushw(gn("en"))
            for k in range(4):
                s = gn(f"sm{k}")
                self.set(s, s + (c("w1") - s) * gn("ca"))
                self.flushw(s)
                self.set(c("w1"), s)
            self.set(c("w0"), c("w1"))

        def pulse():
            self.ld(0, gn("k"))
            p.iconst(1, BLOCK - 1)
            p.iop(0, 0, "AND", 1)
            p.st(C["q8"], 0)
            self.set(gn("ph"), frac(gn("ph") + (gn("inc0") + fi(self.ci("q8")) * gn("dinc"))))
            self.set(c("w0"), sin_t(gn("ph")) * gn("ep"))
            self.set(gn("ep"), gn("ep") * gn("kep"))
            self.flushw(gn("ep"))

        def tzfm():
            self.tz_tick()
            p.ld(0, C["w1"])
            p.st(C["w0"], 0)
        self.icmp(kind, "EQ", 0, strike, lambda: self.icmp(kind, "EQ", 3, dust, lambda: self.icmp(
            kind, "EQ", 4, pulse, lambda: self.icmp(kind, "EQ", 5, tzfm))))
        self.set(c("g"), (c("ws") + c("w0")) * gn("tg"))

        def burst():
            self.tz_tick()
            self.set(c("g"), c("g") + c("w1") * Kc(float(self._tg("TZFM"))))
        self.iflag(gn("burst"), burst)
        self.ld(8, gn("k"))
        p.iconst(12, 1)
        p.iop(8, 12, "+", 8)
        self.st(gn("k"), 8)
        self.set(c("g"), c("g") * gn("vel"))

    @staticmethod
    def _tg(t: str) -> float:
        from . import live as LV
        return float(LV.TG[t])

    def tz_tick(self) -> None:
        """live.TZ.__call__ on the generator's TZ words -> C['w1']"""
        c, gn = self.c, self.gn
        self.set(c("w1"), sin_t(gn("mph")))                                    # mv
        self.set(gn("mph"), frac(gn("mph") + gn("fm")))
        self.set(c("tmp4"), gn("ci") + ((gn("ei") * gn("d6")) * c("w1")) * gn("fm"))
        self.set(gn("cph"), frac(gn("cph") + c("tmp4")))
        self.set(c("w1"), sin_t(gn("cph")) * gn("eo"))
        self.set(gn("ei"), gn("ei") * gn("ki"))
        self.flushw(gn("ei"))
        self.set(gn("eo"), gn("eo") * gn("ko"))
        self.flushw(gn("eo"))

    def tz_setup(self, depth: E, tau: E) -> None:
        """live.TZ.setup(f0, side, depth, tau)"""
        c, gn = self.c, self.gn
        self.set(c("tmp3"), tau)
        self.set(gn("ci"), gn("f0") * Kc(kf("INVR")))
        self.set(gn("fm"), (gn("f0") * gn("c_side")) * Kc(kf("INVR")))
        self.set(gn("d6"), depth * Kc(6.0))
        self.set(gn("ki"), onepole(recip(c("tmp3"))))
        self.set(gn("ko"), onepole(recip(Kc(3.0) * c("tmp3") + Kc(0.005))))

    def gen_setup(self) -> None:
        """live.Gen._setup: the controls of these 32 samples"""
        p, C = self.p, self.L.C
        c, gn = self.c, self.gn
        dec = gn("c_dec")
        self.iflag(gn("burst"), lambda: self.tz_setup(gn("c_utz"), mn(dec, 0.03)))
        kind = gn("kind")
        # TYPE_GAIN, here once (v0.45: was every sample)
        self.ld(0, kind)
        p.iconst(1, 0)
        p.iop(0, 0, "MAX", 1)
        p.iconst(1, len(TYPES) - 1)
        p.iop(0, 0, "MIN", 1)
        self.tabv(0, "TG", 0)
        self.st(gn("tg"), 0)

        def strike():
            self.set(gn("kn"), onepole(recip(dec * Kc(0.25))))
            self.set(gn("cn"), Kc(0.15) * gn("c_udust"))

        def dust():
            self.ld(0, gn("c_DUST"))
            p.st(C["q9"], 0)
            self.set(c("tmp2"), expmap_e(self.ci("q9"), "DDUST") * (Kc(0.5) + gn("vel")))     # dens
            self.set(gn("pd"), c("tmp2") * Kc(kf("INVR")))
            self.set(gn("kd"), onepole(recip(dec)))
            self.set(gn("ga"), Kc(2.0) * rsqrt(mx(c("tmp2") * dec, 1.0)))

        def pulse():
            self.set(c("tmp2"), gn("c_ubend") * Kc(3.0))                     # ub3
            self.set(c("tmp3"), (gn("f0") * Kc(2.0)) * Kc(kf("INVR")))        # c2
            self.set(gn("inc0"), c("tmp3") * exp2(c("tmp2") * gn("pe")))
            self.set(gn("pe"), gn("pe") * Kc(kf("K_PE")))
            self.set(c("tmp4"), c("tmp3") * exp2(c("tmp2") * gn("pe")))       # inc1
            self.set(gn("dinc"), (c("tmp4") - gn("inc0")) * Kc(1.0 / BLOCK))
            self.set(gn("kep"), onepole(recip(dec * Kc(0.3))))

        def tzfm():
            self.tz_setup(mx(gn("c_utz"), 0.15), dec)
        self.icmp(kind, "EQ", 0, strike, lambda: self.icmp(kind, "EQ", 3, dust, lambda: self.icmp(
            kind, "EQ", 4, pulse, lambda: self.icmp(kind, "EQ", 5, tzfm))))

    def driven(self) -> None:
        """live.Exciter._driven: this block's pressure and speed (BOW) or breath (BLOW)"""
        p, C = self.p, self.L.C
        c, ex, V = self.c, self.ex, self.V
        bow = lambda then, else_=None: self.icmp(ex("kind"), "EQ", TYPES.index("BOW"), then, else_)
        self.set(c("w0"), c("c_dec") * Kc(RATE))                                 # decR
        self.set(c("w1"), Kc(kf("KH_BLOW")))
        self.set(c("dw"), Kc(0.4) + Kc(0.6) * ex("vel"))
        bow(lambda: (self.set(c("w1"), Kc(kf("KH_BOW"))), self.set(c("dw"), Kc(0.2) + Kc(0.8) * ex("vel"))))
        self.cmp(ex("atk"), "GT", 0.0, lambda: self.set(c("x1"), onepole(recip(ex("atk") * Kc(1.0 / 3.0)))))

        def bow_c():
            self.ld(0, self.ci("Q_DUST"))
            p.st(C["q9"], 0)
            self.set(c("pk"), expmap_e(self.ci("q9"), "BDUST") * Kc(kf("INVR")))   # pg
            self.set(c("y1"), Kc(0.7) * Kc(kf("INVR")))                          # sinc

        def blow_c():
            self.set(c("pk"), Kc(400.0) * exp2(c("c_uhard") * Kc(kf("L30"))))   # cut
            self.set(c("y1"), exp2(c("pk") * Kc(kf("BLOW_A"))))                 # a
            self.set(c("pk"), Kc(1.0) - c("y1"))                                 # ca
            self.set(c("ws"), Kc(0.3) + Kc(0.7) * c("c_udust"))                  # bg
        bow(bow_c, blow_c)
        p.iconst(0, 0)
        p.st(C["jj"], 0)
        p.iconst(0, 1)
        p.st(C["fcount"], 0)

        def sample():
            def run():
                self.ld(8, ex("t"))
                p.ld(1, C["jj"])
                p.iop(8, 8, "+", 1)
                p.st(C["cnt2"], 8)
                self.ld(1, ex("n_end"))

                def one():
                    k = fi(self.ci("cnt2"))

                    def ramp():
                        self.set(c("tmp0"), mn(k * Kc(kf("K_RAMP")), 1.0))

                    def onset():
                        self.set(c("tmp0"), Kc(1.0) - ex("oq"))
                        self.set(ex("oq"), ex("oq") * c("x1"))
                    self.cmp(ex("atk"), "GT", 0.0, onset, ramp)
                    self.cmp(k, "GT", c("w0"), lambda: self.set(ex("hold"), ex("hold") * c("w1")))
                    self.set(c("tmp1"), (c("tmp0") * ex("hold")) * c("dw"))          # pr
                    # the arrays' j-th words: I1 = press + 4 j, I4 = drive + 4 j
                    p.ld(0, C["jj"])
                    p.lsh(0, 0, 2)
                    p.ld(12, C["fa"])
                    p.iop(1, 12, "+", 0)
                    p.st(C["tmp5"], 1)
                    p.ld(12, C["fb"])
                    p.iop(1, 12, "+", 0)
                    p.st(C["tmp6"], 1)

                    def bowj():
                        self.set(c("tmp2"), Kc(0.25) + Kc(0.15) * sin_t(ex("sph")))   # sp
                        self.set(ex("sph"), frac(ex("sph") + c("y1")))

                        def grit():
                            self.fz(c("tmp3"))
                            self.set(c("tmp4"), rnd("vu01"))
                            self.cmp(c("tmp4"), "LT", c("pk"), lambda: self.set(c("tmp3"), rnd("vbi")))
                            self.set(ex("grit"), ex("grit") * Kc(0.6) + c("tmp3"))
                            self.set(c("tmp2"), c("tmp2") * (Kc(1.0) + (ex("grit") * c("c_udust")) * Kc(0.5)))
                        self.cmp(c("c_udust"), "NE", 0.0, grit, lambda: self.fz(ex("grit")))
                        self._putj("tmp5", c("tmp1"))
                        self._putj("tmp6", c("tmp2"))

                    def blowj():
                        self.set(c("tmp3"), rnd("vgauss"))
                        self.set(ex("breath"), c("pk") * c("tmp3") + c("y1") * ex("breath"))
                        self._putj("tmp5", c("tmp1") * (Kc(1.0) + ex("breath") * c("ws")))
                    bow(bowj, blowj)
                    p.ld(0, C["jj"])
                    p.iconst(12, 1)
                    p.iop(0, 12, "+", 0)
                    self.st(ex("np"), 0)
                p.if_(8, "GE", 1, lambda: self.iset(self.ci("fcount"), 0), one, kind="i")
            self.iflag(self.ci("fcount"), run)
            p.ld(0, C["jj"])
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(C["jj"], 0)
        self.sloop("cnt1", BLOCK, sample)

    def _putj(self, at_word: str, e) -> None:
        """the word at the address in scratch AT_WORD = E"""
        p = self.p
        self.ev(w(e), 0)
        p.ld(12, self.L.C[at_word])
        p.seti(1, 12)
        p.sti(0, 1, 0)

    # -- the block (live.Voice._run) ---------------------------------------------------------
    def fill(self, arr: str, bits_: int) -> None:
        p, L = self.p, self.L
        p.iconst(0, L.A[arr])
        p.seti(1, 0)
        p.iconst(5, bits_)
        p.loop_r(10, BLOCK, lambda: p.stpost(1, 5), one=11)

    def J(self, arr: str) -> Mv:
        """ARR[j] inside a jloop: I4 = the arrays + 4 (j + WIN)"""
        return Mv("i", 4, (self.L.A[arr] - self.L.arrays) // 4 - WIN)

    def OBP(self) -> Mv:
        """the voice's ob_prev[j] inside a jloop (I3 = the voice + 4 j, set by the loop)"""
        return Mv("i", 3, VOICE["obp"])

    def jloop(self, body, obp: bool = False, need_j: bool = False) -> None:
        """for j in 0..31: I4 = the arrays + 4 (j + WIN), advanced by a post-modify each pass
        (and I3 = the voice + 4 j: OBP); C['jj'] = j when NEED_J or OBP. BODY may use any register
        but I4 (and I3), and must not move I4 (no routine inside it does)"""
        p, C = self.p, self.L.C
        need_j = need_j or obp
        if need_j:
            p.iconst(0, 0)
            p.st(C["jj"], 0)
        p.iconst(0, self.L.arrays + 4 * WIN)
        p.seti(4, 0)

        def it():
            if obp:
                p.ld(0, C["jj"])
                p.lsh(0, 0, 2)
                p.ld(12, C["vbase"])
                p.iop(1, 12, "+", 0)
                p.seti(3, 1)
            body()
            p.ldpost(12, 4)                     # I4 one word on
            if need_j:
                p.ld(0, C["jj"])
                p.iconst(12, 1)
                p.iop(0, 12, "+", 0)
                p.st(C["jj"], 0)
        self.sloop("cnt3", BLOCK, it)

    def run_block(self) -> None:
        p, C, L = self.p, self.L.C, self.L
        c, ci, V, A, J = self.c, self.ci, self.V, L.A, self.J
        self.rt("bctl", lambda: self.block_controls())
        self.rt("f0", lambda: self.f0_of())
        # the ramp (j + 1) / 32 (exact: FLOAT (j + 1) BY -5), into scratch (RJ)
        p.iconst(0, A["RJ"])
        p.seti(4, 0)
        p.iconst(8, 0)
        p.iconst(9, -5)

        def rj():
            p.iconst(12, 1)
            p.iop(8, 12, "+", 8)
            p.float_(5, 8, 9)
            p.stpost(4, 5)
        p.loop_r(10, BLOCK, rj, one=11)
        # the exciters: x = sum of the impulsive ones' blocks x their gains
        self.fill("X", 0)
        self.iset(ci("hasx"), 0)
        for which, gain, pa, da in (("EA", "c_ga", "P0", "D0"), ("EB", "c_gb", "P1", "D1")):
            self.set_exc(which)
            ex = self.ex

            def live_(gain=gain, pa=pa, da=da, which=which):
                self.iset(ci("fa"), A[pa])
                self.iset(ci("fb"), A[da])
                self.rt("exc_block", lambda: self.exc_block())
                self.set_exc(which)

                def mix():
                    self.iset(ci("hasx"), 1)
                    p.ld(5, C[gain])
                    p.iconst(0, A["X"])
                    p.seti(4, 0)
                    p.iconst(0, A["E"])
                    p.seti(1, 0)

                    def s():
                        p.ldi(6, 0, 4)
                        p.ldpost(7, 1)
                        p.fop(7, 7, "*", 5)
                        p.fop(6, 6, "+", 7)
                        p.stpost(4, 6)
                    p.loop_r(10, BLOCK, s, one=11)
                self.iflag(ex("driven"), None, mix)
            self.iflag(ex("done"), lambda: self.iset(ex("np"), 0), live_)
        self.ld(0, Mv("i", 2, VOICE["EA"] + EXC["done"]))
        self.ld(1, Mv("i", 2, VOICE["EB"] + EXC["done"]))
        p.iop(0, 0, "AND", 1)
        p.st(C["excdone"], 0)
        # the chirp, BEND's glide, the LPG's loss
        self.set(c("ch"), c("c_chirp") * V("cenv"))
        self.set(V("cenv"), V("cenv") * Kc(kf("K_CHIRP")))
        self.flushw(V("cenv"))
        self.set(c("bend"), exp2((c("c_bend") * self.vb("A", "level") + c("ch")) * Kc(1.0 / 12.0)))
        self.set(c("tmp0"), V("lenv"))                                         # gl
        self.set(V("lenv"), V("lenv") * onepole(mn(c("c_inv_t60") * Kc(4.0), 100.0), blocks=True))
        self.flushw(V("lenv"))
        self.set(c("loss"), c("c_lpg") * (Kc(1.0) - c("tmp0")))
        # FDBK (fixed 0) + COUP under TRADE: B back into A, a block late, bounded
        self.fz(c("back"))
        self.icmp(ci("c_xmod"), "EQ", XMODS.index("TRADE"), lambda: self.set(c("back"), Kc(0.0) + c("c_coup")))

        def fdbk():
            def mixb():
                def j():
                    self.set(J("X"), J("X") + (tanh(self.OBP() * Kc(2.0)) * c("back")) * Kc(0.08))
                    self.cmp(self.OBP(), "NE", 0.0, lambda: self.iset(ci("hasx"), 1))
                self.jloop(j, obp=True)
            self.cmp(c("back"), "GT", 0.0, mixb)
        self.icmp(V("kb"), "NE", OFF, fdbk)
        # TUNE or GEOM moved: retune
        self.iset(ci("retune"), 0)

        def moved():
            self.cmp(c("l2f0"), "NE", V("pp_l2"), lambda: self.iset(ci("retune"), 1))
            self.cmp(c("c_geom_e"), "NE", V("pp_ge"), lambda: self.iset(ci("retune"), 1))
        self.iflag(V("ppok"), moved)
        self.set(V("pp_l2"), c("l2f0"))
        self.set(V("pp_ge"), c("c_geom_e"))
        self.iset(V("ppok"), 1)
        # MORPH's depth slews; its weights ramp while it moves
        self.iset(ci("ramp_og"), 0)

        def slew():
            self.set(c("tmp0"), V("morph"))                                    # m0
            self.set(V("morph"), V("morph") + (c("c_morph") - V("morph")) * Kc(0.25))
            self.cmp(V("morph"), "LT", 1e-6, lambda: self.fz(V("morph")))
            self.cmp(c("tmp0"), "NE", V("morph"), lambda: self.iset(ci("ramp_og"), 1))

        def at_strike():
            self.set(V("morph"), c("c_morph"))
            self.cmp(V("morph"), "LT", 1e-6, lambda: self.fz(V("morph")))
        self.icmp(V("blocks"), "EQ", 0, at_strike, slew)
        self.fz(c("mexp"))
        self.cmp(V("morph"), "GT", 0.0,
                 lambda: self.set(c("mexp"), (V("morph") * (Kc(1.0) - V("menv"))) * Kc(0.5)))
        self.set(V("menv"), V("menv") * onepole(mn(c("c_inv_t60") * Kc(1.0 / 0.35), 20.0), blocks=True))
        self.flushw(V("menv"))
        # body A's coefficients, then its block
        self.set(c("lf0"), c("f0") * c("bend"))
        self.set(c("linv"), c("c_inv_t60"))
        self.set(c("lpos"), c("c_pos"))
        self.set_body("A")
        self.rt("coeffs", lambda: self.coeffs())
        # the forces: a driven exciter with pressure this block and gain >= 1e-4
        self.iset(ci("drv"), 0)
        self.iset(ci("fa"), 0)
        self.iset(ci("fb"), 0)
        for which, gain, f in (("EA", "c_ga", "fa"), ("EB", "c_gb", "fb")):
            exw = lambda n, which=which: Mv("i", 2, VOICE[which] + EXC[n])
            self.iflag(exw("driven"), lambda exw=exw, gain=gain, f=f: self.icmp(exw("np"), "GT", 0, lambda: self.cmp(
                c(gain), "LT", 1e-4, None, lambda: (self.iset(ci(f), 1), self.iset(ci("drv"), 1)))))
        self.set_body("A")

        def plain_a():
            p.ld(0, C["hasx"])
            p.st(C["hasxb"], 0)
            self.iset(ci("sel"), A["X"])
            self.iset(ci("best"), A["OA"])
            self.set_body("A")
            self.rt("run_body", lambda: self.run_body())
        self.iflag(ci("drv"), lambda: self.rt("run_driven", lambda: self.run_driven()), plain_a)
        # BUZZ
        self.iset(ci("bzon"), 0)

        def buzz():
            self.iset(ci("bzon"), 1)
            self.set(c("tmp1"), Kc(0.25) * (Kc(1.0) - c("c_buzz")) + Kc(0.004))      # gap

            def j():
                self.set(c("tmp2"), rnd("vgauss"))                                    # nz[j]
                self.set(c("tmp3"), c("tmp2") - V("rattle"))                          # hp
                self.set(V("rattle"), c("tmp2"))
                self.set(c("tmp4"), mx(ab(J("OA")) - c("tmp1"), 0.0))                 # ex
                self.sign(c("tmp5"), J("OA"))
                self.set(J("BZ"), ((c("tmp3") * c("tmp4")) * Kc(0.8) + (c("tmp5") * c("tmp4")) * Kc(0.5))
                         * c("c_buzz"))
            self.jloop(j)
        self.cmp(c("c_buzz"), "GT", 0.0, buzz)
        # body B
        self.fill("OB", 0)

        def body_b():
            self.set(c("invtb"), c("c_inv_t60"))
            self.set(c("bb"), exp2((c("c_bend") * self.vb("B", "level") + c("ch")) * Kc(1.0 / 12.0)))
            self.iflag(ci("bzon"), lambda: self.jloop(lambda: self.set(J("XB"), J("X") + J("BZ") * Kc(0.5))),
                       lambda: self.jloop(lambda: self.set(J("XB"), J("X"))))
            p.ld(0, C["hasx"])
            p.ld(1, C["bzon"])
            p.iop(0, 0, "OR", 1)
            p.st(C["hasxb"], 0)
            xm = ci("c_xmod")

            def excite():
                self.jloop(lambda: self.set(J("XB"), (Kc(1.0) - c("c_coup")) * J("XB")
                                            + (c("c_coup") * mn(mx(J("OA"), -1.0), 1.0)) * Kc(0.5)))
                self.cmp(c("c_coup"), "GT", 0.0, lambda: self.jloop(
                    lambda: self.cmp(J("OA"), "NE", 0.0, lambda: self.iset(ci("hasxb"), 1))))

            def bendx():
                self.set(c("bb"), c("bb") * exp2(c("c_coup") * self.vb("A", "level")))

            def choke():
                self.set(c("invtb"), c("invtb") * (Kc(1.0) + (c("c_coup") * Kc(30.0)) * self.vb("A", "level")))
            self.icmp(xm, "EQ", 0, excite, lambda: self.icmp(xm, "EQ", 3, excite, lambda: self.icmp(
                xm, "EQ", 1, bendx, lambda: self.icmp(xm, "EQ", 2, choke))))
            self.set(c("lf0"), (c("f0") * V("bratio")) * c("bb"))
            self.set(c("linv"), c("invtb"))
            self.set(c("lpos"), c("c_pos") * Kc(0.73))
            self.set_body("B")
            self.rt("coeffs", lambda: self.coeffs())
            self.iset(ci("sel"), A["XB"])
            self.iset(ci("best"), A["OB"])
            self.set_body("B")
            self.rt("run_body", lambda: self.run_body())

            def trade():
                self.set(c("tmp0"), Kc(1.0) - c("c_coup") * Kc(0.002))            # s
                self.set(c("tmp0"), Kc(1.0) - c("tmp0"))                            # 1 - s
                self.set_body("A")

                def sc():
                    self.set(c("tmp1"), c("tmp0") * self.md("y"))
                    self.set(self.md("y"), self.md("y") - c("tmp1"))
                    self.set(self.md("d"), self.md("d") - c("tmp1"))
                self.mloop("cnt0", sc)
            self.icmp(xm, "EQ", 3, trade)
            self.jloop(lambda: self.set(self.OBP(), J("OB")), obp=True)
        self.icmp(V("kb"), "NE", OFF, body_b)
        # y = oa + ob (+ bz)
        self.jloop(lambda: self.set(J("Y"), J("OA") + J("OB")))
        self.iflag(ci("bzon"), lambda: self.jloop(lambda: self.set(J("Y"), J("Y") + J("BZ"))))
        # the flushes
        self.set_body("A")
        self.mloop("cnt0", self.flush_mode)
        self.icmp(V("kb"), "NE", OFF, lambda: (self.set_body("B"), self.mloop("cnt0", self.flush_mode)))
        for which in ("EA", "EB"):
            exw = lambda n, which=which: Mv("i", 2, VOICE[which] + EXC[n])

            def fl(exw=exw):
                for f in ("oq", "hold"):
                    self.flushw(exw(f))
                self.icmp(exw("kind"), "EQ", TYPES.index("BOW"), lambda: self.flushw(exw("grit")),
                          lambda: self.flushw(exw("breath")))
            self.iflag(exw("driven"), fl)
        # the IDLE rule: exciters done, the click done, the block and the bodies quiet
        self.iset(ci("ended"), 0)

        def maybe():
            self.peak_of("Y", "pk")

            def quiet():
                self.set_body("A")
                self.energy("ymax")

                def b_quiet():
                    self.iset(ci("ended"), 1)
                self.cmp(c("ymax"), "LT", kf("IDLE"), lambda: self.icmp(V("kb"), "NE", OFF, lambda: (
                    self.set_body("B"), self.energy("ymax"),
                    self.cmp(c("ymax"), "LT", kf("IDLE"), b_quiet)), b_quiet))
            self.cmp(c("pk"), "LT", kf("IDLE"), quiet)
        ck = lambda f: Mv("i", 2, VOICE["CK"] + CLK[f])
        clk_done = lambda then: self.iflag(V("clk"), lambda: (
            self.ld(0, ck("k")), self.ld(1, ck("len")), p.if_(0, "GE", 1, then, kind="i")), then)
        self.iflag(ci("excdone"), lambda: clk_done(maybe))
        # the click, straight to the output
        self.iflag(V("clk"), lambda: (self.ld(0, ck("k")), self.ld(1, ck("len")),
                                      p.if_(0, "LT", 1, lambda: self.rt("click", lambda: self.click()), kind="i")))
        # the DC block
        self.set(c("x1"), V("dc_x"))
        self.set(c("y1"), V("dc_y"))

        def dc():
            self.set(c("y1"), (J("Y") - c("x1")) + Kc(kf("DC_A")) * c("y1"))
            self.set(c("x1"), J("Y"))
            self.set(J("Z"), c("y1"))
        self.jloop(dc)
        self.set(V("dc_x"), c("x1"))
        self.set(V("dc_y"), c("y1"))
        self.flushw(V("dc_y"))
        # the level guard
        self.peak_of("Z", "pk")
        self.cmp(c("pk"), "GT", V("lim"), lambda: self.set(V("lim"), c("pk")),
                 lambda: self.set(V("lim"), V("lim") * Kc(kf("LIM_KR"))))

        def guard():
            self.set(c("tmp0"), Kc(kf("LIM_TH")) * recip(V("lim")))
            self.jloop(lambda: self.set(J("Z"), J("Z") * c("tmp0")))
        self.cmp(V("lim"), "GT", kf("LIM_TH"), guard)
        self.rt("post", lambda: self.post())
        self.ld(8, V("blocks"))
        p.iconst(12, 1)
        p.iop(8, 12, "+", 8)
        self.st(V("blocks"), 8)
        # the fault test: a state non-finite or past GUARD, or the output non-finite -> rest
        self.iset(ci("pon"), 0)
        self.set_body("A")
        self.rt("bad", lambda: self.bad_body())
        self.icmp(V("kb"), "NE", OFF, lambda: (self.set_body("B"), self.rt("bad", lambda: self.bad_body())))

        def zbad():
            self.ld(0, J("Z"))
            p.lsh(0, 0, -23)
            p.iconst(1, 0xFF)
            p.iop(0, 0, "AND", 1)
            p.if_(0, "EQ", 1, lambda: self.iset(ci("pon"), 1), kind="i")
        self.jloop(zbad)

        def fault():
            self.iset(V("on"), 0)
            self.fill("Z", 0)
        self.iflag(ci("pon"), fault)
        self.iflag(ci("ended"), lambda: self.iset(V("on"), 0))

    def sign(self, dst: Mv, x: Mv) -> None:
        """np.sign: 1, -1, or +0 (for either zero)"""
        self.fz(dst)
        self.cmp(x, "GT", 0.0, lambda: self.set(dst, Kc(1.0)),
                 lambda: self.cmp(x, "LT", 0.0, lambda: self.set(dst, Kc(-1.0))))

    def peak_of(self, arr: str, word: str) -> None:
        """C[word] = max |ARR| (np.max(np.abs(..)))"""
        p, C, L = self.p, self.L.C, self.L
        p.iconst(0, L.A[arr])
        p.seti(1, 0)
        p.ldpost(5, 1)
        p.iconst(6, 0x7FFFFFFF)
        p.iop(5, 5, "AND", 6)

        def s():
            p.ldpost(7, 1)
            p.iop(7, 7, "AND", 6)
            p.fop(5, 5, "MAX", 7)
        p.loop_r(10, BLOCK - 1, s, one=11)
        p.st(C[word], 5)

    def flush_mode(self) -> None:
        md = self.md
        self.cmp(ab(md("y")), "LT", kf("FLOOR"), lambda: self.cmp(ab(md("d")), "LT", kf("FLOOR"), lambda: (
            self.fz(md("y")), self.fz(md("d")))))

    def energy(self, word: str) -> None:
        """C[word] = max |y| + max |y - d| over the body's modes (I0)"""
        c, md = self.c, self.md
        self.fz(c("dmax"))
        self.fz(c(word))

        def m():
            self.set(c(word), mx(c(word), ab(md("y"))))
            self.set(c("dmax"), mx(c("dmax"), ab(md("y") - md("d"))))
        self.mloop("cnt0", m)
        self.set(c(word), c(word) + c("dmax"))

    def bad_body(self) -> None:
        """pon = 1 if a mode's y or d is non-finite or not under GUARD (1e4): integer
        compares of the magnitudes' bits (a NaN's are above every finite's)"""
        p = self.p
        md = self.md

        def m():
            for f in ("y", "d"):
                self.ld(0, md(f))
                p.iconst(1, 0x7FFFFFFF)
                p.iop(0, 0, "AND", 1)
                p.iconst(1, bits(1.0e4))
                p.if_(0, "GE", 1, lambda: self.iset(self.ci("pon"), 1), kind="i")
        self.mloop("cnt0", m)

    # -- a body's coefficients (live.Body.coeffs, and retune) --------------------------------
    def coeffs(self) -> None:
        """I0 = the body (u2); lf0 = f0 x bend, lgeom = c_geom_e, linv, c_matl, loss, lpos,
        c_tilt, mexp; retune: re-express the state for the new pitch"""
        p, C = self.p, self.L.C
        c, bd, md, tm, ci = self.c, self.bd, self.md, self.tm, self.ci
        self.ev(mn(mx(c("c_matl") + bd("bias"), 0.0), 1.0), 0)
        p.st(C["mt"], 0)
        self.set(c("omt"), Kc(1.0) - c("mt"))
        self.set(c("a1"), Kc(4.0) * (c("omt") * c("omt")) + Kc(0.015))
        self.set(c("a2"), Kc(2.0) * ((c("omt") * c("omt")) * c("omt")) + Kc(0.002))
        self.set(c("ltilt"), Kc(-0.7) * c("c_tilt"))
        self.set(c("lpos"), c("lpos") * Kc(0.5))
        p.iconst(0, NEG0)
        p.st(C["S"], 0)
        p.st(C["Wsum"], 0)
        self.ld(0, bd("ogok"))
        self.st(bd("ogokp"), 0)

        def pass1():
            self.set(c("q0"), rnd("vbi") * bd("dsig"))                          # inc
            self.set(md("drift"), md("drift") * Kc(0.995) + c("q0"))
            lr = c("q1")
            self.set(lr, c("c_geom_e") * md("L"))
            self.set(c("q2"), exp2(lr) * (Kc(1.0) + md("drift")))              # ratio
            self.set(c("q3"), c("q2") * c("lf0") + md("offs"))                 # f
            p.fconst(0, 0.0)
            self.st(tm("phi"), 0)                                               # alive
            self.cmp(c("q3"), "LT", kf("F_HI"), lambda: self.cmp(c("q3"), "GT", kf("F_LO"), lambda: (
                p.fconst(0, 1.0), self.st(tm("phi"), 0))))
            self.set(c("q3"), mn(mx(c("q3"), kf("F_LO")), kf("F_HI")))
            self.set(c("q4"), c("q3") * Kc(kf("H_SCALE")))                     # h
            self.set(c("q5"), sinp(c("q4")))                                   # s
            self.set(c("q6"), (Kc(2.0) * c("q5")) * cosp(c("q4")))             # sw
            self.set(c("q3"), c("q3") * Kc(0.001))                              # fk
            self.set(c("q7"), (c("q3") * c("a2") + c("a1")) * c("q3") + Kc(1.0))   # den
            self.set(c("q8"), c("loss") * mx(c("q2") - Kc(1.0), 0.0) + Kc(1.0))   # lf
            self.set(c("q9"), mn((c("linv") * c("q7")) * c("q8"), 1000.0))     # inv
            self.cmp(tm("phi"), "EQ", 0.0, lambda: self.set(c("q9"), Kc(1000.0)))
            self.set(c("q0"), -expm1(c("q9") * Kc(kf("C_DECAY"))))              # q = 1 - r
            self.set(tm("m"), c("q0") * (Kc(2.0) - c("q0")))
            self.set(c("q4"), c("q5") * c("q5"))                                # s2
            self.set(tm("k"), c("q0") * c("q0") + Kc(4.0) * ((Kc(1.0) - c("q0")) * c("q4")))

            def retune():
                self.set(c("q7"), md("d") - (Kc(2.0) * md("s2")) * md("y"))
                self.set(md("d"), (Kc(2.0) * c("q4")) * md("y") + c("q7") * (c("q6") * recip(mx(md("sw"), 1e-6))))
            self.iflag(ci("retune"), retune)
            self.set(md("s2"), c("q4"))
            self.set(md("sw"), c("q6"))
            self.sp_of(c("q3"), lr, c("q2"))
            self.set(c("q3"), ab(sin_t(frac(c("q3") * c("lpos")))))            # sh
            self.set(tm("b"), (c("q3") * exp2(lr * c("ltilt"))) * md("aj"))    # shape
            self.set(c("S"), c("S") + tm("b"))
            self.set(tm("ogp"), md("og"))

            def morph():
                self.set(md("og"), exp2(lr * c("mexp")))                        # we
                self.set(c("Wsum"), c("Wsum") + md("og") * md("mult"))
            self.cmp(c("mexp"), "GT", 0.0, morph)
        self.mloop("cnt0", pass1)
        self.set(c("gn"), Kc(kf("OUT")) * recip(mx(c("S"), 1e-6)))
        self.iset(bd("ogok"), 0)

        def ogn():
            self.iset(bd("ogok"), 1)
            self.set(c("Wsum"), bd("nfull") * recip(c("Wsum")))
        self.cmp(c("mexp"), "GT", 0.0, ogn)

        def pass2():
            self.cmp(tm("phi"), "EQ", 0.0, lambda: self.fz(c("q0")),
                     lambda: self.set(c("q0"), tm("b") * c("gn")))             # amp
            self.set(tm("b"), c("q0") * md("sw"))
            self.set(tm("phi"), c("q0") * Kc(kf("OUT4")))
            self.iflag(bd("ogok"), lambda: self.set(md("og"), md("og") * c("Wsum")))
        self.mloop("cnt0", pass2)

    # -- a body's block (live.Body.run, _out, _done) ----------------------------------------
    def run_body(self) -> None:
        """I0 = the body (u2); hasxb: driven by the input; sel: the input array; best: the
        output array (the sum over modes, from -0, weighted by MORPH's og)"""
        p, C, L = self.p, self.L.C, self.L
        c, bd, md, tm, ci = self.c, self.bd, self.md, self.tm, self.ci
        p.ld(0, C["best"])
        p.seti(1, 0)
        p.iconst(5, NEG0)
        p.loop_r(10, BLOCK, lambda: p.stpost(1, 5), one=11)
        # the weights: 0 none, 1 og, 2 og ramping from og_prev
        p.iconst(0, 0)
        p.st(C["ramp"], 0)

        def ogw():
            p.iconst(0, 1)
            p.st(C["ramp"], 0)
            self.iflag(ci("ramp_og"), lambda: self.iflag(bd("ogokp"), lambda: (p.iconst(0, 2), p.st(C["ramp"], 0))))
        self.iflag(bd("ogok"), ogw)

        def mode():
            def variant(inp: bool, og: int):
                for f, r in (("y", 0), ("d", 1)):
                    self.ld(r, md(f))
                for f, r in (("m", 2), ("k", 3), ("b", 4)):
                    self.ld(r, tm(f))
                self.ld(5, md("og"))
                self.ld(6, tm("ogp"))
                p.fop(6, 5, "-", 6)                 # og - og_prev
                self.ld(7, tm("ogp"))
                # (post-modified: I4 the input, I1 the output, I2 the ramp; I2 is put back after)
                p.ld(12, C["sel"])
                p.seti(4, 12)
                p.ld(12, C["best"])
                p.seti(1, 12)
                if og == 2:
                    p.fpass(5, 7)               # F5 = og_prev, F6 = og - og_prev
                    p.iconst(12, L.A["RJ"])
                    p.seti(2, 12)

                def s():
                    p.fop(7, 2, "*", 1)
                    p.fop(1, 1, "-", 7)
                    p.fop(7, 3, "*", 0)
                    p.fop(1, 1, "-", 7)
                    if inp:
                        p.ldpost(8, 4)
                        p.fop(7, 4, "*", 8)
                        p.fop(1, 1, "+", 7)
                    p.fop(0, 0, "+", 1)
                    src = 0
                    if og == 1:
                        p.fop(7, 0, "*", 5)
                        src = 7
                    elif og == 2:
                        p.ldpost(12, 2)
                        p.fop(12, 6, "*", 12)
                        p.fop(12, 5, "+", 12)
                        p.fop(7, 0, "*", 12)
                        src = 7
                    p.ldi(9, 0, 1)
                    p.fop(9, 9, "+", src)
                    p.stpost(1, 9)
                p.loop_r(10, BLOCK // 2, lambda: (s(), s()), one=11)

            def by_og(inp):
                p.ld(12, C["ramp"])
                p.iconst(13, 1)
                p.if_(12, "EQ", 13, lambda: fast(inp, 1),
                      lambda: (p.iconst(13, 2), p.if_(12, "EQ", 13, lambda: slow(inp),
                                                       lambda: fast(inp, 0), kind="i")), kind="i")

            def slow(inp):
                variant(inp, 2)
                self.ptr(2, "vbase")
                self.ptr(3, "u0")
                self.st(md("y"), 0)
                self.st(md("d"), 1)

            def fast(inp: bool, og: int):
                """v0.45: the same sums, five to seven instructions a sample: the multiplies
                beside the adds (mfop), the loads and stores beside the computes (fopm).
                k F0, b F1, m F2, og F3, y F4, x F5, the sum F6, og y F7, d F8, out F9,
                m d F12, k y F13, b x F14; I1 reads the output, I4 writes it a sample
                behind (primed with its word before: rewritten as it was), I2 the input"""
                for r_, f in ((0, "k"), (1, "b"), (2, "m")):
                    self.ld(r_, tm(f))
                self.ld(4, md("y"))
                self.ld(8, md("d"))
                if og:
                    self.ld(3, md("og"))
                p.ld(12, C["best"])
                p.seti(1, 12)
                p.iconst(13, -4)
                p.iop(12, 12, "+", 13)
                p.seti(4, 12)
                p.ldi(6, -1, 1)                     # the word before: stored back unchanged
                if inp:
                    p.ld(12, C["sel"])
                    p.seti(2, 12)
                    p.ldpost(5, 2)                  # x[0]

                def s():
                    p.fopm(12, 2, "*", 8, ("st", 4, 6))          # m d; the last sum out
                    p.mfop(13, 0, 4, 8, 8, "-", 12)              # k y; d -= m d
                    if inp:
                        p.mfop(14, 1, 5, 8, 8, "-", 13)          # b x; d -= k y
                        p.fopm(8, 8, "+", 14, ("ld", 5, 2))      # d += b x; the next x
                    else:
                        p.fop(8, 8, "-", 13)                     # d -= k y
                    p.fopm(4, 4, "+", 8, ("ld", 9, 1))           # y += d; out[j]
                    if og:
                        p.fop(7, 3, "*", 4)                      # og y
                        p.fop(6, 9, "+", 7)
                    else:
                        p.fop(6, 9, "+", 4)
                p.loop_r(10, BLOCK // 4, lambda: (s(), s(), s(), s()), one=11)
                p.stpost(4, 6)
                self.ptr(2, "vbase")
                self.ptr(3, "u0")
                self.st(md("y"), 4)
                self.st(md("d"), 8)
            p.ld(12, C["hasxb"])
            p.ifz(12, "NE", lambda: by_og(True), lambda: by_og(False))
        self.mloop("cnt0", mode)
        self.done_body()

    def done_body(self) -> None:
        """live.Body._done on the output array ('best'): peak, level"""
        p, C = self.p, self.L.C
        c, bd = self.c, self.bd
        self.ptr(0, "u2")
        p.ld(0, C["best"])
        p.seti(1, 0)
        p.ldpost(5, 1)
        p.iconst(6, 0x7FFFFFFF)
        p.iop(5, 5, "AND", 6)

        def s():
            p.ldpost(7, 1)
            p.iop(7, 7, "AND", 6)
            p.fop(5, 5, "MAX", 7)
        p.loop_r(10, BLOCK - 1, s, one=11)
        p.st(C["pk"], 5)
        self.set(bd("peak"), mx(bd("peak"), c("pk")))
        self.set(bd("level"), c("pk") * recip(bd("peak")))

    def run_driven(self) -> None:
        """live.Body.run_driven on body A (I0): every sample, v = 40 sum(phi d), the force(s)
        from it (+ x), then every mode; OA = the sum over modes (weighted as run_body)"""
        p, C, L = self.p, self.L.C, self.L
        c, bd, ci, J = self.c, self.bd, self.ci, self.J
        exa = lambda n: Mv("i", 2, VOICE["EA"] + EXC[n])
        exb = lambda n: Mv("i", 2, VOICE["EB"] + EXC[n])
        # the forces' constants
        for f, exw, g in (("fa", exa, "c_ga"), ("fb", exb, "c_gb")):
            def consts(exw=exw, g=g, f=f):
                self.set(c(f"{f}_s"), Kc(1.5) + Kc(6.0) * (Kc(1.0) - c("c_hard")))
                self.set(c(f"{f}_g"), (Kc(4.0) * c(g)) * (Kc(0.5) + Kc(1.5) * c("c_hard")))
                self.icmp(exw("kind"), "EQ", TYPES.index("BLOW"), lambda: self.set(c(f"{f}_g"), Kc(0.03) * c(g)))
            self.iflag(ci(f), consts)
        p.iconst(0, 0)
        p.st(C["ramp"], 0)

        def ogw():
            p.iconst(0, 1)
            p.st(C["ramp"], 0)
            self.iflag(ci("ramp_og"), lambda: self.iflag(bd("ogokp"), lambda: (p.iconst(0, 2), p.st(C["ramp"], 0))))
        self.iflag(bd("ogok"), ogw)
        # n, the modes' first record and coefficients
        p.ldi(0, BODY["n"], 0)
        p.iconst(1, 1)
        p.iop(0, 0, "MAX", 1)
        p.iconst(1, NMAX)
        p.iop(0, 0, "MIN", 1)
        p.st(C["nn"], 0)
        self._mstart()

        def j():
            # v = 40 sum(phi d), from -0
            p.ld(10, C["u0"])
            p.ld(11, C["u1"])
            p.ld(9, C["nn"])
            p.iconst(0, NEG0)

            def vm():
                p.seti(3, 10)
                p.seti(0, 11)
                p.ldi(1, TMODE.index("phi"), 0)
                p.ldi(2, MODE["d"], 3)
                p.fop(1, 1, "*", 2)
                p.fop(0, 0, "+", 1)
                p.iconst(12, 4 * MW)
                p.iop(10, 12, "+", 10)
                p.iconst(12, 4 * TW)
                p.iop(11, 12, "+", 11)
            p.loop_r(9, None, vm, one=12)
            p.fconst(1, 40.0)
            p.fop(0, 0, "*", 1)
            p.st(C["vv"], 0)
            # the force at j
            self.fz(c("tmp4"))
            first = [True]
            for f, exw, pa, da in (("fa", exa, "P0", "D0"), ("fb", exb, "P1", "D1")):
                def force(f=f, exw=exw, pa=pa, da=da):
                    self.fz(c("tmp3"))

                    def inside():
                        def bow():
                            self.set(c("tmp0"), J(da) - c("vv"))                         # dv
                            self.set(c("tmp1"), ab(c("tmp0") * c(f"{f}_s")) + Kc(0.75))  # y
                            self.set(c("tmp1"), c("tmp1") * c("tmp1"))
                            self.set(c("tmp1"), mn(mx(c("tmp1") * c("tmp1"), kf("BOW_LO")), kf("BOW_HI")))
                            self.set(c("tmp1"), mn(mx(Kc(0.25) * recip(c("tmp1")), 0.0025), 0.245))
                            self.set(c("tmp3"), ((c("tmp0") * c("tmp1")) * J(pa)) * c(f"{f}_g"))

                        def blow():
                            self.set(c("tmp0"), J(pa) - c("vv") * Kc(0.6))               # dp
                            self.set(c("tmp3"), (c("tmp0") * mx(0.0, Kc(1.0) - ab(c("tmp0")) * Kc(0.9)))
                                     * c(f"{f}_g"))
                        self.icmp(exw("kind"), "EQ", TYPES.index("BOW"), bow, blow)
                    self.ld(0, exw("np"))
                    p.ld(1, C["jj"])
                    p.if_(1, "LT", 0, inside, kind="i")
                self.iflag(ci(f), force)
                # live: one force alone, or fa + fb
                if f == "fa":
                    self.iflag(ci("fa"), lambda: self.set(c("tmp4"), c("tmp3")))
                else:
                    self.iflag(ci("fb"), lambda: self.iflag(ci("fa"), lambda: self.set(c("tmp4"), c("tmp4") + c("tmp3")),
                                                            lambda: self.set(c("tmp4"), c("tmp3"))))
            self.iflag(ci("hasx"), lambda: self.set(c("tmp4"), c("tmp4") + J("X")))
            # every mode, the sum
            p.ld(5, C["tmp4"])                 # f_j
            p.ld(10, C["u0"])
            p.ld(11, C["u1"])
            p.ld(9, C["nn"])
            p.iconst(8, NEG0)
            p.ld(6, C["jj"])                   # r_j (the ramp's)
            p.lsh(6, 6, 2)
            p.iconst(12, L.A["RJ"])
            p.iop(6, 12, "+", 6)
            p.seti(1, 6)
            p.ldi(6, 0, 1)

            def um(og: int):
                def m():
                    p.seti(3, 10)
                    p.seti(0, 11)
                    p.ldi(0, MODE["y"], 3)
                    p.ldi(1, MODE["d"], 3)
                    p.ldi(2, TMODE.index("m"), 0)
                    p.fop(2, 2, "*", 1)
                    p.fop(1, 1, "-", 2)
                    p.ldi(2, TMODE.index("k"), 0)
                    p.fop(2, 2, "*", 0)
                    p.fop(1, 1, "-", 2)
                    p.ldi(2, TMODE.index("b"), 0)
                    p.fop(2, 2, "*", 5)
                    p.fop(1, 1, "+", 2)
                    p.fop(0, 0, "+", 1)
                    p.sti(MODE["y"], 3, 0)
                    p.sti(MODE["d"], 3, 1)
                    if og == 1:
                        p.ldi(2, MODE["og"], 3)
                        p.fop(0, 0, "*", 2)
                    elif og == 2:
                        p.ldi(2, TMODE.index("ogp"), 0)
                        p.ldi(3, MODE["og"], 3)
                        p.fop(3, 3, "-", 2)
                        p.fop(3, 3, "*", 6)
                        p.fop(2, 2, "+", 3)
                        p.fop(0, 0, "*", 2)
                    p.fop(8, 8, "+", 0)
                    p.iconst(12, 4 * MW)
                    p.iop(10, 12, "+", 10)
                    p.iconst(12, 4 * TW)
                    p.iop(11, 12, "+", 11)
                p.loop_r(9, None, m, one=12)
            p.ld(12, C["ramp"])
            p.iconst(13, 1)
            p.if_(12, "EQ", 13, lambda: um(1), lambda: (p.iconst(13, 2), p.if_(12, "EQ", 13, lambda: um(2),
                                                                                  lambda: um(0), kind="i")), kind="i")
            p.fpass(0, 8)
            self.st(J("OA"), 0)
        self.jloop(j, need_j=True)
        self.iset(ci("best"), L.A["OA"])
        self.done_body()

    # -- the click (live.Click.block) --------------------------------------------------------
    def click(self) -> None:
        """the click's block into W (zeros past its end), then Y += W"""
        p, C = self.p, self.L.C
        c, J = self.c, self.J
        ck = lambda f: Mv("i", 3, CLK[f])
        self.base(3, "CK")
        self.fill("W", 0)

        def j():
            def one():
                kind = ck("kind")

                def hann(at: str, dst: str):
                    """0.5 - 0.5 cos_t(F(at) ninv) for 0 <= at < n, else 0"""
                    self.fz(c(dst))
                    p.ld(0, C[at])
                    self.ld(1, ck("n"))
                    p.if_(0, "LT", 1, lambda: p.ifz(0, "GE", lambda: self.set(
                        c(dst), Kc(0.5) - Kc(0.5) * cos_t(fi(self.ci(at)) * ck("ninv")))), kind="i")

                def snap():
                    self.ld(0, ck("k"))
                    p.st(C["q8"], 0)
                    p.iconst(12, -1)
                    p.iop(0, 12, "+", 0)
                    p.st(C["q9"], 0)
                    hann("q8", "tmp0")
                    hann("q9", "tmp1")
                    self.set(c("tmp2"), (c("tmp0") - c("tmp1")) * ck("gain"))

                def tick():
                    self.set(c("tmp2"), sin_t(ck("ph")) * ck("e"))
                    self.set(ck("ph"), frac(ck("ph") + ck("inc")))
                    self.set(ck("e"), ck("e") * ck("ke"))

                def noise():
                    self.set(c("tmp0"), rnd("vgauss"))
                    self.set(c("tmp2"), ((c("tmp0") - ck("prev")) * ck("e")) * Kc(0.5))
                    self.set(ck("prev"), c("tmp0"))
                    self.set(ck("e"), ck("e") * ck("ke"))

                def thump():
                    self.set(ck("ph"), frac(ck("ph") + (Kc(40.0) + Kc(50.0) * ck("pe")) * Kc(kf("INVR"))))
                    self.set(ck("pe"), ck("pe") * ck("kp"))
                    self.set(c("tmp2"), sin_t(ck("ph")) * ck("e"))
                    self.set(ck("e"), ck("e") * ck("ke"))
                self.icmp(kind, "EQ", 0, snap, lambda: self.icmp(kind, "EQ", 1, tick, lambda: self.icmp(
                    kind, "EQ", 2, noise, thump)))
                self.set(J("W"), c("tmp2") * ck("level"))
                self.ld(8, ck("k"))
                p.iconst(12, 1)
                p.iop(8, 12, "+", 8)
                self.st(ck("k"), 8)
            self.ld(0, ck("k"))
            self.ld(1, ck("len"))
            p.if_(0, "LT", 1, one, kind="i")
        self.jloop(j)
        self.jloop(lambda: self.set(J("Y"), J("Y") + J("W")))

    # -- after the bodies (live.Voice._post) -------------------------------------------------
    def kchain(self, word: str, fns) -> None:
        """dispatch on the int scratch word WORD: fns[k]() for WORD == k (None: nothing)"""
        def at(k):
            if k == len(fns) - 1:
                if fns[k]:
                    fns[k]()
                return
            self.icmp(self.ci(word), "EQ", k, fns[k] or (lambda: None), lambda: at(k + 1))
        at(0)

    def post(self) -> None:
        """RING, SHIFT, FORM, WATR, FOLD, CHAR, the VCA (each crossfading over FADE blocks when
        switched mid-note), then the knee. Z in and out; OA, OB are ra, rb."""
        p, C, L = self.p, self.L.C, self.L
        c, ci, V, J = self.c, self.ci, self.V, self.J
        self.iset(ci("first"), 0)
        self.icmp(V("blocks"), "EQ", 0, lambda: self.iset(ci("first"), 1))
        self.set(c("kv"), onepole(mn(c("c_inv_t60"), 100.0)))
        ons = (("Q_RING", "GT", 0), ("Q_SHIFT", "NE", 64), ("Q_FORM", "GT", 0), ("Q_WATR", "GT", 0),
               ("Q_FOLD", "GT", 0), ("Q_CHAR", "GT", 0), ("Q_LPG", "GT", 0))
        assert VOICE["parok"] + 6 < 64
        for k, st in enumerate(POST):
            lvw = Mv("i", 2, VOICE["lv"] + k)
            parw = Mv("i", 2, VOICE["par"] + k)
            okw = Mv("i", 2, VOICE["parok"] + k)
            q, cond, v = ons[k]
            self.iset(ci("pon"), 0)
            self.icmp(ci(q), cond, v, lambda: self.iset(ci("pon"), 1))
            self.set(c("lv0"), lvw)
            self.rt("lvstep", self.lvstep)
            self.set(lvw, c("lv1"))
            ramped = st in ("ring", "fold", "char", "vca")
            if ramped:                          # p0: the last setting, set before, not the first block
                self.iset(ci("pmove"), 0)
                self.set(c("p0"), parw)
                self.iflag(okw, lambda: self.iflag(ci("first"), None, lambda: self.iset(ci("pmove"), 1)))
            self.iflag(ci("pon"), lambda st=st, parw=parw, okw=okw: (self.par_of(st, parw), self.iset(okw, 1)))
            self.set(c("pcur"), parw)
            if ramped:                          # moved: p0 != par
                self.iflag(ci("pmove"), lambda: self.cmp(c("p0"), "EQ", c("pcur"), lambda: self.iset(ci("pmove"), 0)))
            if st == "vca":                     # the VCA's envelope runs every block: g[j] = e, e x= kv
                self.set(c("tmp0"), V("venv"))

                def env():
                    self.set(J("P1"), c("tmp0"))
                    self.set(c("tmp0"), c("tmp0") * c("kv"))
                self.jloop(env)
                self.set(V("venv"), c("tmp0"))
                self.flushw(V("venv"))

            def drop(st=st):
                if st == "shift":
                    self.iset(V("sh_on"), 0)
                elif st == "form":
                    self.iset(V("fo_on"), 0)
                    self.iset(Mv("i", 2, VOICE["FO"] + FORM["wetok"]), 0)
                elif st == "watr":
                    self.iset(V("wa_on"), 0)

            def stage(st=st):
                self.stage(st, c("pcur"))
                self.rt("mix", self.mix)
            # both levels 0: the stage is dropped (its state goes), else it runs and is mixed
            self.cmp(c("lv0"), "EQ", 0.0, lambda: self.cmp(c("lv1"), "EQ", 0.0, drop, stage), stage)
        # the knee
        self.jloop(lambda: self.set(J("Z"), tanh(J("Z") * Kc(1.5)) * Kc(kf("I15"))))

    def lvstep(self) -> None:
        """a stage's levels: the first block lv0 = lv1 = on; else lv1 = lv0 -+ FADE_STEP, clamped"""
        c, ci = self.c, self.ci

        def first():
            self.fz(c("lv0"))
            self.iflag(ci("pon"), lambda: self.set(c("lv0"), Kc(1.0)))
            self.set(c("lv1"), c("lv0"))

        def later():
            self.iflag(ci("pon"), lambda: self.set(c("lv1"), mn(c("lv0") + Kc(kf("FADE_STEP")), 1.0)),
                       lambda: self.set(c("lv1"), mx(c("lv0") - Kc(kf("FADE_STEP")), 0.0)))
        self.iflag(ci("first"), first, later)

    def mix(self) -> None:
        """z = w, or z + r (w - z) while fading (r from lv0 to lv1 across the block)"""
        c, J = self.c, self.J

        def whole():
            self.jloop(lambda: self.set(J("Z"), J("W")))

        def fading():
            self.set(c("tmp1"), c("lv1") - c("lv0"))
            self.jloop(lambda: self.set(J("Z"), J("Z") + (c("lv0") + c("tmp1") * self.ramp_j())
                                        * (J("W") - J("Z"))))
        self.cmp(c("lv0"), "EQ", 1.0, lambda: self.cmp(c("lv1"), "EQ", 1.0, whole, fading), fading)

    def ramp_j(self) -> Mv:
        """the ramp (j + 1)/32 at j, in a jloop: the RAMP table's copy in scratch (RJ)"""
        return self.J("RJ")

    def par_of(self, st: str, parw: Mv) -> None:
        c, ci = self.c, self.ci
        if st == "ring":
            self.set(parw, c("c_uring"))
        elif st == "shift":
            self.set(c("tmp0"), (fi(ci("Q_SHIFT")) - Kc(64.0)) * Kc(1.0 / 63.0))              # s
            self.set(c("tmp1"), Kc(5.0) * exp2(ab(c("tmp0")) * Kc(kf("L400"))))              # hz
            self.cmp(c("tmp0"), "GT", 0.0, lambda: self.set(parw, c("tmp1") * Kc(kf("INVR"))),
                     lambda: self.set(parw, (-c("tmp1")) * Kc(kf("INVR"))))
        elif st == "form":
            self.ld(0, ci("Q_FORM"))
            self.st(parw, 0)
        elif st == "watr":
            self.set(parw, c("c_uwatr"))
        elif st == "fold":
            self.set(parw, c("c_ufold"))
        elif st == "char":
            self.set(parw, c("c_uchar"))
        else:
            self.set(parw, c("c_ulpg"))

    def stage(self, st: str, parw: Mv) -> None:
        """one stage's output into W (live.Voice._stage); pmove: ramp from p0"""
        p, C, L = self.p, self.L.C, self.L
        c, ci, V, J = self.c, self.ci, self.V, self.J
        if st == "ring":
            def dj():
                self.iflag(ci("pmove"), lambda: self.set(c("tmp0"), c("p0") + (parw - c("p0")) * self.ramp_j()),
                           lambda: self.set(c("tmp0"), parw))

            # the carrier: B's block x 8, or (B off) a sine at f0 sqrt 2; then one formula
            self.set(c("tmp2"), (c("f0") * Kc(kf("SQ2"))) * Kc(kf("INVR")))

            def j():
                dj()

                def osc():
                    self.set(c("tmp3"), sin_t(V("ring_ph")))
                    self.set(V("ring_ph"), frac(V("ring_ph") + c("tmp2")))
                self.icmp(V("kb"), "NE", OFF, lambda: self.set(c("tmp3"), J("OB") * Kc(8.0)), osc)
                self.set(J("W"), J("Z") * (Kc(1.0) - c("tmp0"))
                         + (tanh(J("OA") * Kc(8.0)) * tanh(c("tmp3"))) * (Kc(0.25) * c("tmp0")))
            self.jloop(j)
        elif st == "shift":
            self.rt("shift", lambda: self.shift(parw))
        elif st == "form":
            self.rt("form", lambda: self.form(parw))
        elif st == "watr":
            self.rt("water", lambda: self.water(parw))
        elif st in ("fold", "char"):
            # (live computes the shape at par, then at p0 when it moved: the same values either
            # way; here at p0 first, kept in E, so the shape's code is there once)
            def moved():
                self.set(c("sfc"), c("p0"))
                self.rt(st, lambda: self.shape(st))
                self.jloop(lambda: self.set(J("E"), J("W")))
            self.iflag(ci("pmove"), moved)
            self.set(c("sfc"), parw)
            self.rt(st, lambda: self.shape(st))
            self.iflag(ci("pmove"), lambda: self.jloop(
                lambda: self.set(J("W"), J("E") + self.ramp_j() * (J("W") - J("E")))))
        else:
            def j():
                self.iflag(ci("pmove"), lambda: self.set(c("tmp0"), c("p0") + (parw - c("p0")) * self.ramp_j()),
                           lambda: self.set(c("tmp0"), parw))
                self.set(J("W"), J("Z") * ((Kc(1.0) - c("tmp0") * Kc(0.5)) + (c("tmp0") * Kc(0.5)) * J("P1")))
            self.jloop(j)

    def shape(self, st: str) -> None:
        """live.Voice._shape: FOLD or CHAR of Z at the setting in sfc, into W"""
        c, J = self.c, self.J
        par = c("sfc")
        if st == "fold":
            self.set(c("tmp0"), Kc(1.0) + Kc(8.0) * par)
            self.set(c("tmp1"), (c("tmp0") * Kc(4.0)) * Kc(kf("FOLDK")))
            self.set(c("tmp2"), Kc(0.25) * (Kc(1.0) - par * Kc(0.3)))
            self.jloop(lambda: self.set(J("W"), sin_t(frac(J("Z") * c("tmp1"))) * c("tmp2")))
        else:
            self.set(c("tmp0"), Kc(1.0) + Kc(20.0) * (par * par))
            self.set(c("tmp1"), Kc(0.1) * par)
            self.set(c("tmp2"), recip(tanh(c("tmp0"))))
            self.set(c("tmp3"), tanh(c("tmp1")))
            self.jloop(lambda: self.set(J("W"), tanh(J("Z") * c("tmp0") + c("tmp1")) * c("tmp2") - c("tmp3")))

    def shift(self, parw: Mv) -> None:
        """live.Shifter: the Hilbert pair and the quadrature oscillator, W = the shifted Z"""
        p, C, L = self.p, self.L.C, self.L
        c, V, J = self.c, self.V, self.J
        sh = lambda f, k=0: Mv("i", 3, SHF[f] + k)
        self.base(3, "SH")

        def init():
            for f in ("in1", "in2", "ph", "iprev"):
                self.fz(sh(f))
            for f in ("ay1", "ay2", "by1", "by2"):
                for k in range(4):
                    self.fz(sh(f, k))
            self.iset(V("sh_on"), 1)
        self.iflag(V("sh_on"), None, init)
        A2 = L.TB["A2"]
        B2 = L.TB["B2"]
        self.set(c("tmp5"), parw)

        def j():
            x = J("Z")
            for ch, cs, y1, y2, out in (("a", A2, "ay1", "ay2", "tmp0"), ("b", B2, "by1", "by2", "tmp1")):
                self.set(c("tmp2"), x)                        # x
                self.set(c("tmp3"), sh("in2"))                # old2
                for i in range(4):
                    self.set(c("tmp4"), Mv("a", cs + 4 * i) * (c("tmp2") + sh(y2, i)) - c("tmp3"))
                    self.set(c("tmp3"), sh(y2, i))
                    self.set(sh(y2, i), sh(y1, i))
                    self.set(sh(y1, i), c("tmp4"))
                    self.set(c("tmp2"), c("tmp4"))
                self.set(c(out), c("tmp2"))
            self.set(sh("in2"), sh("in1"))
            self.set(sh("in1"), x)
            self.set(c("tmp2"), sh("iprev"))                  # i
            self.set(sh("iprev"), c("tmp0"))
            self.set(J("W"), c("tmp2") * cos_t(sh("ph")) + c("tmp1") * sin_t(sh("ph")))
            self.set(sh("ph"), frac(sh("ph") + c("tmp5")))
        self.jloop(j)
        for f in ("ay1", "ay2", "by1", "by2"):
            for k in range(4):
                self.flushw(sh(f, k))

    # an SVF band is a record of five words: ic1 ic2 a1 a2 a3 (SVF1); W = (scratch word, byte
    # offset): the record's address is that word's value + the offset (the voice's base, or a
    # band loop's pointer)
    def _svr(self, w) -> None:
        p, C = self.p, self.L.C
        word, off = w
        p.ld(13, C[word])
        p.iconst(12, off)
        p.iop(13, 12, "+", 13)
        p.st(C["svr"], 13)

    def svf_set(self, fc: E, kk: float, w) -> None:
        """live.SVF.set for one band (kk: the constant F(1) recip(q))"""
        c = self.c
        self.set(c("sfc"), fc)
        self.p.fconst(0, kk)
        self.p.st(self.L.C["skk"], 0)
        self._svr(w)
        self.rt("svf_set", self._svf_set)

    def _svf_set(self) -> None:
        p, C, c = self.p, self.L.C, self.c
        self.set(c("tmp0"), mn(c("sfc"), kf("F_HI")) * Kc(kf("H_SCALE")))
        self.set(c("tmp1"), sinp(c("tmp0")) * recip(cosp(c("tmp0"))))          # g
        self.set(c("tmp2"), recip(Kc(1.0) + c("tmp1") * (c("tmp1") + c("skk"))))  # a1
        self.ld(0, c("tmp1"))
        self.ld(2, c("tmp2"))
        p.fop(3, 0, "*", 2)                                                     # a2 = g a1
        p.fop(4, 0, "*", 3)                                                     # a3 = g a2
        p.ld(12, C["svr"])
        p.seti(1, 12)
        for k, r in ((2, 2), (3, 3), (4, 4)):
            p.sti(k, 1, r)

    def svf_tick(self, x: E, w, v1: str, v2: str | None) -> None:
        """live.SVF.tick: C[v1] = band (v1), C[v2] = low (v2)"""
        self.set(self.c("sx"), x)
        self._svr(w)
        self.rt("svf_tick", self._svf_tick)
        if v1 != "sv1":
            self.set(self.c(v1), self.c("sv1"))
        if v2:
            self.set(self.c(v2), self.c("sv2"))

    def _svf_tick(self) -> None:
        p, C = self.p, self.L.C
        p.ld(12, C["svr"])
        p.seti(1, 12)
        p.ld(0, C["sx"])
        for k in range(5):                      # ic1 ic2 a1 a2 a3 -> F1..F5
            p.ldi(1 + k, k, 1)
        p.fop(6, 0, "-", 2)                     # v3 = x - ic2
        p.fop(7, 3, "*", 1)
        p.fop(8, 4, "*", 6)
        p.fop(7, 7, "+", 8)                     # v1 = a1 ic1 + a2 v3
        p.fop(8, 4, "*", 1)
        p.fop(8, 2, "+", 8)
        p.fop(9, 5, "*", 6)
        p.fop(8, 8, "+", 9)                     # v2 = (ic2 + a2 ic1) + a3 v3
        p.fop(9, 7, "+", 7)
        p.fop(9, 9, "-", 1)                     # ic1 = 2 v1 - ic1
        p.sti(0, 1, 9)
        p.fop(10, 8, "+", 8)
        p.fop(10, 10, "-", 2)                   # ic2 = 2 v2 - ic2
        p.sti(1, 1, 10)
        p.st(C["sv1"], 7)
        p.st(C["sv2"], 8)

    def form(self, parw: Mv) -> None:
        """live FORM: two formant band-passes (SVF(2), q 8), the wet mix ramping"""
        p, C, L = self.p, self.L.C, self.L
        c, ci, V, J = self.c, self.ci, self.V, self.J
        fo = lambda f, k=0: Mv("i", 3, FORM[f] + k)
        self.base(3, "FO")
        bands = [{f: fo(f"s{k}", SVF1.index(f)) for f in SVF1} for k in range(2)]
        brec = [("vbase", 4 * (VOICE["FO"] + FORM[f"s{k}"])) for k in range(2)]
        kk = kf("KK_FORM")

        def init():
            for b in bands:
                self.fz(b["ic1"])
                self.fz(b["ic2"])
            self.iset(V("fo_on"), 1)
            p.iconst(0, -1)
            self.st(fo("v"), 0)                    # form_v None
        self.iflag(V("fo_on"), None, init)

        def reset():
            self.ld(0, parw)
            self.st(fo("v"), 0)
            self.set(c("tmp5"), u_of(parw) * Kc(4.0))      # v
            self.ev(c("tmp5"), 0)
            p.trunc(0, 0)
            p.iconst(1, 3)
            p.iop(0, 0, "MIN", 1)
            p.st(C["q8"], 0)
            self.set(c("tmp6"), c("tmp5") - fi(self.ci("q8")))                     # fr
            p.ld(0, C["q8"])
            p.lsh(0, 0, 1)
            p.st(C["q9"], 0)
            for k, b in enumerate(bands):
                # fc = VOWELS[j][k] (1 - fr) + VOWELS[j + 1][k] fr
                p.ld(0, C["q9"])
                p.iconst(12, k)
                p.iop(0, 12, "+", 0)
                self.tabv(1, "VOW", 0)
                p.st(C["w0"], 1)
                p.ld(0, C["q9"])
                p.iconst(12, k + 2)
                p.iop(0, 12, "+", 0)
                self.tabv(1, "VOW", 0)
                p.st(C["w1"], 1)
                self.set(c("dw"), c("w0") * (Kc(1.0) - c("tmp6")) + c("w1") * c("tmp6"))
                self.svf_set(c("dw"), kk, brec[k])
            self.set(c("tmp5"), mn(fi(parw) * Kc(1.0 / 16.0), 1.0) * Kc(0.8))    # w1
            self.iflag(fo("wetok"), lambda: self.set(fo("w0"), fo("wet")), lambda: self.set(fo("w0"), c("tmp5")))
            self.set(fo("wet"), c("tmp5"))
            self.iset(fo("wetok"), 1)
        self.ld(0, fo("v"))
        self.ld(1, parw)
        p.if_(0, "NE", 1, reset, lambda: self.set(fo("w0"), fo("wet")), kind="i")
        self.set(c("dw"), (fo("wet") - fo("w0")) * Kc(1.0 / BLOCK))

        def j():
            for k in range(2):
                self.svf_tick(J("Z"), brec[k], f"u{k}", None)
            self.set(c("tmp5"), Kc(kk) * c("u0") + Kc(kk) * c("u1"))          # fsum
            self.cmp(c("dw"), "EQ", 0.0, lambda: self.set(c("tmp6"), fo("wet")),
                     lambda: self.set(c("tmp6"), fo("w0") + fi(self.ci("jj1")) * c("dw")))
            self.set(J("W"), (Kc(1.0) - c("tmp6")) * J("Z") + (c("tmp6") * c("tmp5")) * Kc(2.0))
        self.jloop1(j)
        for b in bands:
            self.flushw(b["ic1"])
            self.flushw(b["ic2"])

    def jloop1(self, body) -> None:
        """a jloop with C['jj1'] = j + 1"""
        p, C = self.p, self.L.C

        def b():
            p.ld(0, C["jj"])
            p.iconst(12, 1)
            p.iop(0, 12, "+", 0)
            p.st(C["jj1"], 0)
            body()
        self.jloop(b, need_j=True)

    def base(self, ireg: int, rec: str) -> None:
        """Ireg = the voice's sub-record REC (its words then in short instructions)"""
        p, C = self.p, self.L.C
        p.ld(13, C["vbase"])
        p.iconst(12, 4 * VOICE[rec])
        p.iop(13, 12, "+", 13)
        p.seti(ireg, 13)

    def bloop(self, at: int, n: int, stride: int, body) -> None:
        """for n records of STRIDE words from the voice's word AT: I3 = the record"""
        p, C = self.p, self.L.C
        p.ld(13, C["vbase"])
        p.iconst(12, 4 * at)
        p.iop(13, 12, "+", 13)
        p.st(C["bests"], 13)

        def it():
            self.ptr(3, "bests")
            body()
            self.bump("bests", 4 * stride)
        self.sloop("cnt2", n, it)

    def water(self, parw: Mv) -> None:
        """live.Water: the skin above 1.8 f0 vocoded by six bands, level-matched"""
        p, C, L = self.p, self.L.C, self.L
        c, ci, V, J = self.c, self.ci, self.V, self.J
        wa = lambda f: Mv("i", 0, WAT[f])
        self.base(0, "WA")
        wb = lambda f: Mv("i", 3, WBAND[f])
        bands_at = VOICE["WA"] + WAT["bands"]
        lp = [{f: wa(f"l{n}{f}") for f in SVF1} for n in (1, 2)]
        lrec = [("vbase", 4 * (VOICE["WA"] + WAT[f"l{n}ic1"])) for n in (1, 2)]
        arec, crec = ("bests", 4 * WBAND["aic1"]), ("bests", 4 * WBAND["cic1"])
        assert all(WAT[f"l{n}{f}"] == WAT[f"l{n}ic1"] + k for n in (1, 2) for k, f in enumerate(SVF1))
        assert all(WBAND[f"{x}{f}"] == WBAND[f"{x}ic1"] + k for x in ("a", "c")
                   for k, f in enumerate(("ic1", "ic2", "a1", "a2", "a3")))
        an = {"ic1": wb("aic1"), "ic2": wb("aic2"), "a1": wb("aa1"), "a2": wb("aa2"), "a3": wb("aa3")}
        car = {"ic1": wb("cic1"), "ic2": wb("cic2"), "a1": wb("ca1"), "a2": wb("ca2"), "a3": wb("ca3")}
        each = lambda body: self.bloop(bands_at, 6, WBAND.n, body)

        def init():
            for b in lp:
                self.fz(b["ic1"])
                self.fz(b["ic2"])

            def band():
                for f in ("aic1", "aic2", "cic1", "cic2", "e", "es"):
                    self.fz(wb(f))
            each(band)
            self.fz(wa("ss"))
            self.fz(wa("sw"))
            for f in ("gok", "amtok", "kok"):
                self.iset(wa(f), 0)
            self.iset(V("wa_on"), 1)
        self.iflag(V("wa_on"), None, init)
        self.set(c("tmp5"), parw)                                               # amt

        def setup():
            self.set(wa("kf0"), c("f0"))
            self.set(wa("kamt"), c("tmp5"))
            self.iset(wa("kok"), 1)
            for r in lrec:
                self.svf_set(c("f0") * Kc(1.8), kf("KK_LP"), r)
            self.set(c("tmp6"), mn(5.0, Kc(kf("W_SPAN")) - c("l2f0")))           # span
            self.set(c("w0"), c("f0") * Kc(2.2))                                 # b0
            p.iconst(0, 0)
            p.st(C["idx"], 0)

            def band():
                p.ld(0, C["idx"])
                self.tabv(0, "WK", 0)
                p.st(C["w1"], 0)
                self.set(c("w1"), c("w0") * exp2(c("tmp6") * c("w1")))         # fc
                p.fconst(0, 1.0)
                self.st(wb("use"), 0)
                self.cmp(c("w1"), "LE", 0.4 * RATE, None, lambda: (self.fz(wb("use")),
                                                                  self.set(c("w1"), Kc(1000.0))))
                self.svf_set(c("w1"), kf("KK_AN"), arec)
                self.svf_set(c("w1") * (Kc(1.04) + Kc(0.04) * c("tmp5")), kf("KK_CAR"), crec)
                p.ld(0, C["idx"])
                p.iconst(12, 1)
                p.iop(0, 12, "+", 0)
                p.st(C["idx"], 0)
            each(band)
        same = lambda: self.cmp(wa("kf0"), "EQ", c("f0"), lambda: self.cmp(wa("kamt"), "EQ", c("tmp5"), None, setup),
                                setup)
        self.iflag(wa("kok"), same, setup)

        def j():
            self.svf_tick(J("Z"), lrec[0], "sv1", "u1")
            self.svf_tick(c("u1"), lrec[1], "sv1", "u2")
            self.set(J("XB"), c("u2"))                                          # body
            self.set(J("BZ"), J("Z") - c("u2"))                                 # skin
            p.iconst(0, NEG0)
            p.st(C["ws"], 0)

            def band():
                self.svf_tick(J("BZ"), arec, "u0", None)
                self.set(c("u0"), Kc(kf("KK_AN")) * c("u0"))                     # an
                self.svf_tick(J("BZ"), crec, "u1", None)
                self.set(c("u1"), Kc(kf("KK_CAR")) * c("u1"))                    # car
                self.set(c("u2"), ab(c("u0")))                                  # av
                for f, ka, kr in (("e", "KA1", "KR1"), ("es", "KA2", "KR2")):
                    e = wb(f)
                    self.cmp(c("u2"), "GT", e, lambda e=e, ka=ka: self.set(e, c("u2") + (e - c("u2")) * Kc(kf(ka))),
                             lambda e=e, kr=kr: self.set(e, c("u2") + (e - c("u2")) * Kc(kf(kr))))
                self.set(c("dmax"), wb("e") * recip(wb("es") + Kc(1e-6)))         # ratio
                self.set(c("dmax"), mn(c("dmax") * c("dmax"), 6.0))              # gate
                self.cmp(wb("use"), "EQ", 0.0, lambda: self.set(c("ws"), c("ws") + Kc(0.0)),
                         lambda: self.set(c("ws"), c("ws") + c("u1") * c("dmax")))
            each(band)
            self.set(J("E"), c("ws"))                                           # wet
        self.jloop(j)

        def acc():
            self.set(wa("ss"), wa("ss") + J("BZ") * J("BZ"))
            self.set(wa("sw"), wa("sw") + J("E") * J("E"))
        self.jloop(acc)
        self.set(c("w0"), Kc(1.0))
        self.cmp(wa("sw"), "GT", 1e-20, lambda: self.set(c("w0"), sqrt(wa("ss") * recip(wa("sw")))))
        self.set(c("w0"), mn(c("w0"), kf("GMAX")))                                # g
        self.iflag(wa("gok"), lambda: self.set(c("w1"), wa("g")), lambda: self.set(c("w1"), c("w0")))   # g0
        self.set(wa("g"), c("w0"))
        self.iset(wa("gok"), 1)
        self.iflag(wa("amtok"), lambda: self.set(c("tmp6"), wa("amt")), lambda: self.set(c("tmp6"), c("tmp5")))  # a0
        self.set(wa("amt"), c("tmp5"))
        self.iset(wa("amtok"), 1)

        def j2():
            self.set(c("u0"), c("w1") + (c("w0") - c("w1")) * self.ramp_j())   # ramp
            self.cmp(c("tmp6"), "EQ", c("tmp5"), lambda: self.set(c("u1"), c("tmp5")),
                     lambda: self.set(c("u1"), c("tmp6") + (c("tmp5") - c("tmp6")) * self.ramp_j()))
            self.set(J("W"), (J("XB") + J("BZ") * (Kc(1.0) - c("u1"))) + (J("E") * c("u0")) * c("u1"))
        self.jloop(j2)
        for b in lp:
            self.flushw(b["ic1"])
            self.flushw(b["ic2"])

        def fl():
            for f in ("aic1", "aic2", "cic1", "cic2", "e", "es"):
                self.flushw(wb(f))
        each(fl)

    # -- steals and the slot's life across machines ------------------------------------------
    def stolen_check(self) -> None:
        """the guard left this voice out twice in one note (perc.guard.around): it rests"""
        p, C, L = self.p, self.L.C, self.L
        p.ld(9, C["t"])
        p.lsh(12, 9, 2)
        p.iconst(11, L.stolen)
        p.iop(12, 11, "+", 12)
        p.seti(1, 12)
        p.ldi(0, 0, 1)

        def rest():
            p.iconst(0, 0)
            p.sti(0, 1, 0)
            self.iset(self.V("on"), 0)
            self.iset(self.V("fading"), 0)
        p.ifz(0, "NE", rest)

    def new_note(self) -> None:
        """a trig: the guard's strikes against this slot start again"""
        p, C, L = self.p, self.L.C, self.L
        p.ld(9, C["t"])
        p.lsh(12, 9, 2)
        p.iconst(11, L.strikes)
        p.iop(12, 11, "+", 12)
        p.seti(1, 12)
        p.iconst(0, 0)
        p.sti(0, 1, 0)


def voice(p: Prog, L: Layout, t: int | None = None) -> "FP":
    """one slot's block (run mode: T is the slot)"""
    g = FP(p, L)
    _voice(g, t)
    return g


def vbase(g: FP) -> None:
    """R12 = I2 = C['vbase'] = the slot's voice: STATE + STRIDE t (t < 8), STATE2 + STRIDE (t - 8)"""
    p, C, L = g.p, g.L.C, g.L
    assert STRIDE == 4096 - 128
    p.ld(9, C["t"])
    p.iconst(12, 7)
    p.iop(13, 9, "AND", 12)
    p.lsh(12, 13, 12)
    p.lsh(13, 13, 7)
    p.iop(12, 12, "-", 13)                     # (t & 7) x 3968
    p.iconst(11, L.state)
    p.iconst(13, 8)
    p.if_(9, "GE", 13, lambda: p.iconst(11, L.state2), kind="i")
    p.iop(12, 11, "+", 12)
    p.st(C["vbase"], 12)
    p.seti(2, 12, "this slot's FASCIA voice")


def _voice(g: FP, t) -> None:
    p, C = g.p, g.L.C
    # I5 = the scratch's base for the whole voice (its words are DM(k, I5), FProg); the guard
    # around the voice uses I5 itself, so it is set here, every voice
    p.iconst(0, g.L.base5)
    p.seti(5, 0, "the scratch's base + WIN words")
    p.scr = (g.L.scratch, g.L.scratch_end, g.L.base5)
    p.scr_on = True
    if p.run:
        p.iconst(9, t)
        p.st(C["t"], 9)
    vbase(g)
    g.stolen_check()
    p.ld(0, TRIG_WORD)
    p.lsh(0, 0, -16)
    p.iconst(1, 1)
    p.ld(9, C["t"])
    PP._shift_by(p, 1, 9)
    p.iop(0, 0, "AND", 1)
    p.ifz(0, "NE", g.new_note)
    g.voice(t)
    p.scr_on = False


def off(g: FP) -> None:
    """a slot not on FASCIA: its voice off (a track that comes back starts clean)"""
    p, C, L = g.p, g.L.C, g.L
    vbase(g)
    p.iconst(0, 0)
    for f in ("on", "pending", "fading"):
        p.sti(VOICE[f], 2, 0)
    p.sti(VOICE["FO"] + FORM["wetok"], 2, 0)


def program(L: Layout, next_sw: int, prefix: str = "fs") -> str:
    """fascia.asm: entered by smp.asm's tail; on to NEXT_SW (the shared tail) when done"""
    from ..perc import guard as G
    p = FProg("emit", prefix=prefix)
    p.spill = None
    p.scr = (L.scratch, L.scratch_end, L.base5)
    g = FP(p, L)
    p.raw("// fascia.asm -- FASCIA, machine type 18 (docs/fascia.md): dnfw.fascia.live on the")
    p.raw("// DN2's DSP. GENERATED by scripts/gen_fascia_asm.py from dnfw.fascia.program (one program")
    p.raw("// for this text and its model); do not edit by hand.")
    p.raw("")
    p.raw(".SECTION/PM seg_pmco;")
    p.raw("")
    p.raw(".GLOBAL wr_fsc.;")
    p.raw("wr_fsc.:")
    for addr, v in L.pool.items():             # the constant pool, every block (scratch is shared)
        p.iconst(0, v)
        p.st(addr, 0)
    p.pool = {v: a for a, v in L.pool.items()}
    p.iconst(0, 0)
    p.st(L.order_i, 0)
    top = p.label("slot")
    nxt = p.label("next")
    other = p.label("other")
    p.place(top)
    p.ld(0, L.order_i)
    p.lsh(12, 0, 2)
    p.iconst(9, L.order)
    p.iop(12, 9, "+", 12)
    p.seti(1, 12)
    p.ldi(9, 0, 1)                             # the slot, the newest first (PERC's ORDER)
    p.iconst(12, 15)
    p.iop(9, 9, "AND", 12)
    p.st(L.C["t"], 9)
    PP.raw_type(p, 2)
    p.ipass(0, 2)
    p.iconst(12, TYPE)
    p.e("COMP(R0, R12);")
    p.jump("NE", other)
    G.around(p, L.C["t"], L.cost, BUFFERS, lambda: _voice(g, None),
             rests=L.stolen, rest_blocks=1, strikes=L.strikes, steal_at=2)
    p.jump("", nxt)
    p.place(other)
    off(g)
    p.place(nxt)
    p.ld(0, L.order_i)
    p.iconst(12, 1)
    p.iop(0, 12, "+", 0)
    p.st(L.order_i, 0)
    p.iconst(12, 16)
    p.e("COMP(R0, R12);")
    p.jump("LT", top)
    G.end_mark(p)                              # our voices' time, for the guard's limit
    p.e(f"JUMP {next_sw:#x};", "the shared tail (ping.asm's wr_ping: restores the registers)")
    p.scr_on = True                            # the routines and leaves run inside a voice only
    g.emit_rts()
    p.emit_subs()
    p.scr_on = False
    p.raw(".wr_fsc..end:")
    p.raw("      .type wr_fsc.,STT_FUNC;")
    return p.text()


def run_voice(L: Layout, read, t: int, mem=None):
    """the model: one slot's block on memory READ (and MEM's earlier writes). -> (Prog, mem)"""
    mem = mem or Mem(read)
    for addr, v in L.pool.items():             # the pool, as wr_fsc fills it at its entry
        mem.put(addr, v)
    p = FProg("run", mem=mem)
    p.pool = {v: a for a, v in L.pool.items()}
    p.spill = None
    g = FP(p, L)
    _voice(g, t)
    return p, mem


MISC_OFF = 0x3200                    # in the Monomachine scratch (L2): its bookkeeping ends at 0x3180


def layout() -> Layout:
    """where the build puts FASCIA (dnfw.waverider.dsp)"""
    from ..waverider import dsp
    from ..shft import live as SL
    _, at = SL.tables_bytes()
    misc = dsp.MNM_SCRATCH_L2 + MISC_OFF
    return Layout(state=dsp.FSC_STATE_L2, state2=dsp.FSC_STATE2_L2, scratch=dsp.FSC_SCRATCH_DM, tables=dsp.FSC_TABLES_DDR,
                  sin=dsp.SHFT_TABLES_DDR + at["sin"], order=PP.ORDER, order_i=misc, cost=misc + 0x40,
                  strikes=misc + 0x80, stolen=misc + 0xC0)
