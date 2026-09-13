# The display path, found by watching the screen instead of naming a function

**Measured 2026-09-13 on Digitone II 1.11**, against digikit `ec32de1`, resumed
from the 400M boot rung with the UI drawing (409 frames composed).

This project named the display path twice by reading code and was wrong twice —
`Sound::updateMirror` was a vtable-only lambda nothing calls, and forcing
`parameter_value_getter`'s return changed nothing on screen. The rule that came
out of it is that **an instruction pattern confirms an address, never a role**.

So nothing here is named by eye. `scripts/paint_map.py` watches the bytes that
*are* the screen and records the `pc` of every instruction that writes one; a pc
that wrote a pixel is on the display path by definition.

## 1. The write hook fires — and that settles a second question

1,637,709 framebuffer writes from 29 distinct pcs across 209M instructions.

That matters beyond this page. `scripts/write_map.py` used the same
`install_mmio_trace` mechanism over candidate cave RAM and printed `events: 0`
twice, and both runs were too short to reach the code that writes — so *"the
hook does not fire"* and *"nothing wrote"* were never separated, and the write
map has never produced a number anyone could read. **The mechanism works.** Its
zeros were run length, not blindness.

### The buffers are behind pointers, and the first run of this got it wrong

`profile.fb_front` and `fb_back` are the addresses of the **pointers**, not of
the buffers — they sit four bytes apart, and `emu.panel.read()` dereferences
before reading 1024 bytes. Watching them directly watches the pointer variables
and the RAM after them.

The first run did exactly that and produced a confident, plausible table: 1,521
writes, 6 pcs, neat 32-bit widths. Nothing in the output looked wrong. It was a
map of a data structure that paints nothing.

> **A watch aimed at the wrong address does not report an error. It reports a
> table.** The tell was arithmetic and available before the run: two
> "framebuffer addresses" four bytes apart cannot both be 1024-byte buffers.

## 2. The drawing primitives

Every pc that wrote a screen byte, grouped by the function containing it
(`dnfw fn entry --at`):

| entry | direct callers | writes | shape |
|---|---|---|---|
| `0x40113b90` | 18 | 1,302,866 | read-modify-write — reads == writes |
| `0x40114d94` | 34 | 104,448 | **writes only, no reads** — a fill or clear |
| `0x40114842` | 90 | 75,656 | read-modify-write |
| `0x401157fc` | 108 | 45,598 | read-modify-write |
| `0x40115118` | 5 | 49,434 | read-modify-write |
| `0x40113cf4` | 21 | 28,511 | |
| `0x40113edc` | 18 | 1,124 | |
| `0x40131d8e` | 2 | 1,024 | writes only — in the `panel_diff` neighbourhood |

The two with 90 and 108 direct callers are the general-purpose primitives the
whole UI draws through. `0x40114d94` writing without ever reading is the
signature of a fill: it does not need the old pixels.

**These are leaves, not the page renderer.** They say where the ink goes.

## 3. Walking back: only 2 of 34 callers actually fire

`scripts/caller_map.py` hooks a function entry and reads the return address off
the stack, which on ColdFire is `(sp)` at the first instruction of a callee.

`param_index_in_page` (`0x400dbcc4`) — **2,798 entries, 2 distinct callers**:

| returns to | count | enclosing function |
|---|---|---|
| `0x40037166` | 2,797 | `0x40036bac` |
| `0x400371cc` | 1 | `0x40036bac` |

So the static list of 34 is right and almost all of it is cold. One function
does essentially all the parameter-table indexing this instrument does while
drawing.

### The control: two unrelated instruments agree to the byte

The runtime return addresses are `0x40037166` and `0x400371cc`. The static
caller scan reports call sites at `0x40037160` and `0x400371c6` — **exactly six
bytes earlier in both cases**, which is the length of `jsr <32-bit absolute>`.

A linear disassembly scan in this repository and a stack read inside someone
else's emulator, sharing no code, land on the same two instructions. Neither was
adjusted to fit the other.

### And the chain above it

| watched | live caller | count |
|---|---|---|
| `param_index_in_page` `0x400dbcc4` | `0x40036bac` | 2,798 |
| `0x40036bac` | `0x4003951e` — **the destination-list builder** | 2,097 |
| `parameter_value_getter` `0x4006408a` | `0x4006538e` | 2,796 |
| | `0x40063af0` | 233 |

`0x4003951e` is already named in `docs/version-anchors.md` as the
destination-list builder — found independently, months of reasoning earlier, by
following the four filter sites. It turning up here as the live caller is
corroboration from a direction that was not looking for it.

**`parameter_value_getter` runs constantly** (3,031 calls) even though forcing
its return changes nothing on screen. Both facts are now measured, and together
they say it computes a parameter value for something that is not the pixels —
which is a live lead rather than the dead end it looked like.

## 4. A candidate for the page renderer, explicitly not confirmed

`0x400167a4` (7 direct callers) calls the text primitive `0x401157fc` 466 times,
and it sits where 1.10E's `FUN_40016f38` — identified in
`docs/parameter-table-consumer.md` as the `[MOD]`/parameter page renderer — would
land after the relink. Its body repeats one block (`0x40046bfe`, `0x40030e66`,
two vtable calls, then `0x4003e426`, the engine thunk site named in
`docs/version-anchors.md`) several times over, which is the shape of a loop over
parameter cells.

**This is a candidate and nothing more.** No reference to the 1.11 record base
`0x401f7f94` was found in its first 1,600 bytes, and "it is near where the old
one was" is precisely the reasoning that produced two wrong identifications
already. It gets confirmed by a role test or not at all.

## What this does not establish

**No input is modelled** (`docs/emulator.md`), so every count here is from an
undriven boot sitting on whatever page it starts on. Nothing reached only by
pressing `[MOD]` or turning an encoder appears, and that includes the whole
mirror path — which is why `updateMirror` and its enclosing function stay silent
in every run so far. Those zeros still mean "not entered during an undriven
boot".

## Reproducing

```
python scripts/paint_map.py  --digikit ~/digikit --snapshot ~/snaps/boot400M.snap
python scripts/caller_map.py --digikit ~/digikit --snapshot ~/snaps/boot400M.snap \
    --at 0x400dbcc4 --at 0x4006408a
dnfw fn <image> entry   --at <pc>        # what function is this
dnfw fn <image> callers --at <entry>     # and the static list to check against
```

Ask `emu.run.usable_rung()` which snapshot to resume; do not copy a rung number
out of a docstring (`docs/emulator.md`).
