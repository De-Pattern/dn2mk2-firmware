# Section 7 is the SHARC program, and it ships in every OS update

**2026-09-13.** `docs/data-sections.md` states plainly: *"There is no SHARC
program anywhere in the update."* `docs/engine-index-map.md` §10 supports it with
a measurement: `blob` is *"not a 48-bit instruction stream"*.

**Both are wrong.** Section 7 — labelled `blob` by `elektron-firmware-tool`, and
by digikit after it — is the DSP's program image. It is an **ADI boot stream**,
not a raw instruction stream, which is why a test for SHARC's 48-bit
instruction width found nothing and concluded there was nothing there.

This matters beyond bookkeeping. The question *"does the DSP already have a
fourth LFO generator?"* has sat in `docs/ROADMAP.md` as out of scope, on the
reasoning that the DSP runs code we do not ship and cannot see. We ship it. It
is 836,956 bytes, and `dnfw extract` has been writing it to disk all along.

## The evidence

### 1. It is built from FreeRTOS for SHARC, with ADI's SHARC service libraries

Seven unstripped source paths survive in the image (`section_7_blob.aplib.bin`,
1.11):

```
0x011918  ..\..\..\..\lib\freertos-sharc\event_groups.c
0x011958  ..\..\..\..\lib\freertos-sharc\queue.c
0x0119a0  ..\..\..\..\lib\freertos-sharc\stream_buffer.c
0x011a20  ..\..\..\..\lib\freertos-sharc\portable\CCES\SHARC_215xx\port.c
0x01b780  ..\..\..\..\lib\freertos-sharc\tasks.c
0x01b7d0  ..\..\..\..\lib\freertos-sharc\timers.c
0x01b878  ..\..\..\..\lib\freertos-sharc\portable\heap_4.c
```

`portable\CCES\SHARC_215xx\port.c` is decisive: **CCES** is Analog Devices'
CrossCore Embedded Studio, and `SHARC_215xx` is its port directory for the
ADSP-215xx family — which is the part `docs/device-model.md` records (ADSP-21569).
A FreeRTOS *port layer* for a processor is only ever compiled into a program
that runs on it.

Three assert strings carry ADI's own build host path and name its service
drivers:

```
ASSERT [ADI_GPIO_CALLBACK_MEM_SIZE == sizeof(ADI_GPIO_CALLBACK_ENTRY)]
  fails at "C:\temp\win32\kit\SHARC\lib\src\services\Source\gpio\adi_gpio.c":226
ASSERT [ADI_PCG_MEMORY_SIZE >= sizeof(ADI_PCG_DEV)]
  fails at "...\services\Source\pcg\adi_pcg_v1.c":178
ASSERT [ADI_SPU_MEMORY_SIZE == sizeof(ADI_SPU_DEV_DATA)]
  fails at "...\services\Source\spu\adi_spu_v2.c":147
```

And a FreeRTOS task name, at `0x00c7d0`:

```
Audio Task
```

### 2. The container is an ADI boot stream, and the block chain walks

A magic byte proves nothing — `0xAD` occurs 1,833 times in this section by
chance. A *format* is proven by walking it: read a block header, step over the
payload its own byte count declares, and require the next header to be there.

The section opens `01 50 91 ad` — little-endian `0xAD915001`, the ADI block
header signature in the top byte. Header is four 32-bit little-endian words:
`{code, target, count, argument}`, with flags in bits 8–15 of the code.

**The chain walks the entire section and stops exactly at its last byte:**

```
$ dnfw ldr Digitone_II_OS1.11_dist.zip
stream at 0x000000: 95 block(s), ends 0x0cc55c (end of data)
  contiguous targets: 74 of 90 transition(s)  <- convincing
  entry point: 0x001c12e2
  835,436 payload bytes into 9 region(s):
    0x20000000..0x2001e880     125,056 bytes
    0x2001e888..0x2008823c     432,564 bytes
    0x28240000..0x28240300         768 bytes
    0x282403f0..0x2826f000     191,504 bytes
    0x282c0000..0x282dd52c     120,108 bytes
    0x28380000..0x283825c0       9,664 bytes
    0x283825c4..0x2839bffc     105,016 bytes
    0x80000000..0x80000014          20 bytes
    0x80000018..0x8052fbe0   5,438,408 bytes
```

95 blocks × 16 bytes of header + 835,436 bytes of payload = **836,956, the
section's exact length**, terminating on a block flagged `final` whose target is
the entry point. A wrong rule for which blocks carry payload desynchronises
within two or three blocks and then either overruns the end or stops early;
landing precisely on the last byte after 95 steps is not something chance does.

The flag assignment was **derived by walking** — it is the only one under which
the section is consumed exactly — and only then checked against ADI's published
boot-stream flags, which it matches: `FILL 0x01`, `IGNORE 0x08`, `INDIRECT 0x10`,
`FIRST 0x40`, `FINAL 0x80`. Derivation first, corroboration second.

The load addresses are SHARC memory, not ColdFire: L1 at `0x20000000`, L2 at
`0x28240000` and `0x28380000`, and 5.4 MB of DDR at `0x80000000` (almost all of
it a zero fill, which is why the section is under a megabyte).

## Why the earlier measurement missed it

`engine-index-map.md` measured per-byte-position entropy at stride 6, found it
flat, and concluded "not a 48-bit instruction stream". **The measurement was
correct and the inference did not follow**: an ADI boot stream is a sequence of
16-byte headers and payloads, so it has no global 6-byte period even when every
payload is 48-bit SHARC code. The test could only ever have detected a *raw*
instruction dump.

Windowing the same measurement shows the structure the whole-file average hid:

| window | stride 4 spread | stride 6 spread |
|---|---|---|
| whole section (836,956 B) | 1.17 | 1.00 |
| `0x000000`–`0x020000` (where the strings are) | **3.18** | 1.03 |
| `0x040000`–end | 1.36 | 1.34 |

The tail is float32 (byte 3 taking `0x3f`/`0xbf`/`0x3e` — exponent bytes), and
at 575 KB of 837 KB it dominates any average taken over the whole section. So
"blob is largely float32" was right about the tail and wrong to speak for the
file. **Aggregate statistics over a heterogeneous container describe none of its
parts.**

## A false negative I nearly handed to someone else

The first scan of every section for source paths reported **zero** for section 7,
and I was one message from passing that on. Two bugs, both mine:

```python
# filter as written -- Python parses this as (a) or (b and c)
'.cpp' in s or '.c' in s and '/' in s
```

The paths end `.c`, not `.cpp`, and they are **Windows paths with backslashes**,
so the `'/' in s` clause rejected every one of them. Nothing was hidden,
encoded, or obfuscated: the strings are plain ASCII, visible to `strings`.

It is worth writing down because of what it looked like on the way past. The
same scan run at strides 2, 3 and 4 produced *tantalising* fragments —
`..\..\i\retssaceetgop.`, `\\\\brrshcvtrpc` — which read exactly like a
de-interleaving problem and cost twenty minutes of hypothesis about SHARC word
packing. They were the same plain strings, sampled every Nth byte. **A filter bug
does not announce itself as a filter bug; it announces itself as a discovery.**

## What this does and does not establish

**Established.** The SHARC program ships in the OS update, in section 7, as an
ADI boot stream, built with CCES and FreeRTOS for the ADSP-215xx. It is
therefore patchable by the same pipeline as everything else: `dnfw` already
extracts, rebuilds and re-signs this section.

**Not established.** Whether the synthesis engine — and any LFO generator — is
in this image at all, rather than on the ColdFire. `docs/data-sections.md`
listed two surviving readings and this kills neither; it only removes the reason
to believe the DSP's code was unavailable. The next test is to disassemble a
payload block at its declared target address and see what it is.

**Not attempted.** Reading SHARC instructions. That is a second architecture, a
second toolchain, and nothing in this repository decodes it.

## The uploader, found (2026-09-16) — the ColdFire pushes the image over SPI

This section existed because section 7 *is* the SHARC program. The remaining
gap was **how it gets there**, and `docs/engine-index-map.md` §9 had made that
gap load-bearing: it concluded that no upload path existed in MAIN OS, that the
SHARC therefore boots from its own serial flash, and that *"the DN2's engine is
permanently unmodifiable"*. That verdict is now **superseded** — see the
correction filed in that section.

The path is at `0x400cf34c`, and it is one of only two callers of the container
lookup (`docs/ideas-backlog.md` §6). It reads section 7 by id, mallocs a 1 MB
buffer, copies the stored bytes in, writes a `0x03` block header, and then
pushes the image **one byte at a time over a DSPI controller**:

```
0x400cf602  movel %a0,%d0           ; a0 walks the buffer, d3 is its start
0x400cf604  subl %d3,%d0
0x400cf606  cmpl %d0,%d2            ; d2 = length, so this is "bytes remaining"
0x400cf608  bles 0x400cf63c         ; done

0x400cf60a  moveb 0xec094018,%d0    ; flow control from the FPGA
0x400cf610  moveq #16,%d1
0x400cf612  andl %d1,%d0            ; bit 4
0x400cf616  bnes 0x400cf60a         ; spin while asserted

0x400cf618  mvzb %a0@+,%d1          ; the next byte of the boot stream
0x400cf61a  oril #0x90010000,%d1
0x400cf620  movel %d1,0xec038034    ; push it
0x400cf626  movel 0xec03802c,%d0
0x400cf62c  bges 0x400cf626         ; spin until the sign bit sets
0x400cf62e  movel #0x80000000,%d0
0x400cf634  movel %d0,0xec03802c    ; write-1-clear, and round again

0x400cf63c  movel #0x18000000,%d1   ; and a final frame to close the queue
0x400cf644  movel %d1,0xec038034
```

**The register map identifies the hardware, and it is not ambiguous.** The
whole `0xec03xxxx` window is 15 accesses across exactly six addresses, and the
six are the six offsets a minimal ColdFire **DSPI** driver uses, in their
standard positions:

| Offset | DSPI register | Accesses |
|---|---|---|
| `+0x00` | `MCR` — module configuration | 5 |
| `+0x0c` | `CTAR0` — clock/transfer attributes 0 | 1 write |
| `+0x10` | `CTAR1` — clock/transfer attributes 1 | 1 write |
| `+0x2c` | `SR` — status | 5 |
| `+0x30` | `RSER` — interrupt/DMA request enable | 1 write |
| `+0x34` | `PUSHR` — transmit FIFO push | 2 writes |

Six for six, at the right offsets, is not a coincidence that a general register
block produces. And it is **internally consistent**: `CTAR1` is written, and the
`PUSHR` words below select attributes register 1. The two magic words are
`PUSHR` fields exactly:

| Bits | Field | `0x90010000` | `0x18000000` |
|---|---|---|---|
| 31 | `CONT` — hold chip select | 1, keep CS asserted between bytes | 0, release |
| 30–28 | `CTAS` — which attributes register | 1 | 1 |
| 27 | `EOQ` — end of queue | 0 | **1** |
| 23–16 | `PCS` — chip select | `0x01`, PCS0 | none |
| 15–0 | `TXDATA` | the stream byte | — |

and `0xec03802c` behaves as `SR` should: the loop spins on bit 31 (`TCF`,
transfer complete) and then clears it by writing a one back, which is
write-1-to-clear semantics and not something a general register does by
accident.

**What this settles.** §9 listed the ADSP-21569's boot options as "SPI master
(its own serial flash), SPI slave or link port (a host pushes the image), or
UART", and said the question turned on which. It is **SPI slave boot: the host
pushes the image.** The SHARC has no program until the ColdFire gives it one,
every power-up, out of section 7 of the update file. Its program is therefore
in this repository's reach, and is patchable by the same pipeline as the rest.

**What this does not settle.** Still exactly what the section above says: this
removes the reason to believe the DSP's code was unavailable; it does not show
that the synthesis engine or any LFO generator lives in that image rather than
on the ColdFire. It also does not say a *modified* boot stream will be accepted
— the stream carries ADI block headers and checksums of its own, which nothing
here has yet parsed.

**One loose end, deliberately not guessed at.** `0xec038000` sits in the
FlexBus window, not in the MCF5441x's own peripheral space at `0xfc0xxxxx`
(which this same function uses, at `0xfc0451f0`). So it is either an external
SPI controller that presents a DSPI-compatible register interface, or a second
mapping of an on-chip one. The register *layout and semantics* are measured and
certain; the silicon behind them is not, and nothing here depends on which it
is.

### The other caller is a bulk stream, and it is the best lead yet for §15

`0xec038000` and `0xec03802c` are each touched by one function besides the
uploader: **`0x400cf7be`**. It is not boot code. It is a chunked,
double-buffered streaming transfer over the same SPI port, and it is called
from two sites (`0x40025e9e`, `0x400d0fec`) where the uploader has only one.

What is measured:

```
0x400cf7d6  tstl 0x42440958         ; a length global, written by 0x400cf68c
0x400cf7fc  movel 0xec03802c,%d0
0x400cf802  btst #28,%d0            ; SR bit 28 = TFFF, transmit FIFO fill
0x400cf806  beqw ...                ; give up if the FIFO is not ready
0x400cf80a  cmpal #2800,%a2         ; 2,800-byte chunks
0x400cf814  pea %a3@(2800)          ; and a second pointer 2,800 further on
0x400cf818  pea %a2@(-2800)         ;   -- double buffering
0x400cf838  movel #0xec038034,%d0   ; PUSHR into a register, for an indirect
                                    ;   write loop rather than the byte-at-a-
                                    ;   time store the boot path uses
```

The difference from the boot path is the whole point. Boot spins on `TCF`
(transfer *complete*) once per byte — correct, slow, and fine for a one-off.
This one tests `TFFF` (FIFO *has room*) and pushes through a register-held
port address, which is how you keep a FIFO fed. **That is a throughput path.**

**Why this matters.** `docs/engine-index-map.md` §15 says the test for a fourth
LFO generator is to "find whatever crosses to the SHARC and drive lane 4
there". The FPGA register file is ruled out above as too small. This is the
first thing found that is the right shape to carry continuous data to the DSP.

> **[CORRECTED 2026-09-16, from `m-dwyer/digikit` `machine-engine-link`.]**
> digikit had already found this path and is well ahead on it, and her account
> corrects two things below that were read wrong here. Recorded rather than
> quietly edited, because both are the same kind of error.
>
> 1. **It is send *and receive*, not a two-buffer send.** The signature is
>    `(tx_len, tx_buf, rx_len, rx_buf)`. The SHARC sends **2,748 bytes back**
>    every frame. Calling the second pair a second output buffer was a guess
>    from the shape of the argument list, never checked.
> 2. **The transfer is eDMA, not PIO.** DSPI2's driver uses **eDMA channels 28
>    and 29**; TCD 29's DADDR is set to `PUSHR`, and `SERQ` is written `0x1c`.
>    The `movel #0xec038034,%d0` read below as "a register-held port address
>    for an indirect write loop" is the eDMA *destination being programmed*.
>    CTAR0 is `0xFA010000` — 16-bit frames — and each PUSHR entry is
>    `0x8001xxxx`.
> 3. She names the instance: **DSPI2**. The loose end below about which
>    silicon this is resolves the same way — her verified MCF5441x notes put
>    on-chip peripherals at `0xFC0x_xxxx`, so `0xEC038000` is reached over
>    FlexBus.
>
> The **boot** path below is unaffected: that one really is byte-at-a-time PIO
> spinning on `TCF`, and it is a different routine from the runtime driver.

#### Its two callers are interrupt handlers

Both open by saving the MAC unit — `macsr`, `acc0`–`acc3`, `accext01/23`, `mask`
— and close by restoring it. That is an **ISR prologue**: ordinary C code has no
reason to preserve the multiply-accumulate registers. So this transfer is
**periodic**, driven by an interrupt, not by a user action.

The argument list is `(tx_len, tx_buf, rx_len, rx_buf)`:

```
0x40025e8a  pea 0x800053a4     ; rx_buf -- SRAM
0x40025e90  pea 0xabc          ; rx_len = 2,748
0x40025e94  pea 0x80005e60     ; tx_buf -- SRAM
0x40025e9a  pea 0xa80          ; tx_len = 2,688
0x40025e9e  jsr 0x400cf7be

0x400d0fd8  clrl %sp@-         ; rx_buf = 0  -- this handler receives nothing
0x400d0fda  clrl %sp@-         ; rx_len = 0
0x400d0fdc  pea 0x4244098c     ; tx_buf -- BSS this time, not SRAM
0x400d0fe2  pea 0xa80          ; tx_len = 2,688
0x400d0fe6  movew #2,0x4244098c  ; the frame header word, written in first
0x400d0fec  jsr 0x400cf7be
```

### The cross-device comparison, which is new

digikit's numbers for the same driver on **Digitakt II 1.15C/1.16** are
`FUN_400cf9c4(0x802, 0x80005348, 0xabc, 0x8000488c)`. Against ours on
**Digitone II 1.11**:

| | DN2 1.11 | DT2 1.15C/1.16 |
|---|---|---|
| `tx_len` | `0xa80` = **2,688** | `0x802` = **2,050** |
| `rx_len` | `0xabc` = **2,748** | `0xabc` = **2,748** |
| test-mode handler | `tx 0xa80`, `rx 0` | `tx 0x802`, `rx 0` |

**The receive length is identical across the two instruments; the transmit
length is not.**

> **[REFRAMED 2026-09-16 — `lalzart/digitakt-ii-firmware-research-public`.]**
> A third independent account explains the pattern rather than contradicting
> it, and its reading is the better one. The transfer is **full-duplex with a
> single padded frame size**: the frame is `0xabc` = **2,748 bytes** in both
> directions, and the *payload* inside it is device-specific — `0x802` = 2,050
> on the DT2, `0xa80` = 2,688 on the DN2. So `0xabc` is not "the receive
> length"; it is the frame, and it is the same on both because the link is
> configured once.
>
> They close the size independently from the hardware side: DSPI2 CTAR0, SPI
> mode 1, **16-bit MSB-first**, active-low PCS0, one continuous `0x55e`-word
> window — and `0x55e` = 1,374 words = 2,748 bytes. They also give digikit's
> eDMA channels a direction (**29 transmits** via `DSPI2_SOUT`, **28 receives**
> via `DSPI2_SIN`) and identify the publication as a level-5 interrupt
> software-forced from a level-6 eDMA-completion path.
>
> And they independently find **sixteen per-track unit records** of `0x60` = 96
> bytes on the DT2, against the **146** bytes per track measured here on the
> DN2 — a larger per-track record for the FM machines, and a confirmation from
> outside that the per-track block structure read below is real.
>
> See `docs/lalzart-dt2-crosscheck.md`. A follow-up note is owed to digikit
> PR #12, where this was phrased the weaker way.

What the ColdFire *sends* is therefore device-specific — consistent with
per-track machine state, of which the two devices have different amounts —
while the frame that carries it is common.

That is worth having for the chimera: a DN2 running DT2 machines would have to
produce a DT2-shaped payload, but the link itself needs no change.

And the buffers are not scratch. `0x80005000`–`0x80006000` holds **at least 125
accesses across 43 addresses**, largely longword, and the functions touching
them are the same `0x40025xxx` cluster the first caller belongs to
(`0x400258da`, `0x40025b6e`, `0x40025baa`, `0x40025e0a`). There is a whole
subsystem here that maintains structured SRAM buffers and streams them to the
DSP on an interrupt.

**Stated as a lead, not a finding.** What it carries is *not* established. A
periodic ~2.7 KB push to the DSP is the right shape for per-frame control data
*and* for audio *and* for a codec/FPGA refresh, and nothing here separates
those yet. `0x42440958` is a length in a global 52 bytes below `0x4244098c`, so
there is a small descriptor structure around `0x42440950` worth reading.
`pea 0x80001a20` at `0x400cf7ea` passes an SRAM address to `0x40134490`,
unexplained.

**The test that would settle it**, and the one to run next: find what *writes*
`0x80005e60` and `0x4244098c`. If sound parameters reach them — from
`Sound::updateMirror`'s live side, or from the value array at `sound + 0x14 +
slot*2` — this is the path §15 asked for, and lane 4 can be driven here. If
they are filled from an audio ring instead, it is not, and the search
continues. The failure mode to avoid is the one §11 and §15 already demonstrate:
a structure that looked like engine addressing turning out to be storage.

## The `0xec09xxxx` window is an FPGA register file, not a data path

`docs/engine-index-map.md` §9 counted 270 accesses to `0xec09xxxx` and called
it "a peripheral or FPGA control surface, not a boot channel". **That reading
was right**, and the uploader above is why it was still the wrong conclusion:
the boot channel is the DSPI at `0xec038000`; `0xec094018` is only the
flow-control line beside it.

Mapped properly, the window is **at least 279 accesses across 57 distinct
addresses**, of which 257 are byte-wide, 13 word-wide and 9 are `lea`. They
span `0xec094000`–`0xec094070`:

| Address | Accesses | Shape |
|---|---|---|
| `0xec09404e` | 25 | 12 read / 12 write / 1 `lea`, **7 functions** — the busiest |
| `0xec094018` | 21 | 8 functions, incl. the uploader's flow control |
| `0xec094024` | 18 | **write-only**, 7 functions |
| `0xec09404b` | 15 | 6 functions |
| `0xec094019` | 13 | 4 functions |
| `0xec094034` | 8 | **the only exclusively word-wide register**, and only in `0x400cf34c` |
| `0xec09406x` | 1–4 each | all in `0x400cec70` — one subsystem's own block |

A byte-wide register file, with several write-only registers and one subsystem
per address range, is a control surface. 279 accesses is far too few to be
carrying audio. **Sound parameters do not cross to the SHARC through here as
PIO** — which matters, because `docs/engine-index-map.md` §15 says the test for
a fourth LFO generator is to "find whatever crosses to the SHARC and drive lane
4 there". This narrows where to look: not this window, and not the DSPI, which
is used once at boot. The remaining candidates are a DMA channel the FPGA
exposes, or a shared memory region.

```
python scripts/mmio_window_map.py <image.syx> 0xec090000 0xec0a0000
python scripts/mmio_window_map.py <image.syx> 0xec030000 0xec040000
```

**Read those counts as lower bounds.** The script matches the `move`, `movea`,
`clr` and `tst` forms whose absolute address sits immediately after the opcode
word; it does not match `andi`/`ori`/`bset`/`btst` against an absolute address,
because those carry their immediate first and matching them would misread
operands as addresses.

> A first version of this map said **220 across 50** and showed the `0xec03xxxx`
> window as three registers. Both were undercounts, from matching only the `d0`
> spelling of each `move` — the register number is part of the opcode. The
> access it missed was `movel %d1,0xec038034`, the SHARC's boot data port: the
> single most important access in either window. Corrected before publication,
> and recorded because **an undercount reads exactly like a clean negative** —
> which is the same failure that produced the superseded verdict this section
> exists to correct.

## Naming

The file stays `section_7_blob.*`. `blob` is `elektron-firmware-tool`'s guess and
digikit inherits it, so changing the name here would break the glob that lets
the two tools exchange extractions (`scripts/export_sections_for_digikit.py`
keeps the wrong name `DSP` for section 2 for exactly this reason). The name is
compatibility; this file is what it holds.

## Two guards of my own that were wrong, both in the direction of a false negative

Worth recording because in both cases the *tool* reported a clean, confident
result that was an artefact of its own rule.

**A plausibility check that rejected the real data.** `walk()` refused any block
whose `count` exceeded the section length — reasonable, until the last block
turns out to be a legitimate **4.5 MB zero fill** into DDR that carries no bytes
at all. The guard truncated the walk at 88 of 95 blocks and reported
`implausible count`, which reads like a finding about the firmware. The rule had
to test the *payload*, not the count.

**A discrimination rule that rejected the real stream.** `convincing` required
every target to continue the last. A real image loads several memories and so
jumps between them by design — sixteen times here — so that rule called the true
95-block walk unconvincing while blessing six-block fragments *of that same
walk*. A stricter test is not a safer test when the thing it excludes is the
answer.

## Reproducing

```sh
dnfw ldr <image.syx>                       # walk section 7's block chain
dnfw ldr <image.syx> --scan                # find every chain in the section
dnfw extract <image.syx> -o <dir>          # writes section_7_blob.aplib.bin
```

Neither check needs the emulator, the device, or a SHARC disassembler.

---

# Loading the image, and a landmark scan that found nothing

`dnfw ldr --anchors`, added after the walk was confirmed.

## The idea

The SHARC image has no RTTI, so the trick that turned MAIN OS into a named C++
program does not transfer. It has something nearly as good: **FreeRTOS is open
source**, and `configASSERT()` bakes `__FILE__` into the binary. The image names
its own translation units. Anything holding one of those string addresses is
*inside that file*, whose source can be read upstream — so `tasks.c` would
become a bounded, named region of an otherwise anonymous blob.

Finding those references needs no disassembler, which is the point: nothing in
this repository decodes SHARC.

First, `bootstream.load_regions()` plays the stream back into the memory it
describes — 9 regions, **6,423,108 bytes** once the fills are materialised.
Offsets into the section are not addresses, so nothing can be cross-referenced
until the blocks sit where they load.

## The result: no reference to any landmark, anywhere

| | |
|---|---|
| landmark strings found | 7 FreeRTOS paths + `Audio Task` |
| their load addresses | `0x2826ee10`, `0x282d0738`, `0x282dd0e0`, … |
| 32-bit words equal to one, in 6.4 MB | **0** |

And this is the *strengthened* scan, run after the first one came back empty:

* both word orders, little and big endian;
* **stride 1**, not stride 2 — an immediate embedded in an instruction need not
  sit on any alignment;
* **word-address variants** (`addr >> 2`, `addr << 2`), because SHARC address
  spaces are word-addressed and a pointer need not be a byte address.

Zero in every combination.

## What the negative means, and what it does not

It does **not** mean the strings are unreferenced — they are assert arguments in
compiled code that certainly passes them.

It means **the address is never materialised as a 32-bit constant** anywhere in
the loaded image. Why not is **unexplained**, and the rest of this section says
so carefully, because an earlier draft did not.

> **Correction, same day.** This paragraph first read: *"On SHARC+ VISA a full
> address is assembled across instruction fields — a split immediate, or an
> offset against a page/base register — so no word scan can ever see it."* That
> is a **plausible hypothesis stated as a cause**, and it was written before it
> had been tested against its obvious rival.

**The rival hypothesis was that the scan used the wrong numbers.** The landmarks
were searched for at their *load* addresses, and `docs/sharc-code-map.md`
establishes that SHARC code addresses live in a different space
(`load = exec × 2 + 0x28000000`). So the code would hold `0x137708`, not
`0x2826ee10`, and the scan could not have matched whatever the code contained.

That hypothesis was then tested and **ruled out**: converting every landmark to
exec space and rescanning, stride 1, both endiannesses, still finds **zero**.

```
0x13453c  "Audio Task"       0x137708  event_groups.c    0x137728  queue.c
0x137760  stream_buffer.c    0x1377a0  port.c            0x16839c  tasks.c
0x168424  timers.c           0x16e870  heap_4.c
```

So: **one hypothesis eliminated, the cause still unknown.** The split-immediate
explanation survives as the leading candidate and nothing more. It is the same
class of failure as the `clrl` value watch (`docs/emulator.md`) — an instrument
that cannot detect what it was pointed at — caught before the zero was written up
as a finding, but *not* before a guess about its cause was.

The idea is not dead; the *method* is. Finding these references needs a
disassembler that decodes immediate construction — digikit's `sharc_disasm.py`
is that tool. The landmark addresses above are the input to hand it, and they
are the durable product of this section.

`dnfw ldr --anchors` prints this caveat next to its own empty table rather than
leaving it here, because a future reader will run it before reading this file.
