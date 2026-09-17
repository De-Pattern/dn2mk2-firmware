"""Three LFO wavetables, generated from maths: basic shapes, a harmonic sweep, vowels.

The owner, 2026-09-17: *"a wavetable option should be richer in the transition
between waves ... some mythical and loved wavetable to sweep across"*, and chose
three tables over one. Each is **our own maths** -- no ROM data from any other
instrument -- inspired by the classic ideas:

- **WTB1, basic shapes:** sine -> triangle -> saw -> square -> ever narrower pulse,
  the morph soft synths ship as their default table.
- **WTB2, harmonic sweep:** a sine that gains harmonics frame by frame, the PPG
  Wave's signature brightening sweep, rebuilt additively.
- **WTB3, vowels:** A E I O U and back, two formant bumps per vowel placed on
  harmonics of the fundamental.

## Why 7 frames of 32 signed bytes

The clean caves hold 896 bytes each (`docs/memory-map.md`). Three tables of
7 x 32 bytes are 672, which leaves room for the glyph sets and labels in the same
cave. The generator **interpolates bilinearly** -- across the 32 samples along the
phase, and between two frames along SPH -- so an LFO never hears a step between
samples or a jump between frames. 32 points a cycle is plenty for an LFO; the
only visible cost is that a square's edges become 1/32-cycle ramps.
"""

from __future__ import annotations

import math

FRAMES = 7
SAMPLES = 32
PEAK = 127


def _normalise(values: list[float]) -> list[int]:
    peak = max(abs(v) for v in values) or 1.0
    return [max(-PEAK, min(PEAK, int(round(v / peak * PEAK)))) for v in values]


def _frame(f) -> list[int]:
    return _normalise([f(i / SAMPLES) for i in range(SAMPLES)])


def basic_shapes() -> list[list[int]]:
    def pulse(duty):
        return lambda x: 1.0 if x < duty else -1.0
    return [
        _frame(lambda x: math.sin(2 * math.pi * x)),
        _frame(lambda x: 1 - 4 * abs(x - 0.25) if x < 0.75 else 4 * x - 4),   # triangle
        _frame(lambda x: 2 * x - 1),                                          # rising saw
        _frame(pulse(0.5)),
        _frame(pulse(0.25)),
        _frame(pulse(0.125)),
        _frame(pulse(0.0625)),
    ]


def harmonic_sweep() -> list[list[int]]:
    counts = [1, 2, 3, 5, 8, 11, 15]           # 15: the most 32 samples can hold
    return [_frame(lambda x, n=n: sum(math.sin(2 * math.pi * k * x) / k for k in range(1, n + 1)))
            for n in counts]


# (F1, F2) in harmonics of the fundamental, approximating a ~110 Hz voice and
# capped at the 15th harmonic.
VOWELS = {"A": (7, 11), "E": (4, 15), "I": (3, 15), "O": (4, 8), "U": (3, 6)}


def vowel_sweep() -> list[list[int]]:
    def vowel(f1, f2):
        def amp(k):
            return (0.7 * (k == 1)
                    + math.exp(-((k - f1) / 1.2) ** 2)
                    + 0.6 * math.exp(-((k - f2) / 1.5) ** 2))
        return lambda x: sum(amp(k) * math.cos(2 * math.pi * k * x) for k in range(1, 16))
    return [_frame(vowel(*VOWELS[v])) for v in "AEIOUIE"]


TABLES = [("WTB1", "WT1", basic_shapes), ("WTB2", "WT2", harmonic_sweep), ("WTB3", "WT3", vowel_sweep)]


def table_bytes(frames: list[list[int]]) -> bytes:
    assert len(frames) == FRAMES and all(len(f) == SAMPLES for f in frames)
    return bytes((v & 0xFF) for frame in frames for v in frame)


def reference(frames: list[list[int]], phase: int, sph: int) -> int:
    """The generator's arithmetic in Python, for checking the assembly bit for bit."""
    pos = min((sph & 0x7F) * 49, (FRAMES - 1) * 1024)
    f, ff = pos >> 10, pos & 1023
    if f == FRAMES - 1:
        f, ff = FRAMES - 2, 1024
    s, sf = phase >> 27, (phase >> 17) & 1023
    s1 = (s + 1) & 31

    def row(fr):
        a, b = frames[fr][s], frames[fr][s1]
        return a * 1024 + (b - a) * sf
    ab, cd = row(f), row(f + 1)
    out = (ab * 1024 + (cd - ab) * ff) << 4
    out &= 0xFFFFFFFF
    return out - (1 << 32) if out & 0x80000000 else out


def generator_source(tables: list[int]) -> str:
    """The three generators, labels wt1..wt3; `tables` are the tables' addresses."""
    last = (FRAMES - 1) * 1024
    return f"""
| ---- WTB1..3: bilinear through 7 frames x 32 samples, SPH = position -----
wt1:
    lea     {tables[0]:#010x},%a0
    bra.s   10f
wt2:
    lea     {tables[1]:#010x},%a0
    bra.s   10f
wt3:
    lea     {tables[2]:#010x},%a0
10: lea     %sp@(-24),%sp
    moveml  %d2-%d7,%sp@
    move.l  %sp@(28),%d7            | the phase
    andi.l  #0x7f,%d1
    move.l  %d1,%d6
    lsl.l   #6,%d6                  | *64
    move.l  %d1,%d0
    lsl.l   #4,%d0                  | *16
    sub.l   %d0,%d6                 | *48
    add.l   %d1,%d6                 | *49: position, 10-bit frames
    cmpi.l  #{last},%d6
    ble.s   11f
    move.l  #{last},%d6
11: move.l  %d6,%d5
    moveq   #10,%d0
    lsr.l   %d0,%d5                 | frame
    andi.l  #1023,%d6               | between frames
    cmpi.l  #{FRAMES - 1},%d5
    bne.s   12f
    moveq   #{FRAMES - 2},%d5
    move.l  #1024,%d6
12: move.l  %d7,%d4
    moveq   #27,%d0
    lsr.l   %d0,%d4                 | sample 0..31
    moveq   #17,%d0
    lsr.l   %d0,%d7
    andi.l  #1023,%d7               | between samples
    move.l  %d4,%d3
    addq.l  #1,%d3
    andi.l  #31,%d3                 | the next sample, wrapping
    move.l  %d5,%d2
    lsl.l   #5,%d2                  | row offset
    bsr     20f                     | row(f) -> %d0
    movea.l %d0,%a1
    addi.l  #{SAMPLES},%d2
    bsr     20f                     | row(f+1) -> %d0
    move.l  %a1,%d1
    sub.l   %d1,%d0
    muls.l  %d6,%d0                 | (row(f+1) - row(f)) * ff
    asl.l   #8,%d1
    asl.l   #2,%d1                  | row(f) * 1024
    add.l   %d1,%d0
    asl.l   #4,%d0
    moveml  %sp@,%d2-%d7
    lea     %sp@(24),%sp
    rts

| row: %a0 table, %d2 row offset, %d4/%d3 samples, %d7 sf -> %d0. Clobbers %d1.
20: move.l  %d2,%d0
    add.l   %d4,%d0
    mvs.b   %a0@(0,%d0:l),%d0       | a
    move.l  %d2,%d1
    add.l   %d3,%d1
    mvs.b   %a0@(0,%d1:l),%d1       | b
    sub.l   %d0,%d1
    muls.l  %d7,%d1
    asl.l   #8,%d0
    asl.l   #2,%d0
    add.l   %d1,%d0
    rts

"""
