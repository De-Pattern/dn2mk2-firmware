"""Every safety gate, on the exact .syx you will flash. Nothing is cleared without it.

    DT2_SECTIONS=/path/to/stock-1.11-sections \\
    python scripts/ship_gate.py Digitone_II_OS1.11.syx build.syx \\
        [--venv ../digikit/.venv/bin/python] [--digikit-sharc ../digikit-wt-sharcemu] \\
        [--only STEP[,STEP...]] [--list]

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
5. **boot from reset** (`emu_boot_check.py`): boots and draws its UI, no fault (v0.37: and the
   start-up animation's first frame is s!Rwa²'s).
5b. **start-up animation** (v0.37, `emu_aniz_check.py`): from the snapshot before the intro,
   with the build's hook and appended area installed, every frame (v0.39: 38, his own), each his, in
   order, to the intro's last frame.
6. **engine + LOAD/SAVE** (`emu_boot_engine.py`): the evaluator runs clean under the
   real loader; CODE chunks intact; machine types survive a SAVE/LOAD round trip.
6b. **sample link** (v0.16, `emu_waverider_menu.py`'s `link16`): on the ColdFire, the
   +Drive's pool image loads into a Python DSP over the fast link (one packet lost and
   resent), commands included; with nothing getting through, the loader stops; a
   recording comes back over TDM and is written to a Python +Drive. Every byte checked,
   and every period the frame's routing words (0xa5a..) are stock's (v0.20). v0.38 (`live`):
   22 samples added live and 3 recordings, one after another, each into the first empty
   slot past the power-on count; each must play by the DSP's own rule (`slot_plays`: the
   magic, the count, the entry), its frames the image's; a recording while it records.
6p. **per-project pools** (v0.38, `emu_waverider_menu.py`'s `link16` `pools`, scripts/emu_pools.py):
   the OS's LOAD, NEW and SAVE AS through the build's detours; each project its own slots, the
   legacy pool for old ones; power cuts after every sector; the DSP never another project's sample.
6e. **ERASE MOD DATA** (v0.39, `emu_erase.py`, docs/erase-mod-data.md): through the real keys
   (+DRIVE, RIGHT, two questions; NO at either erases nothing) and link command 28, on a Python
   +Drive logging every command: TRIM only in the mod's four regions, covering them exactly,
   headers first; stock areas and gaps byte-identical; everything reads erased; no write
   after the first TRIM; a bad card and a TRIM error fail at their sector; a power-on after
   cuts at seven points boots with an empty pool, and after the whole erase as a fresh install.
6s. **DIRECT JUMP** (`emu_jump.py`, docs/jump.md): the sequencer ticked through stock's own ISR;
   off is stock's state every tick; on, every track goes on from its own step (Elektron's rule); a cue
   that is not the PTN view's stays stock's; the setting persists in its sector.
6q. **UI fuzz** (v0.33, `emu_fuzz_ui.py`): the sample pages driven at random, two seeds.
   v0.34 (docs/timing-model.md): with the audio interrupt firing on its own at its real
   cadence through the real vectors, preempting the mod's UI code; a CPU exception, the
   interrupt no longer delivered, or audio frames overrunning their budget fail a seed.
6s. **parameter slides** (`emu_slides.py`, the build and stock 1.11): a slide's ramp exact per
   frame and landing on the locks; SLIDE off and every lock table identical to stock's.
7. **unit tests** (`pytest -m "not slow"` on the safety, mod, PERC and filter tests; v0.38: on
   both cores, pytest-xdist `-n 2 --dist load`, the same tests and the same pass line).

The SHARC runner's parts (v0.34): decode/map/voice/guard, stress (K = 3 and the memory-cost
clock), garbage, **wipe** (the output guard really resets a poisoned voice and records it),
smp, link/rec/pvmix/tdm, stock (ping until v0.44), mnm/frame.

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

**v0.38 (owner, 2026-11-01): faster, with nothing less checked.** The numbers above name the
steps; they run in this order (`--list`): preflight, ColdFire code current, the build is this
tree's, DSP identity, DSP hardware rules, the C symbols in the layout, the ColdFire instruction
set, then the unit tests (both cores), then the SHARC runner starts beside the ColdFire emulator
steps, which run quickest first and the hour-long dead link last. The SHARC runner's parts run
quickest first too, and a part that fails stops the gate when the ColdFire step under way ends,
not an hour later. Every check is the same one, on the same inputs: the order is all that moved.

`--only STEP[,STEP...]` runs just those steps on the build (a SHARC runner step's name, e.g.
`chords`, names its part). Each step's pass goes into the same reuse cache, traced exactly as in
a full run (the setup, which makes every step's commands, runs whole either way, so a step's
commands and this script's own inputs are the same). It never prints the clearance and never
writes the build's `.gate.json`: only a full run clears a build.

The workflow: when a change touches a step's inputs, run that step alone with `--only` first,
until it passes. Then run the full gate, and make no edit to a test or a script while it runs:
the full run reuses the standalone passes only while nothing they read has changed.
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
    if "mchunk_code_end" in lay:  # the machines chunk: the shims, then strings and tables
        out[lay["slot_shim"]] = [(lay["slot_shim"], lay["name_long_5"])]
    return out
# v0.40 (owner, 2026-11-05): the one build the missing Monomachine golden runs may be excepted
# for -- its DSP image (section 7) and the MnM code and test as they were at v0.39 (dbbe804).
# Any change to these ends the exception: the golden runs must exist again.
MNM_EXC_SEC7 = "1864d691b2f91bc8006580ab4a07701b1b7644be67fb1f5663429aabc7496ed0"
MNM_EXC_TREES = {"src/dnfw/mnm": "c27c4179af8142a94794fcafac097b5b99edd267",
                 "test/test_mnm.py": "cbe70e82073139d8f21ba0bb58972a927ef74016"}
# without the golden runs test_mnm collects only its 8 tests that need none (they skip as a
# module); its 366 golden cases are not collected at all (measured on v0.39's tree, 2026-11-05)
MNM_EXC_REST = 8
TESTS = ["test/test_safety.py", "test/test_mods_list.py", "test/test_mods_platform.py",
         "test/test_waverider_mod.py", "test/test_waverider_dsp.py",
         "test/test_waverider_pages.py",                    # v0.45: test_ping_coldfire/_live dropped with PING
         "test/test_shft_live.py", "test/test_mnm.py",
         "test/test_gran_live.py", "test/test_perc_live.py", "test/test_sampler.py",
         "test/test_sources.py", "test/test_md_ui.py", "test/test_patcher.py",
         "test/test_sampler_relatch.py", "test/test_pools.py",
         "test/test_gate_cache_foreign.py",                 # v0.48: the cache's cross-worktree guard and its control
         "test/test_slides.py",
         "test/test_libtree.py", "test/test_web_tool.py"]   # v0.40: nested folders (the model, the page's levels)
HIT = re.compile(r"^\s+([0-9a-f]{8}):", re.M)

# v0.38 (owner, 2026-11-01): the steps by name, for --only and --list, in the order a full run
# takes them. The quick ones, and those new code most often fails, first, so a failure shows
# in minutes; the SHARC runner (gate_sharc.parts(), names "sharc:...") starts after the unit
# tests, on its own core beside the ColdFire emulator steps, and a part that fails stops the
# gate at the next step's end. What each step checks is unchanged, and the steps that are
# never reused (preflight to the ColdFire instruction set) stay so.
FIRST = (("preflight", "preflight (never reused)"),
         ("code-fresh", "ColdFire code current (never reused)"),
         ("rebuild", "the build is this tree's (never reused)"),
         ("dsp-identity", "DSP identity (never reused)"),
         ("hwrules", "DSP hardware rules (never reused)"),
         ("symbols", "every C-keyed check has its symbol in the layout (never reused)"),
         ("coldfire", "ColdFire instruction set, each code chunk and MAIN OS (never reused)"),
         ("overbridge", "Overbridge's code untouched (never reused)"),
         ("unit", "unit tests, both cores (pytest-xdist)"))
# the ColdFire emulator steps: (id, the gate's name), quickest first (v0.37's timings), the
# hour-long dead link last
EMU = (("meter", "DSP load meter (ColdFire)"),
       ("keepsamp", "SAMP kept across sample machines (ColdFire)"),
       ("functurn", "FUNC + turn (ColdFire)"),
       ("aniz", "start-up animation, every frame"),
       ("recorder", "recorder screen (ColdFire)"),
       ("mnmpages", "Monomachine pages and detents (ColdFire)"),
       ("question", "stock questions and held keys (ColdFire)"),
       ("mnmdefaults", "Monomachine start values (ColdFire)"),
       ("alloc", "GRID allocate slice locks (ColdFire)"),
       ("multisel", "multi-select delete (ColdFire)"),
       ("unused", "SELECT UNUSED (ColdFire)"),
       ("hooks", "overlays let go (ColdFire)"),
       ("recflow", "recorder flow (ColdFire)"),
       ("slice", "SLICE menus and SLICES keys (ColdFire)"),
       ("samplist", "sample list, browser, playhead (ColdFire)"),
       ("colsw", "MACHINE SEL columns, SYN held (ColdFire)"),
       ("machines", "every machine through MACHINE SEL's own list; a power-on with ours on the tracks (ColdFire)"),
       ("drive", "+DRIVE browser (ColdFire)"),
       ("drivenav", "+DRIVE keys and long names (ColdFire)"),
       ("jump", "DIRECT JUMP (ColdFire)"),
       ("slides", "parameter slides (ColdFire)"),
       ("bouncegone", "BOUNCE out: an older project's BOUNCE track and recorder trigs (ColdFire)"),
       ("rectext", "RECORDER text inside its places, every state and R.LEN value (ColdFire)"),
       ("kbrec", "KEYBOARD kept through grid recording (ColdFire)"),
       ("thres", "THRES on both processors (coupled)"),
       ("fineswap", "STRT/LEN/LOOP fine records swapped in and out (ColdFire)"),
       ("fineknob", "STRT's knob against stock's fine FREQ (ColdFire)"),
       ("link16", "sample link (ColdFire)"),
       ("pools", "per-project pools (ColdFire)"),
       ("erase", "ERASE MOD DATA (ColdFire)"),
       ("engine", "engine + LOAD/SAVE"),
       ("boot", "boot from reset"),
       ("fuzz", "UI fuzz, two seeds, the audio interrupt at its real rate (ColdFire)"),
       ("link16-dead", "sample link, dead link (ColdFire)"))
EMU_ID = {n: i for i, n in EMU}


def sharc_ids() -> dict[str, list[str]]:
    """{'sharc:a+b': [a, b]} for each part of the SHARC runner (gate_sharc.parts())"""
    import gate_sharc                           # noqa: PLC0415
    return {"sharc:" + "+".join(p): p for p in gate_sharc.parts()}


def all_ids() -> list[tuple[str, str]]:
    return ([*FIRST] + [(i, n) for i, n in EMU]
            + [(i, "SHARC runner: " + ",".join(p)) for i, p in sharc_ids().items()])


def resolve_only(spec: str) -> set[str]:
    """--only's list -> step ids. A SHARC runner step's own name (e.g. chords) names its part;
    'sharc' every part. Unknown names are an error."""
    ids = {i for i, _ in all_ids()}
    parts = sharc_ids()
    out = set()
    for x in (s.strip() for s in spec.split(",")):
        if not x:
            continue
        if x in ids:
            out.add(x)
        elif x == "sharc":
            out |= set(parts)
        elif any(x in p for p in parts.values()):
            out |= {i for i, p in parts.items() if x in p}
        elif "sharc:" + x in parts:
            out.add("sharc:" + x)
        else:
            raise SystemExit(f"--only: no step {x!r} (python scripts/ship_gate.py --list)")
    return out


def _frozen(fn):
    """FN with its free variables bound to their values now. A deferred ColdFire step's body
    runs after the rest of the setup, which reuses names (js, g, kit, ...); frozen, it reads
    exactly what it read when it ran in place (v0.37 and before)."""
    if not getattr(fn, "__closure__", None):
        return fn
    import types                                # noqa: PLC0415
    cells = []
    for c in fn.__closure__:
        try:
            cells.append(types.CellType(c.cell_contents))
        except ValueError:                      # not bound yet: left as it is
            cells.append(c)
    new = types.FunctionType(fn.__code__, fn.__globals__, fn.__name__, fn.__defaults__, tuple(cells))
    new.__kwdefaults__ = fn.__kwdefaults__
    return new


def repo_modules() -> set[str]:
    return {str(pathlib.Path(m.__file__).resolve()) for m in list(sys.modules.values())
            if getattr(m, "__file__", None) and pathlib.Path(m.__file__).resolve().is_relative_to(ROOT)}


class Stop(Exception):
    pass


LOWTRAP: dict[int, list[str]] = {}         # v0.46: wild reads seen, per thread (emulib/lowtrap.py)
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
    trap = [ln for ln in out.splitlines() if ln.startswith("LOWTRAP FAIL")]
    if trap:                                    # v0.46: a wild read fails the step it ran in
        LOWTRAP.setdefault(threading.get_ident(), []).append(f"{name}: {trap[0][:600]}")
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
    p.add_argument("stock", type=pathlib.Path, nargs="?", help="Elektron's Digitone_II_OS1.11.syx")
    p.add_argument("build", type=pathlib.Path, nargs="?", help="the exact .syx that will be flashed")
    p.add_argument("--venv", default=str(ROOT.parent / "digikit/.venv/bin/python"),
                   help="python with digikit's emulator deps (unicorn)")
    p.add_argument("--digikit-sharc", default=os.environ.get(
        "DNFW_DIGIKIT_SHARC", str(ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--only", metavar="STEP[,STEP...]",
                   help="run just these steps (--list), each recorded in the reuse cache as a full run "
                        "would; never a gate pass, never the build's .gate.json")
    p.add_argument("--list", action="store_true", help="print the steps' names, in the full run's order")
    a = p.parse_args()

    if a.list:
        for i, n in all_ids():
            print(f"  {i:16s} {n}")
        print("\n  (a SHARC runner step's own name, e.g. chords, names its part; 'sharc' names them all)")
        return 0
    if a.stock is None or a.build is None:
        p.error("the stock .syx and the build are required")
    only = resolve_only(a.only) if a.only is not None else None
    if only is not None and not only:
        p.error("--only names no step")

    def wanted(sid):
        return only is None or sid in only

    if "DT2_SECTIONS" not in os.environ:
        print("DT2_SECTIONS must point at stock 1.11's extracted sections.\n\nDO NOT FLASH.")
        return 2

    build_bytes = read_image(a.build)
    sha = hashlib.sha256(a.build.read_bytes()).hexdigest()
    work = pathlib.Path(tempfile.mkdtemp(prefix="ship_gate_", dir=ROOT / "out"
                                         if (ROOT / "out").is_dir() else None))
    logs = work / "logs"
    logs.mkdir()
    print(f"ship gate: {a.build.name}\n  sha256 {sha}\n  work {work}\n"
          + (f"  ONLY: {', '.join(sorted(only))} (a partial run: never a gate pass)\n" if only is not None else ""),
          flush=True)
    results: dict[str, str] = {}

    def gate(name, ok, detail):
        results[name] = ("PASS: " if ok else "FAIL: ") + detail
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}\n", flush=True)
        if not ok:
            raise Stop(name)

    reused: dict[str, str] = {}
    setup_mods: set[str] = set()                # the repository's modules once the setup is done

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
        LOWTRAP.pop(threading.get_ident(), None)
        ok, detail = body(tdir)
        wild = LOWTRAP.pop(threading.get_ident(), None)
        if wild:                                # v0.46: whatever the step found, a wild read fails it
            ok, detail = False, "a read below 0x40000000 by our code (the v0.44 freeze's kind): " + "; ".join(wild)
        if ok:
            # v0.38: this script's own inputs are the same in a full run and an --only run: the
            # whole setup runs in both, and nothing after it may import a module of ours
            late = repo_modules() - setup_mods
            if own is None and late:
                return False, (f"ship_gate imported {sorted(late)} after its setup: its own inputs would "
                               "differ between a full and an --only run; import it in the setup")
            ins = gate_cache.inputs(tdir, work, logs)
            ins.update(own_inputs(own))
            gate_cache.store(ROOT, name, key, ins, detail, sha)
        return ok, detail

    plan: dict[str, tuple] = {}                 # the ColdFire emulator steps, run in EMU's order

    def later(sid, gname, cname, cmds, body):
        assert EMU_ID.get(gname) == sid, (sid, gname)
        plan[sid] = (gname, cname, cmds, _frozen(body))

    sharc = None
    sharc_box: list = []                        # (ok, detail) of each SHARC part as it ends
    sharc_want: list = []

    def sharc_failed():
        """a SHARC part has failed: stop now, not after the ColdFire steps"""
        bad = [d for ok, d in list(sharc_box) if not ok]
        if bad:
            gate("SHARC runner", False, bad[0])

    try:
        # setup: everything below runs in a full run and in an --only run alike (the build
        # read, its sections written, every step's commands made), so a step's commands and
        # this script's own inputs are the same in both
        stock = load(read_image(a.stock))
        built = load(build_bytes)
        sec3 = built.container.find(3).unpack()
        stock3 = stock.container.find(3).unpack()
        stock7 = stock.container.find(7).unpack()
        sec7 = built.container.find(7).unpack()
        bdir = work / "build"
        bdir.mkdir()
        (bdir / "section_3_MAIN_OS.bin").write_bytes(sec3)
        (work / "stock_section_3_MAIN_OS.bin").write_bytes(stock3)
        dsp_changed = sec7 != stock7
        want7 = dsp.section7(stock7) if dsp_changed else None
        import gate_sharc                       # noqa: PLC0415
        from dnfw.mods import waverider as W    # noqa: PLC0415
        lay = W.SPEC.get("layout", {})

        # 1. preflight
        if wanted("preflight"):
            ok, text = safety.report(safety.preflight(stock, build_bytes))
            (logs / "preflight.log").write_text(text)
            gate("preflight", ok, "bootstrap/updater/meta/Outbox untouched, signature, DSP size"
                 if ok else text[-600:])
        # v0.33: the ColdFire code the build carries is what csrc/ compiles to now (v0.33's
        # first builds carried a waverider_code.json older than three C fixes, and the gate's
        # emulator steps tested the old code; scripts/gen_waverider_code.py --check)
        if wanted("code-fresh"):
            rc_c, out_c = run("code fresh", [sys.executable, "scripts/gen_waverider_code.py", "--check"], logs,
                              env={"PYTHONPATH": str(ROOT / "src")})
            gate("ColdFire code current", rc_c == 0, out_c.strip()[-400:])
        # and the file under test is what this tree builds, byte for byte (so every step below
        # tests these sources, not an older build of them)
        if wanted("rebuild"):
            rb = work / "rebuilt.syx"
            rc_b, out_b = run("rebuild", [sys.executable, "-c", "from dnfw.cli.main import main; main()", "mods", "apply",
                                          a.stock, "--mod", "waverider", "-o", rb], logs, env={"PYTHONPATH": str(ROOT / "src")})
            same_b = rc_b == 0 and rb.exists() and read_image(rb) == build_bytes
            gate("the build is this tree's", same_b, "dnfw mods apply here gives the same file, byte for byte"
                 if same_b else ("it differs: rebuild it from this tree" if rc_b == 0 else out_b[-400:]))

        # 2 + 3. the DSP program
        if dsp_changed:
            if wanted("dsp-identity"):
                same = sec7 == want7
                gate("DSP identity", same, "section 7 is exactly dsp.section7(stock), the image "
                     "the SHARC gate runs" if same else "section 7 is not what the SHARC gate "
                     "tests; its result would not apply to this file")
            # v0.32: the hardware rules no emulator sees (complex-ping's hwrules.py, from a
            # checkout of his digitone-2-modding-skill beside this repository): our code and
            # round each patch, against the stock image's own
            if wanted("hwrules"):
                skill = ROOT.parent / "digitone-2-modding-skill"
                rc, out = run("hwrules", [sys.executable, "scripts/gate_hwrules.py", a.stock, a.build, skill], logs,
                              env={"PYTHONPATH": "src"})
                gate("DSP hardware rules", rc == 0 and "PASS:" in out, out.strip().splitlines()[-1] if out.strip() else
                     "gate_hwrules.py printed nothing")
            # v0.25: beside the ColdFire steps (its own core); v0.38: started after the unit
            # tests, its verdict looked at after each ColdFire step and taken at the end
            # v0.28: the step is scripts/gate_sharc.py's; its reuse record holds what the
            # runner read and that file, not this script or the ColdFire's artefacts
            sharc_want[:] = [p for sid, p in sharc_ids().items() if wanted(sid)]

            def sharc_thread():
                # v0.28: in parts (gate_sharc.parts: together the runner's default steps), each
                # cached on its own; the verdict is every part's
                try:
                    for steps in sharc_want:
                        cmd = gate_sharc.command(a.stock, a.digikit_sharc, steps, "part_" + "_".join(steps))

                        def body(tdir, cmd=cmd, steps=steps):
                            rc, out = run(f"sharc_m5_{'_'.join(steps)}", cmd, logs, trace=tdir)
                            return gate_sharc.verdict(rc, out)
                        ok, detail = cached(f"SHARC runner: {','.join(steps)}", [cmd], body, own=gate_sharc.OWN)
                        sharc_box.append((ok, f"{','.join(steps)}: {detail}"))
                        print(f"  (SHARC runner, {','.join(steps)}: {'PASS' if ok else 'FAIL'})", flush=True)
                        if not ok:
                            break
                except Exception as e:          # noqa: BLE001
                    sharc_box.append((False, f"the runner did not run: {e}"))
        else:
            results["DSP identity"] = results["SHARC runner"] = "n/a: section 7 is stock"
            if only is not None and any(s.startswith("sharc:") or s in ("dsp-identity", "hwrules") for s in only):
                print("  (section 7 is stock: the DSP steps do not apply)", flush=True)

        # v0.30: a check keyed on a C symbol must not be skipped because the symbol never
        # reached the layout (6k was, once: smp_machine_commit was linked but not listed)
        # (v0.38: before the emulator steps; it reads only the C and the layout)
        if wanted("symbols"):
            csrc_text = "".join(f.read_text() for f in (ROOT / "csrc").rglob("*.c"))
            for sym, what in (("smp_question_up", "stock questions and held keys (ColdFire)"),
                              ("smp_machine_commit", "SAMP kept across sample machines (ColdFire)"),
                              ("smp_knob_at", "FUNC + turn (ColdFire)"),
                              ("smp_pl_on", "per-project pools (ColdFire)"),
                              ("jmp_on", "DIRECT JUMP (ColdFire)")):
                if re.search(rf"\b{sym}\b", csrc_text) and sym not in lay:
                    gate(what, False, f"{sym} is in the C but not in the layout: the check cannot run")
            results["symbols"] = "PASS: every C-keyed check has its symbol in the layout"
            print("[PASS] symbols: every C-keyed check has its symbol in the layout\n", flush=True)

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
        for va, at, n, image in (code_chunks if wanted("coldfire") else []):
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
        if wanted("coldfire"):
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

        # 4b. v0.41 (docs/ROADMAP.md 1b, docs/overbridge.md): no byte the build changes lies in an
        # instruction Overbridge's audio path can run (scripts/gate_overbridge.py: from the mode-6
        # packet builder, the USB input to TX, the USB writer, the mode getter, and the audio
        # interrupt up to the link's hook, followed through every branch and call); and the
        # detector's negative control, rooted at a site the build patches, must find it
        if wanted("overbridge"):
            ob_args = [sys.executable, "scripts/gate_overbridge.py", work / "stock_section_3_MAIN_OS.bin",
                       bdir / "section_3_MAIN_OS.bin"]
            rc_o, out_o = run("overbridge", [*ob_args, "--json", work / "overbridge.json"], logs)
            rc_c, out_c = run("overbridge_control", [*ob_args, "--control", "0x400DB092"], logs)
            last = out_o.strip().splitlines()[-1] if out_o.strip() else ""
            good = rc_o == 0 and rc_c == 0 and last.startswith("PASS")
            gate("Overbridge's code untouched", good,
                 last[6:] + " (its negative control found the patched applier)" if good
                 else (out_o[-500:] + " | control: " + out_c[-200:]))

        # 5. boot from reset
        boot_cmd = [a.venv, "-u", "scripts/emu_boot_check.py", bdir / "section_3_MAIN_OS.bin"]
        # v0.37: the build plays the start-up animation (dnfw.bootanim): every frame the stamp
        # shows during the boot, checked bit for bit against his (s!Rwa²'s), all of them shown
        from dnfw.mods import waverider as Wb   # noqa: PLC0415
        anim = hasattr(Wb, "_boot")
        if anim:
            boot_cmd.append("--aniz")

        def boot_body(tdir):
            rc, out = run("boot_check", boot_cmd, logs, trace=tdir)
            good = rc == 0 and "booted and drew its UI" in out
            if anim:
                good = good and ", 0 not his" in out
            return good, ("booted and drew its UI, no fault" + ("; the start-up animation's first frame, "
                          "his" if anim else "") if good else out[-800:])
        later("boot", "boot from reset", "boot from reset", [boot_cmd], boot_body)

        # 5b. v0.37: the start-up animation, every frame. From reset the intro stops after its
        # first frame under the emulator (stock too), so from the snapshot taken just before
        # it, with this build's intro hook and appended area installed as its loader would:
        # every frame (v0.39: s!Rwa²'s own 38), each bit for bit his, in order, to the intro's last frame
        if anim:
            from dnfw import bootanim as BA      # noqa: PLC0415
            n_anim = len(BA.DURATIONS_MS)
            aniz_cmd = [a.venv, "-u", "scripts/emu_aniz_check.py", a.build]

            def aniz_body(tdir):
                rc, out = run("aniz_check", aniz_cmd, logs, trace=tdir)
                good = (rc == 0 and "in order: PASS" in out and f"{n_anim} of {n_anim} distinct, 0 not his" in out
                        and ", 0 wrong; the label" in out and f"over frame(s) [{n_anim - 1}]" in out)
                return good, (f"all {n_anim} frames, each his, in order, to the intro's end; the panel showed "
                              f"each, the version label over the last only" if good else out[-800:])
            later("aniz", "start-up animation, every frame", "start-up animation", [aniz_cmd], aniz_body)

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
        # v0.27: SHFT (7) and GRAN (8) removed: 7 and 8 load as Multi-Mode now; v0.45: PING (6)
        # removed too, so the LOAD bound is stock again and every type above 5 loads as Multi-Mode
        types += ["--filter-type", "2"] + (["--filter-type", "6", "--filter-type", "7",
                                            "--filter-type", "8", "--filter-max", "5"]
                                           if dsp_changed else [])
        eng_cmd = [a.venv, "-u", "scripts/emu_boot_engine.py", "--build", bdir, "--frames", "8", *types]

        def eng_body(tdir):
            rc, out = run("boot_engine", eng_cmd, logs, trace=tdir)
            clean = rc == 0 and "ran clean" in out and "FAIL" not in out and "corrupt" not in out
            return clean, ("evaluator clean, CODE intact, machine and filter types round-trip"
                           if clean else out[-800:])
        later("engine", "engine + LOAD/SAVE", "engine + LOAD/SAVE", [eng_cmd], eng_body)

        # 6b. the sample link on the ColdFire (v0.16): the +Drive's image loaded over the
        # fast link with a packet lost (resent), the loader stopping when nothing gets
        # through (v0.20: the frame's words are never written), and a recording read back
        # and saved -- each against a Python DSP and +Drive
        # (scripts/emu_waverider_menu.py's link16 step)
        from dnfw.mods import waverider as W        # noqa: PLC0415
        lay = W.SPEC.get("layout", {})
        snap = ROOT.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"
        EMU_ENV = {"DT2_MAIN_IMG": str(pathlib.Path(os.environ["DT2_SECTIONS"]) / "section_3_MAIN_OS.bin"),
                   "DNFW_EMU_FLAGS": '{"weakptr": false}',
                   "DNFW_LOWTRAP": "1"}   # v0.46: every emulator step traps wild reads (emulib/lowtrap.py)
        if "smp_tdm_sent" in lay:
            syms = work / "link16_syms.json"
            syms.write_text(json.dumps({k: v for k, v in lay.items() if k.startswith("smp_")}))
            scen = ("save", "fast", "dead", "high", "lowram") if "smp_ram" in lay else ("save", "fast", "dead")
            if "smp_slices_set" in lay:
                scen += ("slices",)             # v0.23: the slice editor's reading and saving
            if "smp_lib_state" in lay:
                scen += ("lib",)                # v0.31: the +Drive's library, bounded to its region
            if "smp_heads" in lay:
                scen += ("live",)               # v0.38: 22 live adds and 3 recordings, each must play
            if "smp_lib_fpar" in lay:
                scen += ("nest",)               # v0.40: folders inside folders over the link, power cuts
            if "smp_rs_done" in lay:
                scen += ("recstore",)           # v0.46: a recording into +DRIVE > RECORDED: exact, power cuts, no room
            if "smp_saved" in lay:
                scen += ("norm",)              # v0.41: takes normalised to full scale (last: it leaves takes in the pool)
            # v0.31: "dead" (every packet lost: the RAM check's four seconds, then seven tries
            # three seconds apart before the loader stops) takes about an hour in the emulator
            # on its own, so it is a step of its own, cached on its own: the gate's run fits
            # the two-hour limit, and a run cut off there keeps whichever step passed
            dead = [sc for sc in scen if sc == "dead"]
            scen = tuple(sc for sc in scen if sc != "dead")
            steps = ",".join(f"link16:{syms}:{sc}" for sc in scen)
            l16_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                       "--build", bdir, "--snapshot", snap, "--steps", steps,
                       "--png-dir", work / "link16"]
            if dead:
                ld_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                          "--build", bdir, "--snapshot", snap, "--steps", f"link16:{syms}:dead",
                          "--png-dir", work / "link16dead"]

                def ld_body(tdir):
                    rc, out = run("link16 dead", ld_cmd, logs, env=EMU_ENV, trace=tdir)
                    oks = re.findall(r"link16 dead: .*\"ok\": (true|false)", out)
                    good = rc == 0 and oks == ["true"]
                    return good, ("dead (nothing gets through): the RAM check gives up after four seconds, "
                                  "the loader tries each chunk seven times and stops, nothing reaches the "
                                  "DSP's routing" if good else out[-800:])
                later("link16-dead", "sample link, dead link (ColdFire)", "sample link, dead link (ColdFire)", [ld_cmd, sorted(EMU_ENV.items())], ld_body)

            def l16_body(tdir):
                rc, out = run("link16", l16_cmd, logs, env=EMU_ENV, trace=tdir)
                oks = re.findall(r"link16 (save|fast|dead|high|lowram|slices|lib|live|nest|recstore|norm): .*\"ok\": (true|false)", out)
                good = rc == 0 and len(oks) == len(scen) and all(v == "true" for _, v in oks)
                return good, ("save, fast (a lost packet resent); every byte loaded and saved; the frame's routing words stock's in "
                              "every period; v0.22: the RAM check first, past 128 MB loaded only when it "
                              "passes (high, lowram); v0.31: the kit's samples first; the +Drive's library written, read back, "
                              "a hole reused, every write inside its region, a small device refused (lib); v0.38: 22 samples "
                              "added live and 3 recordings, one after another, each plays on the DSP by its own rule "
                              "(the count covers it), a recording while it records too (live)"
                              + ("; v0.40: folders inside folders: an old flat library read as it was, a path's "
                                 "levels made once, look-alikes apart, six deep at most, DROP refused with a folder "
                                 "inside, one sector a change, a power cut after every sector of making and of a "
                                 "DELETE leaves a sound tree, a v0.39 reads every name (nest)" if "nest" in scen else "")
                              + ("; v0.46: a recording into +DRIVE > RECORDED: its trimmed frames exact, in RECORDED under "
                                 "its name, the slot marked as that sample, a power cut after any pass leaves no entry or "
                                 "all of it, a slot changed mid-copy stops it, no room writes nothing (recstore)"
                                 if "recstore" in scen else "")
                              + ("; v0.41: takes at 4,000, 32,000 and 10 (-70 dBFS) normalised to full scale, every frame "
                                 "exact, none clipped; an all-zero take stays zero (norm)" if "norm" in scen else "")
                              if good else out[-800:])
            later("link16", "sample link (ColdFire)", "sample link (ColdFire)", [l16_cmd, sorted(EMU_ENV.items())], l16_body)

            # 6p. v0.38: per-project sample pools (csrc/sampler/pools.c, docs/project-pools.md;
            # scripts/emu_pools.py): the OS's own LOAD, NEW and SAVE AS through the build's
            # detours; each project its own slots, the legacy pool for old projects, the lists
            # across a power cycle, corrupted lists and changed frames falling back safely, a
            # power cut after every sector of a change and of a switch, every write inside its
            # region, the image one v0.37 reads; the DSP's directory checked every period:
            # never another project's sample, never one half sent
            if "smp_pl_on" in lay:
                pl_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                          "--build", bdir, "--snapshot", snap, "--steps", f"link16:{syms}:pools",
                          "--png-dir", work / "pools"]

                def pl_body(tdir):
                    rc, out = run("pools", pl_cmd, logs, env=EMU_ENV, trace=tdir)
                    res = work / "pools" / "link16_pools.json"
                    why, good = out[-800:], False
                    if rc == 0 and res.exists():
                        r = json.loads(res.read_text())
                        facts = r.get("facts", {})
                        good = bool(r.get("ok")) and len(facts) >= 16 and all(facts.values())
                        why = json.dumps({k: v for k, v in facts.items() if not v})[:800] or out[-800:]
                    return good, ("per-project pools: LOAD / NEW / SAVE AS through the OS's own code, each project "
                                  "its own slots, old projects today's pool, lists kept across a power cycle, a corrupted "
                                  "list its previous copy, changed frames silent, a power cut after every sector safe, "
                                  "every write in its region, the DSP never another project's sample" if good else why)
                later("pools", "per-project pools (ColdFire)", "per-project pools (ColdFire)",
                      [pl_cmd, sorted(EMU_ENV.items())], pl_body)

            # 6e. v0.39: ERASE MOD DATA (csrc/sampler/erase.c, docs/erase-mod-data.md;
            # scripts/emu_erase.py): the key path (+DRIVE, RIGHT, two questions; NO at either and
            # LEFT erase nothing), link command 28 (a wrong word refused), on a Python +Drive that
            # logs every eMMC command: TRIM only inside the four regions, covering each exactly,
            # headers first, never a write from the first TRIM on; the stock store, the factory
            # buffer and the gaps byte-identical; every region's sector read back erased (0x00
            # and 0xFF cards); a card that keeps a sector and a TRIM error fail at their sector;
            # a power-on after a cut at seven points boots with the pool empty, writing only in
            # its regions, and after the whole erase exactly as on a +Drive never written
            if "smp_er_state" in lay:
                er_js = work / "erase.json"
                er_cmd = [a.venv, "-u", "scripts/emu_erase.py", "--build", bdir, "--snapshot", snap,
                          "--scenario", "all", "--json", er_js, "--png-dir", work / "erase"]

                def er_body(tdir):
                    rc, out = run("erase", er_cmd, logs, env=EMU_ENV, trace=tdir)
                    why, good = out[-800:], False
                    if rc == 0 and er_js.exists():
                        r = json.loads(er_js.read_text())
                        checks = r.get("checks", {})
                        good = bool(r.get("ok")) and len(checks) >= 35 and all(c["ok"] for c in checks.values())
                        why = json.dumps({k: c for k, c in checks.items() if not c["ok"]})[:800] or out[-800:]
                        if good:
                            c = r["commands"]
                            why = (f"ERASE MOD DATA: NO at each question and LEFT erase nothing; three YES: "
                                   f"{c['trims']} TRIM calls (CMD35/36/38), only in the four regions and "
                                   f"covering them exactly, headers first, no write after the first; stock areas "
                                   f"and gaps byte-identical, every region erased and verified ({r['reads']} reads); "
                                   f"link 28 likewise (0xFF card); a kept sector and a TRIM error fail at their "
                                   f"sector; {len(r['boot'])} power-ons after cuts boot empty, the whole erase as a "
                                   f"fresh install; {len(checks)} checks")
                    return good, why
                later("erase", "ERASE MOD DATA (ColdFire)", "ERASE MOD DATA (ColdFire)",
                      [er_cmd, sorted(EMU_ENV.items())], er_body)

        # 6c. the RECORDER screen (v0.22): FUNC+VOICE opens it over any page, its knobs
        # change the recorder and never the track's sound, NO closes it, and the UI keeps
        # drawing throughout (scripts/emu_waverider_menu.py, keys and knob as the panel)
        if "rec_overlay" in lay:
            ov, src = hex(lay["rec_overlay"]), hex(lay["rec_src"])
            steps = (f"wait:5,png:p0,mem:{ov}:4,press:17,wait:3,tap:49,wait:3,release:17,"
                     f"wait:30,mem:{ov}:4,png:a1,spin:0:3,wait:5,mem:{src}:4,spin:0:9,wait:5,mem:{src}:4,png:a2,no,"
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
                    seen = [int(m[k], 16) for k in (ov, f"{ov}@1", f"{ov}@4")]
                    srcs = [int(m[k], 16) for k in (src, f"{src}@3")]     # v0.41: 3 detents, then 9 more
                    shots = [pathlib.Path(r["screens"][n]).read_bytes() for n in ("p0", "a2", "a4")]
                    good = (seen == [0, 1, 0] and srcs == [0, 3] and not r["setter_writes"]
                            and r["screen_frames"] > 0 and shots[1] != shots[0] and shots[1] != shots[2])
                    why = (f"overlay {seen}, src {srcs}, setter writes "
                           f"{len(r['setter_writes'])}, frames {r['screen_frames']}")
                return good, ("FUNC+VOICE opens it, knob A moves SRC four detents a choice (3: none, 12: three; v0.41) with no write to the sound, NO closes it, "
                 "the screen drawn throughout"
                              if good else why)
            later("recorder", "recorder screen (ColdFire)", "recorder screen (ColdFire)", [rec_cmd, sorted(EMU_ENV.items())], rec_body)

        # 6d. after a recording (v0.22; v0.25 as the DT2's): SAVING/NORMALIZING (phase 4) on to
        # TRIM once saved; TRIM's ends move (E, H); FUNC + YES plays the preview while held
        # (a command each way, FUNC's release seen); YES on to FILE NAME (spelt by knob and
        # arrows; FUNC + YES inserts, FUNC + NO deletes), YES on to ASSIGN, a [TRIG] key
        # makes track 3 ONESHOT playing the slot (stock's MACHINE SEL commit and setValue)
        # v0.40: the preview's playhead (the owner: it never moved): held, the frame counter
        # moved on 150 twice (6,400 audio frames, as the audio interrupt would count them), the column drawn moves right each time and the
        # screen with it; let go, none (trim_head_x -1, the screen changed again)
        if "rec_phase" in lay and "rec_pv_on" in lay:
            g = {k: hex(lay.get(k, 0)) for k in ("rec_overlay", "rec_phase", "trim_slot", "trim_n", "trim_s",
                                                  "trim_e", "nm_text", "rec_pv_on", "smp_func_held", "smp_cmds",
                                                  "smp_saved", "trim_head_x")}
            kit = 0x4210C08C                    # the snapshot's live kit ([0x800052a0])
            snd = hex(kit + 52 + 1163 * 2)      # track 3's sound
            steps = (f"wait:3,mem:0x800052a0:4,mem:{snd}:256,poke:{g['trim_slot']}:00000004,"
                     f"poke:{g['trim_n']}:00017700,poke:{g['trim_s']}:00000000,poke:{g['trim_e']}:00017700,"
                     f"poke:{g['smp_saved']}:00000000,poke:{g['rec_overlay']}:00000001,"
                     f"poke:{g['rec_phase']}:00000004,wait:10,mem:{g['rec_phase']}:4,"
                     f"poke:{g['smp_saved']}:00000001,wait:10,mem:{g['rec_phase']}:4,png:t1,spin:4:5,wait:5,"
                     f"mem:{g['trim_s']}:4,spin:7:-3,wait:5,mem:{g['trim_e']}:4,png:t2,spin:5:2,wait:5,png:tz,"
                     f"mem:{g['smp_cmds']}:4,"
                     f"press:17,wait:2,press:10,wait:3,mem:{g['rec_pv_on']}:4,mem:{g['smp_cmds']}:4,"
                     f"mem:{g['trim_head_x']}:4,png:p0,addl:0x4058e8d4:150,wait:3,mem:{g['trim_head_x']}:4,png:p1,"
                     f"addl:0x4058e8d4:150,wait:3,mem:{g['trim_head_x']}:4,png:p2,"
                     f"release:10,wait:3,release:17,wait:3,mem:{g['rec_pv_on']}:4,mem:{g['smp_func_held']}:4,"
                     f"mem:{g['smp_cmds']}:4,mem:{g['trim_head_x']}:4,png:pr,yes,wait:10,mem:{g['rec_phase']}:4,png:n0,spin:0:3,wait:3,right,"
                     f"wait:3,spin:0:2,wait:3,mem:{g['nm_text']}:8,press:17,wait:2,yes,wait:3,release:17,wait:3,"
                     f"mem:{g['nm_text']}:8,press:17,wait:2,no,wait:3,release:17,wait:3,mem:{g['nm_text']}:8,"
                     # v0.33: FUNC + NO steps the cursor back too (owner: held, it clears letter
                     # after letter; the repeat runs on the unit's 1.5 kHz clock, which the
                     # emulator barely moves): "CB", cursor on B -> "CB", cursor on C -> "B"
                     f"press:17,wait:2,press:12,wait:10,release:12,wait:3,release:17,wait:3,mem:{g['nm_text']}:8,"
                     f"png:n1,yes,wait:10,mem:{g['rec_phase']}:4,png:a1,tap:27,"
                     f"wait:20,mem:{g['rec_phase']}:4,mem:{snd}:256,png:r1,mem:{lay['trim_zoom']:#x}:4")
            js = work / "recflow.json"
            flow_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                                            "--build", bdir, "--snapshot", snap, "--steps", steps,
                                            "--png-dir", work / "recflow", "--json", js]

            # the harness keys a repeated read of an address by its place among all reads
            # (emu_waverider_menu.py's mem:): the n-th read of VA, worked out from the steps
            reads = [st.split(":")[1] for st in steps.split(",") if st.startswith("mem:")]

            def nth(va, n):
                k = [i for i, x in enumerate(reads) if x == va][n]
                return va if not n else f"{va}@{k}"

            def flow_body(tdir):
                rc, out = run("recorder flow", flow_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and js.exists():
                    r = json.loads(js.read_text())
                    m = r["memory"]
                    ph, cm, pv = g["rec_phase"], g["smp_cmds"], g["rec_pv_on"]
                    phases = [int(m[nth(ph, k)], 16) for k in range(5)]
                    cmds = [int(m[nth(cm, k)], 16) for k in range(3)]
                    before, after = bytes.fromhex(m[snd]), bytes.fromhex(m[nth(snd, 1)])
                    s0, e0 = int(m[g["trim_s"]], 16), int(m[g["trim_e"]], 16)
                    names = [bytes.fromhex(m[nth(g["nm_text"], k)])[:4] for k in range(3)]
                    hx = g["trim_head_x"]
                    heads = [struct.unpack(">i", bytes.fromhex(m[nth(hx, k)]))[0] for k in range(4)] \
                        if "trim_head_x" in lay else None
                    shot = {k: pathlib.Path(r["screens"][k]).read_bytes() for k in ("p0", "p1", "p2", "pr")}
                    facts = {"kit": m["0x800052a0"] == f"{kit:08x}",
                             "phases": phases == [4, 1, 2, 3, 0],
                             "trim": 0 < s0 < e0 < 0x17700,
                             "preview": int(m[pv], 16) == 1 and int(m[nth(pv, 1)], 16) == 0
                             and cmds[1] == cmds[0] + 1 and cmds[2] == cmds[1] + 1
                             and int(m[g["smp_func_held"]], 16) == 0,
                             "v0.40: the preview's playhead moves with it (held: drawn, further on each "
                             "time, the screen changing) and is gone once let go":
                             heads is not None and 4 <= heads[0] < heads[1] < heads[2] <= 123 and heads[3] == -1
                             and shot["p0"] != shot["p1"] != shot["p2"] != shot["pr"],
                             "name": names == [b"CB\0\0", b"C B\0", b"CB\0\0"],
                             "v0.33: FUNC + NO steps back: a second one takes the letter before (and, held, the rest)":
                             bytes.fromhex(m[nth(g["nm_text"], 3)])[:2] in (b"B\0", b"\0\0"),
                             "oneshot": before[0xDE] != 8 and after[0xDE] == 8,
                             "samp": after[0x6A] == 5,
                             "frames": r["screen_frames"] > 0,
                             "v0.33: F zooms TRIM (drawn)": int(m[f"{lay['trim_zoom']:#x}"], 16) >= 1
                             and pathlib.Path(r["screens"]["tz"]).read_bytes() != pathlib.Path(r["screens"]["t2"]).read_bytes()}
                    good = all(facts.values())
                    why = str(facts) + f" phases {phases} cmds {cmds} names {names} heads {heads}"
                return good, ("SAVING on to TRIM; TRIM's ends move; FUNC + YES previews while held, its playhead "
                              f"moving (columns {heads[:3]}), gone at release; YES on to "
                              "FILE NAME (knob, arrows, FUNC + YES inserts, FUNC + NO deletes), YES on to ASSIGN, "
                              "a [TRIG] key makes track 3 ONESHOT on the slot" if good else why)
            later("recflow", "recorder flow (ColdFire)", "recorder flow (ColdFire)", [flow_cmd, sorted(EMU_ENV.items())], flow_body)

        # 6e. v0.23, SLICE: its menus drawn over the page (the menu, the grid dialog, the
        # editor with a slice table), the editor's keys and knobs moving the picked slice;
        # and in KEYBOARD mode on a SLICE track (SLCE NOTE) each key plays its own note's slice,
        # as the DT2 (v0.48; v0.26..v0.47 ranked the keys' notes): trig 9 C, 10 D, 2 C#
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
            # v0.42: the menus poked over the SLICE track's page itself (slice.c closes a menu whose
            # page the screen does not draw: NiKo's GRID report), not over the snapshot's page
            steps = (f"wait:2,{pk},tap:2,wait:10,png:p0,poke:{g['slc_state']}:00000001,wait:6,png:m,"
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
                     # v0.33: YES on the SLICE track's page answers (the menu, or NO SAMPLE ON
                     # SAMP) after MACHINE SEL (FUNC + SRC, NO: its keys' releases never reach the
                     # mod, so SRC stayed "held" and every YES went to stock: the owner's dead
                     # SLICE/GRID menus, reproduced) and a FUNC combo on the page (FUNC + LEFT)
                     f"{pk},tap:2,wait:10,func-src,wait:20,no,wait:10,png:y0,press:17,wait:2,left,wait:3,release:17,wait:6,yes,wait:8,png:y1,"
                     f"no,wait:6,tap:18,wait:6,press:33,wait:6,release:33,wait:6,press:34,wait:6,release:34,wait:6,"
                     f"press:26,wait:6,release:26,wait:6")
            js = work / "slice.json"
            slc_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                                          "--build", bdir, "--snapshot", snap, "--steps", steps,
                                          "--regs-at", "0x400576ca",
                                          "--png-dir", work / "slice", "--json", js]

            # v0.40 (a user: "sometimes EDIT SLICE POINTS or CREATE SLICE GRID returns CANNOT
            # READ IT"): the menus opened again and again, TR.DET OFF and ON, after CLEAR SLICE
            # GRID and not, while other link work is in flight (the loader, TRIM's read of another
            # slot, LOAD TO PROJECT, a preview, refused chunk reads, a take saving and
            # normalising into the slot, a project switch): each must reach the editor with the
            # slot's waveform and its grid kept; and the editor's LINKED points (the DT2's, knob
            # A): START moves the previous END, END the next START, bounded; UNLINKED as before
            # (emu_waverider_menu.py's link16 scenario slicebusy, the +Drive and DSP played)
            busy_cmd = None
            if "slc_linked" in lay:
                bsyms = work / "slicebusy_syms.json"
                bsyms.write_text(json.dumps({k: v for k, v in lay.items() if k.startswith(("smp_", "slc_")) or k == "wr_draws"}))
                busy_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT,
                            "--build", bdir, "--snapshot", snap, "--steps", f"link16:{bsyms}:slicebusy",
                            "--png-dir", work / "slicebusy"]

            def slc_body(tdir):
                rc, out = run("slice menus", slc_cmd, logs, env=EMU_ENV, trace=tdir)
                busy_ok, busy_why = True, ""
                if busy_cmd:
                    brc, bout = run("slice busy", busy_cmd, logs, env=EMU_ENV, trace=tdir)
                    busy_ok = brc == 0 and re.findall(r"link16 slicebusy: .*\"ok\": (true|false)", bout) == ["true"]
                    busy_why = "" if busy_ok else " slicebusy: " + bout[-1500:]
                why, good = out[-800:] + busy_why, False
                if rc == 0 and js.exists():
                    r = json.loads(js.read_text())
                    m = r["memory"]
                    shots = {n: pathlib.Path(r["screens"][n]).read_bytes() for n in ("p0", "m", "g", "e1", "e2", "y0", "y1")}
                    table = list(_st.unpack(">9I", bytes.fromhex(m[g["slc_sl"]])))
                    notes = [int(x["D4"], 16) for x in r["regs_at"].get("0x400576ca", [])]
                    split = list(_st.unpack(">12I", bytes.fromhex(m[f"{g['slc_sl']}@3"])))
                    facts = {"drawn": len({shots[n] for n in ("p0", "m", "g", "e1", "e2")}) >= 4,
                             "v0.33: YES after FUNC + LEFT answers on a SLICE page": shots["y0"] != shots["y1"],
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
                             # v0.48 (the owner: the DT2's stock behaviour): each key its own
                             # note, the DSP the slice (note - C1) wrapped: trig 9 a C, trig 10
                             # its D (+2), trig 2 its C# (+1), the chromatic keyboard's notes
                             "slice notes": len(notes) == 3 and notes[0] % 12 == 0
                             and notes[1] == notes[0] + 2 and notes[2] == notes[0] + 1}
                    good = all(facts.values()) and busy_ok
                    why = str(facts) + f" notes {notes}" + busy_why
                return good, ("menu, grid dialog and editor drawn; RIGHT picks slice 2, E moves its start, NO "
                 "closes; FUNC + RIGHT splits slice 2, FUNC + LEFT removes it; FUNC + E moves at the normal step; KEYBOARD on a SLICE track: each key its own note (trig 9 C, 10 D, 2 C#), the slice that note's, as the DT2's"
                              + ("; v0.40: EDIT SLICE POINTS and CREATE SLICE GRID (TR.DET OFF, ON, after CLEAR) reach the "
                                 "editor every time while the loader, TRIM's read, LOAD TO PROJECT, a preview, refused reads, "
                                 "a take saving and normalising, a project switch are in flight; LINKED START/END move the "
                                 "neighbour, bounded; UNLINKED as before" if busy_cmd else "")
                              if good else why)
            later("slice", "SLICE menus and SLICES keys (ColdFire)", "SLICE menus and SLICES keys (ColdFire)", [slc_cmd, busy_cmd, sorted(EMU_ENV.items())], slc_body)

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
            # v0.42 (NiKo, v0.40): CREATE RANDOM LOCKS stays open after its YES; another track
            # (TRACK + [TRIG 2]) must close it, YES there must not open it again, and back on the
            # GRID track YES opens it, a page key (tap 5) closes it, YES there not again
            letgo = "slc_letgo" in lay
            if letgo:
                st_, lg_ = f"{lay['slc_state']:#x}", f"{lay['slc_letgo']:#x}"
                steps += (f",yes,wait:6,down,wait:3,yes,wait:6,mem:{st_}:4,"
                          f"press:16,wait:2,press:26,wait:3,release:26,wait:2,release:16,wait:10,"
                          f"mem:0x42431a6c:1,mem:{st_}:4,mem:{lg_}:4,png:t2,yes,wait:8,mem:{st_}:4,png:t2y,no,wait:6,yes,wait:8,mem:{st_}:4,no,wait:6,"
                          f"press:16,wait:2,press:25,wait:3,release:25,wait:2,release:16,wait:10,"
                          f"yes,wait:6,mem:{st_}:4,tap:5,wait:10,mem:{st_}:4,yes,wait:8,mem:{st_}:4,png:p5y,"
                          f"no,wait:4,tap:2,wait:8")
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
                    sts = [int(v, 16) for k, v in m.items() if k.split("@")[0] == hex(lay["slc_state"])]
                    facts = {"three trigs locked": int(m[hex(lay["slc_alloc_n"])], 16) == 3,
                             "linear: slices 1, 2, 3": d0[:3] == [512, 1024, 1536],
                             "closed": sts[:1] == [0],
                             "NO puts the locks back": d0[4:6] == [1024, 1536]}
                    if letgo:
                        trk = [int(v, 16) for k, v in m.items() if k.split("@")[0] == "0x42431a6c"]
                        lgv = [int(v, 16) for k, v in m.items() if k.split("@")[0] == hex(lay["slc_letgo"])]
                        facts.update({"RANDOM stays open after YES": sts[1:2] == [5],
                                      "on track 2": trk == [1],
                                      "another track closes it": sts[2:3] == [0] and lgv[:1] >= [1],
                                      "YES on track 2 opens nothing": sts[3:4] == [0],
                                      "YES again on track 2 opens nothing": sts[4:5] == [0],
                                      "back: YES opens it": sts[5:6] == [5],
                                      "a page key closes it": sts[6:7] == [0],
                                      "YES off the page opens nothing": sts[7:8] == [0]})
                    good = all(facts.values())
                    why = str(facts) + f" {d0} states {sts}"
                return good, ("GRID's ALLOCATE SLICE: LINEAR locks slices 1..3 on three placed trigs; NO after "
                              "RANDOM puts them back" + ("; v0.42: open RANDOM lets go on another track and on another "
                              "page, and YES there opens nothing" if letgo else "") if good else why)
            later("alloc", "GRID allocate slice locks (ColdFire)", "GRID allocate slice locks (ColdFire)", [al_cmd, sorted(EMU_ENV.items())], al_body)

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
                   "wait:12", "png:ph1", f"poke:{lay['smp_pos']:#x}:" + "C000" * 16, "wait:36", "png:ph2"]
            # v0.40 (owner: "the slice machine's on-screen indicators are a little slow to catch
            # up"): the DSP's packets through smp_pos_in, two voices on the page's track (the
            # snapshot's table gives every voice to track 1, the active one): a note at 0x2000,
            # then a second at 0xA000 while the first still sounds -- the playhead is the NEWER
            # note's (v0.30..v0.39: the lower position's, the older note's until it ended);
            # then the first voice retriggered at 0xE000: that one. Each moved column is drawn by the
            # next UI pass after 40 frames (the emulator's frame counter moves only by addl);
            # a playhead that stays in its column asks for no redraw
            ph_new = "smp_pos_in" in lay
            ph_cmd, phjs = None, work / "playhead.json"
            if ph_new:                          # (a run of its own: the list's steps below are timed)
                F_ = "0x4058e8d4"
                pkt = 0x46A23000                 # (above the harness's call stack: SENTINEL + 0x2C00)
                per = f"{lay['smp_periods']:#x}"
                wd = f"{lay['wr_draws']:#x}"

                def packet(n, v0, v1):
                    return [f"poke:{per}:{n:08x}", f"poke:{pkt:#x}:{v0:04x}{v1:04x}" + "ffff" * 14,
                            f"call:{lay['smp_pos_in']:#x}:{pkt:#x}", f"addl:{F_}:40", "wait:3"]
                ps = base + ["wait:6", "tap:2", "wait:6", "png:v0", "mem:0x42431a6c:1"]
                for n, v0, v1, nm in ((100, 0x2000, 0xFFFF, "v1"), (101, 0x2100, 0xA000, "v2"),
                                      (102, 0x2108, 0xA008, "v3"), (103, 0xE000, 0xA010, "v4")):
                    ps += packet(n, v0, v1) + [f"call:{lay['smp_playhead']:#x}:0", f"png:{nm}", mem(lay["wr_draws"])]
                ph_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                          "--snapshot", snap, "--steps", ",".join(ps), "--png-dir", work / "playhead", "--json", phjs]
            st += ["tap:2", "wait:6"]
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
                                 "wait:8", "yes", "wait:6", "png:b1", mem(lay["smp_fb_open"]), "yes", "wait:8", "png:b2",
                                 mem(lay["smp_fb_folder"]), "down", "wait:2", "yes", "wait:8", "png:b3t",
                                 mem(samp0, 2), mem(lay["smp_fb_open"]),
                                 "right", "wait:6", "yes", "wait:8", "png:b3",
                                 mem(samp0, 2), mem(lay["smp_fb_open"]), mem(lay["smp_lst_open"])]
            # (v0.33: YES on a sample in PROJECT RAM ticks it, as the DT2's; RIGHT, LOAD TRK assigns)
            # (v0.31: FUNC + YES opens on the two stores, the cursor on PROJECT RAM: YES enters it)
            # the SAMPLE ACTION menu: into "loops", RIGHT on its sample, DELETE, asked, YES
            st += samp_all(3) + ["wait:10"] + turn(2) + ["wait:10", "press:17", "wait:2", "yes", "wait:2", "release:17", "wait:8",
                                 "yes", "wait:6", "down", "wait:4", "yes", "wait:6", "right", "wait:6", "png:m1", "down", "wait:3",
                                 "down", "wait:3", "yes", "wait:6", "png:m2", "yes", "wait:8", "png:m3",
                                 mem(M + 8 + 16 + 4, 4)]
            # (v0.30: the reach scaled by depth over the loaded samples, held at the ends. The
            # DELETE above emptied slot 1, so two are loaded: slots 0 and 3. SAMP 1 (slot 0):
            # +43 one sample on (SAMP 4), +125 to the last and no further (SAMP 4), +1 none
            # (SAMP 1). v0.29's first form set SAMP 2, the slot just deleted, and counted three)
            # (v0.40: the reference is the voice's target cell, the sound's value or the trig's
            # lock: SAMP 1 there as the sound's, as stock's sync puts it)
            st += [f"poke:0x800052a8:{snd0:08x}", f"poke:{samp0:#x}:0100", f"poke:{cell - 0x800068E4 + 0x80003AF0:#x}:0100",
                   f"onpc:0x400db22c:{cell:#x}:2c00",
                   f"call:{lay['smp_mod_apply']:#x}:0x800068e4", mem(cell, 2),
                   f"onpc:0x400db22c:{cell:#x}:7e00", f"call:{lay['smp_mod_apply']:#x}:0x800068e4", mem(cell, 2),
                   f"onpc:0x400db22c:{cell:#x}:0200", f"call:{lay['smp_mod_apply']:#x}:0x800068e4", mem(cell, 2)]
            # (v0.45: smp_mod_apply sets SAMP to the target first -- a slot never glides -- and
            # then runs the stock apply, which adds the modulation: the modulated value goes in
            # where that apply adds it, on its entry, not before the call)
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
                    o = 0
                    facts = {"playhead drawn and moving": len({shots["p2"], shots["ph1"], shots["ph2"]}) == 3,
                             "v0.27: SAMP set without a turn leaves the list closed": int(m[lo], 16) == 0,
                             "list opens on a turn": int(m[f"{lo}@{1 + o}"], 16) == 1,
                             "DOWN moves SAMP": m[sp] == "0500",
                             "NO puts it back and closes": m[f"{sp}@{3 + o}"] == "0200" and int(m[f"{lo}@{4 + o}"], 16) == 0,
                             "browser opens, a folder entered": int(m[fo], 16) == 1 and int(m[ff], 16) == 0
                             and shots["b1"] != shots["b2"],
                             "v0.33: YES on a sample ticks it: SAMP kept, the browser up":
                             m[f"{sp}@{7 + o}"] == "0300" and int(m[f"{fo}@{8 + o}"], 16) == 1,
                             "RIGHT, LOAD TRK: SAMP, both closed": m[f"{sp}@{9 + o}"] == "0100" and int(m[f"{fo}@{10 + o}"], 16) == 0
                             and int(m[f"{lo}@{11 + o}"], 16) == 0,
                             "DELETE in the SAMPLE ACTION menu empties the slot": m[hex(M + 28)] == "00000000"
                             and len({pathlib.Path(r["screens"][n]).read_bytes() for n in ("m1", "m2", "m3")}) == 3,
                             "modulated SAMP through the loaded slots, by depth, held at the last":
                             [m[ce], m[f"{ce}@{14 + o}"], m[f"{ce}@{15 + o}"]] == ["0400", "0400", "0100"]}
                    if ph_new:
                        prc, pout = run("playhead", ph_cmd, logs, env=EMU_ENV, trace=tdir)
                        pr = json.loads(phjs.read_text()) if prc == 0 and phjs.exists() else {"memory": {}, "screens": {}}
                        pm = pr["memory"]
                        heads = [c["d0"] for c in pr.get("direct_calls", []) if int(c["fn"], 16) == lay["smp_playhead"]]
                        sh = {n: pathlib.Path(pr["screens"][n]).read_bytes() if n in pr["screens"] else b""
                              for n in ("v0", "v1", "v2", "v3", "v4")}
                        dr = [int(pm[k], 16) for k in (wd, f"{wd}@2", f"{wd}@3", f"{wd}@4") if k in pm]
                        facts["v0.40: the newest note's playhead (0x2000, then 0xA000 over 0x2100, 0xA008, the first voice again at 0xE000)"] = (
                            pm.get("0x42431a6c") == "00" and heads == [0x2000, 0xA000, 0xA008, 0xE000])
                        facts["v0.40: a moved playhead drawn at the next pass, a still one not redrawn"] = (
                            len(dr) == 4 and sh["v1"] != sh["v0"] and sh["v2"] != sh["v1"] and dr[1] > dr[0]
                            and dr[2] == dr[1] and sh["v3"] == sh["v2"] and sh["v4"] != sh["v3"] and dr[3] > dr[2])
                        why_ph = f" playheads {heads} draws {dr}"
                    else:
                        why_ph = ""
                    good = all(facts.values())
                    why = str(facts) + why_ph
                return good, ("the playhead drawn where the DSP says"
                              + ("; v0.40: the newest note's, drawn at the next pass when its column moves, no redraw when it does not"
                                 if ph_new else "") + "; SAMP set without a turn opens nothing, a turn opens the list, DOWN moves it, NO "
                              "puts it back; FUNC + YES's browser enters a folder, YES ticks a sample and RIGHT, LOAD TRK assigns it; "
                              "its SAMPLE ACTION menu deletes; modulation on SAMP steps through the loaded slots" if good else why)
            later("samplist", "sample list, browser, playhead (ColdFire)", "sample list, browser, playhead (ColdFire)", [sl_cmd, ph_cmd, sorted(EMU_ENV.items())], sl_body)

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
                    "wait:10", "press:17", "wait:2", "yes", "wait:2", "release:17", "wait:8", "yes", "wait:6",
                    f"call:{fbc:#x}",
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
                later("multisel", "multi-select delete (ColdFire)", "multi-select delete (ColdFire)", [ms_cmd, sorted(EMU_ENV.items())], ms_body)

            # 6i2. v0.45: SELECT UNUSED (the DT2's 13.6.6; Wolljamin). Slots 0..7 loaded. Used: pattern
            # 0's kit, track 0 (ONESHOT) on SAMP 2 (slot 1); pattern 5's kit, track 3 on SAMP 4
            # (slot 3); a SAMP p-lock in pattern 5's table, track 3, step 0, on SAMP 7 (slot 6).
            # A decoy: pattern 7's track 0 is an FM machine whose slot-43 byte is 8 (slot 7):
            # not a sample machine, so not a use. Every other kit's types poked to 0 (FM).
            # SELECT UNUSED marks {0, 2, 4, 5, 7} (5); UNLOAD empties exactly those
            if "smp_fb_mark_unused" in lay:
                P0, PSTR, KSTR = 0x4121898C, 122478, 23921
                d2 = bytearray(d[:0xC10])
                for k in range(8):
                    struct.pack_into("<IIfI", d2, 8 + 16 * k, 0x84001000 + 0x40000 * k, 24000, 1.0, 1)
                us = list(base) + [f"poke:{M:#x}:{d2.hex()}"]
                for n in range(128):
                    for t in range(16):
                        if n == 0 or (n, t) == (5, 3):
                            continue
                        us.append(f"poke:{kit + KSTR * n + 52 + 1163 * t + 0xDE:#x}:00")
                us += [f"poke:{kit + 52 + 1163 * t + 0x6A:#x}:0000" for t in range(1, 16)]
                us += [f"poke:{kit + 52 + 0x6A:#x}:0200",
                       f"poke:{kit + KSTR * 5 + 52 + 1163 * 3 + 0xDE:#x}:08",
                       f"poke:{kit + KSTR * 5 + 52 + 1163 * 3 + 0x6A:#x}:0400",
                       f"poke:{kit + KSTR * 7 + 52 + 0xDE:#x}:00",
                       f"poke:{kit + KSTR * 7 + 52 + 0x6A:#x}:0800"]
                for n in range(128):                    # every pattern's SAMP index: no lock
                    tb = P0 + PSTR * n + 97872
                    us.append(f"poke:{tb + 20640:#x}:" + "ff" * (101 * 16))
                tb5 = P0 + PSTR * 5 + 97872
                us += [f"poke:{tb5 + 258 * 79:#x}:2b03" + "0700" + "ffff" * 127,
                       f"poke:{tb5 + 20640 + 101 * 3 + 43:#x}:4f",
                       "wait:4", f"call:{lay['smp_fb_mark_unused']:#x}"]
                us += [f"call:{lay['smp_fb_marked']:#x}:{k}" for k in range(8)]
                us += [f"call:{lay['smp_fb_delete']:#x}:0:0xffffffff", "wait:4"] + [mem(M + 8 + 16 * k + 4) for k in range(8)]
                ujs, usf = work / "unused.json", work / "unused.steps"
                usf.write_text(",".join(us))
                us_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                          "--snapshot", snap, "--steps", f"@{usf}", "--png-dir", work / "unused", "--json", ujs]

                def us_body(tdir):
                    rc, out = run("select unused", us_cmd, logs, env=EMU_ENV, trace=tdir)
                    why, good = out[-800:], False
                    if rc == 0 and ujs.exists():
                        r = json.loads(ujs.read_text())
                        m = r["memory"]
                        d0 = [int(str(c.get("d0")), 0) if c.get("d0") is not None else None
                              for c in r.get("direct_calls", [])]
                        fr = [int(m[hex(M + 8 + 16 * k + 4)], 16) for k in range(8)]
                        facts = {"five unused marked": d0[:1] == [5],
                                 "the marks are 0, 2, 4, 5, 7": [x & 1 for x in d0[1:9]] == [1, 0, 1, 0, 1, 1, 0, 1],
                                 "UNLOAD empties them, keeps 1, 3, 6 (a kit's SAMP, another pattern's kit, "
                                 "another pattern's SAMP lock; an FM track's byte ignored)":
                                 [x != 0 for x in fr] == [False, True, False, True, False, False, True, False]}
                        good = all(facts.values())
                        why = f"{facts} d0={d0} frames={fr}"
                    return good, ("SELECT UNUSED marks the loaded slots no pattern's kit or SAMP lock uses (5 of 8: a "
                                  "kit's SAMP, another pattern's kit, a lock in another pattern, an FM track's byte "
                                  "ignored); UNLOAD empties exactly those" if good else why)
                later("unused", "SELECT UNUSED (ColdFire)", "SELECT UNUSED (ColdFire)", [us_cmd, sorted(EMU_ENV.items())], us_body)

            # 6l. v0.31: the browser's two stores and the +Drive's library. A library of three
            # samples (two in INCOMING, one in DRUMS) put in its RAM as lib.c reads it at
            # power-on; FUNC + YES opens on the two stores, UP to +DRIVE, YES: its folders
            # (2); YES into the first (2 samples); YES ticks one (1 selected); RIGHT, LOAD TO
            # PROJ (the first action), YES: queued (pending); NO: back to +DRIVE's folders;
            # NO: back to the two stores; NO: closed
            if "smp_fb_store" in lay and "smp_lp_queued" in lay:
                import zlib as _z                # noqa: F401
                LRAM = SMx.MIRROR + 0x100000
                LDATA = 0x700000 + 1 + 256 + 4

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
                idx = lent(LDATA, 1000, 0, "inc one") + lent(LDATA + 4, 1000, 0, "inc two") + lent(LDATA + 8, 500, 2, "drum one")
                fold = b"INCOMING".ljust(32, b"\0") + b"RECORDED".ljust(32, b"\0") + b"DRUMS".ljust(32, b"\0")
                lsteps = [f"poke:{LRAM + 0x200:#x}:{idx.hex()}", f"poke:{LRAM + 0x200 + 2048 * 64:#x}:{fold.hex()}",
                          f"poke:{lay['smp_lib_state']:#x}:00000002", f"call:{lay['smp_lib_refresh']:#x}"]
                fbs, pend = lay["smp_fb_store"], lay["smp_lib_pending"]
                ds = base + lead + lsteps + samp_all(3) + [f"poke:{lay['smp_overlay_dirty']:#x}:00000001", "wait:10"] + turn(2) + [
                    "wait:10", "press:17", "wait:2", "yes", "wait:2", "release:17", "wait:8", "png:d0", mem(fbs),
                    "up", "wait:4", "yes", "wait:6", "png:d1", mem(fbs), f"call:{fbc:#x}",
                    "yes", "wait:6", "png:d2", f"call:{fbc:#x}", "yes", "wait:6", "png:d3", f"call:{fbm:#x}",
                    # v0.33: FUNC + YES held on a sample previews it (+DRIVE's: asked of the
                    # loader); let go, it stops
                    "press:17", "wait:2", "press:10", "wait:6", mem(lay["smp_pv_state"]),
                    "release:10", "wait:2", "release:17", "wait:4", mem(lay["smp_pv_state"]), f"call:{fbm:#x}",
                    "right", "wait:6", "png:d4", "yes", "wait:6", mem(lay["smp_lp_queued"]),
                    "no", "wait:6", mem(lay["smp_fb_folder"]), mem(fbs), "no", "wait:6", mem(fbs),
                    "no", "wait:6", mem(lay["smp_fb_open"]),
                    # v0.33: MOVE SELECTED, then MOVE HERE (the DT2's 13.6.5): open again (on
                    # +DRIVE now), INCOMING, tick "inc one", RIGHT, MOVE SELECT (the fourth),
                    # NO up to the folders, DOWN twice to DRUMS, RIGHT, MOVE HERE (the third): DRUMS
                    # then holds two
                    "press:17", "wait:2", "yes", "wait:2", "release:17", "wait:8", "yes", "wait:6", "yes", "wait:6",
                    "yes", "wait:4", "right", "wait:4", "down", "wait:2", "down", "wait:2", "down", "wait:2", "yes", "wait:4",
                    "no", "wait:6", "down", "wait:4", "down", "wait:4", "right", "wait:4", "png:mv", "down", "wait:2", "down", "wait:2",
                    "yes", "wait:6", "yes", "wait:6", f"call:{fbc:#x}", "png:mv2"]
                djs = work / "drive.json"
                d_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                         "--snapshot", snap, "--steps", ",".join(ds), "--png-dir", work / "drive", "--json", djs]
                # v0.40: folders inside folders (takton: a pack's nested folders flattened into
                # many top-level "TRANCE STARTER PAC"s): a three-level library with look-alike
                # names at different levels and an old import's flat folder, driven through
                # every level (scripts/emu_drive_nest.py: its facts; v0.39's code fails them)
                nest = "smp_fb_titletext" in lay
                njs_ = work / "drive_nest.json"
                dn_cmd = [a.venv, "-u", "scripts/emu_drive_nest.py", "--build", bdir, "--snapshot", snap,
                          "--json", njs_, "--png-dir", work / "drive_nest"]

                def d_body(tdir):
                    rc, out = run("+drive browser", d_cmd, logs, env=EMU_ENV, trace=tdir)
                    why, good = out[-800:], False
                    if rc == 0 and djs.exists():
                        r = json.loads(djs.read_text())
                        m = r["memory"]
                        d0 = [int(str(c.get("d0")), 0) for c in r.get("direct_calls", [])][2:]   # (the refresh's, the turn's)
                        sh = [pathlib.Path(r["screens"][n]).read_bytes() for n in ("d0", "d1", "d2", "d3", "d4")]
                        S = hex(fbs)
                        facts = {"opens on the two stores": int(m[S], 16) == 0xFFFFFFFF,
                                 "UP, YES: +DRIVE, its three folders (v0.33: RECORDED shows, named, though empty)":
                                 int(m[f"{S}@1"], 16) == 1 and d0[0:1] == [3],
                                 "YES: INCOMING's two samples": d0[1:2] == [2],
                                 "YES ticks one": d0[2:3] == [1],
                                 "v0.33: FUNC + YES held previews it; let go, it stops":
                                 int(m[hex(lay["smp_pv_state"])], 16) in (1, 2, 3)
                                 and int(m[f"{hex(lay['smp_pv_state'])}@3"], 16) == 0,
                                 "the preview ticks nothing (still one)": d0[3:4] == [1],
                                 "v0.33: MOVE SELECTED, MOVE HERE: DRUMS holds two": d0[4:5] == [2],
                                 "LOAD TO PROJ queues it": int(m[hex(lay["smp_lp_queued"])], 16) == 1,
                                 "NO: +DRIVE's folders": int(m[hex(lay["smp_fb_folder"])], 16) == 0xFFFFFFFF
                                 and int(m[f"{S}@6"], 16) == 1,
                                 "NO: the two stores": int(m[f"{S}@7"], 16) == 0xFFFFFFFF,
                                 "NO: closed": int(m[hex(lay["smp_fb_open"])], 16) == 0,
                                 "each step drawn": len(set(sh)) == 5}
                        good = all(facts.values())
                        why = f"{facts} d0={d0} mem={m}"
                    if good and nest:
                        rc, out = run("+drive nested folders", dn_cmd, logs, env=EMU_ENV, trace=tdir)
                        r = json.loads(njs_.read_text()) if njs_.exists() else {}
                        good = rc == 0 and bool(r.get("ok")) and len(r.get("facts", {})) >= 24
                        why = (json.dumps({k: v for k, v in r.get("facts", {}).items() if not v})[:900]
                               + " " + json.dumps(r.get("seen", {}))[:600]) if r else out[-800:]
                    return good, ("the two stores, +DRIVE's folders and samples, a tick, LOAD TO PROJECT "
                                  "queued, NO back up a level each time and closed at the top"
                                  + ("; v0.40: folders inside folders, three levels (look-alike names, an old "
                                     "flat folder): each level's folders then samples, the path in the title, "
                                     "preview, LOAD TO PROJECT, NO up onto the folder left, MOVE, a folder's "
                                     "FUNC + YES all it holds, SELECT ALL a list's own, CREATE FOLDER inside, "
                                     "DELETE of a folder with folders inside, the rest untouched" if nest else "")
                                  if good else why)
                later("drive", "+DRIVE browser (ColdFire)", "+DRIVE browser (ColdFire)",
                      [d_cmd] + ([dn_cmd] if nest else []) + [sorted(EMU_ENV.items())], d_body)

                # 6l2. v0.39 (the owner, v0.38): +DRIVE's keys as Elektron's lists, and long names
                # as the DT2's. A folder of 17: "SHORT ONE.WAV", then 16 hi-hats whose names are
                # one but for their last two characters (his "AT HIHAT": six rows of "AT BIRDHOUSE
                # HI-HA"). Held DOWN steps on by itself, in the list and in the action menu;
                # FUNC + DOWN a page; a knob turned pushed in a page a detent, unpushed one; D
                # pushed leaves +DRIVE up (stock took it); NO still goes up. An unselected long
                # name is head...tail; the selected one scrolls from its start to its end; moved
                # off, it is head...tail again and the new one starts from its start
                if "smp_fb_rowtext" in lay and "smp_mq_off" in lay:
                    hh = [f"AT BIRDHOUSE HI-HAT CLOSED VEL {k:02d}" for k in range(16)]
                    # v0.41: a user's v0.38 INCOMING folder (his video: hands off, the cursor going
                    # between the top two rows by itself)
                    pab = ["LC_FTR_100_FX_IMPACT_01.WAV", "LC_FTR_100_FX_RISE_01.WAV", "LC_FTR_BASS_A#_02.WAV",
                           "LC_FTR_BASS_G.WAV", "LC_FTR_PERC_01.WAV", "LC_FTR_PERC_07_01.WAV"]
                    nidx = lent(LDATA, 1000, 2, "SHORT ONE.WAV") + b"".join(
                        lent(LDATA + 4 + 4 * k, 1000 + k, 2, nm) for k, nm in enumerate(hh)) + b"".join(
                        lent(LDATA + 4 + 64 + 4 * k, 1000 + k, 0, nm) for k, nm in enumerate(pab))
                    nfold = b"INCOMING".ljust(32, b"\0") + b"RECORDED".ljust(32, b"\0") + b"AT HIHAT".ljust(32, b"\0")
                    TICK = 0x4058E8D4
                    rt, mq, cur, mcur = lay["smp_fb_rowtext"], lay["smp_mq_off"], lay["smp_fb_cur"], lay["smp_fb_mcur"]
                    snap_ = [mem(rt, 144), mem(mq), mem(cur), mem(TICK)]
                    ns = base + lead + [f"poke:{LRAM + 0x200:#x}:{nidx.hex()}", f"poke:{LRAM + 0x200 + 2048 * 64:#x}:{nfold.hex()}",
                                        f"poke:{lay['smp_lib_state']:#x}:00000002", f"call:{lay['smp_lib_refresh']:#x}"]
                    ns += samp_all(3) + [f"poke:{lay['smp_overlay_dirty']:#x}:00000001", "wait:10"] + turn(2) + [
                        "wait:10", "press:17", "wait:2", "yes", "wait:2", "release:17", "wait:8", "up", "wait:4", "yes", "wait:6",
                        f"poke:{lay['smp_fb_folder']:#x}:00000002", f"poke:{cur:#x}:00000000",
                        f"poke:{lay['smp_overlay_dirty']:#x}:00000001", "wait:6", "png:n0"] + snap_      # 0: the folder
                    # (the emulator's clock, the 1.5 kHz ticks at 0x4058e8d4, does not run: it is set
                    # as time would move it: the repeat's 0.4 s then 0.08 s steps, the marquee's 1 s
                    # rest and 0.2 s a character)
                    def clock(t):
                        return [f"poke:{TICK:#x}:{t:08x}", "wait:2"]
                    ns += clock(100) + ["press:14", "wait:2"] + clock(700) + clock(850) + clock(1000) + snap_   # 1: held DOWN
                    ns += ["release:14", "wait:2"] + clock(1300) + snap_ + clock(1600) + snap_                  # 2, 3: let go
                    # 4-19: the marquee of the row it stopped on (selected at tick 1000)
                    MQT = (1100, 1900, 2600, 2900, 3200, 4100, 5000, 6200, 7400, 7700, 8200, 8700, 8850, 9000, 9500, 10900)
                    for t in MQT:
                        ns += clock(t) + snap_
                    ns += ["down", "wait:3"] + snap_                                                               # 20: moved off
                    ns += ["press:17", "wait:2", "down", "wait:2", "release:17", "wait:3"] + snap_                  # 21: FUNC + DOWN
                    ns += [f"poke:{cur:#x}:00000000", "wait:3", "turn:3:1", "wait:3"] + snap_                     # 22: pushed, two detents
                    ns += ["press:44", "wait:3", "release:44", "wait:4", mem(lay["smp_fb_open"]), mem(lay["smp_fb_store"]),
                           mem(lay["smp_fb_folder"]), "png:n1"]
                    ns += ["right", "wait:4"] + clock(20000) + ["press:14", "wait:2"] + clock(20700) + clock(20850) + clock(21000) + [
                           "release:14", "wait:3", mem(mcur), mem(lay["smp_fb_menu"]),
                           "png:n2", "no", "wait:4", "no", "wait:4", mem(lay["smp_fb_folder"]), mem(lay["smp_fb_open"])]
                    # v0.41: in INCOMING with the cursor on its first row, encoder A jittering (+1, -1,
                    # ... with no key, as a worn encoder resting between detents reports): the cursor
                    # moves once at most and stays; then turned by hand, three detents on and three
                    # back: a row a detent, the turn back losing one
                    jit0 = sum(1 for x in ns if x == mem(cur))
                    jrt = sum(1 for x in ns if x == mem(rt, 144))
                    ns += [f"poke:{lay['smp_fb_folder']:#x}:00000000", f"poke:{cur:#x}:00000000",
                           f"poke:{lay['smp_overlay_dirty']:#x}:00000001", "wait:6", mem(rt, 144), mem(cur), "png:n3"]
                    for _ in range(6):
                        ns += ["spin:0:1", mem(cur), "spin:0:-1", mem(cur)]
                    ns += ["png:n4"]
                    ns += ["spin:5:1", mem(cur), "spin:5:1", mem(cur), "spin:5:1", mem(cur),
                           "spin:5:-1", mem(cur), "spin:5:-1", mem(cur), "spin:5:-1", mem(cur)]
                    njs = work / "drivenav.json"
                    n_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                             "--snapshot", snap, "--steps", ",".join(ns), "--png-dir", work / "drivenav", "--json", njs]

                    def n_body(tdir):
                        rc, out = run("+drive keys, names", n_cmd, logs, env=EMU_ENV, trace=tdir)
                        why, good = out[-800:], False
                        if rc == 0 and njs.exists():
                            m = json.loads(njs.read_text())["memory"]

                            def at(va, i):          # the I-th read of VA
                                ks = [k for k in m if k == hex(va) or k.startswith(hex(va) + "@")]
                                return m[ks[i]] if i < len(ks) else None

                            def i32(va, i):
                                v = at(va, i)
                                return None if v is None else int.from_bytes(bytes.fromhex(v), "big", signed=True)

                            def rows(i):
                                v = at(rt, i)
                                b = bytes.fromhex(v) if v else bytes(144)
                                return [b[24 * r:24 * r + 24].split(b"\0")[0].decode("ascii", "replace") for r in range(6)]
                            ticks = [i32(TICK, i) for i in range(23)]
                            curs = [i32(cur, i) for i in range(23)]
                            offs = [i32(mq, i) for i in range(23)]
                            r0 = rows(0)

                            W = 21                         # (smp_page.c's FB_W)

                            def ht(nm):                    # head...tail: ten, "...", eight
                                return nm[:10] + "..." + nm[-8:]
                            sel = curs[3]                  # the hi-hat held DOWN stopped on: hh[sel - 1]
                            mq_rows = [rows(i) for i in range(3, 20)]          # (0: let go; 1..16: the marquee)
                            name = hh[sel - 1] if sel and 1 <= sel <= 16 else ""
                            seen = {r for rs in mq_rows for r in rs}
                            top = max(0, min(sel - 2, 17 - 6)) if sel else 0
                            after = rows(20)
                            ntop = max(0, min(curs[20] - 2, 17 - 6)) if curs[20] is not None else 0
                            end = len(name) - W
                            # (selected at tick 1000: a second's rest (1500 ticks), a character each 300 to
                            # its end, a second's rest, then from the start again)

                            def mq_want(t):
                                u = (t - 1000) % (3000 + 300 * end)
                                return 0 if u < 1500 else min(end, (u - 1500) // 300)
                            want = [mq_want(t) for t in MQT]
                            facts = {
                                "a short name whole, its .WAV dropped": r0[0] == "SHORT ONE",
                                "an unselected long name head...tail (\"AT BIRDHOU...D VEL 00\")": r0[1] == ht(hh[0]) and r0[2] == ht(hh[1]),
                                "held DOWN steps on by itself (a press and three repeats)": curs[1] == 4,
                                "let go, it stops": curs[2] == curs[3] == curs[1],
                                "the selected long name starts from its start": bool(name) and mq_rows[1][sel - top] == name[:W],
                                "it scrolls on to its end, a character each 0.2 s, and starts again": offs[4:20] == want
                                and end == 12 and max(want) == end and want[-1] > 0 and 0 in want[want.index(end):]
                                and any(r == name[-W:] for r in mq_rows[1 + want.index(end)]),
                                "only the selected row scrolls": all(r == ht(hh[top + j - 1]) for rs in mq_rows
                                                                     for j, r in enumerate(rs) if top + j != sel and top + j >= 1)
                                and all(rs[sel - top] == name[o:o + W] for rs, o in zip(mq_rows[1:], want)),
                                "DOWN: the next": curs[20] == sel + 1,
                                "moved off: head...tail again": after[sel - ntop] == ht(hh[sel - 1]),
                                "the new one from its start": after[curs[20] - ntop] == hh[curs[20] - 1][:W] and offs[20] == 0,
                                "FUNC + DOWN: a page": curs[21] == min(curs[20] + 6, 16),
                                "a knob pushed in: a page a detent (two)": curs[22] == 12,
                                "D pushed: +DRIVE still up, in its folder": int(m[hex(lay["smp_fb_open"])], 16) == 1
                                and int(m[hex(lay["smp_fb_store"])], 16) == 1 and int(m[hex(lay["smp_fb_folder"])], 16) == 2,
                                "held DOWN in the action menu steps on": i32(mcur, 0) == 4 and int(at(lay["smp_fb_menu"], 0), 16) == 1,
                                "NO: out of the menu, then up a level": i32(lay["smp_fb_folder"], 1) == -1 and i32(lay["smp_fb_open"], 1) == 1}
                            jc = [i32(cur, jit0 + k) for k in range(1 + 12 + 6)]
                            jr = rows(jrt)
                            jit = jc[1:13]
                            facts.update({
                                "INCOMING: the user's six LC_FTR_ samples, the cursor on the first":
                                    jc[0] == 0 and jr[0].startswith("LC_FTR_100") and jr[1].startswith("LC_FTR_100"),
                                "an encoder jittering +1/-1, no key: the cursor moves once at most, then stays (v0.41)":
                                    None not in jit and max(jit) <= 1 and len(set(jit[1:])) == 1,
                                "turned by hand: a row a detent; turned back, the first detent back lost (v0.41)":
                                    None not in jc[13:] and jc[13:16] == [jit[-1] + 1, jit[-1] + 2, jit[-1] + 3]
                                    and jc[16:19] == [jit[-1] + 3, jit[-1] + 2, jit[-1] + 1]})
                            good = all(bool(v) for v in facts.values())
                            why = f"{ {k: v for k, v in facts.items() if not v} } cur={curs} jitter={jc} jrows={jr} off={offs} ticks={ticks} rows0={r0} rows3={rows(3)} rows20={after}"
                        return good, ("held arrows repeat in the list and the action menu, FUNC + DOWN a page, a pushed "
                                      "knob a page a detent, D pushed keeps +DRIVE, NO goes up; long names head...tail, "
                                      "the selected one scrolls to its end and back, moved off it is head...tail again; an encoder jittering +1/-1 moves the cursor once at most (v0.41)"
                                      if good else why[:1500])
                    later("drivenav", "+DRIVE keys and long names (ColdFire)", "+DRIVE keys and long names (ColdFire)",
                          [n_cmd, sorted(EMU_ENV.items())], n_body)

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
            later("mnmpages", "Monomachine pages and detents (ColdFire)", "Monomachine pages and detents (ColdFire)", [mp_cmd, sorted(EMU_ENV.items())], mp_body)

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
                  f"wait:6,yes,wait:6,png:m,mem:{S:#x}:4,no,wait:6,mem:{S:#x}:4,"
                  # v0.41 (the owner, v0.40: "YES opens the slice menu, sometimes" while saving):
                  # FUNC + SETTINGS, YES, and a YES while SAVING is drawn (its view 0x40206e94 at
                  # the list's end), then one on the message after it (0x40206ddc): both stock's,
                  # no menu; smp_question_up sees both up; the message's YES takes it down
                  f"press:17,wait:2,tap:8,wait:2,release:17,wait:20,yes,wait:3,png:s,call:{Q:#x},yes,wait:3,"
                  f"mem:{S:#x}:4,wait:15,png:e,call:{Q:#x},yes,wait:6,mem:{S:#x}:4,call:{Q:#x}")
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
                    d0 = d0 + [None] * (6 - len(d0))
                    facts = {"TRIG 1 held: seen held": m[hex(H)] == "02000000",
                             "TRIG 1 + YES: stock's, no menu": int(m[hex(S)], 16) == 0,
                             "let go: nothing held": m[f"{hex(H)}@2"] == "00000000",
                             # v0.41: after the question's YES the save's message is up (ERROR here:
                             # the emulator has no card), and it is a stock popup too, so the
                             # third probe reads 1 (0 on v0.30..v0.40, which saw only the question)
                             "the question seen up; then the save's message": d0[:3] == [0, 1, 1],
                             "its YES the question's: no menu": int(m[f"{hex(S)}@3"], 16) == 0,
                             "then YES on the page opens the menu, NO closes it":
                             int(m[f"{hex(S)}@4"], 16) != 0 and int(m[f"{hex(S)}@5"], 16) == 0,
                             "the question drawn": shots["q"] != shots["m"],
                             # v0.41
                             "SAVING seen up: YES on it is stock's, no menu": d0[3] == 1 and int(m[f"{hex(S)}@6"], 16) == 0,
                             "the message after it seen up: its YES takes it down, no menu":
                             d0[4] == 1 and d0[5] == 0 and int(m[f"{hex(S)}@7"], 16) == 0}
                    good = all(facts.values())
                    why = f"{facts} d0={d0} mem={m}"
                return good, ("a stock question's YES is the question's; TRIG + YES is stock's; the page's "
                              "own YES still opens its menu; SAVING's and its message's keys are stock's" if good else why)
            later("question", "stock questions and held keys (ColdFire)", "stock questions and held keys (ColdFire)", [q_cmd, sorted(EMU_ENV.items())], q_body)

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
            later("keepsamp", "SAMP kept across sample machines (ColdFire)", "SAMP kept across sample machines (ColdFire)", [k_cmd, sorted(EMU_ENV.items())], k_body)

        # 6m. v0.32: FUNC + turn on our machines' controls (a tester's list; the owner: a control
        # that jumps with FUNC goes on jumping to its next value, one that does not stays put).
        # Stock's jump kept where it is right (PERC's first control, by octaves); a control of
        # choices steps one choice a click the way the knob turned; any other control of ours
        # stays where it was; nothing changes without FUNC, with a stale knob, or on a stock
        # machine. (The emulator's encoders do not move a stock page's value: the setter's own
        # call of smp_quant is made, the knob's last turn poked and its time copied from the UI
        # clock by the stock memcpy.)
        if "smp_knob_at" in lay:
            from dnfw.mnm import machines as MMf      # noqa: PLC0415
            from dnfw.perc import machines as PMf     # noqa: PLC0415
            from dnfw.sampler import machines as SMf  # noqa: PLC0415
            kit = 0x4210C08C
            snd0 = kit + 52
            clock, memcpy = 0x4058E8D4, 0x40134490
            ptch, other = PMf.PARAMS[0][1], PMf.PARAMS[2][1]
            wprs, wlo, wtop = PMf.PARAMS[3][1], PMf.PARAMS[3][2], PMf.PARAMS[3][3]
            w_on = wlo + (95 * 2 * wtop + 127) // 254
            w_off = wlo + (31 * 2 * wtop + 127) // 254
            dwave = MMf.TYPES[MMf.NAMES.index("DPRO-WAVE")]
            q = next(r for r in SMf.QUANT if r[1] == SMf.PLAY_REC and "ONESHOT" in r[0])
            play = SMf.RECORDS[SMf.PLAY_REC][0]
            p_from, p_to = q[3][0], q[3][1]

            rid = {sl: r for r, sl, _lo, _t in PMf.PARAMS}
            rid[play] = SMf.PLAY_REC
            lfo_rec, lfo_slot = 94, 60                # v0.33: an LFO record (stock's, LFO3's first)

            def fcase(ty, slot, old, held, knob, fresh, value):
                s = [f"poke:{snd0 + 0xDE:#x}:{ty:02x}", f"poke:{snd0 + 20 + 2 * slot:#x}:{old:04x}",
                     f"poke:{lay['smp_func_held']:#x}:{held:08x}",
                     f"poke:{lay['smp_knob_d']:#x}:{knob & 0xFFFFFFFF:08x}"]
                s += [f"call:{memcpy:#x}:{lay['smp_knob_at']:#x}:{clock:#x}:4"] if fresh else \
                     [f"poke:{lay['smp_knob_at']:#x}:80000000"]   # (half the clock away: stale)
                r = lfo_rec if slot == lfo_slot else rid[slot]       # (the setter passes the record: v0.33 reads it)
                return s + [f"call:{lay['smp_quant']:#x}:sound0:{slot}:{value:#x}:{r}"]
            cases = [("PERC's first control: stock's octave jump kept", (5, ptch, 0x4000, 1, 1, True, 0x4C00), 0x4C00),
                     ("PERC, another control: it stays put", (5, other, 0x2000, 1, 1, True, 0x7F00), 0x2000),
                     ("DPRO WAVE's WPRS, right: the next choice in one click", (dwave, wprs, w_off << 8, 1, 1, True, 0x0000), w_on << 8),
                     ("DPRO WAVE's WPRS, left: back in one click", (dwave, wprs, w_on << 8, 1, -1, True, 0x7F00), w_off << 8),
                     ("ONESHOT's PLAY, right: the next mode in one click", (8, play, p_from << 8, 1, 1, True, 0x0000), p_to << 8),
                     ("no FUNC: as it is", (5, other, 0x2000, 0, 1, True, 0x2100), 0x2100),
                     ("a stale knob: as it is", (5, other, 0x2000, 1, 1, False, 0x2100), 0x2100),
                     ("a stock machine: as it is", (1, other, 0x2000, 1, 1, True, 0x2100), 0x2100),
                     ("v0.33: an LFO control on PERC: stock's FUNC jump kept", (5, lfo_slot, 0x2000, 1, 1, True, 0x4000), 0x4000),
                     ("v0.33: an LFO control on a Monomachine track: stock's", (dwave, lfo_slot, 0x2000, 1, 1, True, 0x4000), 0x4000),
                     ("v0.33: an LFO control on ONESHOT: stock's", (8, lfo_slot, 0x2000, 1, 1, True, 0x4000), 0x4000)]
            fs = ["wait:3"]
            for _n, args, _w in cases:
                fs += fcase(*args)
            fs += [f"poke:{lay['smp_func_held']:#x}:00000000", f"poke:{snd0 + 0xDE:#x}:01", "wait:4"]
            fjs = work / "functurn.json"
            f_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                     "--snapshot", snap, "--steps", ",".join(fs), "--png-dir", work / "functurn", "--json", fjs]

            def f_body(tdir):
                rc, out = run("FUNC + turn", f_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and fjs.exists():
                    calls = [c for c in json.loads(fjs.read_text())["direct_calls"]
                             if int(str(c.get("fn", "0")), 0) == lay["smp_quant"]]
                    got = [c["d0"] & 0xFFFF for c in calls]
                    facts = {n: (g == w) for (n, _a, w), g in zip(cases, got)}
                    good = len(got) == len(cases) and all(facts.values())
                    why = f"{facts} got={[hex(g) for g in got]}"
                return good, ("FUNC + turn: PERC's first control keeps stock's octave jumps; other controls of ours "
                              "stay put; choices step one a click either way (WPRS, PLAY); no change without FUNC, "
                              "with a stale knob, or on a stock machine" if good else why)
            later("functurn", "FUNC + turn (ColdFire)", "FUNC + turn (ColdFire)", [f_cmd, sorted(EMU_ENV.items())], f_body)

        # 6n. v0.32: the DSP load meter. smp_dsp_load gives the last half second's peak (the
        # idle packets' unit 18, permille) in percent, rounded, and -1 when none came in the last
        # second; a PERC page with FUNC held draws it in the tempo's place
        if "smp_dsp_load" in lay:
            kit = 0x4210C08C
            ms = ["wait:3", f"poke:{kit + 52 + 0xDE:#x}:05", "wait:20", "png:tempo",
                  f"poke:{lay['smp_load_peak']:#x}:00000274",                  # 628 permille
                  # (the emulator runs no audio periods: the clock and the packet's time are set)
                  f"poke:{lay['smp_periods']:#x}:00001000", f"poke:{lay['smp_load_seen']:#x}:00000fff",
                  f"call:{lay['smp_dsp_load']:#x}",
                  f"poke:{lay['smp_func_held']:#x}:00000001", "tap:2", "wait:10", "png:load",   # (a page key: drawn again)
                  f"poke:{lay['smp_func_held']:#x}:00000000",
                  f"poke:{lay['smp_load_seen']:#x}:00000000",
                  f"call:{lay['smp_dsp_load']:#x}", "wait:4"]
            mjs = work / "meter.json"
            m_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                     "--snapshot", snap, "--steps", ",".join(ms), "--png-dir", work / "meter", "--json", mjs]

            def m_body(tdir):
                rc, out = run("load meter", m_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and mjs.exists():
                    r = json.loads(mjs.read_text())
                    d0 = [c["d0"] for c in r["direct_calls"] if int(str(c["fn"]), 0) == lay["smp_dsp_load"]]
                    shots = {k: pathlib.Path(v).read_bytes() for k, v in r["screens"].items()}
                    facts = {"628 permille reads 63 %": d0[:1] == [63],
                             "none in the last second reads -1": d0[1:2] == [-1],
                             "FUNC held draws something else in the tempo's place": shots.get("tempo") != shots.get("load")}
                    good = len(d0) == 2 and all(facts.values())
                    why = f"{facts} d0={d0}"
                return good, ("the DSP load meter: the half second's peak in percent, none when the DSP is "
                              "silent; drawn in place of the tempo while FUNC is held" if good else why)
            later("meter", "DSP load meter (ColdFire)", "DSP load meter (ColdFire)", [m_cmd, sorted(EMU_ENV.items())], m_body)

        # 6o. v0.33: MACHINE SEL to a Monomachine machine gives it its own start (dnfw.mnm's
        # DEFAULTS: SID on PULS, PW at the middle), not the shared records' defaults. A real
        # MACHINE SEL first (6k's: ONESHOT to the next sample machine; its commit's arguments
        # kept), then the commit called again for track 1 to SID: its eight records' words
        if "smp_machine_commit" in lay:
            from dnfw.mnm import machines as MMo     # noqa: PLC0415
            from dnfw.perc import machines as PMo    # noqa: PLC0415
            from dnfw.perc import live as PLo        # noqa: PLC0415
            kit = 0x4210C08C
            snd0 = kit + 52
            sa, ty = snd0 + 20 + 2 * 43, snd0 + 0xDE
            sid = MMo.TYPES[MMo.NAMES.index("SID 6581")]
            cm = lay["smp_machine_commit"]
            want = [PLo.knob_word(x, top, lo) for (_r, _s, lo, top), x in zip(PMo.PARAMS, MMo.DEFAULTS["SID 6581"])]
            os_ = (f"wait:3,poke:{ty:#x}:08,poke:{sa:#x}:0500,wait:4,tap:2,wait:6,func-src,wait:20,down,wait:4,"
                   f"yes,wait:20,call:{cm:#x}:arg1@{cm:#x}:0:{sid}:arg4@{cm:#x}:arg5@{cm:#x},wait:10,types,"
                   + ",".join(f"mem:{snd0 + 20 + 2 * sl:#x}:2" for _r, sl, _lo, _t in PMo.PARAMS))
            ojs = work / "mnmdefaults.json"
            o_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                     "--snapshot", snap, "--args-at", hex(cm), "--steps", os_, "--png-dir", work / "mnmdefaults",
                     "--json", ojs]

            def o_body(tdir):
                rc, out = run("mnm defaults", o_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and ojs.exists():
                    m = json.loads(ojs.read_text())["memory"]
                    types = m.get("types@0") or [None]
                    got = [int(m.get(f"{snd0 + 20 + 2 * sl:#x}", "0") or "0", 16) for _r, sl, _lo, _t in PMo.PARAMS]
                    facts = {"track 1 is SID": types[0] == sid, "its eight controls at SID's own start": got == want}
                    good = all(facts.values())
                    why = f"{facts} got={[hex(g) for g in got]} want={[hex(w) for w in want]} types={types}"
                return good, ("MACHINE SEL to SID: its eight controls at its own start (PULS, PW at the middle)"
                              if good else why)
            later("mnmdefaults", "Monomachine start values (ColdFire)", "Monomachine start values (ColdFire)", [o_cmd, sorted(EMU_ENV.items())], o_body)

        # 6p. v0.33: our overlays let go when the page under them goes (docs/freeze-hunt.md).
        # The sample list opened on track 1 (a SAMP turn), then TRK + [TRIG 2] to track 2, a
        # stock machine: the next UP is not the list's (it closes); then MACHINE SEL in and
        # out (FUNC + SRC, NO), and YES on a SLICE track's page still answers (its menu, or
        # NO SAMPLE ON SAMP)
        if "smp_lst_open" in lay and "smp_held_lo" in lay:
            from dnfw.sampler import machines as SMp    # noqa: PLC0415
            kit = 0x4210C08C
            snd0, snd1 = kit + 52, kit + 52 + 1163
            srec = SMp.RECORDS[SMp.SAMP_REC][0]
            lo_ = lay["smp_lst_open"]
            hs = [f"wait:3,poke:{snd0 + 0xDE:#x}:08,poke:{snd1 + 0xDE:#x}:00,poke:{snd0 + 0x6A:#x}:0200",
                  "wait:4,tap:2,wait:8",
                  f"call:{lay['smp_quant']:#x}:sound0:{srec}:{3 << 8:#x}:{SMp.SAMP_REC}",
                  f"poke:{snd0 + 0x6A:#x}:0300,poke:{lay['smp_overlay_dirty']:#x}:00000001,wait:10,png:h0,mem:{lo_:#x}:4",
                  "press:16,wait:2,press:26,wait:3,release:26,wait:2,release:16,wait:10,mem:0x42431a6c:1",
                  f"up,wait:6,mem:{lo_:#x}:4,png:h1",
                  "press:16,wait:2,press:25,wait:3,release:25,wait:2,release:16,wait:10",
                  f"poke:{snd0 + 0xDE:#x}:0d,poke:{snd0 + 0x6A:#x}:0000,wait:4,tap:2,wait:8",
                  "func-src,wait:20,no,wait:10,png:h2,yes,wait:8,png:h3"]
            hjs = work / "hooks.json"
            h_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                     "--snapshot", snap, "--steps", ",".join(hs), "--png-dir", work / "hooks", "--json", hjs]

            def h_body(tdir):
                rc, out = run("hooks let go", h_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and hjs.exists():
                    r = json.loads(hjs.read_text())
                    m = r["memory"]
                    sh = {n: pathlib.Path(r["screens"][n]).read_bytes() for n in ("h2", "h3")}
                    facts = {"the list opens on track 1": int(m[hex(lo_)], 16) == 1,
                             "TRK + [TRIG 2]: track 2": int(m["0x42431a6c"], 16) == 1,
                             "UP there: the list closed, not taking it": int(m[f"{hex(lo_)}@2"], 16) == 0,
                             "after MACHINE SEL in and out, YES on a SLICE page answers": sh["h2"] != sh["h3"]}
                    good = all(facts.values())
                    why = f"{facts} mem={m}"
                return good, ("the sample list lets go when another track is active; YES on a SLICE page "
                              "answers after MACHINE SEL" if good else why)
            later("hooks", "overlays let go (ColdFire)", "overlays let go (ColdFire)", [h_cmd, sorted(EMU_ENV.items())], h_body)

        # 6r. v0.35: MACHINE SEL's columns (flupperich6l, v0.33: with a machine low in our long
        # SRC list chosen, RIGHT showed an empty FLTR column: stock's LEFT / RIGHT keeps the
        # list's top row, and stock's lists never scroll). Track 1 on WaveTone: MACHINE SEL,
        # nine DOWNs to GRID, YES, RIGHT: the FLTR column drawn with MULTI-MODE marked on its
        # first row; LEFT: GRID under the cursor again; RIGHT once more: the same column
        if "colsw" in lay:
            kit = 0x4210C08C
            ty = kit + 52 + 0xDE
            rs = (f"wait:3,poke:{ty:#x}:01,wait:4,tap:2,wait:6,func-src,wait:20," + "down,wait:3," * 9
                  + "png:r0,yes,wait:20,right,wait:20,png:r1,left,wait:20,png:r2,right,wait:20,png:r3,types,"
                  + "no,wait:10,png:v0,press:2,wait:30,png:v1,release:2,wait:10,png:v2")   # v0.35: SYN held (O14)
            rjs = work / "colsw.json"
            r_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                     "--snapshot", snap, "--steps", rs, "--png-dir", work / "colsw", "--json", rjs]

            def r_body(tdir):
                rc, out = run("machine sel columns", r_cmd, logs, env=EMU_ENV, trace=tdir)
                why, good = out[-800:], False
                if rc == 0 and rjs.exists():
                    import numpy as np                     # noqa: PLC0415
                    from PIL import Image                  # noqa: PLC0415
                    r = json.loads(rjs.read_text())

                    def lit(name, y0, y1, x0=76, x1=116):   # the list column, in screen pixels
                        im = np.array(Image.open(r["screens"][name]).convert("L")) > 128
                        k = im.shape[1] // 128
                        return float(im[y0 * k:y1 * k, x0 * k:x1 * k].mean())
                    types = r["memory"].get("types@0") or [None]
                    facts = {"track 1 is GRID": types[0] == 12,
                             "RIGHT: the FLTR column's first row marked": lit("r1", 8, 16) > 0.3,
                             "... and its list drawn": lit("r1", 8, 60) > 0.1,
                             "LEFT: the SRC column's bottom row (GRID) marked": lit("r2", 52, 60) > 0.3,
                             "RIGHT again: the same FLTR column": pathlib.Path(r["screens"]["r3"]).read_bytes()
                             == pathlib.Path(r["screens"]["r1"]).read_bytes(),
                             # O14: SYN held long on GRID's page shows its values, let go shows its labels
                             "SYN held: the page changes": pathlib.Path(r["screens"]["v1"]).read_bytes()
                             != pathlib.Path(r["screens"]["v0"]).read_bytes(),
                             "SYN let go: the page as before": pathlib.Path(r["screens"]["v2"]).read_bytes()
                             == pathlib.Path(r["screens"]["v0"]).read_bytes()}
                    good = all(facts.values())
                    why = f"{facts} types={types} lit={lit('r1', 8, 16):.3f}/{lit('r1', 8, 60):.3f}/{lit('r2', 52, 60):.3f}"
                return good, ("MACHINE SEL: RIGHT from GRID shows the FLTR column from its top, LEFT returns "
                              "to GRID; SYN held shows the page's values" if good else why)
            later("colsw", "MACHINE SEL columns, SYN held (ColdFire)", "MACHINE SEL columns, SYN held (ColdFire)", [r_cmd, sorted(EMU_ENV.items())], r_body)

        # 6s. v0.45 (v0.44's BOUNCE froze the unit on MACHINE SEL's YES, and at every power-on of
        # a project holding a BOUNCE track: pages.py wr_label indexed past the Monomachine's label
        # tables and walked absolute 0x000000EE, zero RAM in the emulator, nothing on the unit).
        # Not from ui800M-v014, whose MACHINE SEL rows are v0.14's: boot400M with this build
        # installed (its own rows), the kit given every one of our types at the UI's first draw
        # (the newest on the active track) and booted on; then each track of ours drawn (FLTR,
        # SYN) and every row of LIST_NEW picked through MACHINE SEL's own list. A read below
        # 0x40000000 by code that is not stock's fails, as does EXCEPTION (scripts/emu_machine_boot.py,
        # scripts/emu_machine_sweep.py)
        from dnfw.waverider import coldfire as _cfm     # noqa: PLC0415
        mb_types = sorted(_cfm.NEW_TYPES, reverse=True)
        mb_snap, mb_js, ms_js = work / "machines-boot.snap", work / "machines-boot.json", work / "machines.json"
        stock_sec = work / "stock_section_3_MAIN_OS.bin"
        mb_cmd = [a.venv, "-u", "scripts/emu_machine_boot.py", "--build", bdir, "--stock", stock_sec,
                  "--snapshot", ROOT.parent / "digikit/out/snapshots/dn2-1.11/boot400M.snap",
                  "--types", ",".join(map(str, mb_types)), "--out", mb_snap, "--json", mb_js]
        ms_cmd = [a.venv, "-u", "scripts/emu_machine_sweep.py", "--snapshot", mb_snap, "--stock", stock_sec,
                  "--mod-types", ",".join(map(str, mb_types)), "--list", ",".join(map(str, _cfm.LIST_NEW)),
                  "--png-dir", work / "machines", "--json", ms_js]
        MB_ENV = {**EMU_ENV, "DT2_SYX": str(pathlib.Path(a.stock).resolve())}

        def mb_body(tdir):
            rc, out = run("machines: power-on", mb_cmd, logs, env=MB_ENV, trace=tdir)
            if rc != 0 or "machine boot: PASS" not in out:
                return False, out[-800:]
            rc, out = run("machines: MACHINE SEL", ms_cmd, logs, env=MB_ENV, trace=tdir)
            good = rc == 0 and "machine sweep: PASS" in out
            return good, (f"a power-on with types {mb_types} on the tracks, each track of ours drawn, and all "
                          f"{len(_cfm.LIST_NEW)} rows of MACHINE SEL's own list picked: no read below 0x40000000 "
                          "by our code, no EXCEPTION" if good else out[-800:])
        later("machines", "every machine through MACHINE SEL's own list; a power-on with ours on the tracks (ColdFire)",
              "every machine, MACHINE SEL's own list (ColdFire)", [mb_cmd, ms_cmd, sorted(MB_ENV.items())], mb_body)

        # 6q. v0.33: the sample pages driven at random (scripts/emu_fuzz_ui.py: SAMP turns,
        # the list, the browser and its menu, page and [TRIG] keys, MACHINE SEL, the machine
        # changed under the page): two seeds, each must finish, fault nothing in our code and
        # answer the last probe. v0.34 (docs/timing-model.md): the audio interrupt fires on
        # its own at its real cadence throughout (digikit's SSI0/eDMA event source, through
        # the real vectors), preempting the mod's UI code as on the unit; a CPU exception,
        # the interrupt no longer delivered, or audio frames overrunning fail the seed. It
        # needs the section the snapshot was booted with beside it (its own build's edits
        # are put back to stock first)
        # v0.38 (blskk's crash): first a fixed arp scenario (a SLICE track at NOTE, the arp on,
        # KEYBOARD's CHORD MEMORY with 12-note chords, keys held while the sequencer ticks, the
        # RECORDER and ARP pages up); the seeds also turn the arp, KEYBOARD and the sequencer; every
        # run fails on a free() of a stack address (emu_waverider_menu.py's stack_frees)
        if "smp_lst_open" in lay:
            snap_sec = pathlib.Path(str(snap) + ".section_3_MAIN_OS.bin")
            fz_cmd = [sys.executable, "scripts/emu_fuzz_ui.py", bdir, "3,7", "--steps", "24",
                      "--venv", a.venv, "--snapshot", snap, "--json", work / "fuzz.json",
                      "--isr-frame", "75000"]

            def fz_body(tdir):
                if not snap_sec.exists():
                    return False, f"missing {snap_sec} (the snapshot's own MAIN OS section): the real-rate interrupt needs it"
                rc, out = run("ui fuzz", fz_cmd, logs, env={**EMU_ENV, "PYTHONPATH": str(ROOT / "src")}, trace=tdir)
                return rc == 0, (out.strip().splitlines()[-1] if rc == 0 else out[-800:])
            later("fuzz", "UI fuzz, two seeds, the audio interrupt at its real rate (ColdFire)", "UI fuzz, two seeds, real-rate ISR (ColdFire)", [fz_cmd, sorted(EMU_ENV.items())], fz_body)

        # 6s. DIRECT JUMP (csrc/jump, docs/jump.md; scripts/emu_jump.py): the sequencer ticked
        # through stock's own ISR, a pattern cued with PTN + TRIG. Off: every tick's sequencer
        # state is stock's (same digest as the stock image's run). On (PTN + YES): the switch
        # within one step of the cue, and from the step after it every track goes on from its
        # own step in the playing pattern, wrapped by its new length (Elektron's rule; per
        # pattern, per track with lengths 5, 7, 3, and after a 12-step pattern's loop and a
        # half into a 16-step one); with equal lengths from PLAY, where stock plays that pattern
        # from PLAY. On, a cue through the sequencer's own cue routine (program changes,
        # chains, songs): stock's. The setting written to its sector, read back at power-on, NO turns
        # it off. v0.40 (owner: "works ~70% of the time", not when rapid-fired): 83 cues one after
        # another at every phase after the previous switch, pairs before one switch, PTN held
        # across two: each at the first step boundary, from where the pattern was (v0.39's code
        # fails 29). No fault anywhere
        if "jmp_on" in lay:
            jdir = work / "jump"
            jdir.mkdir(exist_ok=True)
            jruns = [("off", "pp", True), ("off", "pp", False), ("pc", "pp", False), ("on", "pp", False),
                     ("ref", "pp", True), ("on", "pt", False), ("ref", "pt", True), ("on", "odd", False),
                     ("persist", "pp", False), ("rapid", "pp", False)]
            jcmds = [[a.venv, "-u", "scripts/emu_jump.py", "--build", bdir, "--snapshot", snap, "--scenario", sc,
                      "--variant", var, "--png-dir", jdir / "screens", "--json", jdir / f"{sc}_{var}_{'stock' if st else 'build'}.json"]
                     + (["--stock"] if st else []) for sc, var, st in jruns]

            def jump_body(tdir):
                res = {}
                for (sc, var, st), cmd in zip(jruns, jcmds):
                    rc, out = run(f"jump {sc} {var} {'stock' if st else 'build'}", cmd, logs, env=EMU_ENV, trace=tdir)
                    got = re.findall(r"^emu_jump \w+: (\{.*\})$", out, re.M)
                    if not got:
                        return False, f"{sc}/{var}: no result (rc {rc}): {out[-600:]}"
                    res[(sc, var, st)] = json.loads(got[-1])
                    if rc != 0 or res[(sc, var, st)].get("faults"):
                        return False, f"{sc}/{var}: rc {rc}, faults {res[(sc, var, st)].get('faults')}"
                stock_off = res[("off", "pp", True)]["trace_digest"]
                why = []
                if res[("off", "pp", False)]["trace_digest"] != stock_off:
                    why.append("off: the sequencer's state differs from stock's")
                pc = res[("pc", "pp", False)]
                if pc["trace_digest"] != stock_off or pc["jmp"]["jmp_count"] != 0:
                    why.append("a cue not from the PTN view jumped")
                for var in ("pp", "pt", "odd"):
                    on, ref = res[("on", var, False)], res.get(("ref", var, True))
                    if on.get("on") != 1 or not on.get("sector_after_yes", "").startswith("444e3253"):
                        why.append(f"{var}: PTN + YES did not turn it on and write it")
                    sw = on.get("switch_global")
                    if sw is None or on["switch_after_cue_ticks"] > 6 or on["jmp"]["jmp_count"] != 1:
                        why.append(f"{var}: no switch within a step of the cue ({on.get('switch_after_cue_ticks')} ticks)")
                        continue
                    if not on.get("rule_ok"):
                        why.append(f"{var}: after the jump, steps {on.get('rule_bad')} do not go on from the playing pattern's")
                    if ref is not None:
                        after = [g for g in on["steps"] if int(g) > sw]
                        bad = [g for g in after if on["steps"][g] != ref["steps"].get(g)]
                        if bad or len(after) < 20:
                            why.append(f"{var}: after the jump, steps {bad[:4]} are not where stock plays that pattern")
                if not res[("persist", "pp", False)].get("ok"):
                    why.append("the setting did not persist (or wrote outside its sector)")
                rp = res[("rapid", "pp", False)]
                if not rp.get("ok"):
                    why.append(f"rapid fire: {rp.get('n_bad')} of {rp.get('cues')} cues not switched at the next "
                               f"boundary from where the pattern was, e.g. {rp.get('bad', [])[:2]}")
                on = res[("on", "pp", False)]
                return not why, ("; ".join(why) if why else
                                 f"off and a program-change cue: stock's state every tick; on: switched "
                                 f"{on['switch_after_cue_ticks']} tick(s) after the cue, start step {on['jmp']['jmp_last']}; "
                                 "every track goes on from its own step, wrapped by its new length (per pattern; per "
                                 "track, lengths 5, 7, 3; after a 12-step pattern's loop and a half, start "
                                 f"{res[('on', 'odd', False)]['jmp']['jmp_last']}), and from PLAY where stock plays it; "
                                 "the setting written, read back at power-on, turned off; v0.40: rapid fire, "
                                 f"{res[('rapid', 'pp', False)].get('cues')} cues at every phase after a switch "
                                 "(pairs, PTN held across two), each at the next boundary")
            later("jump", "DIRECT JUMP (ColdFire)", "DIRECT JUMP (ColdFire)", [*jcmds, sorted(EMU_ENV.items())], jump_body)

        # 6s. parameter slides (docs/slides.md, scripts/emu_slides.py): on the ColdFire, a trig's
        # locks applied as the frame ISR's note block applies them, then the real frame ISR every
        # frame: with SLIDE on, FILTER FREQ and FM TONE's FDBK ramp to the trig's locks over SLEN,
        # exact per frame, and land on them; a knob, a tempo change, a trigless lock, a retrig,
        # a new sound, a trig with no p-lock; the lock table's SAVE/LOAD and step clear. With
        # SLIDE off, and for every lock table, the same as stock 1.11 byte for byte: every frame's
        # smoother state and output arrays (the emulator's own EMAC, and the instrument's
        # arithmetic), what SAVE stores and LOAD restores, and stock skipping our records.
        # v0.40: copy and paste through the panel (track copy/clear/paste, trig copy/paste) carry
        # SLD/SLEN exactly as the track's stock lock beside them (both fail on v0.39's code)
        # v0.40 review (scripts/emu_slides_paths.py): every hooked paste site driven and counted --
        # shift right/left, track paste and its UNDO, page copy/paste and its UNDO, page autocopy
        # on lengthening -- each against the whole lock table; slot 80 (shift and autocopy treat
        # our records as stock's): the same routines with and without our records make the same
        # writes outside them, from the same memory, and never touch the sound; a track and a trig
        # paste on a nearly full lock table keep every stock lock (939cbc42 dropped two)
        # v0.40 (a user's report): a trig with a stock p-lock on a sample machine's SAMP (ONESHOT)
        # and on SLICE's SLCE, through stock's builder and applier and the real frame ISR (with
        # smp_mod_apply): the frame's word, played through the DSP's model, is exactly the locked
        # sample / slice, with the track's value on two others; unlocked trigs the track's (v0.39:
        # the lock was a scaled offset from the track's value)
        if "sl_smooth" in lay:
            sl_cmds = [[a.venv, "-u", "scripts/emu_slides.py", "--build", bdir, "--snapshot", snap,
                        "--json", work / f"slides-{k}.json",
                        *(["--stock"] if k == "stock" else ["--png-dir", work / "slides-png"])]
                       for k in ("build", "stock")]

            def sl_body(tdir):
                outs = []
                for k, cmd in zip(("build", "stock"), sl_cmds):
                    rc, out = run(f"slides {k}", cmd, logs, env=EMU_ENV, trace=tdir)
                    if rc != 0 or "PASS" not in out.strip().splitlines()[-1]:
                        return False, f"{k}: " + out[-800:]
                    outs.append(json.loads((work / f"slides-{k}.json").read_text()))
                b, s = outs
                same = [k for k in ("off_shas_emac", "off_shas", "plain_stored_sha", "plain_loaded_sha",
                                    "ours_loaded_rest_sha") if b.get(k) != s.get(k)]
                if same or not s.get("stock_skips_ours"):
                    return False, f"differs from stock: {same or 'stock did not skip ids 200/201'}"
                # v0.40: TRIG page 2, our two places (x 21..71, the bottom 25 rows) aside, is
                # stock 1.11's page pixel for pixel
                fb, fs = b.get("trig2_frame"), s.get("trig2_frame")
                if not fb or not fs:
                    return False, "TRIG page 2: no frame from the build or stock"
                fb, fs = bytes.fromhex(fb), bytes.fromhex(fs)

                def lit(buf):
                    return {(x, y) for x in range(128) for y in range(64)
                            if (buf[(7 - (y // 8)) + 8 * x] >> (y % 8)) & 1}
                ours = lambda p: 21 <= p[0] <= 71 and p[1] >= 39          # noqa: E731
                diff = {p for p in lit(fb) ^ lit(fs) if not ours(p)}
                if diff:
                    return False, f"TRIG page 2 differs from stock's outside SLD/SLEN: {len(diff)} pixels, e.g. {sorted(diff)[:4]}"
                return True, (f"SLIDE on: FREQ and FDBK ramp over {b['expected_ramp_frames']} frames "
                              f"(1 step at {b['tempo_word_after_isr'] / 120:g} BPM), exact, landing on the "
                              f"locks; {len(b['checks'])} checks; SLIDE off: {len(b['off_shas'])} frames' "
                              f"arrays and the lock table's SAVE/LOAD identical to stock 1.11; the TRIG page's SLD/SLEN "
                              f"set through the panel, the held trig staying on after release; v0.40: track copy, "
                              f"clear and paste carry them exactly as the stock locks, trig copy/paste too, no "
                              f"SLD/SLEN value in a stock lock; v0.40 review: shift, page paste and both "
                              f"UNDOs, autocopy driven (site hits {b.get('paths_hits')}), slot 80 harmless, "
                              f"a paste on a full table keeps every stock lock; v0.40: a SAMP and a SLCE p-lock play their own sample and "
                              f"slice whatever the track's (SAMP 10 and slice 7 over SAMP 2/5, slice 2/5); "
                              f"v0.40: SLD drawn as stock's RTRG and SLEN as "
                              f"stock's LEN pixel for pixel (off/on, unlocked/locked), the page otherwise "
                              f"stock's")
            later("slides", "parameter slides (ColdFire)", "parameter slides (ColdFire)",
                  [*sl_cmds, sorted(EMU_ENV.items())], sl_body)

        # v0.48 (docs/bounce-removal-plan.md): BOUNCE is out; it replaces v0.44..v0.47's rectrig
        # step and keeps that step's other checks (SAMP never glides, the RECORDER's CHAN knob and
        # FILE NAME keys, the Monomachine's TUNE). Always run: not keyed to a symbol, so it can
        # never drop out unseen
        bg_js = work / "bouncegone.json"
        bg_cmd = [a.venv, "-u", "scripts/emu_bouncegone.py", "--build", bdir, "--snapshot", snap,
                  "--json", bg_js, "--png-dir", work / "bouncegone"]

        def bg_body(tdir):
            rc, out = run("bounce gone", bg_cmd, logs, env=EMU_ENV, trace=tdir)
            last = out.strip().splitlines()[-1] if out.strip() else ""
            if rc != 0 or not last.startswith("PASS"):
                return False, out[-900:]
            return True, (f"{last[6:]}: a BOUNCE track from an older project plays SAMP OFF with the "
                          f"sequencer over its recorder trigs, nothing sent to the DSP, nothing kept clear "
                          f"in the recordings' area; recorder trigs and a slide through SAVE/LOAD byte for "
                          f"byte; the LED site stock's; record 244's text stock's; FUNC + VOICE the plain "
                          f"RECORDER; SAMP never glides; CHAN, FILE NAME; the Monomachine's TUNE")
        later("bouncegone", "BOUNCE out: an older project's BOUNCE track and recorder trigs (ColdFire)",
              "BOUNCE out: an older project's BOUNCE track and recorder trigs (ColdFire)",
              [bg_cmd, sorted(EMU_ENV.items())], bg_body)

        # v0.48 (owner, 2026-11-09): no text outside its place, every value of a control at one
        # place and size: the RECORDER in every state of its centre box and R.LEN through its values
        rx_js = work / "rectext.json"
        rx_cmd = [a.venv, "-u", "scripts/emu_rectext.py", "--build", bdir, "--snapshot", snap,
                  "--json", rx_js, "--png-dir", work / "rectext"]

        def rx_body(tdir):
            rc, out = run("recorder text", rx_cmd, logs, env=EMU_ENV, trace=tdir)
            last = out.strip().splitlines()[-1] if out.strip() else ""
            if rc != 0 or not last.startswith("PASS"):
                return False, out[-900:]
            return True, (f"{last[6:]}: every centre-box message of the RECORDER inside its box (no "
                          f"pixel in the gutters, the border untouched), R.LEN's MAX and step counts on "
                          f"one line inside their column")
        later("rectext", "RECORDER text inside its places, every state and R.LEN value (ColdFire)",
              "RECORDER text inside its places, every state and R.LEN value (ColdFire)",
              [rx_cmd, sorted(EMU_ENV.items())], rx_body)

        # v0.48 (owner, 2026-11-09: "chromatic view is gone after REC grid mode ... i wish it
        # [persisted], across all tracks and machine types"). KEYBOARD's state is the long at
        # 0x42431a99 in this snapshot (the keyboard object's +56: 0x40047088 toggles it,
        # 0x4004702e sets it; found with --access). KEYBOARD on; RECORD (grid recording on):
        # off, as stock; RECORD again (off): on again (stock left it off); to track 2 (made an
        # ONESHOT) with TRK + [TRIG 3]: still on; RECORD twice there: on; KEYBOARD off; RECORD
        # twice: still off (nothing given back that was not taken)
        from dnfw.sampler import machines as SMk        # noqa: PLC0415
        KB = "mem:0x42431a99:4"
        kb_steps = ["wait:6", KB, "tap:18", "wait:8", KB, "tap:19", "wait:8", KB, "tap:19", "wait:8", KB,
                    f"poke:{0x4210C08C + 52 + 1163 * 2 + 0xDE:#x}:{SMk.TYPE_OF['ONESHOT']:02x}",
                    "press:16", "wait:2", "tap:27", "wait:2", "release:16", "wait:8", KB,
                    "tap:19", "wait:8", KB, "tap:19", "wait:8", KB,
                    "tap:18", "wait:8", KB, "tap:19", "wait:8", KB, "tap:19", "wait:8", KB, "png:end"]
        kb_js = work / "kbrec.json"
        kb_cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", ROOT, "--build", bdir,
                  "--snapshot", snap, "--steps", ",".join(kb_steps), "--png-dir", work / "kbrec", "--json", kb_js]
        KB_WANT = [0, 1, 0, 1, 1, 0, 1, 0, 0, 0]

        def kb_body(tdir):
            rc, out = run("keyboard rec", kb_cmd, logs, env=EMU_ENV, trace=tdir)
            if rc != 0 or not kb_js.exists():
                return False, out[-900:]
            got = [int(v, 16) for v in json.loads(kb_js.read_text())["memory"].values()]
            if got != KB_WANT:
                return False, f"KEYBOARD's word {got}, wanted {KB_WANT}"
            return True, ("KEYBOARD on; RECORD (grid recording): off as stock; RECORD again: on again; on "
                          "another track, an ONESHOT: still on, and through RECORD twice; KEYBOARD off: "
                          "RECORD twice leaves it off")
        later("kbrec", "KEYBOARD kept through grid recording (ColdFire)",
              "KEYBOARD kept through grid recording (ColdFire)", [kb_cmd, sorted(EMU_ENV.items())], kb_body)

        # v0.48 (Error Kit): THRES on the coupled emulator (emu_coupled.py: the ColdFire and the
        # DSP together, block by block): a -34 dB tone on IN; THRES 30 (tick -45 dB) starts the
        # take on the ARM; THRES 110 holds it back, and turned to 30 while armed it starts
        th_js = work / "thres.json"
        th_cmd = [a.venv, "-u", "scripts/emu_coupled_thres.py", "--build", a.build, "--stock", a.stock,
                  "--snapshot", snap, "--json", th_js]

        def th_body(tdir):
            rc, out = run("thres coupled", th_cmd, logs, env=EMU_ENV, trace=tdir)
            last = out.strip().splitlines()[-1] if out.strip() else ""
            if rc != 0 or not last.startswith("PASS"):
                return False, out[-900:]
            return True, (f"{last[6:]}: on the ColdFire and the DSP together, a -34 dB tone on IN: THRES 30 (its "
                          f"tick at -45 dB) starts the take on the ARM; THRES 110 holds it back, and turned to 30 "
                          f"while armed, it starts without a new ARM")
        later("thres", "THRES on both processors (coupled)", "THRES on both processors (coupled)",
              [th_cmd, sorted(EMU_ENV.items())], th_body)

        # v0.48 (impbox, the owner: "exact dt2"): STRT, LEN, LOOP's fine records (fmt.c
        # smp_fine), on the ColdFire emulator: swapped in on ONESHOT/STRETCH/REPITCH/BOUNCE,
        # every byte back on WaveTone, none on GRID/SLICE/WERP, a fresh machine's LEN 120.00
        fs_js = work / "fineswap.json"
        fs_cmd = [a.venv, "-u", "scripts/emu_fine_swap.py", "--build", a.build, "--snapshot", snap, "--json", fs_js]

        def fs_body(tdir):
            rc, out = run("fine swap", fs_cmd, logs, env=EMU_ENV, trace=tdir)
            last = out.strip().splitlines()[-1] if out.strip() else ""
            if rc != 0:
                return False, "\n".join(l for l in out.splitlines() if l.startswith("FAIL"))[-900:] or out[-900:]
            return True, (f"{last}: STRT/LEN/LOOP carry FREQ's fine words while ONESHOT (all three), STRETCH, "
                          f"REPITCH, BOUNCE (STRT, LEN) is the active track; every byte of the records and "
                          f"runtime entries back on WaveTone; none on GRID, SLICE, WERP; a fine STRT kept "
                          f"through track changes; a fresh machine's LEN at 120.00")
        later("fineswap", "STRT/LEN/LOOP fine records swapped in and out (ColdFire)",
              "STRT/LEN/LOOP fine records swapped in and out (ColdFire)", [fs_cmd, sorted(EMU_ENV.items())], fs_body)

        # ... and STRT's knob: every knob step with the inputs of one of stock FREQ's makes
        # the same change (emu_fine_knob.py over emu_encoder_trace.py)
        fk_js = work / "fineknob.json"
        fk_cmd = [a.venv, "-u", "scripts/emu_fine_knob.py", "--build", a.build, "--snapshot", snap, "--json", fk_js]

        def fk_body(tdir):
            rc, out = run("fine knob", fk_cmd, logs, env=EMU_ENV, trace=tdir)
            last = out.strip().splitlines()[-1] if out.strip() else ""
            if rc != 0 or not last.startswith("PASS"):
                return False, out[-900:]
            return True, last[6:]
        later("fineknob", "STRT's knob against stock's fine FREQ (ColdFire)",
              "STRT's knob against stock's fine FREQ (ColdFire)", [fk_cmd, sorted(EMU_ENV.items())], fk_body)

        # the setup is done: from here on, nothing may import a module of ours (cached())
        setup_mods |= repo_modules()

        # 7. unit tests (v0.38: first of the long steps, on both cores: pytest-xdist, test by
        # test (--dist load: test_mnm.py alone is over half the time, so file by file one core
        # would wait on it). No test of TESTS shares a file with another (test_safety's
        # out/safety/waverider.syx is one test's own); module fixtures and lru_caches are built
        # in each worker. Before the SHARC runner starts, so they have both cores)
        tests = [t for t in TESTS if (ROOT / t).exists()]
        py_cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not slow",
                  "-n", "2", "--dist", "load", *tests]

        def py_body(tdir):
            import importlib.util               # noqa: PLC0415
            if importlib.util.find_spec("xdist") is None:
                return False, ("pytest-xdist is not installed for this python (pip install "
                               "--break-system-packages pytest-xdist): unchecked is not passing")
            # v0.40 (owner, 2026-11-05): the Monomachine golden runs were lost with the old
            # workspace. The owner approved ONE exception, for this DSP image only: if they are
            # missing, test_mnm's cases may go unrun when the build's section 7 and the MnM code
            # and its test are byte-identical to v0.39's (source dbbe804), which passed against
            # the real golden runs. Every other skip still counts: exactly test_mnm's cases plus
            # the one skip every run has had (EFM-SD's eighth knob) may be skipped, no more
            exc = mnm_exception()
            if isinstance(exc, str):
                return False, exc
            rc, out = run("pytest", py_cmd, logs, env={"PYTHONPATH": "src"}, trace=tdir)
            last = out.strip().splitlines()[-1] if out.strip() else ""
            # "586 passed, 1 skipped in 512.3s (0:08:32)": the counts, as serial pytest prints them
            ok = rc == 0 and re.search(r"\b\d+ passed\b", last) is not None
            if ok and exc is not None:
                m = re.search(r"\b(\d+) skipped\b", last)
                skipped = int(m.group(1)) if m else 0
                if skipped != exc + 1 or exc != MNM_EXC_REST:
                    return False, (f"{last} -- under the MnM exception test_mnm must collect exactly "
                                   f"{MNM_EXC_REST} tests (it collected {exc}) and exactly "
                                   f"{MNM_EXC_REST + 1} may be skipped (those and EFM-SD's eighth knob), "
                                   f"not {skipped}")
                last += (f" [owner exception 2026-11-05: the Monomachine golden runs are missing, so "
                         f"test_mnm's 366 golden cases are not collected and its {exc} other tests "
                         f"skip; section 7, src/dnfw/mnm and test_mnm.py byte-identical to v0.39's "
                         f"(dbbe804), which passed them all]")
            return ok, last

        def mnm_exception():
            """None: the golden runs are there, nothing excepted. An int: the exception applies,
            that many test_mnm cases go unrun. A str: why it does not apply (a failure)."""
            golden = pathlib.Path(os.environ.get("MNM_GOLDEN",
                                                 str(ROOT.parent / "mnm132" / "research" / "golden")))
            if golden.is_dir():
                return None
            if hashlib.sha256(sec7).hexdigest() != MNM_EXC_SEC7:
                return ("the Monomachine golden runs are missing and this build's DSP image is not "
                        "v0.39's: the owner's exception (2026-11-05) does not cover it")
            for path, want in MNM_EXC_TREES.items():
                got = subprocess.run(["git", "rev-parse", f"HEAD:{path}"], cwd=ROOT,
                                     capture_output=True, text=True).stdout.strip()
                dirty = subprocess.run(["git", "status", "--porcelain", "--", path], cwd=ROOT,
                                       capture_output=True, text=True).stdout.strip()
                if got != want or dirty:
                    return (f"the Monomachine golden runs are missing and {path} differs from "
                            f"v0.39's: the owner's exception (2026-11-05) does not cover it")
            r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                                "-p", "no:cacheprovider", "test/test_mnm.py"], cwd=ROOT,
                               capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "src"})
            m = re.search(r"\b(\d+) tests? collected\b", r.stdout)
            if r.returncode != 0 or not m:
                return "the MnM exception could not count test_mnm's cases: unchecked is not passing"
            return int(m.group(1))
        if wanted("unit"):
            gate("unit tests", *cached("unit tests", [py_cmd], py_body))

        # the SHARC runner (v0.25: beside the ColdFire steps, on its own core)
        if dsp_changed and sharc_want:
            sharc = threading.Thread(target=sharc_thread, daemon=True)
            sharc.start()

        # 5, 5b, 6, 6b..6r. the ColdFire emulator steps, quickest first (EMU); after each, a
        # SHARC part that has failed stops the gate
        ran = set()
        for sid, _gname in EMU:
            if sid in plan and wanted(sid):
                gname, cname, cmds, body = plan[sid]
                sharc_failed()
                gate(gname, *cached(cname, cmds, body))
                ran.add(sid)
                sharc_failed()

        if sharc is not None:
            print("  (waiting for the SHARC runner)", flush=True)
            sharc.join()
            if only is None:
                good = len(sharc_box) == len(gate_sharc.parts()) and all(ok for ok, _ in sharc_box)
                gate("SHARC runner", good, "; ".join(d for _, d in sharc_box) if sharc_box
                     else "the runner did not finish")
            else:
                for k, steps in enumerate(sharc_want):
                    ok, d = sharc_box[k] if k < len(sharc_box) else (False, "did not run: an earlier part failed")
                    gate(f"SHARC runner: {','.join(steps)}", ok, d)
                    ran.add("sharc:" + "+".join(steps))

    except Stop as s:
        for proc in list(LIVE):                 # the SHARC runner, if it is still going
            proc.kill()
        print(f"\nGATE FAILED at: {s}\n\n  DO NOT FLASH {a.build.name}.\n  Logs: {logs}")
        return 1

    if only is not None:
        # v0.38: --only: the steps asked for, each recorded in the reuse cache as a full run
        # would record it. Never a gate pass: no record beside the build, no clearance
        ran |= {sid for sid, _ in FIRST if sid in only and sid not in ("dsp-identity", "hwrules")}
        ran |= {sid for sid in ("dsp-identity", "hwrules") if sid in only and dsp_changed}
        missing = sorted(only - ran)
        print(f"ONLY {', '.join(sorted(only))}: " + ("each asked-for step passed" if not missing else
              f"passed, but {', '.join(missing)} did not apply to this build (not run)")
              + f"\n  logs: {logs}\n\n  A PARTIAL RUN, NOT A GATE: do not flash on it. Only a full run of "
              f"ship_gate.py on {a.build.name} can clear it.")
        return 0 if not missing else 3

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
