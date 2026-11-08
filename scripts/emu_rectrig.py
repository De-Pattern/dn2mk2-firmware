"""v0.44 BOUNCE: recorder trigs, the buffers, QREC, QPLAY (csrc/sampler/rectrig.c, rec.c), under
the emulator. The build's audio interrupt is run frame by frame with the sequencer's state set
as the sequencer would set it (playing, each track's step: TRACK_CUR), the recorder trigs in the
playing pattern's own lock table (where rt_frame reads them), track 0's frame words as the frame
builder carries them (type BOUNCE, BUF, R.LEN, SRC, CHAN). Checked: the table's place, a trig
fires from the step itself (no note), its command, the packets, the QPLAY switch, the one-shot's
spending and re-arming, 2+1, the guards, the handover, QREC; then the RECORDER through the
panel: [TRIG] places and removes a trig, YES YES arms. docs/rectrig.md."""

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
BUF_SLOT0, BUF_N = 128, 8
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
    machine.write(lay["rt_manual"], b"\x00\x00\x00\x00")

    # ---- the pattern: playing, per pattern, 16 steps; its lock table is where rectrig.c reads it
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

    # ---- track 0 BOUNCE on BUF 1, R.LEN 4, SRC MAIN, CHAN L+R: the frame's words, as the frame
    # builder carries the sound's (rectrig.c reads them there)
    T, V = 0, 0

    # (the frame builder, in the audio interrupt, rebuilds the frame from the kit's sounds every
    # frame: the sound's type byte and its parameter words are what to set)
    kit = machine.long(KIT)

    def ctl_put(t, slot, value):
        snd = kit + 52 + SOUND_STRIDE * t
        put16(snd + 48 + 2 * slot, value << 8)
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
    call(lay["rt_poll"])
    on = L("rt_on")
    used = machine.read(lay["rt_used"], BUF_N)
    nx = [machine.long(lay["rt_nx_place"] + 4 * b) for b in range(BUF_N)]
    need = [machine.long(lay["rt_nx_need"] + 4 * b) for b in range(BUF_N)]
    room = [machine.long(lay["rt_nx_room"] + 4 * b) for b in range(BUF_N)]
    check("buffers on; only BUF 1 (the BOUNCE track's) has a next place planned",
          on == 1 and list(used) == [1] + [0] * 7 and room[0] >= need[0] > 0 and all(n == 0 for n in need[1:]),
          f"on {on}, used {list(used)}, need {need}")

    def rec_lock(step):
        return call(lay["sl_lock_get"], table, T, step, 2)[0] & 0xFFFF

    # ---- recorder trigs placed as the UI places them (rt_trig_toggle on the UI's table) --------
    v4 = call(lay["rt_trig_toggle"], table, T, 4, 0)[0] & 0xFFFF
    v8 = call(lay["rt_trig_toggle"], table, T, 8, 1)[0] & 0xFFFF
    heads = [machine.read(table + REC * i, 2) for i in range(RECS)]
    check("a recorder trig on step 4, a one-shot on step 8 (values 1, 2), one record of ours",
          v4 == 1 and v8 == 2 and rec_lock(4) == 1 and rec_lock(8) == 2 and rec_lock(5) == 0xFFFF
          and heads.count(bytes([RAM_REC, TAG | T])) == 1, f"{v4}, {v8}, {rec_lock(5)}")
    call(lay["rt_trig_toggle"], table, T, 8, 1)       # (the one-shot off again until its own section)
    again = call(lay["rt_trig_toggle"], table, T, 4, 0)[0] & 0xFFFF
    back = call(lay["rt_trig_toggle"], table, T, 4, 0)[0] & 0xFFFF
    check("[TRIG] again clears it, once more places it", again == 0xFFFF and back == 1, f"{again}, {back}")
    machine.at = 0x46A30000
    stored = machine.alloc(TABLE_BYTES)
    call(SAVE, stored, table)
    ids = [machine.read(stored + REC * i, 1)[0] for i in range(RECS)]
    ram2 = machine.alloc(TABLE_BYTES)
    machine.write(ram2, b"\xff" * (REC * RECS))
    machine.write(ram2 + INDEX, b"\xff" * (16 * 101))
    call(LOAD, ram2, stored)
    rb = [call(lay["sl_lock_get"], ram2, T, s, 2)[0] & 0xFFFF for s in (4, 8, 5)]
    check("SAVE stores the record as id 202; LOAD brings it back", ID_REC in ids and rb == [1, 0xFFFF, 0xFFFF],
          f"ids {sorted(set(ids) - {255})}, back {rb}")

    # ---- the sequencer runs: the trig fires from the step itself (no note, no voice) ----------
    put32(SEQ_PLAYING, 1)
    put32(FRAMES, 40_000)

    def at_step(s, frames=2):
        machine.write(TRACK_CUR + T, bytes([s]))
        machine.write(TRACK_CUR, bytes([s]))   # (track 0 is the master too)
        for _ in range(frames):
            put32(FRAMES, machine.long(FRAMES) + 1)
            frame()
        put32(FRAMES, machine.long(FRAMES) + 160)   # a step's time passes (about 0.1 s), and
        call(lay["rt_poll"])                        # the UI loop plans the next place, as it does every pass
    for s in range(0, 4):
        at_step(s)
    f0 = L("rt_fired")
    check("steps 0..3 fire nothing", f0 == 0, f"fired {f0}")
    if os.environ.get("RT_DEBUG"):
        print("DEBUG last_step", machine.read(lay["rt_last_step"], 16).hex(), "is_bounce", call(lay["rt_is_bounce"], T)[0],
              "lock(4)", rec_lock(4), "buf_of", call(lay["rt_buf_of"], T)[0], "playing", machine.long(SEQ_PLAYING),
              "pos", L("rt_pos"), "steps", L("rt_steps"))
    call(lay["rt_poll"])
    tempo = machine.word(TEMPO_AT)
    nx0 = machine.long(lay["rt_nx_place"])
    need0 = machine.long(lay["rt_nx_need"])
    want_fr = min(4 * (86400000 // tempo), (need0 // 2) & ~31)
    gen0, sent0 = L("rt_gen"), L("smp_rt_sent")
    qhead = machine.read(lay["smp_cmds"], 4)
    at_step(4, 3)
    w = [machine.long(lay["rt_w"] + 4 * j) for j in range(6)]
    want_slot = BUF_SLOT0 + 1                          # BUF 1's idle half (half 1)
    check("step 4 fires one take (the step itself, no note needed; the frames after it not again)",
          L("rt_fired") == 1 and L("rt_gen") == gen0 + 1 and L("rt_last_key") == (T << 8 | 4),
          f"fired {L('rt_fired')}, gen {L('rt_gen') - gen0}, key {L('rt_last_key'):#x}")
    check(f"its command: a buffer take's sequence, NOW, MAIN, L+R, its place, slot {want_slot}, R.LEN 4 steps "
          f"at the frame's tempo ({want_fr} frames), the steps in the threshold word",
          (w[0] & 0x8000) and w[1] == 2 and w[2] == 1 and (w[3] & 3) == 0
          and (w[3] >> 8) == nx0 // 512 and (w[5] >> 24) == want_slot and (w[5] & 0xFFFFFF) == want_fr
          and (w[4] >> 16) == 4, [hex(x) for x in w])
    for _ in range(12):
        put32(FRAMES, machine.long(FRAMES) + 1)
        frame()
    check("the packets carried it (8 repeats), the UI's queue untouched",
          L("smp_rt_sent") == sent0 + 1 and machine.read(lay["smp_cmds"], 4) == qhead,
          f"rt sent {L('smp_rt_sent') - sent0}")
    play0 = machine.read(lay["rt_play"], 1)[0]
    samp0 = call(lay["rt_bounce_samp"], T)[0]
    check("QPLAY PLEN: the track still hears nothing new while the take records (its old half empty: SAMP 0)",
          play0 == 0 and samp0 == 0 and machine.read(lay["rt_pend"], 1)[0] == 1, f"play {play0}, SAMP {samp0}")
    for s in range(5, 16):
        at_step(s)
    mid = machine.read(lay["rt_play"], 1)[0]
    at_step(0)
    after = machine.read(lay["rt_play"], 1)[0]
    sampb = call(lay["rt_bounce_samp"], T)[0]
    check(".. and switches at the pattern's first step, not before: the voice's SAMP is the half's "
          f"({want_slot + 1})", mid == 0 and after == 1 and sampb == want_slot + 1,
          f"before {mid}, after {after}, SAMP {sampb}")
    steps_rec = machine.read(lay["rt_rsteps"] + 2 * (want_slot - BUF_SLOT0), 2)
    check("the take's steps kept (4)", struct.unpack(">H", steps_rec)[0] == 4, steps_rec.hex())

    def take_over():                                   # time passes: the take ends, the UI plans the next place
        put32(FRAMES, L("rt_cur_end") + 10)
        call(lay["rt_poll"])

    # ---- the one-shot on step 8: fires once, then spent; YES YES arms it again ----------------
    take_over()
    call(lay["rt_trig_toggle"], table, T, 8, 1)       # the one-shot placed now
    for s in range(1, 8):
        at_step(s)
    f1 = L("rt_fired")
    at_step(8, 3)
    f2 = L("rt_fired")
    v8s = rec_lock(8)
    if os.environ.get("RT_DEBUG"):
        print("DEBUG oneshot: why", L("rt_why"), "refused", L("rt_refused"), "key", hex(L("rt_last_key")), "cur", L("rt_cur"),
              "nx_room", machine.long(lay["rt_nx_room"]), "nx_need", machine.long(lay["rt_nx_need"]), "manual", L("rt_manual"), "on", L("rt_on"))
    check("the one-shot on step 8 fires, and is spent (3) after it", f2 == f1 + 1 and v8s == 3, f"fired {f2 - f1}, value {v8s}")
    take_over()
    for s in list(range(9, 16)) + list(range(0, 8)):
        at_step(s)
    f3 = L("rt_fired")
    at_step(8, 3)
    f4 = L("rt_fired")
    check("spent: the next pass over step 8 records nothing", f4 == f3, f"fired {f4 - f3}")
    n = call(lay["rt_rearm"], table, T)[0]
    check("YES YES: the spent one-shot armed again (1)", n == 1 and rec_lock(8) == 2, f"{n}, {rec_lock(8)}")
    take_over()
    for s in list(range(9, 16)) + list(range(0, 8)):
        at_step(s)
    f5 = L("rt_fired")
    at_step(8, 3)
    check(".. and fires once more", L("rt_fired") == f5 + 1, f"fired {L('rt_fired') - f5}")

    # ---- a second BOUNCE track on the same buffer, "2+1": it hears the same half --------------
    type_put(1, BOUNCE)
    ctl_put(1, SLOT_BUF, 0)
    s1 = call(lay["rt_bounce_samp"], 1)[0]
    check("a second BOUNCE track on BUF 1 hears the same half (2+1)", s1 == sampb, f"{s1} vs {sampb}")
    ctl_put(1, SLOT_BUF, 3)
    s1b = call(lay["rt_bounce_samp"], 1)[0]
    check("on BUF 4 (nothing recorded) it hears nothing: SAMP 0", s1b == 0, s1b)
    type_put(1, 8)                                     # ONESHOT again

    # ---- guards --------------------------------------------------------------------------------
    take_over()
    machine.write(lay["rt_manual"], b"\x00\x00\x00\x01")
    for s in list(range(9, 16)) + list(range(0, 4)):
        at_step(s)
    f6 = L("rt_fired")
    at_step(4, 3)
    why_manual = L("rt_why")
    check("a manual take's turn: the trig records nothing, and says why (2)", L("rt_fired") == f6 and why_manual == 2
          and L("rt_why_at") != 0 and machine.read(lay["rt_why_trk"], 1)[0] == T, f"fired {L('rt_fired') - f6}, why {why_manual}")
    machine.write(lay["rt_manual"], b"\x00\x00\x00\x00")
    # the allocator keeps a manual take clear of the live halves and the planned places
    pl = machine.long(lay["rt_rplace"] + 4 * (want_slot - BUF_SLOT0))
    by = machine.long(lay["rt_rbytes"] + 4 * (want_slot - BUF_SLOT0))
    call(lay["rt_poll"])
    room_w = machine.alloc(8)
    place = call(lay["smp_rec_place"], 5, room_w)[0]
    rm = machine.long(room_w)
    nxp = machine.long(lay["rt_nx_place"])
    nxn = machine.long(lay["rt_nx_need"])
    clash = (place < pl + by and pl < place + rm) or (place < nxp + nxn and nxp < place + rm)
    check("a manual take's place keeps clear of the live half and the planned next take", not clash and rm > 0,
          f"place {place:#x} room {rm:#x}; half {pl:#x}+{by:#x}; next {nxp:#x}+{nxn:#x}")

    # ---- the take saved into a pool slot (FUNC + YES): the handover ---------------------------
    take_over()
    for s in list(range(5, 16)) + [0]:                 # the last take heard (QPLAY PLEN: the top)
        at_step(s)
    pl = machine.long(lay["rt_rplace"] + 4 * (want_slot - BUF_SLOT0 + 0))
    by = machine.long(lay["rt_rbytes"] + 4 * (want_slot - BUF_SLOT0 + 0))
    playing_half = machine.read(lay["rt_play"], 1)[0]
    pl = machine.long(lay["rt_rplace"] + 4 * playing_half)
    by = machine.long(lay["rt_rbytes"] + 4 * playing_half)
    hb = machine.alloc(8)
    hs = machine.alloc(8)
    hp = call(lay["rt_take_handover"], T, hb, hs)[0]
    check("the playing take hands over: its place, bytes and steps (4)",
          hp == pl and machine.long(hb) == by and machine.long(hs) == 4, f"{hp:#x} {machine.long(hb)} {machine.long(hs)}")

    # ---- a track that is not BOUNCE never fires; a BOUNCE track with no trigs neither ----------
    type_put(T, 8)
    for s in list(range(5, 16)) + list(range(0, 5)):
        at_step(s)
    f7 = L("rt_fired")
    type_put(T, BOUNCE)
    check("the same steps on an ONESHOT track record nothing", L("rt_fired") == f7 and f7 == L("rt_fired"), f"{f7}")

    # ---- QREC 8 ----------------------------------------------------------------------------------
    setv("rt_qrec", 4)                                 # 8 steps
    qw = machine.alloc(24)
    machine.write(qw, struct.pack(">6I", 0x0101, 2, 1, 0, 33, 5 << 24 | 4800))
    at_step(5)
    call(lay["rt_q_set"], qw)
    q0 = L("rt_qfired")
    for s in (6, 7):
        at_step(s)
    q1 = L("rt_qfired")
    at_step(8)
    q2 = L("rt_qfired")
    check("QREC 8: a manual NOW waits through steps 5..7, goes on step 8", q1 == q0 and q2 == q0 + 1, f"{q0} {q1} {q2}")
    setv("rt_qrec", 0)

    # ---- the step clear --------------------------------------------------------------------------
    call(lay["sl_lock_set"], table, T, 4, 2, 0xFFFF)
    call(lay["sl_lock_set"], table, T, 8, 2, 0xFFFF)
    heads = [machine.read(table + REC * i, 2) for i in range(RECS)]
    check("clearing both recorder trigs frees our record", heads.count(bytes([RAM_REC, TAG | T])) == 0)
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
        led_stock = leds()
        claims0 = L("bn_led_claims") if "bn_led_claims" in lay else None
        call(lay["rec_combo"])                              # FUNC + VOICE: the RECORDER
        panel.settle(10_000_000)
        panel.screen("bounce_recorder")
        act = L("rec_overlay") == 1 and L("rec_phase") == 0 and machine.read(kit + 52 + SOUND_STRIDE * T + 0xDE, 1)[0] == BOUNCE
        check("the RECORDER of a BOUNCE track is up, the BOUNCE view (rec_overlay, phase REC, the sound BOUNCE)", act,
              f"overlay {L('rec_overlay')}, phase {L('rec_phase')}")
        # (no harness calls from here on: a call into the firmware in the middle of the UI's run
        # takes the CPU from under the UI task -- reads only)
        panel.tap(key(25 + 2))                              # [TRIG 3]: a recorder trig on step 3
        panel.settle(10_000_000)
        panel.screen("bounce_trig3")
        v3 = machine.word(table + REC * [i for i in range(RECS) if machine.read(table + REC * i, 2) == bytes([RAM_REC, TAG | T])][0] + 2 + 2 * 2) \
            if any(machine.read(table + REC * i, 2) == bytes([RAM_REC, TAG | T]) for i in range(RECS)) else 0xFFFF
        check("[TRIG 3] on the BOUNCE RECORDER places a recorder trig on step 3 (and no note trig)", v3 == 1, f"value {v3}")
        if claims0 is not None:
            led3 = leds()
            check("v0.45: the panel up, [TRIG 3]'s LED red (mode 2, palette 17), the other trig LEDs unlit "
                  "(stock's note trigs not shown through)",
                  L("bn_led_claims") > claims0 and led3[2] == (2, 17)
                  and all(m_ == 1 for i, (m_, _v) in enumerate(led3) if i != 2), f"{led3[:4]} claims {L('bn_led_claims')}")
        panel.tap(key(25 + 2))
        panel.settle(10_000_000)
        v3b = machine.word(table + REC * [i for i in range(RECS) if machine.read(table + REC * i, 2) == bytes([RAM_REC, TAG | T])][0] + 2 + 2 * 2) \
            if any(machine.read(table + REC * i, 2) == bytes([RAM_REC, TAG | T]) for i in range(RECS)) else 0xFFFF
        check("[TRIG 3] again removes it", v3b == 0xFFFF, f"value {v3b}")
        if claims0 is not None:
            led3b = leds()
            check("v0.45: removed, its LED unlit again", led3b[2:3] == [(1, 1)], f"{led3b[:4]}")
        panel.tap(key(10))                                  # YES
        panel.settle(200_000)
        panel.tap(key(10))                                  # YES again, within 0.4 s: arm
        panel.settle(10_000_000)
        check("YES YES: taken as the arming, no RECORD NOW sent", L("bn_yes_at") == 0 and L("rec_state") != 2,
              f"yes_at {L('bn_yes_at')}, state {L('rec_state')}")
        panel.screen("bounce_armed")
        panel.tap(key(12))                                  # NO: closes
        panel.settle(10_000_000)
        check("NO closes the RECORDER", L("rec_overlay") == 0)
        if claims0 is not None:
            c1 = L("bn_led_claims")
            panel.settle(10_000_000)
            led_after = leds()
            check("v0.45: closed, the trig LEDs are stock's again and ours claim nothing",
                  led_after == led_stock and L("bn_led_claims") == c1, f"{led_after[:4]} vs {led_stock[:4]}")

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
    ok = all(c["ok"] for c in report["checks"].values())
    report["ok"] = ok
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1))
    n = len(report["checks"])
    print(("PASS" if ok else "FAIL") + f": {sum(c['ok'] for c in report['checks'].values())}/{n} checks", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
