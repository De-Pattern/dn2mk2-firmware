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
