"""Build `waverider-disc-wtplace`: our reader in WaveTone's place (a discriminator, never shipped).

    python scripts/build_waverider_disc_wtplace.py --m5b M5B.syx --out OUT.syx [--stock ZIP]

Stock DN2 1.11 section 7 plus one CALL target and our block-1 region:

- the WaveTone arm's `CALL 0x1c6d4a` at sw 0x1c9611 becomes `CALL 0x16ed00`
  (csrc/waverider/sharc/wt_place.asm, a C-ABI adapter that calls wr_render5);
- the region 0x2dd600..0x2e7000 as M5d ships it (the reader, state, tables), with the
  adapter in the type-5 loop's span;
- **no** machine-type lookup patch (so no track is ever type 5), **no** entry JUMP at
  sw 0x1c9448, no type-5 loop.

A WaveTone track then plays our saw (table 0 frame 0, note 60) through the firmware's
own call, frame and per-track chain. Section 3 is m5b's, as in every other Waverider
discriminator. docs/waverider-dsp-compare.md has the reading. Refuses an existing OUT.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.image import bootstream, sharc_object  # noqa: E402
from dnfw.waverider import dsp  # noqa: E402

CALL_SW = 0x1C9611                                  # the WaveTone arm's render call
CALL_STOCK = bytes.fromhex("04181c004a6d")          # CALL 0x1c6d4a (DB), 25a, 48-bit
CALL_NEW = bytes.fromhex("0418160000ed")            # CALL 0x16ed00 (DB): the same form
SOURCE = ROOT / "csrc/waverider/sharc/wt_place.asm"


def adapter(work: pathlib.Path) -> bytes:
    import sharc_resolve_jumps as rj  # noqa: PLC0415  (WSL + selas)
    src = SOURCE.read_text(encoding="utf-8")
    _, be, _ = rj.resolve(src, dsp.LOOP_SW, work)
    return sharc_object.load_bytes(be)


def section7(stock: bytes, obj: bytes) -> bytes:
    if hashlib.sha256(stock).hexdigest() != dsp.STOCK_SHA256:
        raise SystemExit("not stock DN2 1.11 section 7")
    if bootstream.read_span(stock, dsp.sw_to_load(CALL_SW), len(CALL_STOCK)) != CALL_STOCK:
        raise SystemExit("sw 0x1c9611 is not the stock `CALL 0x1c6d4a`")
    if len(obj) > dsp.CODE_SPAN - 64:
        raise SystemExit("the adapter does not fit its span with 64 bytes of padding")
    base = dsp.objects()
    dsp.objects = lambda: {**base, "machine5_live": obj}   # this build only
    added = dsp.spans()
    dsp._check_free(stock, added)
    out = bytearray(bootstream.insert_before_final(
        stock, b"".join(bootstream.block(at, payload) for _, at, payload in added)))
    bootstream.write_span(out, dsp.sw_to_load(CALL_SW), CALL_NEW)
    result = bytes(out)
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise SystemExit(f"the result does not walk as a boot stream ({walked.reason})")
    # the two patches the shipping build makes must be absent
    if bootstream.read_span(result, dsp.sw_to_load(dsp.ENTRY_SW), len(dsp.ENTRY_STOCK)) != dsp.ENTRY_STOCK:
        raise SystemExit("the entry at sw 0x1c9448 is not stock")
    if bootstream.read_span(result, dsp.dm_to_load(dsp.LOOKUP_DM), 32) != bootstream.read_span(
            stock, dsp.dm_to_load(dsp.LOOKUP_DM), 32):
        raise SystemExit("the machine lookup is not stock")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--m5b", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--stock", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--s7-only", type=pathlib.Path, help="write section 7 here and stop (runner checks)")
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit(f"{a.out} exists: never overwrite a build")
    import sharc_waverider_render as m1  # noqa: PLC0415
    from dnfw.cli.main import main as dnfw  # noqa: PLC0415
    stock = m1.dn2_section7(a.stock)
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        obj = adapter(work)
        s7 = section7(stock, obj)
        print(f"section 7: {len(s7)} bytes, sha256 {hashlib.sha256(s7).hexdigest()}; adapter {len(obj)} B")
        if a.s7_only:
            a.s7_only.write_bytes(s7)
            return 0
        p = work / "s7.bin"
        p.write_bytes(s7)
        return dnfw(["build", "-o", str(a.out), "-s", f"7={p}", str(a.m5b)]) or 0


if __name__ == "__main__":
    raise SystemExit(main())
