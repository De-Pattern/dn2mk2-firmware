"""What each mod costs on the stock path, in instructions, against stock.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \\
        scripts/emu_mod_cost.py --label lfo4 --build out/modcost/lfo4
    # the stock control: no --build
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \\
        scripts/emu_mod_cost.py --label stock
    # then the table, from every JSON the runs wrote:
    python scripts/emu_mod_cost.py --table out/modcost

**The question (owner, 2026-09-27).** With fxmod + lfo4 + songguard + arpmodes,
SAVE PROJECT while a pattern plays stutters the playback until the save ends,
with the arp on UP as much as on RAND. Stock 1.11 does not. So the suspect is
what the mods cost *on the path every build runs*, not on a mode the owner
chose. This measures that path, one build at a time, from the same snapshot and
with the same inputs, so the only difference between two runs is the build.

**What it can and cannot reach.** The sequencer does not play under the
emulator and the audio-frame chain needs the DSP side that is not modelled
(`docs/emulator.md`), so nothing here runs *the* frame. What it runs is each
routine on that path that a mod changed, entered directly with the arguments
the firmware's own call sites pass:

| probe | routine | runs in | why |
|---|---|---|---|
| `eval_a` | evaluator A `0x40137726`, one call = one frame's LFO pass over 16 tracks | the audio frame (`0x400272d4`) | lfo4's fourth LFO and fxmod's DEST hook live inside it |
| `eval_b` | evaluator B `0x401373dc`, one index | the priority-8 task (`0x4012b0aa`) | lfo4 patches it too |
| `memcpy_202`, `memcpy_2688`, `memset_1163` | `0x40134490`, `0x401344d8` | everywhere, the frame included | lfo4 hooks both entries |
| `save_sound`, `load_sound` | SAVE `0x400dd6a6`, LOAD `0x400dd1ea`, per live sound | the save and load jobs | lfo4 hooks both converters; arpmodes bounds LOAD; the slot lookup fxmod hooks may sit in them |
| `arp_up` | the arp step `0x4002a0bc`, UP, four notes | the frame ISR's trig handler | arpmodes' hook is past UP's branch, so this must equal stock |
| `arp_rand`, `arp_shuf` | the same step, RAND and SHUF, four notes over RNG 1 | the same | arpmodes' own cost in the owner's kind of use (stock plays CYCL) |
| `arp_*_worst` | 128 notes over RNG 7: 1,024 entries | the same | SHUF's longest bit scan |
| `serialise` | the project serialiser `0x400e1494`, the whole project (`--serialise`) | the MRAM / SAVE PROJECT job | what a save actually runs; how much of it is ours |

Every probe reports its instructions and how many of them executed inside the
build's own code (its caves, its hook stubs, its appended chunks), so a
difference to stock is attributed rather than inferred. `writes_above_bss`
records every write between BSS's end and the harness's stack, by whose code:
the mods' RAM is there, and a stock writer there would be a collision.

The instruction count is the cost measure. It is not a time: the instrument's
cache, the eMMC DMA's bus traffic and the RTOS are not modelled. It is what can
be compared, build against build, exactly.
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import pathlib
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

EVAL_A, RATE = 0x40137726, 0x402A0DEC
EVAL_B, EVAL_B_STATE = 0x401373DC, 0x44616448     # (state, index, 1 << index), 0x4012b0aa
SET_FRAC = bytes.fromhex("a93c000000204e75")      # movel #32,%macsr ; rts (emu_lfo4_tick.py)
MIRROR_AT, MIRROR_BYTES, TRACKS, REST = 34, 202, 16, 0x4000
MEMCPY, MEMSET = 0x40134490, 0x401344D8
SAVE, LOAD = 0x400DD6A6, 0x400DD1EA               # (stored, live, flag), (live, stored)
SOUND, STORED = 1163, 359
LIVE_CONTAINER, SOUND_AT = 0x800052A0, 52
STEP = 0x4002A0BC
SERIALISE, PROJECT_HOLDER = 0x400E1494, 0x4018A97A
MRAM_IMAGE = 0x405CD96C
BSS_END = 0x466B74D0                              # every mod's RAM lives above this
STACK, STACK_DEPTH = 0x46A00000, 0x10000          # emulib.machine's call stack, and its reach


def mod_ranges(stock: bytes, built: bytes, chunks):
    """-> sorted, merged [lo, hi) the build owns: changed runs and loaded chunks."""
    from emulib.image import differences

    spans = [(va, va + len(b)) for va, b in differences(stock, built)]
    spans += [(load, load + length + bss) for load, length, bss, _, _ in chunks]
    spans.sort()
    merged = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return merged


class Meter:
    """Counts every instruction, and those inside the build's own ranges."""

    def __init__(self, m, ranges):
        from unicorn import UC_HOOK_CODE

        self.m = m
        self.lo = [r[0] for r in ranges]
        self.hi = [r[1] for r in ranges]
        self.total = self.ours = 0
        self.big = 0                              # memcpy / memset calls of >= one sound
        self.calls = 0
        m.uc.hook_add(UC_HOOK_CODE, self._tick)
        m.uc.hook_add(UC_HOOK_CODE, self._big, begin=MEMCPY, end=MEMCPY)
        m.uc.hook_add(UC_HOOK_CODE, self._big, begin=MEMSET, end=MEMSET)

    def _tick(self, uc, address, size, user):
        self.total += 1
        i = bisect.bisect_right(self.lo, address) - 1
        if i >= 0 and address < self.hi[i]:
            self.ours += 1

    def _big(self, uc, address, size, user):
        from unicorn.m68k_const import UC_M68K_REG_A7

        sp = uc.reg_read(UC_M68K_REG_A7)
        n = struct.unpack(">I", bytes(uc.mem_read(sp + 12, 4)))[0]
        self.calls += 1
        if n >= SOUND:
            self.big += 1

    def run(self, fn, *args, limit=20_000_000):
        """-> (result, instructions, ours, memcpy/memset calls, of them >= 1163 B)."""
        self.total = self.ours = self.big = self.calls = 0
        result = self.m.call(fn, *args, limit=limit)
        return result, self.total, self.ours, self.calls, self.big


def stats(rows):
    tot = [r[1] for r in rows]
    ours = [r[2] for r in rows]
    return {"calls": len(rows), "mean": sum(tot) / len(tot), "min": min(tot), "max": max(tot),
            "ours_mean": sum(ours) / len(ours), "ours_max": max(ours),
            "copies_mean": sum(r[3] for r in rows) / len(rows),
            "big_copies": sum(r[4] for r in rows)}


class ArpAdapter:
    """What `emu_arp_modes.hold` needs of a machine."""

    def __init__(self, m):
        self.m = m

    def write(self, va, data):
        self.m.write(va, data)

    def put32(self, va, v):
        self.m.write(va, struct.pack(">I", v & 0xFFFFFFFF))

    def alloc(self, n):
        return self.m.alloc(n)


def measure(args) -> dict:
    from emulib.image import code_chunks
    from emulib.machine import SNAP, Machine

    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    built = stock
    if args.build:
        built = open(os.path.join(args.build, "section_3_MAIN_OS.bin"), "rb").read()
    m = Machine(args.snapshot or SNAP)
    chunks = code_chunks(built) if len(built) > len(stock) else []
    ranges = mod_ranges(stock, built, chunks) if built is not stock else []
    if built is not stock:
        from emulib.image import differences

        m.apply(differences(stock, built))
        for chunk in chunks:
            m.load_code_chunk(chunk)
        m.flush()
    meter = Meter(m, ranges)
    out = {"label": args.label, "build": args.build or "stock",
           "owned_bytes": sum(hi - lo for lo, hi in ranges)}

    # Every write above BSS, and whose code made it. The mods' RAM lives there;
    # nothing of stock's should write it, the save path least of all. The
    # harness's own stack (below STACK) and scratch (above it) are left out.
    above = {"ours": 0, "foreign": 0, "foreign_sites": {}}

    def wrote(pc, address, value, size):
        i = bisect.bisect_right(meter.lo, pc) - 1
        if i >= 0 and pc < meter.hi[i]:
            above["ours"] += 1
            return
        above["foreign"] += 1
        key = f"{pc:#010x} -> {address & ~0xFFF:#010x}"
        above["foreign_sites"][key] = above["foreign_sites"].get(key, 0) + 1

    m.watch_writes(BSS_END, STACK - STACK_DEPTH - 1, wrote)
    out["writes_above_bss"] = above

    # -- evaluator A: one call is one frame's LFO pass over sixteen tracks
    frac = m.alloc(len(SET_FRAC))
    m.write(frac, SET_FRAC)
    m.call(frac)
    span = MIRROR_AT + TRACKS * MIRROR_BYTES + 32
    buf = m.alloc(span)
    m.write(buf, struct.pack(">H", REST) * (span // 2))
    o1, o2 = m.alloc(256), m.alloc(256)
    rate = m.long(RATE)
    rows = [meter.run(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, o1, o2, 0)
            for _ in range(args.warm + args.frames)][args.warm:]
    out["eval_a"] = stats(rows)

    # -- evaluator B, as the priority-8 task calls it at 0x4012b0aa, once per index
    rows = [meter.run(EVAL_B, EVAL_B_STATE, t, 1 << t) for _ in range(2) for t in range(TRACKS)]
    out["eval_b"] = stats(rows[TRACKS:])

    # -- memcpy / memset, a small copy the frame makes and two large ones
    a, b = m.alloc(4096), m.alloc(4096)
    out["memcpy_202"] = stats([meter.run(MEMCPY, a, b, 202) for _ in range(8)])
    out["memcpy_2688"] = stats([meter.run(MEMCPY, a, b, 2688) for _ in range(8)])
    out["memset_1163"] = stats([meter.run(MEMSET, a, 0, 1163) for _ in range(8)])

    # -- the converters, on the sixteen live sounds
    base = m.long(LIVE_CONTAINER)
    if base:
        stored, back = m.alloc(STORED + 16), m.alloc(SOUND + 16)
        saves, loads = [], []
        for t in range(TRACKS):
            live = base + SOUND_AT + SOUND * t
            saves.append(meter.run(SAVE, stored, live, 0))
            m.write(back, m.read(live, SOUND))
            loads.append(meter.run(LOAD, back, stored))
        out["save_sound"], out["load_sound"] = stats(saves), stats(loads)
    else:
        out["save_sound"] = out["load_sound"] = None

    # -- the arp step on UP, four held notes (emu_arp_modes.py's layout)
    import emu_arp_modes as arp

    e = ArpAdapter(m)
    m.write(arp.GEN, struct.pack(">I", 0x1234ABCD) + bytes(arp.RAM_BYTES - 4))   # arpmodes' RAM, as its harness seeds it

    def arp_run(name, mode, rng, notes, steps, arp_id):
        sound = m.alloc(arp.SOUND + 16)
        s = bytearray(arp.SOUND)
        s[arp.MODE], s[arp.RNG], s[arp.LEN] = mode, rng, 15
        s[arp.MASK:arp.MASK + 2] = b"\xff\xff"
        m.write(sound, bytes(s))
        arp.hold(e, sound, notes, arp_id)       # a new id: arpmodes starts a fresh record
        rows = [meter.run(STEP, arp.TRACK, arp_id) for _ in range(steps)]
        out[name] = stats(rows)
        out[name]["notes"] = [r[0] if r[0] < 0x80000000 else r[0] - (1 << 32) for r in rows[:8]]

    # UP is the owner's control and must equal stock. RAND and SHUF are
    # arpmodes' own (stock plays CYCL for both); four notes over RNG 1 is the
    # owner's kind of use, and 128 notes over RNG 7 (1,024 entries, one cycle)
    # is SHUF's worst case -- the bit scan's longest walk.
    arp_run("arp_up", 2, 1, arp.PRESSED, 24, 11)
    arp_run("arp_rand", 6, 1, arp.PRESSED, 24, 12)
    arp_run("arp_shuf", 5, 1, arp.PRESSED, 24, 13)
    arp_run("arp_rand_worst", 6, 7, list(range(128)), 64, 14)
    arp_run("arp_shuf_worst", 5, 7, list(range(128)), 1024, 15)

    # -- the whole project serialiser, as the MRAM job and SAVE PROJECT run it
    out["serialise"] = None
    if args.serialise:
        try:
            obj = m.call(PROJECT_HOLDER)
            project = m.call(m.long(m.long(obj) + 40), obj) if obj else 0
        except Exception as exc:                      # noqa: BLE001 -- recorded, not hidden
            project, out["serialise_error"] = 0, repr(exc)
        out["project"] = hex(project)
        if project:
            prog = m.alloc(16)
            try:
                r = meter.run(SERIALISE, MRAM_IMAGE, project, 0, 0xFFFFFFFF, prog, limit=2_000_000_000)
                out["serialise"] = stats([r])
            except Exception as exc:                  # noqa: BLE001
                out["serialise_error"] = repr(exc)

    # -- last, with an LFO4 in use: a DEST on `--lfo4-tracks` of the live
    # sounds, set through the table's own API as a knob turn does. An idle LFO4
    # and a working one are different costs, and both are the build's. This
    # runs after every idle probe, because it leaves entries in the table.
    if args.lfo4_dest and args.build:
        sym_path = os.path.join(args.build, "symbols.json")
        sym = {k: int(v, 16) for k, v in json.load(open(sym_path)).items()}
        base = m.long(LIVE_CONTAINER)
        for t in range(args.lfo4_tracks):
            live = base + SOUND_AT + SOUND * t
            m.call(sym["ext_set"], live, 3, args.lfo4_dest << 8)     # DEST
            m.call(sym["ext_set"], live, 7, 0x6000)                  # DEP, off centre
        out["lfo4_live"] = m.long(sym["ext_live"])
        rows = [meter.run(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, o1, o2, 0)
                for _ in range(args.warm + args.frames)][args.warm:]
        out["eval_a_lfo4"] = stats(rows)
        rows = [meter.run(EVAL_B, EVAL_B_STATE, t, 1 << t) for _ in range(2) for t in range(TRACKS)]
        out["eval_b_lfo4"] = stats(rows[TRACKS:])
        a, b = m.alloc(4096), m.alloc(4096)
        out["memcpy_202_lfo4"] = stats([meter.run(MEMCPY, a, b, 202) for _ in range(8)])
        out["memcpy_2688_lfo4"] = stats([meter.run(MEMCPY, a, b, 2688) for _ in range(8)])
        if args.serialise and out.get("serialise"):
            prog = m.alloc(16)
            r = meter.run(SERIALISE, MRAM_IMAGE, project, 0, 0xFFFFFFFF, prog, limit=2_000_000_000)
            out["serialise_lfo4"] = stats([r])
    return out


def table(folder: str) -> int:
    rows = {}
    for p in sorted(pathlib.Path(folder).glob("*.cost.json")):
        d = json.loads(p.read_text())
        rows[d["label"]] = d
    if "stock" not in rows:
        raise SystemExit("no stock.cost.json: the control is missing, and nothing compares")
    probes = ["eval_a", "eval_a_lfo4", "eval_b", "eval_b_lfo4", "memcpy_202", "memcpy_202_lfo4",
              "memcpy_2688_lfo4", "memcpy_2688", "memset_1163", "save_sound", "load_sound",
              "arp_up", "arp_rand", "arp_shuf", "arp_rand_worst", "arp_shuf_worst", "serialise",
              "serialise_lfo4"]
    order = ["stock"] + sorted(k for k in rows if k != "stock")
    print(f"{'probe':<13}" + "".join(f"{k:>22}" for k in order))
    for probe in probes:
        s0 = rows["stock"].get(probe)
        line = f"{probe:<13}"
        for k in order:
            d = rows[k].get(probe)
            if not d:
                line += f"{'-':>22}"
                continue
            mean = d["mean"]
            if k == "stock" or not s0:
                line += f"{mean:>22,.0f}"
            else:
                delta = mean - s0["mean"]
                line += f"{mean:>12,.0f} {delta:+8,.0f}".rjust(22)
        print(line)
    print("\nof which inside the build's own code (mean per call):")
    for probe in probes:
        line = f"{probe:<13}"
        for k in order:
            d = rows[k].get(probe)
            line += f"{(d['ours_mean'] if d else 0):>22,.0f}"
        print(line)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", help="a directory holding the build's section_3_MAIN_OS.bin")
    p.add_argument("--label", default="stock")
    p.add_argument("--snapshot")
    p.add_argument("--frames", type=int, default=32)
    p.add_argument("--warm", type=int, default=8)
    p.add_argument("--serialise", action="store_true", help="also run the whole project serialiser")
    p.add_argument("--lfo4-dest", type=int, default=0,
                   help="also measure with LFO4 aimed at this slot (76 is filter base); needs the build's symbols.json")
    p.add_argument("--lfo4-tracks", type=int, default=16, help="how many tracks get that LFO4")
    p.add_argument("--out", default=os.path.join(HERE, "..", "out", "modcost"))
    p.add_argument("--table", metavar="DIR", help="print the comparison of every run in DIR")
    args = p.parse_args()
    if args.table:
        return table(args.table)
    out = measure(args)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{args.label}.cost.json")
    with open(path, "w", newline="\n") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
