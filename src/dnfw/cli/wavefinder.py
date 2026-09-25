"""`dnfw wavefinder` -- the baked-wavetable tooling (`docs/wavefinder-feasibility.md`).

  `dnfw wavefinder expect`               what Milestone 0's telemetry must show
  `dnfw wavefinder header OUT.h`         the C header the build compiles
  `dnfw wavefinder verify CAPTURE.txt`   check a `scripts/midi_watch.py` capture
  `dnfw wavefinder scan PATH`            a WAV or a folder of them: format, frames,
                                         and what the reduction will do to each
  `dnfw wavefinder bake PATH --out DIR`  reduce and bake each WAV: DIR/<name>.h
                                         and DIR/<name>.bin (big-endian int16)

`expect`, `header` and `verify` default to Milestone 0's original test table
(`dnfw.wavefinder.testtable`); `--wav FILE` uses a WAV instead. **Tables that
are not ours -- Elektron's factory set, third-party packs -- are for local
testing only** and never go into a build this project ships.
"""

import pathlib

from ..wavefinder import bake, expect, reduce, source, testtable

NAME = "wavefinder"
HELP = "baked wavetables: scan and reduce WAVs, emit the C header, the expected telemetry"


def configure(parser) -> None:
    sub = parser.add_subparsers(dest="action", required=True)
    for name, help_ in (("expect", "print the values the firmware must report"),
                        ("header", "write the C header the build compiles"),
                        ("verify", "check a midi_watch.py capture against the expectation")):
        p = sub.add_parser(name, help=help_, description=help_)
        p.add_argument("--wav", type=pathlib.Path, default=None,
                       help="reduce this WAV wavetable instead of the original test table")
        if name == "header":
            p.add_argument("out", type=pathlib.Path, help="where to write the header")
        if name == "verify":
            p.add_argument("capture", type=pathlib.Path, help="midi_watch.py output, saved as text")
    p = sub.add_parser("scan", help="describe a WAV or every WAV in a folder")
    p.add_argument("path", type=pathlib.Path)
    p = sub.add_parser("bake", help="reduce and bake a WAV or every WAV in a folder")
    p.add_argument("path", type=pathlib.Path)
    p.add_argument("--out", type=pathlib.Path, required=True, help="directory for .h and .bin")


def _table(args) -> list[list[int]]:
    return reduce.from_wav(args.wav.read_bytes()) if args.wav else testtable.table()


def _scan(path: pathlib.Path) -> int:
    files = source.collect(path)
    if not files:
        raise ValueError(f"no .wav under {path}")
    bad = 0
    for f in files:
        i = source.info(f.read_bytes())
        if not i["ok"]:
            bad += 1
            print(f"  {f.name}: CANNOT USE -- {i['error']}")
            continue
        print(f"  {f.name}: {i['encoding']}, {i['channels']} ch, {i['rate']} Hz, "
              f"{i['samples']:,} samples = {i['frames']} x {i['frame']} ({i['origin']})")
        for w in i["warnings"]:
            print(f"      note: {w}")
    print(f"\n  {len(files)} file(s), {len(files) - bad} usable. Each reduces to "
          f"{reduce.FRAMES} x {reduce.POINTS} int16 = {reduce.FRAMES * reduce.POINTS * 2:,} B.")
    return 1 if bad else 0


def _bake(path: pathlib.Path, out: pathlib.Path) -> int:
    files = source.collect(path)
    if not files:
        raise ValueError(f"no .wav under {path}")
    out.mkdir(parents=True, exist_ok=True)
    print("  LOCAL TESTING ONLY unless the table is ours: nothing third-party ships.\n")
    for f in files:
        table = reduce.from_wav(f.read_bytes())
        (out / f"{f.stem}.h").write_text(bake.header(table, expect.PROBES, expect.SLICE),
                                         encoding="utf-8", newline="\n")
        (out / f"{f.stem}.bin").write_bytes(bake.to_bytes(table))
        print(f"  {f.name} -> {f.stem}.h / .bin, checksum {bake.checksum(table):#06x}")
    return 0


def run(args) -> int:
    if args.action == "scan":
        return _scan(args.path)
    if args.action == "bake":
        return _bake(args.path, args.out)
    table = _table(args)
    if args.action == "header":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(bake.header(table, expect.PROBES, expect.SLICE),
                            encoding="utf-8", newline="\n")
        print(f"  {args.out}: {len(table)} x {len(table[0])} int16, "
              f"checksum {bake.checksum(table):#06x}")
        return 0
    if args.action == "verify":
        ok, lines = expect.verify(expect.parse(args.capture.read_text(encoding="utf-8",
                                                                      errors="replace")), table)
        for line in lines:
            print(f"  {line}")
        print(f"\n  {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    total = expect.summary(table)
    print(f"  table: {len(table)} frames x {len(table[0])} points, int16, "
          f"{len(bake.to_bytes(table)):,} bytes")
    print(f"  probe_a (CC 26) = {expect.PROBE_A} in every burst")
    print(f"  checksum {total['checksum']:#06x} = {total['checksum']}: "
          + ", ".join(f"{k} = {v}" for k, v in total["cc"].items())
          + f"  (once wf_passes > 0; a pass is {total['bursts_per_pass']} bursts)")
    print()
    print("   #  frame index   value    u16   frame idx_lo idx_hi  val_lo val_mid val_hi")
    for k, r in enumerate(expect.probes(table)):
        c = r["cc"]
        print(f"  {k:2d}  {r['frame']:5d} {r['index']:5d}  {r['value']:6d}  {r['u16']:5d}"
              f"   {c['wf_frame']:5d} {c['wf_idx_lo']:6d} {c['wf_idx_hi']:6d}"
              f"  {c['wf_val_lo']:6d} {c['wf_val_mid']:7d} {c['wf_val_hi']:6d}")
    return 0
