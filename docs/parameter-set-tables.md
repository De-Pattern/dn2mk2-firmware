# The ParameterSet tables: what is at `0x42c6xxxx`, and who fills it

`docs/modulation-mask.md` closed with a hard stop. The hardware experiment in
`scripts/build_moddest_expand.py` proved that for a parameter the track's
`ParameterSet` **enumerates**, the mask at `record+0x24` is the gate — flip it
and the parameter is both offered and modulated. For a parameter it does *not*
enumerate (Chorus, Master), the mask is irrelevant. That made the enumeration
the next thing to understand, and the enumeration ran through a table the code
`lea`s at **`0x42c64b3c`** — an address **outside the loaded MAIN OS image**
(`0x40000400`–`0x4030b980`). Nothing in the firmware file sits there, so the
table could not be read, and the FX-modulation idea and the LFO4 enumeration
question both stalled on it.

**It is BSS, and it is built at boot by walking the parameter table.** The
tables are not data we could have found in the image, because they do not exist
until the firmware constructs them out of the very records we already know how
to edit.

## 1. The region is BSS, and BSS is ~100 MB

The startup sequence at `0x4000053e` makes the layout explicit. Two calls, in
this order — both confirmed by scanning for their call sites, each has exactly
one:

```
0x4000053e  jsr 0x4000045c    ; copy .data image -> 0x80000000 (two blocks)
0x40000542  jsr 0x400004b2    ; clear BSS
```

The second routine is a plain 16-bytes-at-a-time clear whose bounds are
immediates:

```
400004b2:  lea %sp@(-16),%sp
400004b6:  moveml %d4-%d7,%sp@
400004ba:  moveal #0x402fc000,%a0        ; BSS start
400004c0:  movel  #0x466b74d0,%d1        ; BSS end
400004c6:  subl   %a0,%d1
400004c8:  asrl   #4,%d1                 ; length / 16
400004ca:  clrl %d4 / %d5 / %d6 / %d7
400004d2:  moveml %d4-%d7,%a0@           ; zero 16 bytes
400004d6:  lea %a0@(16),%a0
400004da:  subql #1,%d1
400004dc:  bnes 0x400004d2
```

| Build | BSS start | BSS end | Size |
|---|---|---|---|
| DN2 1.10E | `0x402e2000` | `0x464f47d0` | 102,836,176 B |
| DN2 1.11 | `0x402fc000` | `0x466b74d0` | 104,576,208 B |

Three things follow, and the third corrects this repository's own map.

**`0x42c64b3c` is inside `[0x402fc000, 0x466b74d0)`.** So are the other loose
high addresses recorded during the mask work — `0x44644dc4`, `0x446478d0`,
`0x4664acdc`. They are ordinary BSS globals. Nothing exotic is mapped there.

**BSS overlaps the `.data` initializer, deliberately.** BSS starts at exactly
`0x402fc000`, which `docs/memory-map.md` records as ".data/BSS initializer block
1". That is not a contradiction: the copy routine runs **first** and consumes the
initializer into `0x80000000`, and the clear routine then recycles that same
image tail as the first bytes of BSS. The ordering is what makes it safe, and it
is a second, independent reason those trailing bytes are not free cave space.

**Runtime data does not live only at `0x80000000`.** `docs/memory-map.md` states
"runtime data lives at `0x80000000`, not in the image". That is true of the
initialized `.data` — about 64 KB of it — and false of everything else. The bulk
of the firmware's mutable state is the ~100 MB of BSS in the `0x40000000` SDRAM
space, starting immediately after the image. The `0x80000000` window is a
separate, small, fast memory (the DSP section loads at `0x80000400`), not the
main heap.

**The BSS end doubles as a validity test.** An absolute address decoded out of
this image is only plausibly a data reference if it lands in
`[0x402fc000, 0x466b74d0)`. Scanning 1.11 for `lea`/`pea` of absolute longs
above the image end turns up apparent targets at `0x4e541300` and `0x5a2967c1`;
both are outside BSS and are ColdFire opcode bytes masquerading as addresses,
exactly the trap `docs/version-anchors.md` warns about. Use the range as a
filter.

## 2. Six tables, laid out back to back

Every reference into `0x42c64000`–`0x42c65200` in 1.11 — 29 of them — lives in
one code block, `0x400db4f8`–`0x400dc930`. The allocator calls in the builder
pass each table's address and **byte length**, so the layout is measured, not
inferred, and the lengths close the gaps between consecutive addresses exactly:

| Address (1.11) | Bytes | Entries | Holds |
|---|---|---|---|
| `0x42c647a8` | 4 | — | "tables built" flag, set to 1 at the end |
| `0x42c647ac` | `0x194` | 101 | **MIDI** track slot → parameter id |
| `0x42c64940` | `0x68` | 26 | 26-entry set (page group not yet named) |
| `0x42c649a8` | `0x194` | 101 | **FX / global** slot → parameter id |
| `0x42c64b3c` | `0x194` | 101 | **SOUND** slot → parameter id |
| `0x42c64cd0` | `0x48` | 18 | filter-type pages, 6 × 3 |
| `0x42c64d18` | `0x320` | 200 | machine (SYN) pages, 5 × 40 |

All entries are 32-bit parameter ids. The 101-entry width is the same `0..100`
span the destination-list builder walks (`FUN_4003951e`, `i != 0x65`), which is
what first suggested these were the slot maps.

## 3. The builder: `param_set_tables_build`

**1.11 `0x400dc4d0`, 1.10E `0x400de902`. One call site each** (1.11
`0x400bb266`), so it runs once at init.

It zeroes the tables, then walks the parameter table record by record — the same
`record[id] = 0x401f7f94 + id*60` geometry the mask work established — and files
each id into a table chosen by the record's **page id**:

```
400dc54e:  loop, d2 = id = 1..320, a2 = record[id]
             d0 = a2@(0x00)   page id
             d7 = a2@(0x04)   index within page
             d3 = a2@(0x18).w MIDI CC
             d5 = a2@(0x1a).w
             d4 = a2@(0x1c)   NRPN
           ...dispatch on d0...
400dc7ea:  addql #1,%d2 ; lea %a2@(60),%a2 ; cmpil #321,%d2 ; bne loop
400dc800:  movel #1,0x42c647a8            ; built
```

The dispatch, with every compare read as **unsigned** (`bcs`/`bhi` after
`cmp`, which is how the range tests are written):

| Page id | Goes to | At index |
|---|---|---|
| `0..4` | `0x42c64d18` (machine) | `page*40 + idx - 25` |
| `5..10` | `0x42c64cd0` (filter type) | `page*3 + idx - 66` |
| `11..15` | `0x42c64b3c` (**sound**) | `idx`, if `is_sound_param(id)` |
| `16..21` | `0x42c649a8` (**FX/global**) | `idx`, plus CC/NRPN side tables |
| `22..25` | `0x42c647ac` (**MIDI**) | `idx` |
| `26..28` | sound **and** MIDI | `idx`, each behind its own predicate |
| `29, 30, 0xffffffff` | nowhere | not enumerated at all |

**The index is `record+0x04` verbatim.** The slot a parameter occupies in its
set is a field of its own record. That is the whole mechanism.

## 4. The two predicates

Both take a parameter id, read that record's page id, and return 1 = *include*.
They are exclusion lists. What they are *for* is visible in the LFO pages, and
it is not what it first looks like.

**`is_sound_param` — 1.11 `0x400dbd0c`:**

```
d2 = record[id].page
exclude if  (page - 17) <= 8u  and  (1 << (page-17)) & 0x1f3   ; pages 17,18,21,22,23,24,25
exclude if  id in {84, 94, 104}
exclude if  id in {28, 29, 30, 31}
otherwise include
```

**`is_midi_param` — 1.11 `0x400dbd7c`:**

```
d2 = record[id].page
exclude if  (page - 11) <= 10u and  (1 << (page-11)) & 0x4c7   ; pages 11,12,13,17,18,21
exclude if  id in {20, 26, 76, 86, 96}
otherwise include
```

Both open with the same three instructions — bound the id at 320, compute
`id*60`, `lea 0x401f7f94,%a0` — which is the family fingerprint
`docs/version-anchors.md` already records for the `record+0x00` readers.

### What the exclusions are actually doing

Each LFO page holds **ten** records but occupies only **eight** slots, and the
reason is two different mechanisms, only one of which is the predicate. Taking
LFO1 (page 26, ids 75–84):

| id | short | idx | in sound? | in MIDI? |
|---:|---|---:|---|---|
| 75 | `SPD` | 1 | yes | yes |
| 76 | `MULT` | 2 | yes | **no** |
| 77 | `FADE` | 3 | yes | yes |
| 78 | `DEST` | 4 | yes | yes |
| 79 | `WAVE` | 5 | yes | yes |
| 80 | `SLEW` | **6** | yes | yes |
| 81 | `SPH` | **6** | yes | yes |
| 82 | `MODE` | 7 | yes | yes |
| 83 | `DEP` | 8 | yes | yes |
| 84 | `MULT` | **2** | **no** | yes |

**`SLEW` is not excluded by anything — it loses a collision.** Ids 80 and 81
declare the same index 6, both pass both predicates, and the builder walks ids in
ascending order writing `table[idx] = id`. The higher id wins, so `SPH`
overwrites `SLEW` and the slot resolves to Start Phase. Last-write-wins is the
mechanism, and it is worth knowing before editing any `record+0x04`: **a
duplicate index silently evicts the lower id.**

**The duplicate `MULT` is a per-track-type variant, and that is what the id
exclusions exist for.** Ids 76 and 84 are both LFO1 Multiplier at index 2. The
predicates take them apart: `is_sound_param` rejects 84, `is_midi_param` rejects
76. So a synth track and a MIDI track get *different records for the same
control*. They differ in substance:

| id | used by | max (`+0x0c`) | steps | value formatter (`+0x34`) |
|---:|---|---:|---:|---|
| 76 | sound tracks | `5888` (`23<<8`) | 24 | `0x400e35b0` |
| 84 | MIDI tracks | `2816` (`11<<8`) | 12 | `0x400e3584` |

Same CC and NRPN, different range and different formatter. The same pairing
repeats exactly on LFO2 (86/94) and LFO3 (96/104), which is why those six ids are
the entire id-exclusion list between the two predicates.

**A device-checkable prediction falls out of this**, and it costs one minute:
`LFO MULT` on a **synth** track should offer roughly twice as many settings as
`LFO MULT` on a **MIDI** track. If it does not, the reading above is wrong
somewhere.

## 5. The reader: `param_set_slot_to_id`

**1.11 `0x400dc02a`.** Takes a slot index and a machine/filter type, and reads
back out of whichever table owns that slot:

```
slot < 25 or slot > 64  ->  0x42c64b3c[slot]                  ; sound
slot in 25..64          ->  0x42c64d18[type*40 + slot - 25]   ; machine-dependent
slot in 66..68          ->  0x42c64cd0[type*3  + slot - 66]   ; filter-type-dependent
```

This is the function behind `ParameterSet` vtable slot `+0x50`. It explains a
detail that had no explanation before: **the sound slot map is machine-dependent
in exactly one window.** Slots 25–64 are the machine parameters, and they are
resolved through the 200-entry table keyed by machine type; slots 66–68 are
resolved through the 18-entry table keyed by filter type. Everything else —
LFOs, Amp, Portamento, FX sends — is machine-independent and comes straight out
of the sound table.

## 6. The page map, measured

`scripts/dump_param_sets.py` re-runs the construction offline — the dispatch and
both predicates reimplemented against a local image — so this is reproducible
rather than a one-time disassembly:

```
python scripts/dump_param_sets.py                    # occupancy of every set
python scripts/dump_param_sets.py --table sound      # slot by slot, with names
python scripts/dump_param_sets.py --version 1.10E
```

**Both builds produce byte-identical occupancy**, which is the cross-check that
the geometry and the predicates are right: only the addresses moved between
1.10E and 1.11, the parameter data did not. The reconstructed sound table also
reproduces, independently, the LFO index space `docs/engine-state.md` derived
from the value getter — LFO1 at slots 1–8, LFO2 at 9–16, LFO3 at 17–24, Filter
from 69. Two different routes to the same map.

The page map it prints:

| Page | Label | Records | idx range | Enumerated into |
|---:|---|---:|---|---|
| 0–3 | SYN | 38/25/30/8 | 25–64 | machine `0x42c64d18` |
| 5–10 | Filter | 3/2/3/3/3/3 | 66–68 | filter `0x42c64cd0` |
| 11 | Amp | 11 | 80–92 | sound |
| 13 | Filter | 11 | 69–79 | sound |
| 14 | Portamento | 2 | 93–94 | sound |
| 15 | FX (sends) | 8 | 86–99 | sound |
| 16 | Chorus | 8 | 25–31 | **FX/global** |
| 17 | Reverb | 9 | 41–48 | **FX/global** |
| 18 | Delay | 10 | 32–40 | **FX/global** |
| 19–20 | Master | 2 + 9 | 60–69 | **FX/global** |
| 21 | Ext-in | 17 | 49–59 | **FX/global** |
| 22–25 | MIDI (Src, CC, …) | 4/8/16/16 | 8–64 | **MIDI** |
| 26–28 | LFO1 / LFO2 / LFO3 | 10 each | 1–24 | sound **and** MIDI |
| 29 | Retrig | 22 | 0–25 | **nothing** |
| 30 | the `None` / `---` entry | 1 | 0 | **nothing** |
| `0xffffffff` | the 18 dead records | 18 | — | **nothing** |

Occupancy of the three 101-entry tables:

| Table | Slots used | Free |
|---|---|---|
| sound `0x42c64b3c` | 55 | `0`, `25`–`68`, `100` |
| MIDI `0x42c647ac` | 64 | `0`, `65`–`100` |
| FX `0x42c649a8` | 45 | `0`–`24`, `70`–`100` |

The sound table's 25–68 hole is **not** free space. Those slots are served by
the machine and filter tables, as §5 shows; the sound table simply has nothing
to say about them. The genuinely unclaimed sound slots are **65 and 100** — two,
which is the same answer `docs/engine-state.md` reached by counting the value
array, now with a mechanism behind it.

## 7. What this settles

**Enumeration is a data edit, not a code patch.** This is the finding. Which set
a parameter belongs to, and which slot it occupies in that set, are computed at
boot from `record+0x00` and `record+0x04` — two fields of a 60-byte record in a
table we have already edited on hardware twice. Nothing about the enumeration is
baked into an unreachable table; the unreachable table is the *output*.

**But `record+0x04` is a sharper edge than `record+0x24` was.** The mask edits
that have been flashed were self-contained: a wrong mask offers a parameter that
does not move, and nothing else changes. An index edit is not self-contained,
because the builder is last-write-wins. Writing an index another record already
claims **silently evicts** whichever id is lower — the `SLEW`/`SPH` pair in §4 is
that mechanism working as designed, and it would work just as quietly on a
parameter someone needs. Any script that writes `+0x04` should re-run
`scripts/dump_param_sets.py` over its own output and diff the tables against
stock, the way the build scripts already diff the image. A green integrity check
still says only that the file is well-formed.

**The FX-modulation idea has a mechanism, and a price.** Delay (page 18) and
Reverb (page 17) carry a full `0x1e00` mask and are unreachable because they are
filed into the FX/global table `0x42c649a8`, while the LFO destination list walks
the **sound** table. Moving Delay Time into the sound set means giving its record
a page id in `11..15` and a free sound slot. Both fields are writable. But the
price is real and should be stated before anyone builds it:

- it would move the parameter off the Delay page in the UI, because the page id
  *is* the page;
- only slots 65 and 100 are free, so at most two FX parameters could be moved;
- and the open question from `docs/modulation-mask.md` is still open — the apply
  path writes `sound + 0x14 + idx*2`, a **per-voice** location, while Delay is a
  single global instance. An enumerated global parameter would very likely be
  offered as a destination and then not move. That is worth one experiment, and
  it is cheap: two records, four fields, the same build-and-flash loop.

**LFO4's enumeration is no longer the blocker; the slots are.** A fourth LFO
needs 8 contiguous slots in the sound table and 8 more in the sound object's
value array. There are two free slots. The page-id range test `(page - 26) <= 2`
is a second wall, and `docs/lfo4-feasibility.md` §3b already records why a range
test cannot be widened to reach a non-adjacent page — but the range test is not
the thing to attack first, because winning it still leaves six slots short.

**What is *not* settled.** The 26-entry table at `0x42c64940` is allocated and
read (`0x400dc0f2`, bound `25 >= slot`) but no dispatch arm above writes it;
something outside `param_set_tables_build` fills it. The CC/NRPN side tables
(`0x42c65674`, `0x42c660b0`, `0x42c666ec`, `0x42c65eb0`, `0x42c65874`,
`0x42c65038`) are the MIDI-in reverse maps — id-by-CC and id-by-NRPN — read
straight off `record+0x18` and `record+0x1c` in the same loop, and are not needed
for modulation work.

## Anchors

| What | 1.10E | 1.11 |
|---|---|---|
| BSS clear routine | `0x400004b2` | `0x400004b2` |
| BSS span | `0x402e2000`–`0x464f47d0` | `0x402fc000`–`0x466b74d0` |
| `param_set_tables_build` | `0x400de902` | `0x400dc4d0` |
| its one call site | — | `0x400bb266` |
| `param_set_slot_to_id` | — | `0x400dc02a` |
| `is_sound_param` | — | `0x400dbd0c` |
| `is_midi_param` | — | `0x400dbd7c` |
| sound table | `0x42aa6914` | `0x42c64b3c` |

The builder moved by `0x242a` between builds and the sound table by `0x1be228` —
**not** the `+0x768` shift that held for the mask-filter neighbourhood. Re-anchor
by pattern, never by offset: the builder is found by searching for the byte
sequence `4878 0194 4879` (`pea #0x194; pea <abs>`), which is unique in both
images.
