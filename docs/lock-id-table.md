# Lock ids on 1.11: the translation table the firmware uses

Asked by DNX on 2026-09-17, checking SYXGRID's 1.10E claims against 1.11.

**The table.** `0x401fd0b0`, 107 big-endian u32 entries, **lock id -> mirror slot**
(the 101-slot per-track mirror, `docs/lfo4-build-plan.md` §5k). Referenced at
`0x400dccec` and at `0x400dd25e` inside the positional sound deserializer. A
sibling table at `0x401fcc2c` agrees for ids 0..72 and then differs (zeros, then
a second sequence); it is referenced once, at `0x400dce9e`, not yet read.

```
id  1..31  -> slots 1..24 in the 4*slot+lfo grid (4k -> 0)
id 33..72  -> slots 25..64
id 73..106 -> 66 67 68 69 70 71 72 73 74 79 76 77 75 80 81 82 83 84 85 88
              86 87 89 90 91 92 94 93 95 96 97 98 78 99
```

**Joining it to the parameter table** (`0x401f7f94`, 60-byte records: `+0x00`
page, `+0x04` slot, `+0x28` name, `+0x2c` group, `+0x30` short name, `+0x34`
formatter; `+0x18` high byte looks like the MIDI CC, `0xffffffff` where none)
gives every record's lock id: `scripts/lock_ids.py` style join, output in
`out/ws3/lockmap.txt` locally. Pages seen: `0x00` FM TONE, `0x01` WAVETONE,
`0x02`/`0x03` other machines, `0x05`-`0x0a` the six filter variants, `0x0d`
the shared filter envelope, `0x0b` amp, `0x0e` portamento, `0x0f` FX sends and
FX, `0x10` chorus, `0x13`/`0x14` master, `0x16` MIDI notes, `0x17` MIDI SRC,
`0x18`/`0x19` MIDI CC values/selects, `0x1a`-`0x1c` LFO1-3, `0x1d` trig,
`0x1e` none.

## Answers to the eight claims

1. **WAVETONE 38 / 44 = Osc1 Level / Osc2 Level — confirmed.** Page `0x01` slot 30
   (`LEV1`) and slot 36 (`LEV2`); TBL1/TBL2 are slots 27/33 = ids 35/41.
2. **Filter ids — confirmed, with one nuance.** Each filter variant page
   (`0x05`-`0x0a`) carries its own records for slots 66/67/68 = ids 73/74/75:
   73 TYPE / Q / LPF / (none on `0x06`), 74 always `Frequency`, 75 RESO / GAIN /
   FDBK. ENV 76, DEL 77, ATK..REL 78..81, RSET 85, KEY.T 82, BASE 83, WDTH 84,
   BW.RT 105 are single records on the shared page `0x0d`. So 74 is per-variant
   in the table but has the same meaning everywhere.
3. **Retrig storage offsets — not established from the image in this pass.** The
   table does show RTRG/VFAD/LEN/RATE as trig-page records (slots 13..16).
4. **Sound-lock validation — not established in this pass.** Needs the playback
   path read.
5. **FM TONE 58..65 exist** — page `0x00` slots 50..57: Pitch All, Pitch A and B2,
   Ratio All, AB Level, AB Attack, AB Decay, AB End, AB Delay; bipolar, default
   `0x4000`, bipolar formatter `0x400e30f0`. Unlike every other FM TONE record
   they carry **no CC/NRPN** (`0xffffffff` in both fields). Whether a panel page
   shows them is not established; DNX's knob capture did not reach them.
6. **Trig controls share the LFO positions — confirmed.** Page `0x1d` records
   map through the same table: VEL slot 1 -> id 1, LEN 2 -> 5, uTM 3 -> 9,
   AMP.T and FLT.T both slot 4 -> 13, COND 5 -> 17, LFO.T 7 -> 25, PROB 12 -> 14,
   RTRG 13 -> 18, VFAD 14 -> 22, retrig LEN 15 -> 26, RATE 16 -> 30, Euclidean
   17..24 -> 3 7 11 15 19 23 27 31, FILL 25 -> 33, NOTE slot 0 -> the unused 0.
   Those ids collide with LFO ids, so a pool lock could not tell them apart.
   (Why no lock record is written is not read here.)
7. **Shared ids — confirmed.** LFO Slew and Start Phase are separate records on the
   same slot (LFO1: 80/81 slot 6 = id 21; LFO2 slot 14 = 22; LFO3 slot 22 = 23).
   Balance and Pan are both amp slot 89 = id 95.
8. **MIDI SRC — SYXGRID's ids are right.** Page `0x17`: 33 Channel, 34 Bank,
   35 Program, 36 Sub Bank (slot 28, record 167, filed after the others — panel
   order and id order differ). **Note 1..4** are page `0x16` slots 8..11 = ids
   29, 2, 6, 10 — LFO-grid positions. Page `0x16` is classified with the trig page
   by `TrigParameterSet`'s predicate (`docs/parameter-set-tables.md`), so they
   are trig-class data like VEL/LEN, not pool locks.
