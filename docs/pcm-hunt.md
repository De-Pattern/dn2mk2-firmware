# The FM drum transients: how many there are, and where they are not

**Measured 2026-09-14 on Digitone II 1.11.** `docs/ideas-backlog.md` §3 wanted
to expand the FM drum machine's PCM catalogue and to extract the existing one.
This is the first pass, and it is mostly an elimination — but it establishes the
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
| LFO `Waveform` | `0x600` | 7 | TRI SIN SQR SAW EXP RMP RND — **7** |
| SYN `Noise Type` | `0x200` | 3 | 3 |
| **SYN `Drum Transient`** | **`0x7c00`** | **125** | — |
| most continuous params | `0x7f00` | 128 | the usual 0..127 |

So **`TRAN` selects one of 125**. That is the catalogue size, and it is the
number any extraction or replacement tool has to match.

Related parameters sit beside it and are worth having in one place, because they
say the transient is a *layer* rather than the whole drum: `Transient Level`
(`T.LEV`, id 287), `Noise Base/Width/Grain`, `Body Hold/Decay/Level`.

## 2. The SHARC image contains no audio at all

`blob` (section 7) was the obvious place — §3 assumed the samples were there,
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
change per thousand samples — that is a sparse table, not a waveform. Two-thirds
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

**It fires on 99.9% of both code regions.** Those are instructions — established
independently by the cjump census, with nothing to do with this test. A detector
that calls compiled code "audio" nineteen times out of twenty is measuring
entropy, not sound, and every int16 row it produces is worthless.

This is why the control was built in: *a watch must be able to produce a
different answer for each outcome.* Without the code rows, the int16 table looks
like a discovery — 32% of a rodata region "is audio" — and it is nothing.
The float32 rows are trustworthy for the opposite reason: they came back **zero
everywhere**, including on the regions the detector could have flattered.

## 4. What was ruled out in MAIN OS, and what is left

MAIN OS has ~1 MB past the code boundary at `0x401d0000`. Profiling it in 64 KB
chunks finds one dense, high-entropy block at **`0x40240000`–`0x40280000`**
(~256 KB, 3% zeros) — and 256 KB over 125 transients is ~2 KB each, which at
16-bit/48 kHz is ~21 ms. Exactly a transient's length. It fits arithmetically.

**It does not survive a structural test.** If that block were 125 samples it
should segment: silence between hits. Scored in 128-sample RMS windows, the
whole 384 KB span shows **3 quiet→loud transitions read little-endian and 7 read
big-endian**, not 125.

Nor is there an index. Scanning MAIN OS for strictly-increasing 32-bit runs
(the shape an offset table has and little else does) finds three ~129-entry
tables, and all three are mathematics rather than pointers:

```
0x401d88d0   0, 0x2932e, 0x5265c, ...   constant delta 168750
0x40287b04   ...                        constant delta  84375
0x4020b358   0, 0x4c6c8ea9, ... 0x80000000   a saturating curve
```

Arithmetic progressions and a saturation curve — tuning/phase increments and a
transfer function, not a sample catalogue.

## 5. Where this leaves the idea

**Established:** the catalogue is 125; the SHARC image holds no audio; entropy
and statistics cannot find samples in this firmware because compiled ColdFire
code defeats the test.

**Not established:** whether the transients are sampled at all. `TRAN` selecting
1 of 125 is equally consistent with 125 short PCM hits and with 125 parameter
presets driving a synthesised click — and FM DRUM is documented by Elektron as a
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
device holds — answering "are there samples at all" without patching anything.
Read-only, and gated on the owner's go-ahead and a named transport.

## Reproducing

```
python scripts/find_pcm.py 00_Resources/00_Firmware/<image>.zip
python scripts/find_pcm.py <image> --section 3
```

Carved output goes outside the repository. The transients are Elektron's
copyrighted content: extracting them for local analysis is one thing,
redistributing them is not something this project does.
