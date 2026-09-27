"""Build the first ONESHOT firmware from the user's two OS files and one WAV.

    python scripts/build_oneshot.py --sample PATH.wav \\
        [--dn2 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip] \\
        [--donor 00_Resources/00_Firmware/Digitakt_II_OS1.16_dist/Digitakt_II_OS1.16.syx] \\
        [--syx 00_Resources/02_Builds/oneshot_DN2_1.11.syx] [--out out/oneshot-build]

The same path as `dnfw mods apply --mod oneshot --donor ... --sample ...`
(`dnfw.mods.oneshot.compose`), plus what the gates need beside the image:
`section_3_MAIN_OS.bin` and `section_7.bin` for the ColdFire and SHARC emulators,
and `report.json` -- addresses, digests and placements, never a donor byte.

**It never overwrites a build**: if the .syx exists it stops. Nothing is sent to
an instrument.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                          # noqa: E402
from dnfw.firmware.build import build as rebuild, replacement  # noqa: E402
from dnfw.firmware.load import load                            # noqa: E402
from dnfw.firmware.verify import verify                        # noqa: E402
from dnfw.mods import oneshot as MOD                           # noqa: E402
from dnfw.oneshot import sample as SA                          # noqa: E402

FW = ROOT / "00_Resources" / "00_Firmware"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dn2", type=pathlib.Path, default=FW / "Digitone_II_OS1.11_dist.zip")
    p.add_argument("--donor", type=pathlib.Path,
                   default=FW / "Digitakt_II_OS1.16_dist" / "Digitakt_II_OS1.16.syx")
    p.add_argument("--sample", type=pathlib.Path, required=True)
    p.add_argument("--syx", type=pathlib.Path,
                   default=ROOT / "00_Resources" / "02_Builds" / "oneshot_DN2_1.11.syx")
    p.add_argument("--out", type=pathlib.Path, default=ROOT / "out" / "oneshot-build")
    a = p.parse_args()
    if a.syx.exists():
        raise SystemExit(f"{a.syx} exists; builds are never overwritten -- name another with --syx")
    if not a.donor.exists():
        raise SystemExit(f"the donor {a.donor} is not here: this build needs the user's DT2 1.16")

    dn2_raw, dt2_raw = read_image(a.dn2), read_image(a.donor)
    pcm, note = SA.from_wav(a.sample.read_bytes(), MOD.bank_limit())
    print(f"sample: {a.sample.name}: {note}")
    out = MOD.compose(dn2_raw, dt2_raw, pcm)
    fw = load(dn2_raw)
    reps = {sid: replacement(fw, sid, out[sid]) for sid in (MOD.MAIN_OS, MOD.DSP_STREAM)}
    image = rebuild(fw, reps)
    report = verify(load(image))
    bad = [c.name for c in report.checks if not c.ok]
    print(f"integrity: {len(report.checks) - len(bad)}/{len(report.checks)} checks pass")
    if bad:
        raise SystemExit(f"not written: {bad}")

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "section_3_MAIN_OS.bin").write_bytes(out[MOD.MAIN_OS])
    (a.out / "section_7.bin").write_bytes(out[MOD.DSP_STREAM])
    rep = out["report"]
    # the entry points the from-reset boot gate counts (emu_boot_check.py): our shims
    syms = {k: f"{v:#x}" for k, v in rep["layout"].items()
            if k.endswith("_shim") or k == "canon_valid"}
    (a.out / "symbols.json").write_text(json.dumps(syms, indent=1) + "\n", encoding="utf-8")
    rep["sample"] = {"file": a.sample.name, **note}
    rep["image"] = {"bytes": len(image), "sha256": hashlib.sha256(image).hexdigest(),
                    "verify": f"{len(report.checks) - len(bad)}/{len(report.checks)}",
                    "syx": str(a.syx.relative_to(ROOT)) if a.syx.is_relative_to(ROOT) else str(a.syx)}
    (a.out / "report.json").write_text(json.dumps(rep, indent=1, default=str) + "\n", encoding="utf-8")
    a.syx.parent.mkdir(parents=True, exist_ok=True)
    a.syx.write_bytes(image)
    print(f"wrote {a.syx} ({len(image):,} B, sha256 {rep['image']['sha256'][:16]}...)")
    print(f"      {a.out}/section_3_MAIN_OS.bin, section_7.bin, report.json")
    print("Nothing has been sent to an instrument.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
