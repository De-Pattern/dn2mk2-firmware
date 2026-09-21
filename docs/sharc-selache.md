# selache: an open-source SHARC+ toolchain, scored against our DSP image

**2026-09-19.** <https://github.com/js216/selache> (Jakob Kastelic), evaluated at
commit `2b26d3b` on the Digitone II 1.11 DSP program (section 7), with the
Digitakt II 1.15C/1.16 and Digitone II 1.10E images as a check. It helps the
FX-track work (`docs/ideas-backlog.md` §8) and digikit in the same way: it is a
second decoder and a working assembler for the processor we can least read.

The findings went upstream as `m-dwyer/digikit#31`, with the comparison report
committed there as `docs/sharc/selache-comparison.html`. A follow-up on
`m-dwyer/digikit#8` explains why that issue's "no rule can exist" conclusion
probably came from the same table error.

## What it is

A Rust workspace: `selas` (assembler), `selcc` (C99 compiler), `seld` (LDF
linker), `selload` (ELF → LDR boot stream), `seldump`, `selpatch`, `selmem`,
`selar`, `selhex`, `selinit`, `selsyms`, and the library that matters most here,
`selinstr` (encoder, disassembler, VISA width and compression). GPL-3.0; its C
library `libsel` is MIT.

**Licence position.** GPL-3.0 combines with this repository's AGPL-3.0-or-later,
so linking is allowed, but selache is still **not vendored**. `tools/selmap` is 40
lines of our own code that calls `selinstr` through a path dependency on your own
checkout. digikit is GPL-2.0, which cannot take GPL-3.0 code at all, so only
measurements went there.

## Building it (WSL or Linux)

The Windows build fails: Git Bash's `link` shadows MSVC's, and MSVC is not
installed. WSL works:

```sh
curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal
source ~/.cargo/env
cd /mnt/c/ZZ_Code/ZZ_Personal/selache
CARGO_TARGET_DIR=/root/selache-target cargo build --release
cd /mnt/c/ZZ_Code/ZZ_Personal/dn2_firmware/tools/selmap
CARGO_TARGET_DIR=/root/selmap-target cargo build --release
```

`tools/selmap/Cargo.toml` expects selache as a sibling of this repository.

## The oracle

`scripts/sharc_selache_compare.py`. Every absolute `cjump` site and target is a
known instruction start (`sharc_callgraph.py`: 1,606 sites and 461 entries on
1.11, all in code). A walk between two consecutive starts must land exactly. It
can stop, land or overshoot, so the test can say "wrong".

**The control matters more than usual.** VISA resynchronises within a few
instructions. A selache walk started 2 bytes *late* still lands 94.9% of spans,
so the evidence is only the margin over that control, never the headline.

## Results, DN2 1.11

```
python scripts/sharc_selache_compare.py 00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip --digikit ../digikit-up/tools
```

| | digikit `a5643ba` | digikit + #31 | selache | selache, 2 B late |
|---|---|---|---|---|
| spans landed exactly, of 2,030 | 1,712 (84.3%) | 1,966 (96.8%) | 2,009 (99.0%) | 1,927 (94.9%) |
| stopped / overshoot | 318 / 0 | 64 / 0 | 0 / 21 | 0 / 103 |
| in-function cjump sites landed, of 1,589 | 949 | 1,399 | 1,570 | 1,548 |

- selache's pc-relative branch targets fall on an instruction start **92.2%** of the
  time, against 43.7% for random targets. The misses cluster on `if av`,
  `if flag0_in` and `if nbm` jumps, which is data read as code.
- Instructions with a `?` field: 0.48% of those walked.
- Along digikit's walks the two give different lengths for 2,667 of 27,542
  instructions. The walk decides 232 of them:

| digikit form | words | digikit / selache say | oracle sides with |
|---|---|---|---|
| `2a` (really `2b`) | `0x0180–0x01FF` | 48 / 32 | **selache 119 : 0** → digikit#31 |
| `21p_undoc16` | `0x0000–0x007F` | 16 / 48 | digikit 62 : 25 (mixed) |
| `23p_undoc16` | `0x0200–0x03FF` | 16 / 48 | selache 10 : 4 (mixed) |
| `4a` | `0x6A3E…` | 48 / 32 | digikit 8 : 0 |
| `16a`, `7a`, `3c` | | | digikit 4 : 0 |

### The two table fixes (digikit#31)

1. **Type 2b is the PGR's `000000011`, not the PRM's `110000000`.** digikit had
   switched to the PRM value over "width collisions", but those were measured
   under the old most-fixed-bits rule. The known-boundary walk gains 170–231
   spans per image across four images, with zero overshoot. selas independently
   encodes `r1 = r0 + r1` as `0x0180 0x1101`.
2. **`Type10a_rel` (`111`) decodes in VISA** despite the PRM's "ISA-only". It
   adds 21–31 spans per image, again with zero overshoot. `Type10a_abs` stays
   out: against Type 2c on `0xDxxx` the test ties.

`tools/sharcpcode.py compare`: 0 regressions, and aligned decodes rise from
21,361 to 22,678 on 1.11.

## The round trip: disassembly is not a patch format

```
# in WSL
python3 scripts/sharc_selache_roundtrip.py out/sharc/code_283825c4.bin \
    --selmap /root/selmap-target/release/selmap --selas /root/selache-target/release/selas
```

11,440 distinct encodings from the L2 main program, each disassembled, then
reassembled alone at its original width:

| outcome | count |
|---|---|
| identical | 9,599 (83.9%) |
| same width, other bits — register fields the text drops (`bitrev`, `modify`, `dm` moves) | 1,265 |
| width changed, 32 → 16 or 32 → 48 | 216 |
| rejected — forms it prints but cannot parse (`compute(0x…)`, `alu opcode`, `ureg(0x7e)`) | 320 |
| assembler panic | 40 |

The first attempt at this, one stream from offset 0, looked far worse (3 of
116). All of that was zero padding: a 48-bit `nop` prints as `nop`, which
reassembles as the 16-bit `nop`. Text carries no width, so the per-instruction
form with `.NOCOMPRESS` is the only fair test.

## The boot stream, from the producer's side

A four-line program (`r0 = 0x1234; r1 = r0 + r1; nop; jump start;` plus three
data words) was assembled, linked by `seld` with selache's `libsel/link.ldf`, and
written as an LDR by `selload -b SPI -f binary`. `dnfw.image.bootstream.load_regions`
read it back into exactly the linked sections. The code landed at `0x28300000`,
which is 2 × `0x180000` + `0x28000000`: the rule `sharc_callgraph.py` uses,
confirmed by a producer rather than inferred. The headers are 0xAD-signed with
XOR zero, and the words are LE, MSB word first. `selload` only writes LDR; it
has no reader.

## Integration with our tooling

selache enters beside the pipeline, as a tool, never inside `dnfw`.

1. **Oracle, now.** Whenever digikit's decode table or one of our SHARC readers
   changes, run `scripts/sharc_selache_compare.py`. A disagreement the walk
   decides becomes an upstream table fix carrying the firmware measurement, as
   #31 did. Next candidates: the `0x00xx`/`0x02xx` undocumented families, and
   `0xDxxx` (Type 10a_abs vs 2c).
2. **Reading, for the FX-track work (§7, §8).** After #31 lands, digikit's
   `decode_table.json` (and the SHARC_VISA Ghidra language generated from it)
   stays the primary reading surface, with selache's text as a second opinion.
   selache's lengths never stop, so they give an aligned sweep of the whole
   230 KB today. Its text is a reading aid with known holes: `?` forms, and
   data read as code.
3. **Authoring, for DSP patches.** Write the patch as source, assembly or C
   (`selcc`), never as edited disassembly. Place it with `seld` and an LDF that
   describes only the chosen free range. Check it by re-decoding every emitted
   instruction with both decoders, with every boundary agreeing. Then write it
   with `bootstream.write_span` into section 7, and repack and sign with the
   existing `dnfw build` path. Still missing, and each is a project of its own:
   a map of free DSP memory, hook points from the call graph
   (`sharc_callgraph.py`), and a known failure mode when the DSP program is wrong
   (the ColdFire presumably still boots, which is an assumption, not a result).
4. **Whole programs, later.** `selload` can emit a complete boot stream. It is
   validated here on a toy program only, and needs the ColdFire upload path
   (`docs/sharc-image.md`) understood first.

**Not for LFO4.** LFO4 is ColdFire code. Its C toolchain is m68k GCC in the
appended area (`docs/lfo4-build-plan.md` §8); selache compiles for the SHARC
only.

## Limits, kept

- selache's 16-bit set is narrow (`0x0001`, `0x0081`, `0x00C1`, `0x0AFE`,
  `0x1901`, `110x`, `1001…1…1`). The firmware's undocumented `0x00xx`/`0x02xx`
  16-bit words, which digikit models, it reads as 48-bit, and there it is more
  often wrong.
- Its width rule looks at two words at most, with one `word1 & 0x3F ≥ 0x38` test
  for the ambiguous families. That is the same bit test as digikit's 4b.
- It does not know this firmware: no symbols, no names, nothing about Elektron's
  DSP program. It only helps to read and write the instructions.

---

## digikit's decoder overtakes selache on DN2 1.11 — 2026-09-20

Measured with `scripts/sharc_selache_compare.py` on our own image
(`Digitone_II_OS1.11_dist.zip`, 1,606 cjump sites, 461 entries, 230,072 B of
code), against three versions of digikit's table: upstream before PR #33,
this project's #31 branch, and upstream after #33.

| table | spans exact, of 2030 | stopped | overshoot | function-entry walks |
|---|---|---|---|---|
| before #33 (`a5643ba`) | 1712 (84.3%) | 318 | 0 | 949 / 1589 (59.7%) |
| our #31 branch | 1966 (96.8%) | 64 | 0 | 1399 / 1589 (88.0%) |
| **after #33** | **2022 (99.6%)** | **8** | **0** | **1581 / 1589 (99.5%)** |
| selache (unchanged) | 2009 (99.0%) | 0 | **21** | 1570 / 1589 (98.8%) |

**The in-repo decoder is now ahead of selache on this image** — more exact
spans and, more tellingly, **zero overshoots against selache's 21**. An
overshoot is the outcome that means *wrong*, which a percentage alone hides.
That is a first, and it is upstream's win, not ours.

It also closed our own PR #31. That branch argued `Type2b` should be the PGR's
`000000011`; #33's `Type2a_short` correction reaches further on the same
measurement (2022 against 1966 spans, 8 stops against 64), so the change would
have been a regression. Closed on the numbers.

### What it does *not* say, and the number to get next

`docs/ROADMAP.md` records that **only 18.4% of known instruction boundaries
decode** under Ghidra. **That is a different metric** and this run does not
move it: this measures the Python decoder walking between known starts;
that measures what Ghidra's SLEIGH produces after an import. The two share a
table and nothing else.

Getting the comparable figure means regenerating SLEIGH from the corrected
table (`tools/sharcspec/ghidra/gen_sleigh.py`, which #33 also touched) and
re-importing. **Until that is run, no claim should be made about L2 becoming
readable** — the decoder result makes it *likely* and is not evidence of it.
