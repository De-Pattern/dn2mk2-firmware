# The device's MIDI RPC surface — reading the hardware instead of the file

> **~~PARKED 2026-09-12. Recorded, not pursued.~~ — UNPARKED 2026-09-14,
> the protocol now works on hardware; see the end of this file.** The original
> note follows because its reasoning was right at the time.
>
> **PARKED 2026-09-12.** Recorded, not pursued. The DSP hunt needs a tooling
> answer first — we have no SHARC disassembler and no handle on the packing
> (`docs/ideas-backlog.md` §7) — so finding the image would not yet let us read
> it. This route is kept because it is the cheapest way to *settle* the question
> when the hunt resumes, and because steps 1–3 below are useful on their own.

The owner asked, in the middle of the DSP hunt: *"Why don't we go straight to the
Elektron transfer?"*

The instinct is right, and it opens a route this project had not considered.
**The DN2 exposes a large RPC surface over MIDI SysEx, including a raw
filesystem read API.** Everything the DSP hunt has been doing — entropy tests,
periodicity tests, guessing at packing — is static analysis of a file. This is
the option of asking the running instrument instead.

## What is there

Enumerated from the RTTI in MAIN OS 1.11 (`elektron::MidiRpc*`), ~90 request /
response pairs. Grouped:

| Group | Messages |
|---|---|
| **Raw filesystem** | `FsRawReadDir`, `FsRawOpenFileForRead`, `FsRawReadFileV1/V2`, `FsRawCloseFileReader`, `FsRawGetFileInfoFromPathV1/V2`, `FsRawGetFileInfoFromHashAndSize`, `FsRawCreateDir`, `FsRawDeleteDir`, `FsRawDeleteFile`, `FsRawRenameFile`, `FsRawOpenFileForWrite`, `FsRawWriteFileV1/V2`, `FsRawCloseFileWriter` |
| **Sample filesystem** | the same shape again under `FsSample*`, plus `FsSampleListRam`, `FsSampleClearRam`, `FsSampleAssign`, `FsSampleMemoryCompaction` |
| **Data objects** | `DataList`, `DataReadOpen`, `DataReadPartial`, `DataReadClose`, `DataWriteOpen/Partial/Close`, `DataClear`, `DataCopy`, `DataMove`, `DataSwap`, `DataRename`, `DataSetTags` |
| **Device** | `DeviceUID`, `SoftwareVersion`, `Ping`, `StorageSpace`, `Query`, `TempoRead`, `TempoWrite`, **`Screenshot`** |
| **OS upgrade** | `OsUpgradeStart`, `OsUpgradeWrite`, `OsUpgradeEnd` |
| **Generic** | `EnumerateFiles`, `ReadFile`, `WriteFile` |

Dispatch: `Midi::handleSysexRpc(const unsigned char*, int, midiInInterfaceID_t)`
→ `MidiRpcDispatcher::handleMessageAndCreateResponse(shared_ptr<MidiRpcMessage>)`.
A chunk-size limit is named in the strings as `rpc_file_chunk_size_max`.

## Why this matters here

**`FsRaw*` is a raw filesystem read API on the running device.** If the SHARC
boot image is stored as a file — on the eMMC, or in a region the filesystem
layer can address — it can be **listed and read off the hardware directly**,
rather than inferred from a static blob whose packing we cannot guess
(`docs/ideas-backlog.md` §7).

That would not merely shortcut the current hunt; it would settle it. A directory
listing either contains something DSP-shaped or it does not.

**And `Elektron Transfer` is the existing client for this protocol** — which is
exactly what the owner's question was pointing at. `FsSample*` is plainly what
Transfer drives on sampling devices; `FsRaw*`, `Data*` and `EnumerateFiles` are
the generic layer beneath it.

**DNX does not implement any of this.** Checked: the only match across the whole
DNX tree is a coincidence in `package-lock.json`. DNX reads *projects* from
`.dnx` backups; it does not speak the RPC. So this is new ground for both
projects, and anything built here would be useful to DNX too.

## What is not established

Stated plainly, because the temptation is to assume the good case:

- **Whether the DSP image is a file at all.** Firmware regions usually are not in
  the filesystem. `blob` ships inside the ELE3 container, which argues it is
  *not* a file the FS layer sees.
- **Whether `FsRaw*` is enabled on the DN2.** The DN2 does not sample, so the
  `FsSample*` half may be inert on this device; `FsRaw*` may or may not be.
- **The wire format.** Message ids, field layouts and the SysEx envelope are all
  unread. The RTTI gives names, not encodings.

## The next steps, cheapest first

1. **Read the dispatcher.** `MidiRpcDispatcher::handleMessageAndCreateResponse`
   resolves a message id to a handler; that table gives the **opcode for every
   name above**, which is the one thing needed before anything can be sent.
2. **Implement `Ping` and `SoftwareVersion`.** Two messages, no side effects, and
   they prove the envelope, framing and dispatch end to end. `SoftwareVersion`
   also answers a question left open earlier — the OS version is compiled-in
   integers with no string in the image (`docs/os-versions.md`), and this is how
   the device reports it.
3. **Then `Screenshot`.** Still read-only, still harmless, and a screenshot
   arriving on the desktop is unambiguous proof the whole stack works. A good
   milestone precisely because it cannot be misread.
4. **Then `FsRawReadDir` / `EnumerateFiles`.** Read-only. This is the step that
   answers the DSP question — and it also maps the device's storage, which
   `docs/hardware.md` lists as an open item.

**Write operations are out of scope and should stay out.** `FsRawWriteFile*`,
`FsRawDeleteFile`, `DataClear` and the `OsUpgrade*` trio can all destroy a
user's +Drive or brick the device. Nothing in this document needs them, and the
read half is where all the value is.

Recovery remains proven for the OS (`docs/flashing.md`), but **a wiped +Drive is
not recoverable** from anything this project holds — take a DNX backup before
the first RPC session regardless, since even a read API can be sent a malformed
message.

---

# The protocol works, on hardware — 2026-09-14

**Unparked.** The note at the top of this file said the RPC surface was
"recorded, not pursued". It has now been reached on a connected Digitone II
running freshly-reflashed 1.11, read-only.

## The framing, taken from elektroid rather than derived

`docs/references.md` records why: `dagargo/elektroid` (GPLv3) already implements
Elektron's transfer protocol and supports this device by name, so the wire
format was **read out of `src/connectors/elektron.c`**, not reverse-engineered
from the firmware. The plan in §"next steps" — read
`MidiRpcDispatcher::handleMessageAndCreateResponse` to recover opcodes — was
unnecessary, and would have been days of work for something already published.

```
raw   = F0 00 20 3C 10 00 <encode87(body)> F7
body  = <seq:2 big-endian> 00 00 <opcode> [payload]
reply opcode = request opcode | 0x80
```

`encode87` is MSB-first 8-in-7: for each group of seven source bytes, emit one
byte holding their seven top bits, then the seven bytes with bit 7 cleared.

## What the device answered

Sending `ping` (opcode `0x01`) as
`f0 00 20 3c 10 00 00 00 00 00 00 01 f7`:

```
f0 00 20 3c 10 00 04 00 05 00 00 01 2b 16 00 01 02 03 04 06 07 09 00
50 52 51 53 54 55 56 00 57 58 59 5a 5b 5c 5d 00 5e 44 69 67 69 74 6f
00 6e 65 20 49 49 00 f7
```

Decoded: opcode `0x81`, body

```
2b 16 | 01 02 03 04 06 07 09 50 52 51 53 54 55 56 57 58 59 5a 5b 5c 5d 5e | "Digitone II"
```

- `0x2b` = 43 — matching the Digitone II id in elektroid's device table, which
  is an independent confirmation that the framing is right rather than merely
  producing plausible bytes.
- The middle run is the device's **own list of supported opcodes**, 22 of them.

**It contains the whole data-object family** — `0x53 DATA_LIST`,
`0x54/0x55/0x56` read open/partial/close — **and none of the `FsSample`
(`0x10`+) or `FsRaw` (`0x14`+) families.** The device says, in its own words,
what elektroid's table said: this instrument has a data store and no sample
filesystem. `docs/pcm-hunt.md` §8 is confirmed from the hardware.

### Cross-checked against DNX, and one id correction

The DNX session, working the same device from the other side, reports its
`capabilities.ts` records **the same 22 codes for 1.10E build 0050**. So 1.11
advertises an unchanged set, from two tools sharing no code.

**And a correction worth more than the capture:** `0x2b` is the **file-API**
product id. The **dump protocol calls the same instrument `0x15`**. Two id
spaces; never compare an id across them.

## A trap that is not the device: a second application on the port

From DNX, recorded before it costs us a wrong conclusion:

- 2026-09-06, with Overbridge holding the port, two unrelated replies — a
  directory listing and a file chunk — both came back **cut at exactly 885
  bytes**.
- A preset bank listed as **35 of 256** while Elektron Transfer was open.

So **any reply that decodes to 885 bytes, or that lacks a terminating `F7`,
means "suspect a second application on the port" before anything is concluded
about the firmware.** Windows `winmm` gives one process exclusive use of a MIDI
port, so two sessions cannot both hold it — but a *different* application
(Transfer, Overbridge) can corrupt what a holder sees.

## Three bugs of ours, all silent, all caught by controls

None of these announced itself; each produced a confident wrong answer.

| Bug | What it looked like |
|---|---|
| `MIM_LONGDATA` set to `0x3C5` — that is **`MIM_ERROR`**; the correct value is `0x3C4` | Short messages arrived normally, so the input looked healthy while **every SysEx reply was silently discarded**. Two "the device did not answer" results were recorded before this was found. |
| `midiInAddBuffer` called **from inside the MIDI callback**, which Windows forbids | Harmless for exactly as long as `MIM_LONGDATA` never fired. The first run after fixing the constant **hung**. |
| `MIDIHDR.lpData` declared `c_char_p` | ctypes auto-converts a `c_char_p` *field* to NUL-terminated `bytes` on access, so the first genuine reply decoded as **54 bytes of noise**. Must be `c_void_p`. |

The sequence is the lesson. The device was asked twice and appeared silent both
times; the receive path had been "proved" by watching the owner's pad produce
`90 3c 64`, which exercises `MIM_DATA` and says **nothing** about the entirely
separate buffer path SysEx uses. *A control that does not exercise the path
under test is not a control.*

## The Universal Device Inquiry is genuinely unanswered

`F0 7E 7F 06 01 F7` drew nothing, twice, and that now stands as a finding rather
than an artefact: the same tool, in the same run, gets a clean reply to
Elektron's own `0x01`. The DN2 does not implement the MIDI standard identity
request.

## Where this goes next

`0x53 DATA_LIST` is read-only, advertised by the device, and targets the one
filesystem it has. That is the probe that would say whether the FM drum
transients are data objects on the instrument — `docs/pcm-hunt.md` §8.

**Not yet sent.** The DNX session needs the port for +Drive listings and a
project read, and has priority; this session is standing off until it reports
finished. `scripts/midi_probe.py` holds the tooling.

---

## Screenshot: opcode 0x04, and a live mirror (external report, 2026-09-17)

An external contributor, who has built tools for Digitone/Digitakt maintenance
mode, a GFX browser/editor and a boot-logo customisation on a Digitakt, reports:
**the screen is a MIDI RPC service, "4 if I recall", which returns the frame
buffer; it needs decoding, and requesting it repeatedly gives a live mirror.**

It fits what the image says: **`04` is in the DN2's advertised opcode list**
(`01 02 03 04 06 07 09 50 …`, `docs/midi-rpc-dispatch.md`), and `Screenshot` is
among the `MidiRpc*` classes above. Not yet exercised here.

**How to decode it, if it is the panel buffer** (the only 128 x 64 frame the
firmware keeps, read and proven under the emulator — digikit `emu/panel.py`):
1,024 bytes, `byte = page + 8 * column` (page 0..7, column 0..127), and bit `n`
of that byte is row `8 * (7 - page) + n`, least significant bit first — an
SSD1306-style page layout with the **page order inverted** (page 0 is the bottom
eight rows). The check that settles orientation: knobs come out round and text
reads normally. The RPC reply may wrap or compress the buffer; that part is
unread.

**Why it matters here:** hardware screenshots of what our builds draw — boot
screens, LFO glyphs, labels — without the owner photographing the panel.
Device I/O belongs to DNX (`ask DNX for device data`); the request went there.

### The handler, read 2026-09-17

At `0x4012618c` the dispatcher `dynamic_cast`s to `MidiRpcScreenshotRequest`
(typeinfo `0x40207fe4`) and reads **no field** of the request — only its
non-null pointer. So the request is **just the opcode** (envelope aside; the
generic parse step is not read). It then:

1. starts a response with `u32 1`, `u16 128`, `u16 64` — format, width, height;
2. allocates **1,024 bytes**;
3. posts a job (`0x4002e014`, lambdas `0x401250d0` / `0x40125114`) that locks
   (`0x4002e322`), takes a panel framebuffer pointer (`0x40131df8`:
   `move.l 0x402a0b8c,%d0`; the pair is `0x402a0b88`/`0x402a0b8c` on 1.11),
   copies 1,024 bytes, sets a done flag and posts semaphore `0x445fa6b0`;
4. waits on that semaphore and builds the response (`0x401bd23c`).

So the reply carries the raw 128 x 64 panel buffer, decoded as above. Nothing is
written. The one hang mode is the semaphore: a stalled display task makes the
request wait. The exact order of fields in the SysEx reply is not read.

