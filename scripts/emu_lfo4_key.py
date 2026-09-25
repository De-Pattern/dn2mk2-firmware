"""Does the tick ask for LFO4's row under the key the panel wrote it with?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_BUILD=out/lfo4-meterkeep \
        /root/dn2-emu-venv/bin/python -u scripts/emu_lfo4_key.py

**The evidence this is aimed at.** On the instrument LFO4 modulates on roughly
one trig in fifteen. Everything from the panel to the mirror cell is measured
and correct, and `emu_lfo4_vs_lfo3.py` found the evaluator treats LFO4 and LFO3
byte-identically over 240 frames. **A wrong cell would never work. One in
fifteen is not a wrong cell -- it is a key that usually misses.**

`lfo4_refresh` in `csrc/lfo4/bridge.c` reads the row like this:

    sound  = lfo4_sound_of(track);
    values = ext_find(sound);
    for (k...) row[k] = values ? values[k] : ext_default[k];

**A miss is not silent and it is not a no-op: it fills the row with the
defaults**, whose `DEST` is None. So a row that misses modulates nothing, and a
row that hits modulates -- which is exactly binary-per-note behaviour.

`lfo4_hits`, `lfo4_misses` and `lfo4_last_lookup` were added to the bridge to
measure this and **have never been read by anything**. This reads them.

**The prediction, written before the run.** The panel's setter is keyed on the
sound pointer the UI holds; the tick asks `lfo4_sound_of(track)`. If those two
agree, the key theory dies here and the fault is downstream. If they differ,
the fault is the key and no flash was needed to find it.

**The control.** A store under the tick's own key must produce a hit. If even
that misses, the harness is broken and nothing below it means anything -- the
same rule that cost three flashes in `docs/lfo4-build-plan.md`.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build      # noqa: E402
from emulib.machine import SNAP, Machine                           # noqa: E402

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-meterkeep"))
LIVE_CONTAINER, SOUND_AT, SOUND_STRIDE = 0x800052A0, 52, 1163
DEST_SLOT, DEST_VALUE = 3, 67 << 8          # a real destination, not None


def counters(m, sym):
    return (m.long(sym["lfo4_hits"]), m.long(sym["lfo4_misses"]),
            m.long(sym["lfo4_last_lookup"]) - (1 << 32)
            if m.long(sym["lfo4_last_lookup"]) >> 31 else m.long(sym["lfo4_last_lookup"]))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tracks", type=int, default=8)
    args = p.parse_args()

    m = Machine(SNAP)
    image, sym = load_build(BUILD)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"],
                              "section_3_MAIN_OS.bin"), "rb").read()
    m.apply(differences(stock, image))
    for load, _n, bss, init, blob in code_chunks(image):
        m.load_code_chunk((load, len(blob), bss, init, blob))
    m.flush()

    base = m.long(LIVE_CONTAINER)
    print(f"  live container {base:#010x}\n")
    print("  track   panel key (base+52+1163*t)   lfo4_sound_of(t)   agree")
    agree = 0
    keys = []
    for t in range(args.tracks):
        panel = base + SOUND_AT + SOUND_STRIDE * t
        tick = m.call(sym["lfo4_sound_of"], t)
        keys.append((panel, tick))
        same = panel == tick
        agree += same
        print(f"   {t:2d}     {panel:#010x}                {tick:#010x}       "
              f"{'yes' if same else 'NO'}")
    print(f"\n  {agree}/{args.tracks} tracks agree\n")

    # --- the control: store under the tick's own key, then refresh ----------
    t = 0
    _, tick = keys[t]
    m.call(sym["ext_set"], tick, DEST_SLOT, DEST_VALUE)
    h0, s0, _ = counters(m, sym)
    m.call(sym["lfo4_refresh"], t)
    h1, s1, last = counters(m, sym)
    control_ok = h1 > h0 and s1 == s0
    print(f"  control  store under lfo4_sound_of(0) -> hits {h0}->{h1}, "
          f"misses {s0}->{s1}, last_lookup {last}  "
          f"{'HIT (control good)' if control_ok else 'MISS -- HARNESS BROKEN'}")
    if not control_ok:
        print("\n  The control missed. Nothing below this line means anything.")
        return 2

    # --- the test: store under the panel key for a track where they differ --
    differing = [i for i, (pa, ti) in enumerate(keys) if pa != ti]
    if not differing:
        print("\n  **The two keys agree on every track.** The key theory dies here;")
        print("  the fault is downstream of the lookup and this probe says so.")
        return 0
    t = differing[0]
    panel, tick = keys[t]
    m.call(sym["ext_set"], panel, DEST_SLOT, DEST_VALUE)
    h0, s0, _ = counters(m, sym)
    m.call(sym["lfo4_refresh"], t)
    h1, s1, last = counters(m, sym)
    print(f"\n  test     track {t}: stored under {panel:#010x}, tick asks {tick:#010x}")
    print(f"           hits {h0}->{h1}, misses {s0}->{s1}, last_lookup {last}")
    if s1 > s0:
        print("\n  **The tick missed a row the panel had written.** The row falls back")
        print("  to ext_default, whose DEST is None, so that note modulates nothing.")
        print("  That is the fault, found offline, and it is a key and not a cell.")
        return 1
    print("\n  The tick found it anyway -- the keys differ but the lookup tolerates it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
