# The Digitone II's object model

Reverse engineering this firmware without knowing what the device actually
manages produces confident nonsense — several corrections in `docs/engine-state.md`
came from exactly that. This is the object model, taken from DNX's measured
`+Drive` listings and cross-checked against strings in the firmware itself, so
that a count or an index in the code can be matched to a real thing.

## The store, as the device presents it

Measured by DNX from live `+Drive` directory listings (`DNX/docs/device-storage.md`):

| Path | Shape | Total |
|---|---|---|
| `/projects` | 128 entries | 128 projects |
| `/soundbanks` | **8 banks `A`..`H`, 256 presets each** | 2048 presets |
| `/kits` | **8 banks `A`..`H`, 128 kits each** | 1024 kits |

Sounds and kits open by index under their bank, exactly as projects do.

## Where a preset can live — three distinct places

This is the distinction that matters, and conflating them is what goes wrong:

1. **The project's preset pool.** Every project carries **128** preset slots.
   DNX measures the pool in a project image at **128 × 359 bytes**
   (`tail + 10756`). Conceptually these are the presets the project uses; they
   are stored in the project itself, not merely named.
2. **The `+Drive` preset library.** **8 banks × 256 = 2048** presets, device-wide
   and independent of any project.
3. **Kits.** A device-wide library (**8 banks × 128 = 1024**). **Each kit holds
   16 presets — one per track** — and assigning a kit to a project replaces the
   project's 16 track presets in one action. A kit is 10,752 bytes
   (`DN2_KIT.kitSize`); note DNX's warning that a kit reads at two sizes
   depending on whether `STORED_FORM` was requested.

"Preset" is Elektron's Digitone II name for what earlier boxes called a
**Sound**; DNX's docs say "Sound" (after the SysEx dump type) and the firmware
says "Preset". Same object, two vocabularies.

## Patterns

**16 banks `A`..`P` × 8 patterns = 128 per project.** DNX measures the pattern
array at 128 × 89,088 bytes. A pattern pairs with the kit of the same index.

## The firmware agrees, and its format strings encode the geometry

From the SysEx receive handler `FUN_4002d8b2` (1.11). The **width of each field
is the tell**, and it matches the store shape above exactly:

| String | Reading |
|---|---|
| `Received PATTERN %c%02d` | bank letter + **2** digits — 16 banks × **8** patterns |
| `Received SEQ %c%02d` | same addressing |
| `Received PRESET %c:%03d` | bank letter + **3** digits — 8 banks × **256** presets, the `+Drive` library |
| `Received PRESET %d` | a plain index — the project pool slot (0..127) |
| `Received KIT %d` | a plain kit index |
| `Received MIDI PRESET`, `Received SETTINGS` | further distinct classes |

Two digits for patterns and three for presets is not a style choice: it is the
bank capacity, 8 versus 256. That the firmware's field widths independently
reproduce DNX's measured store is the strongest cross-check we have that both
descriptions are right.

## What this settles about the engine array

`docs/engine-state.md` finds an array of **128 entries × 960 bytes** whose index
is clamped to `0..0x7f` and displayed as `Preset: %d` (1-based). Against the
model above:

- it is **not** the `+Drive` preset library — that is 2048, and is addressed
  bank-and-index (`%c:%03d`), not by a bare 0..127 index;
- it is **not** a kit — a kit holds **16** presets, one per track;
- it is **not** the pattern array — 128 is right but a pattern is 89,088 bytes;
- it matches **the project's preset pool**: 128 slots, indexed 0..127,
  project-wide, 359 bytes serialized expanding to 960 in RAM with runtime state.

So the array is the **loaded project's preset pool**, and the base object it
hangs off is the engine/project root — not a per-track object.

## Counts worth keeping straight

| Number | What it is |
|---|---|
| **16** | tracks; also the presets in one kit (one per track); also pattern banks `A`..`P` |
| **8** | patterns per bank; also soundbank and kit bank count (`A`..`H`) |
| **128** | patterns per project; presets in a project's pool; projects; kits per bank |
| **256** | presets per soundbank bank |
| **1024** | kits on the `+Drive` (8 × 128) |
| **2048** | presets on the `+Drive` (8 × 256) |

`128` is therefore **not** a unique fingerprint — it identifies at least four
different things. Any identification resting on the count alone is unsafe; find
the string, the field width, or the entry size as well.
