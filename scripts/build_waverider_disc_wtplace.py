"""Build `waverider-disc-wtplace[-VARIANT]`: our reader in WaveTone's place (discriminators, never shipped).

    python scripts/build_waverider_disc_wtplace.py --m5b M5B.syx --out OUT.syx
        [--variant wtplace|b0code|passthru|b2|rb-*] [--stock ZIP] [--s7-only S7.bin]

`wtplace`: stock DN2 1.11 section 7 plus one CALL target and our block-1 region:

- the WaveTone arm's `CALL 0x1c6d4a` at sw 0x1c9611 becomes `CALL 0x16ed00`
  (csrc/waverider/sharc/wt_place.asm, a C-ABI adapter that calls wr_render5);
- the region 0x2dd600..0x2e7000 as M5d ships it (the reader, state, tables), with the
  adapter in the type-5 loop's span;
- **no** machine-type lookup patch (so no track is ever type 5), **no** entry JUMP at
  sw 0x1c9448, no type-5 loop.

Variants, one change each:

- `b0code`: wtplace, with the adapter and the reader as **code in L1 block 0** (byte
  0x26f800 and 0x26fa00, above the system stack 0x26f000..0x26f7f4), and the CALL
  pointed there. Their data (save area, parameter block, table 0) stays in block 1,
  where wtplace has it. The SHARC+ PRM says code should not be placed in blocks 1 and
  2 while the data caches are enabled there, and DN2 enables them.
- `passthru`: wtplace, with the adapter at the same block-1 address saving and
  restoring the same registers through the same save area, then tail-jumping to the
  stock WaveTone render sw 0x1c6d4a with the call's own frame and arguments untouched.
  Our reader never runs.
- `b2`: stock section 7 plus the adapter, reader, save area, parameter block and table
  0 at M5's block-2 addresses (0x300000.., the layout nodir ran in). Block 1 is stock.

The reader-halving builds (`rb-*`) are `b2` with one early exit each. An exit
leaves the track buffer as the dispatch hands it over; everything before the exit
runs exactly as in `b2`, and the exit is the full path's own return shape:

- `rb-params`: the adapter saves, fills the parameter block, restores and returns;
  the reader is never called.
- `rb-callret`: the adapter calls the reader, which returns at its entry (`I12 =
  DM(M7, I6)`, a NOP where the full path stores the phase through I4, the JUMP, NOP,
  RFRAME).
- `rb-loads`: the reader sets `I4 = R4`, makes its six parameter loads through I4
  and sets `I2 = R0`, then returns as `rb-callret` does (no store through a DAG).
- `rb-setup`: the reader runs to its first `I0 = R3` (the frame rows stored through
  I4, the constants, the count test, the first tap address), then `JUMP wr5_done`
  (the full return, phase stored through I4).
- `rb-oneread`: `rb-setup` plus the first table read `R4 = DM(0, I0)`.
- `rb-noout`: the full render with the output store `DM(I2, M6) = F4` a NOP.
- `rb-setup-a` .. `-d`: `rb-setup`'s span cut again, each exiting through `JUMP
  wr5_done`: a after the frame rows and their two DAG stores (with the 2c parcel
  `0xc018`, `R1 = R1 + R8`); a2 the same with that add written `R1 = R8 + R1`, which
  has no 16-bit form; b + the frame fraction (`0xffff`, AND, FLOAT BY); c + the
  constants, the count test and `R12 = -16`; d + the first tap address (two
  shifts pairs, `R2 = DM(6, I4)`, the add), stopping before `I0 = R3`.
- `rb-store1`: `rb-loads` with its return's NOP made the full path's phase store
  `DM(1, I4) = R9`: the only store through a DAG it makes. rb-callret and rb-loads
  (both survived) store nothing through a DAG; every build that died does, and every
  `rb-setup-*` makes this store, so this one separates it from the setup span.
- `stages`: `b2` (the full reader, which died on silicon) with a stage marker before
  and after each suspect step. A marker is `I1 = 0x5752_00nn` and two 14a stores
  of it to word 1 (byte 4) of both DSP->ColdFire reply pages (`0x2c49d4`,
  `0x2c59d4`; the ColdFire receives the reply at `0x800053a4`, and no ColdFire code
  reads bytes 4..0x15 of it). The scratch is I1, which the adapter saves and restores. After a stall
  the core writes nothing more and the reply DMA replays its pages, so the last
  marker is where the core stopped; a local USB probe reads it (`0x800053a8`). The
  stage numbers are in STAGES_READER / STAGES_ADAPTER.

Section 3 is m5b's, as in every other Waverider discriminator.
docs/waverider-dsp-compare.md has the reading. Refuses an existing OUT.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.image import bootstream, sharc_object  # noqa: E402
from dnfw.waverider import dsp  # noqa: E402
from dnfw.waverider import render as reference  # noqa: E402

CALL_SW = 0x1C9611                                  # the WaveTone arm's render call
CALL_STOCK = bytes.fromhex("04181c004a6d")          # CALL 0x1c6d4a (DB), 25a, 48-bit, memory order
SOURCE = ROOT / "csrc/waverider/sharc/wt_place.asm"
READER = ROOT / "csrc/waverider/sharc/reader_m5.asm"
# (reader DM, adapter DM, save area, parameter block, table 0) per layout
LAYOUT = {
    "b1": (dsp.READER_DM, dsp.LOOP_DM, 0x2DDE00, 0x2DDF00, 0x2DF000),
    "b0": (0x26F800, 0x26FA00, 0x2DDE00, 0x2DDF00, 0x2DF000),
    "b2": (0x300000, 0x300400, 0x301000, 0x301100, 0x302000),
}
B0_FREE = (0x26F7F4, 0x270000)                      # above the system stack, to block 0's end
PASSTHRU = ("      JUMP 0x1c6d4a;                    // DISCRIMINATOR: the stock WaveTone render,\n"
            "                                        // with this call's frame and arguments untouched\n")


def call_bytes(target_sw: int) -> bytes:
    """`CALL target (DB)`, 25a, memory order: the stock call with its 24-bit target."""
    b = bytearray(CALL_STOCK)
    b[2], b[3], b[4], b[5] = (target_sw >> 16) & 0xFF, 0x00, target_sw & 0xFF, (target_sw >> 8) & 0xFF
    return bytes(b)


RB = ("rb-params", "rb-callret", "rb-loads", "rb-setup", "rb-oneread", "rb-noout",
      "rb-setup-a", "rb-setup-a2", "rb-setup-b", "rb-setup-c", "rb-setup-d", "rb-store1")
# the stage markers (`stages`): the reply pages' word 1, both pages
MARK_AT = (0x2C49D4, 0x2C59D4)
# (stage, the source line the marker goes after); the reader's first I0 = R3 is its
# first occurrence. None sits between a flag-setting op and its conditional jump.
STAGES_READER = (
    (3, "wr_render5.:"),
    (4, "      I2 = R0;                          // out"),
    (5, "      DM(6, I4) = R0;                   // frame f0's row"),
    (6, "      R1 = R1 + R8;"),
    (7, "      DM(7, I4) = R1;                   // frame f1's row"),
    (8, "      F11 = FLOAT R3 BY R2;"),
    (9, "      R12 = -16;"),
    (10, "      I0 = R3;"),
    (11, "      R4 = DM(0, I0);                   // frame f0, word w0"),
    (12, "      R7 = DM(0, I0);                   // frame f1, word w1"),
    (13, "      R9 = R9 + R10;                    // phase += inc, mod 2^32"),
    (14, "      DM(I2, M6) = F4;"),
    (15, "      DM(4, I4) = R0;                   // samples left"),
    (16, "wr5_done.:"),
)
# the adapter's: 1 after its saves, 2 before the call, 18 back from the reader, 19 after
# its restores but before I1's (the markers' scratch)
STAGES_ADAPTER = (1, 2, 18, 19)

# rb-setup's span cut again (rb-loads survived on silicon, rb-setup died): each exits
# through the full return (JUMP wr5_done) after the anchor line
SETUP_CUT = {
    "rb-setup-a": "      DM(7, I4) = R1;                   // frame f1's row",
    "rb-setup-b": "      F11 = FLOAT R3 BY R2;",
    "rb-setup-c": "      R12 = -16;",
    "rb-setup-d": "      R3 = R2 + R0;",               # the first tap address, before I0 = R3
}
C018 = "      R1 = R1 + R8;\n"                      # 2c parcel 0xc018, in 0xc000..0xc07f
C018_32 = "      R1 = R8 + R1;                     // DISCRIMINATOR: not 2c-encodable, a 32-bit form\n"
EARLY_RET = ("      I12 = DM(M7, I6);                 // DISCRIMINATOR: return here, the full path's shape\n"
             "      NOP;                              // (the full path stores the phase through I4 here)\n"
             "      JUMP (M14, I12) (DB);\n"
             "      NOP;\n"
             "      RFRAME;\n")
TO_DONE = "      JUMP 0x16eba6;                    // -> wr5_done.  DISCRIMINATOR: early exit\n"


def mark(stage: int) -> str:
    """One stage marker: I1 = 0x5752_00nn, stored to both reply pages' word 1. I1 is
    the adapter's to use (it saves and restores it) and the reader never touches it;
    USTAT1 was the first choice, but selas and digikit disagree on the width of
    `USTAT1 = imm32`, and `DM(abs) = I1` is a form the adapter already makes."""
    return (f"      I1 = {0x57520000 | stage:#x};                  // STAGE {stage}\n"
            + "".join(f"      DM({a:#x}) = I1;\n" for a in MARK_AT))


def insert_after(src: str, anchor: str, text: str) -> str:
    """TEXT after the first line that is exactly ANCHOR (which must exist)."""
    lines = src.splitlines(keepends=True)
    for k, line in enumerate(lines):
        if line.rstrip("\n") == anchor:
            return "".join(lines[:k + 1]) + text + "".join(lines[k + 1:])
    raise SystemExit(f"no line {anchor!r}")


def reader_source(rb: str | None) -> str:
    """reader_m5.asm, cut short for one reader-halving variant (None: the full reader)."""
    src = READER.read_text(encoding="utf-8")
    if rb == "rb-callret":
        return insert_after(src, "wr_render5.:", EARLY_RET)
    if rb == "rb-loads":
        return insert_after(src, "      I2 = R0;                          // out", EARLY_RET)
    if rb == "rb-store1":
        store = EARLY_RET.replace(
            "      NOP;                              // (the full path stores the phase through I4 here)\n",
            "      DM(1, I4) = R9;                   // DISCRIMINATOR: the full path's phase store, alone\n")
        if store == EARLY_RET:
            raise SystemExit("the early return has no phase-store slot")
        return insert_after(src, "      I2 = R0;                          // out", store)
    if rb == "rb-setup":
        return insert_after(src, "      I0 = R3;", TO_DONE)
    if rb == "rb-oneread":
        return insert_after(src, "      R4 = DM(0, I0);                   // frame f0, word w0", TO_DONE)
    if rb == "rb-setup-a2":
        if src.count(C018) != 1:
            raise SystemExit("the c018 add is not one line")
        return insert_after(src.replace(C018, C018_32), SETUP_CUT["rb-setup-a"], TO_DONE)
    if rb == "stages":
        for stage, anchor in STAGES_READER:
            src = insert_after(src, anchor, mark(stage))
        return src
    if rb in SETUP_CUT:
        return insert_after(src, SETUP_CUT[rb], TO_DONE)
    if rb == "rb-noout":
        line = "      DM(I2, M6) = F4;\n"
        if src.count(line) != 1:
            raise SystemExit("the output store is not one line")
        return src.replace(line, "      NOP;                              // DISCRIMINATOR: the output store\n")
    return src


def with_stages(src: str, save: int, par: int) -> str:
    """The adapter with markers 1 (after its saves, I1 among them), 2 (before the call),
    18 (back from the reader) and 19 (restores made, before I1's own)."""
    s1, s2, s18, s19 = STAGES_ADAPTER
    src = insert_after(src, f"      DM({save + 4 * 21:#x}) = I5;", mark(s1))
    line = next(x for x in src.splitlines() if x.startswith(f"      R4 = {par:#x};"))
    src = insert_after(src, line, mark(s2))
    src = insert_after(src, "wr_wt_back.:", mark(s18))
    i1 = f"      I1 = DM({save + 4 * 17:#x});\n"
    if src.count(i1) != 1:
        raise SystemExit("the adapter's I1 restore is not one line")
    return src.replace(i1, mark(s19) + i1)


def adapter(work: pathlib.Path, layout: str = "b1", passthru: bool = False, nocall: bool = False,
            stages: bool = False) -> bytes:
    import sharc_resolve_jumps as rj  # noqa: PLC0415  (WSL + selas)
    rd, ad, save, par, tab = LAYOUT[layout]
    src = SOURCE.read_text(encoding="utf-8")
    for k in range(22):                                          # the save area, 22 words
        src = src.replace(f"DM({0x2DDE00 + 4 * k:#x})", f"DM({save + 4 * k:#x})")
    for k in range(6):                                           # the parameter block
        src = src.replace(f"DM({0x2DDF00 + 4 * k:#x})", f"DM({par + 4 * k:#x})")
    src = src.replace("R4 = 0x2ddf00;", f"R4 = {par:#x};").replace("R8 = 0x2df000;", f"R8 = {tab:#x};")
    src = src.replace("CJUMP 0x16eb00 (DB);", f"CJUMP {rd // 2:#x} (DB);")
    if stages:
        src = with_stages(src, save, par)
    if nocall:
        # rb-params: the parameter block filled, then straight to the restores
        a = src.index("      CJUMP ")
        src = src[:a] + src[src.index(".GLOBAL wr_wt_back.;"):]
    if passthru:
        # keep the saves and the restores; drop the parameter block, the call and the return
        a, b = src.index(f"      R8 = {tab:#x};"), src.index(".GLOBAL wr_wt_back.;")
        src = src[:a] + src[b:]
        a = src.index("      I12 = DM(M7, I6);")
        b = src.index("      RFRAME;\n") + len("      RFRAME;\n")
        src = src[:a] + src[a:b].split("      R0 = DM(")[0] + \
            f"      R0 = DM({save:#x});\n" + PASSTHRU + src[b:]
        src = src.replace("      I12 = DM(M7, I6);                 // the return address - 1, as the firmware's callees\n", "")
    _, be, _ = rj.resolve(src, ad // 2, work)
    return sharc_object.load_bytes(be)


def reader(work: pathlib.Path, layout: str, rb: str | None = None) -> bytes:
    import sharc_resolve_jumps as rj  # noqa: PLC0415
    _, be, _ = rj.resolve(reader_source(rb), LAYOUT[layout][0] // 2, work)
    return sharc_object.load_bytes(be)


def pad(obj: bytes, span: int) -> bytes:
    if len(obj) > span - 64:
        raise SystemExit(f"a code object ({len(obj)} B) does not fit {span:#x} with 64 bytes of NOPs")
    return obj + bytes(span - len(obj))


def finish(stock: bytes, base: bytes, extra: list, target_sw: int) -> bytes:
    for at, payload in extra:                                    # nothing of the stock stream there
        for b in bootstream.walk(stock).blocks:
            if b.count and b.target < at + len(payload) and at < b.target + b.count:
                raise SystemExit(f"{at:#x} overlaps the stock block at {b.target:#x}")
    out = bytearray(bootstream.insert_before_final(
        base, b"".join(bootstream.block(at, payload) for at, payload in extra)))
    if bootstream.read_span(out, dsp.sw_to_load(CALL_SW), 2) != CALL_STOCK[:2]:
        raise SystemExit("sw 0x1c9611 is not a 25a CALL")
    bootstream.write_span(out, dsp.sw_to_load(CALL_SW), call_bytes(target_sw))
    result = bytes(out)
    walked = bootstream.walk(result)
    if not walked.complete or walked.stopped_at != len(result):
        raise SystemExit(f"the result does not walk as a boot stream ({walked.reason})")
    if bootstream.read_span(result, dsp.sw_to_load(dsp.ENTRY_SW), len(dsp.ENTRY_STOCK)) != dsp.ENTRY_STOCK:
        raise SystemExit("the entry at sw 0x1c9448 is not stock")
    if bootstream.read_span(result, dsp.dm_to_load(dsp.LOOKUP_DM), 32) != bootstream.read_span(
            stock, dsp.dm_to_load(dsp.LOOKUP_DM), 32):
        raise SystemExit("the machine lookup is not stock")
    return result


def section7(stock: bytes, obj: bytes) -> bytes:
    """wtplace (and passthru): M5d's block-1 region, OBJ in the loop's span, the CALL to it."""
    if hashlib.sha256(stock).hexdigest() != dsp.STOCK_SHA256:
        raise SystemExit("not stock DN2 1.11 section 7")
    if bootstream.read_span(stock, dsp.sw_to_load(CALL_SW), len(CALL_STOCK)) != CALL_STOCK:
        raise SystemExit("sw 0x1c9611 is not the stock `CALL 0x1c6d4a`")
    if len(obj) > dsp.CODE_SPAN - 64:
        raise SystemExit("the adapter does not fit its span with 64 bytes of padding")
    base = dsp.objects()
    dsp.objects = lambda: {**base, "machine5_live": obj}   # this build only
    try:
        added = dsp.spans()
        dsp._check_free(stock, added)
    finally:
        dsp.objects = lambda: base
    return finish(stock, stock, [(at, payload) for _, at, payload in added], dsp.LOOP_SW)


def variant(stock: bytes, work: pathlib.Path, name: str) -> bytes:
    if name == "wtplace":
        return section7(stock, adapter(work))
    if name == "passthru":
        return section7(stock, adapter(work, passthru=True))
    lay = "b0" if name == "b0code" else "b2"
    rb = name if name in RB + ("stages",) else None
    rd, ad, save, par, tab = LAYOUT[lay]
    # the reader has 0x400 up to b2's adapter; only `stages` (markers) needs more than 0x200,
    # and the other builds keep their bytes
    code = [(dsp.dm_to_load(rd), pad(reader(work, lay, rb), 0x400 if rb == "stages" else 0x200)),
            (dsp.dm_to_load(ad), pad(adapter(work, lay, nocall=rb == "rb-params", stages=rb == "stages"),
                                     0x400 if lay == "b2" else 0x200))]
    if name == "b0code":
        lo, hi = dsp.dm_to_load(B0_FREE[0]), dsp.dm_to_load(B0_FREE[1])
        if not all(lo <= at and at + len(p) <= hi for at, p in code):
            raise SystemExit("the block-0 code leaves the free top of block 0")
        wt = section7(stock, adapter(work))                  # wtplace; its block-1 data stays
        # wtplace's own blocks are already in; add the block-0 code and move the CALL
        out = bytearray(bootstream.insert_before_final(
            wt, b"".join(bootstream.block(at, payload) for at, payload in code)))
        bootstream.write_span(out, dsp.sw_to_load(CALL_SW), call_bytes(ad // 2))
        result = bytes(out)
        walked = bootstream.walk(result)
        if not walked.complete or walked.stopped_at != len(result):
            raise SystemExit(f"the result does not walk as a boot stream ({walked.reason})")
        for at, payload in code:
            for b in bootstream.walk(stock).blocks:
                if b.count and b.target < at + len(payload) and at < b.target + b.count:
                    raise SystemExit(f"{at:#x} overlaps the stock block at {b.target:#x}")
        return result
    t0 = reference.dsp_bytes(dsp.tables()[0])
    extra = code + [(dsp.dm_to_load(save), bytes(0x100)), (dsp.dm_to_load(par), bytes(0x100)),
                    (dsp.dm_to_load(tab), t0)]
    return finish(stock, stock, extra, ad // 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--m5b", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--stock", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--variant", choices=("wtplace", "b0code", "passthru", "b2", "stages") + RB, default="wtplace")
    ap.add_argument("--s7-only", type=pathlib.Path, help="write section 7 here and stop (runner checks)")
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit(f"{a.out} exists: never overwrite a build")
    import sharc_waverider_render as m1  # noqa: PLC0415
    from dnfw.cli.main import main as dnfw  # noqa: PLC0415
    stock = m1.dn2_section7(a.stock)
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        s7 = variant(stock, work, a.variant)
        print(f"section 7 ({a.variant}): {len(s7)} bytes, sha256 {hashlib.sha256(s7).hexdigest()}")
        if a.s7_only:
            a.s7_only.write_bytes(s7)
            return 0
        p = work / "s7.bin"
        p.write_bytes(s7)
        return dnfw(["build", "-o", str(a.out), "-s", f"7={p}", str(a.m5b)]) or 0


if __name__ == "__main__":
    raise SystemExit(main())
