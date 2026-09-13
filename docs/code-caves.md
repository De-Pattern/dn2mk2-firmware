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

---

## RESOLVED: the cave region is fine, and caves execute

> **2026-09-13, confirmed on hardware.** `cave-boot-proof_DN2_1.11.syx` planted a
> cave at `0x4028ea02` — in the constants region — hooked it into the boot path,
> and had it overwrite the SETTINGS menu string in RAM. The device shows
> **`CAVE RAN!!!`** while the image still contains `PERSONALIZE`, so only the
> cave can have written it.
>
> **Caves execute. The constants region is executed by the running image.** The
> mechanism, `patch/cave.py`, the assembler, the `jmp`+return hook form and
> `dnfw cave scan`'s default region are all sound, and the section below — which
> concluded the opposite — is **withdrawn**. It was reasoned from an experiment
> that hooked a function later shown not to be on the path it was being observed
> through, so it could not have worked either way.
>
> octabam's warning is real for the Octatrack and does not apply here. Kept
> below because the comparison of the two projects' cave mechanics is still
> worth having.

## Withdrawn: the cave region this project chose is probably wrong

**2026-09-13.** `cave-proof_DN2_1.11.syx` hooked `parameter_value_getter`'s
single exit and added a constant to the returned value. Flashed, it changed
**nothing**: seven parameters across three pages all read their stock defaults,
checked against the firmware's own record fields.

The image was correct. After a full encode/decode round trip the hook decodes as
`jmp 0x4028ea02` and the cave holds `addi.l #4096,%d0`, the replayed `moveml` and
the jump back. **The bytes are right and the code has no effect.**

### octabam hit this and named it

`00_Resources/01_Reference/octabam/docs/firmware/DSP.md` §R48–R49, on a cave of
theirs that misbehaved:

> the cause is elsewhere in the hook (context, stack, or **the cave region not
> being what the running image executes**) and the next step is a cave that does
> nothing but replay the displaced instructions.

They had already met this failure mode and written it down. **We should have read
their mechanism before building ours** — the reuse rule in the plan exists for
exactly this, and four flashes were spent not following it.

### Where they put caves, and where we put ours

| | octabam (Octatrack) | this project (DN2) |
|---|---|---|
| cave address | `0x400d6b00`–`0x400d7c3c`, ~4.4 KB | `0x4028ea02` |
| region | **inside the code region** | **the read-only constants region** |
| hook form | `jsr cave` + `nop`s, cave `rts`es back | `jmp cave`, cave jumps back |
| assembler | `m68k-elf-as -mcpu=5407` | `m68k-linux-gnu-as -mcpu=cfv4e` |

Their caves live where code lives. Ours lives in data. An MCF5441x has an MMU,
so a non-executable mapping over the constants region would produce exactly what
we see.

**And `dnfw cave scan` bakes the mistake in**: it defaults to
`0x4026e000..0x402e2000`, a range taken from `docs/memory-map.md`'s
"unreferenced padding runs". That range was chosen because the bytes are *free*.
Nothing ever checked that it is *executed*.

### The DN2 has no equivalent space, and that is a real structural difference

Scanning the whole of MAIN OS for zero runs ≥ 24 bytes: **585 runs, and the
lowest-addressed sits at `0x401d06c8`** — the code/rodata boundary itself. There
is **not one free run of 24 bytes anywhere inside the DN2's code region.**

So the octabam recipe cannot simply be copied. The options, in order of appeal:

1. **Establish whether the constants region is executable at all.** If it is, the
   fault is elsewhere and cave placement is fine.
2. **Repurpose dead code inside the code region** — `docs/ideas-backlog.md` §1's
   "sacrifice a feature for room", which now has a second and better reason to
   exist: not space, but *executability*.
3. **Adopt octabam's `jsr`/`rts` hook form**, which is their proven shape and
   costs nothing to match.

### First, though: a test that needs no cave

`scripts/build_inline_proof.py` replaces the value getter's own return-value load
in place, same length:

```
4006414c:  mvsw %a0@(14,%d2:l:2),%d0    7170 2a14
        -> moveq #127,%d0 ; nop         707f 4e71
```

Four bytes for four, the same class of edit as Gate E and the mask flips — both
confirmed working on this device. `127 >> 8 = 0`, so every parameter drawn
through this function should read **0**; `AMP VOL` falls from 110 to 0.

- **values collapse** → the hook site is reached, and **the cave is what fails**;
  the work is placement, per the options above.
- **values unchanged** → the hook site is never reached, and the anchor for
  `parameter_value_getter` in `docs/version-anchors.md` is wrong about what that
  function does.

One of those says the cave mechanism is sound; the other says an anchor is wrong.
Neither is guessable from here.

---

## The `0x40287ef6` array, read out of the code (2026-09-13)

The crash on 2026-09-13 was diagnosed from the *shape* of the free runs —
sixteen of them at a `0x40c` stride, therefore an array. That was an inference.
It is now read directly out of MAIN OS, and the inference was right.

**25 constants in `0x40287e00..0x4028c000` are referenced from MAIN OS**, and
one of the sites is an initialiser:

```
4002a4d2:  movel %a2,%sp@-
4002a4d4:  lea   0x40287f04,%a0        ; the array base
4002a4da:  subal %a1,%a1               ; i = 0
4002a4dc:  clrl  %a0@(0,%a1:l)         ; clear [i]
4002a4e0:  lea   %a0@(0,%a1:l),%a2
4002a4e4:  addql #4,%a1
4002a4e6:  clrl  %a2@(512)             ; clear [i + 512]
4002a4ea:  cmpal #512,%a1
4002a4f0:  bnes  0x4002a4dc            ; 128 iterations, two longs each = 1024 B
4002a4f2:  st    %d0
4002a4f4:  clrl  %a0@(1024)
4002a4f8:  clrl  %a0@(1028)            ; 1032 bytes cleared
4002a4fc:  lea   %a0@(1036),%a0        ; <-- ADVANCE ONE RECORD: 1036 = 0x40c
```

and a nearby site in the enclosing region carries `moveq #16,%d0` beside a `lea`
into the same range.

**So the region is a 16-record array of 1,036-byte structures, base
`0x40287f04`, and MAIN OS clears it.** The stride the guard derived from spacing
alone (`patch/cave.py:suspect_arrays`) is the literal displacement in the
instruction. Sixteen is this machine's track and voice count
(`docs/device-model.md`).

`0x40287f04` is **14 bytes into** the "free run" at `0x40287ef6` that
`dnfw cave scan` offered, so every cave placed from that base sat inside record
zero or later. **The diagnosis is confirmed.**

### Why the emulator could not have told us this

The 400M-instruction run watched `0x40287ef8`, `0x40288000` and `0x40288b28`,
with a static control (`0x401f7f94` → `0xffffffff`) and two dynamic ones
(`0x42c64b3c` → `0x13`, the boot-built `ParameterSet` table; a live TCB) all
green, and the prio-6 main application task started at `n=315,716,921`.

All three array watches read **`0x00000000`**.

That is not evidence of anything, and the reason is worth keeping: **the writes
are `clrl` — they write zeros.** A watch that reads a *value* cannot distinguish
"cleared to zero" from "never touched". The instrument was incapable of
detecting the very thing it was pointed at.

This is the third time this week a test has been built whose two branches
produce identical output — after the trace harness's stamps and the
`updateMirror` hook. The rule it earns:

> **A watch must be able to produce a different answer for each outcome.**
> Watching a value proves nothing about a region that is written with zeros;
> only a *write hook* does. `Machine.install_mmio_trace` in digikit delivers
> write events with `pc`, address and value, and works over any range — that is
> the mechanism a real write map needs, not `--watch`.
