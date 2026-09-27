"""Does skipping an idle LFO4 change what the evaluators write? Old build against fast.

    # in WSL, with digikit's venv (docs/emulator.md), once per build:
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \\
        scripts/emu_lfo4_idle.py --build out/lfo4-everyvoice4 --out /tmp/old.json
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \\
        scripts/emu_lfo4_idle.py --build out/lfo4-fast --out /tmp/fast.json
    python scripts/emu_lfo4_idle.py --compare /tmp/old.json /tmp/fast.json

`lfo4-fast` skips the fourth LFO iteration for a track whose LFO4 has no
destination, and skips the bridge call altogether while the table is empty
(`scripts/build_lfo4_bridge.py`, `idle_skip`). The claim is that nothing the
engine reads changes. This checks it on the evaluators' own output, three ways,
each from the same snapshot with the same inputs:

1. **the table empty** -- every track idle, no call at all;
2. **entries with no destination** -- all sixteen sounds carry an LFO4 row
   (SPD and DEP set) whose DEST is 0: the table is not empty, so the bridge
   runs, and every iteration is skipped on the row's DEST;
3. **a mix** -- tracks 1-4 with LFO4 on filter base (slot 76);
4. **every track** with LFO4 on slot 76 -- the fast build must be the old one.

Blocks are voices, not tracks (`csrc/lfo4/bridge.c`), so how many blocks a
case moves is the old build's answer; in `ui1200M` the four tracks of case 3
already own every voice.

After each, evaluator A has run `--frames` frames over the laid-out mirror and
evaluator B once per index over its state, and the whole mirror is recorded.

What is allowed to differ is one thing: **slot 0 of an idle track**. DEST 0 is
the LFOs' no-destination sink, and the only write a skipped iteration would
have made is LFO4's contribution to it. Every other word must match exactly.
The live state arrays are not compared: an idle LFO4's phase record is what the
skip deliberately stops advancing.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

EVAL_A, RATE = 0x40137726, 0x402A0DEC
EVAL_B, EVAL_B_STATE = 0x401373DC, 0x44616448
SET_FRAC = bytes.fromhex("a93c000000204e75")      # movel #32,%macsr ; rts
MIRROR_AT, MIRROR_BYTES, TRACKS, REST = 34, 202, 16, 0x4000
LIVE_CONTAINER, SOUND_AT, SOUND = 0x800052A0, 52, 1163
# Evaluator B writes through its own pointers, so its output is taken as every
# write it makes, less what may legitimately differ: the LFO state arrays (an
# idle LFO4's record stops advancing), our own BSS (counters, row caches) and
# the harness's stack.
EXCLUDE = ((0x46700000, 0x46703000), (0x46800000, 0x46900000), (0x469F0000, 0x46A00800))
DEST_SLOT = 76
CASES = (("empty", 0, DEST_SLOT), ("nodest", 16, 0), ("mix", 4, DEST_SLOT), ("all", 16, DEST_SLOT))


def run(args) -> dict:
    from emulib.image import code_chunks, differences
    from emulib.machine import Machine

    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    built = open(os.path.join(args.build, "section_3_MAIN_OS.bin"), "rb").read()
    sym = {k: int(v, 16) for k, v in json.load(open(os.path.join(args.build, "symbols.json"))).items()}
    out = {"build": args.build}
    for name, tracks, dest in CASES:
        m = Machine()                                 # a fresh machine per case
        m.apply(differences(stock, built))
        for chunk in code_chunks(built):
            m.load_code_chunk(chunk)
        m.flush()
        base = m.long(LIVE_CONTAINER)
        for t in range(tracks):
            live = base + SOUND_AT + SOUND * t
            m.call(sym["ext_set"], live, 0, 0x7800)           # SPD, fast
            m.call(sym["ext_set"], live, 3, dest << 8)        # DEST
            m.call(sym["ext_set"], live, 7, 0x7000)           # DEP
        frac = m.alloc(len(SET_FRAC))
        m.write(frac, SET_FRAC)
        m.call(frac)
        span = MIRROR_AT + TRACKS * MIRROR_BYTES + 32
        buf = m.alloc(span)
        m.write(buf, struct.pack(">H", REST) * (span // 2))
        o1, o2 = m.alloc(256), m.alloc(256)
        rate = m.long(RATE)
        for _ in range(args.frames):
            m.call(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, o1, o2, 0)
        writes = {}

        def note(pc, address, value, size):
            if not any(lo <= address < hi for lo, hi in EXCLUDE):
                writes[f"{address:#010x}/{size}"] = value & ((1 << (8 * size)) - 1)

        handle = m.watch_writes(0x40000000, 0x4FFFFFFF, note)
        for t in range(TRACKS):
            m.call(EVAL_B, EVAL_B_STATE, t, 1 << t)
        m.uc.hook_del(handle)
        out[name] = {"tracks": tracks, "ext_live": m.long(sym["ext_live"]),
                     "a": m.read(buf, span).hex(), "b": writes}
        print(f"  {name}: {tracks} track(s) with LFO4, ext_live {out[name]['ext_live']}")
    return out


def compare(old_path: str, new_path: str) -> int:
    old, new = json.load(open(old_path)), json.load(open(new_path))
    failures = 0
    for name, tracks, dest in CASES:
        a0, a1 = bytes.fromhex(old[name]["a"]), bytes.fromhex(new[name]["a"])
        allowed, other = [], []
        for off in range(0, min(len(a0), len(a1)) - 1, 2):
            if a0[off:off + 2] == a1[off:off + 2]:
                continue
            track, rem = divmod(off - MIRROR_AT, MIRROR_BYTES)
            slot = rem // 2
            (allowed if slot == 0 else other).append((track, slot))
        def moved(a):
            return sum(1 for off in range(MIRROR_AT, len(a) - 1, 2)
                       if (off - MIRROR_AT) % MIRROR_BYTES == 2 * DEST_SLOT
                       and a[off:off + 2] != struct.pack(">H", REST))

        # **Blocks are voices, not tracks** (`csrc/lfo4/bridge.c`): a block
        # takes the LFO4 of whichever track's sound is on that voice, so how
        # many blocks move is the old build's answer, not the track count.
        moved0, moved1 = moved(a0), moved(a1)
        b0, b1 = old[name]["b"], new[name]["b"]
        b_diff = sorted(k for k in set(b0) | set(b1) if b0.get(k) != b1.get(k))
        b_same = not b_diff
        ok = not other and b_same and moved1 == moved0 and (moved0 > 0) == (tracks > 0 and dest > 0)
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:<5} evaluator A: {len(other)} word(s) differ "
              f"outside an idle track's sink, {len(allowed)} inside it; slot {DEST_SLOT} moved in "
              f"{moved1} block(s), the old build {moved0}; evaluator B's writes "
              f"{'identical' if b_same else 'DIFFERS'} ({len(b0)} words written, {len(b_diff)} differ)")
        for track, slot in other[:6]:
            print(f"          track {track + 1} slot {slot}")
        for k in b_diff[:6]:
            print(f"          B {k}: {b0.get(k)} -> {b1.get(k)}")
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build")
    p.add_argument("--frames", type=int, default=64)
    p.add_argument("--out")
    p.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"))
    args = p.parse_args()
    if args.compare:
        return compare(*args.compare)
    out = run(args)
    with open(args.out, "w", newline="\n") as f:
        json.dump(out, f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
