# FASCIA into v0.45: the integration plan (2026-11-08)

The owner's decisions:
- FASCIA joins v0.45.
- RAM banks are on hold.
- PING and Waverider are removed to make room.
- 3 pages of 8, with the rest folded as macros (`src/dnfw/fascia/model.py` `expand()`).
- The 3-page tour is approved (owner, 2026-11-08: "sounds amazing"). The goldens are regenerated (dn2mk2-bench `goldens/fascia`, v2).
- PING is out (commit 6d3ba05): the stub at PING_SW, image headroom +18,269.

Status of the rest of v0.45, all on branch `v045`:
- SAMP snap: done (rectrig 38+).
- SELECT UNUSED: done, gate step `unused` PASS.
- Library 16,384: done.
  - link16 `nest` PASS, after the superblock-capacity fix.
  - link16 `lib` needed its allowed-writes list to include the extension header (fixed, not yet rerun).
  - erase PASS.
- Trig LEDs: done (rectrig 41/41).

## Facts gathered (research, this session)

### Records: the panel's 24 controls
- Our machines ride WaveTone's records 238..262. Type 5+ is mapped to type 1 for the slot→id lookup (`coldfire.py:213`) and the ownership test (`:343-357`).
- 238..260 sit on slots 25..47. 261/262 (MAST/FINE) sit on slots 48/49, have no CC, and appear on no stock page.
- Only 20 of the 25 go 0..127. TBL1/TBL2 are 0..1, MOD is 0..3, RSET and TYPE are 0..2.
- Slots 50..64 have no WaveTone record. FM Tone's (page 0) records 227..237 and 208..211 sit there, all 0..0x7f00 and without CC.
- Plan: the 24 controls go on the 20 full-range WaveTone records plus FM Tone's spare slots (owner OK, 2026-11-08: no CC on those). That needs `slot_shim`/`canon_valid` to accept page 0 ids for type 18.
- PERC/MnM ride WaveTone's records 238..245 (`perc/machines.py:40-58`). Samplers use `RECORDS` (`sampler/machines.py:29-38`).
- DSP value = `clamp((word>>8) - lo, 0, top)` (`perc/program.py half()`, `sampler/program.py ctl()`).

### Machine type
- **18** is the next free type. In use: PERC 5; MnM 6, 7, 14, 15, 16; samplers 8..13; BOUNCE 17.
- `NEW_TYPES`, `MACHINE_NAMES`, `LIST_NEW` live in `coldfire.py:54-80`. `GROUP_SOURCE` puts 18 in the synth group.
- **Breaks silently on type 18 unless handled:**
  - `pages.py` `wr_count` (:575) / `wr_page` (:607) / `wr_label` (:672): out-of-range table reads.
  - `mnm_index`/`SMP_IDX` return -1.
  - `dsp.py lookup16()` (:212-222) maps unknown types to 0 = **FM Tone**: it must map 18 to `SMP_ENGINE_SLOT` 5.
  - `MACHINE_TYPES` (`dsp.py:188`) must grow.

### Detents and quant
- `fmt.c:86` `need = count <= 8 ? 4 : 1`: BODA (9) and BODB (10) would get one detent each. Make it 4 for FASCIA's choices too.
- `func_kind` covers ids 238..260 only (`OWN_REC_LAST`, `fmt.c:129`).
- The choice zone maths `(k*n)>>7` equals the model's `choice()`.

### Names, highlight, slides
- LFO names: `wr_names`/`wr_named_*` (`pages.py:334-364`, kinds contiguous). Unused records named "-"; `wr_lfo_mask` (`page.c:92-101`) hides them.
- P-lock highlight: `locked()` (`md_page.c:166-174`); `smp_knob_page`/`cell` (`smp_page.c:386-480`) is the DT2-style grid to copy.
- Slides: `slide.c continuous()` (:126-152) needs a type-18 row (`dnfw/slides.py:62-90`). Continuous controls only.
- Defaults on MACHINE SEL: `rec.c` `smp_machine_commit` (`mnm_default`/`mnm_rid` pattern, :739-763).

### DSP
- PERC DSL `dnfw.perc.dsl.Prog` (emit/run). MnM machines adapt into PERC's voice (`mnm/machines.py:85-127`); dispatch is in `perc/program.py voice()`/`program()`.
- Frame: note at header `2+2t`; params at `168 + 2*slot + 146t`; trigger from `TRIG_WORD>>16`.
- **Velocity (found, v0.45):** frame header word `52 + 2t` = the trig's velocity << 8 (ColdFire frame builder 0x4002750c copies `0x8000dd40[t]`; `docs/modulation-matrix.md`). FASCIA reads `min(w >> 8, 127) / 127`.
- L2 code: perc.asm 139,188 of 143,360. L2 0x200E9000..0x200FA000 is unused, but `dsp._check_l2` refuses spans past 0x200EA000 (64 KB clear of the non-cacheable window), so FASCIA's code went to 0x200B1000..0x200C0000 and its voices to 0x20098400 / 0x200A9400 (docs/fascia.md, DSP).
- L1 tail: MnM render scratch to 0x2E6400; REGION to 0x2E7000. DDR above `DDR_FLOOR`.
- Tables: SHFT's sine (256/turn), exp2/tan, xorshift noise.
- Cost: runner `--steps cost`. Guard: `perc/guard.py`, `docs/dsp-time.md`.

### Size (the 2 MiB USB-upgrade limit)
- v0.45 before FASCIA: 2,086,256 of 2,097,152 (+10,896).
- **Removing PING frees about 7.2 KB, measured** (DDR tables 5,504 stored, code 1,401, chunk 127), so the headroom becomes about 18 KB.
- **Waverider frees nothing:** its leftovers are not in the image, and everything named "waverider" is shared plumbing.
- DSP code compresses to about 40 % (aPLib). FASCIA's DSP plus ColdFire must fit about 16 KB stored, with margin.

### PING removal (agent's measured plan)
1. **DSP:** replace `ping.asm` with a stub at `PING_SW` 0x170280 that does the register restore from 0x2dde00, re-runs the two stock instructions, and `JUMP 0x1c944c`. **Never delete it outright: every machine of ours returns through it.** Drop the "PING state" span (`dsp.py:289`) and the "PING tables" span (`dsp.py:326`).
2. **ColdFire:** drop `ping_cf.compose` (`coldfire.py:860-867`) and with it all its edits (FLTR list 0x4004db0c.., name bounds 0x400dc3a4.., the LOAD bound 0x400dd2bc back to stock, slot_to_id 0x400dc096, the descriptor 0x400c24b0, the curve 0x4006eca0). In page.c drop `ping_names`/`ping_active`/PING's part of `wr_cell`, but keep `sl_cell`. Drop the `ping_pages.c_header()` include. Drop the gate's `ping_slot` chunk check.
3. **Keep** `dnfw/ping/live.py`'s float helpers: `shft.live` (PERC's AMD sine) imports them.
4. **Gates:**
   - Drop the `ping` group from `gate_sharc.py` and `step_ping` from `sharc_waverider_m5.py`.
   - Drop `test_ping_*` from TESTS; rework `test_shft_live`/`test_gran_live`/`test_waverider_dsp`.
   - The engine step's `--filter-max 5`: a saved PING sound loads as Multi-Mode.
5. **Release note:** sounds saved with PING load as Multi-Mode (RING becomes resonance: can be loud).

## Order of work
1. PING out, then gate steps for what it touched.
2. `fascia/live.py`: float32 in DSP order, 16 modes per body, twins on the low 8, per-block coefficients; held to the model within spectral tolerance; owner listens.
3. The DSL program (a chained L2 program), the type-18 dispatch, voice rest/steal, velocity.
4. ColdFire: type 18, records, pages (DT2/Elektron grid), quant (4 detents for every choice), names, slides, defaults.
5. Gate steps: SHARC (fascia bit-exact to live.py, chords, garbage, stress, silence) and ColdFire (pages, defaults, functurn, slides); unit tests in TESTS.
6. VERSION 0.45 (already), regenerate, preflight, then step by step, then the full gate. Publish.
