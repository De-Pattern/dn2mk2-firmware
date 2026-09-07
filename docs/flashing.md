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
| | Gate D — recompressed, unchanged | not yet |
| | Gate E — the PERSONALIZE patch | not yet |
