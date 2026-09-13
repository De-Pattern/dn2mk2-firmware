"""Hand our own extraction to the emulator, for a firmware it cannot open itself.

`m-dwyer/digikit` decompresses a firmware by **running the updater's own aPLib
depacker under emulation** rather than reimplementing it (`docs/emulator.md`).
That is why its output is worth cross-checking against: the agreement is with
the device's code, not with another author's reading of it.

It also means digikit needs to *find* that routine, and its address is a
constant derived on Digitakt II 1.15C. It holds on Digitone II 1.10E. On **our
1.11 it unpacks nothing**:

    ValueError: implausible output length 0

But digikit does not have to do the extraction. `emu/config.py` resolves a
sections directory by glob and checks one stamp, so a directory built by any
tool is acceptable to it — its own `NAMES` comment says as much, mapping section
ids to *"the names elektron-firmware-tool uses, so a directory extracted either
way looks the same"*.

`dnfw` opens 1.11 perfectly well. So this writes our extraction in the layout
digikit expects, which unblocks the emulator on 1.11 without touching its code
or waiting on a re-derived constant.

**This is not a workaround that hides a difference.** Our extractor was verified
byte-identical to digikit's on all five sections of 1.10E, and section 4's
8-byte discrepancy was found and fixed by that comparison. Run
`--verify-against` to repeat the check on any firmware both tools can open,
before trusting this bridge on one only we can.

Two details, both taken from digikit rather than assumed:

* the filenames are `section_<id>_<NAME>.bin` with `NAMES = {2: DSP,
  3: MAIN_OS, 4: UPDATER, 5: META, 7: BLOB}`. Section 2 is the **bootstrap**,
  and digikit says so in the same breath — `DSP` is elektron-firmware-tool's
  mistake, kept for compatibility. We match the wrong name deliberately;
  changing it here would only break the glob.
* `.source-sha256` holds the hex digest of the `.syx`, and digikit refuses to
  pair a sections directory with a firmware whose hash disagrees. That check is
  the reason mixing two firmwares in one directory cannot happen silently, so
  this writes it rather than working around it.

No firmware bytes live in this repository; output goes wherever you point it.
"""

import argparse
import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.firmware.load import load

# digikit's emu/extract.py NAMES, verbatim. See the module docstring on `DSP`.
NAMES = {2: "DSP", 3: "MAIN_OS", 4: "UPDATER", 5: "META", 7: "BLOB"}
SOURCE_MARKER = ".source-sha256"


def payload_of(section) -> tuple[str, bytes]:
    """What belongs in the file: decompressed if packed, header-stripped if raw."""
    content = section.unpack()
    if content is not None:
        return "packed", content
    return "raw", section.raw_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=pathlib.Path, help=".syx, or a .zip holding one")
    parser.add_argument("-o", "--out", type=pathlib.Path, required=True,
                        help="sections directory to write (point DT2_SECTIONS here)")
    parser.add_argument("--verify-against", type=pathlib.Path, default=None,
                        help="a digikit-extracted sections directory to compare against")
    args = parser.parse_args()

    raw = read_image(args.image)
    firmware = load(raw)
    digest = hashlib.sha256(raw).hexdigest()

    args.out.mkdir(parents=True, exist_ok=True)
    # Drop any earlier extraction of each section whatever it was named, exactly
    # as digikit does -- a directory holds one firmware at a time, and a stale
    # file that still matches the glob is how two would get mixed.
    written = []
    for section in firmware.container.sections:
        name = NAMES.get(section.id)
        if name is None:
            print(f"  section {section.id}: no digikit name, skipped")
            continue
        for stale in args.out.glob(f"section_{section.id}_*.bin"):
            stale.unlink()
        kind, payload = payload_of(section)
        path = args.out / f"section_{section.id}_{name}.bin"
        path.write_bytes(payload)
        written.append((section.id, kind, path, len(payload), section.dest))
        print(f"  {path.name:<26} {kind:<7} {len(payload):>9,} bytes  dest 0x{section.dest:08x}")

    (args.out / SOURCE_MARKER).write_text(digest + "\n")
    print(f"\n  {SOURCE_MARKER}: {digest}")
    print(f"  wrote {len(written)} section(s) to {args.out}")

    if args.verify_against:
        return _verify(args.out, args.verify_against)

    print("\nPoint the emulator at it:")
    print(f"  DT2_SECTIONS={args.out} python -m emu.run {args.image} --check")
    return 0


def _verify(ours: pathlib.Path, theirs: pathlib.Path) -> int:
    """Compare against a digikit-extracted directory, file by file."""
    print(f"\nverifying against {theirs}")
    bad = 0
    for path in sorted(ours.glob("section_*.bin")):
        other = theirs / path.name
        if not other.exists():
            print(f"  {path.name:<26} MISSING on their side")
            bad += 1
            continue
        a, b = path.read_bytes(), other.read_bytes()
        if a == b:
            print(f"  {path.name:<26} identical ({len(a):,} bytes)")
        else:
            bad += 1
            note = f"ours {len(a):,} vs theirs {len(b):,}"
            if a[8:] == b:
                note += "  -- ours[8:] == theirs: an unstripped 8-byte header"
            print(f"  {path.name:<26} DIFFER  {note}")
    print("\n  all sections agree" if not bad else f"\n  {bad} section(s) disagree")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
