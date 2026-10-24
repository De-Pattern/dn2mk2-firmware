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
3. **SHARC runner** (`sharc_waverider_m5.py`, if section 7 changed): PERC and every
   filter and machine of ours bit-exact to its model, and types 0-4 bit-identical to stock.
4. **ColdFire instruction set** (`check_coldfire.py`): every `CODE` chunk the loader
   runs has no scale-8 addressing; and every hit in MAIN OS against stock lies past
   stock's end *and* outside every `CODE` chunk (i.e. in data that never executes).
5. **boot from reset** (`emu_boot_check.py`): boots and draws its UI, no fault.
6. **engine + LOAD/SAVE** (`emu_boot_engine.py`): the evaluator runs clean under the
   real loader; CODE chunks intact; machine types survive a SAVE/LOAD round trip.
6b. **sample link** (v0.16, `emu_waverider_menu.py`'s `link16`): on the ColdFire, the
   +Drive's pool image loads into a Python DSP over the fast link (one packet lost and
   resent), commands included; with nothing getting through, the loader stops; a
   recording comes back over TDM and is written to a Python +Drive. Every byte checked,
   and every period the frame's routing words (0xa5a..) are stock's (v0.20).
7. **unit tests** (`pytest -m "not slow"` on the safety, mod, PERC and filter tests).

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
from dnfw.waverider import dsp                             # noqa: E402

MAIN_BASE = 0x40000400
# CODE chunks that hold only data, reached through a pointer and never jumped to.
# Each is listed by name, on purpose: a chunk is assumed to execute unless it is here.
DATA_ONLY: dict[int, str] = {}       # (Waverider's wave-display bytes were one, until v0.11)


def code_ranges() -> dict[int, list[tuple[int, int]]]:
    """CODE chunks whose code and data the build itself has recorded: {load: [(start,
    end)]}, the ranges that execute. Waverider's page chunk is assembly (is_wr up to its
    label table) and then C (C_LOAD up to __text_end); between and after them are its
    descriptors, strings, rodata and data, which a scan would misread as instructions
    (W2: a descriptor's two pointers read as `and.l %d0,%a4@(70,%d4:w:8)`). Any other
    CODE chunk is checked whole."""
    lay = json.loads((ROOT / "src/dnfw/mods/waverider_code.json").read_text())["layout"]
    out = {lay["is_wr"]: [(lay["is_wr"], lay["labels"])],
           lay["c_load"]: [(lay["c_load"], lay["c_text_end"])]}      # v0.13: a chunk of its own
    if "ping_slot" in lay:      # PING's chunk: its shims, then its list, names and table
        out[lay["ping_slot"]] = [(lay["ping_slot"], lay["ping_code_end"])]
    if "mchunk_code_end" in lay:  # the machines chunk: the shims, then strings and tables
        out[lay["slot_shim"]] = [(lay["slot_shim"], lay["name_long_5"])]
    return out
TESTS = ["test/test_safety.py", "test/test_mods_list.py", "test/test_mods_platform.py",
         "test/test_waverider_mod.py", "test/test_waverider_dsp.py",
         "test/test_waverider_pages.py", "test/test_ping_coldfire.py", "test/test_ping_live.py",
         "test/test_shft_live.py", "test/test_rings_live.py", "test/test_cz_live.py",
         "test/test_gran_live.py", "test/test_perc_live.py", "test/test_sampler.py",
         "test/test_sources.py", "test/test_md_ui.py"]
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
        # PERC (5), RESONATOR (6), CZ (7) and the sample machines (8..13, v0.13; 13 SLICE,
        # v0.19) are kept by LOAD; 14 still loads as FM Tone
        types = ["--machine-type", "3"] + (["--machine-type", "5", "--machine-type", "6",
                                            "--machine-type", "7", "--machine-type", "8",
                                            "--machine-type", "12", "--machine-type", "13",
                                            "--machine-type", "14", "--machine-max", "13"]
                                           if dsp_changed else [])
        # PING (6), SHFT (7) and GRAN (8) are kept by LOAD; 9 still loads as Multi-Mode
        types += ["--filter-type", "2"] + (["--filter-type", "6", "--filter-type", "7",
                                            "--filter-type", "8", "--filter-type", "9",
                                            "--filter-max", "8"]
                                           if dsp_changed else [])
        rc, out = run("boot_engine", [a.venv, "-u", "scripts/emu_boot_engine.py",
                                      "--build", bdir, "--frames", "8", *types], logs)
        clean = rc == 0 and "ran clean" in out and "FAIL" not in out and "corrupt" not in out
        gate("engine + LOAD/SAVE", clean, "evaluator clean, CODE intact, machine and filter "
             "types round-trip" if clean else out[-800:])

        # 6b. the sample link on the ColdFire (v0.16): the +Drive's image loaded over the
        # fast link with a packet lost (resent), the loader stopping when nothing gets
        # through (v0.20: the frame's words are never written), and a recording read back
        # and saved -- each against a Python DSP and +Drive
        # (scripts/emu_waverider_menu.py's link16 step)
        from dnfw.mods import waverider as W        # noqa: PLC0415
        lay = W.SPEC.get("layout", {})
        snap = ROOT.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"
        if "smp_tdm_sent" in lay:
            syms = work / "link16_syms.json"
            syms.write_text(json.dumps({k: v for k, v in lay.items() if k.startswith("smp_")}))
            scen = ("save", "fast", "dead", "high", "lowram") if "smp_ram" in lay else ("save", "fast", "dead")
            if "smp_slices_set" in lay:
                scen += ("slices",)             # v0.23: the slice editor's reading and saving
            steps = ",".join(f"link16:{syms}:{sc}" for sc in scen)
            rc, out = run("link16", [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                                     "--build", bdir, "--snapshot", snap, "--steps", steps,
                                     "--png-dir", work / "link16"], logs,
                          env={"DT2_MAIN_IMG": str(pathlib.Path(os.environ["DT2_SECTIONS"])
                                                   / "section_3_MAIN_OS.bin"),
                               "DNFW_EMU_FLAGS": '{"weakptr": false}'})
            oks = re.findall(r"link16 (save|fast|dead|high|lowram|slices): .*\"ok\": (true|false)", out)
            good = rc == 0 and len(oks) == len(scen) and all(v == "true" for _, v in oks)
            gate("sample link (ColdFire)", good,
                 "save, fast (a lost packet resent), dead (nothing gets through: the loader "
                 "stops); every byte loaded and saved; the frame's routing words stock's in "
                 "every period; v0.22: the RAM check first, past 128 MB loaded only when it "
                 "passes (high, lowram)" if good else out[-800:])

        # 6c. the RECORDER screen (v0.22): FUNC+VOICE opens it over any page, its knobs
        # change the recorder and never the track's sound, NO closes it, and the UI keeps
        # drawing throughout (scripts/emu_waverider_menu.py, keys and knob as the panel)
        if "rec_overlay" in lay:
            ov, src = hex(lay["rec_overlay"]), hex(lay["rec_src"])
            steps = (f"wait:5,png:p0,mem:{ov}:4,press:17,wait:3,tap:49,wait:3,release:17,"
                     f"wait:30,mem:{ov}:4,png:a1,spin:0:3,wait:5,mem:{src}:4,png:a2,no,"
                     f"wait:30,mem:{ov}:4,png:a3,wait:5,png:a4")
            js = work / "recorder.json"
            rc, out = run("recorder", [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                                       "--build", bdir, "--snapshot", snap, "--steps", steps,
                                       "--png-dir", work / "recorder", "--json", js], logs,
                          env={"DT2_MAIN_IMG": str(pathlib.Path(os.environ["DT2_SECTIONS"])
                                                   / "section_3_MAIN_OS.bin"),
                               "DNFW_EMU_FLAGS": '{"weakptr": false}'})
            why = out[-800:]
            good = False
            if rc == 0 and js.exists():
                r = json.loads(js.read_text())
                m = r["memory"]
                seen = [int(m[k], 16) for k in (ov, f"{ov}@1", f"{ov}@3")]
                shots = [pathlib.Path(r["screens"][n]).read_bytes() for n in ("p0", "a2", "a4")]
                good = (seen == [0, 1, 0] and int(m[src], 16) == 3 and not r["setter_writes"]
                        and r["screen_frames"] > 0 and shots[1] != shots[0] and shots[1] != shots[2])
                why = (f"overlay {seen}, src {int(m[src], 16)}, setter writes "
                       f"{len(r['setter_writes'])}, frames {r['screen_frames']}")
            gate("recorder screen (ColdFire)", good,
                 "FUNC+VOICE opens it, knob A moves SRC with no write to the sound, NO closes it, "
                 "the screen drawn throughout" if good else why)

        # 6d. after a recording (v0.22): TRIM (knobs E and H move the ends), NAME (a knob
        # and the arrows spell it), ASSIGN (a [TRIG] key: that track becomes ONESHOT playing
        # the slot, through stock's MACHINE SEL commit and setValue), each step's key
        if "rec_phase" in lay:
            g = {k: hex(lay[k]) for k in ("rec_overlay", "rec_phase", "trim_slot", "trim_n",
                                           "trim_s", "trim_e", "nm_text")}
            kit = 0x4210C08C                    # the snapshot's live kit ([0x800052a0])
            snd = hex(kit + 52 + 1163 * 2)      # track 3's sound
            steps = (f"wait:3,mem:0x800052a0:4,mem:{snd}:256,poke:{g['trim_slot']}:00000004,"
                     f"poke:{g['trim_n']}:00017700,poke:{g['trim_s']}:00000000,"
                     f"poke:{g['trim_e']}:00017700,poke:{g['rec_overlay']}:00000001,"
                     f"poke:{g['rec_phase']}:00000001,wait:20,png:t1,spin:4:5,wait:5,"
                     f"mem:{g['trim_s']}:4,spin:7:-3,wait:5,mem:{g['trim_e']}:4,png:t2,yes,wait:10,"
                     f"mem:{g['rec_phase']}:4,spin:0:3,wait:3,right,wait:3,spin:0:2,wait:3,up,wait:10,"
                     f"mem:{g['nm_text']}:8,png:n1,yes,wait:10,mem:{g['rec_phase']}:4,png:a1,tap:27,"
                     f"wait:20,mem:{g['rec_phase']}:4,mem:{snd}:256,png:r1")
            js = work / "recflow.json"
            rc, out = run("recorder flow", [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                                            "--build", bdir, "--snapshot", snap, "--steps", steps,
                                            "--png-dir", work / "recflow", "--json", js], logs,
                          env={"DT2_MAIN_IMG": str(pathlib.Path(os.environ["DT2_SECTIONS"])
                                                   / "section_3_MAIN_OS.bin"),
                               "DNFW_EMU_FLAGS": '{"weakptr": false}'})
            why, good = out[-800:], False
            if rc == 0 and js.exists():
                r = json.loads(js.read_text())
                m = r["memory"]
                ph = g["rec_phase"]
                phases = [int(m[k], 16) for k in (ph, f"{ph}@6", f"{ph}@7")]
                before, after = bytes.fromhex(m[snd]), bytes.fromhex(m[f"{snd}@8"])
                facts = {"kit": m["0x800052a0"] == f"{kit:08x}",
                         "trim": (int(m[g["trim_s"]], 16), int(m[g["trim_e"]], 16)) == (2400, 94560),
                         "phases": phases == [2, 3, 0],
                         "name": bytes.fromhex(m[g["nm_text"]])[:3] == b"CC\0",
                         "oneshot": before[0xDE] != 8 and after[0xDE] == 8,
                         "samp": after[0x6A] == 5,
                         "frames": r["screen_frames"] > 0}
                good = all(facts.values())
                why = str(facts)
            gate("recorder flow (ColdFire)", good,
                 "TRIM's ends move, YES on to NAME (spelt by knob and arrows), YES on to ASSIGN, a "
                 "[TRIG] key makes track 3 ONESHOT on the slot" if good else why)

        # 6e. v0.23, SLICE: its menus drawn over the page (the menu, the grid dialog, the
        # editor with a slice table), the editor's keys and knobs moving the picked slice;
        # and in KEYBOARD mode on a SLICE track (SLCE NOTE) trig 4 plays note C0 + 3 and
        # trig 1 C0, the notes SLCE's NOTE mode turns into slices 4 and 1
        if "slc_state" in lay:
            import struct as _st                # noqa: PLC0415
            g = {k: hex(lay[k]) for k in ("slc_state", "slc_nfr", "slc_ns", "slc_cur", "slc_sl")}
            from dnfw.sampler import machines as SMx    # noqa: PLC0415
            hires = hex(SMx.MIRROR + 0x78000)
            pat = bytes((k * 37) % 200 for k in range(1024)).hex()
            tb = _st.pack(">9I", 0, 30000, 0, 36000, 70000, 40000, 72000, 140000, 72000).hex()
            kit = 0x4210C08C
            pk = ",".join(f"poke:{kit + 52 + 1163 * t + 0xDE:#x}:0d,poke:{kit + 52 + 1163 * t + 108:#x}:0000"
                          for t in range(16))
            steps = (f"wait:2,png:p0,poke:{g['slc_state']}:00000001,wait:6,png:m,"
                     f"poke:{g['slc_state']}:00000002,wait:6,png:g,"
                     f"poke:{hires}:{pat},poke:{g['slc_nfr']}:00023280,poke:{g['slc_ns']}:00000003,"
                     f"poke:{g['slc_cur']}:00000000,poke:{g['slc_sl']}:{tb},poke:{g['slc_state']}:00000004,"
                     f"wait:6,png:e1,right,wait:5,spin:4:6,wait:5,png:e2,mem:{g['slc_cur']}:4,"
                     f"mem:{g['slc_sl']}:36,no,wait:6,mem:{g['slc_state']}:4,"
                     f"{pk},tap:18,wait:6,press:28,wait:6,release:28,wait:6,press:25,wait:6,release:25,wait:6")
            js = work / "slice.json"
            rc, out = run("slice menus", [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                                          "--build", bdir, "--snapshot", snap, "--steps", steps,
                                          "--regs-at", "0x400576ca",
                                          "--png-dir", work / "slice", "--json", js], logs,
                          env={"DT2_MAIN_IMG": str(pathlib.Path(os.environ["DT2_SECTIONS"])
                                                   / "section_3_MAIN_OS.bin"),
                               "DNFW_EMU_FLAGS": '{"weakptr": false}'})
            why, good = out[-800:], False
            if rc == 0 and js.exists():
                r = json.loads(js.read_text())
                m = r["memory"]
                shots = {n: pathlib.Path(r["screens"][n]).read_bytes() for n in ("p0", "m", "g", "e1", "e2")}
                table = list(_st.unpack(">9I", bytes.fromhex(m[g["slc_sl"]])))
                notes = [int(x["D4"], 16) for x in r["regs_at"].get("0x400576ca", [])]
                facts = {"drawn": len({shots[n] for n in shots}) >= 4,
                         "picked": int(m[g["slc_cur"]], 16) == 1,
                         "start moved": table[3] > 36000 and table[:3] == [0, 30000, 0],
                         "closed": int(m[g["slc_state"]], 16) == 0,
                         "slice notes": notes == [15, 12]}
                good = all(facts.values())
                why = str(facts) + f" notes {notes}"
            gate("SLICE menus and SLICES keys (ColdFire)", good,
                 "menu, grid dialog and editor drawn; RIGHT picks slice 2, E moves its start, NO "
                 "closes; KEYBOARD trig 4 / trig 1 on a SLICE track play C0+3 / C0" if good else why)

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
