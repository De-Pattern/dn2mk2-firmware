"""P-ISD's ROM words (DSP2 addresses; read from the owner's firmware at build time):
TAB: its 8 mode frequencies, 9 decay steps, 8 mode gains, then the strike excitation (to
the clamp plus a block at the fastest step); GAIN: the waveguide's gain by DEC (P-IRS reads
100); CURVE: the modes' radius by DEC x step (both machines)."""

TABLES = {
    "PISD_TAB": (0x142F33, 1281),
    "PISD_GAIN": (0x142B49, 100),
    "PISD_CURVE": (0x142949, 511),
}
