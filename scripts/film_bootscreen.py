"""Film the boot-screen intro under the emulator, stock beside modded: a strip and GIFs.

    python scripts/film_bootscreen.py ascii  [--resolve 96 --idle-frames 16 ...]
    python scripts/film_bootscreen.py spin
    python scripts/film_bootscreen.py tunnel

Runs digikit's `guirun.py` (in WSL) twice from the same 1.11 snapshot taken just
before the intro -- once stock, once with the mod's bytes written into memory --
and captures the screen every 1M instructions (about four intro frames).

The snapshot is past boot, so the boot hook that copies the appended area above
BSS has already run (stock). The film therefore writes the area straight to its
run-time address, `0x46710000`, along with every section 3 edit the mod makes:
what the boot hook would have done, done by hand. Everything after that -- the
intro calling the stamp, the stamp reading the chunk -- is the real code running.

Writes `docs/img/intro-<mode>-sequence.png`, `docs/img/intro-<mode>.gif` and
`docs/img/intro-stock-film.gif`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image
from dnfw.cli.mods import _read_pgm
from dnfw.firmware.load import load
from dnfw.mods import bootscreen

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
SYX = "/mnt/c/ZZ_Code/ZZ_Personal/dn2_firmware/00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
SNAP = "~/dn2-snapshots/Digitone_II_OS1.11/boot400M.snap"
WORK = ROOT / "out/film"
START, STEP, SHOTS = 3, 1, 38            # millions of instructions from the snapshot; the first capture lands after 3M


def wsl_path(p: pathlib.Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    return "/mnt/" + s[0].lower() + s[2:]


def ranges(stock: bytes, content: bytes) -> list[dict]:
    """Every section 3 byte the mod changed, plus the appended area at run time."""
    out, i, n = [], 0, len(stock)
    while i < n:
        if stock[i] == content[i]:
            i += 1
            continue
        j = i
        while j < n and stock[j] != content[j]:
            j += 1
        out.append({"va": f"{bootscreen.BASE + i:#x}", "hex": content[i:j].hex()})
        i = j
    out.append({"va": f"{bootscreen.SPEC['runtime_va']:#x}", "hex": content[n:].hex()})
    return out


def film(name: str, patch: pathlib.Path | None) -> list[pathlib.Path]:
    shots = [WORK / name / f"f{k:03d}.png" for k in range(SHOTS)]
    shots[0].parent.mkdir(parents=True, exist_ok=True)
    pngs = " ".join(f"--png-at {START + STEP * (k + 1)}M:{wsl_path(p)}" for k, p in enumerate(shots))
    extra = f"--patch-ranges {wsl_path(patch)}" if patch else ""
    script = (f"cd /mnt/c/ZZ_Code/ZZ_Personal/digikit && export DT2_SECTIONS=/root/dn2-sections-111 && "
              f"timeout 1800 /root/dn2-emu-venv/bin/python tools/guirun.py {SNAP} --weakptr --slc "
              f"--syx {SYX} {extra} {pngs} --limit {(START + STEP * SHOTS + 6) * 1_000_000}")
    run = subprocess.run(["wsl", "bash", "-lc", script], capture_output=True, text=True)
    missing = [p for p in shots if not p.exists()]
    if missing:
        print(run.stdout[-2000:], run.stderr[-2000:])
        raise SystemExit(f"{name}: {len(missing)} of {SHOTS} shots missing")
    return shots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["ascii", "spin", "tunnel"])
    ap.add_argument("--pgm", type=pathlib.Path, default=ROOT / "site/art/chimera.pgm")
    ap.add_argument("--resolve", type=int, default=96)
    ap.add_argument("--idle-frames", type=int, default=16)
    ap.add_argument("--glitch", type=float, default=1.0)
    ap.add_argument("--idle", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=26)
    args = ap.parse_args()

    from PIL import Image

    firmware = load(read_image(STOCK))
    stock = firmware.container.find(3).unpack()
    pix = _read_pgm(args.pgm)
    if args.mode == "ascii":
        ascii = bootscreen.ascii_frames(lambda x, y: (x, y) in pix, resolve=args.resolve,
                                        idle_frames=args.idle_frames, glitch=args.glitch,
                                        idle=args.idle, seed=args.seed)
        result = bootscreen.apply(firmware, [], ascii=ascii)
    elif args.mode == "spin":
        result = bootscreen.apply(firmware, [], ascii=bootscreen.spin_frames(
            lambda x, y: (x, y) in pix, seed=args.seed))
    else:
        mark = bootscreen.image_from_pixels(pix)
        result = bootscreen.apply(firmware, [mark, bootscreen.invert(mark)])
    WORK.mkdir(parents=True, exist_ok=True)
    patch = WORK / f"{args.mode}.ranges.json"
    patch.write_text(json.dumps({"ranges": ranges(stock, result.payloads[3])}))
    print("\n".join(result.notes))

    stock_shots = film("stock", None)
    mod_shots = film(args.mode, patch)

    img = ROOT / "docs/img"
    frames = lambda shots: [Image.open(p).convert("RGB") for p in shots]
    s, m = frames(stock_shots), frames(mod_shots)
    w, h = s[0].size
    pick = list(range(0, SHOTS, 4))
    strip = Image.new("RGB", (len(pick) * (w + 4), 2 * h + 4), (60, 60, 60))
    for n, k in enumerate(pick):
        strip.paste(s[k], (n * (w + 4), 0))
        strip.paste(m[k], (n * (w + 4), h + 4))
    strip.save(img / f"intro-{args.mode}-sequence.png")
    m[0].save(img / f"intro-{args.mode}.gif", save_all=True, append_images=m[1:], duration=120, loop=0)
    s[0].save(img / "intro-stock-film.gif", save_all=True, append_images=s[1:], duration=120, loop=0)
    print(f"wrote docs/img/intro-{args.mode}-sequence.png (top stock, bottom {args.mode}), "
          f"intro-{args.mode}.gif, intro-stock-film.gif")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
