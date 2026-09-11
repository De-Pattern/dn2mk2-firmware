# Handover — 2026-09-11

Where the project stands, what is in flight, and what to do next, for whoever
picks it up. Everything here points into the rest of `docs/`; this file is the
map, not the evidence. Overwrite it at the next handover rather than appending.

## In one paragraph

`dnfw` takes an Elektron OS `.syx`, decodes every layer, lets you replace or
patch a section, and rebuilds a signed image the instrument accepts. **Phase 1
is closed:** a recompressed image (Gate D) and a visibly patched one (Gate E,
`SETTINGS > PERSONALIZE` → `DNFW ALIVE!`) both boot on a Digitone II. **One
thing is open and it matters:** those images stall in the Early Start-up Menu's
recovery flash, the one route that works when MAIN OS does not. A fix is built
and waiting for a hardware test. Phase 2 — a fourth LFO — has mapped the
parameter table and is looking for the code that reads it.

## Status

| | |
|---|---|
| Decode / re-encode byte-identically (Gate A) | done |
| aPLib depack and pack (Gate B) | done — smaller than stock on every section |
| Rebuild re-signed and verified (Gate C) | done |
| Disassembler validated (Gate F) | done — Ghidra 12.1.3 passes, Capstone fails |
| Recovery path, **stock** image | done 2026-09-08 |
| Gate D, Gate E — **normal update path** | **done** (reported 2026-09-11) |
| Gate D, Gate E — **recovery path** | **stall at ~80%** — fix in PR #10, untested |
| Phase 2: is the LFO count a table? | yes — `docs/lfo-parameters.md` |
| Phase 2: what reads the table | **unknown** — nothing holds its address |

## Open pull requests

| PR | Branch | What | Merge notes |
|---|---|---|---|
| **#10** | `fix/recovery-shape` | Pad compressed sections to 4 bytes; bound matches to Elektron's 1 MiB window; verifier enforces both; section 2 renamed "bootstrap"; Gates D/E recorded | **Merge first** — every future build depends on it |
| #9 | `analysis/lfo-table-consumers` | The parameter table is 320 records and the id is not unique; `dnfw params` | conflicts with #10 in `docs/flashing.md` |
| #11 | `analysis/os-versions` | What 1.10D→1.10E and 1.10E→1.11 changed; `dnfw diff` | conflicts with #9 on `cli/main.py`'s import line |
| this | `docs/handover` | this file, README status | — |

Each PR stands alone against `main`. The conflicts are all adjacent insertions,
trivial to resolve; whichever merges later gets rebased. **The owner merges;
nothing is pushed to `main` by anyone else.**

## Next, in order

### 1. The recovery test — needs the instrument

Flash **`gate-d2_DN2_1.10E_recompressed.syx`** through the Early Start-up Menu
(`FUNC` at power-on, `TRIG 4`, DIN MIDI — procedure in `docs/flashing.md`).

- Build it from PR #10's branch if it is not already in `00_Resources/02_Builds/`:
  ```
  dnfw extract 00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip --section 3 -o out/
  dnfw build   00_Resources/00_Firmware/Digitone_II_OS1.10E_dist.zip -s 3=out/section_3_MAIN_OS.aplib.bin \
               -o 00_Resources/02_Builds/gate-d2_DN2_1.10E_recompressed.syx
  ```
- The builds are deterministic. **The right file reports content checksum
  `0x716ce858`** in `dnfw inspect`, with every check `[ok ]`, including the
  two new ones: "padded to 4 bytes" and "within Elektron's limits".
- Gate E2 (`dnfw patch apply ... -o gate-e2...`) reports `0xbb2ae9c3`.

**If it completes:** record it in `docs/flashing.md`, then flash Gate E2 the
same way. Recovery works for our images and experiments are safe again. Which
of the two fixes mattered can be split later with one image per fix, if two
more twelve-minute transfers are worth it.

**If it still stalls:** stop guessing and read the bootstrap — step 2.

### 2. If needed: read the bootstrap

Section 2 is the recovery receiver, and a copy ships in every `.syx`: about
30 KB of ColdFire, loaded at `0x02000000` in 1.10E, opening with a
`[u32 size][u32 0x80010000]` header, strings intact (`READY TO RECEIVE`,
`RECEIVING...`, `LENGTH ERROR`, `CRC CHECK`, `VERSION CHECK`, `UPGRADE FAILED`).
Find what references `RECEIVING...` and `LENGTH ERROR`, and read how it copies
a section and how it decompresses. The two hypotheses to confirm or kill are in
`docs/flashing.md`: a length that is not a multiple of four, and a match beyond
1 MiB. Only Ghidra is cleared for this (Gate F); see `docs/mainos-image.md`.

### 3. Phase 2 — the fourth LFO

- **What reads the parameter table.** It is at `0x401e29d4`, 320 × 60-byte
  records, and nothing in MAIN OS holds its address — not the base, not the end,
  not any record. So the consumer uses PC-relative addressing, a base register,
  or an anchor nearby. Find it; it is also what would have to be told the table
  grew. `docs/lfo-parameters.md` on PR #9.
- **Thirty seconds on the instrument:** does the DN2's FX track have LFO pages?
  The clustering of parameter ids rests on it, and with it the proposal that
  LFO4 takes ids `100–107`.
- **How table ids relate to DNX's p-lock ids** (`4 * slot + lfo`). Not
  established; do not assume.

### 4. A decision for the owner: 1.11

Elektron now publish **OS 1.11**, which adds Outbox 8. Every patch here targets
**1.10E, build 40050**, and the guards refuse anything else rather than patch it
blindly. 1.11's MAIN OS moved throughout, so porting is re-finding each patch,
not reapplying offsets (`docs/os-versions.md`). The pipeline carries over: same
signing key, and the codec limits were measured on 1.11. Staying on 1.10E
until LFO4 works is the cheaper path; moving is needed only if Outbox 8 is.

## The two machines

The work has run on two Windows machines, and they are not equivalent.

| | The flashing machine | The second machine |
|---|---|---|
| Windows user | `a` | `Angel Linares` |
| Instrument, Transfer, MIDI | yes — Elektron Transfer, Focusrite USB MIDI (DIN out) | no |
| WSL | Ubuntu, with `m68k-linux-gnu-objdump` | installed, **no distribution** |
| Ghidra | 12.1.3, in WSL under `/opt/ghidra_*` | none, no Java |
| Corpus `00_Resources/` | full: 1.10E, DN1 1.42A, reference clones, builds | 1.10E re-downloaded; builds `gate-d2`, `gate-e2`; reference tool cloned (not built — no compiler) |
| Tests | the full suite, nothing skipped | DN1 and Gate F tooling tests skip; the rest pass |

Things only the flashing machine has:

- **`Transfer.log`**, at `%APPDATA%\Elektron Overbridge\Transfer.log`. Read it
  before suspecting an image — `docs/flashing.md` (on PR #9) explains why.
- A Ghidra decompile helper (`ghidra/DecompileFunction.java`, `decompile.sh`)
  was written during the service-dispatcher work and **never committed**. Check
  that machine's working tree before rewriting it.

Stock images are public. Keep them in `00_Resources/00_Firmware/`, never in git:

```
https://www.elektron.se/wp-content/uploads/2025/10/Digitone_II_OS1.10D_dist.zip
https://www.elektron.se/wp-content/uploads/2026/06/Digitone_II_OS1.10E_dist.zip   <- the one we build from
https://www.elektron.se/wp-content/uploads/2026/09/Digitone_II_OS1.11_dist.zip
```

1.10E's zip is 1,791,511 bytes, SHA-256 `2971b74c…70b3bce78bba`; `dnfw inspect`
reports build 40050, container 1,743,120, 17,259 packets.

## Rules that are not negotiable

- **Never push to `main`.** Branch per feature, atomic commits, a PR at the end;
  the owner merges. `docs/BRANCHING.md`.
- **No claude.ai session links in PR descriptions.** Commit trailers are fine.
- **Nothing reaches the instrument** without the owner's explicit go-ahead and
  a named transport. **Verify before sending:** `dnfw inspect` on the exact file.
- **Never send `#WRITE_SERIAL`, `#WRITE` or `#MMC_RECONFIGURE`.**
  `docs/service-commands.md`.
- **Do not patch the key material** — the string `"Multiplier"` in the
  bootstrap. The recovery receiver carries it too. `docs/ele3-format.md` §5.
- **No Elektron firmware in the repository**, original or modified. Code and
  documentation only.
- **Code shape:** one subject per module, no god files, every capability
  reachable from `dnfw`, reuse the reference repos before writing.
  `docs/PRINCIPLES.md`.

## What was learnt the hard way

- **A green checksum is not a working image.** Our images passed every checksum,
  the HMAC, the reference C tool and the normal update path, and still stalled
  in recovery. The differences were in shape — padding and match distance —
  and nothing checked shape until it was measured against Elektron's own
  streams. When a build misbehaves, compare its *shape* to stock, not only its
  integrity fields.
- **The normal update path is forgiving; recovery is not.** Success through
  Transfer's drop onto a running device does not show an image is safe.
- **Transfer validates nothing.** It says "This syx is for Unknown" about stock
  and about ours alike. A stalled send was a held MIDI port
  (`MIDI Device already in use`), and stock itself needed three clicks on Send.
- **Labels inherited from the reference tool are guesses.** Section 2 was
  "DSP" for a week; its own strings say it is the recovery receiver.
- **Walk a table to its real edges.** The LFO table looked like 30 records and
  a constraint ("Chorus starts at 25"); it is 320 records and the constraint
  was not real. A string test that rejected empty labels stopped the walk
  early.

## Where everything is

| Doc | Holds |
|---|---|
| `README.md` | what the tool does, install, commands |
| `docs/ROADMAP.md` | phases and gates |
| `docs/PRINCIPLES.md` | how code is written here, and why |
| `docs/BRANCHING.md` | the git workflow |
| `docs/ele3-format.md` | the file format: transport, container, sections, codec, signing |
| `docs/mainos-image.md` | the CPU, Gate F, the C++ names, the string pool |
| `docs/flashing.md` | both update routes, the recovery issue, the hardware record |
| `docs/lfo-parameters.md` | the parameter table (fuller version on PR #9) |
| `docs/service-commands.md` | the factory command interface — read before sending anything |
| `docs/os-versions.md` | what each OS release changed (PR #11) |
| `docs/references.md` | the reference projects and what was taken from each |
