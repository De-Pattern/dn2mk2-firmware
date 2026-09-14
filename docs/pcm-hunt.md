# The FM drum transients: how many there are, and where they are not

**Measured 2026-09-14 on Digitone II 1.11.** `docs/ideas-backlog.md` Â§3 wanted
to expand the FM drum machine's PCM catalogue and to extract the existing one.
This is the first pass, and it is mostly an elimination â€” but it establishes the
one number the whole idea needs.

## 1. There are exactly 125 transients

The parameter table names it directly:

```
0x401fc2d0   286   2   42  SYN   Drum Transient   TRAN   7c00   0   227   342
```

The range field at `record+0x...` is `max << 8`, which is checkable against
parameters whose value sets are known:

| parameter | field | implies | actual |
|---|---|---|---|
| LFO `Waveform` | `0x600` | 7 | TRI SIN SQR SAW EXP RMP RND â€” **7** |
| SYN `Noise Type` | `0x200` | 3 | 3 |
| **SYN `Drum Transient`** | **`0x7c00`** | **125** | â€” |
| most continuous params | `0x7f00` | 128 | the usual 0..127 |

So the integer range is 0..124 — **125 positions**.

> **[OVERSTATED — corrected 2026-09-14, same day]** This said *"`TRAN` selects
> one of 125. That is the catalogue size"*, which claims more than the field
> supports. The record's value formatter settles it: id 286's is `0x400e2ef6`,
> and it renders `'%s%d.%02d'` — **a signed decimal like `12.34`**. Enumerated
> parameters do not look like that; LFO `Waveform` and `Noise Type` have
> name-lookup formatters. `0x7c00` is max = **124.00 in 8.8 fixed point**, and
> the `bipolar` flag at `+0x14` is set.
>
> So `TRAN` is a **continuous** control whose fraction may morph between bank
> entries, not a 125-item menu. 125 positions remains the right number for the
> integer part, and the same `max = count - 1` rule still reads LFO `Waveform`
> correctly at 7. But "125 named transients" was not established, and the
> formatter is **display-only** — it never touches the sample data, so it is not
> the route to the catalogue.

Related parameters sit beside it and are worth having in one place, because they
say the transient is a *layer* rather than the whole drum: `Transient Level`
(`T.LEV`, id 287), `Noise Base/Width/Grain`, `Body Hold/Decay/Level`.

## 2. The SHARC image contains no audio at all

`blob` (section 7) was the obvious place â€” Â§3 assumed the samples were there,
and `docs/data-sections.md` had already found it "mixed data, a large part of it
float32". Reading every one of its nine regions as float32:

| region | bytes | zeros | `\|x\|<=1` | zero-crossing rate |
|---|---:|---:|---:|---:|
| `0x2001e888` (L1 data) | 432,564 | **68.8%** | 84.3% | **0.001** |
| `0x282403f0` (rodata) | 191,504 | **68.6%** | 98.8% | **0.003** |
| `0x282c0000` (rodata) | 120,108 | **65.9%** | 98.5% | **0.001** |
| `0x80000018` (DDR) | 5,438,408 | **93.7%** | 96.9% | 0.011 |
| `0x20000000` (code, control) | 125,056 | 0.2% | 80.7% | 0.365 |

**Audio oscillates; these do not.** A zero-crossing rate of 0.001 means one sign
change per thousand samples â€” that is a sparse table, not a waveform. Two-thirds
of every data region is zero bytes.

**So the transients are not in the SHARC image.** That is a genuine negative,
and it also retires Â§3's opening assumption that the search starts in `blob`.

## 3. The detector that had to be thrown away, and the control that caught it

`scripts/find_pcm.py` scores windows on zero-crossing rate, bounded amplitude
and roughness, and reports runs. Read as **int16** it reported:

| region | kind | "audio" |
|---|---|---:|
| `0x20000000` | **CODE** | **99.9%** |
| `0x283825c4` | **CODE** | **99.9%** |
| `0x282403f0` | data | 32.1% |

**It fires on 99.9% of both code regions.** Those are instructions â€” established
independently by the cjump census, with nothing to do with this test. A detector
that calls compiled code "audio" nineteen times out of twenty is measuring
entropy, not sound, and every int16 row it produces is worthless.

This is why the control was built in: *a watch must be able to produce a
different answer for each outcome.* Without the code rows, the int16 table looks
like a discovery â€” 32% of a rodata region "is audio" â€” and it is nothing.
The float32 rows are trustworthy for the opposite reason: they came back **zero
everywhere**, including on the regions the detector could have flattered.

## 4. What was ruled out in MAIN OS, and what is left

MAIN OS has ~1 MB past the code boundary at `0x401d0000`. Profiling it in 64 KB
chunks finds one dense, high-entropy block at **`0x40240000`â€“`0x40280000`**
(~256 KB, 3% zeros) â€” and 256 KB over 125 transients is ~2 KB each, which at
16-bit/48 kHz is ~21 ms. Exactly a transient's length. It fits arithmetically.

**It does not survive a structural test.** If that block were 125 samples it
should segment: silence between hits. Scored in 128-sample RMS windows, the
whole 384 KB span shows **3 quietâ†’loud transitions read little-endian and 7 read
big-endian**, not 125.

Nor is there an index. Scanning MAIN OS for strictly-increasing 32-bit runs
(the shape an offset table has and little else does) finds three ~129-entry
tables, and all three are mathematics rather than pointers:

```
0x401d88d0   0, 0x2932e, 0x5265c, ...   constant delta 168750
0x40287b04   ...                        constant delta  84375
0x4020b358   0, 0x4c6c8ea9, ... 0x80000000   a saturating curve
```

Arithmetic progressions and a saturation curve â€” tuning/phase increments and a
transfer function, not a sample catalogue.

## 4b. Two corrections to Â§2 and Â§3, both mine

**The owner states as fact that the transients are samples â€” Elektron said so.**
That is device knowledge this analysis did not have, and it makes a null result
an instrument problem rather than an answer. Re-examining, the instrument was
wrong twice.

**The zero-crossing test was calibrated for the wrong kind of audio.** It
required `zcr >= 0.05`. A single-cycle wavetable over a 256-sample window has
`zcr â‰ˆ 0.008`, and a low-frequency drum thump is no better. So Â§2's sweeping
claim â€” "the SHARC image contains no audio at all" â€” is **wrong**:
`docs/display-path.md` had *already* found **31 band-limited wavetables spanning
[-1,+1]** on a `0x400` stride from `0x2825e8b0` in the very region this scan
called silent. The correct statement is narrower: **no run of float32 in the
SHARC image has the shape of a 125-entry transient bank.** The wavetables are
there, and they are oscillator data.

**And "bounded" is not "non-zero".** A shape rescan then reported a promising
133,974-float run at `0x804ace88` in DDR â€” 1,072 samples per transient if split
125 ways, which is exactly the right length. It is an artifact: **2,058 of its
2,093 windows are silent.** It is a zero-filled DDR buffer with a fragment at
the end, and it passed because `0.0` lies inside `[-1.1, 1.1]`. The run test now
requires values to vary rather than merely fall in range.

With both fixed, the largest genuine non-zero float runs in section 7 are:

```
0x282c9894   4417 floats   range 2.000   smoothness 0.0010
0x28267428   1025 floats   range 1.343   smoothness 0.0010
0x2826b3a8   1025 floats   range 1.999   smoothness 0.0010
0x282c69d8   1025 floats   range 2.000   smoothness 0.0020
```

**1025 is 1024 + 1** â€” a power-of-two lookup table with the wraparound guard
point â€” and a smoothness of 0.001 says each is a clean curve. These are
oscillator and math LUTs, not percussion.

## 5. Where this leaves the idea

**Established:** the catalogue is 125; the SHARC image holds no audio; entropy
and statistics cannot find samples in this firmware because compiled ColdFire
code defeats the test.

**Not established:** whether the transients are sampled at all. `TRAN` selecting
1 of 125 is equally consistent with 125 short PCM hits and with 125 parameter
presets driving a synthesised click â€” and FM DRUM is documented by Elektron as a
synthesis machine. MAIN OS contains **no** `Pcm`, `Transient`, `Drum`,
`Wavetable` or `Noise` class in its RTTI; the only sample-related names are
`SampleLoaderBgWorker` and `SampleWaveformsFactory`, which are platform plumbing
shared with the sampler products.

**The next step is not another scan.** It is to read the consumer: find the code
that reads parameter id 286 and see what it indexes.
`docs/parameter-table-consumer.md` already maps the ~50 accessors that index
`record[id] = base + id*60`, and Ghidra is cleared for ColdFire (Gate F), so
this is a bounded read rather than a hunt. If it indexes a data array, that
array is the catalogue and its base and stride fall out immediately. If it
selects a code path, the transients are synthesised and Â§3 changes shape
entirely.

**A second, cheaper check available on the device:** `docs/midi-rpc.md` records
an `FsSampleListRam` RPC. If the DN2's sample filesystem is live rather than
vestigial platform code, it would list whatever sample content the running
device holds â€” answering "are there samples at all" without patching anything.
Read-only, and gated on the owner's go-ahead and a named transport.

## Reproducing

```
python scripts/find_pcm.py 00_Resources/00_Firmware/<image>.zip
python scripts/find_pcm.py <image> --section 3
```

Carved output goes outside the repository. The transients are Elektron's
copyrighted content: extracting them for local analysis is one thing,
redistributing them is not something this project does.


---

## 6. The search of the image is now exhausted, and the tool for the device exists

**2026-09-14, after the owner asked whether the options had actually been
exhausted. They had not.** Two things had been skipped.

### Every section, with a detector that works

The corrected shape test — float runs that stay inside `[-1.1, 1.1]`, **vary**,
and are smooth — had only ever been run on section 7. Run across **all** of
them:

| section | result |
|---|---|
| 2 bootstrap (30 KB) | nothing |
| **3 MAIN OS (3.19 MB)** | 3 runs; largest 2,027 floats, smoothness 0.0005 — a curve |
| 4 updater (32 KB) | nothing |
| 7 all nine regions | only 1025/2048/4417-float LUTs |
| 8 ARM accessory (160 KB) | nothing |

**No section contains a 125-entry sample bank as float32 or int16.** That is now
a thorough negative rather than an early one.

### ADPCM, because "noise with clicks" is what ADPCM sounds like as PCM

The owner auditioned the dense MAIN OS block and reported *"noise with some
clicks/beeps"*. That is the exact signature of **compressed** audio played as
raw PCM, so the block was decoded as IMA ADPCM (both nibble orders) — 322,560
bytes becomes 645,120 samples, 13.4 s, ~107 ms per transient over 125. Sent for
audition.

### `elektroid` already speaks this protocol, and supports the DN2

`docs/midi-rpc.md` planned to derive the RPC wire format by reading
`MidiRpcDispatcher::handleMessageAndCreateResponse` (the mangled name is at
`0x40207ec0`). That is a real piece of work — the dispatcher takes a
`shared_ptr<MidiRpcMessage>`, so ids are virtual methods on message objects, and
a scan for a flat `(id, handler)` dispatch table finds **none**.

It does not need deriving. **`dagargo/elektroid`** — GPLv3, GNU/Linux, packaged
in Debian/Ubuntu and on Flathub — implements Elektron's SysEx transfer protocol
and lists **"Elektron Digitakt I and II, Elektron Digitone I and II and Digitone
Keys"** among its supported devices. Its CLI is `connector:filesystem:command`:

```
elektroid-cli info                 # which filesystems THIS device exposes
elektroid-cli elektron:sample:ls   # list samples
elektroid-cli elektron:sample:dl   # download one
elektroid-cli elektron:data:ls     # projects / sounds, with metadata
```

**`elektroid-cli info` against a connected DN2 is the whole experiment.** If the
device reports a `sample` filesystem, the hypothesis in §5 — that the transients
are factory content in device storage rather than in the OS update — is
confirmed, and `sample:ls` then enumerates them. If it reports only `project`
and `sound`, the hypothesis is dead and the transients are inside the firmware
in a form not yet recognised.

Either way it is **read-only**, uses a mature third-party tool rather than
anything we would have to get right first time, and costs one command.

**This is the "reuse before writing" rule earning its place** (`docs/PRINCIPLES.md`):
the alternative was reverse-engineering a message dispatcher to re-derive a
protocol somebody has already implemented and shipped.

**Licence note:** elektroid is **GPLv3**. This repository is AGPL-3.0-or-later,
so porting from it is compatible — but nothing needs porting yet. Running the
tool is not a licence question at all.

---

## 7. The dense block is not raw PCM — measured, not inferred

**2026-09-14.** The owner states as fact that the transients are samples —
Elektron have said so — so every negative here is about where and how they are
kept, not whether they exist.

### What the owner's ear settled, and what it did not

The dense MAIN OS block `0x40238800`–`0x40287400` was rendered five ways (int16
big- and little-endian, signed 8-bit, IMA ADPCM in both nibble orders), cut into
125 pieces each by `scripts/chop_bank.py`, and auditioned:

> "in that form doesn't sound like transients. We might be decompresing them
> wrong, or reading the data in the wrong way"

**That eliminates those five encodings, not the region.** An earlier draft of
this section said the ear test "closes it" — it does not, and the owner caught
the overreach. A listener can only rule out the rendering they were given.

### What measurement settled

Two tests that do not depend on any decode being right:

**Byte-plane entropy.** 16-bit PCM has a structured, correlated MSB plane and a
noisy LSB plane, so the two planes differ. Measured:

| region | even bytes | odd bytes | delta |
|---|---:|---:|---:|
| dense block | 7.504 | 7.507 | **0.003** |
| MAIN OS code (control) | 5.665 | 6.848 | 1.183 |

**Autocorrelation.** A sampled waveform moves in small steps between adjacent
samples. Read as int16 either way, the block's mean |delta| between consecutive
samples is **19,401** against a range of 65,535 — random data would give
~21,845.

**So the block is not raw 16-bit PCM in any byte order.** Its planes are
indistinguishable and its samples are uncorrelated, which no sampled waveform is.

Overall entropy is **7.507 bits/byte** — well above code (6.458) and strings
(4.249), but below the ~7.9+ that general-purpose compression reaches. And
running the device's own aPLib depacker at every 2-byte offset across the first
16 KB produces nothing over 4 KB, so it is not a second aPLib layer.

What it is remains open: some 4-bit or entropy-coded format, or not the bank at
all.

### A scan of my own that produced nothing but false positives

Looking for code that references the block, I scanned MAIN OS for 4-byte
big-endian values landing inside it, at 2-byte alignment, and got 52 "hits from
the code region". They are garbage: values like `0x40244e75` and `0x40254e75`
are 4-byte windows straddling instruction boundaries, and **`4e75` is the
ColdFire opcode for `rts`**. Reading a fixed-width window across a
variable-length instruction stream and calling the result an address is the same
class of error as the linear SHARC walk. Finding real references needs decoded
`lea`/immediate operands, not a byte scan.

### The DDR payload: pitch tables, not audio

Section 7's DDR region spans 5.4 MB while the whole section is 837 KB, so most
is FILL expanded to zeros — but **5.8% is real payload**, 316,716 bytes never
examined, the largest span being `0x8045a6ca`–`0x804ace88` at **337,854 bytes**.
That is ~2.7 KB per transient over 125, an encouraging fit.

It is not audio. Realigned to its float32 boundary (the span starts at `mod4=2`)
it opens with a long run of exactly `1.0f` and ends with smooth sequences like

```
0.8900  0.9371  0.9805  1.0199  1.0622  1.1074
```

A semitone is a ratio of 1.0594, so those are pitch/detune ratio tables spanning
roughly ±2 semitones, interleaved with zero fill.

## 8. The Digitone II has no sample filesystem

`dagargo/elektroid`'s `res/elektron/devices.json` declares, per device, which
filesystems it exposes. It is a mature independent implementation of Elektron's
transfer protocol and supports our device by name:

| device | id | filesystems | storage |
|---|---|---|---|
| Digitakt II | 42 | **`sample`**, `data`, `project`, `preset-takt-ii` | +Drive, RAM |
| **Digitone II** | **43** | `data`, `project`, `preset-takt-ii` — **no `sample`** | none |
| Syntakt | 30 | `data`, `project`, `sound`, **`data-sample`** | none |

**So `FsSampleListRam` would answer nothing on a DN2** — §5's "factory content in
a sample store" is wrong in its specifics, and that test is withdrawn before
being run.

### What the Syntakt row changes

Syntakt OS 1.40 shipped the **SP Twinshot** machine: 64 user sample slots, under
5 s each, 32 MB total, converted to 16-bit 48 kHz mono, loaded through Elektron
Transfer. The community built `mikkovihonen/transientsplit` on top of it
specifically to generate transient layers.

The interesting part is *how* elektroid models it — not as `sample` but as
**`data-sample`**, a specialisation of the generic **`data`** object store. **The
Digitone II already has `data`.**

Elektron's own answer to "let users load their own transients" on this platform
was therefore built on a mechanism the DN2 already carries. That is not evidence
the DN2's *factory* transients are data objects, but it makes
`elektron:data:ls` the first thing to ask the device, and it is read-only.

## 9. Talking to the instrument

`scripts/midi_probe.py` reaches a connected device over USB MIDI through `winmm`
and `ctypes` — `python-rtmidi` and `pygame` have no wheels for the Python here.

**It is read-only by construction.** Every outgoing message must come from a
`READ_ONLY` table in the file; anything else raises before a byte reaches the
port. That is deliberate: `docs/service-commands.md` and `docs/midi-rpc.md`
between them list commands that rewrite a serial number, reconfigure the MMC, or
wipe a +Drive, and **a wiped +Drive is not recoverable from anything this
project holds.**

Ports enumerate correctly (`Elektron Digitone II` in and out). The MIDI Universal
Device Inquiry `F0 7E 7F 06 01 F7` — a MIDI-spec identity request, not an
Elektron command — was sent and **drew no reply in 3 s**.

**That result is not yet interpretable.** "The device declined" and "our receive
path does not work" look identical from here, so `--listen` exists to separate
them: it receives only, and a turned encoder produces short messages. **The
control has not been run** — the owner began reflashing 1.11 to restore factory
firmware, and no traffic should reach a device mid-flash.

Nothing further goes to the instrument until the owner confirms the flash is
complete.
