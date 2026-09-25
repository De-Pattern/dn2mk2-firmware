# What limits the DN2 machine list, and what a sixth machine would cost

**Read 2026-09-25, statically, from DN2 1.11.** digikit's open question after
PR #43 is *"which ColdFire code limits the machine list, and what must change
for another type to reach the DSP as a new selector?"* -- asked of DT2 1.16.
This is the answer for **our** device.

## The table

`0x401f77f4`, rows of **12 bytes**: `{long_name, short_name, 0}`.

| index | long | short |
|---|---|---|
| 0 | `FM Tone` | `FMT` |
| 1 | `WaveTone` | `WVT` |
| 2 | `FM Drum` | `FMD` |
| 3 | `Swarmer` | `SWM` |
| 4 | `MIDI` | `MIDI` |

Rows above it in the same array are filter names (`Comb-`, `Legacy LP/HP`,
`Comb+`), so `0x401f77f4` is where the *machines* start, not where the array
does.

## The bound, in two accessors

```
0x400dc332  moveq #4,%d1              | the ceiling
0x400dc334  movel %sp@(4),%d0         | the machine index
0x400dc338  cmpl %d0,%d1
0x400dc33a  bcss 0x400dc350           | index > 4 (unsigned) -> fallback string
0x400dc33e  lsll #2,%d1               | idx*4
0x400dc340  lsll #4,%d0               | idx*16
0x400dc342  lea 0x401f77f4,%a0
0x400dc348  subl %d1,%d0              | idx*16 - idx*4 = idx*12
0x400dc34a  movel %a0@(0,%d0:l),%d0   | -> table[idx].long
```

`0x400dc358` is the same function for the **short** name, same `moveq #4`, same
`x12`, base `0x401f77f8` (the row's second field).

**So the ColdFire ceiling is `moveq #4` at `0x400dc332` and `0x400dc358`.**

## Three structures agree on five, which is why this is worth acting on

| evidence | says |
|---|---|
| the table's filled rows | 5 (`0..4`) |
| the ColdFire accessors' bound | `index <= 4` |
| the SHARC per-track clamp (`docs/sharc-voice-path.md`) | `min(R2, 4)` |

The SHARC clamp was **[D]** on its own -- one structural read of a
`max`/`min`/`lshift 9` idiom, no control. It now has two independent
corroborations from a different processor and a different kind of artefact
(a data table and a bounds check). That does not make it **[V]**, but it
promotes it well past a guess.

## What a sixth machine would cost

Mechanically, and in order of increasing difficulty:

1. `0x400dc332`: `moveq #4` -> `moveq #5`. One byte.
2. `0x400dc358`: the same. One byte.
3. Row 5 at `0x401f7830`: two pointers to new name strings. **See the warning.**
4. The SHARC clamp `min(R2, 4)` -> `min(R2, 5)`, and the table it indexes at
   `lshift 9` (512-word records) needs a sixth record.
5. **Actual DSP code that renders the new machine.** Everything above is
   plumbing; this is the work, and digikit cost a first custom sound at one to
   two weeks *with* a SHARC emulator they do not have yet.

## The warning: the space after the table is NOT free

`0x401f7830` onward looks like sixteen empty 12-byte rows -- 192 zeroed bytes,
and it would be natural to call it room for eleven more machines.

**It is not.** `0x400dc1fe` reads the same address as a **16-entry array of
longs**, `x4` stride, bound `moveq #15`:

```
0x400dc1fe  moveq #15,%d1
0x400dc204  cmpl %d0,%d1
0x400dc206  bcss 0x400dc214
0x400dc208  lea 0x401f7830,%a0
0x400dc20e  movel %a0@(0,%d0:l:4),%d0
```

So `0x401f7830`..`0x401f786f` is a live 16-long table that merely happens to be
zero in stock, and a machine row written at `0x401f7830` would land inside it.
**A sixth machine's row needs space found elsewhere**, or this table needs
moving first.

This is exactly the trap the mirror geometry set yesterday: a region that reads
as empty is not the same as a region nothing indexes.

## Status

**[D] for the whole page** -- single static read, no emulator run and no
hardware. What would raise it: call `0x400dc332` in the emulator with index 5
and confirm the fallback string, and watch `0x401f7830` during a boot to see
whether the 16-long table is ever written.
