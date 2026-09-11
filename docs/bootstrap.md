# The bootstrap, and how recovery flashing actually works

Section 2 of a Digitone II OS file is the **bootstrap**: the code the Early
Start-up Menu runs, and the one that receives and writes a recovery flash. It is
about 30 KB of ColdFire, ships in every `.syx`, and is the reason a modified
MAIN OS can be flashed at all. This is what it does, read from the 1.10E image.

Everything here was read with Ghidra **after** Gate F cleared the section (see
below), so the disassembly is trusted. The decompiler's invented names
(`FUN_…`, `_DAT_…`) are kept; where a name is asserted it says so.

## Gate F on the bootstrap — PASSED 2026-09-11

`m68k-linux-gnu-objdump -m m68k:cfv4e` against Ghidra 12.1.3
(`68000:BE:32:Coldfire`), linear, over a 16 KB code span at `0x80011000`:

```
objdump    4,850 instructions
ghidra     4,841 instructions, 4 undecodable
agreement  4,815/4,850  (99.28%)
0 divergences on code; 9 clusters, all on 0x0000 padding words objdump declined
```

Same verdict as MAIN OS (`docs/mainos-image.md`): Ghidra and objdump agree on
every real instruction boundary, disagreeing only where objdump refuses a
`00 00` alignment word and Ghidra decodes it. The bootstrap is cleared for
reading.

## The load base is `0x800003fc`

The header the dnfw tools show comes from the section's own first eight bytes,
`[u32 payload_size = 0x7656][u32 0x80010000]`, and `0x7656 + 8` is the section
length. But `0x80010000` is **not** the load base — it is an entry or stack
value. The real base was found from the code itself: the string
`"BOOTSTRAP UPGRADE"` sits at payload offset `0x602c` and the code addresses it
by the absolute immediate `0x80006430`, so the payload runs at
`0x80006430 − 0x602c = 0x80000404`, and the section including its 8-byte header
at **`0x800003fc`**. Every status string then resolves: `READY TO RECEIVE` at
`0x80006603`, `RECEIVING...` at `0x80006614`, `UPGRADING...` at `0x800065e6`.

An earlier note in this repo guessed `0x02000000` (the ELE3 `dest`) and then
`0x80010000` (the header word); both are wrong for reading the code. Load the
**full section** (with header) at `0x800003fc`.

## Recovery is two phases, and the progress bar is the first one

### Phase 1 — receive (`FUN_80003e5a`, the loop; `FUN_800036f6`, the handler)

The screen shows `READY TO RECEIVE`, then `RECEIVING...` with a bar. The bar is

```
progress = received_packets * 128 / total_packets
```

`total_packets` is the count declared in the SysEx **start marker**
(`info[4..6]`); `received_packets` increments as packets arrive. So the bar
measures reception, not flashing.

The handler runs once per SysEx message:

- **Start marker** (`0x7F`, kind `1`): records the total packet count and the
  starting sequence number, sets state = receiving.
- **Data packet** (`0x7E`): checks the packet's sequence number against a
  running counter, verifies the per-packet checksum over 119 bytes, copies the
  101 decoded bytes into the receive buffer, increments the counter, and
  updates the progress globals.
- **End marker** (kind `2`): verifies the totals and sets state = done.

### Phase 2 — write (`FUN_80003c9c`)

When reception is done the screen shows `UPGRADING... / DO NOT TURN OFF` and:

1. A whole-container checksum: over `container_size / 4` words at `0x40000008`,
   `sum += (word_index ^ word)`, compared against the word at `0x40000004`.
   That is **our preamble exactly** — `[u32 size][u32 checksum][container…]`
   received into RAM at `0x40000000`.
2. Erase flash in `0x40000`-byte (256 KB) blocks from `0x80000`.
3. **Copy the raw container to flash** at `0x80000` in `0x200`-byte (512-byte)
   chunks, `(size + 0x1ff) / 0x200` of them, straight from the received bytes.
4. Reset.

**Phase 2 does not decompress anything.** The bootstrap writes the compressed
container to flash as received; sections are decompressed later, on the next
boot, by the updater and MAIN OS. There is no CRC-32 and no per-section size
cap in this path — an earlier note that described one had read a *different*
routine (`FUN_80011844`, which flashes a single small section and does carry a
`0xDEBB20E3` CRC and 64 KB caps; it is not the recovery-container path).

## What this says about the ~80% recovery stall

Two things follow, and they change the diagnosis.

**The padding and match-window fixes are about booting *after* recovery, not
about recovery completing.** Phase 2 copies bytes verbatim; it never
decompresses, so a section that is unpadded or reaches too far back cannot stall
*it*. Those fixes matter when the freshly flashed OS is decompressed on the next
boot — which is a real requirement, just not this stall's cause.

**Reception has no error recovery, and that fits an ~80% freeze.** A data packet
whose sequence number is unexpected, or whose checksum fails, sets the receive
state to 0 and the bar simply stops — no error screen, no retransmit request,
and the transfer is one-way over DIN MIDI at 31,250 baud. A single corrupted
packet anywhere in ~1.7 MB freezes the bar wherever it happened to be.

And the bytes that reception checks — sequence counters and per-packet
checksums — are **content-independent**. For a given packet index our image and
stock carry the same sequence and checksum bytes, because Gate A shows we
reproduce stock's transport byte-for-byte. Stock flashed through this same path.
So nothing reception validates can tell our `gate-d` image apart from stock, and
a stall specific to our image has no mechanism here.

The leading explanation is therefore **a transmission error over DIN MIDI**, not
a defect in the image — consistent with stock itself needing three send attempts
in the same session (`docs/flashing.md`). This is inference from the code, not
proof: the clean test is to re-send **stock** through recovery and see whether
it, too, stalls intermittently.

## What has not been read

- `FUN_80003688` (reconstructs the sequence number from three bytes) and
  `FUN_800036a6` (the 101-byte payload copy) were used but not traced; the
  claim that our sequence encoding matches the device's expectation rests on
  Gate A, not on reading these.
- The reset mechanism (`_DAT_48000000 = 0; DAT_ec090000 = 0x80`) is noted, not
  understood.
- Everything here is the 1.10E bootstrap. 1.10E to 1.11 moved the bootstrap
  again (`docs/os-versions.md`); none of the addresses carry over.
