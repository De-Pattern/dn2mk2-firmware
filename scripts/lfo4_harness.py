"""The LFO4 build in a restored snapshot: its code, its init, its patch sites.

Everything general -- restoring, memory, calls, diffs, checks -- now lives in
`scripts/emulib/`, because five harnesses had grown their own copy of it. What
is left here is the part that is about LFO4 and nothing else: where its `CODE`
chunk goes, and how its table is read and written from outside.

Kept as re-exports (`SNAP`, `Machine`, `check`, `report`, `differences`, ...)
so the scripts written before the split keep working unchanged.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emulib.image import code_chunk, differences, load_build, sites     # noqa: F401,E402
from emulib.machine import SCRATCH, SNAP, STACK, SYX, Machine           # noqa: F401,E402
from emulib.report import check, failures, report                       # noqa: F401,E402

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-ext"
SOUND, KIT = 1163, 23921          # one live sound; the block that holds sixteen
PARAMS = 8


class Harness(Machine):
    """A machine with the LFO4 build installed the way the loader and the
    patch would have left it."""

    def __init__(self, snapshot, image, symbols, build=BUILD):
        super().__init__(snapshot)
        self.sym = symbols
        self.image = image
        self.build = build
        self.load, length, self.bss_len, self.init, self.code = code_chunk(image)
        self.bss = self.load + length

    def u32(self, name):
        return self.long(self.sym[name])

    def install(self):
        """The loader's copy and init, then every site the build patched."""
        self.load_code_chunk((self.load, self.bss - self.load, self.bss_len, self.init, self.code))
        self.patch_sites(sites(self.build))

    def reset(self):
        """Back to a just-booted table, without re-restoring the snapshot."""
        self.write(self.bss, bytes(self.bss_len))
        self.call(self.init)

    # --- the table, through its own API ------------------------------------
    def set(self, key, values):
        for p, v in enumerate(values):
            self.call(self.sym["ext_set"], key, p, v)

    def get(self, key):
        return [self.call(self.sym["ext_get"], key, p) & 0xFFFF for p in range(PARAMS)]
