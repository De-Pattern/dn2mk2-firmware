"""Assemble and execute the external-audio router in the SHARC emulator.

Checks compiled instruction behavior against the routing model. The model's
ownership/bypass contract has separate tests. No device access or firmware build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from dnfw.image import bootstream, sharc_object
from dnfw.perc.dsl import Mem, Prog, bits
from dnfw.sidecar.native_return import Config, MAGIC, USB_PLANES, TRACK_BUFFERS, route, assembly
from dnfw.sidecar.native_return import FRAME, FRAME_TAG, FRAME_NATIVE, FRAME_IDLE, publish_frame, frame_assembly
from dnfw.sidecar.machines import TYPE
import sharc_waverider_render as m1
import sharc_waverider_voice as m2
import sharc_dn2_fixups as fx
from sharc_resolve_jumps import resolve


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--digikit", type=Path, required=True)
    ap.add_argument("--selas", type=Path, help="SHARC assembler executable inside this environment")
    ap.add_argument("--frame", action="store_true", help="Execute the real-frame descriptor publisher before routing")
    ap.add_argument("--tail", action="store_true", help="Check the packaged shared tail and register restoration in --image")
    ap.add_argument("--out", type=Path, default=ROOT / "out/sidecar-return-router")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if a.selas:
        m1.SELAS = str(a.selas.resolve())
    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    if a.tail:
        from dnfw.cli.files import read_image
        from dnfw.firmware.load import load
        stock = load(read_image(a.image)).container.find(7).unpack()
        a.frame = True
    else:
        stock = m1.dn2_section7(a.image)
    cfg = Config(0x290000)  # isolated emulator addresses, not a shipping placement
    code_sw, buffers = 0x180000, 0x291000
    if a.tail:
        cfg, code_sw = Config(0x2E1D00), 0x170280
        spec = json.loads((ROOT / "csrc/waverider/sharc/ping.json").read_text())
        source = (ROOT / spec["source"]).read_text()
        assert hashlib.sha256(source.encode()).hexdigest() == spec["source_sha256"]
        offsets = spec["instruction_offsets"]
        code = sharc_object.load_bytes(bytes.fromhex(spec["object_parcels_be"]))
        # Execute the candidate's own bytes, not a separately spliced test copy.
        stream = stock
    else:
        with tempfile.TemporaryDirectory() as tmp:
            source, parcels, offsets = resolve((frame_assembly if a.frame else assembly)(cfg), code_sw, Path(tmp))
        code = sharc_object.load_bytes(parcels)
        load_address = 0x28000000 + 2 * code_sw
        original = dk.ldr.LoadedMemory.from_stream(stock)
        assert {o for _, _, o in original.owner_runs(load_address, len(code))} == {None}
        stream = bootstream.insert_before_final(stock, bootstream.block(load_address, code))
    memory = dk.ldr.LoadedMemory.from_stream(stream)
    (a.out / "router.asm").write_text(source)
    (a.out / "router.bin").write_bytes(code)
    rows = []
    cases = [
        ("eight_parts", [15, 3, 12, 7, 9, 1, 6, 10], sum(1 << v for v in (15, 3, 12, 7, 9, 1, 6, 10)), MAGIC),
        ("one_and_old_owner", [5, -1, -1, -1, -1, -1, -1, -1], (1 << 2) | (1 << 5), MAGIC),
        ("duplicate_invalid_unowned", [2, 2, 16, -1, -1, 8, -1, -1], 1 << 2, MAGIC),
        ("no_owners", [-1] * 8, 0, MAGIC),
        ("disabled", list(range(8)), 255, 0),
    ]
    for name, owners, mask, enabled in cases:
        mem = Mem()
        mem.put(cfg.enabled, enabled)
        mem.put(cfg.owned, mask)
        for lane, owner in enumerate(owners):
            mem.put(cfg.owner(lane), owner)
            for sample in range(32):
                mem.put(USB_PLANES + (lane * 32 + sample) * 4,
                        bits(((lane * 32 + sample) % 101 - 50) / 64))
        for voice in range(16):
            mem.put(TRACK_BUFFERS + 4 * voice, buffers + voice * 128)
            for sample in range(32):
                mem.put(buffers + voice * 128 + sample * 4, bits(-0.125))
        for addr in (USB_PLANES - 4, USB_PLANES + 1024, buffers - 4, buffers + 2048):
            mem.put(addr, 0x5A5A5A5A)
        if a.frame:
            def half(offset, value):
                addr, shift = FRAME + (offset & ~3), (offset & 2) * 8
                mem.put(addr, (mem.get(addr) & ~(0xFFFF << shift)) | (value << shift))
            for v in range(16):
                half(148 + 2 * v, 1)
                if mask & (1 << v):
                    half(148 + 2 * v, TYPE)
                    lanes = [i for i, owner in enumerate(owners) if owner == v]
                    lane = lanes[0] if len(lanes) == 1 else FRAME_IDLE
                    half(218 + 146 * v, FRAME_TAG | (FRAME_NATIVE if enabled else 0) | lane)
            if name == "duplicate_invalid_unowned":
                # Two allocated voices claiming one lane must both be silent.
                for v in (2, 5):
                    half(148 + 2 * v, TYPE)
                    half(218 + 146 * v, FRAME_TAG | FRAME_NATIVE)
        saved = {}
        if a.tail:
            names = [f"R{i}" for i in range(16)] + [f"I{i}" for i in range(6)] + ["I12"] + [f"M{i}" for i in range(5)]
            saved = {name: 0x10000 + 4 * i for i, name in enumerate(names)}
            for i, value in enumerate(saved.values()): mem.put(0x2DDE00 + 4 * i, value)
            mem.put(0x30FF00 - 24 * 4, 0x123456)
            mem.put(0x30FF00 - 34 * 4, 0xABCDEF)
            saved.update(I5=0x123456, R10=0xABCDEF, I6=0x30FF00, I7=0x30FF00, M6=1)
        runner = fx.sr.Runner(memory, code_sw,
                             regs={"M6": 1, "I6": 0x30FF00, "I7": 0x30FF00},
                             explicit_memory_model=True, approx_recips=True,
                             follow_loaded_calls=True, max_call_depth=64)
        for addr, value in mem.w.items(): m2.poke(runner.state, addr, value)
        if a.frame: publish_frame(Prog("run", mem), cfg)
        route(Prog("run", mem), cfg)
        result = fx.run(runner, 200000, fx.Fixups(), stop_at=[0x1C944C] if a.tail else [])
        differences = [hex(addr) for addr, value in mem.w.items()
                       if m2.word(runner.state, addr) != value]
        returned = (result[0] == "stop" and result[1] == 0x1C944C) if a.tail else (result[0] == "halt" and result[1].reason == "return without followed call")
        register_differences = [name for name, value in saved.items() if m2.word_reg(runner, name) != value]
        row = {"case": name, "returned": returned, "different_words": differences,
               "different_registers": register_differences,
               "instructions": result[2], "ok": returned and not differences and not register_differences}
        rows.append(row)
        print(json.dumps(row), flush=True)
    report = {"ok": all(x["ok"] for x in rows), "frame_publisher": a.frame, "packaged_tail": a.tail, "code_bytes": len(code),
              "instruction_count": len(offsets), "cases": rows,
              "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "image_sha256": hashlib.sha256(a.image.read_bytes()).hexdigest(),
              "scope": "Packaged tail, routing and register restoration" if a.tail else "Compiled router only; no native filter, live USB, timing, or shipping placement claim"}
    (a.out / "report.json").write_text(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
