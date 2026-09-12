# Adding code without moving anything: the code cave

A `patches/` record (`docs`… `patch/spec.py`) can only replace bytes in place,
because changing a section's length would move every address after it and
nothing here fixes up the code that refers to them. A fourth LFO needs *new*
code — a raised parameter-table bound, a modulation tick that runs a fourth
source. The way to add code without relocating the image is a **detour into a
code cave**, and `patch/cave.py` implements it.

This is octabam's and midisc's mechanism (both MIT, same ColdFire core — see
`docs/references.md`), reduced to its parts.

## The mechanism

```
  before                          after
  ------                          -----
  hook:  <stock instrs>           hook:  jmp cave        (+ nop pad)
         ...                             ...
                                  cave:  <payload>
                                         <displaced stock instrs>
                                         jmp hook+len(stock)
```

1. Pick a **hook site** in stock code. Overwrite it with `jmp cave` (6 bytes),
   padding to the next instruction boundary with `nop` (`0x4e71`).
2. The **cave** — free space elsewhere — holds the new **payload**, then the
   stock instructions the jmp displaced, replayed verbatim, then a `jmp` back to
   just past the hook. Control flows out, does the new work, does the original
   work, and returns as if nothing happened.

Two guards make it safe to apply, both in `plan()`:

- **The stock bytes at the hook are asserted.** If they do not match, the image
  is the wrong build or the address is wrong, and nothing is written — the same
  discipline `patch/spec.py` uses, carried to a cave.
- **The cave must be genuinely free.** The applier refuses a cave that is not
  currently all-zero. *Free* is not the same as *safe*: see below.

## What space is safe — and the trap

From `docs/memory-map.md`, on the DN2:

- **Safe:** the unreferenced padding runs inside the constants region. On
  1.10E these cluster around `0x4026e000`; on **1.11** they sit around
  `0x40287000`–`0x4028c000` (addresses move every relink — find them per image,
  never hardcode across versions). `dnfw cave scan` lists them.
- **The trap:** the ~64 KB of zeros from ~`0x402e2000` reads as free but is the
  **.data/BSS initializer**, copied to `0x80000000` SDRAM at boot. Overwriting
  it changes the program's initial RAM state. `cave scan` defaults its range to
  the safe region *below* this so it will not offer it; widen `--start/--end`
  only if you know what you are doing.
- Live code (below the constants) is obviously not free.

The largest safe runs measured on 1.11 are ~1 KB each (55 runs, ~26 KB total) —
plenty for a hook stub and a modest payload, not for a large table.

## "Why not just append at the end and point at it?"

The obvious alternative, and it deserves a real answer rather than the
hand-wave this document used to give. **Appending does not shift anything.** The
"every address after it moves" objection applies to *inserting* in the middle;
bytes added after the section end leave every existing address exactly where it
was, and the CPU does not care whether a `lea` names `0x40287000` or
`0x40400000`. Relocation is not the obstacle.

**The obstacle is that the space past the image end is already spoken for.**
Measured on 1.11 (`docs/memory-map.md`, `docs/engine-index-map.md`):

```
MAIN OS ends      0x4030b980
BSS spans         0x402fc000 .. 0x466b74d0     (104,576,208 bytes)
```

The section end is **inside** the BSS range, with ~104.5 MB of BSS above it. The
clear loop at `0x400004b2` runs before `main` and zeroes all of it. So an
appended table is written correctly by the loader, passes every integrity check,
boots — and is erased milliseconds later, because the linker had already
reserved that address for a BSS variable.

The right way to hold this: a cave is not "blank space", it is space that is
blank **and unclaimed**. Past the section end the bytes are blank and claimed,
which is worse than useless — it fails silently and at runtime, where this
project's integrity checks cannot see it.

Three ways to get genuinely unclaimed space, kept here because the cave is only
the cheapest answer for *small* payloads:

1. **Raise the BSS start above the append.** The bounds are plain immediates
   (`moveal #0x402fc000,%a0`), so it is a same-length edit. The cost is that
   real BSS variables between the old and new start would no longer be zeroed,
   and C++ statics assume they are. Testable, and the failure would be loud, but
   it is a genuine fault and not a theoretical one.
2. **A separate ELE3 section with its own `dest` above `0x466b74d0`.** The
   container is a table of `{id, offset, comp_len, dest}` and 1.11 already ships
   six sections. This avoids both the shifting question and the BSS clear
   entirely. Registered as `docs/ideas-backlog.md` §6 with the two things that
   must be checked first.
3. **Chain cave runs** — ~26 KB total exists, just not contiguously.

For a payload that fits in ~1 KB, the cave still wins on cost alone: no loader
assumptions, no BSS surgery, no new container machinery.

## Displaced instructions must be position-independent

The displaced stock is replayed at a *different address* in the cave, so a
**PC-relative** instruction there (a `Bcc`/`BSR`, `0x6x`) silently retargets.
`plan()` scans the displaced bytes for those opcodes and refuses unless
`allow_pcrel=True`. It is a coarse net, not a disassembler — an operand byte can
collide with `0x6x` — so the real rule stands: **pick hook sites whose displaced
instructions are straight-line** (moves, arithmetic). `dnfw cave probe` reports
the verdict for a candidate site.

## Building a payload

Two ways to produce the payload bytes, by size:

- **`patch/coldfire.py`** — a ColdFire encoder ported from midisc (MIT), every
  encoding checked against a stock instruction and against `m68k-linux-gnu-as`
  (`test/test_coldfire.py`). Good for a one-line hook branch or a handful of
  instructions, and needs no toolchain.
- **`patch/assemble.py`** — shells to the real `m68k-linux-gnu-as` (present in
  WSL, the same binutils as our Gate-F objdump) and returns the assembled bytes.
  Use it for anything non-trivial; it is the lesson taken from ems-octakit
  (architecture only, read license note in `docs/references.md`). Pass `base`
  to link the stub at its cave address when it must resolve its own labels
  absolutely; otherwise external targets are named absolutely and internal
  branches are self-relative, so the bytes are position-correct as-is.

The assembler also picks the tightest encoding — a `move.l #4,%d0` in a payload
comes back as `moveq #4,%d0` (2 bytes, not 6) — which is free space saved in the
cave.

## The CLI

Authoring a cave is scriptable, not a one-liner, because a detour carries code.
The two tedious lookups are commands; applying is Python against `patch/cave.py`.

```
dnfw cave scan <image> [--min N] [--start A] [--end B]
    Free zero-runs in the safe region — candidate caves. Defaults to
    0x4026e000..0x402e2000; confirm any pick against docs/memory-map.md.

dnfw cave probe <image> --at <addr> [--min N]
    Disassemble the hook site and print the exact whole-instruction `stock`
    bytes a detour must displace, with a PC-relative verdict.
```

A worked hook, once authored, is applied like:

```python
from dnfw.image.coldfire import LoadedImage
from dnfw.patch.cave import Cave, CaveHook, apply
from dnfw.patch.assemble import assemble

payload = assemble(""" ... """, base=0x40287ef6)   # 1.11 cave from `cave scan`
hook = CaveHook(id="lfo4-bound", site=0x400dXXXX,
                stock=bytes.fromhex("...")           # from `cave probe`
                payload=payload, cave=Cave(0x40287ef6, 1047))
new_section = apply(LoadedImage(dest=section.dest, content=section.unpack()), hook)
# → recompress, rebuild, re-sign (firmware/build.py), then flash.
```

## Verification

`test/test_coldfire.py` checks the encoder against the real assembler on every
fixed encoding. `test/test_cave.py` checks the applier's guards and that a plan
splices payload → displaced → return-jump. Beyond the unit tests, the whole
detour was assembled, applied, and disassembled back through the reference
objdump: the hook read as `jmp cave`, and the cave as payload, the replayed
stock instruction, and `jmp` back — valid ColdFire end to end.
