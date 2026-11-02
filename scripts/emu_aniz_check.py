"""v0.37: the start-up animation, every frame, under the emulator.

    DT2_SECTIONS=../sec111 ../digikit/.venv/bin/python -u scripts/emu_aniz_check.py BUILD.syx

The boot from reset (`emu_boot_check.py --aniz`) reaches the intro and shows its first
frame, but under `dspboot` the intro's timers do not run on, so the intro stops there
(stock too: one frame in 450M). This check starts instead from digikit's 1.11 snapshot
taken just before the intro (`boot400M`, as `film_bootscreen.py` did), with the intro's
timers as `guirun.py` runs them, and installs the BUILD's own bytes as its loader would
have: the intro hook at INTRO_VA (8 bytes) and the whole appended area
(`platform.runtime`: its header, every CODE chunk at its load address with its BSS, every
data chunk). Nothing else of the build is written: the snapshot is stock past boot.

At each `aniz_show` the decoded frame (zst + 16, 1 KB) is compared with s!Rwa²'s frame d3
(`dnfw.bootanim.images()`, his own frames since v0.39). Passes when every frame was shown,
none wrong, in order (never going back), and the intro ran to its end. v0.39: and at each
`aniz_drawn` the source bitmap the panel is drawn from must be `dnfw.bootanim.shown()`: his
frame, with the mod's version label ORed over the last frame only.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIGIKIT = pathlib.Path("/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(DIGIKIT / "tools"))
sys.path.insert(0, str(DIGIKIT))

from dnfw import bootanim                                     # noqa: E402
from dnfw.cli.files import read_image                         # noqa: E402
from dnfw.firmware.load import load                           # noqa: E402
from dnfw.mods import bootscreen, platform                    # noqa: E402

SNAP = DIGIKIT / "out/snapshots/dn2-1.11/boot400M.snap"
SYX = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
if "DT2_SECTIONS" in os.environ:          # the stock MAIN OS the emulator runs (not the .aplib)
    os.environ.setdefault("DT2_MAIN_IMG", os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"))
LIMIT = 80_000_000            # the intro's 175 frames come at about four per 1M


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("--limit", type=int, default=LIMIT)
    a = ap.parse_args()

    content = load(read_image(a.build)).container.find(3).unpack()
    spec = bootscreen.SPEC
    va = spec["intro_va"]
    hook = bytes(content[va - bootscreen.BASE:va - bootscreen.BASE + 8])
    writes = [(va, hook)] + platform.runtime(content)
    expect = bootanim.images()
    drawn = bootanim.shown()
    res = {"shown": 0, "frames": [], "wrong": [], "stamp": 0, "written": [], "skipped": [], "counters": [],
           "drawn": 0, "drawn_wrong": [], "labelled": set()}

    import guirun                                               # digikit
    from unicorn import UC_HOOK_CODE
    from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D3

    real_build = guirun.build

    def build(*args, **kw):
        out = real_build(*args, **kw)
        m = out[0]
        # the intro hook, the area's header, the stamp (and its BSS, zst) and ANIZ must go
        # in; another chunk at an address the snapshot never mapped is left out (the intro
        # never reaches it) and said so
        need = {va, platform.RUNTIME_VA, spec["stamp"]}
        # the snapshot maps only the 1 MB pages stock had touched; the area's pages above
        # stock's BSS are mapped here, as RAM (the unit's DDR runs to 0x48000000)
        have = [(b, e) for b, e, _ in m.uc.mem_regions()]
        for addr, data in writes:
            for page in range(addr & ~0xFFFFF, addr + len(data), 0x100000):
                if page < 0x48000000 and not any(b <= page <= e for b, e in have):
                    m.uc.mem_map(page, 0x100000)
                    have.append((page, page + 0xFFFFF))
        for addr, data in writes:
            try:
                m.uc.mem_write(addr, bytes(data))
                res["written"].append(addr)
            except Exception as e:                              # noqa: BLE001
                if addr in need:
                    raise
                res["skipped"].append(f"{addr:#x} ({len(data)} B): {e}")

        def at_show(uc, address, size, user):
            k = uc.reg_read(UC_M68K_REG_D3)
            got = bytes(uc.mem_read(spec["zst"] + 16, 1024))
            res["shown"] += 1
            res["frames"].append(k)
            if not (0 <= k < len(expect)) or got != expect[k]:
                res["wrong"].append(k)

        def at_stamp(uc, address, size, user):
            res["stamp"] += 1                                   # its first argument: the intro frame
            sp = uc.reg_read(UC_M68K_REG_A7)
            res["counters"].append(int.from_bytes(uc.mem_read(sp + 4, 4), "big"))
        m.uc.hook_add(UC_HOOK_CODE, at_show, begin=spec["aniz_show"], end=spec["aniz_show"])

        def at_drawn(uc, address, size, user):
            k = uc.reg_read(UC_M68K_REG_D3)
            src = int.from_bytes(uc.mem_read(spec["source_data_ptr"], 4), "big")
            got = bytes(uc.mem_read(src, 1024))
            res["drawn"] += 1
            if got != expect[k]:
                res["labelled"].add(k)
            if not (0 <= k < len(drawn)) or got != drawn[k]:
                res["drawn_wrong"].append(k)
        m.uc.hook_add(UC_HOOK_CODE, at_drawn, begin=spec["aniz_drawn"], end=spec["aniz_drawn"])
        m.uc.hook_add(UC_HOOK_CODE, at_stamp, begin=spec["stamp"], end=spec["stamp"])
        return out

    guirun.build = build
    sys.argv = ["guirun", str(SNAP), "--syx", str(SYX),
                "--limit", str(a.limit)]
    try:
        guirun.main()
    except SystemExit as e:
        if e.code not in (None, 0):
            print(f"guirun exited {e.code}")

    fr = res["frames"]
    distinct = sorted(set(fr))
    backwards = [i for i in range(1, len(fr)) if fr[i] < fr[i - 1]]
    print(f"\n  wrote {len(res['written'])} of {len(writes)} range(s): the intro hook and the appended area")
    for line in res["skipped"]:
        print(f"    not mapped in the snapshot, left out: {line}")
    c = res["counters"]
    print(f"  the intro called the stamp {res['stamp']} time(s), intro frames "
          f"{c[0] if c else None}..{c[-1] if c else None}")
    print(f"  start-up animation: {res['shown']} frame(s) shown, {len(distinct)} of {len(expect)} "
          f"distinct, {len(res['wrong'])} not his, {len(backwards)} going back")
    # the intro to its last frame (the snapshot may come after its first call or two)
    print(f"  shown on the panel: {res['drawn']} time(s), {len(res['drawn_wrong'])} wrong; the label "
          f"({bootanim.label_text()}) over frame(s) {sorted(res['labelled'])} (the last only: {len(expect) - 1})")
    ok = (bool(c) and c[-1] >= bootanim.INTRO_FRAMES - 1 and distinct == list(range(len(expect)))
          and not res["wrong"] and not backwards and res["drawn"] >= res["shown"] and not res["drawn_wrong"]
          and sorted(res["labelled"]) == [len(expect) - 1])
    if not ok:
        missing = [k for k in range(len(expect)) if k not in set(fr)]
        print(f"  the animation is wrong or incomplete (wrong: {sorted(set(res['wrong']))[:10]}, "
              f"missing: {missing[:10]})\n\n  DO NOT FLASH.")
        return 1
    print("  every frame of the animation, his frames bit for bit, in order: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
