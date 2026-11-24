"""Build only the shared DSP tail containing Sidecar's native-return router.

No hardware access. Other engine objects are retained byte-for-byte.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import gen_ping_asm as tail
import gen_waverider_sharc as packaging
import sharc_waverider_render as renderer
from sharc_resolve_jumps import resolve
from dnfw.image import sharc_object
from dnfw.waverider import dsp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selas", required=True)
    args = ap.parse_args()
    renderer.SELAS = args.selas
    with tempfile.TemporaryDirectory() as tmp:
        source, parcels, offsets = resolve(tail.build(), dsp.PING_SW, Path(tmp))
    code = sharc_object.load_bytes(parcels)
    if len(code) + 64 > dsp.PING_CODE_SPAN:
        raise ValueError("Sidecar tail exceeds the existing code reservation")
    tail.OUT.write_text(source, encoding="utf-8", newline="\n")
    spec = {"source": tail.OUT.relative_to(tail.ROOT).as_posix(),
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "toolchain": packaging.TOOLCHAIN, "section": "seg_pmco",
            "load_sw": hex(dsp.PING_SW), "object_parcels_be": parcels.hex(),
            "instruction_offsets": offsets}
    tail.OUT.with_suffix(".json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    bundle = json.loads(dsp.CODE.read_text(encoding="utf-8"))
    bundle["ping"] = {k: v for k, v in spec.items() if k != "instruction_offsets"}
    dsp.CODE.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    print(f"Native-return tail: {len(code)} bytes in {dsp.PING_CODE_SPAN}-byte reservation; other DSP objects retained")


if __name__ == "__main__":
    main()
