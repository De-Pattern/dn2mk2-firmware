"""v0.33: the sample machines' UI, driven at random in the ColdFire emulator, looking for a
freeze (the owner's, zugada_'s and Pablo's reports: the sample list up, keys doing nothing,
no audio).

    DT2_SECTIONS=../sec111 python scripts/emu_fuzz_ui.py BUILD_DIR SEEDS [--steps N] [--json OUT]

BUILD_DIR holds section_3_MAIN_OS.bin (as ship_gate's work/build). For each seed, a pool of
four samples in two folders (as gate 6h's), a random sample machine on every track, then N
random actions of the kind that led to the reports: SAMP turned (the list opens), UP/DOWN,
YES, NO, FUNC + YES (the browser), RIGHT (its menu), LEFT, page keys, [TRIG] keys, MACHINE
SEL in and out, the machine changed under the page, and the audio ISR's frame build between
them (the emulator does not run the ISR by itself: `frame:` enters it, so modulation and
the link's per-frame work interleave with the keys as on the unit). After every few actions
an `alive` checkpoint. A seed fails on:

- the run not finishing (an exception stops the emulator: unicorn does not dispatch them);
- a new memory fault (an access no stock run makes) whose PC is in the mod's code;
- a last probe (out of whatever is up, then two page keys) that changes nothing on the
  screen: hung. (Checkpoints with no new frame are reported, not failed: nothing may have
  needed a redraw.)

Exit 0 when every seed passes. Each seed's steps are printed, so a failure is replayed by
running emu_waverider_menu.py with them.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import struct
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

KIT = 0x4210C08C
SOUND = 1163


def pool_steps(lay) -> list[str]:
    """gate 6h's pool: four slots (one empty), two folders, long names, overviews"""
    from dnfw.sampler import machines as SMx
    M = SMx.MIRROR
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
    st = [f"poke:{M:#x}:{d[:0xC10].hex()}"] + [f"poke:{M + 0x1000 + 100 * k:#x}:{ov.hex()}" for k in (0, 1, 3)]
    st += [f"poke:{M + 0x80000:#x}:{mt.hex()}", f"poke:{lay['smp_dir_ok']:#x}:00000001",
           f"poke:{lay['smp_meta_ok']:#x}:00000001"]
    return st


def seed_steps(lay, seed: int, n: int) -> list[str]:
    from dnfw.sampler import machines as SMx
    rnd = random.Random(seed)
    types = [SMx.TYPE_OF[m] for m in ("ONESHOT", "WERP", "STRETCH", "REPITCH", "GRID", "SLICE")]
    samp_rec = SMx.RECORDS[SMx.SAMP_REC][0]
    st = ["wait:2"] + [f"poke:{KIT + 52 + SOUND * t + 0xDE:#x}:{rnd.choice(types):02x}" for t in range(16)]
    st += [f"poke:{KIT + 52 + SOUND * t + 0x6A:#x}:{rnd.choice((1, 2, 3, 4)):02x}00" for t in range(16)]
    st += pool_steps(lay) + ["wait:6", "tap:2", "wait:8", "alive:start"]

    def turn():
        v = rnd.choice((0, 1, 2, 3, 4, 5, 9, 60, 127))
        t = 0                                   # the snapshot's active track
        return [f"call:{lay['smp_quant']:#x}:sound0:{samp_rec}:{v << 8:#x}:{SMx.SAMP_REC}",
                f"poke:{KIT + 52 + SOUND * t + 0x6A:#x}:{v:02x}00", f"poke:{lay['smp_overlay_dirty']:#x}:00000001"]
    acts = [
        (6, lambda: turn()),
        (6, lambda: [rnd.choice(("up", "down"))]),
        (5, lambda: ["yes"]),
        (4, lambda: ["no"]),
        (3, lambda: ["press:17", "wait:2", "yes", "wait:2", "release:17"]),     # FUNC + YES
        (2, lambda: ["press:17", "wait:2", "no", "wait:2", "release:17"]),      # FUNC + NO
        (3, lambda: ["right"]),
        (2, lambda: ["left"]),
        (2, lambda: [f"tap:{rnd.choice((1, 2, 2, 3, 4, 5))}"]),                  # TRIG, SYN, FLTR, AMP, FX
        (3, lambda: [f"press:{25 + rnd.randrange(16)}", "wait:3", f"release:{25 + rnd.randrange(16)}"]),
        (1, lambda: ["func-src", "wait:20", rnd.choice(("no", "down", "up")), "wait:4", rnd.choice(("no", "yes"))]),
        (2, lambda: [f"poke:{KIT + 52 + 0xDE:#x}:{rnd.choice(types):02x}", f"poke:{lay['smp_overlay_dirty']:#x}:00000001"]),
        (5, lambda: [f"frame:f{rnd.randrange(1 << 30)}"]),
        (1, lambda: ["tap:20"]),                                                  # PLAY
    ]
    weights = [w for w, _ in acts]
    for i in range(n):
        st += rnd.choices([f for _w, f in acts], weights)[0]()
        st.append(f"wait:{rnd.choice((1, 2, 3, 6))}")
        if i % 8 == 7:
            st.append(f"alive:a{i}")
    # the last probe: out of whatever is up, then two page keys must each change the screen
    st += ["no", "wait:4", "no", "wait:4", "tap:3", "wait:8", "alive:p1", "png:p1", "tap:2", "wait:8", "alive:p2", "png:p2"]
    return st


def our_ranges(lay) -> list[tuple[int, int]]:
    out = [(lay["c_load"], lay["c_text_end"])]
    if "ping_slot" in lay:
        out.append((lay["ping_slot"], lay["ping_code_end"]))
    if "slot_shim" in lay:
        out.append((lay["slot_shim"], lay.get("mchunk_code_end", lay["slot_shim"] + 0x10000)))
    return out


def judge(r: dict, lay, baseline_pages: set) -> tuple[bool, dict]:
    ours = our_ranges(lay)
    new = [f for f in r.get("faults", []) if f.get("page") not in baseline_pages]
    in_ours = [f for f in new if any(a <= int(f["first_pc"], 16) < b for a, b in ours)]
    al = r.get("alive", [])
    stalls = [b["name"] for a, b in zip(al, al[1:]) if b["frames"] <= a["frames"]]
    shots = {k: pathlib.Path(v).read_bytes() for k, v in r.get("screens", {}).items() if pathlib.Path(v).exists()}
    probe_ok = "p1" in shots and "p2" in shots and shots["p1"] != shots["p2"]
    # (an exception aborts the emulator itself -- unicorn does not dispatch them -- so it shows
    # as a run that did not finish. 0x4011ea6a, the firmware's formatter, runs on stock too:
    # it is no fault sign. A checkpoint with no new frame is not a freeze by itself -- nothing
    # may have needed redrawing -- so the stalls are kept for the report, and the verdict is the
    # last probe's)
    facts = {"no memory fault from the mod's code": not in_ours,
             "the last probe: out of everything, two page keys each change the screen": probe_ok,
             "frames composed by the end": len(al) >= 2 and al[-1]["frames"] > al[0]["frames"]}
    return all(facts.values()), {"facts": facts, "new_faults": new[:5], "stalls": stalls[:5],
                                 "fault_reports": r.get("fault_reports", [])[:3]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("build_dir", type=pathlib.Path)
    p.add_argument("seeds", help="a range A-B or a list a,b,c")
    p.add_argument("--steps", type=int, default=60)
    p.add_argument("--venv", default=str(ROOT.parent / "digikit/.venv/bin/python"))
    p.add_argument("--snapshot", default=str(ROOT.parent / "digikit/out/snapshots/dn2-1.11/ui800M-v014.snap"))
    p.add_argument("--json", type=pathlib.Path)
    a = p.parse_args(argv)
    from dnfw.mods import waverider as W
    lay = W.SPEC["layout"]
    seeds = (list(range(int(a.seeds.split("-")[0]), int(a.seeds.split("-")[1]) + 1)) if "-" in a.seeds
             else [int(x) for x in a.seeds.split(",")])
    env = {**os.environ, "DT2_MAIN_IMG": str(pathlib.Path(os.environ["DT2_SECTIONS"]) / "section_3_MAIN_OS.bin"),
           "DNFW_EMU_FLAGS": '{"weakptr": false}'}
    work = a.build_dir.parent / "fuzz"
    work.mkdir(exist_ok=True)

    def run(name, steps):
        js = work / f"{name}.json"
        cmd = [a.venv, "-u", "scripts/emu_waverider_menu.py", "--root", str(ROOT), "--build", str(a.build_dir),
               "--snapshot", a.snapshot, "--steps", ",".join(steps), "--png-dir", str(work / name), "--json", str(js)]
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        if proc.returncode != 0 or not js.exists():
            return None, proc.stdout[-1500:] + proc.stderr[-1500:]
        return json.loads(js.read_text()), ""

    # the baseline: the same pool, nothing pressed (the pages stock touches anyway)
    base, why = run("baseline", seed_steps(lay, 0, 0))
    if base is None:
        print("FAIL: the baseline run did not finish:", why)
        return 1
    baseline_pages = {f.get("page") for f in base.get("faults", [])}
    report, bad = {}, []
    for s in seeds:
        steps = seed_steps(lay, s, a.steps)
        r, why = run(f"seed{s}", steps)
        if r is None:
            ok, info = False, {"crashed": why}
        else:
            ok, info = judge(r, lay, baseline_pages)
        report[s] = {"ok": ok, **info}
        print(f"seed {s}: {'PASS' if ok else 'FAIL'} {'' if ok else json.dumps(info)[:600]}", flush=True)
        if not ok:
            bad.append(s)
            (work / f"seed{s}.steps.txt").write_text(",".join(steps))
    if a.json:
        a.json.write_text(json.dumps(report, indent=1))
    print(f"{len(seeds) - len(bad)}/{len(seeds)} seeds pass" + (f"; failing: {bad}" if bad else ""))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
