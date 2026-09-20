"""The gate every build passes before it is allowed near the instrument.

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 /root/dn2-emu-venv/bin/python -u \
        scripts/emu_boot_check.py out/lfo4-bridge/section_3_MAIN_OS.bin

One question, asked from **reset**: does this image boot and draw its UI?

`lfo4-bridge` is why this exists. It passed every check it had, then drew the
instrument's `EXCEPTION` screen at boot -- because every one of those checks
restored `ui1200M`, a snapshot of a machine that has *already booted*. Nothing
ever ran the loader, the init, or the first call into the new code from reset.
Flashing is a ten-minute MIDI transfer and a recovery if it fails; this costs
nothing but wall-clock and runs unattended.

Three outcomes, and they are deliberately not the same:

- **fault** -- the firmware's own reporter at `0x4011ea6a` ran. That routine
  formats `V%02x M%x P%08x`, so the vector, the mode and the faulting PC come
  from the machine rather than from a photograph of the screen.
- **no UI** -- it never faulted and never composed a frame either. A hang looks
  like a pass to anything that only watches for a crash, which is why the
  milestone is checked and not assumed.
- **booted** -- frames were composed and nothing faulted.

The control is the stock image, and it is not optional: it fixes how many
instructions a real boot takes on this machine, so "no UI yet" can be told
apart from "not far enough yet". Its result is cached in `out/boot-check/`,
since stock does not change.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/digikit-up")

from emu import dspboot, symbols                              # noqa: E402
from unicorn import UC_HOOK_CODE                              # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A2                 # noqa: E402

ROOT = pathlib.Path("/mnt/d/01_Code/Z_Personal/dn2_firmware")
SYX = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"
CACHE = ROOT / "out/boot-check/control.json"
REPORTER = 0x4011EA6A


def stock_path():
    return os.path.join(os.environ["DT2_SECTIONS"], "section_3_MAIN_OS.bin")


def run(image_path, limit, frame_at, entries=()):
    """Boot from reset. -> (instructions, frames, the fault or None, reached).

    `entries` are the build's own routines. Whether they ran is as much a part
    of the result as whether it crashed: see `coverage` below.
    """
    holder, state = {}, {"frames": 0, "fault": None}
    reached = {name: 0 for name, _ in entries}

    def pre_start(m):
        st = holder["st"]

        def at_frame(uc, address, size, user):
            state["frames"] += 1

        def at_reporter(uc, address, size, user):
            a2 = uc.reg_read(UC_M68K_REG_A2)
            try:
                record = bytes(uc.mem_read(a2, 16))
            except Exception:                                  # noqa: BLE001
                record = b""
            state["fault"] = {"at": st["n"], "a2": a2, "record": record.hex()}
            uc.emu_stop()

        m.uc.hook_add(UC_HOOK_CODE, at_frame, begin=frame_at, end=frame_at)
        m.uc.hook_add(UC_HOOK_CODE, at_reporter, begin=REPORTER, end=REPORTER)
        for name, addr in entries:
            def hit(uc, address, size, user, name=name):
                reached[name] += 1
            m.uc.hook_add(UC_HOOK_CODE, hit, begin=addr, end=addr)

    m, st, stop = dspboot.run(str(SYX), open(image_path, "rb").read(), limit=limit,
                              machine_out=holder, pre_start=pre_start)
    return st["n"], state["frames"], state["fault"], reached


def control(limit, frame_at, refresh=False):
    """-> what a stock boot does here, cached: stock does not change."""
    if CACHE.exists() and not refresh:
        return json.loads(CACHE.read_text())
    started = time.time()
    ran, frames, fault, _ = run(stock_path(), limit, frame_at)
    row = {"ran": ran, "frames": frames, "fault": fault, "limit": limit,
           "seconds": round(time.time() - started, 1)}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(row, indent=1) + "\n")
    return row


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("image", help="a built section_3_MAIN_OS.bin")
    p.add_argument("--limit", type=int, default=450_000_000)
    p.add_argument("--refresh-control", action="store_true")
    args = p.parse_args()

    profile = symbols.resolve(open(stock_path(), "rb").read())
    frame_at = profile.panel_diff

    base = control(args.limit, frame_at, args.refresh_control)
    print(f"  control (stock 1.11): {base['frames']} frame(s) in {base['ran']:,} "
          f"instruction(s){'' if base['seconds'] is None else f', {base['seconds']}s'}"
          f"{'  [cached]' if not args.refresh_control else ''}")
    if base["fault"] or not base["frames"]:
        print("  the control did not boot cleanly here -- fix the harness, not the build.")
        return 2

    started = time.time()
    # The build writes `symbols.json` beside its section, so the routines to
    # watch come from the build itself rather than a list kept in step by hand.
    entries = []
    beside = os.path.join(os.path.dirname(args.image), "symbols.json")
    if os.path.exists(beside):
        sym = {k: int(v, 16) for k, v in json.load(open(beside)).items()}
        entries = sorted((k, v) for k, v in sym.items()
                         if k.startswith(("lfo4_", "dnfw_")) and not k.endswith("_displaced")
                         and not k.startswith("lfo4_size"))
    else:
        print("  no symbols.json beside the image: coverage cannot be reported, "
              "and a boot alone does not clear a build.")
    ran, frames, fault, reached = run(args.image, args.limit, frame_at, entries)
    print(f"  {os.path.basename(os.path.dirname(args.image))}: {frames} frame(s) in "
          f"{ran:,} instruction(s), {round(time.time() - started, 1)}s\n")

    if fault:
        rec = bytes.fromhex(fault["record"])
        print(f"  FAULT after {fault['at']:,} instructions -- the firmware drew EXCEPTION.")
        print(f"    record at {fault['a2']:#010x}: {fault['record']}")
        if len(rec) >= 8:
            print(f"    a2@(2) = {rec[2]:#04x}   a2@(4) = "
                  f"{int.from_bytes(rec[4:8], 'big'):#010x}")
        print("\n  DO NOT FLASH.")
        return 1
    if not frames:
        print(f"  NO UI: it never faulted and never composed a frame, while stock composed "
              f"{base['frames']} by here.\n  That is a hang, not a pass.\n\n  DO NOT FLASH.")
        return 1
    # Booting is necessary and nowhere near sufficient. `lfo4-bridge` booted
    # here for 400 M instructions without ever calling `lfo4_refresh` -- the
    # audio engine does not run -- and then faulted on the instrument the
    # moment it did. A gate that says passed about code it never executed is
    # the exact failure it exists to prevent, so coverage is part of the
    # verdict rather than a footnote under it.
    ran_names = sorted(n for n, c in reached.items() if c)
    idle = sorted(n for n, c in reached.items() if not c)
    print(f"  booted and drew its UI ({frames} frame(s), control {base['frames']}).")
    listed = ", ".join(f"{n} x{reached[n]}" for n in ran_names) or "none"
    print(f"  of this build's {len(reached)} routine(s), {len(ran_names)} ran: {listed}")
    if idle:
        print("")
        print("  NOT EXERCISED: " + ", ".join(idle))
        print("  Booting says these did not break the boot. It says NOTHING about")
        print("  whether they work, because they never ran. Anything the sequencer")
        print("  or the audio engine reaches needs its own harness -- the emulator")
        print("  runs neither. scripts/emu_boot_engine.py covers the engine path.")
        print("")
        print("  Boots, but NOT cleared for flashing on its own.")
        return 1
    print("")
    print("  Safe to flash as far as booting goes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
