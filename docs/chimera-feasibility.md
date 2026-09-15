# A Digitone II with Digitakt II machines: what the two firmwares actually say

**2026-09-15.** The owner asked two questions: what stops a DT2 image being
flashed on a DN2, and how hard it would be to give the DN2 sample playback,
management and transfer. Both are answered here from the files and from the
connected instrument, not from reasoning about what Elektron probably did.

Images compared: **Digitone II OS 1.11** and **Digitakt II OS 1.16**.

## 1. The two devices run one program

| | DN2 1.11 | DT2 1.16 |
|---|---|---|
| SysEx device id | `0x15` | `0x14` |
| container product code | **52** | **43** |
| build / version | `0059` / 1.11 | `0079` / 1.16 |
| HMAC key string | `Multiplier` | `Master Overdrive` |
| bootstrap | 30,302 B | 30,302 B — **same size, 4.63% of bytes differ** |
| updater | 32,768 B | 32,768 B — **one byte differs** |
| MAIN OS | 3,192,192 B | 3,275,616 B |
| SHARC blob (section 7) | 836,956 B | 321,016 B |
| section 8 | 159,948 B | **byte-identical (SHA-256)** |

**Section 8 is literally the same file on both devices.** C++ class symbols in
MAIN OS: **486 shared, 36 DN2-only, 28 DT2-only.** This is one codebase with a
build-time device configuration.

`dnfw` read the DT2 image with no changes at all — every checksum verified and
**the HMAC trailer reproduced**, so `Master Overdrive` derives exactly as
`Multiplier` does. We can already sign modified Digitakt II firmware.

## 2. What stops a cross-flash: one `moveq`

The updaters differ in a single byte, the immediate at `0x80003d28`:

```
0x80003d1a  movel #1162626355,%d0     ; 0x454C4533 = "ELE3"
0x80003d20  cmpl 0x8000b3d4,%d0       ; magic must match
0x80003d26  bnes 0x80003d3c           ; -> reject
0x80003d28  moveq #52,%d0             ; DN2.  DT2 has: moveq #43
0x80003d2a  cmpl 0x8000b3d8,%d0       ; container product code, offset +4
0x80003d30  bnes 0x80003d3c           ; -> reject
0x80003d32  moveb #1,%d0              ; accept
```

The **bootstrap carries the identical check** at `0x02015028`, differing in the
same one immediate. `VERSION CHECK` in its string table is this.

So the acceptance gate is trivial. **That is not the same as it being safe**, and
three things are not gated by it:

- **The bootstrap is the recovery receiver**, and it differs by 4.63%. Flashing a
  DT2 image replaces the DN2's way back with one built for product code 43.
- **The two SHARC images are different programs**, 837 KB against 321 KB.
- **The panel maps differ** — the bootstrap's own key-name table reads `VOICE` on
  the DN2 and `SAMPLE` on the DT2.

### The construction that is actually safe

Do not widen the recovery. **Keep it, and re-sign the payload.**

- product code **52**
- bootstrap = **DN2's, unmodified**
- MAIN OS and section 7 = DT2's
- signed with **`Multiplier`**

The product code passes, and the HMAC passes *under either hypothesis* — the
image's own key material and the device's installed key are both `Multiplier`,
so it does not matter which one the device uses. Critically, **the recovery
receiver is never modified**, so the way back is preserved by construction
rather than by a patch being correct.

That asymmetry is the whole argument: widening means the first thing you change
is the one component whose failure is unrecoverable, and you cannot test it
except by needing it.

### What is still unknown

**Which key the device verifies with.** Neither bootstrap references its key
material by a 32-bit address — searched both, both word orders — but that scan
cannot see a PC-relative `lea` or a base-register offset, which is the same
false negative `docs/sharc-image.md` records for the SHARC landmark scan. So
this is **unproven, not resolved**, and `§5` of `docs/ele3-format.md` still
lists "does the bootloader check the trailer at all" as open.

The cheap experiment: offer recovery an image signed with a deliberately wrong
key. Rejection at `CRC CHECK` writes nothing — that is the designed path — and
it settles both questions at once.

## 3. Calibrated against a known positive

`bryantysinger/elektron-models-teardown` cross-flashed **Model:Cycles firmware
onto a physical Model:Samples and back**, and their technique is the same one
derived above: preserve the running device's container and section 2, swap the
payload, re-sign with the key derived from the image's own anchor.

Three of their findings corroborate ours from an independent direction:

| | Models teardown | here |
|---|---|---|
| one codebase, build-flagged | builds 3 minutes apart | 486 of ~520 classes shared |
| HMAC key embedded in the image | anchor + following string | same anchor, `Multiplier` / `Master Overdrive` |
| **recovery needs physical MIDI DIN, not USB** | stated as a hard requirement | measured independently, `docs/flashing.md` 2026-09-11 |

We learned that last one as an ~80% stall we first blamed on our own image.

### Where the analogy breaks, and it is the load-bearing part

**Model:Cycles and Model:Samples have no DSP.** Their audio engine is *inside
section 3* — the teardown locates a shared audio core at `0x40054000–0x40058600`
and a Samples-specific engine at `0x400A1000–0x400A7FFF`. Swapping section 3
swapped the whole instrument in one move.

**The DN2's engine is section 7**, a separate ADI boot stream, and MAIN OS is
coupled to it through the parameter table (`docs/fx-parameter-space.md`). So
their one-section swap does not transfer: here it is two components, not one.

**And the direction they proved is the opposite of the one wanted here.** They
flashed the simpler OS onto the sampler, and explicitly did not test the
reverse, flagging that "the Samples does sampling and may expect memory or
storage the Cycles does not have". Putting DT2 firmware on a DN2 is that
untested direction. The one mercy is that the DN2 carries the same 32 GB eMMC,
so the storage a sampler expects is physically present.

## 4. What the DN2 already has, measured on the instrument

The whole sample **MIDI RPC protocol surface** is compiled into DN2 MAIN OS —
all 40-plus `MidiRpcFsSample*` request/response classes, at *identical
occurrence counts* to DT2. So is `SampleLoaderBgWorker`, `SampleWaveformsFactory`,
and the project-format key **`sample_references`**.

**But nothing answers them.** Asked over MIDI on a connected Digitone II:

| opcode | advertised? | reply |
|---|---|---|
| `0x01` ping | yes | answers — 22 opcodes, "Digitone II" |
| `0x02` software_version | yes | answers — `0059` / `1.11` |
| `0x05` storage_info | **no** | **silence** |

The capability list is `01 02 03 04 06 07 09 50 52 51 53 54 55 56 57 58 59 5a
5b 5c 5d 5e` — **no `FsSample` (0x10+), no `FsRaw` (0x14+)** — and an
unadvertised opcode draws nothing in the same window two advertised ones
answered in.

*Caveat, stated because the repository's habit is to state it:* the `0x05`
silence is n=1, and a live alternative is that the opcode dispatches fine but
expects a payload and was sent empty. The negative worth defending is the
symbol one below; the RPC probe corroborates it rather than proving it.

### The layer split

| layer | DN2 | DT2 |
|---|---|---|
| block / volume (`MBR`, `Volume`, `eMMC`) | **5 / 5 / 3** | 5 / 5 / 3 — identical |
| `/projects` path namespace | **4** | 4 — identical |
| FS layer (`fs_`, `FileSystem`, `filesystem`) | **0** | 15 / 3 / 2 |
| `File`, `Directory`, `FileOutputStream` | **0** | present |
| `SampleManager` | **0** | 69 |
| nested directory tree | — | `/1-Dusty/110BPM`, `/factory` ×1359 |

So the DN2 is **not** missing storage — it has the block layer and a
path-addressed store, which is how `/projects` works today. It is missing the
**directory layer above it**, the handlers, and the UI.

### One design route considered and rejected

Samples could in principle live in the DN2's existing data-object store, which
is advertised, bidirectional and working today — that would delete the
filesystem port entirely.

**Rejected by the owner, correctly.** `DataMove` / `DataCopy` / `DataSwap` are
the signature of bank/slot addressing — the sound-bank model — and sample
management on a flat or slot namespace does not scale to a library. Directories
are required. Recorded here because the reasoning is worth keeping even though
the conclusion went the other way.

What survives from the observation is narrower but real: the **chunked bulk
transfer machinery is proven working on the instrument** (open / partial /
close, `rpc_file_chunk_size_max`), so whatever namespace sits on top, the
transport is not a risk item.

## 5. The work, in order of risk

1. **SHARC sample playback.** Section 7, a different program from DN2's, and
   nothing here decodes SHARC yet. The hard part; unchanged by anything above.
2. **Sample RAM budget** on the SHARC's DDR3 — cheap to measure from section
   7's nine load regions, and it could constrain everything else.
3. **FS layer port** — `File`, `Directory`, `FileOutputStream`, `FsRequestHandler`,
   `fs_rebuild_index`, onto a block layer already present on the DN2.
4. **RPC handler registration** — the message classes already ship; the
   capability list is ours to extend.
5. **UI** — browser, picker, free-space view.
6. **DNX client** — an independent track that can start now, since the transfer
   protocol is published (`dagargo/elektroid`) and the device already speaks it.

Elektron Transfer is not a dependency in any of this: a chimera owns both ends.

## Reproducing

```sh
dnfw inspect <dt2.syx>                  # product code, sections, every checksum
dnfw extract <dt2.syx> -o <dir>
python scripts/midi_probe.py --list
python scripts/midi_probe.py --out 1 --in 0 --elektron ping
```

## What was corrected along the way

`docs/ele3-format.md` put the container build string at `0x07`. It starts at
`0x08`; `0x07` is the low byte of the product code. DN2's code is 52 = ASCII
`'4'`, so `0059` printed as `40059` and looked right for eight days. DT2's is
43 = `'+'`, and `+0079` does not look right. The device itself then confirmed
`0059` over MIDI RPC.

**A single-device sample made a wrong parse look right**, which is the fourth
instance of that shape in this project and the reason a second device was worth
more than another week of reading one.
