# Overtone 1.2: how parameter slides and instant pattern switch work

This is a static reading of `ot_sec3.bin` against stock 1.12 (`stock112_sec3.bin`) and stock 1.11. Nothing was run.
Confidence: **[H]** high (read directly from the code), **[M]** medium (read from the code, but some of the meaning is inferred), **[G]** guess.

## 0. Layout of the appended code (needed for everything below)

- In-place edit `0x4000053e` changes `jsr` to `jsr 0x4028dfb0`, a loader stub that overwrites stock bytes at 0x4028dfb0. The 1.11 address is 0x4028da70. **[H]**
- The loader reads a `DNFW` header at file VA `0x4030c980`. Its entries are tagged `CODE`: `{dest, len, bss, entry}`. It copies each chunk, zeroes its BSS and calls its entry. **[H]**
  - **Chunk 1** is the code. File VA `0x4030c9b4` goes to RAM `0x46800000`, length 0x10d08, followed by 0x1a16c bytes of BSS (to `0x4682ae74`). The entry point is `0x46800000`. RAM = file VA + 0x064F364C.
  - **Chunk 2** is data. File VA `0x4031d6cc` goes to RAM `0x46900000`, length 0x70bc, with no entry point.
  - The string addresses translate as follows: "INSTANT PATTERN SWITCH" is at 0x4680fdb0, "SLID" at 0x469068a9, "SLD" at 0x46906953, "SLEN" at 0x46906957, "Parameter Slide" at 0x46906cc4 and "Slide Length" at 0x46906cd4.
- **The parameter table is relocated and grown.** Chunk 2 holds a copy of the stock table followed by new records and their strings. Overtone repoints about 70 `lea 0x401f83a4` sites (1.12) to `0x468fffcc` and raises the id bound from `0x141` to `0x1bf` (the `cmpi #0x141` and `#0x140` checks become `#0x1bf` and `#0x1be`). **[H]**
  - Record id N is at `0x468fffcc + 60*N`, and stock record N is at `0x401f83a4 + 60*N`.
  - Chunk 2 starts at record 0's +0x34. Record 0's first 0x34 bytes, and record 0x1be's last 8 bytes (whose formatter field overlaps the string "FLNG"), are not loaded. This looks like an Overtone quirk; it was not investigated.
- **The two new parameters:** **[H]**
  - id **0x170 (368)**: page 0x0e, mirror slot **112**, range 0..0x100, default 0, "Parameter Slide / SLID / SLD".
  - id **0x171 (369)**: page 0x0e, slot **113**, range 0..0x7f00, default 0x0e00, "Slide Length / SLID / SLEN".
  - Code at `0x46801a5c` writes ids 368 and 369 into a ParameterSet page table, at `0x42433c70` and `0x42433c74`. That is how they appear on the TRIG page. **[M]**

Overtone's "extended slots" run from 101 up. The stock mirror, value array and lock index table are only 101 wide (slots 0..100), so every slot from 101 up needs Overtone's own storage. That is what the rest of this section is about.

---

## 1. STORAGE: where the slide settings live (the most important part)

There are two layers, matching stock's own model: the sound's own value, and a per-trig p-lock.

### 1a. Per-trig SLD/SLEN: lock records in the stock pattern lock pool **[H]**

Overtone does **not** add a new pattern field. It reuses the stock pattern's **80 × 258-byte lock records**. Each record is `{u8 id_or_slot, u8 track, u16 value[128]}`, at pattern data +0, with the per-track index bytes at +20640 and per-step counts at +22256. Encoding:

- **In RAM**, an extended lock's header is `byte0 = slot − 37` (64..126) and `byte1 = track | 0x20`. Bit 5 of the track byte flags the record as extended.
  - It is **not** entered in the per-track index table (+20640, 101 wide). Overtone finds it by a linear search for the 16-bit key across all 80 records (`0x46802896`).
  - The setter, getter and clearer for slots 101..163 are `0x46802978`, `0x46802b9e` and `0x46802ad4`.
  - The per-step count at +22256 is still kept, by calling stock `0x4003ce3c`. Overtone patched that function so it masks bit 5 when it matches the track.
- **On save** (hook `0x400de8c2` → `0x468037f8`), the extended header is converted to a stored **lock id in 107..127** with a plain track byte:
  - slots 101..108 → ids 120..127;
  - slots 109..121 → ids 119..107, in reverse (`id = 228 − slot`);
  - **so SLD (slot 112) is stored as id 116, and SLEN (slot 113) as id 115.**
  - Slots 122 and up alias back into that range (a −8 loop), so they would collide. Only slots 101..121 have unique ids.
- **On load** (hook `0x400de682`, the bound byte at `0x400de6f9`, and `0x400de74a` → `0x468037c8`):
  - the stock id bound 106 is raised to 127;
  - stock's id→slot lookup `0x400dce24` is hooked (`0x4680377e`): ids 120..127 → `0xC0|(id−120)`, ids 107..119 → `319−id`;
  - any result with bit 7 set becomes the extended RAM header and skips the +20640 index write.
- **What stock firmware does with such a file:** stock 1.11 and 1.12 both skip records whose id is above 106 at load (1.11 `0x400de594`: `moveq #106; bcs skip`). A stock save then frees them; our own 2026-09-17 hardware round trip saw the header become `FF FF`. So an Overtone pattern opened on stock firmware simply loses its slide locks; nothing is corrupted.
- **⚠ Conflict with our mod:** this is **the same id space (107..127) our arp p-locks use** (ids 107 and 108; RAM header `(k, track|0x20)`). The design is nearly identical, but the numbering differs, so patterns from the two mods are mutually incompatible.

### 1b. Sound-level SLD/SLEN (the value used when the trig has no lock) **[H for RAM, M for the file layout]**

**In RAM**, Overtone keeps its extra sound parameters in a **side table** instead of growing the sound object (stride 0x954):

- a 256-entry open-addressing hash at `0x4681919c`, keyed by the **sound object's address** (Fibonacci hash);
- 116-byte entries (58 u16 "words") at `0x46811d9c + i*116`, with defaults at `0x46811d28`;
- read and write through `0x4680063c(sound, k)` and `0x4680066c(sound, k, v)`. Getter and setter for extended slots: `0x4680160a` and `0x46801338`.

SLD and SLEN share **word 7**:

- SLD is bit 12;
- SLEN is the low byte, stored as `(SLEN>>8)+1`, where 0 means the default 0x0e00;
- bit 8 is slot 108.

Two mechanisms keep the side table in step with the sound objects:

- **Copies:** hooks on stock memcpy/memset (`0x40134770` and `0x401347b8`) carry the side-table entries along whenever the length is ≥ 1163 bytes and the range covers tracked sounds (`0x468005de`, `0x468001f0`).
- **Saving:** hooks on the sound serializer move the values between the side table and the stored sound.
  - live→stored: `0x400dd888` → `0x468017a4` → `0x46800e2c`;
  - stored→live: `0x400dd3e6` → `0x46801770` → `0x468008d8`;
  - more hooks at `0x400dd71c` and `0x400dda44`.
  - `0x46800e2c` writes words 0..7 as big-endian u16 at stored-sound offsets **36, 44, 52, 60, 68, 76, 84, 92** (`(table[i]+14)*2`, table `0x4680e227` = 4, 8, ..., 32). Word 7, which holds SLD and SLEN, goes to **stored +92**. Bits 7 and 15 of those words carry extra flags.
  - The remaining words (36..57, the follower/FX/etc. parameters) are packed through `0x46800816` into further spare bits; their destination was not traced.

**⚠ Second conflict:** stored +36..+92 are the bytes for **p-lock ids 4, 8, ..., 32**, which stock save never writes. They are **exactly the eight "free" ids our LFO4 plan uses** (`docs/lfo4-build-plan.md`, "Which eight ids"). Two more points:

- our own measurement says a **stock load + re-save zeroes these bytes**, so a sound saved through stock firmware loses its Overtone sound-level SLD/SLEN;
- Overtone sounds and our LFO4 sounds cannot share a project.

### 1c. Instant-switch setting **[H for the mechanism, G for which object]**

- **In RAM**, the flag for the display is `0x4682ae6a`, and arming state is at `0x4682ae68`, `0x4682ae69`, `0x4682ae72` and `0x4682ae73`.
- **Persistent:** one byte, **`(*(PROJECT + 0x50)) + 14`**, set to **0xA5** for ON and 0x00 for OFF (`0x4680df90`; read by `0x4680dccc`, which tests `== 0xA5`).
  - `PROJECT` is the lazy singleton from `0x4018ac5a` (1.12) / `0x4018a97a` (1.11). Its base constructor is named "PROJECT".
  - PROJECT+0x30 is a holder named "SETTINGS" (its data pointer is at holder+0x10 = PROJECT+0x40). **PROJECT+0x50 = SETTINGS holder +0x20**, which the base class clears and sets through setters `0x40198f2e` and `0x40198f84`.
  - **What that pointee is, and whether +14 is a pad byte, was not established.** The magic value 0xA5, rather than 1, suggests Overtone is guarding against stray non-zero bytes in a field that stock does not use. **[G]**
  - Overtone itself never writes it out. It relies on stock persisting that object with the project.

---

## 2. Hook list

The 1.11 addresses come from byte-matching the 1.12 code (low code is unshifted; 0x400dxxxx is −0x164; 0x400fa–0x4018 is −0x2e0 or −0x1cc; BSS 0x42c5bXXX → 0x42c5aXXX).

| 1.12 site | 1.11 | Stock code there | Overtone |
|---|---|---|---|
| `0x4000053e` | same | early boot call | jsr to the loader stub `0x4028dfb0` (1.11 `0x4028da70`), which copies the chunks |
| ~70 `lea 0x401f83a4` and the id bounds | `0x401F7F94`-based table | parameter-record table | repointed to `0x468fffcc`; bound 0x141→0x1bf |
| `0x4003cdba` | same | `getLock(pat,track,step,slot)` | slot 101..140 → `0x46802b9e` |
| `0x4003ceee` | same | `setLock` recorder (slot ≤ 100) | slot 101..140 → `0x46802978` |
| `0x4003d00e` | same | `clearLock` | slot 101..140 → `0x46802ad4` |
| `0x4003ce9e` | same | inside step-count `0x4003ce3c`: track compare | `0x468036f8`: masks bit 5 and ignores byte0 == 0x7f |
| `0x4003d14e` | same | another lock-pool walker (not read) | `0x468030c0` runs first, then stock |
| `0x400de682`, `+0x77` byte, `0x400de74a` | `0x400de51e`, `0x400de595`, `0x400de5e6` | **pattern load**: stored lock records → RAM | id bound 106→127; extended header; `0x4680322c` runs after |
| `0x400de87c`, `0x400de8c2` | `0x400de718`, `0x400de75e` | **pattern save**: RAM → stored lock records | slot→id 107..127; `0x46803198` runs after |
| `0x400dce24` | `0x400dccc0` | lock id→slot | ids 107..127 → extended codes |
| `0x400dd3e6`, `0x400dd888` | `0x400dd282`, `0x400dd724` | sound stored→live and live→stored converters | import and export side-table words to stored +36..+92 and other spare bits |
| `0x400dd71c`, `0x400dda44` | `0x400dd5b8`, `0x400dd8e0` | sound (de)serializer tails | more side-table import/export (`0x4680b192`, `0x4680b104`) |
| `0x40134770`, `0x401347b8` | `0x40134490`, `0x401344d8` | memcpy / memset | length ≥ 1163 → keep the side table in step |
| `0x400d874c` | `0x400d85e8` | **lock-list builder** (per note: list of `{slot,value}`) | after stock, `0x46802c10` scans the extended records for the track and step and fills an extension of the list object at **+860..+1015** (magic `'FT'<<16 \| track` at +860, masks at +944/+948, values at +868 and +952) |
| `0x400db1f6` | `0x400db092` | **lock applier** (writes slots and the bitmap, forwards to DSP) | after stock, `0x46802d5e` copies the extended values into per-track arrays and calls the **slide trigger `0x4680643c`** |
| `0x40026c20` | same | in the frame ISR, near the lock-apply call | `0x468036cc` → `0x46802f12` (per-track reset and stop of slide state) **[M]** |
| `0x40027180` (the operand of `jsr` at `0x4002717e`) | same | frame ISR → smoother `0x400db28e` (1.11 `0x400db12a`) | `0x46803d06`: `0x4680221e`, then the stock smoother, then the **slide tick `0x468068f0`** |
| vtable slot `0x40200cdc` | `0x402008cc` | key handler → `0x400fa88a` (1.11 `0x400fa6be`) | `0x4680df2c`: PTN held (key 0x17) and not key 0x11 → YES (event 10) / NO (event 12) toggle the instant byte |
| `jsr` at `0x400fa3a6` (operand `0x400fa3a8`) | `0x400fa1da` | UI posts a 24-byte message to the sequencer queue via `0x400d9554` (pattern cue) | `0x4680dcec`: arms "instant" if the sequencer is running (`0x42c5b918`) and the byte is 0xA5 |
| `0x400da56a` | `0x400da406` | sequencer pattern-change routine reads mode byte `0x42c5b91e` (1.11 `…a91e`) and compares with 2 | `0x4680dd28`: if armed (and `0x42c5baac` and `0x42c5b9e9` are 0), returns **2**, forcing the immediate path **[M]** |
| `0x400da5be` | `0x400da45a` | `mvsw 0x42c5bab4` before the switch | `0x4680dd52`: armed and the new pattern ≠ `0x42c5b9a0` → jump to stock `0x400da636` (the switch path) |
| `0x400da84a` | `0x400da6e6` | `lea 0x42c5b9c4,%a1` (step position) after the switch | `0x4680dd8c`: recomputes the position (§4) |

Many other edits belong to other Overtone features: the follower envelopes, Sophie/Loop/MD machines, insert FX, the arp, UI pages at `0x400a5xxx`/`0x400b4xxx`/`0x400dbe..dc6a4`, and menu vtables at `0x401edc5c`/`0x401f046c`. They were not mapped here.

## 3. How the slide is applied **[H for structure, M for units]**

- **Trigger, per track** (`0x4680643c`, called from the lock-apply hook):
  - SLD comes from the trig's extended lock (mask bit 11, value high byte) or from the sound's word 7. SLEN comes from bit 12, or from the sound.
  - If SLD is non-zero, Overtone takes a length `L` from SLEN, v = (SLEN>>8)&127, as 16.16 fixed point: v ≤ 30 → v+2; 31..46 → (v−14)·2; then ×4, ×8, ×16, ×32 bands; 127 → 2048. The units are not confirmed; maybe 1/16 steps. **[G]**
  - For **every one of the track's 101 mirror slots** that is "continuous" for the track's machine type (a bitmap built once from the relocated records, `0x46823cd0`), it records **from** (the previous output) and **to** (the new value in the source array `0x80003b12 + 202*track`), but only for slots whose value actually changed.
  - It stores a slot list `0x46823f50+101*t`, a count `0x46823f40[t]`, a length `0x468245b0[t]`, a progress counter `0x468245f0[t]=0` and an active flag `0x468245a0[t]`.
  - A second, 11-value set (`0x46823de0`, `0x46823d50`) covers Overtone's insert FX. **[M]**
- **Every audio frame** (`0x468068f0`, after the stock smoother):
  - progress += (`[0x402a132c]` × 25452) >> 16, a tempo-scaled increment;
  - frac = progress / (L>>15);
  - out = from + ((to−from)·frac >> 15), written **directly into the smoothed per-track DSP array `0x80006906 + 202*track + 2*slot`** (= `0x800068e4 + 34 + …`, the array our docs describe for `0x400db12a`).
  - If the source value no longer equals the recorded "to" (a knob was turned or something else changed it), that slot leaves the slide at once.
  - So the slide works **per track, for all changed parameters, with one length per track**. It overrides only the smoother output and never writes the sound or the pattern.

> **Correction (2026-11-01, measured in the emulator, `docs/jump.md` §1-2):** `0x42c5a91e`
> (1.11) is not a pattern-change mode byte. It is the sequencer's tick within the step; the
> compare with 2 is "the second tick of the step", where stock looks at the queue. Stock 1.11
> has no pattern-change modes. The formula below was confirmed (with it every track lands where
> stock plays the pattern from PLAY), but our DIRECT JUMP follows Elektron's rule instead (from
> the playing pattern's step) and does not use the PROJECT+0x50 byte.

## 4. How instant switch computes the position **[M]**

`0x4680dd8c`, after stock has switched to the new pattern P = `[0x42c5b9a0]`:

- `t = [0x42c5b9d4] + 6*[0x42c5b9d0] + 1`, which reads like ticks since PLAY (6-tick units plus a remainder);
- divisor = 6 if `P.byte[122201] == 1`, else `0x401f6f18[P.byte[122202]]`. This looks like the pattern's scale mode and master scale table;
- `pos = t/div + 1`; if `P.u16[122196]` (length) > 1, `pos = pos mod length`;
- the result is stored to stock's step position `0x42c5b9c4` (1.11 `0x42c5a9c4`).

Arming happens only on a UI pattern cue (PTN+TRIG). Chains, songs and program changes do not go through `0x400fa3a6`, so they keep stock's behaviour of changing at the pattern end.

## 5. Open questions

1. What object is `*(PROJECT+0x50)` (SETTINGS holder +0x20), and is its byte +14 unused and saved with the project? Read the setters `0x40198f2e`/`0x40198f84`, or look at the object under the emulator.
2. Is the lock-list object large enough for Overtone's +860..+1015 writes (the stock entries end at about +822)? Find its allocation stride.
3. Units of SLEN, and the exact meaning of `0x402a132c` and `0x42c5b9d0`/`b9d4`.
4. Where words 36..57 go in the stored sound (`0x46800816`), and whether they also sit in bytes that a stock round trip zeroes.
5. Record 0's unloaded 0x34 bytes and record 0x1be's truncated formatter in the relocated table (a latent Overtone bug?).

## 6. What this means for our mod

- For per-trig storage, the stock lock pool with ids 107..127 is a proven route. Stock firmware drops those records safely. Overtone and our arp mod both use it, so we must coordinate our ids (or accept that the two mods' patterns are incompatible).
- Overtone stores sound-level values in stored-sound ids 4..32. A stock round trip zeroes those bytes, and they clash with our LFO4 plan.
- The slide itself needs no new storage beyond two lock slots. It is one hook after the lock applier and one after the frame-ISR smoother; both sites are identical in 1.11.
