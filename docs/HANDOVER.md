# Handover — 2026-09-14

Where the project stands, what is in flight, and what to do next, for whoever
picks it up. Everything here points into the rest of `docs/`; this file is the
map, not the evidence. **Overwrite it at the next handover rather than
appending.**

## In one paragraph

`dnfw` takes an Elektron OS `.syx`, decodes every layer, lets you replace or
patch a section, and rebuilds a signed image the instrument accepts. **Phase 1
is closed** — a recompressed image (Gate D) and a visibly patched one (Gate E,
`SETTINGS > PERSONALIZE` → `DNFW ALIVE!`) both boot on a Digitone II, and the
recovery route is proven. **Phase 2 — a fourth LFO — is blocked on the DSP, and
the engine question is open, not closed.** The control side is fully mapped and
costed; the generator is SHARC-side and we can decode only ~18% of SHARC
instruction boundaries. A parallel thread (extracting the FM drum transients)
is an elimination so far.

## Standing constraints — read before doing anything

These are the owner's, and they do not lapse:

- **Never push to `main`.** Branch per feature, atomic commits, PR at the end;
  the owner merges.
- **No firmware bytes in the repository, ever.** `00_Resources/` and `out/` are
  gitignored. Code and documentation only. Carved audio stays local too — it is
  Elektron's copyrighted content.
- **Never send `#WRITE_SERIAL`, `#WRITE` or `#MMC_RECONFIGURE`.**
- **Do not patch the "Multiplier" key material** (`docs/ele3-format.md` §5).
- **Nothing reaches the instrument** without the owner's explicit go-ahead *and*
  a named transport. Verify with `dnfw inspect` first.
- **Accumulate knowledge.** Never delete a superseded conclusion — mark it
  `[SUPERSEDED]` / `[WRONG — corrected <date>]`, point to the replacement, and
  keep the reasoning. `docs/PRINCIPLES.md`.
- **Keep claude.ai session URLs out of PR descriptions.** Commits yes, PR bodies
  no.
- PRs are opened through the GitHub API using the `GITHUB__PERSONAL_CLAUDE`
  env var — **no `gh` CLI**. Write PR bodies to a scratchpad `.md` file; never
  bash heredocs with backticks.
- Code shape: one subject per module, no god files, every capability reachable
  from `dnfw`, reuse the reference repos before writing.

## Status

| | |
|---|---|
| Gates A/B/C/F (offline) | done — `pytest test/` |
| Recovery path, stock image | done 2026-09-08 |
| Gate D / Gate E, normal update path | done 2026-09-11 |
| Recovery-path stall at ~80% | resolved — it was the MIDI link, not the image |
| Code caves execute on hardware | **proven** — `CAVE RAN!!!` (`docs/code-caves.md`) |
| Phase 2: is the LFO count a table? | yes — `docs/lfo-parameters.md` |
| Phase 2: what reads the table | ~50 accessors, `base + id*60` — `docs/parameter-table-consumer.md` |
| Phase 2: the display path | mapped by measurement — `docs/display-path.md` |
| Phase 2: **does the engine implement a 4th LFO?** | **UNKNOWN — the two "confirmed" results are withdrawn** |
| SHARC: which bytes are code, and their addresses | solved, both spaces — `docs/sharc-code-map.md` |
| SHARC: can we read instructions? | **only ~18%** — `docs/sharc-reading.md` |
| FM drum transients: located? | **no** — `docs/pcm-hunt.md` |

## The one thing most likely to mislead you

**`docs/engine-index-map.md` §§11 and 14 are WITHDRAWN by §15.** Their headings
used to read `CONFIRMED ON HARDWARE: the engine implements a fourth LFO`, and
that is not true. The probe re-pointed the forward *and* inverse maps together,
so values were written to new offsets and read back from those same offsets — a
self-consistent **storage** round-trip. `Sound::updateMirror` takes a
`Digisharc::soundStorage_v3_t`, which is the *persisted* format DNX decodes, not
an engine structure. The test could not distinguish "the engine runs a fourth
LFO" from "the round-trip is consistent", and both predict the observed result.

Withdrawal banners are now in both headings. **This caught the last session:** a
retraction 180 lines below a heading saying CONFIRMED does not work, and the
claim was reported to the owner as settled fact.

**What still stands:** the reserved fourth slot is real, from three independent
readings (DNX's stored format, DNX's pattern p-lock ids, and this project's
ColdFire-side derivation). What was never shown is that the *engine* acts on it.

**The cheap falsification, still not run:** on stock firmware, save a sound with
LFO3 configured, back it up, and have DNX check whether the bytes land at
offsets 34, 42, 50… If they do, the storage reading is confirmed from a third
direction. No `.dnx` backups exist locally — this needs the owner and a device.

## What a fourth LFO would now cost

`docs/engine-index-map.md` §13 measured the binding constraint:

- the sound object's value array is **exactly 101 entries**, `+0x14`…`+0xDD`
- `+0xDE` is machine type, `+0xDF` is filter type — **the array is flush
  against them**
- live fields continue at `+0xE0` … `+0x146`, so the array sits **mid-structure**
- all **29** access sites use the brief extension word (8-bit displacement), so
  none can be repointed above `+0x7F` without a cave

So the array cannot grow, the object cannot grow, and relocating means 29
detours. The surviving route is §13's: **serve slots ≥101 from a separate array
in the unclaimed RAM above the BSS end**, hooked at four choke points
(`Sound::updateMirror`'s two loops, the reverse copy at `0x400dd25e`,
`parameter_value_getter`). The storage path needs the same treatment for the
values to survive a save, and that part is unscoped.

**None of this is worth building until the engine question above is answered.**

## Where the SHARC work got to

`docs/sharc-reading.md` is the current file; `docs/sharc-code-map.md` has the
addresses.

- **461 functions** derived from call sites alone — every cjump target is an
  entry. `scripts/sharc_callgraph.py`.
- **FreeRTOS is L1, the application is L2** (105 KB). Proved by the image's only
  eight real strings: seven FreeRTOS paths and `Audio Task`, all resolving into
  L1 except `Audio Task` itself.
- **Data operands use a different rule from code addresses**: word-swapped
  `LE(hi) || LE(lo)` of `(load_addr - 0x28000000)`, **byte**-counted. Searching
  with the code rule found zero hits in 6.4 MB.
- **Both regions live in one Ghidra program.** digikit's SLEIGH resolves targets
  itself (`((w1 & 0xff) << 17) + (w2 << 1)`), so L1 goes at `0xb8 << 17` =
  `0x1700000` and all 1,025 `0xb8` calls resolve natively.
  `scripts/export_sharc_regions.py` + `ghidra/SharcImport.java`.
- **Decode quality, scored against an oracle the decoder never saw** (the 1,606
  validated cjump sites):

  | method | bytes covered | boundaries hit |
  |---|---|---|
  | linear walk | 6.9% | 3.9% |
  | Ghidra, following flow | 32.7% | **18.4%** |

  Our own earlier "~81% confidently decoded" is **retracted** — it restarted the
  walk after each stop, and an all-zero word decodes as a confident `Type21a`.
- **95% of failures are one length ambiguity**, `GROUP_5A_5B_MOVE`, which
  digikit marks as an open gap. `scripts/sharc_lengths.py` used 1,606 boundaries
  as constraints and found **five `(word0, word1)` pairs forced both ways** —
  so no rule over those two words can exist. Sent as `m-dwyer/digikit#8`.
- **Unexplained and important:** 778 of 792 unsolvable spans *overshoot* the
  next boundary. Three causes tested and all negative (no too-close boundaries,
  cjump length decodes correctly, entries are not alignment-padded). **Settle
  this before turning the solver into a decoder.**

### Upstream

| | |
|---|---|
| `m-dwyer/digikit#7` | PR — `disassemble()` crashes formatting `word1` when it was never read. Verified stock-crashes / patched-yields. |
| `m-dwyer/digikit#8` | Issue — the 5a/5b evidence above. |
| `#4` open, `#5` closed (our retraction), `#6` open | encoder-flush findings |

## The FM drum transients — what is eliminated

`docs/pcm-hunt.md`. **The owner states as fact that they are samples (Elektron
said so), so every null below is a statement about the search, not the device.**

| Candidate | Verdict |
|---|---|
| MAIN OS `0x40238800`–`0x40287400` (322 KB, dense) | **owner auditioned the WAVs: noise with clicks** — packed bitstream, not PCM |
| SHARC L1 data `0x2001e888` (432 KB) as int16 | 69% silent, 7 segments — not a bank |
| SHARC float32 arrays | LUTs — **1025 floats = 1024+1** guard point, smoothness 0.001 |
| SHARC DDR `0x804ace88` | zero-filled; the "find" was an artifact |

**Two detector faults, both ours, both fixed:** a zero-crossing threshold of
0.05 calibrated for noisy audio (a single-cycle wavetable is ≈0.008, so it
rejected the wavetable bank this repo had *already found*); and treating
"bounded" as "non-zero", since `0.0` lies inside `[-1.1, 1.1]`.

**Also corrected: `TRAN` is not an enumeration.** Its record (id 286, at
`0x401fc2d8`) has max `0x7c00` = **124.00 in 8.8 fixed point**, and its value
formatter `0x400e2ef6` renders `'%s%d.%02d'` — a signed decimal like `12.34`.
Enumerated parameters (LFO `Waveform`, `Noise Type`) have name-lookup
formatters; TRAN does not. The integer range 0..124 is still 125 positions, and
the fraction may morph between bank entries, but **"125 named transients" was
overstated** and the formatter is display-only — it does not reach the data.

**The hypothesis that explains every negative:** the transients are not in the
OS update at all. The ColdFire does no audio DSP, so they must reach the SHARC;
they are not in the SHARC image; MAIN OS holds nothing playable. MAIN OS *does*
carry the whole `FsSample*` RPC surface and `SampleLoaderBgWorker`. Factory
content in the device's own storage fits all of it — **and would be better
news**, because customising them becomes a filesystem push rather than a
firmware patch.

**Next test:** `FsSampleListRam` (`docs/midi-rpc.md`) — read-only, one message,
lists whatever sample content the running device holds. **Gated on the owner's
go-ahead and a named transport.**

## Priority order the owner set

1. **The FM drum transients** (`docs/ideas-backlog.md` §3) — current thread.
2. FX work, **Tier A only**: p-lock / modulate the existing global FX settings
   per pattern. Its first step is free and offline — ask DNX's decoded pattern
   format whether a p-lock can address an FX parameter id at all. §8.
3. **The DN1 is parked behind the PCM work** and explicitly not started. It
   matters because the DN1 runs its audio DSP *on the ColdFire*, in the image,
   with unsigned firmware — so everything behind the SHARC wall is readable
   there, and its LFO generator could serve as a signature for finding the
   DN2's. `docs/dn1-dsp-comparison.md`.

## Environment

| | |
|---|---|
| Repo | `C:\ZZ_Code\zz_personal\dn2_firmware`, remote `dn2_firmware_explore` |
| Ghidra | `C:\tools\ghidra_12.1.3_PUBLIC` — **lowercase `tools`**; SLEIGH fails with a case error otherwise |
| JDK | `C:\Tools\jdk-21.0.12.1+1` |
| SHARC language | `SHARC:LE:32:VISA`, module copied from digikit into `Ghidra\Processors\SHARC` |
| ColdFire language | `68000:BE:32:Coldfire` — Gate F cleared; Capstone/radare2 **fail** |
| digikit | `C:\ZZ_Code\ZZ_Personal\digikit`, pinned `ec32de1`; needs patched Unicorn, run under WSL with `/root/digikit-venv/bin/python` |
| Emulator env | `DT2_SYX`, `DT2_SECTIONS=/root/t111`, `DT2_SNAPSHOTS=/root/snaps-dn2-1.11` |
| Boot snapshot | **use `emu.run.usable_rung()`** — on 1.11 only the 400M rung reaches a drawing UI. Do not copy a number from a docstring. |
| DNX | `C:\ZZ_Code\ZZ_Personal\DNX` — the verification instrument; no `.dnx` backups present |

## Recurring doctrine, earned the hard way

- **A watch must be able to produce a different answer for each outcome.** A
  decode rate computed from the decoder's own self-report is not a watch.
- **It is not enough for the experiment to discriminate — the control has to
  discriminate too.** The int16 audio detector fired on 99.9% of known code.
- **Before reporting a fault in someone else's tool, eliminate your own use of
  it.** `digikit#5` was our bug, filed and retracted.
- **A call-target resolver names a landmark, not a scope.** `dnfw fn entry --at`
  returns the nearest call target at or below, not the enclosing function.
- **An example in a docstring is not a specification.** Two full emulator runs
  were wasted on the wrong boot rung.
- **A decoder that never fails on zeros cannot tell you it has left the code.**
- **Put the retraction where the claim is.** See §§11/14 above.
