"""ship_gate's SHARC runner step, on its own (v0.28).

The step's verdict reads only this file and the runner's own run: the command below, its
exit code and its log. Its reuse record (gate_cache) holds what the runner read (traced:
its scripts, the repository modules it imported, the committed SHARC objects, digikit)
plus this file, gate_cache.py and the tracer -- not ship_gate.py and not the ColdFire's
build artefacts, which the runner never reads. So a change to a ColdFire test or to the
ColdFire code no longer throws away an unchanged DSP's pass (owner, 2026-10-27), while any
change to anything the runner reads still makes it run again. DSP identity (ship_gate,
never reused) ties the pass to the build: the build's section 7 must be exactly
dnfw.waverider.dsp.section7(stock), the image the runner ran.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def default_steps() -> list[str]:
    """the runner's own default step list, read from its source (so no step is ever left out)"""
    import re
    src = (HERE / "sharc_waverider_m5.py").read_text(encoding="utf-8")
    m = re.search(r'add_argument\("--steps", default="([^"]+)"', src)
    return m.group(1).split(",")


# v0.28: the runner in parts, each a step of its own with its own reuse record, so a gate cut
# off by a time limit keeps the parts that passed (the whole runner took more than two hours
# beside the ColdFire steps). The parts together are exactly the runner's default steps.
GROUPS = (("decode", "map", "voice", "guard"), ("stress",), ("garbage",), ("smp",), ("link", "rec", "pvmix", "tdm"),
          ("stock", "ping", "shft", "gran"), ("mnm", "frame"))


def parts() -> list[list[str]]:
    want = default_steps()
    out = [[s for s in g if s in want] for g in GROUPS]
    out = [g for g in out if g]
    left = [s for s in want if not any(s in g for g in out)]
    if left:
        out.append(left)                        # any step not grouped runs in a part of its own
    assert sorted(s for g in out for s in g) == sorted(want)
    return out


def command(stock: str, digikit_sharc: str, steps: list[str] | None = None, tag: str = "") -> list:
    cmd = [sys.executable, "scripts/sharc_waverider_m5.py", "--image", stock, "--digikit", digikit_sharc]
    if steps is not None:
        cmd += ["--steps", ",".join(steps), "--tag", tag or "part"]
    return cmd


def verdict(rc: int, out: str) -> tuple[bool, str]:
    return rc == 0, ("all steps PASS, incl. types 0-4 bit-identical to stock" if rc == 0 else out[-800:])


OWN = (HERE / "gate_sharc.py",)
