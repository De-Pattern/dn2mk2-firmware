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

> **Superseded 2026-09-26 (Waverider Milestone 5, `docs/waverider-m5-dsp.md`).**
> ~~the SHARC per-track clamp `min(R2, 4)` ... says five~~. Run through the
> frame unpack, that clamp's input is the frame field at `84 + 2t` (the ColdFire's
> per-track byte `sound+0xE0`, copied to `0x80003af0 + 153t + 3470`), not the
> machine type. The DSP's own five-way bound on the machine type is the lookup
> `0x25d748[nibble]` (entries `[5..7]` are 0) and the setup guard `compu(type, 5)`
> at `0x1c905d`. The row above was right that three structures agree on five, and
> wrong about which three. Kept as it was read.

## What a sixth machine would cost

Mechanically, and in order of increasing difficulty:

1. `0x400dc332`: `moveq #4` -> `moveq #5`. One byte.
2. `0x400dc358`: the same. One byte.
3. Row 5 at `0x401f7830`: two pointers to new name strings. **See the warning.**
4. The SHARC clamp `min(R2, 4)` -> `min(R2, 5)`, and the table it indexes at
   `lshift 9` (512-word records) needs a sixth record.
   *(Superseded, Milestone 5: not the machine clamp; the DSP needs the lookup
   `0x25d748[5] = 5` instead, and the clamp stays stock.)*
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

## What a sixth machine actually cost on the ColdFire (Waverider, Milestone 5)

**2026-09-26, built and run in the ColdFire emulator** (`dnfw.waverider.coldfire`,
`scripts/emu_waverider_menu.py`, digikit-up `9007c2a`). The five steps above were
the plumbing the name table implied. Running a type-5 track through the UI
found the rest, one blank screen at a time. What MACHINE SEL, the SYN pages and
the frame needed, in the order the emulator showed it:

| # | where | stock | what a type-5 track did before the edit |
|---|---|---|---|
| 1 | the MACHINE SEL list `0x401ddd58`, copied into a function-local `std::vector` by `0x4004d8b6` (storage `pea 0x14`, capacity `lea %a0@(20)`) | `{0, 2, 1, 3, 4}` | not offered |
| 2 | the row group `0x40059274` (a divider where it changes) | 0..3 -> 1, 4 -> 2, else 0 | a divider above *and* below it |
| 3 | the name accessors `0x400dc332` / `0x400dc358` / `0x400dc37e` | `moveq #4`, rows at `0x401f77f4` | fallback string |
| 4 | the attribute rows `0x401f7930` (`{byte, 0, u16 track mask}`), read by the permission test `0x400dc19a(type, track)` the setter asks before it writes `sound+0xDE` | 5 rows, `moveq #4` | **YES did nothing**: the track kept its machine |
| 5 | the stored-sound LOAD `0x400dd1ea`: `stored[244] + 1 < 6` (`moveq #6` at `0x400dd286`) | keeps -1..4 | a saved Waverider sound loads as **FM Tone** |
| 6 | `param_set_slot_to_id` `0x400dc02a` (slots 25..64: `0x42c64d18[type * 40 + slot - 25]`) | type <= 4, else id 0 | no machine parameters: the reset on machine change had nothing to copy |
| 7 | the per-machine SYN page tables `0x42432ad4` (count, pages) and `0x42432b24`, through `0x400c24d2`, `0x400c24ee`, `0x400c248e` | type <= 4, else one empty fallback page | **an empty SYN page**: eight dotted boxes |
| 8 | `getMachineType(track)` `0x4004b7f2`, ~60 callers across the UI | returns `sound+0xDE` | the page drawn but the WAV knobs blank and no knob editable |
| 9 | the sound's "is this parameter mine?" (vtable `+0x50`, `0x40036bfa`): `sound+0xDE == record[param].page` | raw type | the sound disowns WaveTone's records (page 1): the p-lock, LFO-destination and CC paths ask this |

**The design that came out of it:** type 5 is WaveTone to the UI (rows 6-9 read
5 as 1), and itself where identity matters. Five callers of `0x4004b7f2` are
sent to a raw copy of it instead: MACHINE SEL's marker (`0x4005a4ac`), the
machine name (`0x40071912`), the re-commit of a track's own type (`0x4002db2c`),
and two track-state messages (`0x400d5a72`, `0x400d675e`). The sound's own byte
stays 5, so the stock SAVE writes it and the frame builder sends it: `0x4002549c`
copies `sound+0xDE..` into the builder's per-track mirror (`0x80003af0 + 153t +
3468`) when a track's note triggers with a changed sound, or for every track when a
kit loads (`0x40025af4`), and `0x4002757c` writes it at frame offset `148 + 2t`.

**The warning holds and was respected:** the six-row name table, the six
attribute rows and the six-entry list live in clean caves (`0x4028e958`,
`0x4029037c`, `0x4028db24`), not after the old tables.

**One emulator trap worth knowing.** MACHINE SEL's view builds its rows once,
about 67 M instructions after `boot400M` (constructor `0x4005b6de` -> row builder
`0x4005b2c0`). `ui1200M` has them from the stock list, so a build installed over
it shows five rows whatever it changed. The Waverider snapshots are `boot400M`
with the build patched in (`guirun --patch-ranges`) and run to the SYN page.

**Not audited:** 78 `moveq #4` compare sites in MAIN OS were listed; the
per-machine ones above were found and fixed, the rest read as unrelated (MIDI,
arp, message types) at a glance, and **callers of the vtable getter
`0x40036462` (raw) were not traced**. A type-5 path through one of those shows
up as a fallback (most bounded accessors return an empty or default value
above 4), not as WaveTone.

## Status (Milestone 5)

**[E]** for the rows above: each was found by a type-5 track misbehaving in
the emulator and each fix re-run there. The status paragraph above is the
page's first reading, kept.

## The double YES (fix/waverider-select, 2026-09-27)

**What the instrument did** (M5 build, the owner): with the cursor on FM TONE,
WAVERIDER and YES jumped the marker to WAVETONE; a second YES on WAVERIDER moved
it there; reopening MACHINE SEL marked WAVETONE. The same with the stock section 7
(M5's section 3 alone), and not on the ONESHOT build, which makes type 5 too but
leaves `getMachineType` alone. So the bug was the ColdFire's, in what Waverider
maps to WaveTone and ONESHOT does not.

**What the emulator did, the same keys** (`scripts/emu_waverider_menu.py
--watch-types`, snapshot `wr-final-ui800M`, `out/fix-select/`): exactly that.
After the first YES the sound's byte is **5** and the marker is on WAVETONE
(`run1/b_yes.png`); the second YES writes 5 again, from the same setter
(`0x4004cc94`, via `0x40031880` from MACHINE SEL's `0x4005bba6`), and the marker
moves; reopening marks WAVETONE (`run1/d_reopen.png`) with the byte still 5.
Every write to any track's `sound+0xDE` was logged, through the menu, the kit
sync `0x40025af4`, the track sync `0x4002549c` and the audio ISR `0x40025e36`
entered directly: **nothing else writes it**. The stored type persisted; the
menu misread it.

**Why.** MACHINE SEL keeps the machine it marks and puts the cursor on in its
view at `+412`, set at open (`0x4005b6c2`), after every commit and on every
model change (`0x4005a5c6`, `0x4005a632`, `0x4005a9c8`), and its YES commits
only when the cursor's type differs from `+412` (`0x4005bb86`). `+412` comes from
`0x4003134e(model, track)` -- the model-level "which machine does track t have?"
-- which finds the track and ends in a **tail `jmp 0x4004b7f2`**. Milestone 5
canonicalised `0x4004b7f2` (5 reads as 1) and sent its identity callers to a raw
copy by rewriting their `jsr`/`lea`; a `jmp` was not in that search. So `+412`
was 1 after the commit, the menu redrew with WAVETONE marked, the second YES
found 1 != 5 and committed again, and a reopened menu marked 1.

| caller of `0x4003134e` | uses the type for | with 5 |
|---|---|---|
| `0x4005a5c6`, `0x4005a632`, `0x4005a9c8`, `0x4005b6c2` | MACHINE SEL's marker and cursor (`+412`) | **the bug** |
| `0x40041bca` | the track swap `0x40041acc`: re-commits each track's type | commits WaveTone, then its sound copy puts 5 back (emulator, M5) |
| `0x400a7f92`, `0x400b15e8` | keep the old type, re-commit it on cancel | would restore WaveTone (static read; not run) |
| `0x4003e6f2`, `0x40064ea2` | the SYN overview / page accessors `0x400c248e` / `0x400c24ee` | already read 5 as WaveTone's rows |
| `0x40071862`, `0x4008c558`, `0x400b049a` | "is it MIDI?" (`cmp #4`, `-1`) | no |

**The fix** is one long: the tail jump at `0x40031394` goes to `raw_track`
instead (`dnfw.waverider.coldfire`, 7b), so all twelve callers see 5. After it,
the same keys mark WAVERIDER on the first YES and on reopening, and a YES on the
marked row closes the menu, as stock does (`out/fix-select/m5b_oldrows/`, and
`m5b_sel/` on a snapshot with the final build installed from `boot400M`);
`0x4003134e` answers 5 (M5: 1; stock with SWARMER: 3, the control); the swap
commits 5 directly.

**Still canonical, noted:** the virtual getter `0x4004dd98` (the other tail
`jmp 0x4004b7f2`, at `+0x74` of the vtable at `0x401de518`); there are 13
`vtable+116` call sites, not all of that class, and one of them (`0x400d60cc`)
packs a per-track byte into a message; and the machine step `0x4004da90` (an encoder step from the
current machine), which steps from WaveTone's position. Neither is MACHINE SEL's
path and neither writes the sound's byte on its own.

## A section of its own for the sample machines

The owner's request with the same fix: synths | WAVERIDER | MIDI, divided the
way MIDI is. The row builder `0x4005b2c0` (and the second list at `0x40059cdc`)
inserts a row of value `-1` wherever the group changes -- drawn as a dotted line,
**no label**: the stock divider carries no text. The groups are only compared for
equality, so a third is just another section. The group function becomes: synths
0..3 -> 1, MIDI 4 -> 2, **5 and 6 -> 3** (6 reserved for ONESHOT; no row for it in
this build), else 0, in the stock function's 34 bytes.

**The first version of it put every synth in group 0**, and the emulator said
so: called directly (`call:0x40059274:3`) it answered 0, and the menu drew no
divider between SWARMER and WAVERIDER. A `moveq` sat between a `subq` and the
`bcs` that tested its borrow, and `moveq` clears C. The unit test passed,
because its little interpreter of the function's opcodes did not model that.
Both are fixed: the branches now follow the instruction that set their
flags, and the test's `moveq` and `tst` set N and Z and clear C. So a test that
runs a model of the machine is only as good as the model, and the emulator is the
test that counts. The list stays
`{0, 2, 1, 3, 5, 4}`, and its vector's storage and capacity follow `LIST_NEW`'s
length, so a seventh machine is one entry (and its name and attribute rows).
