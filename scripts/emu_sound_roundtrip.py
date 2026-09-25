"""Which bytes of a live sound does the firmware itself carry through save and load?

    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_sound_roundtrip.py --build out/lfo4-everyvoice

**The question.** LFO3's values live inside the sound's own 1,163 bytes, so
every stock path -- save, load, the delivery into a voice, kit copies, undo --
moves them without knowing what they are. LFO4's live in a side table, so each
path has had to be taught, and persistence is the one still failing. The
complete fix is to put LFO4 where LFO3's already are: in bytes the firmware
carries on its own. That needs sixteen bytes (eight 16-bit values) that the
stock converters round-trip **verbatim** and that nothing else interprets.

**Why measure instead of read.** `docs/lfo4-build-plan.md` §8 recorded that "a
live sound has no free slots". That was a reading. This asks the converters.

**How.** Stock converters only: it boots the **unmodified** 1.11 MAIN OS by
default, because an LFO4 build patches its own hooks onto both converters'
entries and they write into exactly the stored holes being measured.

1. **SAVE direction.** Fill a live sound with 16-bit tags, one per word, each
   naming its own offset (`0x4000 + offset/2`). Run `SAVE(stored, live, 0)`.
   Every tag found in the stored sound says "live offset o was written to
   stored offset s".
2. **LOAD direction.** Fill a stored sound with tags (`0x5000 + offset/2`),
   keeping the four-byte magic and version the converter checks. Run
   `LOAD(live, stored)` into a zeroed live sound. Every tag found says "stored
   offset s was written to live offset o".
3. **Round trip.** A live offset `o` is carried by the firmware itself when
   SAVE puts it at `s` and LOAD puts `s` back at `o`.

Then the report separates the carried offsets that are **stock parameter slots**
(`sound + 20 + 2*slot`, slots 0..100) from the rest. The
rest is where LFO4 could live.

**What it cannot say.** Whether those bytes are free at *run time* -- the engine,
the UI and the sequencer do not run here. A carried, non-parameter offset is a
candidate, to be checked with a write-watch before anything is built on it.

**Read-only against the firmware:** scratch buffers only.
"""

from __future__ import annotations

import argparse
import collections
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import emu_boot_engine as eng                                  # noqa: E402
from emu import dspboot                                        # noqa: E402
from unicorn import UcError                                    # noqa: E402

LIVE, STORED = eng.SOUND_BYTES, eng.STORED          # 1163, 359
TAG_LIVE, TAG_STORED = 0x4000, 0x5000


def words(buf):
    return [struct.unpack(">H", buf[i:i + 2])[0] for i in range(0, len(buf) - 1, 2)]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", default="out/ext111/section_3_MAIN_OS.aplib.bin",
                   help="MAIN OS to boot (default: stock 1.11, unpacked)")
    p.add_argument("--limit", type=int, default=400_000_000)
    args = p.parse_args()

    image = os.path.join(eng.ROOT, args.image)
    holder = {}
    print(f"  booting {args.image} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(eng.SYX, open(image, "rb").read(),
                              limit=args.limit, machine_out=holder)
    print(f"  ran {st['n']:,}, stop {stop!r}")
    after = eng.After(m.uc)

    # A real sound to start from, so the converter sees a plausible object:
    # track 1 of the live kit, copied into scratch.
    base = after.long(0x800052A0)
    real = bytes(after.uc.mem_read(base + 52, LIVE)) if base else bytes(LIVE)

    # 1. SAVE: live -> stored.
    live = after.alloc(LIVE + 16)
    stored = after.alloc(STORED + 16)
    tagged = bytearray(real)
    for o in range(0, LIVE - 1, 2):
        struct.pack_into(">H", tagged, o, TAG_LIVE + o // 2)
    after.write(live, bytes(tagged))
    after.write(stored, bytes(STORED))
    try:
        after.call(eng.SAVE, stored, live, 0)
    except UcError as exc:
        print(f"  ** SAVE faulted: {exc} **")
        return 1
    out = bytes(after.uc.mem_read(stored, STORED))
    save_map = {}                                   # live offset -> stored offset
    for s in range(0, STORED - 1):
        w = struct.unpack(">H", out[s:s + 2])[0]
        if TAG_LIVE <= w < TAG_LIVE + LIVE // 2:
            save_map.setdefault(2 * (w - TAG_LIVE), s)
    print(f"\n  SAVE carried {len(save_map)} live word(s) verbatim into the stored sound")

    # 2. LOAD: stored -> live.
    src = after.alloc(STORED + 16)
    dst = after.alloc(LIVE + 16)
    st_tag = bytearray(STORED)
    for s in range(0, STORED - 1, 2):
        struct.pack_into(">H", st_tag, s, TAG_STORED + s // 2)
    st_tag[0:4] = bytes([0xBE, 0xEF, 0xBA, 0xCE])   # the magic the converter checks
    st_tag[4:8] = (3).to_bytes(4, "big")            # and the version
    after.write(src, bytes(st_tag))
    after.write(dst, bytes(LIVE))
    try:
        after.call(eng.LOAD, dst, src)
    except UcError as exc:
        print(f"  ** LOAD faulted: {exc} **")
        return 1
    back = bytes(after.uc.mem_read(dst, LIVE))
    load_map = {}                                   # stored offset -> live offset
    for o in range(0, LIVE - 1):
        w = struct.unpack(">H", back[o:o + 2])[0]
        if TAG_STORED <= w < TAG_STORED + STORED // 2:
            load_map.setdefault(2 * (w - TAG_STORED), o)
    print(f"  LOAD carried {len(load_map)} stored word(s) verbatim into the live sound")

    # 3. Round trip.
    carried = sorted(o for o, s in save_map.items() if load_map.get(s) == o)
    print(f"\n  live offsets the firmware round-trips on its own: {len(carried)}")
    # The value array starts at sound + 20 -- the address the delivery memcpy
    # takes (0x4002549c) -- so slot s is at +20 + 2*s. The first version used
    # +14 and misread stored id 32 as landing in slot 3; the stock load map
    # (0x401fd0b0) folds it onto slot 0, the sink, with ids 0, 4 .. 28.
    param_offsets = {20 + 2 * slot for slot in range(0, 101)}
    free = [o for o in carried if o not in param_offsets]
    runs, cur = [], []
    for o in free:
        if cur and o != cur[-1] + 2:
            runs.append(cur)
            cur = []
        cur.append(o)
    if cur:
        runs.append(cur)
    print(f"    of which stock parameter slots (sound+20+2*slot, slots 0..100): "
          f"{len(carried) - len(free)}")
    print(f"    outside the parameter slots: {len(free)} word(s), in {len(runs)} run(s)")
    for r in runs:
        print(f"      live +{r[0]}..+{r[-1] + 1}  ({2 * len(r)} bytes) -> stored "
              f"+{save_map[r[0]]}..+{save_map[r[-1]] + 1}")
    big = [r for r in runs if len(r) >= 8]
    print(f"\n  runs of eight words or more (room for LFO4's eight values): {len(big)}")

    # And the stored holes LFO4 already uses: where does LOAD put them?
    holes = [eng.VALUES_AT + 2 * i for i in eng.LFO4_IDS]
    print("\n  the stored LFO4 holes (ids 4,8..32) under the stock LOAD:")
    for s in holes:
        o = load_map.get(s)
        print(f"    stored +{s:<3d} -> {('live +' + str(o)) if o is not None else 'dropped'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
