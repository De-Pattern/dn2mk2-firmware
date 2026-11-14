"""Stereo, stage 3 (docs/stereo-assessment.md): the R pass through stock's voice chain.

Stock's chain (sw 0x1c8ef1) runs all sixteen voices stage by stage: for each of seven stages it
calls the stage once per voice, `CJUMP stage (DB)` with R4 the voice's state, R8 = R12 its block,
two words pushed. The build points each of those seven call sites at a wrapper here. For a voice
with no stereo slot the wrapper jumps straight on to the stage (stock, frame and all). For a
stereo voice it:

  1. keeps the frame the body's call made (the body's pushed words above it);
  2. copies the voice's L state for this stage (its stride) to PRE, and calls the stage for L
     with a CJUMP of its own, returning here;
  3. brings R's copy of the state up to date: a word that something else changed since the
     stage's last call on L (PRE differs from LPOST, what L's call left) follows L; a word only
     the stage itself changed (its filter history, its ramps) stays R's own. LPOST becomes what
     L's call left now. (Both copies are equal from the voice's first stereo block: LPOST starts
     at zero, so every non-zero word comes from L.)
  4. for the stage after the body's +4 dB step (0x1cdb56): if that step changed L's block since
     the first stage, R's block is multiplied by the same constant (the step is per voice and
     keeps nothing; whether it ran is read from L's block: equal before and after, it did not;
     equal to before x the constant, it did; a silent L keeps the last block's answer);
  5. calls the stage again with R4 = R's state, R8 = R12 = R's block, the same pushed words;
  6. puts every register back as L's call left them and returns to the body as the stage would.

Each extra call pushes the ARGS words above our frame again (the body's arguments, where the stage
reads them) and makes its own frame, so every call and return pairs as stock's do. Each wrapper
saves R0..R15, I1, I3, I4 and ASTAT where it needs them. Test mode (DUP): the first
stage's wrapper copies L's block, as the machine rendered it, into R's before L's call, so R's
pass must come out bit for bit L's (the runner's check of the whole pass).
"""

from __future__ import annotations

# (call site sw, the stage, track 0's state, the per-voice stride in bytes), in the body's
# order of execution (sharc_stereo_state.py, 2026-11-14)
STAGES = [
    (0x1C9459, 0xB8251B, 0x250020, 0x14),
    (0x1C95C9, 0x1CDB56, 0x24FA20, 0x60),
    (0x1C94FD, 0xB80C39, 0x24F320, 0x70),
    (0x1C95B4, 0xB8265B, 0x250160, 0x14),
    (0x1C959F, 0xB81368, 0x2533E0, 0x20),
    (0x1C98AF, 0xB82342, 0x2505A0, 0xCC),
    (0x1C99CC, 0xB80345, 0x2547A0, 0x2C),
]
GAIN_STAGE = 0x1CDB56            # the first stage after the body's per-sample step
GAIN = 0x3FCADE01                # the step's constant (1.5849, +4 dB; sw 0x1c948c)
SLOTS = 4                        # stereo voices at most (the cap: docs/stereo-assessment.md)
BLOCK = 32                       # samples a block

# placement (L2: inside 0x200A9200..0x200B0000, the room proven on units; loaded with zeros)
CODE_L2 = 0x200A9400
CODE_SW = 0xB80000 + (CODE_L2 - 0x20000000) // 2
DATA_L2 = 0x200AC000
DATA_BYTES = 0x3000

ANY = DATA_L2 + 0x00             # stereo slots in use (0: every wrapper jumps straight on)
LADDR = DATA_L2 + 0x10           # [slot][stage]: the voice's L state for that stage (0: free)
VOICE = DATA_L2 + 0x80           # [slot]: the voice
DUP = DATA_L2 + 0x90             # [slot]: test mode, R's block is L's as rendered
GFLAG = DATA_L2 + 0xA0           # [slot]: the +4 dB step ran (last known)
ODD = DATA_L2 + 0xC0             # blocks where L's block was neither unchanged nor stepped (diagnostic)
SAVE_I7 = DATA_L2 + 0xB0         # I7 before an extra call's argument copies
ARGS = 6                         # words above the frame copied for each extra call (every stage reads
                                 # at most four: its pushed words and the slot the body reserves)
SLOT = DATA_L2 + 0xB4            # the slot being run
SAVE_IN = DATA_L2 + 0x100        # 20 words: R0..R15, I1, I3, ASTAT as the body called
SAVE_OUT = DATA_L2 + 0x180       # the same, as L's call returned
PRE = DATA_L2 + 0x200            # L's state for this stage before its call (0xcc bytes at most)
SNAP = DATA_L2 + 0x300           # L's block after the first stage (the gain check)
RBLK = DATA_L2 + 0x400           # [slot]: R's block, 32 float32
LAMP = DATA_L2 + 0x600           # [slot]: L's block as the amp left it (the post-amp ramps, below)
ONE = 0x3F800000                 # 1.0
R1RAMP = DATA_L2 + 0x2800        # [slot]: the first post-amp ramp (from the hook between the two)
MID_SITE, MID_STOCK = 0x1C9A3A, "R1 = 0x4f800000;"            # between the two ramp loops
OFF = []                         # each stage's offset in a slot's state copy
_o = 0
for _s in STAGES:
    OFF.append(_o)
    _o += _s[3]
STATE_BYTES = _o                 # 0x258: 150 words a voice
RST = DATA_L2 + 0x800            # [slot]: R's state copies, 0x400 apart
LPOST = DATA_L2 + 0x1800         # [slot]: what L's last call left
SLOT_STRIDE = 0x400
SAVE_SUM = DATA_L2 + 0xC00 - 0x80   # the sum hooks' register save (20 words; below RST)

# stage 4: the voices into the tracks (sw 0x1c2512..0x1c2557, docs/stereo-assessment.md). Each
# voice's block x a gain is added to both halves of its track's buffer (64 words a track: L half,
# R half); the mixer takes them on. The gain: 11.6266 (0x413a068e) on the first sample, then
# minus 0.37505 (0x3ec006c4) a sample when the voice's fade word is not zero (a fade out), else
# flat. The hook after the sum turns a stereo voice's share of its track's R half from L into R.
#
# Between the amp and the sum the body runs two per-voice gain ramps on the blocks (sw 0x1c99ed and
# 0x1c9a59: each sample x a value that moves by a step; a level ramp and a fade). They are not
# copied: the amp's wrapper keeps L's block (LAMP) and fills it with 1.0, so the ramps leave their
# own values in it. A hook between the two loops keeps the first ramp (R1RAMP) and fills the block
# with 1.0 again; the hook before the sum makes L = r2 x (r1 x LAMP) and R = r2 x (r1 x R), stock's
# own multiplies in its order.
SUM_PRE_SITE, SUM_PRE_STOCK = 0x1C2512, "R4 = 0x413a068e;"     # the instruction before the sum
SUM_POST_SITE, SUM_POST_STOCK = 0x1C2557, "I2 = 0x25b768;"     # the instruction after it
TRACK_BUF = 0x259F68             # 16 tracks x 64 words
VOICE_TRACK = 0x257898           # each voice's track word
VOICE_FADE = 0x2578B8            # each voice's fade word
VOICE_BLOCK = 0x257EA8           # each voice's block pointer
SUM_GAIN, SUM_STEP = 0x413A068E, 0x3EC006C4

assert STATE_BYTES <= SLOT_STRIDE and LPOST + SLOTS * SLOT_STRIDE <= DATA_L2 + DATA_BYTES
assert SNAP + 4 * BLOCK <= RBLK and RBLK + SLOTS * 4 * BLOCK <= RST
assert max(s[3] for s in STAGES) <= SNAP - PRE

SAVED = [f"R{r}" for r in range(16)] + ["I0", "I1", "I3", "I4", "ASTAT"]


def laddr(slot: int, k: int) -> int:
    return LADDR + 4 * (len(STAGES) * slot + k)


def voice_laddr(v: int) -> list[int]:
    """voice V's L state address for each stage (what LADDR holds for a stereo voice)"""
    return [base + v * stride for _site, _t, base, stride in STAGES]


class _Asm:
    def __init__(self):
        self.lines: list[str] = []

    def e(self, text: str, note: str = "") -> None:
        line = f"      {text}"
        self.lines.append(line.ljust(40) + f"// {note}" if note else line)

    def label(self, name: str) -> None:
        self.lines += [f".GLOBAL {name}.;", f"{name}.:"]

    def jump(self, cond: str, name: str) -> None:
        pre = f"IF {cond} " if cond else ""
        self.lines.append(f"      {pre}JUMP 0x0;".ljust(40) + f"// -> {name}.")

    def jump_abs(self, cond: str, addr: int, note: str) -> None:
        pre = f"IF {cond} " if cond else ""
        self.lines.append(f"      {pre}JUMP {addr:#x};".ljust(40) + f"// {note}")

    def save(self, at: int) -> None:
        for k, r in enumerate(SAVED):
            self.e(f"DM({at + 4 * k:#x}) = {r};")

    def restore(self, at: int) -> None:
        for k, r in enumerate(SAVED):
            self.e(f"{r} = DM({at + 4 * k:#x});")

    def call_stage(self, target: str, back: str) -> None:
        """the body's call again from inside our frame: the ARGS words above our frame (the
        body's pushed arguments, as the stage reads them: DM(1..ARGS, I6)) pushed again, then
        CJUMP (DB) with the frame pushed, back to BACK; after it, I7 as before the copies"""
        self.e(f"DM({SAVE_I7:#x}) = I7;")
        for j in range(ARGS, 0, -1):
            self.e(f"R2 = DM({j}, I6);")
            self.e("DM(I7, M7) = R2;")
        self.e(f"CJUMP {target} (DB);")
        self.e("DM(I7, M7) = R2;")
        self.lines.append("      DM(I7, M7) = 0x0;".ljust(40) + f"// return address - 1: {back}. - 1")


def _loop(a: _Asm, name: str, n: int, ops) -> None:
    """N times OPS (each iteration's instructions, post-modifying with M6 = 1, the ABI's).
    Counts in R15."""
    a.e(f"R15 = {n};")
    a.label(name)
    ops()
    a.e("R15 = R15 - 1;")
    a.jump("NE", name)


def _copy(a: _Asm, name: str, n: int) -> None:
    """N words from I1 on to I3 on. Clobbers R0, R15, I1, I3."""
    def ops():
        a.e("R0 = DM(I1, M6);")
        a.e("DM(I3, M6) = R0;")
    _loop(a, name, n, ops)


def _set(a: _Asm, i: int, addr: int) -> None:
    a.e(f"R0 = {addr:#x};")
    a.e(f"I{i} = R0;")


def program() -> str:
    a = _Asm()
    a.lines += ["// stereo.asm -- the R pass through stock's voice chain (docs/stereo-assessment.md).",
                "// GENERATED by scripts/gen_smp_asm.py from dnfw.sampler.stereo; do not edit by hand.",
                "", ".SECTION/PM seg_pmco;", ""]
    for k, (_site, target, _base, stride) in enumerate(STAGES):
        t = f"{target:#x}"
        n = stride // 4
        # -- the entry: no stereo voice, or not this one: straight on to the stage --
        a.label(f"wr_st_t{k}")
        a.e(f"R0 = DM({ANY:#x});", "stereo slots in use")
        a.e("R0 = PASS R0;")
        a.jump_abs("EQ", target, "none: the stage, as stock")
        for s in range(SLOTS):
            a.e(f"R0 = DM({laddr(s, k):#x});", f"slot {s}'s voice, this stage")
            a.e("COMP(R4, R0);")
            a.jump("EQ", f"wr_st_s{k}_{s}")
        a.jump_abs("", target, "a mono voice: the stage, as stock")
        for s in range(SLOTS):
            a.label(f"wr_st_s{k}_{s}")
            a.e(f"R1 = {s};")
            a.jump("", f"wr_st_c{k}")
        # -- a stereo voice --
        a.label(f"wr_st_c{k}")
        a.e(f"DM({SLOT:#x}) = R1;")
        a.save(SAVE_IN)
        a.e("I1 = R4;", "PRE = L's state")
        _set(a, 3, PRE)
        _copy(a, f"wr_st_pre{k}", n)
        if k == 0:                                     # test mode: R's block is L's as rendered
            _slot_base(a, DUP, 1, 2)
            a.e("R0 = DM(0, I1);")
            a.e("R0 = PASS R0;")
            a.jump("EQ", f"wr_st_nodup{k}")
            _rblk_to_i3(a)
            a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});", "L's block (R12 as called)")
            a.e("I1 = R0;")
            _copy(a, f"wr_st_dup{k}", BLOCK)
            a.label(f"wr_st_nodup{k}")
        a.restore(SAVE_IN)
        a.call_stage(t, f"wr_st_l{k}")
        a.label(f"wr_st_l{k}")
        a.e(f"I7 = DM({SAVE_I7:#x});", "the copies off")
        a.save(SAVE_OUT)
        # sync R's state: a word changed by anything but the stage follows L
        _slot_base(a, RST + OFF[k], 1)                 # I1 = R's state
        _slot_base(a, LPOST + OFF[k], 3)               # I3 = LPOST
        _set(a, 4, PRE)

        def sync():
            a.e("R0 = DM(I4, M6);", "PRE")
            a.e("R1 = DM(I3, M6);", "LPOST")
            a.e("COMP(R0, R1);")
            a.jump("EQ", f"wr_st_keep{k}")
            a.e("DM(I1, M6) = R0;", "changed by another: follow L")
            a.jump("", f"wr_st_next{k}")
            a.label(f"wr_st_keep{k}")
            a.e("R2 = DM(I1, M6);", "R's own: kept (the read moves I1 on)")
            a.label(f"wr_st_next{k}")
        _loop(a, f"wr_st_sync{k}", n, sync)
        # LPOST = L's state as its call left it
        _slot_base(a, LPOST + OFF[k], 3)
        a.e(f"R0 = DM({SAVE_IN + 4 * 4:#x});", "L's state (R4 as called)")
        a.e("I1 = R0;")
        _copy(a, f"wr_st_post{k}", n)
        if k == 0:                                     # SNAP = L's block after the first stage
            a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});", "L's block")
            a.e("I1 = R0;")
            _set(a, 3, SNAP)
            _copy(a, f"wr_st_snap{k}", BLOCK)
        if target == GAIN_STAGE:
            _gain(a, k)
        # R's call: the body's registers, R's state and block
        a.restore(SAVE_IN)
        _slot_base(a, RST + OFF[k], 1)
        a.e("R4 = R13;", "R's state")
        _rblk_to_i3(a)
        a.e("R12 = PASS R13;", "R's block")
        a.e("R8 = PASS R13;")
        for r, at in (("I0", 16), ("I1", 17), ("I3", 18), ("I4", 19)):
            a.e(f"{r} = DM({SAVE_IN + 4 * at:#x});")
        a.call_stage(t, f"wr_st_r{k}")
        a.label(f"wr_st_r{k}")
        a.e(f"I7 = DM({SAVE_I7:#x});", "the copies off")
        if k == len(STAGES) - 1:                       # the amp: LAMP = L's block, L's block = 1.0
            a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});", "L's block (R12 as called)")
            a.e("I1 = R0;")
            _slot_base(a, LAMP, 3, 7)
            _copy(a, f"wr_st_lamp{k}", BLOCK)
            a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});")
            a.e("I1 = R0;")
            a.e(f"R0 = {ONE:#x};")

            def ones():
                a.e("DM(I1, M6) = R0;")
            _loop(a, f"wr_st_ones{k}", BLOCK, ones)
        a.restore(SAVE_OUT)
        a.e("I12 = DM(-1, I6);", "back to the body: the stage's own return")
        a.e("JUMP (M14, I12) (DB);")
        a.e("I7 = I6;")
        a.e("I6 = DM(0, I6);")
        a.lines.append("")
    _mid_hook(a)
    _pre_hook(a)
    _sum_hooks(a)
    a.lines += [".wr_stereo..end:"]
    return "\n".join(a.lines) + "\n"


def _slot_base(a: _Asm, base: int, i: int, shift: int = 10) -> None:
    """I<i> = BASE + SLOT << SHIFT (the DSL's own idiom, R12 R13, which the runner's decoder
    reads at the assembler's boundaries). Clobbers R12, R13."""
    a.e(f"R12 = DM({SLOT:#x});")
    a.e(f"R12 = LSHIFT R12 BY {shift};")
    a.e(f"R13 = {base:#x};")
    a.e("R13 = R13 + R12;")
    a.e(f"I{i} = R13;")


def _rblk_to_i3(a: _Asm) -> None:
    """I3 = R's block for SLOT. Clobbers R12, R13."""
    _slot_base(a, RBLK, 3, 7)


def _gain(a: _Asm, k: int) -> None:
    """R's block x GAIN when the body's step changed L's, read from L's block: SNAP (after the
    first stage) against L's block now. Unchanged: no step (GFLAG 0). Every sample SNAP x GAIN:
    the step (GFLAG 1). Both (an all-zero L): GFLAG as it was. Neither: GFLAG as it was, ODD
    counted. Clobbers R0..R3, R15, I1, I3."""
    def l_and_snap():
        a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});", "L's block (R12 as called)")
        a.e("I1 = R0;")
        _set(a, 3, SNAP)
    a.e("R3 = 0;", "bit 0: unchanged, bit 1: stepped")
    l_and_snap()

    def same():
        a.e("R0 = DM(I1, M6);")
        a.e("R1 = DM(I3, M6);")
        a.e("COMP(R0, R1);")
        a.jump("NE", f"wr_st_ns{k}")
    _loop(a, f"wr_st_same{k}", BLOCK, same)
    a.e("R3 = 1;")
    a.label(f"wr_st_ns{k}")
    l_and_snap()
    a.e(f"R2 = {GAIN:#x};", "F2: the step's constant")

    def stepped():
        a.e("R0 = DM(I1, M6);")
        a.e("R1 = DM(I3, M6);")
        a.e("F1 = F1 * F2;", "the step's own order: sample x constant")
        a.e("COMP(R0, R1);")
        a.jump("NE", f"wr_st_nx{k}")
    _loop(a, f"wr_st_step{k}", BLOCK, stepped)
    a.e("R0 = 2;")
    a.e("R3 = R3 OR R0;")
    a.label(f"wr_st_nx{k}")
    _slot_base(a, GFLAG, 1, 2)
    a.e("R0 = 1;")
    a.e("COMP(R3, R0);")
    a.jump("NE", f"wr_st_g1{k}")
    a.e("R0 = 0;")
    a.e("DM(0, I1) = R0;", "unchanged: no step")
    a.label(f"wr_st_g1{k}")
    a.e("R0 = 2;")
    a.e("COMP(R3, R0);")
    a.jump("NE", f"wr_st_g2{k}")
    a.e("R0 = 1;")
    a.e("DM(0, I1) = R0;", "stepped")
    a.label(f"wr_st_g2{k}")
    a.e("R3 = PASS R3;")
    a.jump("NE", f"wr_st_g3{k}")
    a.e(f"R0 = DM({ODD:#x});", "neither: counted")
    a.e("R1 = 1;")
    a.e("R0 = R0 + R1;")
    a.e(f"DM({ODD:#x}) = R0;")
    a.label(f"wr_st_g3{k}")
    a.e("R0 = DM(0, I1);")
    a.e("R0 = PASS R0;")
    a.jump("EQ", f"wr_st_g4{k}")
    _rblk_to_i3(a)
    a.e(f"R2 = {GAIN:#x};")

    def mul():
        a.e("F0 = DM(0, I3);")
        a.e("F0 = F0 * F2;")
        a.e("DM(I3, M6) = F0;")
    _loop(a, f"wr_st_mul{k}", BLOCK, mul)
    a.label(f"wr_st_g4{k}")


def _voice_block_i4(a: _Asm, sl: int) -> None:
    """I4 = slot SL's voice's block (stock's table). Clobbers R0, R12..R14."""
    a.e(f"R14 = DM({VOICE + 4 * sl:#x});", "the voice")
    a.e("R12 = LSHIFT R14 BY 2;")
    a.e(f"R13 = {VOICE_BLOCK:#x};")
    a.e("R13 = R13 + R12;")
    a.e("I4 = R13;")
    a.e("R0 = DM(0, I4);")
    a.e("I4 = R0;", "the voice's block")


def _mid_hook(a: _Asm) -> None:
    """wr_st_smid, at MID_SITE (after the first post-amp ramp loop): each stereo voice's block
    holds the first ramp (from 1.0): kept in R1RAMP, the block 1.0 again"""
    a.label("wr_st_smid")
    a.save(SAVE_SUM)
    a.e(f"R0 = DM({ANY:#x});")
    a.e("R0 = PASS R0;")
    a.jump("EQ", "wr_st_smid_out")
    for sl in range(SLOTS):
        a.e(f"R0 = DM({laddr(sl, 0):#x});")
        a.e("R0 = PASS R0;")
        a.jump("EQ", f"wr_st_md_next{sl}")
        _voice_block_i4(a, sl)
        a.e(f"R0 = {R1RAMP + 4 * BLOCK * sl:#x};")
        a.e("I3 = R0;")
        a.e(f"R1 = {ONE:#x};")

        def one():
            a.e("R0 = DM(0, I4);")
            a.e("DM(I3, M6) = R0;")
            a.e("DM(I4, M6) = R1;")
        _loop(a, f"wr_st_md_s{sl}", BLOCK, one)
        a.label(f"wr_st_md_next{sl}")
    a.label("wr_st_smid_out")
    a.restore(SAVE_SUM)
    a.e(MID_STOCK, "the displaced instruction")
    a.jump_abs("", MID_SITE + 3, "on, as stock")
    a.lines.append("")


def _pre_hook(a: _Asm) -> None:
    """wr_st_spre, at SUM_PRE_SITE: for each stereo slot in use, its voice's block holds the
    post-amp ramps (from 1.0): L = ramp x LAMP, R = ramp x R."""
    a.label("wr_st_spre")
    a.save(SAVE_SUM)
    a.e(f"R0 = DM({ANY:#x});")
    a.e("R0 = PASS R0;")
    a.jump("EQ", "wr_st_spre_out")
    for sl in range(SLOTS):
        a.e(f"R0 = DM({laddr(sl, 0):#x});")
        a.e("R0 = PASS R0;")
        a.jump("EQ", f"wr_st_pr_next{sl}")
        a.e(f"R14 = DM({VOICE + 4 * sl:#x});", "the voice")
        a.e("R12 = LSHIFT R14 BY 2;")
        a.e(f"R13 = {VOICE_BLOCK:#x};")
        a.e("R13 = R13 + R12;")
        a.e("I4 = R13;")
        a.e("R0 = DM(0, I4);")
        a.e("I4 = R0;", "the voice's block: the ramps")
        a.e(f"R0 = {LAMP + 4 * BLOCK * sl:#x};")
        a.e("I1 = R0;", "L as the amp left it")
        a.e(f"R0 = {RBLK + 4 * BLOCK * sl:#x};")
        a.e("I3 = R0;", "R")
        a.e(f"R0 = {R1RAMP + 4 * BLOCK * sl:#x};")
        a.e("I0 = R0;", "the first ramp")

        def one():
            a.e("F1 = DM(I0, M6);", "r1")
            a.e("F2 = DM(0, I4);", "r2 (the block, from 1.0)")
            a.e("F0 = DM(I1, M6);")
            a.e("F0 = F1 * F0;", "stock's order: ramp x sample, r1 then r2")
            a.e("F0 = F2 * F0;")
            a.e("DM(I4, M6) = F0;")
            a.e("F0 = DM(0, I3);")
            a.e("F0 = F1 * F0;")
            a.e("F0 = F2 * F0;")
            a.e("DM(I3, M6) = F0;")
        _loop(a, f"wr_st_pr_s{sl}", BLOCK, one)
        a.label(f"wr_st_pr_next{sl}")
    a.label("wr_st_spre_out")
    a.restore(SAVE_SUM)
    a.e(SUM_PRE_STOCK, "the displaced instruction")
    a.jump_abs("", SUM_PRE_SITE + 3, "on to the sum, as stock")
    a.lines.append("")


def _sum_hooks(a: _Asm) -> None:
    """stage 4: wr_st_spost, at SUM_POST_SITE (just after stock's voices-into-tracks sum). For
    each stereo slot in use, its voice's track's R half gets g x R - g x L added, sample by
    sample: stock put g x L there, so it ends as g x R (to rounding). g is stock's gain for that
    voice (SUM_GAIN, less SUM_STEP a sample while its fade word is set). Mono voices and the L
    halves are never touched; with R == L every word added is exactly zero."""
    a.label("wr_st_spost")
    a.save(SAVE_SUM)
    a.e(f"R0 = DM({ANY:#x});")
    a.e("R0 = PASS R0;")
    a.jump("EQ", "wr_st_spost_out")
    for sl in range(SLOTS):
        a.e(f"R0 = DM({laddr(sl, 0):#x});")
        a.e("R0 = PASS R0;")
        a.jump("EQ", f"wr_st_sp_next{sl}")
        a.e(f"R14 = DM({VOICE + 4 * sl:#x});", "the voice")
        a.e("R12 = LSHIFT R14 BY 2;")
        a.e(f"R13 = {VOICE_BLOCK:#x};")
        a.e("R13 = R13 + R12;")
        a.e("I4 = R13;")
        a.e("R0 = DM(0, I4);")
        a.e("I4 = R0;", "L: the voice's block")
        a.e(f"R0 = {RBLK + 4 * BLOCK * sl:#x};")
        a.e("I1 = R0;", "R: the slot's block")
        a.e(f"R13 = {VOICE_TRACK:#x};")
        a.e("R13 = R13 + R12;")
        a.e("I3 = R13;")
        a.e("R0 = DM(0, I3);", "the track word")
        a.e("R0 = R0 + R0;", "x 2, its low 16 bits signed (stock: fext se)")
        a.e("R1 = 0xFFFF;")
        a.e("R0 = R0 AND R1;")
        a.e("R1 = 0x8000;")
        a.e("R1 = R0 AND R1;")
        a.jump("EQ", f"wr_st_sp_pos{sl}")
        a.e("R1 = 0x10000;")
        a.e("R0 = R0 - R1;")
        a.label(f"wr_st_sp_pos{sl}")
        a.e("R0 = LSHIFT R0 BY 7;")
        a.e(f"R13 = {TRACK_BUF + 128:#x};")
        a.e("R13 = R13 + R0;")
        a.e("I3 = R13;", "its track's R half")
        a.e(f"R13 = {VOICE_FADE:#x};")
        a.e("R13 = R13 + R12;")
        a.e("I0 = R13;")
        a.e("R0 = DM(0, I0);", "the fade word")
        a.e("R1 = 0;")
        a.e("R0 = PASS R0;")
        a.jump("EQ", f"wr_st_sp_flat{sl}")
        a.e(f"R1 = {SUM_STEP:#x};")
        a.label(f"wr_st_sp_flat{sl}")
        a.e(f"R2 = {SUM_GAIN:#x};", "F2: the gain, sample by sample")

        def one():
            a.e("F0 = DM(I1, M6);", "R")
            a.e("F0 = F2 * F0;")
            a.e("F3 = DM(I4, M6);", "L")
            a.e("F3 = F2 * F3;")
            a.e("F0 = F0 - F3;", "g R - g L")
            a.e("F3 = DM(0, I3);")
            a.e("F3 = F3 + F0;")
            a.e("DM(I3, M6) = F3;")
            a.e("F2 = F2 - F1;")
        _loop(a, f"wr_st_sp_s{sl}", BLOCK, one)
        a.label(f"wr_st_sp_next{sl}")
    a.label("wr_st_spost_out")
    a.restore(SAVE_SUM)
    a.e(SUM_POST_STOCK, "the displaced instruction")
    a.jump_abs("", SUM_POST_SITE + 3, "on, as stock")
    a.lines.append("")
