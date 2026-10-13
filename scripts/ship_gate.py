"""Every safety gate, on the exact .syx you will flash. Nothing is cleared without it.

    DT2_SECTIONS=/path/to/stock-1.11-sections \\
    python scripts/ship_gate.py Digitone_II_OS1.11.syx build.syx \\
        [--venv ../digikit/.venv/bin/python] [--digikit-sharc ../digikit-wt-sharcemu]

**The owner's rule (2026-10-11): every check, on every build, every time. No
exceptions, no "it's only a small change".** This script is that rule as code, so it
does not depend on anyone remembering it. It runs, in order, and stops at the first
failure:

1. **preflight** (`dnfw.safety`): stock input is OS 1.11 byte for byte; bootstrap,
   updater, metadata and Outbox untouched; signature valid; DSP program within the
   uploader's real limit.
2. **DSP identity**: if section 7 changed, it must be *exactly*
   `dnfw.waverider.dsp.section7(stock)` -- the image the SHARC gate runs. Otherwise the
   SHARC gate would be testing a different program from the one being flashed.
3. **SHARC runner** (`sharc_waverider_m5.py`, if section 7 changed): Waverider
   bit-exact, and types 0-4 bit-identical to stock.
4. **ColdFire instruction set** (`check_coldfire.py`): every `CODE` chunk the loader
   runs has no scale-8 addressing; and every hit in MAIN OS against stock lies past
   stock's end *and* outside every `CODE` chunk (i.e. in data that never executes).
5. **boot from reset** (`emu_boot_check.py`): boots and draws its UI, no fault.
6. **engine + LOAD/SAVE** (`emu_boot_engine.py`): the evaluator runs clean under the
   real loader; CODE chunks intact; machine types survive a SAVE/LOAD round trip.
7. **unit tests** (`pytest -m "not slow"` on the safety, mod and Waverider tests).

Only if all pass does it write `BUILD.gate.json` beside the build (the build's
sha256, each gate's result, the date) and print `CLEARED TO FLASH`. Anything else
prints `DO NOT FLASH` and exits non-zero. A build changed after its gate needs a new
gate: the record names the sha256 it cleared.

It takes about an hour, mostly the two ColdFire emulator runs. Run it unattended.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw import safety                                    # noqa: E402
from dnfw.cli.files import read_image                      # noqa: E402
from dnfw.firmware.load import load                        # noqa: E402
from dnfw.mods import platform                             # noqa: E402
from dnfw.patch import area                                # noqa: E402
from dnfw.waverider import dsp, wave                       # noqa: E402

MAIN_BASE = 0x40000400
# CODE chunks that hold only data, reached through a pointer and never jumped to.
# Each is listed by name, on purpose: a chunk is assumed to execute unless it is here.
DATA_ONLY = {wave.SPANS_LOAD: "Waverider's wave-display bytes (wave.SPANS_LOAD), never executed"}


def code_ranges() -> dict[int, list[tuple[int, int]]]:
    """CODE chunks whose code and data the build itself has recorded: {load: [(start,
    end)]}, the ranges that execute. Waverider's page chunk is assembly (is_wr up to its
    label table) and then C (C_LOAD up to __text_end); between and after them are its
    descriptors, strings, rodata and data, which a scan would misread as instructions
    (W2: a descriptor's two pointers read as `and.l %d0,%a4@(70,%d4:w:8)`). Any other
    CODE chunk is checked whole."""
    lay = json.loads((ROOT / "src/dnfw/mods/waverider_code.json").read_text())["layout"]
    out = {lay["is_wr"]: [(lay["is_wr"], lay["labels"]), (lay["c_load"], lay["c_text_end"])]}
    if "ping_slot" in lay:      # PING's chunk: its shims, then its list, names and table
        out[lay["ping_slot"]] = [(lay["ping_slot"], lay["ping_code_end"])]
    return out
TESTS = ["test/test_safety.py", "test/test_mods_list.py", "test/test_mods_platform.py",
         "test/test_waverider_mod.py", "test/test_waverider_dsp.py",
         "test/test_waverider_pages.py", "test/test_ping_coldfire.py", "test/test_ping_live.py"]
HIT = re.compile(r"^\s+([0-9a-f]{8}):", re.M)


class Stop(Exception):
    pass


def run(name, cmd, log_dir, env=None, cwd=ROOT):
    """Run CMD, log its output to LOG_DIR/NAME.log, -> (rc, output)."""
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    t = time.time()
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env={**os.environ, **(env or {})},
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (log_dir / f"{name}.log").write_text(r.stdout)
    print(f"    rc {r.returncode}, {round(time.time() - t)} s, log {log_dir / (name + '.log')}",
          flush=True)
    return r.returncode, r.stdout


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stock", type=pathlib.Path, help="Elektron's Digitone_II_OS1.11.syx")
    p.add_argument("build", type=pathlib.Path, help="the exact .syx that will be flashed")
    p.add_argument("--venv", default=str(ROOT.parent / "digikit/.venv/bin/python"),
                   help="python with digikit's emulator deps (unicorn)")
    p.add_argument("--digikit-sharc", default=os.environ.get(
        "DNFW_DIGIKIT_SHARC", str(ROOT.parent / "digikit-wt-sharcemu")))
    a = p.parse_args()

    if "DT2_SECTIONS" not in os.environ:
        print("DT2_SECTIONS must point at stock 1.11's extracted sections.\n\nDO NOT FLASH.")
        return 2

    build_bytes = read_image(a.build)
    sha = hashlib.sha256(a.build.read_bytes()).hexdigest()
    work = pathlib.Path(tempfile.mkdtemp(prefix="ship_gate_", dir=ROOT / "out"
                                         if (ROOT / "out").is_dir() else None))
    logs = work / "logs"
    logs.mkdir()
    print(f"ship gate: {a.build.name}\n  sha256 {sha}\n  work {work}\n", flush=True)
    results: dict[str, str] = {}

    def gate(name, ok, detail):
        results[name] = ("PASS: " if ok else "FAIL: ") + detail
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}\n", flush=True)
        if not ok:
            raise Stop(name)

    try:
        # 1. preflight
        stock = load(read_image(a.stock))
        ok, text = safety.report(safety.preflight(stock, build_bytes))
        (logs / "preflight.log").write_text(text)
        gate("preflight", ok, "bootstrap/updater/meta/Outbox untouched, signature, DSP size"
             if ok else text[-600:])

        built = load(build_bytes)
        sec3 = built.container.find(3).unpack()
        stock3 = stock.container.find(3).unpack()
        stock7 = stock.container.find(7).unpack()
        sec7 = built.container.find(7).unpack()
        bdir = work / "build"
        bdir.mkdir()
        (bdir / "section_3_MAIN_OS.bin").write_bytes(sec3)
        (work / "stock_section_3_MAIN_OS.bin").write_bytes(stock3)

        # 2 + 3. the DSP program
        dsp_changed = sec7 != stock7
        if dsp_changed:
            same = sec7 == dsp.section7(stock7)
            gate("DSP identity", same, "section 7 is exactly dsp.section7(stock), the image "
                 "the SHARC gate runs" if same else "section 7 is not what the SHARC gate "
                 "tests; its result would not apply to this file")
            rc, out = run("sharc_m5", [sys.executable, "scripts/sharc_waverider_m5.py",
                                       "--image", a.stock, "--digikit", a.digikit_sharc], logs)
            gate("SHARC runner", rc == 0, "all steps PASS, incl. types 0-4 bit-identical "
                 "to stock" if rc == 0 else out[-800:])
        else:
            results["DSP identity"] = results["SHARC runner"] = "n/a: section 7 is stock"

        # 4. ColdFire instruction set
        # (va, offset of its image in sec3, length) for every CODE chunk, from the
        # area's own directory -- the same table the loader reads.
        code_chunks = []
        if len(sec3) > platform.STOCK_LENGTH:
            blob = sec3[platform.STOCK_LENGTH:]
            total, count = struct.unpack_from(">II", blob, 4)
            for i in range(count):
                cid = blob[12 + 12 * i:16 + 12 * i]
                off, n = struct.unpack_from(">II", blob, 16 + 12 * i)
                if cid != area.CODE:
                    continue
                chunk = area.CodeChunk.unpack(blob[off:off + n])
                code_chunks.append((chunk.load, platform.STOCK_LENGTH + off + 16,
                                    len(chunk.image), chunk.image))
        for va, at, n, image in code_chunks:
            if va in DATA_ONLY:
                results[f"ColdFire: chunk {va:#x}"] = f"n/a: {DATA_ONLY[va]}"
                print(f"[n/a ] ColdFire: chunk {va:#x}: {DATA_ONLY[va]}\n", flush=True)
                continue
            spans = code_ranges().get(va, [(va, va + len(image))])
            for lo, hi in spans:
                if not (va <= lo < hi <= va + len(image)):
                    gate(f"ColdFire: chunk {va:#x}", False,
                         f"recorded code range {lo:#x}..{hi:#x} is outside the chunk")
                f = work / f"code_{lo:08x}.bin"
                f.write_bytes(image[lo - va:hi - va])
                rc, out = run(f"coldfire_{lo:08x}", [sys.executable, "scripts/check_coldfire.py",
                                                     f, "--base", hex(lo)], logs)
                gate(f"ColdFire: code {lo:#x}..{hi:#x}", rc == 0, "no scale-8 addressing"
                     if rc == 0 else out[-800:])
        # each executed range, at its place in MAIN OS's appended area (where the chunk's
        # image sits before the loader copies it): file offset + (start - load)
        executed = [(at + lo - va, hi - lo) for va, at, n, image in code_chunks if va not in DATA_ONLY
                    for lo, hi in code_ranges().get(va, [(va, va + n)])]
        rc, out = run("coldfire_main", [sys.executable, "scripts/check_coldfire.py",
                                        bdir / "section_3_MAIN_OS.bin", "--base", hex(MAIN_BASE),
                                        "--against", work / "stock_section_3_MAIN_OS.bin"], logs)
        if rc == 2:
            gate("ColdFire: MAIN OS", False, "no objdump: unchecked is not passing")
        hits = [int(h, 16) for h in HIT.findall(out)] if rc else []
        stock_end = MAIN_BASE + len(stock3)
        bad = [h for h in hits if h < stock_end or any(
            MAIN_BASE + at <= h < MAIN_BASE + at + n for at, n in executed)]
        gate("ColdFire: MAIN OS", not bad,
             f"{len(hits)} hit(s), all in appended data that never executes" if not bad
             else f"{len(bad)} in executed code, first at {bad[0]:#x}")

        # 5. boot from reset
        rc, out = run("boot_check", [a.venv, "-u", "scripts/emu_boot_check.py",
                                     bdir / "section_3_MAIN_OS.bin"], logs)
        gate("boot from reset", rc == 0 and "booted and drew its UI" in out,
             "booted and drew its UI, no fault" if rc == 0 else out[-800:])

        # 6. engine + LOAD/SAVE
        types = ["--machine-type", "3"] + (["--machine-type", "5", "--machine-max", "5"]
                                           if dsp_changed else [])
        # PING (filter type 6): kept by LOAD; 7 still loads as Multi-Mode; 2 is unchanged
        types += ["--filter-type", "2"] + (["--filter-type", "6", "--filter-type", "7",
                                            "--filter-max", "6"] if dsp_changed else [])
        rc, out = run("boot_engine", [a.venv, "-u", "scripts/emu_boot_engine.py",
                                      "--build", bdir, "--frames", "8", *types], logs)
        clean = rc == 0 and "ran clean" in out and "FAIL" not in out and "corrupt" not in out
        gate("engine + LOAD/SAVE", clean, "evaluator clean, CODE intact, machine and filter "
             "types round-trip" if clean else out[-800:])

        # 7. unit tests
        tests = [t for t in TESTS if (ROOT / t).exists()]
        rc, out = run("pytest", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                 "-m", "not slow", *tests], logs, env={"PYTHONPATH": "src"})
        gate("unit tests", rc == 0, out.strip().splitlines()[-1] if out.strip() else "")

    except Stop as s:
        print(f"\nGATE FAILED at: {s}\n\n  DO NOT FLASH {a.build.name}.\n  Logs: {logs}")
        return 1

    record = {"build": a.build.name, "sha256": sha, "stock": a.stock.name,
              "date": datetime.datetime.now().isoformat(timespec="seconds"),
              "gates": results, "logs": str(logs)}
    out = a.build.with_name(a.build.name + ".gate.json")
    out.write_text(json.dumps(record, indent=2))
    print(f"ALL GATES PASS on sha256 {sha[:16]}…\n  record: {out}\n\n"
          f"  CLEARED TO FLASH: {a.build.name}\n  (only this exact file; any change needs a new gate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
