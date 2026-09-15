# Notes for the `machine-engine-link` work: how the ColdFire reaches the SHARC

**2026-09-16.** Your branch note says you are *"mapping out the DSP and how to
interface with it from ColdFire"*. This is what we found on that exact question
over one session, written to be useful without our repository — every claim has
the address and the bytes, so you can check it in your own tooling rather than
take our word for it.

Measured against **Digitone II OS 1.11**, section 3 (MAIN OS), depacked and
loaded at `0x40000400`. The DT2 should be the same code with a different device
gate; we have not re-run these addresses against 1.16.

**Two of these correct things we ourselves published earlier.** Where that is
so, it is flagged — our old claim may already be in your notes.

---

## 1. The ColdFire boots the SHARC over SPI. Section 7 is the image.

This is the headline, and it retracts a claim of ours you may have picked up:
we previously concluded there was **no upload path in MAIN OS**, and therefore
that the SHARC boots from its own serial flash and its program was out of
reach. **That was wrong.** It was a negative produced by searching the wrong
window — we looked through the `0xec09xxxx` accesses, found only byte-wide
registers, and stopped. The boot channel is a DSPI next door.

**The uploader is at `0x400cf34c`.** It looks section 7 up by id, mallocs 1 MB,
copies the stored bytes in, writes a `0x03` block header, and then pushes the
image **one byte at a time**:

```
0x400cf602  movel %a0,%d0           ; a0 walks the buffer, d3 its start
0x400cf604  subl %d3,%d0
0x400cf606  cmpl %d0,%d2            ; d2 = length
0x400cf608  bles 0x400cf63c         ; done

0x400cf60a  moveb 0xec094018,%d0    ; flow control from the FPGA
0x400cf610  moveq #16,%d1
0x400cf612  andl %d1,%d0            ; bit 4
0x400cf616  bnes 0x400cf60a         ; spin while asserted

0x400cf618  mvzb %a0@+,%d1          ; next byte of the boot stream
0x400cf61a  oril #0x90010000,%d1
0x400cf620  movel %d1,0xec038034    ; push
0x400cf626  movel 0xec03802c,%d0
0x400cf62c  bges 0x400cf626         ; spin on bit 31
0x400cf62e  movel #0x80000000,%d0
0x400cf634  movel %d0,0xec03802c    ; write-1-clear

0x400cf63c  movel #0x18000000,%d1   ; final frame closes the queue
0x400cf644  movel %d1,0xec038034
```

### Why we are confident it is a DSPI, rather than reading tea leaves

Not from one constant. The **whole `0xec03xxxx` window is 15 accesses across
exactly six addresses**, and the six are the offsets a minimal ColdFire DSPI
driver uses, in their standard positions:

| Offset | DSPI register | Accesses |
|---|---|---|
| `+0x00` | `MCR` | 5 |
| `+0x0c` | `CTAR0` | 1 write |
| `+0x10` | `CTAR1` | 1 write |
| `+0x2c` | `SR` | 5 |
| `+0x30` | `RSER` | 1 write |
| `+0x34` | `PUSHR` | 2 writes |

Six for six at the right offsets, and **internally consistent**: `CTAR1` is
written, and the `PUSHR` words select attributes register 1. The two magic
words decode as `PUSHR` fields exactly:

| Bits | Field | `0x90010000` | `0x18000000` |
|---|---|---|---|
| 31 | `CONT` hold CS | 1 | 0 |
| 30–28 | `CTAS` | 1 | 1 |
| 27 | `EOQ` | 0 | **1** |
| 23–16 | `PCS` | `0x01` | — |
| 15–0 | `TXDATA` | the byte | — |

and `SR` bit 31 is `TCF`, spun on and then cleared write-1.

**So it is SPI *slave* boot: the host pushes the image.** The ADSP-21569 has no
on-chip flash; this settles which of its boot modes is in use. The DSP has no
program until the ColdFire gives it one, every power-up, out of section 7.

**What follows for you:** the DSP's program is in the update file, in reach of
the same rebuild-and-sign pipeline as everything else. (Whether a *modified*
boot stream is accepted is a separate question — it carries ADI block headers
and checksums we have not parsed.)

Caveat we are keeping honest about: `0xec038000` is in the FlexBus window, not
the MCF5441x's own peripheral space at `0xfc0xxxxx` — which this same function
also uses, at `0xfc0451f0`. So it is either an external controller presenting a
DSPI-compatible interface or a second mapping of an on-chip one. The register
layout and semantics are certain; the silicon is not, and nothing above depends
on which.

## 2. `0xec09xxxx` is an FPGA register file, not a data path

If you have our earlier number for this, it was **wrong and too low**. We said
220 accesses across 50 addresses; the real figure is **at least 279 across 57**.
The undercount came from an opcode mask that matched only the `d0` spelling of
each `move` — and the access it missed was `movel %d1,0xec038034`, the boot
data port itself. Worth knowing if you wrote a similar scanner: the register
number is part of the opcode.

| Address | Accesses | Shape |
|---|---|---|
| `0xec09404e` | 25 | 12 read / 12 write / 1 `lea`, **7 functions** |
| `0xec094018` | 21 | 8 functions, incl. the uploader's flow control |
| `0xec094024` | 18 | **write-only**, 7 functions |
| `0xec09404b` | 15 | 6 functions |
| `0xec094019` | 13 | 4 functions |
| `0xec094034` | 8 | the only exclusively **word-wide** register, only in `0x400cf34c` |
| `0xec09406x` | 1–4 | all in `0x400cec70` — one subsystem's block |

257 of 279 are byte-wide, spanning `0xec094000`–`0xec094070`. A byte-wide file
with several write-only registers and one subsystem per range is a **control
surface**. It is far too small to carry audio, so this is not where sound data
crosses.

Read those as lower bounds: we match `move`/`movea`/`clr`/`tst` whose absolute
address sits right after the opcode word, and deliberately not `andi`/`bset`
and friends, whose immediate comes first and would make us misread operands as
addresses.

## 3. The runtime path: `0x400cf7be`, driven by two interrupt handlers

The same SPI port carries a **periodic bulk stream** at runtime, and this is
the most interesting thread we have open.

`0x400cf7be` differs from the boot path in exactly the way that matters: boot
spins on `TCF` (transfer *complete*) once per byte, correct and slow; this one
tests **`SR` bit 28, `TFFF`** (FIFO *has room*) and pushes through a
register-held port address. That is how you keep a FIFO fed — a throughput
path.

Its two callers both open by saving `macsr`, `acc0`–`acc3`, `accext01/23` and
`mask`, and close by restoring them. **That is an ISR prologue** — ordinary C
has no reason to preserve the MAC unit. The transfer is periodic and
interrupt-driven.

The argument list reads as a two-buffer scatter send, `(len1, buf1, len2, buf2)`:

```
0x40025e9e   (2688, 0x80005e60, 2748, 0x800053a4)    both SRAM
0x400d0fec   (2688, 0x4244098c,    0,          0)    BSS, second pair null
                    ^ a 16-bit `2` is written here first, like a header
```

`0xa80` = 2,688 in both, against the function's own `#2800` chunk bound — so
2,688 is a payload and 2,800 the stride it sits in.

The buffers are not scratch: `0x80005000`–`0x80006000` holds **≥125 accesses
across 43 addresses**, largely longword, from the same `0x40025xxx` cluster the
first caller lives in (`0x400258da`, `0x40025b6e`, `0x40025baa`, `0x40025e0a`).
There is a subsystem there maintaining structured SRAM buffers and streaming
them to the DSP on an interrupt.

**What it carries, we do not know, and we are not guessing.** A periodic ~2.7 KB
push fits per-frame control data, audio, and a codec refresh equally well.
Loose ends we have not pulled: a descriptor structure around `0x42440950`
(`0x42440958` is a length, 52 bytes below `0x4244098c`), and the SRAM address
`0x80001a20` passed to `0x40134490` at `0x400cf7ea`.

**The discriminator, if you get there first:** find what *writes* `0x80005e60`
and `0x4244098c`. Sound parameters reaching them makes this the control path to
the engine. An audio ring means it is not.

## 4. The container lookup, since it is how the uploader finds its image

MAIN OS carries its own full ELE3 parser — `movel #'ELE3',d0` at `0x40134546`,
a `moveq #52` product gate at `0x40134554` (52 = DN2; DT2 is 43). Four
generic entry points, which between them read any section by id:

| Address | What |
|---|---|
| `0x4013459a` | `find_section_by_id(u32 id, Entry out[16]) -> bool` |
| `0x4013458a` | `section_data_address(Entry *) -> entry.offset + 0x80000` |
| `0x401350ce` | `block_copy(src, len, dst)` — the parser's own, 3 callers |
| `0x4011ffe8` | `malloc(size)` — 18 callers |

Entry layout confirmed from the caller at `0x400f2934`: `+0 id`, `+4 offset`,
`+8 stored length`, `+12 dest`.

Two things you may find useful from this:

- **`find_section_by_id` has exactly two callers**, `0x400cf59a` (id 7, the
  SHARC) and `0x400f2934` (id 8, which by the same pattern is a second
  coprocessor image — we read it as ARM Cortex-M).
- **Nothing anywhere reads `entry.dest`.** The same table walk is compiled into
  the bootstrap (`0x02015066`) and the updater (`0x80003d6e`) as well, and in
  both it is **dead code** — zero callers, confirmed by full disassembly, by a
  byte-level scan showing the address is never taken as an immediate, and with
  a positive control (the same scan finds both MAIN OS callers). `dest` is
  documentation: the address each section is linked for.

## 5. One methodological note, offered because it cost us months

Two of the four sections above correct earlier claims of ours, and **both
originals were negatives** — "no upload path", "220 accesses". Looking back,
every expensive mistake in our repository has this shape: a search runs, finds
nothing, and the nothing is written down as a property of the firmware rather
than of the search.

Ours, in full: "no SHARC program in the update" (searched for a raw 48-bit
instruction stream; it is a *boot stream*); "no upload path in MAIN OS"
(searched the wrong window); "no reference to any SHARC landmark" (searched at
load addresses, but SHARC code addresses live in a different space); "the PRM
publishes no register encodings" (read 118 of 798 pages — that one we already
retracted to you on PR #11); "87.82% is 100% of what the figures contain"
(blind to the yellow *unused* cell colour).

The cheap guard we now run before writing down any negative: **point the
instrument at a known positive first.** If it cannot find something you already
know is there, its zero means nothing. And state the scope in the same sentence
as the result — "not found by X" and "not present" are different claims.

Offered as a shared hazard of this kind of work, not as advice about your
process, which from the outside looks more careful than ours has been.

---

## Reproducing

```
python scripts/mmio_window_map.py <image.syx> 0xec030000 0xec040000
python scripts/mmio_window_map.py <image.syx> 0xec090000 0xec0a0000
dnfw fn <image.syx> --section 3 callers --at 0x4013459a
dnfw disasm <image.syx> 0x400cf5e0 200
```

Happy to hand over anything here in another form, or to re-run any of it
against 1.16 if that is more useful to you than 1.11.
