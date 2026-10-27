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


def command(stock: str, digikit_sharc: str) -> list:
    return [sys.executable, "scripts/sharc_waverider_m5.py", "--image", stock, "--digikit", digikit_sharc]


def verdict(rc: int, out: str) -> tuple[bool, str]:
    return rc == 0, ("all steps PASS, incl. types 0-4 bit-identical to stock" if rc == 0 else out[-800:])


OWN = (HERE / "gate_sharc.py",)
