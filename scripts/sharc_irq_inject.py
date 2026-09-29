"""scripts/sharc_irq_inject.py OURS_S7.bin INJECT_SW HANDLER_SW [...] -- enter a DSP interrupt handler at a chosen point of our code.

The runner executes no interrupts; on the chip, interrupts are enabled and nested at the
WaveTone render call, and the audio and link sources fire constantly. For each HANDLER_SW,
this runs OURS_S7 as the stage trace does and, the first time the PC reaches INJECT_SW,
does what the hardware does on entry (the interrupted PC onto the PC stack, ASTATX /
ASTATY / MODE1 onto the status stack) and continues at the handler. It reports whether
execution came back to INJECT_SW, and then whether our code finished the block as it
does without the injection (the stage markers, the call counter, the scratch output).

A runner halt inside a handler (for instance a peripheral register it does not model)
is reported as inconclusive for that handler, not as a result."""
import os, sys, pathlib, tempfile
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
import sharc_waverider_m5 as G
import sharc_waverider_render as m1
import sharc_waverider_m4 as m4
import sharc_dn2_fixups as fx
import build_waverider_disc_wtplace as W

DK = pathlib.Path(os.environ.get("DIGIKIT_SHARC", "D:/01_Code/Z_Personal/digikit-wt-sharcemu"))
IMG = pathlib.Path("../../../00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
dk = m1.Digikit(DK); fx.bind(str(DK / "tools")); m4.IMAGE = IMG
from sharc_core.encoding import UREG_CODES  # noqa: E402
stock = m1.dn2_section7(IMG)
sound, machines = m4.init_sound(IMG)
ours = pathlib.Path(sys.argv[1]).read_bytes()
INJ = int(sys.argv[2], 0)
HANDLERS = [int(a, 0) for a in sys.argv[3:]]
snap, mach = G.snapshot_path(dk, stock, pathlib.Path(tempfile.mkdtemp()))
m2 = G.m2


def marks(r):
    return [m2.word(r["state"].state, a) for a in W.MARK_AT + W.COUNT_AT]


def run(handler):
    ev = {"injected": False, "back": False}

    def at_inj(rr):
        st = rr.state
        if handler is None:
            return
        if not ev["injected"]:
            ev["injected"] = True
            st.call_stack.append(INJ)
            st.status_stack.append((st.uregs.get(UREG_CODES["ASTATX"]), st.uregs.get(UREG_CODES["ASTATY"]),
                                    st.uregs.get(UREG_CODES["MODE1"])))
            st.pc_sw = handler
        else:
            ev["back"] = True

    fr = lambda b: G.base_frame(sound, machines, trigger=(b == 1), t0=4, others={1: 1},
                                trigger_others=True).to_bytes()
    r = G.run_blocks(G.init_on(snap, mach, G.Image(dk, ours)), fr, 1, extra_hooks={INJ: at_inj})
    return r, ev


base, _ = run(None)
assert base["ok"], base.get("halt")
want = marks(base)
print(f"no injection: markers/counter {[hex(v) for v in want]}")
for h in HANDLERS:
    r, ev = run(h)
    if not r["ok"]:
        print(f"handler {h:#x}: INCONCLUSIVE, runner halt: {r.get('halt')} (entered: {ev['injected']}, back: {ev['back']})")
        continue
    got = marks(r)
    same = got == want
    print(f"handler {h:#x}: back at {INJ:#x}: {ev['back']}; block completed; our markers/counter "
          f"{'as without the injection' if same else 'DIFFER: ' + str([hex(v) for v in got])}")
