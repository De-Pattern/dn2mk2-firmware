"""Focused offline proof: external samples through the stock DN2 filter/amp.

Uses the actual stock 1.11 DSP, replacing one oscillator buffer at the existing
custom-machine insertion point. Does not flash, send MIDI, or claim USB timing.
The first run initializes the DSP once; the source-bound cache is reused.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import sharc_waverider_m4 as m4
import sharc_waverider_voice as m2
import sharc_waverider_render as m1
import sharc_dn2_fixups as fx
from dnfw.waverider import frame as FR, voice as V, testtable
from dnfw.image import bootstream
from dnfw.sidecar.native_return import Config, MAGIC, USB_PLANES

BLOCK, RATE = 32, 48000
ENTRY_SW = 0x1C9448  # Existing pre-filter custom-machine insertion point


def run_blocks(state, frames, blocks, inject, trace=False, owners=(0,)):
    """Only the stock frame unpack/voice chain, without unrelated mod engines."""
    out = {"ok": True, "buffers": [], "amp_in": [], "amp_out": [], "amp_state": []}
    stack = m2.word_reg(state, "I7")
    for block in range(blocks):
        taps = {}
        def amp(r):
            buf = m2.word(r.state, V.TRACK_BUFFERS + 4 * owners[0])
            if m2.word_reg(r, "R12") == buf and "in" not in taps:
                taps["in"] = m2.floats(r.state, buf, BLOCK)
                if trace:
                    at = m2.word_reg(r, "R4")
                    out["amp_state"].append({"block": block, "base": hex(at),
                        "words": [m2.word(r.state, at + 4 * k) for k in range(32)],
                        "R8": m2.word_reg(r, "R8")})
        def amp_return(r):
            if "in" in taps and "out" not in taps:
                taps["out"] = m2.floats(r.state, m2.word(r.state, V.TRACK_BUFFERS + 4 * owners[0]), BLOCK)
        hooks = {ENTRY_SW: inject, m4.m3.AMP_STAGE: amp, m4.AMP_RETURN: amp_return}
        tracer = m4.ChainTracer() if trace and block == blocks - 1 else None
        if tracer:
            tracer.buf = m2.word(state.state, V.TRACK_BUFFERS + 4 * owners[0])
            tracer.active = True
            tracer.hooks.update(hooks)
        r = m4.unpack_call(state, frames(block), i7=stack)
        result = fx.run(r, 8_000_000, tracer or m4.fixups(hooks))
        if tracer: out["stage_trace"] = tracer.calls
        if not (result[0] == "halt" and result[1].pc_sw == m4.UNPACK_RETURN):
            out.update(ok=False, halt=str(result[:2]))
            return out
        out["buffers"].append([m2.floats(r.state, m2.word(r.state, V.TRACK_BUFFERS + 4 * v), BLOCK) for v in owners])
        out["amp_in"].extend(taps.get("in", []))
        out["amp_out"].extend(taps.get("out", []))
        state = r
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--digikit", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "out/sidecar-native-chain")
    ap.add_argument("--blocks", type=int, default=12)
    ap.add_argument("--parts", type=int, default=1, choices=(1, 8))
    ap.add_argument("--case", choices=("open", "closed", "minimum_volume", "slow_attack"))
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--filter-type", type=int, default=1, choices=range(6))
    ap.add_argument("--init-cache", type=Path)
    ap.add_argument("--router-bin", type=Path, help="Compiled router from check_sidecar_return_router.py")
    args = ap.parse_args()
    owners = (0,) if args.parts == 1 else (15, 13, 11, 9, 7, 5, 3, 1)
    if args.parts == 8 and not args.router_bin:
        ap.error("eight-part proof requires the compiled return router")
    if args.blocks < 4:
        ap.error("at least four blocks are required")
    args.out.mkdir(parents=True, exist_ok=True)
    dk = m1.Digikit(args.digikit)
    fx.bind(str(args.digikit / "tools"))
    m4.IMAGE = args.image
    stock = m1.dn2_section7(args.image)
    sound, machines = m4.init_sound(args.image)
    stream = stock
    router_cfg = Config(0x290000)
    if args.router_bin:
        router_code = args.router_bin.read_bytes()
        # This is the checked emulator-only placement, not a shipping address.
        stream = bootstream.insert_before_final(stock, bootstream.block(0x28300000, router_code))
    memory = dk.ldr.LoadedMemory.from_stream(stream)
    report = {
        "scope": "Stock DSP filter/amp with synthetic external input; no USB or hardware latency proof",
        "stock_dsp_sha256": hashlib.sha256(stock).hexdigest(),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": {},
        "filter_type": args.filter_type,
        "owners": owners,
        "router_sha256": hashlib.sha256(router_code).hexdigest() if args.router_bin else None,
    }
    target = args.out / "report.json"
    with tempfile.TemporaryDirectory() as tmp:
        reader, _, _ = m1.reader_code(False, Path(tmp))
        mach = m2.Machine(dk, stock, reader, testtable.table())
        cache = args.init_cache or args.out / f"init-{mach.sha[:12]}.snap"
        print("Initializing stock DSP (cached after a successful return)", flush=True)
        init = m2.run_init(mach, cache, accelerate=True, validate=1)
        report["initialization"] = {k: v for k, v in init.items() if k != "runner"}
        target.write_text(json.dumps(report, indent=2))
        if not init["ok"]:
            print("Stock DSP initialization failed; see report.json", flush=True)
            return 1
        cases_to_run = [
            ("open", 127, 100, 0),
            ("closed", 0, 100, 0),
            ("minimum_volume", 127, 0, 0),
            ("slow_attack", 127, 100, 100),
        ]
        if args.parts == 8:
            cases_to_run += [("part4_closed", 0, 100, 0), ("part4_minimum_volume", 127, 0, 0)]
        for name, cutoff, volume, attack in cases_to_run:
            if args.case and args.case != name:
                continue
            print("Native chain case: " + name, flush=True)
            runner = fx.sr.load_snapshot(str(cache), mach.memory)
            runner.data = memory
            runner.state = dataclasses.replace(runner.state, concrete=memory)
            injected = [[] for _ in owners]

            def inject(r):
                # A continuous 6 kHz signal exposes lowpass attenuation. Every
                # case starts from identical engine state and sample phase.
                for lane, owner in enumerate(owners):
                    buf = m2.word(r.state, V.TRACK_BUFFERS + 4 * owner)
                    if not buf:
                        raise RuntimeError("No native track buffer at insertion point")
                    for i in range(BLOCK):
                        x = 0.1 * (lane + 1) / len(owners) * math.sin(2 * math.pi * 6000 * len(injected[lane]) / RATE)
                        word = V.f32_bits(x)
                        injected[lane].append(V.bits_f32(word))
                        m2.poke(r.state, (USB_PLANES + lane * BLOCK * 4 if args.router_bin else buf) + 4 * i, word)
                if args.router_bin:
                    # Model the future negotiated owner descriptor, then execute
                    # the actual router instructions. The surrounding custom-
                    # machine wrapper must preserve registers just as this call
                    # boundary does; no DSP filter/amp code is replaced.
                    m2.poke(r.state, router_cfg.enabled, MAGIC)
                    m2.poke(r.state, router_cfg.owned, sum(1 << v for v in owners))
                    for lane in range(8):
                        m2.poke(r.state, router_cfg.owner(lane), owners[lane] if lane < len(owners) else 0xFFFFFFFF)
                        if lane >= len(owners):
                            for i in range(BLOCK):
                                m2.poke(r.state, USB_PLANES + (lane * BLOCK + i) * 4, 0)
                    call = r.fresh_call(0x180000, regs={"M6": 1})
                    done = fx.run(call, 200000, fx.Fixups())
                    if not (done[0] == "halt" and done[1].reason == "return without followed call"):
                        raise RuntimeError("Compiled router did not return: " + str(done[:2]))
                    r.state = dataclasses.replace(r.state, overlay=call.state.overlay)
                    if any(m2.word(r.state, USB_PLANES + i * 4) for i in range(BLOCK * 8)):
                        raise RuntimeError("Router left a direct USB bypass signal")
                    for lane, owner in enumerate(owners):
                        buf = m2.word(r.state, V.TRACK_BUFFERS + 4 * owner)
                        copied = m2.floats(r.state, buf, BLOCK)
                        if copied != injected[lane][-BLOCK:]:
                            raise RuntimeError(f"Part {lane + 1} did not reach its native source buffer")

            def frames(block):
                f = FR.init_frame(sound, 4)
                for lane, owner in enumerate(owners):
                    f.header(FR.MACHINE, owner, 1)
                    f.sound(owner, {**machines.get(1, {}), 25: 0x4000})
                    # A played note asserts ON, not ON and OFF together.
                    # The legacy helper defaults to all four trigger masks.
                    if block == 0: f.trigger(owner, masks=(FR.TRIG_NOTE,))
                    f.header(52, owner, 127 << 8)  # played velocity
                    f.header(FR.FILTER, owner, args.filter_type)
                    f.header(FR.LEVEL, owner, 127 << 8)
                    affected = not name.startswith("part4_") or lane == 3
                    # Native filter and amp controls, in the instrument's own scale.
                    for index, value in {
                        67: cutoff if affected else 127, 68: 0, 69: 64, 76: 0, 77: 127,
                        81: attack, 82: 0, 83: 127, 84: 127, 85: 127,
                        90: volume if affected else 100, 95: 0, 96: 0, 98: 0,
                    }.items():
                        f.param(owner, index, value << 8)
                return f.to_bytes()

            result = run_blocks(runner, frames, args.blocks, inject, args.trace, owners)
            outputs = [[x for block in result["buffers"] for x in block[lane]] for lane in range(len(owners))]
            output = outputs[0]
            def rms(xs):
                return math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else 0.0
            row = {
                "ok": result["ok"], "halt": result.get("halt"),
                "input_samples": len(injected[0]), "output_samples": len(output),
                "input_rms": rms(injected[0]), "output_rms": rms(output),
                "part_rms": [rms(xs) for xs in outputs],
                "amp_input_rms": rms(result["amp_in"]),
                "amp_output_rms": rms(result["amp_out"]),
                "finite": all(math.isfinite(x) for xs in outputs for x in xs),
                "stage_trace": result.get("stage_trace", []),
                "amp_state": result["amp_state"],
            }
            report["cases"][name] = row
            target.write_text(json.dumps(report, indent=2))
            print(json.dumps({"case": name, **row}), flush=True)
            if not result["ok"]:
                return 1
    cases = report["cases"]
    if args.case:
        report["diagnostic_only"] = True
        target.write_text(json.dumps(report, indent=2))
        return 0
    open_rms = cases["open"]["output_rms"]
    report["checks"] = {
        "every_case_completed_with_finite_audio": all(
            x["ok"] and x["finite"] and x["output_samples"] == args.blocks * BLOCK
            for x in cases.values()),
        "open_native_chain_is_audible": open_rms > 1e-5,
        "native_filter_attenuates_test_signal": cases["closed"]["output_rms"] < open_rms * 0.1,
        "native_amp_volume_reduces_level": cases["minimum_volume"]["output_rms"] < open_rms * 0.1,
        "native_amp_attack_changes_onset": cases["slow_attack"]["output_rms"] < open_rms * 0.5,
    }
    report["ok"] = all(report["checks"].values())
    if args.parts == 8:
        baseline = cases["open"]["part_rms"]
        report["checks"]["all_eight_native_chains_audible"] = all(x > 1e-5 for x in baseline)
        for case in ("part4_closed", "part4_minimum_volume"):
            actual = cases[case]["part_rms"]
            report["checks"][case + "_isolated"] = actual[3] < baseline[3] * 0.1 and all(
                actual[i] == baseline[i] for i in range(8) if i != 3)
        report["ok"] = all(report["checks"].values())
    target.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["checks"], indent=2), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
