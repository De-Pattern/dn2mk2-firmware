"""v0.32: the SHARC+ hardware rules no emulator sees, on a build's DSP code.

    python scripts/gate_hwrules.py STOCK.syx BUILD.syx SKILL_DIR

complex-ping's digitone-2-modding-skill (MIT, github.com/complex-ping/digitone-2-modding-skill)
ships `hwrules.py`: hardware-loop shape (the last 11 instructions 48-bit), loop ends, CALL
near a loop's end, branch spacing and the 12-instruction window after a branch, and same-DAG
loads and stores -- rules each of which silenced or crashed a unit once while both emulators
ran the code "fine" (its references/sharc.md). This runs it on every instruction of ours in
the build's section 7 (PERC, the sample machines, the recorder's preview, PING, the stubs)
and around each patch of the stock's code, and reports only what the stock image does not
already have at the same place. Exit 0 and PASS, or 1 and the violations.

SKILL_DIR is a checkout of that repository (its scripts are run from there, never copied).
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def section7(path: pathlib.Path) -> bytes:
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(path)).container.find(7).unpack()


def ranges() -> list[tuple[int, int, str]]:
    """(sw from, sw to, what) of our code and of a window round each patch of the stock's"""
    from dnfw.waverider import dsp
    obj = dsp.objects()
    out = [(dsp.PERC_SW, dsp.PERC_SW + len(obj["perc"]) // 2, "perc.asm"),
           (dsp.SMP_SW, dsp.SMP_SW + len(obj["smp"]) // 2, "smp.asm"),
           (dsp.PVMIX_SW, dsp.PVMIX_SW + len(dsp.pvmix_object()) // 2, "pvmix.asm"),
           (dsp.PING_SW, dsp.PING_SW + len(obj["ping"]) // 2, "ping.asm"),
           (dsp.IDLE_SW, dsp.IDLE_SW + len(obj["idle_load"]) // 2, "idle_load.asm"),
           (dsp.COUNT_SW, dsp.COUNT_SW + len(obj["block_count"]) // 2, "block_count.asm"),
           (dsp.EMARK_SW, dsp.EMARK_SW + len(obj["entry_mark"]) // 2, "entry_mark.asm")]
    for name, sw in (("the entry JUMP", dsp.ENTRY_SW), ("the machine lookup's base", dsp.LOOKUP_SITE_SW),
                     ("the idle loop's back edge", dsp.IDLE_SITE_SW), ("the handler's call", dsp.CALL_SITE_SW),
                     ("the driver's call of the mix", dsp.PVMIX_SITE_SW)):
        out.append((sw - 48, sw + 48, f"round {name}"))
    return out


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    stock_syx, build_syx, skill = pathlib.Path(argv[0]), pathlib.Path(argv[1]), pathlib.Path(argv[2])
    scripts = skill / "skills" / "digitone-2-modding-skill" / "scripts"
    if not (scripts / "hwrules.py").exists():
        print(f"FAIL: no hwrules.py under {skill} (clone github.com/complex-ping/digitone-2-modding-skill)")
        return 1
    with tempfile.TemporaryDirectory() as ws:
        wsp = pathlib.Path(ws)
        (wsp / "repos").mkdir()
        (wsp / "repos" / "dnfw").symlink_to(ROOT)          # its scripts import dnfw from here
        (wsp / "extracted").mkdir()
        stock7, build7 = section7(stock_syx), section7(build_syx)
        (wsp / "extracted" / "section_7.bin").write_bytes(stock7)
        os.environ["DN2_WORKSPACE"] = ws
        sys.path.insert(0, str(scripts))
        import dn2frame as D                                # noqa: E402  (the skill's)
        import hwrules                                      # noqa: E402
        img, base = D.image_from_sec7(build7), D.image_from_sec7(stock7)
        rs = ranges()
        bad = hwrules.new_violations(img, base, [(a, b) for a, b, _ in rs])
        n = sum(1 for a, b, _ in rs for i in img.linear(a, end=b, stop_invalid=False) if i.sw < b)
    if bad:
        print(f"FAIL: {len(bad)} hardware-rule violation(s) the stock does not have:")
        for r, a, b, t in bad[:40]:
            print(f"  {r:10s} {a:#08x} {b if isinstance(b, str) else hex(b)}  {t}")
        return 1
    print(f"PASS: {n} instructions in {len(rs)} ranges (ours and round each patch): no hardware-rule "
          f"violation the stock does not have (loop shape and ends, branch spacing, same-DAG)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
