# The sections of a Digitone II OS file, all in one place

**Asked 2026-09-17.** A user reported that "section 3 is maintenance mode"; the
owner asked how the sections are named and to document all of it. This page is
the index; each row links to the deeper reading. Measured on **Digitone II OS
1.11** (build `0059`) unless a row says otherwise.

## How the sections are named — and who named them

**Elektron name none of them.** The ELE3 container stores, per section, only a
numeric **id**, an offset, a stored length and a `dest` value
(`docs/ele3-format.md`). There are no name strings in the file.

Every name used in this project is a **label** (`src/dnfw/container/ele3.py`,
`NAMES`), and the code says so: *"Labels, not ground truth."* They come from
`elektron-firmware-tool`'s `format.h`, corrected where reading the bytes proved
a label wrong:

| id | label | origin of the label |
|---|---|---|
| 1 | FPGA | `format.h`; no DN2 file carries this id |
| 2 | bootstrap | `format.h` said **DSP** — wrong; renamed upstream and here on 2026-09-08/11 from its content |
| 3 | MAIN OS | `format.h` |
| 4 | updater | `format.h` |
| 5 | meta | `format.h` |
| 6 | boot | `format.h`; seen only in DN1 images |
| 7 | blob | `format.h`; it is in fact the **SHARC DSP program** (`docs/sharc-image.md`) — the label stayed for compatibility |
| 8 | *(none, `?`)* | new in 1.11; not in `format.h` |

So "section 3 is X" statements depend on whose numbering and labels are meant;
this project's "section 3" is **container id 3**.

## What each section is

| id | label | stored | unpacked | loads at | processor | what it is |
|---|---|---|---|---|---|---|
| 5 | meta | 15 B raw | — | — | — | a build timestamp, ASCII: `260908 14:25:18` |
| 2 | bootstrap | 16,176 B aPLib | 30,302 B | ELE3 dest `0x02010000`, runs at `0x800003fc` | ColdFire | **the recovery receiver** and the **Early Start-up Menu** |
| 3 | MAIN OS | 1,130,528 B aPLib | 3,192,192 B | `0x40000400` | ColdFire V4e | **the instrument's operating system** — UI, sequencer, parameter tables, LFO engine, +Drive, MIDI, and a maintenance mode |
| 4 | updater | 32,776 B raw | — | `0x80000400` (fast SRAM) | ColdFire | a small loader: RAM initialisation and test, device check, a serial console |
| 7 | blob | 602,076 B aPLib | 836,956 B | pushed to the DSP over SPI | ADI SHARC | **the DSP program** — an ADI boot stream built on FreeRTOS for SHARC |
| 8 | — | 103,416 B aPLib | 159,948 B | its own flash window `0x60040000` | ARM Cortex-M | **firmware for another processor**, byte-identical in Digitakt mk1 1.53 — a shared accessory, most likely the Outbox (inferred) |

### id 2 — bootstrap: the Early Start-up Menu

Its strings are the menu you reach by holding FUNC at power-on:

```
STARTUP MENU
1 ... TEST MODE
2 ... EMPTY RESET
3 ... FACTORY RESET
4 ... OS UPGRADE
5 ... EXIT
```

plus `BOOTSTRAP UPGRADE`, `READY TO RECEIVE`, `RECEIVING...`, `UPGRADING...`,
`DO NOT TURN OFF!`, `LENGTH ERROR`, `CRC CHECK`, `VERSION CHECK`,
`UPGRADE FAILED`, `KEY TEST`, `ENCODER TEST`, `LED COLOR LOCK (PRESS FUNC)`, and
the HMAC key string. **Menu item 3 here is FACTORY RESET**, a different "3" from
container section 3 — a plausible source of confusion. Recovery flashing, its
two phases and the ~80% stall: `docs/bootstrap.md`.

### id 3 — MAIN OS, and its maintenance mode

Everything the instrument does in normal use runs from here. Every change this
project has flashed into id 3 appeared in normal operation — new LFO waveforms on
every track, the arpeggiator menu on MIDI tracks, the boot animation
(`docs/flashing.md`). Its internals: `docs/mainos-image.md`, `docs/memory-map.md`.

**It also contains a maintenance mode, as one feature among many** — the word
appears in id 3 and **in no other section**:

| string | where | what it shows |
|---|---|---|
| `MAINTENANCE MODE` | `0x40213ce8`, used by code at `0x4002f02a` | a status message, listed with `Factory reset`, `Update MMC Caches`, `MMC NOT IN SLC MODE`, `Screenshot` |
| `#REBOOT_INTO_MAINTENANCE_MODE` | `0x4021acc6` | a service command, beside `#MMCDUMP`, `#REBOOT`, `#PLAY_PATTERN`, `#STOP_PATTERN`, `#START_UI_TEST` (`docs/service-commands.md`) |
| `MAINTENANCE` | `0x4022969a` | a word in an unrelated dictionary list (`LIGHTWEIGHT`, `LIQUIDATION`, `MALAPROPISM`, …) — name generation, not the mode |

So maintenance mode is **a mode of the main OS**, entered by a reboot command,
not a separate section. What it does once entered has **not been traced**. The
service commands around it include writes this project never sends
(`#WRITE_SERIAL`, `#WRITE`, `#MMC_RECONFIGURE`); read, never trigger.

### id 4 — updater

32,768 bytes of ColdFire code loaded into fast SRAM. Its strings: `#HELLO`,
`HOWDY HO!`, `#STATUS`, `VERSION 1`, `PLATFORM`, `PCBA0109%c%d`,
`WRONG DEVICE TYPE %02x %04x`, `DRAM INITIALIZATION TIMEOUT`,
`DATA CORRUPTION AT ADDRESS %08x`, `CLEARING %x`, and `ELE3`. That reads as a
bring-up loader — SDRAM initialisation and a memory test, a device-type check, a
minimal serial console that knows the container format. **Inferred from strings;
its code is not read.** The Digitakt II's updater differs from the DN2's in one
byte (`docs/chimera-feasibility.md`).

### id 7 — blob, the SHARC program

Once believed to be "mixed data, substantially float32" — **superseded**. It is
an ADI boot stream for the SHARC DSP, uploaded by MAIN OS over SPI at start-up;
the FM drum transient samples live in it, which is what the Transient Swapper
replaces. `docs/sharc-image.md`, `docs/sharc-code-map.md`, `docs/tran-mapping.md`.

### id 8 — the other processor's firmware

A Cortex-M vector table at offset `0x2000`, descriptors naming a 1 MB flash window
at `0x60000000`, and **the same bytes (SHA-256) inside Digitakt mk1 OS 1.53**. Not
DN2 code, claims no ColdFire address space; deleting it would strand whatever
accessory it updates. `docs/data-sections.md`.

## Where each mod writes

All three browser/CLI mods that touch code write **id 3** (the Transient Swapper
writes id 7). None writes ids 2, 4, 5 or 8. `docs/memory-map.md`, `docs/mods.md`.
