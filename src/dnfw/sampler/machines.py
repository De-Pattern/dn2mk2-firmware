"""The Digitakt II's sample machines on the DN2 (docs/sampler.md): what they are and
where their controls sit.

The machines are the DT2's own -- ONESHOT, WERP, STRETCH, REPITCH, GRID, in the DT2's
MACHINE SEL order (DT2 1.17 MAIN OS, the list at 0x4020ef78) -- as machine types 8..12
of the DN2. Their controls and ranges are read from the DT2's parameter descriptors
(0x401eb76c.., docs/dt2-port-map.md); the DSP code is our own (dnfw.sampler.program),
since the DT2's is built around its own engine.

Like every machine of ours, a sample machine's controls are WaveTone records: their
values travel in the frame like any machine parameter, and are p-lockable, LFO
destinations, and saved with the sound. Each control is placed on a record whose range
and default suit it (a DT2 default of "full" on a record whose default is its top).
"""

from __future__ import annotations

FIRST_TYPE = 8
NAMES = ("ONESHOT", "WERP", "STRETCH", "REPITCH", "GRID")      # types 8..12
SHORT = ("ONE", "WRP", "STRE", "RPI", "GRD")
TYPE_OF = {n: FIRST_TYPE + k for k, n in enumerate(NAMES)}
ENGINED = ("ONESHOT", "GRID")             # the machines this build renders

# record id -> (frame slot, low, top): value = clamp((word >> 8) - low, 0, top)
RECORDS = {238: (25, 4, 120), 254: (41, 0, 127), 256: (43, 0, 127), 239: (26, 0, 120),
           258: (45, 0, 127), 257: (44, 0, 127), 241: (30, 0, 127), 260: (47, 0, 127)}

# the eight controls each machine shows, in page order A..H: (record, short, long)
PAGES = {
    "ONESHOT": ((238, "TUNE", "Tune"), (254, "PLAY", "Play Mode"), (256, "SAMP", "Sample Slot"),
                (260, "CFAD", "Crossfade"), (239, "STRT", "Start"), (258, "LEN", "Length"),
                (257, "LOOP", "Loop Pos"), (241, "LEV", "Sample Level")),
    "GRID": ((238, "TUNE", "Tune"), (254, "PLAY", "Play Mode"), (256, "SAMP", "Sample Slot"),
             (239, "GRID", "Slice Grid"), (257, "SLCE", "Slice Select"), (260, "LEN", "Slice Length"),
             (0, "-", "Unused"), (241, "LEV", "Sample Level")),
}
# what each control's value means here
TUNE_REC, PLAY_REC, SAMP_REC, LEV_REC = 238, 254, 256, 241
STRT_REC, LEN_REC, LOOP_REC = 239, 258, 257
GRID_REC, SLICE_REC, SLEN_REC = 239, 257, 260
PLAY_MODES = ("REV", "REVL", "FWDL", "FWD")        # PLAY 0..127 in four, FWD at its default (top)
GRIDS = (4, 8, 16, 32, 64)                         # GRID 0..120 in five
LEV_UNITY = 100                                    # LEV 100 plays the sample at its level

# -- the sample pool, in the DSP's DDR (docs/sampler.md) -------------------------------------
POOL_MAGIC = 0x31504D53                    # 'SMP1'
POOL_SLOTS = 128
ENTRY_WORDS = 4                            # data address, frames, rate (float), spare
