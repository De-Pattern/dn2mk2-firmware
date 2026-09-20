"""The whole of LFO4 under the emulator: a value in the table reaches the engine.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python \\
        scripts/emu_lfo4_bridge.py [--frames 40]

Steps 1-3 each proved one thing separately. This asks the question they were
for: **put LFO4's eight values in the table for one track's sound, and does that
track -- and only that track -- modulate?**

Nothing is laid out by hand except the table entry. The sound address comes from
the build's own `lfo4_sound_of`, so the harness and the firmware agree on the
track -> sound map by construction rather than by two copies of the arithmetic.

Then the same question again after an edit: `ext_set` bumps `ext_generation`,
so the next frame must pick the new value up without anything being told.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")

from emu_lfo4_tick import (DEST_SLOT, EVAL_A, MIRROR_AT, MIRROR_BYTES, MIRROR_SLOTS,  # noqa: E402
                           RATE, REST, SET_FRAC, STATE, STATE_LEN, TRACKS, differences)
from lfo4_harness import SNAP, Machine, check, code_chunk, report  # noqa: E402

BUILD = "/mnt/d/01_Code/Z_Personal/dn2_firmware/out/lfo4-bridge"
TRACK = 1                                  # 0-based: the second track
FAST = (0x7000, 0x0100, 0x4000, DEST_SLOT << 8, 0x0100, 0x0000, 0x0000, 0x5000)
SLOWER = (0x0800,) + FAST[1:]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", default=SNAP)
    p.add_argument("--frames", type=int, default=40)
    args = p.parse_args()

    sym = {k: int(v, 16) for k, v in json.load(open(f"{BUILD}/symbols.json")).items()}
    stock = open(os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin"), "rb").read()
    image = open(f"{BUILD}/section_3_MAIN_OS.bin", "rb").read()
    runs = differences(stock, image)

    m = Machine(args.snapshot)
    for va, blob in runs:
        m.write(va, blob)
    m.flush()
    print(f"{len(runs)} changed run(s), {sum(len(b) for _, b in runs)} byte(s) into the snapshot")

    # The startup loader would have done this at boot -- copy the CODE chunk to
    # its run address, zero its BSS, call its init. A snapshot has already run
    # past that point, so the harness does the loader's job verbatim.
    load, length, bss, init, blob = code_chunk(image)
    m.write(load, blob)
    m.write(load + length, bytes(bss))
    m.call(init)
    print(f"  loader's work: {len(blob)} B at {load:#010x}, {bss:,} B of state zeroed, init at {init:#010x}")
    frac = m.alloc(len(SET_FRAC))
    m.write(frac, SET_FRAC)
    m.call(frac)

    span = MIRROR_AT + TRACKS * MIRROR_BYTES + 32
    buf = m.alloc(span)
    rest = struct.pack(">H", REST) * (span // 2)
    for base in STATE:
        m.write(base, bytes(STATE_LEN))
    rate = m.long(RATE)
    out1, out2 = m.alloc(256), m.alloc(256)

    sound = m.call(sym["lfo4_sound_of"], TRACK)
    print(f"  track {TRACK + 1}'s live sound, from the firmware's own map: {sound:#010x}\n")

    def frames(values):
        for slot, value in enumerate(values):
            m.call(sym["ext_set"], sound, slot, value)
        m.write(buf, rest)
        for base in STATE:                 # from phase zero, so only the rate differs
            m.write(base, bytes(STATE_LEN))
        for _ in range(args.frames):
            m.call(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, out1, out2, 0)
        after = m.read(buf, span)
        written = {}
        for off in range(0, span - 1, 2):
            if after[off:off + 2] != rest[off:off + 2]:
                track, rem = divmod(off - MIRROR_AT, MIRROR_BYTES)
                written[(track, rem // 2)] = struct.unpack(">H", after[off:off + 2])[0]
        return written

    first = frames(FAST)
    for (track, slot), value in sorted(first.items())[:3]:
        print(f"  track {track + 1:<2} slot {slot:<3} -> {value:#06x}")
    print(f"  ... {len(first)} word(s) written\n")

    check("the table entry reached the engine: that track modulated slot 76",
          (TRACK, DEST_SLOT) in first, f"{sorted(k for k in first if k[0] == TRACK)}")
    check("and every other track fell back to the default, DEST = 0",
          all(slot == 0 for (track, slot) in first if track != TRACK),
          f"{sorted((t + 1, s) for t, s in first if t != TRACK and s != 0)}")
    check("and nothing else modulated at all: a row of zeros is a silent LFO",
          len(first) == 1, f"{len(first)} word(s)")
    check("the bridge copied, and then stopped copying",
          m.long(sym["lfo4_copies_in"]) >= TRACKS
          and m.long(sym["lfo4_refreshes"]) > m.long(sym["lfo4_copies_in"]),
          f"{m.long(sym['lfo4_copies_in'])} copies in "
          f"{m.long(sym['lfo4_refreshes'])} refreshes")

    before_edit = first[(TRACK, DEST_SLOT)]
    copies = m.long(sym["lfo4_copies_in"])
    second = frames(SLOWER)
    print(f"\n  after editing SPD: {before_edit:#06x} -> {second.get((TRACK, DEST_SLOT), 0):#06x}")
    check("an edit to the table reaches the engine without anyone being told",
          second.get((TRACK, DEST_SLOT)) not in (None, before_edit),
          f"{before_edit:#06x} vs {second.get((TRACK, DEST_SLOT), 0):#06x}")
    check("and it cost one more copy, not a copy per frame",
          0 < m.long(sym["lfo4_copies_in"]) - copies <= TRACKS,
          f"{m.long(sym['lfo4_copies_in']) - copies} copies over {args.frames} frames")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
