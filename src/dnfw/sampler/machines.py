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
ENGINED = NAMES                           # the machines this build renders (v0.15: all five)

# record id -> (frame slot, low, top): value = clamp((word >> 8) - low, 0, top)
RECORDS = {238: (25, 4, 120), 254: (41, 0, 127), 256: (43, 0, 127), 239: (26, 0, 120),
           258: (45, 0, 127), 257: (44, 0, 127), 241: (30, 0, 127), 260: (47, 0, 127),
           # v0.15, the time machines: BARS on PD1 (0..100, default 50: 1 bar), SEG on TUN2
           # (default 60: 16 segments), MODE on DEC (default 127: FWD)
           240: (29, 0, 100), 242: (31, 4, 120), 255: (42, 0, 127),
           # the recorder (page 2): REC on TBL1 (0/1), SRC on MOD (0..3), THRS on WAV2,
           # RLEN on DRIF, DEST on ATK -- all default 0
           247: (27, 0, 1), 248: (37, 0, 3), 243: (32, 0, 120), 252: (38, 0, 127), 253: (40, 0, 127)}

# the eight controls each machine shows, in page order A..H: (record, short, long)
PAGES = {        # v0.15: the DT2's own SRC layout -- A TUNE, B PLAY, C (empty), D SAMP on top
    "ONESHOT": ((238, "TUNE", "Tune"), (254, "PLAY", "Play Mode"), (260, "CFAD", "Crossfade"),
                (256, "SAMP", "Sample Slot"), (239, "STRT", "Start"), (258, "LEN", "Length"),
                (257, "LOOP", "Loop Pos"), (241, "LEV", "Sample Level")),
    "WERP": ((238, "TUNE", "Tune"), (254, "PLAY", "Play Mode"), (0, "-", "Unused"),
             (256, "SAMP", "Sample Slot"), (242, "SEG", "Segment Size"), (255, "MODE", "Segment Mode"),
             (240, "BARS", "Bars"), (241, "LEV", "Sample Level")),
    "STRETCH": ((238, "TUNE", "Tune"), (254, "PLAY", "Play Mode"), (0, "-", "Unused"),
                (256, "SAMP", "Sample Slot"), (239, "STRT", "Start"), (258, "LEN", "Length"),
                (240, "BARS", "Bars"), (241, "LEV", "Sample Level")),
    "REPITCH": ((0, "-", "Unused"), (254, "PLAY", "Play Mode"), (0, "-", "Unused"),
                (256, "SAMP", "Sample Slot"), (239, "STRT", "Start"), (258, "LEN", "Length"),
                (240, "BARS", "Bars"), (241, "LEV", "Sample Level")),
    "GRID": ((238, "TUNE", "Tune"), (254, "PLAY", "Play Mode"), (0, "-", "Unused"),
             (256, "SAMP", "Sample Slot"), (257, "SLCE", "Slice Select"), (260, "LEN", "Slice Length"),
             (239, "GRID", "Slice Grid"), (241, "LEV", "Sample Level")),
}
# how page.c draws each control (v0.15, after the DT2's widgets)
WIDGETS = {238: "bipolar", 254: "play", 260: "knob", 256: "samp", 239: "knob", 258: "knob",
           257: "knob", 241: "fader", 242: "seg", 255: "play", 240: "bars"}
# what each control's value means here
TUNE_REC, PLAY_REC, SAMP_REC, LEV_REC = 238, 254, 256, 241
STRT_REC, LEN_REC, LOOP_REC = 239, 258, 257
GRID_REC, SLICE_REC, SLEN_REC = 239, 257, 260
BARS_REC, SEG_REC, MODE_REC = 240, 242, 255
CFAD_REC = 260                                     # ONESHOT's crossfade (GRID's LEN is the same record)
BARS = (0.125, 0.25, 0.5, 1, 2, 4, 8, 16)          # BARS 0..100 in eight: index v * 8 // 101
BARS_STEPS = tuple(-(-101 * k // 8) for k in range(1, 8))   # the thresholds: 13 26 38 51 64 76 89
SEGS = (128, 64, 32, 16, 8, 4, 2, 1)               # SEG 0..120 in eight: index v * 8 // 121
SEG_STEPS = tuple(-(-121 * k // 8) for k in range(1, 8))
PLAY_MODES = ("REV", "REVL", "FWDL", "FWD")        # PLAY 0..127 in four, FWD at its default (top)
GRIDS = (4, 8, 16, 32, 64)                         # GRID 0..120 in five
LEV_UNITY = 100                                    # LEV 100 plays the sample at its level

# -- the sample pool, in the DSP's DDR (docs/sampler.md) -------------------------------------
POOL_MAGIC = 0x31504D53                    # 'SMP1'
POOL_SLOTS = 128
ENTRY_WORDS = 4                            # data address, frames, rate (float), format
FMT_F32, FMT_I16 = 0, 1
NAMES_OFFSET = 8 + POOL_SLOTS * ENTRY_WORDS * 4      # 2056: the names, which only the ColdFire reads
NAME_BYTES = 8                             # seven characters and a NUL
DATA_OFFSET = 0x1000                       # the frames start here (the header is 3,080 bytes)

# -- the sample link (v0.14): a packet a frame, ColdFire -> DSP (docs/sampler.md) ----------
LINK_OFFSET = 2650                         # the frame's 16 words at 2650 + 2k (stock: a per-track array the DSP never reads)
LINK_MAGIC = 0x5A31
LINK_SEED = 0x1D0F
LINK_WORDS = 6                             # 24 bytes of pool a packet
POOL_BYTES = 16 << 20                      # the pool's extent in DSP DDR: 16 MB from SMP_POOL_DDR
POOL_WORDS = POOL_BYTES // 4
MIRROR = 0x46B00000                        # the ColdFire's copy of the pool (RAM above BSS)
MIRROR_BYTES = 0x00500000                  # 5 MB, to 0x47000000 (nothing of anyone's above it)

# -- the recorder (docs/sampler.md) ---------------------------------------------------------
REC_REC, RSRC_REC, RTHR_REC, RLEN_REC, RDST_REC = 247, 248, 243, 252, 253
REC_FIRST = 123                            # slots 123..126 (SAMP 124..127) are the DSP's own
REC_SLOTS = 4
USER_SLOTS = 122                           # what the host tool may fill (SAMP 1..122)
REC_OFFSET = 8 << 20                       # their frames: 8..16 MB into the pool, past any mirror
REC_FRAMES = (2 << 20) // 2                # 2 MB of int16 a slot: 21.8 s at 48 kHz
IN_BUF = 0x268538                          # the engine's input block: L 32 floats, R at +0x80
MIX_BUF = 0x268438                         # the main mix (the last block's when we run)
REC_STAGE = 0x2DF800                       # 32 floats of the block being recorded (dnfw.waverider.dsp)
REC_PAGE = ((247, "REC", "Record"), (248, "SRC", "Rec Source"), (243, "THRS", "Rec Threshold"),
            (0, "-", "Unused"), (252, "RLEN", "Rec Length"), (253, "DEST", "Rec Slot"),
            (0, "-", "Unused"), (0, "-", "Unused"))
SRC_NAMES = ("IN", "IN L", "IN R", "MAIN")
