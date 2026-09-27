# Notes for digikit's SHARC runner: memory the chip does not have (2026-09-27)

These notes are for digikit's `work/sharc-emulator` branch at `6f812e9`. They
record a finding with no change of ours to land, so they are written up here,
not sent as a PR. We call digikit as a tool from a checkout we name, and copy
none of its code.

## 1. Any address resolves

`sharc_core.memory._dm_read` / `_dm_write` serve every concrete address:

- If an address is not in the loaded image, `_canonical_dm_address` retries it
  through the `0x28000000` alias.
- A read the loader never covered returns the loader's bytes where they exist,
  or 0 under `explicit_memory_model`, or Unknown by default.
- Nothing checks the address against the ADSP-21569's memory map:
  - four L1 blocks of 192, 192, 128 and 128 KB at byte `0x240000`, `0x2c0000`,
    `0x300000` and `0x380000`, with gaps between them;
  - the caches carved from the tops of blocks 1-3;
  - L2 at `0x20000000` (1 MB), DDR, and the MMR windows.

This is how the DN2 project's Waverider Milestones 1-4 kept wavetables at DM
`0x280000..0x2a0000` for four milestones and read them back correctly. That span
is the gap between L1 blocks 0 and 1, so on silicon it is not memory.

## 2. A strict wrapper, and what it found

`scripts/sharc_strict_memory.py` (in the DN2 repository) wraps the module-level
`_dm_read`/`_dm_write` bindings and `Runner._decode` from outside, and changes
nothing in digikit. Per access it records any of:

- an address outside real memory;
- an address inside a cache-carved region;
- a misaligned 2- or 4-byte access;
- an L1 read of a byte neither the boot stream nor an earlier write put there;
- an instruction fetch outside code memory.

On DN2 1.11, from our post-engine-init snapshot, one block of the stock image
with a WaveTone track trigged gives:

- **"outside" accesses near 0 and near `0xffffff00`**, from stock code at sw
  `0x1c1b65..0x1c314e`. They are null and negative pointers, read out of the
  caller locals our harness zeroes (our `UNPACK_LOCAL` stand-in). That is a
  harness artefact, but the runner gave no sign of it.
- **24-38 misaligned 4-byte accesses** from stock code (e.g. sw `0x1c28e3`, byte
  `0x25c4ae`) in the frame-copy area. These are 16-bit fields. Either the access
  width the executor passes is 4 where the instruction's is 2, or the silicon
  allows it. Worth a look either way.
- **Reads of never-written block-2 bytes** (`0x300000..0x300054`) from sw
  `0x1c26b7..0x1c26c2`. Those are the stack arguments of our harness frame, whose
  stack grows down from `0x300000`. That puts the harness frame in a gap
  (`0x2f0000..0x300000`) and its arguments over the first bytes of L1 block 2.

None of these is a digikit bug in what it executes. Each one is the runner
answering an access the chip would refuse or answer differently.

## 3. What would help

An opt-in `strict_memory_map` on `State`, alongside `explicit_memory_model`, that
halts with the PC on the first access outside a real range, or inside a
configured cache region. That would have caught the Milestone 1-4 tables on day
one. The ranges belong in a per-part table (ADSP-21569 here), not in the
executor.
