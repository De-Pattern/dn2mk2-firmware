"""Assemble the ONESHOT adapter (`csrc/oneshot/sharc/oneshot5.asm`) for its fixed place.

    python scripts/gen_oneshot_sharc.py [--fix]

The adapter branches to its own labels by **absolute** address (the forms the
firmware itself uses), so its source carries the numbers. This assembles it with
selache's `selas` (WSL), reads each label's parcel offset from the object's symbol
table, and checks that every hard-coded target equals `ADAPTER_SW + offset` of the
label its comment names. `--fix` rewrites the numbers and assembles again (the
instruction lengths do not depend on them), then checks once more.

Writes `csrc/oneshot/sharc/oneshot5.json`: the object's parcels, the instruction
offsets and the label map. Our own code only; no donor byte is involved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m3 as m3                     # noqa: E402
import sharc_waverider_render as m1                 # noqa: E402
from dnfw.image import sharc_object                 # noqa: E402
from dnfw.oneshot import build as OB                # noqa: E402

SOURCE = ROOT / "csrc" / "oneshot" / "sharc" / "oneshot5.asm"
OUT = ROOT / "csrc" / "oneshot" / "sharc" / "oneshot5.json"
LABELS = ("os_type5.", "os_loop.", "os_render.", "os_quiet.", "os_next.")
# `IF .. JUMP 0x...; // -> label` and `DM(I7, M7) = 0x...; // return address - 1: label - 1`
# one line each: a comment on the next line must never lend its label to this one
TARGET = re.compile(r"(JUMP[ \t]+)(0x[0-9a-f]+)(;[ \t]*//[ \t]*(?:[^>\n]*->[ \t]*)?(os_\w+\.))")
RETURN = re.compile(r"(DM\(I7, M7\) = )(0x[0-9a-f]+)(;[ \t]*//[^\n]*?(os_\w+\.) - 1)")


def assemble(text: str, work: pathlib.Path) -> tuple[bytes, dict[str, int], list[int]]:
    src = work / "oneshot5.asm"
    src.write_bytes(text.encode())
    obj = work / "oneshot5.doj"
    r = m1._wsl(f"{m1.SELAS} -proc ADSP-21569 -o {m1._wsl_path(obj)} {m1._wsl_path(src)}\n", work)
    if r.returncode or not obj.exists():
        raise SystemExit(f"selas failed:\n{r.stdout}{r.stderr}")
    data = obj.read_bytes()
    syms = sharc_object.symbols(data)
    be, offsets = m3._selas(src, work)
    return be, {k: OB.ADAPTER_SW + syms[k] for k in LABELS if k in syms}, offsets


def targets(text: str, labels: dict[str, int]) -> tuple[str, list[str]]:
    wrong = []

    def fix(m, minus=0):
        want = labels[m.group(4)] - minus
        if int(m.group(2), 16) != want:
            wrong.append(f"{m.group(2)} -> {want:#x} ({m.group(4)})")
        return f"{m.group(1)}{want:#x}{m.group(3)}"

    text = TARGET.sub(lambda m: fix(m), text)
    text = RETURN.sub(lambda m: fix(m, 1), text)
    return text, wrong


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fix", action="store_true")
    a = p.parse_args()
    text = SOURCE.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(dir=ROOT / "out" if (ROOT / "out").exists() else None) as tmp:
        work = pathlib.Path(tmp)
        be, labels, offsets = assemble(text, work)
        fixed, wrong = targets(text, labels)
        if wrong and not a.fix:
            print("targets that do not match the labels:\n  " + "\n  ".join(wrong))
            return 1
        if wrong:
            SOURCE.write_bytes(fixed.encode())
            print("fixed:\n  " + "\n  ".join(wrong))
            be2, labels2, offsets2 = assemble(fixed, work)
            if labels2 != labels or offsets2 != offsets or len(be2) != len(be):
                raise SystemExit("the fixed source moved its own labels; run again")
            _, again = targets(fixed, labels2)
            if again:
                raise SystemExit(f"still wrong after the fix: {again}")
            be, text = be2, fixed
        entry, _ = m3._selas_line(f"JUMP {OB.ADAPTER_SW:#x};", work)
    OUT.write_text(json.dumps({
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "toolchain": "selache selas -proc ADSP-21569 (js216/selache 2b26d3b, GPL-3.0, WSL)",
        "section": "seg_pmco", "load_sw": hex(OB.ADAPTER_SW),
        "labels": {k: hex(v) for k, v in labels.items()},
        "object_parcels_be": be.hex(), "instruction_offsets": offsets,
        "entry_jump": {"source": f"JUMP {OB.ADAPTER_SW:#x};", "object_parcels_be": entry.hex()}},
        indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(be)} bytes, {len(offsets)} instructions, labels "
          + ", ".join(f"{k}{v:#x}" for k, v in labels.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
