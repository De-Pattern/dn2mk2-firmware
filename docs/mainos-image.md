# The MAIN OS image

Section id 3 of the ELE3 container: the code the instrument runs.

| | DN2 1.10E | DN1 1.42A |
|---|---|---|
| depacked size | 3,085,696 | 2,420,912 |
| load address | `0x40000400` | `0x40000400` |
| byte order | big-endian | big-endian |

## It is ColdFire, and that is now measured rather than inferred

The image opens `46 FC 27 00` — `MOVE #$2700,SR`, masking interrupts, the
classic first instruction of a 68k-family reset path, at `0x40000410` behind a
16-byte header. Counting opcodes across the DN2 image: 11,285 `RTS` (`4E75`),
25,503 `JSR.L` (`4EB9`), 2,041 `LINK` (`4E56`), 2,378 `UNLK` (`4E5E`).

**Confirmed 2026-09-07 by disassembling it.** `m68k-linux-gnu-objdump -m
m68k:cfv4e` decodes instructions that exist on ColdFire and on no 68000-series
part. At `0x400015f4` and `0x400015fa`:

```
400015f4:  7f dc    mvzw %a4@+,%d7
400015fa:  71 00    mvsb %d0,%d0
```

`MVS` and `MVZ` are ColdFire ISA_B. Their encoding is `0111rrr1`, the MOVEQ
opcode space with bit 8 set, which is undefined on the 68000 through 68060.
There are **2,166** such halfwords in `0x40000400`–`0x40098000` alone.

This also matches `sambanks/octabam`, which established the Octatrack's CPU as
ColdFire V4e and loads its MAIN OS at **`0x40000400`** — the same address we
measure on both Digitones. One Elektron platform, one convention.

## Getting a disassembler that can read it

Ubuntu's `binutils-m68k-linux-gnu` provides `m68k-linux-gnu-objdump`, and its
BFD carries ColdFire even though `objdump -i` does not say so — that option
lists the coarse architecture (`m68k`) and nothing about sub-machines, so
support is tested by decoding a ColdFire-only instruction rather than read off
a capability list. `image/objdump.py` does exactly that.

On Windows, the shortest route is WSL:

```
wsl -u root apt-get install -y binutils-m68k-linux-gnu
```

`dnfw` finds it there and calls through `wsl`, translating the temporary file
to a `/mnt/<drive>/...` path, so nothing else has to care where it lives.

### Ghidra runs natively on Windows — no WSL needed for it

Only objdump needs WSL. Ghidra's headless analyzer is Java and runs directly:

```
C:\Tools\jdk-21.0.12.1+1              JDK 21 (Temurin), for JAVA_HOME
C:\Tools\ghidra_12.1.3_PUBLIC         set as GHIDRA_HOME
```

`ghidraun-gate-f.bat` is the Windows twin of `run-gate-f.sh` — same scripts,
same `-noanalysis` linear sweep, but through `analyzeHeadless.bat` because the
shell launcher mishandles a Windows JDK path. `ghidranalyze.bat` runs a full
auto-analysis pass and keeps the project, so `DecompileFunction.java` can read a
routine afterwards. Two gotchas met while setting this up, both recorded so they
are not met again: `launch.properties` must be plain UTF-8 with **no BOM**, and
a `%~dp0` script path ends in a backslash that will escape the following quote
in a `.bat` unless it is stripped.

**Gate F still gates everything**, and its reference is objdump, so a section is
not cleared for reading until `dnfw validate-disasm` agrees on it — which needs
WSL. Ghidra passing on MAIN OS (below) does not automatically clear the
bootstrap section: different bytes, and its load base is not yet pinned.

## Gate F — CLOSED 2026-09-08

**The rule: no reverse-engineering starts on a decoder that has not been
checked against objdump.** Run it with `dnfw validate-disasm`. Agreement is
judged on instruction boundaries, not on how each engine spells the result,
because a boundary disagreement means one side has desynchronised and
everything it prints afterwards is fiction.

Reference: `m68k-linux-gnu-objdump` 2.42, `-m m68k:cfv4e`, `-z`.

### Capstone — FAILS, and this is why radare2 cannot be trusted here

Capstone offers m68k modes for the 68000, 010, 020, 030, 040 and 060, and
**no ColdFire mode**. Measured over `0x40001000` + 64 KB of real DN2 code:

| | |
|---|---|
| objdump instructions | 19,117 |
| boundaries Capstone got right | 18,916 (98.95%) |
| divergences | **201** |

The 201 break down into three kinds, and two of them are not what you would
guess:

| Count | What happened |
|---|---|
| 111 | A ColdFire-only `MVS`/`MVZ`. Capstone emits a two-byte `.byte` — but the real instruction can be **six** bytes: `73 f9 40 57 3e 80` is `mvzw 0x40573e80,%d1`. |
| 81 | Capstone has no instruction at that address at all: the downstream wreckage of the above. |
| 9 | The **opposite direction** — Capstone decodes `00 00 2f 0a` as `ori.b #$a,d0`, a 68k instruction ColdFire dropped. objdump correctly rejects it. |

That third row is the one worth remembering. The problem is not only that
Capstone is missing instructions ColdFire added; it also happily accepts
instructions ColdFire removed. Both directions produce plausible-looking code
that is not there.

Across the wider window `0x40000400`–`0x40098000`, Capstone fails on 2,055 of
195,649 instructions and assigns **two bytes to every single one of them** —
which is the desync mechanism stated as a measurement.

This independently reproduces, on the Digitone II, what octabam measured on the
Octatrack on 30 August 2026 (6,757 undecodable instructions, 4,543 of them
longer than two bytes). Their conclusion holds here: r2's m68k backend is
Capstone-based, so **radare2 reads this firmware wrongly and does not say so.**

### Ghidra — PASSES, with one characterised caveat

Ghidra 12.1.3, language `68000:BE:32:Coldfire`, imported with the Binary loader
at `0x40000400` and `-noanalysis`. The export script sweeps **linearly and does
not follow flow**, because that is what `objdump -D` does and a comparison is
only fair if both engines were asked the same question.

Measured over `0x40001000` + **512 KB**:

| | |
|---|---|
| objdump instructions | 165,086 |
| boundaries Ghidra got right | 164,691 (99.76%) |
| divergences | 395, in **99 runs** |
| runs beginning on bytes objdump declined to decode | 93 |
| runs beginning on a real instruction | **6** |

**All six were examined by hand, and none of them is code.** Four sit directly
after a switch dispatch:

```
40073d5e:  48 c0            extl %d0
40073d60:  4e fb 08 02      jmp %pc@(0x40073d64,%d0:l)
40073d64:  00 ba 01 1a ...  <- the jump table starts here
```

`JMP (d8,PC,Xn)` followed by its table. The bytes after it are offsets, and
**both** engines invent instructions from them — objdump reads `oril
#18481372,%d2`, Ghidra reads `ori.l #0x11a00dc,(0x11a,PC)`. Neither is right,
because neither is wrong: a linear sweep cannot know a jump table is data. The
remaining two clusters sit inside runs of `.short` for the same reason.

So **Ghidra misread no real instruction in 512 KB**, and the disagreements are
confined to padding and jump tables — exactly the places a linear sweep is
meaningless. Ghidra's own analyser, which we disabled for fairness, follows
flow and would not disassemble those bytes at all.

`dnfw validate-disasm` still reports FAIL on strict equality, which is correct
and deliberate: the tool counts, a person judges. What it flags is a shortlist
of six things to look at, and looking at them is the work.

**Ghidra is cleared for use on this firmware.** Keep objdump as the reference
for anything that matters, and re-run the gate against a new Ghidra version
before trusting it.

### The two engines side by side

Same span, `0x40001000` + 64 KB:

| | objdump | Ghidra | Capstone |
|---|---|---|---|
| agreement with reference | — | 99.90% | 98.95% |
| divergence runs | — | 9 | 106 |
| runs beginning on real code | — | **0** | **97** |

That last row is Gate F in one line.

## It was built with GCC, and the C++ names are still in it

This is the single most valuable property of the image. Elektron ship it with
RTTI intact, so a 3 MB anonymous blob carries several hundred class names.

`dnfw symbols <image>` lists them; `--ghidra FILE` writes a script that labels
each address.

454 Itanium-ABI type names are recovered from DN2 1.10E. A sample of what is
there, and why it matters:

| Name | Why it is interesting |
|---|---|
| `11LfoPageView` | the `[MOD]` key's page — the LFO4 work starts here |
| `12ModSetupView`, `15ModDestListView`, `22GroupedModDestListView` | modulation destination UI |
| `9ModConfig`, `12SoundModConf`, `14ModulationCopy` | modulation configuration and copying |
| `17SoundParameterSet`, `12ParameterSet`, `17ParameterPageView` | the parameter model |
| `N9Digisharc17soundStorage_v2_tE` | the persisted sound object |
| `15ValueWithMirrorIA4_N9Digisharc11modTarget_tE…` | a **four**-element array of `modTarget_t` |

**The DN2's internal namespace is `Digisharc`; the DN1's is `Digitone`.**
Useful for telling the two apart in shared code, and a reminder that names do
not always match the product.

That `A4_` — an array of four `modTarget_t` — is noted because four is the
number in question. It has **not** been established that it has anything to do
with the LFO slots. Do not build on it until something confirms it.

### The symbol finder has false positives, by construction

`image/symbols.py` accepts a length-prefixed identifier whose prefix matches
the identifier's length. Real strings sometimes satisfy that by accident —
`3VVE` and `4Hfc7` are both in the DN2 results and neither is a class. There is
no way to separate them without cross-referencing the vtables that point at
them, which is a later job. Treat the list as candidates.

## The string pool

UI strings live around file offset `0x1F7000`–`0x202000`, load address
`0x401F7400`+. The LFO parameter names are there in one run:

```
Speed.LFO1.SPD.Multiplier.MULT.Fade In/Out.FADE.Destination.Start Phase.SPH.Trig Mode.LFO2.
```

and `LFO3` appears separately at `0x40201cb0`. **There are exactly three LFO
page labels in the image** — `LFO1`, `LFO2`, `LFO3` — and no fourth.

The SETTINGS menu block is at `0x40200b09`:

```
MANAGE PROJECTS.ProjectMenuView.MIDI CONFIG.SYSEX DUMP.AUDIO ROUTING.PERSONALIZE.DigisharcSettingsMenu
```

`PERSONALIZE` at `0x40200b2e` is the Gate E patch target — unique in the image,
NUL-terminated, cosmetic, and two button presses from the front panel.
