# PROJECT RAM banks (v0.65)

Owner, 2026-11-20: "the priority is expanding the project ram slots into multiple banks if
possible. we can do 4 for now if thats easier/faster/less burden on the system"; the UI closer
to the DT2's where possible. History: `docs/drive-library-plan.md` §6a.1 (banks only if close to
the DT2's and clean) and §10 (not in v0.31: SAMP's range, the DSP's 128-entry directory, the
saved formats); `docs/ROADMAP.md` (kittito, 2026-11-12, item 4). v0.64's image had 291 bytes left;
v0.65's optimal packer (`docs/packer.md`) leaves 87 KB.

## What it is

- **Four banks, A..D**, 127 slots each (SAMP 1..127 as now), so 508 slots of a project's RAM.
  Bank A is today's pool directory, unchanged: every project, sound, kit and p-lock made before
  v0.65 plays what it played.
- The pool's RAM stays 400 MB, shared by all banks (banks are names for slots, not memory).
- The recorder's four slots and the FLEX buffers stay where they are (bank A's 124..127, the
  buffer directory).

## SAMP: the bank in the value's low byte

A sound's values are 16 bits each (`coarse << 8 | fine`); SAMP's record is coarse, so its low
byte is free in every place a value is kept: the sound, the kit, presets, the pattern's locks
(stock stores a lock as the record's whole word: `docs/user-reports.md` P1), copy and paste.

    SAMP word = slot << 8 | BANK_TAG[b]       BANK_TAG = 0x00 (A), 0x40 (B), 0x80 (C), 0xC0 (D)

- Old values have low byte 0: bank A.
- The knob: `fmt.c smp_quant` (the setter's write, for every SAMP turn and its p-lock) steps
  through one row space: OFF, A001..A127, B001..B127, C001..C127, D001..D127, then the FLEX
  buffers B1..B8 (v0.55), and writes the row's word.
- Writes that are not a knob turn of ours (MIDI CC, stock's own setters) keep the bank the value
  had: a CC picks a slot in the current bank.
- The DSP reads the bank as `(low byte + 0x20) >> 6`, so a small offset (an LFO's) never changes
  bank; the ColdFire's modulation remap (`smp_mod_apply`) steps through the loaded slots of the
  bank of the voice's target.

## Where banks B..D live

- **The DSP.** Three bank pages in the pool's recordings area, below the tables:
  `BANK_AREA = TABLE_AREA - 3 x 128 KB`, so the recordings' room ends there (31.4 -> 31.0 MB).
  Each page is a directory page in bank A's own format (magic `SMPB`, count, 128 entries, names,
  meta pointer unused, library ids) at +0, its meta block (long names; folders are bank A's) at
  +0x1000, its slice area (128 x 768) at +0x3000. The DSP finds a bank's entry and slice table at
  fixed addresses; a page without its magic plays nothing.
- **The +Drive.** The pages are inside the pool image (as everything in the pool is), so they
  load and save with it. The image header's check covers them.
- **Per project.** Each project's list (`docs/project-pools.md`) gets a second list for its
  banks B..D in the free range `0x6E0400..` (`docs/memory-map.md`): two copies, header last, as
  bank A's. A bank's slice tables are kept only for the slots that have one (at most 96 a list).
- **Upgrading.** A recording already lying in the new bank area (only when 31 MB of recordings
  were kept) leaves banks B..D off for that pool and says so.

## The UI (the DT2's)

- **The sample list**: the bank box shows the outlined slot's bank; SAMP and UP/DOWN run on
  through the banks; FUNC + UP/DOWN jumps a bank (the DT2's FUNC + arrows).
- **SAMP's box** on the SRC page: the bank letter in its filled part (A, B, C, D; F for FLEX).
- **The browser**: PROJECT RAM lists bank by bank (A: .., B: ..); LOAD TO PROJECT fills the first
  empty slots of the bank the list was on, then the next banks.

## Gate

- `banks` (new, ColdFire emulator): SAMP turned through A127 -> B001 and back, p-locked to C005,
  a sound saved and loaded keeps its bank, a CC keeps the bank; LOAD TO PROJECT into bank B; the
  DSP's model plays bank B's slot from its page, bank A's slot of the same number from A's.
  Negative controls: a page without its magic plays nothing; old values (low byte 0) are bank A.
- `pools`: switching projects keeps each project's banks; `link16`: the pages load and verify.
- SHARC runner: the sampler's bank read on the runner.
