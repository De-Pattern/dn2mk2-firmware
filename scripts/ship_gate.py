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

**v0.25 (the owner's go-ahead, 2026-10-25): the SHARC runner runs beside the ColdFire
steps, and a long step's pass is reused only when nothing it read has changed**
(`scripts/gate_cache.py`): every file its processes opened, the directories they listed,
the native libraries and programs they ran, and this script's own inputs, each hashed
(sha256) when it passed. One differing byte, or a file gone, and the step runs again. The
record says which steps were reused and from which pass.
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
import threading
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

sys.path.insert(0, str(HERE))
import gate_cache                                          # noqa: E402

MAIN_BASE = 0x40000400
# CODE chunks that hold only data, reached through a pointer and never jumped to.
# Each is listed by name, on purpose: a chunk is assumed to execute unless it is here.
DATA_ONLY: dict[int, str] = {       # (Waverider's wave-display bytes were one, until v0.11)
    # the Monomachine build: the tables csrc/sampler/link.c sends the DSP at power-on (read
    # as bytes from TABLE_LOAD, never called; dnfw.mods.waverider._tables)
    0x47000000: "the DSP's tables, sent at power-on by the sample link (data, never called)",
}


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
         "test/test_shft_live.py", "test/test_mnm.py",
         "test/test_gran_live.py", "test/test_perc_live.py", "test/test_sampler.py",
         "test/test_sources.py", "test/test_md_ui.py", "test/test_patcher.py",
         "test/test_sampler_relatch.py"]
HIT = re.compile(r"^\s+([0-9a-f]{8}):", re.M)


class Stop(Exception):
    pass


LIVE: list[subprocess.Popen] = []            # steps running (the SHARC runner beside the rest)


def run(name, cmd, log_dir, env=None, cwd=ROOT, trace=None):
    """Run CMD, log its output to LOG_DIR/NAME.log, -> (rc, output). TRACE: a directory for
    the step's trace (gate_cache: what it read)."""
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    t = time.time()
    env = {**os.environ, **(env or {})}
    if trace is not None:
        trace.mkdir(parents=True, exist_ok=True)
        env["DNFW_GATE_TRACE"] = str(trace)
        env["PYTHONPATH"] = os.pathsep.join([str(HERE / "gate_trace")]
                                            + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    LIVE.append(proc)
    out, _ = proc.communicate()
    LIVE.remove(proc)
    (log_dir / f"{name}.log").write_text(out)
    print(f"    rc {proc.returncode}, {round(time.time() - t)} s, log {log_dir / (name + '.log')}",
          flush=True)
    return proc.returncode, out


def own_inputs(own=None) -> dict[str, str]:
    """What this script's verdicts read: itself, the cache and tracer, and every module of
    the repository it has imported (the build's layout among them). OWN (v0.28): a step
    whose verdict reads only those files (and its own traced run): the cache, the tracer
    and OWN."""
    files = {HERE / "gate_cache.py", HERE / "gate_trace" / "sitecustomize.py"}
    if own is not None:
        files |= {pathlib.Path(f).resolve() for f in own}
    else:
        files |= {HERE / "ship_gate.py", ROOT / "src/dnfw/mods/waverider_code.json",
                  ROOT / "src/dnfw/waverider/sharc_code.json"}
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if f and pathlib.Path(f).resolve().is_relative_to(ROOT):
                files.add(pathlib.Path(f).resolve())
    out = {}
    for f in sorted(files):
        if f.is_file():
            out[str(f)] = "f:" + hashlib.sha256(f.read_bytes()).hexdigest()
    return out


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

    reused: dict[str, str] = {}

    def cached(name, cmds, body, own=None):
        """A long step: reused if a pass with these commands read nothing that has changed
        since (gate_cache); else BODY(trace) -> (ok, detail), and a pass is kept. OWN: the
        files the step's verdict reads (v0.28, the SHARC runner's: gate_sharc.py), else
        all of this script's own inputs."""
        key = [gate_cache.norm_cmd(c, work) for c in cmds]
        rec = gate_cache.lookup(ROOT, name, key, work)
        if rec:
            reused[name] = rec["date"]
            print(f"  (reused: the pass of {rec['date']}, build {rec['build'][:12]}; its "
                  f"{len(rec['inputs'])} inputs are byte-identical now)", flush=True)
            return True, rec["detail"] + " [reused: no input changed]"
        tdir = work / "traces" / "".join(c if c.isalnum() else "_" for c in name)
        ok, detail = body(tdir)
        if ok:
            ins = gate_cache.inputs(tdir, work, logs)
            ins.update(own_inputs(own))
            gate_cache.store(ROOT, name, key, ins, detail, sha)
        return ok, detail

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
            # v0.25: beside the ColdFire steps (its own core); its verdict is taken before
            # the unit tests
            # v0.28: the step is scripts/gate_sharc.py's; its reuse record holds what the
            # runner read and that file, not this script or the ColdFire's artefacts
            import gate_sharc                   # noqa: PLC0415

            def sharc_thread():
                # v0.28: in parts (gate_sharc.parts: together the runner's default steps), each
                # cached on its own; the verdict is every part's
                try:
                    verdicts = []
                    for k, steps in enumerate(gate_sharc.parts()):
                        cmd = gate_sharc.command(a.stock, a.digikit_sharc, steps, f"part{k}")

                        def body(tdir, cmd=cmd, k=k):
                            rc, out = run(f"sharc_m5_part{k}", cmd, logs, trace=tdir)
                            return gate_sharc.verdict(rc, out)
                        ok, detail = cached(f"SHARC runner: {','.join(steps)}", [cmd], body, own=gate_sharc.OWN)
                        verdicts.append((ok, f"{','.join(steps)}: {detail}"))
                        if not ok:
                            break
                    good = all(v for v, _ in verdicts) and len(verdicts) == len(gate_sharc.parts())
                    sharc_box.append((good, "; ".join(d for _, d in verdicts)))
                except Exception as e:          # noqa: BLE001
                    sharc_box.append((False, f"the runner did not run: {e}"))
            sharc_box: list = []
            sharc = threading.Thread(target=sharc_thread, daemon=True)
            sharc.start()
        else:
            sharc = None
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
        boot_cmd = [a.venv, "-u", "scripts/emu_boot_check.py", bdir / "section_3_MAIN_OS.bin"]

        def boot_body(tdir):
            rc, out = run("boot_check", boot_cmd, logs, trace=tdir)
            good = rc == 0 and "booted and drew its UI" in out
            return good, "booted and drew its UI, no fault" if good else out[-800:]
        gate("boot from reset", *cached("boot from reset", [boot_cmd], boot_body))

        # 6. engine + LOAD/SAVE
        # PERC (5), the Monomachine's (6, 7, v0.26: 14..) and the sample machines (8..13,
        # v0.13; 13 SLICE, v0.19) are kept by LOAD; the first type past ours still loads as
        # FM Tone
        from dnfw.waverider import coldfire as _cf
        last = _cf.TYPES_LAST
        mtypes = sorted({5, 6, 7, 8, 12, 13, *range(14, last + 1), last + 1})
        types = ["--machine-type", "3"] + ([x for t in mtypes for x in ("--machine-type", str(t))]
                                           + ["--machine-max", str(last)]
                                           if dsp_changed else [])
        # v0.27: SHFT (7) and GRAN (8) removed: 7 and 8 load as Multi-Mode now
        types += ["--filter-type", "2"] + (["--filter-type", "6", "--filter-type", "7",
                                            "--filter-type", "8", "--filter-max", "6"]
                                           if dsp_changed else [])
        eng_cmd = [a.venv, "-u", "scripts/emu_boot_engine.py", "--build", bdir, "--frames", "8", *types]

        def eng_body(tdir):
            rc, out = run("boot_engine", eng_cmd, logs, trace=tdir)
            clean = rc == 0 and "ran clean" in out and "FAIL" not in out and "corrupt" not in out
            return clean, ("evaluator clean, CODE intact, machine and filter types round-trip"
                           if clean else out[-800:])
        gate("engine + LOAD/SAVE", *cached("engine + LOAD/SAVE", [eng_cmd], eng_body))

        # 6b. the sample link on the ColdFire (v0.16): the +Drive's image loaded over the
        # fast link with a packet lost (resent), the loader stopping when nothing gets
        # through (v0.20: the frame's words are never written), and a recording read back
        # and saved -- each against a Python DSP and +Drive
        # (scripts/emu_waverider_menu.py's link16 step)
        from dnfw.mods import waverider as W        # noqa: PLC0415
        lay = W.SPEC.get("layout", {})
        snap = ROOT.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"
        EMU_ENV = {"DT2_MAIN_IMG": str(pathlib.Path(os.environ["DT2_SECTIONS"]) / "section_3_MAIN_OS.bin"),
                   "DNFW_EMU_FLAGS": '{"weakptr": false}'}
        if "smp_tdm_sent" in lay:
            syms = work / "link16_syms.json"
            syms.write_text(json.dumps({k: v for k, v in lay.items() if k.startswith("smp_")}))
            scen = ("save", "fast", "dead", "high", "lowram") if "smp_ram" in lay else ("save", "fast", "dead")
            if "smp_slices_set" in lay:
                scen += ("slices",)             # v0.23: the slice editor's reading and saving
            steps = ",".join(f"link16:{syms}:{sc}" for sc in scen)
            l16_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                       "--build", bdir, "--snapshot", snap, "--steps", steps,
                       "--png-dir", work / "link16"]

            def l16_body(tdir):
                rc, out = run("link16", l16_cmd, logs, env=EMU_ENV, trace=tdir)
                oks = re.findall(r"link16 (save|fast|dead|high|lowram|slices): .*\"ok\": (true|false)", out)
                good = rc == 0 and len(oks) == len(scen) and all(v == "true" for _, v in oks)
                return good, ("save, fast (a lost packet resent), dead (nothing gets through: the loader "
                              "stops); every byte loaded and saved; the frame's routing words stock's in "
                              "every period; v0.22: the RAM check first, past 128 MB loaded only when it "
                              "passes (high, lowram)" if good else out[-800:])
            gate("sample link (ColdFire)", *cached("sample link (ColdFire)", [l16_cmd, sorted(EMU_ENV.items())], l16_body))

        # 6c. the RECORDER screen (v0.22): FUNC+VOICE opens it over any page, its knobs
        # change the recorder and never the track's sound, NO closes it, and the UI keeps
        # drawing throughout (scripts/emu_waverider_menu.py, keys and knob as the panel)
        if "rec_overlay" in lay:
            ov, src = hex(lay["rec_overlay"]), hex(lay["rec_src"])
            steps = (f"wait:5,png:p0,mem:{ov}:4,press:17,wait:3,tap:49,wait:3,release:17,"
                     f"wait:30,mem:{ov}:4,png:a1,spin:0:3,wait:5,mem:{src}:4,png:a2,no,"
                     f"wait:30,mem:{ov}:4,png:a3,wait:5,png:a4")
            js = work / "recorder.json"
            rec_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                                       "--build", bdir, "--snapshot", snap, "--steps", steps,
                                       "--png-dir", work / "recorder", "--json", js]

            def rec_body(tdir):
                rc, out = run("recorder", rec_cmd, logs, env=EMU_ENV, trace=tdir)
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
                return good, ("FUNC+VOICE opens it, knob A moves SRC with no write to the sound, NO closes it, "
                 "the screen drawn throughout"
                              if good else why)
            gate("recorder screen (ColdFire)", *cached("recorder screen (ColdFire)", [rec_cmd, sorted(EMU_ENV.items())], rec_body))

        # 6d. after a recording (v0.22; v0.25 as the DT2's): SAVING/NORMALIZING (phase 4) on to
        # TRIM once saved; TRIM's ends move (E, H); FUNC + YES plays the preview while held
        # (a command each way, FUNC's release seen); YES on to FILE NAME (spelt by knob and
        # arrows; FUNC + YES inserts, FUNC + NO deletes), YES on to ASSIGN, a [TRIG] key
        # makes track 3 ONESHOT playing the slot (stock's MACHINE SEL commit and setValue)
        if "rec_phase" in lay and "rec_pv_on" in lay:
            g = {k: hex(lay[k]) for k in ("rec_overlay", "rec_phase", "trim_slot", "trim_n", "trim_s",
                                           "trim_e", "nm_text", "rec_pv_on", "smp_func_held", "smp_cmds",
                                           "smp_saved")}
            kit = 0x4210C08C                    # the snapshot's live kit ([0x800052a0])
            snd = hex(kit + 52 + 1163 * 2)      # track 3's sound
            steps = (f"wait:3,mem:0x800052a0:4,mem:{snd}:256,poke:{g['trim_slot']}:00000004,"
                     f"poke:{g['trim_n']}:00017700,poke:{g['trim_s']}:00000000,poke:{g['trim_e']}:00017700,"
                     f"poke:{g['smp_saved']}:00000000,poke:{g['rec_overlay']}:00000001,"
                     f"poke:{g['rec_phase']}:00000004,wait:10,mem:{g['rec_phase']}:4,"
                     f"poke:{g['smp_saved']}:00000001,wait:10,mem:{g['rec_phase']}:4,png:t1,spin:4:5,wait:5,"
                     f"mem:{g['trim_s']}:4,spin:7:-3,wait:5,mem:{g['trim_e']}:4,png:t2,mem:{g['smp_cmds']}:4,"
                     f"press:17,wait:2,press:10,wait:3,mem:{g['rec_pv_on']}:4,mem:{g['smp_cmds']}:4,"
                     f"release:10,wait:3,release:17,wait:3,mem:{g['rec_pv_on']}:4,mem:{g['smp_func_held']}:4,"
                     f"mem:{g['smp_cmds']}:4,yes,wait:10,mem:{g['rec_phase']}:4,png:n0,spin:0:3,wait:3,right,"
                     f"wait:3,spin:0:2,wait:3,mem:{g['nm_text']}:8,press:17,wait:2,yes,wait:3,release:17,wait:3,"
                     f"mem:{g['nm_text']}:8,press:17,wait:2,no,wait:3,release:17,wait:3,mem:{g['nm_text']}:8,"
                     f"png:n1,yes,wait:10,mem:{g['rec_phase']}:4,png:a1,tap:27,"
                     f"wait:20,mem:{g['rec_phase']}:4,mem:{snd}:256,png:r1")
            js = work / "recflow.json"
            flow_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                                            "--build", bdir, "--snapshot", snap, "--steps", steps,
                                            "--png-dir", work / "recflow", "--json", js]

            def flow_body(tdir):
                rc, out = run("recorder flow", flow_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and js.exists():
                    r = json.loads(js.read_text())
                    m = r["memory"]
                    ph, cm, pv = g["rec_phase"], g["smp_cmds"], g["rec_pv_on"]
                    phases = [int(m[k], 16) for k in (ph, f"{ph}@3", f"{ph}@12", f"{ph}@16", f"{ph}@17")]
                    cmds = [int(m[k], 16) for k in (cm, f"{cm}@8", f"{cm}@11")]
                    before, after = bytes.fromhex(m[snd]), bytes.fromhex(m[f"{snd}@18"])
                    s0, e0 = int(m[g["trim_s"]], 16), int(m[g["trim_e"]], 16)
                    names = [bytes.fromhex(m[k])[:4] for k in (g["nm_text"], f"{g['nm_text']}@14",
                                                               f"{g['nm_text']}@15")]
                    facts = {"kit": m["0x800052a0"] == f"{kit:08x}",
                             "phases": phases == [4, 1, 2, 3, 0],
                             "trim": 0 < s0 < e0 < 0x17700,
                             "preview": int(m[pv], 16) == 1 and int(m[f"{pv}@9"], 16) == 0
                             and cmds[1] == cmds[0] + 1 and cmds[2] == cmds[1] + 1
                             and int(m[g["smp_func_held"]], 16) == 0,
                             "name": names == [b"CB\0\0", b"C B\0", b"CB\0\0"],
                             "oneshot": before[0xDE] != 8 and after[0xDE] == 8,
                             "samp": after[0x6A] == 5,
                             "frames": r["screen_frames"] > 0}
                    good = all(facts.values())
                    why = str(facts) + f" phases {phases} cmds {cmds} names {names}"
                return good, ("SAVING on to TRIM; TRIM's ends move; FUNC + YES previews while held; YES on to "
                              "FILE NAME (knob, arrows, FUNC + YES inserts, FUNC + NO deletes), YES on to ASSIGN, "
                              "a [TRIG] key makes track 3 ONESHOT on the slot" if good else why)
            gate("recorder flow (ColdFire)", *cached("recorder flow (ColdFire)", [flow_cmd, sorted(EMU_ENV.items())], flow_body))

        # 6e. v0.23, SLICE: its menus drawn over the page (the menu, the grid dialog, the
        # editor with a slice table), the editor's keys and knobs moving the picked slice;
        # and in KEYBOARD mode on a SLICE track (SLCE NOTE) the keys play the slices in the
        # order of their notes (v0.26): trig 9, 10 (the lowest) slices 1, 2 (notes C0, C0 + 1,
        # which SLCE's NOTE mode turns into those slices), trig 2 (higher) a later one
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
                     f"mem:{g['slc_sl']}:36,"
                     # v0.26: FUNC + RIGHT splits the picked slice in two, FUNC + LEFT removes it
                     f"press:17,wait:2,right,wait:3,release:17,wait:3,mem:{g['slc_ns']}:4,mem:{g['slc_sl']}:48,"
                     f"press:17,wait:2,left,wait:3,release:17,wait:3,mem:{g['slc_ns']}:4,"
                     # v0.27: FUNC held, E moves the start at its normal step (FUNC + YES's preview between moves)
                     f"mem:{g['slc_cur']}:4,mem:{g['slc_sl']}:36,press:17,wait:2,spin:4:3,wait:5,release:17,wait:3,"
                     f"mem:{g['slc_sl']}:36,"
                     f"no,wait:6,mem:{g['slc_state']}:4,"
                     f"{pk},tap:18,wait:6,press:33,wait:6,release:33,wait:6,press:34,wait:6,release:34,wait:6,"
                     f"press:26,wait:6,release:26,wait:6")
            js = work / "slice.json"
            slc_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                                          "--build", bdir, "--snapshot", snap, "--steps", steps,
                                          "--regs-at", "0x400576ca",
                                          "--png-dir", work / "slice", "--json", js]

            def slc_body(tdir):
                rc, out = run("slice menus", slc_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and js.exists():
                    r = json.loads(js.read_text())
                    m = r["memory"]
                    shots = {n: pathlib.Path(r["screens"][n]).read_bytes() for n in ("p0", "m", "g", "e1", "e2")}
                    table = list(_st.unpack(">9I", bytes.fromhex(m[g["slc_sl"]])))
                    notes = [int(x["D4"], 16) for x in r["regs_at"].get("0x400576ca", [])]
                    split = list(_st.unpack(">12I", bytes.fromhex(m[f"{g['slc_sl']}@3"])))
                    facts = {"drawn": len({shots[n] for n in shots}) >= 4,
                             "picked": int(m[g["slc_cur"]], 16) == 1,
                             "start moved": table[3] > 36000 and table[:3] == [0, 30000, 0],
                             # slice 2 (start s, end 70000) split at its middle: s..mid, mid..70000
                             "split": int(m[g["slc_ns"]], 16) == 4 and split[3] == table[3]
                             and split[6] == split[3] + (70000 - split[3]) // 2 == split[4]
                             and split[7] == 70000
                             and split[9:12] == [72000, 140000, 72000],   # slice 3, as it was
                             "removed": int(m[f"{g['slc_ns']}@4"], 16) == 3,
                             "FUNC + E: the normal step": (lambda c, a, b: b[3 * c] - a[3 * c] >= 3 * (0x23280 // 128))(
                                 int(m[f"{g['slc_cur']}@5"], 16),
                                 _st.unpack(">9I", bytes.fromhex(m[f"{g['slc_sl']}@6"])),
                                 _st.unpack(">9I", bytes.fromhex(m[f"{g['slc_sl']}@7"]))),
                             "closed": int(m[g["slc_state"]], 16) == 0,
                             # trig 9, 10 (the bottom row's first two: the lowest notes) slices
                             # 1, 2; trig 2 (the top row: a higher note) a later one
                             "slice notes": len(notes) == 3 and notes[:2] == [12, 13] and notes[2] > 13}
                    good = all(facts.values())
                    why = str(facts) + f" notes {notes}"
                return good, ("menu, grid dialog and editor drawn; RIGHT picks slice 2, E moves its start, NO "
                 "closes; FUNC + RIGHT splits slice 2, FUNC + LEFT removes it; FUNC + E moves at the normal step; KEYBOARD on a SLICE track: trigs 9, 10 play slices 1, 2 and trig 2 a later one (the keys' notes in order)"
                              if good else why)
            gate("SLICE menus and SLICES keys (ColdFire)", *cached("SLICE menus and SLICES keys (ColdFire)", [slc_cmd, sorted(EMU_ENV.items())], slc_body))

        # 6g. v0.25, GRID's ALLOCATE SLICE (YES on a GRID track's page): trigs placed on steps
        # 1, 3, 5 in GRID RECORDING; CREATE LINEAR LOCKS locks slices 1, 2, 3 on them (the
        # stock's own lock calls, read back through its GET); RANDOM again, then NO puts
        # back the linear ones
        if "slc_alloc_n" in lay:
            from dnfw.sampler import machines as SMx    # noqa: PLC0415
            sid = SMx.SLICE_REC
            kit = 0x4210C08C
            get = ",".join(f"call:0x40037c52:0:{sid}:{k},wait:2" for k in (0, 2, 4))
            steps = (f"wait:3,poke:{kit + 52 + 0xDE:#x}:0c,wait:4,tap:2,wait:6,tap:19,wait:6,tap:25,wait:4,"
                     f"tap:27,wait:4,tap:29,wait:4,tap:19,wait:6,yes,wait:6,png:m,yes,wait:6,"
                     f"mem:{lay['slc_alloc_n']:#x}:4,{get},yes,wait:6,down,wait:3,yes,wait:6,yes,wait:6,"
                     f"no,wait:6,mem:{lay['slc_state']:#x}:4,{get}")
            js = work / "alloc.json"
            al_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                      "--snapshot", snap, "--steps", steps, "--png-dir", work / "alloc", "--json", js]

            def al_body(tdir):
                rc, out = run("grid allocate", al_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and js.exists():
                    r = json.loads(js.read_text())
                    m = r["memory"]
                    d0 = [c["d0"] for c in r["direct_calls"]]
                    facts = {"three trigs locked": int(m[hex(lay["slc_alloc_n"])], 16) == 3,
                             "linear: slices 1, 2, 3": d0[:3] == [512, 1024, 1536],
                             "closed": int(m[hex(lay["slc_state"])], 16) == 0,
                             "NO puts the locks back": d0[4:6] == [1024, 1536]}
                    good = all(facts.values())
                    why = str(facts) + f" {d0}"
                return good, ("GRID's ALLOCATE SLICE: LINEAR locks slices 1..3 on three placed trigs; NO after "
                              "RANDOM puts them back" if good else why)
            gate("GRID allocate slice locks (ColdFire)",
                 *cached("GRID allocate slice locks (ColdFire)", [al_cmd, sorted(EMU_ENV.items())], al_body))

        # 6f. v0.25: the sample pages' playhead (the DSP's positions, poked as the link would
        # leave them), the DT2-style sample list (it opens on SAMP's change; DOWN moves SAMP,
        # NO puts it back and closes it), the folder browser (FUNC + YES: a folder entered, a
        # sample picked sets SAMP and closes both), and modulation on SAMP moved through the
        # loaded slots (smp_mod_apply, called on the parameter mirror)
        if "smp_mod_apply" in lay:
            from dnfw.sampler import machines as SMx    # noqa: PLC0415
            M = SMx.MIRROR
            kit = 0x4210C08C
            snd0 = kit + 52
            samp0 = snd0 + 0x6A

            def samp_all(v):
                return [f"poke:{kit + 52 + 1163 * t + 0x6A:#x}:{v:02x}00" for t in range(16)]
            d = bytearray(0x1000)
            struct.pack_into("<II", d, 0, 0x31504D53, 4)
            for k, (fr, nm) in enumerate([(48000, "KICK"), (96000, "SHS_HAU"), (0, ""), (24000, "SNARE")]):
                if fr:
                    struct.pack_into("<IIfI", d, 8 + 16 * k, 0x84001000 + 0x40000 * k, fr, 1.0, 1)
                d[0x808 + 8 * k:0x808 + 8 * k + len(nm)] = nm.encode()
            ov = bytes((40 + (j * 7) % 150) for j in range(100))
            fb, sb = SMx.META_FOLDER_BYTES, SMx.META_SLOT_BYTES
            mt = bytearray(SMx.META_BYTES)
            struct.pack_into("<III", mt, 0, SMx.META_MAGIC, 1, 2)
            mt[12:22] = b"drum_loops"
            mt[12 + fb:12 + fb + 5] = b"loops"
            for k in range(128):
                mt[12 + SMx.META_FOLDERS * fb + sb * k] = 0xFF
            for k, f, nm in ((0, 0, "kick"), (1, 1, "shs_haunt_tape_56_drum_lo"), (3, 0xFF, "snare")):
                r0 = 12 + SMx.META_FOLDERS * fb + sb * k
                mt[r0] = f
                mt[r0 + 4:r0 + 4 + len(nm)] = nm.encode()
            cell = 0x800068E4 + 34 + 86
            mem = lambda va, n=4: f"mem:{va:#x}:{n}"          # noqa: E731
            st = ["wait:2"] + [f"poke:{kit + 52 + 1163 * t + 0xDE:#x}:08" for t in range(16)] + samp_all(2)
            st += [f"poke:{M:#x}:{d[:0xC10].hex()}"] + [f"poke:{M + 0x1000 + 100 * k:#x}:{ov.hex()}" for k in (0, 1, 3)]
            st += [f"poke:{M + 0x80000:#x}:{mt.hex()}", f"poke:{lay['smp_dir_ok']:#x}:00000001",
                   f"poke:{lay['smp_meta_ok']:#x}:00000001"]
            base = list(st)                     # (the pool as loaded: 6i starts from it too)
            st += ["wait:6", "tap:2", "wait:6", "png:p2", f"poke:{lay['smp_periods']:#x}:00000000",
                   f"poke:{lay['smp_pos_at']:#x}:00000000", f"poke:{lay['smp_pos']:#x}:" + "8000" * 16,
                   "wait:12", "png:ph1", f"poke:{lay['smp_pos']:#x}:" + "C000" * 16, "wait:36", "png:ph2",
                   "tap:2", "wait:6"]
            # v0.27: SAMP set without a turn (TRACK + PLAY's clear, a load) leaves the list
            # closed; a turn of SAMP (encoder D) opens it
            # (the emulator's encoders do not move a stock page's value, so a turn is the stock
            # setter's own call of smp_quant on SAMP's slot, then the value it writes)
            def turn(v):                        # (and a redraw asked for, as the turn's own would)
                return [f"call:{lay['smp_quant']:#x}:sound0:{SMx.RECORDS[SMx.SAMP_REC][0]}:{v << 8:#x}",
                        f"poke:{samp0:#x}:{v:02x}00", f"poke:{lay['smp_overlay_dirty']:#x}:00000001"]
            st += samp_all(3) + [f"poke:{lay['smp_overlay_dirty']:#x}:00000001", "wait:10", "png:l0",
                                 mem(lay["smp_lst_open"])]      # (redrawn: the change is seen, and opens nothing)
            st += samp_all(2) + ["wait:10"] + turn(4) + ["wait:10", "png:l1", mem(lay["smp_lst_open"]), "down",
                                 "wait:8", "png:l2", mem(samp0, 2), "no", "wait:8", "png:l3", mem(samp0, 2),
                                 mem(lay["smp_lst_open"])]
            st += samp_all(2) + ["wait:10"] + turn(3) + ["wait:10", "png:l4", "press:17", "wait:2", "yes", "wait:2", "release:17",
                                 "wait:8", "png:b1", mem(lay["smp_fb_open"]), "yes", "wait:8", "png:b2",
                                 mem(lay["smp_fb_folder"]), "down", "wait:2", "yes", "wait:8", "png:b3",
                                 mem(samp0, 2), mem(lay["smp_fb_open"]), mem(lay["smp_lst_open"])]
            # the SAMPLE ACTION menu: into "loops", RIGHT on its sample, DELETE, asked, YES
            st += samp_all(3) + ["wait:10"] + turn(2) + ["wait:10", "press:17", "wait:2", "yes", "wait:2", "release:17", "wait:8",
                                 "down", "wait:4", "yes", "wait:6", "right", "wait:6", "png:m1", "down", "wait:3",
                                 "down", "wait:3", "yes", "wait:6", "png:m2", "yes", "wait:8", "png:m3",
                                 mem(M + 8 + 16 + 4, 4)]
            # (v0.30: the reach scaled by depth over the loaded samples, held at the ends. The
            # DELETE above emptied slot 1, so two are loaded: slots 0 and 3. SAMP 1 (slot 0):
            # +43 one sample on (SAMP 4), +125 to the last and no further (SAMP 4), +1 none
            # (SAMP 1). v0.29's first form set SAMP 2, the slot just deleted, and counted three)
            st += [f"poke:0x800052a8:{snd0:08x}", f"poke:{samp0:#x}:0100", f"poke:{cell:#x}:2c00",
                   f"call:{lay['smp_mod_apply']:#x}:0x800068e4", mem(cell, 2),
                   f"poke:{cell:#x}:7e00", f"call:{lay['smp_mod_apply']:#x}:0x800068e4", mem(cell, 2),
                   f"poke:{cell:#x}:0200", f"call:{lay['smp_mod_apply']:#x}:0x800068e4", mem(cell, 2)]
            js = work / "samplist.json"
            sl_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                      "--snapshot", snap, "--steps", ",".join(st), "--png-dir", work / "samplist", "--json", js]

            def sl_body(tdir):
                rc, out = run("sample list", sl_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and js.exists():
                    r = json.loads(js.read_text())
                    m = r["memory"]
                    shots = {n: pathlib.Path(r["screens"][n]).read_bytes() for n in ("p2", "ph1", "ph2", "l1", "b1", "b2")}
                    lo, fo, ff = (hex(lay[k]) for k in ("smp_lst_open", "smp_fb_open", "smp_fb_folder"))
                    sp, ce = hex(samp0), hex(cell)
                    facts = {"playhead drawn and moving": len({shots["p2"], shots["ph1"], shots["ph2"]}) == 3,
                             "v0.27: SAMP set without a turn leaves the list closed": int(m[lo], 16) == 0,
                             "list opens on a turn": int(m[f"{lo}@1"], 16) == 1,
                             "DOWN moves SAMP": m[sp] == "0500",
                             "NO puts it back and closes": m[f"{sp}@3"] == "0200" and int(m[f"{lo}@4"], 16) == 0,
                             "browser opens, a folder entered": int(m[fo], 16) == 1 and int(m[ff], 16) == 0
                             and shots["b1"] != shots["b2"],
                             "a sample picked: SAMP, both closed": m[f"{sp}@7"] == "0100" and int(m[f"{fo}@8"], 16) == 0
                             and int(m[f"{lo}@9"], 16) == 0,
                             "DELETE in the SAMPLE ACTION menu empties the slot": m[hex(M + 28)] == "00000000"
                             and len({pathlib.Path(r["screens"][n]).read_bytes() for n in ("m1", "m2", "m3")}) == 3,
                             "modulated SAMP through the loaded slots, by depth, held at the last":
                             [m[ce], m[f"{ce}@12"], m[f"{ce}@13"]] == ["0400", "0400", "0100"]}
                    good = all(facts.values())
                    why = str(facts)
                return good, ("the playhead drawn where the DSP says; SAMP set without a turn opens nothing, a turn opens the list, DOWN moves it, NO "
                              "puts it back; FUNC + YES's browser enters a folder and assigns a sample; "
                              "its SAMPLE ACTION menu deletes; modulation on SAMP steps through the loaded slots" if good else why)
            gate("sample list, browser, playhead (ColdFire)",
                 *cached("sample list, browser, playhead (ColdFire)", [sl_cmd, sorted(EMU_ENV.items())], sl_body))

            # 6i. v0.29: multi-select in the browser (a user's report: no way to delete all the
            # samples sent in). At the top, FUNC + YES marks every sample of "drum_loops"
            # (kick); RIGHT on "loops" opens its menu, SELECT ALL marks its sample; RIGHT,
            # DELETE: "DELETE 2?", YES: slots 0 and 1 emptied, the snare (no folder) kept; the
            # marks cleared, the browser still up, and the two emptied folders no longer shown
            if "smp_fb_mark_count" in lay:
                fbc, fbm = lay["smp_fb_count"], lay["smp_fb_mark_count"]
                lead = ["wait:6", "tap:2", "wait:6", f"poke:{lay['smp_periods']:#x}:00000000",     # (as 6f: the
                        f"poke:{lay['smp_pos_at']:#x}:00000000", "wait:12", "tap:2", "wait:6"]      # clock set)
                ms = base + lead + samp_all(3) + [f"poke:{lay['smp_overlay_dirty']:#x}:00000001", "wait:10"] + turn(2) + [
                    "wait:10", "press:17", "wait:2", "yes", "wait:2", "release:17", "wait:8", f"call:{fbc:#x}",
                    "press:17", "wait:2", "yes", "wait:2", "release:17", "wait:6", "png:s1", f"call:{fbm:#x}",
                    "down", "wait:4", "right", "wait:6", "png:s2", "yes", "wait:6", f"call:{fbm:#x}",
                    "right", "wait:6", "down", "wait:3", "png:s3", "yes", "wait:6", "png:s4", "yes", "wait:10",
                    "png:s5", mem(M + 8), mem(M + 24), mem(M + 56), f"call:{fbm:#x}", mem(lay["smp_fb_open"]),
                    f"call:{fbc:#x}"]
                mjs = work / "multisel.json"
                ms_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                          "--snapshot", snap, "--steps", ",".join(ms), "--png-dir", work / "multisel", "--json", mjs]

                def ms_body(tdir):
                    rc, out = run("multi-select", ms_cmd, logs, env=EMU_ENV, trace=tdir)
                    why, good = out[-800:], False
                    if rc == 0 and mjs.exists():
                        r = json.loads(mjs.read_text())
                        m, calls = r["memory"], [c.get("d0") for c in r.get("direct_calls", [])]
                        shots = [pathlib.Path(r["screens"][n]).read_bytes() for n in ("s1", "s2", "s3", "s4", "s5")]
                        d0 = [int(str(x), 0) if x is not None else None for x in calls][1:]   # (the first: the turn's smp_quant)
                        facts = {"the top: three items (two folders, INCOMING)": d0[:1] == [3],
                                 "FUNC + YES on a folder marks its sample": d0[1:2] == [1],
                                 "SELECT ALL on the second folder: two marked": d0[2:3] == [2],
                                 "DELETE 2: slots 0 and 1 emptied, the snare kept": m[hex(M + 8)] == "00000000"
                                 and m[hex(M + 24)] == "00000000" and m[hex(M + 56)] != "00000000",
                                 "the marks cleared, the browser up, only INCOMING left":
                                 d0[3:5] == [0, 1] and int(m[hex(lay["smp_fb_open"])], 16) == 1,
                                 "each step drawn": len(set(shots)) == 5}
                        good = all(facts.values())
                        why = f"{facts} d0={d0}"
                    return good, ("FUNC + YES marks a folder's samples; SELECT ALL a folder's; DELETE takes the "
                                  "marked ones (DELETE 2?), keeps the rest, clears the marks, hides emptied folders"
                                  if good else why)
                gate("multi-select delete (ColdFire)",
                     *cached("multi-select delete (ColdFire)", [ms_cmd, sorted(EMU_ENV.items())], ms_body))

        # 6h. v0.28: the Monomachine machines' pages drawn as the Monomachine's (each machine its
        # own screen, none the stock grid), and their choices' detents (WPRS, two choices: four
        # detents a choice, through smp_quant as the stock setter calls it)
        if "smp_quant" in lay:
            from dnfw.mnm import machines as MMx    # noqa: PLC0415
            from dnfw.perc import machines as PMx   # noqa: PLC0415
            kit = 0x4210C08C
            snd0 = kit + 52
            st = ["wait:2", "png:stock"]
            for ty in MMx.TYPES:
                st += [f"poke:{snd0 + 0xDE:#x}:{ty:02x}", "wait:20", f"png:m{ty}"]
            wslot = PMx.PARAMS[3][1]             # DPRO-WAVE's WPRS: the fourth place
            st += [f"poke:{snd0 + 0xDE:#x}:{MMx.TYPES[MMx.NAMES.index('DPRO-WAVE')]:02x}",
                   f"poke:{snd0 + 0x14 + 2 * wslot:#x}:0000", "wait:4"]
            st += [f"call:{lay['smp_quant']:#x}:sound0:{wslot}:0x100"] * 4
            js = work / "mnmpages.json"
            mp_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                      "--snapshot", snap, "--steps", ",".join(st), "--png-dir", work / "mnmpages", "--json", js]

            def mp_body(tdir):
                rc, out = run("mnm pages", mp_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and js.exists():
                    r = json.loads(js.read_text())
                    shots = {n: pathlib.Path(r["screens"][n]).read_bytes() for n in r["screens"]}
                    pages = [shots[f"m{ty}"] for ty in MMx.TYPES]
                    d0 = [c["d0"] for c in r["direct_calls"]]
                    top = PMx.PARAMS[3][3]
                    on = (95 * 2 * top + 127) // 254 << 8
                    facts = {"each machine its own page, none the stock grid":
                             len(set(pages)) == len(pages) and shots["stock"] not in pages,
                             "WPRS: three detents keep OFF, the fourth gives ON": d0 == [0, 0, 0, on]}
                    good = all(facts.values())
                    why = str(facts) + f" d0 {d0}"
                return good, ("the five Monomachine pages drawn, each its own; a two-choice control "
                              "four detents a choice" if good else why)
            gate("Monomachine pages and detents (ColdFire)",
                 *cached("Monomachine pages and detents (ColdFire)", [mp_cmd, sorted(EMU_ENV.items())], mp_body))

        # 6j. v0.30: a stock question's keys are stock's (a user's report: on a sample track, the
        # OS update's "UPGRADE OS NOW?" answered by our page; v0.29's save question), and a YES
        # with another key held (TRIG + YES) is stock's. On a GRID track's page: TRIG 1 held,
        # YES: no menu. FUNC + SETTINGS's SAVE ALL question (d0 forced at 0x4005f5c6: the
        # emulator's project was never saved, so stock offers the slot list instead) is seen
        # up (smp_question_up 1); its YES is the question's (it closes, no menu); back on the
        # page, YES opens the menu, NO closes it
        if "smp_question_up" in lay:
            kit = 0x4210C08C
            Q, H, S = lay["smp_question_up"], lay["smp_held_lo"], lay["slc_state"]
            qs = (f"wait:3,poke:{kit + 52 + 0xDE:#x}:0c,wait:4,tap:2,wait:6,call:{Q:#x},press:25,wait:2,yes,"
                  f"wait:4,mem:{H:#x}:4,release:25,wait:6,mem:{S:#x}:4,mem:{H:#x}:4,press:17,wait:2,tap:8,"
                  f"wait:2,release:17,wait:20,png:q,call:{Q:#x},yes,wait:30,mem:{S:#x}:4,call:{Q:#x},tap:2,"
                  f"wait:6,yes,wait:6,png:m,mem:{S:#x}:4,no,wait:6,mem:{S:#x}:4")
            qjs = work / "question.json"
            q_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                     "--snapshot", snap, "--set-d0-at", "0x4005f5c6:0", "--steps", qs,
                     "--png-dir", work / "question", "--json", qjs]

            def q_body(tdir):
                rc, out = run("stock question", q_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and qjs.exists():
                    r = json.loads(qjs.read_text())
                    m = r["memory"]
                    d0 = [c["d0"] for c in r["direct_calls"]]
                    shots = {n: pathlib.Path(r["screens"][n]).read_bytes() for n in ("q", "m")}
                    facts = {"TRIG 1 held: seen held": m[hex(H)] == "02000000",
                             "TRIG 1 + YES: stock's, no menu": int(m[hex(S)], 16) == 0,
                             "let go: nothing held": m[f"{hex(H)}@2"] == "00000000",
                             "the question seen up, then gone": d0 == [0, 1, 0],
                             "its YES the question's: no menu": int(m[f"{hex(S)}@3"], 16) == 0,
                             "then YES on the page opens the menu, NO closes it":
                             int(m[f"{hex(S)}@4"], 16) != 0 and int(m[f"{hex(S)}@5"], 16) == 0,
                             "the question drawn": shots["q"] != shots["m"]}
                    good = all(facts.values())
                    why = f"{facts} d0={d0} mem={m}"
                return good, ("a stock question's YES is the question's; TRIG + YES is stock's; the page's "
                              "own YES still opens its menu" if good else why)
            gate("stock questions and held keys (ColdFire)",
                 *cached("stock questions and held keys (ColdFire)", [q_cmd, sorted(EMU_ENV.items())], q_body))

        # 6k. v0.30: MACHINE SEL from one sample machine to another keeps SAMP (owner: the stock
        # commit resets the sound to the new machine's defaults, SAMP to OFF). Track 1 on
        # ONESHOT with SAMP 5; MACHINE SEL, DOWN, YES: the next sample machine, SAMP still 5
        if "smp_machine_commit" in lay:
            kit = 0x4210C08C
            sa, ty = kit + 52 + 20 + 2 * 43, kit + 52 + 0xDE
            ks = (f"wait:3,poke:{ty:#x}:08,poke:{sa:#x}:0500,wait:4,tap:2,wait:6,func-src,wait:20,down,wait:4,"
                  f"yes,wait:20,types,mem:{sa:#x}:2")
            kjs = work / "keepsamp.json"
            k_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                     "--snapshot", snap, "--steps", ks, "--png-dir", work / "keepsamp", "--json", kjs]

            def k_body(tdir):
                rc, out = run("keep SAMP", k_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and kjs.exists():
                    r = json.loads(kjs.read_text())
                    m = r["memory"]
                    types = m.get("types@0") or [None]
                    facts = {"the next sample machine chosen": types[0] == 9,
                             "SAMP kept": m.get(hex(sa)) == "0500"}
                    good = all(facts.values())
                    why = f"{facts} types={types} mem={m}"
                return good, ("MACHINE SEL from ONESHOT to the next sample machine keeps SAMP" if good else why)
            gate("SAMP kept across sample machines (ColdFire)",
                 *cached("SAMP kept across sample machines (ColdFire)", [k_cmd, sorted(EMU_ENV.items())], k_body))

        # 7. unit tests
        if sharc is not None:                   # v0.25: the runner beside the rest
            print("  (waiting for the SHARC runner)", flush=True)
            sharc.join()
            gate("SHARC runner", *(sharc_box[0] if sharc_box else (False, "the runner did not finish")))
        tests = [t for t in TESTS if (ROOT / t).exists()]
        py_cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not slow", *tests]

        def py_body(tdir):
            rc, out = run("pytest", py_cmd, logs, env={"PYTHONPATH": "src"}, trace=tdir)
            return rc == 0, out.strip().splitlines()[-1] if out.strip() else ""
        gate("unit tests", *cached("unit tests", [py_cmd], py_body))

    except Stop as s:
        for proc in list(LIVE):                 # the SHARC runner, if it is still going
            proc.kill()
        print(f"\nGATE FAILED at: {s}\n\n  DO NOT FLASH {a.build.name}.\n  Logs: {logs}")
        return 1

    record = {"build": a.build.name, "sha256": sha, "stock": a.stock.name,
              "date": datetime.datetime.now().isoformat(timespec="seconds"),
              "gates": results, "logs": str(logs),
              "reused": {k: f"the pass of {v}: every file it read is byte-identical" for k, v in reused.items()}}
    out = a.build.with_name(a.build.name + ".gate.json")
    out.write_text(json.dumps(record, indent=2))
    print(f"ALL GATES PASS on sha256 {sha[:16]}…\n  record: {out}\n\n"
          f"  CLEARED TO FLASH: {a.build.name}\n  (only this exact file; any change needs a new gate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
