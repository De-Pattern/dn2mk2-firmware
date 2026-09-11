# Flashing, and getting back

**Step 1 is done: the way back is proven.** The rest of the procedure was
written before it was needed, which is the point of it. Results are recorded
here as they happen, with dates.

## The order, and why it is this order

Each step fails differently from the one before it. Run them in order and a
failure tells you which part is wrong.

### 0. Back up the +Drive — before anything

Use DNX's `.dnx` backup. Firmware and user data are separate, and a firmware
flash should not touch projects — but "should not" is not a backup.

### 1. Prove the way back, with stock firmware — DONE 2026-09-08

**This gated every other hardware step, and it passed.** Stock
`Digitone_II_OS1.10E.syx` was sent to a Digitone II through the Early Start-up
Menu; the transfer reached 100%, the device rebooted, and it came up normally.

The route, as actually used:

1. Hold **`FUNC`** while powering the instrument on to reach the **Early
   Start-up Menu**, then press **`TRIG 4`** to select **OS UPGRADE**.
2. Connect the computer's MIDI **OUT** to the device's MIDI **IN** with a DIN
   cable. **USB MIDI does not work for this** — Elektron's own transfer tool
   says so, and the bootloader only listens on the DIN port.
3. Send the `.syx` with Elektron Transfer's **SysEx Transfer** window, which
   shows "Recovery mode" and a percentage.
4. The device shows `RECEIVING...` with a progress bar while it runs.

Interface used: a Focusrite USB MIDI interface.

**It is slow, and that is arithmetic rather than a fault.** MIDI DIN runs at
31,250 baud, ten bits to the byte, so 3,125 bytes per second. The 2,209,184-byte
image therefore cannot take less than **about 12 minutes**, and will take
somewhat longer. That figure is derived, not measured — the actual duration was
not timed. Do not interrupt it.

**Why this matters more than it looks.** This route lives in the bootloader,
not in MAIN OS, so it still works when a MAIN OS we built does not. It is the
reason anything modified can be flashed at all.

### 2. Gate D — a rebuild that changes nothing

```
dnfw build 00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip -o gate-d.syx
```

Byte-identical to stock, so this proves nothing on its own. Instead extract and
rebuild MAIN OS so the compressed bytes differ while the code does not:

```
dnfw extract <image> --section 3 -o out/
dnfw build <image> -s 3=out/section_3_MAIN_OS.aplib.bin -o gate-d.syx
```

Same code, different stream, valid checksums, valid HMAC. **If it boots, the
repack-and-sign pipeline is accepted by the device.** If it does not, the fault
is in packing or signing — nothing else changed.

### 3. Gate E — a patch you can see

```
dnfw patch apply 00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip -o gate-e.syx
```

Renames `SETTINGS > PERSONALIZE` to `DNFW ALIVE!`. Flash it, open SETTINGS,
photograph the screen.

That closes Phase 1: unpack, modify, repack, re-sign, flash, observe, as a loop
that can be run again.

**Both passed, through the normal update path** — Transfer's drop over USB to
a running instrument, not the Early Start-up Menu. Gate D booted and behaved as
stock; Gate E booted and `SETTINGS` shows `DNFW ALIVE!`. Phase 1 is closed.

## Two routes, and they are not equally forgiving

| | Normal update | Recovery |
|---|---|---|
| how | Transfer, drag the `.syx` onto a running device over USB | Early Start-up Menu, `TRIG 4`, DIN MIDI |
| who receives | the running MAIN OS | the **bootstrap** — section 2 of the last OS flashed |
| works when MAIN OS is broken | no | **yes — the only route that does** |
| accepted Gates D and E | **yes** | **no — stalls at ~80%** |

The recovery route is the one that matters if a build ever fails to boot, so an
image that only the normal route accepts is not safe to experiment with.

## Recovery stalls on our images — OPEN

Reported 2026-09-11. Stock 1.10E through the Early Start-up Menu completes
(2026-09-08). Gates D and E through the same route: Transfer reports 100% sent,
the device's own bar stops at about 80% and stays there. No error text was
reported — and the bootstrap has named failures (`LENGTH ERROR`, `CRC CHECK`,
`VERSION CHECK`, `UPGRADE FAILED`), so a silent stop suggests a hang rather
than a rejection.

**Two differences from stock were found** that no checksum and no HMAC notices.
Both are now fixed and enforced by `dnfw inspect`:

1. **Unpadded section.** Elektron pad every compressed section to a multiple of
   four bytes; our MAIN OS was 1,093,374 bytes stored, two past a boundary. A
   word-at-a-time copy counting its length down in fours never reaches zero on
   that — which would hang, silently. *This is the stronger candidate.*
2. **No match window.** Elektron's streams never reach back more than 1 MiB;
   ours reached 3 MB back in 2,051 places. A bootstrap that decompresses through
   a 1 MiB buffer would read garbage there. *But* the first far match sits 24.8%
   into the upload, and the stall is at ~80%, so on its own this does not
   explain where the device stops — if its bar tracks bytes received.

Both reproduce against the exact file that was flashed: rebuilding Gate D from
`main` gives content checksum `0x6303af0e`, the one recorded before the flash,
and the new checks fail it on both counts.

**Next test:** `gate-d2_DN2_1.10E_recompressed.syx` (content checksum
`0x716ce858`) through the Early Start-up Menu. It fixes both at once, because
the goal is a recovery route that works for our images; which of the two
mattered can be split afterwards with one image carrying each fix, if it is
worth two more twelve-minute transfers.

**If it still stalls,** stop guessing and read the bootstrap. It ships in every
`.syx` as section 2 — about 30 KB of ColdFire, strings intact — and it is the
code that receives, checks and writes a recovery image. It needs the validated
Ghidra setup (`docs/mainos-image.md`, Gate F), which lives on the machine with
WSL and objdump.

### A first look at the flash routine — 2026-09-11, PRE–GATE-F

Ghidra now runs on the flashing-less machine (`docs/mainos-image.md`), and a
first decompile of the bootstrap was taken. **It is not yet trustworthy**: Gate
F has not cleared this section, and the load base is not pinned (references
reach below the tried base of `0x80010000`, so the payload very likely loads
lower). Recorded as a lead, not a fact.

The section-flashing routine reads: read a section, decompress it to RAM,
**CRC-32 it** — the compare constant is `0xDEBB20E3`, the standard CRC-32
residue, the same one the serial record uses — a **version check**, then erase
and program flash in **512-byte chunks** with a percentage bar. It carries two
hard size caps (`< 0x10001` compressed, `< 0xf001` decompressed), so *this*
routine flashes a small section, not the 3 MB MAIN OS. **The large-section path
is the one that stalls at ~80% and is the one to read** — after Gate F clears
the section and the load base is fixed.

If the CRC is computed the way the caps suggest — a running residue to
`0xDEBB20E3` over the decompressed bytes — then a decompressor that produced
even one wrong byte (a far match past a small window, say) would fail the CRC,
not hang. A hang points instead at the copy or decompress step never
terminating, which is where the unpadded-length hypothesis lives.


## When Transfer will not send

Elektron Transfer logs to
`%APPDATA%\Elektron Overbridge\Transfer.log`. **Read it before suspecting the
image** — on 2026-09-08 a stalled send was diagnosed there in one look.

The failure looked like a rejected file: the SysEx Transfer window showed no
progress bar and no percentage, while stock firmware sent normally from the same
window, same cable, same port. The log said otherwise:

```
14:45:29  Trying to send OS for Unknown
14:45:48  error Couldn't open midi output due to exception: MIDI Device already in use
```

Two things to take from it.

**The port is the usual fault, not the file.** A send that hangs leaves the MIDI
output open, so every retry afterwards fails with `MIDI Device already in use`
until Transfer is restarted.

**Transfer does not validate the image.** It logs
`This syx is for Unknown, not Model:Cycles` for a **stock** Digitone II OS file
exactly as it does for one we built — it recognises neither, and sends both. So
Transfer accepting a file is not evidence the file is good, and Transfer
stalling on one is not evidence the file is bad.

**Clicking Send once is not enough.** In the same session stock needed three
attempts before the log showed streaming begin. If no progress appears within a
second or two, click Send again; if that fails, restart Transfer.

Streaming is visible in the log as a run of
`Waiting for: 41.96 milliseconds in legacy sysex send` — one per 128-byte
packet, which is DIN MIDI's rate and confirms the transfer is genuinely moving.

## Standing rules

- **Verify before sending.** `dnfw inspect` on the file you are about to flash.
  `build` and `patch apply` already refuse to write anything that does not
  verify, but the file that reaches the instrument is the one to check.
- **One change at a time.** Gate D and Gate E are separate flashes on purpose.
- **Keep stock to hand.** The unmodified `.syx` is the recovery image; it stays
  in `00_Resources/00_Firmware/` and is never overwritten by a build output.
- **Do not patch the key material.** See `docs/ele3-format.md` §5.

## Record

| Date | Step | Result |
|---|---|---|
| 2026-09-08 | Recovery path, stock 1.10E via Early Start-up Menu | **Pass.** Transfer reached 100%, device rebooted, came up normally. |
| 2026-09-11 (reported) | Gate D — recompressed, unchanged, **normal update** | **Pass.** Boots, behaves as stock. |
| 2026-09-11 (reported) | Gate E — the PERSONALIZE patch, **normal update** | **Pass.** `SETTINGS` shows `DNFW ALIVE!`. |
| 2026-09-11 (reported) | Gates D and E through the **recovery** route | **Stall.** Transfer 100%, device bar ~80%, no error text. See above. |
| | Gate D2 — padded and windowed, **recovery** route | not yet |
