"""Why does a direct call stop working once the panel has been driven?

    # in WSL, with digikit's venv (docs/emulator.md):
    DT2_SECTIONS=/root/dn2-sections-111 DT2_BUILD=out/lfo4-meterkeep \
        /root/dn2-emu-venv/bin/python -u scripts/emu_call_after_panel.py

`emu_lfo4_uikey.py` drove the panel and then called `lfo4_sound_of`, which
returned **8** -- a value that function cannot produce, since it returns either
zero or `base + 52 + 1163*track`. The call did not run. Before the guard was
added, that 8 became "the UI stores LFO4's row under a key the tick never asks
for": a false positive that read exactly like a discovery.

**This blocks most of what is left on LFO4**, because the remaining questions
all want the panel driven *and* a routine called directly, and the combination
fails silently with a plausible-looking integer.

Two candidate causes, and they need separating rather than arguing about:

  1. **the region** -- the build's `CODE` chunk at `0x46800000` does not survive
     the UI running, so the call executes rubbish;
  2. **the mechanism** -- `Machine.call` cannot re-enter from the state the
     panel leaves behind, whatever is in memory.

So run both arms, before and after, with a control on each:

  * `lfo4_sound_of`, whose correct answer is known independently by reading
    `*0x800052a0` and doing the arithmetic in Python;
  * a **four-byte stub in scratch memory** -- `moveq #42,%d0 ; rts` -- which
    depends on nothing but the call mechanism itself;
  * and a byte-for-byte compare of the function's own code, before against
    after, which answers (1) without reference to either call.

**The prediction, written before the run.**

  | bytes | stub | function | reading |
  |---|---|---|---|
  | changed | -- | -- | the region is clobbered: cause (1) |
  | same | 42 | wrong | the fault is specific to that code, not the mechanism |
  | same | wrong | wrong | the mechanism cannot re-enter: cause (2) |
  | same | 42 | right | it works here and `emu_lfo4_uikey.py` differs some other way |
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/mnt/d/01_Code/Z_Personal/dn2_firmware/scripts")
from emulib.image import code_chunks, differences, load_build      # noqa: E402
from emulib.machine import SNAP, Machine                           # noqa: E402
from emulib.panel import DOWN, MOD, Panel                          # noqa: E402

BUILD = os.path.join("/mnt/d/01_Code/Z_Personal/dn2_firmware",
                     os.environ.get("DT2_BUILD", "out/lfo4-meterkeep"))
LIVE_CONTAINER, SOUND_AT, SOUND_STRIDE = 0x800052A0, 52, 1163
STUB = bytes.fromhex("702a4e75")          # moveq #42,%d0 ; rts
STUB_ANSWER = 42
CODE_BYTES = 64


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--presses", type=int, default=4)
    args = p.parse_args()

    m = Machine(SNAP)
    image, sym = load_build(BUILD)
    stock = open(os.path.join(os.environ["DT2_SECTIONS"],
                              "section_3_MAIN_OS.bin"), "rb").read()
    m.apply(differences(stock, image))
    for load, _n, bss, init, blob in code_chunks(image):
        m.load_code_chunk((load, len(blob), bss, init, blob))
    m.flush()

    fn = sym["lfo4_sound_of"]
    stub = m.alloc(len(STUB))
    m.write(stub, STUB)
    m.flush()

    def truth():
        base = m.long(LIVE_CONTAINER)
        return base + SOUND_AT + SOUND_STRIDE * 0 if base else 0

    before = {
        "bytes": m.read(fn, CODE_BYTES),
        "stub": m.call(stub),
        "fn": m.call(fn, 0),
        "truth": truth(),
    }
    print(f"  before panel:  stub -> {before['stub']}  (want {STUB_ANSWER})")
    print(f"                 lfo4_sound_of(0) -> {before['fn']:#010x}  "
          f"(want {before['truth']:#010x})")

    panel = Panel(m)
    panel.settle()
    for _ in range(args.presses):
        panel.tap(MOD)
    panel.tap(DOWN)
    panel.settle()

    # Order matters and the last run got it wrong: the repeat ran third and
    # fourth after the panel, so it could not test "the first call fails".
    # Call the LOADED function first this time, and read the stub's own bytes,
    # which separates the two live explanations:
    #   (a) the first call after the panel does not run;
    #   (b) m.alloc scratch does not survive the panel, so only the stub fails.
    fn_first = m.call(fn, 0)
    want = truth()
    stub_bytes = m.read(stub, len(STUB))
    stub_after = m.call(stub)
    after = {"bytes": m.read(fn, CODE_BYTES), "stub": stub_after,
             "fn": fn_first, "truth": want}

    print(f"  after  panel:  lfo4_sound_of(0) FIRST -> {fn_first:#010x}  "
          f"(want {want:#010x})")
    print(f"                 stub bytes {stub_bytes.hex()}  "
          f"(want {STUB.hex()})")
    print(f"                 stub -> {stub_after}  (want {STUB_ANSWER})")

    if fn_first == want:
        print()
        print("  (a) is DEAD: the first call after the panel ran correctly.")
        if stub_bytes != STUB:
            print("  (b) HOLDS: the scratch allocation did not survive the panel,")
            print("      so the stub failed because its bytes were gone.")
        elif stub_after != STUB_ANSWER:
            print("  (b) does NOT hold either: the stub bytes are intact and it")
            print("      still returns stale. Neither explanation stands.")
        else:
            print("  Both arms work when the loaded function goes first --")
            print("      the fault depends on call ORDER, not on either cause.")
    same_bytes = before["bytes"] == after["bytes"]
    print(f"\n  the function's own {CODE_BYTES} code bytes: "
          f"{'unchanged' if same_bytes else 'CHANGED by the UI running'}")
    if not same_bytes:
        n = sum(1 for a, b in zip(before["bytes"], after["bytes"]) if a != b)
        print(f"    {n} of {CODE_BYTES} differ; first at "
              f"{next(i for i, (a, b) in enumerate(zip(before['bytes'], after['bytes'])) if a != b)}")

    ok_before = before["stub"] == STUB_ANSWER and before["fn"] == before["truth"]
    stub_ok = after["stub"] == STUB_ANSWER
    fn_ok = after["fn"] == after["truth"]

    print()
    if not ok_before:
        print("  **The before-panel control failed.** Neither arm is trustworthy and")
        print("  nothing below this line means anything. Fix the setup first.")
        return 2
    if not same_bytes:
        print("  **Cause (1): the UI running clobbers the build's code region.**")
        print("  A call after driving the panel executes whatever replaced it.")
        return 1
    if not stub_ok and not fn_ok:
        print("  **Cause (2): the call mechanism cannot re-enter after the panel.**")
        print("  Even a four-byte stub that touches nothing returns the wrong value,")
        print("  so this is Machine.call and the panel state, not our code.")
        return 1
    if stub_ok and not fn_ok:
        print("  **Neither cause as stated.** The mechanism works -- the stub is")
        print("  right -- but this function does not. The fault is specific to it")
        print("  or to what it reads, and that is the next thing to bisect.")
        return 1
    if fn_ok and not stub_ok:
        print("  **The loaded code region survives the panel; m.alloc scratch does")
        print("  not stay callable.** Its bytes are intact and the call mechanism")
        print("  works -- the loaded function proves both -- yet executing the stub")
        print("  leaves D0 holding the previous call's value, so emu_start did not")
        print("  run it. Cause unknown; the rule is what matters:")
        print("      after driving the panel, call only into the loaded code region.")
        return 1
    print("  **Both arms survive the panel here.** The failure in emu_lfo4_uikey.py")
    print("  is not reproduced by driving alone, so it differs some other way and")
    print("  that difference is the thing to find.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
