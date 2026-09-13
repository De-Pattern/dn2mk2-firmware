# The trace harness: asking the running firmware what it reaches

## Why it exists

Four LFO4 builds were flashed in the week of 2026-09-09 and every one was
silent. They were investigated as four separate problems — a wrong destination,
a neutral value given in the wrong units, a cave that does not execute, a bad
anchor — and they had **one cause**: each aimed at a function that was not on
the path being observed.

* `0x4004ca80` was identified as `Sound::updateMirror` from a prologue, an
  epilogue and a string inside its bounds. It is a **lambda in a vtable slot**,
  its address appears once in the whole image as data, and **nothing calls it
  directly**.
* `parameter_value_getter` was anchored on a real instruction, but forcing its
  return value changed nothing on screen. It does **not draw parameters**.

Both facts were measurable before a single byte was flashed. The first is a
caller count; the second is only knowable from the device. Between them they
define what this harness is for.

**The rule that comes out of it, now in `docs/version-anchors.md`:** an address
confirmed by an instruction pattern is not a confirmed *role*, and only the role
justifies a hook.

## What made it possible

`docs/flashing.md`, 2026-09-13: a cave hooked into the boot path wrote
`CAVE RAN!!!` over the SETTINGS menu string in RAM and the device displayed it,
while the image itself still contained `PERSONALIZE`. That is the project's
first working code injection, and it turns `patch/cave.py` from a patcher into
an **instrument**: any function, when it runs, can leave a mark a human can see.

It also settled the board's address. The boot proof wrote to `0x402193f4` and
the screen changed, so the display renders that string **live from that
address** — every probe writing there will be seen.

## The design

`PERSONALIZE` is eleven characters. Ship it as `...........` and give each
candidate function a **column** and a **mark**:

```
SETTINGS shows   .G.S...C...
                  |  |   |
                  |  |   `- column 7's function ran
                  |  `----- column 3's function ran
                  `-------- column 1's function ran
```

Eleven reachability answers per flash, against one answer per flash for the
builds that produced them by guessing.

Three properties are worth stating because each removes an ambiguity that has
already cost this project a result:

**The idle row ships in the image.** It is a plain same-length data edit, the
same class as Gate E, so the board appears whether or not any code runs. A blank
row is therefore a *result* — nothing ran — and not the "we cannot tell"
outcome that made the earlier silent builds so expensive.

**The marks accumulate.** They are written into RAM as the instrument is used,
so the row is a record of what an action touched: read it, do one thing (load a
sound, turn an encoder, save), read it again.

**One column is the harness's own control.** `param_index_in_page` has 34 direct
callers and cannot be missed by a working trace. If `P` is blank, the result to
report is "the harness is broken", not anything about the other ten.

## The probe, and why it may be spliced anywhere

A hook at an arbitrary site must leave the machine exactly as it found it, and
*exactly* includes the condition codes. A probe that clobbered CCR between a
`cmp` and its `beq` would silently change what the firmware decides — which is
worse than not running, because it would look like a result.

```
    lea     %sp@(-8),%sp        ; claim the stack BEFORE writing to it, so an
    movem.l %d0/%a0,%sp@        ; interrupt cannot land on the saved registers
    move.w  %ccr,%d0            ; MOVEM and LEA do not affect CCR; nor does this
    lea     BOARD,%a0
    move.b  #MARK,%a0@(COLUMN)  ; the only instruction here that writes CCR
    move.w  %d0,%ccr            ; put it back
    movem.l %sp@,%d0/%a0
    lea     %sp@(8),%sp         ; the displaced stock replays with %sp restored
```

32 bytes, round-tripped through objdump byte-for-byte.

Two details that are easy to get wrong on this CPU:

* **ColdFire MOVEM has no predecrement or postincrement mode.** The stack moves
  by `lea`, not `movem.l %d0/%a0,%sp@-`. The stock prologues in this image use
  the same form, which is how it was noticed.
* **`%sp` is restored before the displaced instructions replay.** ColdFire GCC
  prologues commonly read the first argument as `movea.l %sp@(4),%a0`; if the
  probe still held 8 bytes of stack at replay time, that would read our saved
  registers instead of the argument.

## Where a probe goes

At a **function entry**, not at the instruction of interest. An entry is
straight-line, is already a call target, and answers "was this function
reached", which is the question. Entries come from the direct-call scan in
`image/functions.py`, not from reading a disassembly by eye.

## The guards

| Guard | Where | What it stops |
|---|---|---|
| stock bytes asserted at the site | `patch/cave.py` | applying to the wrong build |
| displaced bytes scanned for PC-relative branches | `patch/cave.py` | replaying a branch at a new address |
| cave must be currently all-zero | `patch/cave.py` | overwriting live data |
| **nothing may branch into the displaced bytes** | `patch/trace.py` | a loop back-edge landing on an operand word |
| no two probes share a column | `patch/trace.py` | two answers overwriting each other |
| every changed byte belongs to a hook, cave or board | the build script | anything unaccounted for |

The branch-target guard is the one `patch/cave.py` could not make on its own: it
needs a whole-image scan, which is `image.functions.branch_targets_within`.

## Using it

```
dnfw fn <image> callers --at 0x4004ca80   # before hooking anything, ever
dnfw fn <image> entry   --at 0x4004cb08   # which function is this address in
dnfw cave <image> scan                    # free runs, candidate caves
dnfw cave <image> probe --at 0x400dbcc4   # the whole-instruction stock to displace
python scripts/build_trace_harness.py     # the eleven-probe build
```

`dnfw fn callers` is the command that would have saved four flashes. It costs
nothing and belongs in front of every hook. A count of zero does not prove an
address is dead — a vtable call names no target — but it proves that **a cave
there cannot be assumed to run**, which is the half that matters, because it
means a silent result would tell you nothing.

## What the harness cannot answer

**Whether the DSP has a fourth LFO generator.** That question is engine-side,
was answered "yes" twice, and both answers are withdrawn (`docs/engine-index-map.md`
§15): both probes changed the forward *and* inverse maps together, so a
consistent storage round-trip predicts the same positive result with only three
generators running. The trace measures the ColdFire, not the SHARC, and that
question needs a test designed so a positive **cannot** be explained by storage
round-tripping.

## Result

_Not yet flashed. `trace-harness_DN2_1.11.syx`, content sha256 `cfc03f1a249b7a92`,
556 bytes changed across 11 hooks, 11 caves and the board._

| col | mark | site | probe | asks |
|---|---|---|---|---|
| 0 | `P` | `0x400dbcc4` | `param_index_in_page` | 34 callers — the harness's own control |
| 1 | `G` | `0x4006408a` | `parameter_value_getter` | mis-anchored; does it run **at all**? |
| 2 | `M` | `0x4004ca80` | `updateMirror` lambda | vtable-only; a mark would overturn the retraction |
| 3 | `S` | `0x4004c5c6` | mirror enclosing fn | the directly-called function the mirror sites sit in |
| 4 | `R` | `0x400dd1ea` | reverse copy | engine → control, through the inverse map |
| 5 | `F` | `0x40043f5e` | fill loop | the 0..100 loop, generic by construction |
| 6 | `B` | `0x4004c178` | bulk copy A | bulk value-array copy via `0x400dbc88` |
| 7 | `C` | `0x4004c23a` | bulk copy B | the second bulk copy |
| 8 | `A` | `0x40036274` | pip consumer A | indexes the value array |
| 9 | `D` | `0x40036bac` | pip consumer B | two generic sites inside it |
| 10 | `E` | `0x40037942` | pip consumer C | two generic sites inside it |
