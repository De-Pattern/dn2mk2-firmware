# The Elektron OS `.syx` format, as measured

Everything here was derived on **2026-09-07** from two files Elektron publish:

- `Digitone_II_OS1.10E.syx` — 2,209,184 bytes
- `Digitone_and_Digitone_Keys_OS1.42A.syx` — 1,397,152 bytes

Field offsets and algorithms are cross-checked against
`mischa85/elektron-firmware-tool` (MIT), which is the reference for the layout.
Where a claim below rests on that repository rather than on our own
measurement, it says so.

Reproduce any of it with `dnfw inspect <image>`.

## Four layers

```
.syx file
  └─ SysEx transport      F0..F7 messages: 2 markers + N data packets
      └─ byte stream      8-byte preamble + container (+ zero padding)
          └─ ELE3 container   header, section table, sections, trailer
              └─ section      8-byte header + aPLib stream, or raw bytes
```

## 1. Transport — `src/dnfw/syx/`

Every message is `F0 <body> F7`. Body layout:

```
data packet, 126 B : 00 20 3C <dev> 00 7E <block:2> <seq> <116B payload> <cksum>
marker,       14 B : 00 20 3C <dev> 00 7F <kind> <7B info>
```

- `00 20 3C` is Elektron's manufacturer id. `<dev>` is the product id: **0x0D**
  Digitone / Digitone Keys, **0x15** Digitone II.
- The 116-byte payload is **8-in-7** — one leading byte carrying the high bits
  of the seven that follow, MSB first — and carries exactly **101** decoded
  bytes. The final packet is zero-padded to a full 101.
- Packet count is `len(stream) // 101 + 1`: a stream that divides exactly still
  gets one more, mostly-empty packet. Measured: DN2 declares 17,259 packets and
  17,259 × 101 = 1,743,159 decoded bytes.
- `block` and `seq` are one 7-bit-wrapping counter starting from the start
  marker's `info[1..3]`. DN2 starts at block 1, seq 0x72.
- The checksum in body byte 125 covers body[6..125), each byte XORed with a
  running `base + index`, plus `base` once more, masked to 7 bits. **`base` is
  not a constant** — it is the start marker's `info[0]` (0x10 on both images).

Marker info is `[base][start block hi][start block lo][start seq][count …]`,
the packet count in the last three bytes, base-128.

**Gate A**: decoding and re-encoding both files with their sections untouched
reproduces them **byte for byte**. `test/test_roundtrip.py`.

## 2. Preamble and container

The decoded stream is `[u32 container size][u32 content checksum]` then the
container. The magic sits at offset 8 in both files.

| | DN2 1.10E | DN1 1.42A |
|---|---|---|
| container size | 1,743,120 | 1,102,352 |
| content checksum | `0x5441d766` | `0x69068797` |

The **content checksum** is not standard: a running 32-bit sum in which each
big-endian word is XORed with its own one-based index before being added.
Trailing bytes that do not fill a word are not covered.

```
acc = 0
for k, word in enumerate(words):   # big-endian, k from 0
    acc = (acc + ((k + 1) ^ word)) & 0xFFFFFFFF
```

## 3. ELE3 container — `src/dnfw/container/ele3.py`

```
0x00  "ELE3"
0x07  build/model string      DN2 "40050"   DN1 "60097"
0x13  version string          DN2 "1.10E"   DN1 "1.42A"
0x1C  u32 section count
0x20  section table, 16 B per entry: id, offset, stored length, dest
```

Sections are laid out on 16-byte boundaries in ascending offset order, after
the header and table. Section ids: 1 FPGA, 2 bootstrap, 3 MAIN OS, 4 updater,
5 meta, 6 boot, 7 blob — labels, not ground truth; Elektron document none of
them. OS 1.11 adds an id 8, compressed, about 160 KB, not yet looked at.

**Id 2 is the bootstrap, not DSP code.** It was labelled "DSP" from
`format.h` until its content was read (2026-09-11): it is ColdFire code with its
own `[u32 size][u32 0x80010000]` header, and it carries the Early Start-up
Menu's strings — `READY TO RECEIVE`, `RECEIVING...`, `UPGRADING...`,
`LENGTH ERROR`, `CRC CHECK`, `VERSION CHECK`, `UPGRADE FAILED`, the key and
encoder tests, `FACTORY RESET` — and the HMAC key string `"Multiplier"`. **It
is the recovery receiver**, which is why it matters more than its size
suggests. Upstream `elektron-firmware-tool` renamed it `bootstrap` on
2026-09-08 from the same evidence, and this project follows their name.

### What each image holds

| | id | stored | dest | storage | depacked |
|---|---|---|---|---|---|
| DN2 | 5 meta | 15 | — | **raw** | — |
| DN2 | 2 bootstrap | 16,168 | `0x02000000` | aPLib | 30,302 |
| DN2 | 3 MAIN OS | 1,093,816 | `0x40000400` | aPLib | **3,085,696** |
| DN2 | 4 updater | 32,776 | `0x80000400` | **raw** | — |
| DN2 | 7 blob | 600,156 | — | aPLib | 833,060 |
| DN1 | 5 meta | 15 | — | **raw** | — |
| DN1 | 2 bootstrap | 15,772 | `0x02000800` | aPLib | 28,766 |
| DN1 | 3 MAIN OS | 925,776 | `0x40000400` | aPLib | 2,420,912 |
| DN1 | 4 updater | 32,776 | `0x80000400` | **raw** | — |
| DN1 | 6 boot | 1,492 | — | **raw** | — |
| DN1 | 7 blob | 126,352 | — | **raw** | — |

**Which sections are raw differs between the two devices** — DN2's `blob` is
compressed and DN1's is not. There is no flag; the only test is whether the
bytes depack. This is why `firmware.build.replacement` reads the answer off the
original section (`docs/PRINCIPLES.md` §14).

What `blob` holds is **UNKNOWN** — 833 KB on the DN2, plausibly fonts, graphics
or factory data. It has not been looked at.

## 4. Sections — `src/dnfw/container/section.py`

A compressed section is `[u32 stream length][u32 sum of stream bytes]`, the
stream, then **zero padding to a multiple of four bytes**. The header describes
the stream alone — its length ends exactly at the end-of-stream token and its
sum excludes the padding — while the section table's length includes it.

The padding was missed at first because nothing checks it: a section without it
passes every checksum and the HMAC, and boots through the normal update path.
It was found on 2026-09-11 while looking for why our images stall in recovery.
All eleven compressed sections of DN2 OS 1.10D, 1.10E and 1.11 are padded, with
0 to 3 bytes each; by chance that would be about one in four million.

### Elektron's streams are bounded, and aPLib's need not be

Two further limits hold on every compressed stream Elektron ship, and are now
enforced (`src/dnfw/codec/limits.py`):

| | Elektron, 1.10E | Elektron, 1.11 | the format allows |
|---|---|---|---|
| furthest match | 1,048,508 | 1,048,553 | the whole output |
| longest match | 2,048 | 2,048 | unbounded |

The window is 1 MiB. MAIN OS is three megabytes, so this is a bound on the
packer, not a shortage of material. Our packer had no window and reached three
megabytes back in 2,051 places.

`dnfw inspect` reports both properties for every section, and `build` and
`patch apply` refuse to write an image that lacks either.

The codec is an aPLib variant: LZ77 with interlaced Elias-gamma codes, offsets
biased by 767, a last-offset reuse code, a far threshold at 3,328 granting a
length bonus, minimum match 2 (3 beyond the threshold). End of stream is a
gamma of `0x1000002` followed by `0xFF`, which reaches the bias **only by
32-bit wraparound**.

### Our packer against Elektron's

Ours is greedy with a lazy lookahead, not the cost-optimal parse `compress.c`
uses, because an optimal parse of 3 MB in Python takes hours. It costs nothing.
Measured 2026-09-11 with the 1 MiB window in force; "stock" is Elektron's
declared stream length:

| Section | raw | ours | stock | |
|---|---|---|---|---|
| DN2 1.10E bootstrap | 30,302 | 16,131 | 16,160 | −0.2% |
| DN2 1.10E MAIN OS | 3,085,696 | 1,091,713 | 1,093,805 | −0.2% |
| DN2 1.10E blob | 833,060 | 596,466 | 600,147 | −0.6% |
| DN2 1.11 MAIN OS | 3,192,192 | 1,129,103 | 1,130,517 | −0.1% |
| DN2 1.11 section 8 | 159,948 | 102,552 | 103,407 | −0.8% |

Every section comes out **smaller than stock**, so a rebuild never needs more
flash than the image it replaces. The window made it smaller still — without
it, 1.11 MAIN OS came out 445 bytes *over* stock, because a long far match costs
more bits than it saves. DN1 figures from 2026-09-07, before the window, were
−0.4% (bootstrap) and −0.2% (MAIN OS).

**The hash key width was the whole story, and it is worth recording because it
was nearly missed.** The minimum match length is 2, so hashing on a wider key
silently discards every short match. On the DN2 bootstrap section: a 4-byte key costs
**+12.4%**, a 3-byte key **+3.2%**, a 2-byte key **−0.2%**. The first working
implementation used 4 bytes and looked fine.

## 5. Trailer — `src/dnfw/integrity/`

The last 32 bytes of the declared container are an **HMAC-SHA256** digest. It
is placed on the first 16-byte boundary at least 4 bytes past the last section,
the gap is zeroed, and the digest covers everything before it — padding
included.

The key is derived from material inside the image, so no key is stored here and
none needs to be:

```
key = SHA256(s) XOR SHA256(reverse(s)) XOR constant
```

`s` is a printable string following the anchor `be f9 a3 f7 c6 71 78 f2` — the
last two SHA-256 round constants — in a decompressed section, terminated by NUL
and followed by the 32-byte constant. A candidate is accepted only when it
reproduces the image's own trailer.

**DN2 1.10E: the string is `"Multiplier"`, it lives in the bootstrap section, and the
derived key reproduces the trailer exactly.** Modified DN2 firmware can be
signed correctly.

**DN1 1.42A is unsigned** — its trailer is 32 zero bytes. A DN1 rebuild needs
checksums only. `load` short-circuits on an all-zero trailer rather than
depacking every section hunting a key that cannot exist.

### Do not patch the key material

Editing the string `"Multiplier"` in the **bootstrap** section would change the key
as well as the digest. The bootstrap is also the recovery receiver, and it
carries this string, so the device very likely verifies with the copy it
already has installed — which would make a changed key a guaranteed recovery
failure. That reading is inference; the code has not been read. Until that is settled,
leave it alone. Patching the same word where it appears in MAIN OS as a
parameter label is a different string and is harmless.

## Open questions

- Whether the bootloader checks the HMAC trailer at all, or only the checksums.
  We produce a correct one either way; the experiment is cheap and unrecorded.
- What `blob` contains.
- Whether the `updater` section (`0x80000400`, raw, 32,776 bytes on both
  devices) is the code that performs the flash. It is the same size on both,
  which is suggestive and not evidence.
