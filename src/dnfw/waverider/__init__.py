"""Waverider: wavetables baked into the firmware (`docs/waverider-feasibility.md`).

Milestone 0 proves the delivery chain -- reduce, bake, load, address, read --
with one table and no audio. One subject per module:

  `reduce`     any wavetable's frames -> the baked geometry, int16
  `testtable`  the original table Milestone 0 bakes (no Elektron data, ever)
  `bake`       int16 frames -> the checksum and the C header the build compiles
  `expect`     what the firmware's telemetry must report, and checking a capture

The CLI is `dnfw waverider`.
"""
