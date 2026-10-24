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
NAMES = ("ONESHOT", "WERP", "STRETCH", "REPITCH", "GRID", "SLICE")   # types 8..13 (v0.19: SLICE)
SHORT = ("ONE", "WRP", "STRE", "RPI", "GRD", "SLC")
TYPE_OF = {n: FIRST_TYPE + k for k, n in enumerate(NAMES)}
ENGINED = NAMES                           # the machines this build renders (v0.15: all five)

# record id -> (frame slot, low, top): value = clamp((word >> 8) - low, 0, top)
RECORDS = {238: (25, 4, 120), 254: (41, 0, 127), 256: (43, 0, 127), 239: (26, 0, 120),
           258: (45, 0, 127), 257: (44, 0, 127), 241: (30, 0, 127), 260: (47, 0, 127),
           # v0.15, the time machines: BARS on PD1 (0..100, default 50: 1 bar), SEG on TUN2
           # (default 60: 16 segments), MODE on DEC (default 127: FWD)
           240: (29, 0, 100), 242: (31, 4, 120), 255: (42, 0, 127),
           # the recorder (page 3, v0.15): ARM on TBL1 (0/1), DEST on MOD (0..3), THRES on
           # WAV2, SRC on DRIF, R.LEN on ATK, CHAN on TYPE (0..2), R.STRT on TBL2 -- all default 0
           247: (27, 0, 1), 248: (37, 0, 3), 243: (32, 0, 120), 252: (38, 0, 127), 253: (40, 0, 127),
           259: (46, 0, 2), 251: (33, 0, 1)}

# the eight controls each machine shows, in page order A..H: (record, short, long)
PAGES = {        # v0.15: the DT2's own SRC layout -- A TUNE, B PLAY, C (empty), D SAMP on top
    "ONESHOT": ((238, "TUNE", "Tune"), (254, "PLAY", "Play Mode"), (0, "-", "Unused"),
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
    # v0.19, the DT2's SLICE (OS 1.15+): the sample's own slices (dn2samples.py makes them)
    "SLICE": ((238, "TUNE", "Tune"), (254, "PLAY", "Play Mode"), (0, "-", "Unused"),
              (256, "SAMP", "Sample Slot"), (257, "SLCE", "Slice Select"), (260, "LEN", "Slice Length"),
              (0, "-", "Unused"), (241, "LEV", "Sample Level")),
}
# how page.c draws each control (v0.15, after the DT2's widgets)
WIDGETS = {238: "bipolar", 254: "play", 260: "knob", 256: "samp", 239: "knob", 258: "knob",
           257: "knob", 241: "fader", 242: "seg", 255: "play", 240: "bars"}
# what each control's value means here
TUNE_REC, PLAY_REC, SAMP_REC, LEV_REC = 238, 254, 256, 241
STRT_REC, LEN_REC, LOOP_REC = 239, 258, 257
GRID_REC, SLICE_REC, SLEN_REC = 239, 257, 260
BARS_REC, SEG_REC, MODE_REC = 240, 242, 255
CFAD_REC = 260                                     # ONESHOT's crossfade (v0.14; off the page from v0.15,
                                                   # whose C is the DT2's empty box; GRID's LEN is the same record)
# v0.18, the DT2's own (its OS 1.17 descriptors and formatters, dt2-coldfire-werp.md):
# BARS 1, 2, 4, 8 (default 4); WERP's SEG a segment's length, 1/32, 1/16, 1/8 of a bar
# (default 1/16), so the sample is (32 >> SEG) << BARS segments. The thresholds put
# the records' defaults (BARS 50, SEG 60) on the DT2's. Seven thresholds each, as the
# ColdFire's tables have room for, the unused ones past any value (255).
BARS = (1, 2, 4, 8)                                # BARS 0..100 in four: 0..12, 13..37, 38..62, 63..
BARS_STEPS = (13, 38, 63, 255, 255, 255, 255)
SEGS = (32, 16, 8)                                 # 1/32, 1/16, 1/8 of a bar: SEG 0..120 in three
SEG_STEPS = (40, 80, 255, 255, 255, 255, 255)
PLAY_MODES = ("REV", "REVL", "FWDL", "FWD")        # PLAY 0..127 in four, FWD at its default (top)
GRIDS = (4, 8, 16, 32, 64)                         # GRID 0..120 in five
LEV_UNITY = 100                                    # LEV 100 plays the sample at its level

# -- the sample pool, in the DSP's DDR (docs/sampler.md) -------------------------------------
POOL_MAGIC = 0x31504D53                    # 'SMP1'
POOL_SLOTS = 128
ENTRY_WORDS = 4                            # data address, frames, rate (float), format
FMT_F32, FMT_I16 = 0, 1
MAX_SLICES = 64                            # v0.19, SLICE: the format word's bits 8..15, the DT2's 64
NAMES_OFFSET = 8 + POOL_SLOTS * ENTRY_WORDS * 4      # 2056: the names, which only the ColdFire reads
NAME_BYTES = 8                             # seven characters and a NUL
DATA_OFFSET = 0x1000                       # the frames start here (the header is 3,080 bytes)

# -- the sample link (docs/sampler.md) ---------------------------------------------------------
# v0.14..v0.19 also sent packets in the frame's words 2650 + 2k: those are the DSP's
# per-track routing (docs/link-research.md, "Who sets the two tables"), not spare, and
# writing them made the stock voices buzz. v0.20 sends everything over the TDM link.
LINK_SEED = 0x1D0F
LINK_WORDS = 6                             # 24 bytes of pool a packet
POOL_BYTES = 400 << 20                     # the pool's extent in DSP DDR: 400 MB from SMP_POOL_DDR (v0.22; 128 MB v0.16..v0.21)
RAM_PROVEN = 128 << 20                     # what ran on the instrument before v0.22: the pool loads past it only
                                           # once the DSP's RAM check (CMD_PROBE) has passed this power-on
POOL_WORDS = POOL_BYTES // 4
MIRROR = 0x46B00000                        # the ColdFire's copy of the pool (RAM above BSS)
MIRROR_BYTES = 0x00500000                  # 5 MB, to 0x47000000 (nothing of anyone's above it)

# -- the recorder (docs/sampler.md) ---------------------------------------------------------
# v0.15: the recorder is driven by the ColdFire (its RECORDER page, YES, ARM), through a
# command block in the pool that the sample link writes; it is not a sound parameter,
# so nothing about it is saved with a sound. Its settings are on the page's records:
REC_FIRST = 123                            # slots 123..126 (SAMP 124..127) are the DSP's own
REC_SLOTS = 4
USER_SLOTS = 122                           # what the host tool may fill (SAMP 1..122)
REC_OFFSET = 96 << 20                      # their frames: 96..128 MB into the pool (v0.16)
REC_SLOT_SHIFT = 23                        # 8 MB a slot
REC_FRAMES = 66 * 48000                    # the DT2's maximum: 66 s of int16 at 48 kHz (v0.16)
# v0.22: the recordings' area is the pool's last 32 MB, shared: a recording goes where the
# ColdFire finds room (link.c's smp_rec_place), at REC_OFFSET + 512 u, into any slot
REC_END = 128 << 20                        # v0.22: the recordings' area stays 96..128 MB (proven RAM)
REC_BYTES = REC_END - REC_OFFSET
USER_HOLE = (REC_OFFSET, REC_END)           # yours: 0..96 MB, then 128..400 MB (dn2samples.py skips the hole)
USER_BYTES = POOL_BYTES - REC_BYTES - DATA_OFFSET
REC_UNIT = 512
REC_MIN_BYTES = 0x10000                    # the least room a recording starts in
IN_BUF = 0x268538                          # the engine's input block: L 32 floats, R at +0x80
MIX_BUF = 0x268438                         # the main mix (the last block's when we run)
TRK_BUF = 0x259F68                         # track t's audio, panned, the last block's: L at
TRK_STRIDE = 0x100                         # + 0x100 k, R at + 0x80 (Overbridge's per-track source B),
TRK_ROUTE = 0x257898                       # k = the s16 at TRK_ROUTE + 2t (the ColdFire's slot map)
TRK_GAIN = 11.627                          # 0x1c244d's gain into that buffer, between triggers
REC_STAGE = 0x2DF800                       # 32 floats of the block being recorded (dnfw.waverider.dsp)
CMD_OFFSET = 0xF00                         # the command block in the pool's directory page:
CMD_WORDS = 6                              #   seq, cmd, src, chan, thres (0..32767), dest << 24 | frames
CMD_NONE, CMD_ARM, CMD_NOW, CMD_STOP, CMD_MONITOR, CMD_ARM_PLAY, CMD_SEND, CMD_VERIFY = 0, 1, 2, 3, 4, 5, 6, 7
CMD_PROBE = 8
# PROBE (v0.22): is all of the 512 MB part there? PROBE_BYTES at PROBE_LO and at PROBE_LO +
# 256 MB (PROBE_HI) are filled with two patterns, then both read back (more than the DSP's
# data cache holds, so the reads come from the RAM). A 256 MB part would put the second
# fill on top of the first: the check fails, and the pool stays in its proven 128 MB. Both
# areas are the pool's own and unloaded while the check runs. Status half 4: 0 never run,
# 3 running, 1 passed, 2 failed.
PROBE_LO = 0x08F00000                      # bytes into the pool (143 MB)
PROBE_HI = PROBE_LO + (256 << 20)          # 399 MB in: 0x9CF00000, under the pool's end
PROBE_BYTES = 256 << 10
PROBE_STEP = 256                           # words a block
PROBE_PAT = (0x5A5A0000, 0x3C3C0000)       # word i holds i + this, low area then high
# VERIFY (v0.16): the sum of the pool's words [src, src + chan), to the status when done
# SEND (v0.16): the pool's words [src, src + chan) back to the ColdFire over the TDM link
# ARM waits for the threshold; ARM_PLAY (R.STRT PLAY) for the first note any track plays
# the DSP's status, in the 32 bytes of the SPI reply that stock leaves unwritten
# (0xa9c..0xabb), written into both reply pages each block: 16 halves, the last a check
REPLY_PAGES = (0x2C49D0, 0x2C59D0)
REPLY_TAIL = 0xA9C
STATUS_MAGIC = 0x5A00                      # | state (0 idle, 1 armed, 2 recording, 3 done)
# the RECORDER page (SYN page 3 of a sample machine), laid out as the DT2's: A SRC, B CHAN,
# C RECORD NOW (YES), D THRES, E DEST (the DT2 has MON here), F R.LEN, G R.STRT, H ARM
RSRC_REC, RCHAN_REC, RTHR_REC, RDST_REC, RLEN_REC, RSTRT_REC, ARM_REC = 252, 259, 243, 248, 253, 251, 247
REC_PAGE = ((252, "SRC", "Rec Source"), (259, "CHAN", "Rec Channel"), (0, "-", "Record Now"),
            (243, "THRES", "Rec Threshold"), (248, "DEST", "Rec Slot"), (253, "R.LEN", "Rec Length"),
            (251, "R.STRT", "Rec Start"), (247, "ARM", "Arm"))
# v0.22, the RECORDER's SRC (rec.c): the input's channels as choices of their own, as the
# DT2's; the DSP still takes a source (0 the input, 1 MAIN, 2 + t) and a channel
SRC_NAMES = ("EXT L+R", "EXT L", "EXT R", "MAIN") + tuple(f"TRK{t}" for t in range(1, 17))
CHAN_NAMES = ("MONO L+R", "MONO L", "MONO R")
RLEN_MAX = 0                               # R.LEN 0 is MAX, 1..127 steps of the sequencer

# -- one detent a choice (v0.15) -------------------------------------------------------------
# A control with a few choices sits on a 0..127 (or 0..100, 0..120) record, so the encoder
# swept many values to reach the next choice. The ColdFire's setter now moves such a
# control one choice a detent (csrc/sampler/fmt.c, smp_quant): (machines, frame slot,
# zone starts in the record's raw coarse units -- or a step -- and the value each choice is
# set to). The DSP's own reading of each control is unchanged: every value set is inside
# the zone the DSP reads it as (test_sampler checks it).
ALL = tuple(NAMES)


def _zones(n, span):                           # v * n // span: the first v of each zone
    return tuple(-(-span * k // n) for k in range(1, n))


QUANT = (
    # (machines, record, zone starts (raw), the value set for each choice (raw))
    (ALL, PLAY_REC, (32, 64, 96), (0, 32, 64, 127)),
    (("WERP",), MODE_REC, (32, 64, 96), (0, 32, 64, 127)),
    (("WERP", "STRETCH", "REPITCH"), BARS_REC, BARS_STEPS[:3], (0, 25, 50, 75)),
    (("WERP",), SEG_REC, tuple(4 + x for x in SEG_STEPS[:2]), (24, 64, 104)),
    (("GRID",), GRID_REC, (24, 48, 72, 96), (0, 24, 48, 72, 96)),
    # (v0.15..v0.21 had the recorder's SRC here: v0.22's recorder is a screen of its own)
)
QUANT_STEP = (                                  # (machines, record, raw coarse a choice)
    (("GRID", "SLICE"), SLICE_REC, 2),
    (("GRID", "SLICE"), SLEN_REC, 2),
)


# -- the fast link (v0.16, docs/link-research.md) ---------------------------------------------
# The SSI0 TDM link between the ColdFire and the DSP carries 16 slots a frame, 32 frames a
# block; stock writes ColdFire -> DSP slots 0..7 at most and reads 0..7, and DSP -> ColdFire
# slots 0..13. Ours: slots 8..15 ColdFire -> DSP (a 512-byte packet a block, 124 words of
# pool), slots 14..15 DSP -> ColdFire (a 128-byte packet a block, 29 words). Each slot
# carries 16 bits under a tag byte, so either justification of the 24 bits on the wire
# decodes: the DSP sees TAG << 24 | v << 8 or TAG << 16 | v.
TDM_RX = 0x2C18E8                           # the DSP's receive ring: two pages of 0x800
TDM_TX = 0x2C08E8                           # its transmit ring
TDM_PAGE = 0x268A38                         # the page this block (0 / 1), stable in the engine
TDM_TAG = 0xA5
RX_MAGIC, TX_MAGIC = 0x5A32, 0x5A33
RX_UNITS, RX_WORDS = 256, 124               # 8 slots x 32 frames; words of pool a packet
TX_UNITS, TX_WORDS = 64, 29                 # 2 slots x 32 frames
LINK_DM = 0x2DF880                          # the link's scratch (dnfw.waverider.dsp)
LINK_BUF = 0x2DF980                         # a packet's 256 units, decoded
LINK_WORDS = ("u", "v", "w", "sum", "bad", "good", "lseq", "nbad", "sbusy", "spos", "send",
              "sseq", "cnt", "off", "a", "pg",
              "vpos", "vend", "vsum", "vsum2", "vdone", "vseq")       # VERIFY: the running sum of a word range
VERIFY_CHUNK = 1024                          # words a block VERIFY adds up
