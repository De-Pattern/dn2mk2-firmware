# The service command interface

Found 2026-09-08 in Digitone II 1.10E MAIN OS, in the string pool around
`0x402020ad`. A text command protocol — Elektron's factory test and service
interface — with about sixty commands.

**Nothing here has been sent to an instrument.** What follows is a reading of
the strings in the firmware. The transport, the framing and whether any of it
is reachable from a normal boot are all **UNKNOWN**, and there is a real risk
of harm in guessing (see the warning below). Recorded because it is the only
route we have seen to the device's serial number, and because `#WRITE_SERIAL`
existing at all is something to know before poking at this.

## Do not send these blind

Some of these commands write. `#WRITE_SERIAL`, `#WRITE_TESTED`,
`#WRITE_UI_TESTED`, `#WRITE_AUDIO_TESTED`, `#MMC_RECONFIGURE`, `#WRITE` and
`#FULL_UPGRADE` all change persistent state, and the responses beside them
(`SERIAL NUMBER ALREADY WRITTEN`, `WRITE PROTECTED`, `ALREADY RECONFIGURED`)
say what they touch. A device whose serial number or factory-test flags are
wrong is a device with a story attached to it for the rest of its life.

The read-only ones are the interesting ones anyway.

## The commands

Handshake and control: `#HELLO` (answered `HOW DO YOU DO?`), `#BREAK`,
`#STATUS`, `#REBOOT`, `#REBOOT_INTO_MAINTENANCE_MODE`, `#ENTER_TEST_MODE`,
`#EXIT_TEST_MODE`.

Firmware: `#UPGRADE` (`READY FOR BOOTSTRAP`, `READY FOR OS`, and the literal
`ELE3` — the container magic), `#FULL_UPGRADE`.

Identity and factory state: **`#READ_SERIAL`**, `#WRITE_SERIAL`,
`#READ_TESTED`, `#READ_UI_TESTED`, `#READ_AUDIO_TESTED`,
`#READ_UI_TEST_COMPLETED`, `#DUMP_UI_CALIBRATION`.

Memory and storage: `#READ`, `#WRITE`, `#MRAM_DUMP`, `#MMCDUMP`,
`#MMC_GET_HEALTH`, `#MMC_GET_RECONFIGURED`, `#MMC_RECONFIGURE`.

Audio and sequencer: `#DUMP_AUDIO`, `#RECEIVE_AUDIO`, `#PLAY_STEREO`,
`#PLAY_START`, `#PLAY_STOP`, `#RECORD_START`, `#RECORD_STOP`, `#PLAY_PATTERN`,
`#STOP_PATTERN`.

UI test: `#START_UI_TEST`, `#ABORT_UI_TEST`, `#UI_TEST_POLL`, `#SHOW_MSG`,
`#TEST_STATUS`, `#RESET_ARM`, `#RESET_POLL`, `#SHOW_TEST_COMPLETE_SIGN`.

## `#READ_SERIAL`, disassembled — 2026-09-08

The string-pool reading below was upgraded to a code reading after the DNX
session pointed out, correctly, that four strings sitting near each other is
the order a compiler emitted literals in, not a binding. It is now bound.

**The comparison is in the chain**, at `0x400d0338`, between `#DUMP_UI_CALIBRATION`
and `#WRITE_SERIAL`:

```
400d0338:  pea 0x402022a3        "#READ_SERIAL"
400d033e:  movel %d2,%sp@-       the received line
400d0340:  jsr %a4@              the comparator
400d0346:  bnes 0x400d038a       no match -> try #WRITE_SERIAL
400d0348:  movel %fp,%d7 ; addil #-128,%d7    d7 = fp-128, a local buffer
400d0350:  movel %d7,%sp@- ; jsr %pc@(0x400cf532)   read_serial(&buf)
400d035e:  tstl %d0
400d0362:    d0 == 0   reply("%.14s
", buf)
400d0376:    d0 == -2  reply("SERIAL NUMBER CRC ERROR
")
400d0380:    otherwise reply("NO SERIAL NUMBER
")
```

`0x402022b0` **is** `"%.14s
"` and it is passed with the buffer the getter
filled. The 14 is now bound to the serial by code, not by adjacency.

### The record, from `read_serial` at `0x400cf532`

```
400cf53a:  pea 0x402ebc3c ; pea 0x16 ; movel #0x3C0000,%sp@-
400cf54a:  jsr 0x4012783a          read 22 bytes from offset 0x3C0000
400cf550:  pea 0x4 ; pea 0x40201f12 ; pea 0x402ebc3c
400cf560:  jsr 0x4016fc8c          compare the first 4 bytes against "SERI"
400cf56c:  bnes -> return -1       no magic  -> NO SERIAL NUMBER
400cf56e:  pea 0x16 ; pea 0x402ebc3c ; pea 0xffffffff
400cf57c:  jsr %pc@(0x400cec84)    CRC-32 over all 22 bytes, init 0xFFFFFFFF
400cf584:  cmpil #0xDEBB20E3,%d0
400cf58a:  bnes -> return -2       bad CRC   -> SERIAL NUMBER CRC ERROR
400cf590:  pea 0xe ; pea 0x402ebc40 ; movel %d3,%sp@-
400cf59c:  jsr 0x4016fd7c          copy 14 bytes from +4 to the caller
```

So the stored record is **22 bytes**, and every field is accounted for:

| Offset | Size | Field |
|---|---|---|
| +0 | 4 | magic `"SERI"` (the literal at `0x40201f12`) |
| +4 | **14** | the serial, copied out and printed with `%.14s` |
| +18 | 4 | CRC-32 |

`0xDEBB20E3` is the standard CRC-32 residue for a message with its own CRC
appended, which is what makes the check a single comparison over all 22 bytes.

**It lives at offset `0x3C0000`** (3,932,160), fetched by `0x4012783a` — a
reader with 12 call sites across the image. Whether that offset is into flash,
the MMC, or something else is **not yet established**; identifying
`0x4012783a` would say.

### What this still does not establish

That any particular unit **has** a valid record. `NO SERIAL NUMBER` is a real
branch, reached whenever the magic is absent, and nothing here has been run
against hardware.

Nearby, `#STATUS` is followed by a block that looks like a device identity
report:

```
START
VERSION 1
%.16s
PLATFORM
PCBA0109%c%d
PRODUCT
%d;%d;%d;%s
%02x %04x %02x %08x %08x %08x %08x
WRONG DEVICE TYPE %02x %04...
```

`PCBA0109` is presumably the board number, with a revision letter and number
after it. The 16-character field and the semicolon-separated product tuple are
unidentified.

**If any of this carries a product number, do not assume it matches the ones
the MIDI protocols report.** DNX observes a Digitone II answering **21** in the
dump protocol and **43** through the file API — the same instrument, two
numbering schemes. A third here would be unsurprising.

## The dispatcher — found 2026-09-08

**It is a chain of string compares, not a table.** Each command is one inline
comparison, about 52 bytes apart, running from `0x400cfca2` (`#HELLO`) to
`0x400d095e` (`#STATUS`).

The enclosing function is **`0x400cf906`**:

```
400cf906:  linkw %fp,#-284                  284-byte frame
400cf90a:  moveml %d2-%d7/%a2-%a5,%sp@
400cf90e:  pea 0x40370e9c ; jsr 0x40111264
400cf91a:  pea 0x402ebe40 ; movel #524296,%sp@- ; jsr %a2@   (a2 = 0x40110fe2)
400cf930:  movel %fp,%d2 ; addil #-192,%d2   <- d2 = fp-192, the command buffer
400cf93c:  movel %fp,%d3 ; addil #-160,%d3   <- a second buffer, 32 bytes along
```

`%d2` holds the command text for the whole chain, and it is a **local stack
buffer at `fp-192`**, about 32 bytes long. Every comparison then looks like:

```
400cfca0:  pea 0x402020ad         push "#HELLO"
400cfca6:  movel %d2,%sp@-        push the received line
400cfca8:  jsr %a5@               a5 = 0x4016f7d4, the string comparator
400cfcac:  tstl %d0
400cfcae:  bnes ...               no match, try the next command
400cfcb0:  pea 0x402020b4         push "HOW DO YOU DO?"
400cfcb6:  jsr 0x400054b4         the reply function
```

So the pieces are: comparator `0x4016f7d4` (82 call sites — a shared strcmp),
reply `0x400054b4` (takes a string pointer), and a precondition check at
`0x400cf6be` that emits `UNIT IN FACTORY TEST MODE`, `WRONG UI CARD` and
`UI CARD NOT TESTED`.

### It is a line protocol, and that is a real constraint

Every message in this region ends **`

`** — `UNIT IN FACTORY TEST MODE

`,
`WRONG UI CARD

`, and the rest. CRLF-terminated text into a ~32-byte stack
buffer is a **byte stream**, which is not how SysEx is framed.

**So this is probably not reachable through SysEx**, and probably not hiding
behind one of the unidentified dump-protocol codes. A serial transport — the
USB port or a debug UART — fits the evidence far better. **Inferred from the
framing, not proven**; the transport is still not named.

### Why the transport is still not named

`0x400cf906` has **no callers and no pointer references anywhere in the image**.
Nothing does `jsr` to it, PC-relative or absolute, and its address appears in no
table. It is reached by something that does not leave a static reference —
most plausibly registered as an RTOS task or a driver callback, which fits its
two entry calls into the `0x4011xxxx` region (`0x40111264`, and `0x40110fe2`
called with `0x80008`) against data at `0x40370e9c` and `0x402ebe40`.

Naming it means following those two calls into the RTOS layer. That is the
remaining work, and it is still entirely offline.

## The firmware carries a USB CDC-ACM device — found 2026-09-08

Prompted by the DNX session finding a stale Windows PnP record for
`VID_1935/PID_FFFF` with a Communications-class interface and no driver bound.
That device is **in this firmware**, and its descriptors are complete.

`0x402e1126` (high speed) and `0x402e1171` (full speed), both followed by the
device descriptor `VID 0x1935 / PID 0xFFFF`, `bDeviceClass 0xEF` (Miscellaneous
— an IAD composite):

```
IAD      first=0 count=2 class=0x02 sub=0x02 prot=0x01
IFACE #0  class=0x02 CDC   sub=0x02 (ACM)  prot=0x01   1 endpoint
   Header 1.10 / ACM / Union(0,1) / Call Management
   EP 0x83  IN   interrupt   maxpkt 512 (64 at full speed)   notification
IFACE #1  class=0x0a CDC-Data                          2 endpoints
   EP 0x02  OUT  bulk        maxpkt 512 (64)
   EP 0x82  IN   bulk        maxpkt 512 (64)
```

**The subclass is 0x02, Abstract Control Model** — the virtual-COM-port
profile — not the 0x01 Direct Line Control the Windows PnP record suggested.
A stale registry entry is weaker evidence than the descriptor itself.

The same descriptor set appears in the **`updater` section** (id 4, raw, loads
at `0x80000400`) at `+0x799d`/`+0x79d7`, so the bootstrap image presents this
interface too.

For completeness, the other Elektron USB device descriptors in MAIN OS:
`0x1034` (the DN2 as a normal MIDI device), `0x0b34` (Overbridge), `0x0134`
(twice), `0x0004`, `0x001e`. Only `0xFFFF` has CDC interfaces; the rest are
Audio/MIDI-Streaming.

### What this does and does not establish

**Established:** the firmware can present a USB CDC-ACM serial port under
`PID 0xFFFF`, with the endpoints above, and the updater can too.

**Not established:** that the `#COMMAND` parser is fed from that port. Two
facts fitting each other is not a proven link — a CRLF line protocol reading
into a 32-byte stack buffer, and a CDC-ACM interface in the same image, are
strongly suggestive and nothing more. `0x400cf906` still has no identifiable
caller. Also unknown: what puts a unit into `PID 0xFFFF` mode and what brings
it back.

## What would settle it

1. **Follow `0x40111264`** into the `0x4011xxxx` region to find what registers
   `0x400cf906`, and whether its input comes from the CDC-Data bulk OUT
   endpoint. `0x40110fe2` is a dead end — it is a two-line setter that stores
   its arguments into globals at `0x443dde20` and `0x443dde24`.
2. **Find what selects `PID 0xFFFF`**, and what returns the unit to normal.
   Until that is known, nothing about this mode is reversible on demand, which
   is the part that matters before anything is plugged in.
3. **Then, and only then, `#HELLO`.** It takes no arguments, changes nothing,
   and a reply of `HOW DO YOU DO?` would confirm the whole picture at zero risk.

`dnfw` has no MIDI or USB I/O and is not the place to add it — it is an offline
image tool. DNX already has device I/O and a written-down discipline for
probing safely (`DNX/docs/device-probing.md`), which is where this belongs if
it is pursued.
