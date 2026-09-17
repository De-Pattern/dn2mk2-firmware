"""What a new LFO waveform needs beyond its generator: the two clamps and the two names.

Shared by `build_lfo_waveshapes.py` and `build_lfo_wavetable.py`. The first
`lfo-waveshapes` build failed on hardware on 2026-09-17 for exactly the two
reasons this module exists:

*"There is 3 new options at the end of the shape list but is listed as ERR. It
seems to sound similar to a random wave"*

## 1. Both evaluators clamp WAVE to 6 before dispatching

```
A 0x40137876  mvs.b %a4@(76),%d3      B 0x40137494  mvs.b %a4@(42),%d3
  0x40137880  moveq #6,%d7              0x401374a8  moveq #6,%d6
  0x40137882  cmp.l %d3,%d7             0x401374aa  cmp.l %d3,%d6
  0x40137884  bge.s +2                  0x401374ac  bge.s +2
  0x40137886  moveq #6,%d3              0x401374ae  moveq #6,%d3
```

So every index above 6 ran as **RND**, the one waveform dispatched by value
rather than through the function table. That is what the owner heard. The
scratch register is reloaded straight after in both (`moveq #11,%d7` at
`0x4013788c`; `move.l %a0,%d6` at `0x401374b6`), so raising both immediates is
the whole fix.

## 2. The value text comes from two formatters with their own bound and table

The `Waveform` records' formatter (`+0x28` of records `0x401f91e4`, `...943c`,
`...9694`) is `0x400e34ac`; a short-name twin is `0x4000766c` (via
`0x401d176c`, `0x401d1988`). Both are:

```
link  %fp,#-28
moveq #6,%d0 ; cmp.l value>>8 ; bcs.s -> sprintf(dest, "ERR")
copy 28 bytes (7 name pointers) from a table to the frame, sprintf(dest, "%s", name[i])
```

The earlier build repointed the short table's `pea` and nothing else, so the
bound still said 6 and the page said `ERR`. The names the page shows are the
long table at `0x401fd5c0` (`TRI SINE SQR SAW EXPO RAMP RAND`).

Rather than grow two stack frames, both functions are replaced at entry by a
frameless stub with the same contract: `(value, dest)` in, `sprintf` tail.

## Not fixed here

The `[MOD]` page's waveform glyph still draws `RND` for new indices; its renderer
is not read.
"""

from __future__ import annotations

SPRINTF = 0x40000E82
PCT_S = 0x40219C2D          # "%s"
ERR = 0x40210C9E            # "ERR"

SHORT_FMT = 0x4000766C
LONG_FMT = 0x400E34AC
FMT_ENTRY_STOCK = bytes.fromhex("4e56ffe47006")   # link %fp,#-28 ; moveq #6,%d0

SHORT_NAMES = 0x401D3574    # TRI SIN SQR SAW EXP RMP RND
LONG_NAMES = 0x401FD5C0     # TRI SINE SQR SAW EXPO RAMP RAND
STOCK_ENTRIES = 7

# (address, stock opcode byte) of each `moveq #6` in the two clamps.
CLAMPS = (
    (0x40137880, 0x7E), (0x40137886, 0x76),   # evaluator A
    (0x401374A8, 0x7C), (0x401374AE, 0x76),   # evaluator B
)

LABELS = ("fmt_short", "fmt_long")


def clamp_edits(max_index: int) -> list[tuple[int, bytes, bytes, str]]:
    """(va, stock, new, why) for the four clamp immediates."""
    if not 6 < max_index <= 127:
        raise ValueError(f"max index {max_index} is not a moveq immediate above 6")
    return [(va, bytes([op, 6]), bytes([op, max_index]), f"WAVE clamp 6 -> {max_index}")
            for va, op in CLAMPS]


def formatter_source(max_index: int, short_table: int, long_table: int) -> str:
    """Two frameless formatters. Entered by `jmp` at the stock entry, so
    `%sp@(4)` is the value and `%sp@(8)` the destination buffer."""
    return f"""
| ---- WAVE value text: the stock contract, a larger bound and table -----
fmt_short:
    lea     {short_table:#010x},%a0
    bra.s   1f
fmt_long:
    lea     {long_table:#010x},%a0
1:  move.l  %sp@(4),%d0
    asr.l   #8,%d0
    cmpi.l  #{max_index},%d0
    bhi.s   2f                      | unsigned, as the stock bcs.s
    move.l  %a0@(0,%d0:l:4),%sp@-   | name
    pea     {PCT_S:#010x}           | "%s"
    move.l  %sp@(16),%sp@-          | dest, past the two pushes
    jsr     {SPRINTF:#010x}
    lea     %sp@(12),%sp
    rts
2:  move.l  %sp@(8),%d0             | the stock ERR tail: sprintf(dest, "ERR")
    move.l  %d0,%sp@(4)
    move.l  #{ERR:#010x},%d0          | ColdFire: no #imm32 to a displacement
    move.l  %d0,%sp@(8)
    jmp     {SPRINTF:#010x}
"""
