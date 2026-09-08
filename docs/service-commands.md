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

## What `#READ_SERIAL` gives back

The format strings sitting immediately after it:

```
#READ_SERIAL
%.14s
SERIAL NUMBER CRC ERROR
NO SERIAL NUMBER
```

So a **14-character serial**, CRC-protected, and two failure replies for a bad
checksum and for an unprogrammed unit.

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

## What would settle it

1. **Follow `0x40111264` and `0x40110fe2`** into the `0x4011xxxx` region to find
   what registers `0x400cf906`. That names the transport.
2. **Confirm or refute the serial reading** — if it is a UART, there should be
   a baud rate and a pin configuration near the driver.
3. **Then, and only then, `#HELLO`.** It takes no arguments, changes nothing,
   and a reply of `HOW DO YOU DO?` would confirm the whole picture at zero risk.

`dnfw` has no MIDI or USB I/O and is not the place to add it — it is an offline
image tool. DNX already has device I/O and a written-down discipline for
probing safely (`DNX/docs/device-probing.md`), which is where this belongs if
it is pursued.
