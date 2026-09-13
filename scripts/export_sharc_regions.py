"""Write the SHARC image's regions out as flat files Ghidra can import.

## The address space Ghidra has to be given

digikit's SLEIGH module resolves a call target itself:

    Dest24: reloc = ((w1 & 0xff) << 17) + (w2 << 1)

so the addresses Ghidra works in are **not** the load addresses in
`docs/sharc-code-map.md`. They are that formula's output, which for the two
execution spaces this image uses comes out as:

    exec 0x1cXXXX  ->  0x380000 + 2 x XXXX      (the L2 code region)
    exec 0xb8WWWW  -> 0x1700000 + 2 x WWWW      (the L1 code region)

The first is just the load address with `0x28000000` removed, which is why the
earlier L2 import at base `0x3825c4` worked. The second is the useful part: it
says where L1 has to be placed for the 1,025 `0xb8` calls to land on their
targets **natively, with no fixing up** -- at `0xb8 << 17`, which does not
collide with anything else in the space.

Put both blocks in one program at those bases and the whole call graph resolves
inside Ghidra.

## Data references, and what is not claimed

A 32-bit operand is stored word-swapped (`scripts/sharc_callgraph.py` has the
evidence), and the value is the load address with `0x28000000` removed -- so
the rodata regions are placed at that same offset and string references resolve
too.

**The L1 blocks are placed by one affine rule, and only half of it is tested.**
`0x1700000 + (addr - 0x20000000)` is verified where the L1 *code* region sits,
because that is where 1,025 call targets land correctly. Applying the same rule
to the L1 *data* region that follows it is an extrapolation: no landmark has
been found in that region to check it against, and the rule that works for L2
data -- subtract `0x28000000` -- cannot apply here, since L1 addresses are below
it. The manifest marks those blocks `unverified` so a listing taken there is
read as a hypothesis. The DDR region at `0x80000000` is not placed at all;
nothing constrains where it would go.

    python scripts/export_sharc_regions.py <image> --out out/sharc
"""

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image          # noqa: E402
from dnfw.firmware.load import load            # noqa: E402
from dnfw.image import bootstream              # noqa: E402

BLOB = 7
L1_BASE = 0x20000000
L2_BASE = 0x28000000

# Where each load region goes in the flat space the SLEIGH module addresses.
# L1 regions land at (0xb8 << 17) + (addr - L1_BASE); L2 at addr - L2_BASE.
L1_FLAT = 0xB8 << 17


def flat_base(addr: int):
    if L1_BASE <= addr < 0x28000000:
        return L1_FLAT + (addr - L1_BASE)
    if addr >= L2_BASE and addr < 0x80000000:
        return addr - L2_BASE
    return None                     # DDR at 0x80000000: no mapping established


def call_sites(base: int, blob: bytes):
    for off in range(0, len(blob) - 6, 2):
        w0, w1, w2 = struct.unpack_from("<HHH", blob, off)
        insn = (w0 << 32) | (w1 << 16) | w2
        if (insn >> 24) & 0xFFFFFF == 0x180400:
            yield base + off, insn & 0xFFFFFF


def exec_to_load(target: int):
    space = target >> 16
    if space == 0x1C:
        return target * 2 + L2_BASE
    if space == 0xB8:
        return (target & 0xFFFF) * 2 + L1_BASE
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", type=pathlib.Path)
    p.add_argument("--section", type=int, default=BLOB)
    p.add_argument("--out", default="out/sharc")
    p.add_argument("--min-bytes", type=int, default=512,
                   help="skip regions smaller than this")
    args = p.parse_args(argv)

    fw = load(read_image(args.image))
    section = fw.container.find(args.section)
    if section is None:
        raise SystemExit(f"image has no section id={args.section}")
    regions = bootstream.load_regions(section.unpack() or section.raw_payload)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest, entries = [], set()
    for base, blob in regions:
        flat = flat_base(base)
        calls = sum(1 for _ in call_sites(base, blob))
        if flat is None or len(blob) < args.min_bytes:
            print(f"  skip  0x{base:08x}  {len(blob):>9,} bytes  "
                  f"{'no flat mapping' if flat is None else 'too small'}")
            continue
        kind = "code" if calls >= 100 else "data"
        # Verified means: something independent lands where this rule predicts.
        # True for the two code regions (call targets) and for L2 data (string
        # references); an extrapolation for the L1 data that trails L1 code.
        verified = "verified" if (kind == "code" or base >= L2_BASE) \
            else "unverified"
        name = f"{kind}_{base:08x}"
        path = out / f"{name}.bin"
        path.write_bytes(blob)
        manifest.append((name, flat, len(blob), kind, path.name, verified))
        print(f"  0x{base:08x} -> flat 0x{flat:07x}  {len(blob):>9,} bytes  "
              f"{kind:<5} {calls:>5} calls  {verified:<10} {path.name}")
        if kind == "code":
            for _, target in call_sites(base, blob):
                addr = exec_to_load(target)
                if addr is not None:
                    fb = flat_base(addr)
                    if fb is not None:
                        entries.add(fb)

    (out / "manifest.tsv").write_text(
        "".join(f"{n}\t0x{b:x}\t{ln}\t{k}\t{f}\t{v}\n"
                for n, b, ln, k, f, v in manifest))
    (out / "entries.txt").write_text(
        "".join(f"0x{e:x}\n" for e in sorted(entries)))
    print(f"\nwrote {out/'manifest.tsv'} ({len(manifest)} blocks) and "
          f"{out/'entries.txt'} ({len(entries)} function entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
