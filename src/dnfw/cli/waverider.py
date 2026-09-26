"""`dnfw waverider` -- the baked-wavetable tooling (`docs/waverider-feasibility.md`).

  `dnfw waverider expect`               what Milestone 0's telemetry must show
  `dnfw waverider header OUT.h`         the C header the build compiles
  `dnfw waverider verify CAPTURE.txt`   check a `scripts/midi_watch.py` capture
  `dnfw waverider scan PATH`            a WAV or a folder of them: format, frames,
                                         and what the reduction will do to each
  `dnfw waverider bake PATH --out DIR`  reduce and bake each WAV: DIR/<name>.h
                                         and DIR/<name>.bin (big-endian int16)
  `dnfw waverider render OUT.wav`       the reference reader (Milestone 1): what
                                         the SHARC code must produce, as audio
  `dnfw waverider frame IMAGE OUT.bin`  the DSP parameter frame (Milestone 4) for
                                         the init sound, from IMAGE's own
                                         parameter defaults: what sw 0x1c2712 unpacks

`expect`, `header`, `verify` and `render` default to Milestone 0's original test table
(`dnfw.waverider.testtable`); `--wav FILE` uses a WAV instead. **Tables that
are not ours -- Elektron's factory set, third-party packs -- are for local
testing only** and never go into a build this project ships.
"""

import pathlib
import wave

from ..firmware.load import load
from ..image.coldfire import LoadedImage
from ..params import table as ptable
from ..waverider import bake, expect, frame, reduce, render, source, testtable
from .files import read_image

NAME = "waverider"
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
    p = sub.add_parser("render", help="render the reference reader to a WAV",
                       description="Render the reference wavetable reader "
                       "(dnfw.waverider.render) to a mono 16-bit 48 kHz WAV: "
                       "a fixed frame position, or a sweep 0 -> 15 -> 0.")
    p.add_argument("out", type=pathlib.Path, help="the WAV to write")
    p.add_argument("--wav", type=pathlib.Path, default=None,
                   help="reduce this WAV wavetable instead of the original test table")
    p.add_argument("--freq", type=float, default=110.0, help="pitch in Hz (default 110)")
    p.add_argument("--pos", type=float, default=None,
                   help="fixed frame position 0..15; default: sweep 0 -> 15 -> 0")
    p.add_argument("--seconds", type=float, default=2.0, help="length (default 2)")
    p.add_argument("--block", type=int, default=32,
                   help="samples per position update (default 32)")
    p.add_argument("--precision", choices=("ideal", "float32"), default="ideal",
                   help="double precision, or float32 rounded as the SHARC code rounds")
    p = sub.add_parser("frame", help="write the DSP parameter frame for the init sound",
                       description="Build the 2,688-byte parameter frame image the DSP's "
                       "sw 0x1c2712 unpacks (dnfw.waverider.frame), every track carrying the "
                       "init sound from IMAGE's parameter table defaults.")
    p.add_argument("image", type=pathlib.Path, help=".syx file, or a .zip containing one")
    p.add_argument("out", type=pathlib.Path, help="the frame image to write (DSP memory order)")
    p.add_argument("--machine", type=int, default=5, help="track 0's machine type (default 5)")
    p.add_argument("--filter", type=int, default=0, choices=range(6),
                   help="track 0's filter type, 0..5 = " + ", ".join(frame.FILTER_NAMES))
    p.add_argument("--trigger", action="store_true", help="set track 0's four trigger bits")
    p.add_argument("--set", action="append", default=[], metavar="INDEX=VALUE",
                   help="override a parameter of track 0 (16-bit value, e.g. 67=0 closes FREQ)")
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


def _render(args) -> int:
    table = _table(args)
    blocks = max(2, int(round(args.seconds * 48000 / args.block)))
    positions = ([render.position(args.pos)] * blocks if args.pos is not None
                 else render.sweep(len(table), blocks))
    samples = render.render_blocks(table, render.increment(args.freq), positions,
                                   args.block, 0, args.precision)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(render.pcm16(samples))
    print(f"  {args.out}: {len(samples):,} samples at 48 kHz, {args.freq} Hz, "
          f"{'position ' + str(args.pos) if args.pos is not None else 'sweep 0 -> 15 -> 0'}, "
          f"{args.precision}")
    return 0


def _frame(args) -> int:
    fw = load(read_image(args.image))
    sec = fw.container.find(3)
    tab = ptable.find(LoadedImage(dest=sec.dest, content=sec.unpack()), 15)[0]
    sound = frame.sound_defaults(tab.records)
    over = {}
    for item in args.set:
        index, _, value = item.partition("=")
        over[int(index, 0)] = int(value, 0)
    f = frame.init_frame(sound, args.machine, cf_filter=args.filter, trigger=args.trigger, track0=over)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(f.to_bytes())
    print(f"  {args.out}: {frame.FRAME_BYTES:,} B, track 0 machine {args.machine}, filter "
          f"{frame.FILTER_NAMES[args.filter]} (DSP {frame.dsp_filter(args.filter)}), "
          f"{len(sound)} init-sound parameters per track{', triggered' if args.trigger else ''}")
    return 0


def run(args) -> int:
    if args.action == "frame":
        return _frame(args)
    if args.action == "render":
        return _render(args)
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
          + f"  (once wr_passes > 0; a pass is {total['bursts_per_pass']} bursts)")
    print()
    print("   #  frame index   value    u16   frame idx_lo idx_hi  val_lo val_mid val_hi")
    for k, r in enumerate(expect.probes(table)):
        c = r["cc"]
        print(f"  {k:2d}  {r['frame']:5d} {r['index']:5d}  {r['value']:6d}  {r['u16']:5d}"
              f"   {c['wr_frame']:5d} {c['wr_idx_lo']:6d} {c['wr_idx_hi']:6d}"
              f"  {c['wr_val_lo']:6d} {c['wr_val_mid']:7d} {c['wr_val_hi']:6d}")
    return 0
