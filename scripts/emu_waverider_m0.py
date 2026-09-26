"""Waverider Milestone 0 under the emulator: boot from reset, then read it back.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_waverider_m0.py --build out/waverider-m0

Three checks, in the order a failure would be explained:

1. **load** -- after a boot from reset, the 16 KB at `wr_table` (from the
   build's `symbols.json`) are byte-for-byte what `dnfw.waverider` bakes. The
   firmware's own loader copied them; nothing here installs anything.
2. **address** -- the probe arrays beside the table hold `expect.PROBES`.
3. **read and report** -- the engine is run the way `emu_boot_engine.py` runs
   it, long enough for the LFO4 telemetry burst (one in 2,049 calls) to fire
   `bursts` times, with the MIDI transmit routine intercepted. What the firmware
   would have sent is decoded with the channel map and checked by
   `expect.verify` -- the same function that checks a capture from the
   instrument, so the emulator and the hardware are held to one standard.

**Why the transmit is intercepted, not run.** The emulator models no MIDI
hardware, so a queue that is never drained could fill and stall; and whether
the real call returns cleanly is already retired by `emu_tlm_send.py`. The hook
records the three bytes and returns as `rts` would, with `d0 = 0`.

**The control.** The engine gate's own criterion comes first: if our code
never ran, or the burst never fired, the script says so instead of reporting
an empty capture as a failure of the table.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from emu import dspboot                                       # noqa: E402
from unicorn import UC_HOOK_CODE, UcError                     # noqa: E402
from unicorn.m68k_const import (UC_M68K_REG_A7, UC_M68K_REG_D0,   # noqa: E402
                                UC_M68K_REG_PC)

from emu_boot_engine import REPORTER, SYX, After              # noqa: E402
from emu_lfo4_tick import (EVAL_A, MIRROR_AT, MIRROR_BYTES, RATE, REST,   # noqa: E402
                           SET_FRAC, STATE, STATE_LEN, TRACKS)
from dnfw.telemetry import gen                                # noqa: E402
from dnfw.waverider import bake, expect, reduce, testtable   # noqa: E402

MIDI_TX = 0x401233F2
CALLS_PER_BURST = 2049


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/waverider-m0")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--bursts", type=int, default=18,
                   help="telemetry bursts to capture (8 probes and 8 slices per cycle)")
    p.add_argument("--wav", default=None,
                   help="the WAV the build baked (a path in WSL), if not the original table")
    args = p.parse_args()

    build = pathlib.Path(args.build)
    if not build.is_absolute():
        build = HERE.parent / build
    sym = {k: int(v, 16) for k, v in json.loads((build / "symbols.json").read_text()).items()}
    # Recomputed from the source, never read from the build's output: compared
    # with the build's own bytes, any bake would pass.
    table = reduce.from_wav(pathlib.Path(args.wav).read_bytes()) if args.wav else testtable.table()
    want = bake.to_bytes(table)
    spec = gen.load()
    names = {s["cc"]: s["name"] for s in spec["signals"]}
    status = 0xB0 | ((spec["channel"] - 1) & 0x0F)

    holder, counts, fault, sent = {}, {}, {}, []

    def pre_start(m):
        st = holder["st"]

        def at_reporter(uc, address, size, user):
            if not fault:
                fault.update(at=st["n"])
            uc.emu_stop()

        m.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)
        for name in ("dnfw_boot", "lfo4_init", "lfo4_row_for_block", "wr_m0_report"):
            if name in sym:
                def hit(uc, address, size, user, name=name):
                    counts[name] = counts.get(name, 0) + 1
                m.uc.hook_add(UC_HOOK_CODE, hit, begin=sym[name], end=sym[name])

    print(f"  booting {build.name} from reset, {args.limit:,} instructions")
    m, st, stop = dspboot.run(SYX, (build / "section_3_MAIN_OS.bin").read_bytes(),
                              limit=args.limit, machine_out=holder, pre_start=pre_start)
    print(f"  ran {st['n']:,}, stop {stop!r}; reached {counts}")
    if fault:
        print(f"\n  FAULT during boot at {fault['at']:,}")
        return 1
    if not counts.get("dnfw_boot"):
        print("\n  the loader never ran: nothing below would mean anything")
        return 2

    fails = []
    after = After(m.uc)

    # 1. load
    got = bytes(m.uc.mem_read(sym["wr_table"], len(want)))
    if got == want:
        print(f"\n  1. load: {len(want):,} B at {sym['wr_table']:#010x} match the host bake")
    else:
        first = next(i for i in range(len(want)) if got[i] != want[i])
        fails.append(f"table differs from the bake first at byte {first} "
                     f"(frame {first // 1024}, point {(first % 1024) // 2})")
        print(f"\n  1. load: MISMATCH at byte {first}")

    # 2. address
    n = len(expect.PROBES)
    frames = struct.unpack(f">{n}H", bytes(m.uc.mem_read(sym["wr_probe_frame"], 2 * n)))
    indices = struct.unpack(f">{n}H", bytes(m.uc.mem_read(sym["wr_probe_index"], 2 * n)))
    if list(zip(frames, indices)) == expect.PROBES:
        print(f"  2. address: the {n} probe points in memory are expect.PROBES")
    else:
        fails.append(f"probe points in memory {list(zip(frames, indices))} != {expect.PROBES}")

    # 3. read and report, through the engine
    def at_tx(uc, address, size, user):
        sp = uc.reg_read(UC_M68K_REG_A7)
        ret, buf, count = struct.unpack(">III", bytes(uc.mem_read(sp, 12)))
        sent.append(bytes(uc.mem_read(buf, min(count, 16))))
        uc.reg_write(UC_M68K_REG_A7, sp + 4)
        uc.reg_write(UC_M68K_REG_D0, 0)
        uc.reg_write(UC_M68K_REG_PC, ret)

    m.uc.hook_add(UC_HOOK_CODE, at_tx, begin=MIDI_TX, end=MIDI_TX)
    span = MIRROR_AT + TRACKS * MIRROR_BYTES + 32
    buf = after.alloc(span)
    after.write(buf, struct.pack(">H", REST) * (span // 2))
    for base in STATE:
        after.write(base, bytes(STATE_LEN))
    frac = after.alloc(len(SET_FRAC))
    after.write(frac, SET_FRAC)
    after.call(frac)
    rate = after.long(RATE)
    out1, out2 = after.alloc(256), after.alloc(256)
    frames_needed = (args.bursts * CALLS_PER_BURST) // TRACKS + 2 * TRACKS
    print(f"  3. running evaluator A for up to {frames_needed} frames "
          f"({args.bursts} bursts at one per {CALLS_PER_BURST} calls)")
    ran = 0
    try:
        for ran in range(1, frames_needed + 1):
            after.call(EVAL_A, buf, rate, 0xFFFF, 0xFFFF, out1, out2, 0)
            if counts.get("wr_m0_report", 0) >= args.bursts or fault:
                break
    except UcError as exc:
        pc = after.uc.reg_read(UC_M68K_REG_PC)
        print(f"\n  ** the evaluator faulted: {exc} at pc {pc:#010x} after {ran} frame(s) **")
        return 1
    print(f"     {ran} frame(s): lfo4_row_for_block {counts.get('lfo4_row_for_block', 0):,}, "
          f"wr_m0_report {counts.get('wr_m0_report', 0)}, {len(sent)} message(s) sent")
    if fault:
        print("\n  ** the firmware drew EXCEPTION while the engine ran **")
        return 1
    if not counts.get("wr_m0_report"):
        print("\n  the burst never fired, so nothing was read: this proves nothing.")
        return 2

    pairs, foreign = [], 0
    for msg in sent:
        if len(msg) == 3 and msg[0] == status and msg[1] in names:
            pairs.append((names[msg[1]], msg[2]))
        else:
            foreign += 1
    ok, lines = expect.verify(pairs, table)
    for line in lines:
        print(f"     {line}")
    if foreign:
        print(f"     note: {foreign} message(s) were not telemetry CCs on channel "
              f"{spec['channel']} -- not ours to judge, listed so they are not hidden")
    if not ok:
        fails.append("the reported values do not match the expectation")
    sums = [(v, i) for i, (n_, v) in enumerate(pairs) if n_ == "wr_passes"]
    print(f"     wr_passes after the run: {sums[-1][0] if sums else None}; "
          f"memory: wr_passes {after.long(sym['wr_passes'])}, "
          f"wr_sum {after.long(sym['wr_sum']) >> 16:#06x}, "
          f"expected {bake.checksum(table):#06x}")

    if fails:
        print("")
        for f in fails:
            print("  FAIL  " + f)
        return 1
    print("\n  reduce, bake, load, address, read: the baked table came back exactly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
