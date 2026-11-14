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
  4. before L's call of the first stage after the body's +4 dB step (0xb80c39 or 0x1cdb56,
     whichever the body calls first; GPEND): if that step changed L's block since the first stage, R's block is multiplied by the same constant (the step is per voice and
     keeps nothing; whether it ran is read from L's block: equal before and after, it did not;
     equal to before x the constant, it did; a silent L keeps the last block's answer);
  5. puts R's state in the voice's own place (L's kept in LPOST) and calls the stage again with
     R8 = R12 = R's block, the same pushed words; then R's state back to its copy, L's back;
  6. puts every register back as L's call left them and returns to the body as the stage would.

Each extra call pushes the ARGS words above our frame again (the body's arguments, where the stage
reads them) and makes its own frame, so every call and return pairs as stock's do. Each wrapper
saves R0..R15, I1, I3, I4 and ASTAT where it needs them. Test mode (DUP): the first
stage's wrapper copies L's block, as the machine rendered it, into R's before L's call, so R's
pass must come out bit for bit L's (the runner's check of the whole pass).
"""

from __future__ import annotations

# (call site sw, the stage, voice 0's state, the per-voice stride in bytes): one wrapper each,
# the amp last. The first six in the body's order of execution (sharc_stereo_state.py,
# 2026-11-14); then the stages of the per-voice dispatch the other filter types and modes take
# (scripts/sharc_stereo_calls.py, every call of the body with random sounds and every filter
# type, 2026-11-14: each called with R8 = R12 the voice's block and R4 its state)
STAGES = [
    (0x1C9459, 0xB8251B, 0x250020, 0x14),
    (0x1C95C9, 0x1CDB56, 0x24FA20, 0x60),
    (0x1C94FD, 0xB80C39, 0x24F320, 0x70),
    (0x1C95B4, 0xB8265B, 0x250160, 0x14),
    (0x1C959F, 0xB81368, 0x2533E0, 0x20),
    (0x1C98AF, 0xB82342, 0x2505A0, 0xCC),
    (0x1C9BB6, 0xB81A16, 0x251260, 0x12C),
    (0x1C9BD1, 0xB80F2E, 0x252520, 0xEC),
    (0x1C9BE9, 0xB806F5, 0x2535E0, 0x48),
    (0x1C99CC, 0xB80345, 0x2547A0, 0x2C),
]
# the bytes from R4 each stage reads and writes (sharc_stereo_foot, every filter type and moving
# sounds, 2026-11-14): two reach past the voices' spacing (0xb81a16 to +0x1fc, 0xb80f2e to
# +0x140), so a voice's state is copied by its size, not its stride
SIZES = [max(st[3], sz) for st, sz in zip(STAGES, (0, 0, 0, 0, 0, 0, 0x200, 0x140, 0, 0), strict=True)]
# the same stages called from other sites (the same state, so the same wrapper)
EXTRA_SITES = [(0x1C9935, 1),       # 0x1cdb56 between the body's x16 and x1/16 (sw 0x1c98eb..0x1c997e)
               (0x1C9B7A, 4), (0x1C9B8F, 3), (0x1C9C4F, 8)]
SITES = [(site, k) for k, (site, *_r) in enumerate(STAGES)] + EXTRA_SITES
# Not wrapped: 0xb81526 (sw 0x1c9c08, the comb filters): it writes a buffer of its own that the
# body then mixes into the block (sw 0x1c9c12..0x1c9c44). L's block changes there in a way no
# check below recognises, so the voice falls back to mono for the rest of the block (MONO).
# Between stages the body may scale L's block by a constant (its +4 dB step after the first
# stage, x16 and x1/16 around 0x1cdb56's second site): each wrapper after the first compares L's
# block on entry with what the last wrapper left (LLAST) and scales R the same.
CONSTS = (0x3FCADE01, 0x41800000, 0x3D800000)     # +4 dB (sw 0x1c948c), 16.0, 1/16
GAIN = CONSTS[0]
SLOTS = 4                        # stereo voices at most (the cap: docs/stereo-assessment.md)
BLOCK = 32                       # samples a block

# placement (L2: inside 0x200A9200..0x200B0000, the room proven on units; loaded with zeros)
CODE_L2 = 0x200A9400
CODE_SW = 0xB80000 + (CODE_L2 - 0x20000000) // 2
DATA_L2 = 0x200ABE00             # (0x200ac000 and 0x3000 bytes until the generic wrapper, 2026-11-14)
DATA_BYTES = 0x4180

ANY = DATA_L2 + 0x00             # stereo slots in use (0: every wrapper jumps straight on)
SLOT = DATA_L2 + 0x04            # the slot being run
SAVE_I7 = DATA_L2 + 0x08         # I7 before an extra call's argument copies
ODD = DATA_L2 + 0x0C             # wrappers where L's block changed in a way not recognised (diagnostic)
CURK = DATA_L2 + 0x10            # the wrapper running: its stage,
CURN = DATA_L2 + 0x14            # its stride in words,
CUROFF = DATA_L2 + 0x18          # its offset in a slot's state copy,
CURFL = DATA_L2 + 0x1C           # bit 0 the first stage, bit 1 the amp,
CURTL = DATA_L2 + 0x20           # its L call's trampoline - 1,
CURTR = DATA_L2 + 0x24           # its R call's
ARGS = 6                         # words above the frame copied for each extra call (every stage reads
                                 # at most four: its pushed words and the slot the body reserves)
# stage 2b, the render (dnfw.sampler.program.stereo_voice): a stereo voice's sample is read
# twice a block, L then R (the reader's weights: 0 0 the mix, 1 -1 L, -1 1 R, see fetch)
STW_L = DATA_L2 + 0x30           # the reader's weights (float): out = fa + fb + WL fa + WR fb
STW_R = DATA_L2 + 0x34
STBUF = DATA_L2 + 0x38           # the voice's block, when not stock's (R's run: RBLK[slot])
STSL = DATA_L2 + 0x3C            # the slot of the voice being rendered (-1: none)
STMIX = DATA_L2 + 0x40           # 1: its L run read the mix (a new stereo note), run again
STCTR = DATA_L2 + 0x44           # a loop counter
STPASS = DATA_L2 + 0x48          # stereo_voice's pass: 0 first, 1 L again, 2 R; 3 done (4, 5: next is R, L again)
VOICE = DATA_L2 + 0x50           # [slot]: the voice
DUP = DATA_L2 + 0x60             # [slot]: test mode, R's block is L's as rendered
MONO = DATA_L2 + 0x70            # [slot]: this block, R is L from here on (an unrecognised change)
LADDR = DATA_L2 + 0x100          # [slot][0]: the voice's first stage's state (0: free); the wrappers
                                 # find the others from VOICE (base + voice x stride)
SAVE_IN = DATA_L2 + 0x200        # 21 words: R0..R15, I0, I1, I3, I4, ASTAT as the body called
SAVE_OUT = DATA_L2 + 0x280       # the same, as L's call returned
SAVE_SUM = DATA_L2 + 0x300       # the sum hooks' register save
DMEM = DATA_L2 + 0x380           # [slot][stage]: the last scale recognised (0 none, j: CONSTS[j - 1])
PRE = DATA_L2 + 0x480            # L's state for this stage before its call (0x200 bytes at most)
RBLK = DATA_L2 + 0x680           # [slot]: R's block, 32 float32
LAMP = DATA_L2 + 0x880           # [slot]: L's block as the amp left it (the post-amp ramps, below)
LLAST = DATA_L2 + 0xA80          # [slot]: L's block as the last wrapper left it
R1RAMP = DATA_L2 + 0xC80         # [slot]: the first post-amp ramp (from the hook between the two)
RDEC = DATA_L2 + 0xE80           # [slot]: R's decimator history (12 words)
SNAP_PRE = DATA_L2 + 0xF80       # the voice's own words before its L run (48 words)
SNAP_POST = DATA_L2 + 0x1080     # ... and after it
ONE = 0x3F800000                 # 1.0

MID_SITE, MID_STOCK = 0x1C9A3A, "R1 = 0x4f800000;"            # between the two ramp loops
OFF = []                         # each stage's offset in a slot's state copy
_o = 0
for _sz in SIZES:
    OFF.append(_o)
    _o += _sz
STATE_BYTES = _o                 # 0x598 a voice
SLOT_STRIDE = 0x600              # (slot << 10) + (slot << 9): _state_copy
RST = DATA_L2 + 0x1180           # [slot]: R's state copies, SLOT_STRIDE apart
LPOST = RST + SLOTS * SLOT_STRIDE   # [slot]: what L's last call left

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
assert max(SIZES) <= RBLK - PRE and LADDR + 4 * SLOTS * len(STAGES) <= SAVE_IN
assert DMEM + 4 * SLOTS * 16 <= PRE and len(STAGES) <= 16 and SNAP_POST + 4 * 48 <= RST
assert DATA_L2 + DATA_BYTES <= 0x200B0000

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


def _loop_n(a: _Asm, name: str, ops) -> None:
    """CURN times OPS (the running wrapper's stride in words). Counts in R15."""
    a.e(f"R15 = DM({CURN:#x});")
    a.label(name)
    ops()
    a.e("R15 = R15 - 1;")
    a.jump("NE", name)


def _copy_n(a: _Asm, name: str) -> None:
    """CURN words from I1 on to I3 on. Clobbers R0, R15, I1, I3."""
    def ops():
        a.e("R0 = DM(I1, M6);")
        a.e("DM(I3, M6) = R0;")
    _loop_n(a, name, ops)


def _state_copy(a: _Asm, base: int, i: int) -> None:
    """I<i> = BASE + CUROFF + SLOT x SLOT_STRIDE (a slot's copy of the running stage's state).
    Clobbers R12, R13."""
    a.e(f"R13 = DM({SLOT:#x});")
    a.e("R12 = LSHIFT R13 BY 10;", "slot x 0x600")
    a.e("R13 = LSHIFT R13 BY 9;")
    a.e("R12 = R12 + R13;")
    a.e(f"R13 = DM({CUROFF:#x});")
    a.e("R12 = R12 + R13;")
    a.e(f"R13 = {base:#x};")
    a.e("R13 = R13 + R12;")
    a.e(f"I{i} = R13;")


def _push_and_go(a: _Asm, tramp: int) -> None:
    """the body's call again from inside our frame: the ARGS words above our frame (the body's
    pushed arguments, as the stage reads them: DM(1..ARGS, I6)) pushed again, then on to the
    running wrapper's trampoline (TRAMP: CURTL or CURTR), which makes the CJUMP"""
    a.e(f"DM({SAVE_I7:#x}) = I7;")
    for j in range(ARGS, 0, -1):
        a.e(f"R2 = DM({j}, I6);")
        a.e("DM(I7, M7) = R2;")
    a.e(f"I12 = DM({tramp:#x});")
    a.e("JUMP (M14, I12);", "not delayed: not the return idiom (JUMP (M14, I12) (DB))")


def _flag(a: _Asm, bit: int, skip: str) -> None:
    """on to SKIP unless the running wrapper's flag BIT is set. Clobbers R0, R1."""
    a.e(f"R0 = DM({CURFL:#x});")
    a.e(f"R1 = {1 << bit};")
    a.e("R0 = R0 AND R1;")
    a.jump("EQ", skip)


def _mono(a: _Asm, skip: str) -> None:
    """on to SKIP when the slot's MONO is set. Clobbers R0, R12, R13, I1."""
    _slot_base(a, MONO, 1, 2)
    a.e("R0 = DM(0, I1);")
    a.e("R0 = PASS R0;")
    a.jump("NE", skip)


def _detect(a: _Asm) -> None:
    """L's block on entry against LLAST: unchanged, or LLAST x one of CONSTS bit for bit (the
    body's own order: sample x constant), R's block is scaled the same; both (an all-zero L):
    the last answer for this slot and stage (DMEM); neither: ODD counted, MONO set. Clobbers
    R0..R5, R12, R13, R15, I0, I1, I3."""
    def l_and_last():
        a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});", "L's block (R12 as called)")
        a.e("I1 = R0;")
        _slot_base(a, LLAST, 3, 7)
    l_and_last()
    a.e("R3 = 1;", "unchanged, until a word differs")

    def same():
        a.e("R0 = DM(I1, M6);")
        a.e("R1 = DM(I3, M6);")
        a.e("COMP(R0, R1);")
        a.jump("NE", "wr_st_dsn")
    _loop(a, "wr_st_dsame", BLOCK, same)
    a.jump("", "wr_st_dc")
    a.label("wr_st_dsn")
    a.e("R3 = 0;")
    a.label("wr_st_dc")
    a.e("R5 = 0;", "the scale found (0: none)")
    for j, c in enumerate(CONSTS, 1):
        l_and_last()
        a.e(f"R2 = {c:#x};")

        def scaled(j=j):
            a.e("R0 = DM(I1, M6);")
            a.e("R1 = DM(I3, M6);")
            a.e("F1 = F1 * F2;")
            a.e("COMP(R0, R1);")
            a.jump("NE", f"wr_st_dx{j}")
        _loop(a, f"wr_st_dk{j}", BLOCK, scaled)
        a.e(f"R5 = {j};")
        a.jump("", "wr_st_dd")
        a.label(f"wr_st_dx{j}")
    a.label("wr_st_dd")
    a.e(f"R12 = DM({SLOT:#x});", "DMEM[slot][stage]")
    a.e("R12 = LSHIFT R12 BY 6;")
    a.e(f"R13 = DM({CURK:#x});")
    a.e("R13 = LSHIFT R13 BY 2;")
    a.e("R12 = R12 + R13;")
    a.e(f"R13 = {DMEM:#x};")
    a.e("R13 = R13 + R12;")
    a.e("I0 = R13;")
    a.e("R3 = PASS R3;")
    a.jump("EQ", "wr_st_dnot")
    a.e("R5 = PASS R5;")
    a.jump("EQ", "wr_st_dstore")
    a.e("R5 = DM(0, I0);", "both: the last answer")
    a.jump("", "wr_st_dapply")
    a.label("wr_st_dnot")
    a.e("R5 = PASS R5;")
    a.jump("NE", "wr_st_dstore")
    a.e(f"R0 = DM({ODD:#x});", "neither: counted, and R is L from here on")
    a.e("R1 = -1;")
    a.e("R0 = R0 - R1;", "+ 1 (G5: no add with a low first register)")
    a.e(f"DM({ODD:#x}) = R0;")
    _slot_base(a, MONO, 1, 2)
    a.e("R0 = 1;")
    a.e("DM(0, I1) = R0;")
    a.jump("", "wr_st_dend")
    a.label("wr_st_dstore")
    a.e("DM(0, I0) = R5;")
    a.label("wr_st_dapply")
    a.e("R5 = PASS R5;")
    a.jump("EQ", "wr_st_dend")
    a.e(f"R2 = {CONSTS[0]:#x};")
    for j, c in enumerate(CONSTS[1:], 2):
        a.e(f"R0 = {j - 1};")
        a.e("COMP(R5, R0);")
        a.jump("EQ", "wr_st_dm")
        a.e(f"R2 = {c:#x};")
    a.label("wr_st_dm")
    _rblk_to_i3(a)

    def mul():
        a.e("F0 = DM(0, I3);")
        a.e("F0 = F0 * F2;")
        a.e("DM(I3, M6) = F0;")
    _loop(a, "wr_st_dmul", BLOCK, mul)
    a.label("wr_st_dend")


def _l_to_r(a: _Asm) -> None:
    """R's block = L's (SAVE_IN's R12). Clobbers R0, R12, R13, R15, I1, I3."""
    a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});")
    a.e("I1 = R0;")
    _rblk_to_i3(a)
    _copy(a, f"wr_st_l2r{len(a.lines)}", BLOCK)


def program() -> str:
    a = _Asm()
    a.lines += ["// stereo.asm -- the R pass through stock's voice chain (docs/stereo-assessment.md).",
                "// GENERATED by scripts/gen_smp_asm.py from dnfw.sampler.stereo; do not edit by hand.",
                "", ".SECTION/PM seg_pmco;", ""]
    for k, (_site, target, _base, stride) in enumerate(STAGES):
        t = f"{target:#x}"
        # -- the entry: no stereo voice, or not this one: straight on to the stage --
        a.label(f"wr_st_t{k}")
        a.e(f"R0 = DM({ANY:#x});", "stereo slots in use")
        a.e("R0 = PASS R0;")
        a.jump_abs("EQ", target, "none: the stage, as stock")
        for s in range(SLOTS):                         # R4 - base = voice x stride? (R0 R1 only:
            a.e(f"R0 = DM({laddr(s, 0):#x});", f"slot {s} in use?")      # the body's R12 is the block)
            a.e("R0 = PASS R0;")
            a.jump("EQ", f"wr_st_n{k}_{s}")
            a.e(f"R0 = DM({VOICE + 4 * s:#x});", f"slot {s}'s voice")
            a.e(f"R1 = {stride:#x};")
            a.e("R0 = R0 * R1 (SSI);")
            a.e(f"R1 = {_base:#x};")
            a.e("R1 = R4 - R1;")
            a.e("COMP(R1, R0);")
            a.jump("EQ", f"wr_st_s{k}_{s}")
            a.label(f"wr_st_n{k}_{s}")
        a.jump_abs("", target, "a mono voice: the stage, as stock")
        for s in range(SLOTS):
            a.label(f"wr_st_s{k}_{s}")
            a.e(f"R1 = {s};")
            a.jump("", f"wr_st_c{k}")
        # -- a stereo voice: this stage's words, then the generic wrapper --
        a.label(f"wr_st_c{k}")
        a.e(f"DM({SLOT:#x}) = R1;")
        a.save(SAVE_IN)
        flags = (1 if k == 0 else 0) | (2 if k == len(STAGES) - 1 else 0)
        for at, v in ((CURK, k), (CURN, SIZES[k] // 4), (CUROFF, OFF[k]), (CURFL, flags)):
            a.e(f"R0 = {v:#x};")
            a.e(f"DM({at:#x}) = R0;")
        for at, lab in ((CURTL, f"wr_st_cl{k}"), (CURTR, f"wr_st_cr{k}")):
            a.lines.append("      R0 = 0x0;".ljust(40) + f"// return address - 1: {lab}. - 1")
            a.e(f"DM({at:#x}) = R0;")
        a.jump("", "wr_st_gen")
        for lab, back in ((f"wr_st_cl{k}", "wr_st_gl"), (f"wr_st_cr{k}", "wr_st_gr")):
            a.label(lab)                               # the stage returns just after its call,
            a.e(f"CJUMP {t} (DB);")                   # as everywhere (the runner checks it)
            a.e("DM(I7, M7) = R2;")
            a.lines.append("      DM(I7, M7) = 0x0;".ljust(40) + f"// return address - 1: {lab}_b. - 1")
            a.label(f"{lab}_b")
            a.jump("", back)
        a.lines.append("")

    # -- the generic wrapper (the running stage's words: CURK CURN CUROFF CURFL CURTL CURTR) --
    a.label("wr_st_gen")
    a.e("I1 = R4;", "PRE = L's state")
    _set(a, 3, PRE)
    _copy_n(a, "wr_st_pre")
    _flag(a, 0, "wr_st_notfirst")
    _slot_base(a, MONO, 1, 2)                      # the first stage: no MONO yet this block
    a.e("R0 = 0;")
    a.e("DM(0, I1) = R0;")
    _slot_base(a, DUP, 1, 2)                       # test mode: R's block is L's as rendered
    a.e("R0 = DM(0, I1);")
    a.e("R0 = PASS R0;")
    a.jump("EQ", "wr_st_lcall")
    _l_to_r(a)
    a.jump("", "wr_st_lcall")
    a.label("wr_st_notfirst")
    _mono(a, "wr_st_lcall")
    _detect(a)
    a.label("wr_st_lcall")
    a.restore(SAVE_IN)
    _push_and_go(a, CURTL)
    a.label("wr_st_gl")
    a.e(f"I7 = DM({SAVE_I7:#x});", "the copies off")
    a.save(SAVE_OUT)
    # LLAST = L's block as its call left it
    a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});")
    a.e("I1 = R0;")
    _slot_base(a, LLAST, 3, 7)
    _copy(a, "wr_st_llast", BLOCK)
    # R is L from here on this block (MONO): R's block = L's, no R call
    _slot_base(a, MONO, 1, 2)
    a.e("R0 = DM(0, I1);")
    a.e("R0 = PASS R0;")
    a.jump("EQ", "wr_st_stereo")
    _l_to_r(a)
    a.jump("", "wr_st_after")
    a.label("wr_st_stereo")
    # sync R's state: a word changed by anything but the stage follows L
    _state_copy(a, RST, 1)                         # I1 = R's state
    _state_copy(a, LPOST, 3)                       # I3 = LPOST
    _set(a, 4, PRE)

    def sync():
        a.e("R0 = DM(I4, M6);", "PRE")
        a.e("R1 = DM(I3, M6);", "LPOST")
        a.e("COMP(R0, R1);")
        a.jump("EQ", "wr_st_keep")
        a.e("DM(I1, M6) = R0;", "changed by another: follow L")
        a.jump("", "wr_st_next")
        a.label("wr_st_keep")
        a.e("R2 = DM(I1, M6);", "R's own: kept (the read moves I1 on)")
        a.label("wr_st_next")
    _loop_n(a, "wr_st_sync", sync)
    # LPOST = L's state as its call left it
    _state_copy(a, LPOST, 3)
    a.e(f"R0 = DM({SAVE_IN + 4 * 4:#x});", "L's state (R4 as called)")
    a.e("I1 = R0;")
    _copy_n(a, "wr_st_post")
    # R's state into the voice's own place for R's call (a stage may also reach its state
    # through a pointer other than R4)
    _state_copy(a, RST, 1)
    a.e(f"R0 = DM({SAVE_IN + 4 * 4:#x});")
    a.e("I3 = R0;")
    _copy_n(a, "wr_st_rin")
    # R's call: the body's registers (R4 the voice's own state, now R's), R's block
    a.restore(SAVE_IN)
    _rblk_to_i3(a)
    a.e("R12 = PASS R13;", "R's block")
    a.e("R8 = PASS R13;")
    a.e(f"I3 = DM({SAVE_IN + 4 * 18:#x});")
    _push_and_go(a, CURTR)
    a.label("wr_st_gr")
    a.e(f"I7 = DM({SAVE_I7:#x});", "the copies off")
    # R's state back to its copy, and L's state as L's call left it (LPOST)
    a.e(f"R0 = DM({SAVE_IN + 4 * 4:#x});")
    a.e("I1 = R0;")
    _state_copy(a, RST, 3)
    _copy_n(a, "wr_st_rout")
    _state_copy(a, LPOST, 1)
    a.e(f"R0 = DM({SAVE_IN + 4 * 4:#x});")
    a.e("I3 = R0;")
    _copy_n(a, "wr_st_lback")
    a.label("wr_st_after")
    _flag(a, 1, "wr_st_out")                       # the amp: LAMP = L's block, L's block = 1.0
    a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});", "L's block (R12 as called)")
    a.e("I1 = R0;")
    _slot_base(a, LAMP, 3, 7)
    _copy(a, "wr_st_lamp", BLOCK)
    a.e(f"R0 = DM({SAVE_IN + 4 * 12:#x});")
    a.e("I1 = R0;")
    a.e(f"R0 = {ONE:#x};")

    def ones():
        a.e("DM(I1, M6) = R0;")
    _loop(a, "wr_st_ones", BLOCK, ones)
    a.label("wr_st_out")
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
        a.e("R0 = LSHIFT R0 BY 1;", "x 2, its low 16 bits signed (stock: fext se)")
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
