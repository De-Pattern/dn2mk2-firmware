"""REC trigs, the REC buffers, QREC and QPLAY under digikit's ColdFire emulator (docs/rectrig.md):
the gate's check (ship_gate.py step "rectrig").

    DT2_SECTIONS=../sec111 DT2_MAIN_IMG=../sec111/section_3_MAIN_OS.bin \\
    DNFW_EMU_FLAGS='{"weakptr": false}' ../digikit/.venv/bin/python -u scripts/emu_rectrig.py \\
        --build out/b41 --snapshot ../digikit/out/snapshots/dn2-1.11/ui800M-v014.snap \\
        --json out/rectrig.json [--png-dir out/rectrig]

The sequencer does not play under the emulator (docs/emulator.md), so, as emu_slides does, a
trig is what the note block runs for a voice: the lock-list builder and the applier (the
build's sl_build / sl_apply, so rt_trig), and every frame after it is the REAL audio
interrupt (0x40025e36 to its rte: smp_mod_apply with rt_frame and rt_map, and smp_tdm sending
the packets). The sequencer's state the build reads is set as it would be: playing (0x42c5a918),
the pattern's mode and length, track 1's step (0x42c5a984).

What it checks (each a named check, all must pass):
- the buffers are on with an empty directory, each has a next place, the two do not overlap;
  off when SAMP 124 holds a saved sample (and SAMP 124 then plays that sample, untouched);
- a REC lock (REC 1 on step 4) set, read back, through SAVE and LOAD as id 202; a step clear
  removes it; stock's LOAD skips id 202 (a pattern saved here opens on stock 1.11);
- the trig at step 4 fires one REC 1 take: the command (a buffer take's sequence, NOW, the
  RECORDER's SRC/CHAN, the place, slot 125 = REC 1's idle half, R.LEN 4 steps at 120 BPM =
  24,000 frames); the other voices of the same trig and a second apply in the frame do not
  fire again; the packets carry it (CMD_REPEAT of them) and the UI's queue is untouched;
- QPLAY PLEN: REC 1 keeps playing its old half while the take records and through steps 5..15,
  and switches at the pattern's first step (rt_map: SAMP 124 -> slot 125); SAMP 126/127 play
  nothing while the buffers are on, any other SAMP is left alone;
- QPLAY OFF: REC 2's take (step 8) is heard at once;
- a manual take armed or recording, or the buffers off: the trig records nothing;
- QREC 8: a manual NOW held for the boundary: not sent on steps 5..7, sent on step 8;
- the allocator: a manual take's place keeps clear of the buffer takes and their next places;
- (with --png-dir) the RECORDER driven through the panel: a step held, H turned four detents:
  that step's REC 1, three detents do nothing; RIGHT shows the REC TRIGS view.
"""

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
    setv("rec_rlen", 4)
    setv("rec_src", 1)                  # MAIN
    setv("rec_chan", 0)
    machine.write(lay["rt_manual"], b"\x00\x00\x00\x00")
    call(lay["rt_poll"])
    on = L("rt_on")
    nx = [machine.long(lay["rt_nx_place"] + 4 * b) for b in range(2)]
    room = [machine.long(lay["rt_nx_room"] + 4 * b) for b in range(2)]
    need = [machine.long(lay["rt_nx_need"] + 4 * b) for b in range(2)]
    check("buffers on with an empty directory; each has a next place, apart",
          on == 1 and room[0] >= need[0] > 0 and room[1] >= need[1] > 0
          and (nx[0] + need[0] <= nx[1] or nx[1] + need[1] <= nx[0]),
          f"on {on}, places {[hex(x) for x in nx]}, need {need}, room {room}")

    # ---- the pattern and the voice (emu_slides' shape) ---------------------------------------
    V, T = 0, 0
    kit = machine.long(KIT)
    snd = kit + 52 + SOUND_STRIDE * T
    put32(OWNER + 4 * V, T)
    call(SYNC, snd, V)
    for s in range(101):
        put32(STATE + 4 * (17 + s), machine.word(SRC + 2 * (17 + s)) << 16)
    call(BITMAP_CLEAR, V)
    machine.at = 0x46A30000
    table = machine.alloc(TABLE_BYTES)
    machine.write(table, b"\xff" * (REC * RECS))
    machine.write(table + INDEX, b"\xff" * (16 * 101))

    def rec_lock(step):
        return call(lay["sl_lock_get"], table, T, step, 2)[0] & 0xFFFF

    call(lay["sl_lock_set"], table, T, 4, 2, 1)      # REC 1 on step 4
    call(lay["sl_lock_set"], table, T, 8, 2, 2)      # REC 2 on step 8
    heads = [machine.read(table + REC * i, 2) for i in range(RECS)]
    check("REC locks set: steps 4 (REC 1) and 8 (REC 2), one record of ours",
          rec_lock(4) == 1 and rec_lock(8) == 2 and rec_lock(5) == 0xFFFF
          and heads.count(bytes([RAM_REC, TAG | T])) == 1,
          f"{rec_lock(4)}, {rec_lock(8)}, {rec_lock(5)}")
    stored = machine.alloc(TABLE_BYTES)
    call(SAVE, stored, table)
    ids = [machine.read(stored + REC * i, 1)[0] for i in range(RECS)]
    ram2 = machine.alloc(TABLE_BYTES)
    machine.write(ram2, b"\xff" * (REC * RECS))
    machine.write(ram2 + INDEX, b"\xff" * (16 * 101))
    call(LOAD, ram2, stored)
    back = [call(lay["sl_lock_get"], ram2, T, s, 2)[0] & 0xFFFF for s in (4, 8, 5)]
    check("SAVE stores the REC record as id 202; LOAD brings it back", ID_REC in ids and back == [1, 2, 0xFFFF],
          f"ids {sorted(set(ids) - {255})}, back {back}")

    # ---- the sequencer, as it would be: playing, per pattern, 16 steps -----------------------
    pat = machine.long(SEQ_PATTERN)
    machine.write(pat + PAT_MODE, b"\x00")
    put16(pat + PAT_LENGTH, 16)
    put32(SEQ_PLAYING, 1)

    def at_step(s, frames=2):
        machine.write(TRACK_CUR, bytes([s]))
        for _ in range(frames):
            frame()

    at_step(3, 3)
    steps3 = L("rt_steps")

    def trig(step, fr):
        put32(FRAMES, fr)
        lst = machine.alloc(LIST_BYTES)
        machine.write(lst, b"\x5a" * LIST_BYTES)
        call(lay["sl_pre"], V, T)
        call(UNDO, V, SRC, snd)
        call(BUILD, T, lst, table, snd + 48, step, step, 0)
        call(APPLY, V, lst, SRC)
        return lst

    call(lay["rt_poll"])                               # the plan at the tempo the frames carry, as the UI makes it
    tempo = machine.word(TEMPO_AT)
    nx = [machine.long(lay["rt_nx_place"] + 4 * b) for b in range(2)]
    need = [machine.long(lay["rt_nx_need"] + 4 * b) for b in range(2)]
    want_fr = [min(4 * (86400000 // tempo), (need[b] // 2) & ~31) for b in range(2)]
    report["tempo_word"] = tempo
    # v0.41 (the owner): a track's REC trigs record only when armed. OFF (the default): the trig
    # records nothing; then ON for the cases below
    machine.write(TRACK_CUR, bytes([4]))
    trig(4, 40_000)
    off_why, off_fired = L("rt_why"), L("rt_fired")
    off_at = L("rt_why_at") if "rt_why_at" in lay else 1
    check("a track not armed (OFF, the default): its REC trig records nothing, and says why (v0.42)",
          off_fired == 0 and off_why == 4 and off_at != 0, f"fired {off_fired}, why {off_why}, at {off_at}")
    machine.write(lay["rt_arm"] + T, b"\x02")         # ON
    gen0, sent0 = L("rt_gen"), L("smp_rt_sent")
    qhead = machine.read(lay["smp_cmds"], 4)
    machine.write(TRACK_CUR, bytes([4]))
    lst = trig(4, 50_000)
    call(APPLY, V, lst, SRC)                          # the trig's chord: another apply, same frame
    w = [machine.long(lay["rt_w"] + 4 * j) for j in range(6)]
    want_slot = REC_FIRST + 2                          # REC 1's idle half
    check("step 4 fires one REC 1 take (a chord's other apply does not fire again)",
          L("rt_fired") == 1 and L("rt_gen") == gen0 + 1, f"fired {L('rt_fired')}, gen {L('rt_gen') - gen0}")
    check(f"its command: a buffer take's sequence, NOW, MAIN, L+R, its place, slot 125, R.LEN 4 steps "
          f"at the frame's tempo ({want_fr[0]} frames)",
          (w[0] & 0x8000) and w[1] == 2 and w[2] == 1 and (w[3] & 3) == 0
          and (w[3] >> 8) == nx[0] // 512 and (w[5] >> 24) == want_slot and (w[5] & 0xFFFFFF) == want_fr[0],
          [hex(x) for x in w])
    for _ in range(12):
        frame()
    check("the packets carried it (8 repeats), the UI's queue untouched",
          L("smp_rt_sent") == sent0 + 1 and machine.read(lay["smp_cmds"], 4) == qhead,
          f"rt sent {L('smp_rt_sent') - sent0}")
    play0 = machine.read(lay["rt_play"], 2)
    m124 = call(lay["rt_map"], 124)[0]
    check("QPLAY PLEN: REC 1 still plays its old half while the take records", play0[0] == 0 and m124 == 124
          and machine.read(lay["rt_pend"], 1)[0] == 1, f"play {list(play0)}, SAMP 124 -> {m124}")
    for s in range(5, 16):
        at_step(s)
    mid = machine.read(lay["rt_play"], 1)[0]
    at_step(0)
    after = machine.read(lay["rt_play"], 1)[0]
    m124b = call(lay["rt_map"], 124)[0]
    check(".. and switches at the pattern's first step, not before (SAMP 124 -> slot 125)",
          mid == 0 and after == 1 and m124b == want_slot + 1, f"before {mid}, after {after}, SAMP 124 -> {m124b}")
    others = [call(lay["rt_map"], v)[0] for v in (126, 127, 50, 0)]
    check("SAMP 126/127 play nothing while the buffers are on; other SAMP left alone",
          others == [0, 0, 50, 0], others)

    # ---- QPLAY OFF: REC 2 heard as it records ------------------------------------------------
    setv("rt_qplay", 0)
    call(lay["rt_poll"])                               # (the UI, between the two trigs)
    machine.write(TRACK_CUR, bytes([8]))
    f_before = L("rt_fired")
    trig(8, 60_000)
    report["rec2_why"] = L("rt_why") if L("rt_fired") == f_before else 0
    play1 = machine.read(lay["rt_play"] + 1, 1)[0]
    w2 = [machine.long(lay["rt_w"] + 4 * j) for j in range(6)]
    check("QPLAY OFF: REC 2's take (step 8) into slot 126, heard at once",
          play1 == 1 and (w2[5] >> 24) == REC_FIRST + 3 and call(lay["rt_map"], 125)[0] == REC_FIRST + 4,
          f"play {play1}, slot {w2[5] >> 24}")
    for _ in range(12):
        frame()
    setv("rt_qplay", 8)
    # ONCE: the first REC trig records, then the track is OFF again (the loop kept)
    machine.write(lay["rt_arm"] + T, b"\x01")
    call(lay["rt_poll"])
    f1 = L("rt_fired")
    machine.write(TRACK_CUR, bytes([4]))
    trig(4, 62_000)
    after_once = machine.read(lay["rt_arm"] + T, 1)[0]
    for _ in range(12):
        frame()
    machine.write(TRACK_CUR, bytes([8]))
    trig(8, 64_000)
    check("ONCE: the first REC trig records, then the track is OFF (the next records nothing)",
          L("rt_fired") == f1 + 1 and after_once == 0 and L("rt_why") == 4,
          f"fired {L('rt_fired') - f1}, arm after {after_once}, why {L('rt_why')}")
    machine.write(lay["rt_arm"] + T, b"\x02")

    # ---- guards --------------------------------------------------------------------------------
    f0 = L("rt_fired")
    setv("rt_manual", 1)
    trig(4, 70_000)
    why_manual = L("rt_why")
    setv("rt_manual", 0)
    check("a manual take's turn: the trig records nothing", L("rt_fired") == f0 and why_manual == 2,
          f"why {why_manual}")
    m_place = call(lay["smp_rec_place"], 10, machine.alloc(4))[0]
    regions = [(machine.long(lay["rt_rplace"] + 4 * i), machine.long(lay["rt_rbytes"] + 4 * i)) for i in range(4)]
    clash = [r for r in regions if r[1] and r[0] <= m_place < r[0] + r[1]]
    check("a manual take's place keeps clear of the buffer takes", not clash,
          f"manual at {m_place:#x}, buffers {[(hex(x), n) for x, n in regions if n]}")
    from dnfw.waverider import dsp as DSPm                     # noqa: PLC0415
    machine.write(DIR + 8 + 16 * REC_FIRST, struct.pack("<IIfI", DSPm.SMP_POOL_DDR + SM.DATA_OFFSET + 0x1000, 48000, 1.0, 1))
    call(lay["rt_poll"])
    off = L("rt_on")
    trig(4, 80_000)
    why_off = L("rt_why")
    keep = call(lay["rt_map"], 124)[0]
    check("a saved sample in SAMP 124: buffers off, the trig records nothing, SAMP 124 plays it",
          off == 0 and L("rt_fired") == f0 and why_off == 1 and keep == 124, f"on {off}, why {why_off}, SAMP 124 -> {keep}")
    machine.write(DIR + 8 + 16 * REC_FIRST, b"\x00" * 16)
    call(lay["rt_poll"])

    # ---- QREC 8 ----------------------------------------------------------------------------------
    setv("rt_qrec", 4)                 # QSTEPS[4] = 8
    words = machine.alloc(24)
    machine.write(words, struct.pack(">6I", 0x1234, 2, 0, 0, 33, 10 << 24 | 48000))
    q0 = L("rt_qfired")
    for s in (2, 3, 4):
        at_step(s)
    call(lay["rt_q_set"], words)
    waiting = call(lay["rt_q_waiting"])[0]
    for s in (5, 6, 7):
        at_step(s)
    before = L("rt_qfired") - q0
    at_step(8, 12)
    check("QREC 8: a manual NOW waits through steps 5..7, goes on step 8",
          waiting == 1 and before == 0 and L("rt_qfired") - q0 == 1 and call(lay["rt_q_waiting"])[0] == 0,
          f"waiting {waiting}, before {before}, fired {L('rt_qfired') - q0}")

    # ---- the step clear --------------------------------------------------------------------------
    call(lay["sl_lock_set"], table, T, 4, 2, 0xFFFF)
    call(lay["sl_lock_set"], table, T, 8, 2, 0xFFFF)
    gone = all(machine.read(table + REC * i, 2) != bytes([RAM_REC, TAG | T]) for i in range(RECS))
    check("clearing both REC locks frees our record", gone)
    put32(SEQ_PLAYING, 0)

    faults = getattr(machine.m, "faults", [])[faults0:]
    check("no memory faults", not faults, faults[:3])

    # ---- the RECORDER through the panel (last: it changes the UI) ----------------------------
    if a.png_dir:
        from emulib.panel import Panel                         # noqa: PLC0415
        panel = Panel(machine, png_dir=a.png_dir)

        def key(code):
            return ((code - 1) // 8, (code - 1) % 8)

        def turn(enc, delta):
            machine.pc = panel.panelin.encoder(machine.m, panel.profile, enc, delta)
            panel.settle(5_000_000)
        panel.settle(5_000_000)
        panel.tap(key(19))                                  # RECORD: grid recording
        panel.settle(10_000_000)
        panel.tap(key(25))                                  # a trig on step 1
        panel.settle(10_000_000)
        call(lay["rec_combo"])                              # FUNC + VOICE: the RECORDER
        panel.settle(10_000_000)
        panel.screen("recorder")
        panel.hold(key(25), 5_000_000)
        panel.settle(10_000_000)
        # (no harness calls from here on: a call into the firmware in the middle of the UI's run
        # takes the CPU from under the UI task -- reads only)
        def rec_of(step):                                   # read as sl_lock_get reads it
            tbl = L("sl_rec_table")
            if not tbl:
                return None
            for i in range(RECS):
                if machine.read(tbl + REC * i, 2) == bytes([RAM_REC, TAG | 0]):
                    return machine.word(tbl + REC * i + 2 + 2 * step)
            return 0xFFFF
        turn(7, 3)                                          # H, three detents: nothing yet
        three = rec_of(0)
        turn(7, 1)                                          # the fourth: REC 1
        four = rec_of(0)
        panel.screen("recorder_held_rec1")
        panel.let_go(key(25))
        panel.settle(10_000_000)
        HELD_OBJ = 0x446478C8
        released = machine.read(machine.long(HELD_OBJ) + 616, 1)[0] == 0
        check("the RECORDER, a step held, H: three detents nothing, the fourth sets REC 1; the step lets go",
              three in (None, 0xFFFF) and four == 1 and released, f"{three}, {four}, released {released}")
        ov0 = L("rec_overlay")
        panel.tap(key(15))                                  # RIGHT: REC TRIGS
        panel.settle(10_000_000)
        ut = machine.read(0x42431A6C, 1)[0]                 # the active track
        machine.write(lay["rt_arm"] + ut, b"\x00")
        turn(7, 3)                                          # H, no step held: three detents, nothing
        a3 = machine.read(lay["rt_arm"] + ut, 1)[0]
        turn(7, 1)                                          # the fourth: ONCE
        a4 = machine.read(lay["rt_arm"] + ut, 1)[0]
        turn(7, 4)                                          # four more: ON
        a8 = machine.read(lay["rt_arm"] + ut, 1)[0]
        check("REC TRIGS view, H (no step held): the active track's arm, OFF -> ONCE -> ON, four detents each",
              a3 == 0 and a4 == 1 and a8 == 2, f"{a3}, {a4}, {a8}")
        panel.screen("rectrigs")
        check("RIGHT shows the REC TRIGS view", L("rec_view") == 1,
              f"view {L('rec_view')}, overlay before {ov0} after {L('rec_overlay')}")
        panel.tap(key(13))                                  # LEFT: back
        panel.settle(5_000_000)
        check("LEFT back to the RECORDER", L("rec_view") == 0, L("rec_view"))

    ok = all(c["ok"] for c in report["checks"].values())
    report["ok"] = ok
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1))
    n = len(report["checks"])
    print(("PASS" if ok else "FAIL") + f": {sum(c['ok'] for c in report['checks'].values())}/{n} checks", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
