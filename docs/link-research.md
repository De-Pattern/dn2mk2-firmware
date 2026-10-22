# ColdFire <-> SHARC data paths on DN2 OS 1.11 — static research (2026-10-22)

Static only. No emulator or runner was used. Sources:
- ColdFire: `dnfw disasm` on `Digitone_II_OS1.11.syx`, plus byte scans of `sec111/section_3_MAIN_OS.bin` (loaded at `0x40000400`).
- SHARC: digikit's `out/sharcdb/dn2-1.11.sqlite` (image sha `336e340a…`, the stock section 7), plus `dnfw.image.bootstream.load_regions` for data words. DM byte address = load − `0x28000000`.

Tags: **[D]** read in code or bytes. **[I]** inferred. **[O]** open.

Scratch helpers used: `q.py` (sharcdb queries) and `mem.py` (SHARC data reads), both in this scratchpad.

## 0. Two corrections to read first

1. **`docs/waverider-dsp-silence.md` mixes DT2 addresses into the DN2 table.** These come from digikit finding 06, which is about DT2 1.16:
   - the "receive descriptor `0x268220` / ADDRSTART `0x268240`, 1,025 words";
   - "output rings A–D" (`0x261cc8…0x264138`).

   On DN2 1.11:
   - `0x268220` holds float constants (`0x3f2b2a8d`, …). [D]
   - `0x268240..0x269244` overlaps the engine's live mix and input buffers (`0x268438..0x2689b8`), the page word `0x268a38` and the dispatch table `0x268a68`.
   - No literal names `0x268240`, `0x268220`, `0x262138` or `0x261cc8` in the DN2 image (`literals` table). [D]
   - So these addresses are **refuted as DN2 ring addresses**. The real DN2 rings are in §2.
2. **The SPI reply tail does have ColdFire readers, but through the DMA buffer `0x80001a20`, not the copy at `0x800053a4`.** A scan for `0x80005e40..5e5f` finds nothing, but that search had no positive control. Details in §3b.

---

## 1. SSI0 TDM link, ColdFire side

### Link configuration (SSI0 init, service path `0x400d55b2..0x400d564c`) [D]
Register reading uses the MCF5441x SSI layout.
- `SSI_CCR` (`0xfc0bc024`) = `0x00016f00`:
  - DC = 15, so **16 words per frame**;
  - WL = `0b1011`, so **24-bit words** (i.MX/ColdFire SSI WL coding). [D for bytes, I for field decode]
- `SSI_TMASK` / `SSI_RMASK` (`+0x48`/`+0x4c`) = `0xffff0000`: **all 16 slots active in both directions**. [D/I]
- `SSI_TCR` = `0x82`, `SSI_RCR` = `0x482`, `SSI_CR` = `0x38 | EN`. Exact justification bits: [O].

### Format [I, from three consistent code facts]
- The DSP writes each TDM TX slot as `fix(x, 31)`, a 32-bit Q1.31 value (sw `0x1c2689`).
- In cmd 0 the DSP writes `0x7FFFFFFF` to slot 0 of frame 0 (sw `0x1c9e1e..0x1c9e24`).
- The ColdFire's alignment routine looks for **`0x007FFFFF`** in RX slot 0 (`0x400d54aa`).
- The ColdFire's calibration injector writes `0x7fffff` as full scale (`0x40138500`).
- In the other direction, the ColdFire writes USB samples as `sample >> 8` (`0x40025fe6`), and the DSP converts RX slots with `float_by(−31)` (sw `0x1c9d1f`).

So each 32-bit slot carries **24 significant bits on the wire**: the top 24 of the DSP word, right-justified on the ColdFire. Which 24 bits survive in each direction, and whether sign extension happens, is for a hardware loopback to settle.

### Mode switch
The ISR is `0x40025e36` (`0x40025e0a` is a small helper it calls). Each period it picks half `h = (ch50 SADDR < 0x4e6e0900)`, then branches on `0x4058e2a8`, read by getter `0x40006c4a`. [D]
- Its values 5 and 6 behave like USB class-audio vs Overbridge. The labels are [I]; digikit links value 6 to `SET_INTERFACE`.

### TX window `0x4E6E0100 + h<<11` (ColdFire → SHARC)

| mode `0x4058e2a8` | what the ISR writes | evidence |
|---|---|---|
| ≠ 5, ≠ 6 | `memset0(half, 0x800)`: all 16 slots of all 32 frames cleared, every period | `0x40026080..0x40026090` → `0x40133ebc` (a `clrl` loop) [D] |
| 5 | `memset0(half, 0x800)`. If USB-in flag `0x80005366` is set, it then writes two slots per frame: slot indices from bytes `0x80005367` and `0x80005368`, data `src[k] >> 8` from `0x4664af4c` / `0x4664af50` | `0x40025f66..0x40026002` [D] |
| 6 | `0x40003376`: for each frame with USB data, `memcpy(half + 64·k, pkt + 32·k, 32)`, i.e. **slots 0..7 only**. Frames without data are `memset0` at 64 bytes per frame. **Slots 8..15 of frames that get data are not written**, so they keep earlier contents | `0x40003480..0x400034a2`, `0x40003410` [D] |

**So stock never puts meaningful data in TX slots 8..15** [D]. They are zero in modes ≠ 6. In mode 6 they are stale (zero, or whatever an earlier mode left).

### RX window `0x4E6DF100 + h<<11` (SHARC → ColdFire)
- **Mode 6:** `0x40003118` builds USB packets of 140 bytes per sample:
  - `memcpy(pkt, RXframe + 64·k, 0x38)`: **slots 0..13**;
  - then `memcpy(pkt + 56, records + 84·k, 84)`.
  - That is 42 channels. [D] (`0x40003270..0x40003284`)
- **Mode 5:** channel getter `0x400253d0(ch, frame)`:
  - `ch <= 13` reads RX slot `ch`;
  - `ch >= 14` reads the SPI reply records (`(ch-14)/2` pair, 42-halfword stride).
  - Two channels selected by `0x80005364` / `0x80005365` are mixed through the MAC into `0x4664b074` (`0x400276b2..0x40027766`). [D]
- **`0x40138460(RXhalf, 0x800053c0)`:** a calibration-pulse injector. It overwrites **all 16 RX slots** with `0x7fffff` and the records with `0x7fff…` while a counter (`0x446406d8`/`0x4464066c`) runs. Otherwise it does nothing. [D]
- **Service mode:**
  - the record loop reads slots 0..2;
  - the alignment routine reads slot 0. [D, docs/audio-dma.md]

**RX slots 14 and 15 are not read by any normal-mode stock consumer found** [D for the three consumers above]. The search was over immediates of the window base. Its positive control is that it found all 9 known `0x4e6df100` sites.

---

## 2. SHARC side of the TDM link

### Rings
Built by sw `0x1ca2d1` (TDM) and sw `0x1ca167` (codec). All descriptors use CFG `0x00100000`, XCNT `0x200`, XMOD 4. They are two-descriptor ping-pong chains. [D]

| ring | buffers (DM byte) | descriptors | opened with (`0x1ccd08`: R4 device, R8 half, R12 dir) |
|---|---|---|---|
| **TDM TX → ColdFire** | `0x2c08e8` / `0x2c10e8` (2,048 B each = 32 frames × 16 slots × 4) | `0x2c28e8` ↔ `0x2c2904` | R4 = 0, R8 = 0, R12 = 0 → **SPORT0 A** [I for the driver-arg meaning] |
| **TDM RX ← ColdFire** | `0x2c18e8` / `0x2c20e8` | `0x2c2920` ↔ `0x2c293c` | R4 = 0, R8 = 1, R12 = 2 → **SPORT0 B** |
| codec DAC | `0x2c0478` / `0x2c0578` (256 B = 32 stereo frames) | `0x2c0878`… | R4 = 4 → SPORT4 A |
| codec ADC | `0x2c0678` / `0x2c0778` | `0x2c08b0`… | R4 = 4, R12 = 2 → SPORT4 B |
| SPI2 receive | `0x2c29d0` / `0x2c39d0` (one page every `0x1000`) | `0x2c2960` ↔ `0x2c297c` | `0x1cc753(R4 = 2)` |
| SPI2 reply | `0x2c49d0` / `0x2c59d0` | `0x2c2998` ↔ `0x2c29b4` | ″ |

**Page ↔ block.** One page is 32 frames, which is one 32-sample DSP block.
- The block handler (sw `0x1c9d6b`, called from the engine task loop at sw `0x1c9fe7` after `0xb891fa` returns) uses `DM(0x268a38)` as the page index for **all four SPORT rings**: `+(pg<<11)` for TDM, `+(pg<<8)` for codec. [D]
- It toggles `DM(0x268a38)` at sw `0x1c9e5a..0x1c9e5f`. [D]
- The SPI rings use their own page `DM(0x2c0450)`, toggled by sw `0x1ca04a`. [D]
- Phase between the DMA's position and the page the CPU writes: [O]. The constant 750 Hz stuck-tone result (2 × 32 frames replayed) supports the "two pages" picture.

### Block dispatch: SPI command word = RX word 0 [D]
Table `0x268a68`:

| cmd | entry | does |
|---|---|---|
| 0 | `1c9dc2` | silence DAC page; **TDM TX slot 0 frame 0 = `0x7FFFFFFF`** (alignment marker) |
| 1 | `1c9e76` | silence DAC; TX slot 0 frame 0 = 0 |
| 2 | `1c9eda` | passthrough. For 32 frames: ADC L/R → **TX slots 0,1**, and **RX slots 0,1** → DAC. The service caller `0x400d0fec` sends a `2` |
| 3 | `1c9f0f` | the engine. ColdFire `0x400274b4` writes `3` to `0x80005e60` every frame |

Anything with `cmd >> 2 ≠ 0` goes to the cmd 0 arm. Every arm ends at `1c9e29`, which **negates** the 64 DAC words of the page, then writes reply word 0.

### Who reads which RX slots (cmd 3) [D]
Each call to `0x1c9d00` converts two slots × 32 frames (stride 16 words), `float_by −31`, into float pairs. The pointer list is at `0x268a40`.

| call site | source slots | destination (L / R, 32 floats each) |
|---|---|---|
| `1c9f20` | ADC L/R (`0x2c0678` page) | `0x268538` / `0x2685b8` |
| `1c9f38` | slots 0,1 | `0x268638` / `0x2686b8` |
| `1c9f51` | slots 2,3 | `0x268738` / `0x2687b8` |
| `1c9f6a` | slots 4,5 | `0x268838` / `0x2688b8` |
| `1c9f86` | slots 6,7 | `0x268938` / `0x2689b8` |

**RX slots 8..15 are never read by stock DSP code.** This is [D] for the cmd 2 and cmd 3 arms. No other literal names `0x2c18e8` / `0x2c20e8`: the only references are these and the descriptor builder.

### Who writes which TX slots (cmd 3)
Writer: sw `0x1c244d`, called at `0x1c307b`. Arguments: inputs struct, mix `0x268438`, reply buffer, TX page, source flag. [D]

- **Loop A** (`0x1c266c`, 14 iterations): triple k = 0..13 of a 42-entry channel table goes to **TX slots 0..13**, 32 frames each, `fix(x·gain, 31)`.
- **Slots 14 and 15 are never written.** The pages load as all zero (`mem.rd`: 0 non-zero bytes in `0x2c08e8..+0x1000`), so slots 14 and 15 stay 0 forever. [D]
- The cmd 0/1/2 arms write only slot 0 (0/1) or slots 0..1 (2).

### Channel table
Image copy at `0x25d760`: 42 triples of `(ptrA, ptrB, gain)`. They are copied to the stack at `1c25c0`. Gains for k = 0..39 are then overwritten with 1.4286; the input gains stay 1.0. [D]

| k | ptrA / ptrB | meaning |
|---|---|---|
| 0, 1 | `0x268438` / `+0x80` (patched at run time from R8) | main L / R |
| 2..33 | A `0x258f68 + 0x80·m`, B `0x259f68 + 0x80·m`, m = k − 2 | track m/2 + 1, L (m even) / R (m odd) |
| 34..39 | `(0x25b168, 0x25b068)`, `(0x25b1e8, 0x25b0e8)`, `(0x25b468, 0x25b368)`, `(0x25b4e8, 0x25b3e8)`, `(0x25b768, 0x25b668)`, `(0x25b7e8, 0x25b6e8)` | 3 stereo FX returns [I for "FX"] |
| 40, 41 | runtime ADC L / R | audio input L / R |

**A or B.** The choice is `s = (frame word at RX + 0xa7a == 0) ? B : A`.
- Engine reads at `0x1c3052`, `0x1c3064..1c3067`; `0x1c244d` applies it at `0x1c25cd..0x1c25e5`.
- ColdFire writes that halfword from byte `0x8000536a` (`0x4002767c`). [D for the code; I for the 32- vs 16-bit width of the DSP read]

Modifier semantics used here:
- Type 7b `I(s ^ idis) = I(s) + M`, with no scaling (digikit `forms_dag._type_7b`, and only this reading makes the loop walk the table);
- Type 7a `modify(nw)` scales ×4.

**So TX slots 0..13 = main L/R, then tracks 1–6 L/R.** [D for the table and loop; I for the modifier semantics]

---

## 3. SPI parameter-frame link

### (a) Length and padding [D]
- **2,748 bytes in both directions.**
  - `0x400cf7be` ignores its own length arguments for the DMA.
  - It programs eDMA ch29 (TX: `0x80002510` staging → PUSHR) and ch28 (RX: POPR → `0x80001a20`). Both use `CITER = BITER = L/2`.
  - `L = min(DM 0x42440958, 2800)` (`0x400cf824..0x400cf8e8`).
  - `0x42440958` is set once at boot: `0x400cef28 jsr 0x40027d3a` (returns `#2748`), then `0x400cef30 jsr 0x400cf688` (stores it).
- **Runtime frames use CTAR0 (16-bit), not CTAR1.**
  - Each TX entry is a PUSHR word whose top half is `0x8001`: CONT = 1, CTAS = 0, PCS 1.
  - CTAR0 `0xFA010000` gives FMSZ 15, i.e. **16-bit frames**.
  - CTAR1 `0xBA010000` gives 8-bit frames; it is the boot path's (CTAS = 1).
- **Bytes 2688..2747 sent:**
  - The fill loop writes the data half of entries 0..1343 from the 2,688-byte payload (`0x400cf918..0x400cf928`).
  - For entries 1344..1373 it writes **only the high half (`0x8001`)** (`0x400cf92c..0x400cf93a`).
  - So the 60 tail bytes on the wire are **whatever is in the staging data halves**. Nothing else in MAIN OS names `0x80002510` (2 hits, both here) [D].
  - The value is power-up SRAM content or zero: [O].
- **The previous frame's reply** is copied from the DMA buffer `0x80001a20` to the caller's buffer (`0x800053a4`, 2,748 bytes) at the start of the next call (`0x400cf7e8..0x400cf7f2`, `0x40134490` = copy). The service caller passes `(2688, 0x4244098c, 0, 0)`, so it skips the copy; the wire length is still 2,748.
- **DSP use of received bytes 2688..2747:**
  - The engine copies **exactly 672 words = 2,688 bytes** of the receive page to `0x25c48c` (sw `0x1c287a` and `0x1c302d`).
  - Direct reads of the receive page: word 0 (cmd); the region at `+0x158` and `+0xa5a`; the fields at `+0xa7a` / `+0xa7c` / `+0xa7e`, which the ColdFire fills at `0x4002767c` / `0x40027660` / `0x40027666`.
  - If the read at `+0xa7e` is a 32-bit one, it also touches halfword 2688, which is padding. If 16-bit, nothing at ≥ 2688 is read. [I]
  - **No DSP read of bytes 0xa82..0xabb was found.** [D for literal/offset reads listed; scope: functions 0x1c2712, 0x1c9d6b, 0x1c244d]

### (b) The 32-byte reply tail (`0xa9c..0xabb`)
**ColdFire readers exist** [D]. They index the **DMA buffer**: halfword `1358 + n` of `0x80001a20` is byte `0xa9c + 2n`.

| accessor | returns |
|---|---|
| `0x400cfa98(n)` | `v < 0 ? 0 : v >> 7` |
| `0x400cfab8(n)` | `v < 0 ? 0 : v` |
| `0x400cfad6(n)` | `(~v & 0xffff) >> 15`, i.e. 1 when v ≥ 0 |

So the tail is 16 × s16, one per track [I], where negative means inactive.

**None of the three has a caller.**
- No `jsr`/`bsr`, and no 32-bit copy of their address at any byte offset in section 3.
- Same for the load accessor `0x400cfa14` and `0x400cfa40`…`0x400cfa7c` / `0x400cfaf4`.
- Positive controls: `0x400cfa90` (reply `+0x16`, the compressor's gain reduction) is found with 1 caller (`0x40070412`), and `0x400cf7be` with 2.

So on DN2 1.11 these tail readers look dead [I]. They are likely shared code from another product.

**DSP writers of the reply** [D within the reply-pointer data flow]:
- word 0: the cycle count, halves swapped (sw `0x1c9e62`);
- `+0x16`: compressor gain reduction, `fix(..,15)` (sw `0x1c3117`, `DM(reply + 11 short)`);
- the records `+0x1c..+0xa9b` (sw `0x1c26c4..0x1c26e9`).

The reply pointer is only passed through `DM(I6−2)` of `0x1c9d6b`, `DM(I6−33)` of `0x1c2712`, and `I13` of `0x1c244d`.
- **Nothing in stock writes `+0x4..+0x15`, `+0x18..+0x1b`, or `+0xa9c..+0xabb`.** The rings load as zero, which matches the 0s seen on the instrument.
- The project's own mod already uses words 1 and 2.

**Packing.** SPI2 moves 16-bit elements (XCNT `0xabc>>1`), MSB first on the wire. Each element is stored little-endian in DSP memory.
- **A DSP 16-bit store at byte offset o arrives at ColdFire `0x80001a20 + o` as the same big-endian u16.**
- A 32-bit DSP word at o arrives with its halves swapped: low half at o, high half at o+2. That is why word 0 is stored "halves swapped".
- So a tail write is: 16 short stores of the values to reply-page offsets `0xa9c + 2n`, on the page `0x2c49d0 + (DM(0x2c0450) << 12)` that `0x1ca020` returns.
- The ColdFire reads it either at `0x80001a20 + 0xa9c` (the live DMA buffer), or at `0x80005e40` after the next call's copy. [D for the mechanism, I for the exact SPI word ordering]
- Checked against the instrument reads in `docs/for-digikit-coldfire-sharc-link.md` §8: `+0x000 = 0x0006` (high half of word 0), `+0x016` a u16.

### (c) Other bytes one side writes and the other never reads
- **Reply, DSP → ColdFire:**
  - `+0x04..+0x15` and `+0x18..+0x1b`: not written by the stock DSP. The ColdFire reads `+0x4..+0x18` through the uncalled accessors only.
  - Records `+0x1c..+0xa9b`: written every block, read only by the USB paths (mode 6 → Overbridge, mode 5 → channels ≥ 14).
- **Frame, ColdFire → DSP:** bytes 2688..2747 are stale padding that the DSP does not use (modulo the `+0xa7e` width question).
- **Inside the 2,688 bytes:** which bytes the DSP consumes after the copy to `0x25c48c` was **not** determined.

---

## 4. DSPI clock and headroom
- Runtime attributes: CTAR0 `0xFA010000` gives DBR 1, PBR 01 (÷3), BR 0 (÷2), so **SCK = f_P / 3**. CSSCK = ASC = DT = 0, and CONT = 1 within a frame, so overhead per frame is minimal. [D for the fields]
- **f_P.** MAIN OS holds a 132 MHz bus-clock constant (`0x07DE2900` at `0x400024a6`; digikit reads it as the bus clock).
  - If this FlexBus-mapped DSPI at `0xec038000` runs from that clock, **SCK ≈ 44 MHz**, and 2,748 × 8 bits takes ≈ **0.50 ms of the 0.667 ms frame (≈ 75 %)**. [I]
  - Independent lower bound, if a transfer finishes within one frame: ≥ 33 Mbit/s. [I]
  - The silicon behind `0xec038000` is still unknown: an FPGA, or a second mapping of an on-chip DSPI. [O]
- **The hard cap is 2,800 bytes.** The RX DMA buffer `0x80001a20 + 2800 = 0x80002510` is exactly where the TX staging starts. [D]
  - Within the current buffers you could lengthen by **52 bytes** (2,748 → 2,800). That is +78 KB/s at about 76 % of the frame [I], and needs only:
    - the boot length (`0x40027d3a`);
    - the DSP XCNT (`0x1ca812` `R4 = 0xabc`; DSP pages are 4,096 B, so there is room);
    - the ColdFire copy length (`0x40025e90`).
  - Going beyond 2,800 means relocating both ColdFire buffers. The time budget would allow about 3,300 bytes at the inferred clock [I].
  - A separate path exists for longer TX: `0x400cf694`, on-chip DSPI1 `0xfc03c034` with eDMA ch15, unused at these lengths.
- **ColdFire CPU budget.** `docs/usbprobe.md`: the audio ISR takes about 56 % of the CPU on stock, with peaks of 74–112 % of a frame. Any per-frame ColdFire copy must be small and tight.

---

## 5. Per-track audio for "sample from track N"

Block order inside the engine `0x1c2712` [D]:
1. `0x1c8ef1`, machine dispatch / voice render (`1c3044`);
2. `0x1c1738`, FX sends (`1c3054`);
3. `0x1c1f1e`, routing into `0x258f68` (`1c305d`);
4. `0x1c244d`, output and Overbridge (`1c307b`).

| buffer | layout | written by | persists into the next block's `0x1c8ef1`? |
|---|---|---|---|
| `TRACK_BUFFERS[t]` = `DM(0x254a60 + 4t)` (ENGINE + `0x137C8`); also copied to the pointer table `0x257ea8` at init (`0x1c150b`) | mono, 32 float | the renders and amp in `0x1c8ef1` (amp at sw `0xb80345`, in place) | until track t is re-rendered within `0x1c8ef1`. Whether anything clears it earlier: [O] |
| `0x257ee8 + 0x100·t` | stereo float: L 32 at +0, R 32 at +0x80 | inside `0x1c8ef1`, through the 32-pointer table `0x258ee8` (`[L2i, L2i+1, R2i, R2i+1]` per pair, built at `0x1c14e1..0x1c1575`; the engine sets `DM(0x257e78) = 0x258ee8` at `0x1c2848` before calling `0x1c8ef1` with R12 = `0x257e6c`) [D for the setup, I for the writes] | until track t is processed again inside `0x1c8ef1` (order unknown) |
| **`0x258f68 + 0x100·k`** (k = routing slot `s16 DM(0x257898 + 2t)`, normally k = t [I]) | stereo float L / +0x80 R, post-chain, with mute ramps; then **×3.2768 in place** (`0x1c248f`) | zeroed and accumulated by `0x1c1f1e` (`0x1c1f48`, `0x1c1fa8`), scaled by `0x1c244d` | **yes, whole block** [D]: the only writers are `0x1c1f1e` and `0x1c244d`, which both run after `0x1c8ef1`. During block n+1's `0x1c8ef1` it holds block n's data |
| **`0x259f68 + 0x100·k`** | stereo float: mono `TRACK_BUFFERS[t]` panned and ramped by `0x2578b8`/`0x257898` | zeroed and accumulated only in `0x1c244d` (`0x1c24b5`, `0x1c2515`) | **yes, whole block** [D] |

**Overbridge channel map** (42 channels: 14 TDM slots, then 28 record channels) [D for the table and loops; I for the modifier semantics and the FX naming]:

| channels | content |
|---|---|
| 0, 1 | main L / R |
| 2..13 | tracks 1–6 L / R |
| 14..33 | tracks 7–16 L / R |
| 34..39 | 3 FX returns L / R |
| 40, 41 | audio input L / R |

Each source is A (`0x258f68`, post-chain) or B (`0x259f68`, raw track panned), chosen per §2.

**Record packing** (`0x1c26c4..0x1c26e9`). Each pair (a, b) of Q31 values is written as three shorts:
- `a[31:16]`;
- `a[15:8] << 8 | b[31:24]`;
- `b[23:8]`.

That gives two big-endian 24-bit samples. The record stride is 42 shorts = 84 B, and record n is sample n of the block.

**Recommended tap for "sample from track N", inside `0x1c8ef1` early in block n+1:**
- read `0x259f68 + 0x100·N` (pre-chain, panned, no extra gain beyond pan), or `0x258f68 + 0x100·N` (post-chain, ×3.2768);
- both are complete, previous-block, stereo, float32, 32 frames;
- check the routing word `DM(0x257898 + 2N)` first: if two tracks share slot k, the buffer holds their sum.

---

## Recommended path (bandwidth × risk)

1. **ColdFire → SHARC: TDM RX slots 8..15. About 1.15 MB/s at 24 bits per slot, 1.5 MB/s if 32 bits survive.**
   - Stock never sends anything meaningful there and never reads them on the DSP.
   - ColdFire side: write slots 8..15 of TX half h after the stock `memset` (modes ≠ 6) or the `memcpy` (mode 6), at the end of ISR `0x40025e36`.
   - DSP side: read `0x2c18e8 + (pg<<11) + 32 + 64·f` in a new step in the cmd 3 arm.
   - Risk: low. No stock consumer, and nothing changes on the SPI link.
   - Unknowns: bit justification (needs a loopback test), and the page/half phase (needs a sequence number in a slot).
2. **SHARC → ColdFire bulk: the reply records (2,688 B per frame ≈ 4.0 MB/s), when Overbridge/USB audio is not streaming.**
   - The ColdFire already gets a copy each frame at `0x800053c0`.
   - Risk: medium. It breaks Overbridge per-track audio and mode-5 channel picks ≥ 14 while active, so gate it on mode / USB state.
   - A safer fixed channel: **TDM TX slots 14..15** (≈ 288 KB/s at 24 bits). They are never written by the DSP and never read by the ColdFire normal path. The ColdFire reads them from RX half h in the ISR.
3. **Small side channels, safe now, ≈ 50–80 KB/s each way:**
   - reply tail `+0xa9c..0xabb` plus `+0x04..0x15` / `+0x18..0x1b` (DSP → ColdFire). The tail readers are uncalled on DN2;
   - frame padding 2688..2747 (ColdFire → DSP). Write the data halves of staging entries 1344..1373, because stock never touches them;
   - plus the existing 32 spare frame bytes.
4. **Lengthen the SPI to 2,800 (+52 B per frame).** Low gain, touches three constants; not worth it alone.
5. **Avoid:** going over 2,800 bytes on SPI (buffer relocation, about 76 % of the bus already used [I]), or reusing TDM slots 0..13 (Overbridge and USB audio).

## What only hardware can settle
- Which 24 (or 32) bits of a TDM slot survive each direction, and sign handling. Test: a DSP-side ramp/pattern in slots 14/15, read by the ColdFire; a ColdFire pattern in slots 8..15, echoed by the DSP into the reply tail.
- The phase relation between the ColdFire half h and the DSP page `DM(0x268a38)` (latency, and whether a written half is consumed exactly once). Use sequence counters in both directions.
- The actual SPI SCK, and the transfer's share of the frame. The 0xec038000 silicon and its clock are [I].
- The power-up content of staging data halves 1344..1373 (the stock TX padding).
- Whether the DSP's read at frame `+0xa7e` is 32-bit, which would make padding halfword 2688 matter.
- Whether TRACK_BUFFERS / `0x257ee8` are cleared at the start of `0x1c8ef1` before track t renders (static order inside `0x1c8ef1` not read).
- The mode values (`0x4058e2a8` = 5 / 6): which USB states they are.
- Whether the tail accessors `0x400cfa98` and the others are truly unreachable (no static caller and no stored pointer found; computed calls were not excluded).

---

## 6. Follow-ups (2026-10-22, static)

### (a) Which pages code inside `0x1c8ef1` should use

**What drives what** [D]:
- **The audio task is woken by the codec SPORT, not by SPI.**
  - Callback `0x1ca136`, registered by `0x1ccba3` from the codec setup `0x1ca167` (call at `0x1ca2b5`).
  - On event bit 8 it does `vTaskNotifyGiveFromISR(DM(0x268a84))`, the Audio Task handle (`0xb88e41` at `0x1ca14f`).
  - The task loop at sw `0x1c9fe7` calls `ulTaskNotifyTake` (`0xb891fa`) and runs `0x1c9d6b` only when the count is exactly 1 (`btgl R0, 0` / `JUMP IF NOT SZ`).
  - If notifications pile up, the block is skipped, not run twice.
- **The SPI page word changes in interrupt context, independently of the block.**
  - `0x1ca04a` is the SPI2 driver callback, installed by `0x1cb7d2` (`DM(dev+4) = 0x1ca04a`), called from the SPI setup `0x1ca46a` at `0x1ca4b8`.
  - On event `== 0x20` it toggles `DM(0x2c0450)`.
  - The only reader is `0x1ca020`, called once per block at the very start of `0x1c9d6b` (sw `0x1c9d96`), before the dispatch.
  - No other access to `0x2c0450` exists: `mem_access` has 3 loads and 1 store; `ptr` has the same.
- **SPI rings** (`0x1ca46a`, descriptor `+0` = next, `+4` = ADDRSTART):
  - RX: `0x2c2960` (page 1, `0x2c39d0`) ↔ `0x2c297c` (page 0, `0x2c29d0`);
  - reply: `0x2c2998` (page 1, `0x2c59d0`) ↔ `0x2c29b4` (page 0, `0x2c49d0`);
  - page word initial value 0.
  - If the chain starts at the page-1 descriptors [I], the toggle makes `DM(0x2c0450)` = **the page whose transfer just completed**. RX and reply complete together, since SPI is full duplex.
  - Then the reply that block n writes into page p goes out **two transfers later**: the DMA is already armed on page 1−p for the next one.
- **Race:** the SPI completion and the block are only frequency-locked, and their phase is unknown. The toggle can fire **during** a block, so re-reading `DM(0x2c0450)` inside `0x1c8ef1` can give the other page. Do not recompute from the page word mid-block.

**Recipe for the reply page** (this is what `0x1c244d` fills) [D for the frame slots, I for the calling convention]:
- `0x1c8ef1` has exactly one caller, the engine (`0x1c3044`). The engine keeps:
  - the RX page pointer at `DM(I6e − 32)` (stored at `0x1c2767`);
  - the **reply page** at `DM(I6e − 33)` (`0x1c276e`/`0x1c2776`, from its stack argument).
- `CALL (db)` = CJUMP sets `R2 = I6, I6 = I7`, and the first push stores R2 at the new I6. So in the **body of `0x1c8ef1` itself**, `I6e = DM(I6)`.
- Therefore:
  - `reply = DM(DM(I6) − 33)`;
  - `rx = DM(DM(I6) − 32)`;
  - equivalently `reply = rx + 0x2000`.
- Deeper in the call tree, walk the chain one `DM(I6)` per frame.
- Alternative that avoids the race entirely for the RX content: the engine copies the 2,688 RX bytes to the static `0x25c48c` before `0x1c8ef1` (`0x1c302d`).

**Recipe for the TDM pages** [D]:
- `DM(0x268a38)` has exactly one store, at sw `0x1c9e5f`, at the end of `0x1c9d6b` after the engine returns. It is task-level, so it is **stable for the whole engine call**.
- The cmd 3 arm uses the value it read at sw `0x1c9db7`:
  - TX page for `0x1c244d` = `0x2c08e8 + (DM(0x268a38) << 11)` (`R10 = pg<<11` at `0x1c9f1d`, `+0x2c08e8` at `0x1c9fab..0x1c9fb1`). This is also `DM(I6e + 2)`;
  - the RX page the converter read = `0x2c18e8 + (DM(0x268a38) << 11)` (`0x1c9f27..0x1c9f2d`).
- **Recomputing from `DM(0x268a38)` inside `0x1c8ef1` is safe.**
- Confidence: high, [D], for "same page as stock". Whether the SPORT DMA has already moved past that page is the same question for stock code: [O], hardware.

### (b) DSP DDR use and size

**Static loads** [D]:
- the boot stream fills `0x80000000..0x80000014` and `0x80000018..0x8052fbe0` (mostly zero);
- the init's sine table at `0x8052fbe0` reaches `0x80530be8` (`docs/w5-tables.md`, measured by `scripts/sharc_ddr_ceiling.py`).

**Every genuine DDR immediate in the code** (sharcdb `literals`, excluding the 15a/16a hits in L2 data at sw `0xb8f…–0xb97…`, which are paired-16-bit data words decoded as instructions; their "addresses" `0x8f…–0x9f…` are not pointers) lies in `0x80000000..0x8052fbe0`:

| address | users | likely role [I] |
|---|---|---|
| `0x80000018` | `0x1c163d`, `0x1c1d03` | FX line, about 356 KB to `0x8005912c` |
| `0x8005912c` | `0x1c1666`, `0x1c1c4a` | FX line, about 4 MB to `0x80459388` |
| `0x80459388`, `0x8045a6c8` | | FX / init |
| `0x8045b000..0x804ac000` | | transient bank (`docs/mods.md`) |
| `0x804abe88..0x804ad790` | `0x1c84xx`/`0x1c8bxx` | machine tables |
| `0x8052d790..0x8052dbc0` | `0x1c90a6..0x1c9587` | dispatch tables |
| `0x8052dbe0`, `0x8052ebe0` | L2 `0xb811xx`, 4 KB each | |
| `0x8052fbe0` | `0x1c45e5`… | sine |

So **nothing in the stock code names DDR above `0x80530be8`**. Scope: immediates only. Run-time-computed pointers, such as heap or DMA descriptors, are not excluded. The runner's stray writes at `0x85d7…–0x9fc4…` came from a pointer the runner never initialises (`docs/w5-tables.md`).

**DMC configuration** [D for the bytes, I for the field decode]:
- The init writes the DMC0 registers from the record at `0x242c4c` (sw `0x120353`, called at `0x120523`):
  - `DMC_CFG (0x31070040) = 0x0af00622`;
  - TR0/TR1/TR2 = `0x42118959` / `0x50ea1450` / `0x0044051e`.
- Decoded with the ADSP-2156x HRM layout as I remember it (no manual copy here to check against):
  - IFWID 2 and SDRWID 2: a 16-bit interface and device;
  - **SDRSIZE 6 = 4 Gbit = 512 MB**;
  - EXTBANK 0.
- This agrees with the D2516 part number. So **all 512 MB, `0x80000000..0x9FFFFFFF`, is very likely configured**.

**Recommendation:**
- The pool can grow from `0x84000000` up to `0x9FFFFFFF`, about 448 MB.
- Keep a small top margin, e.g. end at `0x9F000000`, until a hardware test passes. Run it before shipping:
  - write/read a pattern at `0x9FFFFFF0`;
  - an **alias test**: write distinct values at `0x80100000 + X` and `0x90100000 + X` and check both survive. This catches a 2 Gbit (256 MB) mapping.
- Not checked: SMPU or other address protection on the DMC (no SMPU literal search was done), and the DM/DDR cache attributes of high DDR.
- Also `docs/drive-storage-research.md` §4: the DN2 has the ColdFire Rapid-GPIO block at `0x8c000000`, which DT2 uses with SHARC link port 0 for sample pages. The CPU end exists on DN2, but no DN2 SHARC receiver does.

### (c) Where to hook the SSI ISR `0x40025e36`

- **h** is kept as a long, 0 or 1, at **`%fp@(-56)`** for the whole ISR (`0x40025e50`):
  - TX half = `0x4e6e0100 + (h << 11)`;
  - RX half = `0x4e6df100 + (h << 11)`.
  - The frame is alive until `unlk` at `0x40027bc4`.
- **End of the TX fill**: every mode converges on **`0x40026098`**, branched to from `0x40025f98`, `0x40025fa2` and `0x40026002`, and fallen through to from `0x40026096`:

  | mode | path |
  |---|---|
  | 5, USB flag off | memset at `0x40025f7a` → `0x40025f98` / `0x40025fa2` → `0x40026098` |
  | 5, USB flag on | two-slot loop ends `0x40026000` → `0x40026002 braw 0x40026098` |
  | 6 | `0x4002602a jsr 0x40003376`, then `0x40026078 jsr 0x4013803c` → `0x4002607e bras 0x40026096` → `0x40026098` |
  | other | `0x40026090 jsr memset` → `0x40026096` → `0x40026098` |

  - All five `0x4e6e0100` writers in the ISR are before `0x40026098`. [D]
  - The instructions at `0x40026098` are `movel %fp,%d2` (2 bytes) and `addil #-72,%d2` (6 bytes): 8 bytes, enough for a `jsr cave` plus a NOP. The cave must re-execute both.
  - **Registers are live across this point.** For example, a2 = `0x40006c4a` is used again by `jsr %a2@` at `0x4002779a`. So the cave must save and restore every register it uses (`moveml`).
  - **This is the best place to write TX slots 8..15**: it is as early as possible, so it is least likely to race the DMA into half h. The ISR's wall time peaks over a frame (`docs/usbprobe.md`).
- **RX consumers** run at `0x400277a4..0x40027a44`. Treat RX half h as complete from ISR entry [I]: stock reads it then.
- **Return path:**
  - single exit; the only `unlk`/`rte` in `0x40025e36..0x40027bc6` (even-offset byte scan) [D];
  - common tail `0x40027b68` (branched to from `0x40027aa2`, `0x40027ae0`, `0x40027b02`, `0x40027b4a`, `0x40027b54`);
  - then `0x40027ba2 moveml %fp@(-32),%d0-%d6/%a0` (6 bytes): the MAC restore through `0x40027bbc`, `moveml %fp@(-236),%d0-%a5` at `0x40027bbe`, `unlk` at `0x40027bc4`, `rte` at `0x40027bc6`.
- **A hook at `0x40027ba2`** (replace the 6-byte `moveml` with `jsr cave`; the cave runs its work, then the same `moveml`, then `rts`) may clobber d0–d7 and a0–a5 freely: everything is restored afterwards from the frame.
  - h is still at `%fp@(-56)`.
  - Good for RX-side work: reading slots 14/15 and the reply.
  - Too late for TX writes when the ISR runs long.
- **Budget:** the ISR averages about 56 % of the CPU on stock (`docs/usbprobe.md`). Keep per-period work small; 8 slots × 32 frames = 256 long stores per period.

---

## 7. Track buffer addressing (static, 2026-10-22)

**Access widths** come from sharcdb's `mem_access.width`:
- `0x257898` is read **short-word** (16-bit), stride 2 bytes, so 16 × s16 at `0x257898..0x2578b7`;
- `0x2578b8` is read **byte**-wide, so 16 × u8 at `0x2578b8..0x2578c7`. [D]

### How k is computed for track t (same shape in both loops) [D]

`0x1c244d`, B = `0x259f68`. The loop at `0x1c2515` runs t = 0..15. I2 = `0x257898`, I5 = `0x2578b8`, I4 = `0x257ea8`.
```
1c2518  R2 = DM(I2, M6) u=1        ; w = s16 routing[t]         (short-word)
1c251a  R2 = R2 + R2 ; I0 = DM(I4) ; 2w ; I0 = src ptr = DM(0x257ea8 + 4t) = TRACK_BUFFERS[t]
1c251d  R2 = fext-se(R2, 0, 16)    ; sign-extend 2w to 32 bits
1c2520  R1 = DM(I5, M6) u=1        ; f = u8 flag[t]                 (byte)
1c2522  R1 = leftz(R1)             ; SV <=> f == 0
1c2525  R1 = 0x3ec006c4 (0.375)
1c2528  IF SV R1 = M5 (0)          ; step = f ? 0.375 : 0
1c252a  R2 = lshift(R2, 7)         ; (2w) << 7 = w * 0x100
1c2532  I1 = R2 + 0x259f68         ; B slot base = 0x259f68 + w*0x100
```
`0x1c1f1e`, A = `0x258f68`: the same sequence at `0x1c1fab..0x1c1fc7`. There the step constant is `0x3ee94c03` (0.4556), and the source is the stereo buffer `0x257ee8 + 0x100·t` (I4 = `0x257ee8`, stepped by `0x100`), not a pointer table.

**So k = w, the halfword itself: k = sext16(2w)/2, valid for 0 ≤ w < 0x4000.** A zero halfword means **slot 0**, not "its own slot". With all-zero routing, all 16 tracks are summed into slot 0, and slots 1..15 of A and B stay 0.
- That matches what the runner shows: slot 0 got the sum of everything, including whatever uninitialised track buffers hold, which explains a value and then NaN.
- w must be 0..15. 16 lands in the next buffer (`0x25af68`, the first FX send bus) and beyond.

### Gain, and what the flag means [D for the constants, I for the per-sample reading of the pipelined loop]
- **B:** gain starts at `0x413a068e` = 11.627 and decreases by `step` every sample.
- **A:** gain starts at `0x416201a3` = 14.125, step 0.4556.
- With f = 0 the gain is constant. With f ≠ 0 it ramps to about 0 over the 32 samples (11.627 − 31 × 0.375 = 0, and 14.125 − 31 × 0.4556 = 0).
- **So `0x2578b8[t]` is not a mute. It is a once-per-block "trigger, fade the old sound out" flag** (a de-click at retrigger).
- Then, on output, A is scaled ×3.2768 (in place) and both A and B get the table gain 1.4286 (§2).
- **B gets the mono source on both L and R with the same ramp.** No pan coefficient is read in that loop: its only multiplicands are the ramp register and the constant. So B = dual-mono `TRACK_BUFFERS[t]` × 11.627 (×1.4286 at output). [I, strong]

### Who sets the two tables, and from which frame bytes [D]
The engine `0x1c2712` reads the frame copy at `0x25c48c` (= frame byte 0).

**Routing halfwords:**
- The per-track unpack loop `0x1c2937` (16 iterations) has I5 = `0x25c48e + 0x32` = frame byte `0x34`, advancing by one short per track.
- At `0x1c293e`, `R4 = DM(I5, M1)` with M1 = `0x513` shorts = `+0xa26` bytes gives **frame `0xa5a + 2t`**.
- `0x1c2992` stores it to `DM(I4 + 31)` with I4 = `0x257858 + 2(t+1)`, which is **`0x257898 + 2t`**.
- The engine also computes `frame + 0xa5a` directly at `0x1c2ca6..0x1c2cad`.
- **ColdFire side:** in the per-track field loop `0x400274fa..0x4002759e`:
  - `a3 = 0x80005e60 + 2 + 2t`;
  - `0x40027594 movel (d6)+,%d0` with d6 = `0x80005308`;
  - `0x40027596 movew %d0,%a3@(2648)` writes frame `0xa5a + 2t` = the low 16 bits of `0x80005308[t]`.
  - `0x80005308` is a 16-long table whose entries are compared with track numbers 0..15 (`0x4002592a..0x40025952`: `cmpl #15` then `cmpl (a2)+,%d3`). So it is **slot → track number** [I].
  - In normal use, entry t holds the track that DSP slot t plays [I].
- **The same loop fills other per-track frame fields** (frame offset = `2 + 2t + disp`):
  - `0x02+2t` (value `>> 8`);
  - `0x34+2t` (the field the DSP reads first, its high byte an index);
  - `0x54+2t` (machine slot, clamped 0..4 at `0x1c294c`);
  - `0x74+2t`, `0x94+2t`, `0xb4+2t`.

**Flags:**
- In the engine's 16-track loop, `0x1c2d00`/`0x1c2d10`/`0x1c2d12`/`0x1c2d1e` clear `0x2578b8[t]` and `0x2578c8[t]` (byte stores of M13) every block.
- `0x1c31c7`/`0x1c31c9` (`IF NE … = M14`) set both to 1 only when:
  - bit t of the frame u16 at **frame `0x22`** is set (`R7 = DM(frame + 17 shorts)` at `0x1c2cd6`, `btst(R7, R11 = t)` at `0x1c2d18`), and
  - a per-track value differs from its previous value (`comp` at `0x1c31bf`).
- So the flag means "track t triggered this block" and lasts one block.

**To make B (or A) carry track t's audio in its own slot t:**
- set frame halfword `0xa5a + 2t = t`, for all t;
- leave bit t of frame `0x22` clear, or accept a one-block fade on trigger blocks.

In the runner, all-zero frames route everything to slot 0, which is what was seen.

### Which signal is in A and B
- **B** = `TRACK_BUFFERS[t]`. The pointer comes from `0x257ea8[t]`, copied from ENGINE+`0x137C8` at init (`0x1c14db`/`0x1c150b`). So B is the same mono block the per-track amp at sw `0xb80345` works on in place, taken after `0x1c8ef1` has finished.
  - Whether the amp runs before every reader: [I] yes. `0x1c244d` runs after `0x1c8ef1` returns.
  - No pan or overdrive is applied in B; only the 11.627 × ramp and the routing.
- **A** = the per-track **stereo** buffer `0x257ee8 + 0x100·t` (L 32 / R 32 floats), × 14.125 × ramp, summed per routing slot, then ×3.2768.
  - `0x257ee8` is written inside `0x1c8ef1` through the 32-pointer table `0x258ee8` that the engine installs at `DM(0x257e78)` (`0x1c2848`). It is already stereo, so pan has been applied by then. [I]
  - The FX **sends** (`0x1c1738`: `0x25af68`/`0x25b268`/`0x25b568`) are **taps read from** `0x257ee8`. They are not part of A, and A contains no FX returns.
  - Which per-track stages (filter, amp, overdrive) happen between the mono `TRACK_BUFFERS` and the stereo `0x257ee8`, and in what order, was not read: the writes to `0x257ee8` happen inside `0x1c8ef1`'s callees. [O]
