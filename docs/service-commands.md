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

## What would settle it

Three things, in order, and none of them needs a write:

1. **Find the parser.** The commands are `#`-prefixed text with `%s`/`%d`
   arguments, so there is a dispatch table or a chain of string compares near
   `0x402020ad`. Finding it names the transport by naming its caller. Ghidra is
   cleared for this work now (`docs/mainos-image.md`).
2. **Work out the transport.** Candidates are the USB port, a debug UART, and
   SysEx — the literal `ELE3` beside `#UPGRADE` hints this interface can carry
   an OS image, which is suggestive of the same path the Early Start-up Menu
   uses. It is a guess until the parser says otherwise.
3. **Then, and only then, try `#HELLO`.** It takes no arguments, changes
   nothing, and a reply of `HOW DO YOU DO?` would confirm the whole picture at
   zero risk.

`dnfw` has no MIDI or USB I/O and is not the place to add it — it is an offline
image tool. DNX already has device I/O and a written-down discipline for
probing safely (`DNX/docs/device-probing.md`), which is where this belongs if
it is pursued.
