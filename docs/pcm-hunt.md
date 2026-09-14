# The FM drum transients: how many there are, and where they are not







**Measured 2026-09-14 on Digitone II 1.11.** `docs/ideas-backlog.md` §3 wanted



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







`blob` (section 7) was the obvious place â€” §3 assumed the samples were there,



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



and it also retires §3's opening assumption that the search starts in `blob`.







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







## 4b. Two corrections to §2 and §3, both mine







**The owner states as fact that the transients are samples â€” Elektron said so.**



That is device knowledge this analysis did not have, and it makes a null result



an instrument problem rather than an answer. Re-examining, the instrument was



wrong twice.







**The zero-crossing test was calibrated for the wrong kind of audio.** It



required `zcr >= 0.05`. A single-cycle wavetable over a 256-sample window has



`zcr â‰ˆ 0.008`, and a low-frequency drum thump is no better. So §2's sweeping



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



selects a code path, the transients are synthesised and §3 changes shape



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

---

## 11. The dense block is the compressed factory PRESET PROJECT

**Identified 2026-09-14**, and it closes the largest candidate in this file.

`0x40238800`-`0x40287400`, 322,560 bytes, was the one region whose arithmetic
fit a 125-entry transient bank at ~2.5 KB each. It is not that. It is the
**factory preset project, LZ-compressed inside MAIN OS**.

> **[CORRECTED by the owner, 2026-09-14, within the hour.]** This first said
> "factory preset/sound content" and called the strings preset or sound names.
> They are **pattern names, inside the preset project** — device knowledge this
> analysis did not have. The distinction is not cosmetic: an Elektron *project*
> contains patterns, sounds, kits and settings as one object, which is a
> different thing from a sound bank and has a different size, owner and
> lifecycle. DNX's record gives a DN2 project slot as **4,194,304 bytes**
> allocated and, in raw form, a **12.9 MB** expanded image — so 322 KB
> compressed is the right order for one mostly-empty project, and quite wrong
> for a bank of individual sounds.

### How it was settled

Ghidra's reference model, once the tool was fixed (below), gives 13 references
into the range from six functions. Four of them push addresses that decode to
recognisable text, and the text is the giveaway:

```
0x402572d0   ... f9 be ef ba ce 00 7f 03 | PRESE.TS 1643
0x402765c0   ... 9f 00 be ef df ba ce 07 | HIDDE.N TEA
0x40281ec0   ... f9 be ef ba ce 00 7f 02 | SOLID
```

Those stray `0xff` / `0xfe` bytes inside otherwise clean ASCII are the tell:
**literals interspersed with LZ control bytes.** Scanning the whole block for
ASCII runs finds **591 name-shaped strings** — the owner identifies them as the
**pattern names of the factory preset project** — each truncated where a match
reference interrupts the literal run:

```
LIGHTHOU[SE]   INSEC[T]   VITAMI[N]   CHIPELAG[O]   EDRIKAS
FYRVAK   TARN   IOTA   THREE4   OH IR   QULS
```

`CHIPELAG` is `ARCHIPELAGO` with its head consumed by a back-reference, which is
what compression does to repeated text and what no raw format does.

### Why every earlier measurement now makes sense

| observation | explanation |
|---|---|
| entropy 7.507 — above code, below general compression | LZ-compressed data with frequent literal runs |
| byte-plane entropy delta **0.003** (code shows 1.183) | not PCM; compressed bytes have no MSB/LSB structure |
| no sample-to-sample autocorrelation | same |
| the owner's audition: "noise with some clicks" | compressed data played as PCM |
| aPLib depack finds nothing at any offset | it is a different LZ variant, or framed |

**So the transients are not here**, and the five renderings that were auditioned
were never going to be them. The elimination is now explained rather than merely
observed, which is the difference between "we did not find it" and "we know what
that is".

### What it adds that is worth having

**The DN2 ships its factory preset project compressed inside MAIN OS.** That
was not previously recorded anywhere in this repository, and it bears on
`docs/ideas-backlog.md` §1: a region this large with a known content type is a
much better-understood neighbour than "dense bytes" when reasoning about space.

It also rules the block out for a second, independent reason. A project holds
patterns, sounds, kits and settings — **not sample data**. Even before the
compression argument, a factory project is not where 125 PCM transients would
live, so this region is doubly excluded rather than merely unexplained.

It still reframes the transient hunt. A *compressed* transient bank would look
exactly like this one did — high entropy, no PCM structure, invisible to every
detector in `docs/pcm-hunt.md`. So "not found by a PCM detector" was never
evidence of absence anywhere in this image, and the remaining question is
whether another compressed blob exists that is not this one.

---

## 12. `ghidra/FindDataRefs.java` never worked, and a doc quoted its zero

Found while doing §11, and it invalidates a recorded explanation.

The script answers "who points at this range?", and did it by walking
`getReferenceIterator(lo)` — which iterates references ordered by their **from**
address. Passing `lo`, an address in the *data* region, means every reference
originating in the *code* region below it was never visited. It then compared
each reference's **to** address against `hi` and `break`-ed on the first one
above the range, which — iterating by from-address — happens almost immediately.

It returned `total 0` for everything.

**`docs/modulation-mask.md`'s method note quoted that zero** for the parameter
table and explained it as *"a property of the reference model and not evidence
of absence"*. The sentence about Ghidra is true in general; attached to this
result it explained a broken loop. `docs/version-anchors.md` records **44 `lea`
sites** against that table's base, and a working scan finds them.

**The control is what caught it.** Running the fixed script against the
parameter table — a range known to be referenced — returns 10 references, the
largest group being `FUN_400dc4d0`, which `docs/parameter-set-tables.md`
independently names as **`param_set_tables_build`**. A tool that finds the known
consumer of a known table is a tool whose zero means something.

*A scan that returns zero for the thing you are testing and zero for a thing you
know is there has told you about itself, not about the image.* This project has
now made that mistake with a regex over section 7, with a `lea` scan over the
parameter table, with a linear SHARC walk, and here.

---

## 13. The codec is not identified, and the hunt is parked here

**2026-09-14.** Two attempts to get inside the compressed block, both negative.

**The emulator route (the owner's idea, and the right one).** The firmware must
decompress what it uses, so a bank invisible in the compressed image should be
plain in RAM. `scripts/ram_audio_scan.py` boots and scans. **Its own control
voids it:**

| region | hit rate |
|---|---:|
| **MAIN OS image — control, known not audio** | **4.9%** |
| main BSS, high | 2.0% |
| main BSS, low 16 MB | 0.2% |

The control scores highest. The detector fires on firmware code more than on any
candidate, so it measures structure, not sound.

The mechanism is shared by both surviving tests and is worth recording: a
**pointer table passes both**. High bytes nearly constant (`0x40`-`0x46`) gives
one low-entropy byte plane against a varying one — a large plane delta; and
consecutive pointers are numerically close, which reads as autocorrelation. The
best candidate, `0x446ce000`, is **53% ColdFire addresses**. A pointer rejector
was added and the control still wins.

*Three detectors have now failed for three different reasons — zero-crossing
rate rejected the wavetables, plane-asymmetry and autocorrelation reward pointer
tables. Detecting audio by its statistics is not working in this image, and the
next attempt should watch code rather than bytes.*

**The codec route.** `ghidra/FindDataRefs.java` (fixed, §12) gives six functions
referencing the block. `FUN_401827c4` pushes `0x40240000` six times and
decompiles to 5,810 bytes with eight parameters, heavy byte-pointer and bit
work, and a hash table sized `1 << (n & 0x3f)` — the shape of a compression
codec, though the hash chain is a *compressor* trait and the direction is not
established.

DNX reports stored project files from the device "decode with DNX's LZ4 path",
so LZ4 was the obvious guess. **It is not LZ4**, at least not unframed: a
minimal LZ4 block decoder tried at every byte offset through the first 512
produces nothing over 20 KB. The firmware-embedded blob and the device's stored
files may simply use different codecs.

## What is actually known about the transients, after all of it

- They are **samples** — Elektron have said so (owner).
- `TRAN` (id 286) spans integer positions 0..124, and its value formatter prints
  a signed decimal, so it is a continuous control over ~125 positions rather
  than a 125-item menu.
- They are **not** in any section as raw float32 or int16 PCM.
- They are **not** in the factory project block, which is that block's actual
  identity and excludes it twice over.
- The DN2 exposes **no sample filesystem** — confirmed both by elektroid's
  device table and by the instrument's own supported-opcode list.
- DNX has never seen anything transient-shaped in the device's data store, and
  the word appears nowhere in its code or docs.

Everything beyond that has been the elimination of our own instruments. **Parked
here** rather than pursued further: the remaining leads all require either
identifying an unknown codec or driving an encoder the emulator cannot drive
(`scripts/encoder_drain.py`).

---

## 14. FOUND — and the Syntakt pack is why

**2026-09-14.** The owner suggested looking at Syntakt, whose recent OS ships
user-loadable transients, on the chance Elektron uses one transient system
across both machines. It did not confirm that. It did something better.

### The ground truth nobody had

`Syntakt-OS-1.41.zip` carries a **Twinshot Sound Pack** of plain WAV files, and
eight of them are named **`TRANSIENT 01`-`08.wav`**: 16-bit mono, 44.1 kHz,
5,292 frames = exactly 120 ms. Elektron's own transients, as files.

Measuring this project's detector against them gives the numbers that had been
*invented* every previous time:

| | real transients | the pointer tables that fooled us | old threshold |
|---|---|---|---|
| plane-delta | **0.99 - 3.67** | 0.45 - 0.77 | 0.35 |
| step-correlation | **0.978 - 0.995** | 0.36 - 0.92 | 0.35 |

**The thresholds were three to ten times too loose.** Every false positive in
§13 sat comfortably above them, and real audio clusters far higher and far
tighter. Three detectors failed across this document for three different
reasons, and all three shared one cause: *no positive sample of the thing being
detected.*

### Re-scanning with measured thresholds

| region | hits |
|---|---:|
| **section 3, MAIN OS code — control** | **0** |
| sections 2, 4, 8 | 0 |
| SHARC code and rodata regions | 0 |
| **section 7, DDR `0x80000018`** | **19, contiguous** |
| section 7, L1 data | 3 |

The control is finally clean. The hits form one span,
**`0x8045b818`-`0x804a5018`, 301,056 bytes**, 45 of 57 steps adjacent.

Raw bytes read as audio with no interpretation: `59 01 4d 01 45 01 36 01 22 01`
is 345, 333, 325, 310, 290 — a smooth decay.

**The owner confirmed by ear:** the span is many transients concatenated, and an
8 KB slice of it is a single transient.

### The entry length is 100.0 ms

The transients are packed with no silence between them, so silence-based
segmentation yields one blob. The envelope is periodic instead: autocorrelating
a 64-sample RMS envelope gives a dominant lag of **~4,800 samples**, with 9,600
as its harmonic.

4,800 samples at 44.1 kHz is an awkward 108.8 ms. **At 48 kHz it is exactly
100.0 ms** — a design number. So the bank is 48 kHz, and the span holds
**31 entries**.

### What is not established

- **31 entries, not 125.** `TRAN` spans integer positions 0..124. 31 x 4 = 124
  is arithmetically striking, and `TRAN`'s value formatter prints a *signed
  decimal* rather than an index (§5), which fits interpolation between entries —
  but nothing here demonstrates that mapping, and it is recorded as a
  coincidence to test, not a finding.
- **The span may be clipped.** 150,528 / 4,800 = 31.36, not integral, so the
  boundaries are approximate and the bank may extend past what the detector
  scored.
- **Whether these are the FM drum transients specifically**, as opposed to some
  other short-sample set the SHARC carries, is unproven. They are PCM, they are
  in the audio DSP's image, and they are transient-shaped and transient-length.

### The correction this supersedes

§7 examined this same region, read it as **float32**, found a run of `1.0f` at
the head and semitone-spaced ratios at the tail, and concluded "pitch/detune
ratio tables, not audio". That was sampling the ends of a **mixed** region and
never testing the middle as int16. The region holds both.

### The bank's extent, period and phase — all measured

The first span was clipped at both ends by the detector's own threshold: there
is audio at `0x8045a818` (peak 32,661) before it and well past `0x804a5018`
after. Classifying the whole DDR payload in 2 KB windows shows the real
structure, and it is bounded by content of a *different kind* rather than by a
threshold:

```
0x80459000  zero
0x8045a800  float    <- a float32 table
0x8045b000  AUDIO ...................................  the bank
0x804ac000  float    <- another float32 table
0x804ad000  zero
```

**The bank is `0x8045b000`-`0x804ac000` = 331,776 bytes = 165,888 samples.**
The AUDIO/other alternation inside it is the detector going marginal on denser
passages, not a real boundary — the float tables either side are the boundary.

**Period.** Autocorrelating a 64-sample RMS envelope over the full bank puts
**4,800 samples** top, with **9,600** and **14,400** — exactly 2x and 3x — also
ranking. Harmonics like that do not appear by chance. 4,800 samples is an
awkward 108.8 ms at 44.1 kHz and **exactly 100.0 ms at 48 kHz**.

**Phase.** Chosen by measurement, not assumption: for each candidate phase,
score the energy just after each boundary (an attack) against the energy just
before the next one (a decayed tail). Phase 2,496 scores **14.27**; the next
family of phases scores **1.46**. A tenfold preference means the cuts land on
real hits.

### The count does not resolve, and that is the open question

165,888 / 4,800 = **34.56**. Cutting at the measured phase yields **34 entries**
with a remainder.

That does not agree with the control side. `TRAN` spans integer positions
0..124, and the owner confirms the firmware **interpolates between entries** —
which, at 4 steps per gap, implies `4 x (N-1) = 124`, so **N = 32**.

Three readings of the same bank, none yet reconciled:

| source | count |
|---|---|
| envelope period over the measured extent | 34.56 |
| phase-aligned cut | 34 |
| `TRAN` range + 4-step interpolation | 32 |

Possibilities, none tested: the extent includes ~2 entries of something that is
not a transient; the interpolation step is not 4; or the entry length is not
constant across the bank. **What is solid is the location, the format (16-bit
mono, 48 kHz) and the ~100 ms period. The count is not.**
