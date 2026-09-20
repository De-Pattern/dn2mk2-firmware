# Digitone 1: how a project payload grows across OS versions

**2026-09-20.** Read from the DN1 OS 1.43 image (`Digitone_and_Digitone_Keys_OS1.43_dist.zip`,
MAIN OS at `0x40000400`) after the DNX session found 1.43 projects declaring
**2,782,212** bytes where DNX expected **2,781,700** -- the same +512 the DN2 saw
at OS 1.11. Static reading; nothing was run, and no project was parsed here.
DNX owns the project format; this is the firmware's side of it.

## The loader is a migration ladder

`0x40010a70` walks a project up one version at a time. The rung is a **version
index** in `d3` -- 11, 12, 13, then the final form -- not the four-digit number a
project carries. Each rung converts, then validates the result against **that
rung's** payload size with `0x400fb864(obj, ptr, size)`:

| rung | converter | validated against |
|---|---|---|
| 11 → 12 | `0x40147d42` | 2,781,700 |
| 12 → 13 | `0x40147d96` | 2,781,700 |
| 13 → 14 | `0x40147dea` | 2,781,700 at the rung, then **2,782,212** at `0x40010c4e` |

Both sizes are in the image -- 2,781,700 at 6 sites, 2,782,212 at 14 -- so 1.43
still reads the older layout rather than rejecting it.

## The final object, and the framing check

`0x40147dea` builds the version-14 object: it allocates **2,782,228** bytes
(a 16-byte header plus the 2,782,212 payload), stores vtable `0x4019097c`, puts
the data pointer at `+16`, and zero-fills the payload (`0x400fb8ac`). The
field-by-field moves are in the converter's own body, not in the ladder.

Immediately after, `0x40010c70` checks the payload's framing: magic
**`0xBEEFBACE`** at offset 0 and **`0xBACEF00C`** at offset **2,782,208**
(size − 4). So a payload is `BEEFBACE` … `BACEF00C`, and what moved by 512 is
the trailer's offset -- on the older layout it sat at 2,781,696.

## Where the 512 bytes go: the middle, not the end

The ladder calls the **content** converter `0x4000db48` right after the
constructor, and that one shows it. With `a2` the old payload and `a3` the new:

| step | old -> new |
|---|---|
| header | `+8` (16 B), `+24`; then 484 B zeroed at `+28` |
| `0x4800` blocks from `+512` | same offsets, to `0x240000` |
| `0xA00` blocks from `0x240200` | same offsets, to `0x50000` |
| 38,912 B at `0x290200` | same offset |
| `0x299A00` | same offset, through the element-wise `0x4000cbc4` (extent not read) |
| **`0x29C800`, 0xA00 B** | **-> `0x29CA00`: +512** |
| **`0x29D200` + d2, 0xA00 blocks, d2 < 0xA000** | **-> `0x29D400` + d2: +512** |
| trailer at `2,781,696` | -> `2,782,208`; version 14 written at `+4` |

So everything below **`0x29C800` (2,738,176)** keeps its offset, a 512-byte hole
opens there -- left as the constructor's zero fill, this converter writes nothing
into it -- and the 43,520 bytes from `0x29C800` onward, plus the trailer, move by
512. A reader's offsets hold only up to `0x29C800`, not up to the old trailer.

It also validates the old payload first: version 13 at `+4`, `0xBEEFBACE` at 0,
`0xBACEF00C` at `2,781,696` -- which is where the old trailer sat, confirmed by
the firmware rather than inferred.

**Not established:** what fills those 512 bytes (this converter leaves them zero,
so something later writes them -- 1.43's own features are the obvious candidates)
and the exact extent of the element-wise region at `0x299A00`.

## A correlation worth keeping

The four-digit number a project declares as its format version matches the
**ELE3 build string** of the firmware that wrote it: DN1 1.43 is `0104` and DN2
1.11 is `0059` (`docs/ele3-format.md`). So that field looks like the build
number rather than an independent format counter. Two points is not a rule;
recorded as a lead for DNX to confirm against 1.42A, which we do not have here.
