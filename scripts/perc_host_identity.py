"""The PERC voice host re-coded must sound bit for bit as before: record on the unchanged code, check after.

Every machine of PERC's voice (the Machinedrum machines, the Monomachine machines) through the whole voice as the
DSP runs it each block: dnfw.perc.program.mnm_ages (the keys, costs, rests, the order), then
dnfw.perc.program.voice for every sounding slot in the order it made, on one memory, three voices at once on
slots 0, 3 and 6 (both parities of the frame's halves). Each scenario `mix<i>` (machines i, i+1, i+2): notes on
blocks 1 and 20 (another pitch), the knobs moved on block 10, the track effects on from block 14, slot 0 changed
to the next machine on block 30 with a note on 31; the track buffers left as the voices wrote them (as the chain
leaves them), then zeroed from block 34 (an amp released). Three more: `rests` (three cheap voices for 110
blocks: 64 quiet blocks, then a note wakes them), `nan` (a NaN in a voice's stream: the output guard's wipe),
`types` (the other tracks on every kind of type word: stock machines, the sample machines, unused and garbage
types, with notes). Hashed: every output block of every slot, and the voices' persistent state (PERC's slot
words, the Machinedrum slot words, the Monomachine bookkeeping: keys, costs, order, rests, strikes).

    python scripts/perc_host_identity.py record OUT.json [--jobs N]
    python scripts/perc_host_identity.py check REF.json [--jobs N] [--only SCENARIO,..]

Needs MD_OS_BIN and MNM_OS as the build does. Exit 0 on PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import struct
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SLOTS = (0, 3, 6)
BUF = 0x00300000                               # the harness's track buffers (L1, as trackbuf.asm puts them)


def engines() -> list[tuple[str, object]]:
    """(name, setup(h, t)): puts slot T's frame words on the machine at its defaults"""
    from dnfw.md import voice as MDV
    from dnfw.mnm import machines as MM
    from dnfw.perc import live as PL
    out = []
    for k, M in enumerate(MDV.MM.MACHINES):
        out.append((M.NAME, lambda h, t, k=k, n=M.NAME: _at(h, t, lambda: h.set_controls(k, PL.defaults(n)))))
    for k, n in enumerate(MM.NAMES):
        out.append((n, lambda h, t, k=k, n=n: _at(h, t, lambda: h.set_mnm(MM.TYPES[k], MM.DEFAULTS[n]))))
    return out


def _at(h, t, fn) -> None:
    keep, h.t = h.t, t
    try:
        fn()
    finally:
        h.t = keep


def _records(h, t, rnd, recs) -> None:
    """slot T's records RECS moved to random values (their full ranges)"""
    from dnfw.perc import machines as PMx
    for _rid, slot, lo, top in recs:
        _at(h, t, lambda slot=slot, lo=lo, top=top: h._half(PMx.frame_offset(slot), (rnd.randint(0, top) + lo) << 8))


class Run:
    """one memory, the DSP's PERC entry each block: mnm_ages, then the voices in ORDER"""

    def __init__(self):
        from dnfw.md import core as MDK
        from dnfw.mnm import dpro as MNP
        from dnfw.perc import live as PL
        self.h = PL.Harness()
        self.h.words[self.h.L.md.C["fill"]] = MDK.Z_N
        self.h.words.update(MNP.bench_words(self.h.L.md.mnm))
        self.L = self.h.L
        for t in range(16):                            # tracks not ours: MIDI (type 4)
            self.type_word(t, 4)
        self.out = hashlib.sha256()
        self.blocks = 0
        self.steps = 0

    def type_word(self, t: int, ty: int) -> None:
        from dnfw.perc import machines as PMx
        a = PMx.FRAME + 148 + 2 * t
        w = self.h.mem.get(a & ~3)
        self.h.mem.put(a & ~3, (w & 0xFFFF) | (ty << 16) if a & 2 else (w & 0xFFFF0000) | ty)

    def block(self, notes: dict, trigs: set, zero: bool) -> None:
        from dnfw.perc import program as PP
        from dnfw.perc.dsl import Prog, bits
        mem, L = self.h.mem, self.L
        mem.put(PP.TRIG_WORD, sum(1 << (16 + t) for t in trigs))
        for t, n in notes.items():
            mem.put(PP.NOTE_CELLS + 4 * t, bits(n))
            mem.put(PP.BUFFERS + 4 * t, BUF + 128 * t)
            if zero:
                for k in range(32):
                    mem.put(BUF + 128 * t + 4 * k, 0)
        mem.put(L.C["mcost"], 0)
        p = Prog("run", mem=mem)
        p.spill = L.md.C["ash"]
        PP.mnm_ages(p, L)
        self.steps += p.steps
        order = [mem.get(PP.ORDER + 4 * k) for k in range(16)]
        for t in order:
            if t in notes:
                q, _ = PP.run_voice(L, None, t, mem=mem)
                self.steps += q.steps
        for t in sorted(notes):
            self.out.update(b"".join(struct.pack("<I", mem.get(BUF + 128 * t + 4 * k)) for k in range(32)))
        self.blocks += 1

    def state(self) -> str:
        from dnfw.md import core as MDK
        from dnfw.perc import program as PP, machines as PMx
        mem, L = self.h.mem, self.L
        words = []
        for t in range(16):
            words += [mem.get(L.state + 128 * t + 4 * k) for k in range(PMx.STATE_WORDS)]
        for t in SLOTS:
            words += [mem.get(L.md.state + MDK.MD_STRIDE * t + 4 * k) for k in range(MDK.MD_WORDS)]
        end = PP.STRIKES_OFF + 4 * 16                  # keys, costs, order, RANK_U/N, PERC_I, SMP_I, rests, strikes
        words += [mem.get(PP.MNM_SCRATCH + PP.MNM_KEYS_OFF + 4 * k) for k in range((end - PP.MNM_KEYS_OFF) // 4)]
        return hashlib.sha256(b"".join(struct.pack("<I", w & 0xFFFFFFFF) for w in words)).hexdigest()


def scenario(name: str) -> dict:
    """one scenario by name: 'mix<i>', 'rests', 'nan', 'types'"""
    from dnfw.perc import machines as PMx
    eng = engines()
    rnd = random.Random(name)
    r = Run()
    if name.startswith("mix"):
        i = int(name[3:])
        pick = [eng[(i + j) % len(eng)] for j in range(3)]
        nxt = eng[(i + 3) % len(eng)]
        for (_n, setup), t in zip(pick, SLOTS):
            r.type_word(t, 5)
            setup(r.h, t)
        notes = {t: 60.0 + 7 * j for j, t in enumerate(SLOTS)}
        for b in range(40):
            if b == 10:
                for t in SLOTS:
                    _records(r.h, t, rnd, PMx.PARAMS)
            if b == 14:
                for t in SLOTS:
                    _records(r.h, t, rnd, PMx.FX_PARAMS)
            if b == 30:
                r.type_word(SLOTS[0], 5)
                nxt[1](r.h, SLOTS[0])
            if b == 20:
                notes = {t: 48.5 + 5 * j for j, t in enumerate(SLOTS)}
            trigs = set(SLOTS) if b in (1, 20) else {SLOTS[0]} if b == 31 else set()
            r.block(notes, trigs, zero=b >= 34)
    elif name == "rests":
        names = ("GND-IM", "TRX-BD", "DPRO-WAVE")
        for t, n in zip(SLOTS, names):
            r.type_word(t, 5)
            dict(eng)[n](r.h, t)
        notes = {t: 60.0 for t in SLOTS}
        for b in range(110):
            r.block(notes, set(SLOTS) if b in (1, 100) else set(), zero=b >= 8)
    elif name == "types":                              # the other tracks on every kind of type word (mnm_ages)
        from dnfw.sampler import machines as SM
        names = ("EFM-SD", "VO-6", "SID 6581")
        for t, n in zip(SLOTS, names):
            r.type_word(t, 5)
            dict(eng)[n](r.h, t)
        others = [t for t in range(16) if t not in SLOTS]
        kinds = [0, 1, 2, 3, *SM.TYPES, 5, 6, 7, 14, 15, 16, 23, 31, 32, 33, 255, 0xFFFF]
        notes = {t: 57.0 for t in SLOTS}
        for b in range(30):
            if b % 10 == 0:                            # three sets of types on the other tracks
                for j, t in enumerate(others):
                    r.type_word(t, kinds[(j + 7 * (b // 10)) % len(kinds)])
            extra = {others[b % len(others)]} if b % 3 == 0 else set()
            r.block(notes, (set(SLOTS) | extra) if b in (1, 12) else extra, zero=b >= 20)
    elif name == "nan":
        from dnfw.md import core as MDK
        names = ("TRX-SD", "DPRO-DENS", "PI-BD")
        for t, n in zip(SLOTS, names):
            r.type_word(t, 5)
            dict(eng)[n](r.h, t)
        notes = {t: 62.0 for t in SLOTS}
        for b in range(24):
            if b == 9:                                 # the stream of slot 0 poisoned: the guard wipes it
                for k in range(MDK.B0 - 1, MDK.B0 + MDK.NB):
                    r.h.mem.put(r.L.md.state + MDK.MD_STRIDE * SLOTS[0] + 4 * k, 0x7FC00000)
            r.block(notes, set(SLOTS) if b in (1, 14) else set(), zero=False)
    else:
        raise SystemExit(f"no scenario {name}")
    return {"out": r.out.hexdigest(), "state": r.state(), "blocks": r.blocks, "steps": r.steps}


def names() -> list[str]:
    return [f"mix{i}" for i in range(len(engines()))] + ["rests", "nan", "types"]


def _one(name: str) -> tuple[str, dict]:
    return name, scenario(name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("record", "check"))
    ap.add_argument("path", type=pathlib.Path)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    want = [n for n in names() if not a.only or n in a.only.split(",")]
    t0 = time.time()
    if a.jobs > 1:
        import multiprocessing as mp
        with mp.get_context("fork").Pool(a.jobs) as pool:
            res = dict(pool.imap_unordered(_one, want))
    else:
        res = dict(map(_one, want))
    print(f"{len(res)} scenarios, {sum(v['blocks'] for v in res.values())} blocks, "
          f"{sum(v['steps'] for v in res.values()):,} model steps, {time.time() - t0:.0f} s")
    if a.mode == "record":
        a.path.parent.mkdir(parents=True, exist_ok=True)
        a.path.write_text(json.dumps(res, indent=1, sort_keys=True))
        print(f"recorded {a.path}")
        return 0
    ref = json.loads(a.path.read_text())
    bad = [n for n in res if n not in ref or ref[n]["out"] != res[n]["out"] or ref[n]["state"] != res[n]["state"]]
    for n in bad:
        what = [k for k in ("out", "state") if ref.get(n, {}).get(k) != res[n][k]]
        print(f"  {n}: {', '.join(what)} differ")
    st0 = sum(ref[n]["steps"] for n in res if n in ref)
    st1 = sum(res[n]["steps"] for n in res)
    print(f"model steps {st0:,} -> {st1:,} ({st1 - st0:+,})")
    if a.only:
        print("ONLY " + a.only + ": a partial check")
    print(("PASS" if not bad else "FAIL") + f": {len(res)} scenarios, {len(bad)} differ")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
