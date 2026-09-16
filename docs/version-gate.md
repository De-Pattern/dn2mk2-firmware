
# The OS-upgrade version gate

`docs/STATUS.md` carried an open item from 2026-09-15: *"Is there a
minimum-version gate on the DN2?"* — lalzart records MAIN validating a content
checksum, **minimum version** and the cryptographic trailer before erase and
program, and nothing here had checked it.

**2026-09-16: answered, and the answer is not the one the string pool suggests.**

> **The DN2 has no minimum-version gate. DN2 1.11's OS-upgrade validator does
> exactly two things — a content checksum and the HMAC-SHA256 trailer — and has
> no version comparison of any kind. The `Unsupported downgrade` string is in
> the image but no code path can reach it.**
>
> **The gate is real, and we have read it — on the siblings.** Digitakt II 1.16
> and Digitone 1.43 carry it in the same slot in the same function, and it is a
> **hard-coded build-number floor**, not a comparison against the resident
> version. Syntakt 1.41, like the DN2, does not have one.

## 1. The code space

Upgrade validation across all four products returns a code in `1..6`, rendered
by two separate mappers that agree:

| code | error table `0x40208748` (index = code − 1) | UI mapper `0x40109598` |
|---|---|---|
| 1 | `No error` | *(success, no message)* |
| 2 | `Checksum failed` | `Missing data!` |
| 3 | `Checksum failed` | `Checksum error!` |
| 4 | `Checksum failed` | `Checksum error!` |
| 5 | `Power adapter must be connected` | `No power adapter` |
| 6 | **`Unsupported downgrade`** | **`Downgrade not possible`** |

Both are six-entry tables bounded by a `moveq #5` before the lookup. The error
table is referenced from exactly **one** site in the whole image
(`0x40129e72`), and the UI mapper dispatches on `arg − 1` over the same range.
So code 6 is the only way to say "downgrade", and it has to come out of the
validator.

The same table, entry for entry, is present in every image checked:

| image | table | validator |
|---|---|---|
| DN2 1.11 | `0x40208748` | `0x400dbc4c` |
| DT2 1.16 | `0x4021f6fc` | `0x400d9e4c` |
| Syntakt 1.41 | `0x40242c98` | `0x400a5ba8` |
| DN1 1.43 | `0x401ce9f0` | `0x400a003c` |

Every one of them is called the same way — `pea %fp@(32)` then `jsr` — from an
OS-upgrade receive state machine of identical shape.

## 2. What the DN2's validator actually does

`0x400dbc4c` is 52 bytes, and this is all of it:

```
0x400dbc4e  moveal %sp@(8),%a2
0x400dbc52  movel %a2,%sp@-
0x400dbc54  jsr 0x40122418      ; content checksum
0x400dbc5c  tstl %d0
0x400dbc5e  beqs 0x400dbc76     ;   zero -> return 3
0x400dbc60  movel %a2@,%sp@-    ; stream length
0x400dbc62  pea %a2@(8)         ; container start
0x400dbc66  jsr 0x400d2a60      ; HMAC-SHA256 trailer
0x400dbc6e  tstb %d0
0x400dbc70  bnes 0x400dbc7a     ;   false -> return 4
0x400dbc72  moveq #4,%d0
0x400dbc76  moveq #3,%d0
0x400dbc7a  moveq #1,%d0
```

**Two checks, three possible returns: 1, 3, 4.** Codes 2, 5 and 6 are never
produced. There is no version comparison, no build-string load, no reference to
either version field of the container.

`0x400d2a60` is the trailer verifier, and it is worth naming precisely because
it settles a question open since the project plan:

```
0x400d2a68  pea 0xb             ; 11
0x400d2a6c  pea 0x40210592      ; "Multiplier\0"
0x400d2a80  jsr 0x40134490      ; derive key material
...
0x400d2ad0  lea 0x4021b537,%a1  ; 32-byte constant, XORed into both pads
0x400d2b0a  jsr 0x4011e560      ; digest over (container, length - 32)
0x400d2b1a  ... compare 32 bytes at container + (length - 32)
```

**MAIN OS verifies the HMAC trailer at flash time, over the container minus its
last 32 bytes, keyed from the `"Multiplier"` material.** The plan listed
"whether the bootloader checks the trailer or only the checksums" as an open
question; for the *running-OS* upgrade path it is now answered — it checks.
(The Early Start-up Menu runs the **bootstrap, section 2** — not section 4, and
not this code. That is a separate path; see §6b.)

## 3. The gate, read on the siblings

### Digitakt II 1.16 — `0x400d9e4c`

The same 52-byte function with six extra bytes of gate spliced between the
checksum and the trailer:

```
0x400d9e54  jsr 0x40120a70      ; content checksum
0x400d9e5c  tstl %d0
0x400d9e5e  beqs 0x400d9e72     ;   zero -> return 3
0x400d9e60  movel %a2@,%d0      ; stream length
0x400d9e62  movel #0x3030362F,%d1      ; "006/"
0x400d9e68  cmpl %a2@(16),%d1          ; vs the image's BUILD STRING
0x400d9e6c  bcss 0x400d9e76            ;   "006/" < build -> continue
0x400d9e6e  moveq #6,%d0               ;   else -> Unsupported downgrade
0x400d9e76  ... trailer check as before
```

`%a2` is the 8-byte stream preamble, so `%a2@(16)` is the container's **build
string** at ELE3 `+0x08` — four ASCII digits read as a big-endian u32.

`"006/"` is `0x3030362F`. `'/'` is `0x2F`, one below `'0'`, so *"strictly
greater than `006/`"* is how a compiler writes **"build ≥ 0060"**.

**This is a floor, not a comparison.** Nothing reads the resident firmware's
version. A DT2 refuses any image built before 0060 and accepts every image
built at or after it, no matter what is currently installed.

Measured build strings, and how they fare against that literal:

| image | header byte 8 | build (ELE3 `+0x08`) | version (`+0x13`, 5 bytes) | vs `"006/"` |
|---|---|---|---|---|
| DN2 1.11 | `0x10` | `0059` | `" 1.11"` | below |
| DN2 1.10E | `0x10` | `0050` | `"1.10E"` | below |
| DT2 1.16 | `0x0f` | `0079` | `" 1.16"` | **passes** |
| DN1 1.43 | `0x08` | `0104` | `" 1.43"` | passes |

(The version field is 5 bytes wide and right-justified, which is why 1.10E's
`"1.10E"` fills it and 1.11's `" 1.11"` is space-padded. `docs/ele3-format.md`
says `0x13`, and `0x13` is correct — checked here because it looked like an
off-by-one and is not.)

### Digitone 1.43 — `0x400a003c`

The richest version of the same thing: **three** floors, selected by hardware
variant.

```
0x400a007c  moveq #21,%d0
0x400a007e  cmpl %a0@,%d0              ; product discriminator
0x400a0082  movel 0x402292f0,%d0
0x400a0088  andil #524288,%d0          ; variant flag (bit 19)
...
0x400a00a8  movel #"0022",%d1  ; cmpl %a2@(16) -> below: return 6
0x400a00b8  movel #"0025",%d3  ; cmpl %a2@(16) -> below: return 6
0x400a01a2  movel #"0072",%d1  ; cmpl %a2@(16) -> below: return 6
0x400a0200  moveq #6,%d0               ; Unsupported downgrade
```

Bit 19 of the global at `0x402292f0` is almost certainly Digitone vs Digitone
Keys — the two variants that share this firmware — and each gets its own floor.
Not chased further; DN1 is not this project's target.

### Syntakt 1.41 — `0x400a5ba8`

No build-string comparison. It has the checksum, the trailer, and a pair of
hardware-identity checks (`#157`, `#24599`) that DN1 also carries, but nothing
that reads a version or build field. Like the DN2, its `Unsupported downgrade`
string is unreachable.

**So two of four products ship the gate and two do not.** It is a per-product
decision Elektron makes per release, not a platform property — which means
*absence on DN2 1.11 says nothing about DN2 1.12*.

## 4. `Incompatible OS` is a different check, and it is not about versions

This was the most promising wrong lead, so it is recorded rather than deleted.

The upgrade receive state machine `0x40129c56` dispatches seven ways on the
return of the SysEx packet parser `0x4012229c`:

| parser code | outcome |
|---|---|
| 0 | valid end-of-stream → run the validator `0x400dbc4c` |
| 1 | packet accepted, continue |
| 2 | `Invalid header byte` |
| 3 | `Invalid tail byte` |
| 4 | `Invalid checksum` |
| 5 | **`Incompatible OS`** |
| 6 | `Invalid file contents` |
| >6 | `Unexpected decoding error` |

Code 5 comes from exactly one place:

```
0x4012237a  mvzb %a3@(8),%d0    ; byte 8 of the header packet
0x4012237e  moveq #16,%d1
0x40122380  cmpl %d0,%d1
0x40122382  bnew 0x40122408     ; != 16 -> return 5 -> "Incompatible OS"
```

Byte 8 of the header packet is an **OS-stream product id**, and it is not the
transport device id at byte 4:

| product | byte 4 (transport id) | byte 8 (OS-stream id) |
|---|---|---|
| Digitone II | `0x15` | `0x10` |
| Digitakt II | `0x14` | `0x0f` |
| Syntakt | `0x16` | `0x11` |
| Digitone 1 | `0x0d` | `0x08` |

So `Incompatible OS` means **"this is another machine's firmware"**. It fires
on the wrong *product*, never on the wrong *version*. Chasing it as the
downgrade gate was a dead end, and it stays here so it is not chased again.

## 5. The upgrade stream, as the parser sees it

Established while reading the above, and reusable.

**Framing.** One 16-byte header packet, N × 128-byte data packets, one 16-byte
trailer packet. DN2 1.11 is 18,668 packets.

```
header:   f0 00 20 3c 15 00 7f 01 10 <seq0:3> <count:3> <sum> f7
data:     f0 00 20 3c 15 00 7e <seq:3> <116 bytes, 8-in-7> <sum> f7
trailer:  f0 00 20 3c 15 00 7f 02 10 <seq0:3> <count:3> <sum> f7
```

Byte 6 selects the path: `0x7e` is data, anything else is control, and then
byte 7 is `1` for header and `2` for trailer. Three-byte fields are
`(b0 << 14) + (b1 << 7) + b2` (decoder at `0x40122224`). DN2 1.11's header
gives `seq0 = 242` and `count = 18666`; `seq0` is 242 on every product's image
and looks like a fixed stream-type id.

**Decoder state** lives at a fixed address — `0x4038AEC0` on DN2 1.11, returned
by the one-instruction accessor `0x40122294`:

| offset | field |
|---|---|
| `+0` | state: 0 idle, 1 receiving, 2 complete, 3 validated |
| `+1` | the OS-stream product id from header byte 8 |
| `+4` | `seq0` |
| `+8` | expected packet count |
| `+12` | packets received |
| `+16` | next expected sequence number |
| `+32` | the decoded byte stream |

**The stream** is an 8-byte preamble — `u32 length`, `u32 byte sum` — followed
by the ELE3 container. The validator is handed `state + 32`, so its `%a2@` is
the length, `%a2@(8)` is the container, and `%a2@(16)` is the build string.

## 6. What this changes for us

- **DN2 1.11 will accept an older stock image.** Nothing in its upgrade path
  compares versions. The recovery route in `docs/flashing.md` is not at risk
  from a version gate on this build. *Not tested on hardware* — this is a claim
  about the code, and the safest reading is "no gate found in the only path
  that could enforce one".
- **It does not follow that this holds for future DN2 releases.** DT2 and DN1
  ship the gate; Elektron adds it per product per release. A DN2 OS that
  introduces a floor above build `0059` would refuse 1.11 afterwards.
- **The trailer is verified on the device.** Our rebuilds must be signed
  correctly, and they are — but this is now a hard requirement read from the
  code, not an assumption.
- **`"Multiplier"` remains untouchable.** `0x400d2a60` is the verifier side of
  the key material `docs/ele3-format.md` §5 says not to patch. Patching it
  would break the very check that lets a rebuild install.

## 6b. The recovery path — partly read, and one claim withdrawn

**[CORRECTED 2026-09-16, same day.]** This document first said the *updater*
(section 4) is the Early Start-up Menu's code and that reading it closed the
recovery question. **Section 4 is not the ESM.** The ESM is owned by the
**bootstrap, section 2** — it holds `STARTUP MENU`, `4 ... OS UPGRADE`,
`READY TO RECEIVE`, `RECEIVING...`, `BOOTSTRAP UPGRADE`, `UPGRADE FAILED`,
`LENGTH ERROR` and `UPGRADE ABORTED`. Section 4 holds none of those. So the
recovery question is **not** closed.

### What section 4 actually is, and what it does establish

A 32 KB service monitor: `#HELLO`, `#STATUS`, `#WRITE`, `START`, `VERSION 1`,
`PLATFORM`, `PCBA0109%c%d`, `FLASH`, `CLEARING %x`, plus diagnostics
(`WRONG DEVICE TYPE %02x %04x`, `DRAM INITIALIZATION TIMEOUT`,
`DATA CORRUPTION AT ADDRESS %08x`). See `docs/service-commands.md`; the standing
rule against sending `#WRITE`, `#WRITE_SERIAL` and `#MMC_RECONFIGURE` applies.

It carries no version, build, downgrade or "incompatible" string anywhere in the
section, and no SHA constants and no `"Multiplier"`. Its one container check is
at `0x80003cf8`:

```
0x80003d0a  movel #0x00080000,%sp@-   ; nonvolatile offset 0x80000
0x80003d10  jsr 0x800048aa            ; read 32 bytes from there
0x80003d1a  movel #'ELE3',%d0
0x80003d20  cmpl 0x8000b3d4,%d0       ; magic
0x80003d28  moveq #52,%d0
0x80003d2a  cmpl 0x8000b3d8,%d0       ; product code == 52 (DN2)
0x80003d32  moveb #1,%d0              ; valid
```

**Magic and product code, and nothing else.** This confirms from our own image
something we had only on lalzart's word: **the staged ELE3 slot begins at
nonvolatile offset `0x80000`**.

### Why the bootstrap has not been read

Section 2 is **position-independent**: no absolute reference to any of its own
strings exists at `0x02010000`, `0x80000400` or any other candidate base. Its
blob also carries a header — `00 00 76 56` (length 30,294) then `0x80010000`,
`0x80000de8`, `0x02010000`, `0`, `0x10380000` — so the payload's load base is
not simply the section `dest`. **The base is not established, so the code has
not been read.** Grep will not settle this one.

Two things bound the worry in the meantime:

- The bootstrap's error vocabulary has **no version or downgrade string**. Weak
  evidence: digikit showed the DT2 bootstrap's gate is a *silent skip*, not a
  message.
- digikit's DT2 bootstrap gate guards **`BOOTSTRAP UPGRADE`** — whether the
  bootstrap rewrites *itself* — not whether an OS image is accepted. Even if the
  DN2 has the same thing, it would decline to replace the bootstrap, not refuse
  the flash. That is the distinction that matters for recovery, and it is
  **assumed, not verified, for the DN2.**

## 7. Still open

1. Who calls the UI mapper `0x40109598`, and with what. It is reached
   indirectly (no absolute `jsr` to it anywhere), so the code it renders may
   come from somewhere other than `0x400dbc4c`. This does not change §2 — the
   error *table* has a single reference — but the UI path is unproven.
2. Codes **2** and **5** are unreachable from `0x400dbc4c` too. Something else
   must produce `Missing data!` and the power-adapter refusal, or they are
   dead on this build as well. Worth one pass, cheap.
3. **The bootstrap (section 2) — the Early Start-up Menu's actual code.** Find
   its load base first; §6b says why grep cannot. Then answer the one question
   that matters for recovery: does its OS-flash path check anything beyond
   length, or is `LENGTH ERROR` the whole of it?
4. DN1's variant flag — bit 19 of `0x402292f0` — is assumed to be Digitone vs
   Digitone Keys and was not verified.

## Superseded

**[SUPERSEDED 2026-09-16 — was the state of this document earlier the same
day.]** It read: *"the gate exists, it is in MAIN OS as lalzart says, and its
failure message is found; the exact comparison is not yet read"*, and inferred
from the presence of `Unsupported downgrade` at table index 5 that the DN2
refuses downgrades. **The string is present; the check is not.** The inference
was from a string table to a behaviour, with the producing comparison never
read — exactly the step §4 above shows going wrong a second time with
`Incompatible OS`. Presence of a message is not evidence of a code path.

lalzart's account was not wrong: they document **Digitakt II 1.15C**, and DT2
is one of the two products that does carry the gate. The error was carrying
their finding across products without checking.
