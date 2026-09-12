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

## The recovery stall was the MIDI link, not the image — 2026-09-11

Reported and diagnosed the same day. Gates D and E through the Early Start-up
Menu stalled: Transfer reported 100% sent, the device's `RECEIVING...` bar stuck
at about 80% with no error text. **Then stock 1.10E, re-sent through the same
route, stalled too** — the image that flashed cleanly on 2026-09-08. That is the
result that settles it: the fault is the transfer, not anything we built.

The bootstrap disassembly says why a bad link looks exactly like this
(`docs/bootstrap.md`). Reception has **no error recovery**: a data packet whose
sequence number is unexpected, or whose checksum fails, sets the receive state
to 0 and the bar simply freezes — no error screen, no retransmit, one-way over
DIN MIDI at 31,250 baud. A single corrupted packet anywhere in ~1.7 MB stops the
bar where it happened to be. And the bytes reception checks are sequence
counters and per-packet checksums, which are **content-independent** — Gate A
shows our transport is byte-for-byte stock's — so nothing there can tell our
image from stock. Stock stalling proves the mechanism is the link.

**What to do about it — and what it turned out to be.** Treat recovery as needing
a clean MIDI path: prove the link with **stock** first, and only once stock
completes is a modified image worth sending. On 2026-09-11 the specific cause was
found — the sends were going through a **Focusrite Scarlett 4i4**'s MIDI, and the
interface was going idle part-way through the twelve-minute transfer, dropping
packets (which is why it stalled at a different percentage each time). Stock 1.11
then flashed through recovery cleanly over a fixed link and the device booted it.
For a long recovery transfer, prefer a dedicated class-compliant USB-MIDI cable,
or stop the interface idling (Windows USB selective suspend off, the device's
power-management off). Until the link is proven, do not flash anything through
recovery that the device cannot already boot without.

**The padding and window fixes still matter, for a different reason.** They are
not about recovery *completing* — Phase 2 of the flash copies the container to
flash verbatim and never decompresses (`docs/bootstrap.md`). They are about the
next **boot**, when the freshly written OS is decompressed from flash. An
unpadded or over-reaching section could fail there. So `gate-d2`
(`0x716ce858`) remains the image to flash, once the link is proven — the fix is
correct, it was simply aimed at the wrong stage of the story at first.

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
| 2026-09-11 | **Stock 1.10E** re-sent through the **recovery** route | **Stall too**, ~80%. First sign the stall is the link, not the image. |
| 2026-09-11 | Recovery sends over a **Scarlett 4i4** MIDI interface | **Stall, varying %** (30/70/80). The interface was going idle mid-transfer, dropping packets. |
| 2026-09-11 | **Stock 1.11** through recovery over a **fixed link** | **Pass.** Reached 100%, rebooted, device boots 1.11. Recovery is sound; the culprit was the interface. |
| 2026-09-12 | **Mod-mask test** (`modmask-test_DN2_1.11.syx`) — two 4-byte writes opening Portamento Time and the AMP envelope Delay Time to modulation | **Pass, and the hypothesis confirmed.** `PORT Portamento Time` appears in MOD1's destination list **and is actually modulated**. First functional firmware modification. See `docs/modulation-mask.md`. |

This is the project's **first functional firmware modification** — Gate E changed
a string, this changed what the instrument can do.
| 2026-09-12 | **Expanded mod-destination test** (`moddest-expand_DN2_1.11.syx`) — 32 mask flips in three groups | **Pass, prediction confirmed.** All 13 Group A (per-voice) parameters appear as destinations; **none** of Group B (Chorus) or C (Master). The enumeration, not the mask, is the gate for global parameters. |
| 2026-09-12 | **LFO4 probe** (`lfo4-probe_DN2_1.11.syx`) — LFO3 re-pointed from engine lane 3 to the reserved lane 4 (engine indices 4, 8, 12, 16, 20, 24, 28, 32) | **Pass — and it is the project's central result.** LFO3 still modulates. **The audio engine implements a fourth LFO**; the reserved lane is live, not layout. See `docs/engine-index-map.md` §11. |
| 2026-09-12 | **Coexistence probe** (`lfo4-probe-lfo2_DN2_1.11.syx`) — LFO2 re-pointed to the reserved lane, LFO1 and LFO3 left on lanes 1 and 3 | **Pass. The engine side is closed.** LFO2 (lane 4) and LFO3 (lane 3) modulate **independently and simultaneously**. Lane 4 is a separate generator, not an alias — **four LFOs can run at once**. See `docs/engine-index-map.md` §14. |
| 2026-09-12 | **Coexistence probe** (`lfo4-probe-lfo2_DN2_1.11.syx`) — LFO2 re-pointed to the reserved lane, LFO1 and LFO3 left on lanes 1 and 3 | **Pass. The engine side is now closed.** LFO2 (lane 4) and LFO3 (lane 3) modulate **independently and simultaneously**. Lane 4 is a separate generator, not an alias — **four LFOs can run at once**. See `docs/engine-index-map.md` §14. |

