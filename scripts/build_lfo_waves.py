"""Every new LFO waveform in one firmware: STEP PULS NOIS TRAP + WTB1 WTB2 WTB3.

    python scripts/build_lfo_waves.py

The owner, 2026-09-17: *"make a firmware with everything combined"*, and asked
whether a separate section called from the small caves would save space. It does,
and this is that design.

## Why the pieces moved out of the caves

`lfo-waveshapes11` and `lfo-wavetables` each fill the two clean 896-byte caves
(`docs/memory-map.md`), so together they cannot fit there. A new ELE3 section is
no help by itself: the bootloader does not place a section at its `dest`
(`docs/ideas-backlog.md` §6), so something must copy it anyway.

What works, and is proven on the instrument by `intro-bang`: **append the bytes
past the end of MAIN OS, and have the startup code copy them above BSS before the
BSS clear.** So:

- **One cave holds only the boot copy stub** (about 50 bytes).
- **Everything else -- all generators, hooks, formatters, glyph and label code,
  names, relocated tables, the three wavetables, glyph sets -- is one blob,
  assembled at its runtime address** `0x46780000` and appended to MAIN OS with a
  `LFOW` magic and its length.
- The in-image edits (hooks, repoints, clamps, vtable slots) point into RAM, and
  run only after the copy -- the copy happens in the startup calls, before `main`.

The runtime address is chosen clear of the other tenants: lfo4-tick6a
`0x46700000`, the boot-screen area `0x46710000`, NOI state `0x46740000`, glyph
tiles `0x46750000`. It shares the startup hook site with the boot-screen mod, so
the two are still alternatives until a shared area registry exists.
"""

from __future__ import annotations

import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw.cli.files import read_image
from dnfw.container.section import compress
from dnfw.firmware import build as fwbuild
from dnfw.firmware.load import load
from dnfw.patch.assemble import assemble, available

import build_lfo_waveshapes as shapes
import lfo_wave_glyph as glyph
import lfo_wave_ui as ui
import wavetables as wt

MAIN_OS = 3
BASE = 0x40000400
AREA_VA = 0x4030B980            # the end of stock MAIN OS: where the blob is appended
RUNTIME_VA = 0x46780000         # where the boot stub copies it
MAGIC = b"LFOW"
BOOT_CAVE, BOOT_CAVE_CAP = 0x402CF52C, 896

INIT_VA, CLEAR_VA = 0x4000045C, 0x400004B2
CALLS_VA = 0x4000053E
CALLS_STOCK = bytes.fromhex("4ebaff1c4ebaff6e")          # jsr init ; jsr clear

STOCK_ENTRIES = 7
SHAPES = [(b"STP", b"STEP", "step", "STPS"), (b"PLS", b"PULS", "pulse", "WDTH"),
          (b"NOI", b"NOIS", "noise", "TYPE"), (b"TRP", b"TRAP", "trap", "SLOP")]
TABLES = [(short.encode(), long.encode(), g, "POS")
          for (long, short, _), g in zip(wt.TABLES, ("wt1", "wt2", "wt3"))]
WAVES = SHAPES + TABLES
ENTRIES = STOCK_ENTRIES + len(WAVES)

LABELS = ("step", "pulse", "noise", "trap", "a_call", "b_call", "no_phase", "fmt_v92") \
    + ui.LABELS + ("wt1", "wt2", "wt3") + glyph.LABELS

OUT = pathlib.Path("00_Resources/02_Builds/lfo-waves_DN2_1.11.syx")


def boot_source() -> str:
    return f"""
    .text
| ---- boot: .data init, copy the appended wave blob above BSS, clear BSS ----
boot:
    jsr     {INIT_VA:#010x}
    lea     {AREA_VA:#010x},%a0
    move.l  %a0@,%d0
    cmpi.l  #{int.from_bytes(MAGIC, 'big'):#010x},%d0
    bne.s   2f                      | nothing appended: boot as stock
    lea     {RUNTIME_VA:#010x},%a1
    move.l  %a0@(4),%d0             | total length, header included
1:  move.b  %a0@+,%a1@+
    subq.l  #1,%d0
    bne.s   1b
2:  jsr     {CLEAR_VA:#010x}
    rts
"""


def main() -> int:
    if not available():
        raise SystemExit("no m68k assembler found (m68k-linux-gnu-as, WSL is fine)")

    firmware = load(read_image(pathlib.Path(shapes.STOCK)))
    section = firmware.container.find(MAIN_OS)
    stock = section.unpack()
    if BASE + len(stock) != AREA_VA:
        raise SystemExit("MAIN OS is not stock 1.11's length")
    content = bytearray(stock)

    # ---- the blob's data, laid out from RUNTIME_VA + 8 (after magic and length)
    data = bytearray()
    at = lambda: RUNTIME_VA + 8 + len(data)

    def put(b: bytes, align: int = 1) -> int:
        while len(data) % align:
            data.append(0)
        va = at()
        data.extend(b)
        return va

    short_vas = [put(s + b"\x00") for s, _, _, _ in WAVES]
    long_vas = [put(l + b"\x00") for _, l, _, _ in WAVES]
    never_va = put(shapes.NEVER_FMT)
    table_vas = [put(wt.table_bytes(make())) for _, _, make in wt.TABLES]
    glyph_va = put(b"", 4)
    glyph_bytes, glyph_sets, label_table = glyph.blob(glyph_va, [w[3] for w in WAVES])
    put(glyph_bytes)
    names_va = put(bytes(4 * ENTRIES), 4)
    long_names_va = put(bytes(4 * ENTRIES), 4)
    fn_vas = {old: put(bytes(4 * ENTRIES), 4) for old in shapes.STOCK_TABLES}
    code_va = put(b"", 4)

    # ---- the blob's code, assembled at its runtime address
    shapes.ENTRIES = ENTRIES          # the formatter bound and the no-phase test read it
    text = (shapes.source(fn_vas[0x4020B340], 0, names_va, long_names_va, never_va, 0, 0)
            + wt.generator_source(table_vas)
            + glyph.source(glyph_sets, fn_vas[0x4020B340], len(WAVES), label_table,
                           state_reset=shapes.NOISE_RAM + 8 * glyph.NOISE_GLYPH_KEY))
    code, offsets = shapes.assemble_stubs(text, code_va, LABELS)
    data.extend(code)
    while len(data) % 4:
        data.append(0)

    # the tables the blob relocates, now that the generator addresses are known
    def fill(va: int, values: list[int]) -> None:
        off = va - RUNTIME_VA - 8
        data[off:off + 4 * len(values)] = b"".join(struct.pack(">I", v) for v in values)

    fill(names_va, shapes.read_longs(content, ui.SHORT_NAMES, STOCK_ENTRIES) + short_vas)
    fill(long_names_va, shapes.read_longs(content, ui.LONG_NAMES, STOCK_ENTRIES) + long_vas)
    for old in shapes.STOCK_TABLES:
        extra = [offsets[w[2]] for w in WAVES] if old == 0x4020B340 else [0] * len(WAVES)
        fill(fn_vas[old], shapes.read_longs(content, old, STOCK_ENTRIES) + extra)

    blob = MAGIC + struct.pack(">I", 8 + len(data)) + bytes(data)
    print(f"blob: {len(blob):,} bytes, appended at {AREA_VA:#010x}, runs at {RUNTIME_VA:#010x}")
    print(f"  code {len(code)} B at {code_va:#010x}; tables {', '.join(f'{v:#010x}' for v in table_vas)}")
    for label in LABELS:
        print(f"  {label:<10} {offsets[label]:#010x}")

    # ---- the one thing in a cave: the boot copy stub
    shapes.require_zero(content, BOOT_CAVE, BOOT_CAVE_CAP, "boot cave")
    boot = assemble(boot_source(), base=BOOT_CAVE)
    shapes.write(content, BOOT_CAVE, boot)
    print(f"boot stub {len(boot)} B at {BOOT_CAVE:#010x}")

    # ---- the edits in the image, all pointing into RAM
    be = lambda v: struct.pack(">I", v)
    poke = shapes.poke
    poke(content, CALLS_VA, CALLS_STOCK, b"\x4e\xb9" + be(BOOT_CAVE) + b"\x4e\x71",
         "startup calls -> boot copy stub")
    for old, sites in shapes.REPOINTS.items():
        for va, prefix in sites:
            poke(content, va, prefix + be(old), prefix + be(fn_vas[old]), f"{old:#010x} -> RAM")
    for va, stock_bytes, label in shapes.HOOKS:
        poke(content, va, stock_bytes, b"\x4e\xf9" + be(offsets[label]), f"jmp -> {label}")
    for va in (shapes.SOUND_SET_V92, shapes.MIDI_SET_V92):
        poke(content, va, be(shapes.STOCK_V92), be(offsets["fmt_v92"]), "vtable slot 92 -> fmt_v92")
    for va, stock_bytes, new, why in (glyph.clamp_edits(ENTRIES - 1) + glyph.hooks(offsets)
                                      + ui.clamp_edits(ENTRIES - 1)):
        poke(content, va, stock_bytes, new, why)
    for va in shapes.WAVE_MAX_FIELDS:
        poke(content, va, be(shapes.STOCK_WAVE_MAX << 8), be((ENTRIES - 1) << 8), "LFO Waveform max")

    content += blob
    while len(content) % 4:
        content.append(0)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    replacement = compress(section.id, section.dest, bytes(content))
    OUT.write_bytes(fwbuild.build(firmware, {MAIN_OS: replacement}))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes); MAIN OS {len(content):,} B "
          f"(+{len(content) - len(stock):,}); cave {len(boot)}/{BOOT_CAVE_CAP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
