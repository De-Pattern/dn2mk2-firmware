# What changed between Digitone II OS releases

Measured 2026-09-11 with `dnfw diff`, from the images Elektron publish. Every
comparison is on **decoded** content: two compressions of the same code differ
everywhere, and that is not a change.

```
dnfw diff Digitone_II_OS1.10D_dist.zip Digitone_II_OS1.10E_dist.zip --strings
dnfw diff Digitone_II_OS1.10E_dist.zip Digitone_II_OS1.11_dist.zip  --strings
```

| | 1.10D | 1.10E | 1.11 |
|---|---|---|---|
| build | 40049 | **40050** — every patch here targets this | 40059 |
| built (meta section) | 2025-07-27 23:51 | 2025-09-10 15:18 | 2026-09-08 14:25 |
| published at | `…/uploads/2025/10/` | `…/uploads/2026/06/` | `…/uploads/2026/09/` |
| signing key | `"Multiplier"` | same | same |

## 1.10D → 1.10E: "support for updated production processes"

Elektron's release note is one line. What the images show:

| Section | Change |
|---|---|
| meta | the build timestamp, nothing else |
| **bootstrap** (id 2) | **28,254 → 30,302 bytes, and its load address moved `0x01080000` → `0x02000000`.** Rebuilt almost entirely: 24,934 of the first 28,254 bytes differ |
| MAIN OS | +4,096 bytes, and all of it is a zeroed region at the end. The rest is 70 blocks of change, mostly the scattered one-byte pointer updates of a relink, with two dense ones (below) |
| updater | **byte-identical** |
| blob | **byte-identical** |

**No text changed.** Not one human-readable string was added or removed in MAIN
OS. The service-command strings (`#WRITE_SERIAL`, `#READ_SERIAL`, `#WRITE`,
`#MMC_RECONFIGURE`) are at identical addresses in both. So this is not a
feature and not a change to the factory command set.

The two dense MAIN OS blocks:

| Where (1.10E) | Bytes | What it looks like |
|---|---|---|
| `0x402dcb12 .. 0x402e1bf3` | 15,265 | ColdFire code addressing on-chip peripheral registers (`lea 0xffff8006`), with exception returns — driver or start-up code |
| `0x400c2bc6 .. 0x400d8af7` | 4,788 | code just below the service dispatcher at `0x400cf906`; the dispatcher itself barely changed |

**Reading it — INFERRED, not confirmed:** a hardware revision. The bootstrap
runs from RAM and moved to a different RAM address, and the densest MAIN OS
change is low-level peripheral code. "Production processes" would then mean a
new build of the board, and 1.10E is the release that runs on it. Nothing here
was disassembled; the reading rests on where the changes are and what kind of
bytes they are.

**What it means for this project:** little, and usefully so. The only
recovery-related code that moved is the bootstrap, and our images carry stock
1.10E's bootstrap byte for byte. The updater did not change. So 1.10E did not
introduce the recovery stall — that is our images' shape, see
`docs/flashing.md`.

## 1.10E → 1.11: Outbox 8

A different kind of release entirely.

| Section | Change |
|---|---|
| bootstrap | same size, **moved again** to `0x02010000`; 5,666 bytes differ |
| MAIN OS | **+106,496 bytes**, and everything after the first few bytes has shifted — real feature work, not a relink |
| **updater** | **changed for the first time** in these three releases: 14,231 bytes differ |
| blob | +3,896 bytes |
| **id 8** | **new**, 159,948 bytes decoded, not yet looked at |

The text that appeared is all Outbox 8 and CV configuration — `OUTBOX 8
CONNECTED`, `CV OUT %d`, `PITCH V/oct`, `S-TRIG`, `BreakOutBoxRoutingMenuView` —
plus new storage versions (`projectStorage_v14_t`, `soundStorage_v3_t`, …).

**What it means for this project:** a patch written against 1.10E cannot be
reapplied to 1.11 by offset. MAIN OS moved throughout, so every patch has to be
found again — which is what the `find`/`expect` fields in `patches/` are for,
and why a patch names the build it targets. The compression and signing are
unchanged, and the limits in `src/dnfw/codec/limits.py` were measured on 1.11,
so the pipeline itself carries over.

## Reading `dnfw diff`

- **Blocks are densest first.** A relink produces many small blocks; a rewrite
  produces one large one. Read the top of the list.
- **When lengths differ, the shared prefix is compared unshifted.** Growth at
  the end — 1.10D to 1.10E — then shows only the real changes. An insertion
  part-way through shows as one block from the insertion to the end, as in
  1.10E to 1.11. That is correct, not a failure to align.
- **`--strings` is a filter, not a parser.** It keeps strings that contain a
  word and drops most code, but the odd code fragment (`DHKU *`) gets through
  and reads as one.
