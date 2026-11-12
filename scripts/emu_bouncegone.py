"""v0.48 (docs/bounce-removal-plan.md): BOUNCE is out of the firmware. What an older project
needs still works and nothing of BOUNCE runs: a BOUNCE track (type 17) loaded in the kit plays
SAMP OFF every frame with the sequencer running over recorder trigs on its steps, sends nothing to
the DSP and makes the recordings' allocator keep nothing clear; recorder trigs (the lock store's
third kind, stored id 202) and a slide beside them go through SAVE and LOAD byte for byte; the LED
compose's site holds stock's bytes; record 244's text is stock's on every machine; FUNC + VOICE on
the BOUNCE track opens the plain RECORDER. Kept from the rectrig step it replaces (v0.41..v0.47):
SAMP never glides (v0.45), the RECORDER's CHAN knob and FILE NAME keys through the panel (v0.44),
the Monomachine's TUNE text and steps (v0.47)."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from emulib.image import differences                           # noqa: E402
from emulib.machine import Machine                             # noqa: E402

ISR, ISR_RTE = 0x40025E36, 0x40027BC6
SRC, STATE = 0x80003AF0, 0x8000DE60
OWNER, FRAMES, TEMPO_AT = 0x80005308, 0x4058E8D4, 0x80005E60 + 216
KIT, SOUND_STRIDE = 0x800052A0, 1163
SYNC, UNDO, BITMAP_CLEAR = 0x4002549C, 0x400DAF44, 0x400DB052
BUILD, APPLY = 0x400D85E8, 0x400DB092
LOAD, SAVE, CLEAR = 0x400DE51E, 0x400DE718, 0x4003D14E
SEQ_PLAYING, SEQ_PATTERN, TRACK_CUR = 0x42C5A918, 0x42C5A9A0, 0x42C5A984
PAT_LENGTH, PAT_MODE = 122196, 122201
REC, RECS, INDEX, TABLE_BYTES = 258, 80, 20640, 22256 + 2048
LIST_BYTES = 20 + 202 * 8
STACK_TOP, SENTINEL = 0x46A20000, 0x46A20400
REC_FIRST = 123
RAM_REC, ID_REC, TAG = 0x52, 202, 0x20
PAT_LOCK_TABLE = 97872                  # v0.44: the pattern's lock table inside the pattern object (rectrig.c)
CTL_FRAME = 0x80005E60
BOUNCE = 17
SLOT_BUF, SLOT_SRC, SLOT_RLEN, SLOT_CHAN = 35, 38, 40, 46

report: dict = {"checks": {}}


def check(name, ok, detail=""):
    report["checks"][name] = {"ok": bool(ok), "detail": str(detail)}
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""), flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--build", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--json", default=None)
    p.add_argument("--png-dir", default=None)
    p.add_argument("--layout", default=str(HERE.parent / "src/dnfw/mods/waverider_code.json"))
    a = p.parse_args()

    machine = Machine(a.snapshot)
    uc = machine.uc
    from unicorn import UC_PROT_ALL, UcError
    from unicorn import m68k_const as K
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    snap_image = pathlib.Path(a.snapshot + ".section_3_MAIN_OS.bin")
    if snap_image.exists():
        back = [(va, stock[va - 0x40000400:va - 0x40000400 + len(b)]) for va, b in
                differences(stock, snap_image.read_bytes()) if va + len(b) <= 0x40000400 + len(stock)]
        machine.apply(back)
    image = (pathlib.Path(a.build) / "section_3_MAIN_OS.bin").read_bytes()
    machine.apply(differences(stock, image))
    from dnfw.mods import platform                             # noqa: PLC0415
    from dnfw.sampler import machines as SM                    # noqa: PLC0415
    for va, blob in platform.runtime(image):
        machine.write(va, blob)
    for page in range(SM.MIRROR, SM.MIRROR + SM.MIRROR_BYTES, 0x100000):
        try:
            uc.mem_map(page, 0x100000, UC_PROT_ALL)
        except UcError:
            pass
    machine.flush()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    regs = [getattr(K, f"UC_M68K_REG_{r}{i}") for r in "DA" for i in range(8)]

    def call(fn, *args, until=None, limit=50_000_000):
        saved = [uc.reg_read(r) for r in regs]
        sp = STACK_TOP - 0x200
        machine.write(sp, struct.pack(">I", SENTINEL) + b"".join(struct.pack(">I", x & 0xFFFFFFFF) for x in args))
        machine.write(SENTINEL, bytes.fromhex("4e714e71"))
        uc.reg_write(K.UC_M68K_REG_A7, sp)
        stepper = getattr(machine.m, "_fast_stepper_obj", None)
        if stepper is not None:
            stepper.left = 1 << 40
        try:
            uc.emu_start(fn, until if until is not None else SENTINEL, count=limit)
        finally:
            if stepper is not None:
                stepper.left = 0
        d0 = uc.reg_read(K.UC_M68K_REG_D0)
        pc = uc.reg_read(K.UC_M68K_REG_PC)
        for r, v in zip(regs, saved):
            uc.reg_write(r, v)
        return d0, pc

    def L(name):
        return machine.long(lay[name])

    def put32(va, v):
        machine.write(va, struct.pack(">I", v & 0xFFFFFFFF))

    def put16(va, v):
        machine.write(va, struct.pack(">H", v & 0xFFFF))

    def setv(name, v):
        put32(lay[name], v)

    def frame():
        _, pc = call(ISR, until=ISR_RTE)
        return pc == ISR_RTE

    faults0 = len(getattr(machine.m, "faults", []))

    # ---- the sample link's directory: whole, every slot empty ---------------------------------
    DIR = SM.MIRROR
    machine.write(DIR + 8, b"\x00" * 16 * SM.POOL_SLOTS)
    setv("smp_dir_ok", 1)
    put16(TEMPO_AT, 120 * 120)

    # ---- the pattern: playing, per pattern, 16 steps; its lock table (the pattern object's)
    pat = machine.long(SEQ_PATTERN)
    machine.write(pat + PAT_MODE, b"\x00")
    put16(pat + PAT_LENGTH, 16)
    put32(SEQ_PLAYING, 0)
    table = pat + PAT_LOCK_TABLE
    # the model's table getter (vtable +40: *(model + 16)) must give the same address
    APP, TRACK_CTX = 0x4018A97A, 0x4003EFDE
    app = call(APP)[0]
    ctx = call(TRACK_CTX, app)[0]
    model = machine.long(ctx + 44)
    getter = machine.long(machine.long(model) + 40)
    got = call(getter, model)[0]
    check("the playing pattern's lock table is PATTERN + 97,872 (the model's getter says so)",
          got == table, f"getter {got:#x}, PATTERN + off {table:#x}")

    # ---- track 0 BOUNCE, as an older project holds it (type 17, BUF 1, R.LEN 4, SRC MAIN) ------
    T = 0
    kit = machine.long(KIT)

    def ctl_put(t, slot, value):
        snd = kit + 52 + SOUND_STRIDE * t
        put16(snd + 20 + 2 * slot, value << 8)          # v0.50: where the knob writes (was + 48)
        put16(CTL_FRAME + 168 + 2 * slot + 146 * t, value << 8)

    def type_put(t, ty):
        snd = kit + 52 + SOUND_STRIDE * t
        machine.write(snd + 0xDE, bytes([ty]))
        put16(CTL_FRAME + 148 + 2 * t, ty)
    type_put(T, BOUNCE)
    ctl_put(T, SLOT_BUF, 0)
    ctl_put(T, SLOT_RLEN, 4)
    ctl_put(T, SLOT_SRC, 1)
    ctl_put(T, SLOT_CHAN, 0)

    def rec_lock(tab, step, k=2):
        return call(lay["sl_lock_get"], tab, T, step, k)[0] & 0xFFFF

    # ---- recorder trigs and a slide in the pattern, as v0.44..v0.47 saved them ----------------
    call(lay["sl_lock_set"], table, T, 4, 2, 1)       # a recorder trig on step 4
    call(lay["sl_lock_set"], table, T, 8, 2, 2)       # a one-shot on step 8
    call(lay["sl_lock_set"], table, T, 4, 0, 5)       # a slide on step 4 (the store's first kind)
    before = [rec_lock(table, 4), rec_lock(table, 8), rec_lock(table, 4, 0), rec_lock(table, 5)]
    machine.at = 0x46A30000
    stored = machine.alloc(TABLE_BYTES)
    call(SAVE, stored, table)
    ids = [machine.read(stored + REC * i, 1)[0] for i in range(RECS)]
    ram2 = machine.alloc(TABLE_BYTES)
    machine.write(ram2, b"\xff" * (REC * RECS))
    machine.write(ram2 + INDEX, b"\xff" * (16 * 101))
    call(LOAD, ram2, stored)
    after = [rec_lock(ram2, 4), rec_lock(ram2, 8), rec_lock(ram2, 4, 0), rec_lock(ram2, 5)]
    stored2 = machine.alloc(TABLE_BYTES)
    call(SAVE, stored2, ram2)
    check("recorder trigs (id 202) and a slide on the same step go through SAVE and LOAD as they were, "
          "and save again byte for byte", before == [1, 2, 5, 0xFFFF] and after == before and ID_REC in ids
          and machine.read(stored, TABLE_BYTES) == machine.read(stored2, TABLE_BYTES),
          f"before {before}, after {after}, ids {sorted(set(ids) - {255})}")

    # ---- the allocator keeps nothing clear for a BOUNCE track ----------------------------------
    rm = machine.alloc(8)
    p_b = call(lay["smp_rec_place"], 0, rm)[0]
    r_b = machine.long(rm)
    type_put(T, 8)                                     # the same track ONESHOT
    p_o = call(lay["smp_rec_place"], 0, rm)[0]
    r_o = machine.long(rm)
    type_put(T, BOUNCE)
    check("a recording's place and room are the same with a BOUNCE track as with an ONESHOT one",
          (p_b, r_b) == (p_o, r_o) and r_b > 0, f"bounce {p_b:#x}+{r_b:#x}, oneshot {p_o:#x}+{r_o:#x}")

    # ---- the sequencer plays over the recorder trigs: nothing fires, the voice plays OFF --------
    SAMP_SLOT, VOICE_SOUND, MIRROR = 43, 0x800052A8, 0x800068E4
    snd0 = kit + 52 + SOUND_STRIDE * T
    put32(VOICE_SOUND + 4 * 0, snd0)                   # voice 0 plays track 0's sound
    mir = MIRROR + 34 + 202 * 0 + 2 * SAMP_SLOT
    put16(mir, 129 << 8)                               # a buffer half's SAMP, as v0.47 would have heard
    qhead = machine.read(lay["smp_cmds"], 4)
    sent0 = L("smp_tdm_sent")
    put32(SEQ_PLAYING, 1)
    put32(FRAMES, 40_000)
    heard = []
    for _ in range(2):
        for s in range(16):
            machine.write(TRACK_CUR + T, bytes([s]))
            for _ in range(2):
                put32(FRAMES, machine.long(FRAMES) + 1)
                frame()
                heard.append(struct.unpack(">H", machine.read(mir, 2))[0] >> 8)
    put32(SEQ_PLAYING, 0)
    check("two passes of the pattern over the recorder trigs: the BOUNCE voice plays SAMP OFF every frame",
          heard and all(h == 0 for h in heard), f"{sorted(set(heard))}")
    check(".. and nothing goes to the DSP (no command queued, no packet sent)",
          machine.read(lay["smp_cmds"], 4) == qhead and L("smp_tdm_sent") == sent0,
          f"queue {qhead.hex()} -> {machine.read(lay['smp_cmds'], 4).hex()}, sent {L('smp_tdm_sent') - sent0}")
    check(".. and the recorder trigs are where they were", [rec_lock(table, 4), rec_lock(table, 8)] == [1, 2])
    put32(VOICE_SOUND + 4 * 0, 0)

    # ---- the LED compose's walk is stock's -----------------------------------------------------
    led_site = machine.read(0x4002C880, 6)
    check("the LED compose's site holds stock's jsr 0x4011d3b2 (the BOUNCE REC panel's LEDs gone)",
          led_site == bytes.fromhex("4eb94011d3b2"), led_site.hex())

    # ---- record 244 (BOUNCE's BUF) shows stock's text on every machine --------------------------
    REC244 = 0x401F7F94 + 60 * 244
    stock_f = machine.long(REC244 + 0x34)
    fs = []
    for kind in (13, 4, 0, 2):                         # BOUNCE, ONESHOT, a stock machine, SID
        call(lay["smp_formats"], kind)
        fs.append(machine.long(REC244 + 0x34))
    check("record 244's text is stock's on every machine, BOUNCE's too", all(f == stock_f for f in fs),
          f"{[hex(f) for f in fs]} want {stock_f:#x}")
    call(lay["smp_formats"], 0)

    # ---- v0.45: SAMP never glides (the owner, v0.44: scrolling SAMP past the loaded samples,
    # trigs played the last loaded one). Track 1 ONESHOT, slots 0..2 loaded; SAMP moves from 2 to
    # 10 (past them) with the smoother still at 2: what the voice hears is 10 at once, not the
    # smoother's glide mapped onto the loaded slots (slot 2, SAMP 3, before the fix)
    T1, ONESHOT_TY, SAMP_SLOT, VOICE_SOUND = 1, 8, 43, 0x800052A8
    MIRROR = 0x800068E4
    import dnfw.waverider.dsp as DSPL
    for k in range(3):
        machine.write(DIR + 8 + 16 * k, struct.pack("<IIfI", DSPL.SMP_POOL_DDR + SM.DATA_OFFSET + 0x10000 * k,
                                                    4800, 1.0, 1))
    type_put(T1, ONESHOT_TY)
    snd1 = kit + 52 + SOUND_STRIDE * T1
    put32(VOICE_SOUND + 4 * T1, snd1)
    tgt = SRC + 34 + 202 * T1 + 2 * SAMP_SLOT
    mir = MIRROR + 34 + 202 * T1 + 2 * SAMP_SLOT
    st = STATE + 4 * (101 * T1 + 17 + SAMP_SLOT)
    ctl_put(T1, SAMP_SLOT, 2)
    put16(tgt, 2 << 8)
    put16(mir, 2 << 8)
    put32(st, (2 << 8) << 16)
    frame()
    heard0 = struct.unpack(">H", machine.read(mir, 2))[0] >> 8
    ctl_put(T1, SAMP_SLOT, 10)
    put16(tgt, 10 << 8)                                # the sound's SAMP; the smoother's state still at 2
    seen = []
    for _ in range(6):
        frame()
        seen.append(struct.unpack(">H", machine.read(mir, 2))[0] >> 8)
    check("SAMP past the loaded slots is heard at once, never a loaded one in its place "
          "(v0.45: the smoother's glide was taken for modulation)",
          heard0 == 2 and all(s == 10 for s in seen), f"before {heard0}, after {seen}")
    put32(VOICE_SOUND + 4 * T1, 0)
    type_put(T1, 0)
    machine.write(DIR + 8, b"\x00" * 16 * 3)

    faults = getattr(machine.m, "faults", [])[faults0:]
    check("no memory faults", not faults, faults[:3])

    # ---- the RECORDER through the panel (last: it changes the UI) ----------------------------
    if a.png_dir:
        from emulib.panel import Panel                         # noqa: PLC0415
        panel = Panel(machine, png_dir=a.png_dir)

        def key(code):
            return ((code - 1) // 8, (code - 1) % 8)
        put32(SEQ_PLAYING, 0)
        panel.settle(5_000_000)
        # v0.45: the trig LEDs (stock's LedManager, docs/leds.md: modes at +40, palette values at
        # +256, 4 bytes an LED; the trig keys are ids 26..41) -- stock's before the panel opens
        LM_PTR = 0x446478E0

        def leds():
            lm = machine.long(LM_PTR)
            return [(machine.long(lm + 40 + 4 * i), machine.long(lm + 256 + 4 * i)) for i in range(26, 42)] if lm else []

        def leds_whole():
            """the trig LEDs once a refresh has finished (v0.46): the compose clears every LED, then
            the views set theirs one by one, so a read inside a refresh sees the last ones (0, 0); the
            unit shows them only after it. Up to 20 short settles until none is still cleared"""
            got = leds()
            for _ in range(20):
                if got and all(v != (0, 0) for v in got):
                    break
                panel.settle(1_000_000)
                got = leds()
            return got
        led_stock = leds_whole()
        call(lay["rec_combo"])                              # FUNC + VOICE on the BOUNCE track
        panel.settle(10_000_000)
        panel.screen("bounce_track_recorder")
        check("FUNC + VOICE on a BOUNCE track opens the plain RECORDER (phase REC)",
              L("rec_overlay") == 1 and L("rec_phase") == 0 and machine.read(kit + 52 + SOUND_STRIDE * T + 0xDE, 1)[0] == BOUNCE,
              f"overlay {L('rec_overlay')}, phase {L('rec_phase')}")
        led_up = leds_whole()
        check(".. and the trig LEDs stay stock's", led_up == led_stock, f"{led_up[:4]} vs {led_stock[:4]}")
        panel.tap(key(12))                                  # NO: closes
        panel.settle(10_000_000)
        check("NO closes it", L("rec_overlay") == 0)

        # ---- v0.44 F1: the plain RECORDER (an ONESHOT track): CHAN as its own L/R icon over
        # SRC (the same place on the BOUNCE panel); knob B turns it L+R -> L -> R
        type_put(T, 8)                                      # ONESHOT (the UI reads the kit's sound)
        put32(lay["rec_overlay"], 1)                        # (a write, not a call: the UI task keeps the CPU)
        put32(lay["rec_phase"], 0)
        put32(lay["rec_chan"], 0)
        put32(lay["smp_overlay_dirty"], 1)
        panel.settle(10_000_000)
        panel.screen("recorder_chan_lr")
        panel.push_and_turn(1, 1, times=6)                  # knob B, a few detents up
        panel.settle(10_000_000)
        panel.screen("recorder_chan_l")
        check("knob B on the RECORDER turns CHAN (L+R -> L)", L("rec_chan") == 1, f"chan {L('rec_chan')}")
        check("the RECORDER is up on the ONESHOT track, phase REC", L("rec_overlay") == 1 and L("rec_phase") == 0)

        # ---- v0.44 F2: FILE NAME: UP/DOWN scroll the character at the cursor, LEFT/RIGHT move it
        put32(lay["rec_phase"], 2)                          # PH_NAME
        machine.write(lay["nm_text"], b"A\0\0\0\0\0\0\0")
        put32(lay["nm_cur"], 0)
        put32(lay["smp_overlay_dirty"], 1)
        panel.settle(10_000_000)
        panel.screen("file_name")
        panel.tap(key(11))                                  # UP
        panel.settle(10_000_000)
        ch1 = machine.read(lay["nm_text"], 1)
        check("UP on FILE NAME steps the character at the cursor on (A -> B)", ch1 == b"B", f"{ch1!r}")
        panel.tap(key(14))                                  # DOWN
        panel.settle(10_000_000)
        panel.tap(key(14))
        panel.settle(10_000_000)
        ch2 = machine.read(lay["nm_text"], 1)
        check("DOWN steps it back (B -> A -> space)", ch2 == b" ", f"{ch2!r}")
        panel.tap(key(15))                                  # RIGHT: the cursor moves
        panel.settle(10_000_000)
        check("RIGHT moves the cursor", L("nm_cur") == 1, f"cur {L('nm_cur')}")
        panel.tap(key(12))                                  # NO: the name as it is -> ASSIGN
        panel.settle(10_000_000)
        check("NO on FILE NAME goes on to ASSIGN", L("rec_phase") == 3, f"phase {L('rec_phase')}")
        panel.tap(key(12))                                  # NO: skip
        panel.settle(10_000_000)
        check("NO on ASSIGN: back to the RECORDER", L("rec_phase") == 0, f"phase {L('rec_phase')}")
        put32(lay["rec_overlay"], 0)
        put32(lay["smp_overlay_dirty"], 1)
        type_put(T, BOUNCE)
    # v0.47: the Monomachine's TUNE (knob H, record 240): its header text a signed knob
    # (-64..+63, 0 in tune), not stock's percentage; FUNC + turn steps by semitones (32)
    if "smp_quant" in lay:
        REC240 = 0x401F7F94 + 60 * 240
        stock_t = machine.long(REC240 + 0x34)
        call(lay["smp_formats"], 2)                          # SID 6581 (type 6, kind 2)
        f_t = machine.long(REC240 + 0x34)
        tt = []
        for v in (0, 25, 50, 75, 100):
            machine.write(SENTINEL + 0x100, bytes(16))
            call(f_t, v << 8, SENTINEL + 0x100)
            tt.append(machine.read(SENTINEL + 0x100, 8).split(b"\0")[0].decode("latin-1"))
        check("v0.47: the Monomachine's TUNE reads -64..+63, 0 in tune (not a percentage)",
              f_t != stock_t and tt == ["-64", "-32", "0", "+31", "+63"], f"{tt}")
        call(lay["smp_formats"], 1)                          # PERC (record 240 is its PD1)
        f_p = machine.long(REC240 + 0x34)
        call(lay["smp_formats"], 0)
        f_s = machine.long(REC240 + 0x34)
        check("v0.47: record 240's text is stock's on PERC and stock machines", f_p == stock_t and f_s == stock_t,
              f"perc {f_p:#x}, stock {f_s:#x}, want {stock_t:#x}")
        snd = SENTINEL + 0x200                               # a sound: type SID, TUNE (slot 29) in tune
        machine.write(snd, bytes(0x100))
        machine.write(snd + 0xDE, bytes([6]))
        TSLOT = 29

        def func_turn(d, v):
            put16(snd + 0x14 + 2 * TSLOT, v)
            put32(lay["smp_func_held"], 1)
            put32(lay["smp_knob_d"], d & 0xFFFFFFFF)
            put32(lay["smp_knob_at"], machine.long(FRAMES))
            r = call(lay["smp_quant"], snd, TSLOT, (v + (0x100 if d > 0 else -0x100)) & 0xFFFF, 240)[0] & 0xFFFF
            put32(lay["smp_func_held"], 0)
            return r

        def kn(v):
            c = v >> 8
            return (c * 254 + 100) // 200 - 64
        v, up, down = 50 << 8, [], []
        for _ in range(3):
            v = func_turn(1, v)
            up.append(kn(v))
        for _ in range(5):
            v = func_turn(-1, v)
            down.append(kn(v))
        check("v0.47: FUNC + turn on the Monomachine's TUNE steps by semitones (+1 semitone is the knob "
              "+33 or +31: the record has no +32)", up == [33, 63, 63] and down == [31, 0, -32, -64, -64],
              f"up {up}, down {down}")
        put16(snd + 0x14 + 2 * TSLOT, 50 << 8)
        put32(lay["smp_knob_d"], 1)
        put32(lay["smp_knob_at"], machine.long(FRAMES))
        plain = call(lay["smp_quant"], snd, TSLOT, 51 << 8, 240)[0] & 0xFFFF
        check("v0.47: without FUNC, TUNE turns as before (the value as written)", plain == 51 << 8, f"{plain:#x}")
    ok = all(c["ok"] for c in report["checks"].values())
    report["ok"] = ok
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1))
    n = len(report["checks"])
    print(("PASS" if ok else "FAIL") + f": {sum(c['ok'] for c in report['checks'].values())}/{n} checks", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())