"""The Digitakt II 1.16 ONESHOT voice render, transplanted into Digitone II 1.11.

Measured in `docs/dt2-machine-port.md`, "The experiment, run". The reach set of
the render entry `sw 0x1c4ecf` is four functions, 611 instructions, closed
under calls (digikit's `sharcdb` edges, 2026-09-26):

| donor sw | instrs | what it does |
|---|---|---|
| `0x1c4ecf` | 84 | entry: save registers; zero-fill the output when the record's sample pointer (word 0) or ACTIVE (+0x1b8) is 0; restore |
| `0x1c4f81` | 381 | the reader: 64 points at 96 kHz, 6-tap 256-phase polyphase interpolation of int16 PCM, forward or reverse, loop or one-shot, declick ramps; then calls the decimator |
| `0x1c06ba` | 47 | a float reciprocal/divide helper (used by the declick ramps) |
| `0xb80000` | 99 | a 2:1 decimating filter (64 -> 32 floats), state in the record at +0x104 |

`0x1c4ecf` and `0x1c4f81` are one routine that digikit's function finder
split in two (0x1c4ecf jumps into 0x1c4f81, which jumps back to its epilogue),
so they move as one span. The data the reach set reads at absolute addresses:
the polyphase coefficient table (256 rows of six Q31 words, 6,144 bytes) and
the decimator's four coefficients (16 bytes). Everything else it touches is
relative to the record pointer R4, the output pointer R8 or the stack.

**Nothing below is a donor byte.** Each span is named by address, size and the
SHA-256 of what the user's own DT2 1.16 file loads there; the bytes are read
from that file when the transplant is applied.
"""

from __future__ import annotations

from .spec import Guard, Site, Span, Spec

DONOR = Guard(device="Digitakt II", product=43, version="1.16",
              section7_sha256="0f514a12a2255f5c081e292c47f1f29462003177658da4bbae0a22fd737fffa2")
RECIPIENT = Guard(device="Digitone II", product=52, version="1.11",
                  section7_sha256="336e340aa0cdcd34e314cfa44849f709a3134f6bd4cd57dfc7e15702c83115e2")

# Where the pieces land in the DN2. Every recipient byte is one the DN2 1.11
# boot stream never loads (checked by `plan.build`); unloaded is not the same
# as unused at run time, which is recorded as open in the doc. All of it is in
# L1 block 2, above Waverider M5's spans (0x300000..0x30a000): the first
# placement (sw 0x180800, DM 0x294000) was in the gap between L1 blocks 0 and 1,
# which is not memory on the part (`docs/waverider-m5-dsp.md`, correction 1).
RENDER_SW = 0x185000                    # PM byte 0x30a000, L1 block 2 (above Waverider M5)
DIVIDE_SW = 0x185480
DECIMATOR_SW = 0x185500
COEFF_DM = 0x30C400
DECCOEF_DM = 0x30DC00

SPANS = (
    Span("render", "code", 0x1C4ECF, 0x465,
         "2ad7cf6f5fbc9ea55c39e306bfd7530e8547bcec0db46ff56c7511f2fa0f4cb3", RENDER_SW,
         "FUN_1c4ecf + FUN_1c4f81: the voice render (entry, reader, declick)"),
    Span("divide", "code", 0x1C06BA, 0x6F,
         "89d5bd86bf1d21e98f21793c0ab238910f641690dac4a700a3f3fa13a08fb079", DIVIDE_SW,
         "FUN_1c06ba: float reciprocal/divide helper"),
    Span("decimator", "code", 0xB80000, 0x105,
         "322352d30d2abbe4d74a82288e9590a47d90512758339a7d15c96d6299cbd794", DECIMATOR_SW,
         "FUN_b80000: 2:1 decimating filter (L2 code in the donor)", window="l2"),
    Span("coeff", "data", 0x25D940, 0x1800,
         "f2360d0915d144341126e28248ce6e4a4aa79be2f930c4247f8782fc36bb4dab", COEFF_DM,
         "polyphase coefficients: 256 rows x 6 Q31 words"),
    Span("deccoef", "data", 0x26EF88, 0x10,
         "1057fcc83637caa711a027355ef12fe2cff00937e20c0d4df0b858a71033d093", DECCOEF_DM,
         "the decimator's four float coefficients"),
)

SITES = (
    Site("render", 0x1C50AA, "17a", "data32", 0x25D940, "coeff", "I5 = &coeff (forward loop)"),
    Site("render", 0x1C52BF, "17a", "data32", 0x25D940, "coeff", "I1 = &coeff (reverse loop)"),
    Site("render", 0x1C5193, "8a_rel", "rel24", 0x1C06BA, "divide", "CALL divide (fade-in ramp)"),
    Site("render", 0x1C51F8, "8a_rel", "rel24", 0x1C06BA, "divide", "CALL divide (fade-out ramp)"),
    Site("render", 0x1C525D, "25a_direct", "addr24", 0xB80000, "decimator", "CALL decimator"),
    Site("render", 0x1C5261, "16a", "data32", 0x1C5263, "render",
         "the pushed return address - 1 of that call"),
    Site("decimator", 0xB80031, "14a", "addr32", 0x26EF94, "deccoef", "R5 = DM(coef + 12)"),
    Site("decimator", 0xB80034, "14a", "addr32", 0x26EF90, "deccoef", "R4 = DM(coef + 8)"),
    Site("decimator", 0xB8003D, "14a", "addr32", 0x26EF8C, "deccoef", "R6 = DM(coef + 4)"),
    Site("decimator", 0xB80046, "14a", "addr32", 0x26EF88, "deccoef", "R7 = DM(coef + 0)"),
)

SPEC = Spec(
    name="dt2-1.16-oneshot-render -> dn2-1.11",
    donor=DONOR, recipient=RECIPIENT, spans=SPANS, sites=SITES, entry="render",
    notes=(
        "Every other transfer in the three code spans is PC-relative and stays inside its span "
        "(checked against digikit's decoder by scripts/sharc_oneshot_port.py, step 1).",
        "The render's call convention (from the donor's caller at 0x1c6afd): R4 = the voice record "
        "(0x1d8 bytes), R8 = the output (32 floats), R12 = the block size (32); a CJUMP-style linked "
        "call with the I6/I7 frame, as DN2 code uses.",
    ),
)
