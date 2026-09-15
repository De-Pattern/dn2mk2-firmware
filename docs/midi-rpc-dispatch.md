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

## Where this stands

**Found:** the advertised list, its single call site, the patch shape for
extending it, and the dispatcher's class structure.

**Not found:** what actually routes an opcode to a handler, and therefore what
rejected `0x05`. Next step is to disassemble
`handleMessageAndCreateResponse` — a large function, since a caller `0xe2e`
bytes past `0x40125cbe` is still attributed to it — and find the comparison
chain or registry lookup inside it.

Until that is found, **nothing here says the FsSample handlers exist**. The
classes ship; whether any code constructs them is exactly the open question.
