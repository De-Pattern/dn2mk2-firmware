# The audio DMA windows, and what `#RECORD_START` actually captures

**Read 2026-09-20**, from the question the owner asked about closing the DSP
side: the service console cannot read DSP memory, so can it at least *capture*
what the DSP produces? Answering that meant reading the service audio engine,
and it led somewhere more useful than the console.

## Two windows, one frame layout

The service mode's audio ISR (`0x400d0f90` on DN2 1.11 — it saves every
register including the EMAC's `macsr`, `accext01/23`, `acc0`-`acc3` and `mask`,
which is what an interrupt handler on this core has to do) works between two
fixed memory windows:

| window | direction | used by |
|---|---|---|
| `0x4E6DF100` / `0x4E6DF900` | **in** — read by the record loop at `0x400d10c0` | `#RECORD_START`, and the instrument's own engine |
| `0x4E6E0100` / `0x4E6E0900` | **out** — written by the play loop at `0x400d1058` | `#PLAY_START` / `#PLAY_STEREO`, and the engine |

Each is **double-buffered**: the ISR reads the DMA's current pointer from the
peripheral register `0xFC045640`, compares it against `0x4E6E0900`, and uses the
result to pick which half to work on (`0x400d0f9e`, `scs %d7`, then
`d7 << 11` — the halves are 2,048 bytes apart).

**The frame is 64 bytes and the loop uses three longwords of it.** The outer
loop steps `d3` by 64 up to 2,048 (so 32 frames per half-buffer) and the inner
loop runs three channels, `d2 = 0..2`. Sixteen longword slots per frame with
three in use is a **TDM frame**, not a stereo codec stream.

## What that makes `#RECORD_START`'s first argument

`docs/service-commands.md` describes `#RECORD_START <buf> <a> [len]` and left
open "which signal it records". It is now read: the argument clamped to **0..2**
is a **channel within the TDM frame**, not a choice of source. The handler at
`0x400d0db4` stores `1 << channel` as a mask in the buffer's slot, the buffer
index at `+0x2c + 4*channel` and the offset at `+0x34 + 4*channel` of the control
block at `0x4664b1fc`; the ISR then copies, per frame, one longword from
`0x4E6DF100 + …` into `capture_base + (buffer << 19) + position`, shifted left by
8. Play is the mirror image, with a gain applied through the MAC unit
(`msac.l`, `movclr %acc0`, `asr #8`).

So **capture takes whatever arrives on the input side of that link**, at the
frame rate, into one of five 2 MB buffers — `#DUMP_AUDIO <n>` then reads a
buffer out as a `$$$$` frame.

## Why this matters beyond the console

**Both windows are used by the instrument's ordinary audio engine, not only by
service mode.** `0x4E6DF100` is referenced from six sites inside `0x40025e0a`
(the audio-frame function, 2 callers) and `0x4E6E0100` from five more in the
same region, beside the service code's one each. At `0x400277b4` the engine
computes `0x4E6DF100 + (x << 11)` — the same half-buffer arithmetic — and hands
it with `0x800053c0` to `0x40138460`, then calls `0x40137340`.

That places the two windows on the path the audio actually takes through the
instrument, which is why capture is worth having at all: it is not a test
signal, it is the stream.

## The link is SSI0, and the far end is the SHARC

`0xFC045640` is not a bare register: the CPU is an **MCF5441x**, whose eDMA
transfer-control descriptors start at `0xFC045000` with a `0x20` stride, so
`0x640` is **channel 50's `SADDR`** — the source address of a transfer whose
destination is the SSI0 transmit FIFO. That is why the play loop writes to
`0x4E6E0100` and the ISR reads that register to learn which half is in flight.
`0xFC045618` and `0xFC045658` are the scatter-gather pointers of channels
**48** and **50**, the receive and transmit pair.

digikit's emulator work names the same pair: SSI0-paced eDMA48/50 is where it
puts the **ColdFire ↔ SHARC boundary**. So the two windows are the audio
crossing between the two processors:

| window | eDMA | direction |
|---|---|---|
| `0x4E6E0100` / `0x4E6E0900` | channel 50, TX | ColdFire → **SHARC** |
| `0x4E6DF100` / `0x4E6DF900` | channel 48, RX | **SHARC** → ColdFire |

**So `#RECORD_START` captures what the DSP sends back.** That is the answer the
owner's question needed: the console cannot read DSP memory, but it can record
the DSP's own output, sample-accurate, into a 2 MB buffer and hand it over with
`#DUMP_AUDIO`.

### The `0x007FFFFF` marker, found twice

The alignment routine at `0x400d5470` reads the channel-50 `SADDR`, picks the
receive half from it, and then **searches the 32 frames of that half for a first
longword equal to `0x7FFFFF`** — full-scale positive in 24 bits, left-justified
in a 32-bit slot. On a hit it patches the **`CITER` and `BITER`** fields at
`+0x14` and `+0x1C` of the linked descriptors of *both* channels from 64 to 62,
which slips the frame by two and re-aligns the link.

digikit hit the same constant from the other side, on a Digitakt II 1.16: their
vector-170 handler "is waiting for an external `0x007fffff` sync marker before
it installs the pending normal channel-50 callback". **Two firmwares, two
instruments, two independent readings, one mechanism** — and this side says what
the marker is *for*: frame alignment, corrected by a two-frame DMA slip.

## What is still open

- **What the three channels are.** The loops use three longwords of a 64-byte
  frame; which three slots of sixteen, and whether they are a stereo mix plus
  one more or three of a larger per-track set, is not read.
- **What `0x800053c0` is** in the engine's call at `0x400277ac` — a DSP-side
  address or a descriptor.
- **Nothing here has been exercised on a device.** `#RECORD_START`, `#PLAY_*`
  and `#DUMP_AUDIO` are deliberately off `scripts/service_console.py`'s allow
  list: they start hardware activity, and the list only carries commands that
  have been read *and* are read-only. Moving any of them onto it is a decision
  to make deliberately, not a side effect.
