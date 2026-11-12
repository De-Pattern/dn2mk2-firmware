"""v0.48 (owner, 2026-11-09: no text outside its place; every value of a control at one place and
size): the RECORDER drawn in every state its centre box has, and R.LEN through MAX and its step
counts, on the real screen (the emulator's untorn frame). Every lit pixel between the SRC column
and the THRES column is the box's dotted border (the same in every state) or inside the box; the
gutters either side stay dark; R.LEN's values share one line (the same top and bottom row) inside
their 32-pixel column."""

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
from emulib import bounded                                      # noqa: E402
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
        bounded.run(uc, machine.m, fn, until if until is not None else SENTINEL, limit)
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

    T = 0
    kit = machine.long(KIT)
    machine.write(kit + 52 + SOUND_STRIDE * T + 0xDE, bytes([8]))   # an ONESHOT track: the plain RECORDER
    machine.write(SM.MIRROR + 8, b"\x00" * 16 * SM.POOL_SLOTS)
    setv("smp_dir_ok", 1)
    from emulib.panel import Panel                             # noqa: PLC0415
    panel = Panel(machine, png_dir=a.png_dir or "out/rectext")
    panel.settle(5_000_000)
    put32(lay["rec_overlay"], 1)
    put32(lay["rec_phase"], 0)

    def show(name, heard=True, **vals):
        for k, v in vals.items():
            put32(lay[k], v)
        for _ in range(6):                                 # (rec_poll leaves these be: no DSP here)
            if heard:
                put32(lay["rec_heard"], machine.long(FRAMES) + 1)
            put32(lay["smp_overlay_dirty"], 1)
            panel.settle(2_000_000)
        panel.screen(name)
        return set(panel.panel.lit(bytes(panel.capture.frames[-1]))) if panel.capture.frames else set()

    # the box (smp_page.c rec_screen_draw: x 29..97, y 22..48, drawn bottom-up): screen rows 15..41
    BX0, BX1, R0, R1 = 29, 97, 63 - 48, 63 - 22

    def on_border(x, y):
        return (x in (BX0, BX1) and R0 <= y <= R1) or (y in (R0, R1) and BX0 <= x <= BX1)

    big = 999 * 96000
    states = [
        ("no_dsp", dict(heard=False, rec_state=0, rec_link=0, rec_room=big)),
        ("no_link", dict(rec_state=0, rec_link=-1, rec_room=big)),
        ("no_room", dict(rec_state=0, rec_link=0, rec_room=0, rec_dest=0)),
        ("armed_thres", dict(rec_state=1, rec_link=0, rec_rstrt=0)),
        ("armed_play", dict(rec_state=1, rec_link=0, rec_rstrt=1)),
        ("ready", dict(rec_state=0, rec_link=0, rec_room=big, as_done=-1, rec_saved_slot=-1)),
        ("on_trk", dict(rec_state=0, rec_link=0, rec_room=big, as_done=15, rec_saved_slot=122)),
        ("again_full", dict(rec_state=3, rec_link=0, rec_room=big, as_done=-1, rec_saved_slot=122, smp_rs_last=2)),
        ("again_saved", dict(rec_state=3, rec_link=0, rec_room=big, as_done=-1, rec_saved_slot=122, smp_rs_last=1)),
    ]
    border0, bad = None, {}
    for name, v in states:
        heard = v.pop("heard", True)
        px = show("rec_" + name, heard, **v)
        border = {p for p in px if on_border(*p)}
        if border0 is None:
            border0 = border
        out = sorted(p for p in px if 27 <= p[0] <= 100 and R0 - 1 <= p[1] <= R1 + 1
                     and not on_border(*p) and not (BX0 < p[0] < BX1 and R0 < p[1] < R1))
        if out or border != border0:
            bad[name] = (out[:6], len(border ^ border0))
    check("every centre-box message of the RECORDER stays inside its box (no pixel in the gutters, "
          "the dotted border untouched) in all " + str(len(states)) + " states", not bad, bad)

    # R.LEN (x 47, its 32-pixel column 31..62): MAX and step counts on one line
    rows, cols = {}, {}
    for rl in (0, 1, 16, 64, 128):
        px = show(f"rlen_{rl}", True, rec_state=0, rec_link=0, rec_room=big, rec_rlen=rl)
        val = [p for p in px if 28 <= p[0] <= 66 and 44 <= p[1] <= 56]
        rows[rl] = (min(p[1] for p in val), max(p[1] for p in val)) if val else None
        cols[rl] = (min(p[0] for p in val), max(p[0] for p in val)) if val else None
    one_line = len(set(rows.values())) == 1 and None not in rows.values()
    inside = all(c and 31 <= c[0] and c[1] <= 62 for c in cols.values())
    check("R.LEN's MAX and its step counts on one line, the same rows, inside their column", one_line and inside,
          f"rows {rows}, cols {cols}")
    put32(lay["rec_rlen"], 0)
    put32(lay["rec_overlay"], 0)

    faults = getattr(machine.m, "faults", [])[faults0:]
    check("no memory faults", not faults, faults[:3])
    ok = all(c["ok"] for c in report["checks"].values())
    report["ok"] = ok
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(report, indent=1))
    n = len(report["checks"])
    print(("PASS" if ok else "FAIL") + f": {sum(c['ok'] for c in report['checks'].values())}/{n} checks", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
