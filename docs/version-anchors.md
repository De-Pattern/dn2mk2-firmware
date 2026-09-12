# Anchors across versions: 1.10E ↔ 1.11

Every address in a MAIN OS image moves when Elektron relinks. This is the table
that maps what we have found from one build to the other, plus **how** each was
re-found — because the method matters more than the number: the next release
will move them again, and a recorded method re-runs in minutes where a recorded
address is simply wrong.

1.11 (build 40059) is the target — the device runs it. 1.10E (build 40050) is
kept for comparison.

## The framework is structurally unchanged

Measured on both images, identical counts:

| Signature | 1.10E | 1.11 |
|---|---|---|
| `lea <record base>,%a0` accessor sites | 44 | 44 |
| any 4-byte reference to the record base | 53 | 53 |
| `cmpi.l #321,dN` (the bound) | 38 | 38 |
| `cmpi.l #320,dN` | 20 | 20 |
| ×60 stride idiom (`lsl #2` / `lsl #6` / `sub`) | 37 | 37 |
| object offsets `0x40004`/`0x40008`/`0x40010`/`0x40014`/`0x4001c` | 17/12/17/21/7 | 17/12/17/21/7 |

So the parameter framework and the per-track object layout are the **same shape**
in both; only addresses and one offset moved. The bound-raising job described in
`docs/parameter-table-consumer.md` is therefore the same size on 1.11 (~43 sites).

## The anchors

| What | 1.10E | 1.11 | How it was re-found |
|---|---|---|---|
| **Parameter record base** (record[id] = base + id·60) | `0x401e29a0` | **`0x401f7f94`** | the address the 44 accessors `lea` |
| **Short-name pointer** within a record | base + `0x30` | base + `0x30` | indexing `base+0x30+id·60` returns the LFO names |
| — so name-indexing origin | `0x401e29d0` | **`0x401f7fc4`** | verified: ids 75–84 and 95–104 both give `SPD MULT FADE DEST WAVE SLEW SPH MODE DEP MULT` |
| **LFO short-name strings** | — | `0x4021058e` | searched `SPD\0`, `MULT\0`, `FADE\0` |
| **Modulation mask** within a record | base + `0x24` | base + `0x24` | `docs/modulation-mask.md`; same offset in both |
| **`get_param_mod_mask(id)`** | `0x400de776` | **`0x400dc30e`** | searched the tail bytes `2030 0824 4e75` — a unique 6-byte signature, one hit per image |
| **Destination-list filter sites** (×4) | `0x4003908a` `0x4003936c` `0x4003958e` `0x4003978c` | **`0x400397f2` `0x40039ad4` `0x40039cf6` `0x40039ef4`** | searched `203c 0000 1e00 08` (`movel #0x1e00,%dN; btst`); a uniform `+0x768` shift between builds |
| **Destination-list builder** | — | `0x4003951e` | the `jsr` the filter sites feed |
| **`is_lfo_param_modulatable`** | `0x400de34e` | **`0x400dbee6`** | searched the tail `0683 ffff ffe6 7002 b083 54c0` — `addil #-26,%dN; moveq #2; cmpl; scc`, i.e. page `0x1a..0x1c`. Byte-identical logic in both builds |
| **`parameter_value_getter`** | `0x40064786` | **`0x4006408a`** | the function containing the `+0x4f358` reference at `0x400640dc`; reads an LFO value as `sub + 0x14 + idx*2` |
| **`param_index_in_page(id)`** | — | **`0x400dbcc4`** | returns `record[id] + 0x04`; same shape as the mask getter, different displacement |
| its page-class siblings | — | `0x400dbdea` `0x400dbe5e` `0x400dbe8a` `0x400dbeb6` | a family reading `record[id]+0x00`: `page <= 4`, `page - 5 <= 5`, `page <= 0x1c`, and a bitmask reject over `page - 11` |
| **Engine modulation-state offset** | `+0x4f2e0` | **`+0x4f358`** | histogram of `adda.l #imm,%aN` / `move.l #imm,%dN` immediates in `0x30000..0x70000`; every *other* offset matched exactly, isolating this one (shift of +0x78) |
| **Engine fn — thunk target** | `0x4004d6d4` | **`0x4004dfb0`** | the `jmp` after `move.l #<offset>,%d0; addl %d0,%sp@(4)` |
| **Engine fn — called with the object** | `0x4004d386` | **`0x4004dc62`** | the `jsr` after `adda.l #<offset>,%a2; move.l %a2,%sp@-` |
| thunk site | `0x4003dcb6` | `0x4003e426` | — |
| `adda` site (setup) | `0x4003dbb4` | `0x4003e324` | — |
| `adda` site (large fn) | `0x40040368` | `0x40040b28` | — |
| **`param_set_tables_build`** | `0x400de902` | **`0x400dc4d0`** | byte pattern `4878 0194 4879` (`pea #0x194; pea <abs>`) — unique in both images. Moved by `0x242a`, **not** the `+0x768` of the mask neighbourhood |
| its one call site | — | `0x400bb266` | scan for `jsr`/`bsr` to the builder; exactly one in each build |
| **`param_set_slot_to_id`** | — | **`0x400dc02a`** | the `ParameterSet` vtable `+0x50` body; three-way dispatch on slot |
| **`is_sound_param(id)`** | — | **`0x400dbd0c`** | same head as the other `record+0x00` readers: bound at 320, `id*60`, `lea <table>` |
| **`is_midi_param(id)`** | — | **`0x400dbd7c`** | as above; exclusion masks `0x4c7` over `page-11` |
| **Sound slot table (BSS)** | `0x42aa6914` | **`0x42c64b3c`** | 101 × 4 B; moved by `0x1be228` |
| **BSS clear routine** | `0x400004b2` | `0x400004b2` | same address in both; bounds are immediates |
| **BSS span** | `0x402e2000`–`0x464f47d0` | `0x402fc000`–`0x466b74d0` | ~100 MB. Doubles as the validity filter for decoded absolutes |
| **Section end** | `0x402f1980` | `0x4030b980` | load base + decoded size |
| **.data initializer** | `0x402e2000` (one block) | `0x402fc000` + `0x40304000` (two) | read from the startup copy loops |
| **BSS cleared to** | `0x80008000` | `0x80010000` | same |
| **Safe cave region** | `~0x4026e000`–`0x402e2000` | `~0x40287000`–`0x402fc000` | `dnfw cave scan` |
| **Bootstrap ELE3 dest** | `0x02000000` | `0x02010000` | `dnfw inspect` |

## Still 1.10E-only — re-anchor before use

These were located on 1.10E and have **not** been re-found on 1.11. Do not
extrapolate them; the offsets between the two builds are not constant (code grew
~104 KB, but not uniformly).

- `parameter_page_renderer` `0x40016f38`
- LFO-speed handler `0x40035f32` — the second 3-LFO site
- `LfoPageView` vtable `0x401ecf7c` — the `+0xbc` cell→id method
- `parameter_value_resolver` `0x400635d0`
- bootstrap: `recovery_receive_loop` `0x80003e5a`,
  `verify_and_flash_container` `0x80003c9c`

## The methods, so this is repeatable

1. **A table**: find a string it points at (`SPD\0`), find the 4-byte pointer to
   that string, subtract `id·60`. Confirm by indexing a known block — the LFO
   names at 75–84 and 95–104 are an unambiguous fingerprint.
2. **An object offset**: histogram the immediates of `adda.l #imm,%aN` and
   `move.l #imm,%dN` over a plausible range. Offsets that are unchanged between
   builds confirm the method; the one that moved is the answer.
3. **A function**: anchor on the instruction *sequence* around a known constant,
   not the address — the sequences here were byte-identical across builds.
4. **Never** a blind address histogram over the raw image: ColdFire opcode bytes
   masquerade as addresses (`docs/memory-map.md`, method note).
