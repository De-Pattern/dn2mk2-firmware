# Changes from upstream

As the AGPL requires, a dated record of what this repository changes from
[dn2_firmware_explore](https://github.com/xrcstrecords/dn2_firmware_explore). From v0.8 on, each
release's changes are in [`FIRMWARE.md`](../FIRMWARE.md) and the git history.

- **2026-10-06** — forked from `dn2_firmware_explore` at `8c40698`
  (2026-10-01).
- **2026-10-06** — `scripts/sharc_waverider_render.py`: run selache natively
  when WSL is absent.
- **2026-10-06** — GRAINS: `grains/` (reference model, demos),
  `test/test_grains_model.py`, `docs/grains.md`.
- **2026-10-06** — this README; the upstream README moved to
  `docs/UPSTREAM-README.md`.
- **2026-10-06** — safety: `src/dnfw/safety.py` (the preflight, enforced in
  `dnfw mods apply`), `dnfw preflight`, `test/test_safety.py`,
  `docs/SAFETY.md`.
- **2026-10-11** — Waverider W5: `dnfw.waverider.factory` (11 original tables),
  the tables moved to DSP DDR, TBL on `DRIF`, the POS glide (`machine5_live.asm`,
  `live.glide`), the display following the heard value (`page.c`), the display data
  as its own RAM chunk; the preflight's DSP limit tightened to the uploader's real
  check; `scripts/sharc_ddr_ceiling.py`, `scripts/emu_install_snapshot.py`;
  `docs/w5-tables.md`.
- **2026-10-11** — `scripts/ship_gate.py`: every gate on the exact file, every build
  (`CLAUDE.md`); `docs/SAFETY.md`: the recovery cable's role.
- **2026-10-11** — Waverider W2: LEV and the scanner (RATE, MPOS, MLEV, MOVE) on page
  1, in `machine5_live.asm` and `live` (bit-exact); Waverider's names in every
  destination list (`wr_names`, `page.c`); the code ranges a CODE chunk executes,
  recorded for the gate (`__text_end`, `labels`); `dnfw waverider slice`
  (`waverider.slicer`); `docs/w2-scanner.md`.

