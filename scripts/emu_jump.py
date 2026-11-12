"""DIRECT JUMP in the ColdFire emulator (csrc/jump, docs/jump.md): the sequencer playing, a
pattern cued with PTN + TRIG, ticked through stock's own sequencer ISR.

    DT2_SECTIONS=../sec111 DT2_MAIN_IMG=../sec111/section_3_MAIN_OS.bin \\
    DNFW_EMU_FLAGS='{"weakptr": false}' ../digikit/.venv/bin/python -u scripts/emu_jump.py \\
        --build out/jump-build --snapshot ../digikit/out/snapshots/dn2-1.11/ui800M-v014.snap \\
        --scenario on --variant pp [--stock] --json OUT

The sequencer's timer ISR (0x400d987a, vector 121) does not fire by itself here (the timers
are deferred), so the harness enters it as the interrupt would (an exception frame, its rte
returns to a sentinel), four entries a tick at the snapshot's tempo; the UI runs between, as
the panel drives it. Every entry's sequencer state is recorded: the playing pattern, the
change counter, the tick, each track's current and next step, and a digest of the whole
sequencer block (0x42c5a900..0x42c5ab00, 0x446483d0..0x446484c4).

Two patterns are set up in RAM first (`--variant`): pp, A01 16 steps and A02 12, both per
pattern at 1x; pt, A02 per track (master 16; tracks 16, 5, 7, 3, then 16); odd, A01 12 steps
and A02 16, cued at step 18 (A01 has played one and a half loops, on its own step 6), so
Elektron's rule (go on from the playing pattern's step) and the grid since PLAY differ.
`rule_ok`: from the step after the switch, every track is on (its step at the switch + the
steps since) wrapped by its new length. Scenarios:

- `off`: PLAY, cue A02 (PTN + TRIG 2) at global step 3 (odd: 18), on to step 36 (odd: 50). With `--stock` too:
  the two traces must be identical (the build with the setting off is stock).
- `on`: PTN + YES first (the message, the setting, the sector written), then as `off`.
- `ref`: A02 cued while stopped, then PLAY: stock playing A02 from PLAY, the control for
  where the jump must land.
- `pc`: the setting on, A02 cued through the sequencer's cue routine directly (0x400d93f0,
  as program changes, chains and songs cue): stock's timing.
- `persist`: PTN + YES, then a power-on (the setting's RAM back to its boot values; the UI
  reads the sector); PTN + NO, a power-on again.
- `rapid` (v0.40, the owner's "works ~70% of the time, not when rapid-fired"): the setting on,
  four patterns (A01 16 steps, A02 12, A03 7 at 2x, A04 5), cued one after another, each a
  given number of ISR entries after the previous switch (0, 1, 2 ... 47, then 60, 72, 95: every
  phase of the step), then pairs of cues before one switch (the second cue replacing the first,
  0..6 entries apart, and PTN held across both). Every cue must switch to the pattern cued
  last, at the first step boundary after it (the one after that only when no tick of the step
  was left: cued after its last tick, with nothing armed), and the new pattern's first step must be the playing
  pattern's step + 1 wrapped by its length. v0.39 fails it (29 of 83 cues): a cue taken on
  tick 1 was dropped by stock's tick 2 (which clears the arming), so the change waited for the
  pattern's end; a cue after stock had armed its own change (on the last step) started the new
  pattern at 0; a second cue taken by the switch before it was armed started at 0.

Prints one JSON line `emu_jump <scenario>: {...}`; `--json` keeps it with the trace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from emulib.image import differences                    # noqa: E402
from emulib import bounded                                      # noqa: E402
from emulib.machine import Machine                      # noqa: E402
from emulib.panel import NO, YES, Panel                 # noqa: E402

PLAY, PTN = (2, 3), (2, 6)
TRIG = [(3 + k // 8, k % 8) for k in range(16)]         # codes 25..40
SEQ_ISR, SEQ_VECTOR = 0x400D987A, 121
CUE = 0x400D93F0
STACK_TOP, SENTINEL = 0x46A20000, 0x46A20400
P0, PSTRIDE = 0x4121898C, 122478                         # pattern n at P0 + n * PSTRIDE (0x400fa17c)
K0, KSTRIDE = 0x4210C08C, 23921                          # its kit
LEN, MODE, SCALE, TRK, TLEN = 122196, 122201, 122202, 1701, 1164
FAULT_REPORTER = 0x4011EA6A
BLK_READ, BLK_WRITE = 0x4012C59A, 0x4012C780
BLK_READY, BLK_SECTORS = 0x4461B68C, 0x4461B6B0
SET_SECTOR = 0x6FF000
CALLS_A_TICK = 4                                         # ISR entries a tick here (measured)
CUE_STEP, END_STEP = 3, 36


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", required=True, help="a directory with the build's section_3_MAIN_OS.bin")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--scenario", required=True, choices=("off", "on", "ref", "pc", "persist", "rapid"))
    p.add_argument("--variant", default="pp", choices=("pp", "pt", "odd"))
    p.add_argument("--stock", action="store_true", help="install nothing: the control")
    p.add_argument("--png-dir", default=None)
    p.add_argument("--json", default=None)
    a = p.parse_args()

    m = Machine(a.snapshot)
    uc = m.uc
    from unicorn import UC_HOOK_CODE
    from unicorn import m68k_const as K
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    # the snapshot was booted on a build of its own: its edits back to stock first
    snap_img = pathlib.Path(a.snapshot + ".section_3_MAIN_OS.bin")
    if snap_img.exists():
        m.apply([(va, stock[va - 0x40000400:va - 0x40000400 + len(b)])
                 for va, b in differences(stock, snap_img.read_bytes()) if va + len(b) <= 0x40000400 + len(stock)])
    syms = {}
    if not a.stock:
        image = (pathlib.Path(a.build) / "section_3_MAIN_OS.bin").read_bytes()
        m.apply(differences(stock, image))
        if len(image) > len(stock):
            sys.path.insert(0, str(HERE.parent / "src"))
            from dnfw.mods import platform      # noqa: PLC0415
            for va, blob in platform.runtime(image):
                m.write(va, blob)
        sys.path.insert(0, str(HERE.parent / "src"))
        lay = json.loads((HERE.parent / "src/dnfw/mods/waverider_code.json").read_text())["layout"]
        syms = {k: v for k, v in lay.items() if k.startswith("jmp_")}
    m.flush()

    # the +Drive: served here (the emulator's device is 15 MB and reads zeros)
    disk: dict[int, bytes] = {}
    io = {"reads": [], "writes": []}

    def blk(uc_, address, size, user):
        sp = uc.reg_read(K.UC_M68K_REG_A7)
        sector, n, buf = struct.unpack(">3I", bytes(uc.mem_read(sp + 4, 12)))
        if address == BLK_READ:
            io["reads"].append(sector)
            uc.mem_write(buf, b"".join(disk.get(sector + k, bytes(512)) for k in range(n // 512)))
        else:
            io["writes"].append(sector)
            data = bytes(uc.mem_read(buf, n))
            for k in range(n // 512):
                disk[sector + k] = data[512 * k:512 * k + 512]
    for va in (BLK_READ, BLK_WRITE):
        m.write(va, bytes.fromhex("70004e75"))          # moveq #0,%d0 ; rts: the hook does the work
        uc.hook_add(UC_HOOK_CODE, blk, begin=va, end=va)
    m.write(BLK_READY, struct.pack(">I", 1))
    m.write(BLK_SECTORS, struct.pack(">I", 0x3A00000))
    m.flush()

    faults = []
    uc.hook_add(UC_HOOK_CODE, lambda u, ad, sz, us: faults.append(f"{u.reg_read(K.UC_M68K_REG_PC):#x}"),
                begin=FAULT_REPORTER, end=FAULT_REPORTER)
    png = pathlib.Path(a.png_dir or (pathlib.Path(a.build) / "jump-screens"))
    panel = Panel(m, png_dir=str(png))
    panel.settle(20_000_000)

    def u8(va): return m.read(va, 1)[0]
    def u16(va): return m.word(va)
    def u32(va): return m.long(va)
    def sym(name, n=1):
        return int.from_bytes(m.read(syms[name], n), "big") if name in syms else None

    # the patterns
    A01, A02 = P0, P0 + PSTRIDE
    m.write(A01 + LEN, struct.pack(">h", 12 if a.variant == "odd" else 16))
    m.write(A01 + MODE, b"\0")
    cue_step, end_step = (18, 50) if a.variant == "odd" else (CUE_STEP, END_STEP)
    if a.variant == "odd":
        m.write(A02 + LEN, struct.pack(">h", 16))
        m.write(A02 + MODE, b"\0")
        track_len = [16] * 16
        master_len = 16
    elif a.variant == "pp":
        m.write(A02 + LEN, struct.pack(">h", 12))
        m.write(A02 + MODE, b"\0")
        track_len = [12] * 16
        master_len = 12
    else:
        m.write(A02 + LEN, struct.pack(">h", 16))
        m.write(A02 + MODE, b"\1")
        track_len = [16, 5, 7, 3] + [16] * 12
        master_len = 16
        for t, n in enumerate(track_len):
            m.write(A02 + TRK * t + TLEN, struct.pack(">h", n))
            m.write(A02 + TRK * t + TLEN + 3, b"\2")    # +1167: 1x
    for pat in (A01, A02):
        m.write(pat + SCALE, b"\2")                      # 1x

    regs = [getattr(K, f"UC_M68K_REG_{r}{i}") for r in "DA" for i in range(8)]

    def isr():
        saved = [uc.reg_read(r) for r in regs]
        pc = uc.reg_read(K.UC_M68K_REG_PC)
        sp = STACK_TOP - 0x100
        m.write(sp, struct.pack(">HHI", 0x4000 | (SEQ_VECTOR << 2), 0x2000, SENTINEL))
        m.write(SENTINEL, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        try:
            bounded.run(uc, m.m, SEQ_ISR, SENTINEL, 3_000_000)
        finally:
            for r, v in zip(regs, saved):
                uc.reg_write(r, v)
            uc.reg_write(K.UC_M68K_REG_PC, pc)

    def guest(fn, *args):
        saved = [uc.reg_read(r) for r in regs]
        pc = uc.reg_read(K.UC_M68K_REG_PC)
        sp = STACK_TOP - 0x100
        m.write(sp, struct.pack(">I", SENTINEL) + b"".join(struct.pack(">I", x) for x in args))
        m.write(SENTINEL, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        try:
            bounded.run(uc, m.m, fn, SENTINEL, 5_000_000)
        finally:
            for r, v in zip(regs, saved):
                uc.reg_write(r, v)
            uc.reg_write(K.UC_M68K_REG_PC, pc)

    trace = []

    def pat_index():
        return (u32(0x42C5A9A0) - P0) // PSTRIDE

    def record(tag=""):
        block = m.read(0x42C5A900, 0x200) + m.read(0x446483D0, 0xF4)
        row = {"n": len(trace), "tag": tag, "pat": pat_index(), "a91c": u16(0x42C5A91C), "tick": u8(0x42C5A91E),
               "t6": u32(0x42C5A9D0) * 6 + u32(0x42C5A9D4),
               "cur": list(m.read(0x42C5A984, 16)), "next": list(m.read(0x42C5A964, 16)),
               "digest": hashlib.sha256(block).hexdigest()[:16]}
        trace.append(row)
        return row

    def ticks(n, tag=""):
        for k in range(n * CALLS_A_TICK):
            isr()
            if k % 8 == 7:
                panel.settle(200_000)
            record(tag)

    def global_step():
        return u32(0x42C5A9D0)

    out = {"scenario": a.scenario, "variant": a.variant, "stock": a.stock}

    def press_with_ptn(key, name):
        panel.hold(PTN, 3_000_000)
        panel.tap(key, after=3_000_000)
        out[f"png_{name}"] = panel.screen(name)
        panel.let_go(PTN, 3_000_000)

    def cue_a02():
        panel.hold(PTN, 3_000_000)
        panel.tap(TRIG[1], after=2_000_000)
        panel.let_go(PTN, 3_000_000)
        record("cue")

    def sector():
        s = disk.get(SET_SECTOR)
        return None if s is None else s[:16].hex()

    if a.scenario in ("on", "persist", "pc", "rapid"):
        press_with_ptn(YES, "ptn_yes")
        panel.settle(5_000_000)
        out.update(on=sym("jmp_on"), sector_after_yes=sector(), writes_after_yes=list(io["writes"]))

    if a.scenario == "rapid":
        return rapid(a, m, panel, out, record, trace, sym, faults, isr, u8, u32, press_with_ptn)

    if a.scenario == "persist":
        # power-on: the setting's RAM as the loader leaves it (.data: off, unread), the
        # sector as the +Drive holds it; the UI loop reads it
        def boot():
            for name, n in (("jmp_on", 1), ("jmp_loaded", 4), ("jmp_dirty", 1), ("jmp_armed", 1), ("jmp_pending", 1)):
                m.write(syms[name], bytes(n))
            panel.settle(10_000_000)
            return sym("jmp_on")
        out["after_boot_1"] = boot()
        press_with_ptn(NO, "ptn_no")
        panel.settle(5_000_000)
        out.update(on_after_no=sym("jmp_on"), sector_after_no=sector())
        out["after_boot_2"] = boot()
        out["writes"] = [f"{s:#x}" for s in io["writes"]]
        out["reads"] = [f"{s:#x}" for s in io["reads"]]
        out["ok"] = (out["on"] == 1 and out["after_boot_1"] == 1 and out["on_after_no"] == 0
                     and out["after_boot_2"] == 0 and set(io["writes"]) == {SET_SECTOR}
                     and set(io["reads"]) <= {SET_SECTOR} and not faults
                     and (out["sector_after_yes"] or "").startswith("444e325300000001")
                     and (out["sector_after_no"] or "").startswith("444e325300000001"))
        out["faults"] = faults
        print(f"emu_jump {a.scenario}: {json.dumps(out)}", flush=True)
        if a.json:
            pathlib.Path(a.json).write_text(json.dumps(out, indent=1))
        return 0 if out["ok"] else 1

    if a.scenario == "ref":
        cue_a02()                                    # stopped: stock applies it at once
        panel.settle(5_000_000)
    record("start")
    panel.tap(PLAY)
    record("play")
    while global_step() < cue_step:
        ticks(1)
    # half a step in: tick 3 of step CUE_STEP
    ticks(3)
    cue_at = len(trace)
    out["cue_global_step"] = global_step()
    out["cue_tick"] = u8(0x42C5A91E)
    if a.scenario in ("off", "on"):
        cue_a02()
    elif a.scenario == "pc":
        entry = struct.pack(">IIhhh2xib3x", A02, K0 + KSTRIDE, -1, -1, 0, -1, -1)   # as 0x400fa11e builds it
        buf = STACK_TOP + 0x2000
        m.write(buf, entry[:24])
        guest(CUE, buf, 1)
        record("cue")
    while global_step() < end_step:
        ticks(1)

    # where the pattern changed, and what each track played on the first steps after it
    sw = next((r for r in trace[cue_at:] if r["pat"] == 1), None)
    out["switch_row"] = sw["n"] if sw else None
    out["switch_global"] = sw["t6"] // 6 if sw else None
    out["switch_after_cue_ticks"] = (sum(1 for r in trace[cue_at:sw["n"]]) // CALLS_A_TICK) if sw else None
    # each global step's boundary: the row where t6 is a multiple of 6 and tick 0
    steps = {}
    for r in trace:
        if r["tick"] == 0 and r["t6"] % 6 == 0:
            steps.setdefault(r["t6"] // 6, (r["pat"], r["cur"]))
    out["steps"] = {str(g): {"pat": v[0], "cur": v[1]} for g, v in sorted(steps.items())}
    # Elektron's rule, from this run's own trace: after the switch at step sw, track t is on
    # (its step at sw + the steps since) wrapped by its length in the new pattern
    sw_g = out["switch_global"]
    if sw_g is not None and sw_g in steps:
        at = steps[sw_g][1]
        later = [g for g in sorted(steps) if g > sw_g]
        # the master (the pattern's length; per track, its master length, 16 here) restarts
        # every track when it wraps, as stock does: from the switch it goes on from
        # jmp_last, the start step jmp_position() gave it
        start = sym("jmp_last", 4) or 0
        resets = [g for g in later if (start + g - sw_g - 1) % master_len == 0]

        def want(g, t):
            r = [g0 for g0 in resets if g0 <= g]
            return (g - r[-1]) % track_len[t] if r else (at[t] + g - sw_g) % track_len[t]
        bad = [g for g in later for t in range(16) if steps[g][1][t] != want(g, t) or steps[g][0] != 1]
        out["rule_ok"] = not bad and len(later) >= 20
        out["rule_bad"] = bad[:4]
        out["first_new"] = {"step": sw_g + 1, "cur": steps.get(sw_g + 1, (0, []))[1][:4],
                            "was": at[:4]}
    out["jmp"] = {k: sym(k, 4) for k in ("jmp_count", "jmp_last")} if syms else None
    out["faults"] = faults
    out["trace_digest"] = hashlib.sha256(json.dumps([(r["pat"], r["a91c"], r["tick"], r["t6"], r["cur"], r["next"],
                                                      r["digest"]) for r in trace]).encode()).hexdigest()
    out["track_len"] = track_len[:4]
    print(f"emu_jump {a.scenario}: {json.dumps(out)}", flush=True)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps({**out, "trace": trace}, indent=1))
    return 0 if not faults else 1


def rapid(a, m, panel, out, record, trace, sym, faults, isr, u8, u32, press_with_ptn) -> int:
    """the rapid-fire sweep (the module's docstring, `rapid`)"""
    pats = [P0 + n * PSTRIDE for n in range(4)]
    lens = [16, 12, 7, 5]
    scales = [2, 2, 0, 2]                                 # A03 at 2x (3 ticks a step)
    for pat, n, sc in zip(pats, lens, scales):
        m.write(pat + LEN, struct.pack(">h", n))
        m.write(pat + MODE, b"\0")
        m.write(pat + SCALE, bytes([sc]))

    def pat_index():
        v = u32(0x42C5A9A0)
        return (v - P0) // PSTRIDE if v >= P0 else -1
    count = [0]

    def entry():
        isr()
        count[0] += 1
        if count[0] % 8 == 0:
            panel.settle(200_000)
        return record()

    def cue(keys):
        panel.hold(PTN, 3_000_000)
        for k in keys:
            panel.tap(TRIG[k], after=2_000_000)
        panel.let_go(PTN, 3_000_000)
        return record("cue")

    record("start")
    panel.tap(PLAY)
    record("play")
    for _ in range(3 * 24):                              # on into A01's step 3
        entry()
    plan = [(off, None) for off in [*range(48), 60, 72, 95]]
    plan += [(off, gap) for off in (3, 9, 13, 20) for gap in range(7)]
    plan += [(off, "held") for off in (2, 7, 11, 23)]
    results, playing = [], pat_index()
    for i, (off, gap) in enumerate(plan):
        for _ in range(off):
            entry()
        playing = pat_index()
        others = [n for n in range(4) if n != playing]
        first = others[i % 3]
        target = first
        if gap == "held":
            target = others[(i + 1) % 3]
            c = cue([first, target])
        else:
            c = cue([first])
            if gap is not None:
                for _ in range(gap):
                    entry()
                target = next(n for n in others if n != first and n != pat_index())
                if pat_index() == first:                     # switched already: cue from there
                    target = next(n for n in range(4) if n != first)
                c = cue([target])
        cue_n = len(trace) - 1
        jumps0 = sym("jmp_count", 4) or 0
        # the step boundaries after the cue: a row whose tick is 0 after a row whose tick is not
        sw = b1 = b2 = None
        ticked = False
        for _ in range(16 * 24 * 2):
            prev = trace[-1]
            r = entry()
            if r["tick"] == 0 and prev["tick"] != 0:
                if b1 is None:
                    b1 = r["n"]
                elif b2 is None:
                    b2 = r["n"]
            elif r["tick"] != prev["tick"] and b1 is None:
                ticked = True                    # a tick of the cue's step after the cue
            if r["pat"] != prev["pat"]:
                sw = r
                break
        if sw is None:
            results.append({"i": i, "off": off, "gap": gap, "ok": False, "why": "no switch"})
            continue
        # the first boundary; the one after only when no tick of the cue's step was left
        # (and nothing was armed before the cue: then the first is right too)
        row_ok = sw["n"] == b1 or (not ticked and sw["n"] == b2)
        prev_cur = trace[sw["n"] - 1]["cur"][0] if sw["n"] > 0 else None
        at = sw["cur"][0]                           # the old pattern's step, still played here
        # the new pattern's first step: at the next boundary
        nxt = None
        for _ in range(3 * 24):
            prev = trace[-1]
            r = entry()
            if r["tick"] == 0 and prev["tick"] != 0:
                nxt = r
                break
        first_new = nxt["cur"][0] if nxt else None
        want_first = (at + 1) % lens[target]
        ok = (sw["pat"] == target and row_ok and first_new == want_first
              and nxt is not None and nxt["pat"] == target)
        res = {"i": i, "off": off, "gap": gap, "from": playing, "to": target, "got": sw["pat"],
               "cue_tick": c["tick"], "ticked": ticked, "switch_row_after_cue": sw["n"] - cue_n,
               "at_boundary": "b1" if sw["n"] == b1 else "b2" if sw["n"] == b2 else "late",
               "want": "b1" if ticked else "b2", "at": at, "first_new": first_new,
               "want_first": want_first, "ok": ok}
        results.append(res)
        # the next cue's offset counts from here: the boundary after the switch
    bad = [r for r in results if not r["ok"]]
    out.update(cues=len(results), bad=bad[:12], n_bad=len(bad), jumps=sym("jmp_count", 4),
               results=results, faults=faults)
    out["ok"] = not bad and not faults and len(results) == len(plan)
    print(f"emu_jump rapid: {json.dumps({k: v for k, v in out.items() if k != 'results'})}", flush=True)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps({**out, "trace": trace}, indent=1))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
