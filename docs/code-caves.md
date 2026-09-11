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
plenty for a hook stub and a modest payload, not for a large table. A bigger
cave means either chaining runs or growing the section, and a section-grow needs
the heap boundary above `0x80000000`'s data/BSS pinned so new bytes do not
collide with it.

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
