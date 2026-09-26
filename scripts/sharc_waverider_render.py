"""Waverider Milestone 1, the offline render gate: our own SHARC code, run and checked.

    python scripts/sharc_waverider_render.py \\
        --image 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip \\
        --digikit ../digikit-wt-sharcemu [--assemble] [--seconds 0.5]

Three gates, each one required before the next (`docs/waverider-feasibility.md`,
"Milestone 1"):

1. **The executor runs DN2 1.11.** digikit's SHARC+ runner is pointed at our
   section 7 (sha256 checked) and runs `sw 0x1c0790`, a 13-instruction leaf with
   three return paths, to its return for eleven inputs. Each result is checked
   against the routine as read statically (`expect_1c0790`). With `--assemble`
   the same bytes are also decoded by selache's `selmap` and the two decoders'
   instruction boundaries are compared.
2. **Our reader runs and matches.** `csrc/waverider/sharc/reader.asm`, assembled
   by selache's `selas`, is spliced into the DN2 1.11 boot stream at spans the
   stream never loads, with the Milestone 0 table beside it, and run case by
   case against `dnfw.waverider.render` in both precisions.
3. **A WAV.** A frame-position sweep, one position per 32-sample block, rendered
   by the SHARC code and by the reference, written under `out/waverider/`.

**digikit is a tool here, never a dependency.** It is GPL-2.0+; this script
imports its `tools/` from a checkout you name (`--digikit`, or the
`DNFW_DIGIKIT_SHARC` environment variable), and nothing from it is copied into
this repository. The runner lives on digikit's unmerged branch
`work/sharc-emulator`; this gate was measured at `6f812e9`.

**selache is a tool too** (GPL-3.0, built in WSL, `docs/sharc-selache.md`).
Without `--assemble` the committed `reader.json` -- selas's output for the
committed source, checked by the source's sha256 -- is used, so the gate runs
without WSL. With it, the source is reassembled and must reproduce those bytes.

Exit 0 on PASS, 1 on FAIL. A JSON report goes to `out/waverider/m1_report.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.cli.files import read_image                      # noqa: E402
from dnfw.firmware.load import load                        # noqa: E402
from dnfw.image import bootstream, sharc_object           # noqa: E402
from dnfw.waverider import render, testtable             # noqa: E402

SOURCE = ROOT / "csrc" / "waverider" / "sharc" / "reader.asm"
ASSEMBLED = ROOT / "csrc" / "waverider" / "sharc" / "reader.json"
SECTION = "seg_pmco"
OUT = ROOT / "out" / "waverider"

DN2_111_SECTION7 = "336e340aa0cdcd34e314cfa44849f709a3134f6bd4cd57dfc7e15702c83115e2"
DIGIKIT_MEASURED_AT = "6f812e9"
SELAS = "/root/selache-target/release/selas"
SELMAP = "/root/selmap-target/release/selmap"

# Where our blocks go. Every byte must be one the DN2 1.11 stream never loads
# (checked in `place`): unloaded by the boot stream, NOT proven unused at run time.
CODE_SW = 0x180000                 # PM short-word address; loads at 0x28300000
TABLE_DM = 0x280000                # DM pointers the way the firmware writes them
PARAMS_DM = 0x284000
OUT_DM = 0x288000
MAX_BLOCK = 4096                   # floats the output span holds

STEP1_FN = 0x1c0790
STEP1_RETURN = 0x1c07a6


# -- gate 1 ------------------------------------------------------------------------

def expect_1c0790(r4: int) -> int:
    """`sw 0x1c0790` as read statically from the listing:

        R0 = pass(R4); R2 = R4 + 0xd8000000        (R4 - 0x28000000)
        if R2 <u 0x240000:  return R4
        if R2 <=u 0x39ffff: return R2
        return R4

    i.e. an L1 byte-alias address in 0x28240000..0x2839ffff comes back with the
    0x28000000 alias removed, and anything else comes back unchanged.
    """
    r2 = (r4 - 0x28000000) & 0xFFFFFFFF
    if r2 < 0x240000:
        return r4
    return r2 if r2 <= 0x39FFFF else r4


STEP1_INPUTS = (0x28000000, 0x28100000, 0x2823FFFF, 0x28240000, 0x28300000, 0x2839FFFF,
                0x283A0000, 0x27FFFFFF, 0x80001000, 0x00000000, 0xFFFFFFFF)


def gate1(dk, memory) -> dict:
    results, ok = [], True
    for r4 in STEP1_INPUTS:
        runner = dk.run.Runner(memory, STEP1_FN, regs={"R4": r4})
        res = runner.run(100)
        got = runner.state.uregs[dk.st.UREG_CODES["R0"]]
        got = got.value if isinstance(got, dk.st.Const) else None
        want = expect_1c0790(r4)
        good = (got == want and res.halt.reason == "return without followed call"
                and res.halt.pc_sw == STEP1_RETURN)
        ok &= good
        results.append({"R4": f"{r4:#010x}", "R0": None if got is None else f"{got:#010x}",
                        "expected": f"{want:#010x}", "instructions": res.instructions,
                        "halt": f"{res.halt.reason} at {res.halt.pc_sw:#x}", "ok": good})
    return {"ok": ok, "function": f"{STEP1_FN:#x}", "cases": results}


# -- selache (WSL) ---------------------------------------------------------------------

def _wsl_path(p: pathlib.Path) -> str:
    p = p.resolve()
    return f"/mnt/{p.drive[0].lower()}{p.as_posix()[2:]}"


def _wsl(script: str, work: pathlib.Path) -> subprocess.CompletedProcess:
    """Run a shell script in WSL from a file -- never an inline string."""
    sh = work / "run.sh"
    sh.write_bytes(script.encode())
    return subprocess.run(["wsl", "-e", "sh", _wsl_path(sh)], capture_output=True, text=True)


def assemble(work: pathlib.Path) -> bytes:
    """selas the committed source -> the section's bytes, object parcel order."""
    obj = work / "reader.doj"
    r = _wsl(f"{SELAS} -proc ADSP-21569 -o {_wsl_path(obj)} {_wsl_path(SOURCE)}\n", work)
    if r.returncode or not obj.exists():
        raise SystemExit(f"selas failed:\n{r.stdout}{r.stderr}")
    return sharc_object.code(obj.read_bytes(), SECTION)


def selas_offsets(work: pathlib.Path) -> tuple[list[int], bytes]:
    """The assembler's own instruction boundaries -> (byte offsets, the section).

    The source is reassembled with a label in front of every instruction and the
    labels are read back from the object's symbol table, so the offsets are the
    ones selas used in this very assembly. A decoder's walk is only evidence
    against the producer's boundaries, and selache's own disassembler cannot
    supply them: it does not read some 16-bit forms its assembler emits (the
    Type 3c load `0x9013`, for one), and walks past them. Assembling each
    instruction alone does not work either: selas compresses differently
    inside a DO loop.
    """
    lines, k = [], 0
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        text = line.split("//", 1)[0].strip()
        if text and not text.startswith(".") and not text.endswith(":"):
            lines += [f".GLOBAL wr_i{k};", f"wr_i{k}:"]     # only globals reach .symtab
            k += 1
        lines.append(line)
    src = work / "labelled.asm"
    src.write_bytes(("\n".join(lines) + "\n").encode())
    obj = work / "labelled.doj"
    r = _wsl(f"{SELAS} -proc ADSP-21569 -o {_wsl_path(obj)} {_wsl_path(src)}\n", work)
    if r.returncode or not obj.exists():
        raise SystemExit(f"selas (labelled) failed:\n{r.stdout}{r.stderr}")
    data = obj.read_bytes()
    symbols = sharc_object.symbols(data)
    # symbol values are PM short-word (16-bit parcel) addresses in the section
    offsets = [2 * symbols[f"wr_i{j}"] for j in range(k)]
    return offsets, sharc_object.code(data, SECTION)


def selmap_starts(code: bytes, work: pathlib.Path) -> list[int]:
    """selache's linear walk of CODE (memory order) -> instruction start offsets."""
    blob = work / "walk.bin"
    blob.write_bytes(code)
    r = _wsl(f"{SELMAP} < {_wsl_path(blob)}\n", work)
    if r.returncode:
        raise SystemExit(f"selmap failed:\n{r.stderr}")
    width = {}
    for line in r.stdout.splitlines():
        off, n, _ = line.split("\t", 2)
        width[int(off)] = int(n)
    starts, at = [], 0
    while at in width and at < len(code):
        starts.append(at)
        at += width[at]
    return starts


def source_sha() -> str:
    return hashlib.sha256(SOURCE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def reader_code(do_assemble: bool, work: pathlib.Path) -> tuple[bytes, list[int], dict]:
    """-> (the reader in memory order, the assembler's instruction offsets, provenance)."""
    committed = json.loads(ASSEMBLED.read_text(encoding="utf-8")) if ASSEMBLED.exists() else None
    info = {"source_sha256": source_sha()}
    if do_assemble:
        be = assemble(work)
        offsets, labelled = selas_offsets(work)
        if labelled != be:
            raise SystemExit("labelling the source changed what selas emits")
        info["assembled"] = "now, with selas"
        if committed and committed["source_sha256"] == info["source_sha256"]:
            info["matches_committed"] = (bytes.fromhex(committed["object_parcels_be"]) == be
                                         and committed.get("instruction_offsets") == offsets)
    else:
        if not committed:
            raise SystemExit(f"{ASSEMBLED} is missing: run with --assemble (needs WSL + selache)")
        if committed["source_sha256"] != info["source_sha256"]:
            raise SystemExit(f"{ASSEMBLED} is stale for {SOURCE.name}: run with --assemble")
        be = bytes.fromhex(committed["object_parcels_be"])
        offsets = committed["instruction_offsets"]
        info["assembled"] = f"committed {ASSEMBLED.name} ({committed['toolchain']})"
    return sharc_object.load_bytes(be), offsets, info


def write_assembled(code: bytes, offsets: list[int]) -> None:
    ASSEMBLED.write_bytes((json.dumps({
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": source_sha(),
        "toolchain": "selache selas -proc ADSP-21569 (js216/selache 2b26d3b, GPL-3.0, WSL)",
        "section": SECTION,
        "object_parcels_be": sharc_object.load_bytes(code).hex(),
        "instruction_offsets": offsets,
    }, indent=2) + "\n").encode())


# -- digikit -----------------------------------------------------------------------------

class Digikit:
    """digikit's SHARC tools, imported from a checkout the caller names."""

    def __init__(self, path: pathlib.Path):
        tools = path / "tools"
        if not (tools / "sharc_run.py").exists():
            raise SystemExit(f"{path} has no tools/sharc_run.py: point --digikit at a "
                             f"checkout of work/sharc-emulator ({DIGIKIT_MEASURED_AT})")
        sys.path.insert(0, str(tools))
        import sharc_run  # noqa: PLC0415
        import sharc_trace  # noqa: PLC0415
        import sharcldr  # noqa: PLC0415
        self.run, self.st, self.ldr = sharc_run, sharc_trace, sharcldr
        try:
            self.head = subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                                       capture_output=True, text=True).stdout.strip() or "?"
        except OSError:
            self.head = "?"

    def walk(self, memory, start_sw: int, end_sw: int) -> list[tuple[int, int, str, str]]:
        """digikit's decode from START_SW -> [(sw, parcels, form, kind)] up to END_SW."""
        out, pc = [], start_sw
        while pc < end_sw:
            insn = self.st.decode_at(memory, None, pc)
            out.append((pc, (insn.length_bytes or 0) // 2, insn.type_name, insn.kind))
            if not insn.length_bytes:
                break
            pc += insn.length_bytes // 2
        return out


# -- gate 2 ------------------------------------------------------------------------------

def dn2_section7(image: pathlib.Path) -> bytes:
    fw = load(read_image(image))
    section = fw.container.find(7)
    if section is None:
        raise SystemExit(f"{image} has no section 7")
    data = section.unpack() or section.raw_payload
    digest = hashlib.sha256(data).hexdigest()
    if digest != DN2_111_SECTION7:
        raise SystemExit(f"section 7 sha256 {digest[:12]}... is not DN2 1.11's "
                         f"{DN2_111_SECTION7[:12]}...")
    return data


def place(dk, stream: bytes, code: bytes, table: bytes) -> tuple[bytes, list[dict]]:
    """Splice our code and table into the DN2 stream, only where it loads nothing."""
    base = dk.ldr.LoadedMemory.from_stream(stream)
    spans = [("reader code", dk.ldr.sw_to_byte(CODE_SW), code),
             ("wavetable", dk.ldr.SW_ALIAS_BASE + TABLE_DM, table)]
    reserved = [("parameter block", dk.ldr.SW_ALIAS_BASE + PARAMS_DM, 64),
                ("output buffer", dk.ldr.SW_ALIAS_BASE + OUT_DM, 4 * MAX_BLOCK)]
    report = []
    for name, at, size in [(n, a, len(b)) for n, a, b in spans] + reserved:
        owners = {o for _, _, o in base.owner_runs(at, size)}
        if owners != {None}:
            raise SystemExit(f"{name} at {at:#x}+{size:#x} overlaps DN2 1.11 block(s) {owners}")
        report.append({"what": name, "load_address": f"{at:#010x}", "bytes": size,
                       "dn2_blocks_overlapped": 0})
    extra = b"".join(bootstream.block(at, payload) for _, at, payload in spans)
    return bootstream.insert_before_final(stream, extra), report


def read_floats(dk, state, address: int, count: int) -> list[float]:
    import struct  # noqa: PLC0415
    out = []
    for k in range(count):
        v = dk.st._dm_read(state, address + 4 * k, 4)
        if not isinstance(v, dk.st.Const):
            raise SystemExit(f"output word {k} at {address + 4 * k:#x} is not concrete")
        out.append(struct.unpack("<f", struct.pack("<I", v.value))[0])
    return out


def poke(dk, state, address: int, value: int) -> None:
    if not dk.st._dm_write(state, address, 4, dk.st.Const(value & 0xFFFFFFFF)):
        raise SystemExit(f"write to {address:#x} did not take effect")


def peek(dk, state, address: int) -> int:
    v = dk.st._dm_read(state, address, 4)
    if not isinstance(v, dk.st.Const):
        raise SystemExit(f"{address:#x} is not concrete")
    return v.value


class Reader:
    """wr_render, called over and over on one runner so memory carries between calls."""

    def __init__(self, dk, memory):
        self.dk, self.memory = dk, memory
        self.runner = dk.run.Runner(memory, CODE_SW)
        self.instructions = 0
        self.elapsed = 0.0
        self.calls = 0

    def __call__(self, phase: int, inc: int, pos: int, count: int) -> tuple[list[float], int]:
        if not 1 <= count <= MAX_BLOCK:
            raise ValueError(f"count {count} is outside 1..{MAX_BLOCK}")
        dk = self.dk
        runner = self.runner.fresh_call(CODE_SW, regs={"R4": PARAMS_DM}) if self.calls else \
            dk.run.Runner(self.memory, CODE_SW, regs={"R4": PARAMS_DM})
        for k, v in enumerate((TABLE_DM, phase, inc, pos, count, OUT_DM)):
            poke(dk, runner.state, PARAMS_DM + 4 * k, v)
        res = runner.run(200 * count + 200)
        if res.halt.reason != "return without followed call":
            raise SystemExit(f"wr_render stopped: {res.halt}")
        self.instructions += res.instructions
        self.elapsed += res.elapsed
        self.calls += 1
        self.runner = runner
        return read_floats(dk, runner.state, OUT_DM, count), peek(dk, runner.state, PARAMS_DM + 4)


def compare(got: list[float], table, phase, inc, pos, count) -> dict:
    ideal, end = render.render(table, phase, inc, pos, count, "ideal")
    f32, _ = render.render(table, phase, inc, pos, count, "float32")
    return {"max_abs_error_vs_ideal": max(abs(a - b) for a, b in zip(got, ideal)),
            "float32_mismatches": sum(1 for a, b in zip(got, f32) if a != b),
            "phase_out": end}


CASES = (   # (label, phase, freq Hz or raw inc, Q16 pos, N)
    ("frame 0 (sine), 440 Hz", 0, 440.0, 0, 128),
    ("frame 15 (saw), 440 Hz", 0, 440.0, 15 << 16, 128),
    ("between frames 7 and 8, 1 kHz", 0x12345678, 1000.0, (7 << 16) + 0x8000, 128),
    ("odd frame fraction, 97 Hz", 0x80000000, 97.0, 0x3C71C, 256),
    ("phase wrap 511 -> 0", 0xFF800000, 0x00123457, 5 << 16, 64),
    ("fast: 20 samples a cycle", 0x0000FFFF, 2400.0, 0xEFFFF, 64),
    ("DC: zero increment", 0x7FC00000, 0, 0x98765, 16),
)


def gate2(dk, reader: Reader, table) -> dict:
    rows, ok = [], True
    for label, phase, freq, pos, n in CASES:
        inc = freq if isinstance(freq, int) else render.increment(freq)
        got, phase_out = reader(phase, inc, pos, n)
        c = compare(got, table, phase, inc, pos, n)
        good = (c["float32_mismatches"] == 0 and c["max_abs_error_vs_ideal"] < 1e-6
                and phase_out == c["phase_out"])
        ok &= good
        rows.append({"case": label, "phase": f"{phase:#010x}", "inc": f"{inc:#010x}",
                     "pos_q16": f"{pos:#x}", "n": n,
                     "max_abs_error_vs_ideal": c["max_abs_error_vs_ideal"],
                     "float32_mismatches": c["float32_mismatches"],
                     "phase_out_ok": phase_out == c["phase_out"], "ok": good})
    return {"ok": ok, "cases": rows}


def write_wav(path: pathlib.Path, samples: list[float], rate: int = 48000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(render.pcm16(samples))


def gate3(reader: Reader, table, seconds: float, freq: float, block: int) -> dict:
    blocks = max(2, int(round(seconds * 48000 / block)))
    positions = render.sweep(len(table), blocks)
    inc = render.increment(freq)
    got, phase = [], 0
    for pos in positions:
        samples, phase = reader(phase, inc, pos, block)
        got += samples
    ideal = render.render_blocks(table, inc, positions, block, 0, "ideal")
    f32 = render.render_blocks(table, inc, positions, block, 0, "float32")
    write_wav(OUT / "m1_sharc.wav", got)
    write_wav(OUT / "m1_reference.wav", ideal)
    err = max(abs(a - b) for a, b in zip(got, ideal))
    mism = sum(1 for a, b in zip(got, f32) if a != b)
    pcm, pcm_ideal = render.pcm16(got), render.pcm16(ideal)
    pcm_diff = sum(1 for k in range(0, len(pcm), 2) if pcm[k:k + 2] != pcm_ideal[k:k + 2])
    return {"ok": mism == 0 and err < 1e-6, "samples": len(got), "blocks": blocks,
            "block": block, "freq_hz": freq, "max_abs_error_vs_ideal": err,
            "float32_mismatches": mism,
            "pcm16_identical_to_float32_reference": pcm == render.pcm16(f32),
            "pcm16_samples_differing_from_ideal": pcm_diff,
            "wav": [str((OUT / "m1_sharc.wav").relative_to(ROOT)),
                    str((OUT / "m1_reference.wav").relative_to(ROOT))]}


# -- main --------------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip",
                   help="the DN2 1.11 update (.zip or .syx)")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                       ROOT.parent / "digikit-wt-sharcemu")),
                   help="a digikit checkout of work/sharc-emulator (env DNFW_DIGIKIT_SHARC)")
    p.add_argument("--assemble", action="store_true",
                   help="reassemble with selas and cross-decode with selmap (WSL)")
    p.add_argument("--write-assembled", action="store_true",
                   help="with --assemble: refresh the committed reader.json")
    p.add_argument("--seconds", type=float, default=0.5, help="length of the WAV sweep")
    p.add_argument("--freq", type=float, default=110.0, help="WAV pitch, Hz")
    p.add_argument("--block", type=int, default=32, help="samples per call in the WAV")
    args = p.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    dk = Digikit(args.digikit)
    report["digikit"] = {"path": str(args.digikit), "head": dk.head,
                         "measured_at": DIGIKIT_MEASURED_AT}
    stream = dn2_section7(args.image)
    dn2 = dk.ldr.LoadedMemory.from_stream(stream)

    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        work = pathlib.Path(tmp)

        print("gate 1: digikit's SHARC runner on DN2 1.11")
        g1 = gate1(dk, dn2)
        if args.assemble:
            fn_bytes = dn2.read(dk.ldr.sw_to_byte(STEP1_FN), 2 * (STEP1_RETURN + 4 - STEP1_FN))
            sel = [STEP1_FN + o // 2 for o in selmap_starts(fn_bytes, work)]
            dig = [sw for sw, _, _, _ in dk.walk(dn2, STEP1_FN, STEP1_RETURN + 4)]
            g1["selache_boundaries_agree"] = sel == dig
            g1["ok"] &= sel == dig
        report["gate1"] = g1
        for c in g1["cases"]:
            print(f"  R4={c['R4']} -> R0={c['R0']} (expect {c['expected']}) "
                  f"{c['instructions']:2d} instrs, {c['halt']}  {'ok' if c['ok'] else 'FAIL'}")
        if "selache_boundaries_agree" in g1:
            print(f"  selache and digikit instruction boundaries agree: "
                  f"{g1['selache_boundaries_agree']}")
        if not g1["ok"]:
            return finish(report, False)

        print("\ngate 2: our reader, in the DN2 1.11 image")
        code, offsets, provenance = reader_code(args.assemble, work)
        if args.assemble and args.write_assembled:
            write_assembled(code, offsets)
            provenance["written"] = str(ASSEMBLED.relative_to(ROOT))
        elif provenance.get("matches_committed") is False:
            print(f"  selas no longer reproduces {ASSEMBLED.name} for this source "
                  f"(a different selache build?); --write-assembled refreshes it")
            report["gate2"] = {"provenance": provenance, "ok": False}
            return finish(report, False)
        table = testtable.table()
        memory_stream, placed = place(dk, stream, code, render.dsp_bytes(table))
        memory = dk.ldr.LoadedMemory.from_stream(memory_stream)
        end_sw = CODE_SW + len(code) // 2
        walk = dk.walk(memory, CODE_SW, end_sw)
        starts = [(sw - CODE_SW) * 2 for sw, _, _, _ in walk]
        g2 = {"provenance": provenance, "placement": placed, "code_bytes": len(code),
              "instructions": len(walk), "source_instructions": len(offsets),
              "digikit_matches_assembler_boundaries": starts == offsets,
              "unknown_forms": [f"{sw:#x}" for sw, _, form, _ in walk if form == "unknown"],
              "uncertain_forms": [f"{sw:#x} {form}" for sw, _, form, kind in walk
                                  if kind == "uncertain"]}
        if args.assemble:
            # Informational: selache's own disassembler, which misses 16-bit forms.
            sel = selmap_starts(code, work)
            g2["selmap_walk_disagrees_at"] = [o for o in offsets if o not in sel]
        print(f"  {len(code)} bytes, {len(walk)} instructions ({provenance['assembled']})")
        for row in placed:
            print(f"  {row['what']:16s} at {row['load_address']}, {row['bytes']:6,} B, "
                  f"unloaded by DN2 1.11")
        decoded = (g2["digikit_matches_assembler_boundaries"] and not g2["unknown_forms"]
                   and not g2["uncertain_forms"])
        print(f"  digikit's decode = selas's {len(offsets)} instruction boundaries: "
              f"{g2['digikit_matches_assembler_boundaries']}; unknown/uncertain forms: "
              f"{g2['unknown_forms'] + g2['uncertain_forms'] or 'none'}")
        if "selmap_walk_disagrees_at" in g2:
            print(f"  (selmap's own walk misses boundaries at byte offsets "
                  f"{g2['selmap_walk_disagrees_at'] or 'none'})")
        if not decoded:
            report["gate2"] = {**g2, "ok": False}
            return finish(report, False)
        reader = Reader(dk, memory)
        cases = gate2(dk, reader, table)
        g2.update(cases)
        g2["ok"] = cases["ok"]
        for r in cases["cases"]:
            print(f"  {r['case']:34s} n={r['n']:4d}  max err {r['max_abs_error_vs_ideal']:.2e}"
                  f"  float32 mismatches {r['float32_mismatches']}  {'ok' if r['ok'] else 'FAIL'}")
        report["gate2"] = g2
        if not g2["ok"]:
            return finish(report, False)

        print(f"\ngate 3: a {args.seconds} s frame sweep at {args.freq} Hz, "
              f"{args.block}-sample blocks")
        t0 = time.perf_counter()
        g3 = gate3(reader, table, args.seconds, args.freq, args.block)
        g3["wall_s"] = time.perf_counter() - t0
        report["gate3"] = g3
        print(f"  {g3['samples']:,} samples, max err {g3['max_abs_error_vs_ideal']:.2e}, "
              f"float32 mismatches {g3['float32_mismatches']}, "
              f"16-bit PCM = float32 reference: {g3['pcm16_identical_to_float32_reference']}, "
              f"{g3['pcm16_samples_differing_from_ideal']} sample(s) differ from the ideal's PCM")
        print(f"  wrote {', '.join(g3['wav'])}")

    report["speed"] = {"instructions": reader.instructions, "runner_s": reader.elapsed,
                       "instructions_per_second": reader.instructions / reader.elapsed,
                       "calls": reader.calls,
                       "python": sys.version.split()[0],
                       "implementation": sys.implementation.name}
    print(f"\n  {reader.instructions:,} SHARC instructions in {reader.elapsed:.1f} s = "
          f"{reader.instructions / reader.elapsed:,.0f} instr/s ({sys.implementation.name})")
    return finish(report, g3["ok"])


def finish(report: dict, ok: bool) -> int:
    report["result"] = "PASS" if ok else "FAIL"
    (OUT / "m1_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n",
                                        encoding="utf-8")
    print(f"\n  {report['result']}  (report: out/waverider/m1_report.json)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
