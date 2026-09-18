"""Write the Python ASCII-glitch frames for the cases `js_asciiglitch_check.mjs` compares.

    PYTHONPATH=src python scripts/py_asciiglitch_ref.py OUT_DIR
"""
import pathlib
import sys

from dnfw import asciiglitch
from dnfw.cli.mods import _read_pgm

CASES = [  # mirrors scripts/asciiglitch_cases.mjs
    {},
    dict(ramp=" .-=+*#%@", glitch_chars="01<>/\\", resolve=24, idle_frames=8, seed=7, glitch=1.6, idle=0.9),
    dict(resolve=1, idle_frames=0, glitch=0, idle=0),
]

out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
pix = _read_pgm(pathlib.Path("site/art/chimera.pgm"))
for k, opts in enumerate(CASES):
    fr = asciiglitch.frames(lambda x, y: (x, y) in pix, **opts)
    (out / f"case{k}.bin").write_bytes(b"".join(bytes(f) for f in fr))
print(f"wrote {len(CASES)} cases")
