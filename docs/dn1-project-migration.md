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

## The layout the converter's loops imply (old-file offsets)

| range | shape | moved? |
|---|---|---|
| `0x200` .. `0x240200` | 128 blocks of 18,432 B | no |
| `0x240200` .. `0x290200` | 128 blocks of 2,560 B | no |
| `0x290200` .. `0x299A00` | one block of 38,912 B | no |
| `0x299A00` .. `0x29C800` | 11,776 B, copied **element-wise** through `0x4000cbc4` | no, but rewritten per item |
| `0x29C800` .. `0x2A7200` | 1 + 16 objects of 2,560 B (43,520 B) | **+512** |
| `0x2A7200` | the old trailer | -> `0x2A7400` |

`0x2A7200` is exactly the old trailer offset, which is the check that the loops
were read correctly. The 512-byte hole opens at new `0x29C800`, immediately
before that 17-object tail. The element-wise region is the one to watch for a
*content* change at an unchanged offset.

## The DN2 does the same thing

Digitone II 1.11 (`out/main111.bin`) has the same ladder -- rungs validating
against the old payload size **12,889,604** (`0x400e27a2`, `0x400e284a`,
`0x400e28ea`, `0x400e298a`) and a final rung against **12,890,116**
(`0x400e2a2a`); constructors at `0x401b01ce`.. and `0x401b5a10`.

It also transfers a stored slot with a **fixed** length: `0x4012dae0` checks
slot < 128, resolves the slot (`0x4012d7c2`) and passes the hardcoded
12,890,116 to `0x4012d0b4` (at `0x4012db28`), which adds 122,928 to its first
argument and then moves the bytes in chunks of at most 65,536 through
`0x4012c59a`, advancing the LBA by chunk / 512. **Read versus write inside
`0x4012c59a` was not separated here**; the fixed length holds either way.

So a project written before 1.11 and read on 1.11 carries 512 bytes of slack
after its real payload, exactly as DNX measured on the DN1. A reader should
find the trailer rather than trust the declared length; both candidate offsets
fall inside the fixed-length transfer, so one code path serves both versions on
either instrument.

## What the 512 bytes are: the Outbox 8 CV configuration

The element-wise region at `0x299A00` is the **tail settings** object, and
`0x4000cbc4` is its converter: it accepts version **7** only, copies `0x3000`
bytes, initialises a new field at settings + **11,766** (`0x2DF6`) and stamps
version **8**.

- `0x40015b44` zero-fills **304** bytes (`0x130`), then loops **8 times with a
  22-byte stride**, writing a small header and per-item bytes; it also fills 8
  pairs of longs at `+0x28`/`+0x2c` through the ratio helper `0x40136ff8`.
- `0x40015cb2` zeroes those 64 bytes (8 x 8) by itself.
- The object is copied elsewhere as `0x130` bytes (`0x40015cd2`), so 304 of the
  512 are used.

The firmware names it: RTTI `BreakOutBoxSettingsCvConfigCopy` and
`BOB::bobConfigStorage_v0_t`, the view `BreakOutBoxEditMenuView`, and strings
`OUTBOX 8 CONNECTED`, `OUTBOX 8 STEREO OUT %d/%d`, `CV OUT %d`,
`COPY / PASTE / CLEAR CV CONFIG`. The editor's items are `CV ZERO LEVEL`,
`CV MAX LEVEL`, `INVERT POLARITY`, `SEND MIDI`, `SUSTAIN`, `SOSTENUTO`,
`EXPRESSION LEARN`, `REVERSE DIRECTION`, `PORT A`, `PORT B`, formatted `%d.%03d`.

**So the eight records are the eight CV outputs, not eight tracks.** The DNX
session measured the saved defaults on the instrument (one 22-byte record per
output, then 8 x `3FFF`): `0x1388` = 5000 and `0x3E8` = 1000 read as 5.000 and
1.000 in that three-decimal format, and `0x3C`/`0x48` are notes 60 and 72.
`0x4663` is unaccounted for. The type is already `_v0_t`, so expect it to grow
again.

Measurements on the instrument are the DNX session's
(`dn_sysex/99_HardwareTest/dn1-143-2026-09-20/FINDINGS.md`); they confirmed the
converter byte for byte on a project saved by a 1.43 instrument, and that the
17 objects are song records.
