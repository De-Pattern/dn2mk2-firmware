"""Hardware discriminators D5a/D5b: bisect m5c's type-5 path between the loop's tail,
the software call/return, and the reader's body.

    python scripts/build_waverider_disc_bisect.py --m5b IMAGE.syx --outdir DIR

D2 (the reader never reached) played; D3 (everything but the track-buffer write)
died on the first trig. Each build here is m5c's section 7 with one byte patch, and
m5b's section 3:

- **D5a `waverider-disc-m5c-nocall`**: the loop runs its whole type-5 tail (the frame
  copy, note cell, pitch table and directory reads, every conditional compute, the
  reader-block writes) and then JUMPs past the CJUMP instead of calling the reader.
  Plays -> the loop tail is fine on silicon; the call or the reader kills it.
- **D5b `waverider-disc-m5c-callonly`**: the loop calls the reader, and the reader's
  second instruction JUMPs straight to its own return sequence (`I12 = DM(M7, I6)`;
  one store; `JUMP (M14, I12) (DB)`; `NOP`; `RFRAME`). Nothing of the body runs, and
  no track buffer is written. Dies -> the call/return (CJUMP, the two frame pushes,
  the software return, RFRAME) is what silicon refuses. Plays (with D5a playing) ->
  it is the reader's body.

Both refuse an existing output and check every patched byte is m5c's first.
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

from dnfw.image import bootstream  # noqa: E402
from dnfw.waverider import dsp  # noqa: E402

CALL_SW = 0x16EE0D          # CJUMP 0x16eb00 (DB); DM(I7,M7)=R2; DM(I7,M7)=0x16ee13
CALL_STOCK = bytes.fromhex("0418160000eb" "f29f" "c09f160013ee")
AFTER_CALL_SW = 0x16EE14
READER_2ND_SW = 0x16EB02    # R8 = DM(0, I4); R9 = DM(1, I4)
READER_2ND_STOCK = bytes.fromhex("08980004" "08988104")
READER_RET_SW = 0x16EBA7    # I12 = DM(M7, I6) -- the return sequence
NOP16, NOP48 = bytes.fromhex("0100"), bytes(6)


def jump_abs(target_sw: int) -> bytes:
    """`JUMP target` (Type 8a absolute, 48-bit), memory order, as the image's own
    `jump 0x1c944c` at sw 0x16ee78 is encoded (3e06 1c00 4c94)."""
    return bytes.fromhex("3e06") + (target_sw >> 16).to_bytes(2, "little") + (target_sw & 0xFFFF).to_bytes(2, "big")[::-1]


def patched(stream: bytes, sw: int, stock: bytes, new: bytes) -> bytes:
    if len(new) != len(stock):
        raise SystemExit(f"patch at sw {sw:#x} changes length")
    at = dsp.sw_to_load(sw)
    if bootstream.read_span(stream, at, len(stock)) != stock:
        raise SystemExit(f"sw {sw:#x} is not m5c's expected bytes")
    out = bytearray(stream)
    bootstream.write_span(out, at, new)
    return bytes(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--m5b", type=pathlib.Path, required=True)
    ap.add_argument("--outdir", type=pathlib.Path, required=True)
    ap.add_argument("--stock", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    a = ap.parse_args(argv)
    import sharc_waverider_render as m1  # noqa: PLC0415
    from dnfw.cli.main import main as dnfw  # noqa: PLC0415
    m5c = dsp.section7(m1.dn2_section7(a.stock))
    builds = {
        "waverider-disc-m5c-nocall_DN2_1.11.syx":
            patched(m5c, CALL_SW, CALL_STOCK, jump_abs(AFTER_CALL_SW) + NOP16 + NOP48),
        "waverider-disc-m5c-callonly_DN2_1.11.syx":
            patched(m5c, READER_2ND_SW, READER_2ND_STOCK, jump_abs(READER_RET_SW) + NOP16),
    }
    for name in builds:
        if (a.outdir / name).exists():
            raise SystemExit(f"{a.outdir / name} exists: never overwrite a build")
    with tempfile.TemporaryDirectory() as tmp:
        for name, s7 in builds.items():
            p = pathlib.Path(tmp) / (name + ".s7")
            p.write_bytes(s7)
            print(f"{name}: section 7 sha256 {hashlib.sha256(s7).hexdigest()}")
            rc = dnfw(["build", "-o", str(a.outdir / name), "-s", f"7={p}", str(a.m5b)])
            if rc:
                return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
