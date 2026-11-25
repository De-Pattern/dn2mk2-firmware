"""Gate step `depack` (v0.65, docs/packer.md): the instrument's own depacker on the build.

    ../digikit/.venv/bin/python scripts/emu_depack_check.py STOCK.syx BUILD.syx

v0.65 packs the sections the build changes with a new parse (codec.aplibopt). Our depacker
agreeing with our packer is one implementation agreeing with itself. This runs the
instrument's own aPLib depacker -- the bootstrap's routine at 0x80000432 (digikit's
emu.oracle, in its Unicorn machine), from stock 1.11's section 2, which the preflight checks
is untouched -- on every compressed section of the build that differs from stock, and
requires exactly the bytes our depacker gives (the content the build packed).

Negative control: the same stream of the smallest such section with one byte of its middle
flipped must NOT give that content back (the routine really reads the stream we hand it).

Prints one line a section, then `DEPACK PASS` or `DEPACK FAIL`.
"""
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
DIGIKIT = ROOT.parent / "digikit"
sys.path.insert(0, str(DIGIKIT))

from dnfw.firmware.load import load  # noqa: E402
from emu import oracle  # noqa: E402


def main() -> int:
    stock = load(pathlib.Path(sys.argv[1]).read_bytes()).container
    build = load(pathlib.Path(sys.argv[2]).read_bytes()).container
    boot = stock.find(2).unpack()
    if not boot:
        print("stock section 2 does not depack: DEPACK FAIL")
        return 1
    by_id = {s.id: s for s in stock.sections}
    changed = [s for s in build.sections
               if s.unpack() is not None and s.stored != by_id[s.id].stored]
    if not changed:
        print("no compressed section differs from stock: nothing the new parse made (DEPACK FAIL)")
        return 1
    ok = True
    for s in changed:
        want = s.unpack()
        t = time.time()
        try:
            got = oracle.depack(boot, s.stored)
        except Exception as e:      # the routine faulting is a failure, not a skip
            got = None
            print(f"section {s.id}: the instrument's depacker stopped: {e}")
        same = got == want
        ok &= same
        print(f"section {s.id}: {len(s.stored):,} bytes stored -> instrument's depacker "
              f"{'%s bytes, identical to ours' % format(len(got), ',') if same else 'DIFFERS'} "
              f"({time.time() - t:.0f} s)", flush=True)
    s = min(changed, key=lambda x: len(x.stored))
    bad = bytearray(s.stored)
    bad[8 + (len(bad) - 8) // 2] ^= 0x5A
    try:
        got = oracle.depack(boot, bytes(bad))
    except Exception:
        got = None
    control = got != s.unpack()
    ok &= control
    print(f"negative control: section {s.id} with one byte flipped "
          f"{'does not give its content back' if control else 'STILL GAVE ITS CONTENT BACK'}")
    print("DEPACK PASS" if ok else "DEPACK FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
