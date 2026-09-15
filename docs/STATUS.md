# Project status — the one place to look first

**Living document. Last reviewed 2026-09-16.**

This exists because on 2026-09-15 the assistant told the owner that LFO4's
engine side was **closed** when it is **unknown** — by reading a row lower in
`docs/flashing.md` and taking position in a table for recency. Two rows there
stated opposite verdicts for the same build, and had done for three days.

So: **this file is authoritative for *state*.** The linked documents are
authoritative for *evidence*. Where they disagree, the linked document wins on
what was measured, and this file is wrong and must be fixed.

Rules that keep it honest:

- A claim moves to **Closed** only with a named measurement and a document.
- A claim that is retracted stays visible, struck, with a pointer. Never delete.
- "Not started" and "unknown" are different. Unknown means we tried.

---

## Features

| Feature | State | Gate | Evidence |
|---|---|---|---|
| **Extra LFO destinations** | **SHIPPED** | — | `docs/modulation-mask.md`, browser tool, PR #61 |
| **Transient Swapper** | **SHIPPED** | — | `docs/pcm-hunt.md`, `docs/tran-mapping.md`, PR #64 |
| **TRAN mapping** | **SOLVED** | — | `TRAN = 4 × slot − 8`; 32 of 34 reachable; `docs/tran-mapping.md` |
| **LFO4** | **UNBLOCKED** | **No engine blocker left.** The DSP plays no part — modulation is generated and applied on the ColdFire, and LFO parameters are never sent. What remains is ColdFire work: a modulator slot, the page id, and the page-view | `docs/engine-state.md`, `docs/lfo4-slot-plan.md`, `docs/modulation-mask.md` |
| **Chimera (DT2 machines + samples)** | **SCOPED** | ColdFire half tractable; SHARC half **blocked on reading SHARC code, no longer on reaching it** — we ship its program and know how it is loaded | `docs/chimera-feasibility.md`, `docs/sharc-image.md` |
| **Sample transfer / RPC** | **IN PROGRESS** | what dispatches an opcode | `docs/midi-rpc-dispatch.md` |

### LFO4 — the pieces, and which are real

| Piece | State |
|---|---|
| Storage (reserved 4th slot in the sound format) | **Done by Elektron** (DNX) |
| Destination masks (4th rank on every modulatable parameter) | **Done by Elektron** |
| Modulation apply (generic over parameter index) | **Confirmed on hardware** |
| Parameter records (10 dead ERR slots to repurpose) | **Built** — `scripts/build_lfo4_test.py` |
| Enumeration (getting records into the set the LFO walks) | **Solved, a data edit** — `docs/parameter-set-tables.md` |
| Page id — range test `(page - 0x1a) <= 2` | **Blocked** — `0x1d` Retrig, `0x1e` None |
| Fourth page-view + `[MOD]` navigation | **Not started** |
| **Modulation apply and generation** | **ColdFire, both.** `0x400db1dc` is the MAC-unit kernel; `0x400db22c` drives it for 6 sources × 4 destinations × 16 tracks, inside the DSP-frame ISR |
| Runtime slot space — 8 contiguous slots | **DESIGNED, not built.** ~~BLOCKED~~ — the array genuinely cannot grow in place (101 entries, flush against the machine-type byte at `+0xde`, and it is a field in each of 128 × 2,388-byte sound objects, not a table). But `docs/lfo4-slot-plan.md` gives **two** designs that remove the requirement: a 2,048-byte extension array in the 25 MB for slots 101–108 (~11 hooks), or a **track-level** LFO4 that needs no slots at all (~3 hooks, at the cost of LFO4 not being saved per sound). Neither is built or verified |
| **Does the engine run a 4th LFO generator?** | **DISSOLVED 2026-09-16 — the question was wrong.** The DSP never sees an LFO. Modulation is generated *and* applied on the ColdFire (`0x400db1dc`, MAC unit) into a per-track array, and the DSP frame carries only indices **25–99** — LFO1–3's parameters are 1–24 and are never sent. Confirmed by two independently-derived block boundaries (25 = machine start, 66 = filter start). **A 4th LFO needs no DSP support at all.** `docs/engine-state.md` |

---

## Research items

### Closed

| Item | Answer | Where |
|---|---|---|
| ELE3 container format | Measured, both devices, HMAC reproduced | `docs/ele3-format.md` |
| Container build string offset | `0x08`, not `0x07`; `0x04` is a u32 product code | `docs/ele3-format.md` |
| Product code / device gate | One `moveq`: 52 DN2, 43 DT2, 54 DN1 | `docs/ele3-format.md` §3a |
| Recovery path | Proven on hardware; needs physical MIDI DIN, not USB | `docs/flashing.md` |
| Code caves execute | `CAVE RAN!!!` on hardware | `docs/code-caves.md`, `docs/flashing.md` |
| SHARC program ships in the update | Section 7, ADI boot stream, FreeRTOS/CCES | `docs/sharc-image.md` |
| **How the SHARC is booted** | **The ColdFire pushes it over SPI** — `0x400cf34c` reads section 7, then byte-at-a-time through a DSPI at `0xec038000` (`PUSHR` `+0x34`, `SR` `+0x2c`). SPI *slave* boot, every power-up | `docs/sharc-image.md` |
| **Is the DN2's engine modifiable?** | **Yes in principle** — ~~"permanently unmodifiable"~~ retracted. The DSP has no program until we give it one | `docs/engine-index-map.md` §9 `[SUPERSEDED]` |
| `0xec09xxxx` is an FPGA register file | ≥279 accesses, 57 addresses, byte-wide; **not** a data path — far too few to carry audio | `docs/sharc-image.md`, `scripts/mmio_window_map.py` |
| `0xec038000` is a DSPI block | Six registers at the six standard offsets (`MCR`, `CTAR0/1`, `SR`, `RSER`, `PUSHR`), internally consistent with the `PUSHR` words used | `docs/sharc-image.md` |
| Transient bank location | DDR `0x8045c380`, 34 × 4,800 samples | `docs/pcm-hunt.md` |
| MIDI RPC wire format | From `dagargo/elektroid`; ping answers | `docs/midi-rpc.md` |
| DN2 advertises 22 opcodes, no FsSample | Static array at `0x40207f30`, one reference | `docs/midi-rpc-dispatch.md` |
| SDRAM extent / unclaimed window | 128 MB; **25.3 MB above BSS is free** | `docs/memory-map.md`, `docs/ideas-backlog.md` §6 |
| Who asks for sections by id | **MAIN OS, twice** — `pea #7` at `0x400cf59a`, `pea #8` at `0x400f2934`, both into its own `find_section_by_id` at `0x4013459a`. Literal immediates, **no table** | `docs/ideas-backlog.md` §6 |
| Container parser exists in three places | Bootstrap `0x02015028`, updater `0x80003d28`, **and MAIN OS `0x40134554`** — each with its own `moveq #52` product gate | `docs/ele3-format.md` §3a |
| Heap location | A static arena *inside* BSS; nothing above `0x466b748c` | `docs/ideas-backlog.md` §6 |
| **Does anything honour a section's `dest`?** | **No — nothing reads it.** The table walk is dead code in the bootstrap (`0x02015066`) and the updater (`0x80003d6e`); live only in MAIN OS, which ignores `dest` and supplies its own buffer | `docs/ideas-backlog.md` §6 |
| **Reading an arbitrary section at runtime** | A generic 4-call API already in MAIN OS: `find_section_by_id` `0x4013459a`, `section_data_address` `0x4013458a`, `block_copy` `0x401350ce`, `malloc` `0x4011ffe8` | `docs/ideas-backlog.md` §6 |
| Section entry layout | `+0 id`, `+4 offset`, `+8 stored length`, `+12 dest` — confirmed from the section-8 caller | `docs/ideas-backlog.md` §6 |
| SHARC+ figure extraction | 54/54 figures, 96.69% bit accounting = the ceiling | `docs/sharc-visa-extraction.md` |
| Classic PGR cross-check | All `a`-forms agree; Type 2b conflict confirmed | `docs/sharc-crosscheck-classic-pgr.md` |
| Runtime mirror format shared DN2/DT2 | `Digisharc::` versions identical bar `voiceConfig` | `docs/chimera-feasibility.md` |

### Open

| Item | State | Next move |
|---|---|---|
| **What dispatches an RPC opcode** | Five static approaches failed; DT2 diff reframed it | Extend DN2's list with `10 13 11 12`, count 22→26, ask the device |
| **What crosses to the SHARC at runtime?** | **Answered, by digikit** — a periodic **DSPI2** frame over **eDMA 28/29**, `(tx_len, tx_buf, rx_len, rx_buf)`, driven from an interrupt. She has the frame's 16-pass per-track loop; we contributed the cross-device counts | `docs/sharc-image.md` |
| **What are the other three modulator sources?** | `0x400db22c` applies **six** per track, each with its own 16-word value table and a four-entry destination list. The UI offers three LFOs. If one of the six is free, LFO4 has a home with no structural change | Read what writes the six descriptor lists at `%a2@(3476 + 16k)` — that is where a DEST and DEPTH from the UI land. **Do not assume three are spare** |
| **Does the DSP frame carry an engine/machine id?** | **Open, and digikit's too** — she traced the frame's 16-pass per-track loop over three SRAM tables and found **no engine id in it**, so "stock engine, own parameters" for a new machine is still open | Her `[O]` item; the DN2/DT2 `tx_len` difference (2,688 vs 2,050) is a new constraint on it |
| **The SHARC Audio Task's structure** | Entry pointer unresolved (digikit, decode desync) | Blocked on decompilation, not disassembly |
| **The last 72 bits of SHARC figures** | Not named in Rev 1.5's figures | **Deliberately not chased** — helps nothing; see below |

### Retracted — kept because a closed path is still a signal

| Claim | Fate |
|---|---|
| "The engine implements a 4th LFO" (§11) | **Withdrawn** — storage layout mistaken for engine addressing, §15 |
| "Lanes 3 and 4 coexist" (§14) | **Withdrawn** — same flaw, §15 |
| "125 named transients" | Overstated — `TRAN` is continuous, not a menu |
| "The register classes are not a constraint" | **Wrong** — chapter 27 publishes the encodings |
| "87.82% is 100% of what the figures contain" | **Wrong** — blind to the yellow *unused* cell colour |
| "The PRM alone is insufficient" | Unsupported — withdrawn on digikit PR #11 |
| "Type 2a is a fault in our extraction" | **Wrong** — a generational re-encoding |
| "A section with `dest` above BSS would be written straight there" | **Wrong** — nothing reads `dest`; backlog §6 |
| Bootstrap addresses quoted at base `0x800003fc` | **Wrong base** — it is `0x02010000`; add `0x7dff03fc`-worth of scepticism to any bootstrap address predating 2026-09-15 |
| "The SHARC boots from its own serial flash; the engine is permanently unmodifiable" | **Wrong** — the ColdFire pushes section 7 over SPI at `0x400cf34c`. `engine-index-map.md` §9 `[SUPERSEDED]` |
| "No upload path in MAIN OS" | **Wrong** — a negative from searching the `0xec09xxxx` window; the channel is the DSPI at `0xec038000` next door |

---

## Ideas not yet started

| Idea | Value | Blocker |
|---|---|---|
| **A new ELE3 section as address space** | Would raise the ceiling for the whole project: 25.3 MB vs ~26 KB of caves | **Unblocked 2026-09-16.** A cave of tens of bytes calls the generic lookup and the SPI NOR read. `0x80000` is a **flash offset**, not RAM — digikit's boot trace shows the container read from flash on demand, so nothing has to stay resident |
| Envelope modulator | — | `docs/envelope-modulator-feasibility.md` |
| Mod compatibility check between two mods | Backlog §11 | Wants a mod that shares a section/processor |

---

## Queue — asked for, not yet done

| Request | From | Cost | Note |
|---|---|---|---|
| **Field offsets for `Digisharc::patternStorage_v3_t` vs `_v4_t`** | DNX session, 2026-09-15 | Real work, not a check | Would move DNX from *reading* v4 records to *editing* them. The diff is per-track settings, offsets **1156–1184** within each 1,187-byte track |
| Type 2a / Type 25a field-extent gaps | ours | small | 72 bits over 8 rows; **deliberately parked** — helps no downstream work and would mix sources into a clean metric |
| ~~Send digikit the ColdFire↔SHARC link findings~~ | owner's standing ask | **DONE** | Sent as `m-dwyer/digikit` **#12**. Rewritten first: she was already ahead on the link, so the PR carries only what is additive — the DN2/DT2 frame-length comparison, address correspondences, and both of our corrections |

---

## Open pull requests

**None open on our repo.** #64–#71 all merged; work continues on
`analysis/lfo4-engine-path`. External: `m-dwyer/digikit` **#12** open (the DN2
cross-check of her DSPI2 frame) and **#11** open (SHARC+ VISA cross-check).

> **A branch does not close when its PR does.** #70 merged on 2026-09-15 and
> carried only its **first** commit; fourteen more were then pushed to the same
> branch over two days with no open PR against them, and would have sat there
> unnoticed. This is the fifth time work has been stranded this way in this
> repository. **Check `git log <remote>/main..HEAD` before assuming a branch is
> in flight**, and check the PR's state rather than a note saying it is open —
> this file said "#70 open" while #70 was merged and closed.

---

## How to use this file

Read it first. Then read the linked document for anything you are about to act
on — **this file records what is true, the documents record why**. If you find
them disagreeing, the document is right and this file needs an edit, and that
edit is part of the work, not an afterthought.
