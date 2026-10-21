# Digitakt II machines and samples on the Digitone II: the port map (step 1)

**2026-10-21.** Step 1 of the owner's request to bring the Digitakt II's sample machines
(ONESHOT, WERP, STRETCH, REPITCH, GRID) and its sample storage to the DN2, prompted by
Ermifio's *DIGITONETAKT* video, which shows exactly that running on a DN2: one MACHINE
SEL list holding FM Tone, FM Drum, WaveTone, Swarmer, ONESHOT, WERP, STRETCH, REPITCH and
GRID; the DT2's ASSIGN SAMPLE browser with a folder tree; its slice editor and the SLICES
trig mode. His reply under the video: *"It is the exact same board, including the
storage."* Nothing of his method is published.

Read-only: two firmware files, nothing sent to an instrument. Images: **DN2 1.11** and
**DT2 1.17** (`Digitakt_II_OS1.17.syx`, product code `0082`). Its DSP program (section 7)
is **byte-identical to DT2 1.16's** (sha256 `0f514a12...`), so every earlier DT2 SHARC
finding in this repo (`docs/dt2-machine-port.md`, `docs/drive-storage-research.md` §4,
`docs/chimera-feasibility.md`) holds for 1.17 unchanged.

Marks as elsewhere: **[V]** measured here, **[D]** read once, **[S]** inferred.

## The two firmwares, section by section

| section | DN2 1.11 | DT2 1.17 | |
|---|---|---|---|
| 2 bootstrap | 30,302 | 30,302 | 4.6 % of bytes differ (`docs/chimera-feasibility.md`) |
| 3 MAIN OS (ColdFire) | 3,192,192 | 3,275,616 | one codebase, build-flagged |
| 7 DSP program | 836,956 | 321,016 | different programs |
| 8 | 159,948 | 159,948 | byte-identical |

## ColdFire: what the DN2 lacks [V]

C++ class names (Itanium typeinfo strings) in the two MAIN OS images: **431 shared, 21
DT2-only, 14 DN2-only** (plus a few short strings that only look like names). The DT2-only ones are the whole sample side:

| group | classes |
|---|---|
| sample filesystem (`ekFS`) | `File`, `Directory`, `FileSystemDirectory`, `FileOutputStream`, `FsRequestHandler::FileWriter`, `SamplePoolDirectory` |
| sample management | `SampleManager`, `SamplePicker`, `AssignPrompt`, `FreeSpaceMenuView` |
| sample browser | `SampleListView`, `SampleBrowserPopupMenuView`, `SampleFSSelectView` |
| the machine page | `SourcePageView` (the DT2's SRC page) |
| slicing | `CreateSliceGridHelperview`, `ManualSliceEditorView`, `ManualSliceHelperView` |
| sampling (recording) | `SamplerView`, `SamplerLedView`, `Recorder` |
| outputs | `BreakOutBoxOutputRoutingMenuView` |

(The DN2-only ones are its voice, chord and arp classes: `VoiceConfig*`, `ChordMemory*`,
`ArpSetupMenuView`, `MultiSourcePageView`, `KeyboardSetup`.)

**Size.** Their virtual methods, matched against the DN2 by masked byte signature: about
**590 methods with no DN2 counterpart, roughly 150-240 KB of ColdFire code** [S] (the
estimate runs each method to the next known function entry, so it over-counts; the
MAIN OS sizes differ by only 83 KB, but the DT2 also lacks the DN2's voice/chord code).
Plus non-class code the methods call (the `ekFS` driver at DT2 `0x4015a450`, the pool
allocator at `0x40153814`, the loader logic), not yet sized.

**Already on the DN2** [D]: the eMMC block driver and part table (identical), the MIDI RPC
sample-transfer message classes (`MidiRpcFsSample*`, all of them), `SampleLoaderBgWorker`,
`SampleWaveformsFactory`, xxHash32, and the ColdFire end of the sample link to the DSP
(the Rapid-GPIO port at `0x8c000000`, enabled identically).

## DSP: what the DN2 lacks [V]

`tools/sharcdb.py` on both section 7s, functions compared by relocation-tolerant hash:

| | |
|---|---|
| DT2 functions | 1,228 (50,752 instructions) |
| **with no DN2 twin** | **190 functions, 12,912 instructions** |
| of those, in the L1 code block | 10,972 instructions |

The largest are the DT2 engine's own per-slot dispatch (`0x1c642a`, 1,464), per-track
loop (`0x1c2b24`, 766), the per-track unpack (`0x1c24e9`), the sample readers sharcdb
labels "interpolating table lookup" (`0x1c18a6`, `0x1c5615`, `0x1c4f81`, `0x1c53c5`), the
pool's control-block code (`0x1c3bef` and five callees) and the link-port receiver
(`0x1c3f78`, `0x1c3fe5`, `0x1c7e35`, `0x1c7ec5`).

**Memory.** The DT2's DSP program claims DDR to **`0x82a001c4`**: a 32 MiB zero fill at
`0x80a00000` and a control block at `0x82a00000` that the DN2's does not have (the DN2
claims to `0x8052fbe0`). **That range overlaps where our own DDR data now lives**
(RESONATOR, CZ, PING, SHFT, GRAN and PERC tables and state at `0x81200000-0x81218000`,
GRAN's buffers at `0x81400000`). A port that keeps the DT2's addresses moves ours; a port
that re-places the DT2's code moves its. The 400 MiB sample pool itself is in DSP DDR
[D]; the DN2's DSP has a 512 MB part, of which the stock program claims about 5 MiB [S].

## Machine slots

The DSP maps the frame's machine field through `0x25d748[nibble]`, 8 words, all used
since v0.10 (0-4 stock, 5 PERC, 6 RESONATOR, 7 CZ). If the field is a full nibble, 16
types are addressable and the table, the ColdFire list bounds (`moveq #7` at
`0x400dc332`, `0x400dc358`, `0x400dc37e`) and the LOAD bound grow together. **Not yet
measured**: what lies after the 8-word table, and whether the nibble is masked to 3
bits anywhere. Ermifio's list (4 DN2 + 5 DT2 machines, plus MIDI) needs this or an
equivalent.

## How big, and in what order

Two directions exist, and both are large:

- **A. DN2 base, DT2 parts added** (what the video looks like: the DN2's own UI, FM
  machines first). The ColdFire classes above are transplanted: their calls into code
  the two images share must be re-pointed at the DN2's copies (431 shared classes make
  that a matching problem, not a rewrite), and their data structures checked against the
  DN2's project format. The DSP sample voices are either transplanted the same way or
  re-written in our own DSL (as PERC was), reading the pool.
- **B. DT2 base, DN2 parts added** (the FM engines into the DT2's program). The DN2's
  DSP program is 2.6 times the DT2's; this is the larger move.

**A is the one to take.** Staged, each stage gated:

1. **Machine slots to 16** (needed by everything after it, and by Syntakt machines).
   Small, ColdFire and DSP, fully testable in the emulators.
2. **The DSP sample voice**: one ONESHOT-equivalent voice reading a test sample from a
   fixed DDR pool, held bit-exact to a model in the runner, like PERC. No storage yet.
3. **The link**: the ColdFire pushing a sample into that pool over `0x8c000000`.
4. **ekFS on the eMMC** (the first stage that writes storage): read-only mount first,
   then writes; the +Drive backed up before every test. Recovery is untouched by
   construction, so the risk is data, not the unit.
5. **The UI**: ASSIGN SAMPLE browser, sample locks, then slicing.
6. **WERP, STRETCH, REPITCH, GRID.**

Every stage is weeks, not days, except 1.

## What was not done

No ColdFire disassembly by function (no Ghidra project here); the method sizes are an
estimate. The DT2's DSP machine voices were not separated from its engine plumbing
beyond the hash comparison. Nothing ran in an emulator.
