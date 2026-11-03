"""Parameter slides under digikit's ColdFire emulator (docs/slides.md): the gate's check.

    DT2_SECTIONS=../sec111 DT2_MAIN_IMG=../sec111/section_3_MAIN_OS.bin \\
    DNFW_EMU_FLAGS='{"weakptr": false}' ../digikit/.venv/bin/python -u scripts/emu_slides.py \\
        --build out/bsl --snapshot ../digikit/out/snapshots/dn2-1.11/ui800M-v014.snap \\
        --json out/slides-build.json [--stock]

The sequencer does not play under the emulator (docs/emulator.md; scripts/emu_arp_plocks.py),
so a trig is what the frame ISR does for one: the routines its note block runs for a voice
are called in its order (the voice's sound into the mirror, the locks' undo, the lock-list
builder, the applier), with the build's hooks where the build has them; every frame after
it is the REAL frame ISR (0x40025e36, run to its rte), whose smoother call the build hooks.
Read each frame: the smoother's state (unmodulated) and output for voice 0.

`--stock` installs nothing (stock 1.11, the control) and skips what only the build has; the
gate compares its per-frame arrays with the build's run of the same pattern with SLIDE off:
they must be equal byte for byte. The build's run alone checks the slide (exact values per
frame against the model below), the lock table's SAVE/LOAD, the step clear, a knob turned,
a tempo change, a trigless lock, a trig with SLIDE and no p-lock, a new sound mid-slide.
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

from emulib.image import differences                           # noqa: E402
from emulib.machine import Machine                             # noqa: E402

ISR, ISR_RTE = 0x40025E36, 0x40027BC6
STATE, SRC, OUT = 0x8000DE60, 0x80003AF0, 0x800068E4
OWNER, VSOUND, FRAMES = 0x80005308, 0x800052A8, 0x4058E8D4
TEMPO_AT = 0x80005E60 + 216
KIT, SOUND_STRIDE = 0x800052A0, 1163
SYNC = 0x4002549C                       # (sound, voice): the sound into the voice's mirror block
UNDO = 0x400DAF44                       # (voice, mirror, sound): the locked slots back to the sound
BITMAP_CLEAR = 0x400DB052               # (voice)
BUILD, APPLY = 0x400D85E8, 0x400DB092
LOAD, SAVE, CLEAR = 0x400DE51E, 0x400DE718, 0x4003D14E
REC, RECS, INDEX, COUNTS, TABLE_BYTES = 258, 80, 20640, 22256, 22256 + 2048
LIST_BYTES = 20 + 202 * 8
FREQ, FDBK = 67, 31                     # FILTER FREQ (shared), FM TONE's FEEDBACK (a machine param)
UNITS = (3, 6, 12, 18, 24, 36, 48, 72, 96, 144, 192, 288, 384, 768, 1536)
STACK_TOP, SENTINEL = 0x46A20000, 0x46A20400

failures: list[str] = []
report: dict = {"checks": {}}


def check(name, ok, detail=""):
    report["checks"][name] = {"ok": bool(ok), "detail": detail}
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


def idx(v, s):
    return 17 + 101 * v + s


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--json", default=None)
    p.add_argument("--stock", action="store_true", help="install nothing: the control")
    p.add_argument("--png-dir", default=None, help="the TRIG page's screens (the build's run: the UI part)")
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    a = p.parse_args()

    machine = Machine(a.snapshot)
    uc = machine.uc
    from unicorn import UC_HOOK_CODE
    from unicorn import m68k_const as K
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    snap_image = pathlib.Path(a.snapshot + ".section_3_MAIN_OS.bin")
    if snap_image.exists():
        back = [(va, stock[va - 0x40000400:va - 0x40000400 + len(b)]) for va, b in
                differences(stock, snap_image.read_bytes()) if va + len(b) <= 0x40000400 + len(stock)]
        machine.apply(back)
    lay = {}
    if not a.stock:
        image = (pathlib.Path(a.build) / "section_3_MAIN_OS.bin").read_bytes()
        runs = differences(stock, image)
        machine.apply(runs)
        sys.path.insert(0, str(HERE.parent / "src"))
        from dnfw.mods import platform                         # noqa: PLC0415
        for va, blob in platform.runtime(image):
            machine.write(va, blob)
        # v0.39 (the merge with v0.38): the sample link's RAM window (SMP_MIRROR, 5 MB above
        # BSS, docs/memory-map.md) is DDR on the unit; the snapshot maps only the pages stock
        # touched, and since v0.38 the mod's power-on writes there (link.c's per-slot sums at
        # SMP_MIRROR + 0x22C000) while this check runs the UI. Mapped here as the unit has it
        from unicorn import UC_PROT_ALL, UcError
        from dnfw.sampler import machines as SMx              # noqa: PLC0415
        for page in range(SMx.MIRROR, SMx.MIRROR + 0x500000, 0x100000):
            try:
                uc.mem_map(page, 0x100000, UC_PROT_ALL)
            except UcError:
                pass                                          # (already mapped)
        machine.flush()
        lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
        print(f"  installed {len(runs)} run(s) from {a.build}")
    else:
        print("  stock: nothing installed (the control)")
    build = not a.stock

    regs = [getattr(K, f"UC_M68K_REG_{r}{i}") for r in "DA" for i in range(8)]

    def call(fn, *args, until=None, set_regs=None, limit=20_000_000):
        saved = [uc.reg_read(r) for r in regs]
        sp = STACK_TOP - 0x200
        machine.write(sp, struct.pack(">I", SENTINEL) + b"".join(struct.pack(">I", x & 0xFFFFFFFF) for x in args))
        machine.write(SENTINEL, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        for r, v in (set_regs or {}).items():
            uc.reg_write(getattr(K, f"UC_M68K_REG_{r}"), v & 0xFFFFFFFF)
        stepper = getattr(machine.m, "_fast_stepper_obj", None)
        if stepper is not None:
            stepper.left = 1 << 40
        try:
            uc.emu_start(fn, until if until is not None else SENTINEL, count=limit)
        finally:
            if stepper is not None:
                stepper.left = 0
        out = {r: uc.reg_read(getattr(K, f"UC_M68K_REG_{r}")) for r in
               ("D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "A0", "A1", "A2", "A3", "A4", "A5", "A6")}
        pc = uc.reg_read(K.UC_M68K_REG_PC)
        for r, v in zip(regs, saved):
            uc.reg_write(r, v)
        out["PC"] = pc
        return out

    def u16(va):
        return machine.word(va)

    def put16(va, v):
        machine.write(va, struct.pack(">H", v & 0xFFFF))

    def put32(va, v):
        machine.write(va, struct.pack(">I", v & 0xFFFFFFFF))

    faults_before = len(getattr(machine.m, "faults", []))

    # ---- the voice: track 0's sound on voice 0 --------------------------------------------
    V, T = 0, 0
    kit = machine.long(KIT)
    snd = kit + 52 + SOUND_STRIDE * T
    mtype = struct.unpack(">b", machine.read(snd + 222, 1))[0]
    report["machine_type"] = mtype
    if mtype != 0:                      # FM TONE, so FDBK is a machine parameter that slides
        machine.write(snd + 222, b"\x00")
    report["tempo_word"] = machine.word(TEMPO_AT)
    if not 1200 <= machine.word(TEMPO_AT) <= 60000:
        put16(TEMPO_AT, 120 * 120)
    put32(OWNER + 4 * V, T)
    call(SYNC, snd, V)
    for s in range(101):                # the smoother at rest on the sound's values
        put32(STATE + 4 * idx(V, s), u16(SRC + 2 * idx(V, s)) << 16)
    call(BITMAP_CLEAR, V)

    # ---- the pattern: FREQ and FDBK locked on steps 0, 4 and 8 ----------------------------
    machine.at = 0x46A30000
    table = machine.alloc(TABLE_BYTES)
    machine.write(table, b"\xff" * (REC * RECS))
    machine.write(table + INDEX, b"\xff" * (16 * 101))

    def stock_lock(rec, slot, step, value):
        at = table + rec * REC
        if machine.read(at, 2) == b"\xff\xff":
            machine.write(at, bytes([slot, T]) + b"\xff\xff" * 128)
            machine.write(table + INDEX + 101 * T + slot, bytes([rec]))
        put16(at + 2 + 2 * step, value)

    LOCKS = {0: {FREQ: 0x1000, FDBK: 0x0800}, 4: {FREQ: 0x6000, FDBK: 0x7000}, 8: {FREQ: 0x3000}}
    for step, row in LOCKS.items():
        for slot, v in row.items():
            stock_lock(0 if slot == FREQ else 1, slot, step, v)
    for step in LOCKS:                  # the step's "has a lock" byte the builder's caller tests
        pass

    sl_set = lay.get("sl_lock_set")
    sl_get = lay.get("sl_lock_get")

    def set_slide(step, sld, slen=None):
        if not build:
            return
        call(sl_set, table, T, step, 0, sld)
        if slen is not None:
            call(sl_set, table, T, step, 1, slen)

    lists = []

    def trig(step, frames_now, trigless=False, new_sound=None):
        """what the note block does for a voice (trigless: the applier alone, as the trigless loop)"""
        put32(FRAMES, frames_now)
        lst = machine.alloc(LIST_BYTES)
        machine.write(lst, b"\x5a" * LIST_BYTES)       # a recycled list: garbage everywhere
        lists.append(lst)
        if not trigless:
            if build:
                call(lay["sl_pre"], V, T)
            if new_sound is not None:
                call(SYNC, new_sound, V)
                call(BITMAP_CLEAR, V)
            else:
                call(UNDO, V, SRC, snd)
        call(BUILD, T, lst, table, snd + 48, step, step, 0)
        call(APPLY, V, lst, SRC)
        return lst

    def frame():
        """the real frame ISR, to its rte"""
        r = call(ISR, until=ISR_RTE, limit=50_000_000)
        return r["PC"] == ISR_RTE

    def voice_words(base, n=101, stride=2):
        return [machine.word(base + stride * idx(V, s)) for s in range(n)] if stride == 2 else \
               [machine.long(base + 4 * idx(V, s)) for s in range(n)]

    trace = []

    def run(frames, tag, read=(FREQ, FDBK)):
        rows = []
        for _ in range(frames):
            ok = frame()
            st = {s: machine.long(STATE + 4 * idx(V, s)) for s in read}
            out = {s: machine.word(OUT + 2 * idx(V, s)) for s in read}
            whole = machine.read(STATE, 4 * 1734) + machine.read(OUT, 2 * 1734)
            rows.append({"ok": ok, "state": st, "out": out,
                         "sha": hashlib.sha256(whole).hexdigest()[:16]})
        trace.append((tag, rows))
        return rows

    # The stock smoother 0x400db12a as the instrument computes it. Its one-pole filter is in
    # the EMAC's fractional mode (the ISR sets MACSR = 0x20), and digikit's EMAC halves every
    # fractional product (measured: 0.5 x 0.5 gives 0x10000000, not 0x20000000), so under the
    # emulator the state decays to about half a frame. With `model` on, the routine's entry runs
    # this instead: state' = (0x7c29 state + 0x3d7 (src << 16)) >> 15, out = (state' + 0x8000)
    # >> 16, then its block copy and the LFO DEST copies, as its code does.
    model = {"on": False, "calls": 0}

    def smoother(uc_, address, size, user):
        if not model["on"]:
            return
        model["calls"] += 1
        src = struct.unpack(">1734H", machine.read(SRC, 2 * 1734))
        st = list(struct.unpack(">1734i", machine.read(STATE, 4 * 1734)))
        out = []
        for i in range(1734):
            v = (0x7C29 * st[i] + 0x3D7 * (src[i] << 16)) >> 15
            v = max(-0x80000000, min(0x7FFFFFFF, v))
            st[i] = v
            out.append(((v + 0x8000) >> 16) & 0xFFFF)
        machine.write(STATE, struct.pack(">1734i", *st))
        for t in range(16):
            for off in (42, 58, 74):
                out[(off + 202 * t) // 2] = src[(off + 202 * t) // 2]
        machine.write(OUT, struct.pack(">1734H", *out))
        machine.write(0x80007670, machine.read(SRC + 3468, 0x990))
        sp = uc_.reg_read(K.UC_M68K_REG_A7)
        ret = machine.long(sp)
        uc_.reg_write(K.UC_M68K_REG_A7, sp + 4)
        uc_.reg_write(K.UC_M68K_REG_D0, OUT)
        uc_.reg_write(K.UC_M68K_REG_PC, ret)
    uc.hook_add(UC_HOOK_CODE, smoother, begin=0x400DB12A, end=0x400DB12A)

    f0 = machine.long(FRAMES)
    isr_frames = machine.long(FRAMES)
    ok = frame()
    isr_counts = machine.long(FRAMES) != isr_frames
    report["isr_counts_frames"] = isr_counts
    check("the frame ISR runs to its rte", ok)

    # ---- 1. OFF: SLIDE locked OFF on step 4 (build), nothing (stock); first with the emulated
    # smoother as it is, then with the model: the gate compares both with stock's -----------
    set_slide(4, 0)
    trig(0, f0 + 10)
    off_a = run(30, "off trig 0 (emulated EMAC)")
    trig(4, f0 + 100)
    off_b = run(40, "off trig 4 (emulated EMAC)")
    report["off_shas_emac"] = [r["sha"] for r in off_a + off_b]
    model["on"] = True
    for s_ in range(101):
        put32(STATE + 4 * idx(V, s_), u16(SRC + 2 * idx(V, s_)) << 16)
    trig(0, f0 + 150)
    off_a = run(30, "off trig 0")
    trig(4, f0 + 250)
    off_b = run(40, "off trig 4")
    report["off_shas"] = [r["sha"] for r in off_a + off_b]
    report["off_freq"] = [r["out"][FREQ] for r in off_a + off_b]
    # stock: the lock jumps the smoother; FREQ is 0x6000 from the first frame after the trig
    check("OFF: the lock jumps (as stock)", off_b[0]["out"][FREQ] == 0x6000 and off_a[-1]["out"][FREQ] == 0x1000,
          f"before {off_a[-1]['out'][FREQ]:#x}, after {off_b[0]['out'][FREQ]:#x}")
    w = machine.word(TEMPO_AT)
    report["tempo_word_after_isr"] = w
    if not 1200 <= w <= 60000:
        w = 120 * 120

    if build:
        # ---- 2. ON: SLIDE on step 4, SLEN 1 step (index 4) ----------------------------------
        trig(0, f0 + 200)
        run(10, "on trig 0")
        start = machine.long(lay["sl_started"])
        set_slide(4, 1, 4)
        check("SLD/SLEN locks read back", call(sl_get, table, T, 4, 0)["D0"] == 1
              and call(sl_get, table, T, 4, 1)["D0"] == 4)
        inc = ((w << 16) & 0xFFFFFFFF) // 112500
        mul = (6 << 8) // 6
        units = UNITS[4]

        def ramp(frm, to, n):
            prog, vals = 0, []
            for _ in range(n):
                prog += (inc * mul) >> 8
                frac = min(prog // (2 * units), 32768)
                d = to - frm
                vals.append(frm + ((d * frac) >> 15))
            return vals
        expect_frames = next(i + 1 for i, v in enumerate(ramp(0, 1, 100000)) if v == 1)
        report["expected_ramp_frames"] = expect_frames
        report["ms_at_tempo"] = round(expect_frames / 1.5, 2)
        trig(4, f0 + 300)
        check("a slide began", machine.long(lay["sl_started"]) == start + 1)
        rows = run(expect_frames + 20, "on trig 4")
        for slot, frm, to in ((FREQ, 0x1000, 0x6000), (FDBK, 0x0800, 0x7000)):
            want = ramp(frm, to, expect_frames + 20)
            got = [r["state"][slot] >> 16 for r in rows]
            gout = [r["out"][slot] for r in rows]
            exact = got == want and all(r["state"][slot] & 0xFFFF == 0 for r in rows)
            check(f"ON: slot {slot} ramps {frm:#x} -> {to:#x} over {expect_frames} frames, exact per frame",
                  exact, "" if exact else f"first diff at {next(i for i, (x, y) in enumerate(zip(got, want)) if x != y)}: "
                  f"{got[:6]} vs {want[:6]}")
            check(f"ON: slot {slot} output lands on the target and stays", gout[expect_frames - 1:] ==
                  [to] * (len(gout) - expect_frames + 1), f"out tail {gout[expect_frames - 3:expect_frames + 3]}")
            mono = all(b >= c for b, c in zip(gout[1:], gout)) if to > frm else all(b <= c for b, c in zip(gout[1:], gout))
            check(f"ON: slot {slot} output never steps back", mono)
            report[f"ramp_{slot}"] = gout[:expect_frames + 2]

        # ---- 3. a knob turned mid-slide: that slot leaves, the other slides on -------------
        trig(0, f0 + 600)
        run(10, "knob trig 0")
        trig(4, f0 + 700)
        r1 = run(40, "knob first 40")
        put16(SRC + 2 * idx(V, FREQ), 0x2000)            # the knob: FREQ's source moves
        r2 = run(expect_frames, "knob after")
        last = r1[-1]["out"][FREQ]
        jump = abs(r2[0]["out"][FREQ] - last)
        check("knob mid-slide: FREQ leaves the slide and the smoother glides on (no jump)",
              jump < 0x400 and r2[-1]["state"][FREQ] >> 16 in range(0x1F00, 0x2101),
              f"last slide {last:#x}, next {r2[0]['out'][FREQ]:#x}, end {r2[-1]['out'][FREQ]:#x}")
        fd = ramp(0x0800, 0x7000, 40 + expect_frames)
        check("knob mid-slide: FDBK slides on unchanged", [r["state"][FDBK] >> 16 for r in r1 + r2] == fd)

        # ---- 4. a tempo change mid-slide: the remaining frames follow it -------------------
        call(SYNC, snd, V)
        for s in range(101):
            put32(STATE + 4 * idx(V, s), u16(SRC + 2 * idx(V, s)) << 16)
        call(BITMAP_CLEAR, V)
        trig(0, f0 + 1000)
        run(10, "tempo trig 0")
        trig(4, f0 + 1100)
        ra = run(30, "tempo before")
        tempo_hook = uc.hook_add(UC_HOOK_CODE, lambda uc_, ad, sz, us: put16(TEMPO_AT, w * 2),
                                 begin=lay["sl_smooth"], end=lay["sl_smooth"])
        rb = run(expect_frames, "tempo doubled")
        uc.hook_del(tempo_hook)
        prog, vals = 0, []
        for i in range(30 + expect_frames):
            ww = w if i < 30 else w * 2
            prog += ((((ww << 16) & 0xFFFFFFFF) // 112500) * mul) >> 8
            frac = min(prog // (2 * units), 32768)
            vals.append(0x1000 + (((0x6000 - 0x1000) * frac) >> 15))
        got = [r["state"][FREQ] >> 16 for r in ra + rb]
        landed = next((i + 1 for i, v in enumerate(got) if v == 0x6000), None)
        check("tempo doubled mid-slide: exact per frame, lands sooner", got == vals,
              f"landed at frame {landed} (unchanged tempo: {expect_frames})")
        report["tempo_landed"] = landed

        # ---- 5. a trigless lock trig with SLIDE: from where the voice is ------------------
        set_slide(8, 1, 2)               # SLEN 1/2 step
        trig(8, f0 + 1500, trigless=True)
        rt = run(120, "trigless")
        u2 = UNITS[2]
        prog, want = 0, []
        for _ in range(120):
            prog += (inc * mul) >> 8
            frac = min(prog // (2 * u2), 32768)
            want.append(0x6000 + (((0x3000 - 0x6000) * frac) >> 15))
        got = [r["state"][FREQ] >> 16 for r in rt]
        check("trigless lock with SLIDE: FREQ 0x6000 -> 0x3000 over 1/2 step", got == want,
              f"{got[:4]}...{got[-2:]}")

        # ---- 6. SLIDE on a trig with no p-lock: nothing slides ----------------------------
        start = machine.long(lay["sl_started"])
        set_slide(12, 1, 4)
        snap = machine.read(STATE, 4 * 1734)
        trig(12, f0 + 1700)
        check("SLIDE on a trig with no p-lock: no slide", machine.long(lay["sl_started"]) == start)

        # ---- 7. a new sound mid-slide (a pattern change): every slot leaves ---------------
        trig(0, f0 + 1900)
        run(10, "newsound trig 0")
        trig(4, f0 + 2000)
        run(20, "newsound slide")
        other = kit + 52 + SOUND_STRIDE * 1
        call(SYNC, other, V)
        run(3, "newsound after")
        n = struct.unpack(">H", machine.read(lay["sl_v"], 2))[0]
        check("a new sound on the voice mid-slide: the slide ends", n == 0, f"n {n}")

        # ---- 8. retrig: the same list applied again later re-slides from where it is -------
        call(SYNC, snd, V)
        lst = trig(0, f0 + 2200)
        run(10, "retrig 0")
        lst4 = trig(4, f0 + 2300)
        run(20, "retrig slide")
        mid = machine.long(STATE + 4 * idx(V, FREQ)) >> 16
        put32(FRAMES, f0 + 2400)
        call(lay["sl_pre"], V, T)
        call(UNDO, V, SRC, snd)
        call(APPLY, V, lst4, SRC)
        after = machine.long(STATE + 4 * idx(V, FREQ)) >> 16
        rr = run(expect_frames + 5, "retrig on")
        check("retrig mid-slide: slides on from where it was to the target", after == mid
              and rr[-1]["state"][FREQ] >> 16 == 0x6000, f"mid {mid:#x}, after {after:#x}")

        # ---- 9. the lock table's SAVE and LOAD; the step clear ------------------------------
        stored = machine.alloc(REC * RECS)
        call(SAVE, stored, table)
        heads = [machine.read(stored + REC * i, 2) for i in range(RECS)]
        ours = [h for h in heads if h[0] in (200, 201)]
        check("SAVE: SLD/SLEN stored as ids 200/201 with a plain track", sorted(ours) ==
              [bytes([200, 0]), bytes([201, 0])], f"{[h.hex() for h in ours]}")
        t2 = machine.alloc(TABLE_BYTES)
        call(LOAD, t2, stored)
        same = all(machine.read(t2 + REC * i, REC) == machine.read(table + REC * i, REC) for i in range(RECS))
        check("LOAD: every record back, ours included, byte for byte", same)
        check("LOAD: the SLIDE locks read back", [call(sl_get, t2, T, s, 0)["D0"] for s in (4, 8, 12)] == [1, 1, 1])
        report["stored_records_sha"] = hashlib.sha256(machine.read(stored, REC * RECS)).hexdigest()

        code = machine.alloc(16)
        machine.write(code, bytes.fromhex("203c") + struct.pack(">I", t2) + bytes.fromhex("4e75") + bytes.fromhex("4e75"))
        vt = machine.alloc(64)
        for k in range(16):
            put32(vt + 4 * k, code + 6)                  # every slot: rts
        put32(vt + 40, code)                             # +40: the lock table
        model_obj = machine.alloc(16)
        put32(model_obj, vt)
        rc = call(CLEAR, model_obj, T, 4)
        got = [call(sl_get, t2, T, 4, 0)["D0"], call(sl_get, t2, T, 4, 1)["D0"], call(sl_get, t2, T, 8, 0)["D0"]]
        stock_gone = machine.word(t2 + 2 + 2 * 4) == 0xFFFF and machine.word(t2 + REC + 2 + 2 * 4) == 0xFFFF
        check("step clear: step 4's SLIDE and SLEN gone (and its stock locks), step 8's kept",
              got == [0xFFFF, 0xFFFF, 1] and stock_gone, f"{[hex(x) for x in got]}, stock gone {stock_gone}, pc {rc['PC']:#x}")

        # ---- 10. the note block's hook itself (0x40026bac): registers and flags -----------
        rec = machine.alloc(128)
        put32(rec + 64, 0x12345678)
        r = call(lay["sl_pre_hook"] if "sl_pre_hook" in lay else 0, set_regs={"D2": 3, "D3": 5, "A0": rec,
                 "D4": 0x44, "D5": 0x55, "A2": 0xA2, "A3": 0xA3, "A5": 0xA5})
        check("the note-block hook replays its two instructions and keeps every register",
              r["D0"] == 0x12345678 and r["A4"] == 3 and r["D2"] == 3 and r["D3"] == 5 and r["A0"] == rec
              and r["D4"] == 0x44 and r["A2"] == 0xA2 and r["A5"] == 0xA5)

    # ---- the stored form of a stock pattern loads the same here as on stock ----------------
    plain = machine.alloc(TABLE_BYTES)
    machine.write(plain, b"\xff" * (REC * RECS))
    machine.write(plain + INDEX, b"\xff" * (16 * 101))
    for i, (slot, step, v) in enumerate(((67, 0, 0x1000), (31, 4, 0x7000), (90, 9, 0x2000))):
        machine.write(plain + REC * i, bytes([slot, i]) + b"\xff\xff" * 128)
        put16(plain + REC * i + 2 + 2 * step, v)
        machine.write(plain + INDEX + 101 * i + slot, bytes([i]))
    st_plain = machine.alloc(REC * RECS)
    call(SAVE, st_plain, plain)
    back = machine.alloc(TABLE_BYTES)
    call(LOAD, back, st_plain)
    report["plain_stored_sha"] = hashlib.sha256(machine.read(st_plain, REC * RECS)).hexdigest()
    report["plain_loaded_sha"] = hashlib.sha256(machine.read(back, TABLE_BYTES)).hexdigest()
    # and a stored table carrying ids 200/201 (made here, so the stock run sees one too)
    with_ours = machine.alloc(REC * RECS)
    machine.write(with_ours, machine.read(st_plain, REC * RECS))
    machine.write(with_ours + REC * 5, bytes([200, 0]) + b"\xff\xff" * 128)
    put16(with_ours + REC * 5 + 2 + 2 * 4, 1)
    back2 = machine.alloc(TABLE_BYTES)
    call(LOAD, back2, with_ours)
    rec5 = machine.read(back2 + REC * 5, 2)
    report["ours_loaded_rec5"] = rec5.hex()
    rest = machine.read(back2, TABLE_BYTES)
    rest = rest[:REC * 5] + rest[REC * 6:]
    report["ours_loaded_rest_sha"] = hashlib.sha256(rest).hexdigest()
    if build:
        check("a stored SLIDE record loads into RAM as ours", rec5 == bytes([0x50, 0x20]))
    else:
        report["stock_skips_ours"] = rec5 == b"\xff\xff"

    # ---- the TRIG page, driven as a person would (the build only, last: it changes the UI) ---
    if build and a.png_dir:
        from emulib.panel import Panel                         # noqa: PLC0415
        model["on"] = False
        panel = Panel(machine, png_dir=a.png_dir)

        def key(code):
            return ((code - 1) // 8, (code - 1) % 8)

        def turn(enc, delta):
            machine.pc = panel.panelin.encoder(machine.m, panel.profile, enc, delta)
            panel.settle(5_000_000)

        up = lambda: machine.long(lay["sl_page_up"])           # noqa: E731
        clears = {"n": 0}

        def cleared(uc_, ad, sz, us):
            clears["n"] += 1
        uc.hook_add(UC_HOOK_CODE, cleared, begin=CLEAR, end=CLEAR)

        def lock(tbl, t, step, k):                              # read as sl_lock_get reads it
            head = 0x51 if k else 0x50
            for i in range(RECS):
                h = machine.read(tbl + REC * i, 2)
                if h == bytes([head, 0x20 | t]):
                    return machine.word(tbl + REC * i + 2 + 2 * step)
            return 0xFFFF
        panel.settle(5_000_000)
        panel.tap(key(1))
        panel.settle(20_000_000)
        page1 = up()
        panel.tap(key(1))
        panel.settle(20_000_000)
        page2 = up()
        panel.screen("trig2_idle")
        check("TRIG page 2 draws SLD and SLEN (page 1 does not)", page2 == 1 and page1 == 0,
              f"page 1 up {page1}, page 2 up {page2}, drawn {machine.long(lay['sl_page_seen'])} times")
        panel.tap(key(19))                                      # RECORD: grid recording
        panel.settle(10_000_000)
        panel.tap(key(25))                                      # a trig on step 1
        panel.settle(10_000_000)
        P = machine.long(0x42C5A9A0)                            # the pattern: step flags u16 at +2 step (track 1)
        flags0 = machine.word(P)
        panel.hold(key(25), 5_000_000)
        panel.settle(10_000_000)
        turn(4, 1)                                              # E: SLD on
        turn(5, 3)                                              # F: SLEN 1 -> 3 steps
        panel.screen("trig2_held_locked")
        panel.let_go(key(25))
        panel.settle(10_000_000)
        tbl = machine.long(lay["sl_ui_table"])
        got = [lock(tbl, 0, 0, 0), lock(tbl, 0, 0, 1)] if tbl else None
        check("trig held, E and F turned: step 1 locks SLD ON and SLEN 3 steps", got == [1, 7], f"{got}")
        # the trig stays on after the release, as when a stock parameter is locked from a held
        # trig (and as a long hold with nothing turned: measured, stock never removes a trig on
        # a long hold's release; a tap removes it)
        flags1 = machine.word(P)
        check("trig held, E/F turned, released: the trig stays on, its step unchanged",
              tbl == P + 97872 and flags1 == flags0 and flags1 & 1, f"step 1 flags {flags0:#06x} -> {flags1:#06x}")
        flags_e0 = machine.word(P + 2)
        panel.hold(key(26), 5_000_000)                          # step 2: no trig, nothing to set
        panel.settle(10_000_000)
        turn(4, 1)
        panel.screen("trig2_held_other")
        panel.let_go(key(26))
        panel.settle(10_000_000)
        got2 = [lock(tbl, 0, 1, 0), lock(tbl, 0, 0, 0)] if tbl else None
        check("another step held and turned: its own lock, step 1's kept", got2 == [1, 1], f"{got2}")
        flags_e1 = machine.word(P + 2)
        check("an empty step held, E turned, released: a trig on it, as stock's press places one",
              not flags_e0 & 1 and flags_e1 & 0x381 == 0x381, f"step 2 flags {flags_e0:#06x} -> {flags_e1:#06x}")
        c0 = clears["n"]
        panel.tap(key(25))                                      # step 1's trig removed ...
        panel.settle(10_000_000)
        panel.screen("trig2_removed")
        panel.tap(key(25))                                      # ... and placed again: clean
        panel.settle(10_000_000)
        panel.screen("trig2_placed_again")
        report["ui_clears"] = clears["n"] - c0
        got3 = [lock(tbl, 0, 0, 0), lock(tbl, 0, 0, 1)] if tbl else None
        check("a trig removed and placed again starts without SLD/SLEN", got3 == [0xFFFF, 0xFFFF], f"{got3}")
        panel.tap(key(1))                                       # page 1: E is LFO.T's again
        panel.settle(20_000_000)
        panel.hold(key(25), 5_000_000)
        before = lock(tbl, 0, 0, 0)
        turn(4, 1)
        panel.let_go(key(25))
        panel.settle(10_000_000)
        check("TRIG page 1: E goes to stock (no SLD written)", up() == 0 and
              lock(tbl, 0, 0, 0) == before == 0xFFFF)
        panel.screen("trig1_after")

        # v0.40: copy and paste carry SLD/SLEN as they carry the stock locks (v0.39's known
        # issue: they carried none, and FUNC + RECORD / PLAY / STOP here, which clears every
        # step of the track before it pastes, left the track with no slides at all). The
        # track's map of our locks, and of a stock lock beside them for comparison, read
        # before the copy, after the clear and after the paste, each through the panel.
        def records():
            out = []
            for i in range(RECS):
                h = machine.read(tbl + REC * i, 2)
                if h != b"\xff\xff":
                    out.append((i, h, machine.read(tbl + REC * i + 2, 256)))
            return out

        def ours_map(t=0):
            return {(st, k): lock(tbl, t, st, k) for st in range(128) for k in (0, 1)
                    if lock(tbl, t, st, k) != 0xFFFF}

        def stock_map(slot, t=0):
            for i, h, v in records():
                if h == bytes([slot, t]):
                    return {st: struct.unpack_from(">H", v, 2 * st)[0] for st in range(128)
                            if struct.unpack_from(">H", v, 2 * st)[0] != 0xFFFF}
            return {}

        hits = {}
        for name, va in (("page paste", 0x40053014), ("page undo", 0x40052488), ("track paste", 0x40053728),
                         ("track undo", 0x40052824), ("trig copy", 0x40053D1E), ("trig paste", 0x40055376)):
            hits[name] = 0

            def hit(uc_, ad, sz, us, name=name):
                hits[name] += 1
            uc.hook_add(UC_HOOK_CODE, hit, begin=va, end=va)

        def func_key(k):
            panel.hold(key(17), 5_000_000)
            panel.tap(key(k))
            panel.settle(10_000_000)
            panel.let_go(key(17))
            panel.settle(10_000_000)

        # our locks on steps 2 (from above: SLD on), 6 (SLD, SLEN 1/2) and 41 (SLD, SLEN 6); a
        # stock lock (slot 90's record of track 1) on steps 6 and 41, written as the knob would
        panel.tap(key(30))                                      # a trig on step 6 (placing it clears the step)
        panel.settle(10_000_000)
        pc0, sr0 = uc.reg_read(K.UC_M68K_REG_PC), uc.reg_read(K.UC_M68K_REG_SR)
        for st, sld, slen in ((5, 1, 2), (40, 1, 9)):          # (call() leaves the PC at its
            call(sl_set, tbl, 0, st, 0, sld)                    # sentinel: the UI's put back)
            call(sl_set, tbl, 0, st, 1, slen)
        uc.reg_write(K.UC_M68K_REG_PC, pc0)
        uc.reg_write(K.UC_M68K_REG_SR, sr0)
        free = [i for i in range(RECS) if machine.read(tbl + REC * i, 2) == b"\xff\xff"][-1]
        machine.write(tbl + REC * free, bytes([90, 0]) + b"\xff\xff" * 128)
        machine.write(tbl + INDEX + 90, bytes([free]))
        for st in (5, 40):
            put16(tbl + REC * free + 2 + 2 * st, 0x1234 + st)
        before, st_before = ours_map(), stock_map(90)
        report["copy_before"] = {f"{a}/{b}": v for (a, b), v in before.items()}
        func_key(19)                                            # copy
        func_key(20)                                            # clear
        cleared, st_cleared = ours_map(), stock_map(90)
        func_key(21)                                            # paste
        after, st_after = ours_map(), stock_map(90)
        report["copy_after"] = {f"{a}/{b}": v for (a, b), v in after.items()}
        report["copy_hits"] = dict(hits)
        same_clear = all(((st, 0) in cleared) == (st in st_cleared) for st in (5, 40))
        check("FUNC + RECORD, PLAY, STOP (copy, clear, paste): SLD/SLEN cleared with the stock locks, "
              "then back exactly, every step", bool(before) and after == before and st_after == st_before
              and same_clear and st_before != st_cleared,
              f"before {sorted(before.items())}, cleared {sorted(cleared.items())}, after {sorted(after.items())}; "
              f"stock {sorted(st_before)} -> {sorted(st_cleared)} -> {sorted(st_after)}; hits {hits}")
        leaked = [i for i, h, v in records() if h[0] <= 100 and h[1] <= 16 and h != bytes([90, 0])
                  and any(struct.unpack_from(">H", v, 2 * st)[0] != 0xFFFF for st in (1, 5, 40))]
        check("the paste: no SLD/SLEN value in a stock lock", not leaked, f"{leaked}")
        panel.screen("after_paste")

        # trig copy and paste: step 6 held, RECORD (copy); step 9 held, STOP (paste): step 9 has
        # step 6's SLD/SLEN, as its stock lock
        panel.hold(key(30), 5_000_000)
        panel.tap(key(19))
        panel.settle(10_000_000)
        panel.let_go(key(30))
        panel.settle(10_000_000)
        panel.hold(key(33), 5_000_000)
        panel.tap(key(21))
        panel.settle(10_000_000)
        panel.let_go(key(33))
        panel.settle(10_000_000)
        got = [lock(tbl, 0, 8, 0), lock(tbl, 0, 8, 1)]
        st9 = stock_map(90).get(8)
        report["trig_hits"] = dict(hits)
        check("trig copy/paste: step 6's SLD/SLEN (and its stock lock) on step 9, step 6's kept",
              got == [1, 2] and st9 == 0x1234 + 5 and [lock(tbl, 0, 5, 0), lock(tbl, 0, 5, 1)] == [1, 2],
              f"step 9 {got}, stock {st9}, hits {hits}")
        panel.screen("after_trig_paste")

    faults = getattr(machine.m, "faults", [])[faults_before:]
    check("no fault", not faults, f"{len(faults)} fault(s)")
    report["failures"] = failures
    report["ok"] = not failures
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, indent=1)[:3000])
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1) + "\n")
    print(f"slides ({'stock' if a.stock else 'build'}): {'PASS' if not failures else 'FAIL ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
