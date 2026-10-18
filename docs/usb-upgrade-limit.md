# The USB upgrade's 2 MiB limit (found 2026-10-18)

**What happened.** v0.7 (CZ) sent from Elektron Transfer over USB stalled at the same
point twice, with the bar full and a fraction of a second left; stock 1.11 went
through the same route at once (owner, 2026-10-18). The file was intact (sha256
matched).

**Why.** Transfer's USB route is the running OS's `OsUpgradeStart / Write / End` RPC
(`docs/midi-rpc.md`). `Write` (`0x40129c56`) appends the raw SysEx and hands each
complete message to the packet processor `0x4012229c`, the same protocol the
bootstrap speaks (`docs/bootstrap.md`). For a `0x7E` data packet it checks the
sequence number and the 7-bit checksum, then decodes 101 bytes to

    receive state 0x4038aec0 (from 0x40122294) + 20 + 101 x packet index

with **no bound** on the index other than the packet count the start marker declares.
The next global after the state is at `0x4058aee0`, so the buffer is `0x200000`
bytes. An image whose data packets decode to more than that writes past it into
other globals of the running OS, which stops answering before the end marker.

| image | decoded bytes | vs 2 MiB |
|---|---|---|
| stock 1.11 | 1,885,266 | +211,886 |
| v0.3 Waverider W2 | 2,095,952 | +1,200 |
| v0.4 PING .. v0.6 RESONATOR | 2,103,xxx .. 2,108,xxx | over |
| v0.7 CZ | 2,112,819 | **-15,667** |
| v0.8 (BITS and PHAS dropped) | 2,076,863 | +20,289 |

**What it did to the unit.** Nothing in flash: the image is written only after the
end marker, which never came. The overrun is in RAM and a power cycle clears it; stock
1.11 installed normally afterwards.

**The rule now.** `dnfw.safety.build_checks` refuses any image whose data packets
decode to more than `0x200000` bytes ("image fits the 2 MiB USB upgrade buffer"), and
the check fails closed if the image is not SysEx. The ship gate's preflight runs it,
so no larger build can be cleared.

**The flash slot.** The image is written to SPI NOR from `0x80000`, erased in 256 KB
blocks (`docs/bootstrap.md`). `0x80000 + 2 MiB = 0x280000` is a whole number of those
blocks; the 2 MiB receive buffer is consistent with a 2 MiB firmware slot, and the
same bound keeps an image inside it. What lies above `0x280000` in flash is still
unmeasured (`docs/hardware.md`, "Open"), which is one more reason the bound is hard.

**Budget from here.** 20 KB under the line with CZ in. Every new feature now has to
pay for itself in image size: a Waverider table is about 9 KB of image, the wave
display's spans for it about 3 KB more.
