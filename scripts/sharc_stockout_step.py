"""The SHARC runner's stockout step (the rule for changing Elektron's own DSP code): with only
stock machines (types 0-4) and stock filters, the build's OUTPUT is the stock image's, word for word, every block.

Step 4 (`stock`) compares the 16 mono track buffers. This compares what leaves the engine (docs/link-research.md
section 5, the output stage `0x1c244d`'s channel table), after each call of the per-block routine sw 0x1c2712:

- **main**: the main mix L / R (`0x268438`, 64 floats), after the master chain;
- **tracks A / B**: the 16 tracks' stereo blocks after the routing (`0x258f68 + 0x100 t`) and the panned raw tracks
  (`0x259f68 + 0x100 t`), what Overbridge's track channels carry;
- **FX returns**: the three send FX's stereo returns (`0x25b068..0x25b868`);
- **TDM**: the transmit page the block wrote, slots 0..13 of its 32 frames (slots 14 and 15 are our link's), filled
  with a marker at the output stage's call so a word left from the runner's frame (it overlaps the page) is not compared
  as output;
- **records**: the reply page's Overbridge records (`+0x1c..+0xaa0` of the reply buffer, the output stage's third
  argument, read at its call sw 0x1c307b; in the runner the caller's locals are zeros, so the buffer is at 0);
- the 16 mono track buffers at the block's end are reported, not required: they are the chain's scratch, already
  read into the panned blocks (tracks B) when the output stage runs, and on the current build a few of their words
  differ after that (signed zeros, and one track's low bits on 2026-11-12) while every output above is the same.

Words are compared as bit patterns (NaN included). The frames: every track on a stock machine, random parameter
words on every carried index (machine pages, filter, amp, FX sends, overdrive, ...), random notes and filter types,
trigs spread over the blocks, a few words changed every block (as p-locks and LFOs arrive), a stretch of silence
with the sends up and then a wake, and the frame's FX and master words (after the slots) random. Only what stock's
ColdFire can send: parameter words 0..0x7f00 and filter types 0-5. Header words other than the notes, levels, machines and filters
stay 0, as in the runner's other frames. Also reported, not required: how many words of stock's L1 state
(`0x240000..0x2c0000`) differ, for the changes that also claim state identity (their own proofs check that). A
control flips one bit of the main mix in the build's run and must be seen.
"""

from __future__ import annotations

import os
import random

from dnfw.waverider import frame as FR

OUTPUT_CALL_SW = 0x1C307B                       # the engine's call of the output stage 0x1c244d (R12 = reply)
MAIN = (0x268438, 64)
TRACKS_A = (0x258F68, 16 * 64)
TRACKS_B = (0x259F68, 16 * 64)
FX_RETURNS = (0x25B068, 0x800 // 4)
TX_BASE, TX_PAGE_WORD = 0x2C08E8, 0x268A38      # docs/link-research.md: TX page = base + (DM(0x268a38) << 11)
TX_SLOTS = 14
RECORDS = (0x1C, 0xAA0)
STATE_L1 = (0x240000, 0x2C0000)
OUTPUTS = ("main", "tracks A", "tracks B", "FX returns", "TDM", "records")
STOCK_TYPES = (0, 1, 2, 3, 4)                   # FM TONE, WAVETONE, FM DRUM, SWARMER, MIDI
INDICES = [i for first, last, _ in FR.SLOT_BLOCKS for i in range(first, last + 1)]
FRAME_COPY = 0x25C48C                           # where the engine copies the frame image
# the kit's FX and master words ride after the 16 slots, up to the voice-slot routing map (0xa5a + 2 s) and the
# Overbridge source flag (0xa7a), which stay as the runner's frames have them
TAIL_FREE = list(range(FR.SLOT_BASE + FR.SLOT_STRIDE * FR.TRACKS, 0xA5A, 2))
TX_MARK = 0x7FC0DEAD                            # the TX page before the output stage: what it writes is what differs


def scenario(sound, machines, seed: int, blocks: int, *, globals_random: bool, silence: tuple | None):
    """frame(b) for one scenario: the same bytes for the stock image and the build"""
    rnd = random.Random(seed)
    types = [STOCK_TYPES[(t + seed) % 5] for t in range(16)]
    pages = {t: {i: rnd.randrange(0, 0x7F01) for i in INDICES} for t in range(16)}
    notes = [rnd.randrange(24, 96) << 8 | rnd.randrange(256) for _ in range(16)]
    filters = [rnd.randrange(0, 6) for _ in range(16)]
    trig_at = {t: {rnd.randrange(1, max(2, blocks // 2)), rnd.randrange(1, blocks)} for t in range(16)}
    glob = {o: rnd.randrange(0, 0x7F01) for o in TAIL_FREE} if globals_random else {}
    moves = [[(rnd.randrange(16), rnd.choice(INDICES), rnd.randrange(0, 0x7F01)) for _ in range(6)]
             for _ in range(blocks)]

    def fb(b):
        f = FR.Frame()
        for o, v in glob.items():
            f.put(o, v)
        quiet = silence is not None and silence[0] <= b < silence[1]
        for t in range(16):
            f.header(FR.MACHINE, t, types[t])
            f.header(FR.FILTER, t, filters[t])
            f.header(FR.NOTE, t, notes[t])
            f.header(FR.LEVEL, t, 0x6400)
            f.sound(t, {**machines.get(types[t], {}), **pages[t]})
            if b in trig_at[t] and not quiet:
                f.trigger(t)
        for t, i, v in moves[b]:
            pages[t][i] = v
        if silence is not None and b == silence[1]:
            for t in range(16):
                f.trigger(t)
        return f.to_bytes()
    return fb


EXP_MASK = 0x7F800000                           # a float32 word with every exponent bit set is NaN or infinity


def finite(words) -> bool:
    """every word a finite float32 (no NaN, no infinity)"""
    return all((w & EXP_MASK) != EXP_MASK for w in words)


def sounds(words) -> bool:
    """some word is a finite, nonzero float32: sound. NaN and infinity are not (2026-11-14: `w & 0x7fffffff` alone
    counted them, so a run of NaN passed as sound)"""
    return any((w & EXP_MASK) != EXP_MASK and w & 0x7FFFFFFF for w in words)


def tx_page(m2, st) -> int:
    return TX_BASE + (((m2.word(st, TX_PAGE_WORD) or 0) & 1) << 11)


def mark_tx(m2, st) -> None:
    """at the output stage's call: the page it is about to write, filled with TX_MARK"""
    at = tx_page(m2, st)
    for k in range(0, 0x800, 4):
        m2.poke(st, at + k, TX_MARK)


def outputs(m2, st, reply):
    def words(at, n):
        return tuple((m2.word(st, at + 4 * k) or 0) & 0xFFFFFFFF for k in range(n))
    tx = tx_page(m2, st)
    out = {"main": words(*MAIN), "tracks A": words(*TRACKS_A), "tracks B": words(*TRACKS_B),
           "FX returns": words(*FX_RETURNS),
           "TDM": tuple((m2.word(st, tx + 64 * f + 4 * s) or 0) & 0xFFFFFFFF for f in range(32) for s in range(TX_SLOTS)),
           "records": words(reply + RECORDS[0], (RECORDS[1] - RECORDS[0]) // 4) if reply is not None else None}
    return out


# the control: in one block of the build's run, one mantissa bit of the main mix's first sample is flipped as the
# output stage is called (it reads the mix from there into TDM slot 0): the comparison must see it
CONTROL_WORD = MAIN[0]


def run(M5, snap, m2mach, m5img, stockimg, sound, machines, blocks: int = 16) -> dict:
    m2 = M5.m2
    plan = [("rotate A, globals stock", 11, False, None),
            ("rotate B, globals random", 16, True, None),
            ("rotate C, globals random", 13, True, None),
            ("silence then wake, sends up", 14, False, (blocks // 4, blocks - 3)),
            ("control: one bit of the main mix flipped in the build at block 3", 11, False, None)]
    only = os.environ.get("STOCKOUT_ONLY")          # a name's start: run that scenario alone (while a step is built)
    if only:
        plan = [x for x in plan if x[0].startswith(only)]
    checks, numbers = {}, {}
    for name, seed, gl, sil in plan:
        fb = scenario(sound, machines, seed, blocks, globals_random=gl, silence=sil)
        runs = {}
        for which, img in (("stock", stockimg), ("build", m5img)):
            state = M5.init_on(snap, m2mach, img)
            caps, halt = [], None
            for b in range(blocks):
                cur = {}

                def at_out(r, cur=cur):
                    cur["reply"] = m2.word_reg(r, "R12")   # (0 in the runner: its caller's locals are zeros)
                    mark_tx(m2, r.state)
                def flip(r, at_out=at_out):
                    at_out(r)
                    m2.poke(r.state, CONTROL_WORD, (m2.word(r.state, CONTROL_WORD) or 0) ^ 0x00400000)
                hooks = {OUTPUT_CALL_SW: at_out}
                if name.startswith("control") and which == "build" and b == 3:
                    hooks[OUTPUT_CALL_SW] = flip
                res = M5.run_blocks(state, lambda _b, b=b: fb(b), 1, extra_hooks=hooks)
                if not res.get("ok"):
                    halt = f"block {b}: {res.get('halt')}"
                    break
                state = res["state"]
                st = state.state
                o = outputs(m2, st, cur.get("reply"))
                o["track buffers"] = tuple(res["buffer_bits"][0][t][k] for t in range(16) for k in range(32))
                o["state"] = tuple((m2.word(st, a) or 0) & 0xFFFFFFFF for a in range(*STATE_L1, 4))
                caps.append(o)
            runs[which] = {"caps": caps, "halt": halt}
        s, d = runs["stock"], runs["build"]
        both = s["halt"] is None and d["halt"] is None
        diff = {}
        if both:
            for key in OUTPUTS:
                bad = [b for b, (x, y) in enumerate(zip(s["caps"], d["caps"])) if x[key] != y[key]]
                if bad:
                    diff[key] = bad
        sounding = both and any(sounds(c["main"]) for c in s["caps"])
        main_finite = both and all(finite(c["main"]) for c in s["caps"] + d["caps"])
        records = both and all(c["records"] is not None for c in s["caps"] + d["caps"])
        tb_diff = [b for b, (x, y) in enumerate(zip(s["caps"], d["caps"])) if x["track buffers"] != y["track buffers"]] \
            if both else None
        state_diff = [sum(1 for x, y in zip(a["state"], b2["state"]) if x != y)
                      for a, b2 in zip(s["caps"], d["caps"])] if both else None
        checks[f"{name}: both images return every block"] = both
        if name.startswith("control"):
            checks[f"{name}: the comparison sees it"] = both and bool(diff)
            numbers[name] = {"differing (output: blocks)": diff}
            continue
        checks[f"{name}: the stock run sounds on the main mix (finite, nonzero words)"] = sounding
        checks[f"{name}: the main mix is finite (no NaN, no infinity), every block, both images"] = main_finite
        checks[f"{name}: the reply buffer was found at the output stage's call"] = records
        checks[f"{name}: main, tracks A/B, FX returns, TDM 0..13, records bit-identical, every block"] = (
            both and not diff)
        numbers[name] = {"differing (output: blocks)": diff, "halts": {k: v["halt"] for k, v in runs.items() if v["halt"]},
                         "mono track buffers at the block's end differing (reported, not required)": tb_diff,
                         "stock L1 state words differing per block (reported, not required)": state_diff}
    return {"ok": all(checks.values()), "checks": checks, "numbers": numbers}
