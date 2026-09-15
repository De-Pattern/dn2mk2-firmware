# The MIDI RPC capability list, and the hunt for what dispatches

**2026-09-15.** First step of the chimera's ColdFire half
(`docs/chimera-feasibility.md` §5, item 4): the DN2 already carries all 40-odd
`MidiRpcFsSample*` message classes, at occurrence counts identical to the
Digitakt II, yet advertises none of their opcodes and answered an unadvertised
one with silence. This is about finding what decides that.

## The advertised list is a static array, referenced exactly once

The device's `ping` reply carries its own opcode list:

```
01 02 03 04 06 07 09 50 52 51 53 54 55 56 57 58 59 5a 5b 5c 5d 5e
```

That exact byte string — including the **`50 52 51` transposition**, which a
hand-ordered table would not have — occurs **once** in MAIN OS, at
**`0x40207f30`**. It sits in `.rodata` between RTTI blocks for
`MidiRpcDispatcher`, padded `00 00` to a 4-byte boundary, with a pointer
immediately after. No slack to extend it in place.

**One reference, and it is an iterator pair:**

```
0x40125da4  48 79 40 20 7f 46   pea 0x40207f46      ; END = list + 0x16
0x40125daa  43 e9 00 16         lea %a1@(22),%a1    ; 0x16 = 22, the count
0x40125dae  48 79 40 20 7f 30   pea 0x40207f30      ; BEGIN
0x40125dbc  4e 94               jsr %a4@            ; construct from [begin,end)
0x40125dc0  48 79 40 21 a2 d2   pea 0x4021a2d2      ; "Digitone II"
```

`0x4021a2d2` is the string **`Digitone II`** — so `0x40125cbe`, the function
containing this, is the **ping/query response builder**, and it pairs the
opcode vector with the device name exactly as the reply we captured does.

### Extending what is advertised is a small patch

Three values at one call site, plus a longer array in a code cave:

| at | now | change to |
|---|---|---|
| `0x40125da6` | `0x40207f46` (end) | end of the new array |
| `0x40125dac` | `0x16` (count) | new count |
| `0x40125db0` | `0x40207f30` (begin) | the new array |

That is squarely what `patch/spec.py` and `patch/cave.py` already do, and the
stock bytes are distinctive enough to guard on.

**But advertising is not dispatch**, and this is the part to be careful about:
opcode `0x05` drew silence, so *something* rejects unknown opcodes, and it has
not been shown to be this table. Changing the advertisement alone may well
change nothing but the reply.

## The dispatcher is not polymorphic

`MidiRpcDispatcher`'s RTTI name is at `0x4023145d`, its typeinfo at
**`0x40208014`**, and its vtable at **`0x40208170`**:

```
vt+0  0x40208014   typeinfo
vt+1  0x4012549a   code
vt+2  0x401254fa   code
vt+3  0x00000000   (end of primary)
vt+4  0x4020801c   typeinfo of a second base
```

**Only two virtual functions** — the destructor pair. So
`handleMessageAndCreateResponse` is an ordinary member function, and the
routing lives inside it rather than behind a vtable.

## Two approaches that did not discriminate

Recorded because a method that cannot tell the two cases apart is worth knowing
about before it is trusted:

- **Scanning for an `{opcode, handler}` table.** The heuristic — a small byte
  every 8th position followed by a code pointer — returned runs where the
  "opcode" was always `0x3c`, a byte of the pointer pattern itself. False
  positives, no signal.
- **Counting RTTI references** for advertised classes against unadvertised
  ones. `MidiRpcData*` (opcodes `0x53`–`0x5e`, advertised) and
  `MidiRpcFsSample*` / `MidiRpcFsRaw*` (not advertised) come out **identical**:
  one name reference, one typeinfo, zero typeinfo references, every one. The
  vtable-to-typeinfo link is not where it was looked for, so the test measures
  nothing — it does **not** show the classes are equally live.

## The Digitakt II answers the question the dispatcher hunt could not

Five static approaches failed to find what routes an opcode — the switch-table
scan, the RTTI reference count, the MIDI status-byte tables, the opcode-as-
immediate scan over the query builder, and following the dispatcher's vtable.
The sixth worked, and it is the obvious one: **the DT2 already does sample
transfer**, so diffing the two builds asks the question directly.

Finding it needed no new technique — the DN2's list was located through the
`"Digitone II"` string its builder pushes, and the DT2's through `"Digitakt II"`
at `0x40240edb`. The code is the same shape:

```
48 79 40 21 e5 90   pea 0x4021e590      ; END
43 e9 00 2c         lea %a1@(44),%a1    ; 0x2c = 44 opcodes
48 79 40 21 e5 64   pea 0x4021e564      ; BEGIN
4e 94               jsr %a4@
48 79 40 24 0e db   pea 0x40240edb      ; "Digitakt II"
```

**Same call site, same instruction sequence, same static-array shape. Only the
contents and the count differ.**

| | opcodes | list |
|---|---|---|
| DN2 | **22** | `01 02 03 04 06 07 09 50 52 51 53 54 55 56 57 58 59 5a 5b 5c 5d 5e` |
| DT2 | **44** | `01 02 03 05 04 06 07 09 50 52 51 10 13 11 12 20 21 22 23 28 30 31 32 36 40 41 42 46 …` |

Three things fall straight out:

- **`10 13 11 12` is the `FsSample` family**, present on the DT2 and absent on
  the DN2 — in the same transposed-pair style as `50 52 51`.
- **`05` is in the DT2's list.** That is the opcode probed on hardware that drew
  silence, so `storage_info` is real and its absence from the DN2 is deliberate
  rather than an artefact of the probe.
- The DT2 carries whole families the DN2 lacks: `20 21 22 23`, `28`,
  `30 31 32 36`, `40 41 42 46`.

### What that changes

It does not prove the array gates dispatch. But **if dispatch were independent
of it, the DT2 would not need a different one** — so the array is at least
tracking what each build answers, and possibly deciding it.

That replaces "find the DN2's rejection path" with a decisive experiment:

> Extend the DN2's list with `10 13 11 12`, count `22 → 26`, and ask the device.

- It answers `FsSampleReadDir` → dispatch was gated on this array, and the
  chimera's RPC half is essentially done.
- It advertises them and still goes silent → the handlers are genuinely not
  registered, and that is a clean negative worth having.

Either outcome settles it, which is more than another week of static analysis
was going to do.

## Where this stands

**Found:** both builds' advertised lists, their single call sites, the patch
shape, and the dispatcher's class structure.

**Not found:** the routing itself. Recorded as unresolved rather than guessed
at, because **nothing here yet says the FsSample handlers exist** — the classes
ship on the DN2; whether any code constructs them is exactly what the
experiment above would settle.

**Requires hardware.** The experiment needs a modified image flashed, so it
waits on the owner. Nothing up to building the image touches the device.
