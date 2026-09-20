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

**So the +512 is whatever the 13 → 14 converter writes between the old trailer
offset and the new one.** Reading that converter's callees would name the block;
not done here.

## A correlation worth keeping

The four-digit number a project declares as its format version matches the
**ELE3 build string** of the firmware that wrote it: DN1 1.43 is `0104` and DN2
1.11 is `0059` (`docs/ele3-format.md`). So that field looks like the build
number rather than an independent format counter. Two points is not a rule;
recorded as a lead for DNX to confirm against 1.42A, which we do not have here.
