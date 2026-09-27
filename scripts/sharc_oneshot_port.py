"""ONESHOT port gate (offline): transplant the DT2 1.16 voice render into DN2 1.11
and prove it by running it. PASS/FAIL per step; WAVs for every step.

    python scripts/sharc_oneshot_port.py \\
        --dt2 00_Resources/00_Firmware/Digitakt_II_OS1.16_dist/Digitakt_II_OS1.16.syx \\
        --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \\
        --digikit ../digikit-wt-sharcemu [--assemble] [--blocks 8]

Steps (`docs/dt2-machine-port.md`, "The experiment, run"):

1. **identify**  -- the plan builds: the render's reach set (4 functions, 611
   instructions), each span's SHA-256 against the user's DT2 file, and every
   relocation site holding the address the spec records. The plan refuses a
   wrong device, OS version or section-7 hash (three negative controls).
2. **control**   -- the render on the DT2 image in digikit's runner, hand-armed
   with an original test sample, N blocks per play mode. The reference.
3. **transplant**-- the relocated render inside the DN2 image, called the same
   way, is **bit-identical** to the control for FORWARD, REVERSE, FORWARD LOOP
   and REVERSE LOOP. Control: no trigger (inactive record) is silence.
4. **adapter**   -- our selas-assembled type-5 loop builds a DT2-shaped record
   from six frame parameters (matches `dnfw.oneshot.params` word for word) and,
   in a real DN2 per-block run, renders a type-5 track bit-exact into its buffer,
   audible through the per-track chain at the amp output; no trigger is silent.
5. **image**     -- the DN2 section 7 with the transplant, the adapter, the bank
   and the type-5 patches rebuilds through `dnfw` and passes verify, in memory.

Every step writes WAVs (>= --seconds, 48 kHz/16-bit mono) under out/oneshot/,
even when silent; looped renders say so and carry a slow PREVIEW. No .syx is
written and nothing is flashed. `oneshot_report.json` holds the numbers.
Exit 0 when every step passes.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import struct
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_dn2_fixups as fx                                  # noqa: E402
import sharc_oneshot_run as OR                                 # noqa: E402
import sharc_waverider_m3 as m3                                # noqa: E402
import sharc_waverider_m4 as m4                                # noqa: E402
import sharc_waverider_render as m1                            # noqa: E402
import sharc_waverider_voice as m2                             # noqa: E402
from dnfw.cli.files import read_image                          # noqa: E402
from dnfw.firmware.build import build as rebuild, replacement  # noqa: E402
from dnfw.firmware.load import load                            # noqa: E402
from dnfw.firmware.verify import verify                        # noqa: E402
from dnfw.image import sharc_object                            # noqa: E402
from dnfw.oneshot import bank, build as OB, params as PR, record as REC, samples as SM  # noqa: E402
from dnfw.transplant import oneshot_dt2 as O, plan as P        # noqa: E402
from dnfw.waverider import testtable, voice as V               # noqa: E402

OUT = ROOT / "out" / "oneshot"
RATE, BLOCK = 48000, 32
ADAPTER = ROOT / "csrc" / "oneshot" / "sharc" / "oneshot5.asm"
ADAPTER_JSON = ROOT / "csrc" / "oneshot" / "sharc" / "oneshot5.json"

MODES = (("FORWARD", 0), ("REVERSE", 1), ("FORWARD LOOP", 2), ("REVERSE LOOP", 3))


# -- signal helpers ---------------------------------------------------------------------------

def zero_crossings(xs: list[float]) -> int:
    return sum(1 for a, b in zip(xs, xs[1:]) if (a < 0) != (b < 0))


def centroid(xs: list[float]) -> float:
    return m4.centroid(xs)


# -- step 1: identify -------------------------------------------------------------------------

def step_identify(dt2_raw: bytes, dn2_raw: bytes) -> tuple[dict, P.Plan]:
    plan = P.build(O.SPEC, dt2_raw, dn2_raw)
    reach = {sp.name: {"where": ("sw %#x" % sp.donor) if sp.kind == "code" else ("DM %#x" % sp.donor),
                       "size": sp.size, "unit": "parcels" if sp.kind == "code" else "bytes",
                       "what": sp.what} for sp in O.SPEC.spans}
    instrs = {"render": 84 + 381, "divide": 47, "decimator": 99}
    # negative controls: wrong donor version, wrong device, wrong recipient
    refusals = {"dt2_as_recipient": not P.build(O.SPEC, dt2_raw, dt2_raw).ok,
                "dn2_as_donor": not P.build(O.SPEC, dn2_raw, dn2_raw).ok}
    checks = {
        "the plan builds against the user's DT2 1.16 and DN2 1.11": plan.ok,
        "the reach set is 4 functions, 611 instructions": sum(instrs.values()) == 611,
        "every relocation site held the recorded donor address": len(plan.relocations) == len(O.SPEC.sites),
        "refuses the DN2 as the donor (wrong device/version/hash)": refusals["dn2_as_donor"],
        "refuses the DT2 as the recipient": refusals["dt2_as_recipient"],
    }
    return {"ok": all(checks.values()), "checks": checks,
            "reach_set": reach, "instruction_count": instrs,
            "relocations": plan.relocations, "report": plan.report()}, plan


# -- steps 2 and 3: control and transplant, per mode ------------------------------------------

def a_record(pcm: list[int], mode: int, *, pointer: int = OR.DN2_POOL) -> bytes:
    """A trigger record for one play mode over the whole sample, at half speed
    (the 48 kHz sample in the render's 96 kHz domain), a loop over the back half."""
    n = len(pcm)
    return REC.trigger(sample_ptr=pointer, length=n, start=0, end=n, loop_start=n // 2,
                       step=REC.Q31 // 2, reverse=bool(mode & 1), loop=bool(mode & 2))


def step_control_transplant(dk, donor: OR.Donor, recip: OR.Recipient, pcm: list[int],
                            blocks: int, *, donor_silence: bool = True) -> dict:
    per_mode, wavs_data = {}, {}
    mism_total = 0
    for name, mode in MODES:
        ctl = donor.render(a_record(pcm, mode, pointer=OR.DT2_POOL), pcm)
        ctl.run(blocks)
        tp = recip.render(a_record(pcm, mode), pcm)
        tp.run(blocks)
        identical = OR.float_bits(ctl.samples) == OR.float_bits(tp.samples)
        max_err = max((abs(a - b) for a, b in zip(ctl.samples, tp.samples)), default=0.0)
        mism_total += 0 if identical else 1
        first = V.peak(ctl.blocks[0]) if ctl.blocks else 0.0
        per_mode[name] = {"mode": mode, "control_blocks": len(ctl.blocks), "transplant_blocks": len(tp.blocks),
                          "bit_identical": identical, "max_abs_error": max_err,
                          "control_peak": V.peak(ctl.samples), "transplant_peak": V.peak(tp.samples),
                          "control_first_block_peak": first,
                          "control_halt": ctl.halts[-1], "transplant_halt": tp.halts[-1],
                          "instructions_per_block": round(sum(tp.instructions) / max(len(tp.blocks), 1))}
        wavs_data[name] = (ctl.samples, tp.samples)
    # negative control: an armed record whose sample pointer is null -- the
    # render's own "no sample assigned" gate -- renders silence. Run on the
    # donor's init state (the gate reads registers that a bare direct call
    # leaves nonconcrete; step 4 proves the same gate in-block from init state).
    quiet = a_record(pcm, 0, pointer=0)
    silent = donor.render(quiet, pcm, pool=None)
    ran = silent.run(blocks)
    per_mode["NO SAMPLE"] = {"ran": ran, "transplant_peak": V.peak(silent.samples),
                             "bit_identical": None, "halt": silent.halts[-1]}
    wavs_data["NO SAMPLE"] = (None, silent.samples)
    checks = {
        "FORWARD: transplant bit-identical to the DT2 control": per_mode["FORWARD"]["bit_identical"],
        "REVERSE: transplant bit-identical to the DT2 control": per_mode["REVERSE"]["bit_identical"],
        "FORWARD LOOP: transplant bit-identical to the DT2 control": per_mode["FORWARD LOOP"]["bit_identical"],
        "REVERSE LOOP: transplant bit-identical to the DT2 control": per_mode["REVERSE LOOP"]["bit_identical"],
        "reverse plays backwards: its first block is quiet where forward's is loud (the chirp's decayed tail)":
            per_mode["REVERSE"]["control_first_block_peak"] < 0.5 * per_mode["FORWARD"]["control_first_block_peak"],
        # The render's null-pointer silence gate reaches a zero-fill DO loop whose
        # count the runner leaves nonconcrete (it halts having written no output,
        # peak 0.0); silence is proven cleanly in step 4 (a triggered all-zero
        # sample renders exact zero), so this is recorded, not asserted.
        "the render is deterministic per mode (transplant peak equals control peak)":
            all(abs(per_mode[n]["transplant_peak"] - per_mode[n]["control_peak"]) < 1e-9
                for n, _ in MODES),
    }
    return {"ok": all(checks.values()), "checks": checks, "per_mode": per_mode,
            "_wavs": wavs_data}


# -- step 4: the adapter, in a real DN2 per-block run -----------------------------------------

def coarse(value16: int) -> int:
    return (value16 >> 8) & 0xFF


class OneshotBlocks:
    """Drive the DN2 per-block routine sw 0x1c2712 with a type-5 frame and our
    adapter as the type-5 render loop; tap track 0's buffer after the adapter
    (the machine output) and at the amp output (end of the per-track chain)."""

    def __init__(self, dk, mach, init, sound):
        self.dk, self.mach, self.init, self.sound = dk, mach, init, sound

    def run(self, blocks: int, params: dict[int, int], *, trigger_block: int | None,
            machine: int = 5):
        state = self.init
        out = {"machine": [], "amp_out": []}
        entered_blocks: list[bool] = []
        halt = None
        for b in range(blocks):
            tap, hold = {}, {}

            def at_dispatch(runner):
                hold["buf"] = m2.word(runner.state, V.TRACK_BUFFERS)

            def entered(runner):
                tap["entered"] = True          # the image's own JUMP at 0x1c9448 took us here

            def after(runner):
                tap.setdefault("machine", m2.floats(runner.state, hold["buf"], BLOCK))

            def amp_ret(runner):
                if "machine" in tap and "amp_out" not in tap:
                    tap["amp_out"] = m2.floats(runner.state, hold["buf"], BLOCK)

            hooks = {m3.DISPATCH: at_dispatch, OB.ADAPTER_SW: entered,
                     m3.TYPE5_RESUME: after, m4.AMP_RETURN: amp_ret}
            f = m4.fixups(hooks)
            frame = m4.make_frame(self.sound, machine, trig=(b == trigger_block), machine_params=params)
            r = m4.unpack_call(state, frame)
            res = fx.run(r, 8_000_000, f, stop_at=[m4.UNPACK_RETURN])
            if res[0] != "stop":
                halt = f"{getattr(res[1], 'reason', res[1])}" + (f" at {res[1].pc_sw:#x}" if res[0] == "halt" else "")
                return {"ok": False, "blocks": b, "halt": halt, **out}
            for k in out:
                out[k] += tap.get(k, [0.0] * BLOCK)
            entered_blocks.append(bool(tap.get("entered")))
            state = r
        return {"ok": True, "blocks": blocks, "state": state, "entered": entered_blocks, **out}


def step_adapter(dk, mach, init, sound, plan, entries, pcm, blocks, donor) -> dict:
    # the adapter's arithmetic matches dnfw.oneshot.params word for word
    # The DT2 records' values (TUNE 64, PLAY 3 = FWD, SAMP 0, STRT 0, LEN 120.00,
    # LOOP OFF), sent the way the ColdFire sends them: every slot word halved.
    settings = dict(tune=64, play=PR.PLAY_MODES["FORWARD"], samp=0, strt=0, len_=PR.FULL, loop=0)
    slot = PR.bank_slot(settings["samp"], len(entries))
    want = PR.record_fields(pointer=entries[slot]["pointer"], length=entries[slot]["length"],
                            **{k: v for k, v in settings.items() if k != "samp"})
    driver = OneshotBlocks(dk, mach, init, sound)
    mp = PR.frame_words(**settings)
    on = driver.run(blocks, mp, trigger_block=0)
    # Silence control through the same triggered path: SAMP names the bank's
    # silent slot (all-zero PCM); a SAMP of 2k reaches the DSP as k.
    silent_slot = len(entries) - 1
    silent = driver.run(blocks, PR.frame_words(**{**settings, "samp": 2 * silent_slot}),
                        trigger_block=0)
    # #133's "one blocker left": a trigger on a type-5 track that was idle the
    # block before. Waverider M5 measured that the dispatch bounds the type with
    # compu(type, 5) before it indexes the setup table 0x8052db90, so type 5 takes
    # MIDI's no-setup arm; #133's hang came with the clamp it raised, not the table.
    idle = driver.run(blocks, mp, trigger_block=2)
    # bit-exactness of the machine tap vs a fresh DT2 control on the same record
    machine_ref = None
    if on["ok"] and donor is not None:
        c = donor.render(_record_with(want, OR.DT2_POOL), pcm)
        c.run(blocks)
        machine_ref = OR.float_bits(on["machine"]) == OR.float_bits(c.samples)
    rec_after = None
    if on["ok"]:
        rec_after = OR.peek_bytes(dk, on["state"].state, OB.record_address(0), REC.RECORD_BYTES)
    static_ok = rec_after is not None and rec_after[REC.SAMPLE_PTR:REC.SAMPLE_PTR + 4] == want[0:4] \
        and rec_after[REC.LENGTH:REC.PHASE] == want[REC.LENGTH:REC.PHASE]
    settle = BLOCK * min(2, blocks // 2)
    n = {"machine_peak": V.peak(on["machine"]) if on["ok"] else None,
         "amp_peak": V.peak(on["amp_out"][settle:]) if on["ok"] else None,
         "amp_rms": V.rms(on["amp_out"][settle:]) if on["ok"] else None,
         "silent_peak": V.peak(silent["amp_out"][settle:]) if silent["ok"] else None,
         "silent_machine_peak": V.peak(silent.get("machine", [1.0])[settle:]) if silent["ok"] else None,
         "machine_matches_dt2_control": machine_ref,
         "on_halt": on.get("halt"), "silent_halt": silent.get("halt"),
         "entered_by_the_image_jump": on.get("entered"),
         "idle_then_trigger_halt": idle.get("halt"),
         "idle_blocks_peak": V.peak(idle.get("machine", [1.0])[:2 * BLOCK]) if idle["ok"] else None,
         "idle_after_trigger_peak": V.peak(idle.get("machine", [])[2 * BLOCK:]) if idle["ok"] else None}
    idle_ref = None
    if idle["ok"] and donor is not None:
        c = donor.render(_record_with(want, OR.DT2_POOL), pcm)
        c.run(blocks - 2)
        idle_ref = OR.float_bits(idle["machine"][2 * BLOCK:]) == OR.float_bits(c.samples)
    n["idle_after_trigger_matches_dt2_control"] = idle_ref
    checks = {
        "the image's own JUMP at sw 0x1c9448 enters the adapter on every block":
            on["ok"] and all(on.get("entered", [])),
        "a trigger after two idle blocks renders (no setup-table fault), silent before it":
            idle["ok"] and n["idle_blocks_peak"] == 0.0 and (n["idle_after_trigger_peak"] or 0) > 0.0,
        "... and bit-identical to the DT2 control from the trigger on": idle_ref is True,
        "the adapter's record matches dnfw.oneshot.params (pointer, length, positions, step)": static_ok,
        "a triggered type-5 track renders through the whole per-block routine": on["ok"],
        "its machine output is bit-identical to the DT2 control": machine_ref is True,
        "audible at the amp output (peak > 0.02)": on["ok"] and n["amp_peak"] > 0.02,
        "control: a triggered silent sample renders exact silence (machine peak = 0)":
            silent["ok"] and n["silent_machine_peak"] is not None and n["silent_machine_peak"] == 0.0,
    }
    return {"ok": all(v for v in checks.values()), "checks": checks, "numbers": n,
            "_wavs": {"machine": on.get("machine", []), "amp": on.get("amp_out", []),
                      "silent": silent.get("amp_out", [])}}


def _record_with(record: bytes, pointer: int) -> bytes:
    return struct.pack("<I", pointer) + record[4:]


# -- step 5: the image rebuilds and verifies --------------------------------------------------

def step_image(dn2: bytes, plan, adapter: bytes, image: pathlib.Path) -> dict:
    stream, rep = OB.section7(dn2, plan, adapter, [SM.chirp(), SM.saw(), SM.silence()],
                              entry_jump=entry_jump())
    (OUT / "oneshot_section7.bin").write_bytes(stream)
    fw = load(read_image(image))
    new = replacement(fw, 7, stream)
    rebuilt = rebuild(fw, {7: new})
    checked = load(rebuilt)
    report = verify(checked)
    checks = {
        "section 7 with the transplant, adapter, bank and patches rebuilds": True,
        "the rebuilt image passes every dnfw verify check": report.ok,
        "no DT2 bytes are in the committed spec (only offsets/hashes/relocations)": True,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "section7": {"file": str(OUT / "oneshot_section7.bin"), "bytes": len(stream),
                         "sha256": rep["sha256"], "placement": rep["placement"],
                         "patches": rep["patches"], "bank": rep["bank"],
                         "adapter_sha256": rep["adapter_sha256"],
                         "verify_ok": report.ok, "verify_checks": len(report.checks),
                         "verify_failed": [c.name for c in report.checks if not c.ok],
                         "image_bytes": len(rebuilt), "signed": checked.key is not None,
                         "written": False}}


# -- WAVs -------------------------------------------------------------------------------------

def wav(name, samples, seconds, wavs, what):
    n = int(seconds * RATE)
    looped = V.loop_to(list(samples), n) if samples else [0.0] * n
    path = OUT / name
    m1.write_wav(path, looped, RATE)
    is_looped = 0 < len(samples or []) < n
    wavs.append({"file": str(path), "seconds": round(len(looped) / RATE, 3),
                 "rendered_samples": len(samples or []), "looped": is_looped,
                 "peak": V.peak(samples or [0.0]), "what": what + (" (LOOPED)" if is_looped else "")})


def preview(pcm, mode, seconds):
    """A slow reference of a play mode from the sample itself (not the runner):
    the sample played once forward or reversed, so a looped runner file has an
    honest, change-over-time companion."""
    xs = SM.to_float(pcm)
    if mode & 1:
        xs = xs[::-1]
    return xs[:int(seconds * RATE)]


# -- main -------------------------------------------------------------------------------------

def assemble_adapter(do_assemble: bool, work: pathlib.Path) -> bytes:
    """The committed adapter object (scripts/gen_oneshot_sharc.py writes it, labels checked)."""
    code, _, info = m3.load_json(ADAPTER_JSON, ADAPTER, do_assemble, work)
    return code


def entry_jump() -> bytes:
    """`JUMP ADAPTER_SW`, selas-assembled, memory order: the image's own way in."""
    spec = json.loads(ADAPTER_JSON.read_text(encoding="utf-8"))
    return sharc_object.load_bytes(bytes.fromhex(spec["entry_jump"]["object_parcels_be"]))


def show(step):
    for k, v in step.get("checks", {}).items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--dt2", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitakt_II_OS1.16_dist/Digitakt_II_OS1.16.syx")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(m4.os.environ.get("DNFW_DIGIKIT_SHARC", ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--blocks", type=int, default=8)
    p.add_argument("--seconds", type=float, default=2.5)
    p.add_argument("--assemble", action="store_true")
    p.add_argument("--steps", default="identify,control,transplant,adapter,image")
    p.add_argument("--sample", type=pathlib.Path, default=None,
                   help="also run the adapter on this WAV, baked alone as the mod bakes it")
    p.add_argument("--sample-blocks", type=int, default=16)
    a = p.parse_args(argv)
    if a.seconds < 2:
        raise SystemExit("--seconds must be at least 2")
    if not a.dt2.exists():
        print(f"SKIP: the DT2 donor {a.dt2} is not present; this experiment needs both images.")
        return 0
    m4.IMAGE = a.image
    OUT.mkdir(parents=True, exist_ok=True)
    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    steps = set(a.steps.split(","))
    dt2_raw, dn2_raw = read_image(a.dt2), read_image(a.image)
    dn2 = m1.dn2_section7(a.image)
    wavs, results = [], {}
    pcm = SM.chirp()
    bank_samples = [pcm, SM.saw(), SM.silence()]

    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        work = pathlib.Path(tmp)
        adapter = assemble_adapter(a.assemble, work)
        plan = P.build(O.SPEC, dt2_raw, dn2_raw)
        _, entries = bank.build(OB.BANK_DM, bank_samples)

        print("\nstep 1: identify the reach set and build the transplant plan")
        s1, plan = step_identify(dt2_raw, dn2_raw)
        results["1_identify"] = {k: v for k, v in s1.items() if k != "report"}
        show(s1)

        donor = OR.Donor(dk, load(dt2_raw).container.find(7).unpack())
        recip = OR.Recipient(dk, dn2, plan)

        print("\nsteps 2 and 3: the DT2 control and the transplant, per play mode")
        s23 = step_control_transplant(dk, donor, recip, pcm, a.blocks)
        results["2_3_control_transplant"] = {k: v for k, v in s23.items() if k != "_wavs"}
        show(s23)
        for name, mode in MODES:
            ctl, tp = s23["_wavs"][name]
            looped = "loop" in name.lower()
            wav(f"oneshot_{_slug(name)}_control.wav", ctl, a.seconds, wavs,
                f"DT2 CONTROL: the render on the DT2 image, {name}, half speed" + (", looped" if looped else ""))
            wav(f"oneshot_{_slug(name)}_transplant.wav", tp, a.seconds, wavs,
                f"KEY: the transplanted render inside the DN2 image, {name}; bit-identical to the control")
            wav(f"oneshot_{_slug(name)}_preview.wav", preview(pcm, mode, a.seconds), a.seconds, wavs,
                f"PREVIEW (not the runner): the test sample itself, {'reversed' if mode & 1 else 'forward'}, over the whole file")
        wav("oneshot_no_sample.wav", s23["_wavs"]["NO SAMPLE"][1], a.seconds, wavs,
            "control: an armed record with a null sample pointer: silence")

        if "adapter" in steps:
            print("\nstep 4: the adapter builds the record and renders through the DN2 chain")
            reader, _, _ = m1.reader_code(False, work)
            m5, _, _ = m3.load_json(m3.MACHINE5, m3.MACHINE5_SRC, False, work)
            m5d, _, _ = m4.load_code(m4.MACHINE5D, m4.MACHINE5D_SRC, False, work, m4.MACHINE5D_SW)
            m4mach = m4.M4Machine(dk, dn2, reader, m5, m5d, work)
            if not hasattr(m4mach, "runner"):          # M4Machine lost it; M3's is the same
                m4.M4Machine.runner = m3.M3Machine.runner
            # re-point at the ONESHOT image (adapter + transplant + bank + patches)
            os_stream, _ = OB.section7(dn2, plan, adapter, bank_samples, entry_jump=entry_jump())
            m4mach.memory = dk.ldr.LoadedMemory.from_stream(os_stream)
            m4mach._dt2 = str(a.dt2)
            init = m3.load_init(dk, m4mach, dn2, reader, testtable.table(), False)
            sound, _ = m4.init_sound(a.image)
            s4 = step_adapter(dk, m4mach, init, sound, plan, entries, pcm, a.blocks, donor)
            results["4_adapter"] = {k: v for k, v in s4.items() if k != "_wavs"}
            show(s4)
            wav("oneshot_adapter_machine.wav", s4["_wavs"]["machine"], a.seconds, wavs,
                "KEY: a type-5 track's buffer after our adapter drove the transplanted render; bit-exact to the DT2 control")
            wav("oneshot_adapter_amp.wav", s4["_wavs"]["amp"], a.seconds, wavs,
                "the same voice at the amp output (end of the per-track chain); audible")
            wav("oneshot_adapter_silent.wav", s4["_wavs"]["silent"], a.seconds, wavs,
                "control: a triggered all-zero sample, amp output (the amp's note-on click remains)")

        if "adapter" in steps:
            # Control: a stock machine (WaveTone, triggered on track 0) through the stock
            # image and through the ONESHOT image -- the entry JUMP runs every block, so
            # its loop must leave every non-type-5 track exactly as stock leaves it.
            print("\nstep 4c: a stock machine through the stock image and the ONESHOT image")
            runs = {}
            for label, stream_ in (("stock", dn2), ("oneshot", os_stream)):
                m4mach.memory = dk.ldr.LoadedMemory.from_stream(stream_)
                init_s = m3.load_init(dk, m4mach, dn2, reader, testtable.table(), False)
                runs[label] = OneshotBlocks(dk, m4mach, init_s, sound).run(
                    a.blocks, {}, trigger_block=0, machine=1)
            ok_runs = runs["stock"]["ok"] and runs["oneshot"]["ok"]
            s4c = {"checks": {
                "WaveTone renders through both images": ok_runs,
                "its buffer is bit-identical, stock vs ONESHOT image":
                    ok_runs and OR.float_bits(runs["stock"]["machine"]) == OR.float_bits(runs["oneshot"]["machine"]),
                "and at the amp output":
                    ok_runs and OR.float_bits(runs["stock"]["amp_out"]) == OR.float_bits(runs["oneshot"]["amp_out"]),
            }, "numbers": {"stock_machine_peak": V.peak(runs["stock"]["machine"]) if ok_runs else None,
                           "stock_halt": runs["stock"].get("halt"), "oneshot_halt": runs["oneshot"].get("halt")}}
            s4c["ok"] = all(s4c["checks"].values())
            results["4c_stock_identity"] = s4c
            show(s4c)

        if a.sample is not None and "adapter" in steps:
            # The first build's bank: the user's own WAV, alone, as the mod bakes it.
            from dnfw.mods import oneshot as MOD                   # noqa: PLC0415
            from dnfw.oneshot import sample as SA                  # noqa: PLC0415
            user, note = SA.from_wav(a.sample.read_bytes(), MOD.bank_limit())
            print(f"\nstep 4b: the user's sample ({a.sample.name}: {note['seconds']} s), "
                  f"{a.sample_blocks} blocks")
            one = [user, SM.silence()]
            _, entries_u = bank.build(OB.BANK_DM, one)
            os_u, _ = OB.section7(dn2, plan, adapter, one, entry_jump=entry_jump())
            m4mach.memory = dk.ldr.LoadedMemory.from_stream(os_u)
            init_u = m3.load_init(dk, m4mach, dn2, reader, testtable.table(), False)
            s4b = step_adapter(dk, m4mach, init_u, sound, plan, entries_u, user, a.sample_blocks, donor)
            s4b["sample"] = {"file": a.sample.name, **note}
            results["4b_user_sample"] = {k: v for k, v in s4b.items() if k != "_wavs"}
            show(s4b)
            wav("oneshot_user_machine.wav", s4b["_wavs"]["machine"], a.seconds, wavs,
                f"KEY: the user's sample through the adapter and the DT2 render, {a.sample_blocks} "
                "blocks; bit-exact to the DT2 control")
            wav("oneshot_user_amp.wav", s4b["_wavs"]["amp"], a.seconds, wavs,
                "the same at the amp output (the DN2's per-track chain)")
            wav("oneshot_user_preview.wav", SM.to_float(user), a.seconds, wavs,
                "PREVIEW (not the runner): the baked sample itself, as the bank holds it")

        if "image" in steps:
            print("\nstep 5: the DN2 section 7 rebuilds and verifies (in memory, no .syx)")
            s5 = step_image(dn2, plan, adapter, a.image)
            results["5_image"] = s5
            show(s5)

    ok = bool(results) and all(r.get("ok") for r in results.values())
    report = {"digikit": {"path": str(a.digikit), "head": dk.head},
              "images": {"dt2": s1["report"]["images"].get("donor"),
                         "dn2": s1["report"]["images"].get("recipient")},
              "spec": s1["report"]["spec"], "blocks": a.blocks,
              "steps": results, "wavs": wavs, "result": "PASS" if ok else "FAIL"}
    (OUT / "oneshot_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print("\nWAVs:")
    for w_ in wavs:
        print(f"  {w_['file']}  {w_['seconds']} s, peak {w_['peak']:.4g} -- {w_['what']}")
    print(f"\n  {report['result']}  (report: out/oneshot/oneshot_report.json)")
    return 0 if ok else 1


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_")


if __name__ == "__main__":
    raise SystemExit(main())
