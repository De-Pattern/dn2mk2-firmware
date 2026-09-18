"""Write the Python spin-transition frames for the cases `js_batspin_check.mjs` compares.

    PYTHONPATH=src python scripts/py_batspin_ref.py OUT_DIR
"""
import pathlib
import sys

from dnfw import batspin
from dnfw.cli.mods import _read_pgm

CASES = [  # mirrors scripts/js_batspin_check.mjs
    {},
    dict(resolve=30, idle_frames=6, stars=200, smear=2.5, spin=7, zoom=2, seed=3),
    dict(resolve=2, idle_frames=1, stars=0, smear=0, spin=0, zoom=0),
]
out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
pix = _read_pgm(pathlib.Path("site/art/chimera.pgm"))
for k, opts in enumerate(CASES):
    fr = batspin.frames(lambda x, y: (x, y) in pix, **opts)
    (out / f"case{k}.bin").write_bytes(b"".join(bytes(f) for f in fr))
print(f"wrote {len(CASES)} cases")
