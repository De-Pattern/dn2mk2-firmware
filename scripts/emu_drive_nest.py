#!/usr/bin/env python3
"""v0.40: +DRIVE's folders inside folders, driven on the ColdFire emulator (the gate's `drive`
step runs it beside the flat library's sequence).

takton (Alex): a sample pack with folders inside folders ("TRANCE STARTER PACK/KICKS/...",
".../LEADS/...") showed in +DRIVE as many top-level folders all reading "TRANCE STARTER PAC":
the import page sent each file's whole path as one flat folder name (cut at 31), and the
browser listed every folder at its top. v0.40 keeps a folder's parent in its record's byte 31
(csrc/sampler/lib.c, folder_tree) and the browser lists a folder's folders, then its samples.

A library put in the browser's RAM as lib.c reads it at power-on, three levels deep, with
names that look alike at different levels and an old import's flat folder beside it:

    INCOMING (0)                       INC ONE
    RECORDED (1)
    TRANCE STARTER PACK (2)
        KICKS (3)                      KICK 01, KICK 02
            808 (5)                    808 A, 808 B
            TRANCE STARTER PACK (6)    DEEP LOOK
        LEADS (4)                      LEAD 01
        EMPTY (9)
    TRANCE STARTER PACK/KICKS (7)      OLD KICK        (v0.39's import: one flat name)
    KICKS (8)                          TOP KICK

Then, as a person would: the top (5 folders, not 10: v0.39 lists every folder there), into
each level (YES), the path in the title head...tail, a sample's preview (FUNC + YES held),
a tick and LOAD TO PROJECT from three levels down, NO up a level each time onto the folder
left; MOVE SELECTED from the flat folder and MOVE HERE onto a folder two levels down; a
folder row's FUNC + YES ticks all it holds (6), SELECT ALL in a list only the list's own (2);
CREATE FOLDER inside a folder; DELETE on a folder with a folder inside it (asked first: all
its samples and folders go), and on the top-level folder: the rest of the library untouched.

    python scripts/emu_drive_nest.py --build DIR --snapshot SNAP --json OUT [--layout JSON]

--layout: the build's layout (default: this tree's src/dnfw/mods/waverider_code.json), so the
same sequence runs on an older build (v0.39's: it fails, the flattening).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.sampler import machines as SMx        # noqa: E402

LRAM = SMx.MIRROR + 0x100000
LDATA = 0x700000 + 1 + 256 + 4
FB_W, TITLE_W = 21, 22                          # (smp_page.c: FB_W, FB_TITLE_W)

FOLDERS = [  # (index, name, parent or None)
    (0, "INCOMING", None), (1, "RECORDED", None), (2, "TRANCE STARTER PACK", None),
    (3, "KICKS", 2), (4, "LEADS", 2), (5, "808", 3), (6, "TRANCE STARTER PACK", 3),
    (7, "TRANCE STARTER PACK/KICKS", None), (8, "KICKS", None), (9, "EMPTY", 2)]
SAMPLES = [("KICK 01", 3), ("KICK 02", 3), ("808 A", 5), ("808 B", 5), ("LEAD 01", 4),
           ("DEEP LOOK", 6), ("OLD KICK", 7), ("TOP KICK", 8), ("INC ONE", 0)]


def adl(b, s=1):
    a_, b_ = s & 0xFFFF, s >> 16
    for x in b:
        a_ = (a_ + x) % 65521
        b_ = (b_ + a_) % 65521
    return b_ << 16 | a_


def lent(start, frames, folder, name):
    e = bytearray(64)
    struct.pack_into("<III", e, 0, start, frames, 0x3F800000)
    e[12], e[13] = 1, folder
    struct.pack_into("<I", e, 20, (frames * 2 + 511) // 512)
    e[24:24 + len(name)] = name.encode()
    struct.pack_into("<I", e, 60, adl(bytes(e[:60])) ^ 0x4C494245)
    return bytes(e)


def folder_table():
    t = bytearray(64 * 32)
    for f, nm, par in FOLDERS:
        t[32 * f:32 * f + len(nm)] = nm.encode()
        if par is not None:
            t[32 * f + 31] = 0x80 | par         # (lib.c's tag; v0.39 reads the name only)
    return bytes(t)


def fit(n, w):
    """smp_page.c's fit_name, unselected: whole, or head...tail"""
    if len(n) <= w:
        return n
    head = (w - 3) // 2 + 1
    return n[:head] + "..." + n[len(n) - (w - 3 - head):]


def steps(lay):
    kit = 0x4210C08C
    snd0, M = kit + 52, SMx.MIRROR
    samp0 = snd0 + 0x6A

    def mem(va, n=4):
        return f"mem:{va:#x}:{n}"

    def samp_all(v):
        return [f"poke:{kit + 52 + 1163 * t + 0x6A:#x}:{v:02x}00" for t in range(16)]

    def turn(v):
        return [f"call:{lay['smp_quant']:#x}:sound0:{SMx.RECORDS[SMx.SAMP_REC][0]}:{v << 8:#x}",
                f"poke:{samp0:#x}:{v:02x}00", f"poke:{lay['smp_overlay_dirty']:#x}:00000001"]
    # the pool as the gate's 6f loads it (a sample track's SAMP list, then FUNC + YES)
    d = bytearray(0x1000)
    struct.pack_into("<II", d, 0, 0x31504D53, 4)
    for k, (fr, nm) in enumerate([(48000, "KICK"), (96000, "SHS_HAU"), (0, ""), (24000, "SNARE")]):
        if fr:
            struct.pack_into("<IIfI", d, 8 + 16 * k, 0x84001000 + 0x40000 * k, fr, 1.0, 1)
        d[0x808 + 8 * k:0x808 + 8 * k + len(nm)] = nm.encode()
    st = ["wait:2"] + [f"poke:{kit + 52 + 1163 * t + 0xDE:#x}:08" for t in range(16)] + samp_all(2)
    st += [f"poke:{M:#x}:{d[:0xC10].hex()}", f"poke:{lay['smp_dir_ok']:#x}:00000001"]
    st += ["wait:6", "tap:2", "wait:6", f"poke:{lay['smp_periods']:#x}:00000000",
           f"poke:{lay['smp_pos_at']:#x}:00000000", "wait:12", "tap:2", "wait:6"]
    idx = b"".join(lent(LDATA + 4 * k, 1000 + 10 * k, f, nm) for k, (nm, f) in enumerate(SAMPLES))
    st += [f"poke:{LRAM + 0x200:#x}:{idx.hex()}", f"poke:{LRAM + 0x200 + 2048 * 64:#x}:{folder_table().hex()}",
           f"poke:{lay['smp_lib_state']:#x}:00000002", f"call:{lay['smp_lib_refresh']:#x}"]
    st += samp_all(3) + [f"poke:{lay['smp_overlay_dirty']:#x}:00000001", "wait:10"] + turn(2) + ["wait:10"]

    fbc, fbm = lay["smp_fb_count"], lay["smp_fb_mark_count"]
    folder, cur, rt = lay["smp_fb_folder"], lay["smp_fb_cur"], lay["smp_fb_rowtext"]
    title = lay.get("smp_fb_titletext")

    def look(tag):
        """a point the facts read: the list's count, where it is, its rows and title, marks"""
        out = [f"call:{fbc:#x}", mem(folder), mem(cur), mem(rt, 144), f"call:{fbm:#x}", f"png:{tag}"]
        return out + ([mem(title, 24)] if title else [])
    FUNC, YESK = 17, 10
    s = list(st)
    s += ["press:17", "wait:2", "yes", "wait:2", "release:17", "wait:8", "up", "wait:4", "yes", "wait:8"]
    s += look("top")                                                            # 0: +DRIVE's top
    s += ["down", "wait:2", "down", "wait:2", "yes", "wait:8"] + look("tsp")    # 1: into TRANCE STARTER PACK
    s += ["yes", "wait:8"] + look("kicks")                                      # 2: into KICKS
    s += ["yes", "wait:8"] + look("808")                                        # 3: into 808
    s += [f"press:{FUNC}", "wait:2", f"press:{YESK}", "wait:6", mem(lay["smp_pv_state"]),
          f"release:{YESK}", "wait:2", f"release:{FUNC}", "wait:4", mem(lay["smp_pv_state"])]
    s += ["yes", "wait:4", "right", "wait:6", "yes", "wait:6", mem(lay["smp_lp_queued"])]  # tick, LOAD TO PROJ
    s += ["no", "wait:6"] + look("up1")                                         # 4: NO: KICKS, on 808
    s += ["no", "wait:6"] + look("up2")                                         # 5: NO: TSP, on KICKS
    s += ["no", "wait:6"] + look("up3")                                         # 6: NO: the top, on TSP
    # MOVE SELECTED from the old flat folder, MOVE HERE onto 808 (from KICKS' list)
    s += ["down", "wait:2", "yes", "wait:8", "yes", "wait:4", "right", "wait:4",
          "down", "wait:2", "down", "wait:2", "down", "wait:2", "yes", "wait:4",   # MOVE SELECTED (4th)
          "no", "wait:6", "up", "wait:2", "yes", "wait:6", "yes", "wait:6",         # top, TSP, KICKS (on 808)
          "right", "wait:4", "down", "wait:2", "down", "wait:2", "yes", "wait:6"]   # MOVE HERE (3rd)
    s += ["yes", "wait:8"] + look("moved")                                      # 7: 808 holds three
    s += ["no", "wait:6", "no", "wait:6"]                                       # TSP, on KICKS
    s += [f"press:{FUNC}", "wait:2", "yes", "wait:2", f"release:{FUNC}", "wait:6"] + look("fyes")   # 8: KICKS' row ticked
    s += [f"press:{FUNC}", "wait:2", "yes", "wait:2", f"release:{FUNC}", "wait:6"] + look("fyes2")  # 9: and unticked
    # into KICKS, onto KICK 01 (after its two folders), SELECT ALL: its own two
    s += ["yes", "wait:6", "down", "wait:2", "down", "wait:2", "right", "wait:4", "down", "wait:2",
          "down", "wait:2", "yes", "wait:6"] + look("selall")                   # 10
    s += ["right", "wait:4", "down", "wait:2", "down", "wait:2", "yes", "wait:6"] + look("clrall")  # 11: CLEAR ALL
    # CREATE FOLDER in KICKS (the cursor on a sample): "NEW", YES
    s += ["right", "wait:4"] + ["down", "wait:2"] * 6 + ["yes", "wait:8", "yes", "wait:10"] + look("made")   # 12
    # NO to TSP; DOWN to LEADS, RIGHT, DELETE (the 3rd of a folder's), asked, YES
    s += ["no", "wait:6", "down", "wait:2", "right", "wait:4", "down", "wait:2", "down", "wait:2", "yes", "wait:6",
          mem(lay["smp_fb_menu"]), "png:ask1", "yes", "wait:8"] + look("dleads")   # 13: LEADS gone
    # UP to KICKS (folders inside, nine samples under it now); DELETE, asked, YES
    s += ["up", "wait:2", "right", "wait:4", "down", "wait:2", "down", "wait:2", "yes", "wait:6",
          mem(lay["smp_fb_menu"]), "png:ask2", "yes", "wait:8"] + look("dkicks")   # 14: only EMPTY left
    s += ["no", "wait:6"] + look("top2")                                        # 15: the top, on TSP
    s += ["right", "wait:4", "down", "wait:2", "down", "wait:2", "yes", "wait:6", "yes", "wait:8"] + look("dtsp")  # 16
    s += ["down", "wait:2", "down", "wait:2", "yes", "wait:6"] + look("topkick")   # 17: the top-level KICKS
    s += ["no", "wait:6", "up", "wait:2", "yes", "wait:6"] + look("flat")        # 18: the old flat folder
    return s


def facts(r, lay):
    m = r["memory"]
    calls = [c.get("d0") for c in r.get("direct_calls", [])]
    d0 = [int(str(x), 0) if x is not None else None for x in calls]
    d0 = d0[2:]                                 # (the refresh's, the turn's smp_quant)

    def reads(va):
        return [m[k] for k in m if k == hex(va) or k.startswith(hex(va) + "@")]

    def i32(h):
        return int.from_bytes(bytes.fromhex(h), "big", signed=True)
    fold = [i32(h) for h in reads(lay["smp_fb_folder"])]
    cur = [i32(h) for h in reads(lay["smp_fb_cur"])]
    rows = []
    for h in reads(lay["smp_fb_rowtext"]):
        b = bytes.fromhex(h)
        rows.append([b[24 * j:24 * j + 24].split(b"\0")[0].decode("ascii", "replace") for j in range(6)])
    titles = [bytes.fromhex(h).split(b"\0")[0].decode("ascii", "replace")
              for h in reads(lay["smp_fb_titletext"])] if "smp_fb_titletext" in lay else []
    pv = [i32(h) for h in reads(lay["smp_pv_state"])]
    menu = [i32(h) for h in reads(lay["smp_fb_menu"])]
    count = d0[0::2]
    marks = d0[1::2]
    L = ["top", "tsp", "kicks", "808", "up1", "up2", "up3", "moved", "fyes", "fyes2", "selall", "clrall",
         "made", "dleads", "dkicks", "top2", "dtsp", "topkick", "flat"]
    at = {n: i for i, n in enumerate(L)}

    def g(seq, n, k=None):
        i = at[n]
        v = seq[i] if i < len(seq) else None
        return v if k is None or v is None else (v[k] if k < len(v) else None)
    T = "TRANCE STARTER PACK"
    want_top = ["INCOMING", "RECORDED", T, fit(T + "/KICKS", FB_W), "KICKS"]
    f = {
        "the top: five folders (the pack, the old flat one, look-alike KICKS), not every folder":
            g(count, "top") == 5 and g(rows, "top") is not None and g(rows, "top")[:5] == want_top,
        "YES: the pack's three folders (KICKS, LEADS, EMPTY), not empty":
            g(count, "tsp") == 3 and g(fold, "tsp") == 2 and g(rows, "tsp")[:3] == ["KICKS", "LEADS", "EMPTY"],
        "its title the pack's name": g(titles, "tsp") == T,
        "YES: KICKS, its two folders then its two samples (a look-alike pack name one level down)":
            g(count, "kicks") == 4 and g(fold, "kicks") == 3 and g(rows, "kicks")[:4] == ["808", T, "KICK 01", "KICK 02"],
        "its title the path, head...tail": g(titles, "kicks") == fit(T + "/KICKS", TITLE_W),
        "YES: 808, three levels down: its two samples, the path in the title":
            g(count, "808") == 2 and g(fold, "808") == 5 and g(rows, "808")[:2] == ["808 A", "808 B"]
            and g(titles, "808") == fit(T + "/KICKS/808", TITLE_W),
        "FUNC + YES held previews it there; let go, it stops": len(pv) >= 2 and pv[0] in (1, 2, 3) and pv[1] == 0,
        "a tick there, LOAD TO PROJECT queues it": bool(reads(lay["smp_lp_queued"]))
        and i32(reads(lay["smp_lp_queued"])[0]) == 1,
        "NO: up to KICKS, on 808": g(fold, "up1") == 3 and g(cur, "up1") == 0,
        "NO: up to the pack, on KICKS": g(fold, "up2") == 2 and g(cur, "up2") == 0,
        "NO: up to the top, on the pack": g(fold, "up3") == -1 and g(cur, "up3") == 2 and g(count, "up3") == 5,
        "MOVE SELECTED from the old flat folder, MOVE HERE on 808 (two levels down): 808 holds three":
            g(count, "moved") == 3 and g(fold, "moved") == 5 and "OLD KICK" in g(rows, "moved"),
        "FUNC + YES on KICKS' row ticks all it holds, its folders' too (6)": g(marks, "fyes") == 6,
        "again: none": g(marks, "fyes2") == 0,
        "SELECT ALL in KICKS' list: its own two": g(marks, "selall") == 2 and g(fold, "selall") == 3,
        "CLEAR ALL: none": g(marks, "clrall") == 0,
        "CREATE FOLDER in KICKS: NEW, inside it (three folders, two samples)":
            g(count, "made") == 5 and g(fold, "made") == 3 and "NEW" in g(rows, "made")[:3],
        "DELETE on LEADS, asked first: LEADS gone (KICKS, EMPTY left)":
            len(menu) >= 2 and menu[0] == 2 and g(count, "dleads") == 2 and g(rows, "dleads")[:2] == ["KICKS", "EMPTY"],
        "DELETE on KICKS (folders inside, any depth), asked: only EMPTY left":
            menu[1] == 2 and g(count, "dkicks") == 1 and g(rows, "dkicks")[:1] == ["EMPTY"] and g(fold, "dkicks") == 2,
        "NO: the top as it was": g(count, "top2") == 5 and g(cur, "top2") == 2,
        "DELETE on the pack: it and EMPTY gone; the rest untouched":
            g(count, "dtsp") == 4 and g(rows, "dtsp")[:4] == ["INCOMING", "RECORDED", fit(T + "/KICKS", FB_W), "KICKS"],
        "the top-level KICKS (a look-alike) keeps its sample": g(count, "topkick") == 1 and g(rows, "topkick")[:1] == ["TOP KICK"],
        "the old flat folder, emptied by MOVE, still there": g(count, "flat") == 0 and g(fold, "flat") == 7,
    }
    shots = [pathlib.Path(p).read_bytes() for p in r.get("screens", {}).values() if pathlib.Path(p).exists()]
    f["every step drawn"] = len(shots) >= 20 and len(set(shots)) >= 15
    return f, {"count": count, "marks": marks, "folder": fold, "cur": cur, "titles": titles, "pv": pv,
               "menu": menu, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--layout", default=str(ROOT / "src/dnfw/mods/waverider_code.json"))
    ap.add_argument("--json", required=True)
    ap.add_argument("--png-dir", required=True)
    a = ap.parse_args()
    lay = json.loads(pathlib.Path(a.layout).read_text())["layout"]
    raw = pathlib.Path(a.json).with_suffix(".emu.json")
    cmd = [sys.executable, "-u", str(HERE / "emu_waverider_menu.py"), "--root", str(ROOT), "--build", a.build,
           "--snapshot", a.snapshot, "--steps", ",".join(steps(lay)), "--png-dir", a.png_dir, "--json", str(raw)]
    rc = subprocess.run(cmd, env=os.environ).returncode
    if rc != 0 or not raw.exists():
        print(f"drive nest: the emulator run failed (rc {rc})")
        pathlib.Path(a.json).write_text(json.dumps({"ok": False, "rc": rc}) + "\n")
        return 1
    f, seen = facts(json.loads(raw.read_text()), lay)
    ok = all(bool(v) for v in f.values())
    pathlib.Path(a.json).write_text(json.dumps({"ok": ok, "facts": f, "seen": seen}, indent=1) + "\n")
    for k, v in f.items():
        print(f"  [{'ok ' if v else 'BAD'}] {k}")
    print(f"drive nest: {json.dumps({'ok': ok})}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
