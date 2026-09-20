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

**The stored CRC must be little-endian for that residue to appear.** Fed
big-endian the same 22 bytes yield `0xC7BF6731` instead. Checked against a
synthetic record by the DNX session, 2026-09-08 — so the record is
`"SERI"` + 14 bytes + **CRC-32 little-endian**. Worth noting because the CPU is
big-endian and every other multi-byte field in this firmware is too; a
little-endian field here suggests the record is written by something other than
this firmware, most likely a factory tool. That last part is inference. The
endianness is not: it is what makes the check the code performs succeed.

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
profile.

A Windows PnP record on the author's machine shows a `PID_FFFF` device with
subclass **0x01**, Direct Line Control. That is **not** a contradiction and was
briefly written up here as one, wrongly. That record's `DeviceDesc` is
`Elektron Digitone` with `REV_0001` — a Digitone 1 — while these descriptors
are Digitone II 1.10E. A compatible id is built from what the device actually
sent, so both readings are true of their own instrument. **A DN2 descriptor
does not correct a DN1 enumeration.**

The endpoint layout above is therefore a DN2 fact. Do not assume it for a DN1;
that would need a DN1 image.

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

1. **Find what fills the command buffer.** Both of the dispatcher's entry calls
   turned out to be dead ends: `0x40110fe2` stores its two arguments into
   globals at `0x443dde20`/`0x443dde24` and returns, and `0x40111264` stores one
   into `0x40285858` and returns. Two-instruction setters, not channel opens.
   The function immediately after them decrements counters at `0x443de2e0`,
   `0x443de2dc`, `0x443de2d8` and increments `0x464b2bb0`, which is the shape of
   a timer tick — so the `0x4011xxxx` region looks like a scheduler, and those
   calls register the dispatcher as something periodic rather than opening a
   port.

   That leaves the line reader unfound. It is inside `0x400cf906` somewhere
   between the prologue and the first comparison, and locating it wants a
   proper Ghidra function pass rather than more disassembly by hand — Ghidra is
   cleared for exactly this (`docs/mainos-image.md`).
2. **Find what selects `PID 0xFFFF`**, and what returns the unit to normal.
   Until that is known, nothing about this mode is reversible on demand, which
   is the part that matters before anything is plugged in.
3. **Then, and only then, `#HELLO`.** It takes no arguments, changes nothing,
   and a reply of `HOW DO YOU DO?` would confirm the whole picture at zero risk.

`dnfw` has no MIDI or USB I/O and is not the place to add it — it is an offline
image tool. DNX already has device I/O and a written-down discipline for
probing safely (`DNX/docs/device-probing.md`), which is where this belongs if
it is pursued.

## 1.11: the whole path, read end to end — 2026-09-19

Everything above was 1.10E. This is 1.11 (the build target), read in the code
from the USB endpoint to the reply. **Static reading; the emulator confirmation
is the next step** (below). Nothing has been sent to an instrument.

### What maintenance mode starts

At `0x400cf086` the OS tests bit `0x20` of the boot-flags word `0x40287520`
(set by the bootstrap for the power-on combination or the reboot marker; the
keys are in `dn_sysex`, not here). With the bit set it:

1. registers the byte receiver `0x4011f364` as the USB serial callback
   (`0x400053ac`, stored at `0x403053b8`);
2. calls `0x400cea6e`, which creates the command queue `0x4038ae9c`
   (0x400 entries) and the **service task**: entry `0x400cd48e`, priority 2,
   16 KB stack at `0x40385e9c`. A normal cold boot never creates this task
   (none of the emulator's `TASK_CREATE` logs has that entry);
3. selects **USB mode 4** through `0x40006c52(4)` instead of 2, 5 or 6.

Nothing else on that branch differs, and the UI setup only adds the
`MAINTENANCE MODE` label (`0x4002f02a`, drawn by `0x40117d08` when
`0x400cec62` reports the bit). **So maintenance mode is the normal OS -- engine,
UI, sequencer -- plus a USB serial port and a task that listens on it.**

### The transport is USB CDC-ACM, bulk OUT endpoint 2

`0x40006c52(mode)` picks entry `mode` of a 40-byte table at `0x402875b0`:

| mode | device descriptor | configuration | used by |
|---|---|---|---|
| 1, 2 | `0x402fb298` | `0x402fb233` / `0x402fb1ce`, 0x65 B | normal boot (2) |
| **3, 4** | **`0x402fb1bc`: VID `0x1935`, PID `0xFFFF`** | `0x402fb171` / `0x402fb126`, **0x4B = 75 B** | **maintenance (4)**; 3 is the full-speed twin |
| 5 | `0x402fb50b` | `0x402fb3c3`, 0x148 B | normal boot |
| 6 | `0x402fb3b1` | `0x402fb2aa`, 0x107 B | normal boot |

75 bytes is exactly a CDC-ACM configuration (IAD + two interfaces + three
endpoints, as listed above for 1.10E). The receive side is
`0x4000510c`: a transfer queued on **endpoint 2**, max packet **512** at high
speed and **64** at full speed, completing into `0x400052fe(len, data)`, which
calls the registered callback. That is the CDC-Data `EP 0x02 OUT`. Closed:
**USB serial port → `0x4011f364` → queue `0x4038ae9c` → service task.** The
earlier "not proven" above is superseded.

### The line protocol (`0x4011f364`, per received byte)

| state | byte | action |
|---|---|---|
| idle | `#` | start a text line (the `#` is kept) |
| idle | `!` | binary frame: next 4 bytes are a **big-endian length** |
| idle | `$` | needs `$$$$`, then a 4-byte big-endian length |
| line | `\n` | terminate, post the line to the queue |
| line | `\r` | ignored |
| binary | … | copied into the binary buffer (`0x40305e40`, max 0x80008 B), posted as `'!'` or `'$'` + u32 length + data |

Lines are cut at ~0x3FF / 0x47F bytes in a 0x480-byte ring (`0x445a0480`).
The task takes the first word with `sscanf(line, "%s", cmd)` and compares it
command by command (`0x4017e8a8` is the comparator). Replies go out through
`0x400054b4` (text, CRLF-terminated) and `0x400cd204` (binary: `$$$$`, u32
length, data).

### The four commands asked about

**`#STATUS`** — no arguments. Prints sections, each opened by a line `#`:
`START`/`OK`/`VERSION 1`, then `OS`/`OK`/the 16-character version string,
then `PLATFORM`/`OK`/`PCBA0109<letter><n>` (letter `'A' + (board byte & 31)`),
then `PRODUCT`/`OK`/`52;5;15;Digitone II`, then `FLASH`/`OK` and flash checks.
Read-only.

**`#READ <name>` / `#WRITE <name> <value>`** — **not memory access.**
`sscanf(line, "%s %s")`, the name looked up (`0x400cd190`) in one of two
11-entry tables (`0x401f2c94` / `0x401f2d44`, chosen by `0x4028c148`), each
entry `{name, set, get, select}`. The names are **`SYNC_1`..`SYNC_7`,
`UART9_TXD`, `UART9_RXD`, `UART8_TXD`, `UART8_RXD`**: a factory pin test.
`#READ` replies with the pin's level (`%d`), `#WRITE` drives it, an unknown
name gives `ADDRESS ERROR`. So `#READ` cannot read RAM. (`#MRAM_DUMP` and
`#MMCDUMP` are the dump commands; not read yet.)

**`#PLAY_PATTERN` / `#STOP_PATTERN`** — no arguments. `#PLAY_PATTERN` replies
`FAIL` unless `0x400d046c()` is ready, then starts the sequencer with
`0x400d93f0({0x4121898c, 0x4210c08c}, 1)` and `0x400d7f06(0)` and replies `OK`.
`0x4210c08c` is the live kit base (`docs/engine-index-map.md`). `0x400d93f0` is
the sequencer start 13 normal UI paths call; stop is `0x400d9666(0, 0)` +
`0x400d97ce`, shared with 6–9 normal paths. **So it plays whatever pattern and
kit are loaded, through the normal engine.**

**`#DUMP_AUDIO <n>`** — `sscanf("%s %d")`; `n` is clamped to 0..4 and selects
one of five capture buffers of 0x80000 32-bit samples (2 MB each) from the
pointer at `0x4664b1fc` (set to `0x42441614` at init, `0x400d11d4`). The reply
is a binary frame: `$$$$`, u32 length (samples × 4), the samples. It pairs with
`#RECORD_START <buf> <a> [len]` (`%s %d %d %d`, `0x400d0db4`) and
`#RECORD_STOP <n>` (`0x400d0e64`). The rest of the audio group:
`#RECEIVE_AUDIO <n>` (loads a buffer from a `$$$$` frame; replies
`READY FOR SAMPLE DATA`), `#PLAY_START <buf> <off> <ch> [len]`,
`#PLAY_STEREO` (two at once, interrupts off), `#PLAY_STOP <n>`; lengths cap at
0x8000. **Open:** which signal `#RECORD_START` records -- the codec inputs, or
the instrument's own output -- is not read yet. It decides whether capture can
catch audio breaking up under load.

### What this changes for measuring load

- `#PLAY_PATTERN` is the stress ladder's "play": same engine, scripted.
- `#READ` is **not** a way to read our own counters; a meter needs its own
  channel (a C command added to the same dispatcher is the obvious one: the
  queue and reply function are known).
- `#DUMP_AUDIO` is useful only if recording taps the output; to be read.

### Next, under the emulator

Boot 1.11 with bit `0x20` forced at `0x400cf086`; check the service task is
created and mode 4 selected; then call `0x4011f364` directly with `#HELLO\n`,
`#STATUS\n`, `#READ SYNC_1\n` and capture every `0x400054b4` reply.

## Under the emulator — 2026-09-20

Two harnesses, because the two questions need different setups.

### What maintenance mode starts (`scripts/emu_service_mode.py`)

A cold boot from reset with bit `0x20` forced into `0x40287520` just before the
OS tests it (in the emulator a memory write; on the instrument the bootstrap's
job). Measured:

| | |
|---|---|
| boot flags before the write | `0x4` -- the bit is **not** set on a normal boot |
| USB mode selected | **4** -- the CDC-ACM `PID 0xFFFF` device, against 2/5/6 on a stock boot |
| service task | **created** at 315.7M instructions, entry `0x400cd48e`, priority 2 |
| the task's own body | first ran at 472.3M |

So the static reading holds: maintenance mode is the normal OS plus a USB
serial port and a task listening on it.

**What this harness cannot do, and why.** The service task is priority 2, and
the emulator's semaphore patch means higher-priority tasks never sleep, so it
runs once and starves. It never reaches its queue receive, and no command can
be delivered this way -- checked to 900M instructions (23 min), where the run
ends at the same place as at 500M.

### What it answers (`scripts/emu_service_commands.py`)

So the dispatcher is called directly, as `scripts/emu_arp_plocks.py` calls the
p-lock routines: restore a snapshot, build the command queue in spare RAM with
the line already posted, enter `0x400cd48e` on a synthetic stack. Everything
from there is the firmware's own code -- the comparison chain, the handlers,
the reply function. Ten read-only commands, and it refuses anything that
writes, plays or reboots.

```
#HELLO           -> HOW DO YOU DO?
#STATUS          -> # START / OK / VERSION 1
                    # OS / OK / "0059        1.11"
                    # PLATFORM / OK / PCBA0109A1
                    # PRODUCT / OK / 52;5;15;Digitone II
                    # FLASH / FAIL / WRONG DEVICE TYPE 00 0000
                    # DRAM / OK      # DSP / OK
                    # SUPERCAP / FAIL / SUPERCAP NEVER AT DISCHARGED STATE
                    # UI / FAILED / WRONG UI CARD
                    # MMC / FAIL / WRONG DEVICE TYPE
                    # CODEC / FAIL / NO AUDIO INTERRUPT
#READ SYNC_1     -> 0
#READ_SERIAL     -> NO SERIAL NUMBER
#READ_TESTED     -> 4294967295
#TEST_STATUS     -> WRONG UI CARD / UI TEST NOT PASSED / UI TEST NOT COMPLETED /
                    AUDIO TEST NOT PASSED / FACTORY RESET NOT ARMED FOR NEXT BOOT /
                    MRAM STATE NOT WRITTEN / MMC NOT RECONFIGURED / NOT FACTORY TESTED
#MMC_GET_HEALTH  -> PRE_EOL_INFO 0x00 / DEVICE_LIFE_TIME_EST_TYPE_A 0x00 / ..._B 0x00
#MMC_GET_RECONFIGURED -> FALSE
```

`#HELLO` answering `HOW DO YOU DO?` closes the loop the 1.10E reading opened.

**Read the failures correctly.** FLASH, MMC, CODEC, UI and SUPERCAP fail
because the emulator models none of them; they say nothing about an
instrument. The fields that do not depend on hardware are the interesting ones,
and `%.16s` resolving to `0059        1.11` is **the ELE3 build string plus the
version** (`docs/ele3-format.md`), which independently confirms that the
four-digit number a project declares as its format version is the build number
of the firmware that wrote it.

`#STATUS` carries no serial number, so nothing identifying is in that transcript.

### What is still unexercised

The USB endpoint and the byte receiver's framing: both harnesses start after
them. Their behaviour is read in the code above and not measured.
